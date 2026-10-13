# Manager run sheet: approve or send back a task

> **Start here.** For a manager who reviews the tasks QC people hand over. Do "Once" first. The AI read takes about 1 minute a task. Detail: the [SOP](QC-SOP-first-run.md).
> - Batch step 1, download: the "Dataset with runs" zip holds the runs and reviews the tools read.
> - Batch step 2, release table: flags a grading rule that every AI attempt lost.
> - Batch step 3, manager read (50 tasks take 20 to 70 minutes): an AI lists items the QC person must answer.
> - Rules A to E, for each task: DataOS reviews, review table, proof sheet, reader items, HOLD row.
> - Rule F: record Approved or Rejected in the review sheet.

Write the Python command as `python` (python3 on Mac or Linux). SEND BACK means: in the review sheet set `Status` to `Rejected` and write `Verdict: DENY` and a `Why:` line (rule F). A send-back is a delay, not a loss.

Words in angle brackets, like `<rev folder>`, are placeholders to replace with your own value (leave the brackets out), and square brackets, like `[<zip> ...]`, mean the part can repeat. Under each command you get an Example line with made-up names and no brackets: copy the Example line and change the names to yours.

SOP means [`docs/QC-SOP-first-run.md`](QC-SOP-first-run.md). [SOP 6a](QC-SOP-first-run.md#6a-the-gate-every-task-before-any-upload) (the gate, with the golden-answer comparison in step 4b) still applies as today. The [Glossary](#glossary) at the bottom explains ten words: rev folder, task folder, Major, proof, HOLD, EVIDENCE MISSING, Answer Check review, empty-answer (NOP) run, blame reader and golden-answer reader. Oracle, TFRL and Comprehensive Review are in the [README glossary](../README.md#glossary).

## Once

Do the [Once section of the QC person sheet](QC-RUNBOOK-qc-person.md#once). You need:
- git and Python 3.11 or newer
- Claude Code signed in. Use your Claude Max login: [`qc.py`](../qc.py) `manage` is not tested on the team GLM key. No paid API key is involved.
- the repo clone, and `python qc.py update` (it has no names to replace)

Type every `qc.py` command in this sheet inside the clone. The QC person sheet (Once 3) says how to make the folder `C:/qc` and clone into it. If you are offline, `qc.py update` prints `[qc] update stopped, nothing was overwritten.` and exit code 1; `qc.py` still runs on the old version. To skip the update, put `--no-update` before the command word, for example `python qc.py --no-update release ...`.

## For a batch

### Batch step 1. Download from DataOS

The tools read the DataOS runs and reviews, and only the "Dataset with runs" download holds them.

**Do this**
1. In [DataOS](https://data-os.turing.com) open the dataset the QC person named.
2. Click "Dataset with runs". You get one zip per dataset.

**You should see** (a zip such as `ekw-EKW-123_with_runs.zip`)

```
ekw-EKW-123_with_runs.zip
```

**If not**
- **Download again** if the file is a spreadsheet, or has no `evaluations` folder: it is the wrong download.

### Batch step 2. Release table

[`qc.py`](../qc.py) `release` reads the zip and builds a table with one row per task. A row says HOLD when one grading rule was lost by every valid AI attempt but earned by the golden answer (the task's reference answer; rule E says what to do). More: [`automation/release-check/README.md`](../automation/release-check/README.md).

**Run this**

```
python qc.py release <zip> [<zip> ...] --out qc_release_out
# Example (made-up names, use your own):
python qc.py release C:/qc/downloads/ekw-EKW-123_with_runs.zip C:/qc/downloads/ekw-EKW-124_with_runs.zip --out qc_release_out
```

The output goes where you typed `--out`, counted from the folder you are in (the clone). One zip per dataset, so give one zip for each dataset you downloaded (that is the `[<zip> ...]` part). Put each zip path in double quotes if it has spaces; without quotes you get `not a zip or folder:` and the first half of the path (exit code 1). This one command runs the same two scripts (`build_export_from_zip.py` and `run_release.py`) that the release-check README lists as its three commands, so you do not run those yourself.

**You should see** (the line that names the table; a line starting `[qc] HOLD = a grading rule every valid attempt lost: look at that rule` may follow it when a row says HOLD)

```
[qc] table: C:\qc\EKW_QC_pipeline\qc_release_out\table\release_table.csv
```

**Then** open `qc_release_out/table/release_table.csv`: a row per task, and the column `call` = HOLD, EVIDENCE MISSING or RELEASE. Read `call`. The column `call_with_check1_at_3_attempts` (check 1 is the HOLD check described above) only shows what it would be if the rule had to hold in 3 AI attempts.

### Batch step 3. Manager read

[`qc.py`](../qc.py) `manage` makes 1 AI call per task (about 1 minute, one after another; 50 tasks take 20 to 70 minutes). The AI reads the task and its four DataOS reviews and lists items. Each item names a criterion (one test of the grader), a file and quoted words. More: [`automation/manager-read/README.md`](../automation/manager-read/README.md).

**Run this**

```
python qc.py manage <zip> [<zip> ...] --out qc_manage_out
# Example (made-up names, use your own):
python qc.py manage C:/qc/downloads/ekw-EKW-123_with_runs.zip --out qc_manage_out
```

**You should see** (the table line, then a blame reader line, then a reminder that every item needs a written answer)

```
[qc] table: C:\qc\EKW_QC_pipeline\qc_manage_out\manager_summary.csv   items on 3 of 5 tasks, no items on 2, could not run on 0
```

The blame reader line comes between the table line and the reminder. Its numbers change with your batch; for example:

```
[qc] blame reader: HOLD on 1 of 1 tasks (a flagged test with no filled proof row, or no saved blame_reader.json). Column: blame.
```

The exit code is 0, or 2 when the AI could not run on any task. The AI can give different items on a second run of the same task. A rerun is for "could not run" only (rule D2), not for a different answer.
The line reads `[qc] table: ...manager_summary.csv   items on N of M tasks, no items on X, could not run on Y`: N of the M tasks have items, X have none, and the AI could not run on Y.

The table has a `blame` column, made with no AI call from the `blame_reader.json` the QC person saved in the rev folder. A task shows `HOLD (n flagged open)` when the blame reader flagged n tests and their proof rows are not filled, `HOLD (blame reader has not run)` when there is no `blame_reader.json`, and `no flagged tests` or `n flagged (all answered)` otherwise. Copy `blame_reader.json` and `zero_pass_proof.csv` into the rev folder before you run `manage` (rule C). `--blame` (`python qc.py manage <zip> --blame --out qc_manage_out`) asks the model now, 1 AI call per zero-pass test (40 per task at most), and saves each block as `qc_manage_out/manager/<task id>/blame_reader_report.md`; `--no-blame` leaves the column out. Of the 42 tasks it flagged across the 151 tested, 34 were tasks TFRL (the outside QC team that reviews finished tasks) rejected (SOP 5a has the numbers and the limits; the 151 tasks tested for the blame reader are a different set from the 149 tasks in the table at the end of this sheet).

**Where to read first.** Two checks together say which tasks to read first: the blame reader (the `blame` column) and a read of the task with TFRL's own review prompt by an AI (`qc.py tfrl-read`, which the QC person ran in step 2 and handed over as `tfrl_replay.json` next to `blame_reader.json`). Copy both into the rev folder before you run `manage` (rule C). When at least one rev folder holds `tfrl_replay.json`, `manage` adds a `look_first` column and one line that names the tasks both checks flagged. It makes no AI call and needs no extra option:

```
python qc.py manage <zip> [<zip> ...] --out qc_manage_out
# Example (made-up names, use your own):
python qc.py manage C:/qc/downloads/ekw-EKW-123_with_runs.zip --out qc_manage_out
```

The column reads `both flagged`, `neither flagged`, `one flagged` or `no pointer (...)` (the blame reader has not run, or there is no `tfrl_replay.json` for that task: ask the QC person to run `python qc.py tfrl-read <rev folder>`). `both flagged` means read that task first. It is a pointer, not a rule, and it does not send a task back or pass one: among 105 older tasks TFRL had rated, TFRL rejected 25 of 40 that both checks flagged and 4 of 23 that neither did, and on SVC tasks both flagged was mostly approved (14 of 24), so never send an SVC task back for it. There is no such pointer before DataOS (step 1), because both checks need the AI attempts DataOS makes. Numbers are in "What the numbers say" below.

Per task you get `qc_manage_out/manager/<task id>/manager_read_report.md`. The unzipped downloads, with the rev folders, are in `qc_manage_out/extracted/<zip name>/`.

**If not**
- **Go to rule D2** if `could not run on` shows a number above 0: those tasks have no usable report.

### Where the files are

An example with made-up names. In this sheet your task id is the number after the double underscore in the rev folder name (`rev_11__48213` is task id `48213`). The QC person sheet (step 3b) uses "task id" for the task's folder name, such as `SVC-PC-14-1-0`; the two are different.

```
qc_manage_out/                          <- made by batch step 3
  manager_summary.csv                   <- one row per task
  manager/
    48213/                              <- the task id
      manager_read_report.md            <- rule D2 reads this
  extracted/
    ekw-EKW-123_with_runs/            <- the zip name, without .zip
      EKW-123/                          <- the task name
        rev_9__47102/                   <- an older version: ignore it
        rev_11__48213/                  <- THE REV FOLDER: the biggest number is the newest
          zero_pass_proof.csv           <- rule C: you copy the QC person's file here
          golden_reader.json            <- rule C, EKW row only: you copy this here too
          blame_reader.json             <- rule C: you copy this here too
          task_files/instruction.md     <- rule C: the quoted sentences must be in here
          evaluations/                  <- the DataOS runs
          verifications/                <- the DataOS reviews
```

What the QC person sends you is one Document or Drive folder, linked in the row of the review sheet:

```
(the Doc or folder linked in the row)
  verify-review-findings-result.md      <- rule B (or the words "DataOS listed no problems")
  zero_pass_proof.csv                   <- rule C (or the words "no proof required")
  golden_reader.json                    <- rule C, EKW row only
  blame_reader.json                     <- rule C
  read_EKW-123/
    task_read_report.md                 <- rule D1
    reader_answers.md                   <- rule D1
    manager_answers.md                  <- rule D2 (written after you send the list)
```

## For each task

Check rules A to E, then record the result with rule F. **A ends the task at once** (a rerun makes the rest stale). For B to E check all, and write every reason in the `Why:` line, naming the rule letter and the file.

| Rule | What to look at | SEND BACK when |
|---|---|---|
| [A. DataOS](#a-dataos) | the four "Answer Check" reviews in [DataOS](https://data-os.turing.com) (`overall_verdict` in each JSON) and the run list | any Major; fewer than four finished reviews; either of the two oracle runs below full marks; an empty-answer (NOP) run above zero |
| [B. Review table](#b-review-table) | `verify-review-findings-result.md` from the QC person ([SOP 6c](QC-SOP-first-run.md#6c-after-the-dataos-pipeline-check-the-list-before-you-change-anything)) | no table when the reviews list problems; a table that does not match the four latest reviews; an open REAL DEFECT row; a `Package check` line naming a missing criterion; a CANNOT SETTLE row, unless the files show its gap is no defect |
| [C. Proof sheet](#c-proof-sheet) | `zero_pass_proof.csv` ([SOP 5a](QC-SOP-first-run.md#5a-qc-person-pre-check-before-you-run-the-dataos-pipeline)), on an EKW row also `golden_reader.json`, and the result of [`qc.py`](../qc.py) `proof check` | any `PROOF: HOLD`, or no `golden_reader.json` on an EKW row; a quoted sentence that does not ask for the test; a golden-answer place that does not exist |
| [D. Reader items](#d-reader-items) | `task_read_report.md` with `reader_answers.md`; [`manager_read_report.md`](../automation/manager-read/README.md) with `manager_answers.md` | no report; FLAGGED with no answers; a missing or unbelievable answer; no answers yet to the manager read's list |
| [E. HOLD row](#e-hold-row) | `release_table.csv` ([README](../automation/release-check/README.md)): columns `call`, `check1_rules`, `check1_attempts` | only when the rule or the golden answer it names is wrong; a hard rule is no reason |
| [F. Approve or deny](#f-approve-or-deny-in-the-review-sheet) | the task's row in the [review sheet](https://docs.google.com/spreadsheets/d/1F02SBuSIbqSA5jfM19Wm-u7rSknUnKU7mYe2aYOVHQc/edit) | (not a check: it records the result of A to E) |

### A. DataOS

The pipeline has already judged the task. You read its verdict; you do not run the four reviews again. Your own checks are rules B to E.

**Open this**

In [DataOS](https://data-os.turing.com) open the four "Answer Check" reviews (on the task page, then Verifications, then Comprehensive Review) and read `overall_verdict` in each JSON. Also open the run list. The four reviews come from the pipeline "ManualQC automated QC pipeline 4 Reviewers", version 8 (DataOS pipeline 141; its review prompt is saved as id 431). Reviews from the retired "NO CLAUDE" pipeline or the older "ManualQC automated QC pipeline" do not count ([SOP 6b](QC-SOP-first-run.md#6b-the-dataos-pipeline)).

**You should see** (once per review)

```
overall_verdict: valid
```

`invalid` or `reject` = Major. `needs_revision` with any entry in the review's `findings` list whose `severity` is `major` = Major. `valid`, or `needs_revision` with only minor findings = none. The green PASSED badge is not the verdict.

**If not**
- **SEND BACK** for any Major, even when the review table calls that problem NOT A DEFECT. If the same Major returns after two reruns, send the review and table row to your lead; do not approve.
- **SEND BACK** so DataOS is rerun if fewer than four reviews finished. (The manager read report header says "Answer Check reviews read: N of 4".)
- **SEND BACK** if either of the two oracle runs is below full marks, or the empty-answer run is above zero. (The oracle run submits the golden answer, so it must score full marks, and you need at least two such runs. The empty-answer run, called the NOP run in DataOS, submits nothing, so it must score zero.)
- **Go on** if all four reviews have no Major and the runs are right.

### B. Review table

The QC person checked each problem the DataOS reviews listed against the real files ([SOP 6c](QC-SOP-first-run.md#6c-after-the-dataos-pipeline-check-the-list-before-you-change-anything)). You check that this was done. The file is `verify-review-findings-result.md`.

**You should see** (one row of the table)

```
| P1 | NOT A DEFECT | - | v7 already accepts both spellings | tests/verifier.json:41 | none |
```

**If not**
- **Go on** if the four reviews list no problems at all (minor ones count too): no table is fine.
- **SEND BACK** otherwise for: no table; a table whose problems do not match the four latest reviews; an open REAL DEFECT row; a `Package check` line naming a missing criterion.
- **SEND BACK** for a CANNOT SETTLE row, naming the gap it names, unless the files show it is no defect. Read the gap first.

### C. Proof sheet

The QC person writes a proof for each heavy test (weight at least 0.05 of the task total) that every AI attempt failed. TFRL reads those tasks first, so you check the proof ([SOP 5a](QC-SOP-first-run.md#5a-qc-person-pre-check-before-you-run-the-dataos-pipeline)) with [`qc.py`](../qc.py) `proof check`. On an EKW row the list also holds every test the golden-answer reader flagged HOLD, whatever its weight.

**Do this first**
1. Take `zero_pass_proof.csv` from the Doc or folder linked in the row and copy it into the rev folder: `qc_manage_out/extracted/<zip name>/<task name>/rev_<n>__<id>/`, next to the folder `evaluations`. Batch step 3 made these folders (see the tree above).
2. On an EKW row, also copy `golden_reader.json` into the rev folder.
3. Also copy `blame_reader.json` into the rev folder.

**Run this**

```
python qc.py proof check <rev folder>
# Example (made-up names, use your own):
python qc.py proof check qc_manage_out/extracted/ekw-EKW-123_with_runs/EKW-123/rev_11__48213
```

The check makes no AI call. It reads the answers of the blame reader saved in `blame_reader.json`: a test it flagged needs a filled row, and with no `blame_reader.json` the check ends `PROOF: HOLD (the blame reader has not run on this task)`. The list holds the heavy tests, every test the blame reader flagged, and on an EKW row also every test the golden-answer reader flagged HOLD, whatever its weight. An SVC row only prints `golden-answer reader: skipped`.

**You should see** (the last line; above it is one line per listed test, `OK:` or the fault)

```
PROOF: COMPLETE
```

**Then**
- **Go on** if `no proof required` is printed above `PROOF: COMPLETE`: no test needs a proof.
- **Open `task_files/instruction.md`** in the rev folder if `PROOF: COMPLETE` comes with rows. Each quoted sentence must really ask for the test, and the golden-answer place must exist. Else SEND BACK.

**If not**
- **SEND BACK** so DataOS is rerun if the last line is `PROOF: HOLD (only n of m AI attempts could be scored)`. With fewer than 2 scored AI attempts nobody can tell which tests every attempt failed.
- **SEND BACK** if a `does not exist yet` line is printed and the QC person's Doc or folder has no `zero_pass_proof.csv`: the QC person runs `proof init` and fills the open rows. If the file is there, put it inside the rev folder itself (see the tree) and run the check again.
- **Ask first** if a line starts `MISSING ROW` (and `does not exist yet` is not printed): ask which DataOS run the proof came from. If it is the run you downloaded, SEND BACK. If it is an older run, ask for a proof made from the run you are checking.
- **SEND BACK** for any other `PROOF: HOLD (n open)`: the QC person fills the open rows.
- **SEND BACK** on a row with no `blame_reader.json`: `proof check` ends `PROOF: HOLD (the blame reader has not run on this task)`. The QC person runs `proof init` again; it asks the blame reader once and keeps the rows already there.
- **SEND BACK** on an EKW row with no `golden_reader.json`: `proof check` ends `PROOF: HOLD (the golden-answer reader has not run on this download)`. The QC person runs `proof init` again; it asks the reader once and keeps the rows already there.
- **Run the check again with `--tab SVC`** if an SVC row says the task files do not say the kind and treats it as EKW. Otherwise the row would look like an EKW row with no `golden_reader.json`. Example (made-up names): `python qc.py proof check C:/qc/qc_manage_out/extracted/batch12/SVC-PC-14-1-0/rev_2__171703 --tab SVC`
- **Check the folder, then SEND BACK** if you see `cannot run`: give the check the rev folder (the one named `rev_11__48213`), not its parent. Still failing: SEND BACK.

### D. Reader items

Two AI readers list items: specific claims, each with a file and quoted words. Every item needs a written answer from the QC person. You check the answers. Two readers, two answer files:

| Reader | Who ran it | Report | Answer file |
|---|---|---|---|
| D1, task read | the QC person (step 2 of their sheet) | `task_read_report.md` | `reader_answers.md` |
| D2, manager read | you (batch step 3) | `manager_read_report.md` | `manager_answers.md` |

Both answer files, and the D1 report, are in the QC person's `read_<task name>/` folder. Your D2 report is in `qc_manage_out/manager/<task id>/`.

**D1. Task read**

Open `task_read_report.md` and `reader_answers.md` in `read_<task name>/`. Every numbered item needs an answer.

**If not**
- **SEND BACK** if there is no report.
- **SEND BACK** if the report says FLAGGED and the answers are missing.
- **Go on** if every numbered item has an answer.

**D2. Manager read**

Open `qc_manage_out/manager/<task id>/manager_read_report.md`. The first lines of the report say `Answer Check reviews read: N of 4`. In `manager_summary.csv` the column `result` says which of three things happened.

**You should see** (one row of `manager_summary.csv`)

```
48213,EKW-123,11,items,C:\qc\EKW_QC_pipeline\qc_manage_out\manager\48213\manager_read_report.md
```

**If not**
- **Run it once more** if the result is `could not run` or the report says COULD NOT JUDGE. If the second run fails too, do not approve: send your lead the last 5 lines of the report.
- **Send the whole list to the QC person** if the result is `items`. Either upload `manager_read_report.md` to the row's Doc or folder and paste its link in the comment, or paste the item list under the `Why:` line. If you cannot edit the QC person's Doc or folder, use the second way: paste the item list under the `Why:` line. The QC person answers in `manager_answers.md`. If there is no answer yet: SEND BACK with the list.
- **Go on** to rule E if the result is `no items`. "No items" does not mean the task is clean.

To run the reader once more, use [`manager_read.py`](../automation/manager-read/manager_read.py), the script behind [`qc.py`](../qc.py) `manage`:

```
python automation/manager-read/manager_read.py <rev folder> --out qc_manage_rerun/<task id>
# Example (made-up names, use your own):
python automation/manager-read/manager_read.py qc_manage_out/extracted/ekw-EKW-123_with_runs/EKW-123/rev_11__48213 --out qc_manage_rerun/48213
```

**Check every answer** (D1 and D2)
- **FIXED:** open the file. The quoted words must be changed.
- **NOT A DEFECT:** the sentence must use the quoted words and make sense against the file.
- **SEND BACK** for a missing or unbelievable answer. That is enough. This replaces the [SOP 7](QC-SOP-first-run.md#7-package-and-hand-off) bar (send back only when you can show a Major) for rule D.

### E. HOLD row

HOLD means one grading rule was lost by every valid AI attempt but earned by the golden answer. It is a prompt to look, not a verdict ([README](../automation/release-check/README.md)).

**Open this**

Open `qc_release_out/table/release_table.csv` in a spreadsheet. Find the row whose `task_id` is the id in the rev folder name: for `rev_11__48213` it is `48213`. (The column `sheet_name` shows the task name, `EKW-123`, so you can double-check the row.)

**You should see** (the cells of that row)

```
task_id=48213  sheet_name=EKW-123  call=HOLD  check1_attempts=2 valid  check1_rules=summary_xlsx/v3-total-revenue w=0.5
```

**If not**
- **Go on** if `call` is RELEASE. Expect to see it rarely or never today: only check 1 can be computed from a normal download ([SOP 7](QC-SOP-first-run.md#7-package-and-hand-off)).
- **Go on** if `call` is EVIDENCE MISSING. It is not a failure: a check could not be computed from the download (the column `missing_inputs` says which). The reasons are check 2 and check 3. Check 2 only reads reviews written with the review prompt named answer-check-v11 (DataOS saved prompt id 557); the normal pipeline does not run that prompt, so a normal download always shows it. Check 3 needs files that are not in the zip. answer-check-v11 is not a pipeline, and nobody has to run it.
- **Look at the rule** if `call` is HOLD. Read `check1_rules` (the rule every valid attempt lost, with its weight: `w=0.5`) and `check1_attempts` (how many attempts counted). Find the rule by its name in the task's `tests` folder (inside `task_files`) and read it next to `instruction.md` and the golden answer in `solution/`.
- **SEND BACK** only if the rule or the golden answer is wrong. **Go on** if the rule is just hard: a hard rule is no reason.

### F. Approve or deny in the review sheet

Use the [review sheet](https://docs.google.com/spreadsheets/d/1F02SBuSIbqSA5jfM19Wm-u7rSknUnKU7mYe2aYOVHQc/edit), tab EKW or SVC (your lead posts a new copy each weekend). Find the task's row and set `Claimed By (Reviewer)` to your name. While you review, set `Status` to `Checking`. If another name is already there, ask that person before you take the row.

| Situation | Set `Status` to | Write in `Comments (Feedback)` |
|---|---|---|
| None of A to E sent it back and nothing in "After TFRL names a defect" below applies | `Approved` | `Verdict: APPROVE`, then a line `Why:` with one sentence |
| Any rule sent it back | `Rejected` (never `Deny Review`) | `Verdict: DENY`, then a line `Why:` naming each failed rule letter with the file or quote, and the link to `manager_read_report.md` when rule D applies |
| You cannot decide (rule D2 failed twice, or the oracle evidence is missing) | leave it as `Checking` | `Verdict: CAN'T JUDGE YET`, then a `Why:` line |

Example of a `Comments (Feedback)` text for a send-back (made-up details):

```
Verdict: DENY
Why: Rule C: PROOF: HOLD (1 open) in zero_pass_proof.csv. Rule D2: item 2 of manager_read_report.md has no answer.
```

**A row the QC person set to `Rework Addressed`** starts again at rule A on the newest download. Run batch steps 1 to 3 again, check every earlier item in the new files, then come back to this rule F, and replace the old comment text.

The QC person adds an approved task to the consolidated sheet and sets `Added to Consolidated Sheet` to `Yes` ([SOP 7](QC-SOP-first-run.md#7-package-and-hand-off)). Never send a task to TFRL yourself: Khiem Doan builds the batches and sends them ([SOP 7](QC-SOP-first-run.md#7-package-and-hand-off)).

## What the numbers say (small, selected sets; early and unaudited; read as rough)

TP = bad task flagged, FN = bad task missed, FP = good task flagged, TN = good task passed. A bad task is one TFRL rejected (rows 1 and 2) or the AI audit called defective (rows 3 and 4).

| Against | Reader | TP | FN | FP | TN | Bad tasks flagged | Good tasks flagged |
|---|---|---|---|---|---|---|---|
| TFRL verdict, 149 tasks | manager reader | 48 | 19 | 36 | 46 | 72% (48 of 67) | 44% (36 of 82) |
| TFRL verdict, 95 tasks | either reader (the task read's AI finders, or the manager read) | 29 | 10 | 28 | 28 | 74% (29 of 39) | 50% (28 of 56) |
| AI audit label, 95 tasks (UNAUDITED) | manager reader | 31 | 15 | 18 | 31 | 67% (31 of 46) | 37% (18 of 49) |
| AI audit label, 95 tasks (UNAUDITED) | either reader (the task read's AI finders, or the manager read) | 35 | 11 | 22 | 27 | 76% (35 of 46) | 45% (22 of 49) |

- Rows 1 and 2 use different task sets and different readers. Compare numbers only within one row. The manager-read README quotes other counts on the same 95 tasks (the manager reader alone); do not mix them with row 2.
- Row 1 (rule D2 alone; 149 stored tasks, not a random draw): TFRL rejected 67 and approved 82. The manager reader had an item on 48 of the 67 rejected and 36 of the 82 approved.
- It had items on 84 (56%); of the 65 without items, 46 (71%) had no Major from TFRL, against 82 of 149 (55%) overall. Rules A, B, C, D1 and E are not in these counts.
- Expect many send-backs: they are a delay, not a loss. A written NOT A DEFECT answer with one sentence that uses the quoted words is how a good task passes.
- Where to read first (both checks, `look_first`, from `qc.py tfrl-read` and the blame reader; 105 older tasks TFRL had rated: 47 rejected, 58 approved; 96 of them were not in a numbered batch, so TFRL's standard then may differ, and 10 of the 47 rejected were our own reviews): both the blame reader and the TFRL review read flagged 40 tasks, TFRL had rejected 25 of them (62 percent, range 47 to 76); neither flagged 23, 4 rejected (17 percent, range 7 to 37); one check alone 13 of 31 (42 percent) and 5 of 11 (45 percent), no better than the 45 percent for all 105. By task kind (seen after the data was in): EKW both flagged 15 of 16 rejected, neither 3 of 13; SVC both flagged 10 of 24 rejected (14 approved), neither 1 of 10. The readings were locked before the ratings were opened and an independent recount reproduced every count. The same pattern on the first 151 tasks (all 19 tasks flagged by both were rejected) did not hold as a rule here, so it points at a task and never blocks one.
- The AI audit label shows no detectable link to TFRL's verdict (audit-defective rejected 42 of 88, audit-clean 25 of 61; wide range): trust the TFRL rows.

## After TFRL names a defect

Before the next send, check every task you cleared in that batch for the same kind of defect. Send back any that have it.

## Glossary

- **rev folder:** One saved version of one task inside a "Dataset with runs" download. Its name looks like `rev_11__48213`: version 11 of the task whose id is 48213. A bigger number is newer, so `rev_11` is newer than `rev_9`; always use the biggest. It holds `task_files` (the task itself), `evaluations` (the DataOS runs) and `verifications` (the DataOS reviews).
- **task folder:** The folder that holds one task: `task.toml`, `instruction.md`, `tests/`, `solution/` and `environment/`. Its name is the task name, for example `EKW-123`. In a DataOS download it is the `task_files` folder inside the rev folder.
- **Major:** A problem that makes a correct answer lose credit, or a wrong or empty answer gain credit. One Major sends a task back. Smaller problems do not.
- **proof:** A short written reason, kept in `zero_pass_proof.csv`, that a hard test is fair. A task needs one for each heavy test (weight at least 0.05 of the task total) that every AI attempt failed, and on an EKW task for each test the golden-answer reader flags HOLD. For each such test it gives the instruction sentence that asks for it, where the golden answer (the task's reference answer) meets it, and why a different valid answer would also pass.
- **HOLD:** A tool's word for "stop and look". In `release_table.csv` it means one grading rule was lost by every valid AI attempt but earned by the golden answer: look at that rule. At the end of `proof check`, `PROOF: HOLD` means the proof is not finished. For example `PROOF: HOLD (2 open)` means 2 rows are still missing or wrong. On an EKW task the golden-answer reader also flags a test HOLD when the golden answer, and not the instruction, seems to be what the test asks for.
- **EVIDENCE MISSING:** In `release_table.csv`, the tool could not work out one of its checks from the download. It is not a failure.
- **Answer Check review:** One of the four AI reviews that the DataOS pipeline "ManualQC automated QC pipeline 4 Reviewers" writes on a task (DataOS pipeline 141, version 8, saved review prompt id 431). You find them on the task page under Verifications, then Comprehensive Review. Each has an `overall_verdict`. One Major in any of the four sends the task back.
- **empty-answer (NOP) run:** A DataOS run that submits nothing. It must score zero. The golden-answer run is the oracle run; it must score full marks.
- **blame reader:** An AI step that `proof init` runs. For each test that every AI attempt failed, it says who was at fault: the AI solver, the test, both, or it cannot tell. It saves the answer in `blame_reader.json` ([SOP 5a](QC-SOP-first-run.md#5a-qc-person-pre-check-before-you-run-the-dataos-pipeline)).
- **golden-answer reader:** An AI step that `proof init` runs on an EKW task only. It flags a test HOLD when the golden answer, and not the instruction, seems to be what the test asks for. It saves the answer in `golden_reader.json`.
