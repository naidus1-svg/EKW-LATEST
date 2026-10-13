<!-- Written against the CTP canvas repo turing-ctp-canvas-company-sim at commit 578e40e (2026-10-06). -->

# How to add our QC ideas to the CTP canvas

Audience: engineers on the CTP canvas team. You know your code. You do not know our QC system, so each proposal starts with what the check is for and one invented defect it would catch.

Code read: the extract of `turing-ctp-canvas-company-sim` at commit 578e40e (folders `packages/quality-policy`, `apps/server/src`, `apps/pane/src/api/qc-readiness`, `docs`, `README.md`). All paths below are relative to that repo. Line numbers are from that extract. Our side: the QC process doc `docs/QC-SOP-first-run.md` in `EKW_QC_pipeline` at commit 7e64189.

Words used here:
- **Rubric**: the list of graded rows a trainer writes for a task. Each row says what a correct answer must contain.
- **Golden answer** (golden): the trainer's own reference answer, uploaded as text or files.
- **Gate**: a check that can stop a step (Lock or Submit). A check that only shows a message is a warning.
- **Solver**: an AI agent that tries the task from the prompt and the input files, without seeing the golden.
- **DataOS**: the platform where our own reviews run. Our review there grades the golden itself, grades several solver attempts, and grades one empty answer that must score zero.

---

## 1. What we were told about CTP, checked against the code

| Claim we were told | Verdict | Evidence |
|---|---|---|
| The policy pack has 42 checks, 24 switched on, 6 able to block | **Confirmed** (counted with a Python script that splits `packages/quality-policy/packs/company-sim-v1.yaml` on `- id:` and reads `enabled:` and `enforcement:`) | 42 checks in total. 24 have `enabled: true`. 6 of those 24 have `enforcement: block`: `phase2_units_present`, `prompt_present`, `excluded_inputs_not_selected`, `golden_present`, `golden_bytes`, `twin_rubric_alignment`. 20 checks in total say `block`, but 14 of them are switched off. 23 of the 24 enabled checks list `pre_submit` in `applies_to`. |
| AI checks run on a small model | **Confirmed for the repo baseline only** | `packages/quality-policy/prompts/prism/manifest.yaml` sets `model: claude-haiku-4-5-20251001` on all 14 prompts (lines 13 to 160). The model actually configured inside the live Prism metrics is not in the repo (see section 9). |
| AI checks only warn at Submit | **Confirmed** | All 10 checks of kind `semantic` have `enforcement: warn` (pack lines 42 to 456, plus `prism_pre_submit` at 484). `defaults.semantic_on_error: warn` (pack line 11). Nuance: the dev sample YAML in `apps/server/src/lib/stage-qc-config.mjs` lines 177 to 212 marks the `lock_golden` stage as `gate: true, blocking: true`. The real `canvas_config` lives in CTP Admin, not in the repo, so we cannot say what production does at Lock. |
| The AI checks see 2,400 characters of the golden plus file names only | **Confirmed** | `apps/server/src/lib/stage-qc-payload.mjs` line 18 `PRE_SUBMIT_GOLDEN_CLIP = 2_400`, line 175 clips `golden_text`, lines 162 to 165 and 176 send only `golden_file_names`. It is clipped further to 600 characters (lines 19 and 235) when the request exceeds `STAGE_QC_MAX_EVALUATE_BYTES = 28_000` (line 5). No input file content is sent at all: `buildPreSubmitUnit` (lines 160 to 185) has no field for it. The Lock stage clips the golden at 4,000 characters (line 101). |
| Grading is one AI grade per click with a 0.7 pass | **Confirmed, with detail** | `POST /api/metrics/evaluate` (`apps/server/src/routes/metrics.mjs` line 134) calls one backend once. The default backend is `rewardkit_ds` (`apps/server/src/lib/sim-backends-config.mjs` line 434). It makes one scoring session (`rewardkit-ds.mjs` lines 220 to 232), the judge model defaults to `anthropic/claude-haiku-4-5` (line 194), and pass is `score >= 0.7` on the aggregate (`PASS_THRESHOLD` line 19, `gradeFromScores` line 291). The pass looks at the total score only. A task can pass with failing rows. |
| There is no solver gate | **Confirmed, with a nuance** | A solver run exists: `apps/server/src/lib/headwind-runner.mjs` (route `POST /api/harbor/headwind`, `routes/headwind.mjs` line 70). It stores `headwind_ok` (score at or below 0.55, line 166) in `last_headwind`. No check in `packages/quality-policy` mentions it (we searched the whole package for "headwind": no hits), so nothing stops Lock or Submit on it. The run also shows the golden to the solver as a "for reference" hint (`headwind-runner.mjs` lines 114 to 116), so it is not a clean solver test. |
| There is no blank-answer scoring | **Confirmed** | No code builds an empty or lazy candidate. The candidate path exists (section 7) but an empty candidate is rejected with HTTP 400 (`golden-reference.mjs` lines 153 to 157). |
| The 90-of-100 readiness rule is not enforced at Lock or Submit | **Partly confirmed; the "Blocked can still lock" part we cannot confirm** | The rule exists only as (a) `release.minimum_score: 90` (pack line 15), (b) the handler `release_decision` (`handlers/release-decision.mjs` line 18, `score >= 90`) used by two checks, `harbor_release_gate` (pack lines 471 to 482) and `ready_for_final_qc` (lines 543 to 553), both `enabled: false` with the comment "No production stage builds the review subject". Nothing computes a 0 to 100 score from the graded rows. The server route only reports a status: `lib/qc-readiness.mjs` lines 1 to 6 say it "deliberately makes no lifecycle decision". The Lock and Submit buttons are in the pane, which is not in the extract (only `apps/pane/src/api/qc-readiness/client.ts`). So whether a task marked blocked can still lock is not visible to me. |

Two more facts that matter for every proposal:

1. `evaluateQcReadiness` hard-codes the stage: `apps/server/src/lib/qc-readiness.mjs` line 97 passes `stage: 'pre_submit'`, and `routes/qc-readiness.mjs` lines 14 to 34 take no stage from the request. Checks that list only `lock_golden`, `final_qc`, `peer_review` or `release` in `applies_to` therefore never run through this route. Lock-time checks today are the separate Prism path (`POST /api/stage-qc`, stages `map`, `lock_golden`, `pre_submit`, `routes/stage-qc.mjs` line 148).
2. The evaluator never calls an AI judge itself. For a semantic check it only returns a "request" (`packages/quality-policy/evaluator.mjs` lines 60 to 80 and 118 to 129). The caller then posts those metric ids to `/api/stage-qc`, which builds the evidence packet (`stage-qc-payload.mjs`) and polls Prism (`stage-qc-evaluate.mjs`). So "what the AI sees" is decided in `stage-qc-payload.mjs`, not in the pack.

---

## 2. How the CTP QC code is laid out (the part you will edit)

| Piece | File | What it does |
|---|---|---|
| Policy pack | `packages/quality-policy/packs/company-sim-v1.yaml` | The list of 42 checks. Each has `id`, `kind` (programmatic, semantic, human), `enabled`, `applies_to` (stages), `enforcement` (block, warn, record), and for programmatic checks `impl: { handler: <key> }`. |
| Handler registry | `packages/quality-policy/handlers/index.mjs` lines 23 to 45 (`HANDLERS`) | Static allowlist from handler key to module. An unknown key fails pack loading (`validator.mjs` lines 50 to 54). Adding a handler means a new module here plus one line in this object. |
| Handler shape | e.g. `handlers/ds-rubric-score.mjs` (23 lines) | `export async function evaluate(context, check, services)`. It loops over `context.units` with `perUnit` (`handlers/common.mjs` lines 53 to 59) and returns rows built by `result()` (lines 36 to 51). |
| Evaluator | `packages/quality-policy/evaluator.mjs` lines 109 to 183 | Picks enabled checks for the stage, runs handlers, turns `fail` into `warn` when enforcement is `warn` (lines 19 to 22), and sets overall `status: 'blocked'` if any blocking check failed (lines 24 to 42). A handler that throws becomes `fail` for block checks and `warn` otherwise (lines 156 to 165). |
| Route and glue | `apps/server/src/routes/qc-readiness.mjs`, `apps/server/src/lib/qc-readiness.mjs` | `POST /api/qc-readiness`. Injects `services` (line 100 to 111) such as `validateGolden`. |
| AI evidence packet | `apps/server/src/lib/stage-qc-payload.mjs` | Builds what Prism metrics read. 28,000-byte cap (line 5). |
| Grading | `apps/server/src/lib/metric-eval/port.mjs`, `rewardkit-ds.mjs`, `prism-ctp.mjs`, `lib/rewardkit-compile.mjs` | `POST /api/metrics/evaluate`. Turns rubric rows into a Reward Kit test pack and runs it in a DynamicSession (DS) agent session. |
| Grade record | `rewardkit-ds.mjs` lines 288 to 326 | `last_metric_grade`: `outcome`, `score`, `criteria_results` (one entry per row with `criterion_id`, `outcome`), `pass_count`, `fail_count`. Parsed by `metric-eval/parse-reward-details.mjs`. The pane stores it on the unit and sends it back as `unit.last_metric_grade` (read at `handlers/ds-rubric-score.mjs` line 4). |
| Solver run | `apps/server/src/lib/headwind-runner.mjs` | Runs a model on the task prompt with staged input files (lines 145 to 160). |
| File to text | `apps/server/src/lib/markitdown.mjs` (`buildArtifactsMarkdown`, line 397) and `metric-eval/golden-reference.mjs` (`buildGoldenReference` line 237, `buildCandidateReference` line 264) | Downloads files by signed URL and extracts text. Budgets: 12,000 characters per file and 200,000 total by default (`markitdown.mjs` lines 34 to 42), 800,000 for staging (line 46). |
| Background jobs | `apps/server/src/lib/job-queue.mjs` (`enqueueRunnable` line 154, `waitForJob` line 204) | Used by Headwind (`routes/headwind.mjs` line 70) so long runs do not hold an HTTP request. |

The Lock and Submit buttons, the rubric editor, and the code that assembles `units` are in the pane (`apps/pane/src`), which we did not have. Every proposal that must change what a button does has a "pane" step that we can only describe, not point to a line.

---

## 3. Proposal 1: Grade the golden twice, every row passing, with a model close to DataOS's

### (a) What it checks and why
Today one grading click gives one score from one run of a small judge model, and the golden passes if the total is at least 0.7. A wrong golden, or a flaky row (a row that passes one run and fails the next), can pass once and slip through.

Our process grades the golden itself at least twice on DataOS (step 5a.1 of `docs/QC-SOP-first-run.md`) and again locally, twice, on the same final files, with every row passing on every run (the sweep item, SOP section 6a item 5, that uses `svc-pc-pipeline/tools/judge_emulate.py`).

Invented defect: row R14 says "Net margin is 14 percent". The golden file shows 13.8 percent. A small judge model is generous and passes it on run 1. On run 2 it fails it. A single click shows 0.93, which is a pass. Two runs show R14 disagreeing, which proves the row or the golden is unreliable.

### (b) Where it would live
- **New module**: `apps/server/src/lib/metric-eval/repeat-grade.mjs`. It calls `rewardkitDsEvalBackend.evaluate(body)` (`rewardkit-ds.mjs` line 146) N times with the same body and merges the results. Model to copy for "run more than one": the secondary-run block in `port.mjs` lines 46 to 61 (`include_secondary`), which already runs a second backend on the same body and keeps both results.
- **Route**: add `repeat: 2` to the body of `POST /api/metrics/evaluate` (`routes/metrics.mjs` line 134), handled in `evaluateMetricPort` (`port.mjs` line 35). For long runs reuse the async pattern of `routes/headwind.mjs` lines 70 to 94 (`enqueueRunnable`, then poll `.../jobs/:id`).
- **Judge model**: the value is read from `METRIC_RK_JUDGE`, then `METRIC_RK_MODEL`, else `DEFAULT_METRIC_RK_MODEL = 'anthropic/claude-haiku-4-5'` (`rewardkit-compile.mjs` lines 7 and 38 to 43; passed in at `rewardkit-ds.mjs` line 194). No code change is needed to switch models, only the env value. Which model id matches our DataOS grader is for us to supply.
- **New check**: pack entry `golden_graded_twice_clean` in `company-sim-v1.yaml`, `kind: programmatic`, `applies_to: [lock_golden, pre_submit]`, `enforcement: warn` at first. Copy the shape of `ds_rubric_score` (pack lines 458 to 469). New handler `packages/quality-policy/handlers/golden-repeat-grade.mjs`, registered in `handlers/index.mjs` line 23 to 45. Copy `handlers/ds-rubric-score.mjs`, which already reads `unit.last_metric_grade`.

### (c) The change, step by step
1. In `repeat-grade.mjs`, run the two gradings in parallel with `Promise.all` (so wall time stays near one run). Return `{ runs: [grade1, grade2], fingerprint }`.
2. Build the `fingerprint` from what was graded: the golden file `media_id`s plus a hash of `golden_text`, the rubric `id` and `version` (the packet already carries them, `stage-qc-payload.mjs` lines 316 to 317), and a hash of the prompt. This is the "same final files" proof.
3. Extend `last_metric_grade` (`rewardkit-ds.mjs` lines 313 to 324) with `fingerprint` and keep each run's `criteria_results`.
4. New handler logic, per unit:
   - no stored runs, or stored fingerprint differs from the current files: `warn` "golden changed since it was last graded, grade it again";
   - fewer than 2 runs: `warn`;
   - any row that is not `pass` in any run: `fail`, and list the row ids in `detail`;
   - rows that differ between runs: `fail`, listed as "flaky rows".
5. Pane (not visible to me): the grading button sends `repeat: 2`, stores the whole result on the unit, and sends it back as `unit.last_metric_grade`.

Skeleton, in the style of `ds-rubric-score.mjs`:
```js
export async function evaluate(context, check) {
  return perUnit(context, (unit, unitKey) => {
    const runs = Array.isArray(unit.last_metric_grade?.runs) ? unit.last_metric_grade.runs : [];
    const bad = new Set();
    for (const run of runs)
      for (const row of run.criteria_results ?? [])
        if (row.outcome !== 'pass') bad.add(row.criterion_id);
    const pass = runs.length >= 2 && bad.size === 0 && unit.last_metric_grade.fingerprint === unit.current_fingerprint;
    return result(check, { unit_key: unitKey, status: pass ? 'pass' : 'fail', message: '...', detail: { rows_not_passing: [...bad], runs: runs.length } });
  });
}
```

### (d) Data and runs needed
- Exists already: the grading run, `criteria_results` per row (`parse-reward-details.mjs`), the golden extraction (`buildGoldenReference`).
- To add: the fingerprint, and the second run. The server keeps no grade state; the pane holds `last_metric_grade` on the unit (read at `handlers/ds-rubric-score.mjs` line 4), so the pane must send the fingerprint inputs back.
- A should-pass row (`severity: should-pass`, compiled as `optional = true`, `rewardkit-compile.mjs` line 52) may legitimately fail. Decide whether "every row passing" means every row or every must-pass row. We require every row.

### (e) Effort: **medium**
The server module and handler are small. The cost is in the pane (button, stored shape) and in deciding the judge model.

### (f) Risks and rollout
- A stronger judge model is stricter, so more golden answers will show failing rows. Expect a jump in fails on day one: start as `warn`, and log the share of tasks that fail.
- Time and cost double per click. Each run is a full DS agent session with a timeout of up to 20 minutes (`rewardkit-ds.mjs` line 205). Run the two in parallel and grade at Lock, not at Submit. At Submit only compare the stored fingerprint to the current files.
- The golden reaches the judge by an agent re-typing it into a file ("Write the following content EXACTLY", `rewardkit-ds.mjs` lines 208 to 216), cut at 180,000 characters (line 214). A re-typing slip looks like a golden defect. The two-run rule will surface it, which is useful, but tell trainers.
- Roll out: warn, measure for two weeks, then switch `enforcement` to `block` in the YAML. No code change for the flip.

---

## 4. Proposal 2: Make "90 of 100 plus must-pass" actually stop Lock and Submit

### (a) What it checks and why
A task should not lock or submit unless the computed score is at least 90 out of 100 and every must-pass row passes. Today three different things are called "the result":
1. the readiness status `blocked` or `ready` (`evaluator.mjs` lines 24 to 42, duplicated in `lib/qc-readiness.mjs` lines 31 to 50);
2. the grade outcome at 0.7 (`rewardkit-ds.mjs` line 291, pack `ds_rubric_score` scale 0 to 1, pass 0.7, line 463);
3. a 90 rule in `release_decision` that nothing feeds (see section 1).

The `ds_rubric_score` handler cannot even block: it returns `warn` for any non-pass (`handlers/ds-rubric-score.mjs` line 12), and the check is `enforcement: warn`.

Invented defect: a task has 20 rows. Two must-pass rows fail, but the weighted score is 0.88, which passes the 0.7 bar. Lock goes ahead.

### (b) Where it would live
- **New handler** `packages/quality-policy/handlers/readiness-score.mjs`, registered in `handlers/index.mjs`. Model: `handlers/release-decision.mjs` (the score, failed gates and pass logic already written, lines 3 to 31) combined with the per-unit loop of `ds-rubric-score.mjs`. A new handler is cleaner than bending `release_decision`, which is task-level and carries exception logic.
- **Pack**: new check `readiness_90_must_pass`, `applies_to: [lock_golden, pre_submit]`, `enforcement: warn` first. Leave `harbor_release_gate` disabled or delete it to avoid two competing 90 rules.
- **Route**: `routes/qc-readiness.mjs` lines 14 to 34 and `lib/qc-readiness.mjs` line 97. Add a `stage` field to the request, allowlisted to `lock_golden` and `pre_submit`, and pass it to `evaluatePolicy`. Many existing checks already list `lock_golden` in `applies_to`, so this also switches those on at Lock.
- **Pane** (not visible to me): Lock and Submit must read `report.status` (`client.ts` lines 12 to 30 returns the parsed report) and disable the action when it is `blocked`.

### (c) The change, step by step
1. Compute the score per unit from `last_metric_grade.criteria_results` joined to `rubric_definition.criteria` on `criterion_id`. Score = (sum of points of passing rows) / (sum of all points) x 100. Points come from `row.points ?? row.weight`, the same rule as `handlers/rubric-contract.mjs` lines 12 to 18.
2. Must-pass rows are those with `severity === 'must-pass'` or `gate === true`, the same test as `handlers/response-contract.mjs` line 35.
3. Result per unit: `fail` if score < 90 or any must-pass row is not `pass`. Report "not graded yet" separately from "graded and failed". A run that errored must not look like a failed task: `rewardkit-ds.mjs` lines 250 to 263 turn a failure of the scoring program (Reward Kit, the test runner that scores the rows) into an HTTP error with no grade.
4. Decide one threshold. The pack has two (0.7 grade pass, 90 release). Our recommendation: keep 0.7 only as "the grade ran", and let the new check own the 90.
5. Server-side backstop. `POST /api/verdicts/work-unit` (`routes/verdicts.mjs` lines 38 to 114) records `outcome` and `score` straight from the request body, with no check. Anyone calling it can record `pass`. If Lock and Submit must be tamper-resistant, have `/api/metrics/evaluate` return a signed `grade_token` over `(unit_key, fingerprint, score, outcome)` and have the verdict and readiness routes verify it. The server holds no grade state today, so this is the only way to stop a hand-edited `last_metric_grade`.

### (d) Data and runs needed
- Exists: per-row results and weights.
- Gap to check: the Reward Kit compile uses only `weight` (`rewardkit-compile.mjs` line 51: `Math.max(0.1, Number(c.weight) || 1)`), while our rubric contract counts `points ?? weight`. If twin rubric rows carry `points` and no `weight`, the grader weights differ from the points the 100 is built on. Check that before relying on the score.
- Gap: `release_decision` expects `context.review` (score, failed gates, exceptions). Nothing builds it ("No production stage builds the review subject", pack line 474). The new handler avoids that by computing from units.

### (e) Effort: **medium** for the rule and route, **large** with the signed token and the pane work
The handler and route change are small. The pane gating and the token are not.

### (f) Risks and rollout
- Block rate is unknown. A 90 bar with must-pass rows could block most tasks at first. Ship as `warn` and show the computed score and failing must-pass rows in the readiness panel, then make Submit block, then Lock.
- A stale grade: if the golden or rubric changed after grading, the old score must not count. Use the fingerprint from proposal 1.
- Do not make Submit slower: the check reads the stored grade and does no grading.

---

## 5. Proposal 3: Recompute every expected value from the inputs, with its source, before the rubric opens

### (a) What it checks and why
Wrong answer keys are the most common serious defect in our reviews. We re-derive each fact from the input files ourselves, and our reviewers derive the key answers before they read the grader (`docs/QC-SOP-first-run.md`, "Recompute from source" step 2 of the sweep).

In CTP, each rubric row carries `expected_value` (`stage-qc-payload.mjs` line 322; parsed in `apps/server/src/lib/rubric.mjs` lines 15 to 42). No check recomputes it. The AI check `golden_claims_supported` (pack lines 316 to 330, warn) reads at most 2,400 characters of the golden.

Invented defect: row R7 expects "Q3 revenue: 4.82 million". The source workbook's Q3 sheet totals 4.28 million. The trainer transposed two digits. The golden repeats the mistake, so every golden-based AI check agrees with it.

### (b) Where it would live
- **New unit field** `value_ledger`: a list of `{ fact_id, label, value, unit, source_media_id, locator, method }`, where `method` is `direct` (read off the file) or `computed` (with the formula in words). Rubric rows reference `fact_id`. Parse and clip it like `clipRubric` (`stage-qc-payload.mjs` lines 312 to 333).
- **New handler** `packages/quality-policy/handlers/expected-values-sourced.mjs`. Model: `handlers/excluded-inputs.mjs` (reads `unit.input_files` and rubric fields, lines 16 to 67). Register in `handlers/index.mjs`. Pack entry next to `expected_values_not_in_prompt` (pack line 442), id `expected_values_recomputed`.
- **Service** `services.recomputeValues`, injected where `validateGolden` is injected (`lib/qc-readiness.mjs` lines 100 to 111). Handlers receive `services` as the third argument (`evaluator.mjs` line 136; used by `handlers/golden-bytes.mjs` line 3).
- **Recompute backend**: new `apps/server/src/lib/metric-eval/recompute-ds.mjs`, modelled on `headwind-runner.mjs` (stages input files at `/workspace/data/`, lines 145 to 160, collects output).
- **Pane** (not visible to me): the ledger editor, and the "rubric opens" step. We do not know where the pane opens the rubric panel, so we cannot name the line to guard.

### (c) The change, in two tiers
**Tier A (cheap, deterministic):**
1. The handler fails a unit if any rubric row with a numeric `expected_value` has no `fact_id`, or the ledger entry has no `source_media_id` and `locator`.
2. A service extracts the text of each cited source file with `buildArtifactsMarkdown` (`markitdown.mjs` line 397, already used for goldens in `golden-reference.mjs` line 161) and checks that the ledger value appears in the cited locator. This catches a value with no basis. It does not catch a wrong derivation.

**Tier B (the real defence, a blind recompute):**
1. Start a DS agent session (as in `headwind-runner.mjs` line 145) with the input files and a list of questions made from the ledger labels. Do not send the expected values or the golden. Our own rule is that an answer key must never be visible to the party being tested.
2. Compare the session's answers to the ledger within a tolerance. Disagreement is a `fail` with both values in `detail`.

### (d) Data and runs needed
- Input file bytes. `normalizeFiles` (`handlers/common.mjs` lines 21 to 34) reads `url` from each file, and `markitdown.mjs` downloads by URL against an allowlist (`isAllowedArtifactDownloadUrl`, line 95). Whether the pane sends `input_files[].url` in the readiness request, we cannot tell from the extract. `required-input-files.mjs` only uses `media_id`s.
- Spreadsheet caveat: our review has seen formula cells with no stored value read as blank. We did not find in `markitdown.mjs` or `xlsx-structure.mjs` whether stored values or formulas are read, so Tier A may fail on legitimate formula cells.

### (e) Effort: **large**
New ledger field and editor in the pane, a new backend, and a new check. Tier A alone is **medium**.

### (f) Risks and rollout
- False alarms: values that depend on a stated assumption or a judgment call will not match a blind recompute. Add a `method: assumption` entry that is reported but not failed.
- Trainer friction: a ledger for every value is more work. Require it only for rows with a numeric `expected_value`.
- Roll out Tier A as `warn`, collect mismatch rates, then add Tier B as `warn`, then block.
- Cost and time: one extra DS session per task. Run it once at Lock and cache by fingerprint.

---

## 6. Proposal 4: Let the AI checks read the input file contents and the whole golden

### (a) What it checks and why
The AI checks judge "does the golden answer the prompt", "are its claims supported", "does the rubric allow valid alternatives". Without the input contents and the full golden, they can only judge the shape. The pre-submit prompts say so: `prompts/prism/pre-submit-golden-alignment-v1.md` tells the judge "Do not infer content from a filename alone" and to say plainly when the body was not available.

Invented defect: the golden is a 40-page workbook. The AI sees the first 2,400 characters of the golden (a title sheet and two rows) and file names. It scores 9 out of 10, "aligned", while sheet 5 contradicts the prompt.

### (b) Where it would live
- `apps/server/src/lib/stage-qc-payload.mjs`: `buildPreSubmitUnit` lines 160 to 185, constants lines 5 and 14 to 19, `fitPreSubmitEnvelope` lines 226 to 294. The lock stage packet is `buildSubject` lines 91 to 108.
- Prompt files in `packages/quality-policy/prompts/prism/` and `manifest.yaml` (version, `input_schema_version`, `model`).
- `PRE_SUBMIT_SUBJECT_SCHEMA_VERSION` at `stage-qc-payload.mjs` line 12. Its comment says a shape change must be detectable on both sides, so bump it.

### (c) The change, step by step
1. **Slice 1 (golden only).** Reuse the server-side extraction that Run metric already does: `buildGoldenReference` (`golden-reference.mjs` line 237). Add `golden_extracted` per unit, clipped by a new, larger cap instead of 2,400.
2. **The size limit is the real problem.** The whole envelope is capped at `STAGE_QC_MAX_EVALUATE_BYTES = 28_000` (line 5) and `fitPreSubmitEnvelope` drops whole records to fit. A full golden plus inputs will not fit. Pick one:
   - raise the cap, if the Prism request ceiling allows it (unknown, section 9);
   - split into many small requests, one per rubric row or per golden section, each carrying only the relevant excerpt, and merge the scores (`evaluateStageQcMetrics`, `stage-qc-evaluate.mjs` line 475, already runs several metrics, three at a time, line 197);
   - move these checks off Prism onto a DS agent session that has the files staged under `/workspace/data/` (pattern: `headwind-runner.mjs` lines 149 to 152). This is the only option that gives a judge the full input files.
3. **Slice 2 (inputs).** Add `input_digest` per unit, using the per-file budgets already in `markitdown.mjs` (lines 34 to 47).
4. Rewrite the three prompts that say "names only" (golden alignment, source feasibility, rubric construct), bump their `version` in `manifest.yaml` and the metric bindings, and re-provision. `DESIGN.md` lines 27 to 34 and 224 say provisioning is a separate, explicitly approved step, and `provisioning.mjs` only builds the definitions without writing.
5. Consider a stronger model for these prompts. `manifest.yaml` sets Haiku 4.5 on all of them. A small model reading 100,000 characters will miss things.

### (d) Data and runs needed
- Exists: file extraction, per-file budgets, the packet builder.
- To add: input file URLs in the packet (same open question as proposal 3), and a decision on the request size ceiling.

### (e) Effort: **small** for the golden-only slice if the cap can rise; **medium** for the split-request design; **large** for the DS-session design with full inputs

### (f) Risks and rollout
- Slower and costlier Submit. Today each metric polls up to 180 seconds (`stage-qc-evaluate.mjs` line 198), three at a time. More text per request means slower answers. Keep Submit warning-only and run the new reads at Lock.
- The idempotency cache keys on the payload (`routes/stage-qc.mjs` lines 234 to 240), so a bigger payload changes keys. Harmless, but caches reset.
- More evidence means more findings, and these checks only warn. Expect noise. Keep `warn` and track how often the AI flag matches a human reviewer's finding before any block.
- Confidentiality: full input files go to the metric service. Confirm that is allowed before shipping.

---

## 7. Proposal 5: Map every prompt requirement to a rubric row and block on gaps

### (a) What it checks and why
Every thing the prompt asks for should be graded by at least one row, and no row should grade something the prompt never asked for. Our process numbers each requirement in the prompt and proves each is mapped (`docs/QC-SOP-first-run.md` step 3 of the sweep: `svc_coverage_trace.py list` and `check`, exit 0 required). Without it the row count follows what the trainer thought of, not what the prompt says.

Invented defect: the prompt asks for a summary table, a risk list, and a recommendation. The rubric has 12 rows, all about the table. Nobody grades the recommendation, so a solver that skips it passes.

What CTP has today: nothing that links requirements to rows. `twin_rubric_alignment` (pack lines 348 to 358, block) only compares row ids between the grading sheet and the response-criteria sheet. `pre_submit_completeness_v1` (an AI prompt, warn) asks if "criteria... are materially complete", but sees a clipped prompt.

### (b) Where it would live
- **New unit field** `prompt_requirements`: `[{ id, text }]`, saved with the unit, plus a new rubric row field `covers_requirements: ["Q1", "Q3"]`. Add the row field in `clipRubric` (`stage-qc-payload.mjs` lines 312 to 333) and `parseCriterion` (`apps/server/src/lib/rubric.mjs`, lines 15 to 42).
- **New handler** `packages/quality-policy/handlers/requirement-coverage.mjs`. Copy `handlers/twin-rubric-alignment.mjs` almost line for line: it builds two id sets with `criterionMap` (`common.mjs` lines 13 to 19) and reports `missing_in_grading` and `missing_in_response`. Here the two sets are requirement ids and the union of all `covers_requirements`. Pack entry `prompt_requirements_covered`, `applies_to: [lock_golden, pre_submit]`, `enforcement: warn` first.
- **Extraction**: a new flow that drafts the numbered requirement list from the prompt, next to the existing `draft_rubric` flow (`apps/server/src/lib/pipeline-runner.mjs`, the module that runs AI flows, lines 1 to 60 and 206; and `routes/llm.mjs`). `prompts/flows.json` is not in the extract, so we cannot name the line.

### (c) The change, step by step
1. Draft the requirement list from the prompt with an AI flow. The trainer edits and confirms it. Store a hash of the prompt with the list.
2. Rubric rows get a `covers_requirements` selector in the rubric editor (pane, not visible to me).
3. Handler results, per unit:
   - any requirement with no covering row: `fail` (listed);
   - any row covering nothing: `warn` ("row not asked for by the prompt");
   - prompt hash changed since the list was confirmed: `warn` "requirements are stale".
4. Add an AI check on top, as a semantic check in the pack and a new prompt in `manifest.yaml`, to judge whether a mapped row really tests its requirement. Keep it `warn`.

### (d) Data and runs needed
- Exists: the prompt text and rubric rows, both in the packet.
- To add: the requirement list and the row mapping. Nothing is stored today.

### (e) Effort: **medium**
The handler is about 40 lines. The editor UI and the extraction flow are most of the work.

### (f) Risks and rollout
- Extraction quality: the AI may miss or invent requirements. The trainer-confirmed list is the only source of truth, so block only on that list.
- Gaming: one catch-all row that "covers" every requirement. Add a `warn` when one row covers more than a few requirements.
- Implied requirements (units, layout) will not be in the list. Allow trainers to add requirements by hand.
- Speed: purely deterministic at Submit, no slowdown. Start as `warn` and look at the gap rate.

---

## 8. Proposal 6: Grade a blank answer and a lazy answer, and block if either earns meaningful credit

### (a) What it checks and why
A good rubric gives nothing for an empty answer and little for a lazy one. Our DataOS review grades one empty answer and expects zero, and a reviewer reports a defect if an empty or copied answer scores 0.20 or more of the total (`docs/QC-SOP-first-run.md` step 5a.2).

Invented defect: row R9 says "No unsupported claims appear". An empty file satisfies it. A blank answer scores 0.35 and would pass the 0.7 bar if enough other "absence" rows exist.

### (b) Where it would live
- **The candidate path already exists.** `POST /api/metrics/evaluate` accepts `candidate_response` (text) and `candidate_media_files` and grades them instead of the golden: `rewardkit-ds.mjs` lines 103 to 108 and 173 to 182, `prism-ctp.mjs` lines 297 to 302 and 397 to 407, with `buildCandidateReference` (`golden-reference.mjs` line 264). Grading something that is not the golden needs no new backend.
- **One blocker found**: an empty candidate is rejected. `buildReferenceFromInputs` throws `Candidate has no response text or attached output files to score.` (HTTP 400) when text is empty and there are no files (`golden-reference.mjs` lines 153 to 157). Fix: add an `allowEmpty` option on `buildCandidateReference`, or send a one-line placeholder such as "(no answer provided)".
- **New module** `apps/server/src/lib/metric-eval/negative-controls.mjs`: builds the control bodies and calls `evaluateMetricPort` (`port.mjs` line 35) for each, in parallel. Run it through the job queue like Headwind (`routes/headwind.mjs` line 70).
- **New check**: pack entry `blank_answer_scores_near_zero` (copy `ds_rubric_score`, pack lines 458 to 469), `applies_to: [lock_golden, pre_submit]`, with a handler `handlers/negative-controls-low.mjs` modelled on `handlers/ds-rubric-score.mjs`, reading `unit.last_negative_controls`.

### (c) The change, step by step
1. Build the controls without any model call (deterministic):
   - **blank**: the placeholder, or an empty file with the required file name;
   - **skeleton**: the golden's headings or sheet names with every value removed. This catches structural rows that give credit for a correctly named file. The compile step turns rows into presence checks for sheets, slides and extensions (`rewardkit-compile.mjs` lines 72 to 153), so a skeleton is the likeliest thing to earn unearned credit;
   - **copy-the-input**: the text of the first input file as the answer;
   - **numbers masked**: the golden text with every digit replaced by `#`. Rows that accept any number will pass it.
2. Grade each control with the same backend and judge as the golden. Keep `score` and the per-row `criteria_results` (`rewardkit-ds.mjs` lines 313 to 324), so the trainer sees which rows gave credit.
3. Handler rule, per unit: `fail` if blank or skeleton scores at or above a threshold, `warn` if copy-the-input or masked scores at or above a second threshold. Starting values are a proposal, not code: 0.20 for blank (the figure our reviewers use), and tune the lazy-answer threshold from data (start near 0.40).
4. Store the result as `last_negative_controls` with the same fingerprint as proposal 1, so a stale result is not trusted.

### (d) Data and runs needed
- Exists: the golden text and files, input files, the grading backend, per-row results.
- To add: the control builders, the stored result, and capacity. Each control is a full DS agent session. Today the blank case is not cheaper, because the backend always creates a session (`rewardkit-ds.mjs` lines 220 to 232).
- Rate limits: `/api/stage-qc` has a limiter (`routes/stage-qc.mjs` line 41), `/api/metrics/evaluate` has none in the code we read. Whether DS can take 4 to 5 parallel sessions per task is unknown (section 9).

### (e) Effort: **medium**
Mostly reuse. New work is the control builders, one job wrapper, one handler, one pack entry, and the `allowEmpty` fix.

### (f) Risks and rollout
- False alarms: a legitimate row worth a few points for "file exists" lets a blank answer score a little. A 0.20 threshold leaves room, and the per-row report shows which rows did it.
- The judge model is small. A lenient judge gives credit to blanks that a stricter judge would not, so the result depends on proposal 1's model choice. Use the same judge for all runs.
- Time: up to 20 minutes per session (`rewardkit-ds.mjs` line 205). Run in parallel and at Lock only. Submit only reads the stored result.
- Roll out: `warn` first, with the three or four highest-scoring rows shown. Switch the blank check to `block` first, the lazy checks later.

---

## 9. Suggested order

1. **Proposal 6, blank answer first.** Smallest path to a real defect catch, reuses the candidate path, and needs only the `allowEmpty` fix, a job wrapper and one handler. Ship as `warn`.
2. **Proposal 1, grade twice.** Shares the runner built in step 1 (parallel runs, the stored fingerprint, the per-row record). Pick the judge model here, since proposal 6 depends on it.
3. **Proposal 4, golden-only slice.** If the Prism request cap can rise, this is a small change in `stage-qc-payload.mjs` plus a prompt version bump.
4. **Proposal 5, coverage.** Handler is small and deterministic. Do the pane work in parallel with steps 2 and 3.
5. **Proposal 2, enforce 90 plus must-pass.** Needs the fingerprint and per-row records from steps 1 and 2 to be trustworthy. Do the pane gating and any signed token last, after warn-mode numbers show the block rate.
6. **Proposal 3, recompute values.** Largest. Do Tier A first, Tier B after.

Flip each check from `warn` to `block` in `company-sim-v1.yaml` only after a warn-only period that shows the false-alarm rate. The flip is a YAML change, no code.

---

## 10. What we could not determine from the code

- **The pane.** Only `apps/pane/src/api/qc-readiness/client.ts` was in the extract. We did not see the Lock and Submit buttons, the grading button, the rubric editor, how `units` are built, or what `parseQcReadinessReport` does. So we cannot confirm "a task marked Blocked can still lock", and every pane step above is described, not located.
- **Platform-side enforcement.** CTP Workbench may block Lock or Submit on its own using the `stage_qc` entries (`gate`, `blocking`). The only copy in the repo is the dev sample (`stage-qc-config.mjs` lines 177 to 212): `lock_golden` is `gate: true, blocking: true`, `pre_submit` is `gate: false, blocking: false`. The production config is in CTP Admin.
- **Live Prism metrics.** The model and prompt stored in Prism for each metric id. The repo gives only the baseline in `manifest.yaml`.
- **Deployed settings.** The real values of `METRIC_EVAL_PRIMARY`, `METRIC_RK_JUDGE`, `METRIC_RK_MODEL`, `METRIC_RK_PASS_THRESHOLD`, `METRIC_HUB_PASS_THRESHOLD`. We read only the defaults.
- **Reward Kit internals.** The `required_pass` and `weighted_mean` aggregation (`rewardkit-compile.mjs` line 461) is implemented in an external package. How a failing must-pass row changes the score is not in this repo.
- **Whether `input_files[].url` reaches the server** in the readiness request (needed by proposals 3 and 4).
- **Prism request size ceiling** above the 28,000-byte cap, and whether the DS catalog accepts a given judge model id.
- **DS capacity** for 4 to 5 parallel sessions per task, and any rate limit on `/api/metrics/evaluate`.
- **Weights versus points.** Whether twin rubric rows carry `weight`, `points` or both (see proposal 2, section (d)).
- **Where `last_metric_grade` is stored** between clicks. The README says `saveDraft` persists some state (`README.md`, CTP rules, item 3), but we did not see which fields.
- **The tests** in `apps/server/scripts/` (named in `DESIGN.md` line 77) and `prompts/flows.json` were not in the extract.
- **How many tasks each proposal would block.** Nothing in the code gives base rates.
