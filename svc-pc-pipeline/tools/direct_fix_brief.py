#!/usr/bin/env python3
"""direct_fix_brief.py TASK -> the brief for one direct fix agent, on stdout.
Rows = every DataOS major on the task whose verify ruling is not `no` (open or unsure), joined by (task, reviewer, check) across
dataos-fresh/majors.csv + opus-addendum/majors.csv (the claim, where it points, the source file) and status.csv +
opus-addendum/status.csv (the checker's evidence of why it still holds, GPT's suggested fix as a hypothesis).
Why (2026-09-20 00:50Z): the plan-then-apply fixer closed few of the remaining rows and produced five fake-fix shapes; the rest of
the work is authoring, which needs one agent on the task's files with the full complaint text and the rules below.
"""

import csv
import pathlib
import os
import sys

FRESH = pathlib.Path("/root/qc/_prompts/verify/dataos-fresh")


def rows(p):
    if not p.is_file():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def key(r):
    return (r["task"].strip(), r["reviewer"].strip(), r["check"].strip())


def main():
    task = sys.argv[1]
    majors = rows(FRESH / "majors.csv") + rows(FRESH / "opus-addendum" / "majors.csv")
    status = {}
    for r in rows(FRESH / "opus-addendum" / "status.csv") + rows(FRESH / "status.csv"):
        status[key(r)] = r  # the verify session's status.csv wins (listed last)
    seen = set()
    open_rows = []
    for m in majors:
        k = key(m)
        if k[0] != task or k in seen:
            continue
        seen.add(k)
        s = status.get(k, {})
        ruling = (s.get("still_true") or "yes").strip().lower()
        if ruling == "no":
            continue
        open_rows.append((m, s, ruling))
    if not open_rows and not os.path.exists(f"/root/qc/stream-pipe/{task}/DIRECT-FIX-NOTE.md"):
        print(f"NO OPEN ROWS for {task}")
        sys.exit(1)
    out = []
    out.append(f"# Direct fix of {task}: {len(open_rows)} open DataOS major(s)")
    out.append("")
    out.append(
        "You are working inside this task's package directory (instruction.md, environment/, solution/, tests/). DataOS's "
        "comprehensive review rejected the task on the complaints below. Each was re-checked on the current files by our "
        "verifier and still holds (or could not be ruled). Close every one you can by changing CONTENT; report the rest honestly."
    )
    out.append("")
    out.append("## Rules (the same ones DataOS grades by)")
    out.append(
        "- NEVER close a complaint by narrowing, softening or excluding what a criterion grades. No new 'not graded', 'not required', "
        "'optional', 'any of', 'is welcome but' clauses in tests/*/judge.toml. Such an edit is reverted and counts as a failure."
    )
    out.append(
        "- A false-rejection complaint (1.4 alignment, 1.5 brittle criterion) is closed by making the rubric accept every correct "
        "answer the instruction permits while still grading the same fact (add the legitimate alternatives, fix a wrong Expected "
        "value, split a compound criterion into its independent facts with the weights preserved)."
    )
    out.append(
        "- A missing-content or wrong-golden complaint (1.1, 1.5 coverage, 1.7 consistency) is closed by changing the golden in "
        "solution/, the sources in environment/, or instruction.md so the content exists and every file agrees; the criterion keeps "
        "grading it. If the golden cites a file that does not exist, either add that file to environment/ with real, internally "
        "consistent content the task needs, or remove the citation and everything that depends on it."
    )
    out.append(
        "- A packaging or run-failure complaint (1.8, 1.2) about judge group size: split any judge group with more than 20 criteria "
        "into groups of at most 15, keeping every criterion, its weight, and its files= list; weights across a deliverable still sum "
        "to 1.0. Other 1.8 complaints: ship what the instruction names, remove what it forbids."
    )
    out.append(
        "- Protect difficulty: do not make the task easier, do not reveal answers in environment/ or instruction.md, do not copy "
        "rubric text into the golden."
    )
    out.append(
        "- Touch only files inside this task directory. In tests/, edit only judge.toml and reward.toml. Keep file names as they are."
    )
    out.append(
        "- When done, write /root/qc/stream-pipe/"
        + task
        + "/DIRECT-FIX.md: one section per complaint below, with either the exact "
        "edits (file, what changed, why it closes the complaint) or the line 'NOT FIXABLE WITHOUT A PERSON: <one sentence why>'. "
        "Nothing else is written outside the task directory. Budget: 45 minutes; stop and report at that point."
    )
    out.append("")
    out.append("## Open complaints")
    for i, (m, s, ruling) in enumerate(open_rows, 1):
        out.append(
            f"### {i}. {m['reviewer']} · check {m['check']} {m.get('check_name', '')} · verifier ruling: {ruling}"
        )
        out.append(f"- Claim: {m.get('claim', '').strip()}")
        if m.get("points_at"):
            out.append(f"- Points at: {m['points_at'].strip()}")
        if m.get("source_file"):
            out.append(f"- Review file: {m['source_file'].strip()}")
        if s.get("evidence"):
            out.append(
                f"- Verifier's evidence that it still holds: {s['evidence'].strip()}"
            )
        if s.get("gpt_suggested_fix"):
            out.append(
                f"- Reviewer's suggested fix (a hypothesis, not an instruction): {s['gpt_suggested_fix'].strip()}"
            )
        out.append("")
    note = f"/root/qc/stream-pipe/{task}/DIRECT-FIX-NOTE.md"
    if os.path.exists(note):
        out.append("## Coordinator note (task-specific, read before editing)")
        out.append(open(note, encoding="utf-8").read().strip())
        out.append("")
    print("\n".join(out))


if __name__ == "__main__":
    main()
