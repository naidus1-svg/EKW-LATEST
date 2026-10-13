# How to use this: a walkthrough for task creators

Status: stale. This is one of the oldest docs in the repo and was written for the older `tests/rubric.json` task shape. See the [doc index](../README.md).

This is the practical runbook. `CLAUDE.md` has the full rules and
`QC_DIMENSIONS_FOR_CREATORS.md` has the reasoning behind each one; this file
is just "what do I actually type, in what order, after I finish a piece of
the task."

Severity levels (sev 1, 2, 3) come from the shared grading rules in [QC_FOUNDATION](../../skills/_shared/QC_FOUNDATION.md).

You need Python 3 with `openpyxl`, `python-docx`, and `pypdf` installed
(`pip install openpyxl python-docx pypdf`) to get full coverage. Missing one
of these degrades a script to a reported skip, not a crash, but you'll want
them installed for a real check.

## The four steps, in the order you'll actually hit them

### Step 1 — right after you finish writing `instruction.md`

```bash
python3 task-creation-qc/skills/source-file-reference-check/scripts/check_references.py <path-to-your-task-dir>
```

This checks every filename your instruction mentions by name against what's
actually sitting in `environment/data/`, and flags an empty or
pointer-only data folder. Fix anything at severity 2 before moving on — a
missing referenced file is the single most common reason a task gets
rejected.

### Step 2 — once `environment/data/` is fully assembled

```bash
python3 task-creation-qc/skills/synthetic-marker-scan/scripts/check_synthetic_markers.py <path-to-your-task-dir>
```

This scans every source file for leaked pipeline artifacts: bracket tags
like `[SYNTHETIC]`, unrendered template code like `$(T20.inYear)`, and
suspicious dates (a "2021" record with a "2026" timestamp buried in it).
Anything at severity 2 here is a hard stop, no exceptions, fix it before
going further. A severity 1 date flag is worth a look but isn't automatically
wrong.

### Step 3 — once the golden solution and `rubric.json` are drafted

```bash
python3 skills/svc-task-qc/scripts/check_rubric.py <path-to-your-task-dir>/tests/rubric.json --level <L1|L2|L3>
```

Note this one lives in the sibling `skills/svc-task-qc/` folder, not inside
`task-creation-qc/` — that's intentional (see the note at the bottom of
this file). Checks the rubric's structure: a must-pass gate exists and
isn't overused, the criterion count fits the task's level, no criterion has
a blank pass condition, and a keyword scan for vague language ("board-ready,"
"on-brand," "professional," and similar). That last one is deliberately
loose: it flags more than it needs to, on purpose, so you don't miss a real
one. Read every hit; don't treat all of them as something to fix.

### Step 4 — right before you'd otherwise call the task done

Open `task-creation-qc/skills/authenticity-and-substance-review/CHECKLIST.md`
and go through it against your actual draft, one question at a time. This is
the step the first three don't cover: does the task read as real professional
work, does the golden actually hold up, is the rubric language backed by
something concrete. No script does this for you. Skipping this step is how
most of what the first three scripts miss gets through anyway.

## Reading the output

Every script prints a plain-text summary first, then the same findings as
JSON at the bottom (ignore the JSON unless you're feeding it into something
else). For each line:

- **`PASS`** — nothing to do.
- **`sev 2` or higher** — fix this before delivering. These are the findings
  that get a task rejected outright in the real QC pass.
- **`sev 1`** — worth a look, not automatically wrong. Several checks (the
  date scan, the vague-language scan, the unreferenced-files list) are
  built to over-flag on purpose. Use judgment; don't chase every one to
  zero.

## What "done" looks like

- Steps 1-3 come back with every severity-2-or-higher finding resolved, or
  you have a specific reason you're accepting one anyway.
- Step 4's checklist has a concrete answer for every question, not a
  shrug.
- If `solution_format_match` or `metadata_completeness` come up anywhere,
  check `KNOWN_CALIBRATIONS.md` before assuming either one is a non-issue.

## One thing to know about the folder layout

`rubric-structure-check` doesn't carry its own copy of `check_rubric.py` —
it points at the one in `skills/svc-task-qc/scripts/`, which is the same
script the post-hoc QC review process uses. That's deliberate: one script,
not two copies that can quietly drift apart. Keep the `task-creation-qc/`
and `skills/svc-task-qc/` folders as siblings (same parent directory) the
way they were shared with you, and the paths above will just work.
