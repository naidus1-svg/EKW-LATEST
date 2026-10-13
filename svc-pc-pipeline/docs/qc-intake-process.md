# Human QC intake process (SVC + EKW), from 2026-09-24

Owner: Khiem Doan. This process, the consolidated sheet and the team's QC submissions are Khiem's
responsibility. "The TFRL QC team" (also called "the QC team" below) is the group of human reviewers who
review a sample of each batch (contacts: Inhee Park, Gholamali Aminian). Task authors do not send tasks to
it themselves. Any session touching the consolidated sheet, the QC trackers, or submissions to the TFRL QC
team reads this first.

## What changed and why

Until the sprint that ended 2026-09-23, each team member (about 70 people) sent their own tasks to the TFRL
QC team, either as a Google Doc post in #tfrl_qc or as a row on the consolidated sheet, and the QC team wrote
their result into that row.

On 2026-09-23 and 2026-09-24 the QC team changed the terms (Slack group DM C0C21J534JD, and #tfrl_qc):

- Inhee Park, 2026-09-23 16:21 PDT: the QC team copied the consolidated sheet to a frozen copy for their
  records and "won't do any change" to ours. Sheet ownership was transferred to Khiem (16:29 PDT).
- Inhee, 2026-09-23 16:30 PDT: "we do have our own QC worksheet and we'll share it via TFRL_QC".
- Andrew Ma, 2026-09-23 15:52 PDT: back to regular SLA cadence, sampled review in batches.
- Shayan, 2026-09-23 18:18 PDT: all data sent to Google goes through full DataOS and human QC.
- Gholamali Aminian, 2026-09-24 11:59 PDT: consolidate per workstream and share in batches of at least 50;
  authors should stop sharing datasets with the QC team individually.
- Inhee, 2026-09-24 (pasted by Khiem): Batch Submission Guidelines, summarised:
  1. every task has a unique name, kept through every QC round;
  2. at least 50 tasks per batch, in one top-level folder (e.g. `SVC_batch1/` with one folder per task);
  3. zip that folder and upload it to DataOS as one dataset;
  4. after feedback, fix the task and re-upload a single-task zip under the EXACT same name (no `-v2`);
     DataOS archives the old version;
  5. the latest version in DataOS is the official one for QC;
  6. submit full batches only, never single tasks.
- #tfrl_qc house rules (Jafar, 2026-09-18): submit the complete dataset, share it with the TFRL_QC team,
  include every field of the request template (Team, Dataset, Dataset Link, Google Doc Link, Description,
  Requested Deadline). The QC team picks its own samples and may stop early on recurring issues.

## The process now, end to end

1. A team member finishes a task and gets it through the automated DataOS QC pipeline "ManualQC automated QC
   pipeline 4 Reviewers" (version 8 on 2026-10-05): four identical Answer Check reviews. The
   pipeline rule is met unless any of the four Answer Check reviews reports a major. A manager
   then reviews the result (`../../docs/task-review-rules-v2.md`): if the pipeline fails, they send the task back
   to the author with the failed checks. If it passes, the manager applies rules B to E of `../../docs/QC-RUNBOOK-manager.md` in the weekend review sheet, and the task
   goes in the next TFRL batch only when no rule sends it back. For the reader items (rule D) a missing or unbelievable
   answer is enough; no Major needs to be shown. The author adds a row to the consolidated sheet for a
   cleared task. A pipeline pass is not a TFRL QC approval. This step used to read "both comprehensive reviews at 0
   majors", the rule of the retired "NO CLAUDE" pipeline, and after that the version 6 pair rule; both are retired.
2. When 50 or more new tasks for one workstream (SVC or EKW) are in the sheet and not yet sent, Khiem builds
   one batch: one copy of each task (duplicates left out), task names unchanged, zipped as one folder,
   uploaded to DataOS as one dataset, shared with TFRL_QC, and posted once in #tfrl_qc with one Google Doc.
3. The QC team reviews the batch and returns results. WHERE they return them is not settled yet (see Open).
4. Results get into the consolidated sheet, in the task's row, so the author sees them there.
5. If a task needs a fix, the author fixes it and tells Khiem. Khiem uploads the fix into the SAME batch
   dataset under the SAME name. Authors never upload into a batch dataset (the latest upload becomes the
   official version, so a half-finished fix would go straight to QC).

## Who does what

Team members: log finished tasks in the consolidated sheet as today and give Khiem ADMIN on the dataset that
holds each one; do not share datasets with TFRL_QC or post in #tfrl_qc themselves; never rename a task or add a
version suffix; when a task needs a fix, fix it and tell Khiem.

Khiem: build and send each batch; upload fixes; get QC results into the sheet; be the only contact with the
QC team (Inhee Park, Gholamali Aminian).

## Rules that follow from this

- Task names are permanent. Our names (SVC-PC-n-n-n, task_N, FIN-N...) are already unique; nobody renames.
  Inhee's `SVC_batch1-1` was an example of folder layout, not a naming requirement (unconfirmed; ask if the
  QC team objects).
- Duplicates are removed by us before a batch goes out. A task already reviewed in an earlier batch is only
  re-sent as a fix into its original batch dataset, never as a new copy.
- A task we built that someone else already submitted still gets its own row in the normal section, with the
  "Duplicate (auto)" column set to `dup, row N counts`, where N is the earlier row that stands. The batch builder
  skips any row with that column filled. It is not marked for manual QC on the Combined tracker (the "SVC QC Tracker Combined" tab, see `../skills/task-doc.md`). (2026-09-25:
  LGL-178 row 343 and LGL-182 row 370, both behind Luiz's 2026-09-19 rows.)
- The consolidated sheet (Google Sheet id `15Z00RAT...`, full id in `../skills/task-doc.md`, step 5) is our internal record and stays our source of truth. The QC team no
  longer edits it.
- Automated DataOS QC and the manager review stay the gate before a task can enter a batch. The DataOS gate is
  the pipeline rule in step 1 of the process above: no major in any of the four Answer Check reviews.

## Open (ask Inhee and Gholamali)

1. Where do QC results come back? Today they were written into our sheet next to each task. If they will not,
   Khiem copies them from the QC team's worksheet into our sheet (scriptable once we have its link).
2. Near end of month, is a batch under 50 acceptable if that is all that is ready?

## How we build and send a batch (Khiem's decision, 2026-09-24)

1. Take every task on the consolidated sheet (SVC and EKW tabs) that is ready for human QC, has not been sent in
   a batch yet, and is not a duplicate.
2. For each task, check whether Khiem has ADMIN access to the DataOS dataset holding it. With admin access, copy
   the task into one new DataOS dataset for the batch (DataOS "Copy tasks"; one dataset per workstream batch).
3. Without admin access, tag the task's author in Slack asking them to give Khiem admin access to that dataset.
   The task waits for the next batch until access is granted.
4. Once the batch dataset exists, share it with TFRL_QC, write the batch Google Doc, and post the submission in
   #tfrl_qc in the standard template, tagging the TFRL QC team.
5. Set EQC Status (a column on the consolidated sheet that tracks QC progress per task) to "In progress" on the consolidated sheet for every task in the batch.
6. When the QC team's feedback comes back, write each task's result into its row on the consolidated sheet.

## Batching

One command builds the plan for one batch: `python svc-pc-pipeline/tools/qc_batch_build.py`. By default one batch holds both tabs, SVC tasks first and EKW tasks under them, named `QC_batch<N>` (`--ws SVC` or `--ws EKW` builds a single-tab batch; numbering is shared). It is a dry run by default
and changes nothing outside its local output folder (`./qc_batches`, or `--out`).

1. Run `python svc-pc-pipeline/tools/qc_batch_build.py`. It reads the SVC and EKW tabs, finds its columns by header name, and picks every task
   in the live queue (above the "Put your tasks above" row) whose Task Available Status starts with "EQC ready",
   whose EQC Status is blank, whose "Duplicate (auto)" cell is blank, and whose "QC batch" cell is blank. A value
   in EQC Status means the old QC team already handled the row (Done, Reject, In-progress, Skip - duplicate).
   It keeps one row per task name, prints every task it left out and why, and stops if fewer than 50 are
   ready (`--min` changes the floor).
2. It writes `<BATCH>.access_todo.csv`. Open DataOS and fill in, for each task, the dataset it lives in and
   your role there (ADMIN, VIEWER, OPERATOR). Rows whose sheet link points at a dataset instead of a task
   already carry the dataset id; add the task id.
3. Run again with `--access <that csv>`. Tasks where you are ADMIN go into the batch; the plan
   (`<BATCH>.plan.md`) lists them by source dataset as a checklist for DataOS "Copy tasks" into one new dataset
   named after the batch. Tasks without admin access get one draft Slack ask per author
   (`<BATCH>.access_asks.txt`) and wait for the next batch. It also drafts the batch Google Doc
   (`<BATCH>.gdoc.md`) and the #tfrl_qc post (`<BATCH>.tfrl_qc_post.txt`, standard template).
4. In DataOS: create the batch dataset, copy the tasks in, share it with TFRL_QC. Create the Google Doc and
   share it with qc@turing.com. Every Slack message and post goes through `/draft` and is sent by Khiem.
5. Record it: `python svc-pc-pipeline/tools/qc_batch_build.py --apply --plan qc_batches/<BATCH>.plan.json`. This adds a "QC batch"
   column at the far right if it is not there yet (never moves or deletes columns or rows), writes the batch
   name into it and sets EQC Status to In-progress, for exactly the plan's tasks, on both tabs. It checks every row on both tabs before writing any, finds each row again by
   task name and DataOS link, refuses if any row changed since the plan, saves the old values to
   `<BATCH>.snapshot.json`, and reads every cell back.

How DataOS works underneath (read from its web app code, 2026-09-24): each dataset reports your role as
`my_permission` (ADMIN, OPERATOR, VIEWER); the copy dialog only offers target datasets where you are ADMIN;
"Copy tasks" sends one request with the task ids, source dataset and target dataset, and DataOS finishes the
copy as a background job. Drive it from a signed-in browser; never pull the login token out of the page.

A task already sent in a batch is never sent again. If its row comes back as "EQC Ready - Revision" with EQC
Status blank, the tool lists it as a FIX for its original batch dataset.

Versions (TFRL QC guidelines 1, 4 and 5, Inhee Park, 2026-09-24): one permanent name per task, and the latest
version in DataOS is the official one. DataOS never overwrites a task: every re-upload gets a new task id and
the older one is archived. So:

1. The task link on the sheet is whatever the author pasted, and it goes stale when they re-upload. At copy
   time, search each source dataset by task NAME and copy its latest Ready version, never the sheet id.
2. After copying, the batch dataset must hold exactly one Ready task per name, and the batch Google Doc links
   the copied ids.
3. A fix goes into the ORIGINAL batch dataset: copy the fixed version in under the same name. DataOS then
   archives the older same-name copy in that dataset on its own (seen on QC_batch1, 2026-09-25), so QC always
   sees one Ready version. Update the Doc link, and mark the revision row with the batch name and In-progress.
4. Never rename a task or add a version suffix to tell versions apart.

Not built yet: writing the QC team's results back into the sheet (see Open, item 1). The batch counts from
the dry runs on 2026-09-24 (SVC 76 to 77 ready, EKW 42 ready, one combined batch of 119; admin access not yet checked) show the sheet at
that moment only. They do not say whether any task passes QC or whether Khiem has admin on its dataset.

## Batches sent

- QC_batch1, 2026-09-24: DataOS dataset 2251 (https://data-os.turing.com/datasets/2251), 127 tasks (SVC 86, EKW 41),
  batch Doc 1JhNfL1arKRveujBc_W5DvphsW4pWb-YstN0ljLy-Ky0 (shared with qc@turing.com as editor), dataset shared with the
  TFRL_QC team as viewer, requested deadline 2026-09-25. The consolidated sheet carries "QC_batch1" in the new far-right
  "QC batch" column and EQC Status "In-progress" on those 127 rows (snapshot, write and read-back by
  `qc_batch_build.py --apply`). This records that the tasks were copied and the sheet was marked. It does not record the
  #tfrl_qc post (Khiem posts it by hand) or any QC result. Held for the next batch: 5 tasks whose datasets Khiem could
  not copy from (Talah Habib Khalid 2, Hasnain Khan 1, Yashvi Vora 2; all asked for admin on 2026-09-24).
- QC_batch2, 2026-09-25: DataOS dataset 2443 (https://data-os.turing.com/datasets/2443), 92 tasks (SVC 40, EKW 52),
  batch Doc 15xSBxDHvVIirNklcSeF7E_zCFywopw8tly7GfHiQd4s (shared with qc@turing.com as editor), dataset shared with the
  TFRL_QC team as viewer. task_348 and task_hlt-262 were linked on the sheet at archived versions; their Ready versions
  were copied in as well, so the dataset holds 94 tasks, 92 Ready. Sheet rows marked "QC_batch2" / "In-progress" by
  `qc_batch_build.py --apply`. This does not record the #tfrl_qc post or any QC result. Waiting on admin access: 15 tasks
  (Farhan Asghar 4, Sanskar Soni 6, Salman Arshad 3, Abdul Rahman Munir 1, Usman Rafiq 1; asked 2026-09-25).
  Found while building it: QC_batch1 holds archived copies of SVC-PC-18-4-0, SVC-PC-47-6-0 and SVC-PC-45-1-0. Fixed
  2026-09-25: their latest Ready versions were copied into QC_batch1 (tasks 162701, 162703, 162705; DataOS archived
  the old copies itself), the batch 1 Doc links were switched to them in place (Docs API, comments kept), and sheet
  row 506 (SVC-PC-18-4-0 Rev8, the version copied) was marked QC_batch1 / In-progress. QC_batch1 still holds one Ready
  task per name. This does not say the 3 new versions pass QC or that QC had not already opened the old ones.
- QC_batch3, 2026-09-25: DataOS dataset 2506 (https://data-os.turing.com/datasets/2506), 53 tasks (SVC 11, EKW 42),
  batch Doc 1101s41mRNqvxPX-SC1XX4FrEzqaX8fNiSyTFvpnBs7o (shared with qc@turing.com as editor), dataset shared with the
  TFRL_QC team as viewer. Every task was checked Ready at its source before copying (the version rule), and the dataset
  shows 53 tasks, one per name. Includes the 15 tasks held from QC_batch2 for admin access, all granted by then. Sheet
  rows marked "QC_batch3" / "In-progress" by `qc_batch_build.py --apply`. SVC row 531 says GTM-167 but links DataOS task
  GTM-169; the Doc shows both names. This does not record the #tfrl_qc post or any QC result.
- QC_batch4, 2026-09-26: DataOS dataset 2704 (https://data-os.turing.com/datasets/2704), 92 tasks (SVC 10, EKW 82),
  batch Doc 1MAuP0wl_4U_cv-Lgrv3_vFQ3iqKUfEUoCZjW1ytQhs0 (shared with qc@turing.com as editor; carries the Headroomness
  column the QC team asked for on 2026-09-25; Headroomness is the DataOS Test Results Matrix label for whether a test failed in every agent run, e.g. "yes (some fail)"), dataset shared with the TFRL_QC team as viewer. Every task was checked Ready
  at its source; two sheet links pointed at archived versions (SVC-PC-13-5-0, EKW "520") and their current versions were
  copied. Left out: GTM-169 (same DataOS task already in QC_batch3), LGL-147 (already approved under Luiz), and three
  tasks whose datasets Khiem cannot copy from (HLT-251 Rana Jamil dataset 2349; FIN-363 and LGL-157 Imran Farooqi,
  datasets 2314 and 2571). Consolidated sheet and live tracker marked for exactly the 92. This does not record the
  #tfrl_qc post or any QC result.
- QC_batch5, 2026-09-27: DataOS dataset 2802 (https://data-os.turing.com/datasets/2802), 80 tasks (SVC 11, EKW 69),
  batch Doc 135saoZ65-KPPFjM0jxYbXh2o8O5StCesIukq5O5BDPs (shared with qc@turing.com as editor, Headroomness column; 13
  tasks show "unknown (no per-test results in DataOS)"), dataset shared with the TFRL_QC team as viewer. Admin role was
  read from the DataOS datasets list (714 datasets) and every copied id was confirmed Ready and name-matched first; the
  dataset shows 78 tasks, one per name. HLT-251 went in (admin now granted). Held for the next batch: FIN-363, LGL-157
  (viewer only, Imran Farooqi), mkt_104, HLT-202 (linked datasets 2154 and 2761 return "Dataset not found"), task_279, HLT-133 (sheet links
  return "Task not found"), HLT-248 (link opens task_HLT-256 in the HLT-248 dataset, no HLT-248 task exists); GTM-169 and
  LGL-147 left out as in QC_batch4. Fin-319 and MKT-167 (Zakarya Ahmad, datasets 2143 and 2307) were first held as "not
  shared" and added after Khiem challenged it: the /datasets role list omits datasets Khiem can open, so absence from it is
  not evidence; check the dataset page and its Share dialog instead. Asks drafted in ekw/2026-09-27-qc-batch5-access-asks.md. SVC row for SVC-PC-11-5-0
  was relinked by its author mid-build to task 171313, the copied version. Consolidated rows marked "QC_batch5" /
  "In-progress"; live tracker set to "Submitted for Manual QC" for 76 rows; the tracker sync now never changes a row
  already "Rejected" (it would have undone FIN-322, FIN-351 and LGL-167). 12 Salman resubmissions (task ids 170973 to
  170985) are listed as fixes for QC_batch2 to 4 but were NOT copied: they predate the internal-review feedback.
  This does not record the #tfrl_qc post or any QC result.
- QC_batch6, 2026-09-28: DataOS dataset 2926 (https://data-os.turing.com/datasets/2926), 95 tasks (SVC 43, EKW 52),
  batch Doc 1vWlSpqjJ-4h16zquzyI2ILFMAdyDtmmF4QoiuD1ExOw (shared with QC@turing.com as editor, Headroomness column),
  dataset shared with the TFRL_QC team as viewer. Built with 98; the internal zero-pass review ran before posting (section
  below) and its three confirmed fails (SVC-PC-77-0-0, task_663, task_508) were archived out of the dataset, removed
  from the Doc and unlabelled on the sheet, so their fixes go into the next batch. Never send QC a known fail. Post text:
  ekw/2026-09-28-qc-batch6-tfrl-post.md in turing-context. This does not record QC results.
- QC_batch7, 2026-09-28: DataOS dataset 3042 (https://data-os.turing.com/datasets/3042), 51 tasks (SVC 14, EKW 37),
  batch Doc 1Yxf1knm-kzg_eczlz9v-f9Igf9pVfFiz1g7sNh1E8a8 (Headroomness column; the Drive connector could not add the
  QC@turing.com share, so Khiem shares it by hand), dataset shared with the TFRL_QC team as viewer. 54 copied first; the
  internal review confirmed 6 fails (task_358, task_572, GTM-135, NUM-485, SCO-239, ENG-104), archived out and
  unlabelled; Salman's SVC-PC-51-8-0, 51-3-0, 52-7-0 were added after he granted admin on dataset 2981 (100% pass, no
  review needed); SVC-PC-88-7-0 and NUM-496 arrived late and are archived until reviewed. Posted under the 50 minimum
  would have been acceptable (Khiem: do not hold a batch at 48 or 49). The DataOS Test Results Matrix shows at most 100
  test rows: SCO-239 showed "no (100% pass)" there and had 34 zero-pass tests in its run files, so download any task that
  lists exactly 100 tests or shows no per-test results. `qc_batch_build.py --apply` now picks the planned row when an
  older row for the same task and link (already handled by the old QC team) sits above the resubmission.
- QC_batch8, 2026-09-29: DataOS dataset 3214 (https://data-os.turing.com/datasets/3214), 85 tasks (SVC 19, EKW 66),
  batch Doc 1VvGevzVYcW6WIIGNODse3euIZBVbnQ55QcTIYyfGJEE (Headroomness column), dataset shared with the TFRL_QC team as
  ADMIN (Khiem's rule from this batch on). The QC@turing.com share on the Doc was added through the Drive API as owner
  and read back, because the Drive connector's share call fails with "caller does not have permission"
  (`qc_review/_scratch_share_doc.py <DOC_ID>`). This time the internal screen ran BEFORE copying (section below), so
  the 14 confirmed fails were never copied; they are marked Done/Major on the consolidated sheet, Rejected on the
  tracker where a row exists (601 has none), and their QC_batch8 label was cleared (snapshot and read-back). The sheet
  then carries QC_batch8 on exactly 85 rows (SVC 19, EKW 66), matching the dataset and the Doc. Left out: 22
  resubmissions older than their feedback (Salman's task ids 170973 to 171659 and similar), HLT-225 (its link, dataset
  2949, holds no task by that name), SVC-PC-70-3-0, 75-0-0 and 77-4-0 (viewer only on dataset 3119), and 7 sheet links
  that return "Task not found". 19 rows turned ready during the build and wait for QC_batch9. Headroomness labels for
  14 tasks were corrected from the run files (4 "no runs yet" were a parse miss; 10 "unknown" had no 0% test).
  Post text: ekw/2026-09-29-qc-batch8-tfrl-post.md in turing-context (as posted, the deadline reads September 29).
  This does not record QC results.
- QC_batch9, 2026-09-29: DataOS dataset 3363 (https://data-os.turing.com/datasets/3363), 108 tasks (SVC 17, EKW 91),
  batch Doc 1t_sPJGIaFJRDVH_lj5sD7i5UVgb43-5eCX8e_04MebA (Headroomness column; QC@turing.com writer added through the
  Drive API and read back), dataset shared with the TFRL_QC team as ADMIN (Share dialog read back "TEAM · TFRL_QC ·
  ADMIN"). Screened before copying: 113 candidates with admin on a Ready source, all downloaded with runs, 34 with an
  always-zero test reviewed, every first-pass Major verified. Confirmed fails never copied and marked Done/Major:
  FIN-273, FIN-452 (first pass Minor, verifier raised it to Major), FIN-441. MKT-135 and PHR-136 were downgraded to Minor
  and went in. Seven authors re-uploaded during the build (SVC-PC-88-1-0, 70-8-0, 96-2-0, FIN-434, FIN-441, FIN-442,
  FIN-220): their first copies came in archived because the source revisions had been archived, so the new revisions
  were downloaded, re-screened as `b9r` and the latest Ready versions copied. FIN-441 v3 failed where v2 had been clean.
  Left out: FIN-442 (DataOS refuses "Copy tasks" while a task's evaluations are still running; re-screen CLEAN, goes in
  QC_batch10) and FIN-220 (consolidated row removed mid-build, tracker "fixing pipeline results"; its copy was archived
  out of 3363). The sheet carries QC_batch9 on exactly 108 rows, matching the dataset ids and the Doc links. Lessons:
  (1) the dataset task list shows an optional benchmark tag line (cyber-bench, terminal-bench, expert_knowledge_work)
  between the id and the status, so a parser expecting status right after the id silently drops those rows; five tasks
  looked missing that were there. (2) `copyInto2`'s "started" flag is not evidence either way; recount the dataset.
  (3) A hidden Chrome tab throttles timers to about once a minute, so helper loops need a Web Worker timer.
  Post text: ekw/2026-09-29-qc-batch9-tfrl-post.md in turing-context. This does not record QC results.

## QC results

TFRL QC does not review every task: it reviews a sample of each batch that it picks, looking first at tasks where
a test failed in every agent run. The sample size is set per request and has changed more than once, so ask Khiem
for the rule that applies to a given batch. The figure below is dated and may not apply to a later batch.

From round 1 (2026-09-27) the TFRL QC team reviews a 20% sample of each batch (Inhee Park, 2026-09-25: "if your
dataset has 128 tasks, we'll do 128 x 0.2 = 25 samples"), picking tasks with more issues first, which is why the batch
Docs carry a Headroomness column. A sampled task with a Major is rejected and the author fixes it; the fix goes into the
same batch dataset under the same name. Every task not marked Done in their sheet is accepted as good to go (Khiem,
2026-09-27).

How results land on the consolidated sheet: sampled rows get EQC Status "Done", Headroomness, the three ratings in K:M
and QC's feedback in the Detailed Feedback column; unsampled rows get EQC Status "Done - accepted (not sampled)", blank
K:M and a note. Live Counts counts "not sampled" as approved (formulas changed 2026-09-27). The combined tracker shows
"Approved - Passed Manual QC" or "Rejected".

- QC_batch1 round 1, 2026-09-27 (feedback sheet 1uco3Ua7lb87e4SYHR0ZRmy3IZ3T_pHWPJxQzmSt9Pmg): 25 of 127 sampled.
  6 Major, rejected: SVC-PC-44-0-0, SVC-PC-91-0-0, SVC-PC-88-4-0, HLT-240, FIN-267, task_207. 19 sampled with Good or
  Minor only, approved. 102 unsampled, accepted. Consolidated: 128 rows written (SVC-PC-18-4-0 has two batch rows),
  read back OK. Tracker: 118 rows changed, read back OK; task_315, task_316, task_328, task_306 and "task HLT-201" are
  not on the tracker under those names. This records QC's verdicts; it does not say the rejected tasks have been fixed.
- QC_batch2 and QC_batch3 results, applied 2026-09-27 (sheets 1NSu63l9... and 1XKgwww4..., Inhee Park, shared
  2026-09-26 evening). Batch 2: 20 of 92 sampled, 2 Major (FIN-384 new, GTM-175 already an internal fail), 65 unsampled
  accepted. Batch 3: 20 of 53 sampled, 1 Major (LGL-167, already an internal fail), 32 unsampled accepted. QC passed 6
  tasks our internal review failed (FIN-353, GTM-163, SVC-PC-93-5-0, FIN-322, FIN-351, FIN-396); Khiem: our fail stands,
  QC's result is recorded as a note only. Internal fails QC did not sample were left as they were. HLT-247, LGL-183 and
  MKT-178 had a blank QC batch cell and got the label. Left for Khiem: GTM-167 (QC lists it with DataOS name GTM-169;
  two rows match), task_348 and task_48 (tracker says Rejected with no Major on the consolidated row), task_36 (tracker
  assignee differs from author). Consolidated 494 cells and tracker 120 cells written, read back OK. QC_batch4 and 5 have
  no QC results yet.

QC_batch4 results (Jafar, 2026-09-28, sheet 13aEHwFF..., tab "SVC-EKW-QC_batch4(28QC)"): 28 of 92 sampled, the other
64 accepted as not sampled (the 20 to 25% sampling rule; Khiem 2026-09-28). Applied with the batch 2/3 script, now
finding the QC batch column by header: 17 QC results written (5 Major -> tracker Rejected), 64 accepted -> tracker
Approved, 11 internal fails kept (QC's verdict added as a note; our fail stands), 3 EKW rows QC labelled SVC got their
missing batch label. The tracker step never flips a task that has an internal fail in any batch or a newer version in
a later batch.

QC_batch5 results (Jafar, 2026-09-28, sheet 1TKHPIpk..., tab "SVC-EKW-QC_batch5(24QC)"): 24 of 80 sampled, all "Done",
10 with a Major (SVC-PC-11-5-0, 15-0-0, 17-7-0, 38-4-0, LGL-191, SCO-252, GTM-184, SCO-265, HLT-235, task_111). This
sheet orders its columns 6 Headroomness, 7 QC samples, 8 QC Status (batch 4 had samples, status, headroomness), so the
apply script reorders each row on read. Applied: 11 QC results written (5 new Majors -> tracker Rejected), 56 accepted
as not sampled, 13 internal fails kept; tracker 60 Approved and 5 Rejected, read back OK. num-490 and num-560 have no
tracker row.

Tracker audit the same day (consolidated sheet vs both Combined tabs, newest consolidated row per task): 41 statuses
corrected (25 to Submitted where a newer submission row exists, 9 legacy Done+Major rows to Rejected, 7 Done/Good
rows to Approved), plus FIN-315, FIN-316, FIN-306, HLT-201 and HLT-205, accepted in batches 1 and 2 but missed
because the consolidated names (task_315, "task HLT-201", "tasj_HLT-205") differ from the tracker names. Left as they
are, with the reason: SVC-PC-49-8-0 and FIN-304 (internal fail on the sheet, author marked resubmitted on the tracker
with no resubmission row), task_348 and task_48 (tracker Rejected, sheet accepted; held since 09-27), six EKW task_N
rows now used for "Running the git repo steps", SVC-PC-20-5-0 (rework in progress), SVC-PC-39-4-0 and SVC-PC-94-3-0
(tracker Approved with an unreviewed submission row), SVC-PC-80-0-0 and task_284 (H Done, no ratings), and the NUM
workstream (no rows on the Combined tracker at all). Both tabs were then re-sorted: unclaimed, worked on, submitted,
blocked, approved.

### Golden review of each batch (standing step from 2026-10-02)

After the internal zero-pass review and before a batch is posted to TFRL, the QC lead runs
`svc-pc-pipeline/tools/qc_zero_pass/golden_review_batch.py` on a lane over the batch's current task bundles, with
`--verdicts <bN/verdicts>` so the internal review result is merged, and `--current-dir` pointing at the current version of each task so flags on criteria the authors have since rewritten are dropped as STALE. It compares every criterion that every run failed
with the golden answer and ranks tasks HOLD (rejected by the internal review, or at least one criterion marked HOLD_AI: the golden-comparison passes say 2 of 3 and the pass without the golden also says defect), READ_FIRST (the golden-comparison passes alone say 2 of 3), WIDE_NET (9 or more flags: read
the instruction's scope first) or CLEAN. The tiers are defined in `svc-pc-pipeline/tools/qc_zero_pass/README.md`. It marks nothing failed: a person reads each HOLD and READ_FIRST criterion against the prompt and the golden.
Measured on QC batches 1 to 5 (TFRL-labelled): with the instruction-coverage step it finds 20 of 33 TFRL-confirmed defect
criteria at 6.0 percent false flags (precision 41 percent); the first independent verdicts on held-out flags were
weaker (2 confirmed of 68 on an earlier prompt). Scored on fresh TFRL verdicts (batches 6, 8 and 9: 68 TFRL-reviewed tasks, 22 with a Major), the HOLD_AI flag caught 4 of 22 Majors (18 percent) and flagged 5 of 46 clean tasks, so treat it as a reading order and do not expect it to cut the Major rate.
Evidence: `svc-pc-pipeline/tools/qc_zero_pass/GOLDEN_REVIEW_EVIDENCE.md`.

### Hold tasks whose latest review still says the answer key, sources or prompt is wrong (standing step from 2026-10-02)

Before a batch is posted to TFRL, run `svc-pc-pipeline/tools/qc_zero_pass/triage_review_majors.py` on each task's latest
DataOS comprehensive review JSON files. It sorts every major by what TFRL rejects. A major marked **HOLD** (a different
HOLD from the batch tier above; this one comes from `triage_review_majors.py`) says the golden
answer, the source files or the prompt itself is wrong or ambiguous: do not put that task in a batch until it is fixed
(the script exits with code 10 when a HOLD is present). The other majors (a weak answer can still score, a grading script
misbehaves) are still fixed, but they do not predict a TFRL rejection, so they do not hold a batch.
Measured on 40 TFRL-labelled tasks (25 rejected, 15 passed): HOLD majors were on 10 of 30 rejected tasks and 2 of 17 passed
tasks. That catches about a third of TFRL rejections and holds about one in eight good tasks. It does not replace the
0-majors rule in the SOP. Evidence and limits: `svc-pc-pipeline/tools/qc_zero_pass/REVIEW_TRIAGE_EVIDENCE.md`.

### Internal zero-pass review of batches 1 to 4 (2026-09-26 night)

TFRL QC samples 20%, so Khiem's team reviewed the unsampled tasks most likely to hide a task defect: every task where
at least one test fails in every agent run ("yes (some fail)" Headroomness), 116 tasks across QC_batch1 to 4. Each
0% test was judged task defect or solver miss from the DataOS "Dataset with runs" zip, using the TFRL QC categories and
QC's round 1 Majors as calibration. Every first-pass Major got a second, independent reviewer who tried to refute it;
only confirmed Majors were marked, exactly like manual QC (consolidated H "Done", K:M ratings, N note tagged
"Internal zero-pass review (Khiem's team, not TFRL QC)"; tracker "Rejected").

| Batch | Reviewed | First-pass Major | Confirmed and marked |
|---|---|---|---|
| QC_batch1 | 34 | 8 | 6 |
| QC_batch2 | 33 | 11 | 11 |
| QC_batch3 | 21 | 5 | 4 |
| QC_batch4 | 28 | 13 | 11 |
| total | 116 | 37 | 32 (4 downgraded to Minor, 1 unsure) |

The most common confirmed defect: a criterion that requires the gold's own choice, name or extra deliverable the
prompt never asks for, so correct work fails. Two were grader crashes (a 34-criterion judge group, a deck-audit
script that crashes on inherited font colours). What this does not establish: it reviews only tests at 0% in every
run, not tasks labelled "Almost 100% pass" or "no (100% pass)", and a CLEAN here is not a TFRL QC approval.
Tooling: `qc_review/REVIEW_BRIEF.md`, `VERIFY_BRIEF.md`, `apply_internal_fails.py` (Khiem's machine; the kit is also in this repo at `svc-pc-pipeline/tools/qc_zero_pass/`). Run at most 3
review agents at once; 15 at once crashed the session.

### Internal zero-pass review of QC_batch5 (2026-09-27)

Same method as batches 1 to 4, now the standing step after every batch (`/qc-zero-pass-review QC_batchN`; kit in
the team repo at `svc-pc-pipeline/tools/qc_zero_pass/`). 24 of the 80 tasks had a test at 0% in every agent run; all
24 "Dataset with runs" zips were downloaded with Khiem's OK and reviewed.

| Batch | Reviewed | CLEAN | MINOR | First-pass Major | Confirmed and marked |
|---|---|---|---|---|---|
| QC_batch5 | 24 | 9 | 2 | 13 | 13 |

Confirmed and marked: Rakesh Das 562, 596, 598, 601; Salman Arshad task_111, task_232, SCO-240, SCO-245, SCO-252,
SCO-265, LGL-191, GTM-184; Mácio Meneses MKT-176. Author messages: `ekw/2026-09-27-qc-batch5-internal-review-fails.md`
(adversarially checked; Khiem sends).

- **Most common defect:** a judge that never receives the files it grades against. task_111, LGL-191 and SCO-252's
  v16 fail runs as "fabricating" facts that are in source files the judge is not given.
- **Other defects:**
  - gold figures the sources contradict: SCO-240, SCO-245, SCO-265
  - criteria requiring items the prompt never asks for: 596, 601, task_232, GTM-184, MKT-176
  - one environment defect in 562: no LibreOffice and no recalculation, so correct live formulas read as NaN; six
    other batch 5 tasks recalculate before judging
- **Held for Khiem:** 598 is marked, but its prompt_tests_misalignment cell (consolidated EKW L516) says "Good"
  although the verify feedback calls the finding Major. The one-cell fix was blocked by the permission classifier.
- **Kit changes the same day:**
  - batches are discovered from the `bN` folders
  - `applied_tasks.json` makes each task marked once: a full-scope rerun would otherwise have re-rejected FIN-304,
    HLT-202, SVC-PC-65-0-0, SVC-PC-20-7-0 and GTM-163, which authors had moved on, and rewritten the cleared FIN-322
    and FIN-351 rows
  - a confirmed Major with no Major rating is held back

What this does not establish: it judges only tests at 0% in every run, the 56 other batch 5 tasks were not reviewed,
and a CLEAN is not a TFRL QC approval.

### Internal zero-pass review of QC_batch6 (2026-09-28)

Same method and kit. 29 of the 98 tasks had a test at 0% in every agent run; all 29 "Dataset with runs" zips were
downloaded with Khiem's OK and reviewed (five needed a re-trigger, two were staged by hand because the mover did not
match their filenames).

| Batch | Reviewed | CLEAN | MINOR | First-pass Major | Confirmed and marked |
|---|---|---|---|---|---|
| QC_batch6 | 29 | 19 | 7 | 4 | 3 |

Confirmed and marked: Sufiyan Ahmad Khan task_663; Tanush Banchhod task_508 (NUM-508-rewardkit); Khiem SVC-PC-77-0-0.
SVC-PC-14-1-0's first-pass Major (r-12) was refuted by the verifier and it is MINOR. Author messages:
`ekw/2026-09-28-qc-batch6-internal-review-fails.md` (adversarially checked; Khiem sends; 77-0-0 is Khiem's own task).

- **Defects:**
  - criteria requiring items the prompt never asks for: task_663 v8 (an L2 certification target within 60 days) and
    task_508 (four criteria: covenant list, share total, capitalised-interest share, lease-fee treatment)
  - a criterion formula that rejects correct work: SVC-PC-77-0-0 c07d defines retained stock as the sum of per-SKU
    floors, which overstates it when a SKU is below its floor; codex's release reproduces to the dollar and fails
  - one prompt ambiguity outside the zero list: task_663 v3 accepts only one of two readings of SOW 4.3
- **Eval-side problem found on the way:** the DataOS judge key hit its Anthropic usage limit ("You will regain access
  on 2026-10-01 at 00:00 UTC"). Four runs on 2026-09-28 about 08:18 to 08:27 UTC (task_FIN-408 eval_620357 and three
  task_SCO-136 oracles) scored 0.0 from verifier crashes. MKT-112's codex run and FIN-410's codex attempt 1 also died
  on agent-side errors (OpenAI quota, a missing codex dependency). None of these is a task defect.
- **Kit changes the same day:**
  - `zero_recompute.py` (new): rebuilds each task's zero list from the zip's own runs. The manifest's lists, built
    from the DataOS Test Results Matrix, missed 16 tests on SVC-PC-31-4-0 and undercounted others; reviewers now run
    it first. It handles criteria graded three times per run and reports the share of reward when weights do not sum
    to 1.0. It merges criteria that share a name across different verifiers (FIN-410), so check verifier ids there.
  - `apply_internal_fails.py` and `audit_marks.py` find the "QC batch" column by header. EKW gained an "offboarded"
    column that moved it from R to S, and the hard-coded index matched no rows.

What this does not establish: it judges only tests at 0% in every run (SVC-PC-56-1-0 and task_FIN-408 had one graded
agent run each, so their zero lists are single-run), the 69 other batch 6 tasks were not reviewed, and a CLEAN is not
a TFRL QC approval.

### Internal zero-pass screen of QC_batch8 (2026-09-29, before copying)

Same kit, but run on the candidates BEFORE the batch was copied, so fails never reach the batch dataset (Khiem: "run OUR
checks on them beforehand to screen out"). Headroom was read on all 99 candidates; 43 "Dataset with runs" zips were
downloaded (every task with a test at 0% in every run, no per-test results, or a matrix capped at 100 rows).

| Batch | First-pass verdicts | CLEAN | MINOR | First-pass Major | Confirmed and marked |
|---|---|---|---|---|---|
| QC_batch8 | 29 | 14 | 0 | 15 | 14, then 13 (FIN-237 downgraded to Minor, sent; MKT-188 withdrawn) |

TaskID-MKT-188 was marked and then WITHDRAWN the same day: Farhan showed its v4k parser requirement is grounded in the
task's hard-cases dossier (CHG-3B9D77 tagged to created_at parsing, ticket TCK-C5B240), which both review passes had
never searched. Sheet row 651 cleared (EQC Status and K:M blank, note kept under a withdrawal line) and tracker back to
"Submitted for Manual QC" (`qc_review/_scratch_mkt188_withdraw.py`, snapshot and read-back). It goes into the next
batch. This triggered a full-source re-audit of every marked fail (below) and a "search all sources" step in both briefs.

Confirmed and marked: Hasnain Khan task_305; Rakesh Das 601 (a resubmission, failing
on a new point); Adarsh R FIN-340, FIN-375; Yashvi Vora 395; Ezekiel Ogbu eng-108, phr-164; Momina Saleem FIN-214;
Ahsan Sarwar NUM-496; Khiem SCO-226, LGL-131, SCO-239, ENG-104. Author messages:
`ekw/2026-09-29-qc-batch8-fix-dms.md` in turing-context (Khiem sends).

- **Most common defect:** a criterion requiring something the prompt never asks for: 395 (a fallback plan), eng-108
  (a 12 vs 5 incident split), phr-164 (equity totals two ways, a cohort-ranking disclaimer), FIN-375 (naming missing
  PPA inputs), SCO-226 (late-order attribution), 601 (settling an open pre-2016 question).
- **Other defects:**
  - expected values the sources contradict: phr-164 workbook-32 ("nil for the others" against ten more holders in the
    ESOP export); task_305 v24, a band that rejects the agreement's own s6.1 method
  - a judge that does not receive the file holding the answer: FIN-340 v22b
  - citation criteria that accept one filing only: FIN-340 v27e/f/g
  - LGL-131 v6 (latent, both runs passed) misstates when the rental-license bar applies
- **Grader-side, not the author's rubric:** SCO-239's only confirmed Major is a judge timeout on 14 and 15 criterion
  groups (every criterion recorded 0.0), recurring from QC_batch7. NUM-496's checker parses a percent literal as N
  instead of N/100, so correct live formulas never release a shipset and score 0, and a 15-criterion judge group timed
  out on every sample in one run. Both are fixed by splitting the judge groups or fixing the checker in the task.

What this does not establish: it judges only tests at 0% in every run, batch tasks with no such test were not
reviewed, and a CLEAN is not a TFRL QC approval.

### Full-source re-audit of every marked internal fail (2026-09-29)

Triggered by the MKT-188 withdrawal. All 68 tasks the internal review had marked (batches 1 to 8, ledger
`qc_review/applied_tasks.json`) were re-judged finding by finding, after a text index of every solver-visible source
file (213 tasks, `qc_review/reaudit/index/`) was searched for each criterion's key terms, ids and figures
(`reaudit/reaudit_step1.csv`, method `reaudit/STEP2_METHOD.md`, results `reaudit/step2/`). Opus agents, at most 5 at
once. MKT-188 was run as a known-answer control and came back overturned.

| Result | Tasks |
|---|---|
| Fail stands | 66 (SVC-PC-49-8-0 contested: first re-judge overturned g-07/g-09, an independent second opinion kept the fail, so it stands) |
| Fail withdrawn | 1 (TaskID-MKT-188) |
| Unsure, then kept as a fail | 1 (LGL-131, Khiem's own: the service method is arguably sourced, but v4c5 requires a service date no source gives and the prompt bars unsupported facts; the golden pre-fills "August 29, 2026". Fail kept, Khiem 2026-09-29. Fix: accept a date left "complete at service" in v4c5 and v4d, and drop the pre-filled date from the golden) |

Findings inside standing tasks that were overturned individually: task_GTM-176 v9 (policy states escalation is
cumulative). Kit fix: `REVIEW_BRIEF.md` and `VERIFY_BRIEF.md` now require a search of every file under `environment/`
before calling a criterion unsourced or a 0% test a solver miss.

What this does not establish: it re-judged only findings the verifier had CONFIRMED on marked tasks; it does not
re-check tasks we called CLEAN, and it does not make any standing fail a TFRL QC verdict.

False-CLEAN probe, same day: the mechanical search flagged 274 SOLVER MISS calls whose expected value appears verbatim
in no source (169 at 1% weight or more). The 8 highest-weight, one per task, were re-judged
(`reaudit/FALSECLEAN_METHOD.md`, results `reaudit/falseclean/`): 8 of 8 SOLVER MISS calls hold, each expected value
recomputed exactly from the source data (task_hlt-254, task_FIN-374, task_626, task_fin-352, task_FIN-286,
task_FIN-384 v5, task_phr-156, SCO-201). The flag fires on derived values, so its measured precision is 0 of 8 and the
remaining 161 were not reviewed. This sample does not prove no CLEAN call is wrong; FIN-384's later TFRL QC Major was on
a different criterion.
