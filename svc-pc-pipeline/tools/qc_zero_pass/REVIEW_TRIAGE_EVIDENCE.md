# Review triage: what TFRL rejects, and what the DataOS review's majors say (2026-10-02)

## The finding

The DataOS comprehensive review puts a major on almost every task. Control run #1170 (a DataOS review-only run on the live review prompt, 25 TFRL-rejected and 12 TFRL-passed tasks) flagged 23 of 25 rejected tasks and 10 of 12 passed tasks. So "block on any major" cannot tell the two groups apart.

TFRL rejects mostly for one kind of defect: the golden answer, the source files or the prompt itself is wrong or ambiguous. The review's other majors (a weak answer can still score, the grading scripts misbehave, a criterion is strict) appear on rejected and passed tasks at about the same rate.

## How it was measured (all RAN 2026-10-02)

Data: the 84 unique (task, check) majors of the control runs #962 (10-task screen) and #1170 (37 tasks), as exported by the hold-review lane (`ekw/dataos-review-arms-results-2026-10-02/` on branch handoff/review-prompt-arms-2026-10-02 of khiemdoan-turing/turing-context, hashes in its MANIFEST.txt). They fall on 40 tasks: 25 TFRL-rejected and 15 TFRL-passed. 7 more tasks have no major (5 rejected, 2 passed), so the denominators below are 30 rejected and 17 passed.

Method: three independent Opus passes labelled each major by direction, with the TFRL label and the task name removed. All 84 labels were identical in all three passes. The prompt is `DIRECTION_RULE` in `triage_review_majors.py`.

| Kind of major | Rejected tasks that have one (of 30) | Passed tasks that have one (of 17) |
|---|---|---|
| Any major (the live rule) | 25 | 15 |
| Answer key, sources or prompt wrong (HOLD) | 10 | 2 |
| Correct answer failed (unfair_to_correct) | 15 | 7 |
| Weak answer can score (lenient) | 23 | 11 |
| Grading machinery (harness) | 2 | 3 |

By check on control #1170 (hold-review lane count; check 1.1 is Solvability / correctness, 1.5 is Rubric coverage and calibration, 1.7 is Source-document and prompt internal consistency; the full list is in `../../../docs/ekw-svc-comprehensive-review.md`): majors from checks 1.1 or 1.7 were on 7 of 25 rejected tasks and 0 of 12 passed tasks; 1.5 majors were on 22 rejected and 10 passed tasks.

Other tests that did not separate the groups: blocking only on majors that cite a run (22 of 30 rejected, 14 of 17 passed); how much of the reward the all-failed criteria carry (AUC 0.58 on 130 tasks); a rule written by Opus from half the tasks and tested on the other half (72 percent of rejected tasks caught, 53 percent of passed tasks blocked; three runs wrote the same two-step rule: reject on a wrong golden, source or prompt, or on a run that did correct work and lost reward).

## What it does NOT establish

- 40 tasks, 15 of them passed. The intervals are wide: 2 of 17 could be 0 to 6, and 10 of 30 could be 5 to 15.
- Direction labels are Opus's judgment. Identical labels in three passes also mean a shared bias is possible.
- It has not been checked on fresh batches. Batches 6, 8 and 9 are being scored by another session against TFRL's verdicts.
- It says nothing about whether TFRL's rejections are right. Several TFRL-passed tasks carry run-backed defects of the other kinds.
- The script was run end to end once, on the 84 majors on lane a2, a4 and a5: it labelled 18 as HOLD, the same 18 the hand-run labelled `reference_defect`. It has not been run on a live review JSON (the unit tests use the shape `build_review_union.py` reads).
