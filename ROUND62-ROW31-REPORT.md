# Row 31: judge_file_size_cliff_check.py - design, validation, and report

## The problem

`harbor-rewardkit`'s `judges.py` defines `_MAX_FILE_SIZE = 1024 * 1024` (1,048,576
bytes, 1 MiB) and silently replaces any graded file over that size with the literal
text `"[skipped: file too large]"` before the LLM judge sees it. Confirmed by
reading `rewardkit/judges.py` lines 144 and 180-181 in both the installed 0.2.0
and a 0.1.7 extraction: the behavior is identical across both versions.

Two real incidents:

- **SVC-PC-66-2-0**: a 1,112,742-byte compliant SOLVER SUBMISSION was truncated
  and scored 0.0 because the judge saw `"[skipped: file too large]"` instead of
  the workbook.
- **SVC-PC-52-6-0**: a 1,675-formula all-NaN-cached SOLVER SUBMISSION scored 1.0
  because the judge could not tell a live workbook from a dead one. This is a
  formula-health issue (already covered by `formula_health_check.py`), not a
  cliff issue, but the task shares the same large corpus subtree.

## Why the prior draft did not work

A prior round drafted `judge_file_size_cliff_check.py` that tested whether GOLDEN
reference files exceed 1 MiB. Two independent validation passes found 0/202
goldens exceed 1 MiB. Goldens are always small curated reference files. The
truncation applies to the SOLVER SUBMISSION (the graded file named in
`judge.toml`'s `[judge].files`), not the golden. A checker that measures the
golden's size validates against the wrong population and cannot catch anything.

This report re-derives that finding independently (below) and then investigates
the suggested alternative (golden structural complexity) before settling on a
working design.

## Investigation: can golden structural complexity predict cliff risk?

The brief suggested building a size-risk heuristic from the golden's own
structural complexity (formula count, sheet count, row/column extent) as a proxy
for how large a compliant submission could grow. This was investigated for real.

### Method

Ran `openpyxl.load_workbook` on every xlsx golden across the 202-task subset,
measuring: sheet count, total formula count (scanning up to 5,000 rows per
sheet), max row extent, max column extent. 149 of 202 goldens parsed
successfully as xlsx; the remaining 53 are docx goldens (not applicable to this
mechanism).

### Result: golden complexity is NOT predictive

The incident task's golden (SVC-PC-66-2-0) has: 7 sheets, 45 formulas, 25 max
rows, 6 max cols. Every one of these sits at or near the corpus median:

| Metric | Incident (66-2-0) | Corpus p50 | Corpus p75 | Corpus p90 |
|---|---|---|---|---|
| Sheets | 7 | 7 | 9 | 12 |
| Formulas | 45 | 42 | 161 | 422 |
| Max rows | 25 | 34 | 54 | 124 |
| Max cols | 6 | 9 | 12 | 16 |

Any threshold that flags the incident task flags roughly half the corpus. Any
threshold selective enough to flag a small fraction misses the incident entirely.
Golden structural complexity cannot distinguish the incident task from ~100
others.

The reason is structural: the golden is a curated answer that carries the
derived results, not the raw source data. The bloat does not come from the
deliverable SHAPE being complex. It comes from the solver embedding source DATA
into the deliverable during construction. The golden's complexity measures the
answer's shape, not the data volume that drives bloat.

## What this check measures instead: environment data volume

The environment IS part of the task package. A per-task check that measures the
environment's data file sizes is a real, testable signal from the task package
alone, with no submissions corpus needed. The environment's data files are the
"bloat fuel": the source data a solver builds from and may embed into the
deliverable.

### The bloat mechanism (confirmed against the incident)

SVC-PC-66-2-0's golden is `FY2021_Defect_Rate_Analysis.xlsx` (17,669 bytes). Its
environment contains a 4,021,135-byte `orders_export_1.csv`, a 3,520,643-byte
`Sales_Orders.xlsx`, and a 2,474,869-byte `tickets.json`. The instruction asks
the solver to "build the year's product defect rate" from "the support ticket
export and the order export." A compliant solver that imports and embeds this
source data into the workbook produced a 1,112,742-byte submission: 63x the
golden's size, just past the cliff.

### Threshold: 256 KiB (NAMED, not arbitrary)

`CLIFF_EQUIVALENT_SINGLE_FILE = CLIFF // 4 = 262,144` bytes (256 KiB).

The reasoning, grounded in the format property and the one real data point:

1. The cliff is 1,048,576 bytes (1 MiB, confirmed from `rewardkit/judges.py`).
2. An xlsx embedding tabular data from a source file incurs roughly 3-5x
   overhead (OOXML XML wrapping, shared-strings table, cell metadata). This is
   a well-known property of the xlsx format.
3. At 4x overhead (the middle estimate), a 256 KiB source file produces 1 MiB of
   xlsx content: exactly the cliff. Adding the golden's own ~17-50 KiB pushes
   the total past it.
4. The incident confirms: SVC-PC-66-2-0's 4 MiB source file, with roughly 7%
   embedded (about 274 KiB of source data at 4x overhead), produced a 1,112,742-
   byte submission past the cliff.

This is ONE data point, not a validated ratio. The threshold is named
("cliff-equivalent single-file size at 4x xlsx overhead") and grounded in the
format property, not overfit to the incident.

### Bimodal threshold insensitivity

The corpus's largest-data-file distribution (for xlsx goldens) is bimodal: files
are either small (under 100 KiB, personal template files) or large (3.5-4 MiB,
shared corpus exports). There are no tasks in the ambiguous middle:

| Percentile | Largest data file (bytes) |
|---|---|
| p10 | 23,654 |
| p25 | 104,527 |
| p50 | 3,520,643 |
| p75 | 4,021,135 |
| p90 | 4,021,135 |
| p100 | 4,021,135 |

Any threshold between 256 KiB and 3.5 MiB flags the same 74 tasks. The exact
threshold value is not sensitive in practice: the bimodality separates "has
large shared corpus data" from "does not" cleanly.

### WARN condition

The check flags WARN (never FAIL) when BOTH conditions hold:

1. The golden deliverable is xlsx (the data-accumulating format where embedding
   source data is the natural construction approach).
2. The environment's largest data-shaped file (csv/json/xlsx/xml/tsv/parquet) is
   at least 256 KiB (262,144 bytes).

Non-xlsx goldens (docx, pptx, pdf) are not flagged: the bloat mechanism is
different and not calibrated against any real incident. This is a disclosed
coverage gap in the check's module docstring, not a hidden one.

WARN, not FAIL, because whether the solver actually embeds the data depends on
the solver's approach, not the task package. The check can only say the
environment HAS enough data to push a compliant submission past the cliff, not
that it WILL.

## Validation: real run against the 202-task SVC-PC subset

### Command

```
cd C:\wt_ekwqc\round62-row31-sizecliff\deterministic-checks
python judge_file_size_cliff_check.py C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready --json cliff_check_full.json
```

Then filtered to the 202-task subset (the subset defined by the prior
`C:\ekwqc\_step2_full_202\summary.json` run's task list):

```python
import json
results = json.load(open("cliff_check_full.json", encoding="utf-8"))
tasks_202 = set(l.strip() for l in open("tasklist_202.txt") if l.strip())
subset = [r for r in results if r["task"] in tasks_202]
```

### Result

```
202-task subset: 202 tasks, 74 WARN, 128 pass
Golden formats: .xlsx=129, .docx=69, .pptx=3, .pdf=1
Goldens >= 1 MiB: 0 / 202
```

### Golden size distribution (all 202 tasks, confirming the prior draft)

| Percentile | Golden bytes |
|---|---|
| p50 | 33,886 |
| p75 | 46,334 |
| p90 | 100,682 |
| p95 | 220,301 |
| p99 | 472,974 |
| p100 | 550,298 |

0/202 goldens reach 1 MiB. The prior draft's finding holds independently.

### 74 WARN task IDs

```
SVC-PC-1-2-0, SVC-PC-1-5-0, SVC-PC-11-2-0, SVC-PC-12-2-0, SVC-PC-13-3-0,
SVC-PC-13-7-0, SVC-PC-14-1-0, SVC-PC-14-3-0, SVC-PC-14-4-0, SVC-PC-17-5-0,
SVC-PC-20-3-0, SVC-PC-22-1-0, SVC-PC-22-2-0, SVC-PC-22-3-0, SVC-PC-22-5-0,
SVC-PC-26-3-0, SVC-PC-26-7-0, SVC-PC-3-4-0, SVC-PC-3-8-0, SVC-PC-33-6-0,
SVC-PC-35-0-0, SVC-PC-35-1-0, SVC-PC-35-6-0, SVC-PC-37-3-0, SVC-PC-39-3-0,
SVC-PC-40-1-0, SVC-PC-40-3-0, SVC-PC-41-3-0, SVC-PC-41-4-0, SVC-PC-42-3-0,
SVC-PC-42-7-0, SVC-PC-42-9-0, SVC-PC-49-2-0, SVC-PC-5-1-0, SVC-PC-5-3-0,
SVC-PC-5-4-0, SVC-PC-5-5-0, SVC-PC-52-3-0, SVC-PC-52-5-0, SVC-PC-52-6-0,
SVC-PC-53-3-0, SVC-PC-53-5-0, SVC-PC-53-6-0, SVC-PC-55-0-0, SVC-PC-55-1-0,
SVC-PC-56-1-0, SVC-PC-57-1-0, SVC-PC-57-2-0, SVC-PC-57-4-0, SVC-PC-58-10-0,
SVC-PC-66-2-0, SVC-PC-67-1-0, SVC-PC-67-2-0, SVC-PC-67-4-0, SVC-PC-7-1-0,
SVC-PC-7-4-0, SVC-PC-7-6-0, SVC-PC-70-1-0, SVC-PC-71-4-0, SVC-PC-71-5-0,
SVC-PC-73-4-0, SVC-PC-75-7-0, SVC-PC-75-8-0, SVC-PC-77-1-0, SVC-PC-77-5-0,
SVC-PC-77-8-0, SVC-PC-9-1-0, SVC-PC-91-2-0, SVC-PC-91-3-0, SVC-PC-91-5-0,
SVC-PC-93-5-0, SVC-PC-94-5-0, SVC-PC-94-6-0, SVC-PC-94-7-0
```

Both incident tasks (SVC-PC-66-2-0, SVC-PC-52-6-0) are flagged.

### Why 74 WARN is not a false-positive problem

74/202 (37%) is a high WARN rate. It is the real at-risk population, not noise.
The SVC-PC corpus has a large shared data universe: many tasks share the same
`_corpus_subtree` containing the same 3.5-4 MiB data exports (orders_export_1.csv,
Sales_Orders.xlsx, tickets.json). Every one of the 74 flagged tasks genuinely
has enough data in its environment to push a compliant submission past the
cliff. Whether a given solver actually embeds that data depends on the solver's
approach, which is why the finding is WARN-tier (advisory) and not FAIL-tier
(gate).

### Orchestrator smoke test

Ran the check through `svc_run_checks.py` with 2 WARN tasks and 2 clean tasks:

```
python svc_run_checks.py SVC-PC-66-2-0 SVC-PC-52-6-0 --root ... --out-dir ... --checks judge_file_size_cliff --jobs 1 --shards 1
  D: warn=2
    judge_file_size_cliff            warn=2

python svc_run_checks.py SVC-PC-96-3-0 SVC-PC-96-6-0 --root ... --out-dir ... --checks judge_file_size_cliff --jobs 1 --shards 1
  D: pass=2
    judge_file_size_cliff            pass=2
```

Registration confirmed: `len(svc_run_checks.CHECKS) == 41`,
`len(ekw_run_checks.CHECKS) == 42`, both include `judge_file_size_cliff` with
`letter="D"`, `style="rubric_schema"`, `task_key="task"`.

## EKW side

The EKW corpus lives at `C:\ekwqc\_merged274\files` (274 tasks, confirmed by
listing). The check is format-agnostic: it walks `environment/data/` for EKW
(vs `environment/initial_workspace/` for SVC-PC) and globs `solution/`
recursively for goldens.

A 3-task EKW smoke test (task_1, task_10, task_100) ran clean: EKW
`environment/data/` carries `.md` SEC-filing files, not the csv/json/xlsx data
exports that drive SVC-PC bloat. The `.md` extension is not in the check's
`DATA_EXTS`, so no EKW task is flagged today. The EKW registration is marked
EKW-UNTESTED in `ekw_run_checks.py`'s CHECKS comment: EKW's bloat mechanism (if
any) is a different shape, not calibrated against any real incident. Registered
for parity (same convention as `golden_arithmetic` and `golden_groundedness`
above, which are also SVC-PC-calibrated and EKW-untested) so the check runs and
reports 0 findings rather than being silently absent.

## The real fix belongs in harbor-rewardkit

The truncation is SILENT: the file is replaced with `"[skipped: file too large]"`
with no error, no warning to the pipeline, and no visible marker the judge LLM
can recognize as a truncation. Making it LOUD would prevent both incident
classes at the source:

- **Raise the cliff**: increase `_MAX_FILE_SIZE` to accommodate compliant
  submissions. The incident submission was 1.1 MiB; a 10 MiB or 50 MiB cliff
  would have let it through. This trades safety (judge context window) for
  coverage.
- **Make truncation visible to the judge**: instead of silently replacing with
  `"[skipped: file too large]"`, inject a marker the judge is prompted to
  treat as a hard zero or a flagged condition. This keeps the context budget
  intact while preventing the judge from scoring a truncated file as if it
  were complete.
- **Reject before grading**: if the submission exceeds the cliff, fail the
  grading run with an error rather than silently degrading. This makes the
  problem visible to the pipeline instead of producing a quietly wrong score.

This per-task check is a COMPLEMENTARY advisory that surfaces which tasks carry
the most risk so the pipeline can prioritize the harness fix or pre-check
submission sizes before grading. It is not a replacement for fixing rewardkit.

## Files changed

- `deterministic-checks/judge_file_size_cliff_check.py`: the checker (new file,
  stdlib-only, no openpyxl dependency).
- `deterministic-checks/svc_run_checks.py`: CHECKS dict registration (letter D,
  style rubric_schema).
- `deterministic-checks/ekw/ekw_run_checks.py`: CHECKS dict registration
  (letter D, style rubric_schema, EKW-UNTESTED).
- `ROUND62-ROW31-REPORT.md`: this report.

## Known limits (disclosed, not hidden)

- **xlsx-only**: the check flags tasks with xlsx goldens. A docx or pptx golden
  with a large environment is not flagged (different bloat mechanism, no
  calibration data).
- **No solver-behavior model**: this check measures the environment's data
  volume, not the solver's embedding behavior. A task with a 4 MiB CSV where
  the solver produces a 50 KiB workbook is flagged but does not actually bloat.
  The WARN is "could plausibly," not "will."
- **One data point**: the 4x overhead estimate and the 256 KiB threshold are
  calibrated against ONE real cliff incident (SVC-PC-66-2-0). A second cliff
  incident would refine the estimate.
- **Shared-corpus tasks**: 74/202 tasks are flagged because the SVC-PC corpus
  has a large shared data universe. This is the real at-risk population, not a
  false-positive rate.
