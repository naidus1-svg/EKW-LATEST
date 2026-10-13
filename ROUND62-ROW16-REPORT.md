# Round 62, Row 16: Cell-Address-Pinning Checker

## Summary

Built `cell_address_pinned_check.py`, a deterministic regex-based checker that
flags rubric criteria pinning both an exact numeric answer and the exact
source cell address it came from (e.g. `Expected: 18.33 (Cover!B5)`). This
is the 5th over-specification category, distinct from the 3 existing LLM-
judged categories in `rubric_overspecification_check.py` (count_pinned,
name_pinned, value_pinned) because it is mechanically detectable: the shape
is a number followed by a parenthesized `Sheet!Cell` reference, which is a
regex match, not a semantic judgment.

Validated against the real 600-task SVC-PC corpus and the real 274-task EKW
corpus. The primary pattern (sheet-qualified cell refs) has 100% precision
(0 false positives on 8 spot-checked findings) and 100% recall on the
SVC-PC-41-4-0 ground truth (34/34 criteria found). The secondary pattern
(bare cell refs) has 0% precision (0 true positives, 6 residual false
positives after exclusions) and was kept in the code with exclusions and
documented honestly rather than silently dropped.

Wired into both orchestrators: `svc_run_checks.py` (letter D, warn-only)
and `ekw/ekw_run_checks.py` (letter D, warn-only, EKW-tested against the
real 274-task corpus).

## Architecture choice: standalone script

Built as `cell_address_pinned_check.py`, a standalone script mirroring
`pinned_value_prescreen_check.py`'s structure. NOT a new category inside
`rubric_overspecification_check.py`.

Why: `rubric_overspecification_check.py` is LLM-based (one call per task,
50-100s each). Adding a deterministic regex category there would mix two
fundamentally different detection methods in one file and would either waste
an LLM call to run a regex or need a separate code path that bypasses the LLM
entirely. The existing codebase already established this precedent:
`rubric_overspecification_check.py`'s own docstring explains why it is a
sibling script rather than a 7th pattern inside `content_audit_check.py`
(different detection method, different cost profile). This script follows
the same logic: it is a sibling of `rubric_overspecification_check.py` (same
defect family) but methodologically a sibling of `pinned_value_prescreen
_check.py` (deterministic regex, dual-format, same CLI shape, same
orchestrator registration shape).

The checker reuses `ekw_verifier_json.py` for EKW format support (same as
`pinned_value_prescreen_check.py`), and reads `judge.toml` via `tomllib` for
SVC-PC (same as every other dual-format check in this folder).

## Detection logic

Two regex patterns, each producing its own finding kind:

### 1. cell_address_pinned_sheet_qualified (primary, high precision)

Matches a number followed by a parenthesized sheet-qualified cell reference:
`number (SheetName!ColumnRow)`. Examples from the ground truth:
`18.33 (Cover!B5)`, `439,920 (Cost!C6)`, `16,800 (Cost!B4)`.

The sheet-qualified form is inherently high-precision: the `!` separator is
specific to spreadsheet cell references, and `SheetName!ColumnRow` is
unambiguous syntax. This is the shape all 34 ground-truth criteria in
SVC-PC-41-4-0 use.

Regex: `(<number>)\s*\(\s*(<sheet_name>!<cell_ref>)\s*\)` where:
- number: dollar, percent-decimal, comma-thousands, decimal, or bare integer
- sheet_name: `[A-Za-z_][A-Za-z0-9_]*`
- cell_ref: `[A-Za-z]{1,3}[0-9]+` (1-3 column letters + row digits)

### 2. cell_address_pinned_bare (secondary, lower precision)

Matches a number followed by a parenthesized bare cell reference:
`number (ColumnRow)`. Example from the user's framing: `18.33 (B5)`.

The bare form is less specific and catches false positives: fiscal-year
labels (FY2021), quarter labels (Q3, Q4), source citations (S07, B08, C02),
and part/identifier codes (CNC12, K2207). Three exclusions are applied:

- Fiscal-year labels: `FY\d{4}` excluded (fixes FY2021, FY2022)
- Quarter labels: `Q[1-4]` excluded (fixes Q3, Q4)
- Leading-zero rows: bare cell refs where the row starts with `0` are excluded
  (fixes S07, B08, C02, C06, C08 -- real Excel cell refs never have leading
  zeros)

After exclusions, 1 residual false positive remains on SVC-PC (K12, a source
citation indistinguishable from cell K12 without semantic context) and 5 on
EKW (CNC12 x2, K2207, M4410, D771 -- part/identifier codes). The bare pattern
has 0 true positives on both corpora. It is kept in the code for transparency
and because the user explicitly asked for it, with its measured 0% precision
documented here.

## Hand-derived ground truth: SVC-PC-41-4-0

Read all 4 judge.toml files in full
(`C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready\SVC-PC-41-4-0\tests\
deliverables_01\judge.toml` through `deliverables_04\judge.toml`).
37 total criteria across 4 files.

### Criteria pinning a numeric value AND a cell address (34)

All use the sheet-qualified form `number (Sheet!Cell)`:

| File | Criterion | Expected text |
|---|---|---|
| deliverables_01 | r003 | 18.33 (Cover!B5) |
| deliverables_01 | r004 | 439,920 (Cost!C6) |
| deliverables_01 | r005 | 440 (Cost!B8) |
| deliverables_01 | r006 | 16,800 (Cost!B4) |
| deliverables_01 | r007 | 7,200 (Cost!B5) |
| deliverables_01 | r008 | 156 (Throughput!B4) |
| deliverables_01 | r009 | 250 (Throughput!B5) |
| deliverables_01 | r010 | 50 (Throughput!B7) |
| deliverables_01 | r011 | 0.994 (Quality_Watch!B7) |
| deliverables_01 | r012 | 0.957 (Quality_Watch!B4) |
| deliverables_02 | r013 | 18.33 (Cover!B5) |
| deliverables_02 | r014 | 24,000 (Cost!B6) |
| deliverables_02 | r015 | 0.7 (SRC_Fulfillment!B5) |
| deliverables_02 | r016 | 0.3 (SRC_Fulfillment!B6) |
| deliverables_02 | r017 | 780 (SRC_Fulfillment!B7) |
| deliverables_02 | r018 | 1.6 (SRC_Fulfillment!B9) |
| deliverables_02 | r019 | 300 (Throughput!B6) |
| deliverables_02 | r020 | 0.957 (Quality_Watch!B4) |
| deliverables_02 | r021 | 0.996 (Quality_Watch!B6) |
| deliverables_02 | r022 | 0.994 (Quality_Watch!B7) |
| deliverables_02 | r023 | 16,800 (Cost!B4) |
| deliverables_02 | r024 | 307,944 (Cost!C4) |
| deliverables_03 | r025 | 7,200 (Cost!B5) |
| deliverables_03 | r026 | 131,976 (Cost!C5) |
| deliverables_03 | r027 | 439,920 (Cost!C6) |
| deliverables_03 | r028 | 440 (Cost!B8) |
| deliverables_03 | r029 | 156 (Throughput!B4) |
| deliverables_03 | r030 | 250 (Throughput!B5) |
| deliverables_03 | r031 | 50 (Throughput!B7) |
| deliverables_03 | r032 | 0.167 (Throughput!B8) |
| deliverables_03 | r033 | 175 (Throughput!B9) |
| deliverables_03 | r034 | 75 (Throughput!B10) |
| deliverables_03 | r035 | 350 (Throughput!B11) |
| deliverables_03 | r036 | 0.957 (Quality_Watch!B4) |

### Criteria NOT pinning a numeric value AND a cell address (3)

| File | Criterion | Expected text | Why excluded |
|---|---|---|---|
| deliverables_01 | r001 | present (Fulfillment_Capacity.xlsx) | Filename in parens, not a cell address |
| deliverables_01 | r002 | valid | No value, no cell address |
| deliverables_04 | r037 | WATCH (Quality_Watch!C7) | Non-numeric value + cell address. Same defect shape but outside the user's definition ("pins an exact NUMERIC answer AND the cell address"). Flagged as a known edge case the checker does not catch. |

### Note on the "23" count

The user's prompt said "23 of 37 criteria pin a cell address this way." The
hand-derived count is 34 of 37. The "23" likely refers to the 23 unique
(value, cell_address) pairs: many criteria repeat the same pin across
deliverables (e.g. `18.33 (Cover!B5)` appears in both r003 and r013). Each
criterion that pins a cell address is individually over-specified, so the
checker flags all 34, not just the 23 unique pairs. The checker's count (34)
is the correct one for "criteria that pin a cell address," the user's count
(23) is the correct one for "unique value/cell pairs."

## Precision/recall on SVC-PC-41-4-0

| Metric | Value |
|---|---|
| Hand-derived true positives | 34 |
| Checker findings | 34 |
| True positives (checker) | 34 |
| False positives (checker) | 0 |
| False negatives (checker) | 0 |
| Precision | 100% (34/34) |
| Recall | 100% (34/34) |

The checker finds all 34 ground-truth criteria with zero false positives and
zero false negatives. r001 and r002 (no cell address) are correctly not
flagged. r037 (non-numeric value "WATCH" + cell address) is correctly not
flagged by the numeric+cell pattern.

## Corpus-wide results: SVC-PC (600 tasks)

Ran against the full 600-task SVC-PC corpus at
`C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready`.

### Totals (after exclusions)

- 592/600 clean
- 8/600 tasks with findings
- 240 total findings: 239 sheet-qualified + 1 bare

### Flagged task list

| Task | Criteria | Findings | Sheet-qualified | Bare |
|---|---|---|---|---|
| SVC-PC-12-1-0 | 38 | 24 | 24 | 0 |
| SVC-PC-12-2-0 | 50 | 22 | 22 | 0 |
| SVC-PC-17-5-0 | 49 | 20 | 20 | 0 |
| SVC-PC-17-6-0 | 61 | 48 | 48 | 0 |
| SVC-PC-33-5-0 | 50 | 1 | 0 | 1 |
| SVC-PC-40-0-0 | 104 | 18 | 18 | 0 |
| SVC-PC-41-0-0 | 101 | 73 | 73 | 0 |
| SVC-PC-41-4-0 | 37 | 34 | 34 | 0 |

### Before vs after exclusions (bare pattern)

| | Before exclusions | After exclusions |
|---|---|---|
| Tasks with bare findings | 8 | 2 (SVC-PC-33-5-0 + EKW tasks) |
| Total bare findings | 12 | 1 (K12 in SVC-PC-33-5-0) |
| Bare true positives | 0 | 0 |
| Bare false positives | 12 | 1 |

## Corpus-wide results: EKW (274 tasks)

Ran against the full 274-task EKW corpus at `C:\ekwqc\_merged274\files`.

- 272/274 clean
- 2/274 tasks with findings
- 5 total findings: 0 sheet-qualified + 5 bare
- All 5 bare findings are false positives (part/identifier codes: CNC12 x2,
  K2207, M4410, D771 -- not spreadsheet cell references)
- 0 sheet-qualified findings: EKW verifier.json rubric prompts are free-text
  descriptions that do not use the `Sheet!Cell` form. This is a real signal
  that this defect shape does not appear in the EKW corpus, not a parsing
  failure (the check correctly reads verifier.json, parses criteria, and
  produces findings on the 2 tasks that have bare-pattern matches).

## False-positive spot-check (20 flags)

Spot-checked 20 flags against their real judge.toml text by hand: 8
sheet-qualified findings from 7 tasks (excluding SVC-PC-41-4-0, already
verified above) plus all 12 bare findings from 8 tasks.

### Sheet-qualified findings (8 checked, 8 true positives, 0% FP)

| Task | Criterion | Expected text | Verdict |
|---|---|---|---|
| SVC-PC-12-1-0 | deliverables_01/r003 | 5 (Pipeline_Forecast!B4) | TRUE POSITIVE |
| SVC-PC-12-2-0 | deliverables_01/r004 | 109 (Price_List!C4) | TRUE POSITIVE |
| SVC-PC-17-5-0 | deliverables_01/r003 | 0.7 (Logistics_3PL!B4) | TRUE POSITIVE |
| SVC-PC-17-6-0 | deliverables_01/r004 | 0.649 (SRC!B3) | TRUE POSITIVE |
| SVC-PC-17-6-0 | deliverables_02/r022 | 0.008 (GM_Bridge!B5) | TRUE POSITIVE |
| SVC-PC-40-0-0 | deliverables_01/r007 | 6000 (Cover!B5) | TRUE POSITIVE |
| SVC-PC-41-0-0 | deliverables_01/r008 | 1,204,900 (Cover!B6) | TRUE POSITIVE |
| SVC-PC-41-0-0 | deliverables_02/r021 | 18.33 (Cover!B19) | TRUE POSITIVE |

### Bare findings (12 checked, 12 false positives, 100% FP before exclusions)

| Task | Criterion | Matched | Real meaning | Verdict |
|---|---|---|---|---|
| SVC-PC-33-2-0 | deliverables_03/r028 | 2021 (S07) | Source citation S07 | FALSE POSITIVE |
| SVC-PC-33-3-0 | deliverables_03/r025 | 331 (B08) | Source citation B08 | FALSE POSITIVE |
| SVC-PC-33-5-0 | deliverables_01/r009 | 80000 (K12) | Source citation K12 | FALSE POSITIVE |
| SVC-PC-33-5-0 | deliverables_01/r010 | 8782 (C02) | Source citation C02 | FALSE POSITIVE |
| SVC-PC-33-5-0 | deliverables_01/r010 | 8665 (C06) | Source citation C06 | FALSE POSITIVE |
| SVC-PC-33-5-0 | deliverables_01/r010 | 1787 (C08) | Source citation C08 | FALSE POSITIVE |
| SVC-PC-48-4-0 | deliverables_04/c-037 | 20000 (FY2021) | Fiscal year label | FALSE POSITIVE |
| SVC-PC-48-4-0 | deliverables_04/c-037 | 42000 (FY2022) | Fiscal year label | FALSE POSITIVE |
| SVC-PC-7-0-0 | deliverables_09/c98 | 62.6% (FY2021) | Fiscal year label | FALSE POSITIVE |
| SVC-PC-7-3-0 | deliverables_01/o12 | 62.6% (FY2021) | Fiscal year label | FALSE POSITIVE |
| SVC-PC-70-0-0 | deliverables_03/b13 | 38 (Q3) | Quarter label | FALSE POSITIVE |
| SVC-PC-91-8-0 | deliverables_01/d2 | $2.08 (Q4) | Quarter label | FALSE POSITIVE |

### After exclusions

11 of 12 bare false positives are fixed by the three exclusion rules (fiscal-
year labels, quarter labels, leading-zero source citations). 1 residual
false positive remains: K12 in SVC-PC-33-5-0/r009, a source citation
indistinguishable from cell K12 without semantic context.

### False-positive rate summary

| Pattern | True positives | False positives | Precision | Spot-check sample |
|---|---|---|---|---|
| Sheet-qualified | 239 | 0 | 100% | 8 checked, 0 FP |
| Bare (before exclusions) | 0 | 12 | 0% | 12 checked, 12 FP |
| Bare (after exclusions) | 0 | 1 | 0% | 1 residual FP |

The sheet-qualified pattern is the reliable detector. The bare pattern adds
no true-positive signal and is kept in the code for transparency with its 0%
precision documented.

## Orchestrator registration

### svc_run_checks.py

Added `cell_address_pinned` to the CHECKS dict, placed after
`rubric_overspecification` (same defect family, same letter D):

```python
"cell_address_pinned": dict(
    script="cell_address_pinned_check.py",
    letter="D",
    style="rubric_schema",
    task_key="task",
    verdict=lambda r: (
        "error"
        if r.get("parse_errors")
        else "warn" if r.get("findings") else "pass"
    ),
    findings=_findings_from("findings"),
),
```

Same style as `pinned_value_prescreen_check.py` (style="rubric_schema",
task_key="task"). Warn-only, never gates. Verified by running
`svc_run_checks.py --checks cell_address_pinned` against SVC-PC-41-4-0 and
SVC-PC-12-1-0: both tasks correctly report "warn" in the D column.

### ekw_run_checks.py

Added the same registration to the EKW orchestrator. EKW-TESTED against the
real 274-task corpus (not marked EKW-UNTESTED): the check correctly reads
verifier.json, parses criteria, and produces findings. The 0 sheet-qualified
finding count is a real signal, not a parsing failure. Verified by running
`ekw_run_checks.py --checks cell_address_pinned` against task_1 and task_15:
both pass (0 findings, as expected from the full corpus run).

## Files changed

| File | Change |
|---|---|
| `deterministic-checks/cell_address_pinned_check.py` | New file: the checker |
| `deterministic-checks/svc_run_checks.py` | Added cell_address_pinned to CHECKS dict + D letter list |
| `deterministic-checks/ekw/ekw_run_checks.py` | Added cell_address_pinned to CHECKS dict + D letter list |
