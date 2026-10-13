#!/usr/bin/env python3
"""Certification gate check: before a task is certified "ready", replay its completed judge
runs through the rubric's OWN release rules (must-pass gates, release threshold, open items)
and consult its gate-adjudication record for unresolved true-positive findings.

Why this exists. Two root causes from the 2026-09-14 SVC-PC/EKW QC synthesis
(`ekw/svc-oracle177-rootcause-phase0-synthesis-2026-09-14.md`, sections B.6, B.7 and C.9):

  1. Must-pass criteria do not gate the shipped score. Every SVC-PC judge.toml aggregates by a
     plain `weighted_mean`; "This is a must-pass criterion." is prose inside the description and
     nothing else. A real hard-gate function already exists in the converter repo,
     `evaluate_release_outcome` (`C:/ekwqc/repo/pipeline/tools/rubric_xlsx_to_verifier.py:1455`),
     and is never called outside its unit tests. It cannot be wired into live scoring: the real
     aggregation runs in an external, un-vendored `rewardkit/runner.py` on DataOS. What CAN be
     built is this: a post-hoc step that feeds a finished run's per-criterion pass/fail into that
     existing function and reports what the rubric's own rules say the outcome is. Ground truth
     it has to reproduce: SVC-PC-80-7-0 declares 16 must-pass criteria, both model runs failed
     several of them (a2/a4/a7/e3 and a2/a4/a5/a7/e3 in the two runs on this machine), and the
     platform still reported 0.7 and 0.6667. The reconciliation that certified the 56-task
     population never checked this, because it only ever looked at Oracle runs, where the golden
     passes every criterion by construction and the gate can never fire.
  2. The existing DataOS semantic gates (`rubric_hardcodes_undisclosed_specific_requirement` and
     five siblings) HAD already caught the defects manual QC later found on SVC-PC-93-0-0 (4 gates
     true_positive) and SVC-PC-92-0-0 (3 gates true_positive), and both were certified ready
     anyway: the adjudicated gate output (`<task_id>_qc_validation.xlsx`, one per task, on Drive)
     never left reviewers' machines and nobody consulted it at certification time. This is the
     PRIMARY mechanism here; must-pass replay is the secondary one.

What it does, per task directory under --root:

  a. Loads the rubric from the built package. SVC-PC: every `tests/deliverables/judge.toml` and
     `tests/deliverables_*/judge.toml` (both real layouts), one verifier per `[[criterion]]`,
     keyed `<group>/<name>` so a criterion name reused across groups cannot collide (a real
     SVC-PC defect class, see judge_criterion_name_duplicate_check.py). Must-pass is detected the
     only way SVC-PC exposes it, by the `must-pass` / `must pass` marker in the description text.
     EKW: `tests/verifier.json`, keyed by verifier name, must-pass from `metadata.must_pass`
     (native) or the same text marker in `assertion.rubric.prompt`, release threshold from
     `read_me_contract.release_policy.score_threshold_percent` when present.
  b. Finds every completed run for the task under each --run root: any
     `**/<task-dir>/verifier/reward-details.json`, which is the Harbor trial layout both the
     Oracle pulls (`batch_NNNN/<TASK-ID>/...`) and the DataOS model-run extracts
     (`batch_NNNN_<agent>_evals/<TASK-ID>/...`) use. Per criterion, `value >= 1.0` is a pass.
     Reported reward comes from `verifier/reward.json` ("reward") or `result.json`
     (`verifier_result.rewards.reward`). Run kind (oracle vs model) comes from an explicit
     `oracle:` / `model:` prefix on the --run value, else `result.json`'s `config.agent.name`
     (or `agent_info.name`) when that file exists, else `"unknown"` -- directory naming is
     never used to guess "oracle": SVC-PC's bare `batch_NNNN/<TASK-ID>/...` layout (both
     Oracle pulls and DataOS model-run extracts use it, no `result.json` present either way)
     gives a naming-only guess no real evidence to stand on, and oracle is the one kind that
     forces a task straight to BLOCKED (see `oracle_blocked` below), so a wrong guess there
     is a false certification failure. An `"unknown"`-kind run surfaces as its own open item,
     `run_kind_undetermined`, instead.
  c. Calls `evaluate_release_outcome(verifier, criterion_results)` for each run, with the
     package's verifier list and the run's pass/fail map, exactly as that function expects. The
     function is imported from the converter file (`--converter`, or `$RUBRIC_CONVERTER_PATH`,
     default `C:/ekwqc/repo/pipeline/tools/rubric_xlsx_to_verifier.py`). A verbatim replica
     lives in this file as a fallback and, when the import succeeds, is ALSO run on every call:
     any disagreement is reported as `engine_disagreement` and the task verdict becomes ERROR,
     so drift between the two copies can never pass silently (the vendored-copy-drift trap in
     the project CLAUDE.md).
  d. Looks the task up in the gate-adjudication records given by --gate-records (see "What is
     real and what is stubbed" below).
  e. Looks the task up in the deterministic-check registry output given by --checks-summary
     (`svc_run_checks.py`'s `summary.json` or `summary.csv`: one row per task, one column per
     check with a normalised pass/warn/fail/skip/error verdict, plus C/D/E roll-ups). Only `fail`
     and `error` verdicts are surfaced: `warn` is "a disclosure... never blocks on its own"
     and `skip` means "nothing to verify," per `svc_run_checks.py`'s own docstring. Same optional-
     input discipline as --gate-records: absence is itself disclosed as an open item
     (`checks_not_consulted`), never silently treated as clean. See "Design decision:
     checks-summary severity mapping" below for why `fail`/`error` are open items, not BLOCKED.

Verdict per task, first rule that matches:

  NO RUN                  no run output found for the task under any --run root. Not
                          certifiable on this evidence.
  ERROR                   package unparseable, or the imported engine and the replica disagree.
  BLOCKED                 the gate-adjudication record holds one or more `true_positive` rows
                          with a blank / unresolved Expert Verdict; OR an ORACLE run comes back
                          BLOCKED (the golden fails one of its own must-pass gates, or falls
                          below the release threshold).
  PASS WITH OPEN ITEMS    any of: a MODEL run comes back BLOCKED while the platform reported a
                          nonzero reward (`must_pass_not_enforced`, the 80-7-0 shape, with the
                          failed gate ids named); a MODEL run comes back BLOCKED while
                          `verifier/reward.json` is missing or unparseable so whether the
                          platform paid a reward can't be determined
                          (`must_pass_status_undetermined` -- never silently PASS just because
                          the reward file didn't load); a run's kind (oracle vs model) could
                          not be determined from `result.json` or an explicit --run prefix
                          (`run_kind_undetermined`); a run returns PASS WITH OPEN ITEMS (EKW
                          `claim_status == "Open item"`); the gate record holds only
                          `uncertain` / `partial` rows; no gate record exists for the task
                          (`gate_record_missing`: 3 of the 4 defective sample tasks were in no
                          record at all); --gate-records was not supplied at all
                          (`gate_records_not_consulted`, every task); --checks-summary was not
                          supplied at all (`checks_not_consulted`, every task); no checks-summary
                          entry exists for the task (`checks_record_missing`); the checks
                          registry returned `fail` verdicts on the task
                          (`checks_registry_fail`: real, deterministic findings about structural
                          defects in the task package, surfaced for human review, not BLOCKED --
                          see the design decision below); the checks registry returned `error`
                          verdicts (`checks_registry_error`: check limitation, not a content
                          defect, but no coverage from that check); a run's criteria do not
                          match the package's (`package_run_mismatch`: the run graded a
                          different build); a run carries `exception_info`.
  PASS                    everything above is clear.

  Informational, never verdict-changing unless --require-model-run: `gate_unexercised`, the
  task declares must-pass criteria but only Oracle runs were supplied, so the gate was never
  tested against a real submission. This is the exact blind spot the reconciliation had.

What is real and what is stubbed:

  REAL   The must-pass replay end to end, validated on real run output (see Validation).
  REAL   Gate-record consumption from a LOCAL export: a directory (recursive) or file of
         `*_qc_validation.xlsx` in the tp-fp-classification skill's schema (header row holds
         `... Task ID`, `Auto-Verdict`, `Expert Verdict (fill in)`; verdict vocabulary observed
         in the 104-file 2026-09-11 export: true_positive / false_positive / uncertain /
         partial; Expert Verdict blank on all 1,117 rows). Task id is read from the sheet's
         Task ID column first, the filename second. A `.json` manifest
         `{"SVC-PC-92-0-0": {"unresolved_true_positive": 3, "uncertain": 0, "source": "..."}}`
         or a `.csv` with `task_id, auto_verdict, expert_verdict[, ...]` rows is accepted too,
         so a hand-built record from the DataOS UI can be fed in before the Drive pull exists.
  REAL   Checks-summary consumption from `svc_run_checks.py`'s `summary.json` or `summary.csv`
         (one row per task, one column per check, normalised verdicts). Both the JSON shape
         (`results[].checks.{name}.verdict`) and the CSV shape (`<name>`, `<name>_n`,
         `<name>_first` columns) are parsed; a directory is searched for `summary.json` then
         `summary.csv`. Validated 2026-09-15 against the real 27-task output at
         `ekw/pipeline-mirror/results/round10-svc-checks-output/` (see the round 11 report
         `ekw/pipeline-mirror/results/round11-certification-gate-fix-2026-09-15.md`).
  STUB   The live Drive pull of `<task_id>_qc_validation.xlsx` is NOT wired. A background
         agent cannot complete a Drive read (permission prompt, see the global CLAUDE.md Drive
         section), so export the folder locally first (the `/drive` skill, or the Drive MCP
         connector) and point --gate-records at it. The 2026-09-11 export on this machine,
         `turing-context/ekw/qc-validation-2026-09-11/`, does not contain SVC-PC-92-0-0,
         SVC-PC-92-1-0, SVC-PC-88-0-0, SVC-PC-80-7-0 or SVC-PC-93-0-0; the 92-0-0 and 93-0-0
         gate hits the synthesis cites live in a newer Drive folder that has not been pulled.
  NOT    Raw, un-adjudicated `task_<id>_verifications_results.json` (DataOS's direct gate
         output) is not parsed: no sample of that file exists on this machine, so its shape
         could not be confirmed and is not guessed at. Add it once one is in hand.

Design decision: checks-summary severity mapping (2026-09-15, round 11).

  A `fail` verdict from `svc_run_checks.py`'s registry is a real, deterministic finding about a
  structural defect in the task PACKAGE (not a run). The question is whether it should push a
  task to BLOCKED (like an unresolved gate `true_positive`, which is a human-confirmed defect,
  or like an oracle run that fails its own must-pass gates, which is a structural replay of
  actual grading) or be surfaced as an open item (like `gate_findings_uncertain`,
  `run_open_items`, etc. -- informational but never silently dropped, consistent with this
  script's "PASS WITH OPEN ITEMS" design philosophy).

  The call: open item, not BLOCKED. Reasoning:

  1. Evidential strength. BLOCKED is reserved for the two strongest evidence classes this
     script handles: a human-confirmed unresolved defect (gate `true_positive` with blank
     Expert Verdict, where a classifier already said "real" and a human has not yet closed it)
     and a structural replay of actual grading (oracle fails its own must-pass gates, where
     the golden itself cannot pass the rubric's release rules). A check-registry `fail` is
     deterministic and inspects the real package, but it is neither human-confirmed nor a
     replay of actual grading. It is automated static analysis of the package's structure.
     Putting it in BLOCKED would conflate "a check found a structural pattern" with "a human
     confirmed a defect" and "the golden itself cannot pass."
  2. Known false-positive rates. Some checks in the registry have known limitations.
     `compound_criterion` has a confirmed recall regression from round 9 (its `fail` verdicts
     are still real -- the criteria ARE compound -- but it misses some compound criteria
     that round 9's fix swallows). `test_coverage_absence` returns `error` when it finds no
     sections to test, which is a check limitation, not a content finding. Treating these as
     BLOCKED would block certification on an automated finding that has not been
     human-confirmed and may have a known precision/recall caveat.
  3. The gap this closes. Round 10 batch 2 found that 0 of 15 "certified" tasks come back
     clean under the real 17-check registry, and 14 of 15 carry at least one hard fail or
     error. The gap is that detection exists but its output never reached whoever decided a
     task is "ready." Surfacing fail/error as open items closes that gap: a task with
     check-registry fails can no longer silently pass as PASS; it becomes PASS WITH OPEN
     ITEMS, which requires a human to read the open items before certifying. The human can
     block manually if the findings warrant it; if the findings are later human-confirmed,
     they go through the gate `true_positive` path and become BLOCKED. This is the same
     discipline the script already uses for `gate_findings_uncertain` (uncertain/partial rows
     are open items, not blockers, because the adjudication is not yet confirmed).

  The tradeoff: a task with check-registry fails CAN still be certified as PASS WITH OPEN
  ITEMS, which is weaker than BLOCKED. The counterargument: the human reviewer seeing the open
  item can choose to block, and the findings are now visible at certification time rather
  than invisible (the round 10 status quo). This is a defensible design decision, not the
  only possible one. The alternative (BLOCKED on any `fail`) would be stronger but would
  block certification on automated findings that have not been human-confirmed and may
  carry known precision/recall caveats, which is a higher false-positive cost than this
  script's existing BLOCKED triggers incur.

  What is NOT surfaced: `warn` and `skip` verdicts. Per `svc_run_checks.py`'s own docstring,
  `warn` is "a disclosure the checks themselves do not treat as a defect; it never blocks on
  its own." `skip` means "nothing to verify." Neither is a defect in the registry's own
  severity vocabulary, and surfacing them here would re-interpret that vocabulary, not
  respect it. This is confirmed against the real round-10 output: `judge_determinism_config_lint`
  returns `warn` (status `not_exposed`) on all 27 tasks (a universal SVC-PC blind spot, not a
  per-task defect), and `test_coverage_absence` returns `warn` on 14 of 27 (untested sections
  flagged for review, not blockers per the check's own docstring).

  Which checks count: every one of the 17 registered checks. No check fires `fail`
  universally (unlike `judge_determinism_config_lint` which fires `warn` universally), so
  gating on "any fail" is already targeted enough to avoid noise. The `compound_criterion`
  recall regression affects recall (missing some compound criteria), not precision (false
  fails), so its `fail` verdicts are still real defects even when it also misses some.

Validation (RAN, 2026-09-14; population = the 56-task SVC-PC reconciled set at
`C:/b/_stage_0914_reconciled56`; runs = 128 Oracle runs from `.scratch_oracle_pull_0914`
plus 74 model runs from `C:/b/_terminus_extract` (claude_opus_5 and gpt_5.6 batches); gate
records = the 104-file local export `turing-context/ekw/qc-validation-2026-09-11/`):

  Verdicts over the 56: 0 PASS, 47 PASS WITH OPEN ITEMS, 9 BLOCKED. Exit 1.
  9 BLOCKED (SVC-PC-12-6-0, 12-7-0, 2-4-0, 2-6-0, 2-7-0, 24-4-0, 24-6-0, 24-7-0, 3-8-0): each
  carries unresolved true_positive rows in the 09-11 export (1 to 30 rows per task, all
  content_substance or design_intent, Expert Verdict blank). Those records predate the
  09-12/13 fix passes on this population; `gate_record.last_run` carries the record date so
  the certifier can check whether the fix landed after the finding. The script cannot tell
  on its own: the record has no build hash.
  Oracle runs: 128 of 128 PASS. The golden passes every criterion by construction, so an
  Oracle-only certification can never see the must-pass defect. This null result is the
  reconciliation's blind spot, measured.
  Model runs: 36 of 74 BLOCKED by the rubric's own gates; 35 of those 36 carry a nonzero
  platform reward (`must_pass_not_enforced`, 22 tasks). The one exception reported 0.0, where
  platform and gate agree.
  SVC-PC-80-7-0 (the ground-truth instance): claude_opus_5 run reward 0.7, BLOCKED, failed
  gates a2/a4/a7/e3; gpt_5.6 run reward 0.6667, BLOCKED, failed gates a2/a4/a5/a7/e3. Task
  verdict PASS WITH OPEN ITEMS, not PASS. The manifest's relayed figures ("a2/a5/a7/e3/f2,
  0.65-0.67") describe DataOS runs that are not the two extracted here: f2 passes and a4
  fails in both local runs. The finding (must-pass failures under a nonzero reward)
  reproduces.
  SVC-PC-93-0-0: both model runs BLOCKED (r05/r14/r19/r23 and r02/r04/r05/r10/r14), rewards
  0.7482 and 0.2965; r05 and r14 are among the criteria manual QC named as unreachable.
  SVC-PC-92-1-0: both model runs BLOCKED (r02/r03 and r02/r03/r04/r09), rewards 0.84 and 0.6.
  SVC-PC-92-0-0: 0 must-pass criteria, both model runs PASS (0.85, 0.8). Only the gate-record
  mechanism can catch this task, and its record is not in the local export
  (`gate_record_missing`), which is exactly the certification failure the synthesis describes.
  SVC-PC-88-0-0: 15 of 19 criteria marked must-pass; NO model-run output on this machine
  (searched turing-context, C:/b, C:/ekwqc, Downloads). The "4 must-pass failed, 0.6628"
  finding was replayed as a SYNTHETIC run (str-04, obj-01, jdg-01, jdg-03 forced to 0.0,
  reward.json 0.6628) through the same CLI: BLOCKED, task PASS WITH OPEN ITEMS. A replay of
  the documented finding, not an independent observation.
  Synthetic gate manifest (92-0-0 with 3 unresolved true_positive, 93-0-0 with 4): both
  BLOCKED with the gate ids named. A csv row set whose true_positive row carries Expert
  Verdict "resolved" left 92-1-0 at PASS WITH OPEN ITEMS (its uncertain row only). An
  "svc-pc-10-l2-04" style id landed in `unmapped`, not on any task (39 such rows in the real
  export, 10 files named by level index rather than task id).

Exit 0 when every selected task is PASS, 1 when any task is not PASS, 2 on bad usage.
Stdlib only for the replay path (Python 3.11+ for tomllib); `openpyxl` only when an xlsx
gate-record export is given; `python-docx` + `openpyxl` only because the converter module
imports them at load time (the replica runs without either).

    python certification_gate_check.py --root <package_root> --all \\
        --run oracle:<oracle_pull_root> --run model:<model_run_root> \\
        --gate-records <local qc_validation export dir> \\
        --checks-summary <svc_run_checks.py out-dir or summary.json> --out report.json
    python certification_gate_check.py --root <package_root> SVC-PC-80-7-0 --run model:C:/b/_terminus_extract

Status: v2. Replay path RAN against the 56-task population (128 Oracle + 74 model runs).
Gate-record path RAN against the 104-file local export: schema confirmed, task-id mapping
confirmed, and the true_positive->BLOCKED rule fired on 9 real tasks. Checks-summary path
RAN, 2026-09-15 (round 11), against the real 27-task output at
`ekw/pipeline-mirror/results/round10-svc-checks-output/summary.json`: schema confirmed for
both JSON and CSV shapes, task-id mapping confirmed, and the checks_registry_fail /
checks_registry_error / checks_not_consulted open items fired correctly on real data (see
`ekw/pipeline-mirror/results/round11-certification-gate-fix-2026-09-15.md`). Regression-
checked: the 56-task population was not re-run here (the 09-14 run inputs are not all on
this machine), but the additive-only design (new open items, no change to BLOCKED/PASS logic)
means the only verdict changes are: PASS -> PASS WITH OPEN ITEMS when --checks-summary is
supplied and the task has real fail/error verdicts, and (corrected: an adversarial review
found the original wording here overclaimed "every verdict is identical to v1" when
--checks-summary is absent) PASS -> PASS WITH OPEN ITEMS via the new checks_not_consulted
open item when --checks-summary is NOT supplied and no other open item was already present
(same disclosed-absence pattern gate_records_not_consulted already uses; in every real
validation run here, --gate-records was also unsupplied, so gate_records_not_consulted
already forced PASS WITH OPEN ITEMS and this edge case never changed an actual verdict, but
it is a real behavior change in principle, not "identical to v1" in every configuration).
EKW (`verifier.json`)
path RAN, 2026-09-14, against real EKW harbor output at `C:/ekwqc/_harbor_ekw8/_jobs`
(6 Oracle + 66 terminus-2/MAI-Thinking-1 model trials across 6 of an original 8 tasks;
task_3 and task_53 have trial folders but no `reward-details.json` on this machine, correctly
NO RUN, not a script defect) against the 274-task package root `C:/ekwqc/_merged274/files`.
Two real EKW-only bugs were found and fixed by this run, both because EKW's `verifier.json`
shape does not match the `group/name` addressing the SVC-PC `judge.toml` path was built
around: (1) `discover_runs` could not resolve a task id for any EKW MODEL trial, because
EKW's harbor staging convention nests the real task under a fixed generic leaf directory
("<job>/ekw-0908-task_139/v1/harbor_task"), so `result.json`'s own `task_name` field is the
literal string "harbor_task" for every model trial, not the id -- every EKW model run was
silently attributed to a random trial-hash id that matched no task, so no EKW package task
could ever show a model run at all; fixed with a `PATH_TASK_ID_RE` fallback that searches the
trial's own task path for the "task_NNN" component. (2) `load_run_results` keyed EKW's
per-criterion pass/fail by each criterion's own semantic tag (`criteria[].name`, e.g.
"usable_quantity") instead of the enclosing group key, which is what verifier.json's
top-level verifier `name` field ("v1"...) actually equals and what the package side keys on
-- so no EKW criterion could ever match its package definition (`package_run_mismatch` on
every run, plus spurious `duplicate criterion key` errors when two verifiers reused the same
tag), and every recomputed weighted score silently came out 0.0 regardless of the platform's
own reported reward. Fixed to key on the group when a group holds exactly one criterion (the
shape confirmed on 72/72 real EKW trial files sampled this run); falls back to `group/name`
otherwise so a future multi-criterion group fails loud (unmatched key) rather than silently
overwriting. Fix (2) is verified exactly, not just absence-of-error: post-fix,
`recomputed_weighted_score` equals the platform's own `reported_reward` on every sampled EKW
run (e.g. 0.94/0.94, 0.09/0.09), where pre-fix it was always 0.0. SVC-PC regression-checked
after both fixes: the 56-task population reproduces the exact prior verdict counts (0 PASS,
47 PASS WITH OPEN ITEMS, 9 BLOCKED) -- both fixes are gated to the EKW `key_mode`/fallback
paths and do not touch SVC-PC's `group/name` path. Package parsing (not just the 8 with run
output) was also stress-tested against all 274 real EKW tasks including the `task_FIN-177`
and `task_lgl-*` alt-schema variants: 0 ERROR verdicts.

Two adversarial-verification bugs found and fixed 2026-09-15 (Session D, independent
verifier pass, both reported to the coordinator before either was fixed):
  (1) UNDER-FIRE. `score_contradiction` required `reported_reward > 0.0`, so a MODEL run that
      came back BLOCKED (failed a must-pass gate) with a missing or unparseable
      `verifier/reward.json` -- `reported_reward` resolves to `None` -- raised no open item at
      all: the "we don't know the reward" case silently collapsed into the same bucket as "no
      contradiction found." Proven RAN, not just read: SVC-PC-80-7-0's real claude_opus_5 run
      (reward 0.7, BLOCKED, failed gates a2/a4/a7/e3) copied into a scratch task dir with
      `verifier/reward.json` deleted, paired with a synthetic zero-defect gate record so no
      other open-item source could mask the effect -- pre-fix the task verdict printed plain
      `PASS`, with the BLOCKED run and its four failed gates visible only in the per-run detail
      line, nowhere in `open_items`. Fixed by adding `reward_missing_on_blocked` alongside
      `score_contradiction` and a new `must_pass_status_undetermined` open item in `judge_task`;
      same synthetic case post-fix: verdict `PASS WITH OPEN ITEMS`, open item names the four
      failed gates and says explicitly that whether the platform enforced the gate could not be
      determined.
  (2) OVER-FIRE. Run-kind auto-detection fell back to an `"oracle" in root.name.lower() or
      "oracle" in run_dir.parent.name.lower()` substring guess whenever a run's `result.json`
      carried no agent field -- exactly the shape of every SVC-PC DataOS evals.zip extract,
      oracle pulls and model-run extracts alike, both of which use the bare
      `batch_NNNN/<TASK-ID>/...` layout with no `result.json` at all. A real model run sitting
      under ANY path containing the word "oracle" (this file's own prior docstring example,
      `--run C:/b/_terminus_extract`, was itself unprefixed and safe only because
      `_terminus_extract` happens not to contain the substring) was silently promoted to
      "oracle," and oracle is the one kind that forces a task straight to BLOCKED via
      `oracle_blocked` regardless of the reported reward. Proven RAN: SVC-PC-80-7-0's real
      claude_opus_5 run copied into a scratch dir named
      `nightly_oracle_status_check/SVC-PC-80-7-0` (no `result.json`, run given unprefixed) --
      pre-fix the run was labeled `[oracle]` and the task verdict was `BLOCKED` purely from
      that filename; post-fix the run is labeled `[unknown]`, `oracle_blocked` cannot fire (it
      only ever checks `kind == "oracle"`), a new `run_kind_undetermined` open item names the
      run and says to rerun with an explicit `--run oracle:<path>` / `--run model:<path>`, and
      the real defect (must-pass gates failed under a nonzero reward) still surfaces correctly
      through `must_pass_not_enforced` -- task verdict `PASS WITH OPEN ITEMS`, an honest result
      instead of a false BLOCKED. The docstring's own example command above is now prefixed
      (`--run model:C:/b/_terminus_extract`).
  Both fixes regression-checked against real data, not just the two synthetic cases: the
  original `.scratch_oracle_pull_0914` (128 Oracle runs) no longer exists on this machine (it
  was disposable scratch), so the 56-task population was rerun with the real Oracle run data
  still present here instead (`C:/b/_inspect_2866`, `_inspect_2870`, `_inspect_2871`,
  `_inspect_2872_v2`, `_inspect_2873` -- all real Harbor trial output carrying `result.json`
  with `config.agent.name == "oracle"`) plus the same `C:/b/_terminus_extract` model runs and
  the same 09-11 gate-records export, run through the pre-fix and post-fix script back to
  back: 56/56 task verdicts identical (`BLOCKED=2, NO RUN=17, PASS WITH OPEN ITEMS=37`), zero
  `unknown`-kind runs, zero newly-fired open items -- neither fix changes anything on data that
  doesn't trigger the bug. SVC-PC-80-7-0 specifically reproduces the exact ground truth cited
  above (reward 0.7/0.6667, BLOCKED gates a2/a4/a7/e3 and a2/a4/a5/a7/e3, task PASS WITH OPEN
  ITEMS) unchanged. The EKW path was also spot-checked back to back (same 8-task
  `C:/ekwqc/_harbor_ekw8/_jobs` population as the 2026-09-14 EKW validation above): identical
  verdicts pre- and post-fix (`NO RUN=2, PASS WITH OPEN ITEMS=6`), because every real EKW
  harbor trial on this machine carries a populated `agent_info.name` and never reaches either
  fallback path.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.stderr.write("needs Python 3.11+ for tomllib\n")
    raise SystemExit(2)

DEFAULT_CONVERTER = Path(r"C:/ekwqc/repo/pipeline/tools/rubric_xlsx_to_verifier.py")

# The only way SVC-PC judge.toml exposes a gate: prose in the description. Covers the
# converter's own "This is a must-pass criterion." suffix, to_rewardkit's "[must-pass gate in
# the source rubric ...]" note, and "must pass" without the hyphen.
MUST_PASS_RE = re.compile(r"must[\s-]*pass", re.IGNORECASE)

# SVC-PC task ids as they appear in dir names, run dir names, sheet cells and filenames:
# "SVC-PC-80-7-0", "svc-pc-80-7-0", "svc_pc_65_0_0", "cirrus-y1-task-svc-pc-24-5-0-l2-05".
SVC_ID_RE = re.compile(r"svc[-_ ]?pc[-_ ](\d+)[-_](\d+)[-_](\d+)", re.IGNORECASE)
# EKW task dirs: task_142 / task-142.
EKW_ID_RE = re.compile(r"^task[-_](\d+)$", re.IGNORECASE)
# "svc-pc-10-l2-04" style names carry a level index, not a task id; they cannot be mapped
# without the sheet's own Task ID column and are reported as unmapped rather than guessed.
LEVEL_ID_RE = re.compile(r"svc[-_ ]?pc[-_ ](\d+)[-_ ]l(\d)[-_ ](\d+)", re.IGNORECASE)

# EKW real-run discovery, 2026-09-14 (validated against C:/ekwqc/_harbor_ekw8's real harbor
# job output, both oracle and terminus-2/MAI-Thinking-1 model trials): EKW's own harbor staging
# convention nests the actual task under a FIXED leaf directory name shared by every task
# ("<job>/ekw-0908-task_139/v1/harbor_task" -- the trial's task.path always ends in the literal
# "harbor_task"), so result.json's own "task_name" field is the generic leaf "harbor_task" for
# every model trial, not the real id; only oracle trials that were pointed straight at a
# "task_NNN" directory (no staging layer) happen to carry a useful task_name. Unanchored search
# for a task_NNN pattern in the trial's own task path is the fallback that survives this: it
# finds the id three directories up, where the leaf name is generic but an ancestor is not.
PATH_TASK_ID_RE = re.compile(r"task[-_](\d+)\b", re.IGNORECASE)

PASS_VALUE_EPS = 1e-6
RUN_WALK_MAX_DEPTH = 8

# An Expert Verdict that closes a true_positive row. Everything else (blank included) leaves
# the row unresolved. The 2026-09-11 export has Expert Verdict blank on every row, so today
# every true_positive row is unresolved by this rule; the vocabulary is here so a filled-in
# column is honoured the day one arrives.
RESOLVED_EXPERT_MARKERS = {
    "resolved",
    "fixed",
    "closed",
    "false_positive",
    "not_a_defect",
    "no_fix_needed",
    "wont_fix",
    "won't fix",
    "done",
}
OPEN_AUTO_VERDICTS = {"uncertain", "partial", "inconclusive"}


# --------------------------------------------------------------------------- engine


def _evaluate_release_outcome_replica(verifier: dict, criterion_results: dict) -> str:
    """Verbatim logic of rubric_xlsx_to_verifier.evaluate_release_outcome (2026-09-14 copy).
    Used as the fallback engine when the converter cannot be imported, and as a drift check
    against the imported one when it can."""
    policy = (verifier.get("read_me_contract") or {}).get("release_policy") or {}
    threshold = policy.get("score_threshold_percent")
    verifiers = verifier.get("verifiers") or []

    failed_gates = [
        v["name"]
        for v in verifiers
        if (v.get("metadata") or {}).get("must_pass")
        and not criterion_results.get(v["name"], False)
    ]
    if failed_gates:
        return "BLOCKED"

    total_weight = sum(
        (v.get("metadata") or {}).get("weight") or 0.0 for v in verifiers
    )
    earned_weight = sum(
        (v.get("metadata") or {}).get("weight") or 0.0
        for v in verifiers
        if criterion_results.get(v["name"], False)
    )
    score_percent = (earned_weight / total_weight * 100.0) if total_weight else 0.0
    if threshold is not None and score_percent < threshold:
        return "BLOCKED"

    open_items = [
        v["name"]
        for v in verifiers
        if (v.get("metadata") or {}).get("claim_status") == "Open item"
    ]
    return "PASS WITH OPEN ITEMS" if open_items else "PASS"


def load_release_engine(converter_path: Path):
    """Import evaluate_release_outcome from the converter file. Returns (fn, label, note).
    label is "imported" or "replica"; note explains a fallback."""
    if not converter_path.is_file():
        return (
            _evaluate_release_outcome_replica,
            "replica",
            f"converter not found at {converter_path}; using the in-file replica",
        )
    try:
        spec = importlib.util.spec_from_file_location(
            "_rubric_xlsx_to_verifier", converter_path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        fn = getattr(mod, "evaluate_release_outcome")
    except (
        Exception
    ) as exc:  # noqa: BLE001 - any import failure falls back, and is reported
        return (
            _evaluate_release_outcome_replica,
            "replica",
            f"import of {converter_path} failed ({type(exc).__name__}: {exc}); using the in-file replica",
        )
    return fn, "imported", f"evaluate_release_outcome imported from {converter_path}"


# --------------------------------------------------------------------------- ids


def normalize_task_id(raw: str) -> str | None:
    """Canonical id for matching across package dirs, run dirs, sheet cells and filenames.
    SVC-PC ids become SVC-PC-a-b-c; EKW task_N dirs become task_N; a level-style
    "svc-pc-10-l2-04" name returns None (not mappable without the sheet column)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    m = SVC_ID_RE.search(s)
    if m:
        return f"SVC-PC-{int(m.group(1))}-{int(m.group(2))}-{int(m.group(3))}"
    if LEVEL_ID_RE.search(s):
        return None
    m = EKW_ID_RE.match(s)
    if m:
        return f"task_{int(m.group(1))}"
    return s


# --------------------------------------------------------------------------- package


def _svc_judge_files(task_dir: Path) -> list[Path]:
    return sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def load_package(task_dir: Path, cli_threshold: float | None) -> dict:
    """The rubric as evaluate_release_outcome wants it, plus provenance. Returns
    {format, verifiers, read_me_contract, key_mode, parse_errors, must_pass_source}."""
    pkg = {
        "format": None,
        "verifiers": [],
        "read_me_contract": {
            "release_policy": {"score_threshold_percent": cli_threshold}
        },
        "key_mode": None,
        "parse_errors": [],
        "must_pass_source": None,
    }
    judge_files = _svc_judge_files(task_dir)
    if judge_files:
        pkg["format"] = "svc-pc"
        pkg["key_mode"] = "group/name"
        pkg["must_pass_source"] = (
            "description text marker (judge.toml has no must_pass field)"
        )
        for jf in judge_files:
            group = jf.parent.name
            try:
                data = tomllib.loads(jf.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                pkg["parse_errors"].append(f"{group}/judge.toml: {exc}")
                continue
            for c in data.get("criterion") or []:
                name = str(c.get("name") or "").strip()
                desc = str(c.get("description") or "")
                w = c.get("weight")
                pkg["verifiers"].append(
                    {
                        "name": f"{group}/{name}",
                        "group": group,
                        "criterion": name,
                        "metadata": {
                            "must_pass": bool(MUST_PASS_RE.search(desc)),
                            "weight": float(w) if isinstance(w, (int, float)) else 0.0,
                            "claim_status": None,
                        },
                        "description": desc.strip()[:160],
                    }
                )
        return pkg

    vj = task_dir / "tests" / "verifier.json"
    if vj.is_file():
        pkg["format"] = "ekw"
        pkg["key_mode"] = "name"
        pkg["must_pass_source"] = (
            "metadata.must_pass, or the text marker in assertion.rubric.prompt"
        )
        try:
            data = json.loads(vj.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            pkg["parse_errors"].append(f"tests/verifier.json: {exc}")
            return pkg
        rmc = data.get("read_me_contract")
        if isinstance(rmc, dict):
            native = (rmc.get("release_policy") or {}).get("score_threshold_percent")
            pkg["read_me_contract"] = {
                "release_policy": {
                    "score_threshold_percent": (
                        native if native is not None else cli_threshold
                    )
                }
            }
        verifiers = data.get("verifiers")
        if not isinstance(verifiers, list):
            pkg["parse_errors"].append("tests/verifier.json: 'verifiers' is not a list")
            return pkg
        for v in verifiers:
            if not isinstance(v, dict):
                pkg["parse_errors"].append(
                    "tests/verifier.json: non-object verifier entry"
                )
                continue
            name = str(v.get("name") or "").strip()
            md = v.get("metadata") if isinstance(v.get("metadata"), dict) else {}
            assertion = (
                v.get("assertion") if isinstance(v.get("assertion"), dict) else {}
            )
            rubric = (
                assertion.get("rubric")
                if isinstance(assertion.get("rubric"), dict)
                else {}
            )
            prompt = str(rubric.get("prompt") or v.get("criterion") or "")
            w = md.get("weight")
            pkg["verifiers"].append(
                {
                    "name": name,
                    "group": name,
                    "criterion": name,
                    "metadata": {
                        "must_pass": bool(md.get("must_pass"))
                        or bool(MUST_PASS_RE.search(prompt)),
                        "weight": float(w) if isinstance(w, (int, float)) else 0.0,
                        "claim_status": md.get("claim_status"),
                    },
                    "description": prompt.strip()[:160],
                }
            )
        return pkg

    pkg["parse_errors"].append(
        "no tests/deliverables*/judge.toml (SVC-PC) and no tests/verifier.json (EKW)"
    )
    return pkg


# --------------------------------------------------------------------------- runs


def _parse_run_spec(spec: str) -> tuple[str, Path]:
    """'oracle:C:/x' -> ('oracle', Path); 'model:C:/x' -> ('model', Path); 'C:/x' -> ('auto', Path).
    A bare Windows drive letter ('C:') is not a kind prefix."""
    for kind in ("oracle", "model"):
        if spec.lower().startswith(kind + ":"):
            return kind, Path(spec[len(kind) + 1 :])
    return "auto", Path(spec)


def discover_runs(run_specs: list[str]) -> tuple[list[dict], list[str]]:
    """Every <task-dir>/verifier/reward-details.json under each run root. Returns
    (runs, notes); each run is {label, root, kind, task_id, run_dir}."""
    runs: list[dict] = []
    notes: list[str] = []
    for spec in run_specs:
        kind_hint, root = _parse_run_spec(spec)
        if not root.is_dir():
            notes.append(f"run root not a directory, skipped: {root}")
            continue
        root_depth = len(root.parts)
        found = 0
        for rd in root.rglob("reward-details.json"):
            if rd.parent.name != "verifier":
                continue
            if len(rd.parts) - root_depth > RUN_WALK_MAX_DEPTH:
                continue
            run_dir = rd.parent.parent
            task_id = normalize_task_id(run_dir.name)
            result = _read_json(run_dir / "result.json")
            id_shaped = bool(
                SVC_ID_RE.search(run_dir.name) or EKW_ID_RE.match(run_dir.name)
            )
            if not id_shaped:
                # Not an id-shaped dir (e.g. a DataOS evals.zip trial folder named
                # "claude-code_..."); fall back to the trial's own result.json task_name
                # ("svc/svc-pc-15-3-0"). A dir that is neither id-shaped nor carries a
                # result.json keeps its raw name and can only match a package dir literally.
                tn = str((result or {}).get("task_name") or "")
                alt = normalize_task_id(tn.rsplit("/", 1)[-1]) if tn else None
                if alt and (SVC_ID_RE.search(alt) or EKW_ID_RE.match(alt)):
                    task_id = alt
                else:
                    # task_name didn't resolve either (EKW: it's the generic staging leaf
                    # "harbor_task" on every model trial, see PATH_TASK_ID_RE above). Search
                    # the trial's own task path for a task_NNN component instead of giving up
                    # and attributing the run to a random trial-hash id that matches no task.
                    for path_field in (
                        (((result or {}).get("config") or {}).get("task") or {}).get(
                            "path"
                        ),
                        ((result or {}).get("task_id") or {}).get("path"),
                    ):
                        if not path_field:
                            continue
                        m = PATH_TASK_ID_RE.search(str(path_field))
                        if m:
                            task_id = f"task_{int(m.group(1))}"
                            break
            if task_id is None:
                notes.append(f"cannot resolve a task id for run dir {run_dir}, skipped")
                continue
            kind = kind_hint
            if kind == "auto":
                agent = str(
                    ((result or {}).get("config") or {}).get("agent", {}).get("name")
                    or ""
                )
                if not agent:
                    agent = str(
                        ((result or {}).get("agent_info") or {}).get("name") or ""
                    )
                if agent:
                    kind = "oracle" if agent.lower() == "oracle" else "model"
                else:
                    # No real signal: this run's result.json is absent or carries no
                    # agent field -- the shape of a DataOS evals.zip extract (SVC-PC
                    # oracle pulls AND model-run extracts both use the same bare
                    # "batch_NNNN/<task-dir>/verifier/..." layout with no result.json at
                    # all). "oracle" as a substring of the run root or batch dir name
                    # used to stand in here and it is a pure naming coincidence, not
                    # data: a real model run sitting under any path that happens to
                    # contain the word "oracle" (a QA script's own directory name, a
                    # relocated extract, anything) got silently promoted to "oracle",
                    # and oracle kind is the ONE thing that forces a task straight to
                    # BLOCKED via oracle_blocked -- a false certification failure from a
                    # filename, not a defect. Fail toward not knowing rather than
                    # guessing oracle: "unknown" is surfaced as its own open item below
                    # (run_kind_undetermined) so a human sees it, and an explicit
                    # --run oracle:<path> / --run model:<path> is the only way to force
                    # a kind when no in-data signal exists.
                    kind = "unknown"
            try:
                label = str(run_dir.relative_to(root)).replace("\\", "/")
            except ValueError:
                label = str(run_dir)
            runs.append(
                {
                    "label": f"{root.name}/{label}",
                    "root": str(root),
                    "kind": kind,
                    "task_id": task_id,
                    "run_dir": run_dir,
                    "result": result,
                }
            )
            found += 1
        notes.append(f"{found} run(s) under {root} (kind hint: {kind_hint})")
    return runs, notes


def _read_json(p: Path):
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def load_run_results(run: dict, key_mode: str) -> dict:
    """Per-criterion pass/fail from verifier/reward-details.json, plus the platform's own
    reported reward. Keys match load_package's key_mode."""
    out = {
        "criterion_results": {},
        "criteria_seen": [],
        "groups": {},
        "reported_reward": None,
        "errors": [],
        "exception_info": None,
    }
    run_dir: Path = run["run_dir"]
    details = _read_json(run_dir / "verifier" / "reward-details.json")
    if not isinstance(details, dict):
        out["errors"].append("verifier/reward-details.json missing or unparseable")
        return out
    for group, g in details.items():
        if not isinstance(g, dict):
            continue
        out["groups"][group] = g.get("score")
        crit_list = [c for c in (g.get("criteria") or []) if isinstance(c, dict)]
        for c in crit_list:
            name = str(c.get("name") or "").strip()
            if key_mode == "group/name":
                key = f"{group}/{name}"
            elif len(crit_list) == 1:
                # EKW: the outer dict key here (`group`) is verifier.json's own top-level
                # "name" field ("v1"...) -- the same string load_package uses as the
                # package's verifier key. The criterion's OWN "name" inside the list is a
                # separate semantic tag ("usable_quantity") that verifier.json never exposes
                # at the top level, so keying on it here cannot match the package and instead
                # makes every criterion look missing (package_run_mismatch on every EKW run)
                # or collides across verifiers that reuse the same tag (duplicate criterion
                # key in run output). Confirmed 1 criterion per group on 72/72 real EKW trial
                # files (oracle + terminus-2/MAI-Thinking-1 model runs), 2026-09-14 -- see the
                # module docstring's EKW section. group/name below is the fallback if that
                # 1:1 shape is ever not true for some future task.
                key = group
            else:
                key = f"{group}/{name}"
            val = c.get("value")
            try:
                passed = val is not None and float(val) >= 1.0 - PASS_VALUE_EPS
            except (TypeError, ValueError):
                passed = False
            if key in out["criterion_results"]:
                # Same key twice in one run: pass only if every instance passed.
                out["criterion_results"][key] = out["criterion_results"][key] and passed
                out["errors"].append(f"duplicate criterion key in run output: {key}")
            else:
                out["criterion_results"][key] = passed
            out["criteria_seen"].append(key)
    reward = _read_json(run_dir / "verifier" / "reward.json")
    if isinstance(reward, dict) and isinstance(reward.get("reward"), (int, float)):
        out["reported_reward"] = float(reward["reward"])
    else:
        result = run.get("result") or {}
        rewards = (
            ((result.get("verifier_result") or {}).get("rewards") or {})
            if result
            else {}
        )
        if isinstance(rewards.get("reward"), (int, float)):
            out["reported_reward"] = float(rewards["reward"])
    result = run.get("result") or {}
    if result.get("exception_info"):
        out["exception_info"] = str(result["exception_info"])[:300]
    return out


# --------------------------------------------------------------------------- gate records


def _cell(v) -> str:
    return "" if v is None else str(v).strip()


def _find_col(headers: list[str], *needles: str) -> int | None:
    hl = [h.lower() for h in headers]
    for n in needles:
        for i, h in enumerate(hl):
            if n in h:
                return i
    return None


def _ingest_rows(
    store: dict, rows: list[dict], source: str, unmapped: list[dict]
) -> None:
    for r in rows:
        tid = normalize_task_id(r.get("task_id"))
        if tid is None:
            unmapped.append({"source": source, "raw_task_id": r.get("task_id")})
            continue
        rec = store.setdefault(
            tid,
            {
                "true_positive_total": 0,
                "unresolved_true_positive": 0,
                "uncertain": 0,
                "false_positive": 0,
                "rows": 0,
                "sources": [],
                "unresolved": [],
                "last_run": None,
            },
        )
        if source not in rec["sources"]:
            rec["sources"].append(source)
        rec["rows"] += 1
        # Newest "Last Run" date across the task's rows (ISO strings compare as dates). A
        # certifier needs this to tell a finding recorded before a fix landed from a current one:
        # the record carries no build hash, so the date is the only linkage there is.
        lr = _cell(r.get("last_run"))
        if lr and (rec["last_run"] is None or lr > rec["last_run"]):
            rec["last_run"] = lr
        auto = _cell(r.get("auto_verdict")).lower()
        expert = _cell(r.get("expert_verdict")).lower()
        if auto == "true_positive":
            rec["true_positive_total"] += 1
            if expert not in RESOLVED_EXPERT_MARKERS:
                rec["unresolved_true_positive"] += 1
                rec["unresolved"].append(
                    {
                        "defect_class": _cell(r.get("defect_class")),
                        "fix_title": _cell(r.get("fix_title"))[:120],
                        "issue": _cell(r.get("issue"))[:160],
                        "source_column": _cell(r.get("source")),
                    }
                )
        elif auto in OPEN_AUTO_VERDICTS:
            rec["uncertain"] += 1
        elif auto == "false_positive":
            rec["false_positive"] += 1


def _rows_from_xlsx(path: Path) -> tuple[list[dict], str | None]:
    try:
        import openpyxl  # noqa: WPS433 - optional dependency, only for xlsx exports
    except ModuleNotFoundError:
        return [], "openpyxl not installed; cannot read an xlsx gate-record export"
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return [], f"{path.name}: {exc}"
    ws = wb[wb.sheetnames[0]]
    rows_iter = ws.iter_rows(values_only=True)
    headers = None
    out: list[dict] = []
    fallback_id = normalize_task_id(path.name)
    for raw in rows_iter:
        if raw is None:
            continue
        cells = [_cell(v) for v in raw]
        if headers is None:
            if any(
                "auto-verdict" in c.lower() or "auto_verdict" in c.lower()
                for c in cells
            ):
                headers = cells
            continue
        if not any(cells):
            continue
        ci = {
            "task_id": _find_col(headers, "task id", "task_id"),
            "auto_verdict": _find_col(headers, "auto-verdict", "auto_verdict"),
            "expert_verdict": _find_col(headers, "expert verdict", "expert_verdict"),
            "defect_class": _find_col(headers, "defect class", "defect_class"),
            "fix_title": _find_col(headers, "fix title", "fix_title"),
            "issue": _find_col(headers, "issue description", "issue"),
            "source": _find_col(headers, "source"),
            "last_run": _find_col(headers, "last run", "last_run"),
        }
        row = {
            k: (cells[i] if i is not None and i < len(cells) else "")
            for k, i in ci.items()
        }
        if not row["task_id"] or normalize_task_id(row["task_id"]) is None:
            row["task_id"] = fallback_id or row["task_id"]
        out.append(row)
    if headers is None:
        return [], f"{path.name}: no header row with an Auto-Verdict column"
    return out, None


def _rows_from_csv(path: Path) -> tuple[list[dict], str | None]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = []
            for r in reader:
                norm = {
                    k.strip().lower().replace(" ", "_").replace("-", "_"): v
                    for k, v in r.items()
                    if k
                }
                rows.append(
                    {
                        "task_id": norm.get("task_id")
                        or norm.get("qc_issues_task_id")
                        or norm.get("task"),
                        "auto_verdict": norm.get("auto_verdict"),
                        "expert_verdict": norm.get("expert_verdict")
                        or norm.get("expert_verdict_(fill_in)"),
                        "defect_class": norm.get("defect_class"),
                        "fix_title": norm.get("fix_title"),
                        "issue": norm.get("issue_description") or norm.get("issue"),
                        "source": norm.get("source"),
                        "last_run": norm.get("last_run"),
                    }
                )
        return rows, None
    except Exception as exc:  # noqa: BLE001
        return [], f"{path.name}: {exc}"


def _ingest_json_manifest(store: dict, path: Path, unmapped: list[dict]) -> str | None:
    data = _read_json(path)
    if data is None:
        return f"{path.name}: unparseable JSON"
    if isinstance(data, list):
        _ingest_rows(store, data, path.name, unmapped)
        return None
    if isinstance(data, dict):
        for raw_id, v in data.items():
            tid = normalize_task_id(raw_id)
            if tid is None:
                unmapped.append({"source": path.name, "raw_task_id": raw_id})
                continue
            if not isinstance(v, dict):
                continue
            rec = store.setdefault(
                tid,
                {
                    "true_positive_total": 0,
                    "unresolved_true_positive": 0,
                    "uncertain": 0,
                    "false_positive": 0,
                    "rows": 0,
                    "sources": [],
                    "unresolved": [],
                    "last_run": None,
                },
            )
            if v.get("last_run"):
                rec["last_run"] = str(v["last_run"])
            src = f"{path.name}:{v.get('source', '')}".rstrip(":")
            if src not in rec["sources"]:
                rec["sources"].append(src)
            n_tp = int(v.get("unresolved_true_positive") or 0)
            rec["unresolved_true_positive"] += n_tp
            rec["true_positive_total"] += int(v.get("true_positive_total") or n_tp)
            rec["uncertain"] += int(v.get("uncertain") or 0)
            rec["rows"] += int(v.get("rows") or n_tp)
            for item in v.get("unresolved") or []:
                rec["unresolved"].append(
                    item if isinstance(item, dict) else {"issue": str(item)}
                )
        return None
    return f"{path.name}: JSON manifest must be an object keyed by task id or a list of rows"


def load_gate_records(paths: list[str]) -> dict:
    """Every gate-adjudication record reachable from the given paths. Returns
    {"by_task": {TASK_ID: rec}, "files": n, "errors": [...], "unmapped": [...]}."""
    store: dict = {}
    errors: list[str] = []
    unmapped: list[dict] = []
    n_files = 0
    for p in paths:
        base = Path(p)
        if base.is_dir():
            candidates = sorted(
                list(base.rglob("*.xlsx"))
                + list(base.rglob("*.json"))
                + list(base.rglob("*.csv"))
            )
        elif base.is_file():
            candidates = [base]
        else:
            errors.append(f"gate-records path not found: {base}")
            continue
        for f in candidates:
            if f.name.startswith("~$"):
                continue
            n_files += 1
            if f.suffix.lower() == ".xlsx":
                rows, err = _rows_from_xlsx(f)
                if err:
                    errors.append(err)
                _ingest_rows(store, rows, f.name, unmapped)
            elif f.suffix.lower() == ".csv":
                rows, err = _rows_from_csv(f)
                if err:
                    errors.append(err)
                _ingest_rows(store, rows, f.name, unmapped)
            elif f.suffix.lower() == ".json":
                err = _ingest_json_manifest(store, f, unmapped)
                if err:
                    errors.append(err)
    return {"by_task": store, "files": n_files, "errors": errors, "unmapped": unmapped}


# --------------------------------------------------------------------------- checks summary


def _checks_summary_from_json(path: Path) -> tuple[dict, str | None]:
    """Parse summary.json from svc_run_checks.py. One row per task, one entry per
    check with a normalised verdict (pass/warn/fail/skip/error). Only fail and error
    verdicts are extracted: warn and skip are not defects per svc_run_checks.py's own
    severity vocabulary (warn = 'a disclosure... never blocks on its own')."""
    data = _read_json(path)
    if data is None:
        return {}, f"{path.name}: unparseable JSON"
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("results", [])
    else:
        return {}, f"{path.name}: JSON must be a list or an object with a 'results' list"
    by_task: dict = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        tid = normalize_task_id(row.get("task_id"))
        if tid is None:
            continue
        checks = row.get("checks", {})
        if not isinstance(checks, dict):
            continue
        fails: list[dict] = []
        errors: list[dict] = []
        for name, cell in checks.items():
            if not isinstance(cell, dict):
                continue
            v = str(cell.get("verdict") or "")
            entry = {
                "check": name,
                "n_findings": int(cell.get("n_findings") or 0),
                "first": str(cell.get("first") or "")[:120],
            }
            if v == "fail":
                fails.append(entry)
            elif v == "error":
                errors.append(entry)
        by_task[tid] = {"fails": fails, "errors": errors}
    return by_task, None


def _checks_summary_from_csv(path: Path) -> tuple[dict, str | None]:
    """Parse summary.csv from svc_run_checks.py. Columns: task_id, C, D, E, then for
    each check: <name> (verdict), <name>_n (count), <name>_first (first finding text).
    Same extraction as the JSON parser: only fail and error verdicts are kept."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            headers = reader.fieldnames or []
            # Check columns are the ones that are NOT task_id/C/D/E and do NOT end
            # in _n or _first -- those are the count/first-text companions.
            check_names = [
                h
                for h in headers
                if h
                and h not in ("task_id", "C", "D", "E")
                and not h.endswith("_n")
                and not h.endswith("_first")
            ]
            by_task: dict = {}
            for row in reader:
                tid = normalize_task_id(row.get("task_id"))
                if tid is None:
                    continue
                fails: list[dict] = []
                errors: list[dict] = []
                for name in check_names:
                    verdict = (row.get(name) or "").strip()
                    n_str = (row.get(f"{name}_n") or "").strip()
                    first = (row.get(f"{name}_first") or "").strip()[:120]
                    try:
                        n_findings = int(n_str) if n_str else 0
                    except ValueError:
                        n_findings = 0
                    entry = {
                        "check": name,
                        "n_findings": n_findings,
                        "first": first,
                    }
                    if verdict == "fail":
                        fails.append(entry)
                    elif verdict == "error":
                        errors.append(entry)
                by_task[tid] = {"fails": fails, "errors": errors}
            return by_task, None
    except Exception as exc:  # noqa: BLE001
        return {}, f"{path.name}: {exc}"


def load_checks_summary(paths: list[str]) -> dict:
    """Every svc_run_checks.py summary reachable from the given paths. Accepts a
    directory (searched for summary.json then summary.csv) or a direct file (.json
    or .csv). Returns {"by_task": {TASK_ID: {"fails": [...], "errors": [...]}},
    "files": n, "errors": [...], "n_tasks": n}.

    Only fail and error verdicts are surfaced: warn ('a disclosure, never blocks on
    its own' per svc_run_checks.py's own docstring) and skip ('nothing to verify')
    are not defects and are intentionally excluded. This matches the registry's
    own severity vocabulary, not a re-interpretation of it.
    """
    store: dict = {}
    errors: list[str] = []
    n_files = 0
    for p in paths:
        base = Path(p)
        if base.is_dir():
            json_hits = sorted(base.glob("summary.json"))
            candidates = json_hits if json_hits else sorted(base.glob("summary.csv"))
        elif base.is_file():
            candidates = [base]
        else:
            errors.append(f"checks-summary path not found: {base}")
            continue
        for f in candidates:
            if f.name.startswith("~$"):
                continue
            n_files += 1
            if f.suffix.lower() == ".json":
                by_task, err = _checks_summary_from_json(f)
            elif f.suffix.lower() == ".csv":
                by_task, err = _checks_summary_from_csv(f)
            else:
                continue
            if err:
                errors.append(err)
            for tid, rec in by_task.items():
                existing = store.setdefault(tid, {"fails": [], "errors": []})
                existing["fails"].extend(rec["fails"])
                existing["errors"].extend(rec["errors"])
    return {
        "by_task": store,
        "files": n_files,
        "errors": errors,
        "n_tasks": len(store),
    }


# --------------------------------------------------------------------------- evaluation


def evaluate_run(pkg: dict, run: dict, engine, engine_label: str) -> dict:
    res = load_run_results(run, pkg["key_mode"])
    verifier = {
        "verifiers": pkg["verifiers"],
        "read_me_contract": pkg["read_me_contract"],
    }
    cr = res["criterion_results"]
    outcome = engine(verifier, cr)
    replica = _evaluate_release_outcome_replica(verifier, cr)
    pkg_keys = [v["name"] for v in pkg["verifiers"]]
    pkg_set = set(pkg_keys)
    run_set = set(res["criteria_seen"])
    must_pass = [v["name"] for v in pkg["verifiers"] if v["metadata"]["must_pass"]]
    failed_gates = [k for k in must_pass if not cr.get(k, False)]
    failed_gates_absent = [k for k in failed_gates if k not in run_set]
    total_w = sum(v["metadata"]["weight"] for v in pkg["verifiers"])
    earned_w = sum(
        v["metadata"]["weight"] for v in pkg["verifiers"] if cr.get(v["name"], False)
    )
    weighted = (earned_w / total_w) if total_w else 0.0
    failed_all = [k for k in pkg_keys if not cr.get(k, False)]
    rec = {
        "label": run["label"],
        "kind": run["kind"],
        "run_dir": str(run["run_dir"]),
        "outcome": outcome,
        "engine": engine_label,
        "engine_disagreement": outcome != replica,
        "replica_outcome": replica,
        "reported_reward": res["reported_reward"],
        "recomputed_weighted_score": round(weighted, 4),
        "gate_implied_reward": 0.0 if outcome == "BLOCKED" else round(weighted, 4),
        "score_contradiction": bool(
            outcome == "BLOCKED"
            and res["reported_reward"] is not None
            and res["reported_reward"] > 0.0
        ),
        # BLOCKED by the rubric's own gates, but verifier/reward.json is missing or
        # unparseable so reported_reward is None: a different failure mode than
        # score_contradiction (where we KNOW the platform paid a nonzero reward despite
        # the failed gate) and different again from a clean pass. Collapsing this into
        # score_contradiction (which requires reported_reward > 0.0) is exactly the
        # under-fire bug: a missing/corrupted reward.json made a BLOCKED run silently
        # invisible to judge_task, because it was the only signal that turns a failed
        # must-pass model run into an open item. Never treat "we don't know the reward"
        # as "no contradiction" -- surface it as its own explicit, honest state instead.
        "reward_missing_on_blocked": bool(
            outcome == "BLOCKED" and res["reported_reward"] is None
        ),
        "n_criteria_package": len(pkg_keys),
        "n_criteria_run": len(run_set),
        "n_must_pass": len(must_pass),
        "failed_gates": failed_gates,
        "failed_gates_absent_from_run": failed_gates_absent,
        "failed_criteria": failed_all,
        "missing_in_run": sorted(pkg_set - run_set),
        "extra_in_run": sorted(run_set - pkg_set),
        "group_scores": res["groups"],
        "exception_info": res["exception_info"],
        "errors": res["errors"],
    }
    return rec


def judge_task(
    task_id: str,
    pkg: dict,
    run_recs: list[dict],
    gate: dict | None,
    gate_records_supplied: bool,
    require_model_run: bool,
    checks: dict | None = None,
    checks_summary_supplied: bool = False,
) -> dict:
    reasons: list[str] = []
    open_items: list[str] = []
    info: list[str] = []
    must_pass_n = sum(1 for v in pkg["verifiers"] if v["metadata"]["must_pass"])

    if pkg["parse_errors"] and not pkg["verifiers"]:
        verdict = "ERROR"
        reasons.extend(f"package: {e}" for e in pkg["parse_errors"])
        return _task_record(
            task_id,
            pkg,
            run_recs,
            gate,
            verdict,
            reasons,
            open_items,
            info,
            must_pass_n,
            checks,
        )
    if not run_recs:
        verdict = "NO RUN"
        reasons.append("no run output found for this task under any --run root")
        return _task_record(
            task_id,
            pkg,
            run_recs,
            gate,
            verdict,
            reasons,
            open_items,
            info,
            must_pass_n,
            checks,
        )
    if any(r["engine_disagreement"] for r in run_recs):
        verdict = "ERROR"
        reasons.append(
            "engine_disagreement: imported evaluate_release_outcome and the in-file replica differ"
        )
        return _task_record(
            task_id,
            pkg,
            run_recs,
            gate,
            verdict,
            reasons,
            open_items,
            info,
            must_pass_n,
            checks,
        )

    blocked = False
    # Primary mechanism: unresolved true_positive gate findings.
    if gate is not None and gate["unresolved_true_positive"] > 0:
        blocked = True
        titles = "; ".join(
            (u.get("fix_title") or u.get("issue") or "?")
            for u in gate["unresolved"][:4]
        )
        when = (
            f", record last run {str(gate['last_run'])[:10]}"
            if gate.get("last_run")
            else ""
        )
        reasons.append(
            f"gate_findings_unresolved: {gate['unresolved_true_positive']} true_positive row(s) "
            f"with no resolving Expert Verdict in {', '.join(gate['sources'])}{when} [{titles}]"
        )
    # Secondary mechanism: the rubric's own release rules on the golden.
    for r in run_recs:
        if r["kind"] == "oracle" and r["outcome"] == "BLOCKED":
            blocked = True
            why = (
                f"failed must-pass gate(s) {r['failed_gates']}"
                if r["failed_gates"]
                else f"weighted score {r['recomputed_weighted_score']} below release threshold"
            )
            reasons.append(f"oracle_blocked: {r['label']} {why}")
    if blocked:
        verdict = "BLOCKED"
    else:
        verdict = "PASS"

    # Open items (only lower a PASS; BLOCKED stays BLOCKED but still lists them).
    for r in run_recs:
        if r["kind"] != "oracle" and r["score_contradiction"]:
            open_items.append(
                f"must_pass_not_enforced: {r['label']} failed gate(s) {r['failed_gates']} "
                f"yet platform reported {r['reported_reward']} (gate-implied 0.0)"
            )
        if r["kind"] != "oracle" and r["reward_missing_on_blocked"]:
            open_items.append(
                f"must_pass_status_undetermined: {r['label']} failed gate(s) {r['failed_gates']} "
                f"but verifier/reward.json is missing or unparseable, so whether the platform "
                f"paid a reward despite the failed gate(s) cannot be determined -- this is not "
                f"evidence of a clean pass, flag for review"
            )
        if r["outcome"] == "PASS WITH OPEN ITEMS":
            open_items.append(
                f"run_open_items: {r['label']} has criteria with claim_status 'Open item'"
            )
        if r["extra_in_run"] or (r["missing_in_run"] and r["n_criteria_run"] > 0):
            open_items.append(
                f"package_run_mismatch: {r['label']} extra={r['extra_in_run'][:5]} "
                f"missing={r['missing_in_run'][:5]} (run graded a different build?)"
            )
        if r["exception_info"]:
            open_items.append(
                f"run_exception: {r['label']} {r['exception_info'][:100]}"
            )
        if r["n_criteria_run"] == 0:
            open_items.append(
                f"run_empty: {r['label']} has no criteria in reward-details.json"
            )
    if not gate_records_supplied:
        open_items.append("gate_records_not_consulted: --gate-records not supplied")
    elif gate is None:
        open_items.append(
            "gate_record_missing: no gate-adjudication record found for this task"
        )
    elif gate["uncertain"] > 0 and gate["unresolved_true_positive"] == 0:
        open_items.append(
            f"gate_findings_uncertain: {gate['uncertain']} uncertain/partial row(s)"
        )

    # Checks-summary open items (same disclosure discipline as gate-records above).
    # A fail verdict from the registry is a deterministic, automated finding about a
    # structural defect in the task PACKAGE, not a human-confirmed defect (gate
    # true_positive) or a structural replay of actual grading (must-pass replay). It
    # is surfaced as an open item, not BLOCKED: BLOCKED is reserved for human-confirmed
    # unresolved defects and golden-fails-its-own-gates. An error verdict is a check
    # limitation (the check could not run), not a content defect, but the certifier
    # has no coverage from that check and must be told so. warn and skip are not
    # defects per svc_run_checks.py's own severity vocabulary and are never surfaced.
    if not checks_summary_supplied:
        open_items.append("checks_not_consulted: --checks-summary not supplied")
    elif checks is None:
        open_items.append(
            "checks_record_missing: no svc_run_checks.py summary entry found for this task"
        )
    else:
        fails = checks.get("fails", [])
        errors = checks.get("errors", [])
        if fails:
            fail_descs = []
            for f in fails[:6]:
                first = (f.get("first") or "")[:80]
                fail_descs.append(
                    f"{f['check']} ({f['n_findings']} finding(s)"
                    + (f": {first}" if first else "")
                    + ")"
                )
            more = f", +{len(fails) - 6} more" if len(fails) > 6 else ""
            open_items.append(
                f"checks_registry_fail: {len(fails)} check(s) with fail verdicts "
                f"from svc_run_checks.py: {', '.join(fail_descs)}{more}"
            )
        if errors:
            error_descs = []
            for e in errors[:4]:
                first = (e.get("first") or "")[:80]
                error_descs.append(
                    f"{e['check']} ({e['n_findings']} finding(s)"
                    + (f": {first}" if first else ": check limitation, no findings")
                    + ")"
                )
            more = f", +{len(errors) - 4} more" if len(errors) > 4 else ""
            open_items.append(
                f"checks_registry_error: {len(errors)} check(s) with error verdicts "
                f"from svc_run_checks.py (check limitation, not a content defect, but "
                f"no coverage from these checks): {', '.join(error_descs)}{more}"
            )

    if pkg["parse_errors"]:
        open_items.extend(f"package_partial_parse: {e}" for e in pkg["parse_errors"])

    for r in run_recs:
        if r["kind"] == "unknown":
            open_items.append(
                f"run_kind_undetermined: {r['label']} has no agent name in result.json "
                f"and no oracle:/model: prefix on --run; treated as non-oracle for gate "
                f"checks (never auto-classified as oracle). Rerun with an explicit "
                f"--run oracle:<path> or --run model:<path> to resolve this."
            )

    if must_pass_n and not any(r["kind"] != "oracle" for r in run_recs):
        msg = f"gate_unexercised: {must_pass_n} must-pass criteria declared, only oracle runs supplied"
        if require_model_run:
            open_items.append(msg)
        else:
            info.append(msg)

    if verdict == "PASS" and open_items:
        verdict = "PASS WITH OPEN ITEMS"
    return _task_record(
        task_id, pkg, run_recs, gate, verdict, reasons, open_items, info, must_pass_n,
        checks,
    )


def _task_record(
    task_id, pkg, run_recs, gate, verdict, reasons, open_items, info, must_pass_n,
    checks=None,
) -> dict:
    return {
        "task": task_id,
        "verdict": verdict,
        "format": pkg["format"],
        "n_criteria": len(pkg["verifiers"]),
        "n_must_pass": must_pass_n,
        "must_pass_source": pkg["must_pass_source"],
        "release_threshold_percent": pkg["read_me_contract"]["release_policy"][
            "score_threshold_percent"
        ],
        "n_runs": len(run_recs),
        "n_oracle_runs": sum(1 for r in run_recs if r["kind"] == "oracle"),
        "n_model_runs": sum(1 for r in run_recs if r["kind"] != "oracle"),
        "n_unknown_runs": sum(1 for r in run_recs if r["kind"] == "unknown"),
        "reasons": reasons,
        "open_items": open_items,
        "info": info,
        "gate_record": gate,
        "checks_summary": checks,
        "runs": run_recs,
        "package_parse_errors": pkg["parse_errors"],
    }


# --------------------------------------------------------------------------- main


HOW_TO_READ = {
    "verdict": {
        "PASS": "no unresolved gate findings, golden passes its own gates, every run agrees with the rubric's release rules, gate record consulted",
        "PASS WITH OPEN ITEMS": "certifiable only after a human reads open_items; includes the 80-7-0 shape (a model run failed must-pass gates yet the platform paid a nonzero reward) and a missing or unconsulted gate record",
        "BLOCKED": "an unresolved true_positive gate finding, or the golden itself fails a must-pass gate / release threshold",
        "NO RUN": "no reward-details.json found for the task; not certifiable on this evidence",
        "ERROR": "package unparseable, or the imported engine and the in-file replica disagree",
    },
    "runs[].outcome": "evaluate_release_outcome's verdict for that run: BLOCKED / PASS / PASS WITH OPEN ITEMS",
    "runs[].reported_reward": "what the platform wrote in verifier/reward.json (weighted_mean, no gating)",
    "runs[].gate_implied_reward": "what the rubric's own release rules imply: 0.0 when BLOCKED, else the weighted score",
    "runs[].score_contradiction": "BLOCKED by the rubric's gates but the platform reported > 0",
    "runs[].reward_missing_on_blocked": "BLOCKED by the rubric's gates but verifier/reward.json is missing or unparseable, so whether the platform reported > 0 cannot be determined -- a different, honest 'unknown' state, never collapsed into a pass",
    "runs[].kind": "oracle / model / unknown; unknown means result.json had no agent name and --run carried no oracle:/model: prefix -- never auto-classified as oracle, see run_kind_undetermined",
    "info": "informational only; gate_unexercised means only Oracle runs were available so the must-pass gate was never tested against a real submission",
    "gate_record": "the task's rows from the local qc_validation export (or manifest); null when no record was found; last_run is the newest 'Last Run' date on its rows, the only way to tell a finding that predates a fix from a current one (the record carries no build hash)",
    "checks_summary": "the task's fail/error verdicts from svc_run_checks.py's summary.json/csv (one row per task, one column per check); null when no entry was found; only fail and error verdicts are surfaced, warn/skip are not defects per the registry's own severity vocabulary",
    "stubbed": "live Drive pull of qc_validation.xlsx is not wired; raw verifications_results.json is not parsed",
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("task_ids", nargs="*", help="task ids to check (default: --all)")
    ap.add_argument(
        "--all", action="store_true", help="every task directory under --root"
    )
    ap.add_argument(
        "--root",
        required=True,
        help="package root: one task directory per task (or a single task directory)",
    )
    ap.add_argument(
        "--run",
        action="append",
        default=[],
        help="a run root holding <task>/verifier/reward-details.json at any depth; repeatable; "
        "prefix 'oracle:' or 'model:' to force the run kind",
    )
    ap.add_argument(
        "--gate-records",
        action="append",
        default=[],
        help="local export of gate-adjudication records: a dir or file of *_qc_validation.xlsx, "
        "a .json manifest, or a .csv; repeatable. Not supplied: every task gets the "
        "gate_records_not_consulted open item",
    )
    ap.add_argument(
        "--checks-summary",
        action="append",
        default=[],
        help="svc_run_checks.py output (summary.json or summary.csv): one row per task, "
        "one column per check with a normalised verdict (pass/warn/fail/skip/error). "
        "A directory (searched for summary.json then summary.csv) or a direct file; "
        "repeatable. Only fail and error verdicts are surfaced (warn/skip are not "
        "defects per the registry's own severity vocabulary). Not supplied: every "
        "task gets the checks_not_consulted open item",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="release threshold percent for packages with no read_me_contract (SVC-PC has none)",
    )
    ap.add_argument(
        "--converter",
        default=os.environ.get("RUBRIC_CONVERTER_PATH", str(DEFAULT_CONVERTER)),
        help="path to rubric_xlsx_to_verifier.py (default: %(default)s)",
    )
    ap.add_argument(
        "--require-model-run",
        action="store_true",
        help="promote gate_unexercised (must-pass declared, only oracle runs) to an open item",
    )
    ap.add_argument("--out", help="write the full JSON report here")
    ap.add_argument(
        "--quiet", action="store_true", help="one line per task, no detail lines"
    )
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2
    if not args.all and not args.task_ids:
        sys.stderr.write("give task ids or --all\n")
        return 2
    if not args.run:
        sys.stderr.write("give at least one --run root\n")
        return 2

    if (root / "tests").is_dir():
        task_dirs = [root]
    else:
        task_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.task_ids:
        want = {normalize_task_id(t) or t for t in args.task_ids}
        task_dirs = [
            d for d in task_dirs if (normalize_task_id(d.name) or d.name) in want
        ]
    if not task_dirs:
        sys.stderr.write(f"no task directories matched under {root}\n")
        return 2

    engine, engine_label, engine_note = load_release_engine(Path(args.converter))
    runs, run_notes = discover_runs(args.run)
    runs_by_task: dict[str, list[dict]] = {}
    for r in runs:
        runs_by_task.setdefault(r["task_id"], []).append(r)

    gate_supplied = bool(args.gate_records)
    gate = (
        load_gate_records(args.gate_records)
        if gate_supplied
        else {"by_task": {}, "files": 0, "errors": [], "unmapped": []}
    )

    checks_supplied = bool(args.checks_summary)
    checks = (
        load_checks_summary(args.checks_summary)
        if checks_supplied
        else {"by_task": {}, "files": 0, "errors": [], "n_tasks": 0}
    )

    results = []
    for d in task_dirs:
        tid = normalize_task_id(d.name) or d.name
        pkg = load_package(d, args.threshold)
        recs = [
            evaluate_run(pkg, r, engine, engine_label)
            for r in runs_by_task.get(tid, [])
        ]
        results.append(
            judge_task(
                tid,
                pkg,
                recs,
                gate["by_task"].get(tid),
                gate_supplied,
                args.require_model_run,
                checks["by_task"].get(tid),
                checks_supplied,
            )
        )

    # ---- print
    print(f"engine: {engine_note}")
    for n in run_notes:
        print(f"runs: {n}")
    if gate_supplied:
        print(
            f"gate records: {gate['files']} file(s), {len(gate['by_task'])} task(s) with rows, "
            f"{len(gate['unmapped'])} unmapped row(s), {len(gate['errors'])} error(s)"
        )
        for e in gate["errors"][:10]:
            print(f"  gate-record error: {e}")
    else:
        print(
            "gate records: NOT SUPPLIED (every task carries gate_records_not_consulted)"
        )
    if checks_supplied:
        print(
            f"checks summary: {checks['files']} file(s), {checks['n_tasks']} task(s) with entries, "
            f"{len(checks['errors'])} error(s)"
        )
        for e in checks["errors"][:10]:
            print(f"  checks-summary error: {e}")
    else:
        print(
            "checks summary: NOT SUPPLIED (every task carries checks_not_consulted)"
        )
    print()
    width = max(len(r["task"]) for r in results)
    for r in results:
        gate_str = "-"
        if r["gate_record"] is not None:
            g = r["gate_record"]
            gate_str = f"tp={g['unresolved_true_positive']}/{g['true_positive_total']}"
            if g.get("last_run"):
                gate_str += f"@{str(g['last_run'])[:10]}"
        unknown_str = f", unknown {r['n_unknown_runs']}" if r["n_unknown_runs"] else ""
        print(
            f"{r['verdict']:<21} {r['task']:<{width}}  crit={r['n_criteria']:>3} must-pass={r['n_must_pass']:>2}  "
            f"runs={r['n_runs']} (oracle {r['n_oracle_runs']}, model {r['n_model_runs']}{unknown_str})  gate:{gate_str}"
        )
        if args.quiet:
            continue
        for x in r["reasons"]:
            print(f"    BLOCK  {x}")
        for x in r["open_items"]:
            print(f"    OPEN   {x}")
        for x in r["info"]:
            print(f"    info   {x}")
        for run in r["runs"]:
            if run["outcome"] != "PASS" or run["errors"]:
                print(
                    f"    run    {run['label']} [{run['kind']}] {run['outcome']} "
                    f"reported={run['reported_reward']} gate_implied={run['gate_implied_reward']} "
                    f"failed_gates={run['failed_gates']}"
                )
                for e in run["errors"][:3]:
                    print(f"           {e}")

    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print()
    print(
        "summary: "
        + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        + f"  (of {len(results)})"
    )

    if args.out:
        report = {
            "how_to_read_this_report": HOW_TO_READ,
            "engine": engine_note,
            "run_notes": run_notes,
            "gate_records": {
                "supplied": gate_supplied,
                "files": gate["files"],
                "tasks_with_rows": len(gate["by_task"]),
                "errors": gate["errors"],
                "unmapped": gate["unmapped"][:50],
            },
            "checks_summary": {
                "supplied": checks_supplied,
                "files": checks["files"],
                "tasks_with_entries": checks["n_tasks"],
                "errors": checks["errors"],
            },
            "summary": counts,
            "tasks": results,
        }
        Path(args.out).write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print(f"wrote {args.out}")
    return 0 if all(r["verdict"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
