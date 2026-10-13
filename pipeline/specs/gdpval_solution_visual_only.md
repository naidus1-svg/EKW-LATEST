---
name: gdpval_task_quality
version: "18.5"
cache_bust: "6"

# ── Judge models ────────────────────────────────────────────────────────────
# Multi-judge ensemble. Disagreement between judges on a blocking dimension
# routes the sample to NEEDS_REVIEW rather than being silently majority-voted.
models:
  - model: gpt-5.5
    reasoning_effort: high
    max_tokens: 32000
  - model: gemini-3.1-pro-preview
    reasoning_effort: high
    max_tokens: 32000

# ── Per-sample fields surfaced by the loader ────────────────────────────────
# v18 dataset layout (one directory per task):
#   <task>/task.toml
#   <task>/instruction.md
#   <task>/environment/                      (agent inputs)
#   <task>/solution/golden_outputs/          (the canonical answer — graded)
#   <task>/tests/verifier.json               (the verifier definition — graded)
#   <task>/evals/                            (ignored by v18)
field_types:
  task_id: skip
  annotatorID: skip
  category: text
  difficulty: text
  tags: text
  instruction: text
  input_files: document
  solution_files: document          # canonical answer (one or more files)
  solution_reasoning: text          # optional Reasoning.docx narrative
  verifier_spec_json: text          # verbatim tests/verifier.json
  verifier_assertion_summary: text  # precomputed digest, optional

# ── Loader bindings — where each field comes from on disk ───────────────────
field_bindings:
  solution_files:
    source: directory
    path: solution/golden_outputs
    exclude: ["Reasoning.docx"]     # surfaced separately as solution_reasoning
  solution_reasoning:
    source: file
    path: solution/golden_outputs/Reasoning.docx
    optional: true
  verifier_spec_json:
    source: file
    path: tests/verifier.json
    optional: true
  verifier_assertion_summary:
    source: callback
    callback: build_verifier_assertion_summary
    optional: true

# ── Synthesis layer ─────────────────────────────────────────────────────────
# After all dimensions run, the synthesizer makes ONE LLM call per sample to
# produce the SampleReview: a verdict, a one-line summary, top-K ranked
# actionable issues, and a suggested-fixes list. This is the artifact shown
# to reviewers; raw per-dim judgements are retained for audit only.
synthesis:
  enabled: true
  top_issues_cap: 3
  judge_model: gpt-5.5
  judge_reasoning_effort: high
  judge_max_tokens: 16000

# ── Calibration ─────────────────────────────────────────────────────────────
# A small directory of (sample, expected_verdict) pairs the framework runs
# against this spec on every build. Drift between expected and observed
# verdicts is reported in batch_summary.md. Populated incrementally as we
# accumulate confirmed cases.
calibration:
  goldens_path: calibration/v18/
  enabled: true

# ── Severity scale (referenced by every LLM dimension's rubric) ─────────────
# The scale is GLOBAL. Most dimensions inherit "sev 2 = fixable, sev 3 =
# structural" semantics, but a few dimensions (overall_gdpval_fit,
# instruction_input_consistency, professional_complexity, the two authenticity
# dims, and verifier_spec_parseable) are structural by their nature — even
# their sev-2 findings cannot be fixed by editing the sample. Those dimensions
# carry `reject_at_severity: 2`. Spec authors adding new dimensions should
# pick `reject_at_severity` based on whether sev 2 for that dimension is
# fixable or structural; the rubric severity levels themselves should always
# follow the global scale.
severity_scale:
  0: "no issue or fully meets criterion"
  1: "minor concern; does not affect usability of the sample"
  2: "material concern; sample is usable only after a fix"
  3: "severe failure; sample cannot be made usable by a fix"

# ── Evidence policy ─────────────────────────────────────────────────────────
# Every LLM judge MUST quote a verbatim passage from the inputs to justify
# any finding with severity >= 1. Findings without an evidence quote are
# programmatically demoted to severity 0. This is the principal anti-overcall
# guard.
require_evidence_quote: true

# ── Confidence policy ───────────────────────────────────────────────────────
# Judges return a confidence ∈ {low, medium, high}. Low-confidence severity-1
# findings are demoted to 0; low-confidence severity-2+ findings trigger
# NEEDS_REVIEW for the sample rather than autoacting on them.
confidence_demotion:
  low_at_sev1: demote_to_0
  low_at_sev2_or_higher: route_to_review

# ── Verdict tiering (used by the synthesizer) ───────────────────────────────
# Five-tier verdict computed from all dimensions' findings + gating rules:
#
#   REJECT_STRUCTURAL    any blocking dim at sev >= reject_at_severity with
#                        fixability=structural
#   REJECT_FIXABLE       any blocking dim at sev >= reject_at_severity with
#                        fixability != structural   (rare — most reject-worthy
#                        issues will be fixable, but explicit tier exists)
#   NEEDS_REVIEW         judge disagreement on a blocking dim, OR a
#                        low-confidence finding at sev >= 2, OR finding lands
#                        exactly at reject_at_severity - 1 on a blocking dim
#                        (borderline)
#   ACCEPT_WITH_FIXES    only advisory issues with severity >= 1, OR blocking
#                        issues at severity < reject_at_severity
#   ACCEPT               no findings of severity >= 1 on any blocking or
#                        advisory dim (informational findings allowed)
verdict_tiers:
  - reject_structural
  - reject_fixable
  - needs_review
  - accept_with_fixes
  - accept
---

# GDPVal Task Quality Spec — v18

This spec defines how the quality framework grades GDPVal-style data samples for v18.
It is a **clean break** from v17 — it does not inherit from any prior spec. The unit
of evaluation is a single task directory containing an instruction, a set of input
files, a canonical "golden" solution under `solution/golden_outputs/`, and a verifier
definition under `tests/verifier.json`. v18 does **not** evaluate model outputs.

Each dimension below declares:

- **inputs** — which per-sample fields the judge sees
- **gate** — how findings translate into the sample's verdict (`role`,
  `reject_at_severity`, `on_disagreement`)
- **applies_when** — optional precondition; the dimension is skipped if false
- **severity rubric** — anchored definitions for severity levels 0–3
- **common hard-fail patterns** — concrete diagnostic patterns to flag with
  evidence; judges decide final severity in context, not by auto-jump

Five families of dimensions ship in v18: **Task Structure**, **Authenticity**,
**Solution Quality**, **Verifier Quality** (conditional), and **Programmatic
Checks**.

**Note on gating.** The default `reject_at_severity` is `3`, which means a finding
must reach the unfixable tier to auto-reject. Six dimensions tighten this to `2`
because their sev-2 findings are *also* unfixable in practice — see the per-dim
gate blocks for the rationale.

**Note on hard-fail patterns.** Several dimensions list concrete diagnostic
patterns under "Common hard-fail patterns". These are *guidance for the judge*,
not automatic severity bumps. When a judge sees one of these patterns clearly
present, they should quote the evidence and decide the severity in context.
A pattern that's borderline, ambiguous, or has a plausible benign explanation
should not be flagged.

**Important: evaluation-context conventions.** This corpus is an *evaluation
dataset*, not a copy of in-the-wild work. Several patterns that would be
unusual in a forwarded email are perfectly reasonable as eval setup, and
**must not** be penalised as evidence of being synthetic or constructed:

- **Persona / role assignment.** Phrases like "You are a senior credit
  analyst at a direct-lending fund" or "Acting as the portfolio manager,
  …" set the agent's context. They are not "LLM-shaped framing."
- **Output file specifications.** Instructions that say "save your memo as
  `/workspace/output/memo.docx`" or "produce a `.xlsx` model with sheets
  named …" are eval-infrastructure necessities: the verifier needs to know
  where to look. Naming the deliverable, its file format, or its location
  is not "pre-specifying the structure" in the synthetic sense.
- **Required deliverable list.** An instruction that says "produce two
  files: a recommendation memo and a supporting model" is fine. The
  synthetic version is an instruction whose enumerated requirements read
  as a verifier rubric copied verbatim into the prompt (e.g. "include
  section 1: …, section 2: …, section 3: …" mirroring the rubric items).
- **Length / scope cues.** "A one-page memo" or "a ~500-word summary" is
  a normal professional ask. Only flag length constraints that look
  benchmark-arbitrary (e.g. "exactly 3 bullet points", "exactly 200 words").
- **Capability framing.** Eval tasks are *designed* to exercise model
  capabilities; that is what an eval is. Only flag tasks whose stakes or
  domain are so paper-thin that they couldn't plausibly represent any
  real delegated work.
- **Acceptance criteria in the instruction.** Real professional briefs
  sometimes include "the deliverable must address …" lists. Fine.
- **Anonymisation conventions.** Redacted-real or anonymised real
  documents may carry generic-sounding names without being fabricated.

The anti-overcall guidance on each dimension reflects these conventions.
Judges should err toward "the eval needed this" rather than "this is
synthetic" when a pattern could plausibly fall in either bucket.

---

## Task Structure

### solution_layout_professionalism

```yaml
dimension_name: "Solution Layout Professionalism"
check_kind: llm
inputs: [solution_files]
applies_when:
  builtin: solution_present
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Is the solution presented to professional standard —
appropriate document structure, headings, formatting, length, no obvious
artifacts of careless drafting?

**How to judge.** Look at document-level concerns: heading hierarchy,
consistent formatting, page breaks where expected, tables that render cleanly,
charts that are titled and legend-equipped. This dim is about *presentation*,
not analytical depth (covered by substantiveness) or correctness (covered by
alignment).

**Severity rubric.**
- **0** — Polished and professional throughout; ready to send.
- **1** — Generally good with one or two formatting rough edges (an
  inconsistent heading style, a slightly misaligned table).
- **2** — Multiple meaningful formatting issues (broken layout, unclear
  hierarchy, charts without titles, awkward page breaks).
- **3** — Reads as a rough draft; significant cleanup needed before it could
  be sent to a real audience.

**Common hard-fail patterns.**
- Markdown formatting visible as raw text in a non-markdown deliverable —
  `**bold**` shown literally, `-` characters rendering as plain text instead
  of bullets, leading `#` characters as headings in a `.docx`.
- Inconsistent heading hierarchy (H1 followed by H3 followed by H2, or
  visually-similar headings used for differently-leveled content).
- Mixed fonts or sizes across sections that should be uniform.
- Tables overflow page boundaries or have visibly misaligned columns.
- Charts pasted as low-resolution raster screenshots in a document where
  editable charts are expected.

---

### solution_chart_quality

```yaml
dimension_name: "Solution Chart Quality"
check_kind: llm
inputs: [solution_files]
applies_when:
  builtin: solution_has_charts
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** If the solution contains charts/visualisations, are
they readable, appropriately labelled, and visually correct?

**Skip condition.** This dimension is skipped (no LLM call made) for any
sample where the solution contains no chart-like content. The framework
detects "chart-like" programmatically — embedded images in .docx, chart
sheets in .xlsx, vector chart objects in .pdf.

**How to judge.** When charts are present, examine: axis labels and units,
chart titles, legends, colour/contrast choices, data-ink ratio, and basic
visual accuracy (does the chart correctly represent the underlying data).

**Severity rubric.**
- **0** — Charts are clean, well-labelled, and visually accurate.
- **1** — Minor chart issues (axis label too small, legend placement, one
  questionable colour choice).
- **2** — Material chart problems (mis-scaled axes, unclear or missing labels,
  ambiguous categories).
- **3** — Charts are misleading or unreadable.

**Common hard-fail patterns.**
- Charts with no title or no axis labels at all.
- Y-axis truncated in a way that misleads (e.g. starting at 90% to exaggerate
  a small variation).
- 3D pie or bar charts with no analytical reason for the third dimension
  (decorative 3D distorts perception).
- Pie charts with more than 5 slices (becomes unreadable).
- Two or more charts on the same page showing essentially the same data in
  slightly different forms.
- Charts pasted at low resolution / visibly image-compressed.

---

### solution_visual_insight_surfacing

```yaml
dimension_name: "Solution Visual Insight Surfacing"
check_kind: llm
inputs: [instruction, solution_files]
applies_when:
  builtin: solution_has_charts
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Do the solution's charts actually surface the
analytical insight the task is asking about, or are they decorative?

**Skip condition.** Same as `solution_chart_quality` — skipped if no charts.

**How to judge.** Identify the key analytical question the task poses, then
ask whether the charts help the reader see the answer. A bar chart of raw
inputs is decorative; a bar chart highlighting the three findings that drove
the recommendation surfaces insight. This dim is distinct from
`solution_chart_quality` (which is about chart correctness, not utility).

**Severity rubric.**
- **0** — Charts pull out and highlight the key insight effectively.
- **1** — Charts show the underlying data but the insight requires some
  interpretation by the reader.
- **2** — Charts are present but largely decorative; the actual analytical
  insight lives in the text.
- **3** — Charts mislead or distract from the task's actual analytical
  content.

**Common hard-fail patterns.**
- Charts visualise only raw input data and never any derived/summary view —
  the analytical work is in the text, the charts just decorate.
- Multiple charts that all answer the same analytical question in slightly
  different forms, with no progression of insight.
- Charts that appear in the deliverable but are never referenced or
  discussed in the narrative.
- Charts whose visual emphasis (size, colour, position) misallocates
  attention relative to the analytical priorities.

---

## Verifier Quality

These dimensions evaluate `tests/verifier.json` as a definition document —
how well it captures the criteria a correct solution must meet. They are
**conditional** on the task having a verifier spec; the framework skips them
entirely if `tests/verifier.json` is missing.
