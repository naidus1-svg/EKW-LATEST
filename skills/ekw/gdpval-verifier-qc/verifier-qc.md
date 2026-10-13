# Verifier QC — gate definitions

This file contains only the gates that do **not** depend on
`verifier_assertion_summary` (which is never available during expert task
creation). Gates removed: `verifier_rubric_construct_validity`,
`verifier_outcome_coverage`, `verifier_missing_critical_dimensions`,
`verifier_discriminative_power`.

---

## LLM gates (run as parallel subtasks)

### verifier_rubric_clarity

```yaml
dimension_name: "Verifier Rubric Clarity"
check_kind: llm
inputs: [verifier_spec_json, instruction]
applies_when:
  builtin: task_has_verifier
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Across all verifier rubrics, are the criteria stated
clearly enough that two different judges would reach the same verdict on the
same solution?

**How to judge.** Read each rubric's `assertion.rubric.prompt` and ask
whether it would be interpreted the same way by two competent reviewers.
Watch for vague words ("appropriate", "reasonable", "sufficient") used
without anchoring, multi-clause rubrics that pack several distinct checks
into one, and rubrics whose pass/fail criterion is implicit rather than
stated.

**Severity rubric.**
- **0** — All rubrics state criteria unambiguously; two judges would agree.
- **1** — Most rubrics clear; one or two have minor ambiguity that wouldn't
  flip a verdict.
- **2** — Multiple rubrics are ambiguous in ways that would produce judge
  disagreement on borderline outputs.
- **3** — Pervasive ambiguity; the rubrics cannot reliably be applied without
  the author present.

**Common hard-fail patterns.**
- Multi-clause compound rubrics ("the memo includes findings AND
  recommendations AND a risk table") — partial credit is impossible because
  the whole rubric fails on any one piece.
- Pass condition stated as "no major issues" or "no obvious problems" — a
  default-pass rubric that any non-trivially-broken solution will pass.
- Use of "appropriate", "reasonable", "sufficient", "thorough", "robust" as
  pass conditions without any anchoring to observable features.
- Rubrics where the pass criterion is implicit — the rubric describes the
  topic to grade but never states what counts as passing.
- Rubrics that depend on undefined terms specific to the task without
  defining them.

---

### verifier_rubric_specificity

```yaml
dimension_name: "Verifier Rubric Specificity"
check_kind: llm
inputs: [verifier_spec_json, instruction]
applies_when:
  builtin: task_has_verifier
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Are the rubrics concrete enough to grade against, or
do they ask vague qualitative questions that require the judge to invent the
criteria?

**How to judge.** A specific rubric asks something observable: "the document
includes a synthesis table of the three audit findings cross-mapped to
federal requirements". A non-specific rubric asks something interpretive:
"the analysis is high quality". The distinction is whether the rubric points
at concrete features of the solution.

**Severity rubric.**
- **0** — All rubrics state concrete, observable criteria.
- **1** — Most rubrics specific; one or two lean on vague qualitative
  language but are mostly anchored.
- **2** — Several rubrics rely on undefined qualitative judgments
  ("appropriate", "professional", "thorough" without anchoring).
- **3** — Rubrics are predominantly impressionistic; the judge would have to
  invent most of the criteria.

**Common hard-fail patterns.**
- Rubric asks the judge to perform substantive analysis themselves to grade
  ("the financial model correctly projects revenue", "the recommendation is
  optimal") — the rubric requires the judge to redo the work.
- Subjective qualitative judgments without observable criteria ("the analysis
  is thorough", "the prose is professional", "the tone is appropriate").
- Rubric criteria depend on undefined task-specific terms ("ensure the
  appropriate tone for the audience" with no anchor for "appropriate").
- Rubric grades aesthetic preferences rather than functional correctness
  ("the document is well-organised" without specifying what organisation
  means here).

---

## Programmatic checks (run inline via check_verifier.py — no subtask)

### verifier_spec_parseable

```yaml
dimension_name: "Verifier Spec Parseable"
check_kind: programmatic
callback: check_verifier_parseable
inputs: [verifier_spec_json]
applies_when:
  builtin: task_has_verifier
gate:
  role: blocking
  reject_at_severity: 2
```

**What this evaluates.** Does the verifier JSON parse cleanly into the
`{verifiers: [...]}` shape the framework runtime expects?

**Callback behaviour.** Severity 0 if the spec parses; severity 2 if it is
empty, not valid JSON, not an object, or missing the `verifiers` list.
(A truncated paste is the usual cause of failure here.)

---

### verifier_count_in_range

```yaml
dimension_name: "Verifier Count in Range"
check_kind: programmatic
callback: check_verifier_count_in_range
inputs: [verifier_spec_json]
applies_when:
  builtin: task_has_verifier
gate:
  role: advisory
  reject_at_severity: 3
config:
  min_verifiers: 6
  max_verifiers: 20
```

**What this evaluates.** Are there a reasonable number of verifier rubrics —
not so few that coverage is thin, not so many that the framework becomes
brittle?

**Callback behaviour.** Severity 0 if count is in `[6, 20]`; severity 1 if
outside by 1–2; severity 2 if outside by more.

---

### verifier_outcome_grader_present

```yaml
dimension_name: "Verifier Outcome Grader Present"
check_kind: programmatic
callback: check_verifier_outcome_grader_present
inputs: [verifier_spec_json]
applies_when:
  builtin: task_has_verifier
gate:
  role: advisory
  reject_at_severity: 3
```

**What this evaluates.** Does the verifier include at least one
outcome-grading rubric? A verifier that grades only process or format
cannot drive a meaningful reward.

**Callback behaviour.** Severity 0 when at least one rubric has
`metadata.grading_role == "outcome"` (Omega) or
`metadata.classification == "core"` (legacy). Severity 2 otherwise.
