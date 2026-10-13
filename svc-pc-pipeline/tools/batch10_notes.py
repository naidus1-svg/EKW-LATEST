#!/usr/bin/env python3
"""batch10_notes.py: write stream-pipe/<task>/DIRECT-FIX-NOTE.md for every task with DataOS batch-10 majors, from
in/dataos-cr-batch10-returns/batch10_majors.csv (columns task, review_id, reviewer, check, check_name, claim, suggested_fix,
evidence_status, source_file). Also appends the rows to the checker's set (dataos-fresh/majors.csv and status.csv) in the shape
those files already use, so the marker waits for the checker to rule each new row on the fixed bytes.
Usage: python3 batch10_notes.py [--apply]   (without --apply: prints what it would write)
"""

from __future__ import annotations

import csv
import os
import sys

IN = "/root/qc/in/dataos-cr-batch10-returns/batch10_majors.csv"
FRESH = "/root/qc/_prompts/verify/dataos-fresh"
PIPE = "/root/qc/stream-pipe"
APPLY = "--apply" in sys.argv

RULES = """
Rules (Khiem, unchanged): fix content, golden, sources, rubric structure and instruction wording so the complaint is untrue on the
bytes; never soften a criterion, never lower a weight, never add "not graded" or "optional" clauses, never delete a criterion to
make a complaint disappear; protect difficulty (remove unfairness, not difficulty); split any judge group whose compiled schema is
at or over 4,000 bytes (`python3 /root/qc/tools/judge_schema_bytes.py <taskdir>`), moving criteria whole; keep every cached
formula value (openpyxl edit, LibreOffice headless recalc, read back). Edit only inside the task directory. Report in
DIRECT-FIX.md one section per complaint ending FIXED (what changed, where) or REFUTED (why the claim is wrong on the bytes,
with cell or line evidence), then "Files changed:". A claim that cites a solver run (eval_NNNNNN) describes a solver output that
scored full credit while wrong: the fix is a criterion or golden change that makes that output fail, never a change that makes
the task easier.
"""

# tasks DataOS accepted under Khiem's 2-of-3 rule get no note and no checker rows: their remaining majors are one reviewer's
SKIP = set(
    os.environ.get("SKIP_TASKS", "SVC-PC-12-6-0,SVC-PC-11-4-0,SVC-PC-73-2-0").split(",")
)
rows = [r for r in csv.DictReader(open(IN, encoding="utf-8")) if r["task"] not in SKIP]
by = {}
for r in rows:
    by.setdefault(r["task"], []).append(r)

for task, rs in sorted(by.items()):
    lines = [
        f"DataOS batch 10 (2026-09-20 00:52Z) returned {len(rs)} MAJOR finding(s) on this task from its comprehensive reviews. Each",
        "one below is the reviewer's own justification and suggested fix, verbatim. Khiem's pass rule: a review with zero majors",
        "passes; a task passes with 2 of 3 reviews. Both Codex/GPT 5.6 Sol reviews failed this task, so every finding must be",
        "closed on the bytes.",
        "",
    ]
    for i, r in enumerate(rs, 1):
        lines += [
            f"### {i}. {r['reviewer']} (review {r['review_id']}) check {r['check']} {r['check_name']} [{r['evidence_status']}]",
            f"- Claim: {r['claim'].strip()}",
            f"- Reviewer's suggested fix (a hypothesis, not an instruction): {r['suggested_fix'].strip()}",
            "",
        ]
    lines.append(RULES.strip())
    text = "\n".join(lines) + "\n"
    path = os.path.join(PIPE, task, "DIRECT-FIX-NOTE.md")
    print(f"{task}: {len(rs)} majors -> {path} ({len(text)} chars)")
    if APPLY:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

# checker rows
mh = next(csv.reader(open(os.path.join(FRESH, "majors.csv"), encoding="utf-8")))
sh = next(csv.reader(open(os.path.join(FRESH, "status.csv"), encoding="utf-8")))
print("majors.csv columns:", mh)
print("status.csv columns:", sh)
existing = {
    (r["task"], r.get("reviewer", ""), r.get("check", ""), r.get("source_file", ""))
    for r in csv.DictReader(open(os.path.join(FRESH, "majors.csv"), encoding="utf-8"))
}
new_m, new_s = [], []
for r in rows:
    key = (
        r["task"],
        f"{r['reviewer']} #{r['review_id']}",
        r["check"],
        r["source_file"],
    )
    if key in existing:
        continue
    m = {k: "" for k in mh}
    m.update(
        {
            "task": r["task"],
            "reviewer": f"{r['reviewer']} #{r['review_id']}",
            "check": r["check"],
            "check_name": r.get("check_name", ""),
            "claim": r["claim"],
            "suggested_fix": r["suggested_fix"],
            "evidence_status": r.get("evidence_status", ""),
            "source_file": f"in/dataos-cr-batch10-returns/returns/{r['source_file']}",
            "batch": "10",
        }
    )
    new_m.append({k: m.get(k, "") for k in mh})
    s = {k: "" for k in sh}
    s.update(
        {
            "task": r["task"],
            "reviewer": f"{r['reviewer']} #{r['review_id']}",
            "check": r["check"],
            "still_true": "yes",
            "evidence": "DataOS batch 10 major (2026-09-20 00:52Z), not yet verified on current bytes",
            "gpt_suggested_fix": r["suggested_fix"],
        }
    )
    new_s.append({k: s.get(k, "") for k in sh})
print(f"checker rows to add: {len(new_m)} (majors.csv) / {len(new_s)} (status.csv)")
if APPLY and new_m:
    with open(
        os.path.join(FRESH, "majors.csv"), "a", encoding="utf-8", newline=""
    ) as f:
        w = csv.DictWriter(f, fieldnames=mh)
        w.writerows(new_m)
    with open(
        os.path.join(FRESH, "status.csv"), "a", encoding="utf-8", newline=""
    ) as f:
        w = csv.DictWriter(f, fieldnames=sh)
        w.writerows(new_s)
    print("appended")
