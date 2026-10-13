---
name: gdpval_task_quality_no_eval_gates
extends: ../gdpval_task_quality_v18.md
# Drops the 4 verifier-QUALITY LLM dims (construct validity, outcome coverage,
# missing critical dimensions, discriminative power) — the ones whose judgment
# leans on verifier_assertion_summary / eval-trial signal. Everything else
# (verifier_rubric_clarity, verifier_rubric_specificity, the 3 programmatic
# verifier checks, synthetic_marker_scan, and every non-verifier dimension,
# including anything added to the base spec after this overlay was written)
# is inherited unchanged. Historically this variant was a full ~1400-line
# fork frozen at v18.5 that silently missed every subsequent base-spec fix;
# as an `extends` overlay it now tracks the base spec automatically.
remove_dimensions:
  - verifier_rubric_construct_validity
  - verifier_outcome_coverage
  - verifier_missing_critical_dimensions
  - verifier_discriminative_power
---
