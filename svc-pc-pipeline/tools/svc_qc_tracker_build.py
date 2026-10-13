"""Build the consolidated SVC QC tracker workbook from a workflow gather-result JSON.

Input: the raw .output file (or its parsed `result` object) from the
svc-qc-tracker-build Workflow, which merges per-task check status (A-G) from
every session source report into {rows: [...], ...}.

Usage:
    python tools/svc_qc_tracker_build.py <gather_output.json> <out.xlsx>
"""

import json
import re
import sys
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

CHECKS = ["A", "B", "C", "D", "E", "F", "G", "H"]

# Renumbered 2026-09-13 (user-requested): a new pre-Oracle, deterministic formula-health check
# (tools/svc_formula_health_check.py) is inserted as Check E. Everything from the old E onward
# shifted one letter: old E (Oracle) -> F, old F (Jafar manual review) -> G, old G (tracker
# write-back + readback) -> H.
CHECK_META = {
    "A": {
        "name": "Content audit",
        "catches": "Prompt/golden/rubric text internal consistency",
        "source": "svc-full-audit-* files",
        "explanation": "Reads the prompt, the model answer, and the grading rubric together and checks they all agree on the same facts.",
        "metaphor": "Like proofreading an exam question, its model answer, and its answer key side by side to make sure all three tell the same story.",
        "how_to_run": "One agent per task family reads instruction.md + the golden solution + the rubric spreadsheet in 00_fetched/<ID>/, classifies clean/fixable/unreachable_content, and records defects_found + proposed_fixes per task. Output: ekw/svc-full-audit-batch-0.json through -21.json (22 files, 635 tasks total, one record each: {task_id, classification, defects_found, proposed_fixes, notes}), summarized in ekw/svc-full-audit-report-2026-09-12.md. Re-run: dispatch fresh audit agents per batch of ~30 tasks; there is no single-command script for this check, it is LLM judgment.",
    },
    "B": {
        "name": "Build success",
        "catches": "Did the pipeline actually produce a package (parser gaps, hydration gaps, missing source all show up here)",
        "source": "build-unbuilt / build-check-remainder reports",
        "explanation": "Checks whether the pipeline could even assemble the task's folder of files at all, before anything inside it is judged.",
        "metaphor": "Like checking a shipping order actually got packed into a box before checking whether what's inside the box is correct.",
        "how_to_run": "python pipeline/tools/svc_pc_batch_convert.py --only <TASK-ID-or-comma-list> --reset --corpus-root \"C:\\ekwqc\\cirrus-corpus-fetch\\extracted\\Cirrus Sleep Full Y1 (FINAL VERSION)\" from C:\\ekwqc\\repo\\pipeline\\. Reads 00_fetched/<ID>/, writes to 03_dataos_ready/<ID>/ on success or 03_dataos_messy/<ID>/ on a caught TaskFailure (placeholder/hydration-gap routing). Ground truth for this check is simply: does C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready\\<ID>\\ exist as a directory - a plain `os.listdir`, no script needed. Known failure modes: rubric_xlsx_to_verifier.py can't parse some rubric xlsx layouts (~84 tasks); hydrate_environment.py's IDF-bucket fallback still misses some role/description-only source refs.",
    },
    "C": {
        "name": "Structural audit",
        "catches": "The 6 Jafar patterns (placeholder env vs. named files, deliverable-filename mismatch, unhydrated Drive dependency, answer-key leakage, internal contradiction, unstated deliverable count), on the built package",
        "source": "svc-structural-audit skill, one LLM pass per check",
        "explanation": "Opens the actual built package and checks it contains what the prompt and grader expect: real files, not a placeholder, and a deliverable name that matches what's graded.",
        "metaphor": "Like checking a care package actually has the ingredients the recipe calls for, not just a note that says 'ingredients here.'",
        "how_to_run": "Apply .claude/skills/svc-structural-audit/SKILL.md against C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready\\<TASK-ID>\\: read instruction.md in full, cross-check every judge.toml files=[...] path against solution/files/ and environment/initial_workspace/, check the 6 named patterns. This is a single LLM pass by default - PASS on this check now REQUIRES a second independent pass to agree (agree_count >= 2 below) before a task counts as ready, because a single pass has twice caught real defects a first pass missed (SVC-PC-1-2-0, then 6 tasks in the 56-task pre-Oracle batch on 2026-09-12). Re-run: python tools/svc_qc_reconcile_ground_truth.py after dispatching a fresh audit pass to recompute agree_count from every source file this session has produced.",
    },
    "D": {
        "name": "Mechanical sub-check family (D1-D9)",
        "catches": "Deterministic, zero-LLM checks against the built package and its rubric: filename correctness both directions, rubric schema/placeholder health, rubric text-authoring smells, two different criterion-collision shapes, tab-position claims, deliverable-file integrity, answer-key content leakage (review-only), and judge-determinism config exposure.",
        "source": "tools/svc_mechanical_filename_check.py (D1 - this is the script that drives the row-level Check D pass/fail column below). D2-D9 are new as of 2026-09-14 and live as sibling scripts in tools/ - see the subchecks table for exact paths. None of D2-D9 have been folded into row-level tracker status yet; that is separate follow-up work, not done in this pass.",
        "explanation": "A family of fast, dumb, but reliable script checks. None of them call an LLM; each answers one narrow, mechanical question a human used to check by eye against the built package or its source rubric.",
        "metaphor": "Like a shelf of single-purpose spellcheckers instead of one: one checks filenames match both ways, one checks no answer key was left blank, one checks for duplicate raffle-ticket numbers, one checks the recipe book's page references are actually right.",
        "how_to_run": "Row-level Check D status (pass/fail per task, the column actually rendered below) comes from D1 alone, unchanged from before this expansion: python tools/svc_mechanical_filename_check.py <TASK-ID...|--all> --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready. D2-D9 are new, additive, metadata-only sub-checks - each documented individually below with its own how_to_run, its own --root (D4 differs from the rest), and, where one exists, what a 2026-09-14 verification run against 4 real tasks (SVC-PC-6-0-0, SVC-PC-96-0-0, SVC-PC-66-0-0, SVC-PC-58-0-0) found. All 9 scripts were copied into this repo's tools/ directory on 2026-09-14 from the sibling repo C:\\Users\\khiem.doan_turing\\Documents\\Projects\\harbor-qc-checks (private GitHub khiemdoan-turing/harbor-qc-checks) - see that repo's README.md/OVERVIEW.md/GAP-ANALYSIS.md for the original capability writeup. Copied rather than called cross-repo so this repo does not depend on the sibling repo being present or in sync; each copy carries a provenance comment naming its source file and copy date.",
        "subchecks": {
            "D1": {
                "name": "Deliverable filename check (forward + reverse)",
                "catches": "FORWARD: does instruction.md literally mention every filename judge.toml's files=[...] expects. REVERSE: does judge.toml actually grade every filename instruction.md commands the solver to produce - the more severe direction, since a solver can follow the prompt exactly and still score 0 if the grader never opens that file.",
                "source": "tools/svc_mechanical_filename_check.py - copied 2026-09-14 from harbor-qc-checks/deliverable_filename_check.py (the fixed tomllib-based version with the added REVERSE direction). This is now the real, committed file the old CHECK_META source pointer named but that never existed in this repo; no logic changed on copy.",
                "explanation": "Reads judge.toml's files=[...] and instruction.md's text/'Graded deliverable filenames' section and checks each one appears in the other.",
                "metaphor": "Like a teacher who tells the class to save homework as homework.pdf but only ever opens a folder looking for essay.pdf - checks both that the naming matches, and that what actually gets graded is what students were told to produce.",
                "how_to_run": "python tools/svc_mechanical_filename_check.py <TASK-ID...> --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready [--out report.json], or --all [--id-prefix SVC-PC-] for every task under root. This is the script driving row-level Check D. Verified 2026-09-14 against SVC-PC-6-0-0/96-0-0/66-0-0/58-0-0: all 4 pass FORWARD; SVC-PC-6-0-0 fails REVERSE (3 commanded-but-not-graded files: Governance_and_Corporate_Summary.docx, Question_Source_Map_and_Remediation.xlsx, README.md), matching harbor-qc-checks/PERPLEXITY-QC-FINDINGS.md's own named example; the other 3 pass both directions.",
            },
            "D2": {
                "name": "Rubric schema check",
                "catches": "Blank/stub criterion descriptions, per-file and per-task rubric weight-sum mismatches, and a criterion whose description reads as a real requirement sentence but whose 'Expected:' value slot was never populated (placeholder_expected).",
                "source": "tools/svc_rubric_schema_check.py - copied 2026-09-14 from harbor-qc-checks/rubric_schema_check.py, unchanged.",
                "explanation": "Parses every tests/deliverables*/judge.toml under a task and checks the rubric is internally well-formed: nothing blank, nothing unweighted, weights summing to 1.0.",
                "metaphor": "Like a test's answer key where some questions have no answer written down, some say 'worth 10 points' with the actual right answer left blank, and the points across the whole test don't add to 100.",
                "how_to_run": "python tools/svc_rubric_schema_check.py C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready --task <TASK-ID> [--task <TASK-ID> ...] [--json report.json]. NOTE: unlike every other D subcheck, root here is a POSITIONAL argument, not --root - omit --task to sweep every task dir under root. Verified 2026-09-14: SVC-PC-66-0-0 flags 110/110 criteria and SVC-PC-96-0-0 flags 100/100 criteria as placeholder_expected - matches harbor-qc-checks/PERPLEXITY-QC-FINDINGS.md's documented '100-110 flagged criteria each, worst cases SVC-PC-66-0-0/60-0-0/61-0-0/62-0-0/96-0-0' exactly. SVC-PC-6-0-0 (100 criteria) and SVC-PC-58-0-0 (24 criteria) both came back clean.",
            },
            "D3": {
                "name": "Rubric text lint",
                "catches": "Three rubric-authoring smells: extraction_blind (asks about something a text-extraction judge can't see - cell formatting, protection, hidden state), meta_rubric_knowledge (demands the deliverable claim knowledge of its own grading rubric), stale_format_mismatch (names a file format the task's actual files=[...] doesn't ship).",
                "source": "tools/svc_rubric_text_lint.py - copied 2026-09-14 from harbor-qc-checks/rubric_text_lint.py, unchanged.",
                "explanation": "A pure-text lint over judge.toml criterion descriptions - no file is opened, only the criterion text itself is read.",
                "metaphor": "Three specific ways a rubric can quietly stop making sense: asking if the crust is golden-brown when the grader can only read a text description, still asking about a PowerPoint after the assignment changed to an essay, or asking the student to prove they scored 100% before they've seen the rubric.",
                "how_to_run": "python tools/svc_rubric_text_lint.py <TASK-ID...|--all> --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready [--id-prefix SVC-PC-] [--out report.json]. Verified 2026-09-14 against the 4 sample tasks: SVC-PC-6-0-0 flagged (14 stale_format_mismatch, 1 extraction_blind), SVC-PC-58-0-0 flagged (3 stale_format_mismatch), SVC-PC-96-0-0 and SVC-PC-66-0-0 clean. No harbor-qc-checks doc names a specific expected count for these 4 tasks to cross-check against; ran clean, zero errors.",
            },
            "D4": {
                "name": "Duplicate criterion-ID check (source rubric xlsx)",
                "catches": "Two rows in the SOURCE rubric .xlsx workbook whose criterion id collides after normalization - can silently drop a criterion's weight from scoring even when a separate weight-sum check still reads 1.0, if the dropped and surviving weights happen to cancel out.",
                "source": "tools/svc_duplicate_criterion_check.py - copied 2026-09-14 from harbor-qc-checks/duplicate_criterion_check.py, unchanged logic. Report-only, no --apply/fix mode.",
                "explanation": "Opens a rubric xlsx directly with openpyxl (no judge.toml/tomllib awareness at all) and flags any two rows whose id column collides after str().strip() normalization.",
                "metaphor": "Like two raffle tickets printed with the same number - whoever draws that number, one prize secretly never gets awarded, and because the total ticket count still looks right, nobody notices unless someone checks the numbers themselves.",
                "how_to_run": "python tools/svc_duplicate_criterion_check.py --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\00_fetched\\<TASK-ID> [--glob '*.xlsx'] [--out report.json]. THE ONE D SUBCHECK THAT READS 00_fetched, NOT 03_dataos_ready - confirmed by reading the script (openpyxl only, no judge.toml parsing) and by testing: it finds nothing under the built package. KNOWN FALSE-POSITIVE RISK, found during 2026-09-14 verification and not papered over: this repo's 00_fetched/<ID>/Rubric/ holds TWO source-xlsx shapes. A '_Grading_Rubric.xlsx' shape has a genuine unique id in column A (verified clean on SVC-PC-6-0-0 and SVC-PC-58-0-0). A '_Response_Criteria.xlsx' shape instead has a repeated SECTION label in column A (e.g. 'A. Package form and the workpaper standard', 'H. The adjusting entries') with the real unique id in column B - against this second shape the script's hardcoded 'id lives in column A' assumption produces false collisions: confirmed on SVC-PC-66-0-0, which reported 9 'colliding id groups' that are each just a section header shared by every criterion under that section (verified by direct read of the xlsx columns). Treat any D4 finding against a _Response_Criteria.xlsx file as needing a human read of the actual columns before acting on it, not as a stable pass/fail signal. Also confirmed: SVC-PC-96-0-0 has NO 00_fetched source folder on disk at all (only sibling tasks 96-3-0 through 96-6-0 do) - D4 cannot run against it; this is a real, pre-existing data gap in this repo's build tree, not a script defect.",
            },
            "D5": {
                "name": "Judge criterion-name duplicate check",
                "catches": "Two [[criterion]] blocks in the same judge.toml sharing a name - a different collision shape than D4's xlsx-id collision, since this one is post-build, on the actual judge.toml the grader reads, and can just as easily drop a criterion's weight if something downstream keys criteria by name.",
                "source": "tools/svc_judge_criterion_name_duplicate_check.py - copied 2026-09-14 from harbor-qc-checks/judge_criterion_name_duplicate_check.py, unchanged.",
                "explanation": "Parses every judge.toml under a task and flags [[criterion]] blocks (within one file, and across a task's sibling judge.toml files) that share a name.",
                "metaphor": "The same raffle-ticket-collision idea as D4, but checking the printed programme (judge.toml) instead of the ticket roll (the xlsx rubric) - a different place the same kind of accidental duplicate can hide.",
                "how_to_run": "python tools/svc_judge_criterion_name_duplicate_check.py <TASK-ID...|--all> --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready [--id-prefix SVC-PC-] [--out report.json]. Verified 2026-09-14: all 4 sample tasks pass, 0 per-file and 0 cross-file collision groups.",
            },
            "D6": {
                "name": "Tab-naming / tab-position check",
                "catches": "A criterion claims a specific tab exists at a specific position in the golden workbook (e.g. 'Analysis tab is 2nd from left'); opens the real golden and checks the real sheet order against that claim.",
                "source": "tools/svc_tab_naming_check.py - copied 2026-09-14 from harbor-qc-checks/tab_naming_check.py, with one required adaptation (see how_to_run).",
                "explanation": "Reuses this repo's own tools/svc_formula_health_check.py for judge.toml parsing and golden-file resolution (including the xlsm<->xlsx conversion-shim case), so which file counts as 'the golden' can never drift between the two checks.",
                "metaphor": "Like a recipe book saying 'the frosting recipe is on page 2,' but page 2 is actually the cake recipe - the frosting is somewhere else, or doesn't exist.",
                "how_to_run": "python tools/svc_tab_naming_check.py <TASK-ID...|--all> --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready [--id-prefix SVC-PC-] [--out report.json]. ADAPTATION REQUIRED ON COPY, 2026-09-14: the harbor-qc-checks source imports `formula_health_check` (that repo's own copy, generalized with an --id-prefix parameter on find_task_dirs); this repo's tools/svc_formula_health_check.py predates that generalization and find_task_dirs(root, task_ids=None) does not accept id_prefix at all. First verification run failed with `TypeError: find_task_dirs() got an unexpected keyword argument 'id_prefix'`. Fixed by renaming the import to svc_formula_health_check and filtering --id-prefix locally in this script instead of passing it through (turing-context's find_task_dirs already hardcodes an SVC-PC- prefix for --all, which is a no-op restriction on this all-SVC-PC corpus). Re-verified clean after the fix against all 4 sample tasks: 0 findings on all four.",
            },
            "D7": {
                "name": "Deliverable integrity check",
                "catches": "Whether every golden deliverable file under solution/ actually opens/parses cleanly (xlsx/xlsm via openpyxl, docx via zip structure, pdf via a basic well-formedness check) - generalizes the same 'don't trust a file just because it exists' instinct Check E already applies to spreadsheet formulas, to every deliverable file type.",
                "source": "tools/svc_deliverable_integrity_check.py - copied 2026-09-14 from harbor-qc-checks/deliverable_integrity_check.py, unchanged.",
                "explanation": "Opens every file under a task's solution/ by extension and confirms it actually parses rather than just existing on disk.",
                "metaphor": "Like actually opening a wrapped present to make sure it isn't empty or broken inside, instead of just checking the box has the right label and feels about the right weight.",
                "how_to_run": "python tools/svc_deliverable_integrity_check.py <TASK-ID...|--all> --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready [--id-prefix SVC-PC-] [--out report.json]. Verified 2026-09-14: all 4 sample tasks pass, 0 corrupt files; 1-2 files per task reported 'unchecked' (extensions outside xlsx/xlsm/docx/pdf, e.g. .csv source inputs) which is the script's documented not-a-failure default for an extension it doesn't recognize, not a defect.",
            },
            "D8": {
                "name": "Answer-key content leak check - REVIEW-ONLY, NOT A GATE",
                "catches": "A rubric's own literal expected value (a dollar figure, a date, a specific fact) appearing verbatim inside a file the solver can actually read, gated on that file ALSO having a suspicious name.",
                "source": "tools/svc_answer_key_content_leak_check.py - copied 2026-09-14 from harbor-qc-checks/answer_key_content_leak_check.py, unchanged. Ships deliberately low-confidence by the source repo's own design: a plain 'value appears anywhere in the environment' check was tried first and produced too much noise (control totals legitimately recur in real source documents) to ship as a gate.",
                "explanation": "Extracts rubric expected-values and searches suspiciously-named environment files for a verbatim match. A match is surfaced as a candidate for a human to read, never auto-failed.",
                "metaphor": "The subtler answer-key leak: not an obviously-named answer file, but the actual answer showing up word-for-word inside a study material the student was handed - sometimes totally fine on purpose, so this one only rings the alarm when the value AND a suspicious filename show up together, and always hands the result to a person.",
                "how_to_run": "python tools/svc_answer_key_content_leak_check.py <TASK-ID...|--all> --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready [--min-chars N] [--include-years] [--full-scan] [--out report.json]. REVIEW-ONLY - never wire this into a pass/fail gate; a 'clean' result is not proof of no leakage and a 'flagged' result needs a human read before acting, per the script's own docstring. Verified 2026-09-14: all 4 sample tasks report clean, 0 candidates - ran without error; no independent documented claim exists for these exact 4 tasks to cross-check against.",
            },
            "D9": {
                "name": "Judge-determinism config lint",
                "catches": "A nonzero-temperature LLM-judge criterion with no panel/sample-count control - a judge score that is not reproducible run to run, the single most damaging defect an external QC review found across three OTHER benchmarks (EKW Bench, CompanyBench, ComputerBench).",
                "source": "tools/svc_judge_determinism_config_lint.py - copied 2026-09-14 from harbor-qc-checks/judge_determinism_config_lint.py, unchanged. Multi-schema: tries judge.toml, verifier.json, manifest.json, and any other tests/*.toml or *.json per task.",
                "explanation": "Reads whatever grading-config format a task actually has and flags a temperature/panel/sample-count-shaped field found in the PARSED structure - never raw text, never a string value.",
                "metaphor": "Like a judge who decides a competition's winner by flipping a coin exactly once, with no backup vote if it lands wrong - the same two performances could get a different winner every time the coin is re-flipped.",
                "how_to_run": "python tools/svc_judge_determinism_config_lint.py <TASK-ID...|--all> --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready [--id-prefix SVC-PC-] [--out report.json]. Verified 2026-09-14: all 4 sample tasks report status not_exposed - this repo's judge.toml shape never exposes a temperature/panel field anywhere, so 'not exposed, not verified safe' is this script's documented correct output for this corpus, not a bug and not a false pass.",
            },
        },
    },
    "E": {
        "name": "Formula health",
        "catches": "A rubric criterion expecting a computed/derived cell that reads as an Excel error, or blank/NaN, when the golden workbook is actually opened and its formulas actually recalculated - the single largest recurring defect class found across datasets 968/971/973/974/975 this project",
        "source": "tools/svc_formula_health_check.py",
        "explanation": "Opens every .xlsx/.xlsm under a task's solution/ with the `formulas` Python library, forces a real recalculation of every formula cell (not just a read of whatever value happens to be cached), and reports any cell that comes back as an Excel error or as a blank/NaN where a live formula sits. Cross-references each finding against the task's own judge.toml criteria so a reader can immediately tell 'this affects a graded criterion' from 'this is dead weight'.",
        "metaphor": "Like actually re-running every formula in a spreadsheet instead of trusting whatever numbers happen to be sitting in the cells when you open it.",
        "how_to_run": "python tools/svc_formula_health_check.py <TASK-ID> [<TASK-ID> ...] [--root <03_dataos_ready path>] [--out <report.json>], or --all to sweep every task under root (slow: ~5-30s per spreadsheet file, do not run --all casually - it is a separate, larger follow-up once this script is proven correct on a handful of known cases). Runs pre-Oracle, deterministically, zero LLM cost. Added to the tracker 2026-09-13 as Check E (renumbering shifted Oracle E->F, Jafar F->G, tracker write-back G->H). Corpus-wide sweep completed 2026-09-13 (3 parallel workflows, ekw/svc-formula-health-group1/2/3-2026-09-13.json, 561 tasks: 523 pass / 38 fail read directly from the files) and folded into the tracker by ekw/_scratch_merge_tracker.py - this column now reflects a real result for every row that has a build under 03_dataos_ready.",
    },
    "F": {
        "name": "Oracle",
        "catches": "Golden answer vs. its own rubric, needs 2 independent runs to trust (documented flip risk on a single run)",
        "source": "DataOS-side Oracle run",
        "explanation": "Runs the actual grading rubric against the golden/model answer, twice, to make sure the rubric agrees with itself and isn't flaky.",
        "metaphor": "Like grading the answer key against its own test twice, to make sure you get the same score both times.",
        "how_to_run": "data-os.turing.com -> Datasets -> open the dataset holding the uploaded zip -> open a task -> Run a pipeline -> SVC-bench FullQC Pipeline (spends real Andrew_team credit, confirm before clicking). Full click-path: .claude/skills/dataos-manual-qc/SKILL.md. A task only counts as Oracle-passed once 2 independent runs agree - a single run is not evidence (documented criterion-flip behavior, e.g. 4 false certifications from one run earlier this project). Was Check E before the 2026-09-13 renumbering that inserted formula health as the new Check E.",
    },
    "G": {
        "name": "Manual QC / Jafar review",
        "catches": "Everything the other checks miss: missing files, wrong deliverable paths, unstated formats",
        "source": "Jafar's own manual review PDFs",
        "explanation": "A real person reads the task the way a solver would and flags anything that would confuse or block them.",
        "metaphor": "Like a human proofreader doing a final read of a recipe before it's published, catching things like 'step 4 needs an ingredient no one bought.'",
        "how_to_run": "Human-only step, not automatable. Jafar reviews a DataOS dataset directly in the UI per .claude/skills/dataos-manual-qc/SKILL.md and files findings; this repo's transcriptions of his past reviews are ekw/jafar-qc-review-batch1-2026-09-10.md (10 tasks, dataset QCR_SVC_GDM5_ready_09082026) and ekw/jafar-qc-review-pool22-2026-09-10.md (22 tasks, dataset 885/pool22). To request a new review: get the batch through checks A-D-and-2-pass-C first, upload to DataOS, then ask Jafar's team to review that specific dataset. Was Check F before the 2026-09-13 renumbering.",
    },
    "H": {
        "name": "Tracker write-back + readback",
        "catches": "Did a fix that was supposed to be applied actually get written where it's supposed to live, confirmed by reading it back",
        "source": "RL-World tracker's own 'Written back' / 'Readback verified' columns",
        "explanation": "Confirms a fix that was supposed to be applied to a file was actually saved there, by reading the file back afterward.",
        "metaphor": "Like double-checking you actually hit save and the document really updated, instead of assuming it did.",
        "how_to_run": "Applies to the separate RL-World 'QC Delivery Tracking' Google Sheet (id 1IwBkvxXAKcR4rs6cgGJhVKe9U_SxTE2LFx7Hz6YYnHI), not to this DataOS pipeline population directly - not yet exercised against the 635-task SVC-PC pool this cycle, hence NOT RUN on essentially every row below. Would be: after writing a Feedback Link into that tracker, re-read the cell back and confirm it matches what was written. Was Check G before the 2026-09-13 renumbering.",
    },
}

STATUS_FILL = {
    "pass": PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
    "fail": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
    "not_run": PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid"),
    "stale": PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),
}
STATUS_LABEL = {
    "pass": "PASS",
    "fail": "FAIL",
    "not_run": "NOT RUN",
    "stale": "STALE / DISPUTED",
}

WRAP = Alignment(wrap_text=True, vertical="top", horizontal="left")
HEADER_FILL = PatternFill(start_color="203864", end_color="203864", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)

ID_PATTERN = re.compile(r"^SVC-PC-\d+-\d+-\d+$")

STAGED_56 = {
    "SVC-PC-12-8-0",
    "SVC-PC-13-3-0",
    "SVC-PC-13-6-0",
    "SVC-PC-15-1-0",
    "SVC-PC-15-2-0",
    "SVC-PC-17-6-0",
    "SVC-PC-19-0-0",
    "SVC-PC-19-2-0",
    "SVC-PC-2-0-0",
    "SVC-PC-20-0-0",
    "SVC-PC-21-0-0",
    "SVC-PC-24-0-0",
    "SVC-PC-28-0-0",
    "SVC-PC-29-0-0",
    "SVC-PC-37-3-0",
    "SVC-PC-38-1-0",
    "SVC-PC-38-2-0",
    "SVC-PC-38-5-0",
    "SVC-PC-38-6-0",
    "SVC-PC-38-7-0",
    "SVC-PC-5-1-0",
    "SVC-PC-5-3-0",
    "SVC-PC-52-1-0",
    "SVC-PC-52-2-0",
    "SVC-PC-52-5-0",
    "SVC-PC-52-7-0",
    "SVC-PC-54-1-0",
    "SVC-PC-54-2-0",
    "SVC-PC-54-3-0",
    "SVC-PC-55-1-0",
    "SVC-PC-55-3-0",
    "SVC-PC-55-4-0",
    "SVC-PC-66-0-0",
    "SVC-PC-66-1-0",
    "SVC-PC-66-2-0",
    "SVC-PC-66-3-0",
    "SVC-PC-66-4-0",
    "SVC-PC-66-5-0",
    "SVC-PC-66-6-0",
    "SVC-PC-66-7-0",
    "SVC-PC-67-0-0",
    "SVC-PC-71-0-0",
    "SVC-PC-71-1-0",
    "SVC-PC-71-3-0",
    "SVC-PC-71-4-0",
    "SVC-PC-71-5-0",
    "SVC-PC-71-6-0",
    "SVC-PC-73-0-0",
    "SVC-PC-73-1-0",
    "SVC-PC-73-3-0",
    "SVC-PC-73-5-0",
    "SVC-PC-8-2-0",
    "SVC-PC-8-3-0",
    "SVC-PC-8-4-0",
    "SVC-PC-8-6-0",
    "SVC-PC-8-7-0",
}


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = data.get("result", data)
    rows = result["rows"]
    valid = [
        r
        for r in rows
        if r.get("population") in ("L2", "L3") and ID_PATTERN.match(r["task_id"])
    ]
    dropped = [r["task_id"] for r in rows if r not in valid]
    return valid, dropped


def check_cell_text(check_data):
    if not check_data:
        return "NOT RUN - no check run yet"
    status = check_data.get("status", "not_run")
    label = STATUS_LABEL.get(status, status.upper())
    agree = check_data.get("agree_count", 0)
    if agree >= 2:
        agree_note = f" ({agree} independent passes agree)"
    elif agree == 1:
        agree_note = " (1 pass, not yet independently re-checked)"
    else:
        agree_note = ""
    evidence = check_data.get("evidence", "")
    return f"{label}{agree_note}\n{evidence}".strip()


def build(rows, dropped, out_path):
    wb = Workbook()

    ws = wb.active
    ws.title = "QC Tracker"
    headers = [
        "Task ID",
        "Population",
        "Ready for DataOS/Oracle (computed: A+B+D+E pass, C 2-pass-agreed)",
        "DataOS dataset added",
    ]
    for c in CHECKS:
        headers.append(f"Check {c}: {CHECK_META[c]['name']}")
    for c in CHECKS:
        headers.append(f"Check {c} reconciliation history")

    ws.append(headers)
    for col_idx, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = WRAP
    ws.freeze_panes = "A2"

    rows_sorted = sorted(rows, key=lambda r: r["task_id"])
    for r in rows_sorted:
        dataset_note = r.get(
            "dataos_batch",
            (
                "Staged for DataOS upload (56-task batch), zip build in progress — not yet live in DataOS"
                if r["task_id"] in STAGED_56
                else "Not yet added to any DataOS dataset"
            ),
        )
        # Gate fixed 2026-09-13: was A+B+D pass/C 2-pass-agreed (ready_abcd), which did not
        # include Check E at all even though Check E exists specifically to gate Oracle
        # readiness. Now A+B+D+E pass/C 2-pass-agreed (ready_abcde) - same field the 108-task
        # Check-E batch selection used earlier the same day.
        ready_text = "READY" if r.get("ready_abcde") else "not ready"
        row_values = [r["task_id"], r["population"], ready_text, dataset_note]
        for c in CHECKS:
            row_values.append(check_cell_text(r.get("checks", {}).get(c)))
        for c in CHECKS:
            hist = [h for h in r.get("history", []) if h.get("check") == c]
            if hist:
                row_values.append(
                    "\n".join(f"[this session] {h['description']}" for h in hist)
                )
            else:
                row_values.append("-")
        ws.append(row_values)

    last_row = ws.max_row
    for row in ws.iter_rows(
        min_row=2, max_row=last_row, min_col=1, max_col=len(headers)
    ):
        for col_idx, cell in enumerate(row, start=1):
            cell.alignment = WRAP
            if 5 <= col_idx <= 4 + len(CHECKS):
                check_letter = CHECKS[col_idx - 5]
                task_row = rows_sorted[cell.row - 2]
                cd = task_row.get("checks", {}).get(check_letter)
                status = cd.get("status") if cd else "not_run"
                cell.fill = STATUS_FILL.get(status, STATUS_FILL["not_run"])

    widths = [16, 10, 16, 30] + [30] * len(CHECKS) + [34] * len(CHECKS)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws2 = wb.create_sheet("Read me")
    ws2.append(
        [
            "#",
            "Check",
            "What it catches",
            "Where it lives",
            "Simple explanation",
            "Metaphor",
            "How to run it / reproduce it (exact scripts, skills, files)",
        ]
    )
    for col_idx in range(1, 8):
        cell = ws2.cell(row=1, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = WRAP
    for c in CHECKS:
        m = CHECK_META[c]
        ws2.append(
            [
                c,
                m["name"],
                m["catches"],
                m["source"],
                m["explanation"],
                m["metaphor"],
                m.get("how_to_run", ""),
            ]
        )
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
        for cell in row:
            cell.alignment = WRAP
    for i, w in enumerate([4, 22, 40, 26, 40, 40, 60], start=1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    def write_block(title, lines, col_span=7):
        title_row = ws2.max_row + 2
        ws2.cell(row=title_row, column=1, value=title).font = Font(bold=True, size=12)
        for i, line in enumerate(lines):
            r = title_row + 1 + i
            ws2.cell(
                row=r,
                column=1,
                value=f"- {line}" if not title.startswith("How") else line,
            )
            ws2.merge_cells(start_row=r, start_column=1, end_row=r, end_column=col_span)
            ws2.row_dimensions[r].height = 60
            for cc in range(1, col_span + 1):
                ws2.cell(row=r, column=cc).alignment = WRAP
        return title_row + 1 + len(lines)

    write_block(
        "How this tracker gets rebuilt end-to-end (run this if the sheet looks stale)",
        [
            "1. Check B + D ground truth (no LLM, seconds): python tools/svc_qc_reconcile_ground_truth.py "
            "- lists every built task under C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready\\, "
            "loads all 22 ekw/svc-full-audit-batch-*.json files for check A, re-runs the mechanical filename "
            "scan fresh for check D, and consolidates every workflow's own raw .output JSON (in the session's "
            "tasks/ dir) for check C with oldest-to-newest priority ordering. Writes "
            "ekw/svc-qc-ground-truth-ABCD-2026-09-12.json, including a ready_abcd list.",
            "2. If check C's sources have changed (a new structural-audit sweep landed), add its .output file "
            "to the priority-ordered source list near the bottom of that script before re-running step 1.",
            "3. Merge in checks E-H, population, and reconciliation history: python "
            "ekw/_scratch_merge_tracker.py. It writes ekw/svc-qc-tracker-merged-2026-09-12.json by layering "
            "the new A-D ground truth from step 1 onto a base tracker gather, then folding in: Oracle Check F "
            "(renumbered 2026-09-13 from Check E - see the CHECK_META header comment above) from all six "
            "dataset files (svc-oracle-round1-2-analysis for 968, plus -group1-batch2/971, -dataset972, "
            "-group4-batch2/973, -dataset974, -dataset975 - all six Oracle datasets on disk as of 2026-09-13 "
            "are loaded as of the same-day consolidated fold-in), the 87-task svc-196-reconciliation "
            "verdict-to-Check-A mapping (with a further Check C fold-in from the 346-task 2nd-pass structural "
            "audit and the 156-task structural-fix workflow, both 2026-09-13), Check B/C/D for the "
            "124-task parser-fix rebuild (svc-parser-fix-rebuild-2026-09-12-tasks.json), and Check E "
            "(formula health, tools/svc_formula_health_check.py) read directly from the corpus-wide sweep's "
            "3 group report files (ekw/svc-formula-health-group1/2/3-2026-09-13.json, 561 tasks). The merge "
            "script also computes a per-row ready_abcde field (A-E all pass) for selecting the next "
            "DataOS/Oracle batch - use it, not ready_abcd alone, per "
            "ekw/PENDING-check-e-gate-and-zip-2026-09-13.md.",
            "4. Rebuild the workbook: python tools/svc_qc_tracker_build.py ekw/svc-qc-tracker-merged-2026-09-12.json ekw/svc-qc-tracker-2026-09-12.xlsx",
            "5. Push to the live Google Sheet (same URL, in place): python C:\\Users\\khiem.doan_turing\\.claude\\drive.py put 1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4 ekw/svc-qc-tracker-2026-09-12.xlsx --mime application/vnd.google-apps.spreadsheet",
            "6. Verify before trusting: zipfile.ZipFile(path).testzip() on the built xlsx, and a live byte-size "
            "readback from drive.py after the push.",
        ],
    )

    write_block(
        "Known gaps in this version (disclosed, not silently dropped)",
        [
            "Check A's own source (the 22 batch JSON files) has never been re-run against current source since "
            "it was first built - some tasks whose content changed later (rebuilds, fixes) may carry a stale "
            "content-audit verdict. Cross-check against a task's Check C reconciliation history for a more "
            "recent signal.",
            "Check C's agree_count is only set to 2 where the LAST source to touch a task was the wwgw0i13m "
            "broad-audit sweep AND it was also independently corroborated - most 'pass' rows still reflect a "
            "single audit pass and should be treated as provisional, not final, until a second pass agrees.",
            "The 177-fix worklist's per-task applied/stale/needs-Drive breakdown (69 applied / 65 confirmed / "
            "4 mismatch / 46 stale / 22 Drive-needed) has no recoverable per-task_id list on disk - only the "
            "aggregate counts are known. Individual rows do not reflect this worklist's fixes unless another "
            "source also covered the same task.",
            "Check H (tracker write-back + readback) is NOT RUN for essentially every row - it concerns the "
            "separate RL-World tracker, not yet exercised against this population.",
            "(Resolved 2026-09-13, was flagged the same day as a gap) Check E (formula health) is no "
            "longer NOT RUN for essentially every row - tools/svc_formula_health_check.py has now been "
            "run as a corpus-wide sweep (3 parallel workflows, 561 tasks, 523 pass / 38 fail read directly "
            "from ekw/svc-formula-health-group1/2/3-2026-09-13.json) and folded in. Per "
            "ekw/PENDING-check-e-gate-and-zip-2026-09-13.md, a batch selected for DataOS/Oracle must now "
            "gate on Check E passing too (see the row-level ready_abcde field in the merged tracker JSON), "
            "not on A-D alone.",
            "'DataOS dataset added' reflects local staging/zipping only. Confirm a row is actually live in "
            "DataOS before treating it as submitted - a zip existing locally is not the same as an upload "
            "having succeeded (see the 2026-09-12 dataset-968 upload failure for a real example of this gap).",
            "Reconciliation history is backfilled from THIS SESSION (2026-09-12) only, per explicit instruction "
            "- fixes from earlier sessions/cycles are not reconstructed here.",
            "One task (SVC-PC-9-6-0) shows real, clean data on checks B/C/D but was not found in the base "
            "635-task tracker list pulled from svc-full-tracker-content-2026-09-12.json - flagged, not resolved; "
            "worth a quick manual check of the live SVC_Y1_Pilot_Evals_Expert tracker before assuming either way.",
            "(Resolved 2026-09-13, was flagged the same day as a gap) Check F (Oracle, renumbered from E) "
            "now reflects all six Oracle datasets on disk: 968, 971, 972, 973, 974, 975 - the last three "
            "were added to ekw/_scratch_merge_tracker.py in the same consolidated pass that did this "
            "renumbering. A row's Check F showing 'not run' now genuinely means Oracle has not run against "
            "that task in any of the six known datasets.",
            "(Resolved 2026-09-13, was flagged the same day as a gap) The 124-task parser-fix rebuild's "
            "Check B/C/D fold-in (the _workflow_124_bcd function in ekw/_scratch_merge_tracker.py) has now "
            "been run against the rebuild data - the 124 task IDs in "
            "ekw/svc-parser-fix-rebuild-2026-09-12-tasks.json carry their real per-task Check B/C/D as of "
            "this tracker build.",
            "(Added 2026-09-13) ekw/_scratch_merge_tracker.py is itself a '_scratch_*' file by this "
            "project's own disposable-script convention - it is not guaranteed to survive to a future "
            "session. If this pattern (folding new Oracle/rebuild data into the tracker) keeps recurring, "
            "it is worth promoting the merge logic into tools/ as a proper, versioned script rather than "
            "re-deriving it from scratch each time.",
        ],
    )

    ws3 = wb.create_sheet("Summary")
    n = len(rows_sorted)
    ws3.append(
        [
            "SVC QC tracker - summary",
            f"Built {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}, {n} of 635 tasks in the base tracker (all 635 present as rows; some have zero checks run)",
        ]
    )
    ws3.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws3.append([])
    ws3.append(["Check", "Name", "Pass", "Fail", "Not run", "Stale/disputed", "Total"])
    for col_idx in range(1, 8):
        cell = ws3.cell(row=3, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    check_col_start = 5
    for i, c in enumerate(CHECKS):
        col_letter = get_column_letter(check_col_start + i)
        row_n = ws3.max_row + 1
        ws3.append(
            [
                c,
                CHECK_META[c]["name"],
                f"=SUMPRODUCT(--(LEFT('QC Tracker'!{col_letter}2:{col_letter}{last_row},4)=\"PASS\"))",
                f"=SUMPRODUCT(--(LEFT('QC Tracker'!{col_letter}2:{col_letter}{last_row},4)=\"FAIL\"))",
                f"=SUMPRODUCT(--(LEFT('QC Tracker'!{col_letter}2:{col_letter}{last_row},7)=\"NOT RUN\"))",
                f"=SUMPRODUCT(--(LEFT('QC Tracker'!{col_letter}2:{col_letter}{last_row},5)=\"STALE\"))",
                n,
            ]
        )
    ws3.append([])
    ws3.append(["Population", "Count"])
    ws3.append(["L2", "=COUNTIF('QC Tracker'!B2:B{0},\"L2\")".format(last_row)])
    ws3.append(["L3", "=COUNTIF('QC Tracker'!B2:B{0},\"L3\")".format(last_row)])
    ws3.append(["Total", n])
    ws3.append([])
    ws3.append(
        [
            "Ready for DataOS/Oracle (computed gate: A+B+D+E pass, C 2-pass-agreed)",
            "Count",
        ]
    )
    ws3.append(["READY", "=COUNTIF('QC Tracker'!C2:C{0},\"READY\")".format(last_row)])
    ws3.append(
        ["not ready", "=COUNTIF('QC Tracker'!C2:C{0},\"not ready\")".format(last_row)]
    )
    for col in "ABCDEFG":
        ws3.column_dimensions[col].width = 20
    ws3.column_dimensions["B"].width = 60

    if dropped:
        ws4 = wb.create_sheet("Dropped rows (not tasks)")
        ws4.append(
            [
                "Non-task-id string returned by a gather agent (excluded from the tracker)"
            ]
        )
        for d in dropped:
            ws4.append([str(d)])
        ws4.column_dimensions["A"].width = 80

    wb.save(out_path)
    return n, len(dropped)


if __name__ == "__main__":
    in_path, out_path = sys.argv[1], sys.argv[2]
    rows, dropped = load_rows(in_path)
    n, n_dropped = build(rows, dropped, out_path)
    print(
        f"Built {out_path}: {n} task rows, {n_dropped} non-task rows excluded (see 'Dropped rows' tab)"
    )
