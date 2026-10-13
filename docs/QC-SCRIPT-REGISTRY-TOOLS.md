# Our QC scripts that are not checks

<!-- Written from the main branch at commit 7e64189. Part of the plain-English QC documentation set; see the appendix of QC-SOP-first-run.md. -->

The checks themselves are explained in [QC-SCRIPT-REGISTRY.md](QC-SCRIPT-REGISTRY.md). This page lists the other scripts: the ones that build, package, upload, record returns, regrade, report and keep the lanes running.

The scripts in this repository fall into two kinds: checks, which look at a task package and report a defect, and tools, which move the task along (build it, zip it, upload it, read DataOS's reply, regrade it, fix it, record it in a sheet, or keep the machines running). This section lists the tools, grouped by the stage of the work they belong to, and says for each one what it does, when it runs, who runs it, and what it reads and writes. The check scripts are written up in the check family sections; a short list at the end of this section names the ones that happen to sit in tool folders.

Words used below, defined once here:
- **DataOS**: the platform that grades uploaded tasks. **Pipeline 141** there ("ManualQC automated QC pipeline 4 Reviewers", version 8) runs five evaluation runs, then four identical Answer Check reviews (model reviewers that read the task and report problems as "major" or smaller findings); a task fails if any one review reports a major.
- **Task package**: the folder for one task: instruction.md (the prompt), the input files, the golden (the reference answer, kept in the solution folder), and the rubric (the list of criteria a grader scores an answer against, in judge.toml files for SVC or verifier.json for EKW). **SVC** and **EKW** are the two task families this repo handles.
- **Pipeline**: a fixed series of automated steps. **Verifier**: the files inside a task that grade an answer (verifier.json for EKW, the tests folder for SVC).
- **Oracle**: a grading run where the golden answer is graded against its own rubric; it should score 1.0.
- **Gate**: a check whose failure stops the task from moving to the next step. A **lint** is an automatic style and consistency check on text or settings.
- **Verify** (adversarial verify): an independent model reviewer tries to break the task and returns READY-TO-RESUBMIT or not. **Regrade**: re-scoring saved model answers against a changed rubric.
- **Lane**: one Claude Max account session on the sandbox (the remote machine) that fixes tasks; the **lane runner** is the script that drives one task on one lane. **Bundle**: one zip of many task zips, the unit uploaded to DataOS. **Tracker**: a shared Google Sheet of task status.
- **TFRL QC**: the human QC team that reviews batches of tasks that cleared the DataOS pipeline.
- **Mojibake**: garbled characters from text decoded with the wrong character set. **Harbor** and **reward-kit** (harbor-rewardkit): the task format and the grading library DataOS uses.
- **Who runs it**: roles are taken from the SOP (`docs/QC-SOP-first-run.md`; author, lane runner, manager, QC lead). Where a file says "laptop coordinator" or "coordinator", that means whoever runs the lanes from their own machine; where the file does not say, this section writes "not stated".

How to read the counts and the stage tables: the repository holds 561 script files (450 .py, 111 .sh) outside test files; the counting command is in `REG_TOOLS_COUNTS.txt`. Of these, 49 are registered checks covered in the family sections, 103 are copies of task templates and sample data, and the rest are listed below or in the short checks list at the end.

### Stage 1. Author pre-check

| Script | File | What it does in plain English | When it runs and who runs it | Reads or writes what |
|---|---|---|---|---|
| `svc_run_checks.py` | `deterministic-checks/svc_run_checks.py` | Runs every registered SVC check over a folder of task packages in one command and prints one table (one row per task and check). Also the place where the list of SVC checks (the CHECKS registry) lives. | Task author on their own machine before submitting (SOP section 3). | Reads the package tree (--root). Writes a results folder (--out-dir) with per-check JSON and a summary. |
| `ekw_run_checks.py` | `deterministic-checks/ekw/ekw_run_checks.py` | The EKW twin of svc_run_checks.py. First runs ekw_check_b.py, then every shared check, in one command. | Task author before submitting an EKW task (SOP section 3); the EKW lane also calls it via ekw_gate.py. | Reads the EKW task tree (--root). Writes a staged contract-shaped copy (--stage) and results (--out-dir). |
| `ekw_check_b.py` | `deterministic-checks/ekw/ekw_check_b.py` | "Check B" for EKW: confirms the EKW build produced a valid task package, then lays down a copy in the shape the shared checks expect so they run on EKW tasks unchanged. | Runs inside ekw_run_checks.py; not run alone in the usual flow. | Reads the EKW build. Writes the staged copy and check_b.json. |
| `run_all.py` | `deterministic-checks/run_all.py` | Batch runner: runs every applicable check script in the folder against one set of task packages and merges each script's own JSON report into one result. | Author or QC lead, by hand. The SOP names svc_run_checks.py and ekw_run_checks.py as the current entry points instead. | Reads the package tree. Writes one combined report. |
| `ekw_verifier_json.py` | `deterministic-checks/ekw_verifier_json.py` | Shared reader for EKW's tests/verifier.json file, so each check can read EKW rubrics the same way it reads SVC judge.toml files. | Imported by checks; nobody runs it directly. | Reads tests/verifier.json. |
| `ekw_tracker_writeback.py` | `deterministic-checks/ekw/ekw_tracker_writeback.py` | "Check H" for EKW: writes each task's check results into the EKW QC tracker sheet tab, after checking the sheet did not change under it, then reads the cells back. | After an ekw_run_checks.py run; who runs it not stated. | Reads summary.json and check_b.json from the results folder. Writes cells in the tracker sheet. |
| `workbook_recalc.py` | `deterministic-checks/workbook_recalc.py` | Fills in missing cached formula results in spreadsheets that were already collected, such as answers an AI model submitted during an evaluation run. | Run by hand when a spreadsheet shows blank formula results. | Reads and rewrites spreadsheet files. |
| `formula_cache_autofix.py` | `deterministic-checks/formula_cache_autofix.py` | Mechanical fixer: recalculates and stores the missing formula results that formula_health_check.py flags in golden workbooks. | Author or lane runner, after the health check flags a workbook. | Reads and rewrites the golden xlsx (the golden is the reference answer file). |
| `svc_formula_cache_autofix.py` | `svc-pc-pipeline/tools/svc_formula_cache_autofix.py` | SVC copy of the formula-result fixer above; reuses the health check's file discovery and per-cell logic. | Lane runner or author; the file does not say who. | Reads and rewrites golden workbooks in a package. |
| `svc_recalc_goldens.py` | `svc-pc-pipeline/tools/svc_recalc_goldens.py` | Restores formula results in golden workbooks that a Python library (openpyxl) round-trip stripped. | Run by hand or by a fix step after an edit. | Rewrites golden workbooks. |
| `svc_stray_backup_cleanup.py` | `svc-pc-pipeline/tools/svc_stray_backup_cleanup.py` | Deletes stray backup files left in a task's solution/files folder, with safety checks. | Author or lane runner before packaging. | Reads and deletes files in the golden folder. |
| `svc_stray_backup_cleanup.py` | `deterministic-checks/tools/svc_stray_backup_cleanup.py` | Another version of the same cleanup, under deterministic-checks/tools (the two files differ). | Same as above. | Same as above. |
| `svc_fix_duplicate_criterion_ids.py` | `svc-pc-pipeline/tools/svc_fix_duplicate_criterion_ids.py` | Repairs criterion ids that lost a trailing zero (1.10 stored as 1.1), because two rows sharing an id break the weight lookup. | Author or lane runner after the duplicate-id check flags a rubric. | Rewrites the rubric file. |
| `svc_fix_mojibake_names.py` | `svc-pc-pipeline/tools/svc_fix_mojibake_names.py` | Fixes garbled characters (mojibake: text decoded with the wrong character set) in file and folder names and the config paths that point at them. | Author or lane runner after the mojibake check flags a package. | Renames files and edits config paths. |
| `svc_split_grammar_dirs.py` | `svc-pc-pipeline/tools/svc_split_grammar_dirs.py` | Splits a grading folder that has too many criteria into smaller folders, because DataOS's grader fails on more than about 15 criteria in one folder. | Lane runner or author before packaging. | Rewrites the tests folder layout and weights. |
| `svc_trim_oversized_databooks.py` | `svc-pc-pipeline/tools/svc_trim_oversized_databooks.py` | Shrinks golden workbooks that are over 1 MB, because the grading library (rewardkit) silently skips attachments over that size. | Author or lane runner before packaging. | Rewrites golden workbooks. |
| `svc_prescreen_extract.py` | `svc-pc-pipeline/tools/svc_prescreen_extract.py` | Reproduces the text the DataOS judge model would receive for a task, without calling DataOS. | Run by hand when DataOS's judge was returning errors. | Reads a package. Writes extracted text. |
| `svc_harbor_preflight.py` | `svc-pc-pipeline/tools/svc_harbor_preflight.py` | Checks a batch against the Harbor operator guide before anything is uploaded to cloud storage. | Whoever fires evaluation runs; the file does not name a role. | Reads the batch folder. |
| `check_references.py` | `skills/svc/source-file-reference-check/scripts/check_references.py` | Checks whether the input files an SVC task's instruction.md names exist in the package. Packaged as a skill, so it can run for one task. | Author, by hand, as a skill. | Reads instruction.md and the environment folder. |
| `check_synthetic_markers.py` | `skills/svc/synthetic-marker-scan/scripts/check_synthetic_markers.py` | Scans instruction.md and the data folder for leftover traces of the generation process (such as bracket labels). | Author, by hand, as a skill. | Reads the task folder. |
| `ooxml_edit.py` | `svc-pc-pipeline/tools/ooxml_edit.py` | Edits text inside one part of an xlsx, xlsm, docx or pptx file byte for byte, so nothing else in the file changes. | Called by apply_plan.py; also usable by hand. | Rewrites one part inside an Office zip file. |

### Stage 2. Build and package

| Script | File | What it does in plain English | When it runs and who runs it | Reads or writes what |
|---|---|---|---|---|
| `svc_prefilter.py` | `svc-pc-pipeline/tools/svc_prefilter.py` | Quick rule-based screen of a package before the upload zip is built. Spots hard defects (too many criteria in one folder, a missing file path, an answer-key leak, a leftover lease.json) without any model call. Hard defects stop the build. | Run by svc_build_upload_zip.py (Gate 1); also by hand. | Reads the package. Prints findings. |
| `svc_build_upload_zip.py` | `svc-pc-pipeline/tools/svc_build_upload_zip.py` | The only approved way to build the DataOS upload zip for one task. Refuses to build unless: the screen has no hard defects, the adversarial verify record says READY-TO-RESUBMIT and is newer than the last edit, the regrade record says PASS and is newer than the last edit, the task is not on the accepted list (a task DataOS already passed is never re-touched), and the tests folder is not byte-identical to the last rejected version. Writes a manifest next to the zip. | Author for a first grade (SOP section 6a, item 8, with --first-grade); lane runner for fixed tasks. | Reads the package, verify and regrade records, accepted list and the last-reject fingerprint. With --first-grade (a task DataOS never graded) the regrade and identical-resubmit checks do not apply and the tool proves the task is absent from every return zip. Writes <task>.zip and <task>.zip.manifest.json. |
| `svc_ship_manifest.py` | `svc-pc-pipeline/tools/svc_ship_manifest.py` | Shared freshness rules: a per-task zip is shippable only while the package, the zip, the verify record and the regrade record all still hash to what the builder recorded. A library, not a command. | Imported by the zip builder and the bundler. | Reads zips, manifests, records. Writes manifests. |
| `svc_diff_before_ship.py` | `svc-pc-pipeline/tools/svc_diff_before_ship.py` | Refuses to ship a rebuilt package that silently got worse than the last version confirmed good. | Before shipping; the file does not name who runs it. | Reads the old and new package. |
| `svc_verify_package.py` | `svc-pc-pipeline/tools/svc_verify_package.py` | Post-build check of a built SVC package (the structure and rubric it ended up with). | After a build. | Reads the built package. |
| `svc_write_ready_markers.py` | `svc-pc-pipeline/tools/svc_write_ready_markers.py` | Puts a ready marker file (.harbor_package_ready) on the newest revision of audited tasks so the evaluation worker picks them up. | Coordinator, by hand. | Writes marker files. |
| `svc_preship_gate.sh` | `svc-pc-pipeline/tools/svc_preship_gate.sh` | Last stop-or-go check before shipping (a gate): runs the static rubric check and other hard checks and says SHIPPABLE or not. | Lane runner or author. | Reads a package. Prints a verdict. |
| `svc_v7_batch_precheck.sh` | `svc-pc-pipeline/tools/svc_v7_batch_precheck.sh` | One more look at everything in the ready folder before the user spends DataOS grades on it; re-runs the stop checks to catch drift. | Before an upload (coordinator). | Reads the ready folder. |
| `svc_stage_upload.py` | `svc-pc-pipeline/tools/svc_stage_upload.py` | Collects built packages from several build trees into one tree and zips them as one DataOS upload. | By hand; older method. | Reads build trees. Writes a zip. |
| `svc_stage_upload.py` | `deterministic-checks/tools/svc_stage_upload.py` | A second version of the same staging script. | Same. | Same. |
| `svc_fast_zip.py` | `svc-pc-pipeline/tools/svc_fast_zip.py` | Zips a set of built packages straight from a build tree using the 7z program (faster than the staging script). | By hand. | Reads build tree. Writes a zip. |
| `svc_fast_zip.py` | `deterministic-checks/tools/svc_fast_zip.py` | Identical copy of svc_fast_zip.py (the files are byte for byte the same). | Same. | Same. |
| `ekw_raw_to_rewardkit.py` | `svc-pc-pipeline/tools/ekw_raw_to_rewardkit.py` | Converts a raw EKW task (new task-id prefixes such as GTM, HLT, MKT) into the package shape DataOS grades, the same shape SVC ships. | EKW lane, by ekw_intake.py. | Reads a raw EKW task. Writes the converted package. |
| `ekw_intake.py` | `svc-pc-pipeline/tools/ekw_intake.py` | EKW intake for the fix lanes: cleans up a raw task pulled from Drive, checks it and builds it. | EKW lane runner. | Reads pulled tasks. Writes normalised packages. |
| `ekw_pull_drive.py` | `svc-pc-pipeline/tools/ekw_pull_drive.py` | Pulls raw EKW task folders from Google Drive to a local folder (read-only on Drive). | EKW lane, before intake. | Reads Drive. Writes local folders. |
| `convert.py` | `skills/ekw/ekw-to-dataos-harbor/scripts/convert.py` | Converts an EKW task into the DataOS Harbor format; part of a skill. | Author or QC lead, by hand. | Reads an EKW task. Writes a converted task. |
| `detect_genre.py` | `skills/ekw/ekw-to-dataos-harbor/scripts/detect_genre.py` | Works out whether a task is EKW or DermOTS shaped, so the right conversion runs. | Called by convert.py. | Reads the task. |
| `to_dataos_harbor.py` | `skills/ekw/ekw-to-dataos-harbor/scripts/to_dataos_harbor.py` | Converts an internal harbor task into DataOS harbor shape without the reward-kit conversion. Byte for byte the same as pipeline/tools/to_dataos_harbor.py. | By hand, as a skill. | Reads and writes task folders. |
| `to_rewardkit.py` | `skills/ekw/ekw-to-dataos-harbor/scripts/to_rewardkit.py` | Converts an old-format task (verifier.json plus a verifier library) into the reward-kit format DataOS uses. Differs from pipeline/tools/to_rewardkit.py. | By hand, as a skill. | Reads and writes task folders. |
| `to_rewardkit.py` | `skills/ekw/harbor-rewardkit-convert/scripts/to_rewardkit.py` | A second copy of the reward-kit converter inside another skill. Differs from the other two copies. | By hand, as a skill. | Reads and writes task folders. |
| `rewardkit_convert.py` | `skills/ekw/harbor-rewardkit-convert/scripts/rewardkit_convert.py` | Wrapper that detects the task type, picks an output folder, runs the conversion, then validates the result against constraints that broke uploads before. | By hand, as a skill. | Reads and writes task folders. |
| `to_rewardkit.py` | `pipeline/tools/to_rewardkit.py` | The reward-kit converter in the pipeline folder (1,423 lines). Turns verifier.json plus a verifier library into the format used on DataOS. | Run by svc_pc_batch_convert.py and by hand. | Reads and writes task folders. |
| `to_dataos_harbor.py` | `pipeline/tools/to_dataos_harbor.py` | Converts an internal harbor task into DataOS harbor shape without the reward-kit step. | By hand. | Reads and writes task folders. |
| `rewardkit_convert.py` | `pipeline/tools/rewardkit_convert.py` | Wrapper that auto-detects task type and validates the conversion. | By hand. | Reads and writes task folders. |
| `rewardkit_mean_of_3.py` | `pipeline/tools/rewardkit_mean_of_3.py` | Gives a reward-kit package three judge samples per chunk and averages them, because one judge call can flip a verdict on identical bytes. | By hand. | Rewrites judge settings in a package. |
| `rubric_xlsx_to_verifier.py` | `pipeline/tools/rubric_xlsx_to_verifier.py` | Converts a loose "Grading Rubric" spreadsheet into this project's verifier.json format. | Run by svc_pc_batch_convert.py. | Reads a rubric xlsx. Writes verifier.json. |
| `assemble_task.py` | `pipeline/tools/assemble_task.py` | Turns an expert's loose pieces (prompt, source files, solution files, verifier JSON) into one task folder the QC engine can load. SVC tasks also get a data.dvc pointer file. | Run by svc_pc_batch_convert.py and by the expert-facing QC skill. | Reads the loose pieces. Writes a task folder (--out). |
| `svc_pc_batch_convert.py` | `pipeline/tools/svc_pc_batch_convert.py` | Converts every SVC task in the fetched folder to DataOS reward-kit format in three steps: rubric spreadsheet to verifier.json, assemble the task, then reward-kit conversion. | Whoever refreshes the SVC set; not stated in the file. | Reads pipeline/data/svc_pc_qc/00_fetched. Writes converted tasks. |
| `sync_templates.py` | `pipeline/tools/sync_templates.py` | Keeps the two copies of the verifier library (in pipeline/templates/harbor and in the ekw-to-dataos-harbor skill) identical to the canonical copy in pipeline/templates/dataos_harbor. `--check` lists differences and exits 1; `--write` refreshes the copies. | Whoever changes the templates (QC lead); by hand. | Reads and rewrites template files. |

### Stage 3. Upload and bundle

| Script | File | What it does in plain English | When it runs and who runs it | Reads or writes what |
|---|---|---|---|---|
| `svc_bundle_upload.py` | `svc-pc-pipeline/tools/svc_bundle_upload.py` | The only approved way to assemble a multi-task SVC upload bundle and to re-check one before upload. For every task it recomputes the package hash, the zip hash and the verify and regrade record hashes and compares them to the builder's manifest; any difference drops the task from the bundle and prints why. `bundle` builds, `check` re-checks before upload (its exit code is what to gate on). | QC lead or lane runner on the sandbox (SOP section 6a, item 8). | Reads per-task zips, manifests, records. Writes <bundle>.zip, <bundle>.manifest.json, and a shipped record per task. |
| `ekw_bundle_upload.py` | `svc-pc-pipeline/tools/ekw_bundle_upload.py` | The EKW twin of svc_bundle_upload.py. | EKW lane or QC lead. | Same as the SVC bundler, over EKW work folders. |
| `svc_split_bundle.py` | `svc-pc-pipeline/tools/svc_split_bundle.py` | Splits a bundle that is not yet uploaded into two so each is under DataOS's 500 MB zip limit. | QC lead on the sandbox. | Moves bundle records and zip; writes two bundles. |
| `svc_pipe_batch_pull.py` | `svc-pc-pipeline/tools/svc_pipe_batch_pull.py` | Pulls pipeline zips from the sandbox and stages one DataOS batch (copies each zip, tests it, builds the upload). | Coordinator on the laptop. | Reads sandbox zips. Writes a staged batch. |
| `batch_stager.sh` | `svc-pc-pipeline/sandbox_root/batch_stager.sh` | Bundles tasks that passed the gate into submission zips of at most 480 MB from current bytes; never re-stages a task already recorded. | Run on the sandbox by the coordinator. | Reads passed tasks. Writes zips and a staging record. |
| `dataos_submission.py` | `pipeline/tools/dataos_submission.py` | Prepares a DataOS QC submission package from a bundled EKW cycle: everything needed before the manual DataOS steps. | QC lead. | Reads a cycle folder. Writes a submission package. |
| `harbor_evals.py` | `pipeline/tools/harbor_evals.py` | Automates the Harbor-beta evaluation request steps (the PowerShell guide) for a batch. | Whoever requests evaluation runs. | Uploads a batch; reads and writes run status. |
| `bundle.py` | `pipeline/tools/bundle.py` | Packs one task's audit into a shareable folder and zip. | By hand. | Reads audit outputs. Writes folder and zip. |
| `svc_harbor_fire_gemini.py` | `svc-pc-pipeline/tools/svc_harbor_fire_gemini.py` | Starts Gemini evaluation runs still short of ten per task, with staging guards. | Whoever fires evaluation runs. | Reads run state. Starts runs. |
| `svc_harbor_fire_gemini38.py` | `svc-pc-pipeline/tools/svc_harbor_fire_gemini38.py` | Starts Gemini 3.8 Flash runs on the 40 published SVC tasks. | Same. | Same. |

### Stage 4. Return intake from DataOS

| Script | File | What it does in plain English | When it runs and who runs it | Reads or writes what |
|---|---|---|---|---|
| `svc_dataos_returns_parse.py` | `svc-pc-pipeline/tools/svc_dataos_returns_parse.py` | Reads a DataOS return zip: per task the oracle and solver rewards and the Answer Check review verdicts. Applies the pass rule (patched 2026-10-05): a task passes only with at least 2 reviews and every review read with zero majors. Any major, or an unreadable review, fails it. (The oracle is the run where the golden answer is graded against its own rubric.) | Called by the record-return tools; QC lead by hand. | Reads the *_with_runs.zip. Writes returns.json and extracted review files. |
| `svc_record_return.py` | `svc-pc-pipeline/tools/svc_record_return.py` | Takes in one DataOS return for SVC: passes go on the accepted list (never touched again), rejects get the fingerprint of the graded bytes saved, old verify, regrade and zip records archived, and the task goes to the head of the queue. Dry run unless --apply. | QC lead on the sandbox (SOP section 6b). | Reads the return zip. Writes accepted.txt, lastreject.sha, archives, queue.txt, a copy of the return in _returns/. |
| `ekw_record_return.py` | `svc-pc-pipeline/tools/ekw_record_return.py` | The EKW twin of svc_record_return.py: same pass rule, same fingerprint, same archive-and-requeue. | QC lead on the sandbox. | Same, in the EKW work folder. |
| `svc_requeue_qc_reject.py` | `svc-pc-pipeline/tools/svc_requeue_qc_reject.py` | Sends tasks that passed DataOS but a human reviewer then rejected back to the lanes (SVC or EKW). | QC lead on the sandbox. | Writes queue and archive records. Dry run unless --apply. |
| `svc_harvest_all_returns.py` | `svc-pc-pipeline/tools/svc_harvest_all_returns.py` | Collects every DataOS return across all rounds into durable files. | Coordinator on the laptop. | Reads *_with_runs zips in Downloads. Writes harvest files. |
| `svc_harvest_dataos_findings.py` | `svc-pc-pipeline/tools/svc_harvest_dataos_findings.py` | Builds one repair table of every review finding from all graded rounds. | Coordinator. | Reads return zips. Writes a table. |
| `svc_return_cohort.py` | `svc-pc-pipeline/tools/svc_return_cohort.py` | Pass rate by cohort for one return zip. | By hand. | Reads the return zip. |
| `svc_build_directed_briefs.py` | `svc-pc-pipeline/tools/svc_build_directed_briefs.py` | Writes one complete fix brief per rejected task from every DataOS review it has had. | Coordinator, after harvesting returns. | Reads harvest output. Writes briefs. |
| `svc_dataos_fix_brief.py` | `svc-pc-pipeline/tools/svc_dataos_fix_brief.py` | Prints the fix brief for one task: the locked rules plus that task's exact DataOS findings. | Called by the lane fixer script. | Reads findings JSON. |
| `direct_fix_brief.py` | `svc-pc-pipeline/tools/direct_fix_brief.py` | Prints the brief for one direct-fix agent: every open DataOS major joined with its verify ruling. | Called by direct_fix.sh. | Reads findings and verify output. |
| `batch10_notes.py` | `svc-pc-pipeline/tools/batch10_notes.py` | Writes a DIRECT-FIX-NOTE.md for every task with batch-10 DataOS majors. | Coordinator. | Reads batch10_majors.csv. Writes notes. |
| `build_dataos_union.py` | `svc-pc-pipeline/tools/build_dataos_union.py` | Joins DataOS's own findings files into one file of reviewer findings for the 30 tasks of that run. | Coordinator. | Reads majors and status files. |
| `build_fixer_copies.py` | `svc-pc-pipeline/tools/build_fixer_copies.py` | Rebuilds frozen, aligned copies of those findings files that fix_from_dataos.sh reads. | Coordinator. | Writes majors.csv and status.csv copies. |
| `build_review_union.py` | `svc-pc-pipeline/tools/build_review_union.py` | Builds one findings file for a task from everything that blocks it (two reviewers plus deterministic findings). | Called by fix_from_reviews.sh. | Reads reviews. Writes findings. |
| `eval_evidence_sweep.py` | `deterministic-checks/eval_evidence_sweep.py` | Turns a DataOS with_runs bundle into a per-task worklist: criteria the golden fails, criteria most solver runs fail. | QC lead, by hand. | Reads the bundle. Writes a worklist. |
| `svc_eqc_manual_qc_sync.py` | `svc-pc-pipeline/tools/svc_eqc_manual_qc_sync.py` | Propagates "EQC done" from the consolidated tracker to "Done - Manual QC passed" in the other tracker. | QC lead. | Reads and writes sheets. |

### Stage 5. Regrade and oracle

| Script | File | What it does in plain English | When it runs and who runs it | Reads or writes what |
|---|---|---|---|---|
| `svc_eval_regrade.py` | `svc-pc-pipeline/tools/svc_eval_regrade.py` | Re-grades the real answers DataOS's models produced (saved inside the return zip) against the fixed rubric, before another DataOS round is spent. Direction A: a correct-but-different answer the old rubric wrongly failed must now pass. Direction B: a hollow answer the old rubric wrongly passed must now fail on the added criterion. `reproduce` confirms the reject can be reproduced; `regrade` writes the <task>.regrade.json record the zip builder demands. | Author on a resubmission (SOP section 6a, item 6) and the lane runner. | Reads the return zip and the tests folder. Writes <task>.regrade.json. The `regrade` step calls judge_emulate.py for the model re-grade; `reproduce` uses only the standard library. |
| `judge_emulate.py` | `svc-pc-pipeline/tools/judge_emulate.py` | Local judge emulator: grades one task the way DataOS's grading library does, but sends the judge call through the Claude Code command line (no API key). Used for the oracle run (the golden answer graded against its own rubric, which must score 1.0), a deliverable run, or an echo probe. Never writes inside the task folder; `--dry-run` makes no model call. | Author (SOP section 6a, item 5, twice) and lane runner. | Reads tests, instruction.md, solution/files. Prints or writes scores. |
| `svc_coverage_trace.py` | `svc-pc-pipeline/tools/svc_coverage_trace.py` | Coverage trace: `list` numbers every requirement in instruction.md (R01, R02, ...) with a short hash; `check` verifies a map file covers every requirement with a named criterion or a logged NOT-A-REQUIREMENT note. Exit 0 clean, 1 uncovered, 2 bad map. It proves no requirement was skipped; it does not judge whether the named criterion really grades it. | Author (SOP section 6a, item 3) and the lane runner. | Reads instruction.md and the map file. |
| `svc_discover017_check.py` | `svc-pc-pipeline/tools/svc_discover017_check.py` | Loads each task's tests folder with reward-kit 0.1.7's discover(), the loader DataOS runs at upload, to catch packages DataOS would silently drop. | Before upload; the file does not name who runs it. | Reads tests folders. |
| `oracle_refresh.py` | `svc-pc-pipeline/tools/oracle_refresh.py` | Re-runs the oracle probe for tasks whose staged bytes changed after the probe. | Lane or coordinator. | Reads task bytes. Writes probes/oracle.json. |
| `oracle_refresh_all.sh` | `svc-pc-pipeline/tools/oracle_refresh_all.sh` | Re-runs judge_emulate.py's oracle (3 runs) on the current bytes of each listed task, rotating over lanes. | Coordinator. | Same. |
| `oracle_stale_audit.py` | `svc-pc-pipeline/tools/oracle_stale_audit.py` | For every task on the zip-only list, says whether its oracle result is older than the task's newest shipped byte. | Coordinator. | Reads probe and task timestamps. |
| `oracle_golden_check.py` | `pipeline/tools/oracle_golden_check.py` | Local half of an oracle run: stages a task's golden as the agent's output, runs solve.sh the way Harbor does, then runs the real verifier over it. | By hand. | Reads a task. Writes a run folder. |
| `_oracle_sweep.sh` | `svc-pc-pipeline/sandbox_root/_oracle_sweep.sh` | Oracle sweep: golden reward for each static-clean candidate, in parallel across lanes. | Coordinator on the sandbox. | Reads candidates. Writes scores. |
| `_oracle_sweep_param.sh` | `svc-pc-pipeline/sandbox_root/_oracle_sweep_param.sh` | Same sweep with the task list and output folder as arguments. | Same. | Same. |
| `_step0_oracle.sh` | `svc-pc-pipeline/sandbox_root/_step0_oracle.sh` | Runs the oracle gate on the exact bytes shipped in batch 15 to count how many goldens score below 1.0. | Coordinator, one-off. | Reads batch bytes. Writes scores. |
| `_preship_gate.sh` | `svc-pc-pipeline/sandbox_root/_preship_gate.sh` | Pre-ship gate: oracle score of at least 1.0, plus the other deterministic checks the file lists. | Coordinator. | Reads packages. |
| `_assemble_ready_wave.sh` | `svc-pc-pipeline/sandbox_root/_assemble_ready_wave.sh` | Assembles the ready pool from the oracle sweep into tier 1 (oracle 1.0) and tier 2 (oracle unverified). | Coordinator. | Reads sweep output. Writes the ready pool. |
| `svc_rubric_growth_diff.py` | `svc-pc-pipeline/tools/svc_rubric_growth_diff.py` | Flags criteria a rebuild added or grew compared with the last graded rubric (fixes should delete or loosen, not add). | Lane runner or author before building. | Reads two rubrics. |
| `solver_run.sh` | `svc-pc-pipeline/tools/solver_run.sh` | Runs one task through a model solver (GLM through a proxy), then grades the produced deliverable. | Coordinator on the sandbox. | Writes solver run folders. |
| `solver_batch.sh` | `svc-pc-pipeline/tools/solver_batch.sh` | Runs the model solver across the queued tasks (two runs each) to grade later. | Coordinator. | Writes run folders. |
| `solver_batch_list.sh` | `svc-pc-pipeline/tools/solver_batch_list.sh` | Same, limited to a list of tasks. | Coordinator. | Same. |
| `solver_grade.sh` | `svc-pc-pipeline/tools/solver_grade.sh` | Grades a task's solver runs. | Coordinator or driver. | Reads run folders. Writes grades. |
| `adjudicate_task.sh` | `svc-pc-pipeline/tools/adjudicate_task.sh` | Grades both solver runs against the current rubric, then judges every criterion that both runs failed (a solver error or a wrongly strict criterion). | Coordinator or adjudicate_loop.sh. | Writes ADJUDICATE.json. |
| `adjudicate_batch.sh` | `svc-pc-pipeline/tools/adjudicate_batch.sh` | Runs adjudicate_task.sh over a list of tasks, three at a time, pausing when the machine is busy. | Coordinator. | Same. |
| `adjudicate_loop.sh` | `svc-pc-pipeline/tools/adjudicate_loop.sh` | Keeps the adjudication result fresh for every task in the ready pool. | Left running on the sandbox. | Same. |
| `gather_both_failed.py` | `svc-pc-pipeline/tools/gather_both_failed.py` | Builds the section of the review prompt listing criteria both solver runs failed. | Called by gate_task.sh. | Reads solver run results. |
| `eval_counting.py` | `svc-pc-pipeline/tools/eval_counting.py` | One shared rule for which evaluation trials count for a task, replacing four copies that disagreed. | Imported by other scripts. | Reads run status. |
| `score_acceptance.py` | `svc-pc-pipeline/tools/score_acceptance.py` | Scores review results against the stated fact rather than the check id, for the verifier acceptance test. | Coordinator. | Reads review results. |
| `zero_recompute.py` | `svc-pc-pipeline/tools/qc_zero_pass/zero_recompute.py` | Recomputes each task's zero-pass tests (tests that no solver run passed) from the zip's own runs and diffs them against manifest.json. | QC lead, for a human QC batch. | Reads task zips. Writes a diff. |

### Stage 6. Fix and review helpers

| Script | File | What it does in plain English | When it runs and who runs it | Reads or writes what |
|---|---|---|---|---|
| `svc_v7_lane_runner.sh` | `svc-pc-pipeline/sandbox_root/svc_v7_lane_runner.sh` | The lane runner: fixes one task on one lane with an internal loop of up to 10 attempts: fix, oracle, regrade, adversarial verify, coverage trace, oracle confirm, gated zip. Leaves a verified zip in the ready folder or a logged reason. (A lane is one Claude Max account session.) | Started by svc_v7_pool.sh on the sandbox. | Reads and edits the task package. Writes the ready zip, verify, regrade, logs. |
| `svc_v7_lane_runner.sh` | `svc-pc-pipeline/tools/svc_v7_lane_runner.sh` | Tools copy of the lane runner; differs from the sandbox_root copy. | Same. | Same. |
| `svc_v7_pool.sh` | `svc-pc-pipeline/sandbox_root/svc_v7_pool.sh` | Work-stealing pool: one worker per working lane, each running the lane runner on queued tasks; claims a task with an atomic mkdir so two lanes never take the same one. | Started by the scale-up daemon; stopped with a POOL_STOP file. | Reads queue.txt. Writes claims and logs. |
| `svc_v7_pool.sh` | `svc-pc-pipeline/tools/svc_v7_pool.sh` | Tools copy of the pool script; differs from the sandbox_root copy. | Same. | Same. |
| `ekw_v1_lane_runner.sh` | `svc-pc-pipeline/tools/ekw_v1_lane_runner.sh` | The EKW twin of the lane runner: gate, then a targeted fix fed the specific finding, in a loop. | EKW lane pool. | Same, in the EKW work folder. |
| `ekw_v1_claim.sh` | `svc-pc-pipeline/tools/ekw_v1_claim.sh` | Atomically claims the next unclaimed EKW task for a lane. | Called by the EKW lane pool. | Writes a claim folder. |
| `ekw_gate.py` | `svc-pc-pipeline/tools/ekw_gate.py` | Runs EKW's own check registry (ekw_run_checks.py) over one task and gives one verdict. | EKW lane runner. | Reads a task. Prints a verdict. |
| `svc_triage_queue.py` | `svc-pc-pipeline/tools/svc_triage_queue.py` | Orders the lane queue by expected effort: pinned first, then near-misses, then fewest majors; marks tasks with 2 or fewer majors for targeted fixing. | Coordinator (--apply). | Reads findings. Writes queue.txt, targeted.txt. |
| `svc_dataos_fix.sh` | `svc-pc-pipeline/tools/svc_dataos_fix.sh` | Directed fixer: one Sonnet agent per task, given that task's exact DataOS findings. | Coordinator on the lanes. Same file in sandbox_root. | Edits task packages. |
| `svc_dataos_overnight.sh` | `svc-pc-pipeline/tools/svc_dataos_overnight.sh` | Overnight directed fix plus deterministic verify, started and left to run on the lanes. | Coordinator. The sandbox_root copy differs. | Edits packages. Writes results. |
| `svc_dataos_queue_and_zip.sh` | `svc-pc-pipeline/tools/svc_dataos_queue_and_zip.sh` | Waits for a run to finish, then runs fixes, then builds resubmit zips from verified tasks. | Coordinator. Same file in sandbox_root. | Writes zips. |
| `svc_fullsweep_fill.sh` | `svc-pc-pipeline/tools/svc_fullsweep_fill.sh` | Full-coverage-sweep fixer for tasks DataOS has not graded yet, filling idle lanes. | Coordinator. Same in sandbox_root. | Edits packages. |
| `svc_fullsweep_pool.sh` | `svc-pc-pipeline/tools/svc_fullsweep_pool.sh` | Work-stealing pool for the same sweep, one worker per lane. | Coordinator. Same in sandbox_root. | Edits packages. |
| `svc_scaleup_daemon.sh` | `svc-pc-pipeline/tools/svc_scaleup_daemon.sh` | Waits for a GO signal, then starts the pool detached so it survives the laptop closing. | Coordinator. Same in sandbox_root. | Starts the pool. |
| `svc_v7_rearm.sh` | `svc-pc-pipeline/tools/svc_v7_rearm.sh` | Cron entry that re-arms the scale-up daemon after a crash or reboot. | Cron, every minute. Same in sandbox_root. | Starts the daemon. |
| `svc_v7_stop.sh` | `svc-pc-pipeline/tools/svc_v7_stop.sh` | Stops the daemon, pool and in-flight rebuilds cleanly. | Coordinator. Same in sandbox_root. | Kills processes. |
| `svc_release_launch.sh` | `svc-pc-pipeline/tools/svc_release_launch.sh` | Releases stuck tasks (claims moved aside, retries reset, back in queue) and launches them on free lanes. | Coordinator. | Edits claim folders. |
| `direct_fix.sh` | `svc-pc-pipeline/tools/direct_fix.sh` | One Claude agent per task, end to end: brief from the open DataOS majors, an Opus fix inside the package. | Coordinator. | Edits a package. |
| `finish_direct_fix.sh` | `svc-pc-pipeline/tools/finish_direct_fix.sh` | After a fix agent reports: releases the lock and runs both reviewers at the next round. | Coordinator. | Writes review files. |
| `fix_from_dataos.sh` | `svc-pc-pipeline/tools/fix_from_dataos.sh` | Fix round driven by DataOS's own findings used as the reviewer. | Coordinator on the laptop. | Edits packages. |
| `fix_from_dataos_r3.sh` | `svc-pc-pipeline/tools/fix_from_dataos_r3.sh` | Third pass of the same over a target list. | Coordinator. | Same. |
| `fix_from_reviews.sh` | `svc-pc-pipeline/tools/fix_from_reviews.sh` | Drives one fix round per task from the two reviewers' round-0 findings. | Coordinator. | Edits packages. Writes round counters. |
| `fix_priority_loop.sh` | `svc-pc-pipeline/tools/fix_priority_loop.sh` | Second scan loop that watches the priority list for the fix dispatcher. | Coordinator. | Reads the priority file. |
| `fixes_evidence.sh` | `svc-pc-pipeline/tools/fixes_evidence.sh` | Shows whether the day's fixes did anything (no model calls). | By hand. | Reads logs. |
| `apply_plan.py` | `svc-pc-pipeline/tools/apply_plan.py` | Applies a fix plan's list of edits to the task files byte for byte and logs each in FIX-LOG.md. | gate_task.sh and the coordinator. | Edits task files. Writes FIX-LOG.md. |
| `apply_k_sentence.py` | `svc-pc-pipeline/tools/apply_k_sentence.py` | Appends a stock sentence about cached formula values to instruction.md and task_prompt.txt for tasks with an xlsx deliverable. | Fix step. | Edits two text files. |
| `judge_files_source_fix.py` | `svc-pc-pipeline/tools/judge_files_source_fix.py` | Fixes criteria that grade a named source file without being given it. | Fix step. | Edits rubric files. |
| `metadata_populate.py` | `svc-pc-pipeline/tools/metadata_populate.py` | Fills task.toml [metadata] for every SVC task from the task's own text. | Fix step. | Edits task.toml. |
| `metadata_classify_glm.py` | `svc-pc-pipeline/tools/metadata_classify_glm.py` | Fills domain, occupation and subdomain in task.toml using a GLM model through a proxy. | Fix step. | Edits task.toml. Makes model calls. |
| `metadata_verify.py` | `svc-pc-pipeline/tools/metadata_verify.py` | Asks the metadata-leak check whether a metadata edit cleared the finding. | Fix step. | Reads task.toml. |
| `render_guard_apply.py` | `svc-pc-pipeline/tools/render_guard_apply.py` | Applies a render guard for solver deliverables over 1 MiB (rewardkit skips those silently). | Fix step. | Edits packages. |
| `gate_task.sh` | `svc-pc-pipeline/tools/gate_task.sh` | Scripted GATE-V2 run (the name the script gives its own one-task flow) for one task, with model calls at exactly three points: a blind comprehensive review, a fix plan, and a judgment of criteria both solver runs failed. | Coordinator, via pipe_batch.sh. | Writes artifacts under stream-pipe/<task>/. |
| `pipe_batch.sh` | `svc-pc-pipeline/tools/pipe_batch.sh` | Runs gate_task.sh over the whole queue, detached. | Coordinator on the sandbox. | Writes pipeline logs. |
| `assemble_gate.py` | `svc-pc-pipeline/tools/assemble_gate.py` | Builds GATE.md for a task from what gate_task.sh left behind. No model call. | Called by gate_task.sh. | Reads stream-pipe/<task>/. Writes GATE.md. |
| `gate_check.sh` | `svc-pc-pipeline/tools/gate_check.sh` | Single-task packaging gate: builds the findings block, renders the prompt, runs the review. | Coordinator. | Writes a verdict. |
| `gate_detfindings.py` | `svc-pc-pipeline/tools/gate_detfindings.py` | Builds the deterministic findings block for the gate review prompt. | Called by gate_check.sh. | Reads a package. |
| `gate_build_prompt.py` | `svc-pc-pipeline/tools/gate_build_prompt.py` | Assembles the gate review prompt from the canon spec, addendum, digest and findings. | Called by gate scripts. | Writes a prompt file. |
| `gate_playbooks.py` | `svc-pc-pipeline/tools/gate_playbooks.py` | Per-check instructions and per-finding details for the fix-plan step. | Imported by the gate scripts. | Not described beyond that. |
| `gate_verdict.py` | `svc-pc-pipeline/tools/gate_verdict.py` | Composes the verdict for one task from evidence already computed. | Gate scripts. | Reads findings and reviews. |
| `gate_verdict_cold.py` | `svc-pc-pipeline/tools/gate_verdict_cold.py` | Builds a confusion matrix from review runs for a re-validation. | Coordinator. | Reads review runs. |
| `gate_review.sh` | `svc-pc-pipeline/tools/gate_review.sh` | One task, one reviewer, one review call for the severity-calibration backtest. | Coordinator. | Writes a review JSON. |
| `gate_review_cold.sh` | `svc-pc-pipeline/tools/gate_review_cold.sh` | Cold re-validation copy of gate_review.sh. | Coordinator. | Same. |
| `gate_probe.sh` | `svc-pc-pipeline/tools/gate_probe.sh` | Runs stage_and_zip.sh against a scratch folder to learn whether a task passes on its current bytes. | Coordinator. | Writes to a scratch folder. |
| `gate_prebuild_digests.sh` | `svc-pc-pipeline/tools/gate_prebuild_digests.sh` | Builds a review digest for every task folder that lacks one. | Coordinator. | Writes digests. |
| `stage_and_zip.sh` | `svc-pc-pipeline/sandbox_root/stage_and_zip.sh` | Zips a task only when the gate passes; prints every non-pass cell and exits non-zero on any fail. | Coordinator, via zip_when_ready.sh. | Reads gate outputs. Writes a zip. |
| `zip_when_ready.sh` | `svc-pc-pipeline/tools/zip_when_ready.sh` | Every 2 minutes: for tasks whose latest reviewer verdicts both have zero majors, checks the reviewed bytes equal current staging and zips. | Left running on the sandbox. | Reads verdicts. Writes zips. |
| `build_cr_context.py` | `svc-pc-pipeline/tools/build_cr_context.py` | Builds the text bundle the blind review call reads. | Called by gate_task.sh. | Reads a task. |
| `gather_files_text.py` | `svc-pc-pipeline/tools/gather_files_text.py` | Collects the current text of every editable file for the fix-plan prompt. | Called by gate_task.sh. | Reads task files. |
| `render_prompt.py` | `svc-pc-pipeline/tools/render_prompt.py` | Fills {{PLACEHOLDER}} tokens in a prompt template. | Called by gate_task.sh. | Writes a prompt. |
| `llm_call.py` | `svc-pc-pipeline/tools/llm_call.py` | The only three model-call sites in the gate_task.sh flow. | Called by gate_task.sh. | Makes the model call. |
| `llm_backend.py` | `deterministic-checks/tools/llm_backend.py` | One model call that works for anyone on the QC team, with two backends, so the content audit does not need a Claude Code session. | Imported by checks that need a model. | Makes a model call. |
| `run_workspace_review.py` | `svc-pc-pipeline/tools/run_workspace_review.py` | Workspace-mode comprehensive review: a real agent reads the task's files instead of a text digest. | Coordinator and driver scripts. | Writes review JSON. |
| `run_workspace_review_sev2.py` | `svc-pc-pipeline/tools/run_workspace_review_sev2.py` | Variant that uses severity addendum v2. | Coordinator. | Same. |
| `run_workspace_review_thorough.py` | `svc-pc-pipeline/tools/run_workspace_review_thorough.py` | Variant with the thorough addendum worksheets. | Coordinator. | Same. |
| `bulk_review.sh` | `svc-pc-pipeline/tools/bulk_review.sh` | Runs the workspace review with two reviewers over a list of tasks, N at a time. | Coordinator. | Writes review files. |
| `thorough_pilot.sh` | `svc-pc-pipeline/tools/thorough_pilot.sh` | Runs the canon review plus a thorough addendum as a third reviewer on a list of tasks. | Coordinator. | Writes CR files. |
| `sev2_pilot.sh` | `svc-pc-pipeline/tools/sev2_pilot.sh` | Copy of the thorough pilot pointed at the sev2 review script. | Coordinator. | Same. |
| `opus_pilot.sh` | `svc-pc-pipeline/tools/opus_pilot.sh` | Measurement only: runs the workspace review with Opus on a list of tasks. | Coordinator. | Writes review files. |
| `rereview_pair.sh` | `svc-pc-pipeline/tools/rereview_pair.sh` | Re-runs both reviewers at a given round. | Coordinator. | Writes review files. |
| `rereview_stuck.sh` | `svc-pc-pipeline/tools/rereview_stuck.sh` | Re-runs a reviewer whose verdict landed in a shape the dispatcher rejects. | Coordinator. | Same. |
| `normalize_reviews.py` | `svc-pc-pipeline/tools/normalize_reviews.py` | Recovers reviewer verdicts discarded only for their shape. | Coordinator. | Rewrites review files. |
| `merge_scan_verdicts.py` | `svc-pc-pipeline/tools/merge_scan_verdicts.py` | Merges every scan's verdict CSV into one summary.csv. | Coordinator. | Reads reports. Writes summary.csv. |
| `v3digest_build.py` | `svc-pc-pipeline/tools/v3digest_build.py` | Builds a deterministic Markdown digest of one task package for a digest-review measurement. | Called by v3digest scripts. | Reads a package. Writes one .md. |
| `v3digest_build_prompt.py` | `svc-pc-pipeline/tools/v3digest_build_prompt.py` | Assembles the single-shot digest-review prompt. | Same. | Writes a prompt. |
| `v3digest_control_task_majors.py` | `svc-pc-pipeline/tools/v3digest_control_task_majors.py` | Copy of a control-task script for the digest measurement. | Same. | Reads review output. |
| `v3digest_extract_result.py` | `svc-pc-pipeline/tools/v3digest_extract_result.py` | Post-processes one model call's JSON output for the digest pilot. | Same. | Writes result and stats JSON. |
| `v3digest_pilot.sh` | `svc-pc-pipeline/tools/v3digest_pilot.sh` | Dispatches the digest review for every task and both reviewers. | Coordinator. | Writes results. |
| `v3digest_review.sh` | `svc-pc-pipeline/tools/v3digest_review.sh` | One task, one reviewer, one digest-mode review call. | Called by v3digest_pilot.sh. | Writes a review. |
| `archive_shadowed_rounds.py` | `svc-pc-pipeline/tools/archive_shadowed_rounds.py` | Puts fresh reviewer verdicts back in front of stale higher-round ones. | Coordinator or cron. | Moves files. |
| `archive_shadowed_auto.sh` | `svc-pc-pipeline/tools/archive_shadowed_auto.sh` | Cron wrapper that runs the archive every 2 minutes. | Cron. | Moves files. |
| `unpark_more_rounds.py` | `svc-pc-pipeline/tools/unpark_more_rounds.py` | Gives tasks parked after N fix rounds extra rounds without redoing earlier ones. | Coordinator. | Writes checkpoint and STATE markers. |
| `seed_checkpoints.py` | `svc-pc-pipeline/tools/seed_checkpoints.py` | Seeds STATE markers for tasks that ran on the older script. | After a VM stop or start. | Writes markers. |
| `build_echo_probe.py` | `svc-pc-pipeline/tools/build_echo_probe.py` | Builds the echo probe (script only, no model call). | Called by gate scripts. | Writes probe files. |
| `svc_mark_manual_qc.py` | `svc-pc-pipeline/tools/svc_mark_manual_qc.py` | Sets the Status column to "submit for manual QC" on the live SVC QC Tracker for a list of tasks, cell by cell, not by replacing the file. | QC lead. | Writes tracker cells. |
| `svc_autofix_scan.py` | `svc-pc-pipeline/tools/svc_autofix_scan.py` | Sorts a day's SVC QC findings into mechanical auto-fix and needs-review buckets. | Coordinator. | Reads qc_validation workbooks. |
| `svc_autofix_apply.py` | `svc-pc-pipeline/tools/svc_autofix_apply.py` | Applies the mechanical auto-fix recipes and writes proposed diffs for the review bucket. | Coordinator. | Edits packages. Writes diffs. |
| `svc_qc_triage.py` | `svc-pc-pipeline/tools/svc_qc_triage.py` | Filters QC feedback files so experts only see what they can act on. | Coordinator. | Reads feedback files. |
| `golden_criterion_review.py` | `svc-pc-pipeline/tools/qc_zero_pass/golden_criterion_review.py` | Finds every criterion that every solver run failed, compares with the golden (advisory hold or read-first list). | QC lead. | Reads a task bundle. |
| `golden_review_batch.py` | `svc-pc-pipeline/tools/qc_zero_pass/golden_review_batch.py` | One command for a whole QC batch: golden-comparison review of every task, ranked HOLD, READ_FIRST or CLEAR (HOLD and READ_FIRST correspond to the advisory hold list and read-first list in the row above). | QC lead. | Writes a ranked list. |
| `static_checks.py` | `svc-pc-pipeline/tools/qc_zero_pass/static_checks.py` | Runs mechanical failure-pattern checks over every staged task in a QC batch. | QC lead. | Reads staged tasks. |
| `mover_all.py` | `svc-pc-pipeline/tools/qc_zero_pass/mover_all.py` | Moves finished DataOS task downloads into qc_review/<batch>/zips. | QC lead. | Moves zips. |
| `apply_internal_fails.py` | `svc-pc-pipeline/tools/qc_zero_pass/apply_internal_fails.py` | Marks confirmed internal zero-pass fails on the consolidated sheet and the live tracker. | QC lead. | Writes sheet cells. |
| `audit_marks.py` | `svc-pc-pipeline/tools/qc_zero_pass/audit_marks.py` | Audits the sheets: every confirmed major is marked and no other row has the internal-review tag. | QC lead. | Reads sheets. |
| `fail_dump.py` | `svc-pc-pipeline/tools/qc_zero_pass/fail_dump.py` | Dumps every confirmed-major task with author and findings for drafting author messages. | QC lead. | Reads sheets. |
| `ablation_diff.py` | `pipeline/tools/ablation_diff.py` | Diffs two QC runs (baseline and candidate spec) over the same corpus. | Developer of the pipeline QC engine. | Reads two runs. |
| `consistency.py` | `pipeline/tools/consistency.py` | Aggregates N repeated QC runs to measure judge noise. | Same. | Reads runs. |
| `measure.py` | `pipeline/tools/measure.py` | Reads a batch review and reports calibration signal on GDPVal tasks. | Same. | Reads batch_review.json. |
| `patch_actuator_promoted_advisory.py` | `svc-pc-pipeline/tools/patch_actuator_promoted_advisory.py` | Edits stage_and_zip.sh so the promoted-kinds stop rule is advisory while a flag file exists. | Coordinator, once. | Edits stage_and_zip.sh. |
| `patch_aggregate_judge_input.py` | `svc-pc-pipeline/tools/patch_aggregate_judge_input.py` | Lets aggregate_fresh.py's marker rule read the fresh judge-input report. | Coordinator, once. | Edits aggregate_fresh.py. |
| `patch_aggregate_probe_refresh.py` | `svc-pc-pipeline/tools/patch_aggregate_probe_refresh.py` | Makes aggregate_fresh.py run judge_input_report.py when a probe is missing or older than the task bytes. | Coordinator, once. | Edits aggregate_fresh.py. |
| `patch_brief_coordinator_note.py` | `svc-pc-pipeline/tools/patch_brief_coordinator_note.py` | Makes direct_fix_brief.py append the task's DIRECT-FIX-NOTE.md. | Coordinator, once. | Edits direct_fix_brief.py. |
| `patch_brief_note_only.py` | `svc-pc-pipeline/tools/patch_brief_note_only.py` | Makes direct_fix_brief.py still produce a brief for a task with a note but no open DataOS rows. | Coordinator, once. | Edits direct_fix_brief.py. |
| `patch_dispatcher_park_majors_only.py` | `svc-pc-pipeline/tools/patch_dispatcher_park_majors_only.py` | Makes fix_from_reviews.sh count only major findings for round counters and parking. | Coordinator, once. | Edits fix_from_reviews.sh. |
| `patch_guard_gate_resubmit.py` | `svc-pc-pipeline/tools/patch_guard_gate_resubmit.py` | Makes guard_rt.py hand a re-submitted task back to the fixer when the zip checks block it. | Coordinator, once. | Edits guard_rt.py. |
| `patch_guard_prio_off_flag.py` | `svc-pc-pipeline/tools/patch_guard_prio_off_flag.py` | Adds a flag file that stops the priority loop for good. | Coordinator, once. | Edits guard_rt.py. |
| `patch_guard_promote_not_busy.py` | `svc-pc-pipeline/tools/patch_guard_promote_not_busy.py` | Stops guard_rt.py promoting reviews while a fix cycle is pending or running. | Coordinator, once. | Edits guard_rt.py. |
| `patch_guard_reopen_wait.py` | `svc-pc-pipeline/tools/patch_guard_reopen_wait.py` | After a re-open, ignores further zip blocks until the fixer has run once. | Coordinator, once. | Edits guard_rt.py. |
| `patch_guard_revert_zipvalidity_exemption.py` | `svc-pc-pipeline/tools/patch_guard_revert_zipvalidity_exemption.py` | Reverts the zip-validity half of patch_guard_stale_attempts_resubmit.py. | Coordinator, once. | Edits guard_rt.py. |
| `patch_guard_reviewer_majors.py` | `svc-pc-pipeline/tools/patch_guard_reviewer_majors.py` | Hands a promoted DataOS re-review pair that carries majors back to the dispatcher. | Coordinator, once. | Edits guard_rt.py. |
| `patch_guard_stale_attempts_resubmit.py` | `svc-pc-pipeline/tools/patch_guard_stale_attempts_resubmit.py` | Stops two guard rules from skipping tasks being re-submitted. | Coordinator, once. | Edits guard_rt.py. |
| `patch_zip_fix_pending.py` | `svc-pc-pipeline/tools/patch_zip_fix_pending.py` | Makes zip_when_ready.sh skip a task that was re-opened and not yet fixed. | Coordinator, once. | Edits zip_when_ready.sh. |
| `patch_zip_groups_fire.py` | `svc-pc-pipeline/tools/patch_zip_groups_fire.py` | Makes zip_when_ready.sh block when an authored judge group did not fire after the oracle passes. | Coordinator, once. | Edits zip_when_ready.sh. |
| `patch_zip_last_silent_skips.py` | `svc-pc-pipeline/tools/patch_zip_last_silent_skips.py` | Makes zip_when_ready.sh log its last two unlogged skips. | Coordinator, once. | Edits zip_when_ready.sh. |
| `patch_zip_oracle_stale.py` | `svc-pc-pipeline/tools/patch_zip_oracle_stale.py` | Makes zip_when_ready.sh re-run an oracle probe older than the task's newest byte. | Coordinator, once. | Edits zip_when_ready.sh. |
| `patch_zip_park_and_logs.py` | `svc-pc-pipeline/tools/patch_zip_park_and_logs.py` | Stops a fix park from blocking an attempt and logs two silent skips. | Coordinator, once. | Edits zip_when_ready.sh. |
| `patch_zip_schema_bytes_gate.py` | `svc-pc-pipeline/tools/patch_zip_schema_bytes_gate.py` | Makes zip_when_ready.sh block packaging when a judge group's compiled schema is 4,000 bytes or more. | Coordinator, once. | Edits zip_when_ready.sh. |
| `patch_zip_stale_park.py` | `svc-pc-pipeline/tools/patch_zip_stale_park.py` | Makes zip_when_ready.sh treat a park as stale when both latest reviewer verdicts are newer. | Coordinator, once. | Edits zip_when_ready.sh. |
| `gate_backtest.sh` | `svc-pc-pipeline/tools/gate_backtest.sh` | Runs the severity-calibrated packaging gate on the 10 batch-10 tasks and prints a confusion matrix against DataOS's own results. | Coordinator, one-off test. | Writes test output. |
| `gate_backtest_cold.sh` | `svc-pc-pipeline/tools/gate_backtest_cold.sh` | Cold re-validation of that backtest on the exact graded bytes with fresh digests. | Coordinator, one-off test. | Writes test output. |
| `_qc_common.py` | `svc-pc-pipeline/tools/_qc_common.py` | Shared helper code for the corpus-wide scan scripts (env_size_report, golden_citation_scan and others); not a standalone script. | Imported. | None. |
| `derive_reward_weights.py` | `deterministic-checks/tools/derive_reward_weights.py` | Prototype, not a rollout tool: tests whether the "declared rubric weights not applied" defect can be fixed in bulk. | Developer. | Reads rubrics. |

### Stage 7. Reporting and sync

| Script | File | What it does in plain English | When it runs and who runs it | Reads or writes what |
|---|---|---|---|---|
| `svc_consolidated_record.py` | `svc-pc-pipeline/tools/svc_consolidated_record.py` | Records SVC submissions in the consolidated tracker (tab SVC) following the QC-team SOP: every row goes in the main table above the Rejected section; nothing is moved or written under the Duplicates heading. Dry run by default. | QC lead, after a task passes the manager's review. | Writes tracker rows. |
| `svc_consolidated_links.py` | `svc-pc-pipeline/tools/svc_consolidated_links.py` | Lists consolidated SVC-tab rows that have no link in column C (reads real link metadata). Read-only. | QC lead. | Reads the tracker. Writes _scratch_unlinked.json. |
| `svc_submission_audit.py` | `svc-pc-pipeline/tools/svc_submission_audit.py` | Read-only audit: every task submitted for manual QC has a live-queue row with EQC ready and a valid status. | QC lead. | Reads the tracker. |
| `svc_build_combined_tracker.py` | `svc-pc-pipeline/tools/svc_build_combined_tracker.py` | Builds a combined tracker from two team trackers. No docstring; purpose not described in the file beyond its sheet-id constants and --apply flag. | By hand with --apply. | Reads and writes sheets. |
| `svc_build_freeze.py` | `svc-pc-pipeline/tools/svc_build_freeze.py` | Builds the do-not-touch list from the two team trackers, so lanes never rework and the bundler never ships a task that is already finished. | Coordinator. | Reads trackers. Writes the freeze list. |
| `svc_completion_matrix.py` | `svc-pc-pipeline/tools/svc_completion_matrix.py` | Builds the completion matrix for the 58 tasks from the live tracker plus real file evidence; the denominator comes from the tracker. | Coordinator. | Reads tracker and files. |
| `svc_writeback_32.py` | `svc-pc-pipeline/tools/svc_writeback_32.py` | Writes edited staging files back to Drive one at a time with an audit trail. | Coordinator. | Writes Drive files. |
| `svc_readback_verify.py` | `svc-pc-pipeline/tools/svc_readback_verify.py` | Re-downloads every written file and compares md5 against the local source, a second check after drive.py put. | Coordinator. | Reads Drive. |
| `svc_audit_sheet.py` | `svc-pc-pipeline/tools/svc_audit_sheet.py` | Refreshes the SVC rework audit sheet in the shape that already worked. | Coordinator. | Writes a sheet. |
| `svc_fp_screen_sheet.py` | `svc-pc-pipeline/tools/svc_fp_screen_sheet.py` | Builds the false-positive screen workbook from combined verdicts. | Coordinator. | Writes a workbook. |
| `svc_defect_rollup.py` | `svc-pc-pipeline/tools/svc_defect_rollup.py` | Groups false-positive screen results by task to find repeat-defect tasks. | Coordinator. | Reads verdicts. |
| `svc_full_audit_review_package.py` | `svc-pc-pipeline/tools/svc_full_audit_review_package.py` | Builds the review package from the 22 full-corpus audit batch files. | Coordinator. | Writes a workbook. |
| `svc_autofix_report.py` | `svc-pc-pipeline/tools/svc_autofix_report.py` | Builds the auto-fix summary workbook. | Coordinator. | Writes a workbook. |
| `svc_qc_tracker_build.py` | `svc-pc-pipeline/tools/svc_qc_tracker_build.py` | Builds the consolidated SVC QC tracker workbook from a gathered result JSON. | Coordinator. | Writes a workbook. |
| `svc_qc_reconcile_ground_truth.py` | `svc-pc-pipeline/tools/svc_qc_reconcile_ground_truth.py` | Reconciles checks A, B, C and D across the session's workflows with a fresh rescan, with no model call. | Coordinator. | Reads reports. |
| `svc_qc_validation_sheet.py` | `svc-pc-pipeline/tools/svc_qc_validation_sheet.py` | Builds one qc_validation workbook per task in the column layout of the QC team's own reports. | Coordinator. | Writes workbooks. |
| `svc_difficulty_report.py` | `svc-pc-pipeline/tools/svc_difficulty_report.py` | Splits the SVC task population into easy mechanical wins and tasks that need judgment, for QC assignment. | Coordinator. | Reads tracker. Writes a report. |
| `qc_batch_build.py` | `svc-pc-pipeline/tools/qc_batch_build.py` | Plans and records one human QC batch (SVC and EKW) from the consolidated sheet; process in svc-pc-pipeline/docs/qc-intake-process.md. | QC lead. | Reads and writes sheets. |
| `svc_harbor_coverage.py` | `svc-pc-pipeline/tools/svc_harbor_coverage.py` | Prints the evaluation coverage matrix with its denominator, populations and sources. | Whoever runs evaluations. | Reads run state. |
| `svc_harbor_holes.py` | `svc-pc-pipeline/tools/svc_harbor_holes.py` | Names the exact evaluation slots still short and whether anything is running for them. | Same. | Reads run state. |
| `svc_harbor_leasewatch.py` | `svc-pc-pipeline/tools/svc_harbor_leasewatch.py` | Catches a trial that claimed a lease and never started. | Same. | Reads trial status. |
| `svc_harbor_stallwatch.py` | `svc-pc-pipeline/tools/svc_harbor_stallwatch.py` | Alarms when the shortfall stops moving. | Same. | Reads run state. |
| `svc_harbor_watch.py` | `svc-pc-pipeline/tools/svc_harbor_watch.py` | Prints one line whenever the shortfall changes. | Same. | Reads run state. |
| `svc_harbor_tracker_sync.py` | `svc-pc-pipeline/tools/svc_harbor_tracker_sync.py` | Syncs the Work Tracker Evals tab to the coverage contract and adds provenance columns R to Y. | Same. | Writes sheet cells. |
| `svc_grok_build_tracker_sync.py` | `svc-pc-pipeline/tools/svc_grok_build_tracker_sync.py` | Records the Grok Build run in the Work Tracker. | One-off. | Writes sheet cells. |
| `svc_pipeline_report.py` | `svc-pc-pipeline/tools/svc_pipeline_report.py` | One-screen live state of the lane pipeline. Read-only. | Coordinator on the laptop, over ssh. | Reads sandbox state. |
| `pipe_stages.py` | `svc-pc-pipeline/tools/pipe_stages.py` | One table: where each of the 202 tasks stands (untouched, mechanical, review round N, fix round N, ...). | Coordinator. | Reads stream-pipe. |
| `pipe_status.sh` | `svc-pc-pipeline/tools/pipe_status.sh` | One-screen view of the gate pipeline. | By hand under `watch`. | Reads state. |
| `status_snapshot.py` | `svc-pc-pipeline/tools/status_snapshot.py` | Prints a status snapshot of the lane pipeline. No docstring; purpose not described in the file beyond reading stream-pipe and the corpus. | Not stated. | Reads state. |
| `task_ledger.py` | `svc-pc-pipeline/tools/task_ledger.py` | One row per task: how far from a submittable zip and why. | Coordinator. | Reads stream-pipe; writes a ledger. |
| `task_order.py` | `svc-pc-pipeline/tools/task_order.py` | Gives the batch order from the handoff document. | Coordinator. | Prints an order. |
| `svc_lane_time.py` | `svc-pc-pipeline/tools/svc_lane_time.py` | Where lane time goes: per-task attempts, wall time and loop-back reasons from runner logs. | Coordinator. | Reads logs. |
| `status.sh` | `svc-pc-pipeline/sandbox_root/status.sh` | Live zero-token dashboard of the workspace pipeline. | Coordinator in a tmux window. | Reads state. |
| `throughput_watch.sh` | `svc-pc-pipeline/sandbox_root/throughput_watch.sh` | Zero-model health and throughput watchdog. | Cron every 5 minutes. | Writes watch logs. |
| `cycle.py` | `pipeline/cycle.py` | Driver for the twice-weekly EKW QC cycle: every run is a dated folder with the same numbered stages. | QC lead, twice a week. | Reads cycle inputs. Writes cycles/<date>/ stages. |
| `drive_fetch.py` | `pipeline/tools/drive_fetch.py` | Recursively downloads a Google Drive folder tree. | QC lead. | Reads Drive. Writes local folders. |
| `build_corpus.py` | `pipeline/tools/build_corpus.py` | Turns the public openai/gdpval dataset into a QC calibration corpus (a stratified sample). | Developer. | Downloads data. Writes a corpus. |
| `build_ablation_corpus.py` | `pipeline/tools/build_ablation_corpus.py` | Assembles the labeled ablation corpus with full trajectories. | Developer. | Writes a corpus. |
| `build_audit.py` | `pipeline/tools/build_audit.py` | Builds the per-task QC audit for one task. | Developer. | Reads run output. Writes an audit. |
| `extract_audit_data.py` | `pipeline/tools/extract_audit_data.py` | Pulls everything an audit needs for one task from run output and the corpus. | Developer. | Writes audit JSON. |
| `dataos_evals_import.py` | `pipeline/tools/dataos_evals_import.py` | Imports a DataOS QC-run download into the 03_evals shape the internal QC engine reads. | QC lead. | Reads a download. Writes 03_evals. |
| `gate_diff.py` | `pipeline/tools/gate_diff.py` | Compares the QC gates on the agents.turing pipeline page with the gate list live in the Omega tracker. | By hand. | Reads two lists. |
| `hydrate_environment.py` | `pipeline/tools/hydrate_environment.py` | Resolves and stages the real input files a task's agent needs so the environment folder is not empty. | Not stated. | Writes environment/data. |
| `check_links.py` | `docs/check_links.py` | Fails if a relative link in the front-door docs points to a file not in the repo. | Maintainer of the docs. | Reads docs. |

### Stage 8. Lane orchestration and sandbox upkeep (older fleet and notification scripts)

| Script | File | What it does in plain English | When it runs and who runs it | Reads or writes what |
|---|---|---|---|---|
| `watchdog.sh` | `svc-pc-pipeline/tools/watchdog.sh` | Zero-token health checks for the gate pipeline and the model solver batch, every 60 seconds; alerts go to ALERTS.log. | Cron on the sandbox. | Writes alerts. |
| `watchdog_bench_patch.py` | `svc-pc-pipeline/tools/watchdog_bench_patch.py` | One-off patch to watchdog.sh to bench lanes using each account's own reset time. | Done once. | Edits watchdog.sh. |
| `watchdog_rootmode_patch.py` | `svc-pc-pipeline/tools/watchdog_rootmode_patch.py` | One-off patch adding a host guard that the root directory stays mode 755. | Done once. | Edits watchdog.sh. |
| `guard_rt.py` | `svc-pc-pipeline/tools/guard_rt.py` | Near-real-time guard for the pipeline, with no model tokens except tiny probe calls when a lane is swapped. | Left running on the sandbox. | Reads and writes pipeline state. |
| `after_boot.sh` | `svc-pc-pipeline/tools/after_boot.sh` | Brings the pipeline back after a VM stop and start. | Coordinator. | Restarts processes. |
| `sandbox_housekeep.sh` | `svc-pc-pipeline/tools/sandbox_housekeep.sh` | Housekeeping every 30 minutes after the root disk filled; deletes nothing of value. | Cron. | Moves old files. |
| `scan_governor.sh` | `svc-pc-pipeline/tools/scan_governor.sh` | Keeps the scans from starving latency-sensitive work. | Cron. | Reads load. |
| `scan_slots.py` | `svc-pc-pipeline/tools/scan_slots.py` | Admission control for CPU-heavy scans. | Called by scans. | Writes slot files. |
| `resize_helper_startup.sh` | `svc-pc-pipeline/tools/resize_helper_startup.sh` | Startup script for a helper VM that resizes the sandbox VM. | One-off. | Changes VM settings. |
| `glm_probe.sh` | `svc-pc-pipeline/tools/glm_probe.sh` | Sends one small request per GLM key and prints HTTP status. Never prints the key. | Coordinator. | Reads key file. |
| `task_driver.sh` | `svc-pc-pipeline/sandbox_root/task_driver.sh` | One driver owns one task end to end: review current bytes, and if it fails, fix with Opus and re-review until zero majors. | Fleet pool (older severity-gate design). | Edits a task. Writes reviews. |
| `task_driver_ws.sh` | `svc-pc-pipeline/sandbox_root/task_driver_ws.sh` | The v4 version: workspace-mode review. | Fleet pool. | Same. |
| `driver_pool.sh` | `svc-pc-pipeline/sandbox_root/driver_pool.sh` | Keeps up to POOL task drivers running, one per undone task. | Cron. | Starts drivers. |
| `driver_pool_ws.sh` | `svc-pc-pipeline/sandbox_root/driver_pool_ws.sh` | Same for the workspace drivers over all 202 tasks. | Cron. | Starts drivers. |
| `fleet.sh` | `svc-pc-pipeline/sandbox_root/fleet.sh` | Re-entrant severity-gate supervisor, every minute from cron. | Cron. | Reads verdicts. |
| `fix_loop.sh` | `svc-pc-pipeline/sandbox_root/fix_loop.sh` | Re-entrant Opus fixer supervisor for gate FAILs, every 3 minutes. | Cron. | Edits tasks. |
| `fix_one.sh` | `svc-pc-pipeline/sandbox_root/fix_one.sh` | One Opus fixer pass on a failed task, then rebuilds its digest. | Called by fix_loop.sh. | Edits a task. |
| `freeze_and_fix.sh` | `svc-pc-pipeline/sandbox_root/freeze_and_fix.sh` | One-shot recovery from a false-PASS bug. | One-off. | Writes freeze.out. |
| `gate_prod_run.sh` | `svc-pc-pipeline/sandbox_root/gate_prod_run.sh` | Production severity gate on current bytes for a task list. | Coordinator. | Writes verdicts. |
| `lane_probe.sh` | `svc-pc-pipeline/sandbox_root/lane_probe.sh` | Tests every Max lane with one tiny call. | Coordinator. | Prints lane status. |
| `pool_build.sh` | `svc-pc-pipeline/sandbox_root/pool_build.sh` | Builds digests and deterministic findings in parallel with no model use. | Coordinator. | Writes digests. |
| `recover2.sh` | `svc-pc-pipeline/sandbox_root/recover2.sh` | One-off recovery: installs a new driver and pool and undoes false UNFIXABLE drops. | One-off. | Restarts drivers. |
| `recover3.sh` | `svc-pc-pipeline/sandbox_root/recover3.sh` | One-off recovery: installs the fix-slot driver and cuts load. | One-off. | Kills agents. |
| `recover4.sh` | `svc-pc-pipeline/sandbox_root/recover4.sh` | One-off: relieves load and diagnoses why fixers exceeded the cap. | One-off. | Writes a report. |
| `recover5.sh` | `svc-pc-pipeline/sandbox_root/recover5.sh` | One-off: deploys a smaller pool, resets the fleet and measures load. | One-off. | Writes a report. |
| `reset_ws.sh` | `svc-pc-pipeline/sandbox_root/reset_ws.sh` | Clean reset of the workspace fleet. | One-off. | Releases locks. |
| `scale_up_ws.sh` | `svc-pc-pipeline/sandbox_root/scale_up_ws.sh` | Flips the fleet from the digest gate to the v4 workspace pipeline. | One-off. | Starts and stops cron jobs. |
| `swap_now.sh` | `svc-pc-pipeline/sandbox_root/swap_now.sh` | Retires the old fragmented pipeline and puts the one-driver-per-task pool in its place. | One-off. | Writes a report. |
| `_pause_fleet.sh` | `svc-pc-pipeline/sandbox_root/_pause_fleet.sh` | Full pause: backs up and clears cron, then kills the fleet. | Coordinator. | Edits cron. |
| `_aggfix_run.sh` | `svc-pc-pipeline/sandbox_root/_aggfix_run.sh` | Aggressive fix on 9 wave-1 tasks, then oracle verify. | One-off. | Edits rubrics. |
| `_scopefix_run.sh` | `svc-pc-pipeline/sandbox_root/_scopefix_run.sh` | Single-task scope-breadth fix on one Opus lane. | One-off. | Edits a task. |
| `_grammar_revert.sh` | `svc-pc-pipeline/sandbox_root/_grammar_revert.sh` | Reverts unnecessary grammar splits (pre-split max of 20 criteria per folder or fewer). | One-off. | Restores files. |
| `_dataos_fix.sh` | `svc-pc-pipeline/sandbox_root/_dataos_fix.sh` | Directed DataOS-feedback fixer, one Sonnet agent per task. | Coordinator. | Edits tasks. |
| `_dataos_verify.sh` | `svc-pc-pipeline/sandbox_root/_dataos_verify.sh` | Waits for the directed fixer, then verifies each fixed task: oracle, static check and a softening guard. | Coordinator. | Reads tasks. |
| `_pass_pathcheck_run.sh` | `svc-pc-pipeline/sandbox_root/_pass_pathcheck_run.sh` | Purpose not described in the file (no header comment); its commands run judge_input_gate.py over every task that has a PASS verdict file. | Coordinator. | Writes _pass_pathcheck.json. |
| `_caltest_run.sh` | `svc-pc-pipeline/sandbox_root/_caltest_run.sh` | Few-shot severity-calibration test with calibrated Opus and Fable reviewers on batch-15 tasks. | One-off test. | Writes test output. |
| `_fabletest_run.sh` | `svc-pc-pipeline/sandbox_root/_fabletest_run.sh` | Test whether Fable catches 1.4 and 1.5 defects (checks 1.4, instruction and rubric alignment, and 1.5, rubric coverage, in docs/ekw-svc-comprehensive-review.md) the DataOS Opus seat misses, on 8 failed tasks. | One-off test. | Writes test output. |
| `_prectest_run.sh` | `svc-pc-pipeline/sandbox_root/_prectest_run.sh` | Precision test: do Fable and Opus raise 1.4 or 1.5 (the same two checks) on tasks DataOS passed? | One-off test. | Writes test output. |
| `_notify_1_18.sh` | `svc-pc-pipeline/sandbox_root/_notify_1_18.sh` | Sends an update message to each tmux session of agents. | One-off. | Sends keystrokes. |
| `_notify_1_19.sh` | `svc-pc-pipeline/sandbox_root/_notify_1_19.sh` | Sends a rules update and a budget change to the tmux sessions. | One-off. | Writes BUDGET; sends keystrokes. |
| `_notify_resume.sh` | `svc-pc-pipeline/sandbox_root/_notify_resume.sh` | Tells the tmux sessions to resume after a rate-limit window. | One-off. | Sends keystrokes. |
| `_notify_unblock.sh` | `svc-pc-pipeline/sandbox_root/_notify_unblock.sh` | Tells four sessions to stop waiting on another. | One-off. | Sends keystrokes. |
| `svc_dataos_fix.sh` | `svc-pc-pipeline/sandbox_root/svc_dataos_fix.sh` | Byte-for-byte copy of svc-pc-pipeline/tools/svc_dataos_fix.sh (checked with cmp). Directed fixer: one Sonnet agent per task, given that task's exact DataOS findings. | As for the tools copy. | As for the tools copy. |
| `svc_dataos_overnight.sh` | `svc-pc-pipeline/sandbox_root/svc_dataos_overnight.sh` | Differs from the copy in svc-pc-pipeline/tools/svc_dataos_overnight.sh (checked with cmp), same header purpose. Overnight directed fix plus deterministic verify, started and left to run on the lanes. | As for the tools copy. | As for the tools copy. |
| `svc_dataos_queue_and_zip.sh` | `svc-pc-pipeline/sandbox_root/svc_dataos_queue_and_zip.sh` | Byte-for-byte copy of svc-pc-pipeline/tools/svc_dataos_queue_and_zip.sh (checked with cmp). Waits for a run to finish, then runs fixes, then builds resubmit zips from verified tasks. | As for the tools copy. | As for the tools copy. |
| `svc_fullsweep_fill.sh` | `svc-pc-pipeline/sandbox_root/svc_fullsweep_fill.sh` | Byte-for-byte copy of svc-pc-pipeline/tools/svc_fullsweep_fill.sh (checked with cmp). Full-coverage-sweep fixer for tasks DataOS has not graded yet, filling idle lanes. | As for the tools copy. | As for the tools copy. |
| `svc_fullsweep_pool.sh` | `svc-pc-pipeline/sandbox_root/svc_fullsweep_pool.sh` | Byte-for-byte copy of svc-pc-pipeline/tools/svc_fullsweep_pool.sh (checked with cmp). Work-stealing pool for the same sweep, one worker per lane. | As for the tools copy. | As for the tools copy. |
| `svc_scaleup_daemon.sh` | `svc-pc-pipeline/sandbox_root/svc_scaleup_daemon.sh` | Byte-for-byte copy of svc-pc-pipeline/tools/svc_scaleup_daemon.sh (checked with cmp). Waits for a GO signal, then starts the pool detached so it survives the laptop closing. | As for the tools copy. | As for the tools copy. |
| `svc_v7_rearm.sh` | `svc-pc-pipeline/sandbox_root/svc_v7_rearm.sh` | Byte-for-byte copy of svc-pc-pipeline/tools/svc_v7_rearm.sh (checked with cmp). Cron entry that re-arms the scale-up daemon after a crash or reboot. | As for the tools copy. | As for the tools copy. |
| `svc_v7_stop.sh` | `svc-pc-pipeline/sandbox_root/svc_v7_stop.sh` | Byte-for-byte copy of svc-pc-pipeline/tools/svc_v7_stop.sh (checked with cmp). Stops the daemon, pool and in-flight rebuilds cleanly. | As for the tools copy. | As for the tools copy. |

### Stage 9. Other tool code: the separate gdpval_qc engine, templates, skills and sample data

| Script | File | What it does in plain English | When it runs and who runs it | Reads or writes what |
|---|---|---|---|---|
| `cli.py` | `pipeline/gdpval_qc/cli.py` | Command line for the v18 quality engine (a separate framework that grades task sets with a panel of language models): loads a spec, walks a task folder, runs every dimension. | Developer or QC lead. | Reads a corpus. Writes review artifacts. |
| `v18_engine.py` | `pipeline/gdpval_qc/v18_engine.py` | Drives the 8-stage per-sample flow of the v18 engine. | Called by cli.py. | Reads samples. |
| `v18_loader.py` | `pipeline/gdpval_qc/v18_loader.py` | Loads a task corpus folder for v18. | Called by the engine. | Reads task folders. |
| `v18_spec.py` | `pipeline/gdpval_qc/v18_spec.py` | Parses the v18 spec (markdown with YAML front matter). | Called by the engine. | Reads a spec file. |
| `v18_judge.py` | `pipeline/gdpval_qc/v18_judge.py` | Builds judge prompts and runs the judge ensemble for one dimension. | Called by the engine. | Makes model calls. |
| `v18_aggregate.py` | `pipeline/gdpval_qc/v18_aggregate.py` | Aggregates judge attempts into one finding per dimension. | Called by the engine. | Pure functions. |
| `v18_verdict.py` | `pipeline/gdpval_qc/v18_verdict.py` | Computes the sample verdict from the findings with no model. | Called by the engine. | Pure functions. |
| `v18_synthesizer.py` | `pipeline/gdpval_qc/v18_synthesizer.py` | Per-sample triage of blocking versus cosmetic findings. | Called by the engine. | Makes model calls. |
| `v18_emitter.py` | `pipeline/gdpval_qc/v18_emitter.py` | Writes the batch review as JSON and other outputs. | Called by the engine. | Writes output files. |
| `v18_callbacks.py` | `pipeline/gdpval_qc/v18_callbacks.py` | Built-in programmatic checks for the spec's code-graded dimensions. | Called by the engine. | Reads task files. |
| `v18_calibration.py` | `pipeline/gdpval_qc/v18_calibration.py` | Runs known-good calibration samples. | Called by the engine. | Reads goldens. |
| `v18_trajectory_digest.py` | `pipeline/gdpval_qc/v18_trajectory_digest.py` | Condenses model trajectories into a text digest. | Called by the engine. | Reads trajectories. |
| `v18_verifier_summary.py` | `pipeline/gdpval_qc/v18_verifier_summary.py` | Summarises pass and fail patterns from a task's verifier reports. | Called by the engine. | Reads verifier-report.json files. |
| `context_limiter.py` | `pipeline/gdpval_qc/context_limiter.py` | Limits input size for evaluation calls. | Called by the engine. | Pure functions. |
| `converters.py` | `pipeline/gdpval_qc/converters.py` | Resolves Google Drive URLs and converts Office files to PDF. | Called by the engine. | Reads and writes files. |
| `finding.py` | `pipeline/gdpval_qc/finding.py` | Data types for findings. | Imported. | None. |
| `review.py` | `pipeline/gdpval_qc/review.py` | Data types for per-sample and per-batch reviews. | Imported. | None. |
| `precondition.py` | `pipeline/gdpval_qc/precondition.py` | Preconditions deciding when a dimension applies. | Imported. | None. |
| `upstream_deliverables.py` | `pipeline/gdpval_qc/upstream_deliverables.py` | Separates registered upstream deliverables from source documents in hierarchical tasks. | Imported. | Reads a task. |
| `llm_client.py` | `pipeline/gdpval_qc/llm_client.py` | Common wrapper for model calls with three adapters. | Imported. | Makes model calls. |
| `openai_client.py` | `pipeline/gdpval_qc/openai_client.py` | OpenAI model adapter. | Imported. | Makes model calls. |
| `gemini_client.py` | `pipeline/gdpval_qc/gemini_client.py` | Gemini model adapter. | Imported. | Makes model calls. |
| `openai_batch.py` | `pipeline/gdpval_qc/openai_batch.py` | Batch-API support for one model's leg of the judge ensemble. | Imported. | Makes model calls. |
| `mock_llm.py` | `pipeline/gdpval_qc/mock_llm.py` | A fake model client for tests. | Tests. | None. |
| `__init__.py` | `pipeline/gdpval_qc/__init__.py` | Package description for the v18 engine. | Imported. | None. |
| `__init__.py` | `pipeline/gdpval_qc/tools/__init__.py` | Empty package marker. | Imported. | None. |
| `check_verifier.py` | `pipeline/gdpval_qc/tools/check_verifier.py` | Runs the three code-graded verifier checks for Verifier QC. | Engine or by hand. | Reads verifier files. |
| `check_rubric.py` | `pipeline/gdpval_qc/tools/check_rubric.py` | Structural checks for an SVC rubric.json. | Engine or by hand. | Reads rubric.json. |
| `check_dag.py` | `pipeline/gdpval_qc/tools/check_dag.py` | Whole-workbook checks across levels L1 to L3 of SVC tasks, run once over the tasks folder. | By hand. | Reads tasks. |
| `extract_task_files.py` | `pipeline/gdpval_qc/tools/extract_task_files.py` | Extracts a task's files as text for local QC. | By hand. | Reads a task. Writes text. |
| `test.sh` | `pipeline/templates/dataos_harbor/test.sh` | Task entrypoint script that ships in every converted task folder; it runs the verifier (copies in pipeline/templates/harbor and the skill template are the same files). | Run inside the DataOS grading container, not by people. | Reads the task tests; writes reward files. |
| `test.sh` | `pipeline/templates/harbor/test.sh` | Generic Harbor verifier entrypoint reading tests/verifier.json and writing reward.txt, reward.json and verifier-report.json. | Inside the grading container. | Writes reward files. |
| `test.sh` | `skills/ekw/ekw-to-dataos-harbor/templates/dataos_harbor/test.sh` | Copy of the entrypoint inside the skill's template bundle. | Inside the grading container. | Writes reward files. |
| `verifier_runtime.py` | `pipeline/templates/harbor/verifier_runtime.py` | Runtime that the harbor test.sh calls. | Inside the grading container. | Reads the task and writes reports. |
| `dataos_discovery_probe.py` | `pipeline/templates/dataos_harbor/dataos_discovery_probe.py` | Probe that checks DataOS can discover the task's tests. | Inside the grading container. | Reads tests. |
| `dataos_discovery_probe.py` | `skills/ekw/ekw-to-dataos-harbor/templates/dataos_harbor/dataos_discovery_probe.py` | Copy of the probe in the skill bundle. | Same. | Same. |
| `__verifier_lib` | `pipeline/templates/dataos_harbor/__verifier_lib/ (20 files: __init__, compare, judge, models, runner, source_types, verifiers, and sources/ with __init__, _content_limits, csv, docx, filesystem, json, md, pdf, pptx, registry, response, text, xlsx)` | Verifier library shipped inside every converted task: reads task files by type, compares values, calls the judge. These are the canonical copy; the copies in pipeline/templates/harbor/verifier_lib/ and skills/ekw/ekw-to-dataos-harbor/templates/dataos_harbor/__verifier_lib/ are kept identical by sync_templates.py. | Inside the grading container. | Reads task files. |
| `solve.sh` | `pipeline/data/sample_corpus/task_11/solution/solve.sh` | A sample task's solution script: copies the golden outputs into the workspace output folder, as Harbor runs it. | Sample data. | Writes output. |
| `skills` | `pipeline/data/sample_corpus/task_11/.../skills (docx, pdf, xlsx helper scripts, 36 .py files)` | Office and PDF helper scripts recorded inside one sample evaluation trial (what an AI agent had available). Sample data, not QC tools. | Not run by QC staff. | Not applicable. |
| `verifier_lib` | `pipeline/templates/harbor/verifier_lib/ (20 files, same names as above)` | The "harbor" genre copy of the verifier library. Must equal the canonical copy except requirements.txt (checked by sync_templates.py). | Inside the grading container. | Reads task files. |
| `__verifier_lib` | `skills/ekw/ekw-to-dataos-harbor/templates/dataos_harbor/__verifier_lib/ (20 files)` | The skill's bundled copy of the verifier library; must equal the canonical copy file for file. | Inside the grading container. | Reads task files. |
| `tests` | `pipeline/data/sample_corpus/task_11/tests/ (verifier_runtime.py and verifier_lib/, 20 files)` | A sample task's own grading code (the same verifier library). Sample data. | Not run by QC staff. | Not applicable. |

### Checks that sit in tool folders (described in the check family sections)

These files live next to the tools but find defects rather than build, ship or sync anything. Each belongs to a check family written up elsewhere; they are listed here only so every script file in the repo is accounted for.

| Script | File | What it finds |
|---|---|---|
| `answer_preexposure_scan.py` | `svc-pc-pipeline/tools/answer_preexposure_scan.py` | Finds tasks where the corpus already holds a finished analysis a solver could copy. |
| `asof_date_missing_scan.py` | `svc-pc-pipeline/tools/asof_date_missing_scan.py` | Flags instructions that say "today" or "current" with no stated date. |
| `citation_unverifiable_scan.py` | `svc-pc-pipeline/tools/citation_unverifiable_scan.py` | Flags criteria that grade citations the solver cannot verify. |
| `cross_group_duplicate_scan.py` | `svc-pc-pipeline/tools/cross_group_duplicate_scan.py` | Finds duplicate and compound criteria within and across judge groups. |
| `discretion_pin_scan.py` | `svc-pc-pipeline/tools/discretion_pin_scan.py` | Finds a decision the instruction leaves to the solver that a criterion pins anyway. |
| `env_size_report.py` | `svc-pc-pipeline/tools/env_size_report.py` | Flags tasks whose environment folder is too large. |
| `escape_hatch_scan.py` | `svc-pc-pipeline/tools/escape_hatch_scan.py` | Finds criterion escape hatches and authoring labels. |
| `formula_cache_scan.py` | `svc-pc-pipeline/tools/formula_cache_scan.py` | Finds golden formula cells whose cached value is empty. |
| `golden_citation_scan.py` | `svc-pc-pipeline/tools/golden_citation_scan.py` | Finds golden citations that point at files absent from the corpus. |
| `golden_leak_scan.py` | `svc-pc-pipeline/tools/golden_leak_scan.py` | Finds answers exposed in files the solver can read. |
| `golden_leak_scan_task.py` | `svc-pc-pipeline/tools/golden_leak_scan_task.py` | Single-task wrapper around golden_leak_scan.py. |
| `instruction_input_scan.py` | `svc-pc-pipeline/tools/instruction_input_scan.py` | Finds input files the instruction names that do not exist. |
| `judge_group_size_scan.py` | `svc-pc-pipeline/tools/judge_group_size_scan.py` | Flags judge groups with too many criteria. |
| `judge_input_report.py` | `svc-pc-pipeline/tools/judge_input_report.py` | Finds files the judge silently skips for being over 1 MiB. A copy also sits in deterministic-checks/scans/. |
| `judge_input_report.py` | `deterministic-checks/scans/judge_input_report.py` | Same check, in the deterministic-checks folder. |
| `judge_schema_bytes.py` | `svc-pc-pipeline/tools/judge_schema_bytes.py` | Compiles each judge group's response schema and flags ones at or over 4,000 bytes. |
| `measure_group_chars.py` | `svc-pc-pipeline/tools/measure_group_chars.py` | Measures each judge group's extracted text size against the judge model's window. |
| `metadata_fill.py` | `svc-pc-pipeline/tools/metadata_fill.py` | Finds task.toml [metadata] fields absent from the expected schema. |
| `mojibake_check.py` | `svc-pc-pipeline/tools/mojibake_check.py` | Finds garbled characters in file paths and shipped file names. |
| `muststrip_scan.py` | `svc-pc-pipeline/tools/muststrip_scan.py` | Finds "must-pass" text with no matching stop rule in reward.toml. |
| `oversize_source_scan.py` | `svc-pc-pipeline/tools/oversize_source_scan.py` | Finds source files over the 1 MiB judge limit. |
| `pin_probe.py` | `svc-pc-pipeline/tools/pin_probe.py` | Tests whether pinned values in criteria make correct answers fail. |
| `promoted_kinds.py` | `svc-pc-pipeline/tools/promoted_kinds.py` | Marks which finding kinds are promoted to blocking. |
| `promoted_kinds_gate.py` | `svc-pc-pipeline/tools/promoted_kinds_gate.py` | Read-only command that applies the promoted-kinds rule to one task. |
| `quantifier_scope_scan.py` | `svc-pc-pipeline/tools/quantifier_scope_scan.py` | Flags instruction quantifiers ("each", "every") against criteria. |
| `rewardkit_pin.py` | `svc-pc-pipeline/tools/rewardkit_pin.py` | Finds tasks that install the grading library without a pinned version. |
| `rubric_consistency_scan.py` | `svc-pc-pipeline/tools/rubric_consistency_scan.py` | Finds a rubric that contradicts itself or hides a schema. |
| `source_reliability_scan.py` | `svc-pc-pipeline/tools/source_reliability_scan.py` | Finds goldens that ignore reliability flags on their sources. |
| `tiered_criterion_scan.py` | `svc-pc-pipeline/tools/tiered_criterion_scan.py` | Finds criteria that describe partial credit in a binary-graded corpus. |
| `gate_groups_fire.py` | `svc-pc-pipeline/tools/gate_groups_fire.py` | Blocks a task whose rubric has more judge groups than the oracle scored. |
| `svc_answer_key_content_leak_check.py` | `svc-pc-pipeline/tools/svc_answer_key_content_leak_check.py` | Finds the literal grading answer inside a file the solver can read. |
| `svc_deliverable_integrity_check.py` | `svc-pc-pipeline/tools/svc_deliverable_integrity_check.py` | Checks every file in the golden folder opens without corruption. |
| `svc_duplicate_criterion_check.py` | `svc-pc-pipeline/tools/svc_duplicate_criterion_check.py` | Flags criterion ids that collide after normalising. |
| `svc_formula_health_check.py` | `svc-pc-pipeline/tools/svc_formula_health_check.py` | Check E: golden workbook formulas with blank or NaN results. |
| `svc_judge_criterion_name_duplicate_check.py` | `svc-pc-pipeline/tools/svc_judge_criterion_name_duplicate_check.py` | Flags two judge criteria with the same name. |
| `svc_judge_determinism_config_lint.py` | `svc-pc-pipeline/tools/svc_judge_determinism_config_lint.py` | Checks the grading config's sampling temperature and sample-count settings (a lint is an automatic style and consistency check). |
| `svc_leak_scan.py` | `svc-pc-pipeline/tools/svc_leak_scan.py` | Compares numbers in criteria with numbers in the instruction and task prompt (comment in the file); no docstring. |
| `svc_mechanical_filename_check.py` | `svc-pc-pipeline/tools/svc_mechanical_filename_check.py` | Checks filenames both ways between judge.toml and instruction.md. |
| `svc_mojibake_check.py` | `svc-pc-pipeline/tools/svc_mojibake_check.py` | Mojibake detector (copy of mojibake_check.py's purpose; the two files differ). |
| `svc_rubric_loophole_check.py` | `svc-pc-pipeline/tools/svc_rubric_loophole_check.py` | Advisory scan for rubric loopholes that survived a first fix. |
| `svc_rubric_schema_check.py` | `svc-pc-pipeline/tools/svc_rubric_schema_check.py` | Validates judge.toml rubric files in a built package. |
| `svc_rubric_static_check.py` | `svc-pc-pipeline/tools/svc_rubric_static_check.py` | Static pre-ship checks on rubric packages. |
| `svc_rubric_text_lint.py` | `svc-pc-pipeline/tools/svc_rubric_text_lint.py` | Text lint over judge.toml for three criterion-writing defects. |
| `svc_tab_naming_check.py` | `svc-pc-pipeline/tools/svc_tab_naming_check.py` | Checks that a criterion naming a tab position matches the workbook's real tab order. |
| `compound_criterion_triage.py` | `deterministic-checks/compound_criterion_triage.py` | Same file name in deterministic-checks (triage layer over compound_criterion_check.py). |
| `certification_gate_check.py` | `deterministic-checks/certification_gate_check.py` | Replays completed judge runs through the rubric's own release rules before a task is certified ready. |
| `post_oracle_gate_check.py` | `deterministic-checks/post_oracle_gate_check.py` | Runs the certification and weight-aggregation checks on completed run output. |
| `comprehensive_review_evidence_gate.py` | `deterministic-checks/comprehensive_review_evidence_gate.py` | Post-run check that every review ends in valid result JSON and every oracle run earns full reward. |
| `review_matrix_check.py` | `deterministic-checks/review_matrix_check.py` | Rejects a review whose criterion-by-mechanism matrix is incomplete. |
| `cross_task_rubric_contamination_sweep.py` | `deterministic-checks/cross_task_rubric_contamination_sweep.py` | Manual sweep for rubric text copied from another task; not registered in either runner. |
| `_analyze_ban_shapes.py` | `deterministic-checks/_analyze_ban_shapes.py` | One-off analysis of word-ban criteria; evidence for a check change, not a check. |
| `_analyze_unique_bans.py` | `deterministic-checks/_analyze_unique_bans.py` | One-off analysis of unique ban words across 600 tasks. |
| `duplicate_task_detector_v0.py` | `deterministic-checks/v0-checks/duplicate_task_detector_v0.py` | Version 0, unvalidated: candidate duplicate tasks for human review. |
| `injection_scanner_v0.py` | `deterministic-checks/v0-checks/injection_scanner_v0.py` | Version 0, unvalidated: instruction-injection pattern scan. |
| `pii_metadata_scanner_v0.py` | `deterministic-checks/v0-checks/pii_metadata_scanner_v0.py` | Version 0, unvalidated: sensitive-looking patterns in metadata. |
| `container_build_check.py` | `deterministic-checks/container_build_check.py` | Checks DataOS can build the task's sandbox (for example a Dockerfile is present). |
| `criterion_condition_count_check.py` | `deterministic-checks/criterion_condition_count_check.py` | Flags a criterion that bundles several separately checkable conditions. |
| `duplicate_criterion_check.py` | `deterministic-checks/duplicate_criterion_check.py` | Flags rubric rows whose criterion ids collide after normalising. |
| `formula_provenance_lint.py` | `deterministic-checks/formula_provenance_lint.py` | Static defects in a task's own formula-provenance checker. |
| `golden_dependency_reachability_check.py` | `deterministic-checks/golden_dependency_reachability_check.py` | Flags a criterion that relies on a script or tool the solver was never given. |
| `harbor_rubric_gate.py` | `deterministic-checks/harbor_rubric_gate.py` | Mechanical stop check against the 15-check Harbor task rubric. |
| `invention_detection_input_check.py` | `deterministic-checks/invention_detection_input_check.py` | Checks the judge is shown the source when a criterion asks if the answer invented something. |
| `judge_input_gate.py` | `deterministic-checks/judge_input_gate.py` | Wires judge_input_report.py into the blocking runners. |
| `judge_panel_size_check.py` | `deterministic-checks/judge_panel_size_check.py` | Checks the grading config lists enough judge models to vote. |
| `layout_formula_advisory_check.py` | `deterministic-checks/layout_formula_advisory_check.py` | Four advisory layout and formula rules from the QC batch 1 to 6 failure analysis. |
| `oracle_reproducibility_check.py` | `deterministic-checks/oracle_reproducibility_check.py` | Finds criteria that give different verdicts on the same bytes. |
| `oracle_reward_details_audit.py` | `deterministic-checks/oracle_reward_details_audit.py` | Audits oracle reward-details.json for criterion-level grading defects. |
| `package_shape_check.py` | `deterministic-checks/package_shape_check.py` | Checks what is about to ship is shaped like a task package. |
| `pre_submit_gate.py` | `deterministic-checks/pre_submit_gate.py` | Runs the 2026-09-17 QCR tracer gates without running the whole EKW registry. |
| `reward_signal_gate.py` | `deterministic-checks/reward_signal_gate.py` | Gate built from the mechanisms behind expert QC feedback. |
| `semantic_consistency_check.py` | `deterministic-checks/semantic_consistency_check.py` | Checks a criterion's required answer follows from the instruction's own logic. |
| `timeout_headroom_check.py` | `deterministic-checks/timeout_headroom_check.py` | Checks grading will finish inside the task's own timeout. |
| `weight_aggregation_check.py` | `deterministic-checks/weight_aggregation_check.py` | Checks the reported reward is not an unweighted mean where the rubric declares weights. |

### Registered checks in deterministic-checks (not repeated here)

The 49 other script files directly in `deterministic-checks/` are the check scripts whose file names appear in `deterministic-checks/svc_run_checks.py` and `deterministic-checks/ekw/ekw_run_checks.py` (found by searching both files for quoted `.py` names). They are described in the family sections, not in this section.
