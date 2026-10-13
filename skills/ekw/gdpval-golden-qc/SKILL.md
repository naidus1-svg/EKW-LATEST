---
name: gdpval-golden-qc
description: >-
  QC the expert (golden) solution of a single GDPVal/Omega task.
  Runs Solution QC only. Each LLM gate runs as an isolated parallel subtask;
  results are aggregated into a single verdict.
  Use when asked to QC, review, or check a golden solution or Expert Solution/.
---

# GDPVal — Golden Solution QC

Grade the **expert solution** (`Expert Solution/`) against the task prompt.
Each LLM gate runs as a clean-context subtask in parallel; you (the
orchestrator) collect the findings and compute the final verdict.

This stage grades the golden solution as the **canonical answer** — do not
compare it to any model output and do not treat it as "an improved version"
of anything.

---

## Required inputs — confirm BEFORE grading

| Input | How supplied | If missing |
|---|---|---|
| **Prompt** | Pasted into conversation (wrap in `<task_prompt>` tags) | Ask & wait |
| **`Expert Solution/`** | Uploaded directory or task folder path | Ask & wait |

**Do not start grading until both required inputs are in hand.**
`Source Documents/` is **not** needed for this stage — do not ask for it.

---

## Orchestrator workflow

```
- [ ] 1. Confirm prompt is pasted and Expert Solution/ is non-empty; ask if missing and WAIT
- [ ] 2. Extract solution text: pipeline/.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir> --solution
- [ ] 3. Detect whether any solution file contains chart content (chart object in .xlsx, embedded chart/image in .docx/.pdf, or an image file) → set has_charts flag
- [ ] 4. Spawn one parallel subtask agent per applicable LLM gate (see Gate list below)
- [ ] 5. Collect all finding JSONs from the subtasks
- [ ] 6. Compute verdict using the Verdict computation rules below
- [ ] 7. Synthesize top_issues and suggested_fixes; emit the review
- [ ] 8. Offer to save the review to <task_dir>/qc_golden_review.md
```

### Step 2 — Extract content

Run the extractor; capture its full output — you will embed it verbatim in each
subtask prompt:

```bash
pipeline/.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir> --solution
```

Also open any `.pdf` or image deliverable with the Read tool directly when a
gate needs the rendered artifact (layout, charts).

### Step 3 — Detect charts

Mark `has_charts = true` when any solution file contains:
- A chart object or pivot chart in an `.xlsx` file
- An embedded image or chart in a `.docx` or `.pdf` file
- A standalone image file (`.png`, `.jpg`, `.svg`, etc.)

The two chart gates (`solution_chart_quality`, `solution_visual_insight_surfacing`)
are skipped (`applicable: false`, `severity: 0`) when `has_charts == false`.

### Step 4 — Spawn parallel subtask agents

**Spawn all applicable subtasks at once** (one Agent call per gate, all in a
single message batch so they run concurrently). Each subtask is a **fresh agent**
with no memory of this conversation — give it everything it needs inline.

#### Gate list

| Gate ID | Inputs subtask receives | Skip condition |
|---|---|---|
| `solution_format_match` | prompt + solution file listing + solution text | never |
| `solution_substantiveness` | solution text + solution reasoning (if present) | never |
| `solution_instruction_alignment` | prompt + solution text | never |
| `solution_internal_consistency` | solution text (all files) | never |
| `solution_layout_professionalism` | solution text (+ rendered PDF/image if available) | never |
| `solution_chart_quality` | solution text + rendered chart content | `has_charts == false` |
| `solution_visual_insight_surfacing` | prompt + solution text + rendered chart content | `has_charts == false` |

For skipped gates, record the finding immediately without spawning a subtask:
```json
{
  "dimension": "<gate_id>",
  "severity": 0,
  "confidence": "high",
  "applicable": false,
  "uncertain": false,
  "evidence_quote": null,
  "headline": "Not applicable — no chart content in solution",
  "justification": "No chart-like content detected in any solution file.",
  "fixability": "n/a"
}
```

#### Subtask prompt template

Use this template for every subtask, substituting `{GATE_DEFINITION}`,
`{RELEVANT_INPUTS}`, and `{GATE_ID}`:

```
You are a QC judge for GDPVal/Omega tasks. Grade exactly ONE dimension of a
golden (expert) solution and return ONE finding JSON. Do not do anything else.

Important context: You are evaluating the expert solution as the canonical
answer. Do not compare it to any model output. Judge it on its own merits
against the task prompt.

## Gate definition

{GATE_DEFINITION}

## Inputs

{RELEVANT_INPUTS}

## File-format note

Judge deliverables by their actual on-disk extension. When an Office file is
rendered as extracted text, its real format is still its extension (e.g.
memo.docx). Do NOT flag a text rendering as a format mismatch.

## Grading rules

**Severity scale**
| Sev | Meaning |
|---|---|
| 0 | no issue or fully meets criterion |
| 1 | minor concern; does not affect usability |
| 2 | material concern; usable only after a fix |
| 3 | severe failure; cannot be made usable by a fix |

**Evidence policy (absolute)**
Any finding with severity ≥ 1 MUST include a verbatim evidence_quote — a short
passage (≤ 30 words) copied exactly from the inputs. If you cannot quote
concrete evidence, set severity to 0.

**Confidence policy**
- Low confidence at severity 1 → demote to severity 0.
- Low confidence at severity ≥ 2 → keep severity; mark confidence "low".

**Hard-fail patterns are guidance, not auto-bumps.** Only flag when the pattern
is clearly present with quotable evidence.

**When torn between two severity levels on a blocking dimension,** add
"uncertain": true to the finding. The orchestrator will route to needs_review.

## Required output

Return exactly one JSON object in this shape and nothing else:

{
  "dimension":      "{GATE_ID}",
  "severity":       <0|1|2|3>,
  "confidence":     "<low|medium|high>",
  "applicable":     true,
  "uncertain":      <true|false>,
  "evidence_quote": "<verbatim passage or null>",
  "headline":       "<one sentence ≤ 25 words, specific to this sample>",
  "justification":  "<1-3 sentences referencing the evidence>",
  "fixability":     "<trivial|fixable|structural|n/a>"
}
```

For `{GATE_DEFINITION}`, copy the full dimension block (YAML header + all prose)
from [solution-qc.md](solution-qc.md).

For `{RELEVANT_INPUTS}`, embed the relevant extracted text directly (do not
summarise). For chart gates, include the rendered image/chart content you
obtained via the Read tool.

### Step 5 — Collect findings

Wait for all subtasks to return. Expect one JSON per gate. If a subtask returns
malformed output, note it as `severity: 0, confidence: "low"` and add a
`suggested_fix` to re-run that gate.

---

## Grading protocol reference

All applicable dimensions are LLM-graded (run as subtasks). Confidence and
evidence rules are enforced at aggregation time:

- If a returned finding has `severity ≥ 1` and `evidence_quote` is null or
  empty → demote to severity 0.
- If `confidence == "low"` and `severity == 1` → demote to severity 0.
- If `confidence == "low"` and `severity ≥ 2` → keep severity; tag for
  `needs_review`.

---

## Verdict computation

After all findings are collected and adjusted, compute one verdict. Only
findings where `applicable == true` count. Each dimension has a **gate role**
(`blocking` or `advisory`) and a **`reject_at_severity`** threshold (see
[solution-qc.md](solution-qc.md) for each gate's values). Apply tiers in
priority order — first match wins:

1. **needs_review** — any blocking dimension with `uncertain: true`.
   Reason: "uncertainty on blocking dim '<name>'".
2. **needs_review** — any finding with `confidence == "low"` at `severity ≥ 2`.
   Reason: "low-confidence finding at severity N on dim '<name>'".
3. **reject_structural** — any blocking dimension at `severity ≥ reject_at_severity`
   with `fixability == "structural"`.
4. **reject_fixable** — any blocking dimension at `severity ≥ reject_at_severity`
   with `fixability ≠ "structural"`.
5. **needs_review** — any blocking dimension landing exactly at
   `reject_at_severity − 1` (and severity ≥ 1).
6. **accept_with_fixes** — any blocking-or-advisory dimension at `severity ≥ 1`.
7. **accept** — no applicable non-informational findings at severity ≥ 1.

---

## Output format

Emit the review using this template:

```markdown
# QC review — <task_id> · Golden Solution

**Verdict:** <accept | accept_with_fixes | needs_review | reject_fixable | reject_structural>
**Summary:** <one sentence, ≤ 25 words>
<!-- include only when verdict is needs_review: -->
**Review required because:** <reason>

## Top issues (must-fix)
1. **[sev N · <fixability> · <dimension>]** <headline>
   - Action: <specific action — name a file, section, or quote evidence>
   - Evidence: "<verbatim evidence_quote>"
<!-- up to 3; omit the section entirely if none -->

## Suggested fixes (minor)
- <specific suggestion>
<!-- up to 5; omit if none -->

## All dimension findings
| dimension | role | sev | conf | applicable | fixability | headline |
|---|---|---|---|---|---|---|
| solution_format_match | blocking | 0 | high | true | n/a | no issue |
| ... | ... | ... | ... | ... | ... | ... |
```

**`top_issues`** — up to 3 must-fix items, ranked by (blocking before advisory,
then higher severity, then more structural). A finding is must-fix when:
`severity ≥ 2` on any non-informational dimension, OR `severity == 1` on a
blocking dimension.

**`suggested_fixes`** — up to 5: must-fix overflow + minor advisory-severity-1
findings. Never duplicate a top issue.

Every action must be specific enough to act on without raw notes.

---

## Dimension reference

All 7 gate definitions, severity rubrics, and hard-fail patterns live in
[solution-qc.md](solution-qc.md).

**Solution Quality gates** (5 always-run):
`solution_format_match` · `solution_substantiveness` · `solution_instruction_alignment` ·
`solution_internal_consistency` · `solution_layout_professionalism`

**Chart gates** (2, run only when `has_charts == true`):
`solution_chart_quality` · `solution_visual_insight_surfacing`
