# SVC QC pipeline: first-run SOP

> **Start with the run sheets (2026-10-09).** QC person: [`docs/QC-RUNBOOK-qc-person.md`](QC-RUNBOOK-qc-person.md).
> Manager: [`docs/QC-RUNBOOK-manager.md`](QC-RUNBOOK-manager.md). They are the short, numbered version; this document
> is the detail behind each step.

> **What changed on 2026-09-24/25 (read first).**
> 1. **You no longer submit tasks to the QC team yourself.** Khiem (Khiem Doan, the batch owner for SVC and EKW) sends tasks to the TFRL QC team (the human reviewers who sample each batch; see "What TFRL QC does with a batch" at the end) in batches of
>    50+ from the consolidated sheet. Never rename a task, never upload into a QC batch, and mark duplicates rather
>    than resubmitting. Full process: [`svc-pc-pipeline/docs/qc-intake-process.md`](../svc-pc-pipeline/docs/qc-intake-process.md).
> 2. **The automated fix pipeline lives in this repo**: [`svc-pc-pipeline/README.md`](../svc-pc-pipeline/README.md)
>    (lane runner, gates, bundler, return intake; the lane runner is the script that takes queued tasks through the 6a gate steps 2 to 8 automatically, and the README describes it). It runs EKW tasks on the same lanes when the SVC queue is empty.
> 3. **Claims:** a task with no tracker update in 48 hours can be reassigned by leadership. Update your row's
>    status or note every day you work a task, and take your name off anything you cannot finish.
> 4. **A "stuck" task is not a dead end until someone checks whether our own tooling caused it** (README, decide
>    mode section). Ask before giving a task up.
> 5. **The DataOS gate (updated 2026-10-05):** run "ManualQC automated QC pipeline 4 Reviewers", version 8 (the
>    newest when this was written; in DataOS it is pipeline 141, and version 8 is spec 401). It runs the five evaluation runs (the oracle runs, the GPT 6 Sol solver runs and
>    the empty-answer NOP run), then four identical "Answer Check" reviews (Claude Opus 5.5, medium effort). A task
>    is sent back if any of the four Answer Check reviews has a major, and passes only when all four are clean.
>    Read each review that has a major and fix what is a real problem. The two "Failed Tests" reviews were removed
>    in version 7. The "NO CLAUDE" pipeline, the older "ManualQC automated QC pipeline" (version 5 and earlier, a
>    different pipeline from 4 Reviewers), the version 6 pair rule and the "2 of 3 reviews valid" rule are retired,
>    and versions 1 to 7 of 4 Reviewers are archived. A pipeline pass is not a TFRL QC approval. Before any upload,
>    every task clears the full gate in step 6a, including recompute from source and the coverage trace, and the
>    QC person pre-check in step 5a.
> 6. **Review and hand-off:** your manager reviews the pipeline result (see
>    [`docs/task-review-rules-v2.md`](task-review-rules-v2.md)). A task they clear goes on the consolidated sheet,
>    and Khiem builds the batches that go to TFRL QC. You never send anything to TFRL QC yourself.

Written for someone who has never touched this before. Follow it top to bottom the
first time. Once it's second nature, use it as a reference instead.

Pipeline location: [`deterministic-checks/`](https://github.com/turing-genai-apps/EKW_QC_pipeline/tree/main/deterministic-checks)
in this repo (merged 2026-09-14, PR #29).

**Known gap, read this before you start**: the checks below run against a
*built* task package (an `environment/` + `solution/` + `tests/` folder tree per
task), not the raw prompt/golden/rubric documents. Most built packages for the
SVC corpus still exist only on Khiem's machine, there is no shared team
download for the full corpus yet. One real batch is available now: the
[`svc-qc-handoff-2026-09-14` release](https://github.com/turing-genai-apps/EKW_QC_pipeline/releases/tag/svc-qc-handoff-2026-09-14)
on this repo carries the diagnosis docs plus a 56-task reconciled zip of
already-fixed, already-Oracle-passed packages. Step 3 covers what to do if
your claimed task isn't in that 56 and you don't already have a built
package for it. If you hit that, say so in the QC team Slack channel rather
than building from scratch on your own.

## 0. The one command for the new checks: qc.py

`qc.py` sits at the top of this repo. It does two things every time you run it: it pulls the latest version of
the repo (so you never have to remember to update), then it runs the step you ask for. Needs Python 3.11 or
newer and git. Clone the repo once, then run these from the repo folder:

```
python qc.py checks <folder of task packages>
python qc.py read <task folder> --out read_<task name>
python qc.py review <task folder> <problem list file>
python qc.py siblings <task folder> <problem list file>
python qc.py release <Dataset with runs zip> [<another zip> ...] --out <output folder>
python qc.py manage <Dataset with runs zip> [<another zip> ...] --out <output folder>
python qc.py proof init <rev folder>
python qc.py proof check <rev folder>
python qc.py update
```

- `checks` runs the first-run checks (B to F) on a folder of task packages and writes a summary table (before DataOS, step 1).
- `read` is the pre-send task read (step 5a item 0): four AI calls, about 2 minutes; `task_read_report.md` lands in the folder you name with `--out`.
- `review` is the check of step 6c: it tests each problem the four DataOS reviews listed against the real files.
- `siblings` is the sibling-test check of step 6c: for each test a problem names, one AI call names up to 3 other tests of the task with the same kind of gap, and writes `siblings.md` and `siblings_answers.csv` next to the problem list file. Step 2 is not done until every suggested test has a yes or no and a note in that file. Add `--check` (no AI call): the last line says `SIBLINGS: COMPLETE` or `SIBLINGS: HOLD (n open)`.
- `manage` is the manager read of step 3: one AI call per task, a report of items per task; every item needs a written answer from the QC person (rule D of the manager run sheet, [`docs/QC-RUNBOOK-manager.md`](QC-RUNBOOK-manager.md)).
- `release` builds the pre-send table from a DataOS "Dataset with runs" download (each row is HOLD, EVIDENCE MISSING or RELEASE; step 7 says what to do with HOLD and EVIDENCE MISSING).
- `proof init` and `proof check` are the proof sheet for heavy tests that every AI attempt failed (step 5a); `proof check` ends `PROOF: COMPLETE` or `PROOF: HOLD`. On an EKW task `proof init` also runs the golden-answer reader (4 AI calls, about 2 minutes); add `--tab EKW` or `--tab SVC` when the task files do not say the kind.
- The blame reader runs in `proof init` by default (EKW and SVC); a test it flags needs a proof row, and `--no-blame` turns it off (see "The blame reader" under the proof rule in step 5a).
- If you edited files inside the repo, the pull stops and says so. Nothing is overwritten. Add `--no-update` to skip
  the pull when you are offline. Put it BEFORE the command word: `python qc.py --no-update read ...`. After the command word it fails with `unrecognized arguments`.
- On Windows, if you see a "path too long" error, run it from a short folder such as `C:\qc`.

**Five different things are called HOLD.** They are not one check, and they do not all stop a task:

| Where you see it | What it means | Does it stop the task |
|---|---|---|
| `PROOF: HOLD (n open)`, the last line of `qc.py proof check` | A heavy test that every AI attempt failed, or a test the blame reader flagged, has no written proof row yet | Yes. A task with this line always goes back (step 5a) |
| `SIBLINGS: HOLD (n open)`, the last line of `qc.py siblings --check` | A suggested sibling test has no yes or no and note yet | Yes. Step 6c step 2 is not finished while it says HOLD |
| A row marked HOLD in the table `qc.py release` builds | A grading rule that every valid solver attempt lost and the golden run earned | No, it is a prompt to look. The manager sends the task back only when the rule or the golden answer is wrong (section 7) |
| A batch tier HOLD from `golden_review_batch.py` (the tiers are HOLD, READ_FIRST, WIDE_NET, CLEAN) | The ranking of a batch for reading | On an EKW task it blocks. On an SVC task it only sets reading order (6a step 4b) |
| A major marked HOLD by `triage_review_majors.py` (it exits with code 10) | The golden answer, the sources or the prompt is wrong or ambiguous | Yes for the batch: the task does not go in a batch until it is fixed ([QC intake process](../svc-pc-pipeline/docs/qc-intake-process.md)) |

## 1. Before you start

You need:
- Access to [`turing-genai-apps/EKW_QC_pipeline`](https://github.com/turing-genai-apps/EKW_QC_pipeline) on GitHub.
- Edit access to the [SVC QC Tracker - 2026-09-12](https://docs.google.com/spreadsheets/d/1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4/edit#gid=1655724557)
  Google Sheet, tab "QC Tracker".
- DataOS access under the Andrew_team project at [data-os.turing.com](https://data-os.turing.com),
  for running the oracle and the DataOS pipeline.

Confirm you have all three before picking up a task. If any is missing, ask in
the QC team Slack channel rather than guessing your way around it.

### Using GLM in OpenCode (optional coding assistant)

The GLM key you get from the team is for **our team's GLM gateway** (`http://34.41.10.8:4000`), not for
Z.AI. So do NOT pick "Z.AI" or "Z.AI Coding Plan" in OpenCode's provider list: both send the key to z.ai,
which rejects it with "token expired or incorrect".

Set it up once:

1. Save your key as a Windows user setting (PowerShell, one line, then open a NEW terminal):
   `setx GLM_API_KEY "PASTE_YOUR_KEY_HERE"`
2. Open your OpenCode config file, `C:\Users\<you>\.config\opencode\opencode.json` (create it if it does not
   exist), and add this `provider` block. If the file already has content, merge the block in rather than
   replacing the file:

   ```json
   {
     "$schema": "https://opencode.ai/config.json",
     "provider": {
       "wandb-glm": {
         "npm": "@ai-sdk/openai-compatible",
         "name": "Team GLM gateway",
         "options": { "baseURL": "http://34.41.10.8:4000/v1", "apiKey": "{env:GLM_API_KEY}" },
         "models": { "glm-5.2": { "name": "GLM-5.2 (team gateway)" } }
       }
     }
   }
   ```
3. Restart OpenCode and pick **GLM-5.2 (team gateway)** (`/models` in the terminal version).

If it still fails, check the key itself with this (it lists the models your key can use):
`curl -s http://34.41.10.8:4000/v1/models -H "Authorization: Bearer YOUR_KEY"`.
An error here means the key is wrong or revoked; ask Khiem for a new one. Never paste your key into Slack
or a shared doc.

### Using GLM with the claude command (`qc.py read`)

`python qc.py read` calls the `claude` command. To run it on the team GLM key instead of a Claude Max login, save the key as `GLM_API_KEY` (step 1 above), open a new PowerShell window, go to the repo folder and run `. .\docs\glm-env.ps1`. If PowerShell blocks scripts, paste these lines into the window instead:

```
$env:ANTHROPIC_BASE_URL = "http://34.41.10.8:4000"
$env:ANTHROPIC_AUTH_TOKEN = $env:GLM_API_KEY
$env:ANTHROPIC_MODEL = "glm-5.2"
$env:ANTHROPIC_SMALL_FAST_MODEL = "glm-5.2"
$env:ANTHROPIC_DEFAULT_SONNET_MODEL = "glm-5.2"
$env:ANTHROPIC_DEFAULT_OPUS_MODEL = "glm-5.2"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "glm-5.2"
$env:CLAUDE_CODE_MAX_OUTPUT_TOKENS = "64000"
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
```

The settings last for that window only; close it to go back to your own login. What was tested: one pre-send read of one real SVC package on 2026-10-09 finished with these settings (NOT FLAGGED, 3 model calls, 1599 seconds). Without `CLAUDE_CODE_MAX_OUTPUT_TOKENS` the model's answers, reasoning included, passed Claude Code's 32,000-token output limit and the read stopped. GLM is slower than Claude Max: allow about 30 minutes for one read. `qc.py manage` was not tested on GLM.

## 2. Pick a task

Open the [SVC QC Tracker, tab "QC Tracker"](https://docs.google.com/spreadsheets/d/1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4/edit#gid=1655724557).
**Columns AD through AI (added 2026-09-14), not U through Z** - this doc had
the wrong columns named for a while, U-Z on the real sheet are Check-A
through Check-H reconciliation history, a different section entirely. The
real difficulty-triage columns are:
- **AD** Task ID (cross-check against column A)
- **AE** Difficulty tier. Confirmed against all 635 live rows on 2026-09-16:
  `needs_llm_or_human_judgment` (282), `mechanical_fast` (181),
  `not_yet_diagnosed_needs_deep_pass` (76), `needs_source_data` (70),
  `excluded` (13), `needs_oracle_run` (11), `genuinely_hard_to_classify`
  (1, rare, means what it says). One row, SVC-PC-55-2-0, carries a stray
  dropdown-instruction string instead of a real value, a live data glitch
  to fix in the sheet, not a set of values to plan around.
- **AF** Defect category (a short label naming the actual problem)
- **AG** Note (the real reasoning behind that classification, not a guess)
- **AH** Assigned to (blank until claimed)
- **AI** Claimed at (blank until claimed)

The same spreadsheet also has an [EKW Tracker tab](https://docs.google.com/spreadsheets/d/1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4/edit#gid=1236768796)
for the EKW tasks. **This paragraph used to say EKW had no `verifier.json`
parser and no path through this pipeline at all - that's no longer true,
`ekw_run_checks.py` (see "EKW tasks" under step 3) parses `verifier.json`
and runs the full check registry against it.** Whether every row on this
tracker tab has been updated to reflect that is a separate question this
doc can't answer for you, read the tab's own values rather than trusting
this sentence's memory of them.

Two other sheets come later. The consolidated sheet (one tab for SVC, one for EKW) is where a task your manager has cleared is logged (section 7). You claim a task on the "QC Tracker" tab described in this section.

Find an unclaimed row (AH and AI both blank) whose difficulty tier matches
what you want to work on. Start with `mechanical_fast` if this is your first
task, it means a script exists that resolves the defect once the missing
piece (a file, a value) is supplied, no design judgment required.

**Claim it before you touch anything**: write your name in column AH and the
current timestamp in column AI on that row. This is the only thing standing
between you and someone else duplicating your work, do it first, every time.
If you finish or abandon a task, clear AH and AI so it goes back into the pool.

## 3. Get the task package, and run the checks

**A folder named `03_dataos_ready` describes a pipeline STAGE (bundled into
the format DataOS expects), it is NOT a claim that the task has passed QC.**
That is the entire reason Checks A-E (listed further down in this step) exist, don't treat a task's presence in
that stage as a pass.

**36 tasks have no built package anywhere, not on GitHub, not locally, not
built at all yet.** `SVC-PC-88-8-0` is the known retired wrong-company slot,
skip it entirely. The other 35, confirmed by diffing the tracker against the
actual local build tree:

`SVC-PC-4-1-0, SVC-PC-4-3-0, SVC-PC-4-4-0, SVC-PC-4-5-0, SVC-PC-11-1-0,
SVC-PC-11-5-0, SVC-PC-12-4-0, SVC-PC-13-1-0, SVC-PC-13-2-0, SVC-PC-13-5-0,
SVC-PC-13-8-0, SVC-PC-23-0-0, SVC-PC-27-0-0, SVC-PC-45-6-0, SVC-PC-49-0-0,
SVC-PC-60-1-0, SVC-PC-65-0-0, SVC-PC-74-0-0, SVC-PC-83-0-0, SVC-PC-84-0-0,
SVC-PC-85-0-0, SVC-PC-86-0-0, SVC-PC-87-0-0, SVC-PC-89-0-0, SVC-PC-90-0-0,
SVC-PC-92-2-0, SVC-PC-95-0-0, SVC-PC-97-0-0, SVC-PC-98-0-0, SVC-PC-99-0-0,
SVC-PC-100-0-0, SVC-PC-101-0-0, SVC-PC-102-0-0, SVC-PC-103-0-0, SVC-PC-104-0-0`

**Update 2026-09-23: 17 of the 35 are now built, and 6 of those are
published.** The 6 are on the
[`svc-unbuilt35-2026-09-23` release](https://github.com/turing-genai-apps/EKW_QC_pipeline/releases/tag/svc-unbuilt35-2026-09-23),
one zip per task (`SVC-PC-<id>.zip`, a single-task DataOS upload unit), plus
`task-index.csv` naming each task's zip and its gate results (prefilter,
rewardkit 0.1.7 loader (the rubric loader DataOS runs at upload), oracle run 1 and run 2). Look your task up in
`task-index.csv` first: a task that failed a gate is still published, and the
index says which gate, so you know its state before you start. Published:
`SVC-PC-11-5-0, 13-5-0, 45-6-0, 49-0-0, 65-0-0, 95-0-0`.

The other 11 built tasks were already assigned to someone in the SVC QC
Tracker when the build finished, so they are held rather than published and
the release doesn't carry a zip for them: `SVC-PC-4-1-0, 4-3-0, 4-4-0, 4-5-0,
11-1-0, 12-4-0, 13-1-0, 13-2-0, 13-8-0, 60-1-0, 90-0-0`. `task-index.csv`
lists each with status `built, held` and the owner at build time. If one of
those is yours and you have no package, ask Khiem for the build.

The other 18 cannot be built from any source that exists today, so don't
claim them: `SVC-PC-23-0-0, 27-0-0, 74-0-0, 83-0-0, 84-0-0, 85-0-0, 86-0-0,
87-0-0, 89-0-0, 92-2-0, 97-0-0, 98-0-0, 99-0-0, 100-0-0, 101-0-0, 102-0-0,
103-0-0, 104-0-0`. Sixteen have no Prompt, Golden Response or Rubric link on
their L1 row and no folder in Final L3 Tasks. 23-0-0 has a prompt but its
golden and rubric links are truncated. 92-2-0 has files, but its rubric has
no points or weights and would need authoring. The per-task reason, source
folder and L1 row are in
[`deliverables/svc-pc-unbuilt35-build-2026-09-23/source-inventory.csv`](../deliverables/svc-pc-unbuilt35-build-2026-09-23/source-inventory.csv).

Where the 17 came from, so you can rebuild one if you need to: L1 is current
for them. Every file an L1 row links is byte-identical (md5) to the copy in
the task's folder under Final L2 Tasks / Final L3 Tasks, and those folders
also carry the Response Criteria workbook and extra golden files the L1 row
omits, so the Final folder is the complete source. The builder that produced
the 2026-09-14 corpus is not the one on `main`; the exact five files used are
in `deliverables/svc-pc-unbuilt35-build-2026-09-23/builder-snapshot/`, and
that folder's README has the command.

**Every other task (the remaining ~599)**: the full-corpus release finished
uploading 2026-09-14 (6 batch zips plus `task-to-batch-index.csv`/`.json`
mapping every task to its batch), it's not still landing. Pull the built
package from GitHub, that's the real, current, grading-ready state. Don't
fall back to L1 for these, the built package may have drifted from L1's
original source (pipeline conversion, or a hand-fix), and the built package
is what actually matters for QC.

First check the
[`svc-qc-handoff-2026-09-14` release](https://github.com/turing-genai-apps/EKW_QC_pipeline/releases/tag/svc-qc-handoff-2026-09-14)'s
56-task reconciled zip (11 parts plus a reassemble script), those 56 are
already fixed and Oracle-passed. For the rest of the ~599, check the
[`svc-full-corpus-2026-09-14` release](https://github.com/turing-genai-apps/EKW_QC_pipeline/releases/tag/svc-full-corpus-2026-09-14)
(all 6 batches finished uploading 2026-09-14, use `task-to-batch-index.csv`
to find your task's batch) and work from that local copy, pointing every
command below at it with `--root <path to
your local package tree> <TASK-ID>`. The raw source materials for the
original 35 are linked per task in the L1 source tracker (for the 17 now
built, prefer the Final L2 / Final L3 Tasks folder named in
`source-inventory.csv`, which is a superset of the L1 links):
- [L2 Tasks tab](https://docs.google.com/spreadsheets/d/19h6CVk_F_vJhGv-xhsAXvw-u3NNRGHCeNAnZMTE6zIM/edit#gid=1305184590)
- [L3 Tasks tab](https://docs.google.com/spreadsheets/d/19h6CVk_F_vJhGv-xhsAXvw-u3NNRGHCeNAnZMTE6zIM/edit#gid=0)

Pulling that Drive folder locally is a real, existing script, not something
to improvise:
[`pipeline/tools/drive_fetch.py`](https://github.com/turing-genai-apps/EKW_QC_pipeline/blob/main/pipeline/tools/drive_fetch.py)
(`python drive_fetch.py <folder_id_or_url> <dest_dir>`, three documented
auth modes in its own docstring). Its conventional destination is
`00_fetched/<ID>/`, the same path Check A's audit tooling expects source
material to already be in. Building what lands there into a checkable
`environment/`/`solution/`/`tests/` tree is the part that's still not a
one-command step, flag that specific gap in Slack if it blocks you rather
than improvising a folder layout, the check scripts are strict about
structure.

The five checks, in order, once you have a package:

- **A, content audit.** No single script, this always needs a person or an
  LLM applying a documented method, not full automation. Two real forms of
  it exist right now:
  - [`content-audit/SKILL.md`](https://github.com/turing-genai-apps/EKW_QC_pipeline/blob/main/deterministic-checks/content-audit/SKILL.md)
    (`harbor-content-audit`), a Claude Code skill in this repo: reads a
    task's `instruction.md`, golden answer, and rubric together and checks
    they agree on the same facts, six defect patterns. Calibrated on a real
    50-task EKW sample (44/50 clean, genuine defects confirmed in the
    rest), not yet run at full-population scale on either corpus, treat
    findings as a strong first read, not a verdict.
  - For SVC-PC, the same kind of check has been running for months as a
    plain agent-dispatch process, real output at full scale: one agent per
    task family reads `instruction.md` + the golden answer + the rubric,
    classifies each task `clean` / `fixable` / `unreachable_content`, and
    records `defects_found` + `proposed_fixes`. All 635 SVC-PC tasks have
    been through this once; the batch JSONs and the summary report are in
    Khiem's `turing-context` repo (`ekw/svc-full-audit-batch-0.json`
    through `-21.json`, `ekw/svc-full-audit-report-2026-09-12.md`) as the
    real precedent to follow, not yet mirrored here. Either the skill above
    or this same method applied by hand both satisfy Check A; neither is a
    single command you run and walk away from.
- **B, build.** Confirms the task folder actually exists in a bundled state.
  If it doesn't, the build pipeline failed for this task, that's a separate,
  pipeline-level problem, not something you fix per-task. For EKW tasks this
  is a real script, see "EKW tasks" below.
- **C, D, E: run the whole registry in one command.** [`svc_run_checks.py`](https://github.com/turing-genai-apps/EKW_QC_pipeline/blob/main/deterministic-checks/svc_run_checks.py)
  runs every C/D/E script against an SVC-PC package tree and merges the
  results into one `summary.csv`, so you never invoke the individual check
  scripts by hand:

  ```
  python deterministic-checks/svc_run_checks.py --all --root <path to your local package tree> --out-dir <results dir>
  ```

  Give specific task IDs instead of `--all` for one task or a few.
  `--checks name1,name2` runs a subset (see `CHECKS` in the script for the
  full list of names). `--jobs`/`--shards` default to one per CPU;
  `--merge-only` re-merges the per-check JSON already in `--out-dir` without
  re-running anything. Confirmed clean at the full ~600-task corpus scale.

  As of this writing that's **7 Check-C scripts, 25 Check-D scripts, and 6
  Check-E check entries covering 5 unique script files** (one script,
  `formula_health_check.py`, is registered twice under two different check
  names and argument sets: once for stale-cache health, once with
  `--check-extraction-loss`). Don't copy that roster into this doc, it will
  go stale the way the old hand-written list here did (it named 3 C-checks,
  7 D-checks, and 1 E-check, and was missing more than half of what's
  actually registered). `CHECKS` in `svc_run_checks.py` is the one place
  this list is allowed to live; read it there.

Run C/D/E first, they're free, fast, and catch the most common mechanical
defects before you spend any time on Check A's judgment calls.

### EKW tasks

EKW packages are harbor-shaped (`environment/data/`, `solution/golden_outputs/`,
`tests/verifier.json`), a different shape than what `svc_run_checks.py`
expects natively. Use the EKW runner instead; it runs Check B, stages a
contract-shaped copy, runs the same full C/D/E registry above on it, and
writes one table:

```
python deterministic-checks/ekw/ekw_run_checks.py --all --root <path to the EKW task tree> --stage <short path outside the tree> --out-dir <results dir>
```

The task tree is the `files/` folder of
`EKWBench_274_tasks_harbor_2026-09-10.zip` (274 `task_*` directories). **Real,
downloadable copy**: the
[`ekw-corpus-274-2026-09-17` release](https://github.com/turing-genai-apps/EKW_QC_pipeline/releases/tag/ekw-corpus-274-2026-09-17)
(the actual working corpus, previously reachable only at `C:\ekwqc\_merged274\files`
on one machine with no other copy anywhere - that gap is closed as of this release).
Extract it and point `--root` at the `files/` folder inside. The population to work from is
the `EKW Tracker` tab on the
[SVC QC Tracker](https://docs.google.com/spreadsheets/d/1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4/edit#gid=2072059214).
Give a few task ids instead of `--all` for a single task. Read `summary.csv`:
`B`, `C`, `D`, `E` per task, then one verdict, count and quoted first finding
per check. `pass`, `warn` (disclosed, not a defect on its own), `fail`, `skip`,
`error` (the check produced nothing, read `runs.json`). Full detail per task is
in `check_b.json` and the per-check JSON next to it. With the default
`--jobs`/`--shards` (one per CPU) the full run finishes in under 15 minutes;
80 minutes is what a single *unsharded* `formula_health_check.py` run alone
takes, not this command, see `ekw/README.md` for both numbers. The
canonical narrow-scope example is `--checks check_b,rubric_schema,formula_health`;
everything except `formula_health` finishes in under 20 seconds on its own.

Three things to know before reading EKW results, explained in
[`deterministic-checks/ekw/README.md`](https://github.com/turing-genai-apps/EKW_QC_pipeline/blob/main/deterministic-checks/ekw/README.md):
the 274 tasks are two build genres in one layout and only one runs under
Harbor as-is; `environment_input_check.py`'s pattern-1 hits are reconciled by
the runner because EKW prompts name outputs, not inputs; and
`judge_determinism_config_lint.py` used to flag nearly every task (269/274)
on temperature 1.0 with no panel, that was fixed 2026-09-14 and the finding
is 0/274 as of the README's last update there, re-check the README before
trusting this number, it says to.

### EKW new tasks in raw format

The new EKW tasks (GTM-, HLT-, MKT-, FIN-, SCO-, LGL-, PHR-, ENG-, listed on the
`EKW QC Tracker Combined` tab with a Task Drive Link) arrive in a raw authoring
format, not a package DataOS can grade. Each Drive folder holds `prompt.txt`,
`verifier.json` (15 to 25 rubric checks, each reading one output file),
`source_documents/` (the inputs) and `expert_solution/` (the golden files plus
`Reasoning.docx`). There is no `task.toml`, no Dockerfile and no `tests/`.

Download the task folder, then run one command:

```
python svc-pc-pipeline/tools/ekw_raw_to_rewardkit.py <raw task folder> --out-root <output folder>
```

It builds `<output folder>/<TASK-ID>/` in the same shape SVC-PC uploads. In
plain English, it:

- turns `prompt.txt` into `instruction.md`, points every `/workspace/...` path
  at `/app/`, and adds the list of graded filenames plus the stored-value
  sentence when a spreadsheet is graded;
- copies `source_documents/` into the workspace;
- ships only the golden files a check actually reads, renamed to the name the
  check reads (expert files are often named differently, for example
  `Account_Expansion_Strategy_Expert(1).docx`), and puts `Reasoning.docx` at
  `solution/reasoning.docx`;
- turns each rubric check into a judge criterion named `v<N>-<tag>`, so a finding
  points straight back to the `verifier.json` entry to edit. Checks are grouped
  by the file they read, and no group holds more than 15;
- judges with `anthropic/claude-sonnet-4-6`, the judge every SVC-PC package
  uses, not the `openai/gpt-5.4` named in `verifier.json`. DataOS only supplies
  an Anthropic key to these packages;
- fills in the stored value of every spreadsheet formula cell in the golden
  (the judge reads stored values, and an unsaved recalculation leaves them
  blank).

It prints what it did per task and exits non-zero if it refused or a
self-check failed. It refuses, instead of guessing, in two cases:

- `expert_solution/` is empty or missing (FIN-102 on 2026-09-24). Ask the author
  for the golden.
- A file in `source_documents/` has the same name as a graded deliverable.
  That file would already be sitting at the graded path when the solver
  starts. GTM-142 is like this: its prompt asks the solver to invent all the
  data, and its `source_documents/` holds a finished alternative answer under
  all three deliverable names. Open the files. If they are not real inputs the
  prompt asks the solver to edit, re-run with `--drop-colliding-sources`.

Then check and zip it the same way as SVC-PC: `svc_prefilter.py` on the
package (no HARD lines allowed), `svc_run_checks.py <TASK-ID> --root <output
folder> --out-dir <results>` for C/D/E (use absolute paths for both), and
`svc_build_upload_zip.py <TASK-ID> --first-grade --pkg-root <output folder>`
for the zip.

## 4. Read a failure

What a failure means depends on which check it's on, and this maps directly
to the tracker's difficulty tiers:

- **D or E failing, tier `mechanical_fast`**: a real script exists for this.
  Go to step 5.
- **D or E failing, tier `needs_source_data`**: the script can tell you
  something's wrong (a missing file, a blank rubric value) but can't supply
  the correct content itself. Find or ask for the real value, never invent
  one. Putting an invented number or fact in front of a grader is a hard rule
  violation in this project, not just bad practice.
- **A or C failing, or D/E flagged `needs_llm_or_human_judgment`**: a genuine
  judgment call, does the rubric actually match the task's intent, is a
  finding a real defect or a false positive. Read the full reasoning in the
  tracker's column AG (Note) first, someone may have already worked through this
  exact question.
- **F (Oracle) failing or tier `needs_oracle_run`**: this isn't a defect in
  what you're looking at, it's a scheduling/resource step. See 5a item 1 and 6a step 5.

## 5. Fix it

- **A known mechanical fix with a script**: `formula_health_check.py`'s
  companion [`formula_cache_autofix.py`](https://github.com/turing-genai-apps/EKW_QC_pipeline/blob/main/deterministic-checks/formula_cache_autofix.py)
  handles stale Excel cached values, the single most common real defect
  found in external review.
  [`deterministic-checks/tools/svc_stray_backup_cleanup.py`](https://github.com/turing-genai-apps/EKW_QC_pipeline/blob/main/deterministic-checks/tools/svc_stray_backup_cleanup.py)
  removes leftover `.orig`/`.bak` files from a prior autofix pass (dry-run by
  default, `--apply` to actually delete, always verifies the real file is
  present and non-empty first).
- **Needs real source data**: track down the actual file or value from the L1
  source tracker links in step 3, ask whoever built the task's family, or
  check if a sibling task in the same family already has it.
- **Needs LLM-assisted judgment**: [`deterministic-checks/tools/llm_backend.py`](https://github.com/turing-genai-apps/EKW_QC_pipeline/blob/main/deterministic-checks/tools/llm_backend.py)
  gives a single `call_llm()` function and a CLI
  (`python deterministic-checks/tools/llm_backend.py --prompt "..."`) that
  tries Claude Code CLI first, falls back to your own API key via env vars if
  you set `LLM_API_KEY`/`LLM_API_BASE_URL`/`LLM_API_PROVIDER`/`LLM_API_MODEL`,
  it never assumes or requires Claude Code specifically. Use it to draft a
  fix, then read the draft yourself before applying it.
- **Genuinely needs a real person**: don't force an LLM answer on a design
  question. Flag it and move to the next task. See step 8.

### 5a. QC person pre-check (before you run the DataOS pipeline)

Do each step on the final package. A step is done only when you can point at the line that proves it. Steps 1
and 2 need DataOS runs; running them before the full pipeline is the cheaper way to catch a broken golden or
credit for an empty answer.

**Read the tasks where AI attempts fail first.** TFRL does not sample at random. In QC batches 4 to 13, 173 of the 175 tasks it rated came from the group whose headroom reads `yes (some fail)` (at least one test that every AI attempt failed), and in batches 6, 7, 8, 9 and 13 it rated every task in that group. A batch is only as clean as that group. List those tasks first (the Headroomness column of the batch document), run every step below on them before the rest, and fix each Major-class defect there before the batch goes out. On EKW tasks the golden-answer reader (6a step 4b) is a block, not a reading order: `python qc.py proof init` runs it, and `proof check` does not print `PROOF: COMPLETE` until every test it flags HOLD has a written row. Example (made-up names): `python qc.py proof init C:/qc/downloads/EKW-123/rev_3__171383`

**A heavy test that every AI attempt failed needs a written proof.** A test is heavy when its weight is 5 percent or
more of the task's total weight. A task that has such a test does not go to TFRL until
`python qc.py proof check <rev folder>` prints `PROOF: COMPLETE`. Run `python qc.py proof init <task folder>` (the
task's `rev_<n>__<task id>` folder from the Dataset with runs download) to get `zero_pass_proof.csv`, one row for
each heavy test; lighter tests need no row. The QC person fills in, for every row, the sentence of the instruction
that asks for the test, where the golden answer meets it, and why a different valid answer would also pass it. The
manager reads the proof sheet, opens `instruction.md` and checks each quoted sentence (manager run sheet, rule C); a `proof check` that ends `PROOF: HOLD` always goes back. On an EKW task the same sheet also gets one row for every test the golden-answer reader flags HOLD, whatever its weight, and `golden_reader.json`, the reader's saved answer, goes with the sheet; `proof check` makes no AI call.

**The blame reader (on by default).** For each test that every AI attempt failed, an AI reads the instruction, the test and the grader's written reasons, and says who was at fault: the AI solver (the test looks fair, a hard task and not a defect), the test itself, both, or it cannot tell. `python qc.py proof init <rev folder>` runs it on every EKW and SVC task (step 6 of the QC person sheet, 6b). It makes one AI call per zero-pass test, about 3 per task on average (469 tests over 151 tasks; 101 of the 151 had at least one, the middle one had 2 and the largest had 79), asks at most 40 tests per task, heaviest first (`--blame-max N` changes that), leaves out a test the reference solution failed too (the release check's oracle run covers that), and saves the answers in `blame_reader.json`. A test it blames on the test or on both gets a row in `zero_pass_proof.csv`, whatever its weight, and the row says the blame reader flagged it and why. The QC person either fixes the test and says so, or quotes the instruction sentence that asks for it, and `PROOF` is HOLD until every such row is filled. `proof check` and `manage` make no AI call: they read `blame_reader.json`. A task with zero-pass tests and no `blame_reader.json` is a HOLD (`PROOF: HOLD (the blame reader has not run on this task)`), and so is a task where the AI call failed. `--no-blame` on `proof init` turns the reader off, and the task then has no blame check. Of the 42 tasks it flagged across the 151 tested, 34 were tasks TFRL rejected. How it did, tested with the Opus model on 151 tasks that TFRL had rated (72 rejected, 79 approved): it flagged 34 of 72 rejected tasks (47 percent) and 8 of 79 approved tasks (10 percent). The rule was chosen on one half of the tasks; on the other half it flagged 16 of 36 rejected (44 percent) and 6 of 39 approved (15 percent). By batch group: batches 4 to 7, 20 of 34 rejected (59 percent) and 1 of 47 approved; batches 8 to 13, 14 of 38 rejected (37 percent) and 7 of 32 approved (22 percent), so it caught less in the newer batches. Asked again on the same 151 tasks with the wording that ships (blind, two runs), it flagged 32 and 36 of the 72 rejected tasks and 14 and 13 of the 79 approved ones, so expect roughly 45 percent of rejected tasks and 15 to 18 percent of approved tasks flagged, and the two runs agree on whether a test is flagged for 90 percent of tests; asking three times and voting did not do better than one run. On 105 other rated tasks with stored runs (outside the 151; 96 of them are from before QC batch 4, so their TFRL labels may not compare) it flagged 41 of 47 rejected tasks and 29 of 58 approved ones: on EKW tasks 24 of 28 against 3 of 19, on SVC tasks 17 of 19 against 26 of 39. On SVC tasks it therefore asks for proof rows on many tasks TFRL approved; an AI reader judged 7 of 12 sampled flags on approved tasks to be real faults in the test, so some of those may be defects TFRL missed. Two AI readers working blind (Sonnet and Opus, no tools, no TFRL information) also judged the 110 tests it flagged and 110 it called fair, chosen at random: both said defect for 49 of the 110 flagged (45 percent) and for 4 of the 110 called fair (4 percent), and 20 of the 42 flagged tasks hold a test both call a defect (17 of 34 rejected, 3 of 8 approved). An independent recount reproduced those counts; no person has checked the labels. A false alarm costs one proof row. It was tested with Opus, not with the model the team uses, so run it on a few known tasks first. The yardstick was TFRL's own verdicts, which were found inconsistent; some flagged approved tasks may have real defects TFRL missed. Against our own audit labels, on the 75 approved tasks the audit also covers, it flagged 6 of the 41 the audit calls defective and 2 of the 34 it calls clean (those labels are AI-made). The 79 approved tasks were read from our own copies, which for 78 of them are not the exact copy TFRL rated.

**Where to read first (both checks together).** The blame reader above and TFRL's own review prompt read by an AI point at tasks worth reading first when they agree. `python qc.py tfrl-read <rev folder>` runs the second one (one Opus call, about 3 minutes, in a private copy; it saves `tfrl_replay.json` and `tfrl_replay_report.md` in the rev folder, and a major on check 1.3, 1.4 or 1.5 flags the task). `python qc.py look-first <rev folder>` and the `look_first` column of `python qc.py manage <zip>` then print the pointer from the saved blame answers and that file, with no AI call, and never block a task. On 105 older tasks TFRL had rated (47 rejected, 58 approved), TFRL rejected 25 of the 40 tasks both checks flagged (62 percent) and 4 of the 23 neither flagged (17 percent); one check alone was no better than the 45 percent for all 105. On SVC tasks both flagged was mostly approved (14 of 24), so it is never a reason to send an SVC task back; on EKW tasks it was 15 of 16 against 3 of 13 but was seen after the data was in and needs a clean confirmation. The first 151 tasks suggested 90 percent or better and that did not hold, so this is a pointer, not a rule. Before DataOS (step 1) there is no pointer: both checks need the AI attempts DataOS makes. The yardstick is TFRL's own verdicts, which were found inconsistent; none of this has been measured as an effect on TFRL approval.

0. **Task read (before DataOS).** Run `python qc.py read <task folder>` on the final package. It makes four AI
   calls through your own `claude` command (about 2 minutes) and writes `task_read_report.md`. If the report says
   FLAGGED, each item names a criterion, a file and the quoted words: open the file, check the quote, then fix the
   task or write down why the item is wrong, one line per item in `reader_answers.md`; the manager checks those lines. A flag is a specific claim you can check, not a verdict. If it says
   NOT FLAGGED, that does not mean the task is clean. One `qc.py read` can answer differently when repeated (one package gave FLAGGED, NOT FLAGGED, FLAGGED on three runs): run it again if it says NOT FLAGGED on a task you doubt, and if any run flags it, treat the task as flagged. In a test on tasks from batches 4 to 13 it flagged 14 of 46
   tasks our audit calls defective (about 3 in 10) and 4 of 49 clean ones (about 1 in 12); on batches 10 to 13 alone,
   5 of 22 and 1 of 20 (unaudited: AI models built the audit labels and no person checked them). It misses most
   coverage gaps and ambiguous sentences, so every other step below still applies in full. If it stops and says it
   cannot tell whether the task is EKW or SVC, run it again with `--tab EKW` or `--tab SVC`. Exit code 2 means it
   could not run; the report says why.
1. **Oracle.** Run the oracle on DataOS. The golden must score full marks on every run, and you need at least
   two runs. A rubric that fails on any oracle run is not reliable.
2. **Empty answer.** Run the empty-answer (NOP) evaluation. It must score zero. If it scores above zero, find
   the criterion that gives credit for nothing and fix it. Wording such as "none found" or "absence is
   acceptable" is the usual cause.
3. **Files.** Every file the prompt or a criterion refers to must be in the package. Open each judge group's
   file list and check that each name exists.
4. **Prompt to rubric.** Next to every criterion, write the sentence in `instruction.md` that asks for it. If no
   sentence asks for it, add the sentence to the prompt or delete the criterion. Watch for details the prompt
   never states: word caps, a number of fields, a layout, a threshold, an extra scenario, or a quality word such
   as "portfolio-oriented".
5. **Expected values.** For every expected number or fact, write how a careful solver gets it from the prompt
   and the shipped sources. If it rests on an assumption the prompt does not state, state it in the prompt or
   change the key. Never copy a value from the reference answer without checking it against the sources.
6. **Rubric to prompt, the other way.** For every requirement in `instruction.md` and every trap you planted in
   the sources (conflicting numbers, superseded documents, distractors, exclusions), write which criterion
   tests it. A row count or a keyword check does not test "values stay unchanged". Every planted trap needs its
   own criterion.
7. **Vague answer.** Imagine an answer that restates the prompt without doing the work. List the criteria it
   would still pass. Its score must be near zero.
8. **Judge visibility.** For each judge group, check that the judge can see what it grades: the file is in its
   list, the deliverable is not longer than the extraction limit, and values are not read only from cached
   cells. If a formula must be live, say so in the prompt, and make the criterion check formulas, not typed
   numbers, on the oracle too.
9. **Contradictions.** Read the criteria against each other and against the prompt and sources. If two criteria
   want opposite things, or a criterion rejects the honest answer, fix it.
10. **Exact wording.** Replace any check that scores a correct answer zero because of its wording with one that
    accepts the reasonable phrasings.
11. **No hardcoded answer.** The oracle must compute its answer, not decode a stored key. Do not put hints in
    the prompt of a task that always passes; only make the specification clearer.
12. **Resubmission.** State what changed against the rejected version, answer each earlier QC comment, keep one
    active version, and re-upload under the same task name. For SVC and EKW, only Khiem uploads into a batch
    dataset. Your own upload for the DataOS pipeline (6b step 1) is a new dataset of your own, not a batch.

How these 12 steps match what TFRL rejects. TFRL's most frequent Major findings fall into six kinds, written out in
[`docs/author-pre-submission-checklist.md`](../docs/author-pre-submission-checklist.md). Steps 9 and 10 cover a rule that
fails a correct answer (kind 1). Step 4 covers a rule the prompt never asked for (kind 2). Steps 2, 6 and 7 cover a wrong
or empty answer that earns credit (kind 4). Steps 3, 8 and 9 cover judge visibility, output location and contradictions
(kind 5). Step 5 covers a wrong number or reference answer (kind 6). Two things are not in the 12 steps: kind 3, a prompt
sentence a careful reader can take two ways, and the part of kind 5 about weights following the priorities the prompt
states. Do both as part of step 4 and step 9.

What counts as a Major: a correct answer that follows the prompt loses credit because of the problem, or a wrong
or empty answer gains credit because of it. Minor issues do not fail a task.

This pre-check is built from the Major issues TFRL names. It has not been tested as a way to predict TFRL's
decision.

**When TFRL names a defect.** Before the next send, check every other task you worked on in the same batch (a manager: every task you cleared for it) for the same kind of defect and apply the same fix to each. A Major found in a sampled task usually means the same defect sits in tasks TFRL did not sample, and TFRL's own guidance asks the submitting team to apply fixes across the whole dataset.

## 6. The gate before DataOS, then the DataOS pipeline

**Updated 2026-10-05.** This section used to describe the "NO CLAUDE" pipeline and a rule that both comprehensive
reviews must report no major, and after that the version 6 pair rule. Those pipelines and rules are retired, as are
the older "ManualQC automated QC pipeline" versions and the "2 of 3 reviews valid" majority. The current process is
below; the scripts and their
details are in [`svc-pc-pipeline/README.md`](../svc-pc-pipeline/README.md) and the current sequence in
[`svc-pc-pipeline/docs/svc-return-runbook.md`](../svc-pc-pipeline/docs/svc-return-runbook.md).

Re-run whichever checks failed. Don't re-run checks that already passed.

### 6a. The gate (every task, before any upload)

This gate applies to EVERY task, SVC and EKW, whoever built it. A task goes to DataOS only after all of these pass, in this order:

1. **Checks A to E** (steps 3 to 5 above) and the pre-filter
   (`svc-pc-pipeline/tools/svc_prefilter.py`): no fail or error; no rubric group over 15 criteria, no `files=`
   path with nothing behind it, no answer-key leak. Then `python deterministic-checks/pre_submit_gate.py --root <package folder> --out <results folder>` on the package (`--task <task id>` limits it to one task):
   no fail, and read every warn (the layout, formula-gate and recalc advisories come from real rejections).
2. **Recompute from source (the full coverage sweep).** List every fact the instruction asks for, re-derive
   each value from the files in `environment/` yourself, and match each fact to the criterion that forces it:
   no criterion, add one; a criterion covering part of a set, extend it to the whole set; a criterion accepting
   a wrong alternative, remove the alternative. If the golden disagrees with the sources, the golden is wrong:
   fix it, never loosen the rubric to fit it. Fix the whole class of any gap, not the one example
   (`svc-pc-pipeline/tools/svc_fix_method_rules.md`, rules R1 to R7).
3. **Coverage trace.** `svc_coverage_trace.py list <pkg>` numbers the instruction's requirements;
   `svc_coverage_trace.py check <pkg> <map>` proves every requirement maps to a criterion. Exit 0.
4. **Per-criterion audit.** Work through [`docs/task-failure-checklist.md`](task-failure-checklist.md) for every
   criterion in every group, and record the answers (one line per criterion): Q1 does the prompt ask for this?
   Q2 does it accept every answer the sources support? Q3 does the expected value re-derive from the sources?
   Q4 does the prompt forbid or restrict it? Q5 is every factual statement in the golden stated by a source file?
   Also check the golden passes it on a strict reading. Those four
   questions (Q1 to Q4) cover 49 of the 60 task failures in QC batches 1 to 6; every "no" is a fix before upload.
   4b. **Golden comparison on every criterion every run failed** (once the task has runs; skip on a first build).
   Put the failing runs' grader reasoning beside the golden. For each such criterion, list what it demands that
   appears in the golden (a figure, an assumption, an alternative, an analysis, a label, a reading) and search
   `instruction.md` and the sources for each, counting broad wording ("anything missing", "each affected file") as
   coverage. Anything only the golden contains is the golden's own choice: loosen the criterion or drop it. Two or
   more runs making the same choice the instruction allows is the same finding. A whole batch can be ranked by
   `svc-pc-pipeline/tools/qc_zero_pass/golden_review_batch.py` (run on a lane by the QC lead, see that folder's
   README): HOLD, READ_FIRST, WIDE_NET, CLEAN (four tiers; on an EKW task HOLD blocks, and the other three only set reading order). The batch ranking is a reading order for people. Give it the CURRENT version
   of each task (`--current-dir`): a flag on a criterion the authors have since rewritten is dropped as STALE. For one EKW task its HOLD tier is a block: `python qc.py proof init` asks the reader, and every test it flags HOLD needs a written row before `proof check` prints `PROOF: COMPLETE`. On EKW tasks it flagged 7 and TFRL rejected 6 of them, against 20 of 47 for the unflagged ones (UNAUDITED: TFRL verdicts only); on SVC tasks it shows no separation, so the block is for EKW tasks only. It reaches only 3 to 4 of 20 rejected tasks, so it is one block among others, not a full gate. These counts were measured before the reader was changed to read more task layouts (on 144 of 405 judge.toml bundles it now reads shapes it used to skip), so re-score them before you quote them again.
5. **Oracle, locally, twice.** `svc-pc-pipeline/tools/judge_emulate.py`: the golden scores 1.0 on two
   independent runs on the same final files.
6. **Try to break it.** Ask whether an answer could pass every criterion and still be wrong (a lazy answer, a
   wrong-basis number, an accepted alternative), and tighten until it can't. Then the reverse: could a correct
   answer fail (a different valid reading, a different layout, a sourced figure the judge can't see)? Loosen or
   fix until it can't. On a resubmission,
   `svc_eval_regrade.py` re-grades the real answers DataOS's models produced: a wrong answer that scored full
   marks must now fail, and a correct answer that lost points must now pass.
7. **Adversarial verify.** An independent reviewer, given the task and your step 4 answers, re-checks Q1 to Q4 for
   every criterion against [`docs/task-failure-checklist.md`](task-failure-checklist.md) and returns
   READY-TO-RESUBMIT, written after the last edit.
8. **Gated zip and bundle.** `svc_build_upload_zip.py` and `svc_bundle_upload.py` (each zip under 500 MB;
   `svc_split_bundle.py` splits oversized bundles).
   Gate on the bundle check's own exit code; never pipe `svc_bundle_upload.py check` or `ekw_bundle_upload.py check`
   through `tail` or `head`, which hides a refusal.

For tasks in the lane queue, the lane runner does steps 2 to 8 automatically (README, "The pipeline, step by
step").

### 6b. The DataOS pipeline

1. Upload the bundle as a new dataset at [data-os.turing.com](https://data-os.turing.com): in DataOS, Datasets, then New dataset, then Create & upload (the path in step 9 of the [return runbook](../svc-pc-pipeline/docs/svc-return-runbook.md)). Wait until the
   dataset shows `Tasks (N)` equal to the number of tasks in the zip; the pipeline only runs on tasks ready at
   launch.
2. Run a pipeline (in DataOS, on the dataset page, in the section Pipeline Batch Runs, the button Run pipeline; checked on the live page 2026-10-11): select **"ManualQC automated QC pipeline 4 Reviewers"**, version 8 (the newest when this section was
   updated on 2026-10-05). Do not pick the "NO CLAUDE" pipeline or the older "ManualQC automated QC pipeline"; both are
   retired, and the older one is a different pipeline from 4 Reviewers. The DataOS list also holds look-alikes that are not this process: "TESTING - ManualQC automated QC pipeline 4 Reviewers", "ManualQC automated QC pipeline copy", "CompanyBench automated QC pipeline" and "automated_qc_pipeline". Check the choice on the pipeline's own page (Pipelines, then the card): it must be named exactly "ManualQC automated QC pipeline 4 Reviewers" and its newest version, v8, shows ACTIVE with the note "A task fails if any of the four Answer Check reviews reports a major" (checked 2026-10-11). One run does the five evaluation runs (the
   oracle runs, the GPT 6 Sol solver runs and the empty-answer NOP run), then four identical "Answer Check"
   reviews (Claude Opus 5.5, medium effort). In DataOS this is pipeline 141, version 8 is spec 401 and the saved
   review prompt is 431 (named Comprehensive_v3_pipeline_quality_re-derive_cascade_NOP_2026-10-03). The two "Failed Tests" reviews were removed in version 7, and versions 1 to 7 are archived.
   A run costs about 3.15 USD (approximate: version 7 measured 2.20 USD, and each added review is about 0.47 USD).
   The pipeline includes the oracle, so a separate oracle run is not needed if both of its oracle runs pass.
   Running the oracle first (step 5a) is only a cheaper way to see whether the task clears the bare minimum.
3. **Pass rule: a task is sent back if any of the four Answer Check reviews has a major. It passes only when all
   four are clean.** Read `overall_verdict` and the findings in each review's JSON, not
   only the node that says "Passed" or failed. A verdict of `invalid` or `reject` means that review found one or
   more majors; `valid`, or `needs_revision` with only minor findings, means it found none. The PASSED badge on a
   review card is job status, not the verdict. The four reviews can disagree. A major in any one of them fails the
   task: read that review and fix what it found if the finding is real.
4. On a reject, record the return with `svc_record_return.py <with_runs.zip> --apply`, but check its PASS or FAIL
   line against the four reviews first: a copy of the tool from before 2026-10-05 passes a task when at least two
   reviews are clean, and it does not read Answer Check replies, which carry `findings` instead of `checks` (checked
   2026-10-05 on synthetic reviews). The rule is that any major in any review fails the task. After a second reject,
   classify the history first (checklist "After two rejects"): a different Major
   each round means a full sweep (6a step 2, recompute from source), the same defect means the Q5 golden-statement audit (ask Q5 of 6a step 4 for every factual statement in the golden: does a source file state it?), and two or more of the four
   reviews reporting a major right after a full sweep means rework the design. The task goes back to 6a step 2 with every finding
   from every round, and the whole gate runs again. Fix issues yourself, not with the platform's auto-fix, and
   never make a change that alters what the task tests.

   This step is for a task the DataOS pipeline sent back. A task that TFRL rejected comes back by another route: fix the task and tell Khiem, who re-uploads it into the same batch dataset under the same name (section 7).

A task is ready for your manager's review when the pipeline rule is met on the latest upload and you have read
every review's findings and fixed what is real. A pipeline pass is not a TFRL QC approval, and it does not mean
the task has no defects.

### 6c. After the DataOS pipeline: check the list before you change anything

**Why this step exists.** The DataOS review reads your task and lists problems. Some are real. Some are wrong: the review misread the instruction, or the grader already handles the case. If you change the task for a wrong item you can break a good grader. This step checks each listed problem against your files and tells you which ones to fix.

**What you need**

- Claude Code installed, signed in with one Claude Max account or one GLM account. Nothing else: no server, no sandbox, no DataOS access from the check itself.
- The skill file [`skills/ekw/verify-review-findings/SKILL.md`](../skills/ekw/verify-review-findings/SKILL.md) in this repo. Copy it once to `~/.claude/skills/verify-review-findings/SKILL.md`.
- The downloaded task folder (the one with `instruction.md`, `tests/`, `solution/`, `environment/`).
- The list of problems DataOS gave for your task, saved as a text file.

**Steps**

1. Open the DataOS review result for your task. Copy the list of problems (the "fix list" or "problems found" part). For each problem keep: the description, the criteria it names, the weight, and the suggested change. Paste them into a file called `problems.md`, one problem per block, starting each with `P1.`, `P2.` and so on.
2. Make a working folder. Put a copy of the downloaded task folder in it and name the copy `task` (work on a copy, never your only copy). Put `problems.md` next to it. Do not put anything else in the folder.
3. Open a terminal in the working folder and run:

   `claude -p --model sonnet --allowedTools "Bash,Read,Glob,Grep,Write" --permission-mode dontAsk "Follow this skill file exactly. $(cat ~/.claude/skills/verify-review-findings/SKILL.md) Task folder: ./task Problem list: ./problems.md"`

   Or, inside an open Claude Code session started in that folder, type `/verify-review-findings ./task ./problems.md`.
   The run sheet ([step 5](QC-RUNBOOK-qc-person.md)) runs this same check with `python qc.py review <task folder> <problem list file>` (section 0).
4. Wait. One problem takes about 30 to 60 seconds; a list of 8 takes a few minutes. It is told to read files only and never to run anything from your task folder or change it. In our test it followed that in 45 of 46 runs; once it loaded a task's check code to try it on an empty folder. That is why you work on a copy.
5. Read the table it prints. The same table is saved as `verify-review-findings-result.md` in the working folder.

**How to read the table**

| Verdict | What it means | What you do |
|---|---|---|
| REAL DEFECT | The files show the problem is true: a correct answer would lose credit, a blank or wrong answer would earn it, two parts of the task disagree, or something the instruction asks for is never graded. | Make the fix in the last column. Heaviest weight first. |
| NOT A DEFECT | The files show the problem is wrong or cannot change any score. The row says what it recomputed. | Leave it. Do not change the task for this item. |
| CANNOT SETTLE | The files do not decide it. The row names the missing file or fact. | Send the row to your manager or the QC lead with the named gap. Do not guess. |

Check three things in each REAL DEFECT row before you edit: the file and line it names really say what the row quotes; the numbers in "what I checked" are ones you can recompute in a minute; the fix changes only what the row says. If a row fails any of these, treat it as CANNOT SETTLE.

The line `Package check` at the bottom tells you if a criterion named in the list was not found in your folder. That usually means the review ran on a different version of the task than the one you downloaded. Download the current version and run again.

**Check the sibling tests (required, once per task, after the table)**

The table covers the tests the review named. Other tests of the same task often have the same kind of gap. Run once per task, after you have read the table and before you rerun DataOS:

`python qc.py siblings <working folder>/task <working folder>/problems.md`

It asks the AI once for each test a problem names (about 10 to 20 seconds a call, 4 at once) and writes two files next to `problems.md`. `siblings.md` prints, for each problem block, the tests the reader thinks have the same kind of gap: the test id, its weight, a one-line reason and the first 200 characters of the test. A test that `problems.md` already names is left out, because it is already on your list. `siblings_answers.csv` gets one row for every suggested test. The AI answers are saved in `siblings_reader.json`, so running it again costs nothing and keeps the answers you wrote; `--no-ask` prints saved answers only and makes no AI call. If the AI cannot be called it prints one line and stops with exit code 2.

What you do: for every row of `siblings_answers.csv`, open the test and read it against the instruction. Write `yes` or `no` in the `answer` column and a note of 4 words or more in the `note` column. Yes (same gap): fix it the way you fixed the listed test and say what you changed. No: say why the test is fair. If you have not read the test, do not change it. Then add `--check` to the same command (no AI call). The last line says `SIBLINGS: COMPLETE` or `SIBLINGS: HOLD (n open)`, and the exit code is 1 on HOLD, the same way `proof check` works. This step (6c) is not finished while it says HOLD.

Evidence and limits:
- The reader (Sonnet, no tools) names up to 3 tests per named test. On 120 test-half cases a blind Sonnet judge said 55 percent of the picks TFRL had not cited had the same flaw; a random test of the same task scored 10 percent and a look-alike test 20 percent.
- A second, stronger judge (Opus) said 60, 15 and 20 percent on 40 items per group.
- Against our own audit: for the 54 defects the audit confirmed that span two or more tests (44 tasks), the reader was shown one test and the defect text (other test names hidden) and named 102 of the 194 other tests of that defect (52.6 percent, range 45.6 to 59.5), against 8.0 percent for 3 random tests of the same task; it named at least one other test in 53 of the 54 defects. 108 of its 149 picks (72.5 percent) were tests the audit found defective somewhere, against 15.0 percent of all other tests of those tasks. An independent recount reproduced every count; about 50 percent of the other tests were still found after setting aside the 12 defects whose text carried a number or a name that points at a target. Most of these defects are the "an empty answer still passes" type (30 of 54), and the labels are AI.
- TFRL has not rated any of the picks.
- For tests TFRL cited in separate findings the reader finds nothing beyond chance (2.7 percent).
- Whether the check prevents a second rejection has not been measured: past TFRL feedback rarely names test ids, so only 2 of the 15 tasks needed had usable ids in both rounds.
- So about half of the suggestions are judged to have the flaw and about half are not. The check is required because half of what it names has the flaw; the cost is a few minutes of reading per task, and about half of the rows will be a no.
- Package tests written as python code in the reward.toml layout are not listed, so they are never suggested.

**What to fix and what to ignore**

- Fix every REAL DEFECT row. Fix the one with the largest weight first.
- A REAL DEFECT on a criterion that a blank answer passes counts even if other criteria also mark a blank answer down. Fix it anyway; the row says how much weight is involved.
- Ignore NOT A DEFECT rows. Do not argue with them in the task; if you disagree, put the row in front of your manager.
- Never rewrite a criterion just to make a listed problem go away. Make the change the "Fix to make" column describes, or ask.

**When to rerun DataOS**

- After you changed the instruction, a criterion, the reference answer or an input file for any REAL DEFECT row: resubmit and run the DataOS review again, because the first review no longer describes your task.
- If every row was NOT A DEFECT or CANNOT SETTLE and you changed nothing: do not rerun DataOS. Send the table with your resubmission note. Exception: a Major in any of the four reviews means run the pipeline once more on the same upload, even when every row is NOT A DEFECT (QC person run sheet, step 4).
- After the rerun, repeat this section with the new list. Stop when the list has no REAL DEFECT rows.

**Limits you should know**

- The check is one AI reading your files, and a second run on the same task can give a different verdict (3 of 18 tasks changed between two identical runs in our test). It is a fast first read, not a ruling. Read the working in each row; do not just copy the verdict.
- In our test it called REAL DEFECT on 10 of 12 problems that a slower, stronger reader also found real (15 of 18 checks), and, in at least one check, on 7 of the 10 that the stronger reader found not real (11 of 16 checks; 6 of the 10 problems were checked twice). Several of the extra REAL DEFECT rows are one kind (we read 6 of the 11 closely and 4 of them were this kind): a rule that passes a blank answer because other rules already mark the blank answer down. If a REAL DEFECT row is of that kind, the weight is small and your manager decides whether to fix it; do not rewrite the rule on the skill's word alone.
- We also ran it on the Opus model (46 runs on 28 tasks). It agreed with the stronger reader on 29 of 46 runs; the
  default model agreed on 30 of 46. Opus said REAL DEFECT on 41 of 46 runs and took about twice as long, so the command
  above names the model that was measured. Do not switch it to Opus expecting a better answer.
- It checks the problems on the list. It does not look for problems the review missed.
- It does not tell you whether QC will accept the task. It tells you whether each listed problem is true.

**Fix with the AI (optional step, you read every change)**

After the table, `python qc.py fix <task folder> <findings file>` can ask the AI to draft a fix for the problems you saved in `problems.md` (or for the printed result of `qc.py read`). It makes one AI call in a COPY of the task. It checks your original task folder before and after the call and stops with exit 2 if anything in it changed (files, folders, links, permission bits). The AI can read and write the copy only, with five tools (Read, Glob, Grep, Write, Edit) and no shell; settings files inside the package are ignored. A checker then tests the copy: it needs a fix_log.md, valid grader files, the weight total of each grader file unchanged, and at most one criterion removed. If the checker rejects the fix it tries once more. The last line says `FIX: ACCEPTED BY CHECKER (n files changed)`, `FIX: NO CHANGE MADE` (the AI changed no file) or `FIX: REJECTED (reason)`; a usage limit, a missing claude command or a claude command that ended with an error says `FIX: NOT RUN` and is not a rejected fix.

You read every change in `fix_diff.md` in the output folder, which lists each changed file in plain words (for a criterion: its id, the old and new text, and any weight change; for the instruction: the changed sentences). Copy the changes you accept into the task by hand, then run `qc.py read` on the changed task to re-check it. Accepted by the checker does not mean correct: you decide each change. Read especially for answer leaks: the AI sometimes copies what a grader wants into the instruction, which tells the solver the answer. `fix_diff.md` flags many of these (`POSSIBLE ANSWER LEAK`, `SHARED WORDING WITH A GRADER`) and also flags harmless names and round numbers, so it is a prompt to read, not a verdict.

What we know: after the AI fix, 60 of 99 tasks (61 percent) that our audit called defective pass the audit, against 27 of 99 untouched tasks re-audited. A new serious problem showed up in 20 of 99 after the fix and in 24 of 99 for the untouched tasks, so there is no sign of harm from the fix. "Pass the audit" means our AI audit found no serious problem: no person checked it and TFRL has rated no task fixed this way. The 99 are the tasks the method was tuned on, and it was measured with a shell tool on an older folder layout. A retest on new tasks is under way. Treat the fix as a draft. On Windows see the Windows notes under the fix step in the [QC person run sheet](QC-RUNBOOK-qc-person.md) (long paths, UTF-16 findings).

## 7. Package and hand off

For lane-built tasks and anything going into a QC batch, the only packaging path is the gated one in 6a step 8
(`svc_build_upload_zip.py`, then `svc_bundle_upload.py`): it refuses a zip whose checks, verify or regrade
record is older than the last edit. The two tools below remain for packaging a hand-built task for your own
DataOS run.

**Hand-off after the DataOS pipeline (since 2026-09-24).** Your manager reviews the pipeline result first
([`docs/task-review-rules-v2.md`](task-review-rules-v2.md)): if the pipeline fails, the manager sends the task
back to you with the failed checks. If it passes, the task can go in the next TFRL batch unless the manager's own
read finds a Major they can show: a correct answer that follows the instruction would lose credit because of it,
or a wrong or empty answer would earn credit because of it. From the next batch the manager also applies rules B to E of [`docs/QC-RUNBOOK-manager.md`](QC-RUNBOOK-manager.md) (the run sheet has rules A to F: A is the four pipeline reviews and F is the review sheet entry) and approves a task only when every rule holds; for the reader items (rule D) a missing or unbelievable answer is enough to send a task back. Before the manager clears a task, the manager runs the pre-send check on the task's DataOS dataset. Download the dataset
from DataOS with the **Dataset with runs** button (the zip has one folder per task revision with `evaluations` and `verifications`
inside; if the download is a spreadsheet or has no `evaluations` folder, it is the wrong download), then follow
[`automation/release-check/README.md`](../automation/release-check/README.md). Two commands build the table. A row that says
HOLD names a grading rule that every valid solver attempt lost and the golden run earned: look at that rule. Send the task
back to the QC person with the rule named only when the rule or the golden answer is wrong; a rule that is simply hard is not
a reason to send it back (in a test on 149 labelled tasks this flag fired on defective and clean tasks about equally often,
so it is a prompt to look, not a verdict). A row that says EVIDENCE MISSING is not a failure; it means a check could not be computed from the
download. EVIDENCE MISSING on check 2 of the release-check tool is expected: check 2 is built for the review prompt named answer-check-v11 (DataOS saved prompt 557), which the normal pipeline does not use and which authors and QC people do not run. It is not a reason to send a task back. Today only the first check (the lost rule) can be computed from a download, so the manager also checks that
the QC person's section 6c table is attached for the latest DataOS review and has no open REAL DEFECT row. A task that fails
either goes back to the QC person.

**Manager read (step 3, before the batch goes to TFRL).** On the same **Dataset with runs** download, run
`python qc.py manage <zip> --out <folder>`. It makes one AI call per task through your own `claude` command (about
1 minute a task), reads the task package and its four Answer Check reviews, and writes
`<folder>/manager/<task id>/manager_read_report.md` for each task plus `manager_summary.csv`. Each item names a
criterion, a file, the quoted words and what to change. Every item needs a written answer from the QC person: FIXED, or NOT A DEFECT plus one sentence that uses the quoted
words. The manager sends the QC person the whole list, opens the file for each answer, checks the quote, and sends the
task back when an answer is missing or does not hold up. No Major has to be shown for this; it replaces the Major bar
above for the reader items. In a test on tasks from batches 4 to 13
(UNAUDITED: the labels are model-built and no person checked them) the reader gave items on 31 of 46 tasks our audit
calls defective and on 18 of 49 clean ones, so expect some answers to be NOT A DEFECT. No items does not mean the task is clean.
Exit code 2 means it could not run for at least one task; the report says why. Details:
[`automation/manager-read/README.md`](../automation/manager-read/README.md).

Once the manager has cleared the task, log it in the
[consolidated sheet](https://docs.google.com/spreadsheets/d/15Z00RATLJt7QcyT_-Rc6Y0jYS9WmcqUpukKp08GwAZ8/edit) (the same link as in the run sheet, step 8) as one row and share the dataset that holds it with Khiem as ADMIN and with Andrew_team as
admin (for EKW, also with Luiz as ADMIN). Do not share the dataset with the TFRL QC team and do not post in #tfrl_qc
yourself, and never rename a task. Khiem collects cleared tasks into batches of 50 or more, uploads each batch as
one dataset under the tasks' original names, and sends it. If QC asks for a fix, fix the task and tell Khiem; he
re-uploads it into the same batch under the same name. Full process:
[`svc-pc-pipeline/docs/qc-intake-process.md`](../svc-pc-pipeline/docs/qc-intake-process.md).

Two packaging tools exist in [`deterministic-checks/tools/`](https://github.com/turing-genai-apps/EKW_QC_pipeline/tree/main/deterministic-checks/tools):
- [`svc_stage_upload.py`](https://github.com/turing-genai-apps/EKW_QC_pipeline/blob/main/deterministic-checks/tools/svc_stage_upload.py),
  the original, slower (~2-3 minutes for 50-60 tasks per the last real
  measurement) but fully verified: forces correct exec bits on `.sh` entries
  as it writes the zip, then reopens it to check for any it missed and does
  a full read-back-and-unpack integrity check (`zipfile.testzip()`).
- [`svc_fast_zip.py`](https://github.com/turing-genai-apps/EKW_QC_pipeline/blob/main/deterministic-checks/tools/svc_fast_zip.py),
  meaningfully faster on the same batch (no committed benchmark for the
  exact number, don't quote one), a similar but not identical CLI
  (`--list`/`--tree`/`--zip` are required here and `--tree` takes one path,
  where `svc_stage_upload.py`'s equivalents are optional and `--tree` repeats),
  patches Unix exec bits into the zip after 7z writes it and runs
  `zipfile.testzip()` for corruption. Use this one unless `7z` isn't on your
  machine, in which case it prints that and exits rather than silently
  failing, fall back to `svc_stage_upload.py` when that happens.

After packaging: upload to DataOS, then clear your claim in the tracker
(blank out columns AH and AI on your row) so the task shows as done, not
still claimed.

## 8. When you're stuck

Genuinely needs another person, not more of your own time:
- A rubric that might be wrong rather than the task, needs whoever owns the
  rubric to make a call, not a unilateral edit.
- A missing source file only the task's original author would have.
- Manual QC (check G; the checks before it are A to E and F, the oracle): the TFRL QC team reviews samples of Khiem's batches.
  It is the final human pass that catches anything upstream checks
  structurally can't see. Do not contact the QC team and do not try to clear
  it yourself; tell Khiem.
- No built package exists yet for your claimed task (see step 3's known gap).

If you're not sure which bucket you're in, post in the QC team Slack channel
with the task ID and what you've tried. Someone else may have already hit
the exact same thing.

### What TFRL QC does with a batch

TFRL QC does not review every task. They review a sample of each batch that they pick, and they look first at
tasks where a test failed in every agent run. The sample size is set per request and has changed more than once,
so ask Khiem for the rule that applies to a given batch. A sampled task with a Major issue is rejected and goes
back to its author. A task that was not sampled is accepted.

The bar did not change when sampling started. A Major issue is one that blocks models. Any Major in the prompt,
test or alignment dimensions disqualifies a task. Minor issues do not. Headroom (how hard the task is for
models) is information, not a pass or reject criterion.
