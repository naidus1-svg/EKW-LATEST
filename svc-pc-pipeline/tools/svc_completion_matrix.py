#!/usr/bin/env python3
"""Build the 58-task completion matrix from the LIVE tracker plus real file evidence.

Two rules this file exists to enforce, both learned the hard way in one session:

1. The DENOMINATOR comes from the tracker, never from a staging directory. The 08-29
   cycle reported "12 written, all verified" while 32 tasks sat untouched, because its
   work list was whatever happened to be on disk.

2. A task's STATE comes from evidence that the work happened, never from a proxy for it.
   The first version of this matrix labelled every staged task "staged, rebuilt", which
   was literally true and made SVC-PC-13-8-0 and SVC-PC-14-5-0, where not a single byte
   changed, indistinguishable from tasks that were genuinely fixed. An adversarial
   verifier caught that. Being staged is not being fixed.

So each task's disposition is computed from: did its bytes actually change against the
pre-edit baseline, and did it reach Drive with a confirmed readback.

Also surfaces `Status 8/28` verbatim when it carries a hold word (STRUCK, PULLED, BLOCKED,
FROZEN). SVC-PC-6-6-0 is marked STRUCK (leakage) in the tracker and the first matrix
showed it as an ordinary in-progress task.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

SHEET = "1lAK17_JVjpWO28AkH6LZC_N0zUQEakNGqg-kRgN3pQI"
STAGE = Path("C:/b/_fetched_all32")
STAGE2 = Path("C:/b/_fetched_six")
OUT = Path("ekw/svc-completion-matrix-2026-08-31.md")

WRITTEN_0829 = {
    "SVC-PC-10-4-0",
    "SVC-PC-11-1-0",
    "SVC-PC-12-7-0",
    "SVC-PC-15-4-0",
    "SVC-PC-3-5-0",
    "SVC-PC-3-6-0",
    "SVC-PC-3-9-0",
    "SVC-PC-4-1-0",
    "SVC-PC-4-2-0",
    "SVC-PC-4-4-0",
    "SVC-PC-6-8-0",
    "SVC-PC-8-2-0",
}
EXCLUDED = {
    "SVC-PC-9-2-0": "Jeff hold-out 8/28",
    "SVC-PC-10-3-0": "Jeff pulled, no rework this batch",
}
HOLD_WORDS = ("STRUCK", "PULLED", "BLOCKED", "FROZEN")


def md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def tracker_rows() -> list[dict]:
    tok = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        shell=True,
    ).stdout.strip()
    if not tok:
        sys.exit("no access token")
    raw = subprocess.run(
        [
            "curl",
            "-s",
            f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET}/values/"
            "%27Feedback%20rows%27%21A1%3AP200",
            "-H",
            f"Authorization: Bearer {tok}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    if not raw.strip().startswith("{"):
        sys.exit(f"sheets API did not return JSON: {raw[:200]!r}")
    vals = json.loads(raw)["values"]
    hdr = vals[0]
    return [dict(zip(hdr, r + [""] * (len(hdr) - len(r)))) for r in vals[1:] if any(r)]


def main() -> int:
    recs = tracker_rows()
    by = defaultdict(list)
    for r in recs:
        if r.get("Task"):
            by[r["Task"]].append(r)

    # Work was staged into TWO trees: the original 32 and a later six. Reading only the
    # first undercounts, which is the same shape of bug as reading only one write-back
    # record. Merge them, and remember which tree each task lives in so the byte
    # comparison below looks in the right place.
    baseline, home = {}, {}
    for tree in (STAGE, STAGE2):
        f = tree / "_fetch_baseline.json"
        if not f.exists():
            continue
        for task, files in json.loads(f.read_text(encoding="utf-8")).items():
            baseline.setdefault(task, {}).update(files)
            home[task] = tree
    written = defaultdict(list)
    for w in json.loads(
        (STAGE / "_writeback_results.json").read_text(encoding="utf-8")
    ):
        if w.get("put_exit") == 0:
            written[w["task"]].append(w["rel"])
    confirmed = {
        (r["task"], r["rel"])
        for r in json.loads(
            (STAGE / "_readback_verify.json").read_text(encoding="utf-8")
        )
        if r["verdict"] == "MATCH"
    }

    # What ACTUALLY changed on disk, per task, split by artifact kind.
    changed = defaultdict(lambda: {"rubric": [], "golden": [], "other": []})
    for task, files in baseline.items():
        for rel, meta in files.items():
            p = home.get(task, STAGE) / task / rel
            if p.exists() and md5(p) != meta["md5"]:
                kind = (
                    "golden"
                    if "Golden" in rel
                    else "rubric" if "Rubric" in rel else "other"
                )
                changed[task][kind].append(rel)

    rows = []
    for task in sorted(
        by, key=lambda t: [int(x) for x in t.replace("SVC-PC-", "").split("-")]
    ):
        rs = by[task]
        cats = {(r.get("Error category") or "").strip() for r in rs}
        holds = sorted(
            {
                (r.get("Status 8/28") or "").strip()
                for r in rs
                if any(w in (r.get("Status 8/28") or "").upper() for w in HOLD_WORDS)
            }
        )
        ch = changed.get(task, {"rubric": [], "golden": [], "other": []})
        n_ch = sum(len(v) for v in ch.values())
        n_written = len(written.get(task, []))
        n_conf = sum(1 for rel in written.get(task, []) if (task, rel) in confirmed)

        # This cycle's evidence outranks the 08-29 label. Four tasks were written back
        # on 08-29 AND fixed again tonight; checking the old label first reported them as
        # last cycle's partial work and dropped them from the ready count.
        fixed_now = bool(n_written) and n_conf == n_written and bool(n_ch)

        if task in EXCLUDED:
            state, detail = "EXCLUDED", EXCLUDED[task]
        elif task in WRITTEN_0829 and not fixed_now:
            open_now = [
                r["Row"]
                for r in rs
                if (r.get("Error category") or "").strip() != "Fixable by us"
                or "landed" not in (r.get("Status") or "")
            ]
            state = "DONE 08-29"
            detail = "rubric written back 08-29 and md5-verified"
            if len(open_now) > 1:
                detail += f"; **{len(open_now)} of {len(rs)} findings on this task are not closed by that write**"
        elif (
            task in baseline
            or task in changed
            or (STAGE / task).is_dir()
            or (STAGE2 / task).is_dir()
        ):
            if n_written and n_conf == n_written:
                bits = []
                if ch["rubric"]:
                    bits.append("rubric")
                if ch["golden"]:
                    bits.append("golden")
                state = "FIXED 08-31"
                detail = (
                    f"{'+'.join(bits) or 'files'} edited, {n_written} file(s) "
                    f"written to Drive, readback confirmed"
                )
            elif n_ch:
                state = "EDITED, NOT WRITTEN"
                detail = f"{n_ch} file(s) changed locally but not written to Drive"
            else:
                state = "NOT FIXED"
                detail = (
                    "staged and rebuilt, but zero bytes changed: no fix was " "applied"
                )
        elif cats == {"Re-verify only"}:
            state, detail = "NO EDIT NEEDED", "re-verify only; already correct"
        elif "Needs owner decision" in cats:
            state, detail = "BLOCKED: owner", "awaiting a decision from Jeff or the SME"
        elif "Missing source material / environment" in cats:
            state, detail = "BLOCKED: source", "source material absent"
        elif "Infra" in cats:
            state, detail = "BLOCKED: infra", "infrastructure, not a task edit"
        elif (
            cats == {"Fixable by us"}
            and rs
            and all(
                "piloted-landed" in (r.get("Status") or "")
                or "softened" in (r.get("Status") or "")
                for r in rs
            )
        ):
            # Four tasks (SVC-PC-1-4-0, SVC-PC-2-1-0, SVC-PC-2-3-0, SVC-PC-6-4-0) fell
            # through to REVIEW here: every finding is "Fixable by us" but none of them
            # matches WRITTEN_0829, the baseline/changed staging dirs, or any category
            # branch above, because their fix landed in an earlier pilot pass rather than
            # this cycle's write-back. REVIEW is this file's own self-check for
            # unclassified rows, so treating these four as unclassified was itself the
            # defect: the readiness list (ekw/svc-dataos-readiness-2026-08-31.json,
            # `pushable`) already carries them as done.
            state = "DONE (pilot)"
            detail = (
                "fixable work landed in an earlier pilot pass, tracker Status confirms"
            )
        else:
            state, detail = "REVIEW", f"unclassified: {sorted(cats)}"

        if holds:
            detail = f"**tracker says {'; '.join(holds)}.** " + detail

        rows.append(
            {
                "task": task,
                "findings": len(rs),
                "state": state,
                "detail": detail,
                "holds": holds,
            }
        )

    c = Counter(r["state"] for r in rows)
    order = [
        "FIXED 08-31",
        "NOT FIXED",
        "EDITED, NOT WRITTEN",
        "DONE 08-29",
        "DONE (pilot)",
        "NO EDIT NEEDED",
        "BLOCKED: owner",
        "BLOCKED: source",
        "BLOCKED: infra",
        "EXCLUDED",
        "REVIEW",
    ]

    out = [
        "# SVC completion matrix, all 58 tasks (2026-08-31)",
        "",
        "Every task the audit touched, with a state derived from **evidence that the work "
        "happened**: did the file's bytes actually change against the pre-edit baseline, "
        "and did it reach Drive with a confirmed readback. The denominator comes from the "
        "live tracker, never from a staging directory.",
        "",
        "Both rules were learned the hard way. The 08-29 cycle reported twelve rubrics "
        "written as though finished, when the audit had 58 tasks and 32 still needed our "
        "own work, because its queue came from disk. Then the FIRST version of this very "
        "file labelled every staged task `staged, rebuilt`, which was literally true and "
        "made two tasks where not one byte changed look identical to tasks that were "
        "genuinely fixed. An adversarial verifier caught that. **Being staged is not "
        "being fixed**, and this file now distinguishes them.",
        "",
        f"Source: tracker `{SHEET}`, tab `Feedback rows`, "
        f"{sum(r['findings'] for r in rows)} findings across {len(rows)} tasks, "
        "pulled live at build time.",
        "",
        "## Totals",
        "",
        "| State | Tasks | Meaning |",
        "|---|---|---|",
    ]
    meaning = {
        "FIXED 08-31": "edited, written to Drive, readback confirmed",
        "NOT FIXED": "staged and rebuilt but zero bytes changed",
        "EDITED, NOT WRITTEN": "changed locally, did not reach Drive",
        "DONE 08-29": "written in the prior cycle",
        "DONE (pilot)": "fixable work landed in an earlier pilot pass",
        "NO EDIT NEEDED": "re-verify only",
        "BLOCKED: owner": "needs a decision",
        "BLOCKED: source": "source material absent",
        "BLOCKED: infra": "infrastructure",
        "EXCLUDED": "Jeff pulled it",
        "REVIEW": "unclassified, treat as a defect in this file",
    }
    for s in order:
        if c.get(s):
            out.append(f"| {s} | {c[s]} | {meaning[s]} |")
    out += [
        f"| **Total** | **{len(rows)}** | |",
        "",
        f"Arithmetic: {' + '.join(str(c[s]) for s in order if c.get(s))} = {len(rows)}.",
        "",
    ]

    held = [r for r in rows if r["holds"]]
    if held:
        out += [
            "## Tasks the tracker itself puts on hold",
            "",
            "These carry a hold marker in the tracker's own `Status 8/28` column. The "
            "first version of this matrix did not surface them at all.",
            "",
            "| Task | Hold | State here |",
            "|---|---|---|",
        ]
        for r in held:
            out.append(f"| {r['task']} | {'; '.join(r['holds'])} | {r['state']} |")
        out.append("")

    out += [
        "## Every task",
        "",
        "| Task | Findings | State | Detail |",
        "|---|---|---|---|",
    ]
    for r in sorted(
        rows,
        key=lambda x: (
            order.index(x["state"]) if x["state"] in order else 99,
            [int(y) for y in x["task"].replace("SVC-PC-", "").split("-")],
        ),
    ):
        out.append(f"| {r['task']} | {r['findings']} | {r['state']} | {r['detail']} |")

    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT}  ({len(rows)} tasks)")
    for s in order:
        if c.get(s):
            print(f"  {c[s]:3}  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
