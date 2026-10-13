---
name: harbor-structural-audit
description: >-
  Checks a built Harbor-shaped task package (environment/initial_workspace/,
  instruction.md, tests/) for six defect classes found by real manual review
  on a benchmark task pool: a placeholder environment contradicting a prompt
  that names real required files, a deliverable filename the prompt tells
  the solver to produce that the verifier never reads, an unhydrated
  Drive-only dependency, answer-key or internal-pipeline text leaking into
  the solver-facing prompt, an internal contradiction, and an unstated
  deliverable count or format. This is a THIRD, distinct layer from Oracle
  (checks the rubric agrees with its own golden answer, nothing about the
  built package) and from a content-only read of prompt/golden/rubric text
  (checks internal consistency of that text, never the actual shipped
  files). None of the three alone establishes a task is ready - use this
  whenever a task has moved from "content looks right" toward "about to be
  uploaded for grading," and always alongside, never instead of, the other
  two.
---

# Structural audit for Harbor-shaped task packages

## Provenance and status

Extracted and generalized from a QC pipeline built for one benchmark
(SVC-PC / Cirrus Sleep). The six defect patterns and the methodology below
are defined entirely in terms of the generic package shape
(`instruction.md` + `environment/` + `tests/judge.toml`), not anything
specific to that benchmark's content, and have not needed benchmark-specific
changes to transfer. Status: proven at real scale in the source project;
the worked examples under each pattern below are from that project and are
illustrations only, not paths or IDs meaningful anywhere else.

Applying this skill still requires an LLM (a Claude session) or a person to
actually read the package and apply the six checks -- "mechanical" here
means "follow this exact recipe and report findings verbatim," not "zero
judgment, zero LLM involved."

## Why this exists, and what it is not

A content-only audit (reading prompt/golden/rubric text directly, no
built-package involved) can call a task "clean" while missing an entire
class of real defects: not a rubric-vs-golden mismatch, a
prompt-vs-shipped-environment mismatch. A task can have a perfectly
consistent prompt, golden, and rubric and still be unrunnable, because the
files the prompt names were never staged, or the file the solver is told to
produce is not the file the verifier opens.

An Oracle-style run (submitting a task's own reference answer to its own
grader) does not catch this either -- it proves the rubric agrees with the
golden, nothing about whether the environment matches the prompt.

So there are three layers, and this skill is the third:

| Layer | Checks | Catches | Misses |
|---|---|---|---|
| Content audit | prompt/golden/rubric text | Internal text inconsistency (rubric asks for something prompt never requested, sheet references that don't exist in the golden) | Anything about the actual shipped files |
| Oracle | rubric vs. golden, run twice | The golden fails its own rubric (a real answer-key/rubric mismatch) | Anything about the environment or the prompt-vs-verifier filename contract |
| This skill | the built package: environment/, instruction.md, tests/ | Placeholder environment vs. named-file prompt, deliverable filename mismatch, unhydrated Drive dependency, leaked answer-key naming, unstated deliverable count | Whether the rubric's content is actually correct (that's the content audit's job) or whether the golden passes it (that's Oracle's) |

None of the three alone is 100% confidence. Running all three and still
finding nothing is the honest ceiling, not a guarantee.

## The six defect patterns

1. **Placeholder environment contradicts the prompt.**
   `environment/initial_workspace/` holds only a placeholder file (e.g. a
   `_no_input_files_required.txt`-style marker) while `instruction.md`
   names specific required files by exact filename that are not present
   anywhere. (Source-project example: a task needed two named files,
   neither shipped, neither findable anywhere in the source corpus by
   filename or content search.)
2. **Deliverable filename mismatch.** `instruction.md` tells the solver to
   produce one filename; the verifier (`tests/judge.toml` or equivalent)
   reads a different path. An agent that follows the prompt exactly writes
   files the grader never opens and scores 0, silently. (Source-project
   example: instruction.md demanded two specific golden-style filenames;
   the verifier read two entirely different paths.)
3. **Unhydrated external dependency.** A "Files / Connectors" field or a
   referenced input is only a cloud-storage folder URL, never actually
   pulled into `environment/initial_workspace/`.
4. **Answer-key or internal-pipeline leakage into the solver-facing prompt.**
   A literal `GOLDEN`/`Golden` reference-solution filename the solver is
   told to produce (pattern 2's example above is also this), or raw
   pipeline text (internal stage labels, bracketed build-system language)
   left inside `instruction.md` that doesn't read like task content.
5. **Internal contradiction.** The environment claims via a placeholder that
   no specific input files are needed, while the prompt's own text
   explicitly names required files or an attachment. Both cannot be true at
   once; this pattern is what makes pattern 1 detectable without first
   knowing the file is missing -- the placeholder and the prompt disagree
   with each other, which is checkable from the package alone.
6. **Unstated deliverable count or format.** The prompt asks for multiple
   named outputs (a workbook, a memo, an email) but neither `instruction.md`
   nor the verifier config ever states how many files or what format, so an
   agent has to guess how many files to write and in what shape.

## Where to find the built package

This skill needs the actual converted, staged `environment/` +
`instruction.md` + `tests/` structure for a task -- not a raw prompt/golden/
rubric text cell from a tracker or spreadsheet, and not an inference from
what a tracker row claims. There is no universal location for this; point
it at wherever your own pipeline stages built packages (a build output
directory, a storage bucket, a zip of the task set). If you don't know
where your own pipeline stages this, stop and ask rather than inferring
contents from a tracker row or any other summary artifact.

**If a built package genuinely cannot be located for a task, say so plainly
and stop there for that task.** "No built package" is not "clean" -- it
means this specific risk is unassessed, not cleared. Do not infer a
package's contents from a tracker's raw content cells; read the actual
files.

## Methodology

1. Locate the real built package (above). Record where it was found, or
   that it wasn't.
2. Read `instruction.md` in full, list every filename or attachment it
   names as required input, and cross-check each against the real contents
   of `environment/initial_workspace/`.
3. Read the verifier config under `tests/` and extract the exact path(s) it
   reads as the graded deliverable. Compare against what `instruction.md`
   tells the solver to produce, filename for filename.
4. Check every "Files / Connectors" or similarly-named reference field for
   a bare cloud-storage URL with nothing hydrated locally to back it.
5. Scan `instruction.md` for `GOLDEN`/`Golden` in a filename the solver is
   told to write, and for any bracketed or clearly-internal pipeline
   language that doesn't read like task content.
6. Count the deliverables the prompt's own language asks for, and confirm
   `instruction.md`/the verifier state a matching count and format.
7. Report per task: clean (all six checked, none found), or defective
   (name which pattern, quote the actual mismatch -- not a paraphrase), or
   no_built_package (with where you looked).

## Cross-reference against other layers, every time

A task this skill calls clean is only clean on this layer. If your own
pipeline has other independent QC layers (a content audit, an
Oracle-style rubric-vs-golden run), run this alongside them, not instead
of them -- this skill alone is not a full readiness signal. A task can pass
any two of the three and still fail the third; that is the whole reason to
run all three rather than treat one as sufficient.
