# Harbor QC checks

Ported from `khiemdoan-turing/harbor-qc-checks` on 2026-09-14. That repo is now the historical
dev copy; this folder is the one the QC team pulls from going forward.

Deterministic, benchmark-agnostic pre-grading QC checks, extracted and expanded from a QC
pipeline built for one benchmark (SVC-PC / Cirrus Sleep). See the honest caveat below before
assuming anything not listed in the table is ready to use elsewhere, and see `v0-checks/` for
four new checks that exist but are explicitly unvalidated.

As of 2026-09-14, 9 of the checks below are ported and verified against a second real benchmark
corpus -- EKW, 274 tasks at `C:\ekwqc\_merged274\files\`
([real downloadable copy](https://github.com/turing-genai-apps/EKW_QC_pipeline/releases/tag/ekw-corpus-274-2026-09-17),
see `ekw/README.md`) -- each cross-checked against a real
SVC-PC corpus with confirmed zero regressions. A 10th, `formula_health_check.py`, is ported and
code-complete but its full-274 EKW sweep is still running in a peer session as of this writing --
see its own table row. A new shared parser module, `ekw_verifier_json.py`, reads EKW's
`tests/verifier.json` grading schema into the same shape the checks below already consume.

**For a one-page, presentation-ready summary of the schema and what each check does** (meeting
prep, sharing with another team), see `OVERVIEW.md` instead of this file.

The letters A to E used below (for example "Check B" and the "B / C / D / E roll-ups") are defined in
`OVERVIEW.md`: A is a read-through of question, golden and rubric, B is the build, C is the finished
package, D is the rubric itself, E is the spreadsheet formulas.

## What's here, and what it can catch

| File | Maturity | What it catches |
|---|---|---|
| `reward_signal_gate.py` (+ `_test.py`) | **New 2026-09-18; wired into `pre_submit_gate.py`; calibrated on the 48-finding expert reward-signal review of QCR_EKW_16092026 — the regression test pins eight of the expert's own examples; catches 28/34 of the per-criterion findings deterministically at ~44 % candidate volume.** | The six mechanisms by which the grader scores something other than task quality: a fidelity / consistency / status / cross-document criterion the judge cannot decide from its single source (G1); a required phrase / label / ID absent from the instruction (G2); exact or cents-level numeric pins and the same figure pinned twice (G3); FAIL clauses that forbid what the instruction requires, a source contains, or a sibling PASS rewards (G4); duplicate grading by n-gram overlap (G5); a package library that cannot recalculate uncached formulas, plus exposed weight measured on real-run workbooks (G6); compound criteria (G7); the decision ledger + false-accept sweep (G8); fewer than three judge samples (G9). Candidates must be dispositioned in `reports/<task>_TRACE.json`; undispositioned = fail. |
| `layout_formula_advisory_check.py` (+ `_test.py`) | **New 2026-09-28; wired into `pre_submit_gate.py` as ADVISORY only (warn, never blocks); from the QC batch 1-6 failure analysis (60 failed tasks, 180 local task folders).** Each rule has 1 to 3 true positives, so none may block until precision is measured. | G1: an EKW-native deterministic verifier pins `sheet` / `cell_range` while the instruction allows free tab naming (GTM-178 d4/d5; 1 fire, 1 confirmed). H1: a formula-count/share floor at or above the golden workbook's own value, counted with the vendored library's rules (HLT-189 d2: floor 6, golden 6; 1 fire, 1 confirmed). H2: a formula-count/share verifier on a task whose instruction never asks for formulas or calculated cells (GTM-187 d2; 1 fire, 1 confirmed). I1: a rewardkit judge group reads a deliverable .xlsx and grades formulas/computed values with no soffice/libreoffice recalc in `test.sh`/`Dockerfile` (num-562; 39 fires, 9 confirmed / 22 clean, so advisory). The same round added F2 (oracle reward below 1.0, or grammar too large) and F3 (verifier traceback, rewardkit exit 1, or timeout in ANY run) to `oracle_reward_details_audit.py`, and the I2 re-vendor fix text to `reward_signal_gate.py` G6. |
| `review_matrix_check.py` | **New 2026-09-18.** | Rejects a review / re-check JSON whose criterion × mechanism matrix (rows = every criterion in the package's rubric + `_task`; columns M1–M6) has a missing row, a missing column or an empty cell — the structural cure for stop-at-first-instance reviewing (every prior re-check on the 12-task calibration set left same-mechanism siblings behind). |
| `harbor_rubric_gate.py` (+ `_test.py`) | **New 2026-09-18; wired into `pre_submit_gate.py`; calibrated on the 12-task QCR_EKW_16092026 platform feedback (reproduces every mechanical finding).** | The mechanically decidable part of the platform's 15-check Harbor/Terminal-Bench task rubric (`docs/harbor-task-rubric.md`), which DataOS's `QC` reviewer applies and 12/12 EKW tasks failed: roleplay opener / inputs and deliverables not named by absolute path / missing canary (`instruction_concision`); non-graded or junk files in `solution/` (`no_extraneous_files`); solve.sh wildcard or ungraded copies; no sheet/column contract for a structured deliverable (`structured_data_schema`); zero deterministic assertions or no formula source on a formula-driven golden, hardcoded goldens reported for rebuild (`anti_cheat_robustness`); shipped `judge.py` without the untrusted-`<data>` guard; and any criterion without an instruction anchor in `reports/<task>_TRACE.json` (`test_instruction_alignment`). |
| `eval_evidence_sweep.py` | **New 2026-09-18.** | Turns a DataOS `with_runs` bundle (the "task with runs" download of a task) into a per-task fixer worklist: criteria the ORACLE failed (the ORACLE run grades the golden answer against its own rubric, so a fail means the golden fails its own rubric), criteria failing ≥75 % of real agent runs with the judge's reasoning, the `nop` run's (the empty-answer run) reward and fatal-error state, the platform `qc_*.md` 15-check fail explanations, and — with `--package-root` — whether each flagged criterion is UNCHANGED / EDITED / DROPPED in the current package. Found task_31 `v26` failing both oracle runs while shipped unchanged as `accept`. |
| `package_shape_check.py` (+ `_test.py`) | **New 2026-09-22; calibrated on the 30-task fix session that produced 13 packaging defects no gate caught.** Regression baseline: 29/29 hand-fixed shipped zips pass. | Whether the artifact you are about to SHIP is shaped like a task package, from its member list alone: the archive root is exactly one `task_<id>/` wrapper (catches bare-files-at-root, a `task_files/` "download with runs" root, and a mis-named wrapper — 3 real 2026-09-22 defects); `reports/<task>_TRACE.json` + `_DECISIONS.json` present INSIDE the package and parsing as JSON (the file `reward_signal_gate.py` G8 reads — 11 of 19 round-1 zips shipped without them; **79/79 of the v7 submitted batch lack them**); no `__pycache__`/`*.pyc`/`.DS_Store`/`*.round*`/`*.bak`/nested-`.zip` members (`task_120` ships 22); required members present; and exactly one coherent build genre — an unidentifiable or mixed genre is `fail`, never `skip`. Opt-in `--against <dir>` byte-diffs the archive against the working dir that produced it, mechanizing `fix-task-from-review`'s GAP 5 stale-sibling revert: reproduced both known cases (task_133, task_139) and found three more (task_10, task_111, task_35). Content-blind by design. |
| `timeout_headroom_check.py` (+ `_test.py`) | **New 2026-09-22; calibrated on 87 real DataOS verifier runs and all 79 shipped v7 packages.** | A task whose serial LLM judging cannot finish inside its own `[verifier] timeout_sec`: `rubric_criteria x judge_samples x seconds-per-call` vs the budget, as a headroom ratio. A verifier timeout writes NO reward.json, so it is invisible in an aggregate score report rather than showing as a low score — confirmed real on task_157 and task_LGL-160, both of which died at the 3600 s cap. `--seconds-per-call` defaults to the measured p90 (46.0 s; min 8.6 / median 23.7 / max 61.2 across 87 runs) because a timeout is a tail event; pass `25` for the median per-task ranking (23 fail / 52 pass). Counts only LLM-judged rubric criteria; sample count comes from the task's own `config.models`. rewardkit-hybrid is `skip` (chunked, judged concurrently). At the default 74/75 native packages fail — the batch-wide template `timeout_sec = 3600.0`, a batch decision plus regression guard, not a per-task discriminator. |
| `oracle_reproducibility_check.py` (+ `_test.py`) | **New 2026-09-22; calibrated on the two real `with_runs` QCR bundles; rediscovers all four known non-reproducible criteria.** | The mechanism behind "DataOS fails at random": a criterion whose verdict is not reproducible on byte-identical goldens. Reads a bundle's ORACLE `eval_files/verifier/{verifier-report.json,reward-details.json}` and reports cross-run disagreement at the same `task_checksum` (task_120 `v6c`: 0.98 vs 1.00; task_LGL-168 `v9`; task_LGL-131 `v13`: 3-0, 2-1, 1-2 on identical copies) and split judge votes within a single run that mean-of-3 masks (task_LGL-161 `v14`: 1T/2F in both runs, identical mean — invisible to a mean-score comparison), plus a per-task `unstable_criteria` list with `weight_at_risk`. Reuses `_oracle_merge.py`'s vocabulary; adds the per-sample vote layer `oracle_reward_details_audit.py`'s mean-score comparison cannot express. |
| `formula_provenance_lint.py` (+ `_test.py`) | **New 2026-09-22; calibrated on the 9 measured defects of the 30-task 2026-09-22 fix session — 9/9 baselines flagged, 8/9 by their own mechanism; 0 gate-ready false positives across two shipped sweeps (79-task v7 + 51-task v4), independently re-verified.** | Static lint of a task's OWN copy of the band-anchored formula-provenance template (`tests/deliverables_*/check_formula_provenance.py`), which is hand-edited per task and never otherwise linted — the single largest defect cluster in that session (9 of 30 tasks). Gate-ready detectors: a value that really exists in the task's `environment/` inputs or as a typed constant in its golden falling inside a rubric band (`band_collision`, task_462/559/348), and an echo/reference-chain follower capped below 8 hops (`hop_limit_too_low` — task_390's 3-hop cap scored a real 4-hop live chain as a typed constant, 0 on a 0.10 check). Report-only: unanchored date-window / small-magnitude / unit-interval bands (task_218, task_470), per-cell rather than per-figure violation counting (task_574), a missing `=<literal>*1` guard, a required construct absent from `instruction.md` (task_559's `range_agg`), and a shallow coverage floor or unscoped whole-workbook formula-share assertion (task_348, task_145 — fires on 42/46 non-skip v7 tasks, hence report-only). Never executes the checker: `ast` parse plus a restricted replay of the CONFIG block only; includes a stdlib PDF text extractor so PDF-sourced inputs are scanned. |
| `formula_health_check.py` | **Generic, battle-tested at scale; extended 2026-09-14 with 3 new heuristics.** No benchmark assumptions beyond an opt-in `--id-prefix` flag. Ported to EKW 2026-09-14 (format-agnostic recomputation engine; only judge-file-discovery changed) plus new native `--jobs` parallelism (`ProcessPoolExecutor`, default `cpu_count-1`) -- EKW-verified correct on an 8-task smoke sample only, full-274 sweep still running in a peer session as of this writing; do not report a final EKW number yet. | A rubric criterion expecting a computed/derived spreadsheet cell that reads as blank/NaN/error when actually recalculated, even though a plain read of the cached value looks fine (or vice versa). Plus three new syntactic heuristics: `mixed_qualifier_smell` (a formula mixes a sheet-qualified reference with a bare one, e.g. `Channel_Model!B17*$B$7` where `$B$7` silently resolves same-sheet), `out_of_bounds_unqualified_ref` (a bare reference points past the current sheet's own used range), `cross_scenario_monotonicity` (a best-effort row/sheet-level consistency check). Catches all of this BEFORE an expensive grading round-trip, deterministically, zero LLM cost. |
| `formula_cache_autofix.py` | **Generic, battle-tested at scale.** Imports `formula_health_check.py` for its classification logic. | Mechanically patches only the "pure caching gap" findings from the health check (a formula is correct, its cached value just wasn't recalculated on save) by rewriting the cell's cached `<v>` XML value directly. Never touches formula logic. Refuses (reports "needs judgment") on anything where the live recomputed value is itself missing/erroring -- it never fabricates a number. |
| `rubric_schema_check.py` | **Generic, logic proven at scale in its source project; extended 2026-09-14 with a third detector.** Ported to and verified clean against the real 274-task EKW corpus 2026-09-14, cross-checked against SVC-PC with zero regressions. | Blank/stub criterion descriptions, per-file and per-task rubric weight-sum mismatches, and (new) `placeholder_expected`: a criterion's description reads as a real requirement sentence but its "Expected:" value slot was never populated (`"Expected: ."` with nothing after) -- found on 1,467 criteria across 38 real tasks in this folder's own calibration corpus. |
| `deliverable_filename_check.py` | **Generic; extended 2026-09-14 to check both directions.** | FORWARD (original): whether every filename a judge.toml's `files=[...]` names is actually mentioned in `instruction.md`'s text. REVERSE (new): whether every filename `instruction.md` explicitly commands the solver to produce is actually graded by judge.toml -- the more severe direction, since an agent following the prompt exactly can write a file the grader never opens and silently score 0. Found 26 real REVERSE-only failures and 2 both-fail cases (a real extension typo, `.xlsx` expected vs `.xlsm` commanded) in this folder's own calibration corpus that the forward-only check missed entirely. EKW port 2026-09-14 (after recognizing EKW's own deliverables-heading phrasing and stripping its angle-bracket placeholder convention): FORWARD 272 pass / 2 fail / 0 skip, REVERSE 74 pass / 0 fail / 200 skip, out of 274 -- cross-checked against SVC-PC with zero regressions. |
| `duplicate_criterion_check.py` | **Generic, new (report-only mode of an existing fixer).** Ported to and verified against EKW 2026-09-14; the port fixed a false-positive class where the fallback "guess the last sheet" logic misread unrelated business-data xlsx files as rubric sheets. Cross-checked against SVC-PC with zero regressions. | Rubric criterion IDs that collide after normalization -- a collision can silently drop a criterion's weight from scoring even when a separate weight-sum check still reads 1.0, if the dropped and surviving weights happen to cancel out. |
| `deliverable_integrity_check.py` | **Generic, new.** | Whether every golden deliverable file actually opens/parses cleanly (xlsx/xlsm via openpyxl, docx via its own zip structure, pdf via a basic well-formedness check) -- generalizes the same "don't trust a file just because it exists" check this folder already applies to spreadsheet formulas. |
| `structural-audit/SKILL.md` | **Taxonomy generic and proven; needs an LLM session to apply.** | Placeholder environment contradicting the prompt, deliverable-filename mismatch between prompt and grader, unhydrated external-storage dependency, answer-key/pipeline text leaked into the solver-facing prompt, internal contradictions, unstated deliverable count/format. |
| `content-audit/SKILL.md` | **New, designed for this folder; pattern 6 independently re-derived and confirmed against 2 real, previously-unseen tasks, patterns 1-5 not yet validated.** | Rubric-vs-prompt-vs-golden internal consistency, six patterns: a criterion asking for a fact the prompt/golden never establishes; a rubric's expected value contradicting what the golden actually computes; a golden citing a source absent from its own stated inputs; two rubric criteria contradicting each other; an expected-answer leak into a rubric's own description text; and a criterion requiring content the prompt explicitly forbids inventing (or two criteria in the same file contradicting each other on sourced-vs-invented). |
| `BUILD-CONTRACT.md` | Not a check -- a spec. | Defines the package shape (`instruction.md` + `environment/` + `solution/` + `tests/deliverables*/judge.toml`) every benchmark's own build/conversion step must produce for every check above to work on its output. |
| `ekw_verifier_json.py` | **Not a check -- shared parser module, new 2026-09-14.** | Parses EKW's `tests/verifier.json` grading-config schema (the JSON shape distinct from SVC-PC's `judge.toml`) into the same intermediate criteria/files shape the checks above already consume. Verified 274/274 clean parses across the real EKW corpus, 0 crashes, 0 parse errors, across 7+ real schema variants: dict- and list-shaped `source`, `extract_many`/`arguments.paths` extraction forms, the `task_FIN-177` task's fully alternate schema, directory-type reference entries, and both `rubric` and `deterministic` assertion types. |
| `ekw/ekw_check_b.py` + `ekw/ekw_run_checks.py` | **EKW-specific, new 2026-09-14, calibrated on all 274 tasks of the 2026-09-10 EKW drop.** | The worked example of `BUILD-CONTRACT.md`'s translation layer, a second, independent path onto the same shared checks: it stages EKW's harbor packages into the contract shape (rather than teaching each check to read `verifier.json` natively) so every check above runs on the staged copy unchanged, plus its own Check B (package files, all seven `verifier.json` source shapes plus the foreign schema, weights, graded-file-to-golden agreement, build genre), an optional real reward-kit conversion as build proof, and a runner that merges Check B and all 12 shared checks into one per-task table with B/C/D/E roll-ups. Cross-verified against `ekw_verifier_json.py`'s native parse on 271 of 274 tasks with identical output; real numbers from both paths, plus a runtime and reliability note, are in `ekw/README.md`. |
| `v0-checks/duplicate_task_detector_v0.py` | **v0, UNVALIDATED.** | Near-duplicate task pairs by prompt-text similarity. No calibration data yet -- see the file's own status header. |
| `v0-checks/pii_metadata_scanner_v0.py` | **v0, UNVALIDATED.** | Document author/metadata fields plus shape-based PII pattern matches (SSN-like, email, phone). No sensitivity policy has been set. |
| `v0-checks/injection_scanner_v0.py` | **v0, UNVALIDATED.** | Generic prompt-injection-shaped text patterns, zero-width Unicode, suspicious base64-looking strings. No judge-model-specific threat model behind the pattern list. |
| `v0-checks/golden-reproducibility/SKILL.md` | **v0, UNVALIDATED AS A PROCESS.** | A blind-solve-and-compare procedure to check whether an independent solve of a task (given only environment inputs) actually reproduces the golden answer -- distinct from Oracle, which only checks the golden against its own rubric. |
| `rubric_text_lint.py` | **Generic, new, verified against named real defects.** | Zero-LLM text lint over `judge.toml` criteria for three authoring defects: `extraction_blind` (a criterion asks about something a text-extraction-based judge can't see -- cell formatting, protection, hidden state), `meta_rubric_knowledge` (a criterion demands the deliverable claim knowledge of its own grading rubric, which no solver can know), `stale_format_mismatch` (a criterion's language names a file format the task's actual `files=[...]` doesn't ship). Ported to and verified against EKW 2026-09-14; the port added a `commands`/`command` field to the shared parser's output specifically so `extraction_blind` doesn't false-positive on `extract_formulas`/`extract_xlsx`-sourced criteria -- 7 of 11 initial EKW flags were exactly this false positive. Cross-checked against SVC-PC with zero regressions. |
| `tab_naming_check.py` | **Generic, new, verified 9/9 against real defects.** Ported to and verified clean against the real 274-task EKW corpus 2026-09-14, cross-checked against SVC-PC with zero regressions. | A criterion claims a specific tab exists at a specific position in the golden workbook; opens the real golden and checks the real sheet order. Reuses `formula_health_check.py`'s file-resolution logic so it can never drift from that script's notion of "the golden." |
| `deliverable_count_check.py` | **Generic, new, calibrated against the full corpus (89/6/505 pass/fail/skip at build time).** | A task's "Deliverables:" prose promises more distinct artifacts than its "Graded deliverable filenames" section will ever check for existence -- so some described deliverables are silently never graded. EKW port 2026-09-14, after adding recognition of EKW's own deliverables-heading phrasing ("Produce the following deliverables in `<path>`:"): 204 pass / 3 fail / 67 skip out of 274 -- the 67 skips are genuinely different phrasing or no explicit heading, not a detection gap. 3 known pre-existing false-positive-risk quirks stay documented in the script's own docstring (an appositive-order guard, single-line bulleted lists, a company-name false-exclusion case) -- not fixed, EKW port scope only. |
| `environment_input_check.py` | **Generic, new, verified against 20 named real defects across 4 sub-patterns.** | Mechanizes structural-audit patterns 1, 3, and 5 together: a filename `instruction.md` names as a required input that doesn't exist anywhere in `environment/initial_workspace/`; a bare cloud-storage URL (Drive/Dropbox/OneDrive/SharePoint) treated as an input but never hydrated locally; and a `_no_input_files_required`-style placeholder marker that directly contradicts an instruction.md naming specific required files. EKW port 2026-09-14: pattern 1 (missing named input file) was initially blanket-disabled for EKW as a false-positive class (misreading deliverable filenames as missing inputs); now genuinely runs after fixing that class and unioning in verifier.json's actually-graded filenames -- 273 pass / 1 fail (task_625, a real content-vs-filename-convention finding needing human judgment, not a script defect) out of 274. Patterns 3 and 5 unchanged on EKW (0 hits, already clean). |
| `answer_key_leakage_check.py` | **Generic, new, verified 12/12 real findings, 0 false positives.** | Mechanizes structural-audit pattern 4: a `GOLDEN`/`Golden`-named (or `_SOLUTION`/`_ANSWER`/`_REFERENCE`/`_ANSWERKEY`/`_KEY`-named) filename the solver is told to produce, or bracketed internal-pipeline directive language left inside `instruction.md`. |
| `answer_key_content_leak_check.py` | **Generic, new, shipped as a LOW-CONFIDENCE candidate-for-review tool, not a pass/fail gate (see its own docstring).** | A rubric's own literal expected value (a dollar figure, a date, a specific fact) appearing verbatim inside a file the solver can actually read, gated on the containing file ALSO having a suspicious name -- a plain "value appears anywhere in the environment" check was tried first and produced too much noise (control totals legitimately recur in real source documents) to ship as a gate. Ported to and verified clean against the real 274-task EKW corpus 2026-09-14. |
| `judge_criterion_name_duplicate_check.py` | **Generic, new.** | Closes a gap `duplicate_criterion_check.py`'s own docstring names: two `[[criterion]]` blocks in the same `judge.toml` sharing a `name` -- a different collision shape than the xlsx-rubric `id` collision that script covers, and just as capable of silently dropping a criterion's weight if something downstream keys criteria by name. Ported to and verified clean against the real 274-task EKW corpus 2026-09-14. |
| `extraction_groundedness_check.py` | **Generic, new 2026-09-14, dual-format, corpus-validated.** | Does a criterion's required property match what its actual configured extraction command can see -- the command-aware fix to a false-positive gap `rubric_text_lint.py`'s own docstring already named but couldn't close. SVC-PC has no per-criterion command field anywhere in the real pipeline (confirmed against `rewardkit/judges.py`: every document is routed through MarkItDown unconditionally, keyed only on file suffix), so SVC-PC criteria are graded against a fixed constant; EKW criteria are graded against their own real `commands` field from `ekw_verifier_json.py`. Full-corpus run: SVC-PC 150/600 tasks flagged (466 findings), EKW 4 confirmed + 7 correctly suppressed (matches `rubric_text_lint.py`'s own "11 raw hits, 7 false positives" finding almost exactly). Explicitly does not cover judge FILE-scope adequacy (which files are graded at all) -- a different, still-open mechanism; see `CHANGELOG.md`'s fifth-pass entry for the three false-positive classes found and fixed during corpus-scale testing. |
| `judge_determinism_config_lint.py` | **Generic, new, multi-schema (TOML judge.toml AND JSON verifier.json/manifest.json).** | Reads whatever grading-config format a task actually has for a `temperature`/`sample_count`/`panel`/`vote_count`-shaped field; flags a nonzero-temperature-with-no-panel config as the single most damaging defect an external QC review of three OTHER benchmarks found (a judge score that isn't reproducible run to run). For this folder's own SVC-PC corpus, which exposes no such field anywhere in `judge.toml`, it reports that absence explicitly as "not exposed, not verified safe" rather than a false pass -- see `PERPLEXITY-QC-FINDINGS.md`. Needed ZERO code changes for EKW -- its multi-schema prober already tries `tests/verifier.json` unconditionally -- confirmed 2026-09-14 by actually running it (not just reading the code) across all 274 EKW tasks. That run surfaced a genuine corpus-wide finding: 269 of 274 EKW tasks show `temperature_found_no_panel` (a nonzero judge temperature configured with no panel/sample-count field) -- a real signal worth surfacing to whoever owns EKW's judge/grading config, separate from the porting work itself. SVC-PC regression check: exact match to the documented baseline, 600/600 `not_exposed`. |
| `judge_panel_size_check.py` | **New, uncalibrated, multi-schema (reuses `judge_determinism_config_lint.py`'s config discovery).** | A related but distinct gap the temperature/panel lint's key-name patterns don't cover: a `models`/`model_list`/`panel_models` field that names only ONE model for majority-vote/ensemble judging -- a single point of judgment even at temperature 0. Found real on this repo's own `pipeline/data/sample_corpus/task_11` (`config.models: ["openai/gpt-5.4"]`). **Per-task policy since 2026-09-18** (list the judge model three times; enforced by `reward_signal_gate.py` G9) — no longer a corpus-level note. See `QC-REVIEW-8x-COVERAGE.md`. |
| `criterion_condition_count_check.py` | **New, uncalibrated, multi-schema.** | Counts separately-checkable conditions bundled into one rubric criterion (sentences, "and"/"or" conjunctions outside parentheticals, semicolon/enumerated clauses) and flags any criterion over `--max-conditions` (default 3) -- an external QC review found 13% of sampled rubrics at 8+ conditions per criterion, one at 27, and recommended this ceiling for reproducibility and contradiction-visibility. Lint only, never rewrites a criterion. See `QC-REVIEW-8x-COVERAGE.md`. |
| `invention_detection_input_check.py` | **New, uncalibrated, multi-schema.** | Flags an invention/fabrication-detection criterion ("did the candidate make this up?") whose grading config shows the judge only the candidate's own deliverable, never the source material a judge would need to actually tell invented content from correctly-sourced content -- the exact shape one external QC review's own example described. Found real on `task_11`'s own rubric. See `QC-REVIEW-8x-COVERAGE.md`. |
| `golden_dependency_reachability_check.py` | **New, uncalibrated, multi-schema.** | Flags a rubric criterion whose expected value leans on an analysis script/notebook by name (`"per analysis4.py"`, `"as computed by the ... script"`) that isn't shipped anywhere under `environment/` -- the failure shape behind one external QC review's quarantined task, where ~90% of the rubric's marks depended on two scripts the solver never received. See `QC-REVIEW-8x-COVERAGE.md`. |
| `workbook_recalc.py` | **New, reuses `formula_cache_autofix.py`'s recompute/classify/patch/verify logic verbatim, uncalibrated on real submissions.** | Not a task-shaped check -- a standalone tool for retroactively recomputing and patching stale/blank formula caches in an arbitrary directory of ALREADY-COLLECTED spreadsheets (e.g. agent-submitted deliverables from a completed eval run), for batches that predate the harness fix in `pipeline/templates/harbor/verifier_lib/sources/xlsx.py`. Verified end-to-end against a synthetic stale-cache fixture. See `QC-REVIEW-8x-COVERAGE.md`. |

## Honest caveat -- read this before presenting this as a general QC framework

As of 2026-09-14, most of what's in the table above is no longer just "built generic on
purpose" -- it's cross-benchmark verified. 9 checks (`rubric_schema_check.py`,
`deliverable_filename_check.py`, `duplicate_criterion_check.py`,
`judge_criterion_name_duplicate_check.py`, `rubric_text_lint.py`, `tab_naming_check.py`,
`deliverable_count_check.py`, `environment_input_check.py`, `answer_key_content_leak_check.py`)
plus `judge_determinism_config_lint.py` (which needed no code changes at all) are ported and
verified against a real 274-task EKW corpus with zero SVC-PC regressions, and the
formula-health-check + cache-autofix pair (deterministic, no benchmark assumptions once the one
hardcoded prefix filter became an opt-in flag) was already proven generic before today --
`formula_health_check.py`'s own EKW sweep is still in progress, see its table row. The
six-defect-pattern structural-audit taxonomy still needs a Claude session or a person to read the
package and apply the six checks, so "mechanical" means "follow this exact recipe," not "zero
judgment, zero LLM." Everything else in the source
pipeline -- the tracker builder, the autofix recipe set, the manual-QC intake format, and roughly
28 other one-off scripts -- is specific to that one benchmark in ways a flag can't fix: a
hardcoded task-ID regex, a literal hardcoded batch list, a hardcoded live spreadsheet ID, and one
documented gap where the source pipeline's own docs point at a script that was never actually
built as reusable (the real logic for a related filename check is a disposable scratch file
today, not a maintained tool). Generalizing those is separate, larger work that is in progress
but not done -- please don't present the tracker or autofix logic as ready for another benchmark.

See `GAP-ANALYSIS.md` for what a genuinely comprehensive pre-grading QC framework is still
missing beyond these three pieces, and the phased plan for closing those gaps.

## Quickstart

Both scripts require `--root` explicitly -- there is no default path, on purpose, so this never
silently points at the source project's own directories.

```bash
# Check a specific set of tasks
python formula_health_check.py TASK-1 TASK-2 --root /path/to/your/task/folders --out report.json

# Check every task under a root (one subdirectory per task)
python formula_health_check.py --all --root /path/to/your/task/folders --out report.json

# If your task IDs share a common prefix and you want --all scoped to just those
python formula_health_check.py --all --root /path/to/your/task/folders --id-prefix MYBENCH- --out report.json

# See what the autofix WOULD do, without writing anything
python formula_cache_autofix.py --all --root /path/to/your/task/folders --dry-run --out report.json

# Actually apply the fix (backs up every file it touches to <file>.orig first)
python formula_cache_autofix.py --all --root /path/to/your/task/folders --out report.json
```

Both scripts auto-`pip install openpyxl formulas lxml` on first run if those aren't present. In
a locked-down/sandboxed environment where that install can't reach the network, install them
manually first: `pip install openpyxl formulas lxml`.

## Running every check at once: `run_all.py`

Every script above is independently invocable, on purpose (see the "Honest caveat" above), but
that means checking one batch of tasks against everything here means running ~15 commands by
hand and cross-referencing their outputs yourself. `run_all.py` does that in one command:
invokes every applicable check against one `--root`, unmodified (each still runs exactly as if
you'd called it yourself), and writes one `summary.json` plus a printed table.

```bash
# Every task under --root
python run_all.py --all --root /path/to/your/task/folders --out-dir results/

# An explicit list of task ids
python run_all.py TASK-1 TASK-2 TASK-3 --root /path/to/your/task/folders --out-dir results/

# From a text file, one id per line
python run_all.py $(cat tasklist.txt) --root /path/to/your/task/folders --out-dir results/
```

It does NOT run `formula_cache_autofix.py` or `workbook_recalc.py` by default -- both WRITE to
files, and this is a read-only triage tool. Pass `--include-autofix` to also run
`formula_cache_autofix.py` in `--dry-run` (report-only) alongside the checks; it is never run in
write mode by `run_all.py`. It also does not run the two LLM/human checklists
(`content-audit/SKILL.md`, `structural-audit/SKILL.md`) or `v0-checks/` (explicitly
unvalidated) -- see `run_all.py`'s own module docstring for the full list of what's excluded and
why. See `QC-REVIEW-8x-COVERAGE.md` for more on the new checks it runs alongside the
pre-existing ones. Note `run_all.py` targets the contract shape directly (`instruction.md` +
`environment/` + `solution/` + `tests/`) -- for EKW's own harbor packages, which are NOT in that
shape, use the EKW runner below instead, which stages a contract-shaped copy first.

### EKW tasks

EKW's harbor packages are not in the contract shape, so point the checks at them through the
EKW runner, which stages a contract-shaped copy and runs everything:

```bash
# All 274 tasks, every check, one table (about 80 minutes, formula_health_check dominates)
python ekw/ekw_run_checks.py --all --root C:\ekwqc\_merged274\files --stage C:\ekwqc\_ekw274_stage --out-dir C:\ekwqc\_ekw274_qc

# A few tasks, Check B only, with the real reward-kit conversion as build proof
python ekw/ekw_check_b.py task_142 task_15 --root C:\ekwqc\_merged274\files --stage C:\ekwqc\_ekw274_stage --rewardkit-out C:\ekwqc\_ekw274_rk --out check_b.json
```

`ekw/README.md` explains the output, the two EKW build genres, and which shared checks behave
differently on EKW and why.

## How to read the output (if-then rules, not judgment calls)

- `status: "pass"` on a task in `formula_health_check.py`'s report means zero actionable
  findings. `status: "fail"` means at least one actionable finding -- read `summary.by_kind` for
  which kind(s).
- A finding with `"actionable": false` and a `suppressed_reason` is disclosed but does NOT count
  toward pass/fail -- do not re-interpret it as a failure. This happens for two reasons: the
  `formulas` engine couldn't evaluate the cell at all (a limitation of the check, not a claim
  about the workbook), or the file shows a "whole-file cache wipe" signature (nearly every
  formula cell blank-cache with zero hard breaks -- a known mechanical artifact of certain
  save/convert pipelines, not a targeted defect).
- In `formula_cache_autofix.py`'s report, per-task `status` is one of: `clean` (nothing to fix),
  `fixable`/`would_fix` (a real caching gap, safe to patch), `needs_judgment` (do NOT auto-apply
  -- read the `reasons` field), `fixed` (patched and independently re-verified), or
  `failed_reverted` (a patch attempt was made, verification disagreed, and the original file was
  restored from backup automatically -- no half-fixed file is ever left on disk).
- `structural-audit/SKILL.md` findings are reported as `clean`, `defective (pattern name + exact
  quote)`, or `no_built_package`. Treat `no_built_package` as "unassessed," never as "clean."

## Contact / provenance

Extracted 2026-09-14 from a QC pipeline for the SVC-PC benchmark. Questions about the source
pipeline or this extraction: Khiem Doan.
