> New here? Start at the [repo start page](../README.md); every doc in the repo is in the [doc index](../docs/README.md).

# SVC-PC fix-and-ship pipeline

This folder is the whole SVC-PC pipeline as it runs on 2026-09-25, plus the EKW lane path added that day: the
lane runner that fixes a task, the gates it must pass, the bundler that ships it to DataOS, the return intake,
and the tracker tools that submit passes for manual QC. Everything here is the live copy; the sandbox runs these
exact files (checked by hash on 2026-09-25).
A "lane" is one Claude Max login (`/root/.claude-<letter>`) on the sandbox that runs one task fix at a time;
step 2 below describes how lanes are used.

Results it produced on 2026-09-23: 20 tasks to manual QC in one day, including the first L3 pass (46-0-0);
DataOS batch pass rates 6/28 and 13/29, and 52% for tasks with a full adversarial-verify READY.
Those figures were measured under the older DataOS pipelines, before "ManualQC automated QC pipeline 4 Reviewers".
They are early and unaudited, and they do not predict results under the current pipeline.

## Read first

| Doc | What it is |
|---|---|
| `docs/svc-return-runbook.md` | **CURRENT SEQUENCE** - the step list: return intake, bundling, upload, pool control. Start here. |
| `docs/svc-pc-plain-guide.md` | Plain-language explanation of the method (full coverage sweep, DataOS as the only verdict). SUPERSEDED (see the [doc index](../docs/README.md)): do not follow its commands. |
| `docs/svc-pc-one-shot-fix-guide.md` | How to fix one task by hand with a high success rate. STALE: its pass rule is out of date; the [QC SOP](../docs/QC-SOP-first-run.md) is the process. Do not follow its commands. |
| `tools/svc_fix_method_rules.md` | The fix and verify rules (R1-R7). Line 1 is `METHOD_VERSION` (the version stamp: change a rule, bump it); every prompt embeds this file. |
| `skills/task-doc.md` | The submission record: QCR doc (SOP sections), SVC QC Tracker mark, consolidated tracker row. |
| `docs/plan-v6-dataos-as-gate.md` | The live operating plan and dated state log; the "why" behind each rule. Newest first. |
| `docs/qc-intake-process.md` | Human QC intake since 2026-09-24: Khiem sends batches of 50+ to the TFRL QC team (the human reviewers who sample each batch); `tools/qc_batch_build.py`. |

## The pipeline, step by step

1. **Queue and triage** - `svc_triage_queue.py --apply` orders `_v7/queue.txt`: pins in `_v7/priority.txt` first,
   then near-misses (tasks with a DataOS review already at 0 majors), then fewest majors. <= 2 majors go to
   `targeted.txt`. `svc_build_directed_briefs.py` writes one brief per rejected task from every DataOS review it
   has had.
2. **Lanes** - `sandbox_root/svc_v7_pool.sh` gives every Claude Max lane (`/root/.claude-<letter>`) a persistent
   worker that polls the queue every 2 minutes (stop cleanly with `touch /root/qc/_v7/POOL_STOP`); each
   runs `sandbox_root/svc_v7_lane_runner.sh <TASK> <LANE>`, which loops up to 10 attempts:
   fix (Opus; class enumeration, recompute from source, requirement walk, re-audit) ->
   oracle (`tools/judge_emulate.py`, golden must score 1.0) -> eval-regrade (`tools/svc_eval_regrade.py`, the real
   DataOS answers re-graded against the fixed rubric) -> adversarial verify (must say READY-TO-RESUBMIT) ->
   coverage trace (`tools/svc_coverage_trace.py`) -> oracle confirm run -> gated zip
   (`tools/svc_build_upload_zip.py`: prefilter, rewardkit 0.1.7 loader, verify, regrade, freeze lists).
   Stop: `svc_v7_stop.sh`. Stuck tasks onto idle lanes: `tools/svc_release_launch.sh`.
   **Decide mode** for a task that parked on the same blocker (listed in `_v7/decide.txt`): instead of another
   generic fix, the lane gets the exact failing criteria, the DataOS answers they fail and the golden diagnosis,
   and must pick per criterion REWRITE / DROP / KEEP (answer genuinely wrong, with a cited source record) /
   FIX-GOLDEN, writing `_deepfix/<task>.decision.json`. `svc_eval_regrade.py --decision` exempts only a KEEP
   that cites evidence and a reason, and lists it under `kept_by_decision` in the verdict. The same blocker
   twice in decide mode parks the task with its decision record.
   **Automatic since 2026-09-24/25:** a normal-mode dead end (same blocker repeated) or the 10-attempt cap sends
   the task to decide mode by itself (runner exit 30, logged in `_v7/auto_decide.txt`); a lane usage limit
   (exit 10) never parks a task; the runner releases its own claim on exit 10/30 (a pool restart used to strand
   claims); decide runs get 5400 s and a decide run killed by that limit is a tool problem, not a stuck task.
   **Every park is classified TASK or GATE before anyone releases or unclaims it** (TASK: the problem is in the task;
   GATE: the problem is a bug in one of our own checking tools). Read
   `_deepfix/<task>.regrade.json` (`verdict`, `why`, `llm_regrade.ran`, `direction_B.proof`) and the decision's
   `gate_note`. A `GATE-ERROR` verdict, a re-grade that never ran, a decide run that disputes the gate with
   evidence, or a decide timeout is a bug in our tools: fix the tool, add a regression test named after the task,
   release. The runner writes these to `_v7/gate_errors.txt`. On 2026-09-24, 7 of 8 "genuinely stuck" parks were
   two `svc_eval_regrade.py` bugs (`tools/test_svc_eval_regrade_gate.py`); 4 of those 7 have since passed DataOS.
3. **Bundle and upload** - `tools/svc_bundle_upload.py sweep|bundle|check`: only manifest-backed, byte-fresh zips
   ship. DataOS rejects zips over 500 MB: `tools/svc_split_bundle.py`. Upload, then run the pipeline
   "ManualQC automated QC pipeline 4 Reviewers" (version 8 on 2026-10-05). It runs the five evaluation runs (the
   oracle runs, the GPT 6 Sol solver runs and the empty-answer NOP run), then four identical Answer Check reviews
   (Claude Opus 5.5, medium effort; the review prompt is DataOS saved prompt 431, named
   "Comprehensive_v3_pipeline_quality_re-derive_cascade_NOP_2026-10-03"). The two Failed Tests reviews were removed in version 7. The "NO CLAUDE"
   pipeline, the older "ManualQC automated QC pipeline" (version 5 and earlier, a different pipeline from 4
   Reviewers), the version 6 pair rule and the "2 of 3 reviews valid" rule are retired.
   **Pass rule:** a task fails the pipeline if any of the four Answer Check reviews reports a major, and passes only
   when all four are clean. The author reads each review with a major and fixes what is real. A manager then reviews the result (`../docs/task-review-rules-v2.md`): a task that
   fails goes back to the author with the failed checks, and a task that passes can go in the next TFRL batch unless
   the manager's own read finds a Major they can show, or a manager reader item has no answer that holds up (QC SOP,
   section 7; no Major has to be shown for those items). A pipeline pass is not a TFRL QC approval.
4. **Return intake** - `tools/svc_record_return.py <with_runs.zip> --apply` (the zip is the DataOS "Dataset with runs"
   download of the returned batch): freezes passers, requeues rejects with
   their graded bytes fingerprinted. **Caution:** a copy of the tool from before 2026-10-05 passes a task when at
   least two reviews are clean, and it does not read Answer Check replies, which carry `findings` instead of `checks`
   (checked 2026-10-05 by running the review parser on synthetic reviews: none of four clean Answer Check replies is
   read, and four reviews with one major still meet the at-least-two-clean count). The rule above is that any major in any review fails the
   task. Check its line against the four reviews by hand before `--apply` freezes a task.
   `tools/svc_return_cohort.py` for pass rates.
5. **Record passes** - `skills/task-doc.md`: QCR doc (the one-page document named QCR_<name>_<date> that is handed to the QC team), `tools/svc_mark_manual_qc.py`,
   `tools/svc_consolidated_record.py` (QC-team SOP: link in C, duplicates `Skip- duplicate` in the main table,
   resubmissions `EQC Ready Revision`), `tools/svc_submission_audit.py`, `tools/svc_consolidated_links.py`. This
   records the pass on the trackers. Nobody on the team sends a task to the TFRL QC team directly: Khiem builds
   the batches of 50 or more (`docs/qc-intake-process.md`).
6. **Freeze lists** - `tools/svc_build_freeze.py --push` rebuilds `do_not_touch.txt` from both trackers so lanes
   never work a task someone else owns or already submitted.

## EKW tasks on the same lanes (2026-09-25)

The pool takes SVC tasks first and, when no SVC task is claimable, claims from the EKW queue, so lanes never idle
while EKW work exists.

- Intake: `tools/ekw_pull_drive.py` pulls each claimed task's Drive folder read-only; `tools/ekw_intake.py`
  reshapes it (unzip, flatten, dedupe, verifier.json schema) into `/root/ekwqc/pipeline/data/ekw_qc/_raw/<TASK>`.
  A task missing a file only its author can supply (no verifier.json, no golden, or goldens placed in the inputs)
  parks at once with the reason.
- Runner: `ekw_v1_lane_runner.sh <TASK> <LANE>` (same exit codes as SVC). Lanes edit only `_raw/<TASK>`; every
  attempt rebuilds the package with `ekw_raw_to_rewardkit.py`, then runs the EKW checks (`tools/ekw_gate.py`
  over `ekw_run_checks.py`), the oracle, the adversarial verify, an oracle confirm and the prefilter, and writes
  `/root/qc/_ekw/ready/<TASK>.zip` with a manifest. Non-blocking checks are listed in
  `/root/qc/_ekw/advisory_checks.txt`; a decide round may waive a check finding only with a cited source record
  (`/root/qc/_ekw/waivers/<TASK>.json`). The stuck signature is the criteria named in the verify's closing
  VERDICT paragraph, not every id in its table.
- Queue and claims: `/root/qc/_ekw/` (queue.txt, claims/, ready/, parked.txt, decide.txt), claim helper
  `tools/ekw_v1_claim.sh`.
- Shipping: EKW READY zips go to DataOS only through `tools/ekw_bundle_upload.py bundle` + `check` (same
  stale-zip gate as SVC, plus a golden-in-inputs refusal). Never zip an EKW package by hand. Dataset tag `ekw`,
  pipeline "ManualQC automated QC pipeline 4 Reviewers" (version 8 on 2026-10-05; the earlier "NO CLAUDE" pipeline
  is retired). The per-task WARNING "missing metadata.benchmark_type" was benign under that earlier pipeline: no
  listed type fits EKW.
- Return intake: `tools/ekw_record_return.py <with_runs.zip>` then `--apply`. It reuses the SVC review parser and
  so has the same caution as step 4 above: a copy from before 2026-10-05 does not apply the any-major rule and does
  not read Answer Check replies. Passes go to
  `/root/qc/_ekw/accepted.txt`; rejects are fingerprinted, their ready zip archived, the claim released, requeued at the head, taken out of
  decide mode, and get `briefs/<TASK>.md` with every DataOS finding so far (also seeded as the task's NOT-READY
  verify record, which the runner reads as its first fix directive). Tests: `tools/test_ekw_record_return.py` (8).

## Layout and environment

- `tools/` - every tool the sandbox runs from `/root/qc/tools/`, plus the laptop-side SVC tools. Many older
  scripts (`patch_*`, `gate_*`, `v3digest_*`, `*_pilot.sh`) are superseded experiments kept so nothing the log or
  plan references is missing; the live path is the list above.
- `sandbox_root/` - scripts that live at `/root/qc/` (runner, pool, stop, older fleet drivers).
- Paths are the sandbox's: corpus `/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready/`, work dir `/root/qc/_v7/`,
  python `/root/venv/bin/python3` (harbor-rewardkit), pinned grader `/root/venv017/bin/python3`
  (rewardkit 0.1.7), lanes `/root/.claude-<letter>`. Adjust the variables at the top of each script to run
  elsewhere.
- `judge_emulate.py` imports its sibling `tools/judge_input_report.py` and `_qc_common.py`, and
  `deterministic-checks/tools/llm_backend.py` from this repo (set `DETCHECKS_DIR` if the repo sits elsewhere).
  `deterministic-checks/scans/judge_input_report.py` is the same module wired into the shared check registry.
- Google Sheets tools need `gcloud auth login --enable-gdrive-access`; no API keys are stored anywhere here.

## Tests

`python tools/test_svc_bundle_upload.py` (26 cases), `python tools/test_eval_counting.py`,
`python tools/test_svc_eval_regrade_gate.py` (9, the two gate bugs), `python tools/test_judge_emulate_error_scores.py`
(3, oracle error path), and on the sandbox `bash tools/test_svc_v7_runner_release.sh <runner>` (3),
`bash tools/test_svc_v7_pool_release.sh <pool>` and `bash tools/test_svc_v7_pool_ekw_fallback.sh <pool>` (2),
`bash tools/test_ekw_v1_runner.sh <runner> <claim helper>` (7), plus the per-tool `test_*.py` files.
