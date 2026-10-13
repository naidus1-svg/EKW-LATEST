# QC person run sheet

> **Start here.** For a QC person clearing one task. Do "Once" first, then steps 1 to 8; the AI steps take minutes. Detail: the [SOP](QC-SOP-first-run.md).
> 1. Pre-check by hand: these are the problems TFRL (the outside QC team that reviews finished tasks) rejects tasks for.
> 2. Task read (about 2 minutes): an AI lists defects, each with a quote you can check.
> 3. Script checks: scripts flag mechanical mistakes before the paid DataOS run.
> 4. DataOS (about 3 USD a run): five runs and four reviews; any Major sends the task back.
> 5. Review table (30 to 60 seconds a problem): tells real problems from wrong review items.
> 6. Proof sheet: shows that each heavy test every AI attempt failed is fair; on EKW an AI reader adds rows.
> 7. Hand over to your manager. Step 8, if your row comes back Rejected: answer each item, redo.

Do the steps in order. Type each command on one line, then press Enter. Write the Python command as `python` (python3 on Mac or Linux). Put a path in double quotes if it has spaces.

Words in angle brackets, like `<task folder>`, are placeholders to replace with your own value (leave the brackets out), and square brackets, like `[<zip> ...]`, mean the part can repeat. Under each command you get an Example line with made-up names and no brackets: copy the Example line and change the names to yours.

SOP means [`docs/QC-SOP-first-run.md`](QC-SOP-first-run.md), the detail behind each step. The [Glossary](#glossary) at the bottom explains six words: rev folder, task folder, Major, proof, HOLD and EVIDENCE MISSING.

## Once

Do this one time. After that only "For every task" repeats.

### Once 1. Install git and Python, and ask for access

git downloads the team's tools and Python runs them. Ask your lead for three accesses: the GitHub repo, DataOS ([data-os.turing.com](https://data-os.turing.com), under the Andrew_team project, as SOP section 1 says) and the review sheet. SOP section 1 also lists edit access to the SVC QC Tracker, the sheet tasks are picked from (SOP section 2): ask your lead whether you need it. The SOP sends access questions to "the QC team Slack channel" and the files never name it, so ask your lead for its name.

**Run this**

```
python --version
python -m pip install openpyxl python-docx pdfplumber pypdf
python -m pip install "markitdown[docx,xlsx,pdf,pptx]"
python -c "import openpyxl, docx, pdfplumber, pypdf"
```

The two pip lines install the packages the readers use to open Excel, Word and PDF files. Without them the report covers less. The second pip line (markitdown) is needed by `proof init` on an EKW task (step 6e); installing it now saves a stop later. A third package, `harbor-rewardkit`, is needed only by the oracle command in step 1; its install line is there. On Windows, if `pip` is not found, type `py -m pip install ...` instead (same words after `pip`).

**You should see**

```
Python 3.12.4
```

That is the first command; it must print 3.11 or higher. The last command prints nothing. No output means success. An error means one package is missing.

**If not**
- **Go on** once `python --version` prints 3.11 or higher. Install Python 3.11 or newer if it prints less.
- **Fix first** if `python` is not found: on Windows type `py` instead; on a Mac or Linux use `python3`. If none of the three is found, Python is not installed: install it (your lead gives the download link), then open a new terminal window and try again.
- **Fix first** if the last command prints an error: the install did not finish. Run the pip line again.

### Once 2. Install Claude Code and sign in

The AI steps (task read, review table) call the `claude` command, so it must be signed in. Install Claude Code (the link your lead gives you), then pick ONE way to sign in; you do not need both. After you sign in, check that the `claude` command works from a normal terminal window: type `claude -p hello` and press Enter. Any short reply from the AI means it works. An error, or a request to sign in, means it does not: `qc.py read` and `qc.py review` need this to work, not the `claude` prompt.

**Option A: Claude Max login**

```
claude
```

You should see a prompt open. Then type `/exit`.

**Option B: team GLM key** (GLM is the AI model this key gives you access to, used in place of a Claude Max login; use it only if you have no Claude Max login; your lead gives you the key)

1. Run this once, with your key in place of `PASTE_YOUR_KEY_HERE`, then open a new PowerShell window:

```
setx GLM_API_KEY "PASTE_YOUR_KEY_HERE"
```

2. After Once 3, in that new PowerShell window, go to the clone folder and run [`docs/glm-env.ps1`](glm-env.ps1) before every [`qc.py`](../qc.py) `read` command:

```
. .\docs\glm-env.ps1
```

The line starts with a dot, then a space, then `.\docs\glm-env.ps1`: the first dot is part of the command. The settings last for that window only (SOP section 1), so run this line again in every new PowerShell window.

**You should see**

```
claude now uses the team GLM gateway in this window.
```

**If not**
- **Paste the lines instead** if PowerShell blocks the script: the [GLM section of the SOP](QC-SOP-first-run.md#using-glm-with-the-claude-command-qcpy-read) has lines to paste.

Know this about GLM: it is slow. One task read takes about 30 minutes instead of 2, and `qc.py manage` is not tested on GLM. The only test on record is one `qc.py read` (SOP section 1); the files say nothing about `review`, `siblings` or `proof` on GLM. `docs/glm-env.ps1` is the only GLM script in the repo and it is for PowerShell, so on a Mac or Linux ask your lead.

### Once 3. Clone the repo and update it

[`qc.py`](../qc.py) is the one command for most steps. `update` pulls the newest version of the repo, so you never run old tools. Every other `qc.py` command does this first too.

Make a new empty folder `C:/qc` first (in File Explorer, or type `mkdir C:/qc`), then go into it with `cd C:/qc`. The examples in this sheet use `C:/qc`, and the clone lands inside it as `C:/qc/EKW_QC_pipeline`.

**Run this**

```
cd C:/qc
git clone https://github.com/turing-genai-apps/EKW_QC_pipeline
cd EKW_QC_pipeline
python qc.py update
```

`python qc.py update` has no names to replace. Type every `qc.py` command in this sheet inside this folder (`C:/qc/EKW_QC_pipeline`). If Python says `can't open file` and names `qc.py`, you are in the wrong folder: type `cd C:/qc/EKW_QC_pipeline` and run the command again.

**You should see**

```
[qc] already up to date.
```

or `[qc] updated. What changed:` and a list of changes. `update` ends with exit code 0 when the repo is current and exit code 1 when it could not update.

**If not**
- **Sign in** if git asks you to: use the GitHub account your lead gave access to.
- **STOP** if git asks for a password: ask your lead for a token (do not type your account password).
- **Go on** if you see `[qc] update stopped, nothing was overwritten.` (exit code 1; it is followed by a reason such as a git error, which is what you see offline): qc.py still runs, on the old version. Copy that line to your lead.
- **Clone first** if you see `[qc] this folder is not a git clone, so I cannot update. Clone the repo once, then run qc.py from the clone.` (exit code 1): you are not in the cloned folder. Do the `git clone` above and run `qc.py` from the clone.
- **Offline:** every other `qc.py` command also tries to update first. To skip that, put `--no-update` BEFORE the command word, for example `python qc.py --no-update read C:/qc/tasks/EKW-123 --out read_EKW-123`. After the command word (`read --no-update`) it fails with `unrecognized arguments`.
- **Move the clone** if you are on Windows and see a "path too long" error: use a short folder such as C:/qc.

## For every task

Do steps 1 to 8 in order for each task.

### 1. Pre-check

A read-through of your task against the lists in the [SOP](QC-SOP-first-run.md). The lists are built from the Major problems TFRL names. A step is done only when you can point at the line that proves it.

**Where the task folder comes from.** The task folder (the folder that holds `instruction.md`; see the Glossary) is the built package. For an SVC task SOP section 3 says to pull it from the GitHub releases it lists. For an EKW task use the EKW part of SOP section 3. If you picked the task from the SVC QC Tracker, SOP section 2 says how.

If you picked the task from the SVC QC Tracker, claim it first: write your name in column AH and the time in column AI of its row (SOP section 2: "Claim it before you touch anything").

**Do this**
1. Do [section 5a](QC-SOP-first-run.md#5a-qc-person-pre-check-before-you-run-the-dataos-pipeline) items 3 to 12.
2. Then do [section 6a (the gate)](QC-SOP-first-run.md#6a-the-gate-every-task-before-any-upload) steps 1 to 7 in order. Step 8 there (the gated batch zip) is your lead's. You zip your own task in step 4 below.
3. Write each answer in a notes file. Item 0 is your step 2. Items 1 and 2 (oracle, empty answer) are answered in step 4.

Section 6a step 1 asks for "Checks A to E". Check A (content audit) has no command: SOP section 3 describes it as a person or an AI applying a written method. Checks B to E are the script checks in step 3 below: 3a writes B to E, and 3b writes C, D and E only (it has no B). The same 6a step 1 runs `pre_submit_gate.py`; its arguments, copied from the tool's help, are:

```
python deterministic-checks/pre_submit_gate.py --root <package folder> --out <results folder>
# Example (made-up names, use your own):
python deterministic-checks/pre_submit_gate.py --root C:/qc/tasks --out C:/qc/gate_out
```

`--task <task id>` limits it to one task.

The oracle step (6a step 5) uses [`judge_emulate.py`](../svc-pc-pipeline/tools/judge_emulate.py). Its own notes give the usage `oracle <task>`, where `<task>` can be the full path of the task folder, and `--runs N` grades N independent times. Two runs, as the SOP asks:

```
python svc-pc-pipeline/tools/judge_emulate.py oracle <task folder> --runs 2
# Example (made-up names, use your own):
python svc-pc-pipeline/tools/judge_emulate.py oracle C:/qc/tasks/SVC-PC-14-1-0 --runs 2
```

It prints a result with a `total_reward`; the SOP wants 1.0 on both runs. The tool imports `rewardkit`, so install the package once (the tool's notes name version 0.2.0):

```
python -m pip install "harbor-rewardkit==0.2.0"
```

If it stops with `ERROR: harbor-rewardkit not importable`, the install did not reach the `python` you ran: use the same `python` for the pip line and for the tool. If it stops on another Python error about a missing module, send your lead the last 5 lines.

Three other tools in 6a steps 1 to 7 take these arguments, copied from each tool's own notes. Each `<package folder>` is one task folder (it holds `tests/`, `environment/` and `solution/`).

The pre-filter (6a step 1). Exit code 0 means clean or warnings only; 1 means a HARD line, which you fix before you go on:

```
python svc-pc-pipeline/tools/svc_prefilter.py <package folder> [<package folder> ...]
# Example (made-up names, use your own):
python svc-pc-pipeline/tools/svc_prefilter.py C:/qc/tasks/SVC-PC-14-1-0
```

The coverage trace (6a step 3). `list` prints one numbered line per requirement in `instruction.md`, each with an id and a short hash. `check` verifies a map file that covers every one of them. The map is a tab-separated file, one row per requirement: `<id>`, `<hash>`, the criterion names (comma-separated) or `-`, and a note. A `-` row needs a note that starts `NOT-A-REQUIREMENT:`. Exit code 0 is clean, 1 means uncovered requirements, 2 means a malformed map:

```
python svc-pc-pipeline/tools/svc_coverage_trace.py list <package folder>
python svc-pc-pipeline/tools/svc_coverage_trace.py check <package folder> <map file>
# Example (made-up names, use your own):
python svc-pc-pipeline/tools/svc_coverage_trace.py list C:/qc/tasks/SVC-PC-14-1-0
python svc-pc-pipeline/tools/svc_coverage_trace.py check C:/qc/tasks/SVC-PC-14-1-0 C:/qc/map_SVC-PC-14-1-0.tsv
```

The re-grade of real DataOS answers (6a step 6, on a resubmission only). `<task>` is the task name as it appears in the return zip's folder names, `--zip` is the return zip from DataOS (the one that holds the `evaluations` folder) and `--rubric` is your current, fixed `tests` folder. `reproduce` only reads; `regrade` writes `<task>.regrade.json` into `--out` (default: the folder you are in):

```
python svc-pc-pipeline/tools/svc_eval_regrade.py reproduce <task> --zip <return zip>
python svc-pc-pipeline/tools/svc_eval_regrade.py regrade <task> --zip <return zip> --rubric <tests folder> --out <results folder>
# Example (made-up names, use your own):
python svc-pc-pipeline/tools/svc_eval_regrade.py reproduce SVC-PC-14-1-0 --zip C:/qc/SVC-PC-14-1-0_with_runs.zip
python svc-pc-pipeline/tools/svc_eval_regrade.py regrade SVC-PC-14-1-0 --zip C:/qc/SVC-PC-14-1-0_with_runs.zip --rubric C:/qc/tasks/SVC-PC-14-1-0/tests --out C:/qc/regrade_out
```

Who writes the coverage map is not stated in the files; if you do not know, ask your lead for that one thing.

**You should see** (one line of your notes file, as an example)

```
Item 3, files: all 4 files that instruction.md names are in the package. I opened each judge group's file list.
```

**If not**
- **Ask your lead before you go on** if a tool needs arguments you do not have.

### 2. Task read

[`qc.py`](../qc.py) sends your task to an AI reader (four AI calls, about 2 minutes). The reader lists specific defects. Each one names a file and quoted words, so you can check it in a minute. More: [`automation/task-read/README.md`](../automation/task-read/README.md).

The task folder is the folder you were given for QC: it holds `instruction.md`. In a DataOS download it is `task_files` inside `rev_<n>__<id>`.

**Run this**

```
python qc.py read <task folder> --out read_<task name>
# Example (made-up names, use your own):
python qc.py read C:/qc/tasks/EKW-123 --out read_EKW-123
```

**You should see** (the last line)

```
NOT FLAGGED - report: read_EKW-123/task_read_report.md
```

The last line is `FLAGGED - report: <path>` or `NOT FLAGGED - report: <path>`. The report is `read_<task name>/task_read_report.md`. Exit code 1 means FLAGGED, 0 means NOT FLAGGED, 2 means it could not run.

**One `qc.py read` can answer differently when repeated.** On one package, three runs gave FLAGGED, NOT FLAGGED, FLAGGED, and the flagged items differed. Run it again if it says NOT FLAGGED on a task you doubt, and if any run flags it, treat the task as flagged.

**If not**
- **FLAGGED:** items are numbered `### 1.`, `### 2.`, each with a file and quoted words. Open the file, check the quote. Real problem: fix it. Not a problem: write why (in the answer file below).
- **NOT FLAGGED:** go on. That does not prove the task is good.
- **Run again with `--tab`** only if the message asks for the task kind. **STOP** if it fails twice: send your lead the last 5 lines.
- **Fix the cause** when the last line starts `task_read: could not run:` and says something else. `--tab` does not help with these (exit code 2):
  - `cannot start `claude`: is the claude command installed and on your PATH?`: Once 2 is not done. Check `claude -p hello`.
  - `is not a folder`: the path after `read` is wrong.
  - `has no instruction.md; point task_read at the task folder`: you gave the wrong folder; use the folder that holds `instruction.md`.
  - `no tests/reward.toml or tests/verifier.json: cannot find the grader`: the `tests` folder is missing or incomplete; download the task again.

```
python qc.py read <task folder> --out read_<task name> --tab EKW
# Example (made-up names; use --tab SVC for an SVC task):
python qc.py read C:/qc/tasks/EKW-123 --out read_EKW-123 --tab EKW
```

**Read it three times before the task goes into a batch (recommended).** The reader does not give the same answer on every run: in the batch 14 run, 26 of 146 approved tasks that were clean on the first read were flagged on a repeat read. `--times 3` reads the task up to three times and stops at the first flag. The last line is `FLAGGED` if any read flagged and `NOT FLAGGED` only if all three were clean. It takes up to three times as long (about 6 minutes) and uses up to three times the AI calls. Each read has its own folder: `read_<task name>/read1`, `read2`, `read3`. Against our own audit, 4 of 35 cleared tasks that were clean on three reads were audit-defective, against 12 of 25 for the other cleared tasks (AI audit labels, no TFRL rating, 60 tasks; a clean read still misses most defects).

```
python qc.py read <task folder> --out read_<task name> --times 3
# Example (made-up names, use your own):
python qc.py read C:/qc/tasks/EKW-123 --out read_EKW-123 --times 3
```

**Then write your answers.** Make `read_<task name>/reader_answers.md`, one line per item: `1. FIXED. <one sentence>` or `1. NOT A DEFECT. <one sentence using the quoted words>`. If it was NOT FLAGGED, write `No items.` No program opens the answer files; your manager reads them, so keep the names exactly.

```
1. FIXED. I changed the word limit in instruction.md to match criterion v4.
2. NOT A DEFECT. The quoted words "rounded to two decimals" are met: the golden file shows 12.35.
```

### 3. Script checks (hints)

Scripts run the first-run checks on your task package and write one table. The letters are the check names used in the SOP and in the table columns: A content audit, B build, C, D and E script checks, G the manual pass by the TFRL QC team. `qc.py checks` (3a) writes columns B to E and then F, the worst of the six questions F1 to F6; `svc_run_checks.py` (3b) writes C, D and E only. In the table, F is always the six questions. The SOP also uses the letter F for the oracle (the golden answer run on DataOS, your steps 1 and 4); that is a different thing and is not a table column. A flag is a place to look; fix what is clearly wrong. The six questions in columns F1 to F6 are explained in [`deterministic-checks/ekw/README_sixq.md`](../deterministic-checks/ekw/README_sixq.md).

**Which command?** Look inside your package's `tests` folder. The shape of the package decides, not the task kind.
- `tests/verifier.json` is the EKW harbor shape: use [`qc.py`](../qc.py) `checks` (3a).
- A folder such as `tests/deliverables_01` is the DataOS shape. Every SVC-PC package has it, and so do some EKW packages. Use [`svc_run_checks.py`](../deterministic-checks/svc_run_checks.py) (3b), the command named in [SOP section 3](QC-SOP-first-run.md#3-get-the-task-package-and-run-the-checks).

**3a. EKW harbor shape: `qc.py checks`**

**Run this**

```
python qc.py checks <folder holding the task packages>
# Example (made-up names, use your own):
python qc.py checks C:/qc/tasks
```

**You should see** (the last line; the table lands beside that folder)

```
[qc] table: C:\qc\tasks_qc_out\summary.csv
```

The line is `[qc] table: <folder name>_qc_out/summary.csv`.

"Folder holding the task packages" means a folder whose children are task folders, each with `instruction.md` directly inside it. A DataOS download is `rev_<n>__<id>/task_files`: point at the folder that holds the `task_files` children, not at a folder one level above them.

**If not**
- **Go on** if a DataOS-shaped package shows Check B as fail with `missing_environment_dir`, `missing_golden_dir` and `missing_verifier_json`. Those three messages are expected there and are not a defect to fix: run 3b on that package.
  - Example (made-up names): the row for `EKW-123`, whose tests folder holds `deliverables_01`, shows `B` as `fail` in `summary.csv`, and its `check_b_first` cell reads `environment/data/ missing (the solver's inputs)`. `qc.py checks` looks for the harbor folders (`environment/data/`, `solution/golden_outputs/` and `tests/verifier.json`), and a DataOS-shaped package does not have them.
- **Go on** after you fix what is clearly wrong in the table. A flag is a place to look.
- **STOP** if a Python error shows above the `[qc] table:` line. That line also appears when the checks crashed. Send your lead the last 5 lines.
- **STOP** if you see `shared-check target does not exist:` followed by a path ending `_qc_stage`, even with no Python error. The `[qc] table:` line prints after it, but `summary.csv` was not written (exit code 2). The folder you gave is the wrong level: see "Folder holding the task packages" above. Before you trust the table line, check that `summary.csv` exists.

**3b. DataOS shape: `svc_run_checks.py`**

[`svc_run_checks.py`](../deterministic-checks/svc_run_checks.py) runs checks C, D and E on a DataOS-shaped package and writes one table. Five of its checks ask an AI through your signed-in `claude` command. Without one they print `error`.

**Run this**

```
python deterministic-checks/svc_run_checks.py <task id> --root <folder holding the task packages> --out-dir <results folder>
# Example (made-up names, use your own):
python deterministic-checks/svc_run_checks.py SVC-PC-14-1-0 --root C:/qc/tasks --out-dir C:/qc/svc_checks_out
```

Here `<task id>` is the name of the task's folder under `--root` (the tool looks for `<root>/<task id>`), for example `SVC-PC-14-1-0`. It is not the number in a `rev_<n>__<number>` folder name.

Use full paths (`C:/qc/...`) for `--root` and `--out-dir`, not `..\` or `.\`. With a relative `--root` the tool can start with every check column saying `error`.

**You should see** (the last line of a long output; the first line starts `shared checks (45) on`)

```
1 tasks in 9.1s -> C:\qc\svc_checks_out\summary.csv
```

That last line also prints when every check failed to start. Open `summary.csv` and make sure the check cells say `pass` or `warn`, not `error`.

**If not**
- **Go on** after you fix what is clearly wrong in the table. A flag is a place to look.
- **STOP** if a Python error shows in the output. Send your lead the last 5 lines.

### 4. DataOS

You zip the task, upload it to [DataOS](https://data-os.turing.com) and run the pipeline. It does five evaluation runs, then four "Answer Check" reviews, and a task goes back to you if any review has a Major ([SOP 6b](QC-SOP-first-run.md#6b-the-dataos-pipeline)). A DataOS pipeline run costs about 3 USD of credit: run it once the zip says PASS.

**4a. Build the zip** ([SOP 7](QC-SOP-first-run.md#7-package-and-hand-off), "Two packaging tools")

Make a folder `03_dataos_ready` inside the clone folder (next to [`qc.py`](../qc.py)) and put a copy of your task folder in it. From the clone folder run [`svc_fast_zip.py`](../deterministic-checks/tools/svc_fast_zip.py). It needs 7-Zip, the `7z` command, from 7-zip.org. This tool is for a zip you upload to your own DataOS run (SOP section 7: "for packaging a hand-built task for your own DataOS run"). A zip for a QC batch uses the gated path in 6a step 8, which is your lead's. The tool's help says the task names can also go in a file given with `--list`; you do not need one here.

**Run this**

```
python deterministic-checks/tools/svc_fast_zip.py --tree 03_dataos_ready --zip <task name>.zip <task name>
# Example (made-up names, use your own):
python deterministic-checks/tools/svc_fast_zip.py --tree 03_dataos_ready --zip EKW-123.zip EKW-123
```

**You should see** (the last line)

```
overall: PASS
```

**If not**
- **Use the other tool** if it prints `7z not found on PATH or in the standard 7-Zip install locations.` (exit code 3). Put `["<task name>"]` in a file `tasks.json` (type the square brackets: here they are part of the file), then run [`svc_stage_upload.py`](../deterministic-checks/tools/svc_stage_upload.py). It deletes its `--dest` folder if it exists, so use a new name. It succeeded if it prints no line starting `REFUSING`.
- **STOP** on `overall: FAIL` or `REFUSING`: send your lead the last 10 lines.

```
python deterministic-checks/tools/svc_stage_upload.py --list tasks.json --tree 03_dataos_ready --dest stage_<task name> --zip <task name>.zip
# Example (made-up names, use your own; tasks.json holds ["EKW-123"]):
python deterministic-checks/tools/svc_stage_upload.py --list tasks.json --tree 03_dataos_ready --dest stage_EKW-123 --zip EKW-123.zip
```

Upload only the `.zip`, not the `_manifest.json` beside it.

**4b. Upload and run**
1. Upload the `.zip` as a NEW dataset at [data-os.turing.com](https://data-os.turing.com), never into a QC batch.
2. Wait for `Tasks (N)` to equal your task count.
3. Run pipeline "ManualQC automated QC pipeline 4 Reviewers" (DataOS pipeline 141), version 8. Pick exactly this name. Version 8 was the newest on 2026-10-05, when SOP section 6b was last updated; if DataOS shows a higher version, the files do not say whether to use it, so ask your lead. The SOP retires two pipelines by name: "NO CLAUDE" and the older "ManualQC automated QC pipeline" (version 5 and earlier). The files name no other pipeline, so do not pick any other name in the list (for example one that starts with TESTING or ends in copy); ask your lead what it is. Its four "Answer Check" reviews use the review prompt saved in DataOS as 431, named "Comprehensive_v3_pipeline_quality_re-derive_cascade_NOP_2026-10-03". You do not choose or run that prompt.

**4c. Read the result**

You should see five evaluation runs, then four "Answer Check" reviews. In [DataOS](https://data-os.turing.com) open each review (on the task page, then Verifications, then Comprehensive Review) and read `overall_verdict` in its JSON.

```
overall_verdict: valid
```

`invalid` or `reject` = Major. `valid`, or `needs_revision` with only minor findings = none. The green PASSED badge is job status, not the verdict. Inside a `needs_revision` review, read the `findings`: the SOP separates "minor" from "major" findings, so look at the `severity` field of each entry in the review's `findings` list: it says `major` or `minor`. The JSON also has a `major_count`.

**If not**
- **STOP** if there is any Major. Read it and fix what is real. SOP 6b step 4 then sends the task back to the gate at 6a step 2 "with every finding from every round, and the whole gate runs again": redo 6a steps 2 to 7 (step 1, item 2 above), then zip, upload the new version and run again. If your step 5 table calls that problem NOT A DEFECT, still run the pipeline once more on the same upload: step 5's "do not rerun" does not apply to a Major. If the same Major returns after two reruns: STOP, send your lead the review and the table row.
- **STOP, fix or run again** if fewer than four reviews finished, an oracle run missed full marks, or the empty-answer run scored above zero. (The oracle run submits the golden answer, the task's reference answer, so it must score full marks. The empty-answer run, which the SOP calls NOP, submits nothing, so it must score zero.)
- **Go on** if four reviews finished and none has a Major.

### 5. Review table

The four reviews list problems. Some are real and some are wrong (the review misread your task). [`qc.py`](../qc.py) tests each listed problem against your real files, so you fix only the real ones ([SOP 6c](QC-SOP-first-run.md#6c-after-the-dataos-pipeline-check-the-list-before-you-change-anything)). If the four reviews list no problems at all (minor ones count too), go to step 6.

**Do this first**
1. Copy the problems into `problems.md`: blocks starting `P1.`, `P2.`, each with description, criteria, weight and suggested change. Take them from the "fix list" or "problems found" part of a review (SOP 6c step 1). `qc.py review` takes one problems file, so put the problems of all four reviews in it. The files do not say how to merge a problem that two reviews both list: ask your lead.
2. Make a working folder with a COPY of the task folder named `task`, and `problems.md` next to it.

```
P1. Rule v7-margin-by-region fails a correct answer that writes 12.3 million.
Criteria: v7-margin-by-region
Weight: 0.12
Suggested change: accept the number in any unit.
```

```
review_EKW-123/            <- the working folder (example name)
  task/                    <- a COPY of your task folder
  problems.md
```

**Run this** (30 to 60 seconds a problem)

```
python qc.py review <working folder>/task <working folder>/problems.md
# Example (made-up names, use your own):
python qc.py review C:/qc/review_EKW-123/task C:/qc/review_EKW-123/problems.md
```

**You should see** (one row of the table)

```
| P1 | REAL DEFECT | 0.12 | Rule fails an answer written as 12.3 million | tests/verifier.json:41 | Accept any unit |
```

The table is also saved as `<working folder>/verify-review-findings-result.md`. Keep it. Before the table, about 10 lines of the skill's own prompt text print (they start `No em dashes. No names of companies or people.`): ignore them. A table row can run over more than one line.

**If not**
- **REAL DEFECT:** check that the quoted file and line say what the row says. Then fix the REAL task folder, not the copy, upload, and redo steps 4 and 5. If the check fails, treat the row as CANNOT SETTLE.
- **CANNOT SETTLE:** send the row to your manager with the gap it names.
- **NOT A DEFECT:** leave it.
- **Download the current version and run again** if a `Package check` line names a missing criterion: the review saw another version.
- **Stop** when no REAL DEFECT row is open. If you changed nothing, do not rerun DataOS.

**Check the sibling tests (required, once per task, after the table)**

```
python qc.py siblings <working folder>/task <working folder>/problems.md
# Example (made-up names, use your own):
python qc.py siblings C:/qc/review_EKW-123/task C:/qc/review_EKW-123/problems.md
```

**You should see** a short summary and two new files next to `problems.md`. `siblings.md` lists, under each problem and the heading "Check these tests (required; about half are judged to have the same flaw)", the test id, weight, a one-line reason and the first 200 characters of the test. Tests already in `problems.md` are left out. `siblings_answers.csv` has one row for every suggested test. A second run reads the saved answers (`siblings_reader.json`), makes no AI call and keeps every answer you wrote in the csv; `--no-ask` does the same on purpose.

**Do this before you rerun DataOS:** for every row of `siblings_answers.csv`, open the test and read it against the instruction. Write `yes` or `no` in the `answer` column and a note of 4 words or more in the `note` column. Yes: it has the same flaw, so fix it the way you fixed the listed test and say what you changed. No: say why the test is fair. Do not change a test you have not read. Then run the same command with `--check` added (no AI call):

```
python qc.py siblings <working folder>/task <working folder>/problems.md --check
# Example (made-up names, use your own):
python qc.py siblings C:/qc/review_EKW-123/task C:/qc/review_EKW-123/problems.md --check
```

**You are done** when the last line says `SIBLINGS: COMPLETE`. `SIBLINGS: HOLD (n open)` (exit code 1) comes with one line for every row still missing an answer or a note, or a line saying the reader has not run on the current `problems.md`. While it says HOLD, this step (5) is not finished: do not send the task on.

**Limits** (background; the only part you act on is the last sentence): a blind Sonnet judge said 55 percent of 120 untested picks had the same flaw, against 10 percent for a random test and 20 percent for a look-alike (Opus on 40 per group: 60, 15, 20). Against our own audit, for the 54 defects it confirmed that span two or more tests (44 tasks), the reader was shown one test and the defect text and named 102 of the 194 other tests of that defect (53 percent), against 8 percent for 3 random tests of the same task; 108 of its 149 picks (72 percent) were tests the audit found defective somewhere, against 15 percent of all tests (an independent recount reproduced every count). Those defects are mostly the "an empty answer still passes" type (30 of 54) and the audit labels are AI. TFRL has not rated the picks, and the reader finds nothing beyond chance for tests TFRL cited in separate findings (2.7 percent). Whether the check prevents a second rejection has not been measured. About half of the rows will be a `no`; that is expected.

**If not:** a line `siblings: stopped.` means the AI could not be called, or `siblings_answers.csv` could not be read (close it in your spreadsheet program). Fix that and run it again. Step 5 stays on HOLD until the reader has run.

**Fix with the AI (optional step, you read every change)**

[`qc.py`](../qc.py) `fix` asks the AI to draft a fix for the problems in `problems.md` (or in the printed result of `qc.py read`). It works in a COPY of the task. It checks your original task folder before and after the AI call (files, folders, links and permission bits) and stops with exit 2 if anything in it changed. A checker then tests the copy. It is a draft: you read every change and copy the ones you accept into the task by hand, so you still make the fix yourself (SOP 6b step 4 says to fix issues yourself and not with the platform's auto-fix) ([SOP 6c](QC-SOP-first-run.md#6c-after-the-dataos-pipeline-check-the-list-before-you-change-anything)). If you pass the printed result of `qc.py read` (the line `FLAGGED - report: <path>`), the command opens the report file that line names, so that file must still be on this computer; passing the report file `task_read_report.md` itself works too. A result that says `NOT FLAGGED` is refused: there is nothing to fix.

What the AI can read and write: the copy only, with five tools (Read, Glob, Grep, Write, Edit) and no shell. Settings files inside the package (`CLAUDE.md`, `.mcp.json`, a `.claude` folder) are deleted from the copy and ignored. A task folder that holds a symbolic link is refused. The checker reads the grader files (criteria, weights); it does not look at scripts in `tests/`, so read any change to them in `fix_diff.md`. If `fix_<task name>/fixed` already exists from an earlier run, the command deletes and rebuilds it, so copy the changes you accept into the task before you run again; it stops if the output folder would overwrite the task itself. A `judge_s2.toml` or `judge_s3.toml` beside a `judge.toml` is a byte copy of it (the mean-of-3 judge samples): the command leaves the copies out of the same-name check and rewrites them from the fixed `judge.toml`, and `fix_diff.md` lists them as copies, not as changes to read.

```
python qc.py fix <task folder> <findings file> [--out <output folder>]
# Example (made-up names, use your own):
python qc.py fix C:/qc/review_EKW-123/task C:/qc/review_EKW-123/problems.md
```

**You should see** (the last line)

```
FIX: ACCEPTED BY CHECKER (2 files changed; 1 criterion made looser)
```

A run took about 20 seconds in our two smoke tests. The output folder `fix_<task name>` sits next to your findings file. Open `fix_diff.md` in it: for each changed file it says what changed (criterion id, old and new text, weight changes; the changed sentences of the instruction). Near the top it says `Possible answer leaks flagged: n`. `fix_log.md` is the fixer's own list. The fixed copy is the folder `fixed`.

**How much to trust it.** On our audit of 32 fixed tasks the AI fix left 16 with no serious problem, against 8 when the same tasks were left unfixed (9 tasks better with the fix, 1 worse; the result is fragile). It also added new serious problems on 10 of the 32, against 6 for no fix, a gap too small to call real. Treat the output as a draft you read, not a finished fix.

**Read what got looser first.** Near the top of `fix_diff.md` is a section `Made looser (read these first)`. A criterion is listed there when its weight went down, its text got 20 percent or more shorter, a quoted phrase or a sentence that states a requirement was dropped, its wording now accepts more, a floor went down (or a ceiling went up), or it was removed. The result line counts them: `k criteria made looser`. Some of them are the point of the fix, because the old criterion asked for more than the instruction did. Check each one against the instruction. The list is a reading aid, not a block: in our test it found about 6 in 10 of the criteria a judge called looser (it was tuned on the same 145 fixes, so expect a little less on new tasks). Read the criterion changes below it as well.

**Read for answer leaks.** The AI sometimes copies what a grader wants into the instruction, which tells the solver the answer. Under a new instruction sentence `fix_diff.md` prints `POSSIBLE ANSWER LEAK:` (a number of 3 or more digits, a percent, a dollar amount, or a quoted or capitalised phrase that is also in the grader or the golden answer) and `SHARED WORDING WITH A GRADER:` (six words in a row that the grader or the golden answer also has). The comparison ignores case, thousands commas, curly quotes and "percent" against "%". It does not see small numbers, a decimal against a percent (0.15 against 15%), a plain-words leak shorter than six words, a leak split over two sentences, or golden files that are Excel, Word or PDF. It also fires on names and round numbers the instruction needed: on the 37 earlier fixes that changed the instruction it marked 19 (13 by the first line, 15 by the second); an AI read called 6 of the 37 leaks (a second read agreed on 5) and the flag marked all 6. It is a prompt to read, not a verdict: read every new instruction sentence yourself.

**If the fixed copy is still flagged (optional second pass).** Run `qc.py read` on the fixed copy. If it still flags something, you may run `qc.py fix` once more on the fixed copy, then read every change in the new `fix_diff.md` the same way. In our test of 82 such tasks the second fix left 56 percent with no serious problem on our audit, against 26 percent when the same copy was audited again with no change, and it created fewer new problems. It does not show that the fixed task grades correct answers correctly.

**If not**
- **FIX: ACCEPTED BY CHECKER:** read `fix_diff.md`, copy the changes you accept into the task by hand, then run `qc.py read` on the changed task (step 2).
- **FIX: NO CHANGE MADE:** the AI changed no file (exit 0). Read `fix_log.md` for why; there is nothing to copy.
- **FIX: REJECTED:** the checker found a rule broken after the retry. The files are kept to read; do not copy them in. Make the fix by hand.
- **FIX: NOT RUN:** the AI could not run (usage limit, no claude command, the claude command ending with an error, a symbolic link, a task file that does not parse, a task folder file that changed). It is not a rejected fix. Fix the cause the line names and run again. If the line says the task folder changed, compare it with your copy before you go on.

**Windows notes**
- A path over 260 characters fails to copy. The command then says so and stops. Pass `--out C:/fx` (a short folder) and run again.
- A findings file saved by PowerShell `>` is UTF-16. The command reads it. A UTF-16 file without a byte order mark is refused: save it as UTF-8. A file saved in the Windows ANSI code page (PowerShell 5 `Set-Content`) is read as that code page.

How well it works: after the AI fix, 60 of 99 tasks (61 percent) that our audit called defective pass the audit, against 27 of 99 untouched tasks re-audited. A new serious problem showed up in 20 of 99 after the fix and in 24 of 99 for the untouched tasks, so there is no sign of harm from the fix (20 against 24 does not prove there is none). "Pass the audit" means our AI audit found no serious problem: no person checked it and TFRL has rated no task fixed this way. The 99 are the tasks the method was tuned on, and it was measured with a shell tool on an older folder layout. A retest on new tasks is under way.

### 6. Proof sheet

[`qc.py`](../qc.py) `proof` writes the proof sheet and checks it. A heavy test is one with weight at least 0.05 of the task total (5 percent). If every AI attempt failed such a test, you write a proof that it is fair ([SOP 5a](QC-SOP-first-run.md#5a-qc-person-pre-check-before-you-run-the-dataos-pipeline)). On an EKW task an AI reader of the golden answer can add more rows (6e). Your manager checks the sheet (rule C of the [manager sheet](QC-RUNBOOK-manager.md)).

**6a. Find the rev folder**

In DataOS open your dataset, click "Dataset with runs" for your last run and unzip it into a new folder. If it is a spreadsheet or has no `evaluations` folder, it is the wrong download. Take the folder `<task name>/rev_<n>__<id>` with the highest `n` (the biggest number: rev_11 is newer than rev_9). This is the rev folder.

```
C:/qc/EKW-123_runs/               <- the new folder you unzipped into (example name)
  EKW-123/                        <- the task name
    rev_9__47102/                 <- an older version: ignore it
    rev_11__48213/                <- THE REV FOLDER: the biggest number is the newest
      task_files/                 <- the task itself (instruction.md, tests/, ...)
      evaluations/                <- the DataOS runs
      verifications/              <- the DataOS reviews
      zero_pass_proof.csv         <- proof init writes it here
      golden_reader.json          <- EKW task only: the golden-answer reader's answer (6e)
      blame_reader.json           <- the blame reader's answers (6b)
```

**6b. Start the proof sheet**

On an EKW task this also asks the golden-answer reader (about 2 minutes, 4 AI calls). Read 6e before you run it.

```
python qc.py proof init <rev folder>
# Example (made-up names, use your own):
python qc.py proof init C:/qc/EKW-123_runs/EKW-123/rev_11__48213
```

The blame reader runs by default in `proof init`, on EKW and SVC tasks. An AI reads each zero-pass test (a test that every AI attempt failed) and says whether the test itself may be wrong. It makes 1 AI call per test (about 3 per task on average, 40 tests at most, `--blame-max 20` changes that) and saves `blame_reader.json` in the rev folder. Hand that file over with the sheet in step 7. Every test it flags gets a row in `zero_pass_proof.csv` that starts `BLAME READER FLAGGED THIS TEST` and gives its reason. Fix the test and say so in `other_valid_answer`, or quote the instruction sentence that asks for it; `PROOF` is HOLD until every such row is filled. Of the 42 tasks it flagged across the 151 tested, 34 were tasks TFRL rejected (SOP 5a has the numbers and the limits). `--no-blame` turns it off; the task then has no blame check. If the AI call fails, `proof init` still writes the sheet and ends `PROOF: HOLD (the blame reader did not run on this task ...)`: run `proof init` again once the calls work.

**You should see** (the line that says where the sheet was written)

```
[qc] 1 heavy test failed in all 2 scored AI attempts (heavy: 5 percent or more of the task's total weight, here a weight of 0.05 or more). Wrote C:\qc\EKW-123_runs\EKW-123\rev_11__48213\zero_pass_proof.csv
```

**If not**
- **Redo step 4** if `proof init` says `only n of m AI attempts could be scored`: DataOS scored too few attempts, and `proof check` would end `PROOF: HOLD`. Then start step 6 on the new download. If it happens twice in a row, STOP and send your lead the `proof init` output and the DataOS run link.
- **Go on** (to step 7) if it says `no proof required`: no proof sheet is needed.
- **Run `check`** if it says `zero_pass_proof.csv already exists, so I stopped and changed nothing. Move it away if you want a fresh one.` (exit code 2). Do not move or delete it: it holds your filled rows. Run `proof check` on it (6d).

**6c. Fill in the last three columns**

`<rev folder>/zero_pass_proof.csv` has one row per heavy test that every AI attempt failed. On an EKW task it also has one row for each test the golden-answer reader flagged HOLD, whatever its weight (6e). A test the blame reader flagged gets a row too (6b). Fill the last three columns of each row: `instruction_quote` (the instruction sentence that asks for the test, word for word, 8 words or more), `golden_location` (where the golden answer meets the test) and `other_valid_answer` (why a different valid answer would also pass, 10 words or more). Save as plain CSV (comma delimited) and keep the header row.

```
criterion_id,criterion_text,weight,instruction_quote,golden_location,other_valid_answer
summary_xlsx/v3-total-revenue,Total revenue for fiscal year 2025,0.5,"Report total revenue for fiscal year 2025 in US dollars.","summary.xlsx, sheet Revenue, cell B7","A solver may write 12.3 million or 12300000 and both match the golden value."
```

**6d. Check it**

```
python qc.py proof check <rev folder>
# Example (made-up names, use your own):
python qc.py proof check C:/qc/EKW-123_runs/EKW-123/rev_11__48213
```

**You should see** (the last line; above it is one line per test, `OK:` or the fault)

```
PROOF: COMPLETE
```

**If not**
- **Fix and run again** if the last line is `PROOF: HOLD (n open)`: fix the faulty lines, for example `QUOTE TOO SHORT (6 words, need 8)`, then run `check` again.
- **Fix the task** if you cannot write a row honestly: the test or the instruction is wrong. Redo step 4, then start step 6 on the new download.
- **See 6e** if the last line is a `PROOF: HOLD` that names the golden-answer reader.

**6e. EKW tasks and SVC tasks: the golden-answer reader**

On an EKW task, `proof init` also asks the golden-answer reader, an AI that checks whether the golden answer, and not the instruction, is what a test asks for. The commands and the last line (`PROOF: COMPLETE` or `PROOF: HOLD`) stay the ones you already know.

**EKW task.** The reader adds about 2 minutes and 4 AI calls on your own Claude login, and it needs the Python package markitdown. If you did not install it in Once 1, install it once:

```
python -m pip install "markitdown[docx,xlsx,pdf,pptx]"
```

Every test the reader flags HOLD gets a row in `zero_pass_proof.csv`, whatever its weight. Fill the same three columns as for the other rows. The reader's answer is saved as `golden_reader.json` in the same folder: do not edit it or delete it, and hand it over with the sheet in step 7.

**You should see** (the first line the reader prints; one line per flagged test follows, with the test name and the reader's sentence)

```
[qc] golden-answer reader (EKW task): flagged 1 of the 3 tests that every AI attempt failed (HOLD). For each it says the golden answer, not the instruction, is what the test asks for:
```

When it flags nothing, the line is instead:

```
[qc] golden-answer reader (EKW task): flagged none of the 1 tests that every AI attempt failed.
```

**If not (EKW task)**
- **Run `python qc.py update` once, then `proof init` again** if the line `[qc] STOP: the golden-answer reader could not run on this EKW task` ends `is missing; run: python qc.py update, then try again.` (exit code 2). If the same line comes back, STOP and tell your lead that file is missing from the repo.
- **STOP** if `proof init` ends `PROOF: HOLD (the golden-answer reader could not run)`. Nothing was written. Send your lead the task name, the folder name and the lines above that last line. Run `proof init` again when your lead says it is fixed.
- **Run `proof init` on the same folder again** if `proof check` ends `PROOF: HOLD (the golden-answer reader has not run on this download)`. Your sheet is from before this rule. It keeps every row you wrote and adds the missing ones.

**SVC task.** `proof` prints `golden-answer reader: skipped` and nothing else changes. If it says the task files do not say the kind and treats the task as EKW, but it is an SVC task, add `--tab SVC` to both commands.

```
python qc.py proof check <rev folder> --tab SVC
# Example (made-up names, use your own):
python qc.py proof check C:/qc/downloads/SVC-PC-14-1-0/rev_2__171703 --tab SVC
```

The other way round: if an EKW task prints `golden-answer reader: skipped` and says it cannot tell the task kind, add `--tab EKW` to both commands in the same way.

**6f. Where to read first: the TFRL review read and `look-first`**

Two checks together say which tasks to read first: the blame reader (6b) and a read of the task with TFRL's own review prompt by an AI (Opus, one call, about 3 minutes). Neither can exist before step 4, because both need the AI attempts that DataOS makes, so there is no such pointer in steps 1 to 3 of this sheet. Run the second check on the rev folder, then ask for the pointer. The first command makes one AI call; the second makes none:

```
python qc.py tfrl-read <rev folder>
# Example (made-up names, use your own):
python qc.py tfrl-read C:/qc/EKW-123_runs/EKW-123/rev_11__48213
```

```
python qc.py look-first <rev folder>
# Example (made-up names, use your own):
python qc.py look-first C:/qc/EKW-123_runs/EKW-123/rev_11__48213
```

**You should see** (the last line of each; `both flagged` means read this task's proof rows and review table first)

```
TFRL READ: flagged (major on 1.4)
LOOK: both flagged (task 48213; the blame reader flagged, the TFRL review read flagged)
```

`tfrl-read` works in a private copy and never changes your task. It saves `tfrl_replay.json` and `tfrl_replay_report.md` (the AI's whole review: read it, it says why) in the rev folder; hand both over with `blame_reader.json` in step 7. A second run on the same task asks nothing; `--again` asks again. Both commands exit 0 whether or not they flag: they are pointers, they never send a task back or pass one.

What the pointer rests on: among 105 older tasks TFRL had already rated (47 rejected), TFRL rejected 25 of 40 (62 percent) when both checks flagged the task, 4 of 23 (17 percent) when neither did, and about 4 in 10 when only one did, the same as for any task. The first 151 tasks had suggested 90 percent or better, and it did not hold on these 105. On SVC tasks both flagged was mostly approved (14 of 24), so do not send an SVC task back for this line. On EKW tasks it was 15 of 16 against 3 of 13, but that split was seen after the data was in and is not confirmed yet. These are TFRL's past verdicts on small groups, not a promise about your task.

**If not**
- **`TFRL READ: could not run (...)`**: the reason is in brackets: no evaluation runs in the download (redo step 4), no `claude` command (Once 2), or no usable answer or no answer in 25 minutes (run it again; if it fails twice, send your lead the last 5 lines).
- **`LOOK: no pointer (blame reader not run)`**: run 6b first.
- **`LOOK: no pointer (no TFRL review read)`**: run `tfrl-read` first.

### 7. Hand over to your manager

Your manager finds your work through one new row in the [review sheet](https://docs.google.com/spreadsheets/d/1F02SBuSIbqSA5jfM19Wm-u7rSknUnKU7mYe2aYOVHQc/edit) (your lead posts a new copy each weekend). Add it on the tab for your task kind (EKW or SVC).

| Column | What to put |
|---|---|
| `Submitted by` | your name (use the @ name chip) |
| `Email Id` | your email |
| `task_name` | the task name, for example `EKW-123` |
| `Link in Data-OS (TASK-LINK)` | your task link |
| `Date` | today |
| `Google Doc (if needed)` | the link to one Google Doc or Drive folder (contents below) |
| `S No.`, `Claimed By (Reviewer)`, `Status`, `Added to Consolidated Sheet`, `Comments (Feedback)` | leave empty |

The first lines of that Doc or folder are `Dataset: <link to the dataset page>` and `Pipeline run: <date and time>` (for example `2026-10-09 14:30`). It holds:

```
(your Google Doc or Drive folder)
  verify-review-findings-result.md    <- or the words "DataOS listed no problems"
  zero_pass_proof.csv                 <- or the words "no proof required"
  golden_reader.json                  <- EKW task only, beside the proof sheet (see 6e)
  blame_reader.json                   <- beside the proof sheet (see 6b)
  read_EKW-123/
    task_read_report.md               <- from step 2
    reader_answers.md                 <- from step 2
```

A reviewer from the manager list picks the row up.

### 8. Your row comes back Rejected

`Comments (Feedback)` says `Verdict: DENY` and a `Why:` line naming the failed rules (the rule letters A to F are defined in the [manager sheet](QC-RUNBOOK-manager.md)). It may link the manager reader's report, `manager_read_report.md` ([what it is](../automation/manager-read/README.md)).

```
Verdict: DENY
Why: Rule C: PROOF: HOLD (1 open) in zero_pass_proof.csv. Rule D2: item 2 of manager_read_report.md has no answer.
```

**Do this**
1. Write `read_<task name>/manager_answers.md`, one line per item, same format as step 2. FIXED means the change is in the files.
2. After any change to the instruction, grader (the weighted tests), golden answer or inputs, redo steps 4 to 6.
3. Update the Doc or folder from step 7, then set `Status` on your row to `Rework Addressed`.

When the row says `Approved`:
1. Add the task as one row on the tab of your task kind (SVC or EKW) of the [consolidated sheet](https://docs.google.com/spreadsheets/d/15Z00RATLJt7QcyT_-Rc6Y0jYS9WmcqUpukKp08GwAZ8/edit). Fill the columns up to the DataOS link and ask your lead if unsure.
2. Set `Added to Consolidated Sheet` to `Yes`.
3. Share the dataset as ADMIN with the people your lead names ([SOP 7](QC-SOP-first-run.md#7-package-and-hand-off)), never with the TFRL QC team. SOP 7 names them: Khiem (Khiem Doan, the batch owner) as ADMIN, Andrew_team as admin, and for an EKW task also Luiz as ADMIN.

## After TFRL names a defect

Before the next send, check every other task you worked on in the same batch for the same kind of defect, fix them the same way, and tell your lead.

## Last line, exit code, what you do

Most people read the last line. The exit code is the number the command leaves behind; you only need it if a script checks it. These rows are the ones seen when the commands were run or read in the code.

| Command | Last line you see | Exit code | What you do |
|---|---|---|---|
| `qc.py read` | `FLAGGED - report: <path>` | 1 | Open the report and answer each item (step 2). |
| `qc.py read` | `NOT FLAGGED - report: <path>` | 0 | Go on. Run it again if you doubt the task (step 2). |
| `qc.py read` | `task_read: could not run: ...` | 2 | Read the message (step 2 "If not"). |
| `qc.py checks` | `[qc] table: <folder>_qc_out/summary.csv` | 0 all clear, 1 flags | Open the table (step 3a). Check that `summary.csv` exists. |
| `qc.py checks` | `shared-check target does not exist: ...` then `[qc] table: ...` | 2 | STOP. Wrong folder level (step 3a). |
| `qc.py checks` | a Python error such as `PermissionError`, then a `[qc] table:` line | 1 | STOP. Send your lead the last 5 lines. |
| `qc.py proof check` | `PROOF: COMPLETE` | 0 | Go on to step 7. |
| `qc.py proof check` | `PROOF: HOLD (n open)` | 1 | Fix the lines above it and run again (6d). |
| `qc.py proof check` | any other stop | 2 | Cannot run. Send your lead the last 5 lines. |
| `qc.py siblings ... --check` | `SIBLINGS: COMPLETE` | 0 | Step 5 is finished. |
| `qc.py siblings ... --check` | `SIBLINGS: HOLD (n open)` | 1 | Fill the missing answers and notes, run `--check` again. |
| `qc.py siblings` | `siblings: stopped.` | 2 | Fix what it names and run again (step 5). |
| `qc.py release` | `[qc] table: .../release_table.csv`, a `[qc] HOLD = ...` line may follow | 0 | Open the table (manager sheet). |
| `qc.py release` | `not a zip or folder: ...` | 1 | The zip path is wrong, or a path with spaces was not in double quotes. |
| `qc.py manage` | `[qc] table: .../manager_summary.csv ...`, then other `[qc]` lines | 0, or 2 when any task could not run | Read the counts (manager sheet, batch step 3). |

## If something breaks

Send your lead the last 5 lines the terminal printed. Do not edit [`qc.py`](../qc.py).

Two errors come from how you typed the command, not from the tools:
- `can't open file` naming `qc.py`: you are in the wrong folder. Type `cd C:/qc/EKW_QC_pipeline`.
- `qc.py: error: unrecognized arguments:` followed by the second half of a path: the path has a space and no double quotes. Put the whole path in double quotes.

## Glossary

- **rev folder:** One saved version of one task inside a "Dataset with runs" download. Its name looks like `rev_11__48213`: version 11 of the task whose id is 48213. A bigger number is newer, so `rev_11` is newer than `rev_9`; always use the biggest. It holds `task_files` (the task itself), `evaluations` (the DataOS runs) and `verifications` (the DataOS reviews).
- **task folder:** The folder that holds one task: `task.toml`, `instruction.md`, `tests/`, `solution/` and `environment/` (the zip tool in step 4 says INCOMPLETE if one is missing). Its name is the task name, for example `EKW-123`. In a DataOS download it is the `task_files` folder inside the rev folder.
- **Major:** A problem that makes a correct answer lose credit, or a wrong or empty answer gain credit. One Major sends a task back. Smaller problems do not.
- **proof:** A short written reason, kept in `zero_pass_proof.csv`, that a hard test is fair. A task needs one for each heavy test (weight at least 0.05 of the task total) that every AI attempt failed, and on an EKW task for each test the golden-answer reader flags HOLD. For each such test it gives the instruction sentence that asks for it, where the golden answer (the task's reference answer) meets it, and why a different valid answer would also pass.
- **HOLD:** A tool's word for "stop and look". In `release_table.csv` it means one grading rule was lost by every valid AI attempt but earned by the golden answer: look at that rule. At the end of `proof check`, `PROOF: HOLD` means the proof is not finished. `SIBLINGS: HOLD (n open)` (step 5) is a different message from a different command: it means rows of `siblings_answers.csv` still lack an answer or a note; fill them and run the `--check` command again. For example `PROOF: HOLD (2 open)` means 2 rows are still missing or wrong. On an EKW task the golden-answer reader also flags a test HOLD when the golden answer, and not the instruction, seems to be what the test asks for.
- **EVIDENCE MISSING:** In `release_table.csv`, the tool could not work out one of its checks from the download. It is not a failure. The usual reason is check 2: it only reads reviews written with the review prompt named answer-check-v11 (DataOS saved prompt id 557), and the normal pipeline does not run that prompt. A normal download therefore shows EVIDENCE MISSING for check 2. You do nothing about it, and it never sends a task back.
