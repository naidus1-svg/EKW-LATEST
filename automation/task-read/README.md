# task-read: read a task before you send it

`task_read.py` reads one task package with four model calls and tells you, in plain English, whether it found a
specific defect. It is the cheap, local version of the audit procedure: run it on your own computer before you
upload to DataOS.

## What it does

A task package is the instruction, the input files, the golden (reference answer) and the grader (the rubric:
weighted criteria). The script copies the package to a throwaway folder and makes four `claude -p --model sonnet`
calls, through the `claude` command you already use (Max plan). It calls no paid API.

1. **v2 reader.** The manager's version 2 guide reader. Only rules A1 (golden wrong), A2 (a criterion asks for
   something the instruction does not), A3 (a judge lacks the files it needs) and A7 (a valid answer fails) count.
2. **Finder A.** Goes through the grader criterion by criterion. For each criterion that carries real weight it writes
   two or three different correct answers and checks whether the grader would wrongly refuse them.
3. **Finder B.** The same prompt as A, run a second time on its own, so a defect one pass misses the other may find. A and B run side by side.
4. **Verifier.** One call over the findings of A and B put together (more than 12 findings: one call per 12). It
   keeps a finding only if it can quote file evidence.

A task is **FLAGGED** when the reader fires A1, A2, A3 or A7, or the verifier keeps a finding on a criterion that
counts (EKW: effective weight 0.05 or more; SVC: one of the three heaviest criteria). Effective weight is the
criterion's share of the final score, all shares add to 1.

## Run it

```
python3 automation/task-read/task_read.py <task folder> --out <report folder> [--tab EKW|SVC]
python qc.py read <task folder> [--out DIR] [--tab EKW|SVC]   # same thing through the launcher
```

`<task folder>` is the package as you hold it (`instruction.md`, `environment/`, `solution/`, `tests/`), or the
audit layout (`instruction.md`, `inputs/`, `golden/`, `rubric/criteria.json`). Output: `task_read_report.md` (read
this) and `task_read_result.json`. Exit code 0 not flagged, 1 flagged, 2 could not run (the report says why).

Runtime: 4 calls (more only if the finders report more than 12 findings), about 2 minutes a task in the test.
Settings: `--tab EKW` or `--tab SVC` (the task kind; the tool asks for it when the files cannot tell, see below), `--max-parallel N` (default 3 calls at once), `--claude-cmd` or `$TASK_READ_CLAUDE` for a different
`claude` path, `$TASK_READ_TIMEOUT` seconds per call (default 1800).

The model gets read and Python tools only (`Read, Glob, Grep, python3, ls, cat, head, unzip, strings`) plus
`Write` so a finder can save its `defects.json`, all inside the throwaway copy. Your original folder is never
changed.

## Which kind of task (EKW or SVC)

The two kinds count different findings (EKW: criterion weight 0.05 or more; SVC: one of the three heaviest criteria),
so the tool needs the right kind. It settles it in this order: your `--tab EKW` or `--tab SVC` option; the category word
in `task.toml`; a `tests/verifier.json` grader with no `tests/reward.toml` (EKW). If none of these settles it, the tool
stops before any model call and tells you to run it again with `--tab`. The report header says which source decided.
Give `--tab` whenever you know the kind: two EKW packages in the check below carried an SVC-looking category word.

Why: the first version guessed from whether `tests/reward.toml` exists. 39 of 99 EKW packages have no such file and
all 50 SVC packages have one, so that guess matched the sheet on 60 of 149 packages. The order above settled 121 of
the 149 and was right on 119 of them; the other 28 need `--tab` (in-sample: measured on the same 149 packages the
order was designed on; counts of file layouts against the kind written in the sheet).

## What it catches and does not (numbers are UNAUDITED)

Measured in the pipeline-quality sandbox runs of 2026-10-08 on 149 tasks (88 the audit calls defective, 61 it calls clean) with the reader rules
A1, A2, A3, A7 plus the two finder passes and the verifier (UNAUDITED: the defective and clean labels are
model-built, no person checked them; evidence kept by Khiem Doan).
In plain words: out of 100 defective tasks about 30 get a flag, out of 100 clean tasks about 8.
- Batches 4 to 13 not used to write the finder prompt (46 defective, 49 clean): 14 of 46 defective flagged (30%,
  95% range 19% to 45%), 4 of 49 clean flagged (8%, 3% to 19%) (UNAUDITED).
- Batches 10 to 13 alone (22 defective, 20 clean): 5 of 22 (23%, 10% to 43%) and 1 of 20 (5%, 1% to 24%) (UNAUDITED).
- All 149: 39 of 88 (44%, 34% to 55%) and 5 of 61 (8%, 4% to 18%) (UNAUDITED).
The finder prompt was frozen before these runs and not changed. The reader rules were written after the labels were
seen, so their share is not a fair test. The finders alone caught 13 of 46 and the reader rules alone 2 of 46 in the
batches 4 to 13 group. **No flag does not mean the task is clean.** Most coverage gaps and ambiguous sentences are not
found. Keep reading the task yourself. A flag names a criterion, a file and quoted words, so you can check it in a
minute and ignore it if it is wrong. The test runs used wider tools than the packaged tool set. A re-run of this exact script on 6 tasks, twice each, gave the same verifier flag as the audit run in 8 of 12 runs, and in 10 of 12 once the task kind is read correctly (UNAUDITED); 6 tasks is a smoke check, not a rate.

## Prompts and how to swap one

The four prompts are in `prompts/` and are the only things that steer the model:

| file | source in the sandbox | sha256 |
|---|---|---|
| `v2_reader.md` | `reader/mgr_v2_prompt.md` | `80cd3df3307305d00d7cb762db8790f55d9c30bf1f3a5a30c68abc56a8bbb232` |
| `finder_a.md` | `work/auditlite2/FROZEN_PROMPT.md` | `d6d408730205ada9b29d74c63c91bb00918682420e5cfe7f3b32724522b3c497` |
| `finder_b.md` | `work/auditlite2/FROZEN_PROMPT.md` (same file as finder A) | `d6d408730205ada9b29d74c63c91bb00918682420e5cfe7f3b32724522b3c497` |
| `verifier.md` | `work/auditlite/H/prompts/verifier_prompt.md` | `17a288003448a140b3c61b0bec0b21773eae2ae4efc443720718cd22cefb3b1d` |

To use a newer finder prompt, replace `prompts/finder_a.md` or `prompts/finder_b.md` with the new file. Keep the
first line (`# Defect finder`; the test fake keys on it and tells A from B by the working folder name), the output file name
`defects.json` and its shape (`defects` list with `criteria`, `test`, `quotes`, `answer_sketch`, `description`;
`coverage` object). Then run `python3 test_task_read.py`, and re-measure on tasks with known defects before you
trust the new numbers. Update the sha256 above. The prompts must not contain labels, outside feedback text or expected values:
a test checks that.

## Tests

`python3 automation/task-read/test_task_read.py` uses a fake `claude` script (no model, no network) and prints
`TESTS n/n passed`.
