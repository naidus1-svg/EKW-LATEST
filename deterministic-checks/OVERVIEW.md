# Overview (meeting-ready, one page)

For the full detail behind any line here: `README.md` (capability table + honest caveat),
`BUILD-CONTRACT.md` (the schema in full), `GAP-ANALYSIS.md` (what's still missing),
`PERPLEXITY-QC-FINDINGS.md` (the external reviews that drove the newest checks).

## What this is

Deterministic, zero-LLM QC checks that run on a built benchmark task BEFORE it's sent for
grading. Every check here is a Python script: point it at a task folder, it prints pass/fail plus
a JSON report, no model call, no cost, seconds per task. They catch the class of defect where the
task LOOKS fine but the verifier is silently broken -- missing input files, a rubric with no
actual expected value, a filename the solver is told to write that the grader never opens. Built
generic on purpose: extracted from one benchmark's QC pipeline (SVC-PC), but every check operates
only on the package shape below, never on that benchmark's content.

As of 2026-09-14, that genericity is measured, not assumed: 9 of these checks are ported and
verified against a second real benchmark corpus (EKW, 274 tasks), each cross-checked against
SVC-PC with zero regressions; a 10th (`formula_health_check.py`) is ported and code-complete with
its full-corpus EKW sweep still running.

## The schema every check reads

```
<task-id>/
  instruction.md              <- the solver-facing prompt, full text
  environment/
    initial_workspace/        <- every input file the solver actually gets
  solution/
    <golden deliverable files>
  tests/
    deliverables_00/
      judge.toml               <- [judge] files=[...] + one or more [[criterion]]
    deliverables_01/
      judge.toml
```

`judge.toml` shape, the thing most checks parse:

```toml
[judge]
judge = "anthropic/claude-sonnet-4-6"
files = ["/app/Output_Workbook.xlsx"]     # what the grader actually opens
weight = 0.5

[[criterion]]
name = "obj-01"
description = "FY revenue equals the approved figure. Expected: $1,204,900 (exact)."
type = "binary"
weight = 0.06
```

Any benchmark whose build output lands in this shape gets every check below for free, no code
changes. If your benchmark uses a different config format (we found two others in the wild --
JSON `verifier.json`, JSON `manifest.json` -- see `PERPLEXITY-QC-FINDINGS.md`), a check needs a
new parser for that shape; the checks are not tied to TOML by assumption, just by what this
corpus actually uses today.

As of 2026-09-14, the `verifier.json` case is no longer hypothetical: it's the real schema EKW's
own 274-task corpus uses, and a shared parser module, `ekw_verifier_json.py`, now reads it into
this same shape -- 274/274 clean parses, 0 crashes, 0 parse errors, across 7+ real schema
variants (dict/list `source` shapes, `extract_many`/`arguments.paths` extraction forms, the
`task_FIN-177` task's fully alternate schema, directory-type reference entries, rubric vs
deterministic assertion types).

## Checks A-E, in plain words: what each one is actually asking, and who answers it

Five questions get asked about every task, in this order, before it's ready to grade. Think of it
like publishing a cookbook recipe: does the recipe make sense (A), did the test kitchen actually
cook it (B), did the finished dish come out looking like the photo (C), is the recipe card itself
legible and complete (D), does the math in the recipe add up -- servings, cook time, conversions
(E)?

| # | Plain question | Who answers it today | Deterministic script vs. LLM/human |
|---|---|---|---|
| **A** | Does the question, the model answer, and the grading rubric actually agree with each other? | A person or a Claude session, reading all three side by side (`content-audit/SKILL.md`) | **0% script, 100% judgment.** This is a "does this make sense" question about meaning, not text-matching -- no script here mechanizes it yet. |
| **B** | Did the task actually get built -- did the raw files get converted and staged where they belong? | Each benchmark's own build pipeline. Mechanically this is just "does the output folder exist and look right," but every benchmark builds differently | **Not this folder's job by design**, not because it's hard. `BUILD-CONTRACT.md` explains why: a script here would either check nothing (does a folder exist?) or hardcode one benchmark's build process. |
| **C** | Does the finished package actually WORK -- does the solver have what it needs, does the grader open the file it's supposed to, is anything leaking that shouldn't be? | Used to be 100% a person/LLM reading `structural-audit/SKILL.md`'s 6 known patterns. **As of this batch, all 6 of those patterns now also have a matching script.** | **Now ~100% script-coverable for the 6 KNOWN failure shapes**, zero LLM cost. A human/LLM read-through is still worth doing to catch anything outside those 6 -- the scripts close the known gaps, they don't replace judgment entirely. |
| **D** | Is the grading rubric itself well-formed -- no blank spots, no duplicate questions, no scores that silently don't add up, nothing stale? | Used to be one script (does the prompt mention every graded filename). **Now the single biggest bucket of new scripts.** | **~100% script, zero LLM**, for everything a script CAN mechanically see. A few of the new scripts (duplicate detectors, the leak-content check, the determinism lint) deliberately report "a person should look at this" rather than an automatic pass/fail -- flagged for review, not auto-resolved. |
| **E** | Do the spreadsheet formulas actually compute what they claim to compute? | `formula_health_check.py` + autofix, unchanged approach, extended this batch | **100% script, zero LLM.** The most battle-tested check in the repo. |

**In one line: A and B stayed exactly where they were (A is a reading question, B isn't this
repo's to solve). C and D are where almost all of this session's new work landed -- both moved
from "mostly a person reading a checklist" to "mostly a script," which is the whole point of this
repo existing.**

## What each check does, with a simple picture, and which letter it belongs to

**[C] `environment_input_check.py`** -- like checking a recipe box shipped with every ingredient
the recipe card asks for, BEFORE anyone starts cooking. Catches: the card says "add 2 eggs" but
there are no eggs in the box; the card points to "the folder on Grandma's cloud drive" instead of
actually putting the folder in the box; or the box has a sticker saying "nothing needed, ready to
cook" while the card clearly lists three ingredients. EKW-ported 2026-09-14: 273/274 pass, one
real finding needing human judgment, the other two sub-patterns already clean.

**[C] `answer_key_leakage_check.py`** -- like a teacher naming the answer sheet `ANSWERS.pdf` and
accidentally handing it to the whole class, or leaving a sticky note with grading instructions
stuck to the front of the test.

**[C] `deliverable_count_check.py`** -- like a shopping list that says "buy milk, eggs, AND
bread," but whoever checks the receipt only ever looks for milk. Two of the three things asked
for never get checked at all, and nobody would know unless someone counted. EKW-ported
2026-09-14: 204/3/67 pass/fail/skip out of 274, after recognizing EKW's own deliverables-heading
phrasing.

**[D] `deliverable_filename_check.py`** -- like a teacher who tells the class "save your homework
as `homework.pdf`," but then only ever opens a folder looking for `essay.pdf`. This check looks
both ways: does the naming in the assignment match what the teacher actually checks, AND does
what the teacher checks match what the assignment told the student to call it. The second
direction is the sneaky one -- a student can follow the instructions PERFECTLY and still get a
zero, because the teacher was never going to look at that file. EKW-ported 2026-09-14: FORWARD
272/2/0, REVERSE 74/0/200 pass/fail/skip out of 274.

**[D] `deliverable_integrity_check.py`** -- like actually opening a wrapped present to make sure
it isn't empty or broken inside, instead of just checking the box has the right label and feels
about the right weight.

**[D] `rubric_schema_check.py`** -- like a test's answer key where some questions have no answer
written down at all, some say "worth 10 points" with the actual right answer left blank, and the
points across the whole test don't add up to 100. EKW-ported 2026-09-14, clean across all 274
tasks.

**[D] `rubric_text_lint.py`** -- three specific ways a grading rubric can quietly stop making
sense: asking "is the crust golden-brown?" when the grader can only read a text description of
the pie, not see a picture of it; still asking about a PowerPoint when the assignment was changed
to ask for an essay instead; or asking the student to prove they scored 100% on the rubric before
they've even been allowed to see it. EKW-ported 2026-09-14, clean after fixing an
`extraction_blind` false-positive class (7 of 11 initial flags).

**[D] `duplicate_criterion_check.py` / `judge_criterion_name_duplicate_check.py`** -- like two
raffle tickets printed with the same number. Whoever draws that number, one prize secretly never
gets awarded -- and because the TOTAL number of tickets still looks right, nobody notices unless
someone checks the numbers themselves, not just the count. Both EKW-ported 2026-09-14 and
verified clean; the port also fixed a `duplicate_criterion_check.py` false positive tied to
misread business-data sheets.

**[D] `tab_naming_check.py`** -- like a recipe book saying "the frosting recipe is on page 2," but
page 2 is actually the cake recipe. The frosting is somewhere else, or doesn't exist. EKW-ported
2026-09-14, clean.

**[D] `answer_key_content_leak_check.py`** -- subtler than the filename version above: the actual
answer (not an obviously-named answer file) shows up, word for word, inside one of the study
materials the student was handed. Tricky, because sometimes that's totally fine on purpose (the
answer IS supposed to come from a real source document) -- so this one only rings the alarm when
BOTH the value AND a suspiciously-named file show up together, and it hands the result to a
person to double check rather than auto-failing anything. EKW-ported 2026-09-14, clean.

**[D] `judge_determinism_config_lint.py`** -- like a judge who decides a competition's winner by
flipping a coin exactly once, with no backup vote if it lands wrong. The same two performances
could get a different winner every time the coin gets re-flipped. This check looks for "is there
just one coin flip with no backup" in the grading setup. Needed zero code changes for EKW;
running it against all 274 EKW tasks found 269 with a nonzero judge temperature and no panel -- a
real finding worth flagging to EKW's judge-config owner.

**[E] `formula_health_check.py` + `formula_cache_autofix.py`** -- like a calculator that's still
showing yesterday's frozen answer on its screen instead of doing the math fresh right now. This
check redoes the math to make sure the screen isn't lying to you; the autofix nudges the display
to catch up, but ONLY when it can prove the real math checks out -- it never invents a number.
EKW port: verified correct on an 8-task smoke sample; the full-274 sweep is still running as of
this writing, no final number yet.

**[A] `content-audit/SKILL.md`** -- reading the question, the model answer, and the grading
rubric together and asking "wait, does this rubric even make sense given what the question and
the model answer actually say?" This is the one that still needs a real reader (person or Claude)
-- it's a meaning question, not a find-the-typo question, so no script replaces it.

**[C, methodology] `structural-audit/SKILL.md`** -- the "does everything fit together" checklist
a person used to walk through by eye, all 6 of its steps now also covered by one of the scripts
above. Still worth running as a person/LLM pass for anything outside those 6 known shapes.

**[unlettered, v0/unvalidated -- in `v0-checks/`, don't trust output as a verdict yet]**
duplicate-task detection, PII/metadata scanning, prompt-injection scanning, golden-answer
reproducibility.

## The one-sentence pitch, if you only get one sentence

Every check here answers a question a human reviewer asks by hand today -- "does the solver have
what it needs, does the grader check what it says it checks, is the answer key exposed" -- for
free, in seconds, before a single dollar is spent on an actual grading run. And this batch moved
Checks C and D from "mostly a person's judgment call" to "mostly a script," which is the actual
point.
