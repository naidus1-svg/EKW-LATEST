---
name: rubric-structure-check
description: >-
  Run deterministic structural checks on an SVC/Cirrus task's tests/rubric.json
  (criteria are complete, a must-pass gate exists and isn't over-used, count
  matches the task's L1/L2/L3 level, penalty criteria carry negative points).
  Use when writing or reviewing rubric.json before task delivery.
---

# Rubric structure check

Reuses the existing reviewer-side script in place, exactly the way
`svc-task-qc` already references the EKW pipeline in place — one canonical
implementation, not a vendored copy that can drift out of sync.

## Run it

```bash
python ../../../skills/svc-task-qc/scripts/check_rubric.py <rubric.json> --level <L1|L2|L3>
```

Level is inferred from the `task` field's name if you omit `--level`. Emits
seven findings in the standard shape:

- `rubric_spec_parseable` — the file parses as JSON with a `criteria` list.
- `rubric_category_weights_sum` / `rubric_criteria_category_valid` — only
  meaningful for the older `categories[]`-with-weights rubric shape; report
  "not applicable" on the current flat-category-label shape rather than
  inventing a fake threshold for a schema that has no such invariant.
- `rubric_gate_present_and_sane` — at least one `must_pass` criterion, and
  not more than half of a 4+-criterion rubric gated (a single dissenting
  judge on an over-gated rubric can zero out an otherwise-good solution).
- `rubric_count_for_level` — L1 ≥ 1 criterion, L2 ≥ 6, L3 ≥ 30.
- `rubric_points_penalty_coherent` — penalty-flagged criteria carry negative
  points.
- `rubric_criteria_not_blank` — no criterion has an empty `description` or
  expected-value field. Added after a real delivered rubric shipped a
  criterion with both fields blank — a raw authoring gap, not a judgment
  call, so it's checked here rather than left for an LLM judge to notice.

## What it does not catch

Two things need a human, not this script:

- **Vague rubric language** — "Professional / on-brand," an undefined
  "controls pass," or any other subjective adjective used as a pass/fail
  condition. The script can confirm a field is non-empty; it cannot judge
  whether the words in it are concrete enough. Use the
  [`authenticity-and-substance-review`](../authenticity-and-substance-review/SKILL.md)
  checklist for this.
- **Cross-node anchor consistency** — whether a shared value (start cash, a
  board floor) stays byte-identical across a whole workstream's nodes. That
  check (`check_dag.py`) needs the full corpus, not one in-progress task —
  see [`CLAUDE.md`](../../CLAUDE.md) §8 for when to run it instead.
