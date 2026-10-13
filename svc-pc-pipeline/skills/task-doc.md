---
description: Build the full QC submission record for a group of SVC-PC tasks - the QCR-format Google Doc shared to the QC team, plus both tracker updates.
---

# /task-doc

Build ONE Google Doc for a task group (the tasks named in the arguments), with a QCR block per task, share it so the QC reviewer can open it, THEN record the tasks in both trackers. This is the full, mandatory SVC-PC submission record: the doc alone is not enough, the QC team works from the "SVC QC Tracker Combined" tab and the consolidated tracker.

Arguments: a list of task ids, e.g. `/task-doc SVC-PC-11-4-0 SVC-PC-12-6-0 SVC-PC-73-2-0`.

## Per-task block format (fill every field from real data; purpose is minimalist, 3-5 sentences)

```
QCR_<TASK>_<DDMMYYYY>
Team: Andrew_team | Contact: <"Assigned to" from the tracker>
Task: <TASK> | Revision <N> | Task revision ID: <DataOS rev id>
Dataset: <dataset name from the tracker>
DataOS: https://data-os.turing.com/tasks/<task revision id>
QC reviewer access: qc@turing.com - Editor
Purpose and use case
<3-5 sentence summary from the task's instruction.md: what the agent must do, and any "answer is about the limits of the evidence" points>
Scope (sample count)
1 task: <TASK> (DataOS task revision id <id>). <N> graded deliverable(s), <M> source files totalling <size>.
Dataset structure and key metadata
Harbor / rewardkit SVC-PC package (<file count> files) with: environment/initial_workspace/ - <source files, with row counts for CSVs>; tests/ - the rubric (<group count> judge groups); solution/ - the golden.
Expected outputs
<the graded deliverable filename(s) and format(s) the agent must produce, from instruction.md's graded-deliverables list>
Known limitations or review notes
<the DataOS result this submission rests on (pipeline run, all four Answer Check reviews at 0 majors), any minors the reviews raised, and anything a reviewer should know: large source set, sources that disagree by design, stated givens not to re-derive>
Person of Contact: khiem.doan@turing.com
```

The doc title is `QCR_<first task>_<DDMMYYYY>` (or `QCR_group_<DDMMYYYY>` for several). Bold the field labels (Team, Task, Dataset, DataOS, QC reviewer access, the five section headings, Person of Contact). The five sections are the QC-team SOP's required list (Purpose and use case, Scope, Dataset structure and key metadata, Expected outputs, Known limitations or review notes) plus the contact; a doc missing any of them does not meet the SOP. Also bold the `QCR_...` line per task. Keep formatting basic; do not over-style.

## Process

1. Gather the fields (delegate the read to a Sonnet subagent so the main context stays clean): tracker row per task from the Google Sheet `1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4`, tab "SVC QC Tracker Combined" (the live tab since 2026-09-21; "SVC QC Tracker A" was renamed and a request for it 400s) (column A task id, B Assigned to, plus the rev id and dataset from the "DataOS dataset added"/Note columns), and the package at `/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready/<TASK>/` on the sandbox (instruction.md for purpose; file counts, sizes, CSV row counts; judge-group count). Do not guess numbers.
2. Build the content as markdown: bold every field label with `**...**`, one `---` divider between task blocks, blank line between fields. Create the Google Doc via the Drive MCP connector's `create_file` with `contentMimeType: "text/markdown"` and `textContent: <the markdown>` (Drive converts markdown to a formatted Google Doc, bold and dividers preserved). This is the PRIMARY path and needs NO gcloud - it is why the skill works when gcloud is in reauth (the failure mode that made a prior session hand-build a bare doc). Then read the new doc back with the connector's `read_file_content` to confirm the content rendered before sharing. Fallback ONLY if the connector is unavailable: the gcloud Docs API (`documents.create` + `documents.batchUpdate` with bold ranges), which needs `gcloud.cmd auth login --enable-gdrive-access` and whose login is the user's alone.
3. Share it via the connector's `share_file` (fileId, emailAddress `qc@turing.com`, role `writer`). If refused, report the doc link and ask the user to share it.
3b. **Share the DataOS dataset that holds the task with BOTH QC teams, as Viewer: `TFRL_QC` and `Ardeshir_team` (TRL-QC).** Dataset page > Share > Team. Without it EQC cannot open the task and rejects it with no written reason (2026-09-22: all three `QCR_group_b1` tasks rejected this way; datasets 1816 and 1857 were the only shared ones). Check first: the dataset's Share dialog lists `Team · TFRL_QC · VIEWER` and `Team · Ardeshir_team · VIEWER`. Sharing is a permission grant, so Claude's auto-mode classifier may block it; if blocked, give the user the dataset ids and stop, never route around it.
4. Mark the "SVC QC Tracker Combined" tab (`1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4`; the script's default, `--tab` overrides): set each task's Status to `submit for manual QC` and assign it to the submitter. Dry run first, then apply:
   `python tools/svc_mark_manual_qc.py --tasks <TASK...> --assignee "Khiem Doan"`, then re-run with `--apply`. It discovers the Task/Status/Assigned-to columns by header text, snapshots, writes only those cells, and reads back. Needs `gcloud.cmd auth login --enable-gdrive-access`. Overwriting a co-assignee's name is per the submitter's standing "mark my submissions under my name"; the dry run shows every `old -> new` before you apply. **Never downgrade a status**: if the dry run shows a task going FROM `Approved - Passed Manual QC` (or any Done/Approved state) to `submit for manual QC`, drop it from `--tasks` (2026-09-22: 38-1-0 was already approved from an earlier revision).
5. Add each task to the consolidated tracker (`15Z00RATLJt7QcyT_-Rc6Y0jYS9WmcqUpukKp08GwAZ8`, `SVC` tab) main list: one row per task, columns A blank / B submitter / C the QCR doc title AS A LINK to the doc / D task id / E DataOS link / F `EQC ready` / G blank. QC-team SOP (doc 1IL2s3ez..., section 7c): fill only B:E, never move rows, new rows go at the bottom of the table ABOVE Rejected. A task whose previous submission is under Rejected / highlighted red is a RESUBMISSION: the tool sets F `EQC Ready Revision` and writes `Resubmit- Previous submission major check failed. <what changed>` into the `Resubmission change` column (`--resubmit-note` sets the what-changed text). Use `python tools/svc_consolidated_record.py --doc <title> --doc-url <the doc's viewUrl> --main TASK=REVID ... --dup "TASK=REVID=WHO" ...` (dry run, then `--apply`). `--doc-url` is mandatory for a main-list row: without it column C is a bare title and EQC cannot open the doc (owner, 2026-09-23). It finds the Duplicates heading by text, skips tasks already listed, writes only into a run of consecutive empty rows with a same-step emptiness re-check, snapshots and reads back. The old `_scratch_sheets_write.py` pattern is retired.
6. A task already submitted by someone else whose submission PASSED is a DUPLICATE: do NOT mark it for manual QC in the SVC QC Tracker. Per the QC-team SOP it goes in the MAIN table (bottom of the live queue, above Rejected), NEVER under the lower `Duplicates` heading: B submitter / C `Duplicate - already submitted by <who>` / D task id / E link / F `EQC ready` / G EQC Status `Skip- duplicate` (same tool, `--dup "TASK=REVID=WHO"`; it writes G for you). The sheet highlights it yellow on its own.
7. Report: the doc URL, the sharing state, and the tracker rows written (dry-run diff + readback counts).

## Notes
- The connector `create_file` (markdown -> Google Doc) does NOT need gcloud; use it, not the Docs API, as the default. `drive.py put` is content-replace only and needs gcloud, so it is not the create path.
- Date is DDMMYYYY (today). No em dashes anywhere; hyphens only.
- Fill fields from real data only. Task revision ID is the numeric id in the DataOS URL and is also embedded in the graded `_with_runs` zip path (`.../rev_N__<id>/`); the dataset name and the numeric "Revision N" come from DataOS/the tracker, so if they are not on record, present the Task revision ID and hedge the rest with "confirm on DataOS" rather than guessing.
- Describe the DATAOS-SUBMITTED version, not a drifted sandbox copy. If the sandbox package was locally edited after submission (grammar split, `_scratch_*`, `.preedit` backups), read the structure from the graded `_with_runs` zip's `task_files/` or a pre-edit snapshot so file counts and judge-group counts match what the reviewer opens.
