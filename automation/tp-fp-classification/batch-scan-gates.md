# Batch-wide rubric gates

Standing LLM gates distilled from confirmed `task_author` `true_positive`
findings across TP/FP adjudication rounds (see
`automation/tp-fp-classification/gate-mining/SKILL.md` for the process
that maintains this file — read that first if you're adding a gate, not
just this file). Each gate targets a **specific, quotable structural
defect**, not a stylistic/cosmetic preference — the goal is high
precision on real, scoring-relevant bugs, not coverage of every possible
rubric weakness. `task_author` and `true_positive` are values from the TP/FP
classification skill (`automation/tp-fp-classification/SKILL.md`): a confirmed
defect in the task's own rubric, prompt or source files that the task author
must fix. Run each as an isolated subtask per task (fresh agent,
no memory of the batch), one gate per subtask call, in parallel across
gates and across tasks.

This file accumulates across rounds — it is not scoped to one batch.
Gates get added, corroborated, tightened, or retired round over round;
see the Changelog below for the history.

**Two versions of each gate below.** The "What this evaluates / How to
judge / Severity rubric / Do not flag / Evidence policy" prose is our own
reference documentation — read it to understand the gate, but don't paste
the whole thing into a tool with a character cap. The **"Guidance (paste
into tool)"** block right under each gate's yaml header is the compressed,
self-contained version meant for the actual "when to answer pass, fail, or
not_applicable" field — it carries the same precondition rules in under
1,000 characters, well inside a 5,000-character cap.

## Changelog

- **2026-08-31 (QCR_EKW_27082026; `task_263`/`469`/`177`/`3`/`604`)**:
  initial six gates (1-6 below) distilled from confirmed Major-severity
  findings on this batch.
- **2026-08-31**: considered a gate for "criterion names control figures
  but its FAIL clause doesn't actually require them" (seen on `task_469`,
  `task_336`) — rejected, no quotable evidence policy possible (how loose
  is too loose is a judgment call, not a quote comparison). Left to
  manual review.
- **2026-08-31**: considered a gate for "required document structure is
  never checked" (seen on `task_604`) — rejected for the same reason.
  Left to manual review. Revisit if this recurs on 2+ more tasks across
  future rounds (see `gate-mining/SKILL.md` Methodology step 3).

---

## Gate 1 — `rubric_scope_excludes_required_sources`

```yaml
dimension_name: "Verifier Scope Excludes Required Sources"
check_kind: llm
inputs: [verifier_or_judge_toml, source_document_filenames]
applies_when:
  builtin: task_has_verifier
gate:
  role: blocking
  reject_at_severity: 2
```

**Guidance (paste into tool, ≤ 5,000 chars):**

> PASS if every criterion needing outside-source verification is paired
> with a judge files list that includes those sources, OR the only
> unverifiable part is self-detectable from the deliverable alone (an
> explicit citation to a named outside index/comp set, or a conclusion
> checkable against the deliverable's own numbers) — neither needs the
> source package. FAIL only if: (1) you first open the memo/deliverable
> and name one specific figure, claim, or input it states as fact; (2) you
> confirm that exact figure has no visible derivation path in the files
> given to the judge; and (3) you quote that figure plus the criterion
> text plus the `files = [...]` line, all three, in your answer. Quoting
> only the criterion text and the files list, without naming an actual
> offending figure you found in the deliverable, is not evidence of a
> defect — default to PASS in that case. NOT_APPLICABLE if no criterion in
> this rubric requires checking against anything outside the deliverable
> itself.

**What this evaluates** *(reference only — do not paste)*. Whether a
criterion's pass/fail condition requires checking the deliverable against
source materials, filings, provenance, or "no outside/fabricated data" —
while the judge block grading that criterion is never given those
materials to check against, only the deliverable files themselves.

**How to judge.**
1. For each criterion, read its PASS/FAIL text closely for language that
   requires comparing the deliverable against something *outside* itself:
   "source", "filing", "outside data", "not fabricated", "supported by",
   "traceable to", "as stated in the [agreement/schedule/filing]".
2. Read the `files = [...]` list on that criterion's judge block.
3. Check whether anything in that list is actually a source/reference
   document (matches `environment/data/` or equivalent), or whether it is
   only the agent's own output deliverables.
4. Flag only if the criterion genuinely cannot be checked without the
   missing source — i.e., a judge handed only the deliverable has no way
   to catch a fabricated or misattributed fact even in principle.
5. **Split "absence of outside citation" from "fidelity of a specific
   figure" before scoring.** A FAIL condition like "presents outside
   market/comparable data" is usually self-detectable from the deliverable
   alone — an explicit reference to a named external index, comp set, or
   benchmark shows up in the memo's own text, so the judge doesn't need
   the source package to notice it. A FAIL condition like "fabricated
   facts as inputs" (confirming a *specific number* was legitimately
   derived, not invented) genuinely cannot be checked without the source
   package. Only the second shape earns severity ≥ 2. A criterion that
   mixes both shapes in one FAIL clause caps at the severity of its
   self-detectable half unless the fabricated-figure half is the one
   actually doing work in this task (e.g. the deliverable contains a
   specific figure with no visible derivation path even inside its own
   two files). A FAIL clause that also covers "asserts conclusions
   unsupported by its own calculations" is entirely self-detectable — that
   half is checked by comparing the memo's stated conclusion against the
   workbook's own numbers, both of which are already in the judge's
   `files` list. It never contributes to this gate; do not cite it as
   part of a missing-sources finding.
6. **Naming a specific figure is a precondition for answering FAIL, not
   supporting detail for it.** Before writing FAIL, you must first open
   `covenant_compliance_memo.docx` (or the task's equivalent memo) and
   identify one concrete figure, claim, or input the memo states as fact.
   Then check whether that exact figure is reconstructable from the
   workbook/calculation file alone. If you can point to a specific number
   with no visible derivation path in the two graded files, quote it and
   answer FAIL. If you cannot — if your only basis is "the criterion
   mentions sources and the files list doesn't include them" without
   having actually inspected the memo for a concrete offending figure —
   you have not met the bar for FAIL. Restating the criterion text and the
   `files = [...]` line is never sufficient by itself; that is a necessary
   but not sufficient condition. Default to PASS when you cannot name the
   figure.

**Severity rubric.**
- **0** — every criterion needing outside verification is given the needed
  sources.
- **1** — one low-weight criterion lacks sources, but the same ground is
  covered by another criterion that does have them.
- **2** — a moderate-weight criterion needing outside verification has zero
  access to sources.
- **3** — the heaviest outcome criterion(s) in the deliverable rest on
  claims the judge cannot verify at all.

**Do not flag:** criteria that only check internal consistency of the
deliverable itself (e.g., "the workbook's totals tie out to its own
inputs") — those never needed outside sources. Also do not flag at
severity ≥ 2 a FAIL condition whose violation would be visible directly in
the deliverable's own text (an explicit citation to a named outside
source, index, or comp set) — that half of the check doesn't need the
source package, only careful reading of the deliverable, so a missing
`files` entry doesn't block it.

**Evidence policy.** A FAIL requires THREE quotes, all present in the same
response: (1) the criterion's PASS/FAIL text, (2) the exact
`files = [...]` line it's paired with, AND (3) a specific figure, claim,
or input actually written in the deliverable, with a one-sentence
explanation of why it has no visible derivation path in the files the
judge was given. Quotes (1) and (2) alone are restating the setup, not
evidence of a defect — they are necessary but never sufficient. If you
cannot produce quote (3), the criterion has not been shown to be
unverifiable in this specific case; answer PASS instead.

*(Superseded by the "Guidance (paste into tool)" block above — kept only
as the ternary framing for tools that ask for it in different field names
than "guidance"; the content is identical.)*

---

## Gate 2 — `rubric_self_contradicts_stated_freedom`

```yaml
dimension_name: "Verifier Contradicts Its Own Stated Freedom"
check_kind: llm
inputs: [verifier_or_judge_toml]
applies_when:
  builtin: task_has_verifier
gate:
  role: blocking
  reject_at_severity: 2
```

**Guidance (paste into tool, ≤ 5,000 chars):**

> PASS if no criterion hardcodes one exact answer to a decision that
> another criterion in the same rubric explicitly says is open/flexible.
> FAIL if one criterion states a decision is left to the solver's
> judgment (e.g. "need not reproduce any specific split," "any reasonable
> sequence") while a different criterion requires one specific instance of
> that same decision as the only way to pass — quote both sentences
> verbatim. NOT_APPLICABLE if the rubric contains no explicit
> freedom/latitude statements at all.

**What this evaluates** *(reference only — do not paste)*. Whether one
criterion explicitly grants the solver latitude on an open decision (a count, a sequence, a classification, a
disposition), while a *different* criterion in the same rubric hardcodes
one specific instance of that same decision as the only way to pass.

**How to judge.**
1. Collect every "freedom statement" in the rubric — explicit language
   disclaiming one fixed answer ("need not reproduce any specific...",
   "any reasonable...", "left to the analyst", "no fixed X required").
2. Collect every "hardcoded requirement" — a criterion whose only PASS path
   is one exact enumerated list, one exact classification, or one specific
   value/sequence.
3. For each hardcoded requirement, check whether it falls inside the scope
   a freedom statement elsewhere in the *same rubric* explicitly names.
4. Confirm the freedom statement's own wording doesn't already carve out
   an exception for that specific item — if it does, there's no
   contradiction.

**Severity rubric.**
- **0** — no hardcoded requirement falls inside a stated-freedom scope.
- **1** — tension exists but on a low-weight or advisory criterion.
- **2** — contradiction on a moderate-weight criterion.
- **3** — the hardcoded criterion is high-weight/outcome-defining and sits
  squarely inside what the freedom statement names as open.

**Do not flag:** a freedom statement about one axis being compared against
a hardcoded requirement on a genuinely different axis, or a freedom
statement whose own text already excepts the hardcoded item.

**Evidence policy.** Quote the exact freedom-statement sentence and the
exact hardcoded PASS/FAIL sentence, both verbatim. No quote pair, no
finding.

---

## Gate 3 — `rubric_requires_unsupported_content`

```yaml
dimension_name: "Verifier Requires Content the Prompt Forbids Inventing"
check_kind: llm
inputs: [instruction, verifier_or_judge_toml, source_document_filenames, golden_solution_excerpt]
applies_when:
  builtin: task_has_closed_world_instruction
gate:
  role: blocking
  reject_at_severity: 2
```

**Guidance (paste into tool, ≤ 5,000 chars):**

> PASS if every criterion's required facts/figures/conclusions trace to
> something in the provided source documents or the golden solution's own
> citations. FAIL if the prompt explicitly bans inventing facts (e.g. "do
> not invent," "work only from attached materials") and a criterion's pass
> condition requires a claim, number, or authorization absent from every
> provided document — confirm by checking whether the golden solution
> itself can satisfy the criterion without asserting the same unsupported
> claim. NOT_APPLICABLE if the prompt contains no closed-world/no-invention
> instruction.

**What this evaluates** *(reference only — do not paste)*. Whether a
criterion's PASS condition requires a specific fact, figure, legal
conclusion, or authorization that cannot be traced to anything in the
attached source materials — in a task whose prompt explicitly instructs
the solver not to invent or assume beyond what is given.

**How to judge.**
1. **Gate check first.** Confirm the prompt contains explicit closed-world
   language ("do not invent access/permissions/facts...", "work only from
   the attached materials", or similar). If absent, mark `applicable:
   false` and stop — this gate does not apply to open-research tasks.
2. For each outcome criterion, extract the specific claim, number, or
   authorization required to PASS.
3. Search the provided source documents for that claim. Also check the
   golden solution's own citations, if available — it may cite a source
   you haven't checked yet.
4. If the claim is genuinely absent from every provided document and the
   golden cites no source for it either, this is a candidate finding.
5. **Mandatory confirmation before reporting severity ≥ 2:** check whether
   the golden/oracle deliverable actually satisfies this same criterion as
   written. If the golden *also* cannot satisfy it without asserting the
   same unsupported claim, that's strong confirmation — report at high
   confidence. If the golden manages to satisfy it via a source you
   missed, do not report; you likely missed a citation, not a real defect.

**Severity rubric.**
- **0** — every criterion's required claims trace to provided material.
- **1** — a low-weight criterion requires an untraceable minor detail.
- **2** — a moderate-weight criterion requires an unsupported conclusion.
- **3** — an outcome-defining criterion requires a conclusion no provided
  material supports — meaning even a maximally careful, honest solver
  cannot pass without inventing something, and the golden itself cannot
  cleanly clear it either.

**Do not flag:** judgment calls the prompt explicitly invites (e.g. "where
the materials leave a genuine judgment call, state your assumption and
reason") — those are supposed to require reasoning beyond the literal
text; that is different from requiring a claim with no support anywhere in
the package.

**Evidence policy.** Quote the prompt's closed-world sentence, the
criterion's PASS/FAIL text, and the specific gap in source coverage
(or the golden's own failure to satisfy it, if the confirmation step ran).
Three-part evidence is required for severity ≥ 2 — a finding missing any
one of the three should be demoted to severity 1 or discarded.

---

## Gate 4 — `rubric_hardcodes_undisclosed_specific_requirement`

```yaml
dimension_name: "Verifier Hardcodes an Undisclosed Specific Requirement"
check_kind: llm
inputs: [instruction, verifier_or_judge_toml, source_document_excerpts]
applies_when:
  builtin: task_has_verifier
gate:
  role: blocking
  reject_at_severity: 2
```

**Guidance (paste into tool, ≤ 5,000 chars):**

> Before answering, list EVERY criterion in this rubric whose PASS
> condition names one specific item, fact, count, or aggregate the
> solution must produce (not just the first or most obvious one) — check
> all of them, since more than one can share this shape in the same
> rubric. For each one: PASS if that specific item/fact/count is either
> named directly in the prompt, or the source material's own language
> flags it as uncertain/debatable (giving the solver a textual signal to
> notice it). FAIL if the prompt states the underlying requirement only
> generically, with no way to identify that this particular instance is
> the one meant; AND the source material's own language gives no signal
> of the ambiguity/specificity the criterion demands — or actively
> contradicts it (e.g. source calls the item "settled" or "not expected to
> recur," criterion requires treating it as a live judgment call) — quote
> the criterion text, the prompt's generic sentence, and the source's own
> characterization, all three. Answer FAIL if even one criterion in the
> full list meets this bar, even if others pass. NOT_APPLICABLE if no
> criterion requires singling out one specific unnamed item, fact, count,
> or aggregate.

**What this evaluates** *(reference only — do not paste)*. Whether a
PASS/FAIL condition requires the solver to single out one particular
item, fact, count, or classification by name, when the prompt states the
underlying requirement only in generic/open terms — with nothing in the
provided materials signaling in advance that this specific instance is
the one the rubric author had in mind. Distinct from Gate 3: the fact
itself is usually present and accurate; the defect is that the criterion
demands a specific *interpretive stance or selection* the prompt never
narrows down to, sometimes directly contradicted by the source's own
characterization.

**How to judge.**
1. For each criterion, check whether its PASS condition names one
   specific item, figure, count, or label the solution must produce or
   explicitly acknowledge (a named line item, an exact number of items in
   a list, one particular classification).
2. Check whether the prompt's instruction covering that requirement is
   generic — stated in a way that could apply to many or any items/counts,
   without singling out this one ("where the materials leave a genuine
   judgment call, state your assumption," "your recommended next steps,"
   "identify material risks").
3. If the prompt is generic and the criterion is specific, check how the
   source documents themselves characterize that specific item. If the
   source's own language plainly settles it (states it as fact, "not
   expected to recur," "properly classified," no hedge words) with no
   textual signal of ambiguity, that is strong confirming evidence — an
   honest, careful solver reading only the provided materials has no way
   to know this exact item is the one meant to be singled out.
4. **Distinguish from a legitimate specific requirement.** If the source
   material itself flags the item as debatable in its own words (hedge
   language: "may qualify," "unclear whether," "management believes but
   auditors have questioned") then the specificity IS derivable from the
   materials and this is not a defect.
5. If real agent-run trajectories are available, check whether every
   genuine run failed on exactly this criterion despite otherwise
   reasonable analysis — strong corroborating evidence this couldn't be
   inferred, not weak solver performance.

**Severity rubric.**
- **0** — every criterion's specificity is either named in the prompt or
  signaled by the source's own hedge language.
- **1** — a low-weight criterion is specific with no explicit signal, but
  a careful reader could still plausibly infer it from context.
- **2** — a moderate-weight criterion requires singling out one item with
  no textual signal anywhere in the provided materials.
- **3** — an outcome-defining criterion requires a specific answer that
  only the rubric author's own reference file names, real agent runs fail
  on it despite otherwise sound analysis, and the source's own language
  contradicts (not just omits) the ambiguity/specificity the criterion
  demands.

**Do not flag:** criteria whose specific requirement is genuinely
derivable — named directly in the prompt, singled out by a source
document's own hedge/uncertainty language, or the only reasonable reading
of an otherwise-unambiguous instruction.

**Evidence policy.** A FAIL requires three quotes in the same response:
(1) the criterion's PASS/FAIL text naming the specific item/count, (2) the
prompt's generic instruction it's supposedly an instance of, and (3)
EITHER the source document's own characterization of that specific item
(showing it gives no signal of, or contradicts, the ambiguity the
criterion demands) OR, when the required item is a derived aggregate/count
rather than one named line item (e.g. "39 lines" computed by
cross-referencing two data tables), a demonstration that no single cell,
note, or document anywhere in the source package labels or requests that
aggregate — state which tables you checked and that none names or flags
it. Missing all forms of quote (3) caps the finding at severity 1.

---

## Gate 5 — `rubric_rejects_golden_reference`

```yaml
dimension_name: "Rubric Rejects the Task's Own Golden Reference"
check_kind: llm
inputs: [verifier_or_judge_toml, golden_solution_excerpt, oracle_reward_details]
applies_when:
  builtin: task_has_golden_and_oracle_run
gate:
  role: blocking
  reject_at_severity: 2
```

**Guidance (paste into tool, ≤ 5,000 chars):**

> PASS if the oracle/golden run (the oracle run submits the reference answer) scores a genuine pass (or the oracle's
> reward-details shows no FAIL) on every criterion in this rubric.
> FAIL only if: (1) the oracle/golden run's own reward-details or judge
> output shows a FAIL/zero on a specific criterion; (2) you quote the
> criterion's FAIL condition and the golden's actual content on that same
> point, showing the golden's content is what triggers the FAIL — not a
> pipeline/infra error (check whether the failure is a grammar-size error,
> timeout, or other non-content 400-class failure in runtime.log; if so,
> this is NOT_APPLICABLE, not a rubric defect); and (3) confirm this isn't
> a deliberate adversarial trap the golden intentionally fails as a worked
> counter-example (check the golden's own internal notes/comments for
> stated intent). NOT_APPLICABLE if no oracle run is available, or the
> only failures are infra/pipeline errors unrelated to content.

**What this evaluates** *(reference only — do not paste)*. Whether the
task's own reference (golden) solution — the best-faith, fully-informed
answer the rubric is calibrated against — itself fails a criterion in
that same rubric. Unlike Gate 3, this does not require closed-world
prompt language; it is a standalone, criterion-agnostic check that catches
any case where the rubric's own calibration source cannot clear its own
bar, for whatever underlying reason.

**How to judge.**
1. Read the oracle/golden run's `reward-details.json` (or equivalent judge
   output) for this task. List every criterion scored FAIL or 0.
2. For each FAIL, rule out infra causes first: check `runtime.log` for a
   grammar-too-large error, timeout, or other 400-class failure. If the
   failure is infra, not content, this criterion does not count — mark
   `applicable: false` for it specifically.
3. For remaining genuine content FAILs, read the golden's actual
   deliverable content on that point and the criterion's FAIL condition
   side by side. Confirm the golden's own words are what the criterion's
   FAIL language describes.
4. Check whether the golden's own internal documentation (comments,
   footnotes, an explicit "intentional trap" note) states this is a
   deliberate adversarial element the golden is meant to fail as a
   worked counter-example. If so, this is `design_intent`, not a defect —
   do not report at severity ≥ 2.
5. If a real agent trial scores *higher* on this same criterion (or on
   overall reward) than the oracle, that's strong corroborating evidence
   the rubric, not the trial, is miscalibrated.

**Severity rubric.**
- **0** — the oracle/golden run passes every criterion, or all FAILs are
  infra-only or documented adversarial traps.
- **1** — the golden fails one low-weight/advisory criterion with no
  documented trap intent, but the failure doesn't affect the overall
  verdict much.
- **2** — the golden fails a moderate-weight criterion with no documented
  trap intent.
- **3** — the golden fails an outcome-defining criterion with no documented
  trap intent, and a real agent trial scores better on it than the golden
  does.

**Do not flag:** infra/pipeline failures (grammar-size errors, timeouts)
visible in `runtime.log`; criteria the golden's own internal notes mark as
an intentional adversarial trap it's meant to fail.

**Evidence policy.** A FAIL requires: (1) the criterion's FAIL condition
quoted verbatim, (2) the golden's actual content on that point quoted
verbatim, and (3) confirmation from `runtime.log` (or absence of any
infra-error signature) that the failure is content-driven, not infra.
Missing any of the three caps the finding at severity 1.

---

## Gate 6 — `rubric_requires_unstated_technical_convention`

```yaml
dimension_name: "Verifier Requires an Unstated Technical Convention"
check_kind: llm
inputs: [instruction, verifier_or_judge_toml, golden_solution_excerpt]
applies_when:
  builtin: task_has_verifier
gate:
  role: blocking
  reject_at_severity: 2
```

**Guidance (paste into tool, ≤ 5,000 chars):**

> PASS if every structural/technical convention a criterion requires (a
> checks tab, a specific guard formula, a named worksheet layout, a
> particular file structure) is either stated in the prompt or is a
> direct, necessary consequence of a requirement the prompt does state.
> FAIL only if: (1) a criterion's FAIL condition names a specific
> technical/structural convention (e.g. "no internal check logic," "no
> discount-rate-greater-than-growth guard"); (2) the prompt's actual
> requirement is broader/vaguer and does not name that specific convention
> (e.g. "auditable end to end," "trace figures to source") — that broader
> requirement is satisfiable in ways that don't include this convention;
> and (3) the only place this specific convention appears is in the golden
> solution's own implementation choice, not in the prompt or any source
> document — quote all three. NOT_APPLICABLE if no criterion requires a
> named technical/structural convention beyond what the prompt states.

**What this evaluates** *(reference only — do not paste)*. Whether a
criterion demands a specific professional-practice or spreadsheet/document
convention — a checks tab, a guard formula, a particular layout — that the
prompt never names and that isn't strictly required by anything the prompt
does ask for. Distinct from Gate 4 (which is about singling out one
specific *content* item among many possible ones) and Gate 3 (which needs
closed-world prompt language and a source document to check against) —
here there is typically no source document at all to consult; the only
evidence is the gap between the prompt's stated ask and the golden's
implementation choice.

**How to judge.**
1. For each criterion, identify FAIL language naming one specific
   structural/technical convention rather than a content/analytical
   outcome.
2. Read the prompt's actual requirement in that area. Ask: would a
   reasonable, fully-compliant solution satisfying the prompt's literal
   words necessarily include this specific convention, or could it
   reasonably omit it while still meeting the stated ask?
3. If the convention could reasonably be omitted under the prompt's literal
   words, check the golden solution — is this convention only present
   there, with nothing in the prompt or any source document naming it?
4. If yes to both, this is a hidden professional-standard requirement.

**Severity rubric.**
- **0** — every required convention is either named in the prompt or a
  necessary consequence of what it asks for.
- **1** — a low-weight criterion requires an unstated convention that a
  careful, experienced solver would likely include anyway by default.
- **2** — a moderate-weight criterion requires an unstated convention a
  reasonable compliant solution could omit.
- **3** — an outcome-defining criterion fails an otherwise fully compliant
  solution solely for lacking a convention nowhere requested.

**Do not flag:** conventions that are a necessary mechanical consequence
of a stated requirement (e.g. the prompt asks for a working formula-linked
model, and the criterion requires formulas rather than hardcoded values —
that's not a hidden convention, it's the literal ask).

**Evidence policy.** A FAIL requires three quotes: (1) the criterion's
FAIL language naming the convention, (2) the prompt's broader/vaguer
stated requirement in that area, and (3) the golden's implementation of
the convention with a note that no source document or prompt sentence
names it. Missing any of the three caps the finding at severity 1.

---

## Subtask prompt template

One subtask per (task, gate) pair. Spawn all subtasks for a batch round in
parallel — each is a fresh agent with no memory of prior tasks.

```
You are a QC gate judge for GDPVal/Omega task rubrics. Grade exactly ONE
task against exactly ONE gate and return ONE finding JSON. Do not do
anything else, and do not comment on any dimension other than the one
below.

## Context

You are hunting for a specific, narrow class of rubric defect — not general
rubric quality. Only report a finding if you can produce the exact
verbatim quotes this gate's evidence policy requires. If you cannot quote
them, the answer is severity 0 / applicable false, not a hedge.

## Gate definition

{GATE_DEFINITION}

## Inputs

### Task prompt (instruction.md)
{PROMPT_TEXT}

### Rubric / judge.toml files
{JUDGE_TOML_TEXT}

### Source document filenames available in environment/data/
{SOURCE_FILE_LIST}

### Golden solution excerpt (if provided)
{GOLDEN_EXCERPT}

## Required output

Return exactly one JSON object in this shape and nothing else:

{
  "dimension":       "{GATE_ID}",
  "applicable":       <true|false>,
  "severity":         <0|1|2|3>,
  "confidence":       "<low|medium|high>",
  "evidence_quotes":  ["<verbatim quote 1>", "<verbatim quote 2>", ...],
  "headline":         "<one sentence, ≤ 25 words, specific to this task>",
  "justification":    "<1-3 sentences tying the quotes together>",
  "confirmed_against_golden": <true|false|null>
}

Rules:
- severity ≥ 2 with fewer than the gate's required number of evidence
  quotes → demote to severity 1 and note why in justification.
- Gates 3 and 5 only: leave confirmed_against_golden null if no golden
  excerpt/oracle run was provided; otherwise it must be true or false per
  the mandatory confirmation step.
```
