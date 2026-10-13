---
name: harbor-content-audit
description: >-
  Checks whether a Harbor-shaped task's prompt, golden/reference answer, and
  grading rubric are internally consistent with EACH OTHER as text -- not the
  built package (that is harbor-structural-audit's job). Six defect
  patterns: a rubric criterion asking for a fact or figure the prompt or
  golden answer never establishes; a rubric expecting a specific value that
  doesn't match what the golden answer actually computes or states; the
  golden answer citing a source, sheet, or section absent from its own stated
  inputs; two rubric criteria that contradict each other; a rubric criterion
  that leaks the expected answer directly into its own description text where
  a solver-facing artifact could expose it; and a rubric criterion that
  requires content the task's own prompt explicitly forbids inventing, or two
  criteria in the same rubric that directly contradict each other on
  sourced-vs-invented content. This is the FIRST of
  three distinct QC layers -- catches nothing about the actual shipped files
  (harbor-structural-audit's job) or whether the golden passes its own
  rubric on a live grading run (an Oracle-style check's job). Newly designed
  for this generalized repo, not extracted from a proven source skill --
  calibrated once, on a real 50-task EKW sample (44/50 clean, genuine
  defects confirmed in the rest), not yet at full-population scale; treat
  findings as a strong first read, not a verdict. Use whenever a task's
  prompt/golden/rubric text exists and needs a first read-through, before it
  reaches a built package or a grading run.
---

# Content audit for Harbor-shaped tasks

## Provenance and status

Newly designed for this generalized repo -- not extracted from a proven source skill the way
harbor-structural-audit was. Structural audit's six patterns are lifted verbatim from a real
manual reviewer's own findings on two real task pools, an independently produced, proven
finding-set. No equivalent proven finding-set backs this skill: the six patterns below were
specified from the general shape of what a content audit needs to catch, informed loosely by
the kinds of findings a source project's own content-audit step has reported at scale (a
rounding/precision mismatch between a summary table and the same document's prose; a rubric
citing a sheet or tab absent from the actual workbook; generic templated filler with no
task-specific figure to check) -- but that reporting was self-classified by the auditing agent,
not independently checked by a second, different method the way the structural-audit patterns
were checked against a real reviewer's own PDFs.

**Status: measured, not fully validated.** A real run of this skill against a 50-task sample of
actual EKW tasks (`C:\ekwqc\_merged274\files\`, confirmed transferable with only a trivial path
substitution -- `environment/data/` for `initial_workspace/`, `solution/golden_outputs/` for
`solution/`) came back 44/50 clean on manual audit, with genuine content defects found and
confirmed in the other 6: a severe golden-swap in one task, date mismatches in another, an
internal rubric self-contradiction in a couple more, and an NPV self-contradiction in the
alt-schema task. That is real, measured signal -- the process catches actual defects, not just
clean rubber-stamps. It is not full validation: 50 tasks is a sample of the 274-task population,
not a labeled ground-truth set, and no false-positive/false-negative rate has been recorded for
the 44 tasks the run called clean. Until that fuller validation exists, treat every finding this
skill produces as a candidate for a human or a second independent pass to confirm, not as a
verdict. Pattern 6 (prompt-rubric direct contradiction) carries its own separate, earlier track
record on top of this: unlike patterns 1-5, it was independently re-derived from scratch against
two real, previously-unseen tasks (SVC-PC-35-2-0, SVC-PC-35-4-0) as a verification step when it
was added, and it found what it was supposed to find both times. That is a track record of two,
not a calibrated rate -- weight it accordingly, but it is not zero.

Applying this skill still requires an LLM (a Claude session) or a person to actually read the
three texts and apply the six checks -- "mechanical" here would mean "follow this exact recipe
and report findings verbatim," but even that framing is unproven for this skill specifically,
since it hasn't been run at the scale or against the kind of ground truth that would show
whether the recipe itself is complete.

## Why this exists, and what it is not

An Oracle-style run (submitting a task's own reference answer to its own grader) sounds like it
should cover this ground, but it only proves the rubric agrees with the golden on a live grading
pass -- it says nothing about a rubric asking for a value that neither the prompt nor the golden
ever actually establishes in the first place. A well-formed rubric can ask for a fact that
simply is not in either document, score fine on two Oracle runs anyway (partial credit from
other criteria can mask a single ungroundable one), and still be broken. A content audit catches
this class of defect for zero grading cost, by reading, before anything is run.

A structural audit (harbor-structural-audit) checks a different thing entirely: whether the
actual shipped files back up what the prompt and rubric jointly assume -- placeholder
environments, missing files, filename mismatches between the prompt and the verifier. It has
nothing to say about whether the golden and the rubric agree with each other as text. A package
can be perfectly built, every named file present and correctly wired to the grader, and still
carry a rubric that expects a number the golden never computes, or a golden that cites a sheet
that doesn't exist among its own inputs.

So there are three layers, and this skill is the first:

| Layer | Checks | Catches | Misses |
|---|---|---|---|
| This skill (content audit) | prompt/golden/rubric text, read together, no built package needed | Rubric asks for a fact/figure neither document establishes; rubric's expected value contradicts what the golden actually computes or states; golden cites a source/sheet/section absent from its own stated inputs; two rubric criteria contradict each other; a rubric criterion's description leaks the expected answer into text a solver-facing artifact could expose; a rubric criterion requires content the prompt explicitly forbids inventing, or two rubric criteria in the same file contradict each other on sourced-vs-invented | Anything about the actual shipped files; whether a live grading run agrees with the rubric; run-to-run grading flakiness |
| Oracle | rubric vs. golden, run twice, live grading | The golden fails its own rubric on an actual run (a real answer-key/rubric mismatch), including flakiness across two runs | Anything about the environment or the prompt-vs-verifier filename contract; a rubric asking for something neither document establishes at all, if the golden happens to score acceptably on both runs anyway |
| Structural audit | the built package: environment/, instruction.md, tests/ | Placeholder environment vs. named-file prompt, deliverable filename mismatch, unhydrated external-storage dependency, leaked answer-key naming, unstated deliverable count/format | Whether the rubric's content is actually correct (this skill's job) or whether the golden passes it on a live run (Oracle's job) |

None of the three alone is 100% confidence. Running all three and still finding nothing is the
honest ceiling, not a guarantee -- and for this skill specifically, that ceiling itself hasn't
been measured yet (see Provenance and status above).

## The six defect patterns

1. **Rubric asks for a fact or figure neither document establishes.** A criterion requires a
   specific fact, figure, named entity, or condition that appears in neither the prompt's own
   text nor the golden answer's own text. A solver has no way to produce it from what the task
   actually gives them. If the golden itself doesn't state it either, a live grading run may not
   expose this: the golden can still pick up partial credit from other criteria and never reveal
   that this one specific fact was never groundable in the first place. (Illustrative, not drawn
   from a proven audit: a rubric criterion requires "the report state Q3 attrition improved
   year-over-year," but neither the prompt nor the golden mentions a year-over-year comparison
   anywhere -- only a single quarter's figure.)

2. **Rubric's expected value doesn't match what the golden actually computes or states.** The
   rubric names a specific number, date, or figure as correct, and the golden answer's own text
   computes or states a different one for the same fact. Often a rounding/precision mismatch (a
   summary table rounds a figure that the golden's own prose states precisely a few paragraphs
   later, and the rubric locked onto one of the two); sometimes a genuinely stale rubric left
   over from an earlier draft of the golden. (Illustrative: rubric expects "$4.2M," the golden's
   own Findings section states "$4.18M" for the identical line item.)

3. **Golden answer cites a source, sheet, or section absent from its own stated inputs.** The
   golden's own text -- a formula reference, a citation, a "per the X tab" phrase -- points at a
   sheet name, section heading, or document that is not among the golden's own declared list of
   input files or tabs. This is a text-internal contradiction, catchable by reading the golden
   against its own stated sources alone, with no built package needed. It is distinct from
   harbor-structural-audit's filename-mismatch pattern, which compares the actual shipped files
   against the verifier config; this pattern is the golden's own prose disagreeing with the
   golden's own stated inputs. (Illustrative: the golden's formula references a "SRC_Pipeline"
   tab, but the golden's own stated source list names only a "Data" tab and a "Summary" tab.)

4. **Internally inconsistent rubric.** Two criteria in the same rubric contradict each other:
   one requires a figure to exceed a threshold while another requires the same figure to fall
   below it; one demands a rounded value while another demands the unrounded one for the
   identical fact; or two criteria award credit for mutually exclusive characterizations of the
   same event. A solver cannot satisfy both at once, and depending on which criterion a grader
   happens to weight or read first, the identical submitted answer can score differently on
   different runs -- a flakiness source distinct from Oracle's documented run-to-run flip risk,
   because here the rubric itself is the unstable part, not the grading run.

5. **Rubric criterion leaks the expected answer into its own description text.** A criterion's
   description states the expected value, fact, or conclusion outright -- not "does the response
   correctly identify the primary churn driver" but "the response should identify pricing
   changes as the primary churn driver, consistent with the 14% Q3 increase" -- and that
   description text is, or risks being, visible somewhere a solver-facing artifact could expose
   it: embedded in a criteria file shipped into the environment, echoed into an instruction
   addendum, or otherwise reachable before or during solving. This is the exact leakage class
   this folder's own hard rule names directly: **never put the answer key in front of the graded
   party.** Any rubric criterion whose description would still work as a hint if a solver read
   it verbatim is this pattern, whether or not today's specific packaging happens to keep that
   text hidden -- the defect is in the rubric text itself, because packaging changes, and text
   like this is one accidental include away from reaching the solver.

6. **Prompt-rubric direct contradiction.** Either of two shapes, both graded on the same content:
   the prompt's own instruction.md explicitly forbids inventing certain content -- look for
   language like "don't invent," "consume existing... don't create new," "sourced only," or "use
   only the approved/named sources" -- and a judge.toml criterion requires exactly the kind of
   content that instruction forbids, content that is absent from every source the prompt names;
   or two criteria inside the SAME judge.toml file directly contradict each other, one demanding
   "sourced, not invented" and another requiring content absent from every named source. This is
   more severe than pattern 1 (a fact neither document establishes) because it is not a gap the
   golden happened to leave -- the golden correctly followed the prompt's own explicit
   instruction not to invent, and that correct choice is what the rubric then penalizes. No
   solver can pass such a criterion without violating the prompt that graded them, which makes it
   a permanent, unfixable-by-any-solver rubric failure rather than an authoring gap a stronger
   solver could route around. (Real, independently verified: SVC-PC-35-2-0's instruction.md reads
   "Consume existing inputs -- don't invent terms that already exist," and r027/r045/r046/r047
   require a MAP enforcement escalation ladder -- notice, then suspension, then termination --
   that appears in neither the prompt nor the referenced `Wholesale_Pricing_Proposal_Draft.docx`,
   which states only "MAP policy: retailers may not advertise below MSRP... Priya to own the
   exact policy language" and stops there. SVC-PC-35-4-0 carries the identical invented ladder at
   r026/r027/r028, in the same `deliverables_03/judge.toml` file as sibling criterion r029,
   "Terms consumed from the drafted proposal, not invented Expected: terms sourced" -- a
   same-file self-contradiction, since r026-r028 require exactly the invented content r029
   forbids.)

   **Methodology step for this pattern:** read instruction.md in full FIRST, before opening any
   judge.toml, and note every "don't invent" / "sourced only" / "use only the named sources"
   sentence verbatim, including which specific inputs it names as the allowed sources. Only then
   read every judge.toml criterion in the task and check each one's Expected content against
   those named sources: if a criterion's expected content is not grounded in any of them, check
   whether it also conflicts with the "don't invent" instruction -- if both hold, flag it as this
   pattern rather than pattern 1. While reading, also compare every criterion in the same
   judge.toml file against every other one for a direct sourced-vs-invented contradiction (the
   r029-vs-r026/27/28 shape above), not just against the prompt.

## Where to find the content to audit

This skill needs the raw prompt, golden/reference answer, and grading rubric text for a task --
not a built package (`environment/` + `instruction.md` + `tests/`, harbor-structural-audit's
input) and not an inference from a tracker row's summary of that content. There is no universal
location for this; point it at wherever your own pipeline holds the pre-build task definition (a
tracker's content cells, a task-authoring spreadsheet, a corpus JSON, a set of source documents).
If you don't know where your own pipeline holds this, stop and ask rather than inferring content
from a tracker's status column or a prior audit's summary.

**If the actual prompt/golden/rubric text cannot be located for a task, say so plainly and stop
there for that task.** A tracker row reporting a task as "clean" from a prior pass is not a
substitute for reading the current text: content changes (rebuilds, fixes) can leave a stale
verdict standing, and this skill's job is to read what's there now, not to trust what a status
column claims.

## Methodology

1. Locate the current prompt, golden answer, and rubric text (above). Record where each was
   found, or that one wasn't.
2. Read the prompt (instruction.md) in full FIRST, before opening any rubric file. Note every
   "don't invent," "consume existing... don't create new," "sourced only," or "use only the
   approved/named sources" sentence verbatim, and record exactly which named inputs it declares
   as the allowed sources (a specific docx, a specific tab, "your drafted proposal," and so on).
   If the prompt carries no such language, note that and move on -- pattern 6's prompt-side shape
   does not apply, though the same-file rubric-vs-rubric shape still might.
3. If the rubric's criteria carry per-criterion metadata describing how a criterion should be
   checked and why it matters (EKW's `tests/verifier.json` names these `metadata.how_justification`
   and `metadata.why_justification`), read every one of them next, before reading the golden
   answer or evaluating any criterion's Expected content. That context consistently made the
   difference in practice: agents that read it first caught real defects faster and more
   accurately than agents that went straight to the golden output.
4. Read the golden answer in full. List every fact, figure, date, and named entity it states or
   computes. If the task ships a `Reasoning.docx` (or similarly named reasoning/rationale
   companion file) alongside the primary golden output, read it in full alongside the primary
   output, not as an optional extra -- it can carry context or contradictions the primary golden
   alone doesn't reveal, and every check below draws on it the same way it draws on the primary
   golden.
5. Read the rubric criterion by criterion. For each one: check whether the fact or figure it
   requires appears, with a matching value, in the list from step 4 -- flag any criterion whose
   required fact is absent (pattern 1) or present with a different value (pattern 2). Separately,
   check whether the criterion's Expected content is grounded in any source named in step 2; if it
   is not grounded there AND step 2 recorded a "don't invent" / "sourced only" instruction, flag
   it as pattern 6 instead of pattern 1 -- the distinguishing fact is that the prompt didn't just
   fail to mention this content, it affirmatively told the solver not to produce it.
6. Read every source/sheet/section reference inside the golden answer's own text (formula
   references, "per the X tab" phrasing, citations). Cross-check each against the golden's own
   stated list of input files or tabs. Flag any reference to something not on that list
   (pattern 3).
7. Compare every pair of rubric criteria that touch the same underlying fact or figure. Flag any
   pair that requires mutually exclusive characterizations, thresholds, or precision levels for
   that same fact (pattern 4). While doing this pass, within each single judge.toml file
   specifically, also check every pair for a direct sourced-vs-invented contradiction: one
   criterion requiring content be "sourced, not invented" (or equivalent) while another in the
   same file requires content absent from every named source. Flag that pairing as pattern 6, not
   pattern 4 -- pattern 4 is a factual or threshold conflict, this is a conflict about whether
   invention is allowed at all.
8. Read every rubric criterion's description text as if you were the solver seeing it, and ask
   whether it would function as a hint. Flag any criterion whose description states the expected
   value or conclusion outright rather than describing what a correct response would need to do
   (pattern 5). Then separately check whether that same description text is copied anywhere a
   solver-facing artifact could expose it -- a criteria file, an instruction addendum,
   environment text -- and note whether the leak is live today or latent in the rubric text
   alone.
9. Report per task: clean (all six checked, none found), or defective (name which pattern,
   quote the actual text -- not a paraphrase), or content_unavailable (with where you looked).

## Cross-reference against other layers, every time

A task this skill calls clean is only clean on this layer. Before treating it as ready, confirm
it is ALSO clean on harbor-structural-audit (the built package) and has passed an Oracle-style
run twice. A task can pass any two of the three and still fail the third -- that is the whole
reason to run all three rather than treat one as sufficient. And because this skill's real run
so far is a single 50-task sample self-graded by the auditing agents, not yet independently
checked the way harbor-structural-audit's patterns were against a real reviewer's own PDFs (see
Provenance and status), weight it below harbor-structural-audit until it earns a comparable
independently-checked track record: a "clean" from this skill today carries real, measured
signal, not yet the calibrated confidence harbor-structural-audit's six patterns have earned.

Pattern 5 also cross-references this project's own hard rule: never put the answer key in front
of the graded party. Expected values, test contents, tolerances, and grading criteria may not
appear in anything an evaluated solver reads. This skill's pattern 5 is that rule applied
specifically to rubric-description text, checked before a package is ever built -- catching it
here is cheaper than catching it after the leak has shipped.
