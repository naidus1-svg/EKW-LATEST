---
name: gdpval-verifier-qc
description: >-
  QC the verifier (Rubric) of a single GDPVal/Omega task.
  Runs Verifier QC only — gates that do not require evals data.
  The 2 LLM gates run as isolated parallel subtasks; the 3 programmatic checks
  run inline. Results are aggregated into a single verdict.
  Use when asked to QC, review, or check a task's verifier or Rubric.
---

# GDPVal — Verifier QC

Grade the task's **verifier** (its grading "Rubric") as a definition document:
how well its rubrics capture the criteria a correct solution must meet.

This skill runs **only gates that do not require evals data** — specifically,
it excludes gates that depend on `verifier_assertion_summary`, which is never
available during expert task creation.

**Active gates (5 total):**
- LLM gates (parallel subtasks): `verifier_rubric_clarity`, `verifier_rubric_specificity`
- Programmatic (inline): `verifier_spec_parseable`, `verifier_count_in_range`, `verifier_outcome_grader_present`

**Removed gates** (require `verifier_assertion_summary` — never available here):
`verifier_rubric_construct_validity`, `verifier_outcome_coverage`,
`verifier_missing_critical_dimensions`, `verifier_discriminative_power`

---

## Required inputs — confirm BEFORE grading

| Input | How supplied | If missing |
|---|---|---|
| **Verifier JSON** | Pasted into conversation (wrap in `<verifier>` tags) | Ask & wait |
| **Prompt** | Pasted into conversation (wrap in `<task_prompt>` tags) | Ask & wait |

**Do not start grading until both required inputs are in hand.**
`Source Documents/` and `Expert Solution/` are **not** needed for this stage.

---

## Getting and handling the verifier

Ask the expert to paste the verifier JSON — they should wrap it in
`<verifier>` … `</verifier>` tags. The rubric text to grade lives at
`verifiers[i].assertion.rubric.prompt`. Outcome graders are marked
`metadata.grading_role == "outcome"` (Omega) or `metadata.classification == "core"` (legacy).

Save the pasted JSON to a file before running the programmatic checks:

```bash
# Save the pasted verifier to disk (replace <task_dir> with the task folder path)
# Then run:
pipeline/.venv/bin/python -m gdpval_qc.tools.check_verifier <task_dir>/verifier.json   # --min 6 --max 20 defaults
```

---

## Orchestrator workflow

```
- [ ] 1. Confirm verifier JSON and prompt are pasted; ask if missing and WAIT
- [ ] 2. Save verifier JSON to <task_dir>/verifier.json
- [ ] 3. Run programmatic checks: pipeline/.venv/bin/python -m gdpval_qc.tools.check_verifier <task_dir>/verifier.json
- [ ] 4. Collect the 3 programmatic findings from check_verifier.py output
- [ ] 5. Spawn 2 parallel subtask agents (one per LLM gate) simultaneously
- [ ] 6. Collect the 2 LLM finding JSONs from the subtasks
- [ ] 7. Merge all 5 findings; apply evidence and confidence adjustments
- [ ] 8. Compute verdict using Verdict computation rules below
- [ ] 9. Synthesize top_issues and suggested_fixes; emit the review
- [ ] 10. Offer to save the review to <task_dir>/qc_verifier_review.md
```

### Step 3-4 — Programmatic checks

Run the script and parse its output. It emits findings for
`verifier_spec_parseable`, `verifier_count_in_range`, and
`verifier_outcome_grader_present` in the standard finding shape (always
`confidence: high`, `evidence_quote: null`). Fold them straight into the
verdict.

If `verifier_spec_parseable` fails (severity 2), still run the two LLM
subtasks — grade them against the rubrics you can read.

### Step 5 — Spawn parallel LLM subtask agents

**Spawn both subtasks at once** (one Agent call per gate, in a single message
batch so they run concurrently). Each subtask is a **fresh agent** with no
memory of this conversation — give it everything it needs inline.

#### Gate list

| Gate ID | Inputs subtask receives |
|---|---|
| `verifier_rubric_clarity` | verifier JSON text + prompt text |
| `verifier_rubric_specificity` | verifier JSON text + prompt text |

#### Subtask prompt template

Use this template for both subtasks, substituting `{GATE_DEFINITION}`,
`{VERIFIER_JSON}`, `{PROMPT_TEXT}`, and `{GATE_ID}`:

```
You are a QC judge for GDPVal/Omega task verifiers. Grade exactly ONE
dimension of the verifier and return ONE finding JSON. Do not do anything else.

## Context

You are evaluating the verifier as a definition document — how well its
rubrics capture the criteria a correct solution must meet. The verifier
drives automated reward later in the pipeline, so a weak verifier silently
weakens every downstream score.

## Gate definition

{GATE_DEFINITION}

## Inputs

### Task prompt
{PROMPT_TEXT}

### Verifier JSON
The rubric text to grade lives at verifiers[i].assertion.rubric.prompt.
What a rubric claims to measure is in verifiers[i].metadata.how_justification
and why_justification.

{VERIFIER_JSON}

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
passage (≤ 30 words) copied exactly from the verifier JSON rubric text. If you
cannot quote concrete evidence, set severity to 0.

**Confidence policy**
- Low confidence at severity 1 → demote to severity 0.
- Low confidence at severity ≥ 2 → keep severity; mark confidence "low".

**Hard-fail patterns are guidance, not auto-bumps.** Only flag when the pattern
is clearly present with quotable evidence.

**When torn between two severity levels,** add "uncertain": true to the finding.

## Required output

Return exactly one JSON object in this shape and nothing else:

{
  "dimension":      "{GATE_ID}",
  "severity":       <0|1|2|3>,
  "confidence":     "<low|medium|high>",
  "applicable":     true,
  "uncertain":      <true|false>,
  "evidence_quote": "<verbatim passage from a rubric prompt, or null>",
  "headline":       "<one sentence ≤ 25 words, specific to this verifier>",
  "justification":  "<1-3 sentences referencing the evidence>",
  "fixability":     "<trivial|fixable|structural|n/a>"
}
```

For `{GATE_DEFINITION}`, copy the full dimension block (YAML header + all prose)
from [verifier-qc.md](verifier-qc.md).

### Step 6-7 — Collect and adjust findings

Wait for both LLM subtasks to return. Merge with the 3 programmatic findings
(total: 5). Apply adjustments:

- `severity ≥ 1` with `evidence_quote` null or empty → demote to severity 0.
- `confidence == "low"` and `severity == 1` → demote to severity 0.
- `confidence == "low"` and `severity ≥ 2` → keep severity; tag for
  `needs_review`.

---

## Verdict computation

Only findings where `applicable == true` count. Gate roles and
`reject_at_severity` values are in [verifier-qc.md](verifier-qc.md).
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
# QC review — <task_id> · Verifier

**Verdict:** <accept | accept_with_fixes | needs_review | reject_fixable | reject_structural>
**Summary:** <one sentence, ≤ 25 words>
<!-- include only when verdict is needs_review: -->
**Review required because:** <reason>

## Top issues (must-fix)
1. **[sev N · <fixability> · <dimension>]** <headline>
   - Action: <specific action — name a rubric, quote its text, or cite the count>
   - Evidence: "<verbatim evidence_quote>"
<!-- up to 3; omit the section entirely if none -->

## Suggested fixes (minor)
- <specific suggestion>
<!-- up to 5; omit if none -->

## All dimension findings
| dimension | role | sev | conf | fixability | headline |
|---|---|---|---|---|---|
| verifier_spec_parseable | blocking | 0 | high | n/a | no issue |
| verifier_count_in_range | advisory | 0 | high | n/a | no issue |
| verifier_outcome_grader_present | advisory | 0 | high | n/a | no issue |
| verifier_rubric_clarity | advisory | 0 | high | n/a | no issue |
| verifier_rubric_specificity | advisory | 0 | high | n/a | no issue |
```

Every action must name a specific rubric or quote its text — "improve rubric
wording" is not acceptable.

---

## Dimension reference

All active gate definitions live in [verifier-qc.md](verifier-qc.md).

**LLM gates** (parallel subtasks):
`verifier_rubric_clarity` · `verifier_rubric_specificity`

**Programmatic gates** (run inline via `gdpval_qc.tools.check_verifier` (pipeline/.venv/bin/python -m …)):
`verifier_spec_parseable` · `verifier_count_in_range` · `verifier_outcome_grader_present`
