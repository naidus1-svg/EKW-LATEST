#!/usr/bin/env python3
"""svc_eqc_manual_qc_sync.py - propagate EQC-done to "Done- Manual QC passed".

SOURCE = consolidated tracker 15Z00, EQC Status column:
  - tab 'SVC' : task_name (col by header 'task_name') = SVC-PC-*, EQC Status (header 'EQC Status')
  - tab 'EKW' : task_name = task_N, EQC Status
  A task whose EQC Status == "Done" (case-insensitive) is EQC-passed.

TARGET = SVC QC Tracker 1JmpP38. For each EQC-done task, set its Status cell to
  "Done- Manual QC passed" in the team tab that holds it (matched on Task ID, col A):
  - 'SVC QC Tracker A'   (SVC) : has a 'Status' column  -> written
  - 'Team A EKW Tracker' (EKW) : has a 'Status' column  -> written
  - 'Team B SVC Tracker' (SVC) : NO 'Status' column     -> matches REPORTED, not written
  - 'Team B EKW Tracker' (EKW) : NO 'Status' column     -> matches REPORTED, not written

Columns are discovered by header text (a reordered sheet does not write the wrong column).
Snapshot + row-identity base-check + read-back, like svc_mark_manual_qc.py. The tracker is
edited by many people at once, so writes are surgical batchUpdate on only the Status cells.

Needs a gcloud token WITH Drive scope:  gcloud.cmd auth login --enable-gdrive-access
Usage:
  python tools/svc_eqc_manual_qc_sync.py            # dry run: shows every change + Team-B skips
  python tools/svc_eqc_manual_qc_sync.py --apply    # writes, then reads back
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONS = "15Z00RATLJt7QcyT_-Rc6Y0jYS9WmcqUpukKp08GwAZ8"
QCA = "1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4"
API = "https://sheets.googleapis.com/v4/spreadsheets"
STATUS_VALUE = "Done- Manual QC passed"
DONE = "done"
MAXROW = 2000

# source tabs on 15Z00: (tab, domain)
SOURCES = [("SVC", "SVC"), ("EKW", "EKW")]
# target tabs on 1JmpP38: (tab, domain)
TARGETS = [
    ("SVC QC Tracker A", "SVC"),
    ("Team B SVC Tracker", "SVC"),
    ("Team A EKW Tracker", "EKW"),
    ("Team B EKW Tracker", "EKW"),
]


def norm(s) -> str:
    return str(s).strip().lower()


def token() -> str:
    p = subprocess.run(
        ["gcloud.cmd", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if p.returncode != 0 or not p.stdout.strip():
        sys.exit(
            "gcloud has no token. Run: gcloud.cmd auth login --enable-gdrive-access\n"
            + (p.stderr or "")[:400]
        )
    return p.stdout.strip()


def api(method, sheet, path, tok, body=None):
    url = f"{API}/{sheet}{path}"
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {tok}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            sys.exit(
                f"Sheets API {method} {path} failed: {e.code}\n{e.read().decode()[:500]}"
            )
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    sys.exit(f"Sheets API {method} {path} failed after retries: {last}")


def col_letter(i0: int) -> str:
    s, n = "", i0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def qrange(tab, a1):
    return "/values/" + urllib.parse.quote(f"'{tab}'!{a1}")


def get(sheet, tab, a1, tok):
    return api("GET", sheet, qrange(tab, a1), tok).get("values", [])


def find_col(header, *predicates):
    low = [str(c).strip().lower() for c in header]
    for pred in predicates:
        for j, c in enumerate(low):
            if pred(c):
                return j
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default is dry run)")
    args = ap.parse_args()
    tok = token()

    # 1) source: EQC-done task ids per domain
    done = {"SVC": set(), "EKW": set()}
    for tab, dom in SOURCES:
        head = get(CONS, tab, "A1:AZ1", tok)
        if not head:
            print(f"!! source tab {tab!r} empty header; skipping")
            continue
        tcol = find_col(
            head[0], lambda c: c == "task_name", lambda c: "task" in c and "name" in c
        )
        ecol = find_col(
            head[0], lambda c: c == "eqc status", lambda c: "eqc" in c and "status" in c
        )
        if tcol is None or ecol is None:
            sys.exit(
                f"source {tab!r}: could not find task_name/EQC Status columns in {head[0]}"
            )
        tvals = get(CONS, tab, f"{col_letter(tcol)}2:{col_letter(tcol)}{MAXROW}", tok)
        evals = get(CONS, tab, f"{col_letter(ecol)}2:{col_letter(ecol)}{MAXROW}", tok)
        n = 0
        for i in range(max(len(tvals), len(evals))):
            t = tvals[i][0] if i < len(tvals) and tvals[i] else ""
            e = evals[i][0] if i < len(evals) and evals[i] else ""
            if t.strip() and norm(e) == DONE:
                done[dom].add(norm(t))
                n += 1
        print(f"source {tab!r} ({dom}): {n} EQC-done tasks")

    # 2) plan writes per target tab
    total_write, total_skip_teamb, matched_ids = 0, 0, {"SVC": set(), "EKW": set()}
    write_plan = []  # (tab, statcol, row1based, taskid, old)
    for tab, dom in TARGETS:
        head = get(QCA, tab, "A1:BZ1", tok)
        hdr = head[0] if head else []
        acol = (
            find_col(hdr, lambda c: c == "task id", lambda c: "task" in c and "id" in c)
            or 0
        )
        scol = find_col(hdr, lambda c: c == "status")  # EXACT 'status' only
        tvals = get(QCA, tab, f"{col_letter(acol)}2:{col_letter(acol)}{MAXROW}", tok)
        svals = (
            get(QCA, tab, f"{col_letter(scol)}2:{col_letter(scol)}{MAXROW}", tok)
            if scol is not None
            else []
        )
        hits = []
        for i in range(len(tvals)):
            tid = tvals[i][0] if tvals[i] else ""
            if tid.strip() and norm(tid) in done[dom]:
                hits.append(
                    (
                        i + 2,
                        tid.strip(),
                        (
                            svals[i][0]
                            if scol is not None and i < len(svals) and svals[i]
                            else ""
                        ),
                    )
                )
                matched_ids[dom].add(norm(tid))
        if scol is None:
            total_skip_teamb += len(hits)
            print(
                f"\ntarget {tab!r} ({dom}): NO 'Status' column -> {len(hits)} EQC-done matches NOT written"
            )
            for row, tid, _ in hits[:8]:
                print(f"    row {row:>4}  {tid}")
            if len(hits) > 8:
                print(f"    ... +{len(hits)-8} more")
            continue
        towrite = [
            (row, tid, old) for row, tid, old in hits if old.strip() != STATUS_VALUE
        ]
        print(
            f"\ntarget {tab!r} ({dom}): Status col {col_letter(scol)}; {len(hits)} matches, {len(towrite)} to change"
        )
        for row, tid, old in towrite[:12]:
            print(f"    row {row:>4}  {tid:16}  {old!r} -> {STATUS_VALUE!r}")
        if len(towrite) > 12:
            print(f"    ... +{len(towrite)-12} more")
        for row, tid, old in towrite:
            write_plan.append((tab, col_letter(scol), row, tid, old))
        total_write += len(towrite)

    # unmatched EQC-done tasks (in source, not found in any target tab of that domain)
    for dom in ("SVC", "EKW"):
        unmatched = done[dom] - matched_ids[dom]
        if unmatched:
            print(
                f"\n!! {len(unmatched)} EQC-done {dom} task(s) not found in any target tab (id mismatch?): "
                + ", ".join(sorted(unmatched)[:10])
                + (" ..." if len(unmatched) > 10 else "")
            )

    print(
        f"\nSUMMARY: {total_write} Status cells to write, {total_skip_teamb} matches in Team-B tabs skipped (no Status col)."
    )
    if not args.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0
    if not write_plan:
        print("\nnothing to write.")
        return 0

    # 3) snapshot each touched target tab, then batchUpdate Status cells, then read back
    touched = sorted({tab for tab, *_ in write_plan})
    snap = {tab: get(QCA, tab, "A1:BZ%d" % MAXROW, tok) for tab in touched}
    json.dump(
        snap, open("_snap_qca_eqc_sync.json", "w", encoding="utf-8"), ensure_ascii=False
    )
    print(f"\nsnapshot of {len(touched)} tab(s) -> _snap_qca_eqc_sync.json")
    data = [
        {"range": f"'{tab}'!{scol}{row}", "values": [[STATUS_VALUE]]}
        for (tab, scol, row, _t, _o) in write_plan
    ]
    api(
        "POST",
        QCA,
        "/values:batchUpdate",
        tok,
        {"valueInputOption": "USER_ENTERED", "data": data},
    )
    print(f"wrote {len(data)} cell(s). Reading back...")
    ok = 0
    for tab, scol, row, tid, _o in write_plan:
        got = get(QCA, tab, f"{scol}{row}", tok)
        val = got[0][0] if got and got[0] else ""
        good = val.strip() == STATUS_VALUE
        ok += good
        if not good:
            print(f"  MISMATCH {tab} {scol}{row} {tid}: read back {val!r}")
    print(f"confirmed {ok}/{len(write_plan)} cells hold {STATUS_VALUE!r}.")
    return 0 if ok == len(write_plan) else 1


if __name__ == "__main__":
    raise SystemExit(main())
