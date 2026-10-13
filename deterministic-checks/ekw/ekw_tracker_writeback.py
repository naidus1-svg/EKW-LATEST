#!/usr/bin/env python3
"""Check H for EKW: write a runner's per-task verdicts into an EKW QC tracker tab, base-checked
and read back.

Reads `summary.json` and `check_b.json` from an `ekw_run_checks.py` output directory and writes,
per task row (matched on the `Task ID` column):

  Check B / C / D / E cells        PASS or FAIL on the first line in the trackers' own vocabulary
                                   ("PASS (1 pass, not yet independently re-checked)"), the
                                   evidence on the following lines
  Check A cell                     only when it still holds the pre-parser placeholder: reset to
                                   "NOT RUN - no check run yet" with a line saying B-E ran
  Check B..E reconciliation history  one dated entry appended (a bare "-" is replaced)
  Difficulty tier / Defect category  only when they still hold the pre-parser placeholders
                                   (`pipeline_not_applicable_yet` / `no_verifier_json_parser`);
                                   a value a person set is never overwritten
  Note                             the stale "No QC checks (A-H) have run yet ..." sentence is
                                   replaced; everything else in the note is kept verbatim

Then, in a second write after the first has been read back and verified, the Check H cell and
its history record that this write-back happened and was verified.

Safety, copied from tools/svc_harbor_tracker_sync.py in turing-context: dry run by default;
a full snapshot of the tab is saved locally before any write; the base check and the write live
in the same conditional (every cell this script intends to change must still hold the value the
diff was built against, re-read immediately before writing, or nothing is written); every write
is read back and compared. Columns are located by header text, never by fixed letter, so the
SVC tab's extra "DataOS/Oracle submission status" column does not shift anything. No column is
ever removed or cleared.

Usage
    python ekw_tracker_writeback.py --out-dir C:\\ekwqc\\_ekw274_qc --sheet <spreadsheetId> --tab "EKW Tracker"
    python ekw_tracker_writeback.py --out-dir ... --sheet ... --tab ... --apply
    python ekw_tracker_writeback.py --out-dir ... --sheet ... --tab ... --apply --log writeback.json

Needs a gcloud user credential with Drive scope (`gcloud.cmd auth login --enable-gdrive-access`);
the Sheets API accepts it. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # unicode task names on a cp1252 console
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

API = "https://sheets.googleapis.com/v4/spreadsheets"
RUN_TAG = "deterministic-checks/ekw"
PLACEHOLDER_TIER = "pipeline_not_applicable_yet"
PLACEHOLDER_DEFECT = "no_verifier_json_parser"
STALE_NOTE = "No QC checks (A-H) have run yet - harbor verifier.json parser not built. See ekw/ekw-qc-starting-point-2026-09-14.md."
PASS_LINE = "PASS (1 pass, not yet independently re-checked)"
FAIL_LINE = "FAIL (1 pass, not yet independently re-checked)"
NOT_RUN_LINE = "NOT RUN - no check run yet"
SYSTEMIC = "judge_determinism_config_lint"
DETAIL_CAP = 900

HEADERS = {
    "id": "Task ID",
    "A": "Check A: Content audit",
    "B": "Check B: Build success",
    "C": "Check C: Structural audit",
    "D": "Check D: Mechanical sub-check",
    "E": "Check E: Formula health",
    "H": "Check H: Tracker write-back + readback",
    "hA": "Check A reconciliation history",
    "hB": "Check B reconciliation history",
    "hC": "Check C reconciliation history",
    "hD": "Check D reconciliation history",
    "hE": "Check E reconciliation history",
    "hH": "Check H reconciliation history",
    "tier": "Difficulty tier",
    "defect": "Defect category",
    "note": "Note",
}


# ---------------------------------------------------------------------------
# Sheets I/O
# ---------------------------------------------------------------------------


def tok() -> str:
    for cmd in ("gcloud", "gcloud.cmd"):
        try:
            t = subprocess.run(
                [cmd, "auth", "print-access-token"],
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            t = ""
        if len(t) > 40:
            return t
    sys.exit("no access token; run: gcloud.cmd auth login --enable-gdrive-access")


_TOKEN: list[str] = []


def call(method: str, path: str, body=None):
    if not _TOKEN:
        _TOKEN.append(tok())
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
    )
    req.add_header("Authorization", "Bearer " + _TOKEN[0])
    req.add_header("Content-Type", "application/json")
    try:
        return json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} on {path}: {e.read()[:400]}")


def get_values(sheet: str, rng: str) -> list[list[str]]:
    return call(
        "GET", f"/{sheet}/values/{urllib.parse.quote(rng, safe='')}?majorDimension=ROWS"
    ).get("values", [])


def col_letter(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


# ---------------------------------------------------------------------------
# cell text
# ---------------------------------------------------------------------------


def _cap(s: str) -> str:
    return s if len(s) <= DETAIL_CAP else s[: DETAIL_CAP - 3] + "..."


def _status_line(verdict: str) -> str:
    if verdict == "fail":
        return FAIL_LINE
    if verdict in ("pass", "warn"):
        return PASS_LINE
    return NOT_RUN_LINE


def _sub_detail(name: str, cell: dict) -> str:
    v = cell.get("verdict")
    first = (cell.get("first") or "").replace("\n", " ").strip()
    if v == "pass" and cell.get("reconciled"):
        return f"{name}: pass (reconciled: {first})"
    if v in ("fail", "warn", "error") and first:
        return f"{name}: {v}({cell.get('n_findings', 0)}) {first}"
    return f"{name}: {v}"


def build_cells(
    row: dict, cb: dict | None, stamp: str, letters: dict[str, list[str]]
) -> dict[str, tuple[str, str]]:
    """Returns {letter: (status_line, detail)} for B, C, D, E."""
    out = {}
    prefix = f"[{RUN_TAG} run {stamp}, summary.csv]"
    # B from check_b.json
    b = row["checks"].get("check_b") or {}
    parts = []
    if cb:
        v = cb.get("verifiers") or {}
        parts.append(
            f"genre={cb.get('genre')}; verifiers={v.get('n')} (rubric {v.get('n_rubric')}, deterministic {v.get('n_deterministic')}, foreign {v.get('n_foreign')}); weight_sum={v.get('weight_sum')}; graded={', '.join(cb.get('graded_files') or [])}"
        )
        fails = [f for f in cb.get("findings", []) if f["severity"] == "fail"]
        warns = [f for f in cb.get("findings", []) if f["severity"] == "warn"]
        for f in fails:
            parts.append(f"FAIL {f['kind']}: {f['message']}")
        if warns:
            parts.append(
                "warn: " + "; ".join(f"{f['kind']}: {f['message']}" for f in warns)
            )
        rk = cb.get("rewardkit")
        if rk:
            parts.append(
                "rewardkit_convert: "
                + (
                    "OK"
                    if rk.get("ok")
                    else "FAILED " + "; ".join(rk.get("problems") or [])
                )
            )
        st = cb.get("staged")
        if st:
            parts.append(
                f"staged {len(st.get('groups') or [])} judge group(s), roundtrip_ok={st.get('roundtrip_ok')}"
            )
    out["B"] = (_status_line(b.get("verdict")), _cap(prefix + " " + " | ".join(parts)))
    for L in ("C", "D", "E"):
        names = letters.get(L, [])
        cells = [(n, row["checks"][n]) for n in names if n in row["checks"]]
        verdict = row.get(L, "skip")
        detail = " | ".join(_sub_detail(n, c) for n, c in cells)
        if L == "D" and any(
            n == SYSTEMIC and c.get("verdict") == "fail" for n, c in cells
        ):
            others = [c.get("verdict") for n, c in cells if n != SYSTEMIC]
            detail = (
                "SYSTEMIC: verifier.json config runs the judge at temperature 1.0 with no panel (one config fix across the population; not a per-task rubric defect). Other D sub-checks: "
                + (
                    "all pass/skip"
                    if all(x in ("pass", "skip") for x in others)
                    else "see below"
                )
                + " | "
                + detail
            )
        out[L] = (_status_line(verdict), _cap(prefix + " " + detail))
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--out-dir",
        required=True,
        help="ekw_run_checks.py output directory (summary.json, check_b.json)",
    )
    ap.add_argument("--sheet", required=True, help="spreadsheet id")
    ap.add_argument(
        "--tab", required=True, help="tab title, e.g. 'EKW Tracker' or 'QC Tracker'"
    )
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--log", help="write a JSON record of every cell written here")
    ap.add_argument(
        "--snapshot-dir",
        default=None,
        help="where to save the pre-write tab snapshot (default: --out-dir)",
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    cbj = (
        json.loads((out_dir / "check_b.json").read_text(encoding="utf-8"))
        if (out_dir / "check_b.json").is_file()
        else {"results": []}
    )
    cb_by_id = {r["task_id"]: r for r in cbj.get("results", [])}
    stamp = (summary.get("generated") or time.strftime("%Y-%m-%dT%H:%M:%S"))[:10]
    # letter membership from the runner's own CHECKS table so the tracker matches summary.csv
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ekw_run_checks  # noqa: E402

    letters: dict[str, list[str]] = {}
    for name, spec in ekw_run_checks.CHECKS.items():
        letters.setdefault(spec["letter"], []).append(name)

    # ---- read the tab ---------------------------------------------------------------------
    rows = get_values(args.sheet, f"{args.tab}!A1:AB1000")
    if not rows:
        sys.exit("tab is empty or unreadable")
    header = rows[0]
    col = {}
    for key, title in HEADERS.items():
        if title not in header:
            sys.exit(
                f"header {title!r} not found in tab {args.tab!r}; headers: {header}"
            )
        col[key] = header.index(title)
    snap_dir = Path(args.snapshot_dir or out_dir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap = (
        snap_dir
        / f"tracker_snapshot_{args.tab.replace(' ', '_')}_{time.strftime('%Y%m%dT%H%M%S')}.json"
    )
    snap.write_text(
        json.dumps(
            {"sheet": args.sheet, "tab": args.tab, "values": rows}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    print(f"snapshot: {snap} ({len(rows)} rows)", file=sys.stderr)

    def cell(r: list[str], key: str) -> str:
        i = col[key]
        return r[i] if i < len(r) else ""

    row_of = {}
    for idx, r in enumerate(rows[1:], start=2):
        tid = cell(r, "id").strip()
        if tid:
            row_of.setdefault(tid, idx)

    # ---- build the diff ---------------------------------------------------------------------
    updates: list[tuple[str, str, str, str]] = []  # (range, new, old, label)
    missing_rows, phase2 = [], []
    for res in summary["results"]:
        tid = res["task_id"]
        if tid not in row_of:
            missing_rows.append(tid)
            continue
        rn = row_of[tid]
        r = rows[rn - 1]
        cells = build_cells(res, cb_by_id.get(tid), stamp, letters)

        def rng(key: str) -> str:
            return f"{args.tab}!{col_letter(col[key])}{rn}"

        for L in ("B", "C", "D", "E"):
            status, detail = cells[L]
            new = status + "\n" + detail
            old = cell(r, L)
            if old != new:
                updates.append((rng(L), new, old, f"{tid} {L}"))
            old_h = cell(r, "h" + L)
            entry = f"[{RUN_TAG} {stamp}] Check {L} {(old.splitlines() or ['(blank)'])[0]} -> {status.split(' ')[0]}. {detail[:300]}"
            new_h = (
                entry
                if old_h.strip() in ("", "-")
                else old_h.rstrip("\n") + "\n" + entry
            )
            updates.append((rng("h" + L), new_h, old_h, f"{tid} h{L}"))
        old_a = cell(r, "A")
        if old_a.startswith("NOT RUN") and PLACEHOLDER_TIER in old_a:
            new_a = (
                NOT_RUN_LINE
                + f"\n[{RUN_TAG} {stamp}] Check A (content audit) is judgment work not yet run on EKW. Checks B-E ran; see their columns."
            )
            updates.append((rng("A"), new_a, old_a, f"{tid} A"))
        # tier / defect only over the pre-parser placeholders
        fails = {L: cells[L][0].startswith("FAIL") for L in ("B", "C", "D", "E")}
        d_only_systemic = fails["D"] and all(
            (res["checks"].get(n) or {}).get("verdict") in ("pass", "skip", "warn")
            for n in letters.get("D", [])
            if n != SYSTEMIC
        )
        blocking = (
            fails["B"]
            or fails["C"]
            or fails["E"]
            or (fails["D"] and not d_only_systemic)
        )
        tier = "not_yet_diagnosed_needs_deep_pass" if blocking else "needs_oracle_run"
        first_fail = ""
        cbres = cb_by_id.get(tid) or {}
        for f in cbres.get("findings", []):
            if f["severity"] == "fail":
                first_fail = f["kind"]
                break
        if not first_fail:
            for L in ("C", "E", "D"):
                for n in letters.get(L, []):
                    c = res["checks"].get(n) or {}
                    if c.get("verdict") == "fail" and not (
                        L == "D" and n == SYSTEMIC and d_only_systemic
                    ):
                        first_fail = n
                        break
                if first_fail:
                    break
        defect = first_fail or (
            "judge_temperature_no_panel_systemic" if fails["D"] else "none_found"
        )
        if cell(r, "tier").strip() in ("", PLACEHOLDER_TIER):
            updates.append((rng("tier"), tier, cell(r, "tier"), f"{tid} tier"))
        if cell(r, "defect").strip() in ("", PLACEHOLDER_DEFECT):
            updates.append((rng("defect"), defect, cell(r, "defect"), f"{tid} defect"))
        old_note = cell(r, "note")
        summary_line = f"Checks B-E ran {stamp} ({RUN_TAG}): B={res.get('B')}, C={res.get('C')}, D={res.get('D')}, E={res.get('E')}."
        if STALE_NOTE in old_note:
            new_note = old_note.replace(STALE_NOTE, summary_line)
        elif summary_line not in old_note:
            new_note = (old_note.rstrip() + " " + summary_line).strip()
        else:
            new_note = old_note
        if new_note != old_note:
            updates.append((rng("note"), new_note, old_note, f"{tid} note"))
        phase2.append((tid, rn))

    by_kind: dict[str, int] = {}
    for _, _, _, label in updates:
        by_kind[label.split(" ", 1)[1]] = by_kind.get(label.split(" ", 1)[1], 0) + 1
    print(
        f"{len(summary['results'])} tasks in summary, {len(row_of)} rows in tab, {len(missing_rows)} tasks with no row: {missing_rows[:10]}",
        file=sys.stderr,
    )
    print(f"{len(updates)} cell(s) to write: {by_kind}", file=sys.stderr)
    for rng_, new, old, label in updates[:6]:
        print(
            f"  {rng_} [{label}]\n    old: {old[:120]!r}\n    new: {new[:160]!r}",
            file=sys.stderr,
        )
    if not args.apply:
        print("DRY RUN, nothing written. Re-run with --apply.", file=sys.stderr)
        return 0
    if not updates:
        print("nothing to write", file=sys.stderr)
        return 0

    # ---- base check and write, one conditional ---------------------------------------------
    fresh = get_values(args.sheet, f"{args.tab}!A1:AB1000")

    def fresh_cell(values, rng_: str) -> str:
        a1 = rng_.split("!")[1]
        letters_, digits = a1.rstrip("0123456789"), int(
            a1[len(a1.rstrip("0123456789")) :]
        )
        ci = 0
        for ch in letters_:
            ci = ci * 26 + (ord(ch) - 64)
        r = values[digits - 1] if digits - 1 < len(values) else []
        return r[ci - 1] if ci - 1 < len(r) else ""

    drift = [
        (rng_, old, fresh_cell(fresh, rng_))
        for rng_, new, old, label in updates
        if fresh_cell(fresh, rng_) != old
    ]
    if drift:
        print(
            f"BASE CHECK FAILED, nothing written. {len(drift)} cell(s) moved since the diff was built:",
            file=sys.stderr,
        )
        for rng_, exp, act in drift[:20]:
            print(
                f"  {rng_} expected {exp[:80]!r}, found {act[:80]!r}", file=sys.stderr
            )
        return 1
    written_total = 0
    for i in range(0, len(updates), 400):
        chunk = updates[i : i + 400]
        res = call(
            "POST",
            f"/{args.sheet}/values:batchUpdate",
            {
                "valueInputOption": "RAW",
                "data": [
                    {"range": rng_, "values": [[new]]}
                    for rng_, new, old, label in chunk
                ],
            },
        )
        written_total += int(res.get("totalUpdatedCells") or 0)
    print(f"wrote {written_total} cell(s)", file=sys.stderr)

    after = get_values(args.sheet, f"{args.tab}!A1:AB1000")
    bad = [
        (rng_, new, fresh_cell(after, rng_))
        for rng_, new, old, label in updates
        if fresh_cell(after, rng_) != new
    ]
    if bad:
        print(f"READ-BACK MISMATCH on {len(bad)} cell(s):", file=sys.stderr)
        for rng_, want, got in bad[:20]:
            print(f"  {rng_} wanted {want[:80]!r}, got {got[:80]!r}", file=sys.stderr)
        return 1
    print(f"read-back matches on all {len(updates)} cell(s)", file=sys.stderr)

    # ---- phase 2: Check H records that this write-back was verified -------------------------
    h_updates = []
    for tid, rn in phase2:
        r = after[rn - 1] if rn - 1 < len(after) else []
        old_h = r[col["H"]] if col["H"] < len(r) else ""
        old_hh = r[col["hH"]] if col["hH"] < len(r) else ""
        new_h = (
            PASS_LINE
            + f"\n[{RUN_TAG} {stamp}] Checks B-E, histories, tier/defect placeholders and note written by ekw_tracker_writeback.py and read back cell-for-cell."
        )
        entry = f"[{RUN_TAG} {stamp}] write-back of {sum(1 for u in updates if u[3].startswith(tid + ' '))} cell(s) read back OK."
        new_hh = (
            entry if old_hh.strip() in ("", "-") else old_hh.rstrip("\n") + "\n" + entry
        )
        if old_h != new_h:
            h_updates.append(
                (f"{args.tab}!{col_letter(col['H'])}{rn}", new_h, old_h, f"{tid} H")
            )
        h_updates.append(
            (f"{args.tab}!{col_letter(col['hH'])}{rn}", new_hh, old_hh, f"{tid} hH")
        )
    for i in range(0, len(h_updates), 400):
        chunk = h_updates[i : i + 400]
        call(
            "POST",
            f"/{args.sheet}/values:batchUpdate",
            {
                "valueInputOption": "RAW",
                "data": [
                    {"range": rng_, "values": [[new]]}
                    for rng_, new, old, label in chunk
                ],
            },
        )
    after2 = get_values(args.sheet, f"{args.tab}!A1:AB1000")
    bad2 = [
        (rng_, new, fresh_cell(after2, rng_))
        for rng_, new, old, label in h_updates
        if fresh_cell(after2, rng_) != new
    ]
    print(
        f"Check H: wrote {len(h_updates)} cell(s), read-back {'OK' if not bad2 else 'MISMATCH on %d' % len(bad2)}",
        file=sys.stderr,
    )
    if args.log:
        Path(args.log).write_text(
            json.dumps(
                {
                    "sheet": args.sheet,
                    "tab": args.tab,
                    "stamp": stamp,
                    "snapshot": str(snap),
                    "phase1": [
                        {"range": a, "new": b, "old": c, "label": d}
                        for a, b, c, d in updates
                    ],
                    "phase2": [
                        {"range": a, "new": b, "old": c, "label": d}
                        for a, b, c, d in h_updates
                    ],
                    "readback_ok": not bad and not bad2,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return 1 if bad2 else 0


if __name__ == "__main__":
    raise SystemExit(main())
