---
name: authenticity-and-substance-review
description: >-
  Self-review an SVC/Cirrus task draft against the subjective, LLM-judged QC
  dimensions (professional plausibility, instruction/solution authenticity,
  solution substance and internal consistency, rubric clarity) using the
  same standard a post-hoc QC judge would apply, without calling any judge
  API. Use before delivering a task, especially after the deterministic
  checks pass, to catch what only human judgment can find.
---

# Authenticity and substance review

The post-hoc QC pipeline grades most of these dimensions with a 2-judge LLM
ensemble. There is no equivalent API call here — **your own judgment stands
in for the ensemble.** Read `CHECKLIST.md`, work through it against your own
draft, and be honest rather than charitable: every one of these questions
came from a real recurring defect found across delivered task sets, not a
hypothetical.

## When to use this

After the deterministic checks
([`source-file-reference-check`](../source-file-reference-check/SKILL.md),
[`synthetic-marker-scan`](../synthetic-marker-scan/SKILL.md),
[`rubric-structure-check`](../rubric-structure-check/SKILL.md)) come back
clean. Those catch the mechanical, unambiguous defects; this catches the
ones that need a professional reading the material, not a script.

## How to use the checklist

Work through `CHECKLIST.md` section by section. For each question, answer it
against your actual draft — quote the specific passage or file you're
judging, not a general impression. If you can't answer a question with a
concrete "yes, because ___," treat it as a "no" and fix the draft rather than
talking yourself into a pass. See
[`QC_DIMENSIONS_FOR_CREATORS.md`](../../QC_DIMENSIONS_FOR_CREATORS.md) for
the full rationale and before/after examples behind each dimension this
checklist covers.

## Skip logic (matches the post-hoc pipeline)

- `overall_gdpval_fit` and `professional_complexity` — skip for L1 leaf
  nodes (atomic-by-design is not a defect at that level).
- `solution_chart_quality` / `solution_visual_insight_surfacing` — skip if
  the golden has no charts.
- `verifier_rubric_clarity` / `verifier_rubric_specificity` — the only two
  rubric-quality dimensions that actually run on SVC/Cirrus tasks; the
  other six (`verifier_rubric_construct_validity`, `verifier_outcome_coverage`,
  `verifier_missing_critical_dimensions`, `verifier_discriminative_power`,
  `verifier_spec_parseable`, `verifier_count_in_range`,
  `verifier_outcome_grader_present`) never run — don't spend effort chasing
  them.
