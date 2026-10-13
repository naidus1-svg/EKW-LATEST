# Golden-comparison review: evidence (2026-10-02)

Evidence behind `golden_criterion_review.py` and `golden_review_batch.py`. All numbers were measured on the TFRL-labelled QC bundles (batches 1 to 5) with the analysis scripts kept outside this repo; the sandbox lane runs used the tool in this folder. Held-out predictions for QC batches 6, 8, 9 are in `GOLDEN_REVIEW_HELDOUT_PREDICTIONS.md`.

Lane: Pipeline quality. Data: the local analysis folder and `tests.jsonl` (built 2026-09-30), 133 TFRL-judged bundles with local files (46 rejected, 87 passed). Scripts (local, the local analysis folder): an analysis script, an analysis script, an analysis script. Every number below was printed by those scripts on 2026-10-02.

## Facts (RAN)

- TFRL judged 166 tasks and rejected 55. 54 of the 55 have a MAJOR item; 90 MAJOR items in rejected tasks: misalignment 66, ambiguity 15, coverage 8, other 1.
- 76 of the 87 MAJOR items name a test id that maps to a criterion in the bundle. 69 criteria are named by a misalignment or ambiguity MAJOR.
- Zero-pass screen (criterion failed by every run, at least 2 runs): 586 criteria across the 133 tasks. 35 are TFRL MAJOR misalignment/ambiguity defects. Of the 45 such defect criteria that have run data, 35 (78 percent) are zero-pass, so the screen finds most of them, at 6 percent precision (35 of 586). 376 of the 586 sit in tasks TFRL passed.
- Traceability by script (criterion words against the prompt): AUC 0.51 to 0.58 against passed-task criteria (0.5 is chance). At a 10 percent false-flag budget the best feature flags 29 of 46 rejected tasks and 50 of 87 passed tasks.
- Run-level features among zero-pass criteria (35 defects vs 551 others): number of runs 0.52, number of models 0.50, weight 0.57. Shorter description 0.65 and fewer digits 0.60 are weak.

## What this does NOT establish

- Labels are one TFRL reviewer's reading per task, 4 to 5 batches, and only cited items are labelled. Zero-pass criteria in rejected tasks that TFRL did not cite are counted as non-defects (168 of 210).
- Only the features above were tried. A judgment-based criterion-level test (does the prompt license this value over the failing answers' value) was not run.
- Batches 6, 8 and 9 have no TFRL verdicts.

## Reading

Detection by cheap features is at its ceiling. Defects are decided by content, which is why they resist scripts and, so far, resist the local judges. The zero-pass screen is a good candidate list (about 4 criteria per task); the open question is whether a narrow criterion-level question beats the task-level reviews that blocked half the good tasks. Prevention at authoring is CTP's lane: the guide's 1.5 rule has no test for a criterion pinned to the reference answer's own wording or reading.

## Criterion-level pinned test with Sonnet agents (RAN 2026-10-02)

Method: 5 Sonnet agents, each saw only a task prompt and ONE criterion (no golden, no run data, no verdict), wrote one legitimate alternative answer and said "pinned" or "fair". Set: 76 criteria, 34 TFRL MAJOR misalignment/ambiguity defects and 42 criteria from TFRL-passed tasks (zero-pass, unlabelled), labels hidden. Files: the local analysis folder, an analysis script.

- Caught 11 of 34 defects (32 percent). Flagged 4 of 42 fine criteria (10 percent). Precision on this set 73 percent (11 of 15).
- This set is 45 percent defects. At the real rate among zero-pass criteria (35 of 586, 6 percent) the same rates give about 11 caught and about 55 false flags per 586 criteria, precision about 17 percent. That is an estimate from the rates above, not a run.
- Only 5 of 13 defect tasks had at least one defect criterion caught.
- Bar not set in advance for this test; by the lane's usual bar (catch 80 percent, few false blocks) it fails.

Not established: a different prompt, a stronger model, or giving the agent the failing answers could do better; none was tried.

## Converge versus scatter, by script (RAN 2026-10-02, an analysis script)

For each zero-pass criterion with at least 2 failing runs (582; 35 defects), the mean pairwise word-overlap (cosine) of the grader's reasoning across the failing runs. AUC 0.59 (minimum pairwise 0.59, run count 0.52). At mean similarity of at least 0.5 it flags 366 criteria and 27 of 35 defects (77 percent recall, 7 percent precision); at 0.7 it flags 60 and 7 defects (12 percent precision). Failing runs agreeing with each other, as measured by wording, does not separate defects from solver misses. Not tried: an agent reading the failing runs' answers and judging whether they agree on a defensible alternative (that run goes on the reserved sandbox lanes).

## Failing-answers test by Sonnet on reserved sandbox lanes (RAN 2026-10-02)

Method: Sonnet `claude -p` on lanes a2, j, w, a5, b, c, d, f, g (reserved by the SVC/EKW cycle session to 2026-10-04 21:00 PDT, none on the personal account). Each item: task prompt, one criterion, and the grader's reasoning for each failing run; verdict "solver_miss" or "criterion_defect". Files: the local analysis folder (78 items, bar set first: recall at least 60 percent, at most 10 percent of fine flagged) and `trace/conv_all/` (all 528 zero-pass criteria with at least 2 failing reasonings, two independent passes).

- 78-item set: 14 of 34 defects caught (41 percent) in both passes; 4 and 1 of 44 fine flagged; flagged by both passes 12 of 34 and 0 of 44. Recall below the 60 percent bar.
- Real prevalence, 528 criteria (34 defects, 494 others): pass 1 flags 81 (14 defects, precision 17 percent), pass 2 flags 71 (14 defects, 20 percent), both passes 38 flags (9 defects = 26 percent recall, 24 percent precision), both passes with confidence 2 or more 23 flags (7 defects = 21 percent recall, 30 percent precision). Run-to-run agreement 86 percent. Base rate 6 percent, so the strictest rule is a 5x lift over reading criteria at random, and it misses 79 percent of defects.
- Task level, both-pass flag: 10 of 28 rejected tasks, 10 of 70 passed tasks.
- Verdict: fails the bar as a gate. Usable only as an advisory read-first list. The 494 "others" include 139 criteria in rejected tasks that TFRL did not cite, so some false flags may be genuine defects TFRL did not list.

## Voting and Opus on the same 521 zero-pass criteria (RAN 2026-10-02, an analysis script)

Passes: Sonnet x3 (all1, all2, all3) and Opus x1 (opus1), all on reserved sandbox lanes, same prompt. 34 defects, 487 others. Single passes: Sonnet 32 to 41 percent recall at 10.5 to 13.6 percent false flags (precision 18 to 20); Opus 47 percent recall, 7.4 percent false (precision 31).

| Rule | Flags | Defects caught | False flags | Precision |
|---|---|---|---|---|
| Sonnet 2 of 3 | 61 | 14 (41%) | 47 (9.7%) | 23% |
| Sonnet 3 of 3 | 27 | 6 (18%) | 21 (4.3%) | 22% |
| Opus and Sonnet 2 of 3 | 26 | 11 (32%) | 15 (3.1%) | 42% |
| Opus conf>=2 and Sonnet 2 of 3 | 22 | 10 (29%) | 12 (2.5%) | 45% |

Base rate 6.5 percent (34 of 521), so "Opus and Sonnet 2 of 3" is a 6x lift; in TFRL-passed tasks it flags 7 of 351 criteria (2.0 percent). Recall stays at about one third, so it is a read-first list, not a gate.

Not established: the combination was picked after seeing four candidates on these same labels (no held-out set exists; batches 6, 8 and 9 have no TFRL verdicts), 34 defects give a recall interval of roughly plus or minus 16 points, and false flags in rejected tasks include criteria TFRL did not cite.

## Few-shot with QC examples, task-level stacking, and what the misses look like (RAN 2026-10-02)

- Few-shot (4 QC-confirmed defects with QC's reason text plus 4 fair criteria from other tasks, 8 example tasks excluded from scoring; held-out 446 items, 22 defects): it made every model flag more and catch no more. Sonnet 45 percent recall at 19 to 20 percent false flags (precision 11 percent); Opus 55 percent recall at 17.9 percent false (precision 14 percent). The base prompt's "Opus and 2 of 3 Sonnet" on the same items: 7 of 22 defects, 3.1 percent false, precision 35 percent. Few-shot is worse; the base prompt stays.
- Task level (all 133 bundles, 46 rejected, 87 passed): native-verifier flag catches 19 of 46 rejected and blocks 13 of 87 passed; the AI rule (Opus and 2 of 3 Sonnet, any criterion flagged) catches 10 of 46 and blocks 5 of 87; union 25 of 46 (54 percent) and 18 of 87 (21 percent); intersection 4 of 46 and 0 of 87. The union as a read-first queue: 43 tasks, 25 rejected (58 percent against a 35 percent base rate). Too many blocks to be a gate.
- The 23 defects the best rule misses cluster: task 616 has 5 (rubric grades GAAP figures, per-share alternatives and duration-gap numbers the prompt never asks for), SVC-PC-65-0-0 has 3, SVC-PC-17-7-0 2, SCO-215 2, SVC-PC-20-7-0 3 (no QC reason text). Common thread: a whole rubric theme the prompt does not ask for, which a criterion-by-criterion read cannot see. Next test: a task-level reverse trace (prompt plus all criteria, which criteria grade what the prompt does not ask for), 133 tasks, Opus x1 and Sonnet x2 on the lanes.
- Rejection rate by domain (TFRL judged): GTM 5 of 7, HLT 6 of 10, LGL 3 of 7, SCO 5 of 13, SVC-PC 21 of 68, PHR 2 of 9, FIN 5 of 26, MKT 0 of 4; counts too small to use as a prior.

## Task-level scope test, and the existing internal review as the bar (RAN 2026-10-02)

- Scope test (prompt plus ALL criteria per task, "which criteria grade what the prompt does not ask for"; 133 tasks; Opus x1, Sonnet x2 on lanes): no signal. Opus flags 17 of 46 rejected tasks (37 percent) and 34 of 87 passed (39 percent); Sonnet 61 and 52 percent of rejected against 38 and 48 percent of passed; at confidence 2 or more it is 15 and 11 percent. Criterion level: 7 to 9 of 69 defect criteria found at 2 to 5 percent precision, which is the base rate. A whole-rubric view does not separate defective tasks.
- The bar to beat is the internal review we already run (Opus adversarial pass). On the 97 tasks TFRL and the internal review judged on the same DataOS version and that have local bundles (32 TFRL-rejected, 65 passed): internal review catches 18 of 32 (56 percent) and blocks 9 of 65 (14 percent). AI list alone 6 of 32 and 4 of 65; native flag 13 of 32 and 8 of 65. Internal OR AI list: 19 of 32, 11 of 65. Internal OR native: 20 of 32, 14 of 65. Internal AND (AI list OR native): 13 of 32 (41 percent) and 5 of 65 (8 percent), a high-confidence tier.
- Reviewer consistency: across all 132 TFRL/internal pairs 90 agree (68 percent); on the 97 same-version pairs 74 agree (76 percent). Any detector scored against TFRL is bounded by that noise, and the labelled "negatives" include tasks TFRL passed that may carry the same flaws.
- Reading: nothing tested adds more than one catch over the internal review at a similar block rate. The remaining levers are upstream (authoring, CTP) and the untested definitive route (re-grade the failing runs under a loosened criterion to confirm a defect).

## Golden in view (RAN 2026-10-02): the first real lift

Why: the 23 defects the best rule missed were mostly "the criterion demands something that exists only in the golden" (QC's wording: "the gold's own unsourced assumption", "an alternative that exists only in the gold"), which cannot be seen from the prompt and failing runs alone. 133 golden file sets were extracted with markitdown (`trace/golden/`, capped 16,000 characters per task) and shown with the prompt and each criterion plus the failing runs' reasoning (`trace/gold/`, 20 batches, 98 tasks, 511 items scored: 31 defects, 480 others).

| Rule (same items) | Flags | Defects caught | False flags | Precision |
|---|---|---|---|---|
| Baseline: Opus and 2 of 3 Sonnet, no golden | 26 | 11 of 31 (35%) | 15 (3.1%) | 42% |
| Opus alone, no golden | 52 | 16 of 31 (52%) | 36 (7.5%) | 31% |
| Opus alone, golden in view | 102 | 24 of 31 (77%) | 78 (16.2%) | 24% |
| Opus golden, confidence 2 or more | 86 | 22 of 31 (71%) | 64 (13.3%) | 26% |
| Opus golden AND Opus no golden | 36 | 16 of 31 (52%) | 20 (4.2%) | 44% |
| Sonnet with golden (each pass) | 71 to 102 | 10 to 13 of 31 | 61 to 89 | 13 to 14% |

Opus uses the golden; Sonnet does not (no gain, more false flags). Not established: the picks were made on the same labels, and the false flags include criteria in rejected tasks TFRL did not cite. Next: two more Opus golden passes (gd_opus2, gd_opus3) to test Opus agreeing with itself.

## Golden Opus, three passes, and the stack that beats the current gate (RAN 2026-10-02)

Three Opus passes with the golden in view (gd_opus, gd_opus2, gd_opus3) plus the no-golden Opus pass, same 517 criteria (33 defects, 484 others, 348 in TFRL-passed tasks).

- Each golden-Opus pass alone: 70 to 76 percent recall, 15.7 to 16.1 percent false flags. Opus agreeing with itself: 2 of 3 = 25 of 33 (76%) at 14.7% false; 3 of 3 = 21 of 33 (64%) at 11.0%. Self-agreement barely cuts the false flags: Opus is consistent, so the false flags are not random noise.
- Golden Opus 2 of 3 AND no-golden Opus: 16 of 33 (48%) at 3.9% false, precision 46%.
- Are the false flags false? In TFRL-passed tasks, 44 criteria were flagged by golden Opus 2 of 3; our independent internal review also listed 18 of them (41%) as a defect (not a solver miss), against 19 of 309 (6%) of the unflagged ones. A large part of the "false" flags look like real defects TFRL did not call MAJOR.
- Task level on the 97 same-version TFRL/internal pairs (32 rejected, 65 passed): internal review alone 18 of 32, blocks 9 of 65 (56% / 14%). Golden Opus 2 of 3 alone 14 of 32, blocks 17. Internal OR golden Opus 2 of 3: 25 of 32 (78%), blocks 22 of 65 (34%). Internal OR (golden Opus 2 of 3 AND no-golden Opus): 22 of 32 (69%), blocks 13 of 65 (20%). Internal AND golden Opus 2 of 3: 7 of 32, blocks 4.
- Proposed tiers: HOLD = internal review rejects OR (golden Opus 2 of 3 AND no-golden Opus); READ-FIRST = golden Opus 2 of 3 alone.

Not established: the rules were chosen after seeing these labels (no held-out set; batches 6, 8, 9 lack TFRL verdicts), 33 defects and 32 rejected tasks give wide intervals, and the golden extraction is capped at 16,000 characters per task. Next: build the tool in the team repo, then run it on batches 6, 8, 9 to compare with TFRL when verdicts arrive.

## Operating point and what the stack still misses (RAN 2026-10-02)

- Task-level thresholds on the 97 same-version pairs (32 TFRL-rejected, 65 passed): internal review alone 18 caught / 9 blocked; internal OR at least 1 HOLD criterion 22 / 13 (69 percent / 20 percent); internal OR at least 2 HOLD 19 / 10; internal OR at least 1 golden-2of3 criterion 25 / 22 (78 percent / 34 percent); golden-2of3 with 2 or more criteria alone 9 / 5. The 1-HOLD rule is the best trade; no threshold beats it.
- The 10 TFRL rejections the stack still misses: 3 have defects only on criteria some runs pass (SVC-PC-39-4-0, SVC-PC-47-6-0, SVC-PC-53-3-0, so the zero-pass screen never looks at them); 5 have QC findings with no criterion id or no run data (FIN-369, tasj_HLT-205, SVC-PC-25-2-0, SVC-PC-7-2-0, LGL-192), so no criterion-level method can reach them; 2 are zero-pass criteria the golden review called fair (FIN-384 covenant, SVC-PC-53-5-0 r007b2). Defect criteria that some runs pass are 7 of 809, so reviewing them all would flood the list (about 16 percent false flags on 800 criteria).
- Of the 8 defect criteria golden 2 of 3 misses, about half need the task's input data (QC: "unreachable", "one of several source-supported readings"); the golden prompt does not include inputs.
- Held-out predictions for QC batches 6, 8, 9 are stored in `pipeline-quality-heldout-predictions-2026-10-02.md` (21 of 78 bundles HOLD, 10 of them internal-passed) for scoring when TFRL verdicts arrive.

## Wide-net rule (added 2026-10-02 from the first hold-review verdicts)

The hold-review lane judged the first 29 of 58 flagged criteria on svc-pc-14-1-0 against the instruction and sources: 1 confirmed defect, 28 rejected (genuine model misses or fine); 11 of the rejected ones are true source facts outside a narrow reading of the scope, but the instruction's own wording ("anything missing, stale, unsigned or otherwise unexecuted", "each affected file", "file by file") covers them. On the labelled batches 1 to 5 the only task with 9 or more golden flags (9 flags) had 0 real defects; tasks with 1 to 8 flags had 23 to 34 percent precision. `golden_review_batch.py` therefore puts a task with 9 or more flagged criteria and no internal rejection in the WIDE_NET tier (read the instruction's scope first) instead of HOLD. Thin evidence (one labelled task plus one hold-review judgement); revisit when TFRL verdicts for batches 6, 8 and 9 arrive.

## First independent verdicts on held-out flags (hold-review lane, 2026-10-02; recorded the same day)

The hold-review lane judged the flagged criteria of 10 held-out tasks (QC batches 6, 8, 9; tasks our internal review had passed) against the instruction and the sources, using the test "a correct answer can fail it, a hollow answer can pass it, or it demands what neither the instruction nor the sources ask for":

- svc-pc-14-1-0: 58 flagged criteria, 1 confirmed (a ledger-to-bank tie-out the instruction says not to do), 57 rejected. The instruction's broad hooks ("anything missing, stale, duplicated, unsigned or otherwise unexecuted", "each set of duplicate or competing versions", "where two files disagree... establish which copy governs") cover the rejected ones.
- The other 9 tasks: 10 flagged criteria, 1 confirmed (SCO-232 v11c, in an OLDER copy that the current READY version had already replaced), 9 rejected as genuine model misses or fair.
- Total: 2 confirmed of 68 judged (3 percent); 1 of the 2 was already fixed in the current version. Caveats from the judges: xlsx and docx sources could not be read, so some source claims are unverified; numeric criteria show "failed" unless they score near 1.0, so "every run failed" is weak evidence for them.

What this changes: (1) on tasks the internal review had passed, the HOLD flags are mostly noise, so the batch tool must be run on the CURRENT version of each task (flags on superseded copies are stale); (2) the 22 of 32 versus 18 of 32 gain on batches 1 to 5 was tuned on those labels and is not confirmed on fresh data; treat the tiers as a reading order only until the TFRL verdicts for batches 6, 8 and 9 are scored; (3) the WIDE_NET rule would have moved 58 of these 68 flags out of HOLD.

## Instruction-coverage step adopted (RAN 2026-10-02, 517 criteria, 3 Opus passes with the golden)

Added after the hold-review verdicts: before answering criterion_defect the reviewer must search the prompt for any sentence that covers what the criterion demands, even broadly, and answer solver_miss if one does. Same items, same labels:

| Rule | Flags | Defects caught | False flags | Precision |
|---|---|---|---|---|
| Golden prompt, 2 of 3 passes | 97 | 25 of 33 (76%) | 72 (14.9%) | 26% |
| Coverage prompt, 2 of 3 passes | 49 | 20 of 33 (61%) | 29 (6.0%) | 41% |
| Golden prompt 2 of 3 AND no-golden pass | 36 | 16 of 33 (48%) | 20 (4.1%) | 44% |
| Coverage prompt 2 of 3 AND no-golden pass | 28 | 15 of 33 (45%) | 13 (2.7%) | 54% |

The coverage step halves the false flags and loses 5 of 25 defects. `golden_criterion_review.py` now uses the coverage prompt. The minimum-runs idea (require 3 runs) cannot be tested on these labels: 25 of 26 labelled defect criteria had exactly 2 runs. Not established: the prompt change was chosen after seeing the labels it is scored on; fresh TFRL verdicts for batches 6, 8, 9 decide.

## Version staleness (hold-review lane, 2026-10-02)

The hold-review lane read the instruction and tests of the newest READY copy of each job-B task and upheld none of the 18 confirmations that had source files available as live defects: 15 of 18 quoted text the authors had since rewritten or removed (for example num-508-rewardkit: the archived v1 and v8 lack carve-outs that v9 to v11 added; eng-104 v16c-memo-blocked was replaced by two criteria that accept separate hold, scrap and supplier-return figures). The 3 still current were judged solver misses or hygiene. Lesson: a flag is only meaningful against the current version of the task. The tool now has a staleness gate (`--current`, `--current-dir`). TFRL verdicts are the exception: they judged the QC batch copy, so held-out predictions are scored against that copy.

## Stacked on the DataOS comprehensive review (hold-review lane's merged findings, 2026-10-02)

The hold-review lane merged every failed check of every current comprehensive review on 42 TFRL-labelled tasks (28 rejected, 14 passed; 185 rows, stale reviews excluded). On the 37 tasks with a current review: any major in a current review flags 19 of 25 TFRL-rejected tasks and 4 of 12 TFRL-passed (about 83 percent of what it flags is a TFRL rejection, against a 68 percent base rate); the live gate "any non-accept review" blocks 25 of 25 and 9 of 12. The SOP pass rule (both reviews report 0 majors) is the first of these.

Of the 25 rejected tasks, 6 have no major in any current review (FIN-267, PHR-156, 619, SVC-PC-45-4-0, task_GTM-187, SVC-PC-53-5-0).

The golden review (coverage prompt) overlaps this set on 19 tasks (11 TFRL-rejected, 8 passed; the rest are outside the labelled batches 1 to 5 it was scored on): any major catches 7 of 11 and blocks 0 of 8; golden HOLD catches 7 of 11 and blocks 3 of 8; any major OR golden HOLD catches 8 of 11 and blocks 3 of 8. The one extra catch is PHR-156 (golden HOLD flags 1, READ_FIRST flags 2); the 3 extra blocks are fin-351, svc-pc-93-5-0 and fin-353. Of the in-scope rejected tasks with no review major, golden flags PHR-156 and not 619, hlt-235 or svc-pc-53-5-0.

Reading: the review's own major findings are the stronger signal; the golden review adds one catch for three blocks on this sample. It is a reading aid for tasks whose reviews are clean, not a second gate. Sample is small (19 tasks); do not generalise.

## Held-out score on QC batches 6, 8 and 9 (2026-10-02)

The predictions in `GOLDEN_REVIEW_HELDOUT_PREDICTIONS.md` (78 bundles, 59 unique tasks: 17 HOLD_AI, 8 READ_FIRST, 34 CLEAN) were stored before any TFRL verdict for these batches existed. The field-engineer session scored them against TFRL first-review verdicts: 68 TFRL-reviewed tasks, 22 with a Major, 46 clean. HOLD_AI caught 4 of 22 Majors (18 percent) and flagged 5 of 46 clean tasks (10.9 percent). Best case, if every HOLD had been fixed first and the fix removed the Major: 18 of 68 tasks (26.5 percent) with a Major instead of 22 of 68 (32.4 percent).

This is far below the in-sample figures earlier in this file (those used a different rule, internal review OR golden flags, on batches 1 to 5). The held-out result is the one to use: the golden review does not cut the TFRL Major rate. It is a reading order for a person. Not established: only TFRL-reviewed tasks can be scored, and 233 of the 234 reviewed so far have a criterion every run failed, so this says nothing about tasks without one. The score was computed by another session from a Drive CSV of the flagged tasks; the full 78-bundle list is the Drive file `ekw_heldout_golden_review_all78_bundles_2026-10-02.csv`.
