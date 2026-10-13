# SVC/Cirrus task creation — QC alignment

Status: stale. This is one of the oldest docs in the repo and was written for the older `tests/rubric.json` task shape. See the [doc index](../README.md).

## 1. What this is

L1, L2 and L3 are the three levels of an SVC task set (atomic leaf, mid-level node, apex node); see section 1 of [ONBOARDING](ONBOARDING.md).

Rules for creating SVC/Cirrus tasks so they pass post-hoc QC the first time.
This is the creator-facing counterpart to
[`../skills/svc-task-qc/`](../skills/svc-task-qc/), which is the
QC-reviewer's guide, for grading a task after it's built. This file is for
building it right in the first place.

Every rule below traces back to a real defect found across delivered SVC/Cirrus
task sets. None of it is hypothetical best practice. See
[`QC_DIMENSIONS_FOR_CREATORS.md`](QC_DIMENSIONS_FOR_CREATORS.md) for the full
explanation and before/after example behind each rule.

## 2. Explicit non-goal: no mandated file layout

This file does not require Harbor's directory conventions, does not require
a specific naming scheme, and does not care whether a task was authored
inside or outside Harbor. Whatever structure your creation environment
already uses is fine. The only place file format is even discussed is §7
below, and there it's a "re-confirm case by case" note, not a rule this file
enforces.

## 3. Content quality rules

- An instruction must be self-contained: solvable from the instruction and
  the bundled files alone, no external credentials or unattached filings
  assumed.
- An instruction must not leak the answer, a completed deliverable, or a
  reasoning artifact into the input folder.
- An instruction must not contradict what the bundled sources actually
  contain, and must not reference a file that was never bundled.
- Task complexity must match the node's place in the L1/L2/L3 hierarchy: L1
  atomic-and-mechanical is correct at that level, not a defect; L2/L3 need
  real professional judgment, not template-filling.
- A task must not ask for something while simultaneously forbidding the
  means to produce it (e.g. asking for a full-year figure while excluding
  the only data covering part of the year).

## 4. Source document rules

- No synthetic-pipeline markers (`[TIE]`, `[SYNTHETIC]`, `[AI-GENERATED]`,
  `[FABRICATED]`, `[GENERATED]`, `[OMEGA]`, or prose that states outright a
  document was fabricated for training/eval purposes).
- No unrendered template-call syntax left in a document's text (a generation
  script that computed a value but never substituted it in).
- No anachronistic dates: a field meant to represent the task's fictional
  timeline should not carry the real wall-clock generation date.
- No internal self-contradictions (a running total that doesn't reconcile
  with itself elsewhere in the same file).
- Suspiciously round numbers and sequential IDs are a realism tell; genuinely
  synthetic data (anonymized names, required placeholder identifiers) is
  fine, fabricated-looking data is not.

## 5. Golden solution rules

- A golden must satisfy every explicit requirement the instruction states,
  not just the ones that are easy to check.
- A golden must be internally consistent: if there's more than one
  deliverable, they must agree with each other and with themselves.
- A golden must be substantive, not a skeleton, except an L1 leaf's single
  correctly-stated fact, which is fully substantive at that level.

## 6. Rubric rules

- At least one `must_pass` gate must exist; more than half of a
  4-plus-criterion rubric being gated is a real problem (judge noise on any
  one gate then sinks an otherwise-good solution).
- Criterion count should match the level: L1 ≥ 1, L2 ≥ 6, L3 ≥ 30.
- No blank `description` or expected-value field on any criterion.
- Criterion language must be concrete. "Professional / on-brand" or an
  undefined "controls pass" used as a pass condition is not acceptable; a
  soft qualifier is fine only when backed by a concrete anchor the criterion
  also states.
- Penalty-flagged criteria must carry negative points.

## 7. Known accepted conventions: re-confirm, don't assume

Two findings were ruled false positives or accepted conventions against
earlier delivered task sets: `solution_format_match` (goldens saved under a
build-convention name rather than the literal required path) and
`metadata_completeness` (`task.toml`'s schema differs from what the
dimension expects). Full detail, citations, and a re-confirm field for each
are in [`KNOWN_CALIBRATIONS.md`](KNOWN_CALIBRATIONS.md).

Don't assume either ruling still holds for a task you're creating now. Check
the re-confirm date; if it's blank or old, treat the finding as open.

## 8. Which skill to run, and when

In this repo the skills named below are under `skills/svc/<skill name>/SKILL.md`.

| Stage | Skill | Done when |
|---|---|---|
| Instruction drafted | [`source-file-reference-check`](skills/source-file-reference-check/SKILL.md) | every referenced file resolves, no unexplained orphan inputs |
| Sources assembled | [`synthetic-marker-scan`](skills/synthetic-marker-scan/SKILL.md) | zero marker/template/date hits |
| Golden + rubric drafted | [`rubric-structure-check`](skills/rubric-structure-check/SKILL.md) | `check_rubric.py` returns all severity-0 |
| Before delivery | [`authenticity-and-substance-review`](skills/authenticity-and-substance-review/SKILL.md) (via [`task-creation-self-qc`](skills/task-creation-self-qc/SKILL.md)) | every checklist question has a concrete yes |

Cross-node checks (`check_dag.py`, anchor consistency across a whole
workstream) are QC-time only. They need the full corpus, not one
in-progress task, so there's no creation-time equivalent to run here. Once
several nodes of a workstream exist, run the full
[`svc-task-qc`](../skills/svc-task-qc/SKILL.md) pipeline instead.

## 9. What "done" means

You're ready to deliver when:

- All four skills in §8 have been run against the current draft.
- Every severity-2-or-higher finding from any of them is resolved, or you
  have a specific, written reason you're accepting it anyway.
- Nothing in §7 was assumed without actually checking the re-confirm date
  for this task.
