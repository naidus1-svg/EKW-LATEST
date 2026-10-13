# External QC findings: what they taught this folder, and what's built now

Two independent adversarial QC reviews landed the same week, on unrelated task pools, and pointed
at the same root cause: **verifier/rubric brittleness, not task design, is the dominant defect
class.** This doc records what each review found, which findings this folder can now catch
mechanically, and which ones still need an LLM or a person reading text. Nothing in this folder
touches the reviewed benchmarks themselves; the corpus this folder's own checks are calibrated and
verified against is the unrelated SVC-PC benchmark, used purely as a source of real Harbor-shaped
task packages.

## Review 1: manual task-integrity review (Jafar Muhammadi, SVC-PC pool22 + GDM5, Sept 2026)

31 SVC-PC tasks reviewed by hand. Every finding fell into one of six shapes, and all six were
**already named**, as an LLM-judgment methodology, in this folder's own `structural-audit/SKILL.md`
before this review was read -- the skill's own "Source-project example" text for pattern 2 reads
almost verbatim like the review's SVC-PC-7-4-0 finding. What was missing was not the taxonomy; it
was that patterns 1, 3, 4, and 5 had never been mechanized the way patterns 2 and 6 already had
(`deliverable_filename_check.py`, `deliverable_count_check.py`). That gap is now closed -- see the
coverage matrix below.

## Review 2: Perplexity Benchmark QC (Andrew Ma's team, EKW Bench / CompanyBench / ComputerBench,
20 tasks each, Sept 2026)

**Headline numbers:** verification was the primary defect on 48 of 60 tasks (80%), more than task
design and environment combined. Only 1 of 60 tasks rated "sound." The single most common finding,
present on 54 of 60 tasks, was an undisclosed formatting/ordering/column convention: a rubric
silently requires a presentation choice the instruction never states, so a substantively correct
answer is marked wrong. The single most damaging individual defect (critical severity): an entire
task's grade decided by ONE LLM-judge sample at temperature 1.0, no panel, no majority vote --
literally not reproducible run to run.

**Critical, and worth stating plainly: none of the three reviewed benchmarks use this folder's
`judge.toml` + `[[criterion]]` config shape.** EKW Bench uses `tests/verifier.json` (JSON, a
`verifiers` dict keyed by name, an `assertion.rubric.prompt` free-text field, and a confirmed
`config.temperature` field -- this is where the temperature=1.0 finding was quoted from,
verbatim). CompanyBench uses `tests/manifest.json` (JSON, a `verifier_configs` array,
`scoring.weights`, a `flat_verifier_scoring` function whose actual behavior can silently ignore
the declared weights entirely). ComputerBench uses `tests/verifier.json` too, but shaped
differently again -- a `verifiers` dict where each entry's `assertion.expected` is a **regex
pattern string**, graded via pytest, with no LLM-judge layer visible at all in what was reviewed.
Three benchmarks, three incompatible schemas. A check built against any one of them does not
transfer to the others without a new parser. This repo's own checks below are built against the
SVC-PC judge.toml shape; `judge_determinism_config_lint.py` is the one exception, deliberately
built as a multi-schema prober so it degrades honestly (reports "not exposed" rather than a false
pass) against a config shape it doesn't recognize.

## Coverage matrix: every named defect shape vs. what catches it today

**Legend:** ✅ mechanized, zero LLM, built and verified this session · 🔶 exists as an LLM-judgment
skill pattern (structural-audit or content-audit), not yet mechanized · 🧭 not mechanically
detectable in general (needs a person or LLM reading free text) · — no real signal in this folder's
own corpus to build/calibrate against yet (schema-specific to the reviewed benchmarks)

| Defect (Jafar's plain description / Andrew's code) | Status | What catches it |
|---|---|---|
| Instruction names a specific input file that doesn't exist in the environment (Jafar: "Missing, promised in instruction.md" -- present on nearly every reviewed SVC task) | ✅ | `environment_input_check.py`, pattern 1. 20 real defects found and confirmed across the SVC-PC corpus (e.g. `SVC-PC-1-5-0` names two files that exist nowhere; the `SVC-PC-13-3-0` family names one consolidated file where only 4 per-quarter files ship). |
| A "Files / Connectors" field is a bare cloud-storage folder URL, never hydrated locally (Jafar: "External dependency") | ✅ | `environment_input_check.py`, pattern 3. 5 real defects confirmed (`SVC-PC-1-1-0/1-2-0/1-5-0/1-7-0/54-0-0`). |
| A `_no_input_files_required`-style placeholder coexists with the instruction naming specific required files (Jafar: "Contradiction") | ✅ | `environment_input_check.py`, pattern 5. Zero real positives remain in this folder's own corpus (all 6 placeholder-marker tasks checked by hand were genuinely input-free) -- confirmed via a synthetic fixture instead, since the real corpus has already been cleaned of this one. |
| Instruction commands the solver to produce filename X; the verifier reads a completely different filename (Jafar: SVC-PC-7-4-0 exactly -- "an agent that follows instruction.md exactly writes two files the judge never opens and scores 0") | ✅ | `deliverable_filename_check.py`, REVERSE direction (new). 26 real REVERSE-only failures + 2 both-fail extension-typo cases found in the corpus (`SVC-PC-6-0-0`, `SVC-PC-10-0-0`, `SVC-PC-59-0-0`, the `SVC-PC-96-*` family, and more). |
| Deliverable filename/format/count never specified anywhere, verifier expects a specific shape anyway (Jafar: "Not specified in instruction.md," present on most reviewed tasks) | ✅ (count) / 🔶 (format) | `deliverable_count_check.py` (count, calibrated on the full 600-task corpus, 89/6/505 pass/fail/skip). Format-diversity (a csv/xlsx/docx mix never mentioned) has no dedicated script yet -- flagged as a roadmap item below. |
| Every criterion in a rubric carries "Expected: ." with no actual value (Jafar: SVC-PC-1-1-0, 1-2-0, 1-5-0, 7-2-0, 7-4-0, 7-6-0, 14-1-0, 14-3-0, 14-6-0 -- all their criteria, verbatim) | ✅ | `rubric_schema_check.py`, new `placeholder_expected` detector. Those 9 named tasks are already fixed (checked directly, all now carry real values) -- but the defect is real TODAY in a different population: **1,467 criteria across 38 other tasks**, worst cases `SVC-PC-66-0-0`/`60-0-0`/`61-0-0`/`62-0-0`/`96-0-0` at 100-110 flagged criteria each. |
| A literal `GOLDEN`/reference-solution filename the solver is told to produce, or internal pipeline directive text leaked into the prompt (Jafar: SVC-PC-7-4-0's `..._GOLDEN.xlsx` and `[Sequence AFTER the node's apex gdpval_fit HOLD is adjudicated.]`; Andrew AR-11) | ✅ | `answer_key_leakage_check.py` (new). SVC-PC-7-4-0's own specific instance has since been fixed (confirmed by direct read), but the pattern is real elsewhere TODAY: **12 tasks** in the `SVC-PC-88-*` and `SVC-PC-90-*` families, all with a `..._Golden_...` graded filename template. Zero false positives on the flagged set. |
| A rubric's own literal expected value (not just a filename) leaks verbatim into a file the solver can read (Andrew AR-11, both EKW and CompanyBench) | ✅, low-confidence by design | `answer_key_content_leak_check.py` (new). Shipped as a candidate-for-review tool, not a gate -- a naive "value appears anywhere" check produced 12-873 hits per task on legitimate source documents that are SUPPOSED to state the task's control totals. Gated on suspicious file naming + content match together; zero real leaks found in this corpus (all 35 naming-token hits were genuine unrelated business files, individually confirmed). |
| Two `[[criterion]]` blocks in the same judge.toml share a `name`, silently colliding if anything downstream keys criteria by name (adjacent to Andrew's AR-08, and a gap `duplicate_criterion_check.py`'s own docstring explicitly named) | ✅ | `judge_criterion_name_duplicate_check.py` (new). Zero real collisions in this corpus today (confirmed by an independent cross-checked grep, matching exactly) -- verified instead via synthetic fixtures for both the per-file and cross-file scopes. |
| An LLM-judge criterion's entire grade rests on ONE sample at nonzero temperature with no panel/majority fallback (Andrew PX-01, marked CRITICAL, the single most damaging finding in the whole review) | ✅ for schemas that expose it / explicit "not verified" otherwise | `judge_determinism_config_lint.py` (new, multi-schema). SVC-PC's own `judge.toml` shape exposes NO temperature/panel field anywhere -- every one of 2,252 real judge.toml files reports `config_exposes_no_determinism_control` rather than a false "clean." If this benchmark's determinism setting lives at the harness level instead of per-task, this check cannot see it, and says so explicitly rather than implying safety. |
| Rubric's exact-cell/value assertions are hardcoded to the reference workbook's own specific layout, not to the required content (Jafar: 12-1-0/12-2-0, "48 of 50 criteria are exact cell assertions... the agent must reproduce the golden file's sheet name and cell layout, not the analysis"; Andrew AR-09) | 🔶 | Not yet a dedicated script. `rubric_text_lint.py`'s three checks and `formula_health_check.py`'s new heuristics catch adjacent shapes but not this one directly. Flagged as the top roadmap item below. |
| A rubric criterion claims a specific tab exists at a specific position; it doesn't match the real golden (structural-audit-adjacent, a formatting/convention defect in Andrew's PX-02 family) | ✅ | `tab_naming_check.py` (built earlier this session). 8/8 real defects confirmed (`SVC-PC-65-*`, `SVC-PC-44-*` families). |
| A criterion's language names a file format the task's actual deliverable doesn't ship (Andrew PX-06 / stale-convention family) | ✅ | `rubric_text_lint.py`'s `stale_format_mismatch` (built earlier this session). |
| A criterion asks about something a text-extraction-based judge structurally cannot see -- cell formatting, protection, hidden state (Andrew PX-02's documented mechanical sub-case: "the grader reads the handout only as extracted text... those thresholds... appear in what the agent is told" but not in what the judge can perceive) | ✅ | `rubric_text_lint.py`'s `extraction_blind` (built earlier this session). |
| A criterion demands the deliverable claim knowledge of its own grading rubric (e.g. "all 50 criteria pass, 100/100") | ✅ | `rubric_text_lint.py`'s `meta_rubric_knowledge` (built earlier this session). |
| Missing-sheet-qualifier formula bug: a formula silently resolves a same-sheet reference where a cross-sheet one was intended, producing a real, wrong, non-error number | ✅ | `formula_health_check.py`'s new `mixed_qualifier_smell` / `out_of_bounds_unqualified_ref` heuristics (built earlier this session), verified against the exact cells previously identified in `SVC-PC-58-2-0` and `SVC-PC-78-6-0`. |
| Prompt explicitly forbids inventing content; a rubric criterion requires exactly that invented content (or two criteria in the same file contradict each other on sourced-vs-invented) | 🔶 | `content-audit/SKILL.md` pattern 6, independently re-derived and confirmed against `SVC-PC-35-2-0`/`35-4-0` -- an LLM-judgment skill, not a script; two of two real tests correct is a track record, not a calibrated rate. |
| Rubric pins one exact value/format where a range or alternate is equally correct (Jafar's implicit case in several tasks; Andrew AR-07, present on 44 of 60 reviewed tasks) | 🧭, with a mechanical pre-screen | Genuinely needs judgment (is the alternative truly equally defensible?). A cheap mechanical pre-filter is possible -- flag any criterion with a whole-line/file regex anchor, a hardcoded decimal literal with no tolerance, or an exact-match check on a numeric field with no format normalization -- and route the candidates to a human/LLM pass. Not built yet; roadmap item below. |
| Two rubrics pin mutually exclusive answers, or the source material genuinely supports two valid readings (Andrew AR-04, present on 41 of 60 tasks) | 🔶 (partial) / 🧭 (core judgment) | `content-audit/SKILL.md` pattern 4 already covers the same-judge-file contradiction shape as an LLM-judgment check. The cross-document "which reading is genuinely defensible" question needs a person or LLM regardless. |
| Instruction admits more than one reasonable reading of a key term (Andrew AR-03) | 🧭 | No static signal substitutes for reading the prose. A keyword screen for vague qualifiers was tried in reasoning and rejected as noise-dominated. |
| Undisclosed formatting/ordering convention causes a correct answer to score wrong (Andrew PX-02, the single largest defect cluster: 54 of 60 tasks) | 🧭, with narrow mechanical sub-cases | The general "instruction never states X" claim is a negative-existence claim over free text -- this org's own hard rule says one absent read is not proof of absence, so it needs a person or LLM. A narrow, real, buildable sub-case: when a verifier's declared evidence-reading mode is text-extraction/values-only and the rubric demands something structurally invisible in that mode (an image, a live formula, cell formatting), that IS a pure structural contradiction -- already covered for THIS repo's own package shape by `rubric_text_lint.py`'s `extraction_blind`. |
| Reference/golden answer doesn't actually pass its own rubric when honestly graded (Andrew AR-16, the strongest "just run it" case across all three reviewed benchmarks) | 🔶 (roadmap, already scaffolded) | This is exactly what an Oracle-style run on the golden already checks -- and what `v0-checks/golden-reproducibility/SKILL.md` (built 2026-09-14, still v0/unvalidated) is meant to formalize. Not re-scoped by this session; the external review is strong independent evidence this item deserves priority over other v0/roadmap work. |
| Declared config (weights, scoring mode) doesn't match what actually computes the reward (CompanyBench's `VERIFIER-DECLARED-WEIGHTS-UNUSED`, `VERIFIER-UNREACHABLE-CEILING`) | — | Schema-specific to CompanyBench's `manifest.json` + its `flat_verifier_scoring` function; SVC-PC's `judge.toml` has no equivalent "declared vs. actually-applied" split to check (the `[scoring] aggregation = "weighted_mean"` line is the only aggregation rule, and it's the one actually used). Cannot be calibrated against this folder's own corpus. Documented, not built. |
| A verifier declares a criterion type not in an allowed set (`VERIFIER-TYPE-NOT-ALLOWED`) | — | Same reasoning -- SVC-PC's `judge.toml` only ever uses `type = "binary"`; there is no allowed-type list to check against in this schema. Documented, not built. |
| Judge model is the same model as the solver (self-grading bias) | — | Not checkable from this folder's own `judge.toml` shape without knowing the solver's model out-of-band; no real corpus signal to calibrate against. Documented, not built. |
| Run-to-run grading flip on identical input (Andrew's STABILITY-* codes, CompanyBench: 13 of 88 tasks flipped a verdict on a frozen answer, batch3-only) | 🔶 (mitigated by process, not a script) | This is exactly the failure mode this org's OWN process already guards against structurally: Check C requires 2 independent passes to agree, Check F (Oracle) requires 2 independent runs to agree, before either counts as trusted. Worth stating plainly rather than silently assuming it's covered: that discipline is a PROCESS rule, not a script, and it only helps if it's actually followed every time. |
| Spelling/grammar errors in instruction or rubric text (Andrew AR-01) | 🧭, trivially automatable | Not built this session -- a standard spellchecker/grammar linter (`pyspellchecker`, `language-tool-python`) over `instruction.md` and criterion descriptions would close this in under a day. Lowest-effort item on the whole list; flagged as a quick win below, not built only because it adds a new pip dependency and nobody has decided whether this folder takes on non-stdlib deps yet (every check so far is stdlib + `openpyxl`, already an existing dependency). |

## What this means for "our repo" vs. SVC specifically

Every ✅ item above is now a real, generic, zero-LLM script in this folder, calibrated against SVC-PC
purely because that's the only real Harbor-shaped corpus available to test against -- none of it
is SVC-specific logic, and none of it was built to fix any particular SVC task. The 🔶 items are
real, named LLM-judgment patterns already living in `structural-audit/SKILL.md` or
`content-audit/SKILL.md` -- promoting any of them to a script is future work, not a currently
missing idea. The 🧭 items are the honest ceiling: no static check substitutes for a person or an
LLM reading prose to judge ambiguity, defensibility, or realism, and claiming otherwise would be
the same overclaiming this folder's own `README.md` caveat already warns against.

## Roadmap, ranked by expected value given what both reviews actually found

1. **Hardcoded-cell / gold-path-only rubric detector.** Strip regex/exact-match structure from a
   criterion's expected value, check whether it's byte-identical to the reference workbook's own
   specific cell layout (not just its content), and flag rubrics that are overwhelmingly this
   shape. Directly matches Jafar's 12-1-0/12-2-0 findings (48 of 50 criteria are exact cell
   assertions) and Andrew's AR-09 across all three reviewed benchmarks. Highest-value unbuilt item.
2. **Regex-rigidity / over-strict pre-screen** (Andrew AR-07/AR-04, PX-02's mechanical sub-cases).
   Ship as a candidate-generator, not a gate, matching `answer_key_content_leak_check.py`'s own
   precedent for a check whose false-positive rate can't be driven to zero.
3. **Spellcheck/grammar lint** (Andrew AR-01). Lowest effort, needs a dependency decision first.
4. **Golden-reproducibility v0** (already scaffolded, `v0-checks/golden-reproducibility/SKILL.md`)
   deserves promotion ahead of other v0 items given how strongly Andrew's AR-16 findings (across
   all three benchmarks) corroborate that "does the gold actually pass its own rubric" is a real,
   recurring, high-value gap.
5. **Deliverable-format-diversity check** (a csv/xlsx/docx/json mix in `judge.toml`'s `files=`
   never mentioned in `instruction.md`) -- a natural sibling to `deliverable_count_check.py`, not
   yet built.

## Sources

- `ekw_quality_issues.md`, `companybench_quality_issues.md`, `computerbench_quality_issues.md`
  (Perplexity Benchmark QC, Andrew Ma's team, read in full, 20 tasks/benchmark stratified sample).
- Jafar Muhammadi's two PDF task-integrity reviews, `QCR_SVC_pool22_09092026` (22 tasks) and
  `QCR_SVC_GDM5_09082026` (10 tasks), read in full.
- Every ✅ finding above was independently re-verified against the CURRENT state of the SVC-PC
  corpus (`C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready`, 600+ tasks) at build time, not
  assumed from either report's original text -- several of Jafar's specific named tasks have
  already been fixed since his review and are reported as such above, not silently re-flagged.
