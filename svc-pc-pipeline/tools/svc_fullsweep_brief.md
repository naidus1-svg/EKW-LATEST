You are hardening SVC-PC harbor task {TASK} so it passes DataOS Comprehensive Review on the FIRST upload.
This task has NOT been graded yet, so there are no findings to copy - you run the COMPLETE coverage sweep
yourself. Point-fixing one criterion is exactly why past tasks failed 2-3 times; do the whole sweep.

DO THIS, in order:
1. RE-DERIVE FROM SOURCE. Read instruction.md and every file under environment/initial_workspace/. Compute
   the correct value for EVERY graded fact yourself (totals, per-row values, dates, counts). Note each with
   the source cell/row it came from. If the golden disagrees with source, the GOLDEN is wrong - fix the
   golden (restore formula caches) and re-run the oracle; do not bend the rubric to a wrong golden.
2. COVERAGE MAP. List EVERY factual requirement in instruction.md. For each, name the criterion that FORCES
   it. Three gaps to close:
   - a requirement with NO forcing criterion -> add one, graded against your re-derived value;
   - a criterion covering only a SUBSET (e.g. 10 of 24 rows, 5 of N employees) -> extend it to the FULL set;
   - a criterion that accepts a wrong value via "Expected: X or Y" (two bases/values joined by "or")
     -> keep the instruction-required one, delete the wrong alternative.
   Passing the whole rubric must IMPLY the task was solved correctly.
3. ADVERSARIAL. Try to build a deliverable that passes every criterion yet is materially wrong. If you can,
   the rubric is too loose - tighten until you cannot.
4. GOLDEN 1.0. Re-hand-grade solution/golden_outputs against the edited rubric, then run the oracle. Iterate
   1-4 until: no partial coverage, no passing-but-wrong answer, every requirement forced, golden scores 1.0.

HARD RULES: expected values live ONLY in tests/deliverables*/judge.toml, never in instruction.md or
tests/task_prompt.txt; keep <= 15 criteria per judge dir (split into deliverables_NN_p2 if needed); LF line
endings; do not wb.save() a golden xlsx without restoring formula caches; never lower difficulty. When done,
report the coverage map (requirement -> criterion), the exploit you tried, and the final oracle score.
