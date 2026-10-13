#!/usr/bin/env python3
"""Refresh the SVC rework audit sheet, keeping the shape that already worked.

This deliberately mirrors `ekw/svc-audit-2026-08-31.xlsx` rather than inventing a new
layout. Same tabs, same column order, with the 2026-09-02 evidence APPENDED as extra
columns, which is exactly how that workbook already carried "Status 8/28" beside
"Status 8/31".

## The mistake this version fixes

The first attempt drove a red/amber/green column off oracle criterion counts, so any
task with a single failing criterion went red. That produced 30 red rows out of 58 and
was both alarming and wrong: an oracle criterion failure is often judge variance or a
harness artifact, not a critical defect. It also produced self-contradicting rows
reading "status FIXED" and "may be judge variance" in red.

The working sheet's model is the right one. A task is DONE unless it has a specific
OUTSTANDING item, and that item has a named owner. On 08-31 that was 12 of 58, not 30.
So:

  colour follows the Outstanding column, never a criterion count
  no outstanding item            -> done, no flag
  outstanding, owned by someone else -> needs a human
  outstanding, owned by us       -> on our list

Oracle numbers stay in the sheet as INFORMATIONAL columns, which is what they are. They
tell you roughly where a task sits. They do not decide whether it is finished, because
two runs over identical content flip 2.27% of criteria.

## Ownership, settled on the 2026-09-01 call

Shyam asked whether these fixes need a domain expert to contribute. They do, and Sydnie
is the finance expert. Substantive rubric and golden work is hers or the owning
expert's. What remains on our side is mechanical.

    python tools/svc_audit_sheet.py [--out ekw/svc-audit-2026-09-02.xlsx]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REPO = Path(__file__).resolve().parent.parent
EKW = REPO / "ekw"

READINESS = EKW / "svc-dataos-readiness-2026-08-31.json"
PRIOR_WB = EKW / "svc-audit-2026-08-31.xlsx"
CERT_DOC = EKW / "svc-two-run-certification-2026-09-01.md"
RUN_CURRENT = EKW / "svc-run-2381.json"
RUN_A = EKW / "svc-run-2374.json"
RUN_B = EKW / "svc-run-2376.json"

DONE = PatternFill("solid", fgColor="C6EFCE")  # nothing outstanding
OURS = PatternFill("solid", fgColor="FFEB9C")  # outstanding, on us, mechanical
HUMAN = PatternFill("solid", fgColor="FFC7CE")  # outstanding, needs a person
HEAD = PatternFill("solid", fgColor="1F3A5F")

# Owners that are not us. Used only to split the outstanding rows two ways.
OURS_RE = re.compile(r"\bkhiem\b", re.I)

# Findings dated AFTER the 08-31 workbook, which override the owner it recorded.
# Carrying that column forward unchanged is how 8-1-0 was about to be sent to Sydnie
# as "mechanical, mine". It is neither.
CORRECTIONS = {
    "SVC-PC-8-1-0": (
        "Sydnie / Jeff: needs a ruling, do not write back",
        "The local edit was authored against SVC-PC-8-2-0's rubric and rewrites BFCM "
        "peak-day figures that appear nowhere in 8-1-0's own 50 rows. Writing it back "
        "would put another task's answer into this golden. Established 2026-09-01; "
        "supersedes the 08-31 owner of 'Khiem (write back to Drive)'.",
    ),
}

# A task with several criteria failing in BOTH runs is a real defect, whatever the
# older owner column says. 3-8-0 was carried as "Khiem (verify remaining analogues)"
# while 13 of its criteria fail consistently.
PERSISTENT_FAIL_IS_EXPERT_WORK = 3


def load_json(p: Path):
    if not p.is_file():
        sys.exit(f"missing required input: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def key(name) -> str:
    return str(name or "").strip().upper()


def load_partition():
    d = load_json(READINESS)
    buckets = {k: v for k, v in d.items() if isinstance(v, list) and k != "notes"}
    bucket_of, seen, dupes = {}, set(), []
    for b, tasks in buckets.items():
        for t in tasks:
            k = key(t)
            if k in seen:
                dupes.append(k)
            seen.add(k)
            bucket_of[k] = b
    total = sum(len(v) for v in buckets.values())
    if dupes:
        sys.exit(f"BLOCKED: buckets not disjoint: {dupes}")
    if total != 58:
        sys.exit(f"BLOCKED: partition sums to {total}, expected 58")
    print(f"== partition ==\n  5 disjoint buckets, {total} tasks\n")
    return bucket_of


def load_runs():
    cur = {key(t["task"]): t for t in load_json(RUN_CURRENT)["tasks"]}
    A = {key(t["task"]): t for t in load_json(RUN_A)["tasks"]}
    B = {key(t["task"]): t for t in load_json(RUN_B)["tasks"]}

    tier, both_fail = {}, {}
    bp = bf = fl = 0
    for k in sorted(set(A) & set(B)):
        pa, fa = set(A[k]["pass"]), set(A[k]["fail"])
        pb, fb = set(B[k]["pass"]), set(B[k]["fail"])
        names = (pa | fa) & (pb | fb)
        f2 = sorted(n for n in names if n in fa and n in fb)
        flip = sorted(n for n in names if (n in fa) != (n in fb))
        bp += len([n for n in names if n in pa and n in pb])
        bf += len(f2)
        fl += len(flip)
        both_fail[k] = f2
        tier[k] = "A" if not f2 and not flip else ("B" if not f2 else "C")

    compared = bp + bf + fl
    print("== two-run certification, recomputed from #2374 and #2376 (ds675) ==")
    print(f"  {compared} criteria   both-pass {bp}   both-fail {bf}   flipped {fl}")
    crosscheck(compared, bp, bf, fl)
    c = Counter(tier.values())
    print(f"  Tier A {c['A']}  B {c['B']}  C {c['C']}\n")
    return cur, tier, both_fail


def crosscheck(compared, bp, bf, fl):
    txt = CERT_DOC.read_text(encoding="utf-8")

    def find(p):
        m = re.search(p, txt)
        return int(m.group(1).replace(",", "")) if m else None

    pairs = [
        ("criteria", find(r"Criteria graded per run \|\s*([\d,]+)"), compared),
        ("both-pass", find(r"Passed in \*\*both\*\* runs \|\s*([\d,]+)"), bp),
        ("both-fail", find(r"Failed in \*\*both\*\* runs \|\s*([\d,]+)"), bf),
        ("flipped", find(r"Flipped between runs\*\* \|\s*\*\*([\d,]+)"), fl),
    ]
    bad = [n for n, doc, live in pairs if doc != live]
    for n, doc, live in pairs:
        print(
            f"    {n:<11} doc={doc!s:<6} live={live:<6} {'match' if doc == live else 'MISMATCH'}"
        )
    if bad:
        sys.exit(f"BLOCKED: live data disagrees with the certification doc: {bad}")


def load_prior():
    wb = openpyxl.load_workbook(PRIOR_WB, data_only=True)

    def tab(name):
        ws = wb[name]
        h = [c.value for c in ws[1]]
        return h, [
            dict(zip(h, r))
            for r in ws.iter_rows(min_row=2, values_only=True)
            if any(v is not None for v in r)
        ]

    return {
        n: tab(n)
        for n in (
            "Task status 8-31",
            "Feedback rows",
            "Expert rulings needed",
            "Still outstanding",
        )
    }


def style(ws, ncols, widths=None):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEAD
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(ncols)}{ws.max_row}"
    for c in range(1, ncols + 1):
        L = get_column_letter(c)
        w = max(
            (
                len(str(ws.cell(row=r, column=c).value or ""))
                for r in range(1, min(ws.max_row, 300) + 1)
            ),
            default=10,
        )
        ws.column_dimensions[L].width = min(max(w + 2, 10), (widths or {}).get(L, 46))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(EKW / "svc-audit-2026-09-02.xlsx"))
    args = ap.parse_args()

    bucket_of = load_partition()
    cur, tier, both_fail = load_runs()
    prior = load_prior()

    wb = openpyxl.Workbook()

    # ---- Tab 1: Task status, the 08-31 columns plus 09-02 evidence --------
    src_h, src_rows = prior["Task status 8-31"]
    ws = wb.active
    ws.title = "Task status"
    added = [
        "Oracle 9/02 (run 2381)",
        "Criteria failing 9/02",
        "Certified twice (ds675)",
        "Status 9/02",
    ]
    ws.append(list(src_h) + added)

    counts = Counter()
    for r in src_rows:
        k = key(r.get("Task"))
        c = cur.get(k)
        t = tier.get(k)
        outstanding = str(r.get("Outstanding") or "").strip()
        owner = str(r.get("Owner of the outstanding item") or "").strip()

        persistent = len(both_fail.get(k, []))
        if k in CORRECTIONS:
            owner, outstanding = CORRECTIONS[k][0], CORRECTIONS[k][1]

        if not outstanding:
            flag, status = "done", "Done. Nothing outstanding."
        elif k in CORRECTIONS:
            flag, status = (
                "human",
                "Needs a ruling. Superseded since 08-31, see the note.",
            )
        elif OURS_RE.search(owner) and persistent >= PERSISTENT_FAIL_IS_EXPERT_WORK:
            flag = "human"
            status = (
                f"{persistent} criteria fail in both runs, so this is a real "
                "defect rather than the small verification the 08-31 owner implied."
            )
            owner = (
                f'Sydnie / owning expert. Raised by Khiem on 08-31 as "{owner}", but '
                f"{persistent} criteria fail consistently, which is task content rather "
                "than a verification pass."
            )
        elif OURS_RE.search(owner):
            flag, status = "ours", "On our list, mechanical."
        else:
            flag, status = "human", "Needs a person, not more rework from us."
        counts[flag] += 1

        cert = (
            "yes, passed both runs"
            if t == "A"
            else (
                "one criterion flipped"
                if t == "B"
                else "no, fails in both runs" if t == "C" else "not in the two-run pair"
            )
        )
        oracle = (
            f"{c['passed']}/{c['nCriteria']} passed, reward {round(c['reward'], 3)}"
            if c
            else "not in the 9/01 build"
        )

        # Write the CORRECTED owner and outstanding text, not the 08-31 originals.
        base = []
        for h in src_h:
            if h == "Outstanding":
                base.append(outstanding)
            elif h == "Owner of the outstanding item":
                base.append(owner)
            else:
                base.append(r.get(h))
        ws.append(base + [oracle, (len(c["failed"]) if c else ""), cert, status])
        fill = {"done": DONE, "ours": OURS, "human": HUMAN}[flag]
        ws.cell(row=ws.max_row, column=1).fill = fill
    style(ws, len(src_h) + len(added), {"H": 60, get_column_letter(len(src_h) + 4): 40})

    # ---- Tab 2: oracle detail, diagnostic and clearly labelled -----------
    ws2 = wb.create_sheet("Oracle detail 9-02")
    ws2.append(
        [
            "Task",
            "Criterion",
            "Category",
            "Weight",
            "Also failed in both older runs?",
            "Read this as",
        ]
    )
    for k in sorted(cur):
        bfk = set(both_fail.get(k, []))
        for f in cur[k]["failed"]:
            persistent = f["id"] in bfk
            ws2.append(
                [
                    k,
                    f["id"],
                    f.get("cat") or "",
                    f.get("w") or "",
                    "yes" if persistent else "no",
                    (
                        "A real task defect, it fails consistently"
                        if persistent
                        else "Single run only. May be judge variance, not a defect"
                    ),
                ]
            )
    style(ws2, 6, {"F": 56})

    # ---- Tabs carried forward unchanged ----------------------------------
    for src, name, widths in (
        ("Expert rulings needed", "Expert rulings needed", {c: 46 for c in "CDEFGH"}),
        ("Still outstanding", "Still outstanding", {"B": 60, "D": 60}),
        ("Feedback rows", "Feedback rows", {c: 38 for c in "DEFG"}),
    ):
        h, rows = prior[src]
        w = wb.create_sheet(name)
        w.append(list(h))
        for r in rows:
            w.append([r.get(x) for x in h])
        style(w, len(h), widths)

    # ---- Read me ----------------------------------------------------------
    ws6 = wb.create_sheet("Read me")
    for line in readme(counts):
        ws6.append([line])
    ws6.column_dimensions["A"].width = 108
    for row in ws6.iter_rows(min_row=1, max_col=1):
        row[0].alignment = Alignment(wrap_text=True, vertical="top")

    out = Path(args.out)
    wb.save(out)
    print("== output ==")
    print(f"  {out}  ({out.stat().st_size:,} bytes)")
    for w in wb.worksheets:
        print(f"  {w.title:<24} {w.max_row - 1} rows")
    print(f"\n  done, nothing outstanding : {counts['done']}")
    print(f"  outstanding, on us        : {counts['ours']}")
    print(f"  outstanding, needs a human: {counts['human']}")
    if sum(counts.values()) != 58:
        sys.exit("BLOCKED: rows do not total 58")
    return 0


def readme(counts):
    return [
        "SVC rework audit, refreshed 2026-09-02",
        "",
        "Covers the 58 SVC-PC tasks whose rubrics and goldens we reworked. Same layout as "
        "the 08-31 audit sheet, with the 2026-09-02 evidence added as extra columns.",
        "",
        "WHERE THINGS STAND",
        f"Done, nothing outstanding: {counts['done']}",
        f"Outstanding and on our side, all mechanical: {counts['ours']}",
        f"Outstanding and needing a person: {counts['human']}",
        "",
        "WHO OWNS THE REST",
        "Settled on the 2026-09-01 call: these fixes need a domain expert to contribute, and "
        "Sydnie is the finance expert. The substantive rubric and golden work is hers or the "
        "owning expert's. Our pass is done.",
        "",
        "HOW TO READ THE COLOURS",
        "The colour on the Task column follows the Outstanding column and nothing else. Green "
        "means there is no outstanding item. Amber means there is one and it is ours and "
        "mechanical. Red means it needs a person.",
        "A red row is not a broken task. It is a task waiting on a decision or a source file.",
        "",
        "THE ORACLE NUMBERS ARE INFORMATIONAL",
        "Two oracle runs over identical content flip 2.27% of criteria and change 20 of 42 "
        "task scores. So a failing criterion on a single run does not mean the task is broken, "
        "and the oracle columns do not drive the colour. Use 'Oracle detail 9-02' to tell the "
        "two apart: a criterion that fails in both older runs is a real defect, a criterion "
        "that fails in one run may just be the judge disagreeing with itself.",
        "",
        "BATCH ORACLE #2382 IS VOID AND IS NOT USED ANYWHERE HERE",
        "It was created 2026-09-01 00:28 EDT, the minute the platform judge credential began "
        "returning HTTP 401. All 46 of its tasks read 'Reward 0.00, 0 passed, 1 failed' at "
        "about $0.001 each: one infrastructure failure per task, not fifty criteria graded. It "
        "is not a replicate of #2381. Reading it as one says the whole build failed, which is "
        "false. So the current build has one valid run, and the replicate is blocked until a "
        "platform owner restores the credential.",
        "",
        "THE 9/01 BUILD IS NOT THE READY LIST, THOUGH BOTH ARE 46",
        "Only 41 overlap. Dataset 678 was built before the 08-31 correction, so it contains the "
        "five tasks that correction moved out as not ready (1-4-0, 2-1-0, 2-3-0, 6-4-0, 8-1-0) "
        "and omits five that are ready (1-3-0, 1-6-0, 8-3-0, 8-6-0, 15-5-0). Compare sets by "
        "id, never by count.",
        "",
        "SOURCES",
        "Partition: ekw/svc-dataos-readiness-2026-08-31.json",
        "Prior sheet, carried forward: ekw/svc-audit-2026-08-31.xlsx",
        "Oracle runs, pulled live: #2381 on dataset 678, #2374 and #2376 on dataset 675",
        "Rebuild with: python tools/svc_audit_sheet.py",
    ]


if __name__ == "__main__":
    sys.exit(main())
