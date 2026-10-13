# Authenticity and substance checklist

Answer every question against your actual draft, with a quote or specific
detail — not a general impression. A vague "yes, I think so" means the
answer is actually no.

## Framing the task

- [ ] **`overall_gdpval_fit`** (skip for L1) — Would a professional actually
      get paid to do this exact piece of work? Or does it read as an
      exercise built to be gradable — round numbers, generic stakeholders,
      a test-shaped ask?
- [ ] **`professional_complexity`** (skip for L1) — Does finishing this
      require real judgment (weighing tradeoffs, synthesizing across
      documents), or could someone with no domain background produce the
      same answer by following a template? Look at your own golden: is
      most of the work formatting and arithmetic, or analysis?
- [ ] **`role_and_deliverable_clarity`** — If you handed only the
      instruction to a stranger, would they know who they're supposed to be
      and exactly what artifact to hand back?
- [ ] **`feasibility_and_clarity`** — Is the task doable in the scope
      implied, and would two competent professionals interpret the ask the
      same way? (Before flagging your own draft as infeasible: check whether
      the phasing/seasonality data you think is missing is actually sitting
      in a report you haven't opened, and whether an underspecified
      assumption is one the instruction explicitly invites the solver to
      choose and disclose — both are fine, not gaps.)

## Writing the instruction

- [ ] **`instruction_input_consistency`** (semantic half) — Every file you
      named resolved in `source-file-reference-check` — now check the
      *content*: does what's actually in each file match what the
      instruction assumes is there?
- [ ] **`self_containedness`** (semantic half) — Could this be solved from
      the instruction and the bundled files alone, with no external
      credentials, no specific filing you forgot to attach, no tribal
      knowledge only you have?
- [ ] **`instruction_authenticity`** — Read the actual brief (the
      From/To/Subject request), not the harness-appended "## Environment
      notes" block underneath it — that block is boilerplate, not your
      prose. Does the brief above it sound like a real person wrote it, with
      the specific asides, shorthand, and context a real sender would
      include? Or is it hedged, over-clean, and scaffolded the way an LLM
      writes?

## Assembling `environment/data/`

- [ ] **`input_file_authenticity`** — Read each source document as if you
      were seeing it for the first time. Does anything contradict itself
      internally? Are there suspiciously round numbers, or values that
      couldn't plausibly come from the source they claim to be? (Genuinely
      synthetic-but-authentic markers — placeholder names, anonymized IDs,
      a document's own `TBD` field because it's an explicitly unapproved
      draft — are fine; don't flag those.)

## Building the golden solution

- [ ] **`solution_substantiveness`** — Read the golden with fresh eyes: is
      this real analysis with specific numbers, named entities, and a
      defensible conclusion — or section headings followed by one-liners
      and placeholder values?
- [ ] **`solution_instruction_alignment`** — Go through the instruction's
      explicit requirements one by one. Does the golden actually address
      each one, in the right proportion — not just touch on it in passing?
- [ ] **`solution_internal_consistency`** — If there's more than one
      deliverable (memo + databook + deck), do the numbers in the narrative
      match the numbers in the tables? Do all deliverables tell the same
      story?
- [ ] **`solution_layout_professionalism`** — Would you hand this to a real
      client without embarrassment? Headings, formatting, no leftover
      drafting artifacts?
- [ ] **`solution_chart_quality`** / **`solution_visual_insight_surfacing`**
      (skip if no charts) — Are axes labeled, is there a title and legend —
      and does the chart actually highlight the finding the task is asking
      about, or is it decorative?

## Writing the rubric

- [ ] **`verifier_rubric_clarity`** — For each criterion: if two different
      reviewers graded the same solution against this exact wording, would
      they reach the same verdict? A soft qualifier ("substantially all") is
      fine only if the criterion also pins a concrete anchor (an enumerated
      list, a number, a named item) — otherwise it's a coin flip.
- [ ] **`verifier_rubric_specificity`** — Does each criterion point at
      something observable in the solution, or does it ask an interpretive
      question ("the analysis is high quality") that makes the grader invent
      their own bar?
