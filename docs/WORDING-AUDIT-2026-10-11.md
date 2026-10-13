# Wording audit, 2026-10-11: names and numbers a new person cannot understand

Why this exists: a task author asked what "prompt 557" was. The release-check README called it "saved prompt 557" with no name, a CSV column was called `reviews_557_count`, and nothing said it is a review prompt (named answer-check-v11) that authors never run. This audit read the files below for the same problem: something named only by a number, a code or an internal job name, or defined only somewhere else, so a new person cannot tell what it is, who uses it or whether they must act.

## What was done

- Five readers each read one slice of files (the five largest files of slice 4 were split between two helper readers) and added the missing name or a one or two sentence definition at the first use. Their edits are in this pull request. No rule, step, command, path, threshold or number was changed.
- Where the repo gives no answer (an id or code with no name written anywhere), nothing was guessed. Those items are listed below under "Needs an owner" with who probably knows.
- Statements the readers added that a source doc did not support were corrected before this was committed (11 of them, found by checking each added claim against the doc it came from).
- After the audit, six places that still stated the older two-review pass rule were changed to the rule in SOP section 6b (all four Answer Check reviews clean; a major in any one of them fails the task): README.md lines 9 and 111, docs/autofix-agent-quickstart.md lines 16 and 97, docs/ctp-task-guide.md lines 97 and 813. The matching rows below under "Needs an owner" are resolved.

## Not covered by this pass

- `skills/` (instructions that agents read, not people), `svc-pc-pipeline/docs/plan-v6-dataos-as-gate.md` (a dated log), `pipeline/specs/` (specs the review models read), `deliverables/` (records of past work), the `ROUND62-*` reports at the repo root, `deterministic-checks/` design documents.
- The messages printed by the roughly 200 scripts under `svc-pc-pipeline/tools/` and `deterministic-checks/`. Only `qc.py` and the `automation/` scripts were read for printed messages.

## Slices

- Slice 1: Author, QC person and manager docs (README, docs/README, ONBOARDING, both runbooks, review rules, checklists, rubric guideline, docs/svc)
- Slice 2: SOP, CTP task guide, docs/CLAUDE.md, pipeline hardening, DataOS recipe, harbor evals guide
- Slice 3: Script registries, the two how-to-add guides, the comprehensive review prompt
- Slice 4: automation/ folder and qc.py (docs and the messages the tools print)
- Slice 5: svc-pc-pipeline docs and tool READMEs, pipeline README, deterministic-checks READMEs

## Needs an owner (not edited: the repo does not say)

### Slice 1

Nothing in the repo names these, so I left the text and did not guess.

| file:line | the text | what a reader cannot tell | who probably knows |
|---|---|---|---|
| README.md:111 and docs/autofix-agent-quickstart.md:15 (step 6) | "a task passes when both of its Comprehensive Reviews report 0 major" | The runbooks (qc-person:232, manager rule A) and task-review-rules-v2 say four "Answer Check" reviews from pipeline 141 decide it. Whether "Comprehensive Review" and "Answer Check review" are the same thing, and whether the lane flow uses two and the manual pipeline four, is not stated. Also says 2 vs 4 for the pass rule | repo owner or the lead who wrote the SOP |
| docs/task-failure-checklist.md:5 and docs/QC-RUNBOOK-qc-person.md:232 | same conflict: "any of the four Answer Check reviews reports a major" next to "both" elsewhere | same | same |
| README.md:13 | "RL World", "CTP canvas" | what these platforms are and who uses them | repo owner |
| README.md:113, docs/autofix-agent-quickstart.md:24, docs/manager-task-review-guide-v1.md (check list) , docs/rubric-check-1-5-guideline.md Part 2 | Comprehensive Review check ids: "1.1 to 1.8", "1.1 to 1.9", and "check 1.17" in Part 2 | how many checks exist, and which list is current | whoever owns the review prompt |
| docs/ONBOARDING.md:215 | "k=1 eval (Harbor-beta, automated)" | what k=1 means, what Harbor-beta is | EKW cycle owner |
| docs/ONBOARDING.md:324 | "3 evals + 2 Agent Trajectory QC runs per task, no Loss Pattern / Comprehensive Review" | what Agent Trajectory QC and Loss Pattern are | DataOS or EKW owner |
| docs/ONBOARDING.md:50 | "created and submitted weekly by the SOP owner" | who the SOP owner is | the lead |
| docs/ONBOARDING.md:22 | "treat CLAUDE.md as the spec" | docs/README.md calls docs/CLAUDE.md one person's stale conventions. The two statements conflict | repo owner |
| docs/ONBOARDING.md:20-58 | "all three QC phases", "two-phase" cycle, Phase 1/2, `QC_SOP.docx` | docs/README.md says the Markdown SOP replaced the .docx and that the two-phase cycle may be retired | repo owner |
| docs/QC-RUNBOOK-qc-person.md:178-210 | "Check B", "checks C, D and E", F1 to F6 | what each lettered check checks, in one line. I only said the letters are check names | owner of deterministic-checks |
| docs/QC-RUNBOOK-manager.md:316-317 | "AI audit label (UNAUDITED)", "the task read's AI finders" | what the AI audit is and who ran it | author of the numbers table |
| docs/task-failure-checklist.md:57-67 | Part 2 "Class" E to I | where Classes A to D are | checklist author |
| docs/task-review-rules-v2.md:4,60,70 | "KEEP_HELD", "WIP-fix-needed", "WIP rows", "For the sheet, one line per task" | what these statuses mean and which sheet | the manager lead |
| docs/task-review-rules-v2.md:13 | "Answer Check review results (task page, then Verifications, then Comprehensive Review)" | whether this is one click path or two kinds of review | same as first row |
| docs/approval-review-prompt.md:5 and docs/manager-task-review-guide-v1.md:8,23 | "submit as per sop", "managers channel", "Codex and Terminus", "consolidated sheet" (no link) | which SOP, which Slack channel, what the two model runs are | manager lead. Also unclear: the approval prompt is dated 2026-09-29 and v2 names a reviewer prompt of 2026-09-30, so I linked the rules, not the date |
| docs/author-pre-submission-checklist.md:1 and filename | title says "QC person pre-check", filename says "author" | whether authors or QC people use it | SOP owner |
| docs/author-pre-submission-checklist.md:25 | "pipeline quality analysis, 2026-10-08", "478 serious items on 219 tasks" | where the analysis lives | whoever ran it |
| docs/harbor-task-rubric.md:42,48,52 | "section 1.6 leak sweep", "docs/CLAUDE.md Add expert-created verifiers", `*_TRACE.json`, "canary", "rewardkit" | which document has section 1.6; what rewardkit is | EKW converter owner |
| docs/autofix-agent-quickstart.md:67-72 | "pool", "freeze lists", "tracker sheets", "rewardkit 0.1.7" | what these are and where they live | auto-fix agent owner |
| docs/README.md:65,90,91 | "QCR submission doc", "Round 53", "ROUND62" | what QCR stands for (ONBOARDING.md hints "QC request"), what the rounds were | repo owner |
| automation/release-check/known_prompts.json:2 | `"source": "work/trial3a/dl and dl_copies verification jsons..."` | this path is outside the repo; one entry has a null id and name (88 sightings); names such as `pq_R4_V10_2026-10-07` are not explained. JSON cannot hold a comment, so I did not edit | whoever built the file |
| docs/svc/KNOWN_CALIBRATIONS.md:6 | link to `CLAUDE.md` | docs/svc has no CLAUDE.md. docs/CLAUDE.md is a different file. I think TASK_CREATION_CLAUDE.md was meant, not confirmed. Same in TASK_CREATION_USAGE.md:5 | SVC doc owner |
| docs/svc/KNOWN_CALIBRATIONS.md:34,47 | `qc_runs/2026-07-17_...` | folder is not in the repo | SVC doc owner |
| docs/svc/TASK_CREATION_USAGE.md:18-60 | `task-creation-qc/skills/...` paths | the folder "shared with you" is not described or located | SVC doc owner |
| docs/svc/BUILDER_PREFLIGHT.md:10-60 | "Cirrus Sleep Full Y1 corpus", `_FULLCORPUS`, "DVC", `03_dataos_messy`, `C:\ekwqc\svc-builder-windows` | where the corpus is, what DVC is, what "messy" means | SVC builder owner |
| docs/svc/QC_DIMENSIONS_FOR_CREATORS.md:15 | "Six rubric dimensions never run" followed by a list of seven | the count or the list is wrong | SVC doc owner |
| docs/svc/QC_APPLICABILITY.md:105-130 | `WORKBOOK_FINDINGS.md`, `.../qc_review.md`, "Luiz's ruling" | not in the repo | SVC doc owner |
| docs/rubric-check-1-5-guideline.md:5,74 | "I read", "re-run of 277 tasks", "a Claude Code review" | who "I" is, where the re-run results are | guideline author |

### Slice 2

| file:line | the text | what a reader cannot tell | who probably knows |
|---|---|---|---|
| SUMMARY.md:1 | "Round 53 Checker Bug Fixes" | what a round is, who ran round 53, whether anyone has to act on this record | Khiem Doan (pipeline owner) |
| SUMMARY.md:3, 22 | "C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready" | a Windows path on one machine; not in the repo and no way to get it | whoever ran the round |
| SUMMARY.md:48 and similar | "Deviation from report", "the report recommends" | which report | whoever ran the round |
| SUMMARY.md | "FORWARD direction" (Bug 1 title) | what direction a filename check has | author of deliverable_filename_check.py |
| automation/release-check/known_prompts.json:2 | "source": "work/trial3a/dl and dl_copies verification jsons..." | a folder that is not in the repo | whoever built the file |
| known_prompts.json (entry 48d0b791...) | saved_prompt_id null, name null, n_seen 88 | which prompt this is; 88 runs use a prompt with no name | release-check owner / DataOS prompt owner |
| known_prompts.json (many) | pq_R2_..., pq_R3_..., pq_R4_V10..., pq_ext12_no_weight_floor | what "pq" and the R-numbers stand for, and whether authors ever meet these prompts | whoever saved them in DataOS |
| docs/CLAUDE.md:12 | "Project Omega Guide V2" | where the guide lives | Luiz / Khiem Doan |
| docs/CLAUDE.md:185, 325 | memory names `calibration-iteration4-decomposition-n4`, `expert-calibration-verifier-gates`, "iteration 5" | these are assistant memory notes, not repo files, so a reader cannot open them | Luiz |
| docs/CLAUDE.md:335 | "(EKW + DermOTS)" | DermOTS is never defined | Luiz |
| docs/CLAUDE.md:6,193 | "SVC/Cirrus front", "SVC" | what SVC stands for | Khiem Doan |
| docs/CLAUDE.md:198-204 vs 125-147 | `pipeline/templates/dataos_harbor/` and `pipeline/templates/harbor/` | two different template folder names for the same shipped runtime; reader cannot tell which is real | Luiz |
| docs/QC-SOP-first-run.md:220-257 | "L1", "L2", "L3", "Final L2 Tasks / Final L3 Tasks", "L1 source tracker" | what the levels mean and where the folders are (links point to sheets only) | Khiem Doan |
| docs/QC-SOP-first-run.md:5,613 | "NO CLAUDE" pipeline and older ManualQC versions "retired" | stated as retired; the reader need not act, but nothing says how to tell them apart in the DataOS list | Khiem Doan |
| docs/QC-SOP-first-run.md:481 | the blame reader paragraph (about 40 numbers, "151 tasks", "batches 4 to 13") | one paragraph; the reader needs only "a flagged test needs a proof row", which sits in the middle | Khiem Doan |
| docs/ctp-task-guide.md:97 and 813 | "Each pipeline run has two" comprehensive reviews, "both reviews failing" | stale: the SOP and 2.11 say four Answer Check reviews. Not edited because it changes a stated rule | Khiem Doan |
| docs/ctp-task-guide.md:14, 43 | "L3 Authoring" / "Questions to settle #2, #6" | label to confirm; open questions with no owner | CTP tooling team |
| docs/ctp-task-guide.md:518, 525 | "G, H and I warns", "G2 phrase-pin candidate" | letter codes of the pre-submit gate; defined nowhere here | pre_submit_gate.py author |
| docs/ctp-task-guide.md:890 | the current LLM ("Prism") checks | what Prism is | CTP tooling team |
| docs/ctp-task-guide.md:955 | "before Track 2 locks the template" | what Track 2 is | CTP tooling team |
| docs/ctp-task-guide.md:112 and many | "Claire's L2 sample", "L2/L3", "F14", "C01" | who Claire is; L2/L3 task levels; F and C row id prefixes (Form and Content, partly explained at 1.5) | CTP tooling team |
| docs/pipeline-hardening-20260922.md:70-74, 92, 214 | "G1", "G4", "G7", "G8" | gate codes used as names; no definition and no link | author of the comprehensive review doc (docs/ekw-svc-comprehensive-review.md) |
| docs/pipeline-hardening-20260922.md:4, 39 | "QCR CSV batch", "v6/v7 rework drop", "shipped v7 tasks", "the v7 handoff" | what v6 and v7 are (batches, a build, a handoff file); where they are | author of the session |
| docs/pipeline-hardening-20260922.md:272-274 | "Immediate follow-up: 10 live tasks fail the corrected build gate and are unfixed" | no owner and no status; nothing says whether it still blocks anything | author of the session |
| docs/pipeline-hardening-20260922.md:264 | "I initially reported..." | first person, no name of who "I" is | author of the session |
| reference/dataos_recipe/RECIPE.md:3, 61 | `QCR_EKW_Luiz`, "QCR" | what QCR stands for (CLAUDE.md names a QCR_ file but does not expand it) | Luiz |
| reference/harbor_evals_quick_guide.md:3-12 | "ask the run owner for ...", "enqueue cron is suspended", "provider keys are deployed" | who the run owner and the engineer are; where the cron and keys are | Khiem Doan / run owner |

### Slice 3

| file:line | kind | the text | what a reader cannot tell | who probably knows |
|---|---|---|---|---|
| docs/QC-SCRIPT-REGISTRY.md:37 | N1 | "spec 401" (and "NOP" in the DataOS name of prompt 431) | What spec 401 is, where it is viewed, or whether NOP in the name means the empty-answer run. The wording said saved prompt and pipeline were named; the spec has no name in the repo. | DataOS pipeline owner / release-check lead |
| docs/QC-SCRIPT-REGISTRY.md:37 | N3 | "...Opus 5.5 at medium effort).md, section B), not the prompt text itself, so it could not be checked against code." | The sentence is garbled: a fragment ".md, section B)" sits after the parenthesis and the reader cannot tell which document and section it points to. Left because fixing it means deleting or rewriting text. | Author of the registry (commit 7e64189) |
| docs/QC-SCRIPT-REGISTRY.md:482 | N1 | "patched on 2026-10-05 (pull request 94)" | Pull request 94 in which repo or tool. The repo name is not on that line. | Author of the registry |
| docs/QC-SCRIPT-REGISTRY.md:141; docs/QC-SCRIPT-REGISTRY-TOOLS.md:29,32,455; docs/ekw-svc-comprehensive-review.md:69 | N2 | "Check A", "Check B", "Check E", "Check H", "Check F (Oracle)", "Check G (Manual QC / Comprehensive Review)" | What the lettered checks A to H are, who defined the lettering, and which ones an author or QC person runs. Only B, F and G get a short gloss; A, E, H have none. | EKW QC process owner |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:117,271 | N2 | "EQC done", "EQC ready" | What EQC stands for and which tracker column holds it. | QC lead (tracker owner) |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:53 | N1 | "Run by svc_build_upload_zip.py (Gate 1)" | Which gate list "Gate 1" belongs to and what Gate 2 is. | Author of svc_build_upload_zip.py |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:112,133,260,353 | N1 | "batch-10", "batch 15", "batch-15 tasks" | What batch 10 and batch 15 are (DataOS upload rounds? QC batches?) and which tasks are in them. | Coordinator |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:356,357 | N1 | `_notify_1_18.sh`, `_notify_1_19.sh` | What 1.18 and 1.19 are (rules update versions?). The file names carry a bare version. | Coordinator |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:275 | N1 | `svc_writeback_32.py` | What 32 refers to (32 files? a batch?). | Coordinator |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:60,153,215,329,373 | N1 | "v7" (svc_v7_...), "v4 version", "v3digest", "v18 engine" | What each version number is a version of and which one is live. Only v18 is glossed ("a separate framework that grades task sets..."). | Pipeline maintainer |
| docs/QC-SCRIPT-REGISTRY.md:96,117,140; docs/QC-SCRIPT-REGISTRY-TOOLS.md:16,153 | N2 | "SVC lane step", "SVC lane scan step" vs "Lane: one Claude Max account session" | The TOOLS file defines lane as an account session; the REGISTRY rows use "SVC lane" as a stage of a flow. The two senses are not reconciled (I added only a pointer). | Author of the registry |
| docs/QC-SCRIPT-REGISTRY.md:96 | N2 | "evidence for the fix loop" | What the fix loop is and which script drives it. | Author of the registry |
| docs/QC-SCRIPT-REGISTRY.md:209,251 | N2 | "an earlier draft ... filed it under family 4", "the seed files it under family 4", "filed under family 1 in the seed" | "The seed" and "an earlier draft" are working-document history; a new reader cannot tell what they are. | Author of the registry |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:160 | N2 | "pinned first, then near-misses, then fewest majors" | What a pinned task is. | Coordinator |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:21 | N3 | "the counting command is in `REG_TOOLS_COUNTS.txt`" | The file is not in the repo and no folder is given. | Author of the tools registry |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:490; docs/ekw-svc-comprehensive-review.md:338 | N2 | "2026-09-17 QCR tracer gates", "QCR_EKW_16092026" | What QCR is (a review round? a tracker?) and what a tracer gate is. | EKW QC process owner |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:486 | N1 | "QC batch 1 to 6 failure analysis" | Which QC batches 1 to 6 are and where the analysis lives. | QC lead |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:310 | N3 | "agents.turing pipeline page", "Omega tracker" | Where these live (URL or DataOS menu) and who has access. | QC lead |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:292 | N3 | "Work Tracker Evals tab ... provenance columns R to Y", "coverage contract" | Which sheet, and what the coverage contract is. | Whoever fires evaluation runs |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:202-210,205-206 | N2 | "severity addendum v2", "thorough addendum worksheets", "canon spec", "canon review", "sev2" | What each addendum and the canon spec are and where the text lives. | Gate pipeline maintainer |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:231 | N2 | "CLEAR" in "HOLD, READ_FIRST or CLEAR" | What CLEAR means for a task (no flag? safe to ship?). | QC lead |
| docs/QC-SCRIPT-REGISTRY-TOOLS.md:184 | N2 | "GATE-V2" | What GATE-V2 is the second version of and what V1 was. | Gate pipeline maintainer |
| docs/ekw-svc-comprehensive-review.md:7,289 | N3 | "read the workspace-layout skill first", "diagnose it with the exception-diagnosis skill" | Neither skill is in the repo and no path is given. A person cannot find them. | Review prompt owner |
| docs/ekw-svc-comprehensive-review.md:326,230,232,341 | N2 | "the expert reward-signal review", "Prompt ambiguity / Prompt-Tests misalignment / Test coverage" columns | Who "the expert" is and whether this is the TFRL review with the same three columns. Used six times as the source of rules, never named. | Review prompt owner |
| docs/ekw-svc-comprehensive-review.md:7 | N3 | "tracker history" | Which tracker (the file is not in the repo). | EKW QC process owner |
| docs/QC-HOW-TO-ADD-TO-RL-WORLD.md:7,124,161,199 | N3 | "RL World's own QC notes", "RL World's calibration and QC rules" | Which RL World document these are; no path or link is given, and four claims lean on them. | Author of the RL World doc |
| docs/QC-HOW-TO-ADD-TO-RL-WORLD.md:296 | N3 | "the explain notes say they record it" | Which notes are meant. | Author of the RL World doc |
| docs/QC-HOW-TO-ADD-TO-RL-WORLD.md:51 | N2 | "calibration Auto-QC" (first use at line 51, defined only by a doc link) | What Auto-QC runs and whether a person acts on it. | RL World team |
| docs/QC-SCRIPT-REGISTRY.md:93; docs/ekw-svc-comprehensive-review.md:75 | N2 | "SVC-PC" (used without a definition; EKW is glossed only in the REGISTRY glossary) | Whether SVC-PC is the same as SVC or a subset. | Author of the registry |
| automation/release-check/known_prompts.json:2 | N3 | "source": "work/trial3a/dl and dl_copies verification jsons ..." | A folder that is not in the repo; a reader cannot find where the prompt list came from. JSON cannot hold a comment and the file is read by the tool, so it was not edited. | Release-check lead |
| automation/release-check/known_prompts.json:13-20 | N1 | entry with "saved_prompt_id": null, "name": null, "n_seen": 88 | An unnamed prompt seen 88 times; nobody can tell what it is. Left because I may not invent a name. | Release-check lead |
| automation/release-check/known_prompts.json:various | N2 | names "pq_R2_opus_R2_2026-10-07", "pq_R3_R3_194027...", "pq_ext12_no_weight_floor_2026-10-06", "Latest_comprehensive" | What pq, R2 to R6, ext12 and Latest_comprehensive mean (experiment arms? who runs them?). Only 557, 431 and the TFRL-style entry have names given in the brief. | Release-check lead |

### Slice 4

Paths in the first column are under automation/ unless they start with qc.py. Rows in release-check READMEs, make_table.py, build_export_from_zip.py and test files are findings only (not edited, by the brief).

| file:line | kind | the text | what a reader cannot tell | who probably knows |
|---|---|---|---|---|
| release-check/README.md:3 | N2 | job B12_WITHRUNS | what job this is, whether a reader needs it | release-check author |
| release-check/README.md:35 | N1 | prompt 431, prompt 145 (also 557, in the lead's slice) | names: 431 = Comprehensive_v3_pipeline_quality_re-derive_cascade_NOP_2026-10-03, 145 = Latest_comprehensive (known_prompts.json); README gives numbers only | lead (557 wording) |
| release-check/README.md:21-23,31 | N1 | check 1, check 2, check 3 | the README never names the three checks; the names are only in README_v1_checks.md | lead / release-check author |
| release-check/README.md:22 | N5 | columns call_with_check1_at_3_attempts, missing_inputs | what 'check1 at 3 attempts' means in the table; only the one-line list explains it | release-check author |
| release-check/README_v1.md:3 | N2 | job B12_PORTRC | same as B12_WITHRUNS | release-check author |
| release-check/README_v1.md:57-67 | N3 | final/releasecheck_v1, final/step2, final/step3, 'vendored' | these folders are not in the repo; a reader cannot find or compare them | release-check author |
| release-check/README_v1.md:67 | N2 | 'a lane name', 'sandbox helper' | what a lane is; says release_check always passes local | release-check author |
| release-check/README_v1.md:84-95 | N3 | downloader _scratch_dataos_download_sb.py, 'ask Khiem' | where the downloader lives and who Khiem is; the DataOS pages are marked unconfirmed | Khiem or a manager (the file says so) |
| release-check/README_v1.md:99, README_v1_checks.md:120 | N5 | overall values NEEDS INPUT (release_check.csv) vs EVIDENCE MISSING (release_table.csv) | two names for the same state, in two output files; no sentence says they match | release-check author |
| release-check/README_v1_checks.md:3 | N2 | job B12_RELEASECHECK | same as B12_WITHRUNS | release-check author |
| release-check/README_v1_checks.md:112 | N3 | 'Rule A', final/v13_proposal/RULES_BY_HAND.md | the rules document is not in the repo | release-check author |
| release-check/README_v1_checks.md:122,126 | N2 | V11B1213, rule R3, 'version 11' | what the V11B1213 batch is; what R3 is (only in the vendored gate.py, which is missing here); version 11 is answer-check-v11 | release-check author |
| release-check/README_v1_checks.md:7 | N2 | oracle, Codex, Terminus, 'sandbox' | oracle is defined there; Codex and Terminus are called 'the AI solvers'; fine for QC people but 'sandbox' is not explained | release-check author |
| release-check/make_table.py:52,91 | N5 | cell values NO 557 REVIEW, NO REVIEW ON SPEC <n>; column reviews_557_count | numbers only, no name; tests assert the column | lead (557 wording) |
| release-check/build_export_from_zip.py:355 | N5 | reviews_not_used.csv reason: prompt is 431 (name), not saved prompt 557 | prints the name for the seen prompt but not for 557 | lead (557 wording) |
| release-check/release_check.py:55,443,453 | N5 | columns check1_c_fail, check2_v11, check3_gate, check3_rules; check3_rules holds bare codes (P0, S1, R1, F1, R3) | c_fail and v11 are never defined; codes are named only in check3_missing_inputs, and only for P0, S1, R1, F1. Not renamed: test_release_check.py asserts them and make_table.py reads them | gate owner (vendored gate.py) |
| release-check/release_check.py:7-8,16 | N3 | 'work/V11B1213 layout', 'saved prompt version 11' | an export layout in a folder that is not in the repo | release-check author |
| manager-read/README.md:3-4, manager_read.py:2,5 | N3 | 'the step 3 manager reader', 'the audit sandbox' | step 3 of what, and what audit; not defined in the repo | manager-read author |
| manager-read/README.md:5 | N1 | docs/QC-RUNBOOK-manager.md, rule D | path is given but docs/ is not in this repo and rule D is not defined here | manager runbook author |
| manager-read/README.md:60-83 | N2 | truth_v5, material_tabrule, MGRADVIS, FAOPUS, seed 12, batches 4 to 13, out/*.md, work/mgradvis | internal run names and files outside the repo; a QC person cannot tell if any matters (the section is measurements, no action) | manager-read author |
| manager-read/prompts/manager_prompt.md:12-28 | N2 | manager rules v3; type letters U, A7, A1, O, C, D, R; Y1 | model-facing and locked by PROMPT_SHA256, so not edited. The printed report does explain each type letter in its What is wrong line | manager-read author |
| manager-read/manager_read.py:~365 | N5 | item header '### 1. U on d1/heavy' | type letter printed alone in the header; TYPE_TEXT explains it two lines below. Left to keep the report format | manager-read author |
| task-read/README.md:13 | N3 | 'the manager's version 2 guide reader', rules A1 A2 A3 A7 | the version 2 guide is not in the repo; the four rules are defined in the same sentence | task-read author |
| task-read/README.md:57-62, task_read.py:94-99 | N2 | 'batches 4 to 13', 'pipeline-quality sandbox runs of 2026-10-08', 'the audit', 'evidence kept by Khiem Doan'; LIMITS prints batches 4 to 13 and 'the audit' in every report | which batches and which audit; where the evidence is | task-read author (Khiem Doan per README) |
| task-read/prompts/v2_reader.md, finder_a.md, finder_b.md, verifier.md | N2 | Tier A / Tier B, A1 to A7, B1 to B3, 'Defect finder FA' | model-facing, sha256 listed in the README, so not edited; the report prints plain text for A1, A2, A3, A7 | task-read author |
| ekw-qc-cycle/SKILL.md:1-12 | N2 | EKW-GDPVal, 'harbor-bundle', 'the evaluator', 'the owner' | a routine prompt read by Claude, not a person; left unedited. README.md says the same terms without definitions | QC lead |
| README.md:16-17 | N3 | 'the QC SOP', 'harbor format', 'Internal QC cycle' | SOP location not given in the repo (tp-fp SKILL.md points to docs/QC_SOP.docx, absent here) | QC lead |
| qc.py:5 | N2 | 'first-run checks (B to F)' | which checks B to F are; code is in deterministic-checks/ekw, not in this repo | owner of deterministic-checks/ekw |
| qc.py:8,944,1035,1226,1283 | N3 | 'SOP 6c' (1226 and 1283 are printed) | which SOP document, where it lives | QC lead |
| qc.py:597,1485,1493 | N1 | 'step 6 cannot be finished', 'Start step 6 again' (597 and 1485 are printed) | step 6 of what; the usage text numbers steps 1 to 3 only | QC lead |
| qc.py:305 | N1 | printed: docs/QC-RUNBOOK-manager.md, rule D | docs/ not in this repo; rule D not defined here | manager runbook author |
| qc.py:496 | N3 | printed: 'the Once section of the QC person run sheet' | where the run sheet is | QC lead |
| qc.py:296 | N5 | manager_summary.csv column 'rev' (bare number) | that it is the revision number; not renamed because qc_test.py line 1250 asserts the header | whoever reads that CSV |
| qc.py:226 | N5 | release table value RELEASE | HOLD and EVIDENCE MISSING are explained in the printed message, RELEASE is not | release-check author |
| tp-fp-classification/SKILL.md:37,144,170,431,607,720,906 | N3 | docs/QC_SOP.docx, docs/CLAUDE.md, docs/svc/KNOWN_CALIBRATIONS.md, pipeline/cycle.py, pipeline/tools/to_rewardkit.py, pipeline/gdpval_qc/v18_emitter.py | none are in this repo and nothing says which repo or drive holds them | pipeline engineer or QC process owner |
| tp-fp-classification/SKILL.md:719-722,753-787 | N3 | shared Drive upload folder, 'QC Task Tracker' tab, 'QC Task Overview' tab | no location given | QC lead |
| tp-fp-classification/SKILL.md:230 | N2 | SVC-PC | not explained anywhere in the repo | task owners |
| tp-fp-classification/SKILL.md:791-792 | N2 | 'ultracode', 'the Workflow tool' | unexplained | skill author |
| tp-fp-classification/SKILL.md:44, gate-mining/SKILL.md:34 | N4 | 'paste this file into a fresh session' | who does this, and whether a task author ever does | QC lead |
| tp-fp-classification/batch-scan-gates.md:19-25 | N3 | 'paste into tool' | which tool or field | gate owner |
| tp-fp-classification/batch-scan-gates.md:562 | N2 | GDPVal/Omega | not defined | gate owner |
| tp-fp-classification/batch-scan-gates.md (whole) | N4 | gate hits | does not say whether an author or QC person has to act on a gate hit | gate owner |

### Slice 5

| file:line | the text | what a reader cannot tell | who probably knows |
|---|---|---|---|
| deterministic-checks/README.md:29 | columns M1-M6, "criterion × mechanism matrix" | what M1 to M6 are | Khiem Doan (author of review_matrix_check.py) |
| deterministic-checks/README.md:30 | "DataOS's `QC` reviewer", "QCR_EKW_16092026" | what the QC reviewer is (not the Answer Check), what QCR_EKW_16092026 names | Khiem Doan |
| deterministic-checks/README.md:32,35 | "v7 submitted batch", "fix-task-from-review's GAP 5" | which batch v7 is; where that skill and GAP 5 live | Khiem Doan |
| deterministic-checks/ekw/README.md:66 | "DataOS dataset 608 (Oracle batch 2313, 112 pass, 7 fail)" | no name for dataset 608 or batch 2313 | Khiem Doan |
| deterministic-checks/OVERVIEW.md:153 | "EKW's judge-config owner" | who this is; ekw/README.md says the 269 flags were fixed on 2026-09-14, OVERVIEW still reads as open | Khiem Doan |
| deterministic-checks/ekw/README_sixq.md:4,46 | docs/author-pre-submission-checklist.md, out/SIXQ.md | neither file is in the repo | Khiem Doan |
| pipeline/README.md:382 and NEW_QC_GATES_PLAN.md | "one real omega task", `[TIE]`, `[OMEGA]` markers; repo x-gdpval-enterprise-workflow | what omega and TIE are; where that repo is; who runs gdpval-qc and whether it is part of normal QC | Mahesh Joshi (named as requester) |
| svc-pc-pipeline/README.md:10 | "first L3 pass (46-0-0)" | what L3 is | Khiem Doan |
| svc-pc-pipeline/README.md:24 | docs/plan-v6-dataos-as-gate.md | the plain guide and runbook point at ekw/plan-2026-09-21-v6-dataos-as-gate.md instead; one path is wrong | Khiem Doan |
| svc-pc-pipeline/README.md:78, task-doc.md:43 | `Skip- duplicate`, `EQC Ready Revision`, "EQC" | what EQC stands for; these are fixed cell values the tools write into the sheet (N5) | QC-team SOP owner, Inhee Park |
| svc-pc-pipeline/docs/comp-review-proposed-block-golden-demand.md:3,15 | "dataset 3424", "control run (#962, prompt #145 unchanged)", E1 to E15 | names of dataset 3424 and run 962; what E1 to E15 are | Khiem Doan (hold-review lane) |
| comp-review doc, GOLDEN_REVIEW_EVIDENCE.md:5,23,141 | "hold-review lane", "field-engineer session", "CTP's lane", "job-B", "Pipeline quality" lane | these are session or team names; none is defined | Khiem Doan |
| qc-intake-process.md:40,118,237,243,353 | "weekend review sheet", `/draft`, `b9r`, `copyInto2`, `/qc-zero-pass-review`, "codex" | where each lives and what it is | Khiem Doan |
| qc-intake-process.md:193,204, 440 | "in turing-context" (branch/paths such as ekw/2026-09-29-...) | what turing-context is and how to get it | Khiem Doan |
| svc-pc-one-shot-fix-guide.md:1,547 | "Comprehensive Review" | how it relates to the four Answer Check reviews now used (guide still mixes both names) | Khiem Doan |
| svc-pc-one-shot-fix-guide.md:303,342,549, Appendix D | `staged_svc68_1_fix/...`, `scratch/docgen/gen.js` | files on an author's machine, not in the repo | Khiem Doan |
| svc-return-runbook.md:29,34 | "QC-team SOP (doc 1IL2s3ez..., section 7c)" | id truncated, Drive doc not linked | Khiem Doan |
| svc-return-runbook.md:3,37,255 | "v8.1", "verify_capped vs full READY", "MVP config", "tier2" | v8.1 reads like pipeline version 8 but is the sequence version; the others are undefined | Khiem Doan |
| svc-pc-pipeline/skills/task-doc.md:40 | `Ardeshir_team` (TRL-QC) | who this team is; runbook says it is unclear whether it still needs access | Khiem Doan |
| judge_emulate.README.md:109, arithmetic-review.md, judge_emulate_REVIEW.md | "GATE-V2 3.1", "GATE-V2 class H", "GATE-V2 3.0" | what GATE-V2 is and where it is written | Khiem Doan |
| svc-pc-plain-guide.md:190 | "the standing ask to Shyam", "decided per track" | who Shyam is and what a track is | Khiem Doan |

## The worst places for a new person, by slice

### Slice 1

1. **The pass rule is stated two ways.** README.md:111 and the auto-fix quickstart say "both Comprehensive Reviews report 0 major"; the QC person sheet, manager sheet and review rules v2 say four "Answer Check" reviews, and the pipeline name appears with no hint that these are the same reviews. A new person cannot tell which reviews decide a task. I could not fix this because the repo does not say.
2. **docs/ONBOARDING.md** tells a reader to follow a three-phase `QC_SOP.docx` and to "treat CLAUDE.md as the spec", while the doc index says both are old or personal. It also uses k=1, Harbor-beta, Agent Trajectory QC and "the SOP owner" with no definition.
3. **Lettered check codes in the run sheet.** "Check B", "checks C, D and E", F1 to F6, and Class E to I in the failure checklist are shown to the person running the tool with only a generic gloss from me.
4. **Review rules v2 status words.** KEEP_HELD, WIP-fix-needed and "the sheet" are used with no definition, and the file's own header says it is a proposal while the doc index marks it CURRENT.
5. **SVC docs with dead pointers.** KNOWN_CALIBRATIONS links to a `CLAUDE.md` that is not in that folder, TASK_CREATION_USAGE points to a `task-creation-qc/` folder nobody locates, and BUILDER_PREFLIGHT needs a corpus whose location is not given. The status line I added at least tells the reader these are stale.

### Slice 2

1. docs/QC-SOP-first-run.md:481 (the blame reader paragraph): a single paragraph with around 40 numbers and batch ranges that a QC person must read to find one instruction, with no name for what a flagged test costs them until the middle. Not fixed because splitting it would be a rewrite. 2. docs/QC-SOP-first-run.md:220-257 (L1, L2, L3, Final L2/L3 Tasks, "35", "17", "18" task lists): the reader is told where a package comes from using level names that are never defined. 3. docs/ctp-task-guide.md:97, 813 and the "Each pipeline run has two" row: it contradicts the four-review pipeline stated at 2.11, so a trainer cannot tell which count is right (listed, not edited). 4. docs/pipeline-hardening-20260922.md (G1, G4, G7, G8, v6/v7): gate codes and batch versions are used as names throughout with no definition, so a new person cannot follow the defect table. 5. docs/CLAUDE.md:7 to 12 and 335 (SVC, DermOTS, Project Omega Guide V2, assistant memory names): the whole file assumes the reader already knows these names, and the memory names point at notes that are not in the repo.

### Slice 3

1. QC-SCRIPT-REGISTRY.md:37, the explanation of the review prompt: it read "saved prompt 431, used by pipeline 141 version 8, spec 401" with no names, then a garbled tail (".md, section B)"). The names for 431 and 141 are now in, but spec 401 and the broken sentence remain. 2. QC-SCRIPT-REGISTRY-TOOLS.md, the lettered "Check B", "Check E", "Check H" and "EQC" labels (lines 29, 32, 117, 455): a QC person cannot tell whether these are steps they run or tracker words. 3. QC-SCRIPT-REGISTRY.md, the bare step numbers "1.4", "1.6", "1.8" in rows and docstring quotes: they look like step numbers of the script but are check ids in another document (now glossed). 4. known_prompts.json: an entry with no name seen 88 times, and run-arm names (pq_R2 and so on) with no meaning anywhere in the repo; JSON cannot carry the explanation, so the README must. 5. ekw-svc-comprehensive-review.md: "the expert reward-signal review", "Check F / Check G" and two skills (workspace-layout, exception-diagnosis) that a human cannot find; the document tells the reader to read them first.

### Slice 4

1. release-check README.md, README_v1.md and README_v1_checks.md: the three READMEs a QC person is sent to are stacked (v2 refers to v1, v1 refers to a copy of an older README), and use three job names (B12_WITHRUNS, B12_PORTRC, B12_RELEASECHECK), "Rule A", R3 and V11B1213 with no definition, so a reader cannot tell which README is current or what to do with a HOLD, NEEDS INPUT or EVIDENCE MISSING row. 2. The output table of release-check: column names check2_v11 and check1_c_fail, the bare gate codes in check3_rules, reviews_557_count and the NO 557 REVIEW cell show numbers and codes to the person running it, and NEEDS INPUT (release_check.csv) and EVIDENCE MISSING (release_table.csv) name the same state in two files. 3. qc.py printed pointers "SOP 6c", "step 6" and "the Once section of the QC person run sheet": the person is told to go somewhere that is not in the repo and the usage text only numbers steps 1 to 3. 4. manager-read README: "step 3 manager reader", "audit sandbox", truth_v5, material_tabrule, MGRADVIS, FAOPUS and "rule D" in a document a manager reads to know whether to approve; the measurements section does not say it needs no action. 5. tp-fp-classification SKILL.md and batch-scan-gates.md: they point at docs/QC_SOP.docx, docs/CLAUDE.md, pipeline/cycle.py and a shared Drive folder that are not in this repo, and batch-scan-gates.md never says whether anyone has to act on a gate hit.

### Slice 5

1. **svc-pc-one-shot-fix-guide.md** title and section 8: it tells authors to "pass Comprehensive Review" and "re-run the DataOS Comprehensive Review", while the same guide's pass rule is now the four Answer Check reviews; nothing says whether they are the same thing. 2. **deterministic-checks/README.md** capability table: rows packed with G1 to G9, H1, I1, F2, M1 to M6, "QC reviewer", v7 batch and task-specific ids, with no statement of who runs which check or whether a fail blocks a task. 3. **svc-pc-pipeline/README.md** steps 2 to 5: lanes, decide mode, TASK or GATE, L3, EQC values and QCR are all shorthand; I defined the ones the repo supports, but L3 and EQC remain. 4. **qc-intake-process.md** batch log (QC_batch1 to 9): sheet ids, "b9r", "copyInto2", "codex", "turing-context" and personal names with no definition; a new QC person cannot tell which of it is theirs to do. 5. **GOLDEN_REVIEW_EVIDENCE.md and the comp-review block**: bare run, dataset and prompt numbers (#962, #1170, 3424, E1 to E15) and team labels (hold-review lane, CTP, job-B, field-engineer session) that are never named.

## Second pass: newcomer reads and fixes (2026-10-11)

Four readers were each given only the files of one role (4 to 9 files) and asked to walk the process as a newcomer. None could run its part alone. The counts below are theirs; they understate what a full clone gives, because every link to a file outside the role's set counted as missing. They are still the right list of what a beginner must be told in the file itself.

| Reader (role) | Files given | Steps enough to act on without guessing |
|---|---|---|
| QC person | 4 | 16 of 30 |
| Manager | 8 | 5 of 20 (9 partly) |
| Task author | 8 | 6 of 31 (14 partly) |
| SVC operator | 9 | 9 of 44 |

Fixes from these reads were applied in this pull request under four rules: the SOP wins where two files disagree; stale guides get a status line; a command is added only if `qc.py --help` lists it; no click path is written unless a file already states it. What the rules could not settle is below.

### QC person and author path: left for the owner

| file:line | the text | why a rule could not decide | who probably knows |
|---|---|---|---|
| SOP:178 and SOP:777 | "If you finish or abandon a task, clear AH and AI so it goes back into the pool." vs "clear your claim ... so the task shows as done, not still claimed." | The SOP contradicts itself on what a cleared claim means for a finished task (R1) | SOP owner (Khiem) |
| SOP:161 and SOP:346 | "EKW Tracker tab" with gid=1236768796, and "EKW Tracker tab" with gid=2072059214; SOP:370 "EKW QC Tracker Combined tab"; ONBOARDING:166 "Omega - Task Tracker - Tasks" tab | One tab name has two ids inside the SOP, and a third and fourth name appear. ONBOARDING's tracker may be a separate sheet for `cycle.py`, which no file says | SOP owner (Khiem) |
| SOP heading 5a vs SOP:473-479 | 5a is titled "(before you run the DataOS pipeline)"; its proof paragraph needs the `rev_<n>__<id>` folder "from the Dataset with runs download" | Heading and paragraph disagree inside the SOP: a proof sheet cannot exist before the first DataOS run. RB step 6 does it after DataOS | SOP owner |
| SOP:570-575 and SOP:593 | step 4 lists Q1 to Q5, then "Those four questions cover 49 of the 60"; step 7 "re-checks Q1 to Q4" | SOP contradicts itself on whether Q5 is part of the per-criterion audit | SOP owner |
| SOP:769 | "`--list`/`--tree`/`--zip` are required here" for `svc_fast_zip.py` | The tool's own help says `--list` is optional when task names are given. This is the SOP against the tool, not file against file, so R1 and R4 do not cover it. I worked around it in RB:248 | owner of `svc_fast_zip.py` |
| SOP:726-727 | "From the next batch the manager also applies rules B to E ..." | No date or batch number, so no file says whether it applies now (COLDSOP Q11) | Manager run sheet owner (Khiem) |
| SOP:535 vs SOP:803 | "a correct answer that follows the prompt loses credit ..." vs "A Major issue is one that blocks models." | Two wordings of Major; the SOP does not say they are the same | SOP owner |
| SOP:645, SOP:653-655 | 6c says to copy the skill file to `~/.claude/skills/...` and uses bash `$(cat ...)` | `qc.py update` help says it refreshes the skill file, and `qc.py review` reads it from the repo, but I did not run `review`, so I added no "you do not need to copy it" sentence | SOP owner |
| RB:332 area and SOP:733 | Hand-over list omits `siblings.md`, `siblings_answers.csv` and the pre-check notes file; "Doc or folder" and who may read it | SOP 7 only requires the 6c table; the manager run sheet (not in my repo) decides what else is checked | Manager run sheet owner |
| RB:129 | "Write each answer in a notes file" | No file says the notes file's name or where it goes. I did not invent a name | SOP owner |
| RB:169 area | Whether to re-run `qc.py read` after fixing | Not stated anywhere in the five files | SOP owner |
| RB:513-514 area (Approved) | "Fill the columns up to the DataOS link"; when to clear AH and AI | Not stated; AH/AI contradiction above | Khiem |
| RB:458 | "your lead posts a new copy each weekend"; what `TASK-LINK` is | No file says which copy or what link | Lead |
| RB and SOP 6a step 7 | "An independent reviewer ... returns READY-TO-RESUBMIT" | No file names the reviewer or a command | SOP owner |
| SOP:561-596 | Arguments for `svc_prefilter.py`, `svc_coverage_trace.py check <map>` (map file format), `judge_emulate.py`, `svc_eval_regrade.py`, `svc_build_upload_zip.py`, `svc_bundle_upload.py`, `svc_record_return.py` | Not verifiable here (R4); I did not copy usage I could not check | Owner of `svc-pc-pipeline/tools` |
| SOP:21-22 and 609-610 | Which of the DataOS entries TESTING..., "...copy", CompanyBench... and automated_qc_pipeline are for what; what to do about a version above 8 | The SOP is silent on these names (R1) | Pipeline owner (Khiem) |
| SOP 6b | Who pays about 3.15 USD per run; any limit on reruns | Not stated | Lead / Khiem |
| SOP:3, README:7 | Who "my lead", "my manager" are; QC team Slack channel name; what Luiz's role is; how to get a Claude Max login or the GLM key; Claude Code install link | Not stated anywhere in my files | Whoever onboards you |
| README:8, DR:33, DR:74, author-pre-submission-checklist:3 | Whether the SOP is for task authors or QC people. The SOP never names its reader as "author"; its steps address a QC person | Index and README call it the authors' SOP, the checklist says it is for the QC person; the SOP is silent (R1). Also no file walks an author through writing a task from a blank page, and I cannot claim that no such file exists from the five I edited | Khiem |
| README:3, DR:3 | "Last checked: 2026-10-02" while the index lists files dated 2026-10-06, 2026-10-09 and 2026-10-11 | I did not re-check the repo against main, so I cannot truthfully update the line | Whoever maintains the index |
| README:113 | Glossary entry "Comprehensive Review ... Each finding has an id (1.1 to 1.8)" | The SOP now names the four reviews "Answer Check"; no file says whether Comprehensive Review still exists as a separate DataOS review | SOP owner |
| ON:305-306 | `cycle.py dataos` "drafts ... the `#TFRL_QC` Slack message" | Describes what the script writes; I did not change it. Whether to stop drafting it is a code decision | `cycle.py` owner |
| ON:381 vs SOP:372 | "6+ atomic ... checks" vs "`verifier.json` (15 to 25 rubric checks)" | Not clearly a conflict (a minimum vs a description of arriving tasks); no rule decides | SOP owner |
| SOP:385 vs ON:342 | `/workspace/...` in ONBOARDING section 8 vs the converter that "points every /workspace/... path at /app/" in the SOP | Not a conflict inside my files: the SOP says the converter does the change. The file does not say which path an author writes | SOP owner |
| SOP:397 vs ON:275 | Judge models: `anthropic/claude-sonnet-4-6` (package judge), "GPT-5.5 + Gemini-3.1-pro" (`gdpval-assess`), Opus 5.5 (Answer Check) | Different tools, no file maps which one affects a task author | SOP owner |
| SOP:473 area, 6a step 8 | Who does 6a step 8 (RB: "your lead's"; SOP: the lane runner for queued tasks) | The SOP does not say who does it for a QC person | Khiem |
| Outside my files | docs/rubric-check-1-5-guideline.md line 62 ("Both reviews accept" = both Comprehensive Reviews with 0 major and 0 minor); docs/harbor-task-rubric.md lines 153 and 157 (formula gates, oracle "1.0 (or ... explained)"); docs/author-pre-submission-checklist.md lines 3 and 5 ("not a gate"; heavy rules only) | By R1 the SOP wins in each case, but these files are not mine to edit | Owners of those files |

### QC person and author path: needs a click path

Nothing in any file states these (R5). Exact questions:
1. In DataOS, where do I upload a zip as a new dataset, and which project and what name do I give it?
2. Where do I start a pipeline run on a dataset and what settings, if any, does the form ask for?
3. Where in a finished run do I open each of the four Answer Check reviews and see its JSON (`overall_verdict`, `findings`)?
4. Where do I see the five run scores (the oracle runs and the empty-answer run) for a task?
5. Where is the "Dataset with runs" button (run page or dataset page), and if I ran the pipeline more than once, which run does it download?
6. How do I share a dataset with Khiem, Andrew_team and Luiz as ADMIN?
7. How do I run the oracle or the empty-answer evaluation alone (before the full pipeline), as 5a items 1 and 2 ask?
8. Where in DataOS do I see a rejection from TFRL and its written findings, and how does the manager tell me a task is Approved or Rejected (channel or column)?
9. Which Google Drive location should the hand-over Doc or folder be created in, and who must be able to read it?

### manager path: left for the owner

| file:line | the text | why a rule could not decide | who probably knows |
|---|---|---|---|
| V2:4 vs docs/README.md:54 | V2 "Status: proposal. Not yet shown to work ... reading order, not a pass bar" vs index "CURRENT; replaces the nine DENY rules" | SOP 7 sends the manager to V2 but never says whether it is a pass bar or a proposal | Khiem Doan or the V2 author (D1, Q16) |
| V2:57 vs RB:162 | V2 "(1 is enough on the manager's own tasks)" | SOP 5a says at least two oracle runs and is silent on managers' own tasks | Khiem Doan (D4) |
| V2:25, V2:57, V2:95 vs RB:295 | V2: CAN'T JUDGE YET for no model runs, fewer than 2 oracle runs, no review, unreadable task. RB: only "D2 failed twice, or the oracle evidence is missing", and rule A sends back when fewer than four reviews finished | SOP is silent on CAN'T JUDGE YET and on the sheet Status for it | RB author (D5) |
| RB:160, RB:250 | "send ... to your lead" | SOP names a "QC lead" (582) and "your manager or the QC lead" (667) but not who a manager's lead is or the channel | Khiem Doan (Q4) |
| RB:295-306 | Tell the author | SOP 7 says the manager sends the task back to the QC person, not how or where. Guide v1 section 6 (now stale) said a Slack reply in the author's thread | Khiem Doan (Q5, D15) |
| RB:289 | "your lead posts a new copy each weekend", "If another name is already there, ask that person" | SOP is silent on the review sheet copies | Lead who posts the sheet (Q15) |
| RB:32, RB:116 | "the dataset the QC person named"; the Doc or folder linked in the row | SOP 7 covers the consolidated sheet and sharing with Khiem, not how the QC person names the dataset to the manager | RB author (Q3-step in (a)) |
| RB:324-326 | "After TFRL names a defect" | No file says how a manager learns TFRL named one or what "same kind" means | Khiem Doan (Q13) |
| RB:231-265 | When an answer is "unbelievable" | Tests exist only for FIXED and NOT A DEFECT; no rule for other cases | RB author (Q11) |
| RB:308-322 vs V2:39 | V2: "Do not quote a catch rate or a false-flag rate"; RB prints a TP/FP table | SOP silent. I added only the "early and unaudited" label. V2:39 also asks for a date on any rate, and no file gives one | V2 author (D9) |
| README.md:113 vs G1:38 | Finding ids "1.1 to 1.8" vs "1.1 to 1.9" | The defining file (docs/ekw-svc-comprehensive-review.md) is not in the repo; SOP is silent | Author of the review prompt (Q12, D7) |
| README.md:117 | EQC | The repo never spells it out | Khiem Doan (Q14) |
| README.md:3, docs/README.md:3 | "Last checked: 2026-10-02" while the run sheets are dated 2026-10-09 | README says to run `docs/check_links.py` and re-read before changing it; I did not | Whoever merges the PR (D16) |
| automation/release-check/README.md:3 | Points to `README_v1.md`, absent from the repo | Cannot tell whether the file was dropped or never added | Release-check author |
| automation/release-check/README.md:43 | "prompt 145 (2 reviews)" | No file says what prompt 145 is | Release-check author (Q9) |
| docs/README.md:57 and RB, V2 links | `WORDING-AUDIT-2026-10-11.md` and `ekw-svc-comprehensive-review.md` | Not in the repo copy I was given; link target may be in another PR | PR owner |
| RB:293 | Case 3 (EVIDENCE MISSING): whether to write it in the sheet | RB rule F says Why is one sentence and is silent | RB author |

### manager path: needs a click path

1. Where on the DataOS task page is the run list (the Evaluations tab or list), so a manager can read the oracle runs, the solver runs and the empty-answer run? (Only the old guide v1 says "Evaluations list on the task", and it is now marked stale.)
2. How does a manager tell the four Answer Check reviews of pipeline 141 version 8 from other reviews on the same task page (a label, a pipeline name column, a prompt id shown)?
3. Which DataOS screen shows the pipeline name and version a review came from?
4. How do you download a Google Drive folder or Doc the QC person linked (button names), and how does a QC person put `manager_answers.md` there?
5. Where in the review sheet is the Doc or folder link (which column), and which tab holds the current weekend copy?

### SVC path: left for the owner

| file:line | the text | why a rule could not decide | who probably knows |
|---|---|---|---|
| runbook:77 vs README(pipeline):108 | runbook step 9: 'tag `cirrus sleep`'; pipeline README: "Dataset tag `ekw`" for EKW | SOP names no tag (R1 silent). The two may both be right (SVC vs EKW) but no file says so | Khiem Doan |
| runbook:36 vs runbook:215-216 | "Column C is a LINK (`--doc-url`, required)" vs "C QCR doc title" | The first is in the CURRENT SEQUENCE, the second in history, but SOP 752-755 does not name column C | Khiem Doan (owner of the consolidated sheet) |
| runbook:76 vs runbook:144, 150, 271 | "Upload (delegated to Claude since 2026-09-22 ...)" vs "Uploading the `ready/` zips is still the user's action" | SOP 6b step 1 says "Upload the bundle" without an actor | Khiem Doan |
| runbook:195-196 vs README(pipeline):49-52 vs SOP 627-632 | "cap 3 DataOS rounds/task total; after 3, cut as irreparable" vs 10 lane attempts then decide mode vs no cap in the SOP | SOP is silent on a cap for a person; the 3-round line is in the history part | Khiem Doan |
| SOP:572-575 vs SOP:593-595 | "Q1 ... Q5" listed, then "Those four questions cover 49 of the 60", and step 7 re-checks "Q1 to Q4" | The SOP contradicts itself: unclear which four, and whether the verifier must also check Q5 | SOP author (Khiem Doan or the checklist owner) |
| SOP:596-599, 718-721 vs 760-775 | 6a step 8 "gated zip and bundle" for every task vs "The two tools below remain for packaging a hand-built task for your own DataOS run" | SOP contradicts itself on whether a hand-built task may skip the gated path | Khiem Doan |
| SOP:36-47, 86-87, 792; intake | "the QC team Slack channel" | No file gives the channel name. `#tfrl_qc` is the TFRL channel and authors must not post there | Khiem Doan |
| SOP:27-29, 723-745; intake 41-44 | "your manager" | No file names the manager, or the channel, sheet or form for hand-over and for the written answers to reader items | Khiem Doan or team lead |
| SOP:624-626; pipeline README:76-79; runbook:18-22 | "a copy of the tool from before 2026-10-05 ..." | No file gives a way to tell which copy you hold, or a version stamp | whoever maintains `svc_record_return.py` |
| SOP:569, 585, 591, 593; QUICK:58 | `svc_coverage_trace.py check <pkg> <map>`, `judge_emulate.py`, `svc_eval_regrade.py`, adversarial verify, no arguments or map format | R4 allows only `qc.py` commands. The tools exist under `svc-pc-pipeline/tools/` in the ADVRUN repo but I did not copy their help | tool authors (QUICK:58 says some were "not verified") |
| runbook:9-10, 14, 70-74; pipeline README:96-103 | sandbox login with `~/.ssh/kiem_sandbox`; which tools run on a laptop and which on the sandbox | No file says whether an author may use the sandbox, queue a task, or get the key | Khiem Doan |
| SOP:17-24, 609-611 | pipeline list names "TESTING - ...", "... pipeline copy", "CompanyBench ...", "automated_qc_pipeline" | None appears in any file; the SOP names only 4 Reviewers v8. R1: silent. Also no statement about versions above 8 | Khiem Doan |
| SOP:628-631 | "rework the design" | Not defined anywhere | SOP author |
| SOP:582, 735 and others | "QC lead", "EQC" (README glossary says the repo never spells it out), tier names `mechanical_fast` vs batch tiers vs `ready_tier2` | Not defined in any file | Khiem Doan |
| SOP:3-5 and README:7-13 | links to `docs/QC-RUNBOOK-qc-person.md`, `QC-RUNBOOK-manager.md`, `task-review-rules-v2.md`, `task-failure-checklist.md`, `rubric-check-1-5-guideline.md`, `svc_fix_method_rules.md`, `author-pre-submission-checklist.md`, `skills/ekw/verify-review-findings/SKILL.md`, `automation/release-check/README.md`, `automation/manager-read/README.md`, `docs/glm-env.ps1` | Outside the 10 files I was given, so I could not open them. docs/README.md lists most as CURRENT. Five are not in the index: the author checklist, the verify skill, release-check, manager-read, glm-env.ps1 | whoever owns the repo index |
| docs/README.md:73 and SOP:727 | "rules A to F" changed to "B to E" | I changed it by R1, but the run sheet itself was not in my files. If it truly has rule A and rule F, the SOP sentence "also applies rules B to E" needs a look | manager run sheet author |
| README.md:113 (glossary) | "Each finding has an id (1.1 to 1.8)" | The quickstart agrees. The review prompt v2 in open PR #75 may change the ids; the stale guide says 1.1 to 1.10 | review prompt owner |

### SVC path: needs a click path

Nothing was written for these; no file states them.

1. In DataOS, which page and which button gives the "Dataset with runs" download (the SOP says "the button")? What does the file name look like?
2. How do I download the current version of one task from DataOS, instead of using the 2026-09-14 GitHub release (SOP lines 236-242)?
3. How do I run only the oracle, and how do I run only the empty-answer (NOP) evaluation, on DataOS (SOP 493-497)? The docs/README.md:87 DataOS recipe is marked STALE.
4. After the dataset shows `Tasks (N)`, where exactly is "Run pipeline", and how do I choose version 8 in the list?
5. Where do I open each of the four Answer Check reviews and see `overall_verdict` and the findings (SOP 618-623)?
6. Where in the Create & upload dialog is the tag field, and which tag goes in it (see the tag item above)?

