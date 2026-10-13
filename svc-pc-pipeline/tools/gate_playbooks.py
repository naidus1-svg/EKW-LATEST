#!/usr/bin/env python3
"""gate_playbooks.py - per-check instructions and per-finding details for the fix-plan step.

Why this exists (laptop, 2026-09-19): a deterministic gate cell (stage_and_zip.sh blocks on it) used to reach the fix-plan model
as one generic sentence ("fix whatever the check name indicates") and, apart from judge_scope_over_inclusion, nothing else. The
model never saw the cell's own findings, what the check measures, what a fix looks like, what it must not do, or which op can
express it. Ten tasks sat blocked with zero applicable edits (metadata_leak needed an op that did not exist, environment_input
needed one heading restored, rubric_schema needed one weight). This module gives every blocking cell:

  1. a PLAYBOOK written from the check's own source and real blocked tasks: what it measures, what to read, the exact procedure,
     the ops that express the fix, what never to do, and how the cell is re-checked;
  2. DETAILS: the cell's own JSON findings, verbatim, capped;
  3. DOCS: the head of the check module's docstring, so a cell with no hand-written playbook still carries the author's account.

Used by build_review_union.py. Pure functions, no writes.
"""

from __future__ import annotations

import ast
import glob
import json
import os
import re

CHECKS_DIR = "/root/ekwqc/deterministic-checks"

# How the accounting rule reads in every gate finding: one line per finding in `notes`, so a later reviewer (or an override
# decision) can see what was done and why without re-reading the whole plan.
ACCOUNTING = (
    "In `notes`, write one line per finding of this cell: 'GATE <cell> <file or group> <location>: EDITED <what>' or "
    "'GATE <cell> <file or group> <location>: NOT EDITED because <reason quoting the criterion, source line or check rule>'. "
    "A finding you neither fix nor account for is treated as ignored."
)

PLAYBOOKS: dict[str, dict] = {
    "metadata_leak": {
        "measures": (
            "Hidden metadata text (xlsx cell comments and sheet titles, pptx speaker notes, docx headers/footers/comments) in a file the "
            "SOLVER receives, or in a golden file, that contains a value which numerically or literally matches an Expected value of one of "
            "this task's own criteria, or that names an internal grading file. Environment-side HIGH findings make the cell `fail` and block "
            "the zip; golden-side findings and candidates are `warn` and do not block."
        ),
        "read": (
            "Each finding carries: kind (cell_comment | speaker_notes | header_footer | sheet_title), file, location (Sheet!Cell for a comment, the "
            "part path for notes and footers), text (the metadata verbatim), value (the criterion value it matched), value_kind, match_type, "
            "criterion and judge_group. `criterion_text` shows that criterion's own Expected wording."
        ),
        "procedure": [
            "The check's own calibration (hand-verified over 47 distinct environment patterns) found ZERO genuine answer-key leaks: every "
            "flag was a common English word or label that co-occurs with a quoted Expected value ('approved', 'demand', 'Confidential'), "
            "the real source data a criterion describes, a scale suffix read as a number ('(rounded $000s)' parses as 0 and matches an "
            "Expected value of 0.002; '$18K' matches '$18.00'), or an Excel cell-reference misparse. Treat each finding as a collision to "
            "neutralise in the metadata, not as proof of a leak, and DO NOT touch visible cell values, slide text or document body. "
            "`all_collisions` lists EVERY expected value the text matches: the check reports only the first, so clearing one can expose the "
            "next; the replacement text must match none of them.",
            "Sort each finding: (a) GRADING ARTIFACT: the text names an internal grading or answer file (rubric, criteria, judge, golden, "
            'answer key): blank the whole matched text with replace="". (b) STATES THE ANSWER: the text asserts a conclusion, figure or '
            "judgement the deliverable is supposed to derive: remove that clause and keep the rest of the note. (c) SOURCE ANNOTATION with a "
            "colliding figure or symbol: remove only the colliding token (for example '$195.5K->$196K', or reword '(rounded $000s)' to "
            "'(rounded to thousands)') so the sentence stays natural and no number in it can match an Expected value. (d) COMMON WORD or "
            "LABEL that matched a quoted Expected word: reword just that word ('approved' -> 'signed off', 'Confidential' -> 'Internal use "
            "only', 'demand' -> 'sell-through').",
            "For each edit emit one `replace_ooxml_text` with file, kind, location, find (a substring of the finding's `text`, copied verbatim; "
            "whitespace is ignored) and replace. Keep `find` as short as the collision allows but long enough to be unique; the op refuses a "
            "match that occurs in more than one place, so add the location or a longer find. The same wording in several files needs one edit "
            "per file.",
            "Before choosing replacement text, read `criterion_text`: the new metadata must not contain the criterion's value, a number "
            "equal to it after rounding, or its quoted word. Check EVERY number left in the sentence against every value listed in the "
            "findings for this task, not only the one that was flagged.",
            "sheet_title findings: do NOT rename a sheet. A rename breaks every formula and every criterion that names the sheet, and a sheet "
            "title that a criterion quotes is the source's own label, not an answer. Account for it in `notes` (NOT EDITED, source label) and "
            "move on; the gate policy for that case is a decision for the owner, not an edit.",
            "Golden-side findings (`golden_high_findings`) are warnings and do not block; edit one only when it is a grading artifact (a).",
        ],
        "never": [
            "Never edit visible cell values, slide text, document body text or formulas to clear this cell.",
            "Never rename a sheet or delete a comment part. Never blank a comment that is the only place a fact a criterion depends on appears "
            "(if the flagged figure is a real datum found nowhere else in the environment, leave it and say so in notes).",
            "Never invent replacement facts. Replacement text either removes words or restates the same idea without the colliding token.",
        ],
        "ops": ["replace_ooxml_text"],
        "confirm": "The zip step re-runs metadata_leak on the staged bytes; the cell must read pass (or warn) with zero environment_high_findings.",
    },
    "answer_key_rubric_leak": {
        "measures": (
            "Whether a criterion's own prose (its requirement sentence or Expected clause in judge.toml) copies the golden file's wording: a run "
            "of consecutive matching word tokens between the criterion text and a golden file. FLAGGED (fail) is a run of 9 or more tokens with at "
            "least 7 content words; CANDIDATE (warn) is a run of 8 or more. Both block the zip. This is the rubric copying the answer, not the "
            "solver seeing it."
        ),
        "read": (
            "Each finding has criterion, judge_group, golden_file, run_length, content_words, numeric_ratio, clause_ratio (share of the run "
            "inside the Expected clause) and matched_text (the shared run, lowercased)."
        ),
        "procedure": [
            "Open the criterion in the judge.toml named by judge_group (its text is in the file dump below). Find the sentence that contains "
            "matched_text.",
            "Paraphrase that sentence so that no run of 8 consecutive words is shared with the golden file. Change the syntax, not just one "
            "word in the middle: reorder the clause, swap the verb form, restate the property ('uses the December 2021 exit run rate for "
            "payroll' instead of 'carries payroll at the december 2021 exit run rate'). Keep every number, name, unit, threshold and the "
            "pass/fail condition exactly as they are.",
            "Check the paraphrase against the golden text in the file dump: scan the golden for any 8-word run that now matches the new "
            "wording. Then check the other criteria named in the same cell (each finding is one criterion).",
            "One `replace_literal` per criterion on judge.toml (find = the exact old sentence, replace = the paraphrase).",
        ],
        "never": [
            "Never edit the golden to break the overlap: the golden is correct and the rubric is what copies it.",
            "Never weaken what the criterion demands, change an Expected value, or change a weight.",
        ],
        "ops": ["replace_literal"],
        "confirm": "answer_key_rubric_leak must read pass: no criterion shares a run of 8 or more tokens with a golden file.",
    },
    "judge_scope_over_inclusion": {
        "measures": (
            "A judge group's files=[...] in tests/deliverables*/judge.toml lists BOTH the graded deliverable and pre-existing environment source "
            "files. The rewardkit judge concatenates every listed file as undifferentiated text under a generic prompt that never says which "
            "file is the submission, so source text can be credited as if the deliverable contained it (an empty deliverable scored 0.52 to "
            "0.84 on the two confirmed tasks; DataOS major 1.5). Any group with a deliverable AND a source in files= fails."
        ),
        "read": (
            "Each finding is one judge group: group (the judge.toml path), deliverable_files_in_scope, source_files_in_scope, n_criteria_in_group, "
            "reward_at_risk_upper_bound. The group's criteria are in the file dump below."
        ),
        "procedure": [
            "For each flagged group, list its criteria and mark each as (1) gradable from the deliverable alone, or (2) a fidelity or traceability "
            "criterion that compares a figure or fact with a source ('matches', 'traces to', 'consistent with', 'per <source file>').",
            "Make every type (2) criterion self-contained BEFORE removing the source: put the reference fact in its Expected clause (the value the "
            "golden uses, with the source named in words, for example 'Expected: 17 vendors, per Vendor_Agreement_Shopify.pdf section 4') and "
            "grade the deliverable's statement against that stated value. The value is already known from the golden and the cited source.",
            "Then remove every source file from that group's files=[...], keeping the deliverable only (one `replace_literal` on the files line; "
            "keep the exact path style already used in the file). Do this for EVERY flagged group.",
            "Keep the criterion count, names and weights unchanged.",
        ],
        "never": [
            "Never leave a source in files= 'because a criterion needs it': the cell will fail again. Rewrite the criterion instead (step 2).",
            "Never delete a criterion, change a weight, or edit reward.toml to make the finding go away.",
            "Never drop a source and leave a criterion that can only be graded by reading that source (it becomes unpassable: a false rejection).",
        ],
        "ops": ["replace_literal"],
        "confirm": "judge_scope_over_inclusion must read pass: no group lists a deliverable together with an environment source file.",
    },
    "rubric_schema": {
        "measures": (
            "The built rubric files are well formed: at least one tests/deliverables*/judge.toml; every criterion has a real description; no bare "
            "tier stub ('Judgment Expected: x' with no requirement sentence); no placeholder 'Expected:' value; per-group criterion weights sum to the "
            "weight reward.toml declares for that group, and the groups sum to 1.0."
        ),
        "read": (
            "The row lists blank_desc, bare_tier, placeholder_expected, file_weight_mismatch ([{file, declared, criteria_sum}]), parse_errors, "
            "weight_sum, header_alias_suspect and blank_fraction."
        ),
        "procedure": [
            "file_weight_mismatch: for each entry, the group's criteria must sum to `declared` (the value in tests/reward.toml). Decide which side is "
            "wrong: if criteria were deleted or split earlier and their weight was not carried over, raise the remaining criterion weights (a "
            "single remaining criterion takes the whole declared weight); if reward.toml is wrong, correct it. Compute the new values exactly, to the "
            "precision the file already uses, and check that the group sums to `declared` and that all groups still sum to 1.0.",
            "blank_desc / bare_tier / placeholder_expected: the criterion needs its real requirement sentence or Expected value. Rebuild it from "
            "instruction.md and the golden (the values are in the file dump); never invent a value that the golden does not support.",
            "One `replace_literal` per changed weight or sentence on judge.toml or reward.toml (find = the exact current line, unique in the file).",
        ],
        "never": [
            "Never drop a criterion to make the sums agree. Never change a weight on a group that already matches its declared value.",
        ],
        "ops": ["replace_literal"],
        "confirm": "rubric_schema must read ok: true with no mismatch and weight_sum 1.0.",
    },
    "environment_input": {
        "measures": (
            "Whether instruction.md's account of its inputs matches environment/initial_workspace/: pattern 1 (a named input file that is missing), "
            "pattern 3 (a cloud-storage URL given as an input), pattern 5 (placeholder-only environment while the prompt names required files)."
        ),
        "read": "pattern1.missing lists [{filename, text}] for each file the prompt names that is not in the workspace; candidates_considered lists what was read as an input.",
        "procedure": [
            "For each missing filename, decide what it is. If it is one of the files under solution/files/ (a graded DELIVERABLE), the checker read a "
            "deliverable listing as an input because the listing does not sit under the exact marker it recognises. The marker is the heading "
            "'## Graded deliverable filenames' followed by 'Submit the graded deliverables using these exact filenames (and paths where shown):'. "
            "Restore that heading and sentence in instruction.md and make the identical change in tests/task_prompt.txt (the two files must stay "
            "byte-identical). Example seen on 82-4-0: the section read '## Required deliverable filenames' / 'Submit the deliverables using these "
            "exact filenames' and the deliverable was reported missing.",
            "If it is a real input that was never staged, do not invent the file. Name in `notes` where it should come from, and if another shipped "
            "file holds the same data reword the prompt sentence to name that file.",
            "A cloud-storage URL given as an input (pattern 3): rewrite the sentence to name the staged file, or remove the URL if the data is staged.",
        ],
        "never": [
            "Never add a placeholder file to the environment to satisfy the check. Never change a deliverable's filename."
        ],
        "ops": ["replace_literal"],
        "confirm": "environment_input must read pass (pattern1.missing empty).",
    },
    "extraction_groundedness": {
        "measures": (
            "Whether a criterion's required property is one the judge can never see. For SVC-PC the judge reads every document through MarkItDown, "
            "which returns cell VALUES and text only: formula text, number formats, tab colours, hidden rows and protection never reach it. A "
            "criterion that grades such a property is unpassable by construction (a false rejection)."
        ),
        "read": "Each finding has kind (extraction_blind_confirmed), file (the judge.toml), criterion, matched (the blind phrase, e.g. 'formula-driven') and description.",
        "procedure": [
            "Open the criterion. Keep what it verifies about VALUES (the number is present and correct, the row is filled) and remove or reword the "
            "property the judge cannot see: 'formula-driven cells carry their computed values' becomes 'the ending-headcount cells show numeric values'.",
            "If the criterion's whole point is the invisible property (live formulas, a colour), it cannot be graded by this judge: replace it with a "
            "value-based restatement, and say in `notes` what was dropped.",
            "One `replace_literal` per criterion on judge.toml. Keep weight and name.",
        ],
        "never": [
            "Never leave the blind phrase in the description 'for context': the check matches the phrase itself."
        ],
        "ops": ["replace_literal"],
        "confirm": "extraction_groundedness must read pass (no extraction_blind_confirmed findings).",
    },
    "formula_health_extraction_loss": {
        "measures": (
            "A workbook the judge reads has formula cells with no cached value in the file AS SHIPPED, so the judge's extractor "
            "(openpyxl data_only) returns blank for them. Findings are per cell: file, sheet, cell, formula, kind extraction_cache_loss."
        ),
        "read": "n_files_with_extraction_loss says how many files; every finding names its file. Environment files and golden files are treated differently.",
        "procedure": [
            "If the file is an ENVIRONMENT source that is listed in a judge group's files=, it should not be there at all (see judge_scope_over_inclusion): "
            "remove it from files= and, if a criterion depended on it, put the needed value in that criterion's Expected clause. That removes the "
            "extraction loss from the judge's view without touching the source.",
            "If the file is the GOLDEN, write the cached value into the cells the criteria grade with `set_xlsx_cell` (a literal replaces the formula and "
            "its stale cache). Do the cells a criterion names first; list any cells you left in `notes`.",
        ],
        "never": ["Never edit an environment workbook's formulas or values."],
        "ops": ["replace_literal", "set_xlsx_cell"],
        "confirm": "formula_health_extraction_loss must read pass, or the affected file must no longer be in any files= list.",
    },
    "weight_application": {
        "measures": (
            "Whether the task's declared weights and 'must-pass' criteria can be honoured by the scoring config that ships with it. Two mechanisms. "
            "(1) must_pass_no_gate (the one seen on every current finding): a criterion description matches the regex must[\\s-]*pass "
            "(case-insensitive, so 'must-pass', 'must pass', 'MUST-PASS') but its group's aggregation is weighted_mean; only required_pass or "
            "all_pass ever zero a score on a failed criterion, so the words are inert prose. (2) reward.toml problems: reward_toml_missing, "
            "reward_block_missing, weights_table_unknown_keys, weights_declared_but_unusable, weights_table_partial, weights_table_value_mismatch "
            "(the [[reward]] weights table must name every tests/deliverables* directory exactly and carry each group's declared weight)."
        ),
        "read": (
            "weight_gate_unusable[]: type, group, criteria (the names of the offending criteria), detail. For a reward.toml type the detail names the "
            "keys or values that are wrong."
        ),
        "procedure": [
            "must_pass_no_gate: for EACH criterion named in `criteria`, open it in that group's judge.toml and remove every match of the regex "
            "must[\\s-]*pass. If the sentence only announces the flag ('This is a must-pass criterion.', 'MUST-PASS.', 'Must pass:'), delete that whole "
            "sentence. If the phrase sits inside a real requirement, reword just that clause without the words (for example 'the total must pass the "
            "tie-out' becomes 'the total has to tie out'). Change nothing else in the description: Expected values, thresholds, names and weights stay.",
            "After editing, read each edited description once more against the regex: no 'must pass', 'must-pass', 'must  pass' or 'Must-Pass' may remain, "
            "including inside the Expected clause.",
            "Do NOT implement all_pass or required_pass: that would change how the task scores, and this cell asks only that inert prose is not left "
            "pretending to gate.",
            "reward.toml types: rebuild the weights table in tests/reward.toml: keys are the exact names of the tests/deliverables* directories, values are "
            "each group's declared weight (the sum of that group's criterion weights), and together they sum to 1.0. Make it one `replace_literal` on the "
            "existing weights line, or `append_text` if the table is absent.",
        ],
        "never": [
            "Never change a criterion weight or a group weight to move a score. Never delete a criterion. Never switch the aggregation.",
        ],
        "ops": ["replace_literal", "append_text"],
        "confirm": "weight_application must read pass: no description matches must[\\s-]*pass under a weighted_mean group.",
    },
    "verifier_executability": {
        "measures": "Whether the grading entrypoint can run at all. tests/test.sh must not carry CRLF line endings (a CRLF shebang names an interpreter that does not exist).",
        "read": "The finding says which entrypoint parse failed.",
        "procedure": [
            "Convert tests/test.sh to LF line endings with `normalize_line_endings` (file = tests/test.sh)."
        ],
        "never": ["Never rewrite the script's commands."],
        "ops": ["normalize_line_endings"],
        "confirm": "verifier_executability must read pass.",
    },
}

# ---------------------------------------------------------------------------
# C1 (laptop, 18:25Z/18:40Z 2026-09-19): the 11 canonical scans (+3 new C1-addendum scans) and the 4 named
# ADVISORY-set actuator cells the DataOS reviewers caught majors on that fix_from_dataos.sh never saw, because
# neither family reached build_review_union.py's union before this change. Every entry below shares the same
# NEVER baseline the coordinator specified verbatim; a scan-specific "never" is appended where one applies.
# ---------------------------------------------------------------------------
NEVER_BASE = [
    "Never delete a criterion.",
    "Never widen or delete an Expected value to satisfy a check.",
    "Never invent a source or a citation.",
    "A value the shipped sources cannot support is corrected in the golden from the sources, or the pin is "
    "removed and the derivation is graded instead - the accounting line says which.",
]

PLAYBOOKS.update(
    {
        # -- 4 actuator cells (45-check suite, in stage_and_zip.sh's ADVISORY set: recorded but do not block
        #    the zip on their own, so a reviewer catching one as a major was never surfaced to the fixer) --
        "source_citation_existence": {
            "measures": (
                "The golden's own provenance text cites a file (by name or by 'per <source>' phrase) that does "
                "not exist anywhere under this task's environment/ or solution/files/ (golden_cites_absent_file). "
                "Downgraded to ADVISORY (does not block the zip); DataOS reviewers still file it as a major "
                "(source_citation_existence=warn caught on 67-3-0, 88-0-0, 6-2-0, 39-3-0, C1 18:25Z)."
            ),
            "read": "checks/recheck/summary.csv column source_citation_existence carries pass|warn|fail, _n (finding count), _first (first citation text). Full findings are in the matching recheck dir's source_citation_existence.json (cell_details), or golden_citation_scan.csv for the same task (same underlying defect, different pipeline stage).",
            "procedure": [
                "For each cited name, decide what it actually points at: a real corpus file under a different "
                "name (a typo, an old filename, a renamed source) or a file that was genuinely never shipped.",
                "If the real file exists under a different name, correct the citation text to the real filename "
                "with `replace_literal` (golden xlsx cell, docx paragraph, or table text as the citation appears).",
                "If no matching file exists anywhere in the corpus, do not invent one: reword the citation to name "
                "the source generically (e.g. 'per the FY2021 management commentary') only if that softer claim is "
                "still true, or remove the specific-file claim and keep the figure with its Source Register entry "
                "if that register already correctly names the real source.",
            ],
            "never": NEVER_BASE + ["Never point the citation at a file that does not contain the cited fact just to clear the check."],
            "ops": ["replace_literal", "set_xlsx_cell", "replace_docx_text"],
            "confirm": "source_citation_existence must read pass (or the ADVISORY warn must carry zero absent-file citations) on the next recheck.",
        },
        "golden_arithmetic": {
            "measures": (
                "A dollar or numeric figure stated in the golden does not appear, with its unit/subject anchor, "
                "anywhere in this task's shipped environment - i.e. the figure cannot be found supported by the "
                "sources it is implicitly claiming to come from. ADVISORY (does not block); DataOS filed it as a "
                "major with the exact mismatching figure quoted (6-2-0, 39-3-0, C1 18:25Z)."
            ),
            "read": "checks/recheck/summary.csv column golden_arithmetic: verdict, _n, _first (e.g. \"'$4,390' does not appear near its unit/subject anchors {'present'} anywhere in this task's environment\"). Full detail in the recheck dir's golden_arithmetic.json.",
            "procedure": [
                "Recompute the figure from the named source arithmetic yourself (the line items or table the "
                "golden's own narrative says it derives from) and compare to what the golden states.",
                "If the golden's figure is arithmetically wrong (does not foot to the sources), correct the "
                "golden cell with `set_xlsx_cell` or `replace_docx_text` to the correct, source-derived value.",
                "If the golden's figure is correct but simply not stated near a recognizable unit/subject anchor "
                "in any shipped file (the underlying fact is real but the anchor text the check looks for is "
                "phrased differently in the source), add or correct the anchor phrasing at the SOURCE table (only "
                "if the source itself is malformed) or, if the source is authoritative as written, leave the "
                "golden's correct figure and record in `notes` which source row backs it and why the anchor text "
                "differs.",
            ],
            "never": NEVER_BASE,
            "ops": ["set_xlsx_cell", "replace_docx_text", "replace_literal"],
            "confirm": "golden_arithmetic must read pass (or its ADVISORY warn's mismatching-figure list must be empty) on the next recheck.",
        },
        "criterion_groundedness": {
            "measures": (
                "Whether a criterion's own Expected value is actually derivable from the shipped sources, not "
                "just asserted. ADVISORY (does not block the zip); DataOS filed it as a major on 4 tasks in this "
                "batch (5-4-0's '10,000 paths' value, 6-2-0, 9-5-0, 21-3-0, C1 18:25Z) - a pinned value the "
                "sources cannot reproduce is exactly the false-rejection risk this whole job exists to close."
            ),
            "read": "checks/recheck/summary.csv column criterion_groundedness: verdict, _n, _first. Full detail (which criterion, which Expected value, why it cannot be reproduced) in the recheck dir's criterion_groundedness.json.",
            "procedure": [
                "Reproduce the Expected value from the named sources yourself, the same computation the criterion "
                "implies (count, sum, lookup). Do not skip this: 'GPT filed it as a major' is a claim about the "
                "sources, not about the golden - check it against the actual files.",
                "If the sources DO support the value and the check's own derivation missed something (wrong table, "
                "stale extract, a filter it didn't apply), the criterion is fine: record in `notes` the exact "
                "computation that reproduces it and change nothing.",
                "If the sources cannot support the pinned value, follow the coordinator's rule exactly: either "
                "correct the golden AND the Expected clause together from the real, source-derived value "
                "(`set_xlsx_cell`/`replace_docx_text` on the golden, `replace_literal` on judge.toml so both "
                "agree), or remove the numeric pin from the Expected clause and grade the derivation method "
                "instead (e.g. 'the count is computed by filtering X on Y and stating the result' rather than a "
                "fixed number) - never both invent a new number AND leave the old wording implying it was found.",
            ],
            "never": NEVER_BASE,
            "ops": ["replace_literal", "set_xlsx_cell", "replace_docx_text"],
            "confirm": "criterion_groundedness must read pass (or its ADVISORY warn's ungrounded-value list must be empty) on the next recheck, and the oracle must still total 1.0.",
        },
        "golden_groundedness": {
            "measures": (
                "The golden states a value in a workbook cell that a recomputation from the shipped environment "
                "tables does not reproduce (e.g. 'Golden states 7674.0 at Close Bridges!B7 ... but no "
                "recomputation from 55 environment table(s) reaches it'). ADVISORY (does not block)."
            ),
            "read": "checks/recheck/summary.csv column golden_groundedness: verdict, _n, _first. Full detail in the recheck dir's golden_groundedness.json.",
            "procedure": [
                "Recompute the flagged cell from the environment tables the golden's own narrative or Source "
                "Register says it comes from.",
                "If the recomputation reaches a different number, correct the golden cell (`set_xlsx_cell`) to "
                "the recomputed, source-grounded value; check nothing downstream (a formula, a rollup, another "
                "criterion) that reads this cell now disagrees.",
                "If the golden's value is a stated ASSUMPTION rather than a derivation (the instruction or the "
                "golden's own notes say so), the finding is a false positive for this cell: leave the value and "
                "make sure the cell or its adjacent note actually says 'assumption', not silence, so the next "
                "recheck (and a human reviewer) can tell the difference.",
            ],
            "never": NEVER_BASE,
            "ops": ["set_xlsx_cell", "replace_literal"],
            "confirm": "golden_groundedness must read pass on the next recheck.",
        },
        # -- 3 more actuator cells needed by promoted_kinds.py's kind-level findings (not among the
        #    original 4; these are 45-check cells too, read the same way via cell_details) --
        "rubric_overspecification": {
            "measures": (
                "A criterion's Expected clause pins a specific count or a specific name/label that the criterion "
                "does not need to pin to grade the real requirement (overspec_type: count_pinned or name_pinned). "
                "ADVISORY (does not block the zip); C1's promoted-kind gate only fires on this for a count/name that "
                "is NOT independently stated in instruction.md (a pin that echoes something instruction.md itself "
                "states, e.g. an explicit 'five lettered asks, A through E', is legitimate and does not promote)."
            ),
            "read": "checks/recheck/summary.csv column rubric_overspecification: verdict, _n, _first. Full findings (criterion, overspec_type, pinned_value, quote, instruction_text) in the recheck dir's rubric_overspecification.json.",
            "procedure": [
                "Grep instruction.md for the pinned count or name. If it IS stated there, this finding is a false positive for promotion purposes: record in `notes` why the pin is legitimate and change nothing.",
                "If instruction.md does NOT state it, loosen the Expected clause to accept any count/name that follows a stated, correct method, keeping the underlying requirement intact.",
            ],
            "never": NEVER_BASE,
            "ops": ["replace_literal"],
            "confirm": "rubric_overspecification must read pass (or the remaining pins are confirmed instruction-grounded in notes) on the next recheck.",
        },
        "fabricated_unfilenamed_fact": {
            "measures": (
                "The golden asserts a fact (a business claim, a figure, an entity) that no file in the shipped "
                "environment supports, without naming a specific record for it (contrast source_citation_existence, "
                "which is about an EXPLICIT citation to an absent file). ADVISORY. C1's promoted-kind gate only fires "
                "when the fabricated claim itself names a specific absent RECORD (a filename-shaped token or a "
                "document-titled phrase like 'Q4 Board Minutes') - a bare unsupported entity/vendor claim with no "
                "named record does not promote (verified: SVC-PC-2-7-0's 'NovaTex' claim is exactly this case)."
            ),
            "read": "checks/recheck/summary.csv column fabricated_unfilenamed_fact: verdict, _n, _first. Full findings (claim, claim_context, golden_file, matched_env_file, evidence) in the recheck dir's fabricated_unfilenamed_fact.json.",
            "procedure": [
                "Read `claim` and `evidence`. Search the environment yourself for anything that supports the claim.",
                "If the claim depends on a named record that does not exist, remove the claim or reword it to what the shipped sources actually support; if the record should exist and was simply never shipped, say so in `notes` rather than inventing it.",
            ],
            "never": NEVER_BASE,
            "ops": ["replace_docx_text", "set_xlsx_cell", "replace_literal"],
            "confirm": "fabricated_unfilenamed_fact must read pass on the next recheck.",
        },
        "judge_scope_under_inclusion": {
            "measures": (
                "A criterion's Expected text implies a source the judge needs to verify it (an 'implied_source' the "
                "check infers from the criterion's own wording) but that source is not in the judge group's "
                "files=[...] - the mirror image of judge_scope_over_inclusion (a source present that shouldn't be) "
                "and closely related to citation_unverifiable_scan. ADVISORY; C1's promoted-kind gate promotes any "
                "finding of this kind (no further sub-filter - verified empirically clean against SVC-PC-2-7-0)."
            ),
            "read": "checks/recheck/summary.csv column judge_scope_under_inclusion: verdict, _n, _first. Full findings (group, criterion, quote, expected_text, implied_source) in the recheck dir's judge_scope_under_inclusion.json.",
            "procedure": [
                "Read `implied_source` for the file(s) the criterion needs but files= lacks.",
                "Add the source to the group's files=[...] (respect the 1 MiB cap; build a *_judge_extract for an oversized source), or reword the criterion to grade the deliverable's own trace/statement instead of an external comparison (same two options as citation_unverifiable_scan).",
            ],
            "never": NEVER_BASE + ["Never remove the criterion instead of resolving the missing source."],
            "ops": ["replace_literal"],
            "confirm": "judge_scope_under_inclusion must read pass on the next recheck.",
        },
        # -- 11 canonical scans --
        "formula_cache_scan": {
            "measures": "A workbook cell holds a formula with no cached value in the shipped bytes, so the judge's extractor reads it blank. Same underlying defect class as the 45-check formula_health_extraction_loss cell; this is the fast per-task scan version (columns: file, kind, location, detail).",
            "read": "checks/formula_cache_scan.csv rows: task, file, kind, location, detail.",
            "procedure": [
                "If the file is an environment source listed in a judge group's files=, remove it from files= and, if a criterion needed the value, put it in that criterion's Expected clause instead (see judge_scope_over_inclusion).",
                "If the file is the golden, write the cached value into the flagged cell with `set_xlsx_cell` (a literal replaces the formula and its stale/missing cache); do the cells a criterion grades first.",
            ],
            "never": NEVER_BASE + ["Never edit an environment workbook's formulas or values."],
            "ops": ["set_xlsx_cell", "replace_literal"],
            "confirm": "formula_cache_scan must read pass (or the flagged file is no longer in any files= list) on rescan.",
        },
        "quantifier_scope_scan": {
            "measures": "A golden or criterion phrase uses a completeness quantifier (each/every/all/per/complete/full/'current line') whose implied row count does not match the actual source table it should cover (columns: phrase, golden_table, golden_rows, source_table, source_rows, gap).",
            "read": "checks/quantifier_scope_scan.csv rows: task, phrase, golden_table, golden_rows, source_table, source_rows, gap.",
            "procedure": [
                "Compare golden_rows to source_rows for the named tables. If the golden is missing rows the source actually has, add the missing rows (or the missing aggregate) to the golden table so 'every'/'all' is literally true.",
                "If the source table itself is a sample or extract (not the true population) and the golden correctly covers everything the source actually provides, reword the quantifier to state the real scope ('every row in the provided sample' rather than 'every order') instead of adding fabricated rows.",
            ],
            "never": NEVER_BASE + ["Never pad the golden with invented rows to close a genuine population gap the sources do not cover."],
            "ops": ["set_xlsx_cell", "replace_literal", "append_text"],
            "confirm": "quantifier_scope_scan must read pass (gap resolved) on rescan.",
        },
        "escape_hatch_scan": {
            "measures": "The golden or a criterion uses weasel/escape-hatch language ('as appropriate', 'if applicable', 'N/A', 'TBD') where the sources actually support stating a concrete answer, letting the golden dodge a commitment the instruction asked for (columns: where, id_or_loc, token_or_path).",
            "read": "checks/escape_hatch_scan.csv rows: task, where, id_or_loc, token_or_path.",
            "procedure": [
                "Open the flagged location and determine, from the sources, the concrete value or decision the escape-hatch phrase is standing in for.",
                "Replace the escape-hatch token with the concrete, source-grounded statement (`replace_literal`/`set_xlsx_cell`/`replace_docx_text`). If the sources genuinely do not resolve it (a real open question), leave the phrase and record in `notes` why no concrete answer exists.",
            ],
            "never": NEVER_BASE,
            "ops": ["replace_literal", "set_xlsx_cell", "replace_docx_text"],
            "confirm": "escape_hatch_scan must read pass (or the token is recorded as a genuine unresolved question) on rescan.",
        },
        "source_reliability_scan": {
            "measures": "A source figure near the flagged location conflicts with another source's figure for the same fact, or is otherwise unreliable/stale, without the golden disclosing or resolving the conflict (columns: file, loc, flag, nearest_figure, detail).",
            "read": "checks/source_reliability_scan.csv rows: task, file, loc, flag, nearest_figure, detail.",
            "procedure": [
                "Read `detail` and find both conflicting figures in their source files.",
                "If the instruction or golden already picks one source as authoritative, make sure the golden states which figure it used and why (name the source); if neither is stated as authoritative, disclose both and the conflict explicitly rather than picking silently.",
            ],
            "never": NEVER_BASE,
            "ops": ["set_xlsx_cell", "replace_docx_text", "replace_literal"],
            "confirm": "source_reliability_scan must read pass (conflict disclosed or resolved) on rescan.",
        },
        "rubric_consistency_scan": {
            "measures": "Two or more criteria in this task contradict each other or grade the same fact in incompatible ways (columns: kind, criterion_ids, detail).",
            "read": "checks/rubric_consistency_scan.csv rows: task, kind, criterion_ids, detail.",
            "procedure": [
                "Read `detail` and both (or all) named criteria side by side. Work out which one states the requirement correctly against instruction.md.",
                "Reword the wrong criterion's Expected clause with `replace_literal` so it no longer contradicts the other; keep both criteria's names and weights unless the coordinator's task explicitly asked to merge them.",
            ],
            "never": NEVER_BASE,
            "ops": ["replace_literal"],
            "confirm": "rubric_consistency_scan must read pass (no contradiction) on rescan.",
        },
        "answer_preexposure_scan": {
            "measures": "A golden sentence overlaps closely enough with a source-file sentence that a solver reading only the sources (not the golden) would already have the answer pre-written for them - the judge is effectively grading whether the solver copied a source verbatim rather than derived anything (columns: golden_sentence, source_file, source_loc, overlap, golden_file, reason). Warn also folds into the union here (not just fail): a WARN-level near-miss is still worth a human look (17-7-0's four '(final)' rows, C1 18:25Z - a golden literally citing a source filename fragment like '(final)' is a softer form of the same leak).",
            "read": "checks/answer_preexposure_scan.csv rows: task, golden_sentence, source_file, source_loc, overlap, golden_file, reason.",
            "procedure": [
                "Read golden_sentence next to the cited source_loc. If the golden is legitimately quoting the source as a named citation (the instruction asks the deliverable to quote it), this is not a leak: record in `notes` why the overlap is intentional and change nothing.",
                "If the overlap is the golden accidentally restating source prose as if it were the solver's own derived conclusion, paraphrase the golden sentence (same technique as answer_key_rubric_leak: reorder the clause, restate the property, keep every number/name/unit the same) so it no longer shares a long run with the source.",
            ],
            "never": NEVER_BASE + ["Never remove a citation that is a legitimate, disclosed quotation just to clear the overlap score."],
            "ops": ["replace_literal", "set_xlsx_cell", "replace_docx_text"],
            "confirm": "answer_preexposure_scan must read pass (or the remaining warn rows are confirmed legitimate quotations) on rescan.",
        },
        "instruction_input_scan": {
            "measures": "instruction.md names an input file (by exact filename) that does not resolve to anything actually staged in environment/ (columns: named_input, kind, resolved_to=MISSING). Same defect class as the 45-check environment_input cell's pattern 1.",
            "read": "checks/instruction_input_scan.csv rows: task, named_input, kind, resolved_to.",
            "procedure": [
                "If named_input is a graded DELIVERABLE (under solution/files/) rather than a real input, the check likely missed the deliverable-listing marker: restore the '## Graded deliverable filenames' heading in instruction.md and make the identical change in tests/task_prompt.txt.",
                "If it is a real input that was never staged, do not invent the file: name in `notes` where the data should come from, and if another shipped file already carries the same data, reword the prompt sentence to name that file instead.",
            ],
            "never": NEVER_BASE + ["Never add a placeholder file to the environment to satisfy the check."],
            "ops": ["replace_literal"],
            "confirm": "instruction_input_scan must read pass (resolved_to no longer MISSING) on rescan.",
        },
        "cross_group_duplicate_scan": {
            "measures": "The same fact is graded by criteria in two different judge groups (or the same group twice), double-counting or double-penalizing one underlying defect (columns: kind, groups, criterion_ids, note).",
            "read": "checks/cross_group_duplicate_scan.csv rows: task, kind, groups, criterion_ids, note.",
            "procedure": [
                "Read `note` and both named criteria. If they truly grade the identical fact with no distinct scope, reword one so it grades a genuinely different aspect (or, if the task's design intends the duplication, record in `notes` why it is intentional and change nothing).",
            ],
            "never": NEVER_BASE,
            "ops": ["replace_literal"],
            "confirm": "cross_group_duplicate_scan must read pass (or the duplication is recorded as intentional) on rescan.",
        },
        "discretion_pin_scan": {
            "measures": "A criterion pins an exact Expected value ('Expected: 10,000') for something instruction.md or the golden's own language treats as a matter of reasonable judgment/estimate, over-constraining what should be graded as a defensible range or method (columns: discretion_phrase, criterion_id, pinned_expected, match_basis, overlap, discretion_sentence).",
            "read": "checks/discretion_pin_scan.csv rows: task, discretion_phrase, criterion_id, pinned_expected, match_basis, overlap, discretion_sentence.",
            "procedure": [
                "Read discretion_sentence (the instruction/golden language that signals discretion) next to the pinned Expected value.",
                "If the value really is a fixed, source-derivable fact (the 'discretion' language was about something else nearby), leave the pin and record in `notes` why it is not actually discretionary.",
                "If the underlying quantity genuinely allows a defensible range or method, loosen the Expected clause to accept any value that follows a stated, correct method or falls in a stated tolerance band - never just delete the number with no replacement bar.",
            ],
            "never": NEVER_BASE,
            "ops": ["replace_literal"],
            "confirm": "discretion_pin_scan must read pass (or the pin is confirmed non-discretionary in notes) on rescan.",
        },
        "golden_citation_scan": {
            "measures": "A filename-shaped or 'per <source>' citation in the golden's own text does not resolve to any real file under environment/ or solution/files/ (columns: cited_name, found_where=MISSING). Same defect class as the actuator cell source_citation_existence; this is the fast per-task scan version. Warn also folds into the union here.",
            "read": "checks/golden_citation_scan.csv rows: task, cited_name, found_where.",
            "procedure": [
                "Work out what the citation actually refers to: a real file under a slightly different name, or a genuinely unshipped source.",
                "Correct the citation text to the real filename if one exists; otherwise reword to a generic, still-true description or remove the specific-file claim.",
            ],
            "never": NEVER_BASE,
            "ops": ["replace_literal", "set_xlsx_cell", "replace_docx_text"],
            "confirm": "golden_citation_scan must read pass (found_where no longer MISSING) on rescan.",
        },
        "muststrip_scan": {
            "measures": "A criterion still carries leftover authoring/editorial markup (a template placeholder, a 'MUST STRIP'-style internal note, a TODO/FIXME left in from drafting) that should never have shipped in the rubric text (columns: group, criterion_id, line).",
            "read": "checks/muststrip_scan.csv rows: task, group, criterion_id, line.",
            "procedure": [
                "Open the named criterion and remove exactly the flagged leftover line/phrase with `replace_literal`, leaving the real requirement sentence and Expected clause intact.",
            ],
            "never": NEVER_BASE,
            "ops": ["replace_literal"],
            "confirm": "muststrip_scan must read pass (flagged line gone) on rescan.",
        },
        # -- 3 new C1-addendum scans (18:40Z) --
        "tiered_criterion_scan": {
            "measures": "A criterion's own description promises tiers or partial credit (full/half/zero credit, 'at least N of M', a graded scale) while every criterion in this corpus is graded type=\"binary\" by rewardkit (confirmed corpus-wide, no scale/numeric type exists) - so the promised partial credit can never actually be awarded; a solver who earns the 'half credit' case scores zero.",
            "read": "checks/tiered_criterion_scan.csv rows: task, judge_toml, criterion, weight, matched_phrase, description.",
            "procedure": [
                "Read the full Expected clause and work out the distinct tiers/thresholds it describes.",
                "Split the single criterion into separately weighted binary criteria in judge.toml, one per tier/threshold, each independently pass/fail, dividing the ORIGINAL weight across them so the group's total weight is unchanged.",
                "Reword each new criterion's description to state its own single, binary bar (no 'half credit' language remaining in any of them).",
            ],
            "never": NEVER_BASE + ["Never collapse the tiers into a single pass/fail bar that silently drops the partial-credit case - split the weight instead."],
            "ops": ["replace_literal", "append_text"],
            "confirm": "tiered_criterion_scan must read pass (no remaining tier/partial-credit language under a binary criterion), the group's criteria still sum to the declared weight, and the oracle must still total 1.0.",
        },
        "citation_unverifiable_scan": {
            "measures": "A criterion grades a citation, source or provenance claim ('cites', 'traceable', 'reconciles to') and names a specific external record (a ledger, a source file, a specific named workbook) that is not present in the judge group's files=[...], so the judge has nothing to verify the citation against and can only take the deliverable's own word for it.",
            "read": "checks/citation_unverifiable_scan.csv rows: task, judge_toml, criterion, weight, matched_phrase, files_in_scope, description (description is prefixed with '[external pointer: ...]' naming the specific file/record the scan found missing from files=).",
            "procedure": [
                "Identify the exact external file/record the criterion needs, from the '[external pointer: ...]' text.",
                "If that source file exists in the corpus and is small enough, add it to the group's files=[...] (respect the judge's 1 MiB per-file cap; if it's oversized, build a *_judge_extract the same way earlier oversized-group fixes in this corpus did - keep every fact the criteria cite, drop the rest, disclose the truncation in the extract's own NOTE row).",
                "If adding the source is not practical (too large even as an extract, or the source doesn't actually exist), reword the criterion to grade the deliverable's OWN trace/source-register table instead of an external reconciliation - i.e. check that the deliverable states its sourcing claim and the claim is internally consistent, not that it matches a file the judge cannot read.",
            ],
            "never": NEVER_BASE + ["Never remove the criterion instead of resolving the pointer."],
            "ops": ["replace_literal"],
            "confirm": "citation_unverifiable_scan must read pass (either the source is now in files=, or the criterion now grades only the deliverable's own content) on rescan.",
        },
        "asof_date_missing_scan": {
            "measures": "instruction.md uses 'today', 'as of now', 'right now' or a bare 'as of' with no stated date, while this task's own environment sources carry real dates - so a solver has no fixed 'today' to compute against, and the golden was necessarily built against one specific date the instruction never names.",
            "read": "checks/asof_date_missing_scan.csv rows: task, phrase, sentence, source_date_evidence (example dated source filenames as corroboration the ambiguity is real, not a genuinely dateless task).",
            "procedure": [
                "Work out which date the golden was actually built against (the FY/quarter the golden's own figures and sourced facts are anchored to).",
                "State that date explicitly in the flagged instruction.md sentence (e.g. 'as of today, October 2021' rather than a bare 'today'), and make the identical change in tests/task_prompt.txt (the two files must stay byte-identical in this corpus).",
            ],
            "never": NEVER_BASE + ["Never pick a date that disagrees with what the golden was actually built against."],
            "ops": ["replace_literal"],
            "confirm": "asof_date_missing_scan must read pass (every flagged phrase now sits next to an explicit date) on rescan.",
        },
        "judge_group_size_scan": {
            "measures": (
                "A judge group's criteria count exceeds 24 (empirically-set N: the largest group that ran cleanly across "
                "the 23-task DataOS batch was 24; the smallest observed crash was 29). rewardkit's default batched judge "
                "mode compiles one required property per criterion into a single strict schema; a group this large gets "
                "rejected outright (400 invalid_request_error on every run) - confirmed on SVC-PC-26-4-0 (44 criteria) and "
                "SVC-PC-26-8-0 (29 criteria), 9 DataOS majors, both entire tasks unscoreable including the oracle."
            ),
            "read": "checks/judge_group_size_scan.csv rows: task, judge_toml, n_criteria, mode.",
            "procedure": [
                "Read every criterion in the oversized group and group them by the distinct fact/section they grade.",
                "Split into multiple tests/deliverables_NN/judge.toml groups of at most 24 criteria each, giving each a "
                "distinct deliverables_NN directory name; copy the SAME files=[...] list into every new group (the "
                "deliverable and sources a criterion needs do not change because it moved groups).",
                "Divide the weight: sum the original group's declared weight (from tests/reward.toml) and allocate it "
                "across the new groups in proportion to how many criteria (or how much of the original weight) each new "
                "group carries, then update tests/reward.toml's weights table so the new group names replace the old one "
                "and the total still sums to 1.0.",
            ],
            "never": NEVER_BASE + [
                "Never merge or delete criteria to get under the threshold - split groups, don't shrink coverage.",
                "Never let the new groups' weights sum to anything other than the original group's declared weight.",
            ],
            "ops": ["append_text", "replace_literal"],
            "confirm": "judge_group_size_scan must read pass (every group at or under 24 criteria) and the oracle must still total 1.0 across all groups.",
        },
    }
)

ADJUDICATION_PLAYBOOK = {
    "measures": (
        "Two independent GLM solver runs each did the task from instruction.md alone; BOTH failed this criterion under the real judge. An adjudicator "
        "decided the criterion rejects a compliant reading of the instruction (a false rejection: a major at any weight, DataOS 1.5). The finding carries the "
        "adjudicator's `instruction_quote` (the sentence it says demands this, or empty if the instruction never asks for it), what each run actually "
        "did (`run_glm1`, `run_glm2`), its reasoning and a proposed fix_direction."
    ),
    "read": "instruction_quote, run_glm1, run_glm2, reasoning (in description), fix_direction, criterion_text, weight.",
    "procedure": [
        "Check the adjudication before acting on it. Read the criterion (criterion_text) and the quoted instruction sentence. The adjudicator can be wrong: if "
        "the instruction states the requirement clearly and a careful solver could meet it, the criterion is fair and the runs simply missed it. Then emit NO "
        "edit for this finding and say in `notes`: NOT EDITED because <the sentence that demands it>. Never weaken a requirement the instruction states.",
        "If the adjudication is right (the instruction never asks for it, or admits more than one valid reading and the criterion insists on one, or the expected "
        "value cannot be derived from the named sources), change the CRITERION in judge.toml so that every valid reading passes: state the accepted alternatives "
        "explicitly in the Expected clause (for example 'either the $X path or the $Y path, provided the deliverable states which it used'), or drop the "
        "requirement the instruction never made. Keep the criterion's name and weight. One `replace_literal` per criterion.",
        "If the instruction itself is the ambiguous side and one reading is clearly intended, sharpen the instruction sentence instead (and make the identical change in "
        "tests/task_prompt.txt). Prefer the criterion edit; change the instruction only when the ambiguity would mislead a real solver.",
        "Check the golden still passes the changed criterion (it must keep scoring 1.0 on its own rubric) and that no other criterion in the group now duplicates it.",
    ],
    "never": [
        "Never lower difficulty: a requirement a careful solver could meet is not a false rejection however many weak runs missed it.",
        "Never delete the criterion or change its weight. Never edit the golden to match a solver's choice.",
    ],
    "ops": ["replace_literal"],
    "confirm": "The runs are re-graded against the changed rubric and re-adjudicated; the criterion must no longer fail both runs for the reason given, and the oracle must stay 1.0.",
}

ORACLE_PLAYBOOK = {
    "measures": (
        "The golden is graded by the real judge against the task's own rubric (probes/oracle.json) and must score 1.0 (GATE-V2 3.4, DataOS 1.1/1.5). "
        "A criterion below 1.0 means either the golden is missing or wrong on what that criterion asks, or the criterion asks for something the "
        "instruction never required or that a correct golden cannot satisfy."
    ),
    "read": "Each finding is one failing criterion: its name, weight, the judge's own verdict_text, and criterion_text (the rubric wording).",
    "procedure": [
        "Read verdict_text: it states exactly what the judge found missing or wrong, usually with counts and quoted cells. Read criterion_text next, then the "
        "golden content below.",
        "Decide which side is wrong. If the judge's account is correct and the criterion is fair (it follows from instruction.md), fix the GOLDEN: "
        "`set_xlsx_cell` for a workbook cell, `replace_docx_text` for a docx paragraph. Make the smallest edit that satisfies the criterion as written, and "
        "keep every other criterion passing (look at what else the same cell or paragraph is graded on).",
        "If the criterion asks for something instruction.md never required, or a correct golden cannot meet it, fix the CRITERION in judge.toml with "
        "`replace_literal` (never lower difficulty: state the same demand, correctly).",
        "Where the same defect recurs in more than one golden cell (a whole column of generic source labels, for example), sweep every occurrence you can see, "
        "not only the one the verdict quotes, and say which you checked in `notes`.",
    ],
    "never": [
        "Never change a criterion only so a wrong golden passes. Never remove or zero a weight. Never invent a source, figure or citation the environment does not contain.",
    ],
    "ops": ["set_xlsx_cell", "replace_docx_text", "replace_literal"],
    "confirm": "The oracle is re-run on the changed bytes and must total 1.0.",
}

FLIP_PLAYBOOK = {
    "measures": (
        "The golden was graded against its own rubric multiple independent times (probes/oracle.json's `flips`, "
        "probes/oracle.runs.json for the full per-run detail). A criterion that passed in one run and failed in another is not "
        "deterministic: the judge is reading the SAME bytes two different ways, which means a real solver's bytes will be graded "
        "on a coin flip too (DataOS: 5-4-0 scored 0.9714 on q27 for exactly this reason, and GATE-V2's own batch-7/8 sample found "
        "16 of 29 majors were this same class - the golden failing its own rubric only sometimes)."
    ),
    "read": "Each finding lists every flipping criterion (group, id/name) with EVERY run's own passed/value/verdict_text, so the "
    "disagreement between runs is visible directly, not just asserted.",
    "procedure": [
        "Read every run's verdict_text for the criterion side by side. The judge is not lying in either run: find the specific "
        "word or clause in the criterion's Expected text that a careful reader could parse two ways, and confirm both readings "
        "against the golden content below.",
        "If the Expected clause bundles more than one requirement (a compound 'X and Y' or 'X, or if not X then Y'), split it "
        "into separate criteria in judge.toml, one requirement each, and divide the original weight across them so the group's "
        "total weight is unchanged.",
        "If the Expected clause uses a judgment word ('reasonable', 'approximately', 'sufficient', 'roughly', 'material') "
        "replace it with the exact value and an explicit tolerance the golden actually hits (a number, a percentage band, or "
        "'exact match required').",
        "If the Expected clause does not name where to look, name the sheet, cell, or section explicitly so two runs of the "
        "judge are extracting the same fact from the same place rather than searching the whole document differently each time.",
        "After the rewrite, re-run the oracle at --runs 3 (or more) on the changed bytes and confirm the criterion no longer "
        "appears in flips.",
    ],
    "never": [
        "Never loosen the bar to make the flip stop (e.g. lowering what counts as a pass) - the criterion must still demand the "
        "same thing, just unambiguously.",
        "Never delete a flipping criterion. A flip is evidence the wording is unclear, not evidence the check is unnecessary.",
        "Never just re-run the oracle and hope the flip does not recur without changing the wording - a flip that already "
        "happened once will recur at the same rate; the fix is the wording, not the sample.",
    ],
    "ops": ["replace_literal", "set_xlsx_cell", "replace_docx_text"],
    "confirm": "probes/oracle.json's `flips` list is empty for this criterion across a fresh 3-run oracle probe on the changed "
    "bytes, and total_reward (the minimum across the 3 runs) is still 1.0.",
}


def oracle_flip_playbook_text() -> str:
    p = FLIP_PLAYBOOK
    lines = [
        f"WHAT THE CHECK MEASURES: {p['measures']}",
        f"WHAT TO READ: {p['read']}",
        "PROCEDURE:",
    ]
    lines += [f"  {i}. {s}" for i, s in enumerate(p["procedure"], 1)]
    lines.append("NEVER:")
    lines += [f"  - {s}" for s in p["never"]]
    lines.append(f"OPS THAT EXPRESS THE FIX: {', '.join(p['ops'])}")
    lines.append(f"HOW IT IS RE-CHECKED: {p['confirm']}")
    return "\n".join(lines)


GENERIC = {
    "measures": "A deterministic check in the 45-check suite blocks the zip. Its own account is in `docs` below.",
    "read": "`details` holds the cell's findings verbatim.",
    "procedure": [
        "Read `docs` for what the check measures, then each item in `details`; find the exact text or file it points at in the file dump below.",
        "Make the smallest edit that removes the finding without changing what the task demands, using one of the listed ops.",
        "If no op can express the fix, or the fix would make the task easier, emit no edit for it and explain in `notes`.",
    ],
    "never": [
        "Never delete a criterion, change a weight, or lower difficulty to clear a finding."
    ],
    "ops": [
        "replace_literal",
        "set_xlsx_cell",
        "replace_docx_text",
        "replace_ooxml_text",
    ],
    "confirm": "The cell must read pass on the next zip attempt.",
}


def playbook_text(cell: str) -> str:
    p = PLAYBOOKS.get(cell) or GENERIC
    lines = [
        f"WHAT THE CHECK MEASURES: {p['measures']}",
        f"WHAT TO READ: {p['read']}",
        "PROCEDURE:",
    ]
    lines += [f"  {i}. {s}" for i, s in enumerate(p["procedure"], 1)]
    lines.append("NEVER:")
    lines += [f"  - {s}" for s in p["never"]]
    lines.append(f"OPS THAT EXPRESS THE FIX: {', '.join(p['ops'])}")
    lines.append(f"HOW IT IS RE-CHECKED: {p['confirm']}")
    lines.append(f"ACCOUNTING: {ACCOUNTING}")
    return "\n".join(lines)


def adjudication_playbook_text() -> str:
    return _render(ADJUDICATION_PLAYBOOK)


def _render(p: dict) -> str:
    lines = [
        f"WHAT THE CHECK MEASURES: {p['measures']}",
        f"WHAT TO READ: {p['read']}",
        "PROCEDURE:",
    ]
    lines += [f"  {i}. {s}" for i, s in enumerate(p["procedure"], 1)]
    lines.append("NEVER:")
    lines += [f"  - {s}" for s in p["never"]]
    lines.append(f"OPS THAT EXPRESS THE FIX: {', '.join(p['ops'])}")
    lines.append(f"HOW IT IS RE-CHECKED: {p['confirm']}")
    return "\n".join(lines)


def oracle_playbook_text() -> str:
    p = ORACLE_PLAYBOOK
    lines = [
        f"WHAT THE CHECK MEASURES: {p['measures']}",
        f"WHAT TO READ: {p['read']}",
        "PROCEDURE:",
    ]
    lines += [f"  {i}. {s}" for i, s in enumerate(p["procedure"], 1)]
    lines.append("NEVER:")
    lines += [f"  - {s}" for s in p["never"]]
    lines.append(f"OPS THAT EXPRESS THE FIX: {', '.join(p['ops'])}")
    lines.append(f"HOW IT IS RE-CHECKED: {p['confirm']}")
    return "\n".join(lines)


def check_docs(cell: str, max_chars: int = 2600) -> str:
    """Head of the check module's docstring, or '' when no module matches. Cells map to <cell>_check.py; a few map by prefix."""
    base = (
        cell.split("_extraction_loss")[0] if cell.endswith("_extraction_loss") else cell
    )
    cands = [f"{CHECKS_DIR}/{base}_check.py", f"{CHECKS_DIR}/{base}.py"] + sorted(
        glob.glob(f"{CHECKS_DIR}/{base}*.py")
    )
    for p in cands:
        if os.path.isfile(p) and not p.endswith("_test.py"):
            try:
                d = (
                    ast.get_docstring(
                        ast.parse(open(p, encoding="utf-8", errors="replace").read())
                    )
                    or ""
                )
            except Exception:  # noqa: BLE001
                return ""
            d = re.sub(r"\n{3,}", "\n\n", d).strip()
            return d[:max_chars] + (" ..." if len(d) > max_chars else "")
    return ""


def _short(v, n=700):
    s = v if isinstance(v, str) else json.dumps(v, default=str, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f"... [{len(s) - n} more chars]"


def cell_details(recheck_dir: str, cell: str, max_items: int = 14) -> dict:
    """The cell's own findings, verbatim and capped. Reads <recheck_dir>/<cell>.json; returns {} when absent."""
    p = os.path.join(recheck_dir, f"{cell}.json")
    if not os.path.isfile(p):
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"unreadable": str(exc)}
    if isinstance(d, list):
        d = {"results": d}
    r = (
        (d.get("results") or [d])[0]
        if isinstance(d.get("results"), list) and d.get("results")
        else d
    )
    if isinstance(r, list):
        r = {"items": r}
    out = {"status": r.get("status"), "summary": r.get("summary")}
    for k, v in r.items():
        if k in ("task_id", "task_format", "status", "summary"):
            continue
        if isinstance(v, list):
            if not v:
                continue
            out[k] = [
                (
                    {
                        kk: (
                            _short(vv, 900) if isinstance(vv, (str, list, dict)) else vv
                        )
                        for kk, vv in it.items()
                    }
                    if isinstance(it, dict)
                    else _short(it)
                )
                for it in v[:max_items]
            ]
            if len(v) > max_items:
                out[f"{k}__omitted"] = len(v) - max_items
        elif isinstance(v, dict):
            out[k] = _short(v, 1500)
        elif v not in (None, "", [], {}) and k not in (
            "n_golden_files_scanned",
            "n_environment_files_scanned",
            "n_expected_values",
        ):
            out[k] = _short(v, 300)
    return out
