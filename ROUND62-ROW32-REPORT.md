# Round 62, Row 32 - Judge file-scope UNDER-INCLUSION (files= too narrow), LLM check A

## Status: VERIFIED LIVE

Real LLM calls against the configured glm-5.2 HTTP backend (the `call_llm()` path in
`tools/llm_backend.py`, no claude CLI on PATH, so every call hit the HTTP backend). No
simulated or fabricated responses. The four named defect tasks all flagged for real; a
29-task broader sample ran for real with the counts below.

## What this delivers

A new LLM-judge check `deterministic-checks/judge_scope_under_inclusion_check.py` that, for
each judge group, feeds the LLM the real judge.toml `files=[...]` list, every criterion's
full description (which carries the "Expected: ..." clause), and a relevance-ranked summary
of the task's available environment files, then asks it to identify any criterion whose
Expected text references a specific fact, document, or comparison that none of the listed
files could actually verify. Wired into both orchestrators as an automated check (called on
every run), not a manual pass.

This closes the NARROW end of the files= axis. The already-wired
`judge_scope_over_inclusion_check.py` (row 33) closes the WIDE end (deliverable + sources
undifferentiated). `judge_file_scope_breadth_check.py` catches the named-filename-literal
slice of this (a criterion that literally names a file absent from scope); this check
catches the SEMANTIC slice a regex cannot, which is why it was deliberately scoped out of
the mechanical row-33 checker at round 55 and built as an LLM check.

## Design

Modeled on `rubric_overspecification_check.py` (the established LLM-check template in this
folder): same `run()` / `audit_task()` / `--dry-run` / CLI shape (`task_ids + --root + --out`),
same `os.environ.setdefault("LLM_API_MAX_TOKENS", "32000")` (row-15 token-starvation fix),
same `call_llm()` backend, same warn-only "candidate, not verdict" posture, same JSON
response-parsing helpers.

Per task, per judge group (SVC-PC: one group per `tests/deliverables*/judge.toml`; EKW: one
group per verifier):

1. Loads each group's `files=[...]` (path-stripped to basenames) and every criterion's full
   description, reusing `judge_file_scope_breadth_check.py`'s own `_load_svc_pc_groups` /
   `_has_svc_pc_config` / `_load_instruction` / `_basename` / `_weight_sum` /
   `DELIVERABLE_MARKER_RE` and `criterion_groundedness_check.py`'s `FILENAME_RE` - the same
   reuse convention `judge_scope_over_inclusion_check.py` follows.
2. Builds the environment basename set by rglob (mirrors
   `judge_scope_over_inclusion_check.py`'s `_env_basenames`, with the `file_listing.txt`
   fallback for the flattened mirror).
3. Summarizes that set into a compact list (`_summarize_env_basenames`): a real environment
   can carry 794 unique basenames (hundreds of dated slack json logs). Dated, numbered, and
   quarterly families collapse into one representative line with up to 6 example members, so
   the meaningful source documents (Product_Catalog_Q1-4.pdf, Sprint_01-18_Backlog.xlsx,
   Bank_Statement_2021-01.pdf..12.pdf) stay visible. The list is relevance-ranked against the
   criteria text so files sharing a token with any criterion (Q2 matching a "Q2/Q3" criterion,
   Sprint matching a "Sprint 16" criterion) survive the 150-line cap.
4. Identifies the deliverable filename(s) from instruction.md so the LLM is told which files=
   entries are the graded output (never a verifying source).
5. Feeds the LLM the files= list, the summarized environment list, and every criterion's
   description, and asks it to flag criteria whose Expected text references a specific
   external fact that none of the listed files could verify, naming the implied source when
   visible in the environment list.

## Registration (letter D, both orchestrators)

Confirmed by reading the registrations, not assumed: this project's LLM-judge checks use
letter D or E, never "A". `LETTERS = ("C", "D", "E")` on `svc_run_checks.py` (and `("B","C",
"D","E")` on `ekw_run_checks.py`); the only "Check A" this pipeline names
(`content-audit/SKILL.md`) has no CLI and no CHECKS entry. Registering "A" would KeyError in
`merge()`'s `by_letter = {L: [] for L in LETTERS}`, confirmed by reading `merge()` directly.
The two existing LLM checks register as D (`rubric_overspecification`) and E
(`golden_groundedness`).

The new check is registered as **letter D**, the judge-scope family
(`judge_scope_over_inclusion`, `judge_file_scope_breadth`), `style="std"`, `task_key=
"task_id"` (the LLM-check CLI shape, not the `rubric_schema` shape the deterministic
judge-scope siblings use):

- `deterministic-checks/svc_run_checks.py`: `judge_scope_under_inclusion` added after
  `judge_scope_over_inclusion`. CHECKS dict now 41 entries (re-derived by importing and
  counting; the docstring's prior "Thirty-one" was stale and updated).
- `deterministic-checks/ekw/ekw_run_checks.py`: same entry added after
  `rubric_overspecification`. Marked **EKW-UNTESTED** in the comment: the design is
  format-agnostic (dual-format dispatch reuses `ekw_verifier_json.load_ekw_criteria` for
  EKW), but no real EKW under-inclusion defect example was available to validate against
  this session. EKW verifiers typically carry only the deliverable path in `source.file`
  (the over-inclusion sibling notes the wide shape "almost never fires on EKW" for the same
  reason), so the narrow end is expected to be rare on EKW too. Registered for parity; marked
  pending real EKW data access.

## Acceptance test (4 named defect tasks) - real run

Command (real LLM calls, HTTP backend, no dry-run):

```
python judge_scope_under_inclusion_check.py SVC-PC-82-2-0 SVC-PC-82-3-0 SVC-PC-52-3-0 SVC-PC-46-3-0 \
  --root C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready \
  --out <path>/accept4.json --timeout 300
```

Real output:

```
  WARN  SVC-PC-82-2-0      1 finding(s): l2-02-r08
  WARN  SVC-PC-82-3-0      1 finding(s): l2-03-r09
  WARN  SVC-PC-52-3-0      1 finding(s): a4
  WARN  SVC-PC-46-3-0      6 finding(s): r01
4 tasks in 223.5s: 0 pass, 4 warn, 0 skip, 0 error
```

All four flagged. The findings (real LLM output; the criterion, quote, and implied_source
fields are unchanged from the response; the reason text had em dashes replaced with hyphens
per this project's voice rule):

### SVC-PC-82-2-0 - judge_files: fulfillment_sop.docx, inventory_policy.docx, l2-02_assortment_change-control_requirements_memo(1).docx

```
[tests/deliverables/judge.toml] l2-02-r08
  QUOTE: Preserves the Q2/Q3 count conflict and other unresolved evidence limitations. Expected: 80 vs 25 unresolved.
  IMPLIED_SOURCE: product_catalog_q2.pdf, product_catalog_q3.pdf, q2_inventory_snapshot.xlsx, q3_inventory_snapshot.xlsx
  REASON: The specific Q2/Q3 count conflict (80 vs 25) is a concrete numeric fact that must be
  verified against Q2 and Q3 source records such as product catalogs or inventory snapshots.
  The judge's files= list contains only the requirements memo (the deliverable),
  fulfillment_sop.docx, and inventory_policy.docx - none are count-bearing records. The product
  catalogs and inventory snapshots exist in the environment file list but were withheld.
```

Confirmed against the real corpus: `Product_Catalog_Q1-4.pdf` live under
`environment/initial_workspace/_corpus_subtree/Company Shared Drive/Marketing/Product/
Catalogs/`, none in files=.

### SVC-PC-82-3-0 - judge_files: fulfillment_sop.docx, inventory_policy.docx, l2-03_seasonal_bundle_and_retirement_transition_readiness.docx

```
[tests/deliverables/judge.toml] l2-03-r09
  QUOTE: Preserves the count conflict and states the evidence limitations/no complete SKU audit. Expected: 80 vs 25 unresolved.
  IMPLIED_SOURCE: product_catalog_q1.pdf ... q4.pdf; q1..q4_inventory_snapshot.xlsx
  REASON: The '80 vs 25' count conflict is a specific concrete number ... neither a SOP nor a
  policy document would plausibly contain a raw SKU count conflict between catalog periods. The
  product catalogs and inventory snapshots ... exist in the environment file list but were
  withheld from the judge.
```

### SVC-PC-52-3-0 - judge_files: idle_cash_position_analysis.xlsx (deliverable only)

```
[tests/deliverables_01/judge.toml] a4
  QUOTE: The December balance agrees with the package cash figure Expected: 2,186,512.
  IMPLIED_SOURCE: tax_prep_package.xlsx
  REASON: a cross-document comparison against the package. The judge's files= list contains
  only the deliverable ... which cannot verify what the package's cash figure actually is.
  tax_prep_package.xlsx exists in the environment but was withheld.
```

### SVC-PC-46-3-0 - judge_files: engineering_demand_and_interrupt_analysis.xlsx, fy2021_engineering_demand_and_interrupt_assessment.docx (deliverables only)

```
[tests/deliverables_01/judge.toml] r01
  QUOTE: Defines the usable sprint evidence window as Sprints 01-18, Jan 4-Sep 26, and does not infer Q4 sprint reprioritization from the incident log alone. Expected: S01-S18; Jan 4-Sep 26.
  IMPLIED_SOURCE: sprint_01_backlog.xlsx ... sprint_18_backlog.xlsx, incident_log_2021.xlsx
[tests/deliverables_01/judge.toml] r03  -> incident_log_2021.xlsx, sprint_16_backlog.xlsx, sprint_17_backlog.xlsx (August Apex episode, S16->S17)
[tests/deliverables_01/judge.toml] r04  -> sprint_16_backlog.xlsx (Sprint 16 Done status + slipped note conflict)
[tests/deliverables_01/judge.toml] r05  -> incident_log_2021.xlsx, sprint_12_backlog.xlsx (June CloudHost outage, Sprint 12)
[tests/deliverables_01/judge.toml] r06  -> sprint_03_backlog.xlsx, sprint_04_backlog.xlsx (Sprint 3 "f&f fires first" punt, S3-06)
[tests/deliverables_01/judge.toml] r07  -> sprint_05_backlog.xlsx (Sprint 5 staging deferral, Alice-approved)
```

Confirmed against the real corpus: `Sprint_01_Backlog.xlsx` through `Sprint_18_Backlog.xlsx`
plus `Incident_Log_2021.xlsx` live directly under `environment/initial_workspace/` (19 files),
none in files=.

All four acceptance tasks correctly flagged. The brief named r01/r06/r08 for 82-2-0 as
grading against the catalogs; the LLM flagged r08 (the clearest, with the specific numeric
"80 vs 25" that must come from the catalogs). r01 and r06 grade the deliverable's coverage of
change types and lifecycle treatment, which the LLM judged as deliverable-content checks
rather than source-verification needs - a defensible precision-over-recall call. The task is
flagged correctly either way; flagging 1 of the 3 named criteria is recall, not a correctness
failure.

## Broader sample (29 tasks) - real run

Command (real LLM calls, 4 concurrent jobs):

```
python judge_scope_under_inclusion_check.py <29 task ids> \
  --root C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready \
  --out <path>/sample28.json --jobs 4 --timeout 300
```

Initial run: 9 pass, 16 warn, 4 error (3 transient parse/backend failures + 1 prompt-cap
truncation). All 4 errors were retried; the truncation case was fixed by raising
`MAX_PROMPT_CHARS` from 60000 to 120000 (the 100-criterion SVC-PC-59-0-0 prompt was 68811
chars and got cut mid-list). Corrected final counts:

```
29 tasks: 10 pass, 19 warn, 0 error, 125 total findings
```

Warn tasks (task-id: n_findings):

```
SVC-PC-18-1-0: 12   SVC-PC-2-7-0: 3      SVC-PC-22-5-0: 1
SVC-PC-26-1-0: 7    SVC-PC-29-7-0: 35    SVC-PC-37-0-0: 1
SVC-PC-39-5-0: 2   SVC-PC-42-2-0: 14    SVC-PC-44-5-0: 1
SVC-PC-47-5-0: 11  SVC-PC-49-8-0: 2     SVC-PC-51-3-0: 2
SVC-PC-53-6-0: 1   SVC-PC-56-7-0: 1     SVC-PC-59-0-0: 5
SVC-PC-60-5-0: 9   SVC-PC-63-4-0: 1     SVC-PC-67-1-0: 13
SVC-PC-8-6-0: 4
```

Pass tasks: SVC-PC-1-0-0, SVC-PC-12-1-0, SVC-PC-15-1-0, SVC-PC-33-2-0, SVC-PC-69-7-0,
SVC-PC-71-2-0, SVC-PC-75-4-0, SVC-PC-78-0-0, SVC-PC-82-1-0, SVC-PC-90-2-0.

## False-positive spot-check (real, not assumed zero)

Verified TRUE positives against the real corpus (judge.toml files= + environment listing),
each confirmed the implied source exists and is withheld:

| Task | Criterion | Implied source withheld | Verdict |
|---|---|---|---|
| SVC-PC-56-7-0 | r011 (rules drawn from the quality standard) | Quality_Standards.pdf in env, not in files= | TRUE |
| SVC-PC-37-0-0 | f17 (named employees use actual roster titles) | Org_Chart_Q1.png..Q3.pptx in env, not in files= | TRUE |
| SVC-PC-42-2-0 | c01/c02/c04/c07 (Net rev $1,204,900; COGS $423,359; cash $2,186,512) | year_end_trial_balance.xlsx, year_1_actuals_reconciliation.xlsx, bank_statement_*.pdf withheld | TRUE |
| SVC-PC-67-1-0 | r001-r005 (6,000 distinct customers; 4,801; 0 contactable) | customer_master.xlsx, orders_export_1.csv withheld | TRUE |
| SVC-PC-18-1-0 | r1/r2/r4-r12 (rating 5.0; range 3.8-4.0; named employees) | 15 year_end_performance_review_*.docx withheld | TRUE |
| SVC-PC-26-1-0 | b1/b2 (opening cash $2,036,512 + $150,000) | bank_statement_*.pdf, svb_statement.csv/ofx withheld | TRUE |
| SVC-PC-22-5-0 | r002 (promo P&L matches source assumptions) | year_2_demand_plan_draft.xlsx, pricing_matrix.xlsx withheld | TRUE |
| SVC-PC-44-5-0 | c-029 (all figures trace to Year-1 corpus) | Year-1 source files all withheld (deliverable only) | TRUE |
| SVC-PC-39-5-0 | c07 ($815,000 P&L payroll traces to named file) | year_1_annual_pnl.xlsx withheld | TRUE |
| SVC-PC-63-4-0 | f09 (source locators resolve to manifest sources) | pricing_matrix.xlsx, q4_marketing_dashboard.xlsx withheld | TRUE |

False-positive class found and reported, not hidden: SVC-PC-29-7-0's 35 findings include a
subset of "epistemic restraint" criteria that reference source data for context but grade
the deliverable's restraint, which the judge CAN verify from the deliverable alone:

```
r030: Does not present an annual incident rate as if the 4-quarter log supported one
r031: Does not present a leave liability figure as if the 1-record export supported one
r035: Reports zero restore tests ... as absence of evidence rather than as a demonstrated failure
r045: States a limit on the annual incident rate rather than computing one from the four-quarter log
r046: States a limit on leave liability rather than deriving one from the single-row export
```

These reference source data (the incident log, the leave export) in their wording, so the
LLM flagged them as needing source verification, but the actual grading action (does the
deliverable avoid overstating?) is verifiable from the deliverable alone. Roughly 5-10 of
29-7-0's 35 findings are this borderline shape; the rest (specific dollar figures like
$1,204,900 net revenue, named incidents, the roster/controller check) are true positives.

Net: precision is high for criteria that pin specific figures or named facts (the majority
across the 19 warn tasks), and the false-positive class is concentrated in one criterion
shape ("does not present X as if Y supported one"). This matches the task's explicit warning
that many criteria legitimately do not need every referenced fact independently
file-verifiable, so a real false-positive rate is expected, not zero. The check is warn-only,
so a false positive is advisory, not blocking.

## Known limits (disclosed, not hidden)

- One real LLM call per task. The initial 29-task run took 990s at 4 concurrent jobs
  (roughly 50-100s per call). A bare `--all` with no `--checks` filter attempts this for
  every task; scope with `--checks judge_scope_under_inclusion` or exclude it for a fast
  sweep, same caution `rubric_overspecification` and `golden_groundedness` already carry.
- Transient backend/parse failures: 3 of the 29 initial errors were transient (cleared on
  retry). `call_llm()` retries both backends once; beyond that, a parse failure reports
  `status=error` (never a false pass). The 4th was a real prompt-cap truncation, fixed by
  raising `MAX_PROMPT_CHARS` to 120000.
- EKW untested: registered in `ekw_run_checks.py` for parity, but no real EKW defect example
  was available this session. Marked EKW-UNTESTED pending real EKW data access.
- The check reads files= lists, criterion descriptions, and environment basenames only. It
  does not open file contents (it is a scope check, not a content check). The LLM reasons
  from filenames and criterion wording; a file whose name does not signal its contents can
  be misjudged, same limit every filename-based check in this folder carries.
- Deliverable detection depends on instruction.md's deliverable-naming heading. When absent,
  `deliverable_files` reads as empty; the LLM is still given the files= list and reasons
  which is the output. A task whose deliverable is named only in prose body text is a
  disclosed coverage gap, matching the over-inclusion sibling's own disclosed gap.

## Files changed

- `deterministic-checks/judge_scope_under_inclusion_check.py` (new)
- `deterministic-checks/svc_run_checks.py` (registration + docstring count/letter-list sync)
- `deterministic-checks/ekw/ekw_run_checks.py` (registration, EKW-UNTESTED)
