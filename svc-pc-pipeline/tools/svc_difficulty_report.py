"""SVC-PC QC difficulty/assignment report.

Built for the 2026-09-14 QC-team ask (Sydnie, Rich, and others): split the 635-task
SVC-PC/Cirrus Sleep tracker population into easy mechanical wins vs. tasks that
genuinely need LLM-or-human judgment, so the team can prioritize the former for a
Wednesday deadline without duplicating each other's work.

This is an AGGREGATION script, not a fresh QC investigation. Every non-tracker fact
in TASK_CLASSIFICATION below traces to text actually read in:

  - ekw/svc-oracle177-hardfail-fixplan-2026-09-14.md
  - ekw/svc-oracle177-group1-verification-2026-09-14.md  (dataset 1001, 19 tasks)
  - ekw/svc-oracle177-group2-verification-2026-09-14.md  (dataset 1002, 20 tasks)
  - ekw/svc-oracle177-group3-verification-2026-09-14.md  (dataset 1003, 22 tasks)
  - ekw/svc-oracle177-group4-verification-2026-09-14.md  (dataset 1004, 28 tasks)
  - ekw/svc-oracle177-group5-verification-2026-09-14.md  (dataset 1005, 48 tasks)
  - ekw/svc-oracle177-group6-verification-2026-09-14.md  (dataset 1000, 40 tasks)

Those six group docs cover a specific 177-task slice of the 635-task population (the
"Oracle177" batch: every task that was A-E clean and got a fresh, live Oracle read on
2026-09-14). Group 1's doc does not carry a single unified per-task summary table the
way groups 2-6 do (it has a per-round Oracle table plus a prose "ready" section
instead), so its 19 rows below are hand-transcribed from that prose rather than
table-parsed; groups 2-6 are transcribed from their own unified summary tables. Every
row's defect_category / difficulty_tier / note is a direct transcription of what that
group's doc (or the fixplan doc, for the shared-root-cause groupings) already
concluded - this script does not re-derive, re-run, or re-diagnose anything.

For the other 635 - 177 = 458 tasks, no group doc or fixplan doc gives any per-defect
diagnosis, so difficulty_tier is honestly reported as "not_yet_diagnosed" and
current_blocking_check is computed mechanically from the tracker's own checks A-F
(first non-"pass" check, or "ready" if A-F are all pass in the tracker - note that a
tracker "ready" at this fallback level has NOT been run through the harbor-qc-checks
script gate the way the 177-task group actually was, so it is a weaker signal than a
177-task-group "ready").

Output: one CSV, tools/svc_difficulty_report.csv, columns:
  task_id, population, current_blocking_check, defect_category, difficulty_tier, note
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TRACKER_PATH = REPO / "ekw" / "svc-qc-tracker-merged-2026-09-12.json"
FIXPLAN_PATH = REPO / "ekw" / "svc-oracle177-hardfail-fixplan-2026-09-14.md"
GROUP_DOC_PATHS = {
    n: REPO / "ekw" / f"svc-oracle177-group{n}-verification-2026-09-14.md"
    for n in range(1, 7)
}
OUT_CSV = REPO / "tools" / "svc_difficulty_report.csv"

EXCLUDE_TASKS = {
    "SVC-PC-88-8-0"
}  # confirmed retired slot, wrong-company task, never use

# ---------------------------------------------------------------------------
# Confirm the source docs this report is built from are actually present,
# so a missing/renamed file fails loudly instead of silently under-reporting.
# ---------------------------------------------------------------------------


def _check_sources_exist() -> None:
    missing = [
        p
        for p in [TRACKER_PATH, FIXPLAN_PATH, *GROUP_DOC_PATHS.values()]
        if not p.exists()
    ]
    if missing:
        raise SystemExit(
            "Missing required source doc(s), cannot build an honest report:\n"
            + "\n".join(f"  {p}" for p in missing)
        )


# ---------------------------------------------------------------------------
# Per-task classification for the 177-task Oracle177 batch (groups 1-6,
# 2026-09-14). Hand-transcribed from the group docs' own tables/prose and the
# fixplan doc, grouped and commented by source so each row is traceable.
#
# Fields per row: (task_id, current_blocking_check, defect_category,
#                  difficulty_tier, note)
#
# current_blocking_check values used here: "F" (Oracle), "script_gate" (the
# harbor-qc-checks deterministic gate that sits between tracker Check F and
# Check G - not one of the tracker's own lettered checks, called out
# separately here because that is literally what is blocking these specific
# tasks today), or "ready".
# ---------------------------------------------------------------------------

TIER_MECH = "mechanical_fast"
TIER_DATA = "needs_source_data"
TIER_JUDGE = "needs_llm_or_human_judgment"
TIER_UNDX = "not_yet_diagnosed"

READY_NOTE = "READY: A-E clean, Oracle pass on 2 agreeing rounds, full harbor-qc-checks deterministic gate clean ({crit} criteria, {files} solution file(s), counted fresh via tomllib). No outstanding defect; submit as-is."


def _ready(crit: str, files: str, extra: str = "") -> str:
    n = READY_NOTE.format(crit=crit, files=files)
    return n + (" " + extra if extra else "")


def _oracle_fail(reward: str, extra: str = "") -> str:
    n = f"Oracle-fail, both independent rounds agree (reward {reward}). No per-criterion root-cause diagnosis exists yet for this task - only the aggregate reward is known."
    return n + (" " + extra if extra else "")


# --- GROUP 1 (dataset 1001, batches #2899/#2900) ---------------------------
# Hand-transcribed from ekw/svc-oracle177-group1-verification-2026-09-14.md
# Section 2 (Oracle table) + Section 4/5 (script gate + ready list); this doc
# has no single unified per-task table, unlike groups 2-6.
GROUP1 = [
    (
        "SVC-PC-1-6-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.94/0.94"),
    ),
    (
        "SVC-PC-16-0-0",
        "script_gate",
        "rubric_extraction_blind_lint",
        TIER_JUDGE,
        "rubric_text_lint flagged criterion r038 (deliverables_03/judge.toml) as extraction_blind, matched keywords 'hidden row'/'hidden sheet'. Group1's own read: this reads as a negative-assertion criterion ('contains no hidden sheet/row/column') rather than one that itself demands the judge see hidden formatting state - worth a quick human read before treating as a real defect; the script's verdict is flagged, not waived.",
    ),
    (
        "SVC-PC-24-7-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-40-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.98/0.98"),
    ),
    (
        "SVC-PC-42-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.89/0.92", "(L3)"),
    ),
    (
        "SVC-PC-53-5-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("9", "1"),
    ),
    (
        "SVC-PC-56-4-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.79/0.90"),
    ),
    (
        "SVC-PC-58-8-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "Oracle rounds disagree (1.00 vs 0.97) - a genuine criterion-level flip matching the documented compound-expected-value-flip pattern. Needs a 3rd independent read; never resolve by picking a side.",
    ),
    (
        "SVC-PC-6-3-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.75/0.83"),
    ),
    (
        "SVC-PC-66-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.94/0.90"),
    ),
    (
        "SVC-PC-69-1-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.83/0.87"),
    ),
    (
        "SVC-PC-72-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.79/0.79", "(L3)"),
    ),
    (
        "SVC-PC-7-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.95/0.95"),
    ),
    (
        "SVC-PC-77-0-0",
        "script_gate",
        "rubric_meta_knowledge_impossible",
        TIER_JUDGE,
        "rubric_text_lint flagged criterion c18 (deliverables_02/judge.toml, L3 task) as meta_rubric_knowledge, matched keyword 'self-assessment'. Same shape as 16-0-0: reads as a negative assertion ('contains no grading/scoring/self-assessment content'), not a criterion demanding the deliverable know its own score - worth a human read, not overridden here.",
    ),
    (
        "SVC-PC-77-3-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.99/0.99"),
    ),
    (
        "SVC-PC-77-5-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("23", "1"),
    ),
    (
        "SVC-PC-77-7-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("20", "2"),
    ),
    (
        "SVC-PC-88-0-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("19", "4", "(L3)"),
    ),
    (
        "SVC-PC-93-1-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("23", "1"),
    ),
]

# --- GROUP 2 (dataset 1002, batches #2891/#2892) ----------------------------
GROUP2 = [
    (
        "SVC-PC-22-3-0",
        "script_gate",
        "rubric_extraction_blind_lint",
        TIER_JUDGE,
        "rubric_text_lint flagged criterion r003 (deliverables_01/judge.toml) as extraction_blind - asks whether the workbook is 'computed by formula, not hard-typed,' a property the MarkItDown-based judge extraction cannot see. Group2's own read: a real structural rubric defect, independent of whether the golden is actually correct.",
    ),
    (
        "SVC-PC-24-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "2"),
    ),
    (
        "SVC-PC-24-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.95/0.98"),
    ),
    (
        "SVC-PC-24-6-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-42-3-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "Oracle rounds disagree (0.96 vs 1.00). Needs a 3rd independent read; never resolve by picking a side.",
    ),
    (
        "SVC-PC-42-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.97/0.97"),
    ),
    (
        "SVC-PC-42-8-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.96/0.96"),
    ),
    (
        "SVC-PC-58-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.88/0.88"),
    ),
    (
        "SVC-PC-66-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.86/0.83"),
    ),
    (
        "SVC-PC-7-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.74/0.75"),
    ),
    (
        "SVC-PC-71-0-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "Oracle rounds disagree (1.00 vs 0.83). Needs a 3rd independent read; never resolve by picking a side.",
    ),
    (
        "SVC-PC-72-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("12", "1"),
    ),
    (
        "SVC-PC-77-8-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("24", "2"),
    ),
    (
        "SVC-PC-77-9-0",
        "script_gate",
        "formula_smell_needs_human_check",
        TIER_JUDGE,
        "formula_health_check flagged mixed_qualifier_smell in solution/files/Cirrus_FY2021_Working_Capital_Model.xlsx, sheet Scenarios, cell B13 (mixes a sheet-qualified ref with 2 bare ones). Cached and recomputed values currently agree, so not wrong today, but the finding sits inside graded scope (criteria c07a/c07c). The same heuristic was independently cross-checked on 4 other tasks by the fixplan doc and found likely false-positive-prone (23/24 sampled cells matched cached==recomputed) - worth the same spot-check here before treating as a real defect.",
    ),
    (
        "SVC-PC-78-6-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.82/0.71"),
    ),
    (
        "SVC-PC-78-7-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.77/0.81"),
    ),
    (
        "SVC-PC-8-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.96/0.98"),
    ),
    (
        "SVC-PC-93-3-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.98/0.98"),
    ),
    (
        "SVC-PC-93-4-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "Oracle rounds disagree (1.00 vs 0.67); this fresh pair does not even agree with itself, so it stays disputed regardless of the tracker's older separate fail evidence. Needs a 3rd independent read.",
    ),
    (
        "SVC-PC-93-6-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.66/0.66"),
    ),
]

# --- GROUP 3 (dataset 1003, batches #2893/#2894) ----------------------------
GROUP3 = [
    (
        "SVC-PC-78-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.7666/0.8111"),
    ),
    (
        "SVC-PC-93-0-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("25", "1"),
    ),
    (
        "SVC-PC-80-6-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-72-3-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("12", "1"),
    ),
    (
        "SVC-PC-58-2-0",
        "F",
        "formula_missing_sheet_qualifier_confirmed",
        TIER_MECH,
        "Confirmed missing-sheet-qualifier formula bug (a '=Channel_Model!B17*$B$7'-shaped reference silently resolving $B$7 on the wrong sheet, a 210x overstatement); Group3's doc calls this 'already root-caused in a prior session, not a surprise.' Root cause and fix pattern (add the correct sheet qualifier) are both known - mechanical once someone edits the formula, no open design question.",
    ),
    (
        "SVC-PC-58-3-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "This pair disagrees (1.00 vs 0.98); tracker also carries flip_disputed from an earlier dataset (993). Needs a 3rd independent read.",
    ),
    (
        "SVC-PC-58-9-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "This pair disagrees internally (1.00 vs 0.94), but the tracker's fuller history (dataset 988, both_fail) keeps the overall verdict at fail rather than auto-resolving off this pair alone. Needs a 3rd independent read across all evidence, not just this pair.",
    ),
    (
        "SVC-PC-58-4-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.8959/0.8959"),
    ),
    (
        "SVC-PC-24-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9833/0.9833"),
    ),
    (
        "SVC-PC-10-0-0",
        "F",
        "no_oracle_runs_never_evaluated",
        TIER_UNDX,
        "Zero Oracle runs of any kind - this task does not appear in either of dataset 1003's two batch runs. The dataset's own validation panel flags it with an ERROR (plus 2 warnings), consistent with why it never ran. Needs investigation into the validation error before it can even be scored, let alone diagnosed.",
    ),
    (
        "SVC-PC-28-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9576/0.9576"),
    ),
    (
        "SVC-PC-45-3-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.744/0.7588"),
    ),
    (
        "SVC-PC-22-7-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9417/0.9417"),
    ),
    (
        "SVC-PC-77-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9697/0.9697"),
    ),
    (
        "SVC-PC-93-5-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "Previously an established pass (dataset 991, both rounds >=1.0); this group's own fresh pair disagrees internally (1.00 vs 0.9829), which is what triggered a same-day tracker correction from pass to flip_disputed. Needs a 3rd independent read.",
    ),
    (
        "SVC-PC-93-2-0",
        "F",
        "wrong_deliverable_format",
        TIER_MECH,
        "Group3's own tracker cross-reference flags this as the 'known wrong_deliverable_format pattern' (part of the 93-x family shipping .xlsx where the rubric requires .docx; prior fail from dataset 991 agrees with this fresh fail). Root cause is known; fix is a mechanical re-export/conversion to the required format once confirmed.",
    ),
    (
        "SVC-PC-68-3-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.75/0.75"),
    ),
    (
        "SVC-PC-65-8-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9667/0.9434"),
    ),
    (
        "SVC-PC-71-2-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "This group's own pair agrees pass (1.0/1.0), but the tracker keeps the overall verdict flip_disputed because an earlier, different-dataset pair (993) flipped, and the project rule is never to resolve a standing dispute by picking a side (including a newer agreeing pair alone). Not treated as ready.",
    ),
    (
        "SVC-PC-80-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9833/0.9833"),
    ),
    (
        "SVC-PC-25-1-0",
        "ready",
        "stray_orig_file_cleanup",
        TIER_MECH,
        _ready(
            "33",
            "2",
            "Note: the 2 files are the real golden plus a same-named .xlsx.orig backup left by an earlier formula_cache_autofix.py run - no gating script flags a stray .orig file, but it should be deleted from solution/files/ before this task ships.",
        ),
    ),
    (
        "SVC-PC-8-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9836/0.9836"),
    ),
]

# --- GROUP 4 (dataset 1004, batches #2895/#2896/#2903/#2904) ---------------
GROUP4 = [
    (
        "SVC-PC-14-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.95 (4/4 runs agree)", "(L3)"),
    ),
    (
        "SVC-PC-14-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("23", "3"),
    ),
    (
        "SVC-PC-2-2-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "4 independent runs split 2 pass / 2 fail. Needs a 3rd (in this case really a 5th) independent read; never resolve by majority of runs.",
    ),
    (
        "SVC-PC-25-2-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("32", "1"),
    ),
    (
        "SVC-PC-25-3-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.94/0.94/0.89/0.91 (4/4 runs agree fail)"),
    ),
    (
        "SVC-PC-25-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("20", "1"),
    ),
    (
        "SVC-PC-31-6-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.96/0.86/0.96/0.96 (4/4 runs agree fail)"),
    ),
    (
        "SVC-PC-3-4-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.96 (4/4 runs agree)"),
    ),
    (
        "SVC-PC-36-4-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "4 independent runs split 2 pass / 2 fail. The tracker's existing F status only folded in 1 of the 4 runs (batch_2904, fail) against older dataset-993 history and called it an agreeing fail - it never saw the other 3 runs. Needs a real fold-in of all 4 runs plus a further independent read, not just a re-check of the existing tracker note.",
    ),
    (
        "SVC-PC-3-8-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready(
            "57",
            "2",
            "Note: tracker Check F currently reads fail, but that is from an older, different dataset (991) that predates this build; this Group4 package's own 4 fresh runs (2895/2896/2903/2904) all score 1.00, and the tracker's own evidence text already flags the conflict as unresolved. Live evidence says ready; the tracker fold-in itself needs fixing separately.",
        ),
    ),
    (
        "SVC-PC-41-6-0",
        "script_gate",
        "rubric_extraction_blind_lint",
        TIER_JUDGE,
        "rubric_text_lint flagged criterion r003 (deliverables_01/judge.toml) as extraction_blind - asks the judge to confirm summary cells are 'formula-driven from source tabs,' which MarkItDown-based extraction can't see.",
    ),
    (
        "SVC-PC-43-1-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.62/0.68 (2/2 runs agree, notably low)"),
    ),
    (
        "SVC-PC-46-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.76/0.76"),
    ),
    (
        "SVC-PC-46-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("12", "1"),
    ),
    (
        "SVC-PC-53-3-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("9", "1"),
    ),
    (
        "SVC-PC-53-6-0",
        "script_gate",
        "formula_smell_needs_human_check",
        TIER_JUDGE,
        "formula_health_check flagged mixed_qualifier_smell in FY2022_Customer_Support_OKR_Plan.xlsx, sheet 'Volume & Demand', cell D19. Cached value 5464.8 vs recomputed 5464.800000000001 - floating-point noise, not a real discrepancy (per the fixplan doc's own cross-check of this exact cell), and the finding does not map to any graded criterion. Fixplan's recommendation, not yet acted on: fold this back into the ready/Jafar-bound set once independently confirmed.",
    ),
    (
        "SVC-PC-57-2-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("16", "1"),
    ),
    (
        "SVC-PC-57-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("13", "1"),
    ),
    (
        "SVC-PC-65-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.95/0.99 (2/2 runs agree)"),
    ),
    (
        "SVC-PC-67-2-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("16", "1"),
    ),
    (
        "SVC-PC-67-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("16", "1"),
    ),
    (
        "SVC-PC-68-1-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "Only 2 runs exist and they disagree (0.75 vs 1.00). Needs a 3rd independent read.",
    ),
    (
        "SVC-PC-68-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.71/0.96 (2/2 runs agree)"),
    ),
    (
        "SVC-PC-70-5-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-73-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("14", "1"),
    ),
    (
        "SVC-PC-77-4-0",
        "script_gate",
        "duplicate_criterion_check_likely_benign",
        TIER_JUDGE,
        "duplicate_criterion_check flagged one id collision in the pre-conversion rubric xlsx (sheet 'Score Analysis'): two rows both labeled 'Total' (row 8 =SUM(B5:B7), row 21 =SUM(B11:B20)). Reads as two ordinary subtotal rows, not duplicate scored criteria - consistent with judge_criterion_name_duplicate_check (the check that actually reads the built judge.toml) finding zero collisions. Likely benign, but the literal script verdict is fail and was not waived; needs a quick human confirm.",
    ),
    (
        "SVC-PC-91-0-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "Only 2 runs exist and they disagree (1.00 vs 0.89, L3 task). The tracker's existing F status only folded in 1 of the 2 runs (batch_2904, fail) against older dataset-991 history - never saw the agreeing/disagreeing pair together. Needs a proper fold-in of both runs plus a 3rd independent read.",
    ),
    (
        "SVC-PC-94-0-0",
        "script_gate",
        "missing_input_file",
        TIER_JUDGE,
        "Two findings: (1) rubric_text_lint flags criterion b3 (deliverables_01/judge.toml) extraction_blind, same class as 41-6-0 above; (2) environment_input_check flags instruction.md line 60 naming a single required file Q1-Q4_Channel_Attribution.xlsx that does not exist - environment/initial_workspace/ instead has 4 separate quarterly files (Q1_/Q2_/Q3_/Q4_Channel_Attribution.xlsx). Group4's own read: may be intentional shorthand a solver would read as 'the four quarterly files,' or a genuine mismatch - a human call, not resolved in the doc. Same family as SVC-PC-91-2-0/91-3-0 (fixplan) and SVC-PC-12-1-0's related Pipeline_Tracker.xlsx question.",
    ),
]

# --- GROUP 5 (dataset 1005, batches #2897/#2898/#2901/#2902 canonical) -----
GROUP5 = [
    (
        "SVC-PC-19-7-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.8906/0.8672"),
    ),
    (
        "SVC-PC-80-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.4167/0.4815 (3 runs, notably low)"),
    ),
    (
        "SVC-PC-14-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.95/0.95"),
    ),
    (
        "SVC-PC-17-8-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9474/0.9474"),
    ),
    (
        "SVC-PC-19-6-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("40", "2"),
    ),
    (
        "SVC-PC-43-4-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.885/0.885"),
    ),
    (
        "SVC-PC-67-1-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("20", "1"),
    ),
    (
        "SVC-PC-14-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail(
            "0.1954/0.1954 (very low, likely a severe/structural failure worth a first look)"
        ),
    ),
    (
        "SVC-PC-18-0-0",
        "F",
        "corrupted_deliverable_xlsx",
        TIER_MECH,
        "Flat 0.0 reward on all 4 runs with no reward-details and no exception_info - on the surface matches the documented 'genuine unexplained anomaly' shape, but Group5's doc dug one layer further into verifier/test-stdout.txt and found the real cause: a zip-level corruption in the deliverables_05 xlsx (MarkItDown's XlsxConverter: 'Error -3 while decompressing data: invalid code -- missing end-of-block'). This is a corrupted-file build defect, not a content or judgment issue - fix is rebuilding the task from source (python pipeline/tools/svc_pc_batch_convert.py --only SVC-PC-18-0-0 --reset ...).",
    ),
    (
        "SVC-PC-28-3-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-41-2-0",
        "script_gate",
        "formula_smell_needs_human_check",
        TIER_JUDGE,
        "formula_health_check flagged 18 mixed_qualifier_smell findings, the largest count of any task in this population; also flagged by rubric_text_lint. Per the fixplan doc's cross-check of this exact task (and 3 others sharing this heuristic), the flagged cells' recomputed_value matched cached_value in 23 of 24 sampled cases (the 24th was floating-point noise) - likely false-positive-prone, but not yet confirmed for all 18 findings specifically on this task; fixplan recommends a spot-check of 2-3 formulas by eye before treating as clean.",
    ),
    (
        "SVC-PC-21-1-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9268/0.9268"),
    ),
    (
        "SVC-PC-12-7-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("43", "1"),
    ),
    (
        "SVC-PC-28-4-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.984/0.984"),
    ),
    (
        "SVC-PC-22-1-0",
        "script_gate",
        "rubric_text_lint_flag_unspecified_type",
        TIER_JUDGE,
        "One of the fixplan doc's 10 advisory-only tasks: passed every deterministic gate except rubric_text_lint. The fixplan doesn't break out which of extraction_blind / stale_format_mismatch / meta_rubric_knowledge applies to this specific task (only the pooled list of 10). Per the fixplan: a real risk pattern, not yet a confirmed defect - needs a fast human read.",
    ),
    (
        "SVC-PC-1-3-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9074/0.9074"),
    ),
    (
        "SVC-PC-2-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-80-7-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-44-4-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "Oracle rounds disagree (1.00 vs 0.9667). Needs a 3rd independent read.",
    ),
    (
        "SVC-PC-44-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9235/0.9395"),
    ),
    (
        "SVC-PC-72-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.92/0.92 (3 runs)"),
    ),
    (
        "SVC-PC-53-4-0",
        "script_gate",
        "rubric_text_lint_flag_unspecified_type",
        TIER_JUDGE,
        "One of the fixplan doc's 10 advisory-only tasks: same situation as SVC-PC-22-1-0 above - passed every deterministic gate except rubric_text_lint, specific finding type not broken out for this task individually, real risk pattern per the fixplan but not a confirmed defect.",
    ),
    (
        "SVC-PC-3-7-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9696/0.9696"),
    ),
    (
        "SVC-PC-68-0-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("15", "3"),
    ),
    (
        "SVC-PC-9-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9815/0.9907 (2 runs)"),
    ),
    (
        "SVC-PC-96-4-0",
        "script_gate",
        "blank_rubric_expected_value",
        TIER_DATA,
        "rubric_schema_check flagged all 40 grading criteria across all 4 judge.toml files with a blank/placeholder Expected: value (placeholder_expected detector, 40/40 hit) - a total rubric-hydration failure, not partial, per the fixplan doc. Needs the pre-hydration rubric source for this task (same class of fix as the SVC-PC-14-1-0 'supporting company record' placeholder bug on record) - get the real values from whoever ran the rubric build, do not guess at 40 values.",
    ),
    (
        "SVC-PC-21-3-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("23", "1"),
    ),
    (
        "SVC-PC-43-5-0",
        "script_gate",
        "tab_naming_mismatch",
        TIER_MECH,
        "tab_naming_check flagged 1 tab-position mismatch (rubric text names the wrong tab position vs. the real golden's tab order - the same stale-rubric-template class documented for the 65-x/44-x families); also flagged by rubric_text_lint. Fix is a mechanical rubric-text edit to match the real tab position, once confirmed against the golden.",
    ),
    (
        "SVC-PC-19-3-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("40", "2"),
    ),
    (
        "SVC-PC-80-3-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.752/0.7205 (2 runs)"),
    ),
    (
        "SVC-PC-2-6-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-67-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.8077/0.8077"),
    ),
    (
        "SVC-PC-1-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.903/0.903"),
    ),
    (
        "SVC-PC-20-0-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "Oracle rounds disagree (0.9583 vs 1.00); tracker's stale F read of plain fail is superseded by this fresh disputed pair. Needs a 3rd independent read.",
    ),
    (
        "SVC-PC-20-7-0",
        "script_gate",
        "rubric_text_lint_flag_unspecified_type",
        TIER_JUDGE,
        "Passed every deterministic gate except rubric_text_lint (finding type not broken out for this task in Group5's doc). Not one of the fixplan's named 10 advisory tasks - this is a Group5-doc-only finding.",
    ),
    (
        "SVC-PC-21-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("22", "1"),
    ),
    (
        "SVC-PC-5-0-0",
        "F",
        "rubric_possibly_over_strict",
        TIER_JUDGE,
        "Fails cleanly and consistently across all 4 runs (0.8788/0.8788/0.8687/0.8788). Group5's doc names this as the handoff's documented 'rubric possibly over-strict, not a golden defect' case: the golden's behavior looks reasonable, the rubric's phrasing is what fails it. Needs a rubric-author decision, not an automatic golden edit.",
    ),
    (
        "SVC-PC-70-1-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-6-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.8833/0.90"),
    ),
    (
        "SVC-PC-2-7-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-2-5-0",
        "F",
        "oracle_disputed_flip",
        TIER_JUDGE,
        "Oracle rounds disagree (1.00 vs 0.9833). Needs a 3rd independent read.",
    ),
    (
        "SVC-PC-53-1-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("9", "1"),
    ),
    (
        "SVC-PC-22-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9841/0.9841"),
    ),
    (
        "SVC-PC-21-2-0",
        "ready",
        "stray_orig_file_cleanup",
        TIER_MECH,
        _ready(
            "22",
            "2",
            "Note: the 2 files are Close_Authority_and_Review_Map.xlsx plus a stray same-named .xlsx.orig backup - no gating script flags it, but it does not belong in solution/files/ and should be removed before shipping.",
        ),
    ),
    (
        "SVC-PC-13-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9811/0.9811"),
    ),
    (
        "SVC-PC-65-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9114/0.927"),
    ),
    (
        "SVC-PC-36-1-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.9815/0.9815"),
    ),
    (
        "SVC-PC-91-3-0",
        "script_gate",
        "missing_input_file",
        TIER_JUDGE,
        "environment_input_check flagged instruction.md naming Q1-Q4_Channel_Attribution.xlsx as a required input that does not exist. Same shared-root-cause family as SVC-PC-94-0-0/91-2-0 per the fixplan doc (3-task family, one root cause). Fix: locate/add the real combined file, OR confirm it is intentionally absent and edit instruction.md to stop naming it - needs someone who knows this task family's intended design to pick which.",
    ),
]

# --- GROUP 6 (dataset 1000, batches #2889/#2890) ----------------------------
GROUP6 = [
    (
        "SVC-PC-12-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.93/0.93"),
    ),
    (
        "SVC-PC-12-1-0",
        "script_gate",
        "missing_input_file",
        TIER_JUDGE,
        "Three independent blockers, per Group6's doc: (1) environment_input_check fails - instruction.md names Pipeline_Tracker.xlsx, but only 4 per-rep/segment trackers exist (Brian_Q4_Pipeline_Tracker.xlsx, Elena_Q4_Pipeline_Tracker.xlsx, Retail_Partnership_Prospects.xlsx, Wholesale_Prospect_List.xlsx) - the fixplan frames the fix as a genuine design choice (reference the 4 files directly vs. build the missing combined file); (2) tracker Check G already = fail - Jafar's team has already reviewed and rejected this specific task in manual QC, independent of today's Oracle result, and Check G never auto-clears; (3) Jafar's external review separately named this task's rubric as '48 of 50 criteria are exact cell assertions against the reference workbook' - no script catches that defect class yet. Genuinely judgment-heavy, not a quick fix.",
    ),
    (
        "SVC-PC-12-6-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("23", "1"),
    ),
    (
        "SVC-PC-15-5-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("50", "1"),
    ),
    (
        "SVC-PC-16-2-0",
        "F",
        "infra_failure_docker_build_not_content",
        TIER_JUDGE,
        "Exception in both rounds, both carrying a RewardFileNotFoundError ('tar: /testbed: Cannot open' family) - a Docker/Harbor build defect at the task level, reproduced identically across two entirely separate Oracle batches. This is an infrastructure failure, not a content defect; no fix has been built yet (a lightweight local Dockerfile-build check was proposed but not built).",
    ),
    (
        "SVC-PC-16-3-0",
        "F",
        "infra_failure_docker_build_not_content",
        TIER_JUDGE,
        "Same defect as SVC-PC-16-2-0 - exception in both rounds, same RewardFileNotFoundError / Docker build-defect signature. Infrastructure failure, not content; no fix built yet.",
    ),
    (
        "SVC-PC-20-1-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("12", "2"),
    ),
    (
        "SVC-PC-20-2-0",
        "script_gate",
        "rubric_stale_format_mismatch",
        TIER_MECH,
        "rubric_text_lint flagged stale_format_mismatch (10 hits, the largest count in this group) - rubric text names a document format that doesn't match the actual graded file's extension. Once confirmed against the real deliverable, the fix is a mechanical rubric-text edit to match the real format.",
    ),
    (
        "SVC-PC-20-3-0",
        "script_gate",
        "formula_smell_needs_human_check",
        TIER_JUDGE,
        "formula_health_check flagged 4 mixed_qualifier_smell findings. Per the fixplan doc's direct cross-check of this exact task (one of its 4 named Group-3 tasks), all 4 flagged cells have recomputed_value matching cached_value - likely a false positive on this heuristic, per the fixplan not yet acted on.",
    ),
    (
        "SVC-PC-20-4-0",
        "script_gate",
        "rubric_stale_format_mismatch",
        TIER_MECH,
        "rubric_text_lint flagged stale_format_mismatch (4 hits). Mechanical rubric-text fix once the real deliverable format is confirmed.",
    ),
    (
        "SVC-PC-20-5-0",
        "script_gate",
        "rubric_stale_format_mismatch",
        TIER_MECH,
        "rubric_text_lint flagged stale_format_mismatch (1 hit). This task's Oracle result also resolves a prior tracker flip_disputed state to a clean agreeing pass today. Mechanical rubric-text fix once confirmed.",
    ),
    (
        "SVC-PC-20-8-0",
        "script_gate",
        "rubric_stale_format_mismatch",
        TIER_MECH,
        "rubric_text_lint flagged stale_format_mismatch (3 hits). Mechanical rubric-text fix once confirmed.",
    ),
    (
        "SVC-PC-25-5-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.94/0.94"),
    ),
    (
        "SVC-PC-3-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.87/0.87"),
    ),
    (
        "SVC-PC-35-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.86/0.86"),
    ),
    (
        "SVC-PC-35-3-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.98/0.98"),
    ),
    (
        "SVC-PC-35-4-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.83/0.83"),
    ),
    (
        "SVC-PC-36-3-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("15", "1"),
    ),
    (
        "SVC-PC-44-1-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail(
            "0.90/0.94 (criteria mix differs slightly between rounds, both fail)"
        ),
    ),
    (
        "SVC-PC-52-4-0",
        "F",
        "jafar_exact_cell_assertion_rubric",
        TIER_JUDGE,
        "Oracle-fail (agree, 0.93/0.93), never reached the script gate. Separately, Jafar's external review named this task's rubric as part of the same '48/50 criteria are exact cell assertions against the reference workbook' pattern as SVC-PC-12-1-0 - no script catches that defect class yet per harbor-qc-checks' own roadmap. Both the Oracle-fail root cause and the rubric-design caveat are undiagnosed at the criterion level.",
    ),
    (
        "SVC-PC-53-0-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("9", "1"),
    ),
    (
        "SVC-PC-54-4-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail("0.90/0.90"),
    ),
    (
        "SVC-PC-55-0-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("100", "3"),
    ),
    (
        "SVC-PC-6-2-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail(
            "0.90/0.80 (criteria mix differs slightly between rounds, both fail)",
            "Tracker Check G already = fail - Jafar's team has previously rejected this task independently of today's Oracle result.",
        ),
    ),
    (
        "SVC-PC-67-3-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("15", "1"),
    ),
    (
        "SVC-PC-72-1-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("12", "1"),
    ),
    (
        "SVC-PC-73-2-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("14", "1"),
    ),
    (
        "SVC-PC-76-0-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("10", "1"),
    ),
    (
        "SVC-PC-91-1-0",
        "script_gate",
        "formula_smell_needs_human_check",
        TIER_JUDGE,
        "formula_health_check flagged monotonicity_check_skipped_no_driver_link (x3) and cross_scenario_monotonicity (x5) - a different formula_health heuristic than mixed_qualifier_smell, not covered by the fixplan doc's false-positive cross-check of that other heuristic. Also flagged by rubric_text_lint for 1 extraction_blind criterion. Neither finding has been confirmed real or false-positive yet.",
    ),
    (
        "SVC-PC-91-2-0",
        "script_gate",
        "missing_input_file",
        TIER_JUDGE,
        "environment_input_check flagged instruction.md naming Q1-Q4_Channel_Attribution.xlsx as a required input that does not exist. Same shared-root-cause family as SVC-PC-94-0-0/91-3-0 per the fixplan doc.",
    ),
    (
        "SVC-PC-91-4-0",
        "script_gate",
        "rubric_stale_format_mismatch",
        TIER_MECH,
        "rubric_text_lint flagged stale_format_mismatch (1 hit). This is the task with the documented historical anomaly (an earlier round scored a flat 0.0 with no criteria detail); today's 2 runs both cleanly score 1.00 with 18/18 criteria passed and also resolve a prior tracker flip_disputed state - Group6's doc reports this as the clean result found, not as erasing the historical anomaly record. Mechanical rubric-text fix once confirmed.",
    ),
    (
        "SVC-PC-91-5-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("11", "2"),
    ),
    (
        "SVC-PC-91-6-0",
        "script_gate",
        "rubric_stale_format_mismatch",
        TIER_MECH,
        "rubric_text_lint flagged stale_format_mismatch (1 hit); one of the fixplan doc's 10 named advisory tasks. Mechanical rubric-text fix once confirmed.",
    ),
    (
        "SVC-PC-91-7-0",
        "script_gate",
        "rubric_stale_format_mismatch",
        TIER_MECH,
        "rubric_text_lint flagged stale_format_mismatch (3 hits). Also resolves a prior tracker flip_disputed state to a clean agreeing pass today. Mechanical rubric-text fix once confirmed.",
    ),
    (
        "SVC-PC-91-8-0",
        "script_gate",
        "rubric_stale_format_mismatch",
        TIER_MECH,
        "rubric_text_lint flagged stale_format_mismatch (1 hit); one of the fixplan doc's 10 named advisory tasks. Mechanical rubric-text fix once confirmed.",
    ),
    (
        "SVC-PC-92-0-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("10", "1"),
    ),
    (
        "SVC-PC-92-1-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("10", "1"),
    ),
    (
        "SVC-PC-92-3-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("10", "1"),
    ),
    (
        "SVC-PC-92-4-0",
        "ready",
        "none_ready_for_submission",
        TIER_MECH,
        _ready("10", "1"),
    ),
    (
        "SVC-PC-96-0-0",
        "F",
        "oracle_fail_undiagnosed",
        TIER_UNDX,
        _oracle_fail(
            "0.90/0.93 (criteria mix differs slightly between rounds, both fail)"
        ),
    ),
]

ORACLE177_GROUPS = {1: GROUP1, 2: GROUP2, 3: GROUP3, 4: GROUP4, 5: GROUP5, 6: GROUP6}
ORACLE177_EXPECTED_COUNTS = {1: 19, 2: 20, 3: 22, 4: 28, 5: 48, 6: 40}


def _build_oracle177_classification() -> dict[str, dict]:
    """Flatten the 6 groups into task_id -> classification dict, with a hard
    self-check against each group's own documented task count (the whole
    point of this table is to be trustworthy for a Wednesday deadline)."""
    out: dict[str, dict] = {}
    for group_num, rows in ORACLE177_GROUPS.items():
        expected = ORACLE177_EXPECTED_COUNTS[group_num]
        if len(rows) != expected:
            raise SystemExit(
                f"Group {group_num} classification has {len(rows)} rows, "
                f"expected {expected} per its own verification doc. Fix the "
                f"data before trusting this report."
            )
        for task_id, blocking, category, tier, note in rows:
            if task_id in out:
                raise SystemExit(
                    f"Duplicate task_id {task_id} across Oracle177 groups - fix the source data."
                )
            out[task_id] = {
                "current_blocking_check": blocking,
                "defect_category": category,
                "difficulty_tier": tier,
                "note": f"[group{group_num}/fixplan, 2026-09-14] {note}",
            }
    total = sum(ORACLE177_EXPECTED_COUNTS.values())
    if len(out) != total:
        raise SystemExit(
            f"Oracle177 classification totals {len(out)}, expected {total}."
        )
    return out


# ---------------------------------------------------------------------------
# Fallback classification for the other 635 - 177 = 458 tasks: tracker-only,
# honestly tiered as not_yet_diagnosed since no group/fixplan doc covers them.
# ---------------------------------------------------------------------------

CHECK_ORDER = ["A", "B", "C", "D", "E", "F"]


def _tracker_blocking_check(checks: dict) -> str:
    for letter in CHECK_ORDER[:-1]:  # A-E
        status = checks.get(letter, {}).get("status")
        if status != "pass":
            return letter
    # A-E clean; look at F
    f_status = checks.get("F", {}).get("status")
    if f_status == "pass":
        return "ready"
    return "F"


def _tracker_fallback_note(task_id: str, checks: dict, blocking: str) -> str:
    if blocking == "ready":
        return (
            "Tracker checks A-F all read pass, but this task was NOT part of the "
            "2026-09-14 Oracle177 batch, so it has not been run through the "
            "harbor-qc-checks deterministic script gate the way the 177-task group "
            "was. Weaker 'ready' signal than a group1-6 ready task - worth a script-gate "
            "pass before submitting to Jafar."
        )
    entry = checks.get(blocking, {})
    status = entry.get("status", "missing/never run")
    evidence = (entry.get("evidence") or "").strip()
    if evidence:
        snippet = evidence[:220] + ("..." if len(evidence) > 220 else "")
        return f"Tracker Check {blocking} = {status}. Evidence on file (not independently re-diagnosed here): {snippet}"
    return f"Tracker Check {blocking} = {status}. No evidence text on file and no group/fixplan doc covers this task - genuinely undiagnosed."


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    _check_sources_exist()

    with open(TRACKER_PATH, encoding="utf-8") as f:
        tracker = json.load(f)
    tracker_rows = {r["task_id"]: r for r in tracker["rows"]}

    oracle177 = _build_oracle177_classification()

    out_rows = []
    diagnosed_count = 0
    tier_breakdown: dict[str, int] = {}

    for task_id, row in sorted(tracker_rows.items()):
        if task_id in EXCLUDE_TASKS:
            continue
        population = row.get("population", "?")
        checks = row.get("checks", {})

        if task_id in oracle177:
            cls = oracle177[task_id]
            blocking = cls["current_blocking_check"]
            category = cls["defect_category"]
            tier = cls["difficulty_tier"]
            note = cls["note"]
        else:
            blocking = _tracker_blocking_check(checks)
            category = "not_yet_diagnosed"
            tier = TIER_UNDX
            note = _tracker_fallback_note(task_id, checks, blocking)

        if tier != TIER_UNDX:
            diagnosed_count += 1
        tier_breakdown[tier] = tier_breakdown.get(tier, 0) + 1

        out_rows.append(
            {
                "task_id": task_id,
                "population": population,
                "current_blocking_check": blocking,
                "defect_category": category,
                "difficulty_tier": tier,
                "note": note,
            }
        )

    # Sanity: every Oracle177-classified task_id must actually exist in the tracker.
    missing_from_tracker = sorted(set(oracle177) - set(tracker_rows))
    if missing_from_tracker:
        raise SystemExit(
            f"Oracle177 task_ids not found in tracker: {missing_from_tracker}"
        )

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "task_id",
                "population",
                "current_blocking_check",
                "defect_category",
                "difficulty_tier",
                "note",
            ],
        )
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Wrote {len(out_rows)} rows to {OUT_CSV}")
    print(
        f"Real (non-not_yet_diagnosed) difficulty tier assigned to {diagnosed_count} of {len(out_rows)} tasks"
    )
    for tier in (TIER_MECH, TIER_DATA, TIER_JUDGE, TIER_UNDX):
        print(f"  {tier}: {tier_breakdown.get(tier, 0)}")


if __name__ == "__main__":
    main()
