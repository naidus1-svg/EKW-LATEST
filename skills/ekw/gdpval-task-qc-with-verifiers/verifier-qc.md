# Verifier QC — offered stage

Grade the task's **verifier** (its grading "Rubric") as a *definition document*:
how well its rubrics capture the criteria a correct solution must meet. This is
the same artifact that drives automated reward later in the pipeline, so a weak
verifier silently weakens every downstream score.

**When to run this stage.** Either (a) *offered* after Source File and Prompt QC
in the full flow (ask whether the expert has a verifier/Rubric to QC; not
unprompted); or (b) **standalone**, when the expert asks to QC only the verifier
(source/prompt already done — see *Two ways to run* in [SKILL.md](SKILL.md)).
Like the prompt, the **verifier is not stored in the task folder** — the expert
pastes it into the conversation (it is the task's "Rubric" in the tracker). In
standalone mode the expert still pastes the **prompt** as context (used by 5 of
the 6 LLM dims, but **not** re-graded); `Source Documents/` is **not** needed,
and the `Expert Solution/` is optional but strengthens the construct-validity,
coverage, and missing-dimensions dims.

**Before grading, confirm the required inputs are present** — the verifier JSON
(pasted) and the prompt (pasted). If either is missing, ask the expert and wait;
don't start grading (see
[Required inputs](SKILL.md#required-inputs--confirm-before-grading) in SKILL.md).

Grade every dimension following the protocol/scales/policies in
[SKILL.md](SKILL.md), then fold these findings into the same verdict computation.

## Getting and handling the verifier

1. **Ask the expert to paste the verifier JSON** into the conversation (the SOP
   tells them to wrap it in `<verifier>` … `</verifier>` tags; they may also
   just paste it raw or point at a local copy). It is one JSON object of this
   shape:

   ```json
   {
     "task_id": "...",
     "config":  { "models": [...], "temperature": 1.0, ... },
     "verifiers": [
       {
         "name": "v1",
         "metadata": {
           "how_justification": "what this rubric checks",
           "why_justification": "why it matters",
           "tag": "...",
           "grading_role": "outcome | process",
           "classification": "core | ...",
           "importance": "core | ...",
           "weight": 0.05
         },
         "assertion": { "type": "rubric", "rubric": { "prompt": "Pass if … Fail if …" } }
       }
     ]
   }
   ```

   The **rubric text** you grade for clarity/specificity lives at
   `verifiers[i].assertion.rubric.prompt`. What a rubric *claims* to measure is
   in `verifiers[i].metadata.how_justification` / `why_justification`. Outcome
   graders are marked `metadata.grading_role == "outcome"` (Omega) or
   `metadata.classification == "core"` (legacy).

2. **Save the pasted JSON to a file** (e.g. `<task_dir>/verifier.json`) and run
   the deterministic checks — do **not** grade these three by hand:

   ```bash
   pipeline/.venv/bin/python -m gdpval_qc.tools.check_verifier <task_dir>/verifier.json   # defaults: --min 6 --max 20
   ```

   It emits findings for `verifier_spec_parseable`, `verifier_count_in_range`,
   and `verifier_outcome_grader_present` in the standard finding shape; fold
   them straight into the verdict. (A truncated paste will trip
   `verifier_spec_parseable` — re-copy the full Rubric cell if so.)

3. **Read the rubrics directly** (the pasted JSON is already text) and grade the
   six LLM dimensions below.

## Applicability and inputs

- **All dimensions here require `task_has_verifier`** — satisfied because the
  expert provided the verifier. (If `verifier_spec_parseable` fails, the
  LLM dimensions still apply, but grade them against the rubrics you *can* read.)
- Several dimensions take **`solution_files`** as input — use the
  `Expert Solution/` when it exists (extract it with
  `pipeline/.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir> --solution`). When the
  solution is absent (early QC), judge the verifier against the **prompt** and
  the rubrics alone; never mark a dimension `not applicable` just because the
  solution is missing.
- Several dimensions reference **`verifier_assertion_summary`** — a digest of
  how each rubric scored across past model runs. That digest is built only from
  a Harbor task's `evals/` directory, which **does not exist in the expert
  layout**, so the summary is **never available in this stage.** Each such
  dimension carries explicit fallback guidance ("When the summary isn't
  available … fall back to reading each rubric"); always use that fallback path
  here.

Where a `gate:` block below says `instruction`, that is the **prompt** the
expert pasted; where it says `verifier_spec_json`, that is the pasted verifier.

---

## Verifier Quality

These dimensions evaluate the verifier as a definition document — how well it
captures the criteria a correct solution must meet.

### verifier_rubric_clarity

```yaml
dimension_name: "Verifier Rubric Clarity"
check_kind: llm
inputs: [verifier_spec_json, instruction]
applies_when:
  builtin: task_has_verifier
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Across all verifier rubrics, are the criteria stated
clearly enough that two different judges would reach the same verdict on the
same solution?

**How to judge.** Read each rubric's `assertion.rubric.prompt` and ask
whether it would be interpreted the same way by two competent reviewers.
Watch for vague words ("appropriate", "reasonable", "sufficient") used
without anchoring, multi-clause rubrics that pack several distinct checks
into one, and rubrics whose pass/fail criterion is implicit rather than
stated.

**Severity rubric.**
- **0** — All rubrics state criteria unambiguously; two judges would agree.
- **1** — Most rubrics clear; one or two have minor ambiguity that wouldn't
  flip a verdict.
- **2** — Multiple rubrics are ambiguous in ways that would produce judge
  disagreement on borderline outputs.
- **3** — Pervasive ambiguity; the rubrics cannot reliably be applied without
  the author present.

**Common hard-fail patterns.**
- Multi-clause compound rubrics ("the memo includes findings AND
  recommendations AND a risk table") — partial credit is impossible because
  the whole rubric fails on any one piece.
- Pass condition stated as "no major issues" or "no obvious problems" — a
  default-pass rubric that any non-trivially-broken solution will pass.
- Use of "appropriate", "reasonable", "sufficient", "thorough", "robust" as
  pass conditions without any anchoring to observable features.
- Rubrics where the pass criterion is implicit — the rubric describes the
  topic to grade but never states what counts as passing.
- Rubrics that depend on undefined terms specific to the task without
  defining them.

---

### verifier_rubric_specificity

```yaml
dimension_name: "Verifier Rubric Specificity"
check_kind: llm
inputs: [verifier_spec_json, instruction]
applies_when:
  builtin: task_has_verifier
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Are the rubrics concrete enough to grade against, or
do they ask vague qualitative questions that require the judge to invent the
criteria?

**How to judge.** A specific rubric asks something observable: "the document
includes a synthesis table of the three audit findings cross-mapped to
federal requirements". A non-specific rubric asks something interpretive:
"the analysis is high quality". The distinction is whether the rubric points
at concrete features of the solution.

**Severity rubric.**
- **0** — All rubrics state concrete, observable criteria.
- **1** — Most rubrics specific; one or two lean on vague qualitative
  language but are mostly anchored.
- **2** — Several rubrics rely on undefined qualitative judgments
  ("appropriate", "professional", "thorough" without anchoring).
- **3** — Rubrics are predominantly impressionistic; the judge would have to
  invent most of the criteria.

**Common hard-fail patterns.**
- Rubric asks the judge to perform substantive analysis themselves to grade
  ("the financial model correctly projects revenue", "the recommendation is
  optimal") — the rubric requires the judge to redo the work.
- Subjective qualitative judgments without observable criteria ("the analysis
  is thorough", "the prose is professional", "the tone is appropriate").
- Rubric criteria depend on undefined task-specific terms ("ensure the
  appropriate tone for the audience" with no anchor for "appropriate").
- Rubric grades aesthetic preferences rather than functional correctness
  ("the document is well-organised" without specifying what organisation
  means here).

---

### verifier_rubric_construct_validity

```yaml
dimension_name: "Verifier Rubric Construct Validity"
check_kind: llm
inputs: [verifier_spec_json, instruction, solution_files, verifier_assertion_summary]
applies_when:
  builtin: task_has_verifier
gate:
  role: blocking
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Do the rubrics actually measure the quality they
claim to measure? If a rubric is named "instruction alignment" or framed as
checking output quality, does it in fact distinguish aligned outputs from
misaligned ones — or does it measure a proxy that happens to correlate?

**How to judge.** For each rubric, identify what it *claims* to assess (often
clear from its name + how_justification + why_justification metadata), then
examine whether the assertion text actually tests that. A common failure is
rubrics that check surface features (presence of a heading named "Findings")
while claiming to grade substance (whether findings are actually present).

When `verifier_assertion_summary` is provided, also use the actual pass/fail
patterns it reports. A rubric that *claims* to measure substance but
appears in the "always-passes" list of the summary is a strong construct-
validity red flag — any plausible attempt passed it, so it isn't actually
measuring what it claims.

**Severity rubric.**
- **0** — Every rubric is a valid construct for what it claims to measure.
- **1** — Most rubrics valid; one or two measure adjacent properties rather
  than the stated target.
- **2** — Multiple rubrics measure proxies that don't reliably indicate the
  intended construct.
- **3** — Rubrics measure something materially different from what they
  claim, or rely on proxies so loose they don't discriminate.

**Common hard-fail patterns.**
- Rubric checks the expert solution's specific section ordering, headings,
  or phrasing rather than requirements stated in the instruction.
- Rubric checks surface presence ("includes a section titled 'Findings'")
  while its justification claims it grades substance ("the findings are
  comprehensive").
- Rubric tests alphabetical or positional conventions the instruction never
  specified (e.g. "states are listed alphabetically" when ordering wasn't
  required).
- Rubric tests for the expert's specific stylistic choices (paragraph length,
  tone, bullet vs. prose) that weren't required by the task.

**Not a hard fail (eval-context convention).** Verifiers that demand
specific numerical or factual values (e.g., "the memo outputs $1.24M as
the final figure", "the model projects 8.7% growth") are LEGITIMATE
deterministic outcome checks for tasks where there is a uniquely-correct
answer. Do NOT flag value-specific verifiers as a construct-validity
problem — they are doing exactly what deterministic verification should
do. Flag them only when the specific value being checked clearly doesn't
correspond to a uniquely-correct answer (e.g. a value that varies with
defensible interpretation choices).

---

### verifier_outcome_coverage

```yaml
dimension_name: "Verifier Outcome Coverage"
check_kind: llm
inputs: [verifier_spec_json, instruction, solution_files, verifier_assertion_summary]
applies_when:
  builtin: task_has_verifier
gate:
  role: blocking
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Do the rubrics together cover the important *outcomes*
of a correct solution? "Outcome" means "did the solution achieve the intended
result", as opposed to "process" rubrics that only check whether expected
steps were taken.

**How to judge.** Enumerate the substantive outcomes a good solution must
achieve (drawn from the instruction). For each, check that at least one
rubric in the verifier graders that outcome. Coverage failures are typically
verifiers that check format/structure thoroughly but leave the substantive
correctness ungraded.

When `verifier_assertion_summary` is provided, use it as a second lens.
Rubrics in the "always-passes" list are weak coverage — they pass for any
plausible attempt, so they don't actually contribute to outcome
discrimination. If many rubrics are in that list, the verifier likely has
broad nominal coverage but thin effective coverage.

**Severity rubric.**
- **0** — All major outcome aspects are covered by at least one rubric.
- **1** — Coverage is broad with one minor gap.
- **2** — A material outcome aspect (something the task is centrally about)
  is uncovered.
- **3** — Coverage is fundamentally lacking — multiple critical outcomes
  ungraded; the verifier could pass a wrong solution.

**Common hard-fail patterns.**
- All rubrics in the verifier test format or structure (file types, section
  presence, heading names); none test whether the substance is correct.
- All rubrics check that the agent *did* something (produced output, included
  a section); none check whether doing it achieved the intended outcome.
- Two or more rubrics test the same underlying property (double-counting) —
  the verifier penalises the same failure twice in the aggregate reward.
- The central analytical question of the task has no rubric graders, while
  many peripheral concerns each have dedicated rubrics.

---

### verifier_missing_critical_dimensions

```yaml
dimension_name: "Verifier Missing Critical Dimensions"
check_kind: llm
inputs: [verifier_spec_json, instruction, solution_files, verifier_assertion_summary]
applies_when:
  builtin: task_has_verifier
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Is there any specific important quality criterion
that the verifier does not check at all? This is the complement to
`verifier_outcome_coverage` — that dim asks how broad coverage is, this dim
asks specifically what's missing.

**How to judge.** Produce a short list (one or two items) of criteria that a
careful human reviewer of the solution would weight heavily and that the
verifier does not test. If you cannot name anything specific missing, the
severity is 0.

When `verifier_assertion_summary` is provided, cross-reference its
per-verifier patterns. If important outcomes are nominally covered by
rubrics that all sit in the "always-passes" list, treat that as effectively
missing coverage of those criteria.

**Severity rubric.**
- **0** — No critical gaps that a careful reviewer would flag.
- **1** — One minor criterion uncovered that probably should be graded.
- **2** — One important criterion uncovered — a criterion a domain reviewer
  would weight heavily.
- **3** — Multiple important criteria uncovered.

**Common hard-fail patterns.**
- The central analytical question of the task (the part that distinguishes
  good solutions from mediocre ones) is not graded by any rubric.
- The most analytically demanding part of the task is ungraded while easier
  surface checks dominate.
- A specific requirement named in the instruction ("recommend a course of
  action") has no corresponding rubric.
- The verifier grades many peripheral aspects but misses the core
  deliverable's primary quality criterion.

---

### verifier_discriminative_power

```yaml
dimension_name: "Verifier Discriminative Power"
check_kind: llm
inputs: [verifier_spec_json, solution_files, verifier_assertion_summary]
applies_when:
  builtin: task_has_verifier
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Would this verifier distinguish a good solution from
a plausible-but-wrong solution? If most rubrics would pass for any reasonable
attempt at the task, the verifier has low discriminative power and won't be
useful for ranking model performance.

**How to judge.** Use `verifier_assertion_summary` as the primary signal
when it's available: it lists per-verifier pass rates across multiple
models' trials. The summary's "always-passes" set is direct evidence of
weak discrimination — those rubrics pass for whatever those models
produced, regardless of solution quality. The "discriminates" set is
direct evidence that the verifier IS distinguishing model performance.

When the summary isn't available (no `evals/` directory present), fall
back to reading each rubric in `verifier_spec_json` and asking: would a
"plausible but wrong" answer (something a competent agent who
fundamentally misread the task would produce) pass it? If yes for most
rubrics, the verifier doesn't discriminate.

**Severity rubric.**
- **0** — Verifier clearly distinguishes good from plausibly-wrong solutions.
- **1** — Mostly discriminative; one or two rubrics would pass any plausible
  attempt.
- **2** — Several rubrics are too lenient; the verifier mostly accepts.
- **3** — Verifier accepts virtually any plausible attempt; no
  discrimination.

**Common hard-fail patterns.**
- Default-pass rubrics — pass condition is "no obvious problems" or
  "doesn't contain X"; passes any solution that doesn't actively fail.
- Rubrics that pass any output containing certain keywords or section
  headings, regardless of substance.
- Rubrics that pass based on length alone ("the memo is at least 500 words")
  without quality criteria.
- Pass criterion is met by skeleton or placeholder solutions — the rubric
  doesn't require real content.
- Rubrics whose pass condition is satisfied by the formatting itself rather
  than by analytical correctness.

---

## Programmatic Checks (no LLM)

Do **not** grade these three by reading the JSON — run
`pipeline/.venv/bin/python -m gdpval_qc.tools.check_verifier <task_dir>/verifier.json` and fold its
emitted findings into the verdict. The blocks below document what each check
does; the script is the authority for the severity.

### verifier_spec_parseable

```yaml
dimension_name: "Verifier Spec Parseable"
check_kind: programmatic
callback: check_verifier_parseable
inputs: [verifier_spec_json]
applies_when:
  builtin: task_has_verifier
gate:
  role: blocking
  reject_at_severity: 2          # an unparseable verifier is structurally broken
```

**What this evaluates.** Does the verifier JSON parse cleanly into the
`{verifiers: [...]}` shape the framework runtime expects?

**Callback behaviour.** Severity 0 if the spec parses; severity 2 if it is
empty, not valid JSON, not an object, or missing the `verifiers` list. The
parse error is attached to the finding for reviewer drill-down. (A truncated
paste is the usual cause of a failure here.)

---

### verifier_count_in_range

```yaml
dimension_name: "Verifier Count in Range"
check_kind: programmatic
callback: check_verifier_count_in_range
inputs: [verifier_spec_json]
applies_when:
  builtin: task_has_verifier
gate:
  role: advisory
  reject_at_severity: 3
config:
  min_verifiers: 6
  max_verifiers: 20
```

**What this evaluates.** Are there a reasonable number of verifier rubrics —
not so few that coverage is necessarily thin, not so many that the framework
becomes brittle?

**Callback behaviour.** Counts rubrics in the spec. Severity 0 if count is in
`[min_verifiers, max_verifiers]`; severity 1 if outside by 1–2; severity 2 if
outside by more.

---

### verifier_outcome_grader_present

```yaml
dimension_name: "Verifier Outcome Grader Present"
check_kind: programmatic
callback: check_verifier_outcome_grader_present
inputs: [verifier_spec_json]
applies_when:
  builtin: task_has_verifier
gate:
  role: advisory
  reject_at_severity: 3
```

**What this evaluates.** Does the verifier include at least one
*outcome-grading* rubric? A verifier that grades only process or format
without checking the substance of the deliverable cannot drive a
meaningful reward.

**Callback behaviour.** Severity 0 when at least one rubric matches an
outcome marker; severity 2 otherwise. The check handles both verifier
spec schemas the framework encounters:

- Legacy GDPVal-216: `metadata.classification == "core"` (where "core"
  implied outcome-checking).
- Omega: `metadata.grading_role == "outcome"` (where importance and
  grading role are separate metadata fields).

A rubric matches if EITHER marker is set.

---

When every applicable dimension above has a finding (the six graded by you,
the three from `check_verifier.py`), fold them into the verdict in
[SKILL.md](SKILL.md) and update the review. Title the review
`# QC review — <task_id> · Verifier` (or append a Verifier section if you are
extending an earlier review).
