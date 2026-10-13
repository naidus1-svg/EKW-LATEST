# Task failure checklist (every task, SVC and EKW, before it goes on the consolidated sheet)

Built 2026-09-28 from every failure on record: 60 failed tasks from QC batches 1 to 6 (23 TFRL QC Majors, TFRL being the outside QC team, and 48
internal-review Majors, 11 tasks in both). Each class below caused at least one real rejection. A task is ready only
when you have answered every question for every criterion and fixed every "no".

Run it as SOP section 6a step 4 (the per-criterion audit) and hand the same list to the step 7 reviewer (SOP section 7). Record the
answers: one line per criterion, criterion id, then Q1 to Q4 answered yes/no with the prompt line or source cell.

This checklist is the author's own audit, done before the DataOS pipeline runs. After the pipeline runs, a task is
sent back if any of the four Answer Check reviews reports a major. That rule says when a task is
sent back; it does not change what you fix here. Run the author pre-check in the first-run SOP (section 5a) before
the pipeline, and this checklist as the per-criterion audit in step 6a.

**Every "no" is a fix. Do not rate it.** TFRL QC rejects a task when any criterion can fail a correct answer, whatever
its weight and however unlikely that answer seems. In a blind test on 2026-09-28 our reviewers found the exact
criteria QC later rejected in num-616 (the $8.63 and $9.03 book-value figures) and SVC-PC-53-5-0 (r007b2, one form of
the inbound fix), then rated both Minor and would have shipped them. If you answered "no", change the criterion or the
prompt before upload.

## Part 1: the judgment questions, for EVERY criterion (49 of the 60 failures)

A script cannot answer these. You answer them by reading the prompt, the sources and the criterion side by side.

**Q1. Does the prompt ask for this?** (22 failures, the most common cause)
Find the prompt line that asks for the exact thing the criterion checks: the figure, the row, the caveat, the
section, the named item. "The gold has it" is not a reason. If no prompt line asks for it, either add it to the prompt
or drop the criterion.
- SVC-PC-65-0-0 c-009/c-010 required costing the CEO's and COO's finance time; the prompt never asked for it.
- FIN-385 v13a required a sixth recommendation area; the prompt lists five.
- task_NUM-508 coverage required a 40.3% capitalised-interest share nobody asked for.

**Q2. Does it accept every answer the sources support?** (12 failures)
Where the sources allow more than one reasonable reading (two dates on one form, a cap that reads two ways, a
choice the prompt leaves to the solver), the criterion must accept each of them or the prompt must pick one.
- LGL-167 v6 pinned $16,828.45; the late-charge cap supports $16,808.45 too.
- task_663 v3 accepted only 74.3% utilization; SOW 4.3 supports 75.7% equally.
- SVC-PC-88-4-0: the member's own form carries two effective dates; the rubric accepted one.

**Q3. Does the expected value re-derive from the sources?** (9 failures)
Recompute every number and name in the gold and in each criterion from the files in `environment/`, yourself. If the
gold disagrees with the sources, the gold is wrong.
- PHR-152 v14 demanded a 10 to 15 month payback its own savings range cannot produce (3.9 to 7.1 months).
- SCO-240 v2/v10: the expected 17.0% lift used mismatched rows; the matched rows give 13.8%.
- GTM-175 v16 required "Orangewood Palms"; every source says "Orangewood Palms Plaza".
- SVC-PC-77-0-0 c07d summed per-SKU floors as retained stock, wrong for any SKU already below its floor.

**Q4. Does the prompt forbid or restrict it?** (6 failures)
Check the criterion against every restriction in the prompt: records-only rules, "don't assume", scope fences,
length or format freedom ("any tab naming is fine", "3 pages").
- HLT-189 required a clinical checklist and a facility restraint policy the prompt's records-only rule forbids.
- LGL-192 v24 allowed only a closed list of memo headings the prompt never states; v23 counts words for a 3-page ask.
- SVC-PC-44-0-0 c-090 failed runs for not describing channel-level results the prompt tells them not to report.

**Q5. Is every factual statement in the golden stated by a source?** (the repeat-reject pattern)
Q3 re-derives the golden's numbers and names; Q5 covers its narrative. Every citation, case, date, approval and
retest result the golden asserts must be stated in a named file in `environment/`, or remove it. Tasks DataOS
rejected twice for the same defect were usually this: an invented case, approval or retest result in the golden.

**After two rejects, classify the history before fixing again.** A different Major each round: do a full sweep of
every criterion (Q1 to Q4, split compound criteria, generalize figures or wording a correct answer could differ on).
The same defect again: run Q5 on the whole golden. Two or more of the four Answer Check reviews
reporting a major right after a full sweep: the task design is wrong, stop patching and rework it. Drop over-reach and add missing coverage in the same pass: fewer criteria is
not the goal.

## Part 2: mechanical checks (11 of the 60 failures), run the scripts

The Class letters and codes such as G1 or H2 are the check names used by the scripts in the Check column.

| Class | What goes wrong | Check | Example |
|---|---|---|---|
| E | The judge is not given the source files a fabrication or grounding criterion grades against | every such criterion's judge `files=` (rewardkit) or source `path`s (EKW native) include the sources it cites; `deterministic-checks/invention_detection_input_check.py`, `judge_scope_under_inclusion_check.py` | task_111, LGL-191, SCO-215 |
| F | Grader crash or timeout, oracle below 1.0 | oracle scores 1.0 twice (SOP 6a step 5); after the DataOS run, `deterministic-checks/oracle_reward_details_audit.py --root <unzipped with-runs>` (F2/F3) | SVC-PC-45-1-0, HLT202, PHR-156 |
| G | A deterministic check pinned to the golden's sheet names or cells while the prompt allows any layout | `deterministic-checks/layout_formula_advisory_check.py` G1 | GTM-178 |
| H | A formula-count or formula-share gate a compliant answer cannot meet | same check, H1 (floor at or above the golden's own count) and H2 (formula gate on a prompt that doesn't ask for formulas) | HLT-189 d2, GTM-187 d2 |
| I | Formulas graded with no recalculation step, so correct formulas read as blank | same check, I1; EKW native: re-vendor `tests/verifier_lib` (reward_signal_gate G6) | num-562 |

All of these run inside `deterministic-checks/pre_submit_gate.py`. Run it on your task package and read every warn,
not only the fails.

## Tested blind, 2026-09-28

Reviewers given only the task files (no runs, no QC feedback) applied this checklist to four tasks TFRL QC rejected in
QC_batch4 that our own review had missed. They found QC's exact criterion in all four: num-616 (all three reasons),
SVC-PC-53-5-0 (r007b2), num-619 (the mechanism check), task_phr-156 (fmla-8). They rated most of them Minor, which is
why the rule above says to fix every "no" instead of rating it. PHR-156's other defect, a judge timeout, only shows in
DataOS runs; `oracle_reward_details_audit.py` (F3) catches it after the run. Control tasks: SVC-PC-42-3-0 (passed
review) got no Major; hlt-214 got four that QC has not ruled on yet. The checklist flags more than QC rejects: every
extra flag is a criterion to loosen or a prompt line to add, which costs time but does not fail a task.

## What this does not guarantee

Part 1 is judgment: it catches these classes when the questions are answered honestly for every criterion, which is
what the step 7 reviewer re-checks. The examples above were all findable by reading the prompt, sources and criterion
side by side; none needed information outside the task.
