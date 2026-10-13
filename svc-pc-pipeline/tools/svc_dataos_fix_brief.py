#!/usr/bin/env python3
"""Print the directed-fix brief for one SVC-PC task: locked rules + that task's exact DataOS findings.
Read by the lane fixer (_dataos_fix.sh) and passed to `claude -p --model sonnet`.

Usage: svc_dataos_fix_brief.py <TASK> [findings_json]
"""

import json
import sys

RULES = """You are repairing SVC-PC harbor task {task}. Your CWD is the task package. DataOS's GPT-5.6-sol
reviewers REJECTED this task. Below are their EXACT findings and suggested fixes. Your job is to fix each
one by editing the rubric (tests/deliverables*/judge.toml), and instruction.md + tests/task_prompt.txt only
when a finding is about ambiguity. Do not go hunting for other problems; fix what DataOS named.

METHOD - think like the GPT-5.6-sol reviewer that rejected this. Do NOT just paste the suggested_fix; it is a
hint about WHERE to look, your own re-derivation is the WHAT:
1. RE-DERIVE the correct answer from the SOURCE yourself. Read instruction.md and every file under
   environment/initial_workspace/. Compute the exact required values (totals, averages, dates, counts) FROM
   SOURCE, not from the golden. Note each value and the source cell/row it came from. If the golden disagrees
   with source, the GOLDEN is wrong - fix the golden (and rerun the oracle), do not bend the rubric to it.
2. ADVERSARIALLY test the rubric for being TOO LOOSE: can you construct an answer that passes every criterion
   but is WRONG (wrong basis, wrong count, a value the instruction forbids)? If yes, that exploit IS the
   defect - tighten the criterion so it rejects the exploit and forces your re-derived value.
3. Test the rubric for being TOO STRICT: does any criterion reject a correct answer (an exact allow-list that
   excludes a legitimately-rounded value, a single accepted basis when two reconcile)? Widen it to a
   source-justified band or accept-set.
4. For missing coverage: name the instructed fact no criterion grades, then add a criterion that grades it
   using your re-derived value. Passing the full rubric must IMPLY the task was solved correctly.
Trust your re-derivation over the suggested_fix when they conflict, and say why in your change log.

Apply each finding by its bucket:
- missing_coverage (1.5): ADD a criterion that grades the named fact. Read solution/golden_outputs/ and use
  the golden's REAL value as the expected value. Never invent a number; if you cannot find it in the golden,
  say so and skip that one.
- over_enforcement (1.4): NARROW the named criterion to exactly what instruction.md requires, or remove it.
- ambiguity (1.3): edit instruction.md AND tests/task_prompt.txt IDENTICALLY to state the one required
  reading the golden takes. Change nothing else.
- source_consistency (1.7) / leakage (1.6): follow the suggested_fix.

Hard rules:
- After editing, the golden (solution/golden_outputs) MUST still pass EVERY criterion. Re-hand-grade the
  golden against your edited rubric; if any edit makes it fail, you got the edit wrong, redo it.
- Never lower difficulty. Adding coverage or narrowing an over-reaching criterion is not lowering
  difficulty; deleting a legitimate graded requirement is, and is forbidden.
- Expected values live ONLY in tests/deliverables*/judge.toml. NEVER write an expected value into
  instruction.md or tests/task_prompt.txt (the solver reads those).
- Keep <= 15 criteria per judge dir; if adding one pushes a dir over 15, split it into
  deliverables_NN_p2/_p3 (copy the [judge] block, partition criteria). LF line endings only.
- Do not wb.save() a golden xlsx without restoring formula caches.

THEN VERIFY THE WHOLE RUBRIC LIKE GPT (not only the named findings - this is objective work, not a severity
call, so it does NOT hit the local-reviewer severity wall):
1. RE-DERIVE FROM SOURCE. Independently compute the correct value for each graded field from the source
   files, the way the golden author should have. If the golden disagrees with the source, the GOLDEN is
   wrong - fix solution/golden_outputs and its downstream cells, not the rubric.
2. BUILD A PASSING-BUT-WRONG ANSWER. Try to satisfy EVERY criterion with a materially wrong deliverable (a
   wrong-basis value in a required cell, an alternative the rubric still accepts, a fact no criterion forces).
   If one exists, the rubric is too loose - tighten until no such answer exists. Report the exploit you tried.
3. COVERAGE. For every requirement instruction.md states, name the criterion that FORCES it; add one (graded
   against the value from step 1) for any gap. Do not over-tighten so a correct answer is rejected.
4. Confirm the golden still scores 1.0. Iterate 1-4 until no re-derivation mismatch, no passing-but-wrong
   answer exists, every requirement is forced, and the golden = 1.0.

When done, report the re-derivation result, the exploit you tried and how the tightened rubric blocks it, the
coverage list, each finding id and what you changed, and the final oracle score. Then stop.

=== DataOS findings to fix ==="""


def main():
    task = sys.argv[1]
    fj = sys.argv[2] if len(sys.argv) > 2 else "/root/qc/_findings.json"
    data = json.load(open(fj, encoding="utf-8"))
    d = data.get(task, {})
    findings = d.get("findings", [])
    # dedupe by (check_id, name), keep the one with the longest suggested_fix, skip deterministic (handled)
    best = {}
    for f in findings:
        if f.get("bucket") == "deterministic":
            continue
        key = (f.get("check_id"), f.get("name"))
        if key not in best or len(f.get("suggested_fix") or "") > len(
            best[key].get("suggested_fix") or ""
        ):
            best[key] = f
    print(RULES.format(task=task))
    if not best:
        print("(no non-deterministic findings on record for this task)")
        return
    for i, f in enumerate(
        sorted(best.values(), key=lambda x: str(x.get("check_id"))), 1
    ):
        print(
            f"\n[{i}] {f.get('check_id')} {f.get('bucket')} / {f.get('name')} (severity {f.get('severity')})"
        )
        print(f"  problem: {f.get('justification')}")
        print(f"  DataOS suggested_fix: {f.get('suggested_fix')}")


if __name__ == "__main__":
    main()
