# Source File and Prompt QC — required stage

Grade the **prompt** (provided by the expert) and the **source/input files**
(`Source Documents/`). These are the artifacts an expert produces first, so this
is the stage to pass *before* building a solution.

**Before grading, confirm the required inputs are present** — the prompt
(pasted) and a non-empty `Source Documents/`. If either is missing, ask the
expert and wait; don't start grading (see
[Required inputs](SKILL.md#required-inputs--confirm-before-grading) in SKILL.md).

Grade every dimension below and produce one finding each, following the
**grading protocol**, **severity scale**, **evidence policy**, **confidence
policy**, **eval-context conventions**, and **verdict computation** in
[SKILL.md](SKILL.md). Two families ship in this stage: **Task Structure** and
**Authenticity**.

**Early-QC note.** Two dimensions (`overall_gdpval_fit`,
`professional_complexity`) can also read the Expert Solution as a strengthening
signal. At early QC the solution often does not exist yet — judge from the
prompt and source files, and fold the solution in *only when it is present*.
Never mark these `not applicable` just because the solution is absent.

---

## Task Structure

### overall_gdpval_fit

```yaml
dimension_name: "Overall GDPVal Fit"
check_kind: llm
inputs: [instruction, solution_files]   # solution optional at early QC
gate:
  role: blocking
  reject_at_severity: 2          # sev 2 = "benchmark-shaped"; not fixable by editing
  on_disagreement: review
```

**What this evaluates.** Holistically, does this task represent realistic,
economically valuable knowledge-work that a professional would be paid to perform?

**How to judge.** This is a single gestalt judgment, not a sum of subcriteria.
Take a top-down impression of the `instruction` and the domain it implies (+ the
Expert Solution when present) together. The question is only: if you encountered this task in a
real professional workflow, would you immediately recognise it as legitimate paid
work in that domain? Other dimensions handle authenticity, complexity, and
formatting in detail; do **not** re-grade those concerns here.

**Severity rubric.**
- **0** — Unmistakably real delegated professional work. The domain is obvious,
  the scope feels appropriate for a billable engagement (and, when present, the
  golden solution demonstrates genuine economic value).
- **1** — Reads as real professional work with a mild constructed feel — slightly
  oversized or undersized scope, slightly idealised stakeholders, or stakes that
  feel a touch hypothetical.
- **2** — Materially test-like. Individual sub-components are plausible, but the
  whole reads as a benchmark or training exercise (round-numbered financials,
  generic "Acme Corp" stakeholders, scope chosen to exercise specific
  capabilities).
- **3** — Clearly constructed and not credible as real delegated work — template
  structure, "illustrative" framings, or textbook-shaped scenarios.

**Common hard-fail patterns.**
- Task framing is paper-thin — a layer of professional role over what is
  fundamentally a benchmark question (the role and stakes are decorative,
  not driving the content).
- Instruction enumerates the deliverable's required sections in language that
  reads as a verifier rubric copied verbatim into the prompt (e.g. each
  section header maps 1-to-1 to a rubric item, often using the rubric's
  internal phrasing). Normal "the memo should cover X, Y, and Z" enumeration
  is **not** a hard-fail.
- Arbitrary, benchmark-shaped constraints with no plausible workplace
  motivation: "exactly 3 bullet points", "exactly 200 words". Natural
  professional length cues like "a one-page memo" or "a ~500-word summary"
  are **fine**.

**Anti-overcall.** Real professional work is often structured, repetitive,
and dryly written. Eval-context conventions (persona prompts, output file
paths, named deliverables, required-format specifications, length cues)
are not synthetic markers — see the eval-context conventions in SKILL.md.
Flag only when the *overall feel* of the sample reads as exercise-shaped after
holistic consideration.

---

### instruction_input_consistency

```yaml
dimension_name: "Instruction / Input Consistency"
check_kind: llm
inputs: [instruction, input_files]
gate:
  role: blocking
  reject_at_severity: 2          # sev 2 = "input missing/mismatched"; can't fix by editing the sample
  on_disagreement: review
```

**What this evaluates.** Does the instruction match the inputs actually provided?
A solving agent should be able to read the instruction and locate every file,
section, or data element the instruction references — and the inputs should
contain the substance the instruction relies on.

**How to judge.** Walk the instruction looking for explicit references (file
names, section names, "the attached X", named data tables) and verify each
exists in `input_files`. Then check the inverse: are there inputs that the
instruction doesn't reference but obviously expects the agent to find? Finally,
spot-check that the inputs contain real substance, not just placeholder data.

**Severity rubric.**
- **0** — Instruction and inputs are fully consistent. Every reference resolves;
  no important input goes unmentioned.
- **1** — Minor mismatch (filename has a small typo; instruction says "the
  spreadsheet" and the file has a slightly different name). The agent can
  reasonably infer what was meant.
- **2** — A relied-upon input is missing or mismatched in a way that forces the
  agent to guess what data to use. An attached file is referenced but not
  provided; or the data table the instruction needs is absent.
- **3** — The instruction references inputs that don't exist at all, or
  contradicts the inputs that do (numbers disagree, dates contradict, roles
  conflict).

**Common hard-fail patterns.**
- Instruction explicitly names a file by filename that is not present in
  `input_files`.
- A specific number, date, or named entity in the instruction directly
  contradicts the same item in the inputs (e.g. instruction says "the Q3
  report", inputs are dated Q2).
- Instruction references sections, tables, or appendices ("see Appendix B")
  that don't exist in the named input file.
- Instruction and inputs use incompatible scope (instruction asks about
  "all three regions", inputs cover only two).

---

### self_containedness

```yaml
dimension_name: "Self-Containedness"
check_kind: llm
inputs: [instruction, input_files]
gate:
  role: blocking
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Can the task be solved from the given instruction and
inputs alone, or does it implicitly require things the agent doesn't have —
external context, credentials, network access, or undocumented domain knowledge?

**How to judge.** Read the instruction as if you were the agent. Ask: do I have
everything I need to begin? If the task needs external lookup (current stock
price, today's date, a specific company filing), is that information embedded
in the inputs, or does the agent have to fetch it? Tools the agent already has
(Python, document libraries, basic web search if granted) do not count as
external dependencies; the question is about *information* and *context*, not
runtime capabilities.

**Severity rubric.**
- **0** — Fully self-contained. Instruction + inputs supply everything the agent
  needs.
- **1** — Requires general professional knowledge any competent agent would have
  (basic accounting conventions, common formatting expectations). Not a defect.
- **2** — Requires undocumented domain context — specific company policies,
  internal jargon defined nowhere, conventions the agent couldn't reasonably
  guess.
- **3** — Cannot be solved without information that isn't provided at all
  (external credentials, a specific filing not attached, results of a
  proprietary system).

**Common hard-fail patterns.**
- Instruction requires real-time external data not embedded in inputs (today's
  date, current stock price, live system state, recent news).
- Instruction references proprietary company policies, internal documents, or
  named systems with no documentation supplied.
- Instruction implies credentials or login to external resources are needed.
- "As discussed in our last meeting…" / "Per our previous email…" framings
  with no record of the prior interaction provided.
- Task requires consulting a specific named external party ("ask Legal", "check
  with Finance") with no fallback context.

**Anti-overcall.** Many tasks legitimately require *general* professional
knowledge (e.g. "write a memo to the CFO" doesn't need to define what a CFO is).
Only flag missing context that is *specific* and *not inferrable*.

---

### role_and_deliverable_clarity

```yaml
dimension_name: "Role and Deliverable Clarity"
check_kind: llm
inputs: [instruction]
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Two separate clarities, both needed: **role** (who is
the agent supposed to be — analyst, attorney, examiner) and **deliverable**
(what concrete artifact must be produced, in what format).

**How to judge.** Role can be stated explicitly ("as a senior credit analyst")
or inferable from the framing of the request. Deliverable should specify the
artifact type ("a memo", "a model", "a one-page summary") and ideally the file
format. Either being ambiguous is a problem; both being ambiguous compounds it.

**Severity rubric.**
- **0** — Both role and deliverable are crisp and unambiguous; a competent agent
  knows immediately what shape the answer should take.
- **1** — Minor ambiguity in one of the two — usually the deliverable's file
  format is unstated but reasonably inferable.
- **2** — Material ambiguity in either dimension. Reasonable agents would
  produce noticeably different shapes of deliverable.
- **3** — Either role or deliverable is essentially undefined, or the two are
  contradictory.

**Common hard-fail patterns.**
- Instruction assigns conflicting roles ("you are a junior analyst, produce a
  board-level strategic recommendation").
- Deliverable type is never stated and cannot be inferred from context (no
  hint of memo vs. report vs. spreadsheet vs. presentation).
- Multiple deliverables requested but the count is ambiguous ("produce
  documentation" could mean one file or many; "supporting materials" plural
  but unclear how many).
- "Write something useful" / "produce a deliverable" / other vague asks with
  no shape.

---

### professional_complexity

```yaml
dimension_name: "Professional Complexity"
check_kind: llm
inputs: [instruction, input_files, solution_files]   # solution optional at early QC
gate:
  role: blocking
  reject_at_severity: 2          # sev 2 = "predominantly mechanical"; can't add judgment by editing
  on_disagreement: review
```

**What this evaluates.** Does the task require genuine professional judgment —
synthesis across documents, weighing tradeoffs, applying domain expertise — or
could a non-expert produce the same answer by mechanically following a template?

**How to judge.** Look for tasks where the solution requires actual *decisions*:
deciding what to include and exclude, weighing competing considerations, inferring
intent from ambiguous inputs, or producing analysis that goes beyond
transcription. When the golden solution is present it is the strongest signal —
does it demonstrate analytical effort, or is it largely formatting + paraphrase +
arithmetic? When the solution is absent (early QC), judge from the instruction +
inputs: does the task *as posed* demand real judgment to complete?

**Severity rubric.**
- **0** — Requires meaningful professional judgment. Synthesis, tradeoff
  weighing, or genuine domain expertise visibly drive the solution.
- **1** — Mostly substantive but with some rote / template-able parts (e.g. a
  standard cover memo wrapping the real analysis).
- **2** — Predominantly mechanical with thin layers of judgment — most of the
  work is filling slots in a template, copying numbers, or applying a fixed
  rubric.
- **3** — A first-week intern with a template could produce a comparable
  result.

**Common hard-fail patterns.**
- Pure transcription — task amounts to rewriting one document's content in a
  different format with no analytical work added.
- Pure arithmetic with no judgment ("sum these numbers", "calculate this
  ratio", "convert these units") — the answer is a calculation, not a decision.
- Task reduces to mechanically applying a clearly stated formula or procedure
  the instruction itself spells out.
- The solution could be generated by a 100-line script with no model
  reasoning — i.e. the work is fully procedural.

**Anti-overcall.** Volume of work does not equal complexity, but neither does
brevity equal triviality. Short solutions can require deep judgment (a one-page
recommendation memo, a single chart with a key insight). Judge the *type* of
work the task requires, not its length. A pre-specified deliverable structure
(named files, required sections, length cues) is eval-context convention and
does **not** indicate the task is mechanical — what matters is whether the
*content* requires real judgment.

---

### feasibility_and_clarity

```yaml
dimension_name: "Feasibility and Clarity"
check_kind: llm
inputs: [instruction, input_files]
gate:
  role: advisory
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Two related questions: **feasibility** (is the task
doable within the stated scope and given inputs?) and **interpretive clarity**
(would two competent professionals interpret the request the same way?).

**How to judge.** This dim is distinct from `instruction_input_consistency`
(which is about whether referenced inputs exist) and from
`role_and_deliverable_clarity` (which is about who and what). Here, ask: given
the inputs, is the task reasonably scoped to be completed in the implied time?
And: if you asked two senior practitioners to do this, would their deliverables
have the same shape?

**Severity rubric.**
- **0** — Clearly feasible; instruction would be interpreted identically by any
  competent professional.
- **1** — Feasible with mild ambiguity that wouldn't change the deliverable's
  shape (e.g. exact memo length unstated but obvious from context).
- **2** — Feasibility is doubtful (too much work for the implied scope, or too
  little information) *or* the instruction is ambiguous enough to produce
  noticeably different answers.
- **3** — Infeasible within the stated scope, or fundamentally unclear.

**Common hard-fail patterns.**
- Instruction asks for analysis the inputs don't actually contain the data to
  support (e.g. "compare revenue trends across 5 years" with one year of data).
- Requested deliverable scope is implausible for the implied timeframe
  ("comprehensive 50-page report in two hours").
- Two stated requirements directly contradict each other (the deliverable
  cannot satisfy both simultaneously).
- The instruction has two plausible interpretations that would lead to
  materially different deliverables.

**Anti-overcall.** Eval-context conventions (named deliverables, file
paths, length cues, persona prompts) are not interpretive ambiguity. When
the instruction specifies an output format or location, that *removes*
ambiguity rather than creating it.

---

## Authenticity

### instruction_authenticity

```yaml
dimension_name: "Instruction Authenticity"
check_kind: llm
inputs: [instruction]
gate:
  role: blocking
  reject_at_severity: 2          # sev 2 = "LLM-shaped instruction"; not fixable
  on_disagreement: review
```

**What this evaluates.** Is the instruction text plausibly written by a real
human professional in the relevant domain, or does it read as LLM-generated
or template-filled?

**How to judge.** Look for human signals (domain-specific shorthand, casual
asides, sender-recipient context, references to past communications, dated
items, specific people/places that ground the request) and LLM signals
(hedging language; generic phrasings without grounding; over-clean
numerical examples; overly explicit politeness; scaffolded structure with
no real-world specifics).

A crucial framing for this corpus: the dataset is an *evaluation*, so several
patterns that would be unusual in an in-the-wild email are perfectly
acceptable here. Specifically, none of the following are signals of synthetic
origin and must not be penalised:

- A persona / role assignment ("You are a senior credit analyst", "Acting as
  the portfolio manager, …")
- Output file or path specifications ("save your memo as
  `/workspace/output/memo.docx`", "produce two files named …")
- A required deliverable list, even when enumerated
- Natural length cues ("a one-page memo", "a ~500-word summary")
- Standard business words ("comprehensive", "actionable") used in normal
  proportion
- Anonymised-real organisations or people

**Severity rubric.**
- **0** — Reads unmistakably as written by a human domain practitioner. Specific
  details, natural register, contextual asides.
- **1** — Mostly human but with small stylistic tells suggesting light AI
  assistance.
- **2** — Materially LLM-shaped: hedging without specifics, template-like
  organisation, polished "ask" disconnected from any real-world context.
- **3** — Clearly LLM-generated; reads like prompt output (e.g. "as an AI…",
  systematic paragraphing with each paragraph hitting a different "topic").

**Common hard-fail patterns.**
- Generic placeholder organisations used throughout with no real-world
  anchoring ("ABC Corporation", "Widget Inc", "Generic Industries", "Company
  X"). Anonymised real names are fine; transparently invented stand-ins are
  not.
- Stakeholders named but given no titles, no relational context, no
  organisational structure — just first-name characters appearing without
  backstory or job function.
- Markdown formatting in the instruction body (visible `**bold**`, `-`
  bullets rendered as bullets, `#` headings) when the instruction is
  presented as prose — real professional emails and briefs rarely use raw
  Markdown.
- "As an AI assistant…" / "I am a language model…" / similar meta-framings.

**Anti-overcall.** Humans *can* write clean, structured instructions —
structure alone is not a tell. Persona prompts, output-file specs, named
deliverables, and required-format lists are eval-context conventions, **not**
synthetic markers (see SKILL.md). The "As a {role}, I want to …"
user-story format from agile/software contexts is borderline: prefer
flagging only when the rest of the instruction is also clearly LLM-shaped.
Clusters of business words ("comprehensive", "thorough", "actionable") are
common in normal writing and are weak signals on their own; treat them as
contributing evidence at most, not a hard-fail by themselves. Quote
concrete passages when flagging severity ≥ 1.

---

### input_file_authenticity

```yaml
dimension_name: "Input File Authenticity"
check_kind: llm
inputs: [input_files]
gate:
  role: blocking
  reject_at_severity: 2          # sev 2 = "synthetic feel"; not fixable
  on_disagreement: review
```

**What this evaluates.** Do the input files look like real artifacts produced
by humans in a real professional workflow, or do they look synthesised to
look-the-part?

**How to judge.** Real documents carry real signals: specific organisation
names, sector-appropriate jargon, dated content, footers/headers/version
artifacts, page-break weirdness, internal numbering schemes, references to
people by name. Synthetic documents typically have too-clean formatting,
generic placeholders, perfect regularity, LLM-flavored phrasing, and rounded
numbers throughout.

**Severity rubric.**
- **0** — Authentic documents with all the natural messiness of real artifacts.
- **1** — Mostly authentic with a few generic placeholders that don't undermine
  overall credibility.
- **2** — Material synthetic feel: names, dates, or organisations read as
  manufactured; the documents look generated rather than gathered.
- **3** — Clearly fabricated documents — generic names throughout, suspiciously
  regular structure, obvious LLM hallmarks (rounded numbers, identical sentence
  cadence, no version artifacts).

**Common hard-fail patterns.**
- Input files contain pre-baked analysis or conclusions that the agent is
  supposed to produce — i.e. the inputs leak the answer.
- Round-numbered financial figures throughout ($100K, $1M, $50K) with no
  irregular numbers — real financial data is rarely this clean.
- Perfectly clean formatting across multiple "different" source documents:
  identical fonts, no version artifacts, no revision marks, no formatting
  variation between supposedly-distinct-origin documents.
- Suspiciously consistent narrative voice across documents that should have
  come from different authors or organisations.
- Generic stakeholder names ("John Smith", "Acme Inc") used uniformly across
  the entire input set.
- LLM-style diagrams or tables with uniform styling, generic icons, or
  visibly templated structure.

**Anti-overcall.** Redacted or anonymised real documents may look generic but
are still real. If the document carries domain-specific structure (a real audit
template, a real industry filing format) under generic names, the document is
authentic. Round-numbered figures *occasionally* (a single round-numbered
forecast, a top-line metric quoted as a round number) appear in real
business documents and are not on their own a synthetic marker. Quote a
concrete passage when flagging.

---

When every dimension above has a finding, return to [SKILL.md](SKILL.md):
compute the verdict, synthesize top issues + suggested fixes, present the review,
then offer Solution QC (if `Expert Solution/` exists) and Verifier QC (if the
expert has a verifier/Rubric to paste).
