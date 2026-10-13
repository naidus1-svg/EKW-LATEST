# manager-read: the step 3 manager reader

`manager_read.py` reads one task and its four DataOS Answer Check reviews the way the step 3 manager reader did in
the audit sandbox. It makes one model call and prints a report of items. Each item names a criterion, a
file, the quoted words and what to change. **Every item needs a written answer from the QC person.** The manager sends the
whole list and approves the task only after the answers check out (docs/QC-RUNBOOK-manager.md, rule D).

## What it reads

A task package is the instruction, the input files, the golden (reference answer) and the grader (the rubric:
weighted criteria that an AI judge applies to a model's answer). Answer Check reviews are four AI reviews that the
normal DataOS pipeline ("ManualQC automated QC pipeline 4 Reviewers", DataOS pipeline 141, version 8; its review prompt is
saved as prompt id 431, named Comprehensive_v3_pipeline_quality_re-derive_cascade_NOP_2026-10-03) runs on the task. A review is a MAJOR
review when it lists at least one finding with severity major. The reader gets:

- `instruction.md`, the input files, the golden and every criterion with its effective weight (its share of the final score);
- the major findings of the four Answer Check reviews, text cut at 1500 characters (minor findings are not read: the
  audit run did not have them either). If fewer than four complete reviews are found, the reader is told to judge
  from the package alone;
- the reward of the stored empty-answer (nop) run, when the download has one.

Input is a `rev_<n>__<id>` folder of a **Dataset with runs** download (the file you get from the DataOS button of that name; it holds `task_files/`, `verifications/` and
`evaluations/`), or a plain package folder (`--reviews DIR` points at the review files), or an audit-layout folder.
It works in a throwaway copy and never changes your folder.

## Run it

```
python3 automation/manager-read/manager_read.py <rev folder> --out <report folder> [--tab EKW|SVC] [--reviews DIR]
python qc.py manage <Dataset with runs zip or extracted folder> [...] --out <folder>    # every task of a download
```

Output per task: `manager_read_report.md` (read this) and `manager_read_result.json`. `qc.py manage` also writes
`manager_summary.csv`, one row per task. Exit code of the script: 0 no items, 1 items, 2 could not run (or the
reader returned HOLD, meaning it could not judge; the report says why). Options: `--claude-cmd` or
`$MANAGER_READ_CLAUDE` for a different `claude` path, `$MANAGER_READ_MODEL` (default `sonnet`),
`$MANAGER_READ_TIMEOUT` seconds for the call (default 2400). Needs the `claude` command (Max plan, no paid API),
Python 3.11 or newer, and `automation/task-read/task_read.py` next to it (shared package layout code).

Cost: one call per task. In the smoke check below it took between 23 and 67 seconds per task (see the check).

The model gets Read, Glob, Grep and read-only commands (`python3, ls, cat, head, unzip, strings, pdftotext`).
No Write. The audit runs used unrestricted Bash inside a sandbox that hid every other file: this tool restricts
the commands instead, so the measured numbers below describe the reader, not exactly this tool.

## What was measured (all UNAUDITED)

The defective and clean labels are model-built (truth_v5, `material_tabrule`); no person checked them. "Flagged"
means the stored reader's verdict was SEND_BACK (it listed at least one fix item). Source: out/MGRADVIS.md,
out/FAOPUS.md, work/mgradvis/tasks.csv.

- On the 95 tasks of batches 4 to 13 that were not used to write the finder prompt (46 defective, 49 clean): the
  manager reader alone flagged 31 of 46 defective and 18 of 49 clean (UNAUDITED).
- The step 1 task read (`qc.py read`) plus the manager reader as a second reader flagged 35 of 46 defective and
  22 of 49 clean (UNAUDITED). The step 1 task read alone: 14 of 46 and 4 of 49 (UNAUDITED).
- On all 149 labelled tasks (88 defective, 61 clean): the manager reader flagged 61 of 88 and 23 of 61 (UNAUDITED).
- Against TFRL (the outside QC team) instead of the audit label (39 rejected, 56 approved of the 95): flagged 26 of 39 rejected and
  23 of 56 approved (UNAUDITED). The manager run sheet (`docs/QC-RUNBOOK-manager.md`, last section) shows other counts on the same 95 tasks for "either reader" (29 of 39 rejected, 28 of 56 approved); do not mix the two sets of counts.

In plain words: out of 100 tasks the audit calls defective the reader gives items on about 67; out of 100 clean
tasks, about 37. So **expect to drop some items**; an item is a specific claim with a quote you can check in a
minute. No items does not mean the task is clean: the reader misses most coverage gaps and ambiguous sentences.
A wider version that also promoted its low-priority notes to items (MGRADVIS) caught more but gave items on far more
clean tasks, with no paired gain; it is not in this tool.

## Prompt

`prompts/manager_prompt.md` is the manager prompt of the audit runs, unchanged (file
`build/step3/manager/manager_prompt.md`). sha256 `2cb1fa1180b5abf81f89a7da0e481deb391a30ed189f91ac19df9613e8492905`.
The script refuses to run when the file does not match that hash. To change the prompt on purpose, edit the file,
update `PROMPT_SHA256` in the script and this line, run the tests, and re-measure before you quote any number.
A test checks that the prompt carries no label or expected value.

## Tests

`python3 automation/manager-read/test_manager_read.py` uses a fake `claude` script (no model, no network) and prints
`TESTS n/n passed`. It runs on Windows and Linux (the fake is started through the Python interpreter).

## Smoke check of this packaged tool

PILOT, 6 tasks, run twice each (12 runs), a smoke check and not a rate (UNAUDITED). The 6 came from the 95 held-out
tasks (seed 12): 3 the stored reader sent back, 3 it approved. The reader saw no label. Against the stored verdict the
first run gave the same flag (items or none) on 5 of 6 tasks and the second run on 6 of 6; the two runs agreed with
each other on 5 of 6, and both agreed with the stored verdict on 5 of 6. The one task that differed (stored APPROVE)
got 2 items in one run and none in the other. Items are not stable: on the 3 sent-back tasks the first run named 2 of
the stored reader's 3 criteria, 1 of 4 and 0 of 1. Cost: 1 model call per task, 22 to 84 seconds (mean 54) per task;
12 runs, 4 at a time, took 3 minutes 13 seconds. Dollar cost was not recorded.
