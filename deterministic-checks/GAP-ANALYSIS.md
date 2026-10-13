# Gap analysis: what a comprehensive pre-grading QC framework is still missing

The three pieces in this zip (formula health check + autofix, structural-audit taxonomy) are
real and generic, but they don't add up to comprehensive QC on their own. Below is a specific,
evidenced list of what's missing, why it matters, and a realistic sequencing for closing the
gaps -- written so "what's missing" has a concrete answer instead of a verbal one.

## The gaps

| # | Missing check class | Relation to what exists | Why it matters |
|---|---|---|---|
| 1 | Rubric schema & weight-sum validation | Exists already in the source pipeline (`svc_verify_package.py`) but is not wired into the check taxonomy [verified: read of tools/svc_qc_tracker_build.py's CHECK_META dict and tools/svc_verify_package.py, 2026-09-14] -- an orphaned tool | Catches blank/stub criterion descriptions and per-file grading-weight mismatches. Already-built, close to zero-cost to integrate. |
| 2 | Duplicate criterion-ID detection | Adjacent to #1, a blind spot #1 doesn't cover | Two rubric rows sharing an ID silently collapse in a dict keyed by ID; if the resulting weight error happens to cancel out, a weight-sum-to-1.0 check still passes even though a criterion's weight was silently dropped. Confirmed root cause of at least one real task's Oracle failure in the source project. |
| 3 | Cross-file reference resolution (three-way + orphaned files) | Extends the structural-audit taxonomy, which today is one-directional (only catches a prompt naming a file that's missing) | Nothing currently confirms a verifier-named file actually exists on disk independent of matching prompt text, and nothing flags environment files that exist but are referenced by nobody (dead corpus files, or evidence the wrong file version got staged). |
| 4 | Duplicate / near-duplicate task detection | New axis. The content-audit layer's own scope is within-task consistency [verified: content-audit CHECK_META entry, tools/svc_qc_tracker_build.py, 2026-09-14], not cross-task comparison | Two tasks built from the same source material with near-identical prompts/rubrics inflate the apparent task count and let a solver or judge effectively "solve once, get credit twice." |
| 5 | PII / document-metadata scanning | New. Distinct from the structural-audit's pattern-4 leakage check, which only catches *grading-pipeline* leakage (golden filenames, internal build labels), not privacy leakage | Real corpus documents (financial, HR, or operational records used to build tasks) can carry author names, revision history, and comments in their native file metadata that no current check opens or scans. |
| 6 | License / copyright / provenance scanning | New, zero coverage today | Cheap to scaffold now (a provenance-manifest convention + a check that every environment file is accounted for), even where it's currently a no-op -- much cheaper than retrofitting after external distribution once a benchmark pulls in real third-party/licensed source documents. |
| 7 | Judge-injection / prompt-injection scanning | New. Distinct from pattern-4 pipeline leakage -- this is about adversarial or corrupted text, not accidental metadata leakage | A source document ingested wholesale into the environment, or a corrupted prompt, could contain injection-shaped text (e.g. "ignore previous instructions," hidden characters, embedded encoded payloads) that reaches a judge model's grading context unchecked. |
| 8 | Deliverable file integrity / openability check | Extends the formula-health check's spirit beyond spreadsheet formula cells to whole-file corruption of ANY claimed deliverable format | Nothing currently confirms a `.docx`/`.pdf`/other deliverable actually opens/parses cleanly, only that spreadsheet formulas recompute. This generalizes the same "don't trust the file just because it exists" instinct the formula-health check already applies, to every deliverable type. |
| 9 | Verifier/judge-config smoke test | New, strictly pre-grading | Confirms a judge/verifier config file actually parses and instantiates without error, and that its referenced grading logic/tools are present, BEFORE spending an expensive grading run on a config-level bug. |
| 10 | Deterministic golden-answer reproducibility | New, and distinct from an Oracle-style check (which grades a golden answer against its own rubric -- a self-consistency check, not independent proof) | Checks whether an independent solver, given ONLY the environment inputs, would actually arrive at the same golden answer. The most rigorous and most expensive item here -- scope as a 5-10% sample spot-check, not exhaustive, and build it last. |

## Sequencing -- status as of 2026-09-14 (updated same day, third pass)

**Done:** the formula-health/autofix pair and structural-audit taxonomy (extracted, generalized,
proven at scale in the source project). #1 (`rubric_schema_check.py`), the Check-D promotion
(`deliverable_filename_check.py`, with the regex-to-tomllib parser fix -- the old regex produced
wrong verdicts on at least 7 of 8 spot-checked tasks), #2 (`duplicate_criterion_check.py`), and
#8 (`deliverable_integrity_check.py`) are now built and smoke-tested (`--help` runs clean on
each; `rubric_schema_check.py`'s logic additionally verified byte-identical to its source on a
fixture; `deliverable_filename_check.py` verified against 10 real task directories). A generic
Check-A content-audit skill and a Check-B build-contract spec were also written (both new, not
extracted from a proven source -- see their own files for maturity notes).

**v0, built today, explicitly unvalidated (do not trust output as a verdict yet):** #4
(`v0-checks/duplicate_task_detector_v0.py`), #5 (`v0-checks/pii_metadata_scanner_v0.py`), #7
(`v0-checks/injection_scanner_v0.py`), #10 (`v0-checks/golden-reproducibility/SKILL.md`). Each
states its own unvalidated status verbatim in its docstring/output and needs calibration against
real labeled examples, a policy decision, a real threat model, or a real trial run (respectively)
before its findings should be trusted rather than just reviewed.

**Second-pass additions (2026-09-14, same day), driven by two external QC reviews -- see
`PERPLEXITY-QC-FINDINGS.md` for the full evidence trail and coverage matrix.** #1's structural-audit
sibling patterns (2 and 6 were already mechanized; **patterns 1, 3, 4, 5 are now mechanized too**):
`environment_input_check.py` (patterns 1/3/5), `answer_key_leakage_check.py` (pattern 4). Extends
to #2 and #8's adjacent blind spots: `judge_criterion_name_duplicate_check.py` (the exact gap
`duplicate_criterion_check.py`'s own docstring named -- judge.toml `[[criterion]].name` collisions,
a different data shape than the xlsx `id` column that script covers), `deliverable_filename_check.py`
extended with the REVERSE direction (instruction commands a filename that judge.toml does not
grade -- found 26 real cases the forward-only check missed), `rubric_schema_check.py` extended
with a third `placeholder_expected` detector (found 1,467 real criteria across 38 tasks),
`rubric_text_lint.py` / `tab_naming_check.py` / `deliverable_count_check.py` (new, mechanize
several PX-02/PX-06-family undisclosed-convention sub-cases), `answer_key_content_leak_check.py`
(a new, deliberately low-confidence candidate-for-review tool, not a gate -- see its own docstring
for why a naive version couldn't be shipped as one), and `judge_determinism_config_lint.py` (#9,
partially -- a multi-schema prober for the single most damaging defect either review found: a
judge score decided by one nonzero-temperature sample with no panel; explicitly reports "not
exposed" rather than a false pass against a config shape, like this folder's own SVC-PC judge.toml,
that does not expose the field at all).

**Third-pass addition (2026-09-14, later the same day): EKW cross-benchmark port.** 9 of the
checks above (`rubric_schema_check.py`, `deliverable_filename_check.py`,
`duplicate_criterion_check.py`, `judge_criterion_name_duplicate_check.py`, `rubric_text_lint.py`,
`tab_naming_check.py`, `deliverable_count_check.py`, `environment_input_check.py`,
`answer_key_content_leak_check.py`) are now ported and verified against a second real benchmark
corpus -- EKW, 274 tasks at `C:\ekwqc\_merged274\files\` -- each cross-checked against a real
SVC-PC corpus with confirmed zero regressions. `judge_determinism_config_lint.py` needed no code
changes at all; a full run against the 274-task EKW corpus [verified: judge_determinism_config_lint.py
executed over the full 274-task EKW corpus, not just read, 2026-09-14] found 269 tasks with
`temperature_found_no_panel` -- the same reproducibility gap #9 flags, now confirmed on a second
corpus, and a real finding worth surfacing to whoever owns EKW's judge/grading config, separate
from the porting work itself. A 10th script, `formula_health_check.py`, is ported, code-complete,
and gained native `--jobs` parallelism, but its full-274 EKW sweep is still running in a peer
session as of this writing -- treat it as unverified until that number lands. A new shared parser
module, `ekw_verifier_json.py`, reads EKW's `tests/verifier.json` schema into the checks' shared
intermediate shape: 274/274 clean parses, 0 crashes, 0 parse errors, across 7+ real schema
variants. This turns "built generic on purpose" into measured fact for the 9 (soon 10) checks
involved. Its direct bearing on the gap table above is narrow: gap #9 (verifier/judge-config
smoke test) is the only row it touches, and only partially -- the other nine gap classes are
unaffected by this pass.

**Still not started, real design work (weeks, not hours):** a shared intermediate output schema
so every check's results fold together generically instead of via hand-written per-run merge
logic, the rest of #3 (cross-file reference resolution beyond what environment_input_check.py now
covers), the rest of #9 (config-vs-actually-applied-behavior consistency diffing, which needs a
benchmark's own reward-computation code alongside its declared config -- schema-specific, and
CompanyBench's own review found this exact gap costing real reward-share via an inert
`scoring.weights` field), and #6 (license/provenance scanning -- needs a manifest convention
agreed across teams before code is useful). New, not on the original 10-item list: a hardcoded-
cell/gold-path-only rubric detector (the single highest-value unbuilt item per both external
reviews -- see `PERPLEXITY-QC-FINDINGS.md`'s roadmap section) and a regex-rigidity/over-strict
pre-screen for the AR-07/AR-04/PX-02 family.

**2026-09-14, external review coverage add-on:** a separate external QC review's 8.1-8.8
remediation list is fully triaged in `QC-REVIEW-8x-COVERAGE.md`. Two items were root-caused
directly in the pipeline rather than merely detected (8.1's grading-time formula blindness in
`pipeline/templates/harbor/verifier_lib/sources/xlsx.py`, 8.4's silent truncation across every
extractor in that same folder). New checks close 8.2's single-judge-panel gap
(`judge_panel_size_check.py`), 8.6's over-bundled-criterion gap
(`criterion_condition_count_check.py`), and 8.7's judge-can't-see-the-source gap
(`invention_detection_input_check.py`); 8.3's failure shape gets a generalized check
(`golden_dependency_reachability_check.py`) alongside a new retroactive tool for already-
collected submissions (`workbook_recalc.py`). 8.5 was explicitly dropped for this pass (needs a
new source command + numeric comparator support, not attempted here); 8.8 needed no new work
(already the standing purpose of the existing Check C/D scripts).
