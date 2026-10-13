<!-- Written against the RL World platform repo x-gdpval-enterprise-workflow at commit eb16a55 (2026-10-06). -->

# How to add our QC ideas to RL World

Audience: engineers on the RL World team. You know your code. You have not seen our QC system, so each proposal below says what the check does, where in your repo it would go, and how to roll it out without surprising anyone.

Everything here comes from reading the read-only extract of `x-gdpval-enterprise-workflow` at commit `eb16a55` (paths below are relative to that extract) and from RL World's own QC notes. Nothing was run. Where we describe what code does, we read it; we did not execute it. Line numbers are from that commit.

## Words used in this document

- **Verifier**: RL World's word for one grading criterion (one pass/fail test of an AI's answer). The full list for a task is `tests/verifier.json`. A "rubric" verifier is judged by an AI model reading a written criterion (`assertion.type === "rubric"`). A "deterministic" verifier is a coded comparison (`assertion.type === "deterministic"`). Source: `src/app/auto-seed/reviewer-flow/steps/calibration-state.ts:38-40`, and the sample verifiers in `src/app/auto-seed/reviewer-flow/__tests__/calibration-schema.test.ts:38-66`.
- **Golden**: RL World's name for the reference answer, the expert-made correct deliverable. In the calibration records it appears as the subject `"Golden"` (`src/lib/v1/services/calibration/__tests__/submission-fixture.ts:11`).
- **Calibration**: the step (step 9, folder `step9_calibration`) where an expert grades each AI attempt and the golden on every verifier, then reconciles any disagreement with the AI grader. Docs: `docs/auto-seed/calibration-auto-qc.md`.
- **LLM**: a large language model, an AI text model. In RL World's code `type: "llm"` marks a quality check that an AI model performs; `type: "programmatic"` marks a check that is ordinary code (`src/lib/v1/pipeline/quality/types.ts:4`).
- **Gate**: a point where work stops until a rule says it may continue. In RL World, `applyGatePolicy` (`src/lib/v1/pipeline/quality/gate-policy.ts:28`) is the rule that decides whether failed quality checks block a step.
- **Pipeline**: here, RL World's chain of twelve steps that builds a task. The five automated quality stages run after steps 1 to 5 (`STAGE_QUALITY_CHECKS`, `src/lib/v1/pipeline/quality/stage-quality-checks.ts:624`).
- **Advisory / blocking**: the two values of `severity` on a check definition (`types.ts:6`). Advisory is meant to warn only.

## Four facts about your code that the proposals depend on

1. **Quality checks are registered in three places that must agree.** A display entry in `src/lib/v1/domain/qc/quality-check-catalog.ts` (id, title, description), a runtime entry in `RUNTIME_QUALITY_CHECKS` in `src/lib/v1/pipeline/quality/stage-quality-checks.ts:32` (version, type, severity, inputs, and for AI checks the mode and prompt), and, for code checks only, a runner in `PROGRAMMATIC_CHECK_RUNNERS` in `src/lib/v1/pipeline/quality/programmatic-checks.ts:1219-1243`. The type `RuntimeQualityCheckCatalog` (`stage-quality-checks.ts:25-31`) is keyed on the catalog ids, so a catalog entry with no runtime entry fails the TypeScript build. A programmatic check with no runner does not fail the build; at run time it returns an `error` outcome with `no_runner_registered:<id>` (`quality-runner.ts`, in `runOne`). We counted these with a script: 23 `type: "programmatic"` and 32 `type: "llm"` definitions in `stage-quality-checks.ts`, and 23 `[registryKey(` entries in the runner table (lines 1220-1242).
2. **`severity` is declared but nothing we read acts on it.** `severity: "advisory"` is set on exactly one check, `verifier_count_in_range` (`stage-quality-checks.ts:568-573`; we counted one `advisory` with a script). The field exists on both definition types (`types.ts:54` and `:65`). But `applyGatePolicy` (`gate-policy.ts:28-58`) looks only at each result's `outcome`: every result that is not `passed` is a failure, and in `BLOCKING` mode every failure blocks (lines 44-50). `PersistedQualityCheckResult` (`types.ts:27-39`) has no `severity` field, and `buildQualitySnapshot` and `parseQualitySnapshotDocument` (`quality-snapshot.ts`) store none. `grep` for `severity` across `src/lib/v1/pipeline/quality` and `src/lib/v1/domain/qc` finds it only in `types.ts` and `stage-quality-checks.ts`. The code that calls `runStageQuality` (the repair loop) is not in the extract, so we cannot say whether it reads severity. The conclusion: **today "advisory" very likely still blocks in blocking mode.** Proposals 2 and 4 want "start as a warning", so Step 0 below fixes this first.
3. **A "soft progress" mode already exists.** `GATE_POLICY_MODE.SOFT_PROGRESS` (`gate-policy-modes.ts:7-10`) lets a step pass with failed checks, recording them as `softProgressFailedIds` (`quality-runner.ts`, in `runStageQualityInner`) and showing "completed with warnings" in the UI (`src/lib/v1/domain/qc/qc-status.ts:133-171`). It is per run, not per check, so it cannot make one new check advisory while the other checks block.
4. **Calibration stores expert grades with an `agrees` flag.** Details are under Proposal 1.

### Step 0 (shared by proposals 2, 3 and 4): make "advisory" real

- Add `severity: QualityCheckSeverity` to `PersistedQualityCheckResult` (`types.ts:27`). The runner already has the definition when it builds the result (`quality-runner.ts`, the `return { ...checkResult, checkId: definition.id, ... }` block), so add `severity: definition.severity` there.
- Accept it as optional in `isPersistedQualityRow` (`quality-snapshot.ts`) so old snapshots still parse; treat a missing value as `"blocking"`.
- In `applyGatePolicy`, keep advisory failures in `failures` but skip them when computing `blocked` and `blockingFailures`. The `GatePolicyDecision` already separates `failures` from `blockingFailures`, so no new shape is needed.
- Test: copy a case from the existing gate-policy tests (the tests folder for `pipeline/quality` is not in the extract; we could not check which tests exist).
- Effort: small. Risk: this changes behavior for `verifier_count_in_range`, which will stop blocking. That matches its label, but tell the team.
- Also check, before relying on it, how your UI lists failed checks (`src/app/auto-seed/reviewer-flow/calibration-qc-view.tsx` and the Trainer Review screens). We did not trace where advisory failures would show.

---

## Proposal 1: Measure how often the AI grader agrees with experts

### (a) What it checks and why

During calibration an expert grades every AI attempt and the golden on every verifier. The AI grader's own pass/fail for the same pair is already stored next to it, with a flag saying whether they agree. Today nobody totals these. The proposal turns them into an accuracy table: for each kind of verifier and for each verifier, how often the AI grader's call matches the expert's. It tells you which AI judges you can trust and which verifiers to distrust.

Invented example: a task has 30 rubric verifiers. Across 4 attempts plus the golden that is 150 expert/AI pairs. The table shows 11 mismatches, 9 of them on one verifier "Memo states the net variance". That points at one badly worded criterion, not at the AI grader in general.

There is a second, smaller table worth building from the same records: how often the 32 AI quality checks match the expert's own quality opinion (see "Joining AI check results" below).

### (b) Where the data lives (exact files and record shape)

**Where the expert grades are stored.**

1. `tasks/{taskId}/v{N}/step9_calibration/.metadata/calibration_qc.json`. This is the Calibration Auto-QC document (`docs/auto-seed/calibration-auto-qc.md:35`). It is read and written by `CalibrationQcDocService` in `src/lib/v1/services/calibration/qc-doc-service.ts` (read at line 82, path from `GcsPaths.calibrationQc` at lines 87 and 159). Its parked form is built in `runCalibrationQcPendingSubmit` (`src/lib/v1/services/calibration/qc.ts:352-360`) and carries `submission`, which is the full calibration feedback (type `CalibrationRegenRequest`). The `submission` is copied unchanged when the status changes (`src/lib/v1/services/qc/targets/calibration.ts:120-124`). **Only exists when calibration Auto-QC is configured**: the docs say that when it is unconfigured, disabled, or has no enabled agents, "no document written" (`calibration-auto-qc.md:23-26`).
2. `tasks/{taskId}/v{N}/step9_calibration/.metadata/calibration_draft.json` is the expert's working draft (`calibration-auto-qc.md:36`). It holds the raw per-verifier, per-attempt expert grade as `draft.attemptGrades[subject]` (`src/app/auto-seed/reviewer-flow/steps/calibration-assembly.ts:140`). Whether the draft file is kept after submission is not shown in the extract.
3. The AI grader's side: each regrade mirrors `result.json`, `verifier/reward.json` and `verifier/verifier-report.json` into step 9 (`CALIBRATION_REGRADE_MIRRORED_ARTIFACTS`, `src/lib/v1/services/calibration-regen/regrade/contracts.ts:143-147`), with a provenance stamp (`ModelRegradeStampSchema`, `contracts.ts:125-139`).

**Shape of the stored record.** The Zod schema file itself (`src/lib/v1/schemas/calibration-regen-request`) is not in the extract. The shape below is reconstructed from the one fixture that parses it (`src/lib/v1/services/calibration/__tests__/submission-fixture.ts:3-30`) and from the code that builds it (`calibration-assembly.ts:138-187`):

```
CalibrationRegenRequest
  taskId, version ("v3")
  verifierFeedback[]                       one entry per verifier
    verifierId
    attemptGrades[]                        one entry per subject ("Golden" or an attempt label)
      subject
      satisfied      boolean               the expert's pass/fail
      llmPassed      boolean               the AI grader's pass/fail
      agrees         boolean               satisfied === llmPassed (assembly line 150)
      reconciliation (only when agrees is false)
        decision     "agree_judge" | "disagree"
        reason       (only for disagree) one of: grader_made_up, grader_missed,
                     check_vague, check_missing_context, other
        explanation  (only for disagree)
    gradedFairly     boolean   false if any mismatch was reconciled as "disagree" (lines 179-182)
    fairToCheck      boolean
    requirementSource  { kind: prompt | source_data | implicit | not_sourced, ... }
    checkQuality     { testsOneThing, clearPassFail, graderHasContext (null for non-rubric), ...Issue text }
    importance       "critical" | "nice_to_have"
    importanceJustification
  overallVerifiers { systemicFailure, coverageGaps, redundancies }
  goldenIssueFixes[]
```

The reason labels are in `src/app/auto-seed/reviewer-flow/steps/calibration-constants.ts:35-41`.

**An important detail about `agrees`.** `agrees: false` only means the expert's first answer differed from the AI's. After a mismatch the expert must reconcile it (`MissingCalibrationReconciliationError`, `calibration-assembly.ts:77-90`), and may answer `agree_judge` (the AI was right, the expert changed their mind; `calibration-assembly.ts:104-108`) or `disagree` (the AI was wrong). So there are two different measures:
- **Raw agreement** = share of pairs where `agrees` is true.
- **Confirmed AI error rate** = share of pairs where `agrees` is false and `reconciliation.decision` is `disagree`.
Report both. The confirmed error rate is the fairer one. The code we read does not show whether the expert sees the AI grade before first grading (the "blind" step); the UI code that decides that (`calibration-step.tsx`, `use-calibration-grading.ts`) we did not trace, so treat "blind" as unverified until someone checks.

**Joining to verifier type.** The record has only `verifierId`. The criterion type comes from the task's `tests/verifier.json` for the same version: `assertion.type` is `rubric` or `deterministic`, with extra tags in `metadata` (`grading_role`, `importance`, `weight`; sample at `calibration-schema.test.ts:38-66`). Read the verifier file from `step4_verifiers/tests/verifier.json` (`calibration-regen/regrade/stamp-writer.ts` syncs from this path; test constants at `complete-regrade.test.ts` `STEP4_VERIFIER_PATH`).

**Joining AI check results (second table).** The 32 AI quality checks write snapshots (`QualitySnapshot`, `quality-snapshot.ts:22-25`, written by `writeQualitySnapshot`; the storage module `../storage` is not in the extract, so the object path is unknown). Several AI checks list offending verifiers by id in `result.metadata.offenders`, and the expert's `checkQuality` answers map onto them:

| Expert answer in `checkQuality` | AI check to compare | Offender field |
|---|---|---|
| `testsOneThing = false` | `verifier_atomic_criteria` (`stage-quality-checks.ts:559`) | `offenders[].verifierId` |
| `clearPassFail = false` | `verifier_reasonable_specificity` (`stage-quality-checks.ts:537`) | `offenders[].verifierId` |
| `graderHasContext = false` | `verifier_self_contained_rubric_prompt` (`stage-quality-checks.ts:546`) | offenders have no `verifierId`; compare per task, not per verifier |

The mapping of expert questions to AI checks is our reading of the names and prompts; it is not stated anywhere in the code, so confirm it with whoever wrote the calibration form.

### (c) The change, step by step

1. Write a pure function `computeJudgeAgreement(submissions, verifierSets)` in a new file `src/lib/v1/services/calibration/judge-agreement.ts`, beside `qc-doc-service.ts`. Keep it free of I/O so a unit test can feed it the fixture above.
2. For each submission, walk `verifierFeedback[].attemptGrades[]`. Emit one row per pair: `taskId, version, verifierId, verifierType (rubric/deterministic, from verifier.json), subjectKind (golden/attempt), satisfied, llmPassed, agrees, decision, reason`.
3. Aggregate to: raw agreement and confirmed AI error rate, each by verifier type, by subject kind (golden versus attempt), by `reason`, and by verifier id. Add the count of pairs next to every rate. Show a Wilson 95 percent interval on any rate with fewer than about 50 pairs.
4. A small script (or a read-only admin route) lists calibration documents across tasks, calls `readQcDoc` for each version, and feeds the function. There is no existing batch reader in the extract; `CalibrationQcDocService.readQcDoc(taskId, version)` reads one. Where RL World keeps one-off scripts is not shown in the extract.
5. For the second table, load each version's latest quality snapshot (highest `attempt`, then `feedbackAttemptIndex`, from the metadata at `quality-snapshot.ts:7-20`), pull `offenders[].verifierId` for the three checks, and compare with `checkQuality`.
6. Output a CSV first. Add a dashboard later only if people use the CSV.

### (d) Data and runs needed

- Exists: expert grades with `agrees` in `calibration_qc.json` for every task that went through configured calibration Auto-QC; the AI verdicts in the same record (`llmPassed`).
- Gap: tasks that completed calibration while Auto-QC was unconfigured have no `calibration_qc.json`. For those you would need the draft file or the step-9 regrade reports. How many tasks that is, and whether drafts are kept, the extract does not show.
- Gap: the number of tasks and attempts available is not shown; the confidence intervals will tell you whether it is enough.
- No new AI runs are needed.

### (e) Effort

Small for the function and CSV (one new file, no change to existing behavior). Medium if you also join the quality snapshots, because the snapshot storage path and the verifier-to-check mapping must be confirmed first.

### (f) Risks and rollout

- **Selection bias.** Experts only reconcile mismatches, so agreement on pairs where both said "pass" is never questioned. The raw rate can look too good; the confirmed-error rate has the opposite bias if experts concede quickly.
- **Golden pairs are special.** Calibration cannot finish while the golden fails a verifier (RL World's calibration and QC rules), so golden pairs are skewed toward pass. Report golden and attempt pairs separately.
- **A changed verifier set breaks joins.** The regen flow rewrites verifiers (`calibration-regen/planner.ts`), so always join on the same `version`.
- **Rollout:** read-only analysis, no blocking. Share the table with the team that owns the AI checks before choosing any threshold.

---

## Proposal 2: Cheap script checks that need no AI

All three are new programmatic checks, copied from existing ones, and registered as advisory (after Step 0). Common model to copy: `runVerifierCountInRange` (`src/lib/v1/pipeline/quality/programmatic-checks.ts:1172-1217`), the one existing advisory code check, which reads `tests/verifier.json`, returns early with `passed` when the file is missing or invalid (leaving that to `verifier_json_valid`), and puts counts in `metadata`. For checks that open Office files, copy `runSyntheticMarkerScan` (`programmatic-checks.ts:910-971`), which starts a Python script through `runLintProcess` (`programmatic-checks.ts:107`) and maps its exit status to `passed`, `failed` or `error`.

Registration for each new check (same for all three):
1. Display entry in `src/lib/v1/domain/qc/quality-check-catalog.ts`, in the step's array (step_2, where `environment/data` first exists, near `synthetic_marker_scan` at line 124; step_4, the verifiers step, near `verifier_count_in_range` at line 331).
2. Runtime entry in `RUNTIME_QUALITY_CHECKS` (`stage-quality-checks.ts`; step_2 near line 201, step_4 near line 568) with `version: 1, type: "programmatic", severity: "advisory"` and the `inputs` it reads (`InputSelector` kinds are listed at `types.ts:41-45`: `structured`, `artifact`, `workspace_file`, `run_metadata`).
3. Runner function and a line in `PROGRAMMATIC_CHECK_RUNNERS` (`programmatic-checks.ts:1219-1243`) using `registryKey("step_N", "<id>", 1)`.
4. Add the id to `IMPORTED_SOURCE_DATA_SKIPPED_CHECK_IDS` (`stage-quality-checks.ts:673-677`) only if it should not run on imported packages (2a and 2b scan input files authored by this pipeline; imported packages keep their own file types, see the comment at lines 667-672).

### 2a. Search hidden file contents for the answer

**(a) What and why.** Visible leaks are the job of the AI check `input_file_anti_leak_scan` (`stage-quality-checks.ts:220`), which reads files through office-document tools. Text in places a viewer does not show can still be read by a solver that unzips the file: spreadsheet cell comments, tracked deletions in Word, speaker notes in PowerPoint, hidden sheets and hidden rows. The script looks there for the answer literals. Invented example: the verifier says the correct total is 48,215.60, and the input workbook has a comment on cell D9 reading "check: total should be 48,215.60".

**(b) Where.** Python script beside the existing one at `src/lib/v1/pipeline/agent/skills/source-artifact-craft/scripts/` (the path of `lint_artifacts.py` is built at `programmatic-checks.ts:52-55`). Better a new script than another mode on `lint_artifacts.py`, because we cannot see that file (it is not in the extract) and so cannot say how it is organized. New check id `hidden_content_answer_scan` in step_4 (the verifiers, which hold the answer literals, exist from step 4; `environment/data` exists from step 2). Inputs: `workspace_file tests/verifier.json` and `artifact environment/data`.

**(c) Outline.**
1. Runner reads `tests/verifier.json` with `validateVerifierJson` (imported at `programmatic-checks.ts:27`, used at line 1184) and returns `passed` early when it is missing or invalid, as `runVerifierCountInRange` does.
2. Collect answer literals: for rubric verifiers, quoted strings and numbers with at least four significant digits or a decimal point from `assertion.rubric.prompt`; for deterministic ones, `assertion.expected`. Rubric prompts inline their expected values by policy (the prompt of `verifier_self_contained_rubric_prompt`, `stage-quality-checks.ts:546`, requires it), which is why this works at all.
3. Write the literals to a temp JSON file and call the script with `runLintProcess(pythonBin, [script, dataDir, literalsPath], {cwd, maxBuffer, timeout})`, using `process.env.SOURCE_ARTIFACT_PYTHON_BIN ?? "python3"` as at line 922.
4. The script opens each `.docx/.pptx/.xlsx` as a zip and reads only the hidden parts: Word `comments.xml`, `w:del` text, `w:vanish` runs, footnotes; PowerPoint `notesSlides/*.xml` and comments; Excel `comments*.xml`, `threadedComments`, sheets with `state="hidden"`, hidden rows and columns, defined names; PDF annotations and document metadata. Exit 1 with a list of `{file, part, literal}` when it finds a hit.
5. Runner maps exit codes like lines 940-971: 0 pass, nonzero fail with the hit list in `metadata`, spawn error gives outcome `error`.

**(d) Data.** All present at step 4: `tests/verifier.json` and `environment/data`. No runs.

**(e) Effort.** Medium: the Office-format parsing is the work (about five formats and several part types each); the TypeScript side is one runner copied from `runSyntheticMarkerScan`.

**(f) Risks.** False alarms from short or common numbers: require distinct literals and require the hit to be in a hidden part only. A literal that is a legitimate raw input value (the total of a column that really is in the data) is not a leak when it sits in a visible cell, so never scan visible cells here. Run advisory for at least a few hundred tasks and sample every hit by hand before blocking.

### 2b. Flag spreadsheet formula cells that have no saved result

**(a) What and why.** An Excel formula cell holds the formula plus a saved ("cached") result. Files written by a script often have the formula and no saved result. A grader that reads the file as text, or with a library that reads saved values, sees an empty cell. RL World's own notes say no check opens a workbook the way the grader's spreadsheet reader does (RL World's calibration and QC rules). Invented example: an input workbook total cell holds `=SUM(B2:B40)` with no saved value, so a solver tool reads an empty total.

**(b) Where.** Same script folder as 2a, new check id `xlsx_formula_cached_values` in step_2 (inputs `artifact environment/data`), beside `synthetic_marker_scan` (`stage-quality-checks.ts:201`). A second, later use is on the golden workbooks (Proposal 3's data) at golden-data time; where to hook it is under "could not determine".

**(c) Outline.** The script unzips each `.xlsx`, parses each `xl/worksheets/sheet*.xml`, and counts `<c>` elements that contain `<f>` but no `<v>`. Report `{file, sheet, cellRef}` for up to 20 cells (the existing path-leak check caps its offender list at 20 the same way, `MAX_PATH_LEAK_OFFENDERS`, `programmatic-checks.ts:1070`). The TypeScript runner is the same wrapper as 2a.

**(d) Data.** `environment/data` at step 2; no runs. Whether the grader's reader ignores cached values or recalculates is not shown in the extract; confirm with the grader owners before deciding that "no saved result" is always a defect.

**(e) Effort.** Small: one XML pass, one runner.

**(f) Risks.** Cells that legitimately evaluate to empty text; flag only when there is no `<v>` element at all. Tasks where the intended workflow is "open and recalculate" would warn forever; keep advisory.

### 2c. Flag duplicate criteria and criteria that bundle several facts

**(a) What and why.** Two verifiers with the same wording double-count one fact; one verifier that demands several unrelated facts gives a pass/fail that hides which fact failed. AI checks already exist for both (`verifier_non_overlapping_criteria`, `stage-quality-checks.ts:484`; `verifier_atomic_criteria`, `:559`). A script gives a cheap, repeatable second opinion and a way to measure those AI checks (Proposal 1). Invented example: verifiers 7 and 19 both say "The memo states the corrected net income of $127,669" with one extra adjective.

**(b) Where.** New runners in `programmatic-checks.ts`, step_4, ids `verifier_duplicate_criteria` and `verifier_bundled_facts`, `inputs: [{ kind: "workspace_file", relativePath: "tests/verifier.json" }]`. Model: `runVerifierCountInRange` (`programmatic-checks.ts:1172`). To get a criterion's text, copy the logic of `resolveVerifierCriterionText` (`src/app/auto-seed/reviewer-flow/steps/calibration-state.ts:42-52`: rubric prompt, or path plus comparison plus expected for deterministic).

**(c) Outline.**
1. Parse with `validateVerifierJson`; return `passed` early on missing or invalid.
2. Duplicates: lower-case, strip punctuation, split into words, compare every pair by word-set overlap (start at 0.9); also flag pairs with the same `source` file and the same literal expected value.
3. Bundles: count distinct numbers, dollar amounts and quoted strings in one rubric prompt, and numbered list markers ("1.", "(a)"); flag when above a limit chosen from data (start at 4 distinct literals or 2 list markers).
4. Put the pairs or verifier ids in `metadata` in the same shape as the AI checks use (`{ verifierId, ... }`), so Proposal 1's join works.

**(d) Data.** `tests/verifier.json` only.

**(e) Effort.** Small.

**(f) Risks.** **Your own policy permits several facts under one construct.** The prompt of `verifier_atomic_criteria` says a criterion may require specific counts, amounts and dates "and still be atomic" if all evidence the same construct (`stage-quality-checks.ts:561-562`). A word-count rule would flag criteria your AI check passes by design. Name the script's flag "possible bundle", keep it advisory, and use Proposal 1's `checkQuality.testsOneThing` data to find a limit that matches what experts call non-atomic before raising severity. Also note the whole pipeline is "rubric first": zero deterministic verifiers is valid (`verifier_rubric_first_policy`, `stage-quality-checks.ts:446-457`), so do not assume deterministic fields exist.

---

## Proposal 3: Recompute the key answers independently

### (a) What it checks and why

Take the answers the grader expects, work them out again from the input files with separate code, and compare. Three things should agree: the grader's expected values, the golden (reference answer), and the independent recomputation. A mismatch means a wrong grader value, a wrong reference answer, or an ambiguous instruction. Invented example: the verifier says average days-to-pay is 42; the script, averaging the invoice dates in the input workbook, gets 37 because the verifier author included credit notes.

Today RL World has only indirect cover. The reference answer must pass every verifier, which exposes some wrong expected values (RL World's calibration and QC rules). One AI check, `verifier_anchored_to_required_artifacts` (`stage-quality-checks.ts:458`), asks the model to construct "one alternative" reading for each numeric anchor to see whether the anchor is uniquely forced; no script is behind it.

### (b) Where it would live

- New programmatic check `answer_recompute_matches` in step_4 (`quality-check-catalog.ts` near line 331, runtime entry near `stage-quality-checks.ts:568`, runner in `programmatic-checks.ts`), with inputs `workspace_file tests/verifier.json`, `workspace_file .long-horizon/recomputed-answers.json` (new file), `artifact environment/data`.
- The recompute program itself cannot be generic. Each task needs its own. The extract does not show the step-4 authoring agent (the `../agent` folder imported at `programmatic-checks.ts:20-30` is not included), so how to ask it for a second program is undetermined; the least invasive option is a new required output of step 4, `tests/recompute.py` writing `.long-horizon/recomputed-answers.json` as `{ "<verifierId>": value }`. The step-4 output contract and its Zod schema (`step4` in `agent/output-schemas`) would need the new file.
- The second comparison (against the reference answer) belongs after the golden exists. The golden regrade already produces a verifier report per subject whose assertion results carry `expected` and `actual` (fixture at `src/lib/v1/services/calibration-regen/regrade/__tests__/complete-regrade.test.ts:190-216`: `assertion_results[].result.{success, expected, actual, effective_weight}`). The schema is `CompletedVerifierReportSchema` (`src/lib/harbor-model-output/verifier-report-schema`, not in the extract). Compare `recomputed[verifierId]` with `result.actual` of the golden's report; golden report paths come from `buildRegradeCoordinates` (`regrade/paths.ts:41-62`).

### (c) The change, step by step

1. Define the file format and tolerance: a number, string or boolean per verifier id, plus optional `tolerance` and `unit`.
2. Phase 1, no new authoring step: apply only to deterministic verifiers (their `assertion.expected` is a literal) where the recompute is trivial; leave the rest `skipped`.
3. Phase 2: require the recompute program at step 4 and add the step-4 check above. Run it with `runLintProcess` (the same way Python is called at `programmatic-checks.ts:107-200`) with the timeout constant `LINT_PROCESS_TIMEOUT_MS` (line 64) or a shorter one.
4. Compare to the verifier's expected value. For rubric verifiers, the expected value is only inside the prompt text, so extract the same literals as in 2a, step 2 and require the recomputed value to appear among them.
5. After golden exists, add the golden comparison to the calibration QC staging code (`src/lib/v1/services/calibration/qc-task-data.ts`, which already stages the golden harbour folder and the submission snapshot) or to a new advisory finding shown with the calibration QC panel.

### (d) Data and runs needed

- Exists: `tests/verifier.json`, `environment/data`, the golden files and result (`goldenDataUploadPrefix` / `goldenDataResultPath`, used in `regrade/paths.ts:50-53`), and golden verifier reports.
- Missing: the recompute program and its output. It would have to be written by the step-4 agent or by a person.
- Runs: one cheap Python run per task, plus whatever the golden regrade already does.

### (e) Effort

Large. The TypeScript part is small, but it needs a new authoring output at step 4 (agent prompt, output schema, repair behavior when the program disagrees), and a safe place to run agent-written code.

### (f) Risks and rollout

- **Running agent-written Python in the QC worker.** The workspace is frozen read-only only for AI checks (`needsFrozenWorkspace`, `quality-runner.ts:236-243`); programmatic checks run unfrozen. A recompute program could write into the workspace. Run it in a copy, or freeze first.
- **False alarms:** rounding, units, "as of" dates, and judgment calls (credit notes in or out). Use a tolerance field and report the two values side by side. Only advisory.
- **Circularity:** if the same agent writes both the verifier and the recompute program, a shared misreading passes both. The value comes from a different instruction or model; in practice, expect the recompute to catch arithmetic slips more than misreadings.
- **Rollout:** Phase 1 on deterministic verifiers, advisory, for a few weeks; count mismatches and sample them by hand; only then ask the step-4 agent for the program.

---

## Proposal 4: Two rules to test on RL World's own data before blocking anything

### (a) What they check and why

- **Rule A: a blank-answer run that earns 20 percent or more of the total score is serious.** If doing nothing scores 20 percent, the grader rewards emptiness (for example, "does not mention X" criteria that pass on an empty file). Invented example: a task has 40 equally weighted verifiers and 9 are phrased as "the memo does not claim ...". An empty answer passes all 9: 22.5 percent.
- **Rule B: every AI model fails the same verifier although it followed the instruction is serious.** If four different attempts fail one criterion, the criterion is probably wrong, too strict, or based on a wrong expected value, not four separate model errors. Invented example: all four attempts report "revenue 3.2 million" and the verifier expects 3.4 million, because the expected value used a different cutoff date.

These are hypotheses. RL World's data should say how often they fire and whether they fire on real problems before anything blocks.

### (b) Where the data and the code would live

**Rule A needs a blank-answer run, which RL World does not have** (its searches found no empty-run). What RL World does have that is close: the golden regrade runs the verifier set against one subject through the same grader as the model attempts (`CalibrationRegradeService.discoverGoldenSlots`, `src/lib/v1/services/calibration-regen/regrade/service.ts:845-865`, using `GOLDEN_REVERIFY_EXECUTION`, `GOLDEN_REVERIFY_SLUG`, `GOLDEN_REVERIFY_STEP_FOLDER` imported at lines 40-42), and the slot kinds are an enum, `CALIBRATION_REGRADE_TARGET = { MODEL, GOLDEN }` (`regrade/contracts.ts:3-6`) with a stamp union per kind (`contracts.ts:142`). A third kind, `BLANK`, mirrors the golden slot with an empty output folder.
The score is already computed: the verifier report has `reward` and `summary.{total_weight, passed_weight}` and per-assertion `effective_weight` (fixture `complete-regrade.test.ts:190-216`). Rule A is `passed_weight / total_weight >= 0.20`.

**Rule B needs per-verifier results for every model attempt, which already exist.** Each trial's `verifier/verifier-report.json` is mirrored into step 9 per model (`regrade/service.ts:788-830` walks `trial_N` folders; slug example `openai__gpt-5.5` in `complete-regrade.test.ts`). `assertion_results[].result.success` is the per-attempt pass/fail. "Followed the instruction" is the hard part; the code has no automatic judge of it. Two proxies exist in stored data:
1. The golden passes the verifier (required for calibration to finish), so the verifier is satisfiable.
2. The expert's reconciliation: if all attempts failed by the AI grader and the expert disagreed on any (`decision = disagree`), the grader was wrong (data from Proposal 1).
RL World also already has a human version of rule B: the expert's "systemic failure" answer in `overallVerifiers` (`src/app/auto-seed/reviewer-flow/steps/overall-verifiers-state.ts:51,175-182,473-476`), which raises an admin escalation (`shouldEscalateSystemic`, line 527). It is not tied to a per-verifier count of failing models.

### (c) The change, step by step

**First, only measure (no code in the task flow):**
1. Rule B offline: read the mirrored model reports for finished tasks; for each verifier count models with `success: false`. Mark "all-fail" when every attempt fails and there are at least 3 attempts. Cross-tabulate with the golden result and with Proposal 1's `reconciliation.decision`. Output: how many verifiers are all-fail, and what share of those experts called a grader error.
2. Rule A offline: pick 50 to 100 finished tasks, create the blank run for each by hand (empty output folder, same grader), read `passed_weight / total_weight`. Output: distribution of blank scores and how many reach 20 percent.
3. A static approximation to try later, checked against step 2: from `verifier.json`, add the weights of verifiers that would pass on missing content (negative rubrics, `not_contains`, `expected: false`). The weight is `metadata.weight` (sample at `calibration-schema.test.ts:38-66`; the effective weight rules are in the grader, which is not in the extract).

**Then, if the data supports it:**
4. Rule A: add the `BLANK` target to `CALIBRATION_REGRADE_TARGET` and a `BlankRegradeStamp` to the union (`contracts.ts:3-6`, `:125-142`); add `discoverBlankSlots` beside `discoverGoldenSlots` (`service.ts:845`); mirror the report into a new step-9 path built in `regrade/paths.ts`. Trigger it where the golden-only regrade starts on entering calibration (`use-calibration-grading.ts` calls `calibration/regrade-golden`).
5. Compute both rules in one pure function in `src/lib/v1/services/calibration/` that takes the reports and returns findings `{rule, verifierId?, score?, detail}`.
6. Surface them as warnings: show in the calibration QC panel (`src/app/auto-seed/reviewer-flow/calibration-qc-view.tsx`). Blocking would be a later change to the calibration gates (`steps/calibration-gates.ts`) and the calibration QC target (`src/lib/v1/services/qc/targets/calibration.ts`); do not do it until Step 0 exists and the false-alarm rate is known.

### (d) Data and runs needed

- Rule B: existing model reports and golden reports only. Number of attempts per task is set in the models editor (`src/components/admin/HarborOutputModelsEditor.tsx`; the config schema `models-config-shared` is not in the extract), so confirm it is at least 3 for the tasks you analyze.
- Rule A: **new runs**: one blank run per task, through the same grader. The cost per run, and how the blank folder is represented to the grader's file reader, the extract does not show.

### (e) Effort

Rule B measurement: small (a script over mirrored reports). Rule A measurement: medium (hand-made blank runs). Wiring either rule into calibration as a warning: medium, because of the new regrade target, stamp and paths. Making them block: not recommended now.

### (f) Risks and rollout

- **Rule B false alarms:** a hard task, where every model genuinely fails, looks identical to a broken criterion. The proxies above reduce this; sample before trusting. Few attempts (2 or 3) make "all fail" common by chance.
- **Rule A:** 20 percent is a guess. Plot the real distribution first and pick the threshold from the gap between healthy and broken tasks. Some tasks legitimately give partial credit for "no fabricated numbers" style criteria.
- **Rollout:** measure, then warn in the panel, then, only if experts call more than about nine in ten warnings real, consider blocking at the calibration gate. Keep advisory support (Step 0) in place first.

---

## Suggested order

1. **Step 0 (make advisory real).** Small, and proposals 2 and 4 cannot start as warnings without it.
2. **Proposal 1 (agreement table).** Read-only, no new runs, and it produces the evidence the others depend on: which verifiers experts call wrong, which AI checks match expert opinion, and what limits suit 2c and Rule B.
3. **Proposal 2b, then 2c, then 2a.** 2b and 2c are small and use files already present; 2a is medium.
4. **Proposal 4, measurement only.** Rule B first (no new runs), then Rule A on a sample.
5. **Proposal 3 last.** Largest effort and it changes the step-4 authoring contract; Phase 1 (deterministic verifiers only) can start earlier if wanted.

## What we could not determine from the code

- **The Zod schemas** `calibration-regen-request`, `step-output-calibration-qc`, `step-output-calibration-draft`, `calibration/verifier-results-schema` and `harbor-model-output/verifier-report-schema` are not in the extract. The record shapes above come from the fixture, the assembly code, and the regrade test, not from the schema files. Field names or optional fields may differ.
- Whether the expert sees the AI grader's verdict before grading (the "blind" step). We did not trace the UI that shows grades.
- Whether `calibration_draft.json` is kept after submit, and where grades live for tasks whose calibration Auto-QC was unconfigured.
- The object path of quality snapshots (`writeQualitySnapshot` is in `../storage`, not in the extract), and which attempt is the right one to join.
- Where Trainer Review stores the person's agree/disagree on each automated check (the explain notes say they record it; we did not find the stored field). That would be the best truth for measuring the 32 AI checks directly.
- Whether the repair loop and the UI treat `severity: "advisory"` differently. The loop's code is not in the extract; the quality-runner and gate-policy code we read ignores it.
- The step-4 authoring agent, its output schema, and how step-4 outputs are repaired (`../agent`, `../steps` folders are not in the extract).
- The contents of `lint_artifacts.py` and `facts.py`, so we cannot say what they already inspect inside Office files or how the marker mode is structured.
- How the grader's spreadsheet reader treats formula cells without saved values, how it computes `effective_weight`, and the cost and file-handling of a blank-answer run.
- Whether the test folders contain gate-policy tests to copy for Step 0 (the quality tests folder is not in the extract).
- The number of finished tasks and attempts available, so we cannot say whether the Proposal 1 and Rule B samples are large enough.
