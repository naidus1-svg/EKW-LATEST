# Solution QC — offered stage

Evaluate the contents of `Expert Solution/` as the **canonical answer**
to the task. Do **not** compare it to any model output (e.g. `Claude Output/`)
and do **not** treat it as "an improved version" of anything — it is the golden
answer assessed on its own terms.

**When to run this stage.** Either (a) *offered* after Source File and Prompt QC
in the full flow — only when `Expert Solution/` exists and is non-empty, and not
unprompted; or (b) **standalone**, when the expert asks to QC only the solution
(source/prompt already done — see *Two ways to run* in [SKILL.md](SKILL.md)). In
standalone mode the expert still pastes the **prompt** as context (used by the
format-match, alignment, and visual-insight dims, but **not** re-graded);
`Source Documents/` is **not** needed.

**Before grading, confirm the required inputs are present** — the prompt
(pasted) and a non-empty `Expert Solution/`. If either is missing, ask the expert
and wait; don't start grading (see
[Required inputs](SKILL.md#required-inputs--confirm-before-grading) in SKILL.md).

Pull the solution text with `pipeline/.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir>
--solution`, and open `.pdf` / `.docx` / image deliverables with the Read tool
directly when a dimension needs the *rendered* artifact (layout, charts).

Grade every dimension following the protocol/scales/policies in
[SKILL.md](SKILL.md), then fold these findings into the same verdict computation.

**Applicability.**
- All dimensions here require `solution_present` (true for this stage).
- `solution_chart_quality` and `solution_visual_insight_surfacing` require
  `solution_has_charts`: only applicable when a solution file contains
  chart-like content (a chart object in `.xlsx`, an embedded image/chart in
  `.docx`, a chart/image in `.pdf`, or an image file). If no solution file has
  charts, mark both `applicable=false` (`severity=0`).

**File-format note.** Judge the deliverable by its **actual on-disk extension**.
When the extractor renders an Office file as text, the deliverable's real format
is still its extension (e.g. `memo.docx`) — do **not** flag the text rendering as
a format mismatch.

---

### solution_format_match

```yaml
dimension_name: "Solution Format Match"
check_kind: llm
inputs: [instruction, solution_files]
applies_when:
  builtin: solution_present
gate:
  role: blocking
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Does the solution file (or set of files) match the
deliverable format the instruction asks for? File types, expected file names
if specified, expected number of deliverables.

**How to judge.** Extract from the instruction what the deliverable format
should be — "memo" → .docx, "model" → .xlsx, "summary" → either, "report" →
.docx or .pdf — and verify the solution files match. If the instruction
specifies file names, check those too. If multiple deliverables are
requested, confirm all are present.

**Judge by the ORIGINAL file extension on disk.** Office files may be surfaced
to you as extracted text rather than the binary; the deliverable's ACTUAL
format is still its on-disk extension (e.g. `.docx`). Do NOT flag the text
rendering as a format mismatch.

**Severity rubric.**
- **0** — Exact format match; all expected deliverables present in the
  expected formats.
- **1** — Minor format mismatch (extra supporting file, slight naming
  variation, deliverable in a related format).
- **2** — Material format mismatch — one deliverable is in the wrong type, or
  a required deliverable is missing while others are present.
- **3** — Fundamentally wrong format (instruction asks for a spreadsheet, all
  files are memos; or no recognisable deliverable exists).

**Common hard-fail patterns.**
- File extension doesn't match the requested deliverable type (e.g. `.txt`
  when a `.docx` memo was requested, `.md` when a polished document was
  requested).
- Wrong number of files (a single `.docx` when memo + supporting spreadsheet
  were both requested).
- A solution file is empty or near-empty when the request implied a
  substantive deliverable.
- File name explicitly contradicts a name the instruction specified
  (instruction asks for `q3_analysis.xlsx`, solution provides
  `Analysis.xlsx`).

---

### solution_substantiveness

```yaml
dimension_name: "Solution Substantiveness"
check_kind: llm
inputs: [solution_files, solution_reasoning]
applies_when:
  builtin: solution_present
gate:
  role: blocking
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Is the solution substantive professional work — real
analysis, real structure, real conclusions — or is it a skeleton, stub, or
placeholder-heavy draft?

**How to judge.** Read the actual content of each solution file. Substantive
work has specific numerical results, named entities, defensible conclusions,
and developed arguments. Skeleton work has section headings followed by
one-liners, placeholder values, "TBD" markers, or generic filler. The expert's
reasoning file in `Expert Solution/` (if present) can help calibrate intent but
the substantive content must be in the deliverable files themselves.

**Severity rubric.**
- **0** — Fully substantive across all deliverable files; demonstrates real
  analytical effort.
- **1** — Mostly substantive with one or two thinly-developed sections.
- **2** — Materially incomplete; large sections are placeholders, one-liners,
  or summaries of what should go there.
- **3** — Skeleton-only or pervasive use of "[INSERT X]" / "TBD" / template
  filler patterns; the deliverable is not usable as-is.

**Common hard-fail patterns.**
- LLM closing phrases pasted into formal deliverable documents where they
  don't belong: "I hope this helps" / "Let me know if you need anything
  else" / "Feel free to reach out" / "Based on the analysis above…" appearing
  at the end of a *report* or *memo body*. (These same phrases at the close
  of an actual professional email are fine — judge by document type.)
- LLM-characteristic hedging in formal documents: "It's important to note
  that…", "It's worth highlighting that…", "It should be noted…" used
  pervasively as filler. Occasional use in real documents is fine.
- Citations to fabricated sources — named references like "(Smith 2023)" or
  footnotes to documents that don't appear in the inputs and look invented.
- Section headers followed by content less than two lines long, or section
  headers followed by content that only restates the heading.
- "[INSERT X]" / "[TBD]" / "[Placeholder]" / "<your data here>" patterns
  anywhere in the deliverable.
- Conclusions or recommendations that don't follow from the body — the
  recommendation contradicts the analysis, or appears with no supporting
  argument.
- Generic bullet lists with no task-specific content ("• Plan", "• Execute",
  "• Review") used as substantive content.

---

### solution_instruction_alignment

```yaml
dimension_name: "Solution / Instruction Alignment"
check_kind: llm
inputs: [instruction, solution_files]
applies_when:
  builtin: solution_present
gate:
  role: blocking
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Does the solution actually answer the task as posed?
Does it address each requirement, in roughly the right proportion?

**How to judge.** Extract the instruction's requirements (often a numbered or
bulleted list of things the deliverable must include). For each requirement,
locate where in the solution it is addressed and assess depth. A misalignment
can take two forms: missing a requirement entirely, or addressing it
superficially when the instruction asked for analysis.

**Severity rubric.**
- **0** — Addresses every stated requirement in proportion to its emphasis in
  the instruction.
- **1** — Addresses every requirement but with mild proportionality issues —
  one minor requirement underdeveloped, or one overemphasised at the expense
  of others.
- **2** — Misses or only superficially addresses one important requirement.
- **3** — Materially misses the point — multiple requirements unaddressed, or
  the deliverable answers a noticeably different question.

**Common hard-fail patterns.**
- Solution answers a noticeably different question than asked — the named
  subject, system, or person in the instruction is absent or peripheral in
  the deliverable.
- A required output element (named explicitly in the instruction) is missing
  entirely.
- The deliverable includes large unrequested sections (e.g. a "Methodology"
  or "Background" section the instruction never asked for) that crowd out
  the actual ask.
- The deliverable answers only part of a multi-part question (handles
  question 1 thoroughly, ignores or single-lines questions 2 and 3).

**Anti-overcall.** When the instruction prescribes a specific output
structure (named sections, ordered deliverables, format requirements),
the deliverable following that structure is *good alignment*, not
suspicious conformity. Only flag when the deliverable departs from what
was asked, not when it matches closely.

---

### solution_internal_consistency

```yaml
dimension_name: "Solution Internal Consistency"
check_kind: llm
inputs: [solution_files]
applies_when:
  builtin: solution_present
gate:
  role: blocking
  reject_at_severity: 3
  on_disagreement: review
```

**What this evaluates.** Is the deliverable internally consistent — do the
numbers reconcile, do the conclusions follow from the analysis, do the
deliverable files agree with each other where they overlap?

**How to judge.** When the solution contains multiple files (e.g. a memo plus
a spreadsheet, or a report plus a presentation), look for cross-references
and verify they agree. Within a single file, check that key numbers cited
in the narrative match the numbers in tables/charts, that percentages sum
where they should, and that the conclusion is supported by the body. This dim
is distinct from `solution_substantiveness` (which asks "is there enough
there") and `solution_instruction_alignment` (which asks "does it answer the
question"); here we ask "does it agree with itself".

**Severity rubric.**
- **0** — Fully internally consistent. Numbers reconcile, conclusions follow,
  files agree with each other.
- **1** — One minor inconsistency (a number rounded differently in two places;
  a small percentage-sum issue that doesn't change the conclusion).
- **2** — A material inconsistency — a key number disagrees between memo and
  model, or a stated conclusion is contradicted by the body, or two
  deliverable files give different answers to the same question.
- **3** — Pervasive or severe inconsistencies that fundamentally undermine the
  deliverable's credibility.

**Common hard-fail patterns.**
- Numbers cited in the narrative don't match numbers in tables or attached
  spreadsheets (e.g. memo says "revenue grew 12%", model shows 8%).
- Percentages that should sum to 100% don't sum to 100% (allocation tables,
  category breakdowns).
- The executive summary's bottom line contradicts the body analysis (summary
  says "recommend approval", body argues for further study).
- Cross-file inconsistency — memo references a value the spreadsheet doesn't
  contain, or two files give different totals for the same item.
- Date inconsistencies — different dates given for the same event in
  different parts of the deliverable.
- Internal arithmetic that doesn't check (line items in a table don't sum to
  the stated total; subtotals are wrong).

---

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
alignment). Open the rendered file (PDF/image) with the Read tool when text
extraction can't reveal layout problems.

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

**Skip condition.** Mark `applicable=false` for any solution that contains no
chart-like content (no chart objects in `.xlsx`, no embedded images/charts in
`.docx`, no chart/image content in `.pdf`, no image files). When in doubt that
charts exist, run the dimension. To judge charts you must view the **rendered**
file — open the PDF/image with the Read tool, not just the text extract.

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

**Skip condition.** Same as `solution_chart_quality` — mark `applicable=false`
if no charts.

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

When every applicable dimension above has a finding, fold them into the verdict
in [SKILL.md](SKILL.md) and update the review.
