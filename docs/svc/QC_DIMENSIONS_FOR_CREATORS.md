# QC dimensions for SVC/Cirrus task creators

Status: stale. This is one of the oldest docs in the repo and was written for the older `tests/rubric.json` task shape. See the [doc index](../README.md).

This explains every dimension the post-hoc QC pipeline checks, in the order
you'll hit them while building a task, not in pipeline order. Every
before/after example here is a real defect found in a delivered task set,
not a hypothetical.

Severity levels (sev 1, 2, 3) come from the shared grading rules in [QC_FOUNDATION](../../skills/_shared/QC_FOUNDATION.md). L1, L2 and L3 are the three levels of an SVC task set (atomic leaf, mid-level node, apex node); see section 1 of [ONBOARDING](ONBOARDING.md).

Two things up front:

- **Six rubric dimensions never run on SVC/Cirrus tasks:**
  `verifier_rubric_construct_validity`, `verifier_outcome_coverage`,
  `verifier_missing_critical_dimensions`, `verifier_discriminative_power`,
  `verifier_spec_parseable`, `verifier_count_in_range`,
  `verifier_outcome_grader_present`. They depend on eval-run data or a
  legacy rubric schema this task family doesn't use. Don't spend effort on
  them.
- **Two dimensions have a status you should re-confirm, not assume.** They're
  marked below and detailed in [`KNOWN_CALIBRATIONS.md`](KNOWN_CALIBRATIONS.md).

Each entry: what it checks, a real before/after, what happens if it ships
anyway, and how to catch it yourself.

---

## 1. Framing the task

### `overall_gdpval_fit`
*Skipped for L1 leaf nodes: atomic-by-design is not a defect at that level.*

**Ask yourself:** would a professional actually get paid to do this exact
piece of work?

**Before → After:** An L1 leaf phrased as "which month is the low point?"
would read as mechanical and test-shaped if judged at the apex bar, but at
L1 that's the correct level of atomicity, not a defect. The dimension only
bites at L2/L3, where the same bar as real delegated work applies.

**If shipped:** Blocking, severity 2. Automatic reject, and the fix isn't
an edit, it's rebuilding the task with real grounding.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

### `role_and_deliverable_clarity`

**Ask yourself:** if a stranger read only the instruction, would they know
exactly who they're supposed to be and what artifact to hand back?

**Before → After:** Vague: "put together an analysis of the situation."
Clear: "As the FP&A analyst, produce a one-page memo and a supporting
Excel databook, saved to the two named paths below."

**If shipped:** Advisory, severity 3. Lands as a needs_review note, usually
a quick instruction edit.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

### `professional_complexity`
*Skipped for L1 leaf nodes.*

**Ask yourself:** does finishing this require real judgment, or could
someone with no domain background produce the same answer by following a
template?

**Before → After:** Look at your own golden. If it's mostly formatting,
paraphrase, and arithmetic with no synthesis or tradeoff weighing, the task
is mechanical regardless of how long the instruction is.

**If shipped:** Blocking, severity 2. The task's structure lacks a judgment
opportunity; no edit fixes that, only a redesign.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

### `feasibility_and_clarity`

**Ask yourself:** is this doable in the scope implied, and would two
competent professionals interpret the request the same way?

**Before → After:** A real recurring pattern: an instruction asks for a
full-year calculation while explicitly forbidding use of the only data that
covers the missing quarter ("do not use this as Q4 attribution or ROAS
evidence"). The task asks for X while banning the means to get X. Another:
"compute the four monthly metrics" without saying which four.

**Before you flag your own draft as infeasible, check two things first:**
monthly phasing/seasonality data is often already present in a named report
you haven't opened, and an instruction that explicitly invites the solver to
"choose a sensible assumption and disclose it" is inviting underspecification
by design, not leaving a gap.

**If shipped:** Advisory, severity 3.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

---

## 2. Writing the instruction

### `instruction_input_consistency`

**Ask yourself:** does every file, section, or data element the instruction
references actually exist, with the substance the instruction assumes?

**Before → After:** The single most common real defect found across every
delivered task set so far: an instruction says "compare the KPI report
against the close package," and neither file exists among the inputs. Or:
"tied to the monthly P&L marketing line" when only one month's P&L was
actually bundled.

**If shipped:** Blocking, severity 2. The solving agent has no way to guess
what data to use; unfixable without either bundling the file or rewriting
the instruction.

**Catch it yourself:** `source-file-reference-check` (the mechanical half:
does the name resolve) plus `authenticity-and-substance-review` (the
semantic half: does the content match).

### `input_prompt_leakage`

**Ask yourself:** does any file in `environment/data/` hand the solving
agent the answer, or a completed/reasoning artifact it shouldn't see?

**Before → After:** A `Reasoning.docx`, a completed deliverable, or a grading
rubric sitting in the input folder, not just thematic overlap with the
instruction (a source document discussing "leverage ratio" when the
instruction asks about leverage is expected, not a leak).

**Note for this task family specifically:** many SVC/Cirrus nodes
legitimately consume an upstream node's completed golden as an intended
input (the decomposition-DAG design: a downstream node is *supposed* to be
handed a prior-run result). That's by design, not contamination. The actual
leak to watch for is the answer stated in the *prompt text itself*, or a
value the *current* node is supposed to derive appearing in its own raw
inputs.

**If shipped:** Blocking, severity 2. The artifact itself has to be
removed; there's no partial fix.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

### `self_containedness`

**Ask yourself:** could this be solved from the instruction and the bundled
files alone, with no external credentials, no unattached filing, no tribal
knowledge only you have?

**Before → After:** An instruction that depends on "the company guide"
(referenced by name, never bundled), or a governed data file mentioned by
name and never included.

**If shipped:** Blocking, severity 3. A structural failure the agent cannot
work around.

**Catch it yourself:** `source-file-reference-check` (mechanical half) plus
`authenticity-and-substance-review` (semantic half).

### `instruction_authenticity`

**Ask yourself:** read the actual brief above the harness-appended
"## Environment notes" block (that block is boilerplate, not your prose,
and shouldn't be judged as a synthetic tell). Does the brief read like a
real person wrote it: specific asides, sender/recipient context, dated
references, or does it read hedged, over-clean, and scaffolded the way an
LLM writes?

**Before → After:** Human-voiced: "From: VP Risk. To: FP&A/Treasury. Re:
[specific, dated ask with a concrete constraint]." LLM-shaped: generic
hedging, a hollow "as a {role}, I want to..." framing with no real-world
grounding underneath it, or a suspiciously tidy structure with no actual
context.

**If shipped:** Blocking, severity 2. This is a voice problem, not an
editing artifact; no touch-up fixes it.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

---

## 3. Assembling `environment/data/`

### `input_file_authenticity`

**Ask yourself:** read each source file as if seeing it cold. Does anything
contradict itself? Are there impossible values, or content that couldn't
plausibly come from the source it claims to be?

**Before → After (leaked pipeline scaffolding, the single most damaging
version of this):** A generation script computed a value but never
substituted it into the final text, leaving a literal
`'+$(T20.inYear)+'&#8211;'+$(T22.inYear)+'` inside a document's narrative.
This exact string was found verbatim in multiple delivered task sets sharing
the same corpus file. It isn't a one-off; it's baked into a shared source
document and needs fixing once, at the source.

**Before → After (anachronistic dates):** A shipment tracking sheet
correctly labels its rows `INB-2021-04` through `INB-2021-08` and states
"Feb–Sep 2021" in its own summary, but the Dock Arrival column shows dates
in **2026**. Month and day are right; only the year is wrong, almost
certainly the generation script stamping the real wall-clock year instead of
the task's fictional one.

**Before → After (internal contradiction):** A marketing review reports
full-year cumulative customers as 12,000 in one place and 6,000 for the same
period elsewhere in the same file.

**What's *not* a defect here:** synthetic-but-authentic markers: anonymized
names, round figures, a document's own `TBD` field because it's explicitly
an unapproved draft, or a negative-total row in an orders export that's
actually a legitimate refund/credit entry.

**If shipped:** Blocking, severity 2. Unfixable without regenerating the
file.

**Catch it yourself:** `synthetic-marker-scan` (catches the leaked-template
and anachronistic-date shape of this mechanically) plus
`authenticity-and-substance-review` for internal contradictions a script
can't judge.

### `synthetic_marker_scan`

**Ask yourself:** did any generation-tooling residue survive into a source
file? A bracket tag, or a document that states outright it's synthetic?

**Before → After:** A literal `[SYNTHETIC]`, `[AI-GENERATED]`, `[FABRICATED]`,
or similar tag in a source file's text. Also covers prose that breaks the
fourth wall entirely ("this document is a fabricated artifact created solely
for a training case study") without a bracket tag.

**If shipped:** Blocking, severity 2. One confirmed hit is unambiguous,
zero tolerance, no threshold.

**Catch it yourself:** `synthetic-marker-scan`. This is the single cheapest,
highest-value script to run right before delivery.

### `metadata_completeness`
**Status: re-confirm before relying on this; see [`KNOWN_CALIBRATIONS.md`](KNOWN_CALIBRATIONS.md).**

**Ask yourself:** does `task.toml` carry a non-empty `category` field?

**If shipped:** Informational only. Never gates a verdict on its own.

---

## 4. Building the golden solution

### `solution_format_match`
**Status: re-confirm before relying on this; see [`KNOWN_CALIBRATIONS.md`](KNOWN_CALIBRATIONS.md).**

**Ask yourself:** does the golden deliverable match the file type and name
the instruction specifies?

**If shipped:** Blocking, severity 3 in principle, but see the calibration
note before treating a build-name mismatch as an automatic defect.

### `solution_substantiveness`

**Ask yourself:** read the golden with fresh eyes. Is this real analysis,
with specific numbers, named entities, and a defensible conclusion, or a
skeleton of headings with one-liners and placeholder values?

**Before → After:** For an L1 leaf, a single correctly-stated figure *is*
fully substantive. Don't hold it to the "no two-line sections" bar meant
for L2/L3.

**If shipped:** Blocking, severity 3.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

### `solution_instruction_alignment`

**Ask yourself:** go through the instruction's explicit requirements one by
one. Does the golden actually address each, in the right proportion?

**Before → After:** A workbook that omits a precedence-rule table the
instruction explicitly requests. A monthly reconciliation that leaves
required AOV, cumulative-customer, and variance columns blank. A source
citation that's generic ("channel-performance data") instead of naming the
specific file the instruction asked to be cited.

**If shipped:** Blocking, severity 3.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

### `solution_internal_consistency`

**Ask yourself:** if there's more than one deliverable, do they agree with
each other, and does each agree with itself?

**Before → After:** Especially high-value where a memo, databook, and deck
must all reconcile. A number quoted in narrative prose must match the number
in the table it's summarizing.

**If shipped:** Blocking, severity 3.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

### `solution_layout_professionalism`

**Ask yourself:** would you hand this to a real client without
embarrassment?

**If shipped:** Advisory, severity 3. Usually a quick formatting pass.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

### `solution_chart_quality` / `solution_visual_insight_surfacing`
*Both skipped if the solution has no charts.*

**Ask yourself:** are axes labeled with a title and legend, and does the
chart actually surface the finding the task is asking about, or is it
decorative (a raw-input bar chart instead of one highlighting the three
findings that drove the recommendation)?

**If shipped:** Advisory, severity 3 each.

**Catch it yourself:** `authenticity-and-substance-review` checklist.

---

## 5. Writing the rubric

*Six rubric dimensions never run on this task family; see the note at the
top of this document. Only the two below actually apply.*

### `verifier_rubric_clarity`

**Ask yourself:** if two different reviewers graded the same solution
against this exact criterion wording, would they reach the same verdict?

**Before → After:** Vague, ungrounded: `"Professional / on-brand"` used as
a pass/fail condition, recurring near-verbatim across multiple criteria in
a real delivered rubric. Anchored: a criterion whose `expected`/
`expected_value` field supplies a concrete number, band, or named item; a
soft qualifier like "substantially all" is fine *only when* backed by an
enumerated set or objective fallback the criterion also states.

**Also watch for:** a criterion with a completely blank `description` and
expected-value field. This happened in a real delivered rubric
(`rubric-structure-check` catches this mechanically; it's not a wording
problem, it's a row nobody finished writing).

**If shipped:** Advisory, severity 3, but an ungrounded criterion
means two fair graders can disagree on the same solution, which is a real
scoring-integrity problem even though it doesn't auto-reject.

**Catch it yourself:** `rubric-structure-check` for blank fields;
`authenticity-and-substance-review` for vague-but-non-blank wording.

### `verifier_rubric_specificity`

**Ask yourself:** does the criterion point at something observable in the
solution, or does it ask an interpretive question that makes the grader
invent their own bar?

**Before → After:** Non-specific: "the analysis is high quality."
Specific: "the document includes a synthesis table cross-mapping the three
audit findings to the named requirements."

**If shipped:** Advisory, severity 3.

**Catch it yourself:** `authenticity-and-substance-review` checklist.
