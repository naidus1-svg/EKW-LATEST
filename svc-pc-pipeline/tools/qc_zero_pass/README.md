# Internal zero-pass review (run on every QC batch)

TFRL QC (the human QC team) samples 20% of each batch. This review covers the rest of the risky tasks ourselves: every task in the batch
where at least one test fails in every agent run ("yes (some fail)" Headroomness, the label in the DataOS Test Results Matrix).
On QC_batch5 it reviewed 24 tasks (9 CLEAN, 2 MINOR,
13 first-pass MAJOR) and all 13 Majors were confirmed by the verifier. On QC_batch1 to 4 it reviewed 116
tasks and confirmed 32 task defects (37 first-pass Majors, 4 downgraded, 1 unsure), marked exactly like manual QC.

Working folder: `$QC_REVIEW_DIR` (default `~/Documents/qc_review`): `manifest.json`, `zero_tests.json`,
`ids_to_batch.json`, `<batch>/zips`, `<batch>/work`, `<batch>/verdicts`.

## Steps

1. For each task in the batch, read its Test Results Matrix with `headroom(id)` from `dataos_helpers.js` (on a task
   whose batch copy shows no runs, use its source task). Keep tasks with a non-empty `zero` list. The matrix shows at
   most 100 test rows, so also download every task with `n` exactly 100 or no per-test results and run
   `zero_recompute.py` on it: on QC_batch7, SCO-239 read "no (100% pass)" in the matrix and had 34 zero-pass tests.
2. Add them to `manifest.json` (`batch`, `ws`, `task` = sheet name, `dataos_name`, `author`, `copy` = the id you will
   download, `batch_copy`, `zero`), `zero_tests.json` and `ids_to_batch.json` (id -> `bN`).
3. Downloads need Khiem's explicit OK (count, source, size). Then run `python mover_all.py 60` in the background and
   `dlQueue([...ids])` in the DataOS tab. One download at a time.
4. First pass: reviewer agents follow `REVIEW_BRIEF.md`, about 5 tasks each, **at most 3 agents at once** (15 at once
   crashed the session on 2026-09-26). Output `<batch>/verdicts/<TASK>.json`.
   Each reviewer runs `python zero_recompute.py --batch bN <TASK>` after unzipping and reviews every test it lists,
   not the manifest's `zero` list (which missed 16 tests on SVC-PC-31-4-0 in QC_batch6).
   Before reviewers start, run `python static_checks.py --batch bN`: the mechanical checks from the QC batch 1-6
   failure analysis (G1 layout pin, H1/H2 formula gates, I1 no recalc, F2 oracle below 1.0, F3 run crash or timeout).
   All are warnings; pass each G1/H1/H2/F2/F3 hit to that task's reviewer as a lead to confirm.
5. Every first-pass MAJOR gets an independent adversarial verifier (`VERIFY_BRIEF.md`) -> `<TASK>.verify.json`.
6. `python apply_internal_fails.py --batch bN` (dry run), then `--apply`. Marks only verdict MAJOR + verify
   CONFIRMED_MAJOR: consolidated H "Done", K:M ratings, N note tagged "Internal zero-pass review (Khiem's team, not
   TFRL QC)"; tracker "Rejected" (task_N collision guard). Snapshot + read-back built in. Batches are discovered from
   the `bN` folders (bN -> QC_batchN), so a new batch needs no code change.
   - Each task is marked once. `applied_tasks.json` records every applied `bN/<task>`; a rerun skips them, because
     authors then fix and resubmit, which clears the note or moves the tracker status on, and re-marking would
     re-reject work in progress. To re-mark a task on purpose, delete its ledger entry first.
   - A CONFIRMED_MAJOR whose verify `ratings` carry no "Major" is held back ("no Major in verify ratings"). Fix the
     verify file's ratings to match its feedback, then apply. QC_batch5 598 went out with Minor/Good/Good this way.
7. `python audit_marks.py --show` to prove every confirmed fail is marked and nothing else carries the tag. After
   authors resubmit, "tracker not Rejected" and cleared consolidated rows are expected for already-applied tasks.
8. `python fail_dump.py` groups confirmed fails by author for the author messages (draft with an evidence ledger;
   Khiem sends).

## What it does not establish

It judges only tests at 0% in every run. A CLEAN verdict is not a TFRL QC approval, and tasks labelled "Almost 100%
pass" or "no (100% pass)" are not reviewed.

## Golden-comparison review of zero-pass criteria (advisory)

`golden_criterion_review.py <bundle.zip|dir> [--config-dir /root/.claude-<lane>]` takes one task bundle, finds every criterion that every solver run failed
(at least 2 runs), and asks Opus whether the criterion is the problem. Three passes see the prompt, the criterion, the failing runs' grader reasoning and the
golden answer; one pass sees the same without the golden. Output JSON with two tiers: `hold_ai` (golden 2 of 3 AND the no-golden pass say defect) and `read_first`
(golden 2 of 3). Advisory: it never blocks a task, and a reviewer reads each flagged criterion against the prompt and the golden. The block is outside this tool: on EKW tasks `python qc.py proof init` runs it and every HOLD_AI criterion needs a written row before `python qc.py proof check` prints `PROOF: COMPLETE` (the proof step of docs/QC-RUNBOOK-qc-person.md). `$GCR_CLAUDE` replaces the `claude` command (the tests point it at a fake).

Why the golden: most criteria QC calls "pinned" demand something that exists only in the golden (its own assumption, an unsourced figure, an alternative or
analysis the prompt never asks for), which cannot be seen from the prompt and the runs alone. Run it on a lane (`--config-dir`), never on a personal account;
a task takes 4 `claude -p` calls and about 2 minutes. `python test_golden_criterion_review.py` runs the stdlib tests with no model call (`--replay-dir` scores saved replies).
It reads `instruction.md`, the grader (`judge.toml`, or `tests/verifier.json` where the criteria are called v1, v2 and so on), the golden from `solution/files` or `solution/golden_outputs`, and each AI attempt's `reward-details.json` in any of its three shapes (plain, a list of judge passes, a group). The bundle can be a zip, a task folder or one `rev_<n>__<id>` folder.

Measured 2026-10-02 on 133 TFRL-labelled bundles (46 rejected, 87 passed; 33 TFRL-confirmed defect criteria among 517 zero-pass criteria): golden Opus alone finds
70 to 76 percent of the defect criteria and flags about 16 percent of the others; golden 2 of 3 AND the no-golden pass flags 48 percent of the defects at 3.9 percent
false flags (precision 46 percent). At task level on the 97 tasks TFRL and the internal review judged on the same version: the internal review alone caught 18 of 32
TFRL rejections and blocked 9 of 65 passes; internal review OR (golden 2 of 3 AND no-golden) caught 22 of 32 and blocked 13 of 65. Where golden Opus flagged a criterion in a
task TFRL passed, the internal review also called it a defect 41 percent of the time (6 percent for unflagged), so part of the "false" flags look like real defects TFRL did not call MAJOR.

Not established: the tiers were chosen on the same labels they are scored on (no held-out set yet; QC batches 6, 8 and 9 have no TFRL verdicts), the golden text is capped at
16,000 characters per task, and 33 defects give wide intervals. Evidence: `GOLDEN_REVIEW_EVIDENCE.md`; held-out predictions: `GOLDEN_REVIEW_HELDOUT_PREDICTIONS.md`.

### One command for a whole batch: `golden_review_batch.py`

`python golden_review_batch.py --bundles <dir of bundle zips or task dirs> --lanes /root/.claude-a2,/root/.claude-j,... --out <outdir> [--verdicts <bN/verdicts>]`
runs the golden-comparison review on every bundle in parallel (one worker per lane), skips bundles whose output already exists (resumable), merges the
internal zero-pass review verdicts (first pass MAJOR and adversarial pass CONFIRMED_MAJOR counts as rejected, the rule `apply_internal_fails.py` uses), and writes
`report.md` and `report.json` ranked HOLD (internally rejected, or at least one HOLD_AI criterion), READ_FIRST, WIDE_NET (9 or more flagged criteria and no internal rejection: read the instruction's scope first), ERROR, CLEAN. Advisory: it marks nothing failed.
Run it on a lane host, never on a personal account, and on the CURRENT version of each task (a flag on a superseded copy is stale: the first hold-review verdicts found one already fixed in the READY version). Treat the tiers as a reading order until they are scored on fresh TFRL verdicts. `python test_golden_review_batch.py` runs the 4 stdlib tests (no model call).

What the batch tiers are worth (measured 2026-10-02 on QC batches 1 to 5, 97 tasks judged by TFRL and the internal review on the same version: 32 TFRL-rejected, 65 passed):

| Gate | TFRL rejections caught | TFRL-passed tasks blocked |
|---|---|---|
| Internal review alone | 18 of 32 (56%) | 9 of 65 (14%) |
| HOLD (internal review OR at least one HOLD_AI criterion) | 22 of 32 (69%) | 13 of 65 (20%) |

Fresh run, QC batches 6, 8, 9 (78 bundles with a criterion every run failed): 21 HOLD, 11 READ_FIRST, 46 CLEAN; 10 of the 21 HOLD tasks were passed by the internal review.
Predictions were stored before TFRL verdicts existed. Scored later against TFRL's first-review verdicts for batches 6, 8 and 9 (68 TFRL-reviewed tasks, 22 with a Major, by the field-engineer session): HOLD_AI caught 4 of 22 Majors (18 percent) and flagged 5 of 46 clean tasks (10.9 percent). That is the held-out result. The 22 of 32 figures above are in-sample and use a different rule (internal review OR golden flags). Do not expect the golden review to cut the TFRL Major rate; it is a reading aid.

Current measured numbers for the review prompt (all 517 zero-pass criteria of the labelled batches, 33 TFRL-confirmed defects): golden review with the instruction-coverage step, 2 of 3 passes: 20 of 33 defects at 6.0 percent false flags (precision 41 percent); stacked with the no-golden pass: 15 of 33 at 2.7 percent (precision 54 percent). Without the coverage step: 25 of 33 at 14.9 percent (precision 26 percent). Details in `GOLDEN_REVIEW_EVIDENCE.md`.

### Staleness gate: always check a flag against the CURRENT version of the task

Authors rewrite tasks after a review. The hold-review lane checked 18 of the first batch-6/8/9 confirmations against the newest READY copies and 15 quoted text the authors had already rewritten or removed. So the tool takes the current version of the task: `golden_criterion_review.py <bundle> --current <current version>` (batch: `golden_review_batch.py ... --current-dir <folder of current versions, same task names>`). A flag whose criterion is missing from the current version, or whose text differs there, is labelled STALE and leaves the HOLD and READ_FIRST lists (it is kept in the JSON with the reason). Without `--current` nothing is checked, so every flag is only as fresh as the bundle it came from. TFRL scoring is different: score against the version TFRL saw (the QC batch copy).

### Sort a DataOS review's majors by what TFRL rejects: `triage_review_majors.py`

`python3 triage_review_majors.py REVIEW.json [REVIEW2.json ...] [--out report.md] [--lanes DIR,DIR,DIR]` reads the review JSON files, takes the majors, and has Opus (3 passes, 2 of 3 must agree) label each one. A major that says the golden answer, the sources or the prompt itself is wrong is **HOLD**: the task should not go to TFRL until it is fixed (exit code 10). A major where a correct answer is failed and a recorded run shows it is FIX_NEXT. A weak answer that can still score, a grading-script problem, or anything else is FIX_LAST. The 0-majors SOP rule is unchanged; this only orders the work and adds the hold. Measured on 40 TFRL-labelled tasks: HOLD majors were on 10 of 30 rejected and 2 of 17 passed tasks. Evidence and limits: `REVIEW_TRIAGE_EVIDENCE.md`. Tests: `python3 test_triage_review_majors.py`.
