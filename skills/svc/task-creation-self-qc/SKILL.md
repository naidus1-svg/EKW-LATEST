---
name: task-creation-self-qc
description: >-
  Run a self-QC pass on an in-progress SVC/Cirrus task before delivery —
  sequences deterministic reference, marker, and rubric checks plus an
  LLM-judged authenticity-and-substance checklist. Use when a creator asks
  to QC, self-check, or sanity-check a task they're building, or before
  marking a task ready for delivery.
---

# Task-creation self-QC

The entry point — run this rather than each sub-skill separately unless
you're mid-draft and only want one specific check. Works on a partial task:
you can run the earlier stages before a golden or rubric exists yet.

This is not the post-hoc QC pipeline in miniature. There's no severity
aggregation, no verdict tier, no LLM-judge ensemble here — it's "run these
checks, read what comes back, decide for yourself whether you're comfortable
shipping." The actual verdict on a delivered task still comes from the real
post-hoc pipeline; this exists so fewer of its findings are a surprise.

## Sequence

Run whichever stages apply to where the task currently stands. `CHECKLIST.md`
is a condensed, copy-pasteable version of this same sequence.

1. **Instruction drafted, sources not yet assembled** — nothing to run yet
   beyond your own read of the instruction against
   [`QC_DIMENSIONS_FOR_CREATORS.md`](../../QC_DIMENSIONS_FOR_CREATORS.md)
   §1–2 (framing, writing the instruction).
2. **`environment/data/` assembled** — run
   [`source-file-reference-check`](../source-file-reference-check/SKILL.md),
   then [`synthetic-marker-scan`](../synthetic-marker-scan/SKILL.md). Fix
   every severity-2 finding from both before moving on.
3. **Golden and rubric drafted** — run
   [`rubric-structure-check`](../rubric-structure-check/SKILL.md). Fix every
   non-zero severity finding.
4. **Before delivery** — work through
   [`authenticity-and-substance-review`](../authenticity-and-substance-review/SKILL.md)'s
   `CHECKLIST.md` end to end. This is the stage most tasks skip and most
   defects survive past — don't shortcut it because the scripts came back
   clean.

## Deciding whether you're done

You're ready to deliver when:

- Every severity-2 finding from the three scripts is resolved, or you have a
  specific, written reason you're accepting it anyway.
- Every question in the authenticity-and-substance checklist has a concrete
  "yes, because ___" answer against your actual draft.
- You've checked whether `solution_format_match` or `metadata_completeness`
  apply to your situation and, if so, confirmed the current ruling in
  [`KNOWN_CALIBRATIONS.md`](../../KNOWN_CALIBRATIONS.md) rather than assuming
  it still holds.

See [`CLAUDE.md`](../../CLAUDE.md) for the full content-quality rules these
checks are built from.
