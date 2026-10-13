# The build contract

## What "Check B" is, and why it isn't a script here

Every benchmark's QC has (at least) two layers before grading:

- **Check A** - does the *content* hold up: prompt, golden, rubric internally consistent,
  formulas recompute clean, filenames line up. That's what this folder's checks do.
- **Check B** - did the benchmark's own build pipeline actually run and produce a valid task
  package in the first place: did the raw source corpus get pulled, converted, hydrated into
  `environment/initial_workspace/`, did the golden get generated into `solution/`, did the
  judge config get written to `tests/`.

Check B cannot be a generic script in this folder. Every benchmark's raw source corpus has a
different shape: SVC-PC starts from live spreadsheets and MSAs, another benchmark might start
from a database dump, a set of PDFs, a Drive folder of scanned documents, or an API response.
Each needs its own extraction, conversion, and hydration logic to turn that source material into
task files. A script here that tried to check "did your build succeed" would either be so generic
it checks nothing (does a directory exist?) or would have to hardcode one benchmark's source
format, which is exactly the mistake `README.md`'s honest caveat already warns against for the
rest of that source pipeline.

What generalizes instead is the *shape build output has to land in*. Every check in this folder
(`formula_health_check.py`, `structural-audit/SKILL.md`, and the rubric/filename/integrity checks
still being built per `GAP-ANALYSIS.md`) is written against one fixed package shape and knows
nothing about how that shape got produced. Get your build script's output into this shape and
every check here runs against it immediately, with zero changes to the checks. That shape is the
actual contract, below.

## The contract

For each task, a directory named by a unique task ID, directly under whatever root you point a
check's `--root` at:

```
<root>/
  <TASK-ID>/
    instruction.md
    environment/
      initial_workspace/
        <every input file the solver gets, any nesting>
    solution/
      <golden / reference deliverable files, any nesting>
    tests/
      deliverables_00/
        judge.toml
      deliverables_01/
        judge.toml
      ...
```

- **`instruction.md`** - the solver-facing prompt. Full text, nothing else. Any internal
  pipeline label, stage name, or answer-key filename that leaks in here is itself a defect
  (`structural-audit` pattern 4), not part of the contract.
- **`environment/initial_workspace/`** - every file the solver starts with, actually staged on
  disk. Not a link, not a bare cloud-storage URL sitting in a text field (pattern 3), not a
  placeholder marker if `instruction.md` names real required files (patterns 1 and 5).
- **`solution/`** - the golden/reference deliverable files. Checks that inspect this directory
  glob it recursively rather than assuming one fixed filename or one fixed subpath
  (`find_spreadsheets` in `formula_health_check.py` walks `solution/` with `rglob("*")` and
  filters by suffix precisely so a nested path or a build-time renamed file still gets found) -
  but the files that end up under `solution/` still have to be the actual graded content, not a
  stand-in.
- **`tests/deliverables_*/judge.toml`** - one or more TOML files, each in its own
  `deliverables_NN/` subdirectory. Each file needs:
  - a `[judge]` table with a `files = [...]` list: the exact deliverable path(s) this group of
    criteria grades, relative to the task directory.
  - one or more `[[criterion]]` blocks, each with `name`, `description`, `weight`, and `type`.

  This is read verbatim by `load_judge_criteria()` in `formula_health_check.py`: it globs
  `tests/deliverables_*/judge.toml` (underscore, not a bare `deliverables*`), reads `judge.files`
  once per file, and flattens every `[[criterion]]` under it with that same file list attached.
  A `judge.toml` that doesn't parse, or a criterion missing one of those four fields, is exactly
  the failure mode the (still-being-built) rubric-schema check exists to catch - but it can only
  catch it if the file is at this path with this table structure.

## Confirmed against the two checks that exist today

This shape is not a guess. It's read directly out of the two working checks in this folder:

- `formula_health_check.py`'s own docstring states its expected package shape explicitly
  (`solution/` holding golden `.xlsx`/`.xlsm`, `tests/deliverables*/judge.toml` with
  `[[criterion]]` blocks carrying `judge.files` plus `name`/`description`/`weight`/`type`), and
  `find_spreadsheets()`, `load_judge_criteria()`, and `resolve_graded_files()` implement exactly
  that: glob `solution/` recursively for spreadsheet suffixes, glob
  `tests/deliverables_*/judge.toml`, pull `judge.files` and the four criterion fields.
- `structural-audit/SKILL.md`'s frontmatter and methodology are written against the same package:
  `environment/initial_workspace/`, `instruction.md`, `tests/`, cross-checking prompt text against
  what's staged in the workspace and against the verifier's `files=[...]`.

Both were re-read in full to write this document, specifically to confirm they agree with each
other and that neither has a quiet extra assumption this document would otherwise miss.

## What this means for your build script

- **If your build script's output already matches this shape:** every check in this folder, and
  every one still to come per `GAP-ANALYSIS.md`, runs on it today with zero changes.
- **If it doesn't:** the fix is in your build script's output, or a thin translation layer you
  write and own next to your build script - a small script that reads whatever your pipeline
  actually produces and re-lays it out into this shape (real files or symlinks, task ID directory
  names, `judge.toml` in the right place). It is never the checks in this folder. If a check needs
  to change to accommodate a benchmark-specific quirk, that is a sign the quirk belongs in your
  translation layer instead, not a reason to add a flag or a special case to a shared check.
- **Non-spreadsheet deliverables are fine.** `formula_health_check.py` finds zero `.xlsx`/`.xlsm`
  under `solution/` and reports `status: pass` with an explicit note that it verified nothing
  (`no .xlsx/.xlsm found... not itself a defect`), rather than treating an empty result as an
  error. A task whose deliverable is a `.docx` or a `.pdf` is outside that check's scope, not a
  contract violation - see `GAP-ANALYSIS.md` item 8 for the integrity check that will eventually
  cover those formats, once built, against this same shape.
- **A documented format-conversion shim is an escape hatch, not a rewrite.** If your build
  authors goldens in one format (e.g. `.xlsm`) and converts them at grading time, drop a shell
  script under `tests/` or `environment/` that does the conversion and mentions both formats by
  name; `detect_conversion_shim()` looks for exactly that and treats the converted file as the
  real graded file instead of flagging a filename mismatch. Don't invent a new field or directory
  for this - use the mechanism that's already there.

## Worked example: EKW (`ekw/`)

EKW's build lands in `environment/data/`, `solution/golden_outputs/` and `tests/verifier.json`,
none of which this contract names, and its 274-task drop mixes two build genres in one layout.
`ekw/ekw_check_b.py` is what this document asks a non-conforming benchmark to write: its own
Check B (package files, verifier schema in every shape the corpus actually uses, weights, graded
files against goldens, genre), and a translation layer (`--stage`) that lays each task out in
the shape above with a lossless, round-trip-verified `judge.toml` per graded-file group. The
shared checks then run on the staged tree with zero changes, through `ekw/ekw_run_checks.py`.
Where a shared check misreads an EKW convention (EKW prompts name outputs, never inputs), the
runner reconciles the verdict and records that it did, rather than patching the check. Read
`ekw/README.md` before adapting this pattern to another benchmark.
