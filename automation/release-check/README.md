# Release check from a DataOS "with runs" download (version 2)

Written 2026-10-08 (US Eastern), job B12_WITHRUNS. This folder is `final/releasecheck_portable_v1` plus one new script and three small edits to `release_check.py`. For the checks themselves read `README_v1.md` (the v1 README, unchanged) and `README_v1_checks.md`. Needs only Python 3.11 or newer. No pip install, no network, no DataOS login from the script.

## In plain words

This folder holds the release check: a script that reads a DataOS "Dataset with runs" download and writes `release_table.csv`, one row per task, with three yes/no checks and one `call` (HOLD, EVIDENCE MISSING or RELEASE). The manager runbook (`docs/QC-RUNBOOK-manager.md`) says what to do with each value.

**answer-check-v11** is the name of one DataOS review prompt: the question text DataOS gives the review models when it reviews a task. DataOS stores it as saved prompt id 557, and that number is the only thing some options, column names and messages in this folder show (for example `--spec 557`). It is not a pipeline, and you do not run it or pick it. The normal pipeline ("ManualQC automated QC pipeline 4 Reviewers") writes its four Answer Check reviews with a different saved prompt, id 431. The text of answer-check-v11 is stored in DataOS, not in this repo.

What that means for you: check 2 of the release table is built for answer-check-v11 reviews. A download from the normal pipeline has none, so check 2 cannot be computed and `call` reads EVIDENCE MISSING. That is expected. It is not a failure, it is not a reason to send a task back, and nobody has to fix it.

## Get the zip

In DataOS, open the task (or the dataset that holds it) and click the button labelled **Dataset with runs**. The file you
get is a zip. Open it to check: it should hold folders named `rev_<number>__<task id>` containing `evaluations` and
`verifications`. If the file is a spreadsheet, or has no `evaluations` folder, it is the wrong download.

## The three commands

Managers following the manager run sheet do not type these. One command runs the first two of them and writes the table to `qc_release_out/table/release_table.csv`:

```
python qc.py release <zip> [<zip> ...] --out qc_release_out
```

The three commands below are the manual route, for working in this folder directly.

Put the zip(s) in a folder, say `~/b12`. Run from this folder:

```
python3 -I build_export_from_zip.py ~/b12/my_download.zip ~/b12/export
python3 -I run_release.py ~/b12/export ~/b12/export/_pkgs ~/b12/out --dl ~/b12/export/_dl_stub --tasks ~/b12/export/tasks.csv
python3 -I tests/run_tests.py
```

1. The first reads the zip (or several zips, or an already unzipped folder; list them all before the output folder) and writes the export folder. It prints one line: tasks, reviews used, runs, NOP rows (NOP means the empty-answer run). It also writes `build_report.txt` (warnings), `reviews_not_used.csv` (reviews it set aside and why) and `run_mapping.csv` (which evaluation folder became which run id).
2. The second writes `~/b12/out/release_table.csv`: one row per task with `call` (HOLD, EVIDENCE MISSING or RELEASE), `call_with_check1_at_3_attempts`, the three check results and `missing_inputs`.
3. The third is a self test of the folder (30 tests). It prints a `TESTS run= failures= errors= skipped= passed=` line.

Options of the first command: `--spec 557` (the saved prompt id of answer-check-v11, the review prompt check 2 is built for; default 557), `--any-prompt` (use reviews written with any prompt; see below), `--all-revisions` (by default only the highest `rev_` of a task name is used).

## How to read the table

HOLD: at least one check says yes; look at the reason columns, and send the task back only if the rule or the golden answer they name is wrong (in a test on 149 labelled tasks this flag fired on defective and clean tasks about equally often, so it is a prompt to look, not a verdict). EVIDENCE MISSING: no check says yes and one could not be computed; `missing_inputs` says which. RELEASE: all three computed and none said yes. Counts only; no cutoff is applied. With a normal download only check 1 can be computed (see the next section and [SOP 7](../../docs/QC-SOP-first-run.md#7-package-and-hand-off)), so expect HOLD or EVIDENCE MISSING, and RELEASE rarely or never.

On the two test zips (2 tasks) the table reads: one task HOLD (check 1 found a rule that both valid attempts lost and the passing reference run earned, from only 2 attempts), one EVIDENCE MISSING. Neither task has a check 2 or check 3 result. See `out/WITHRUNS.md` for the numbers.

## What the table does not tell you

- **Check 2 (the review-based check) needs reviews written with the review prompt answer-check-v11 (DataOS saved prompt id 557).** The zip files do not carry the saved prompt id. The script recognises the prompt by an exact text match (sha256 of the question text) against `known_prompts.json`, which was built from 17 prompts seen in the stored downloads. In both test zips the reviews were prompt 431 (4 reviews) and prompt 145 (2 reviews); none was answer-check-v11, so check 2 read NOT COMPUTABLE for both tasks. A review with a prompt not in `known_prompts.json` is set aside, never guessed. With `--any-prompt` the older-prompt reviews are fed to check 2 as if they were answer-check-v11; use it only to look, not to release.
- **Check 2 also needs the verifier step** (`--run-verifier`, uses your own `claude` login, about 1.6 calls per task, or `--verifier-out DIR`).
- **Check 3 needs three files that are not in the zip**: `preflight.csv`, `step1.csv` and the review run row. Without them check 3 reads CANT_JUDGE for every task.
- **Check 1 counts a run only if its per-rule file has no judge error.** If the judge model could not be called (for example a missing API key or a spend limit), v2 drops the run and says so in `check1_attempts`. 6 of the 12 evaluation folders in the two test zips had that error in every rule; v1 counted two of them (the two solver runs of one task) as valid attempts.
- **Run status is derived**, not downloaded: PASSED when the reward is 1.0, otherwise FAILED.
- **"Review newer than last package edit" reads NOT KNOWN**: the zip has no timestamps for reviews or for the task.
- **Revisions**: a zip with several `rev_` folders for one task name uses the highest. The task id changes with each revision; reviews and runs of older revisions are not mixed in.
- **A RELEASE is not a statement that the task is sound.** Two checks of three computed, with only two or three attempts, is a thin base.

## Files

`build_export_from_zip.py` (new), `known_prompts.json` (new), `release_check.py` (v1 plus three edits: tasks listed in tasks.csv appear even with no review; runs whose per-rule file shows a judge error are not counted; a package whose grader file check 2 cannot read no longer stops check 2 for the other tasks), `run_release.py`, `make_table.py`, `build_export.py` (v1, still works for the downloader's folders), `vendor/` (unchanged), `tests/` (v1 tests plus `test_build_export_from_zip.py`).
