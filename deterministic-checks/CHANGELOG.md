# Changelog

## 2026-09-28 (advisory checks from the QC batch 1-6 failure analysis)

- `layout_formula_advisory_check.py` (new, + `_test.py`, 15 tests): G1 sheet/cell_range pin under free tab naming,
  H1 formula floor at the golden's own count, H2 formula gate the instruction never asks for, I1 rewardkit formula
  criteria with no LibreOffice recalc step. Wired into `pre_submit_gate.py` as advisory; never blocks.
- `oracle_reward_details_audit.py`: F2 `oracle_reward_below_one` / `oracle_grammar_too_large` and F3
  `verifier_crash` (traceback, rewardkit exit 1, `Reward '<group>' failed`, timeout) over every run, not only
  oracle runs; warn-only. Also resolves the nested `<task>/<task>/rev_*` with_runs layout. 7 new tests.
- `reward_signal_gate.py` G6: evidence now names the drifted vendored `xlsx.py` and the fix (re-vendor
  verifier_lib). Status unchanged.
- Corpus run over 180 local QC-review task folders: G1 1/1, H1 1/1, H2 1/1 confirmed; I1 39 fires (9 confirmed,
  22 clean); F2 5 tasks (2 confirmed, 2 clean); F3 7 tasks (3 confirmed, 3 clean). Precision on clean tasks is not established: clean
  labels come from zero-pass review only.

## 2026-09-23 (SVC-PC pipeline moved into the team repo; judge-input gate; llm_backend OSError)

- `svc-pc-pipeline/` (new, repo root): the full SVC-PC fix-and-ship pipeline that ran on the QC sandbox, with its
  runbook, rules, submission skill and README. See `svc-pc-pipeline/README.md`.
- `judge_input_gate.py` + `scans/judge_input_report.py`: build the real `/app` content root and run it through
  rewardkit's own input builder, so a judge `files=` entry that rewardkit silently skips (over 1 MiB) or cannot
  find is caught before DataOS (67-1-0 and 8-2-0 majors). `judge_emulate.py` imports the report module.
- `tools/llm_backend.py`: `_call_claude_cli` catches `OSError`, not only `FileNotFoundError`. An "Exec format
  error" while the claude binary auto-updates is infra (LLMBackendError), not a crash; it had parked
  SVC-PC-35-0-0 as a tool bug.

## 2026-09-17 (structural_audit_check run-to-run determinism fix, rows 28-29)

Fixes the run-to-run non-determinism an adversarial re-review found in
`structural_audit_check.py`. SVC-PC-16-2-0 (a confirmed true positive:
instruction.md line 1 is `# L2-02 - Prompt`, a pipeline node identifier,
and rubric r021 requires zero occurrences of it) came back clean on one
LLM call after correctly flagging it on another. A fresh 18-task sample
also returned 0/18 warn versus the original 9/28, consistent with the
check under-firing on borderline signals.

Root cause was the same failure mode row 35's
`fabricated_unfilenamed_fact_check.py` hit and fixed: (1) a "prefer
precision over recall" system-prompt line that suppressed borderline flags,
and (2) an implicit "scan and report what jumps out" methodology a single
LLM call can silently skip on a bad roll. Applied the same two-part fix,
adapted to this check's six structural patterns: replaced both
precision-over-recall lines with recall-positive framing (a candidate flag
is far cheaper than a missed structural defect), and made the methodology
enumerate each of the six patterns explicitly by requiring a
`pattern_review` array in the JSON output (one entry per pattern 1-6,
placed before verdict and findings) so a pattern is never silently skipped.
Also strengthened pattern 4's trigger description to name "node identifier"
and "eval-only vocabulary" (the rubric's own terms) and cross-check
against rubric criteria requiring zero occurrences of those terms, after
verification showed the LLM recognized `L2-02` as a "task identifier label"
but did not connect it to pattern 4 without the explicit term.

Verified with 72 real LLM calls (LLM_BACKEND_FORCE=http, glm-5.2): 16-2-0
went from 0/3 clean to 3/3 warn(p4); the 72-3-0 and 82-2-0 acceptance
tests still flag their original patterns (p2, p5) plus new true-positive
p4 findings; 1-0-0 (known false-positive case) is 2/3 warn, not 3/3, so
not a systematic false positive. A fresh 20-task x3 sweep (60 calls, 0
errors) shows 70% full agreement (status + pattern), 85% status
agreement, 7/10 warned tasks stable on all 3 runs, with the 6
disagreements all borderline (additional pattern on 1/3 runs, or
borderline pattern on 1/3 runs). See ROUND62-ROW28-29-FIX-REPORT.md for
the full per-task table and spot-checks.

## 2026-09-14 (batch runner, on top of the external review coverage add-on)

Adds `run_all.py`: invokes every applicable check in this folder against one `--root` in a
single command and aggregates each script's own JSON report into one `summary.json` plus a
printed table, instead of running ~15 scripts by hand per batch. Read-only by design --
`formula_cache_autofix.py` and `workbook_recalc.py` (both write files) are excluded unless
`--include-autofix` is passed, and even then only in `--dry-run`. Normalizes each script's own
status vocabulary (confirmed by reading real output, not assumed -- e.g.
`answer_key_content_leak_check.py` uses clean/candidate/flagged/error,
`judge_determinism_config_lint.py` uses flag/clean/parse_error/no_determinism_fields_found,
`rubric_text_lint.py` has no per-task status field at all) into a shared "does this need
attention" classification without erasing each script's own reported value from the table.
`rubric_schema_check.py`'s and `duplicate_criterion_check.py`'s divergent CLI shapes (positional
root, `--task`/`--json`; no per-task concept at all, respectively) are handled with dedicated
invocation and normalization paths rather than assuming CLI uniformity. Verified end-to-end
against this repo's own real `pipeline/data/sample_corpus/task_11` fixture, `--all`, explicit
task-id lists, and `--include-autofix`, confirmed to write nothing to disk in dry-run mode.

## 2026-09-14 (external review coverage add-on, on top of the third pass)

Adds coverage for a separate external QC review's remediation list (8.1-8.8; see
`QC-REVIEW-8x-COVERAGE.md` for the full item-by-item disposition), authored as new files
alongside the existing scripts rather than editing any of them: `judge_panel_size_check.py`
(single-model panel-size gap the determinism lint's key-name patterns don't cover),
`criterion_condition_count_check.py` (over-bundled rubric criteria), `invention_detection_input_check.py`
(invention-detection criteria with no source-material visibility), `golden_dependency_reachability_check.py`
(a golden's expected value leaning on an unshipped analysis script), and `workbook_recalc.py`
(retroactive stale-cache patching for already-collected submissions, reusing
`formula_cache_autofix.py`'s logic against an arbitrary directory instead of a task's
`solution/`). All five are v1/uncalibrated -- self-tested against synthetic fixtures and, where
applicable, against this repo's own real `pipeline/data/sample_corpus/task_11` fixture, not run
over a real corpus at scale.

Also fixes the root cause behind two of that review's items directly in the pipeline (not in
this folder): `pipeline/templates/harbor/verifier_lib/sources/xlsx.py`'s `extract_xlsx()` (the
actual per-task grading-sandbox text extractor, shipped verbatim into every bundled task by
`cycle.py bundle`) now recomputes formula cells with the `formulas` engine before falling back
to the on-disk cache, instead of trusting a cache that can be blank/stale even when the formula
itself is correct; `pipeline/gdpval_qc/converters.py`'s `_xlsx_to_text` (Internal QC's own
conversion path) gets the same fix. Every text extractor under `verifier_lib/sources/` (xlsx,
docx, pptx, pdf, csv, md, text) now appends an explicit truncation notice into the returned text
whenever the `max_content_chars` cap actually cuts something, instead of silently returning a
partial document as if it were complete. Both fixes are additive/fallback-safe by construction
(a recompute or truncation-notice failure degrades to the pre-existing behavior, never a hard
failure) and were verified against a synthetic stale-cache workbook and this repo's real
`task_11` fixture respectively -- see `QC-REVIEW-8x-COVERAGE.md` for the verification detail.
## 2026-09-14 (sixth pass, certification gate)

Added `certification_gate_check.py`, the reconciliation-gate step from the SVC-PC/EKW
root-cause synthesis (groups B.6/B.7/C.9): before a task is certified "ready", replay every
completed judge run (`<task>/verifier/reward-details.json`, the Harbor trial layout both the
Oracle pulls and the DataOS model-run extracts use) through the converter repo's own, never-called
hard-gate function `evaluate_release_outcome` (`rubric_xlsx_to_verifier.py:1455`, imported at
runtime, with a verbatim in-file replica run alongside it so drift can never pass silently), and
look the task up in its gate-adjudication record (`<task_id>_qc_validation.xlsx`, local export
only; the Drive pull is NOT wired). Verdict per task: NO RUN / ERROR / BLOCKED (unresolved
`true_positive` gate rows, or the golden itself fails a must-pass gate) / PASS WITH OPEN ITEMS
(a model run BLOCKED by the rubric's gates while the platform paid a nonzero reward, a missing or
unconsulted gate record, run/package mismatch) / PASS. SVC-PC must-pass is detected the only way
the format exposes it, the `must-pass` marker in description prose; EKW reads `metadata.must_pass`
natively (EKW path READ, not yet RAN). Validated on the 56-task reconciled population: 128/128
Oracle runs PASS (the golden passes everything by construction, so Oracle-only certification can
never see this class); 36 of 74 real model runs BLOCKED by their own gates, 35 with a nonzero
platform reward, on 22 tasks; the ground-truth instance SVC-PC-80-7-0 reproduces (rewards 0.7 and
0.6667, failed gates a2/a4/a7/e3 and a2/a4/a5/a7/e3, verdict PASS WITH OPEN ITEMS, not PASS); the
104-file 2026-09-11 qc_validation export BLOCKS 9 of the 56 on unresolved true_positive rows dated
09-11 (whether the 09-12/13 fixes closed them is for the certifier, the record has no build hash,
so the record date is printed next to the count). SVC-PC-88-0-0 has no model-run output on this
machine; its "4 must-pass failed, 0.6628" finding was replayed as a synthetic run only. Raw
`verifications_results.json` is not parsed (no local sample to confirm its shape).

## 2026-09-14 (fifth pass, extraction groundedness)

Added `extraction_groundedness_check.py` (dual-format, mechanism 3 of the SVC-PC/EKW
root-cause plan): does a criterion's required property match what its actual configured
extraction command can see. Closes a false-positive gap `rubric_text_lint.py`'s own docstring
already named but couldn't fix (its `extraction_blind` sub-check has no way to know a
criterion's file is read via `extract_formulas`/`extract_xlsx` instead of blind `extract_text`).
Confirmed directly against real code, not assumed: SVC-PC's judge.toml has no per-criterion
extraction-command field anywhere in the real pipeline (`to_rewardkit.py`/`rewardkit/judges.py`
route every document extension through MarkItDown unconditionally, keyed only on file suffix;
the formula-aware path exists but is architecturally unreachable since SVC-PC never emits
`assertion.type=="deterministic"`), so SVC-PC criteria are graded against a fixed constant
(`SVC_PC_FIXED_COMMANDS`), while EKW criteria are graded against their own real `commands` field.
Validated against the two motivating criteria (SVC-PC-1-1-0 `str-01`, SVC-PC-7-3-0 `st5`) --
neither matched by `rubric_text_lint.py`'s own pattern list, which this script's
`EXTRA_BLIND_PATTERNS` supplements. Full-corpus run found and fixed three real false-positive
classes before shipping: a fixed grading-tolerance idiom ("Tolerance: within 0.0%..."), a
literal business value that happened to read "0.0%", and a criterion (SVC-PC-58-6-0 `c13`) that
had already correctly disclaimed its own extraction-blindness in its own text -- the last one
guarded by a new `BLINDNESS_DISCLAIMED_RE`, mirroring `rubric_text_lint.py`'s own
`meta_rubric_knowledge` negation convention. Full-corpus numbers: SVC-PC 150/600 tasks flagged
(466 findings); EKW 4/274 confirmed + 7 correctly suppressed by the command-aware gate -- that
4+7=11 and the 7-suppressed count match `rubric_text_lint.py`'s own documented "11 raw hits, 7
false positives" finding on the same corpus almost exactly, direct corroborating evidence the
command-awareness fix does what it was built to do. Explicitly out of scope, recorded rather than
silently absorbed: judge FILE-scope adequacy (which files are graded at all, e.g. SVC-PC-92-0-0's
finding that the judge sees only the response doc, never the source corpus) is a different
mechanism (breadth vs. this script's depth) and needs its own check.

## 2026-09-14 (fourth pass, EKW)

Added `ekw/`: EKW's Check B and translation layer (`ekw_check_b.py`) and a runner
(`ekw_run_checks.py`) that runs Check B plus all 12 shared checks over an EKW harbor tree and
merges them into one per-task table with B/C/D/E roll-ups. Calibrated on all 274 tasks of the
2026-09-10 EKW drop: seven `verifier.json` source shapes plus `task_FIN-177`'s foreign schema,
two build genres (180 native-harbor, 94 rewardkit-hybrid) in one layout, four graded-path
conventions, goldens with cp437-mojibake names (`task_653`, a real build defect on the DataOS
path). Fixed `pipeline/tools/rewardkit_convert.py`'s validator, which only looked for
`tests/deliverables/judge.toml` and so failed nearly every chunked EKW conversion. No shared
check was modified; the runner reconciles `environment_input_check.py`'s pattern-1 hits on EKW
(prompts name deliverables, not inputs) and records that it did.

## 2026-09-14 (third pass)

Mechanized structural-audit patterns 1, 3, 4, and 5 (patterns 2 and 6 were already mechanized):
added `environment_input_check.py` and `answer_key_leakage_check.py`. Closed a gap
`duplicate_criterion_check.py`'s own docstring named: added `judge_criterion_name_duplicate_check.py`.
Extended `deliverable_filename_check.py` with a REVERSE direction (instruction commands a filename
judge.toml doesn't grade) and `rubric_schema_check.py` with a third `placeholder_expected`
detector. Added `answer_key_content_leak_check.py` (a deliberately low-confidence candidate-for-
review tool) and `judge_determinism_config_lint.py` (a multi-schema prober for judge-score
determinism). Driven by two external QC reviews (Jafar Muhammadi's manual SVC-PC task-integrity
review, and Andrew Ma's team's Perplexity Benchmark QC across EKW/CompanyBench/ComputerBench) --
full findings, coverage matrix, and roadmap in the new `PERPLEXITY-QC-FINDINGS.md`. Every new/
extended check calibrated and verified against the current state of the real 600+ task SVC-PC
corpus, not assumed from either review's original text.

## 2026-09-14 (second pass)

Added `rubric_schema_check.py` (Check D2: rubric weight-sum validation, blank/stub criterion
detection, ported from the source pipeline's orphaned `svc_verify_package.py`),
`deliverable_filename_check.py` (Check D promoted from a disposable scratch file, tomllib parser
fix), `duplicate_criterion_check.py`, `deliverable_integrity_check.py`, a generic Check-A
content-audit skill, a Check-B build-contract spec, and four v0/unvalidated Phase-3 checks
(`v0-checks/`).

## 2026-09-14 (first pass)

Extracted and generalized the formula-health-check + cache-autofix script pair and the
structural-audit six-defect-pattern taxonomy from an SVC-PC QC pipeline. Added README.md
(capability table + honest caveat) and GAP-ANALYSIS.md (10-item gap list with sequencing).
