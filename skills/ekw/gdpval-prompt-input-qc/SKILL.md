---
name: gdpval-prompt-input-qc
description: >-
  QC the prompt and source/input files of a single GDPVal/Omega task.
  Runs Source File & Prompt QC only. Each LLM gate runs as an isolated
  parallel subtask; results are aggregated into a single verdict.
  Use when asked to QC, review, or check a task's prompt or source files.
---

# GDPVal — Prompt & Input QC

Grade the **prompt** and **source/input files** (`Source Documents/`) of one
GDPVal task. Each LLM gate runs as a clean-context subtask in parallel; you
(the orchestrator) collect the findings and compute the final verdict.

---

## Required inputs — confirm BEFORE grading

| Input | How supplied | If missing |
|---|---|---|
| **Prompt** | Pasted into conversation (wrap in `<task_prompt>` tags) | Ask & wait |
| **`Source Documents/`** | Uploaded directory or task folder path | Ask & wait |
| `Expert Solution/` | Optional — strengthens `overall_gdpval_fit` and `professional_complexity` | Note; proceed without |

**Do not start grading until both required inputs are in hand.**

---

## Orchestrator workflow

```
- [ ] 1. Confirm prompt is pasted and Source Documents/ is non-empty; ask if missing and WAIT
- [ ] 2. Extract all source file text: pipeline/.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir>
- [ ] 3. If Expert Solution/ is present, extract it too: pipeline/.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir> --solution
- [ ] 4. Spawn one parallel subtask agent per LLM gate (see Gate list below)
- [ ] 5. Collect all 8 finding JSONs from the subtasks
- [ ] 6. Compute verdict using the Verdict computation rules below
- [ ] 7. Synthesize top_issues and suggested_fixes; emit the review
- [ ] 8. Offer to save the review to <task_dir>/qc_prompt_input_review.md
```

### Step 2-3 — Extract content

Run the extractor; capture its full output — you will embed it verbatim in each
subtask prompt:

```bash
pipeline/.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir>           # source files
pipeline/.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir> --solution  # Expert Solution if present
```

### Step 4 — Spawn parallel subtask agents

**Spawn all 8 subtasks at once** (one Agent call per gate, all in a single
message batch so they run concurrently). Each subtask is a **fresh agent** with
no memory of this conversation — give it everything it needs inline.

#### Gate list (one subtask per row)

| Gate ID | Inputs subtask receives |
|---|---|
| `overall_gdpval_fit` | prompt + source file text + solution text (if present) |
| `instruction_input_consistency` | prompt + source file text |
| `self_containedness` | prompt + source file text |
| `role_and_deliverable_clarity` | prompt only |
| `professional_complexity` | prompt + source file text + solution text (if present) |
| `feasibility_and_clarity` | prompt + source file text |
| `instruction_authenticity` | prompt only |
| `input_file_authenticity` | source file text only |

#### Subtask prompt template

Use this template for every subtask, substituting `{GATE_DEFINITION}`,
`{RELEVANT_INPUTS}`, and `{GATE_ID}`:

```
You are a QC judge for GDPVal/Omega tasks. Grade exactly ONE dimension and
return ONE finding JSON. Do not do anything else.

## Gate definition

{GATE_DEFINITION}

## Inputs

{RELEVANT_INPUTS}

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

**Eval-context conventions — do NOT penalise these**
Persona/role assignments, output file path specs, required deliverable lists,
length/scope cues, and named deliverables are normal eval dataset setup. Treat
them as intended, not as synthetic markers.

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
from [source-and-prompt-qc.md](source-and-prompt-qc.md).

For `{RELEVANT_INPUTS}`, embed the relevant extracted text directly (do not
summarise).

### Step 5 — Collect findings

Wait for all 8 subtasks to return. Expect one JSON per subtask. If a subtask
returns malformed output, note it as `severity: 0, confidence: "low"` and add
a `suggested_fix` to re-run that gate.

---

## Grading protocol reference

All dimensions are LLM-graded (run as subtasks). Confidence and evidence rules
are enforced at aggregation time:

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
[source-and-prompt-qc.md](source-and-prompt-qc.md) for each gate's values).
Apply tiers in priority order — first match wins:

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
# QC review — <task_id> · Prompt & Input

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
| dimension | role | sev | conf | fixability | headline |
|---|---|---|---|---|---|
| overall_gdpval_fit | blocking | 0 | high | n/a | no issue |
| ... | ... | ... | ... | ... | ... |
```

**`top_issues`** — up to 3 must-fix items, ranked by (blocking before advisory,
then higher severity, then more structural). A finding is must-fix when:
`severity ≥ 2` on any non-informational dimension, OR `severity == 1` on a
blocking dimension.

**`suggested_fixes`** — up to 5: must-fix overflow + minor advisory-severity-1
findings. Never duplicate a top issue.

Every action must be specific enough to act on without raw notes — name a file,
section, or quote the evidence. "Improve authenticity" is not acceptable.

---

## Dimension reference

All 8 gate definitions, severity rubrics, and hard-fail patterns live in
[source-and-prompt-qc.md](source-and-prompt-qc.md).

**Task Structure gates** (6):
`overall_gdpval_fit` · `instruction_input_consistency` · `self_containedness` ·
`role_and_deliverable_clarity` · `professional_complexity` · `feasibility_and_clarity`

**Authenticity gates** (2):
`instruction_authenticity` · `input_file_authenticity`
