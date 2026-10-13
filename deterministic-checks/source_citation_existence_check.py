#!/usr/bin/env python3
"""Source-citation existence check: does a task's golden answer (sub-case A)
or its instruction.md (sub-case B) cite a source file that is absent from the
shipped environment?

Why this exists
----------------
A prior round's coverage-gap synthesis (see
ekw/pipeline-mirror/khiem-202-data/comprehensive-review-qc-feedback-2026-09-15/
coverage-synthesis.md, Class 8) found a partially-covered gap: golden or
instruction files cite a source file that is absent from the real shipped
environment, but the EXISTING checks only catch specific sub-cases:

  - `criterion_groundedness_check.py` catches pinned-value cases where a
    criterion's Expected clause names a value the environment lacks. It
    extracts from CRITERION text, not golden cell text.
  - `content_audit_check.py` pattern 3 (Check A, LLM-judged) catches
    golden-prose self-citation of an absent source, e.g. "reconciles to the
    December hosting invoice" when no such file exists. It reads flat text,
    not the filesystem, and is LLM-judged rather than deterministic.

The REMAINING uncovered slice this check closes:

  Sub-case A (mechanically tractable, the primary path): golden CELL CONTENT
    (an xlsx cell value, a docx table cell, etc.) cites a file-path-shaped
    string that does not exist in the task's environment directory. The real
    example this was built from is SVC-PC-37-3-0 RC5/RC6 (cov5 report): the
    golden's Physical Presence Evidence!B6:C6 cites
    `Company Shared Drive\\Vendors\\SwiftShip_Express\\Contracts\\
    MSA_SwiftShip_2021.pdf` which does not exist, and no "Reno" evidence
    appears in any of the 183 environment files. The existing prose-focused
    checks can miss content embedded in spreadsheet cells specifically, so
    this check iterates golden files cell-by-cell (reusing the openpyxl /
    python-docx loading path answer_key_rubric_leak_check.py already
    calibrated) and extracts file-path-shaped strings, then cross-references
    each against a recursive listing of the task's environment directory.

  Sub-case B (harder, semantic, a conservative deterministic heuristic):
    instruction.md names files by CATEGORY, not filename - e.g. "the Apex and
    SwiftShip rate cards" (SVC-PC-41-4-0 RC2, cov6 report) with no actual
    filenames matching that description anywhere in the environment.
    `environment_input_check.py`'s bare-token filename extractor requires a
    `word.ext` shape and structurally cannot extract a category-name
    reference like "rate cards" (no file extension present in the phrase).
    This check uses a fuzzy heuristic: it finds a category word (card, export,
    report, file, document, sheet, ledger, invoice, log, register, policy,
    contract, manual, plan, tracker, schedule, roster) preceded by a proper
    noun in the same clause, then checks whether any environment basename
    contains that proper noun. If no environment file plausibly corresponds,
    it flags a candidate finding.

Calibration
-----------
Sub-case A: calibrated against the real 202-task SVC-PC corpus (round 31-32)
by reconstructing native task dirs from the text/metadata corpus at
full-202-text-and-listings + real golden files from full-202-solution-files,
using file_listing.txt basenames as the environment.

  Before the round-31 fix: 149 sub-case A findings across 14/33 sampled
  tasks. After the fix (6 extraction-artifact filters): 123 findings across
  the same 14 tasks (17% reduction). The dominant residual is a STRUCTURAL
  false positive: PBC tracker / evidence index / source register goldens
  (SVC-PC-14-1-0, 71 findings from one golden) whose PURPOSE is to list files,
  some of which are genuinely absent (the tracker tracks what is missing).
  This is disclosed below, not fixable without semantic understanding of the
  golden's role.

  TRUE POSITIVES confirmed against real data:
    - SVC-PC-37-3-0: MSA_SwiftShip_2021.pdf and MSA_Apex_2021.pdf (the
      known cov5 defect: the golden cites MSA files absent from the
      environment; env has COI_Apex_Logistics.pdf and COI_SwiftShipExpress.pdf
      but no MSA files).
    - SVC-PC-17-4-0: Quality_Standards.xlsx (env has Quality_Standards.pdf,
      not .xlsx: a real file-type mismatch).
    - SVC-PC-1-2-0/1-5-0: Cirrus_Sleep_Canonical_Facts_Trusted.xlsx and
      Cirrus_Sleep_Bible_Human_Trusted.docx (the instruction marks these as
      "Source of truth for verification only"; their absence from the env is
      a real gap or an intentional non-ship, either way correctly flagged).

  TRUE NEGATIVES confirmed: 17/33 sampled tasks returned 0 sub-case A
  findings (SVC-PC-1-1-0, 10-2-0, 10-3-0, 10-4-0, 10-5-0, 11-2-0, 11-4-0,
  12-1-0, 12-2-0, 12-3-0, 12-5-0, 15-1-0, 15-2-0, 15-4-0, 15-5-0, 16-1-0,
  17-2-0). The round-31 review's claim that sub-case A was "never tested
  against real positive data" is DISPROVEN: real clean tasks correctly
  produce zero findings.

Sub-case B: calibrated against the real 202-task SVC-PC corpus (round 31).
  Before the fix: 46/202 tasks fired, 65 findings, of which ~64 were false
  positives (~98% FP rate). After the fix (COMMON_CAPITALIZED_WORDS exclusion
  set + FY exclusion): 5/202 tasks fired, 7 findings (89% reduction).

  The remaining 7 findings:
    - 1 TRUE POSITIVE: SVC-PC-41-3-0 "the NovaTex MSA Schedule" (env has
      Year_2_Demand_Plan_Draft.xlsx and Holiday_Forecast_vs_Actual.xlsx but
      no NovaTex MSA file).
    - 1 BORDERLINE: SVC-PC-72-3-0 "the launch-agency SOW, invoices" (SOW =
      Statement of Work; can be file-identifying since SOW_BrightMark_Launch.pdf
      exists in other tasks' environments. Correctly kept as a finding.)
    - 5 STRUCTURAL LIMITS: Workday x4 (SVC-PC-29-2-0, SVC-PC-88-0-0 x3) and
      Shopify x1 (SVC-PC-70-1-0). These are real system names whose
      environment files are named by content, not system name (e.g., the
      roster file exists but is not named "workday_*"). Disclosed below.

  The round-31 adversarial review's three claimed FP modes, re-derived
  against the real 202-task corpus:
    1. "FY being treated as a proper noun": CONFIRMED. 6/65 findings before
       the fix (SVC-PC-12-3-0, 12-5-0, 46-3-0, 72-1-0, 75-2-0, 92-0-0).
       Fixed by adding "fy" to COMMON_CAPITALIZED_WORDS.
    2. "generic deliverable words (memo, workbook, chart)": NOT CONFIRMED.
       These specific words do NOT appear as proper nouns in any of the 65
       findings. The broader pattern IS real (other heading/label words do
       get treated as proper nouns), but the specific examples in the
       review's paraphrase are inaccurate. Added "memo", "workbook",
       "chart" to COMMON_CAPITALIZED_WORDS preemptively.
    3. "person names all trip it": NOT CONFIRMED in this corpus. No actual
       person names appear in the 65 findings. Person names in the
       instruction files appear in email headers ("From: Sarah Kim") which
       are not near category words, so they don't trigger findings. This
       is a latent risk if a person name happened to appear near a category
       word, but it did not manifest in 202 real tasks.

Known limits, disclosed rather than silently dropped
----------------------------------------------------
  Sub-case A:
    1. PBC tracker / evidence index / source register goldens: the golden's
       PURPOSE is to list files, some absent. SVC-PC-14-1-0 produces 71
       findings from one PBC tracker golden. Not fixable without
       understanding the golden's semantic role. A human reviewer recognizes
       "this is a PBC tracker, it lists missing files" and moves on.
    2. Name variations: COI_SwiftShip_Express.pdf (golden) vs
       COI_SwiftShipExpress.pdf (env) at SVC-PC-12-6-0. Exact basename
       matching misses files with minor naming differences. Fuzzy matching
       would create its own false negatives.
    3. Range shorthand: FIXED for the Qn-Qm_ numeric-quarter shape (round
       42, `_quarter_range_satisfied`) -- Q1-Q4_Channel_Attribution.xlsx
       (golden) vs Q1_Channel_Attribution.xlsx + Q2/Q3/Q4 (env) at
       SVC-PC-13-3-0 is suppressed only when every individual quarter file
       the range stands for is confirmed present. A different range word
       (e.g. a half-year "H1-H2_") is still unfixed, not confirmed to
       occur in the real corpus.

  Round 42 fixes (source_citation_existence triage, real 600-task corpus
  before/after; see deterministic-checks/_scratch_fullcorpus_diff2.py-style
  verification, not retained): starting point 255/600 tasks warn, 11,978
  total findings. Three check-tooling gaps GLM's round-42 triage
  characterized (`ekw/pipeline-mirror/results/round42-source-citation-
  triage-consolidated-2026-09-16.md` on `origin/glm-worker`,
  turing-context repo), each independently re-verified against this real
  corpus (not GLM's mirror) before fixing:
    1. Companion-deliverable reference escaping skip_basenames
       (SVC-PC-7-4-0, filter 7 above): a two-golden task where each
       golden cross-references the OTHER by an internal/pre-rename name
       ("L2-04_Task_7_Golden.xlsx", "Cirrus_Sleep_FY2022_Ops_Model_
       GOLDEN.xlsx") neither of which exists anywhere in the real
       600-task corpus. 3 findings removed, gated on 2+ golden files so
       the 9 other real "golden"-substring findings in the corpus
       (SVC-PC-3-4-0, SVC-PC-7-2-0, SVC-PC-94-3-0 x7 -- all single-golden
       tasks) are untouched.
    2. Versioned naming-convention extraction artifact (SVC-PC-80-7-0,
       Pass-3 guard above): a golden's own naming-convention EXAMPLE
       ("..._v2.0_FINAL.docx") gets its tail matched as a bare filename
       ("0_FINAL.docx") because the regex sees a word boundary right
       after the "." in "v2.0". Fixed generally (any bare-filename match
       immediately preceded by "<digit>."), which also caught a second,
       previously uncharacterized real instance GLM's sample never
       covered: SVC-PC-80-5-0's "...v1.1_FINAL.xlsx" example producing
       phantom citation "1_FINAL.xlsx". Both phantom basenames confirmed
       absent everywhere in the real corpus before suppressing. 2
       findings removed.
    3. Range shorthand over present quarterly files (SVC-PC-13-3-0 /
       SVC-PC-42-1-0 in GLM's sample; `_quarter_range_satisfied` above):
       fixed generally rather than per-task, which surfaced the same
       shape recurring far beyond GLM's 2-task sample -- 8 tasks total
       (SVC-PC-13-3-0, 26-3-0, 42-1-0, 47-0-0, 47-5-0, 75-3-0, 75-8-0,
       91-3-0), 18 findings. Conservative by construction: suppresses
       only when EVERY quarter the range names is confirmed present, so
       a partial range stays flagged.
  **Real full-600-task after: 251/600 warn (-4), 11,955 total findings
  (-23), 0 errors either run, 0 findings added (fixed diff, not just a
  count coincidence: the exact 23 findings removed are the union of the
  three patterns above and nothing else).** Reproduce with
  `python deterministic-checks/source_citation_existence_check.py --all
  --id-prefix SVC-PC- --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\
  03_dataos_ready --out out.json` (~4-11 min single-process depending on
  disk cache state; no --shards/--jobs flag on this script).

  Sub-case B:
    1. System names (Workday, Shopify): real system names where the env file
       is named by content, not system name. The finding fires because no
       env basename contains "workday" or "shopify". This is a true positive
       (the system's export genuinely doesn't exist as a named file) or a
       structural false positive (the file exists under a different name).
       Either way, warn-only; a human decides.
    2. Business acronyms that CAN be file-identifying (SOW, MSA): correctly
       NOT excluded, because real env files like SOW_BrightMark_Launch.pdf
       and MSA_SwiftShip_2021.pdf exist. The finding on SVC-PC-72-3-0 ("the
       launch-agency SOW") is a borderline case a human should triage.
    3. COMMON_CAPITALIZED_WORDS is an ever-growing exclusion list calibrated
       against real data. New tasks may introduce new heading words not yet
       in the list; each would produce a false positive until added. This
       is the same maintenance pattern duplicate_criterion_content_check.py
       uses for its Jaccard threshold.

Severity and gating
-------------------
Every finding this check produces is warn-severity (a candidate for human or
LLM review), never fail. Both sub-cases are heuristics: sub-case A's
path-citation regex can match a label or formula fragment that happens to
end in a recognized extension, and sub-case B's proper-noun + category-word
match can fire on a person or place name rather than a file. A finding never
hard-gates a task on its own, matching how every other warn-tier check in
this folder (pinned_value_prescreen, spelling_grammar, test_coverage_absence,
instruction_requirement_coverage) already works.

Output shape
------------
Per-task result dict (the same verdict + findings shape every other check in
this folder produces, so it merges into svc_run_checks.py /
ekw_run_checks.py the same way):

    {
        "task_id": "SVC-PC-37-3-0",
        "status": "pass" | "warn" | "skip" | "error",
        "task_format": "svc_pc" | "ekw" | "none",
        "n_golden_files": 1,
        "environment_exists": true,
        "findings": [
            {
                "kind": "golden_cites_absent_file" | "instruction_names_absent_category",
                "sub_case": "A" | "B",
                "severity": "warn",
                "citation": "the path or category phrase found",
                "basename": "MSA_SwiftShip_2021.pdf",   # sub-case A only
                "location": "solution/files/Revenue.xlsx!Physical Presence Evidence!B6",
                "environment_checked": "environment/initial_workspace/",
                "evidence": "no file matching 'MSA_SwiftShip_2021.pdf' under environment/initial_workspace/"
            }
        ],
        "n_findings": 0,
        "errors": []
    }

Usage
-----
    python source_citation_existence_check.py --all --root DIR --out report.json
    python source_citation_existence_check.py SVC-PC-37-3-0 --root DIR --out report.json
    python source_citation_existence_check.py --all --root DIR --out report.json --id-prefix SVC-PC-

Stdlib only for the runner; openpyxl / python-docx are pulled in via the
imports from answer_key_rubric_leak_check.py (same as content_audit_check.py).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Reuse the golden-file discovery and text-extraction helpers from
# answer_key_rubric_leak_check.py (the same import path content_audit_check.py
# uses). find_golden_files knows the SVC-PC (solution/files/) and EKW
# (solution/golden_outputs/) golden directories and the supported extensions.
from answer_key_rubric_leak_check import (
    find_golden_files,
    SUPPORTED_EXTENSIONS,
)  # noqa: E402

# Reuse the workspace-directory resolution and the pre-graded-heading cut
# from environment_input_check.py so this check's notion of "the environment"
# and "the instruction's input section" is byte-identical to the check that
# already calibrated both against the real corpus.
from environment_input_check import (  # noqa: E402
    detect_task_format,
    resolve_workspace_dir,
    prompt_scan_text,
    basename as _env_basename,
    FILENAME_EXTS as _ENV_FILENAME_EXTS,
)

# Reuse ekw_verifier_json for EKW graded-file names (used to skip a golden
# citing its own deliverable).
from ekw_verifier_json import load_ekw_files  # noqa: E402

# Windows console defaults to cp1252; force UTF-8 so non-cp1252 characters in
# real golden/instruction text never crash a batch run. Same line every other
# check in this folder carries.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# File extensions this check recognizes inside a golden cell or instruction
# phrase as "a cited file." Broader than environment_input_check.py's
# FILENAME_EXTS because a golden cell can cite any source type the task ships
# (a PDF contract, a PNG evidence scan, a ZIP export). Adds pdf, zip, and a
# few image formats on top of the shared list.
CITED_EXTS = _ENV_FILENAME_EXTS + r"|zip|png|jpg|jpeg|gif|eml|msg|html|htm|xls"

# A bare filename token in running text: word characters plus "&" and "-"
# ending in a recognized extension. Identical shape to
# environment_input_check.py's BARE_TOKEN_RE (so the two extractors can never
# disagree about what counts as a bare filename), just pointing at the
# broader CITED_EXTS list.
BARE_FILENAME_RE = re.compile(rf"\b[\w][\w&\-]*\.(?:{CITED_EXTS})\b", re.IGNORECASE)

# A path-shaped token WITHOUT internal spaces: a non-space run containing at
# least one path separator and ending in a recognized extension. Catches
# `path/to/file.xlsx` and `path\\to\\file.pdf` embedded in prose or a cell
# that does not sit alone as the whole cell value.
EMBEDDED_PATH_RE = re.compile(rf"\S*[\\/]\S*\.(?:{CITED_EXTS})", re.IGNORECASE)

# Whole-cell path detection uses this: a stripped cell value that contains a
# path separator and ENDS in a recognized extension is treated as a single
# path citation. Catches `Company Shared Drive\\Vendors\\SwiftShip_Express\\
# Contracts\\MSA_SwiftShip_2021.pdf` sitting alone in one cell, where the
# internal spaces would defeat BARE_FILENAME_RE and EMBEDDED_PATH_RE. The
# negative lookbehind/ahead stops at sentence-ending punctuation so a prose
# paragraph that happens to end in ".pdf" is not consumed whole.
WHOLE_CELL_PATH_END_RE = re.compile(rf"\.(?:{CITED_EXTS})$", re.IGNORECASE)
SENTENCE_BREAK_RE = re.compile(r"[.!?]\s|\n")

# A bare year-month filename like "2021-12.pdf" or "2021-12.xlsx": a range-end
# shorthand in golden cells ("Bank_Statement_2021-01.pdf .. 2021-12.pdf (all
# 12 present)"), not a real filename. Real audit files have descriptive
# prefixes (Bank_Statement_2021-12.pdf, AR_Aging_2021-12.xlsx). Calibrated
# against SVC-PC-14-1-0 G11/G24/G29/G46 (4 cells, each producing one bare
# year-month FP alongside a correctly-matched descriptive citation).
BARE_YEAR_MONTH_RE = re.compile(
    r"^\d{4}-\d{2}\.(?:" + CITED_EXTS + r"$)", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Sub-case B: category-name references in instruction.md
# ---------------------------------------------------------------------------

# Noun categories files are routinely named by in these task prompts. A
# category reference is a clause ending in one of these words and preceded by
# a proper noun. Hand-curated from the cov6 report's "rate cards" example
# plus the standard SVC-PC / EKW input-naming vocabulary. Deliberately a
# closed list: a word not here is not treated as a file-category signal, so
# the check does not fire on generic prose uses of "the" + noun.
CATEGORY_WORDS = {
    "card",
    "cards",
    "export",
    "exports",
    "report",
    "reports",
    "file",
    "files",
    "document",
    "documents",
    "sheet",
    "sheets",
    "ledger",
    "ledgers",
    "invoice",
    "invoices",
    "log",
    "logs",
    "register",
    "registers",
    "policy",
    "policies",
    "contract",
    "contracts",
    "manual",
    "manuals",
    "plan",
    "plans",
    "tracker",
    "trackers",
    "schedule",
    "schedules",
    "roster",
    "rosters",
}
CATEGORY_WORDS_RE = re.compile(
    r"\b(" + "|".join(sorted(CATEGORY_WORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Words that are capitalized at sentence start but are NOT proper nouns.
# Excluded from the proper-noun set so a clause's first capitalized word
# ("Use the Apex rate cards") does not pollute the proper-noun list with
# generic openers. Lowercased for comparison.
#
# NOTE: heading/section-label words (Required, Source, Assigned, System,
# etc.) are NOT in this set. This set BREAKS the backward walk, which would
# prevent a real proper noun earlier in the clause from being reached
# ("the Apex system files" would break at "system" and lose "apex"). Those
# words are in COMMON_CAPITALIZED_WORDS instead, which treats them as
# modifiers so the walk can continue past them.
SENTENCE_START_COMMON = {
    "the",
    "this",
    "that",
    "these",
    "those",
    "a",
    "an",
    "and",
    "but",
    "or",
    "for",
    "with",
    "from",
    "by",
    "in",
    "on",
    "at",
    "to",
    "of",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "should",
    "could",
    "may",
    "might",
    "must",
    "can",
    "shall",
    "if",
    "when",
    "while",
    "where",
    "why",
    "how",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "there",
    "here",
    "it",
    "its",
    "they",
    "them",
    "we",
    "you",
    "he",
    "she",
    "his",
    "her",
    "our",
    "your",
    "their",
    "produce",
    "build",
    "create",
    "deliver",
    "save",
    "use",
    "using",
    "work",
    "given",
    "based",
    "per",
    "via",
    "each",
    "every",
    "all",
    "any",
    "some",
    "such",
    "other",
    "same",
    "one",
    "two",
    "three",
    "four",
    "five",
    "first",
    "second",
    "third",
    "last",
    "next",
    "previous",
    "following",
    "return",
    "submit",
    "provide",
    "include",
    "exclude",
    "review",
    "reference",
    "named",
    "cite",
    "open",
    "see",
    "find",
    "load",
    "read",
}

# Month and day-of-week names plus their abbreviations. Excluded from the
# proper-noun set so "the March data book" does not treat "March" as a
# file-identifying proper noun. "March" is a date modifier, not a file name.
MONTH_DAY_NAMES = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
    "sun",
}

# Common English words that get capitalized (title-case at sentence/title
# start, or all-caps for emphasis) and are NOT file-identifying proper nouns.
# Unlike SENTENCE_START_COMMON (which BREAKS the backward walk), these are
# treated as modifiers: the walk continues past them so a real proper noun
# earlier in the clause ("the Apex system files") can still be reached. A
# capitalized token in this set is not added to the proper-noun list.
#
# Calibrated against the real 202-task SVC-PC corpus (round 31-32). Every
# word here produced a confirmed false-positive sub-case B finding in a real
# task instruction before it was added:
#   - design, task, critical, document: SVC-PC-92-0-0 "TASK DESIGN DOCUMENT"
#     / "FY2022 Critical Policy" (section header, not a file reference)
#   - final, version, required: SVC-PC-13-3-0 "Use only the named FINAL VERSION
#     source files" / "Required input files" (emphasis/sentence-start caps)
#   - items: SVC-PC-14-1-0 "Open Items log" (generic audit term)
#   - assess, prefer: SVC-PC-14-6-0 "Assess and log" / SVC-PC-88-0-0 "Prefer
#     register" (sentence-start verbs)
#   - control, gap: SVC-PC-14-6-0 "Control-Gap Register" (deliverable name,
#     not a source)
#   - both: SVC-PC-7-4-0 "Both files" (determiner/pronoun)
#   - define: SVC-PC-80-7-0 "Define document" (sentence-start verb)
#   - system: SVC-PC-92-0-0 "Do not use System Exports" (generic word)
#   - word: SVC-PC-93-0-0 "one Word document" (Microsoft Word, not a source)
#   - excel: SVC-PC-70-4-0 "Inventory financial cost/targets memo as an
#     Excel file" (Microsoft Excel, not a source)
#   - pbc: SVC-PC-14-1-0 "prepared-by-client (PBC) tracker" (generic audit
#     acronym, not a source name)
#   - hr: SVC-PC-14-6-0 "HR/ (headcount report)" (department abbreviation)
#   - fy: SVC-PC-92-0-0 "FY2022 Critical Policy" (fiscal-year date modifier,
#     same role as "March" in MONTH_DAY_NAMES; 6/65 findings in the 202-task
#     run)
#   - assigned: SVC-PC-82-{1,2,3,4}-0 "Assigned corpus files" (heading)
#   - source: SVC-PC-76-{2,3,4}-0 "Source files" (heading)
#   - extract: SVC-PC-25-{4,7}-0 "Extract policy" (heading verb)
#   - export, goldens: SVC-PC-82-1-0 "System Export files" / "Goldens,
#     rubrics, or tracker" (heading words)
#   - buy, proposal: SVC-PC-80-6-0 "Build-vs-Buy Proposal (document" (heading)
#   - change, governance, operating, adoption: SVC-PC-94-8-0 "AI Adoption
#     Governance and Operating Change Plan" (heading)
#   - topline, forecast, accuracy, deliverable, workpaper: SVC-PC-72-1-0
#     "Topline_Forecast_Accuracy_Workpaper.docx -- plan" (heading)
#   - materials, certifications: SVC-PC-55-1-0 "Materials & Certifications
#     Register" (heading)
#   - liquidity, preservation: SVC-PC-77-8-0 "Liquidity Preservation Plan"
#     (heading; this is a deliverable name, not a source)
#   - memo, workbook, chart: not found as proper nouns in the 202-task corpus
#     (the round-31 review's claim about these specific words was NOT
#     confirmed), but added preemptively as generic deliverable words that
#     could appear capitalized in other tasks.
# "workday" is NOT here: it is a real system name (Workday Inc.) and a
# legitimate source reference. Its false-positive case (SVC-PC-88-0-0: the
# instruction says "Workday export" but the file is named by content, not
# system name) is a structural limit disclosed in the Known limits section,
# not a word to exclude.
COMMON_CAPITALIZED_WORDS = {
    "design",
    "task",
    "final",
    "version",
    "required",
    "items",
    "assess",
    "control",
    "gap",
    "both",
    "define",
    "prefer",
    "critical",
    "document",
    "system",
    "word",
    "pbc",
    "hr",
    "fy",
    "memo",
    "workbook",
    "chart",
    "assigned",
    "source",
    "extract",
    "export",
    "goldens",
    "buy",
    "proposal",
    "change",
    "governance",
    "operating",
    "topline",
    "forecast",
    "accuracy",
    "deliverable",
    "workpaper",
    "materials",
    "certifications",
    "excel",
    "liquidity",
    "preservation",
    "adoption",
    # Round-31 second pass: remaining FPs from the 202-task re-run.
    "mdf",
    "okr",
    "swot",
    "sor",
    "annual",
    "engineering",
    "list",
    "request",
    "promo",
    "subject",
    "enterprise",
    "exposure",
    "insurable",
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _basename(text: str) -> str:
    """Reduce a cited path to its filename, whatever separator it was
    authored with. Mirrors environment_input_check.py's basename() so the two
    checks can never disagree about what the basename of a citation is."""
    return _env_basename(text)


def _collect_environment_basenames(env_dir: Path) -> set[str]:
    """Recursive lowercase basename set of every file under the environment
    directory. A file at any depth counts (some tasks stage inputs under a
    _corpus_subtree/ layer). Empty set if the directory does not exist."""
    names: set[str] = set()
    if not env_dir.is_dir():
        return names
    for _root, _dirs, filenames in os.walk(env_dir):
        for fn in filenames:
            names.add(fn.lower())
    return names


def _golden_own_basenames(
    golden_files: list[Path], task_dir: Path, fmt: str
) -> set[str]:
    """Lowercase basenames a golden citation should NOT be flagged for: the
    golden files' own names (a golden citing itself or a sibling golden) and,
    for EKW, every filename the verifier actually grades (the authoritative
    deliverable list, so a golden citing its own output by a name the verifier
    reads is not reported as a missing SOURCE). For SVC-PC the graded
    deliverable names come from the golden files themselves (the solution/ is
    the graded output), so golden_files' own basenames already cover it."""
    names = {p.name.lower() for p in golden_files}
    if fmt == "ekw":
        try:
            sources, _errs = load_ekw_files(task_dir)
        except Exception:
            sources = []
        for src in sources:
            for f in src.get("files", []):
                names.add(_env_basename(f).lower())
    return names


# ---------------------------------------------------------------------------
# Sub-case A: extract path citations from golden cell content
# ---------------------------------------------------------------------------


def _extract_path_citations(text: str) -> list[tuple[str, str, str]]:
    """Extract every file-path-shaped citation from a text chunk (a cell
    value, a paragraph, a table cell). Returns a list of
    (citation_text, basename, kind) where kind is "path" or "filename".

    Three extraction passes, in order, with later passes dropping any match
    nested inside an earlier pass's span (so a path like
    `a/b/MSA.pdf` is reported once as a path, not a second time as the bare
    filename `MSA.pdf`):

      1. Whole-chunk path: if the entire stripped chunk contains a path
         separator and ends in a recognized extension, treat the whole
         stripped chunk as one path citation. This is the only pass that
         allows spaces inside the path (a path sitting alone in a cell, like
         `Company Shared Drive\\Vendors\\...\\MSA_SwiftShip_2021.pdf`). A
         chunk with sentence-ending punctuation or a newline is left for the
         embedded passes, since a prose paragraph that happens to end in
         ".pdf" is not a single path.

      2. Embedded path without spaces: a non-space run containing a path
         separator and ending in a recognized extension (`path/to/file.xlsx`,
         `dir\\file.pdf`).

      3. Bare filename: a `word.ext` token with no separator, the same shape
         environment_input_check.py's BARE_TOKEN_RE extracts.
    """
    if not text or not text.strip():
        return []
    results: list[tuple[str, str, str]] = []
    covered: list[tuple[int, int]] = []

    stripped = text.strip()

    # Pass 1: whole-chunk path (allows internal spaces).
    if ("\\" in stripped or "/" in stripped) and WHOLE_CELL_PATH_END_RE.search(
        stripped
    ):
        if not SENTENCE_BREAK_RE.search(stripped):
            bn = _basename(stripped)
            # Require a real extension in the basename (defensive: a path
            # ending in a directory name with a dot would false-match).
            if (
                bn
                and "." in bn
                and bn.rsplit(".", 1)[1].lower() in {e for e in CITED_EXTS.split("|")}
            ):
                results.append((stripped, bn, "path"))
                covered.append((0, len(text)))
                return results

    # Pass 2: embedded path without spaces.
    for m in EMBEDDED_PATH_RE.finditer(text):
        raw = m.group(0)
        bn = _basename(raw)
        if (
            bn
            and "." in bn
            and bn.rsplit(".", 1)[1].lower() in {e for e in CITED_EXTS.split("|")}
        ):
            # Skip a lone separator run ("//" or "\\") that happens to be
            # followed by a .ext-looking token from surrounding text.
            if bn.replace(".", "").replace("/", "").replace("\\", "").strip("_-"):
                results.append((raw, bn, "path"))
                covered.append((m.start(), m.end()))

    # Pass 3: bare filename, dropping any nested inside a pass-1/2 span.
    for m in BARE_FILENAME_RE.finditer(text):
        if any(s <= m.start() and m.end() <= e for s, e in covered):
            continue
        # Version-number tail split (round 42, SVC-PC-80-7-0): a versioned
        # naming-convention EXAMPLE like
        # "..._v2.0_FINAL.docx" has a "." immediately before a digit (the
        # "0" of "v2.0"), which is a \b word boundary, so the regex matches
        # the tail "0_FINAL.docx" as if it were its own bare filename. No
        # real filename in this corpus is ever preceded by "<digit>." with
        # no separator; this shape only occurs when a decimal version
        # number got split mid-token. Confirmed real: the golden's section
        # 6.2 naming-convention example is
        # "Cirrus_Finance_OperationalCarbonEstimate_FY2021_v2.0_FINAL.docx",
        # and "0_FINAL.docx" is absent everywhere in the real 600-task
        # corpus (it was never a standalone citation).
        if (
            m.start() >= 2
            and text[m.start() - 1] == "."
            and text[m.start() - 2].isdigit()
        ):
            continue
        raw = m.group(0)
        bn = _basename(raw)
        if bn and "." in bn:
            results.append((raw, bn, "filename"))

    return results


def _iter_golden_text_chunks(golden_files: list[Path]):
    """Yield (file_path, location, text) for every text-bearing unit in every
    golden file. `location` is a human-readable coordinate so a finding names
    exactly where the citation lives (sheet + cell for xlsx, paragraph/table
    for docx, slide for pptx, line for flat text). Opens xlsx/docx/pptx
    programmatically (cell-level access), not via flat-text extraction, so a
    path embedded in a single spreadsheet cell is attributable to that cell.

    Never raises: an unparseable file yields an error string and is skipped
    (the caller records the error on the per-task result)."""
    import zipfile

    try:
        import openpyxl
    except ImportError:  # pragma: no cover
        openpyxl = None

    try:
        import docx as _python_docx

        have_docx = True
    except ImportError:  # pragma: no cover
        have_docx = False

    for gf in golden_files:
        suffix = gf.suffix.lower()
        rel = gf.name
        try:
            if suffix in (".txt", ".md", ".csv", ".json"):
                text = gf.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    yield gf, f"{rel}:line{i}", line
            elif suffix in (".xlsx", ".xlsm") and openpyxl is not None:
                wb = openpyxl.load_workbook(str(gf), data_only=True, read_only=True)
                for ws in wb.worksheets:
                    for row in ws.iter_rows():
                        for cell in row:
                            v = cell.value
                            if isinstance(v, str) and v.strip():
                                yield gf, f"{rel}!{ws.title}!{cell.coordinate}", v
                            elif isinstance(v, (int, float)):
                                yield gf, f"{rel}!{ws.title}!{cell.coordinate}", str(v)
                wb.close()
            elif suffix == ".docx":
                if have_docx:
                    document = _python_docx.Document(str(gf))
                    for i, p in enumerate(document.paragraphs, 1):
                        if p.text.strip():
                            yield gf, f"{rel}:para{i}", p.text
                    for ti, table in enumerate(document.tables):
                        for ri, row in enumerate(table.rows):
                            for ci, cell in enumerate(row.cells):
                                if cell.text.strip():
                                    yield gf, f"{rel}:table{ti}!r{ri}c{ci}", cell.text
                else:
                    # zipfile fallback: flat text, no cell attribution.
                    with zipfile.ZipFile(gf) as zf:
                        if "word/document.xml" in zf.namelist():
                            xml = zf.read("word/document.xml").decode(
                                "utf-8", errors="replace"
                            )
                            text = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
                            yield gf, f"{rel}:text", text
            elif suffix == ".pptx":
                with zipfile.ZipFile(gf) as zf:
                    for name in sorted(zf.namelist()):
                        if name.startswith("ppt/slides/slide") and name.endswith(
                            ".xml"
                        ):
                            xml = zf.read(name).decode("utf-8", errors="replace")
                            text = " ".join(re.findall(r"<a:t[^>]*>([^<]*)</a:t>", xml))
                            if text.strip():
                                yield gf, f"{rel}:{name}", text
        except Exception:
            # Unreadable file: skip silently; the caller's n_golden_files
            # count already records the file was present, and a read error
            # on one golden should not lose every other golden's findings.
            continue


# Range-shorthand basename: "Q1-Q4_Channel_Attribution.xlsx" stands for the
# four separate files "Q1_Channel_Attribution.xlsx" .. "Q4_...". Confirmed
# recurring, not a one-off (round 42: SVC-PC-13-3-0's
# Q1-Q4_Channel_Attribution.xlsx and SVC-PC-42-1-0's
# Q1-Q4_Trial_Balance.xlsx, same shape, different suffix). Scoped to the one
# range shape actually observed in the real corpus (quarters 1-4); a
# different range word (e.g. a half-year "H1-H2_") is not covered because it
# has not been confirmed to occur.
QUARTER_RANGE_RE = re.compile(r"^Q([1-4])-Q([1-4])_(.+)$", re.IGNORECASE)


def _quarter_range_satisfied(bn: str, env_basenames: set[str]) -> bool:
    """True if `bn` is a Q<start>-Q<end>_ range-shorthand basename and EVERY
    individual per-quarter file it stands for is present in
    `env_basenames`. Implements the check's own disclosed Known Limit #3
    ("range shorthand... not fixable without understanding range
    semantics") for the one range shape confirmed recurring in the real
    corpus. Deliberately conservative: ALL quarters in the range must be
    present, or the citation is left flagged -- a partial range (e.g. only
    Q1-Q3 shipped out of a cited Q1-Q4) is a genuine gap, not shorthand
    noise, so it must not be silently suppressed."""
    m = QUARTER_RANGE_RE.match(bn)
    if not m:
        return False
    start = int(m.group(1))
    end = int(m.group(2))
    suffix = m.group(3)
    if start >= end:
        return False
    return all(f"q{n}_{suffix}".lower() in env_basenames for n in range(start, end + 1))


def analyze_subcase_a(
    task_dir: Path,
    fmt: str,
    golden_files: list[Path],
    env_basenames: set[str],
    skip_basenames: set[str],
    env_dir: Path,
) -> list[dict]:
    """Sub-case A: scan golden cell content for file-path-shaped citations
    and flag any whose basename is not present in the environment. Returns a
    list of finding dicts (empty if clean).

    Six extraction-artifact filters (calibrated against the real 202-task
    SVC-PC corpus with full environment reconstruction, round 31-32) suppress
    false positives from golden cells that use shorthand conventions rather
    than literal filenames:
      1. Basename contains "#": a wildcard/placeholder (Q#_Board_Minutes.docx
         means Q1/Q2/Q3/Q4_Board_Minutes.docx). (SVC-PC-14-1-0, 6 findings.)
      2. Basename starts with "(" or whitespace: a parenthetical list of
         filenames mangled into one basename. (SVC-PC-14-1-0 G6, 1 finding.)
      3. Bare year-month basename (2021-12.pdf): a range-end shorthand.
         (SVC-PC-14-1-0, 10 findings.)
      4. Basename starts with "_": a suffix fragment (_v2.docx,
         _DOCX_SOURCE.docx) split from a longer filename. (SVC-PC-14-1-0,
         2 findings.)
      5. Digit-only stem < 4 chars (12.pdf, 03.pdf): date/number fragments.
         (SVC-PC-14-1-0, 4 findings.)
      6. Basename contains ";": multiple filenames joined in one cell.
         (SVC-PC-14-1-0, 2 findings.)
      7. Basename contains "golden" AND the task has 2+ golden files: a
         companion-deliverable cross-reference by internal/pre-rename name
         (round 42, SVC-PC-7-4-0, 3 findings -- see _golden_own_basenames'
         docstring for why skip_basenames alone can't catch this).
      8. Basename matches the Qn-Qm_ range-shorthand shape (see
         _quarter_range_satisfied below) AND every individual per-quarter
         file it stands for is present in the environment: not a filter in
         the artifact-suppression sense (it still checks the environment),
         applied at the final match point instead of here (round 42,
         SVC-PC-13-3-0 / SVC-PC-42-1-0, 4 findings)."""
    findings: list[dict] = []
    if not golden_files:
        return findings
    env_rel = f"environment/{env_dir.name}/"
    seen_citations: set[tuple[str, str]] = set()
    for gf, location, text in _iter_golden_text_chunks(golden_files):
        for citation, bn, kind in _extract_path_citations(text):
            key = (bn.lower(), location)
            if key in seen_citations:
                continue
            # Skip the golden citing its own deliverable / a sibling golden /
            # a verifier-graded file (a golden naming its own output is not a
            # missing SOURCE).
            if bn.lower() in skip_basenames:
                seen_citations.add(key)
                continue
            # Extraction-artifact filters (see docstring above).
            bn_stripped = bn.strip()
            if "#" in bn:
                seen_citations.add(key)
                continue
            if bn_stripped.startswith("(") or bn != bn_stripped:
                seen_citations.add(key)
                continue
            if BARE_YEAR_MONTH_RE.match(bn):
                seen_citations.add(key)
                continue
            # Suffix fragments: basenames starting with "_" (e.g. _v2.docx,
            # _DOCX_SOURCE.docx) are tail-ends of longer filenames that the
            # embedded-path regex split at a separator. Real filenames in
            # these tasks never start with "_". (SVC-PC-14-1-0, 2 findings.)
            if bn_stripped.startswith("_"):
                seen_citations.add(key)
                continue
            # Very short digit-only stems: "12.pdf", "03.pdf" are date or
            # number fragments, not real filenames. Real files always have a
            # descriptive prefix. (SVC-PC-14-1-0, 4 findings.)
            stem = bn_stripped.rsplit(".", 1)[0] if "." in bn_stripped else bn_stripped
            if stem.isdigit() and len(stem) < 4:
                seen_citations.add(key)
                continue
            # Multi-file cells: basenames containing ";" are multiple
            # filenames joined in one cell value, not a single citation.
            # (SVC-PC-14-1-0, 2 findings.)
            if ";" in bn:
                seen_citations.add(key)
                continue
            # Companion-deliverable reference by internal/pre-rename name
            # (round 42, SVC-PC-7-4-0): a multi-golden task (2+ golden
            # files, a two-workbook deliverable) where one golden's text
            # cross-references the OTHER golden by an internal codename
            # containing "golden" (e.g. "L2-04_Task_7_Golden.xlsx",
            # "Cirrus_Sleep_FY2022_Ops_Model_GOLDEN.xlsx") rather than its
            # shipped solution/ basename. `skip_basenames`
            # (_golden_own_basenames) only knows the golden files' own
            # SHIPPED names, so it can't recognize this. No real
            # environment input file anywhere in the 600-task corpus is
            # ever named with "golden" in it (that word is reserved for
            # internal grading artifacts); confirmed absent everywhere as
            # a real file for both round-42 examples. Gated on 2+ golden
            # files so a single-golden task's "golden"-substring citation,
            # if one ever appears, is still flagged rather than silently
            # suppressed.
            if "golden" in bn.lower() and len(golden_files) >= 2:
                seen_citations.add(key)
                continue
            seen_citations.add(key)
            if bn.lower() in env_basenames:
                continue
            if _quarter_range_satisfied(bn, env_basenames):
                continue
            findings.append(
                {
                    "kind": "golden_cites_absent_file",
                    "sub_case": "A",
                    "severity": "warn",
                    "citation": citation[:500],
                    "basename": bn,
                    "location": location,
                    "environment_checked": env_rel,
                    "evidence": (
                        f"no file matching '{bn}' under {env_rel} (cited in "
                        f"golden {location})"
                    ),
                }
            )
    return findings


# ---------------------------------------------------------------------------
# Sub-case B: category-name references in instruction.md
# ---------------------------------------------------------------------------


def _proper_nouns_in_clause(text: str, cat_start: int) -> list[str]:
    """Proper-noun tokens (lowercased) that form a file-reference noun phrase
    ending at the category word at char offset `cat_start`.

    Walks backwards from the category word through the short token window
    immediately before it, collecting proper nouns connected by
    and/or/&/,//+, allowing at most one lowercase modifier word (e.g. "rate"
    in "rate cards"). The walk stops at a determiner (the/a/an), a common
    word (verb/preposition/sentence-opener), a month/day name, a sentence
    terminator, or a second lowercase token. This is the adjacency
    requirement: a file reference reads "the Apex and SwiftShip rate cards"
    (proper nouns adjacent to the category head), not "Acme Corp filed the
    report" (a verb and determiner sit between the proper noun and the
    category word, so the walk breaks before reaching a proper noun).

    A token is a proper-noun candidate if it starts with an uppercase letter
    (or is an all-caps acronym of length >= 2), is not a month/day name, and
    is not a common word. Hyphenated tokens are split on the hyphen so an
    embedded all-caps segment ("recent-IPO") yields its "IPO" part. A
    capitalized token in COMMON_CAPITALIZED_WORDS (Design, System, FY, PBC,
    etc.) is treated as a modifier, not a proper noun, so the walk can
    continue past it to a real proper noun earlier in the clause.
    """
    before = text[:cat_start]
    # Bound the window at the nearest preceding sentence terminator so a
    # proper noun from an unrelated earlier sentence cannot leak in.
    breaks = list(re.finditer(r"[.!?]\s+|\n\s*\n|^", before))
    clause_start = breaks[-1].end() if breaks else 0
    window = text[clause_start:cat_start]
    # Split into alpha tokens (hyphens split, so "recent-IPO" -> "recent","IPO")
    # and connective tokens.
    tokens = re.findall(r"[A-Za-z]+|[&/,+]", window)
    proper: list[str] = []
    modifier_used = False
    for tok in reversed(tokens):
        if tok in ("the", "a", "an"):
            break
        if tok in ("and", "or", "&", "/", "+", ","):
            continue
        low = tok.lower()
        if low in MONTH_DAY_NAMES:
            break
        if low in SENTENCE_START_COMMON:
            break
        is_upper_start = tok[0].isupper()
        is_acronym = tok.isupper() and len(tok) >= 2
        if (is_upper_start or is_acronym) and len(tok) >= 2:
            if low in COMMON_CAPITALIZED_WORDS:
                # A capitalized common word (Design, System, FY, PBC) is not
                # a file-identifying proper noun. Treat it as a modifier, not
                # a break, so a real proper noun earlier in the clause ("the
                # Apex system files") can still be reached. A second such
                # word ends the chain (two generic capitalized words in a
                # row is a title/header, not a file reference).
                if not modifier_used:
                    modifier_used = True
                    continue
                break
            proper.append(low)
            continue
        # A lowercase non-common token: allow at most one as a modifier
        # (the "rate" in "rate cards", the "data" in "data book"). A second
        # lowercase token ends the chain, since two lowercase words between
        # the category head and any proper noun read as prose, not a file
        # reference.
        if not modifier_used:
            modifier_used = True
            continue
        break
    return list(reversed(proper))


def _extract_category_references(text: str) -> list[tuple[str, list[str], str]]:
    """Find category references in text. Returns a list of
    (phrase_text, proper_nouns, category_word). A category reference is a
    category word preceded by at least one proper noun in the same clause;
    references with no proper-noun signal are dropped (they have nothing to
    cross-reference against the environment)."""
    refs: list[tuple[str, list[str], str]] = []
    seen_ends: set[int] = set()
    for m in CATEGORY_WORDS_RE.finditer(text):
        cat_word = m.group(1).lower()
        proper = _proper_nouns_in_clause(text, m.start())
        if not proper:
            continue
        # De-duplicate overlapping category matches that resolve to the same
        # clause + proper-noun set (e.g. "rate cards" matches both "card" and
        # "cards"); keep the longest (the plural form, usually).
        if m.end() in seen_ends:
            continue
        phrase_start = max(0, m.start() - 100)
        phrase = text[phrase_start : m.end()].strip()
        refs.append((phrase, proper, cat_word))
        seen_ends.add(m.end())
    return refs


def analyze_subcase_b(
    instruction_text: str,
    fmt: str,
    env_basenames: set[str],
    env_dir: Path,
) -> list[dict]:
    """Sub-case B: scan instruction.md's input section for category-name
    references and flag any whose proper-noun tokens do not appear in any
    environment basename. Returns a list of finding dicts (empty if clean).

    Coverage boundary (disclosed, not silently accepted): this catches the
    "no environment file contains the proper noun at all" sub-case. It does
    NOT catch the "a file with the proper noun exists but is the wrong file
    type" sub-case (cov6: SwiftShip_Evaluation.docx exists but is an
    evaluation, not a rate card). Distinguishing those needs semantic
    judgment, which is an LLM task and is explicitly deferred here. The
    heuristic is warn-only."""
    findings: list[dict] = []
    if not instruction_text or not env_basenames:
        return findings
    scan_text = prompt_scan_text(instruction_text, fmt)
    env_rel = f"environment/{env_dir.name}/"
    seen_keys: set[tuple[str, str]] = set()
    for phrase, proper, cat_word in _extract_category_references(scan_text):
        # A category reference is a plausible match if ANY environment
        # basename contains ANY proper-noun token (case-insensitive
        # substring). If every proper noun is absent from every basename,
        # flag it.
        matched = any(any(pn in bn for bn in env_basenames) for pn in proper)
        if matched:
            continue
        key = (phrase, ",".join(sorted(proper)))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        findings.append(
            {
                "kind": "instruction_names_absent_category",
                "sub_case": "B",
                "severity": "warn",
                "citation": phrase[:500],
                "proper_nouns": sorted(proper),
                "category_word": cat_word,
                "environment_checked": env_rel,
                "evidence": (
                    f"no environment basename contains any of "
                    f"{sorted(proper)}; instruction names a file by "
                    f"category '{cat_word}' with no plausibly matching "
                    f"file under {env_rel}"
                ),
            }
        )
    return findings


# ---------------------------------------------------------------------------
# Per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir: Path) -> dict:
    """Run both sub-cases for one task. Returns the per-task result dict.
    Never raises: a missing golden, missing environment, or unreadable file
    produces a skip/error/empty finding rather than crashing the batch."""
    task_id = task_dir.name
    fmt = detect_task_format(task_dir)
    env_dir, _fmt = resolve_workspace_dir(task_dir)
    golden_files = find_golden_files(task_dir, fmt if fmt != "none" else "svc_pc")
    if fmt == "none" and golden_files:
        # detect_task_format defaulted to svc_pc for the golden path; keep
        # the fmt the golden discovery actually used for reporting.
        fmt = _fmt

    result = {
        "task_id": task_id,
        "status": "pass",
        "task_format": fmt,
        "n_golden_files": len(golden_files),
        "environment_exists": env_dir.is_dir(),
        "findings": [],
        "n_findings": 0,
        "errors": [],
    }

    if not env_dir.is_dir():
        result["status"] = "skip"
        result["errors"].append(
            f"environment directory not found: {env_dir} -- nothing to "
            f"cross-reference citations against"
        )
        return result

    env_basenames = _collect_environment_basenames(env_dir)
    skip_basenames = _golden_own_basenames(golden_files, task_dir, fmt)
    findings: list[dict] = []

    # Sub-case A: golden cell content citations.
    if golden_files:
        findings.extend(
            analyze_subcase_a(
                task_dir, fmt, golden_files, env_basenames, skip_basenames, env_dir
            )
        )
    else:
        # No golden files: not an error (some task packages ship only
        # instruction + judge.toml), but sub-case A has nothing to scan.
        result["errors"].append(
            "no golden files found under solution/ -- sub-case A skipped"
        )

    # Sub-case B: instruction.md category references.
    instr_path = task_dir / "instruction.md"
    if instr_path.is_file():
        try:
            instruction_text = instr_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            result["errors"].append(f"could not read instruction.md: {exc}")
            instruction_text = ""
        if instruction_text:
            findings.extend(
                analyze_subcase_b(instruction_text, fmt, env_basenames, env_dir)
            )
    else:
        result["errors"].append("no instruction.md found -- sub-case B skipped")

    result["findings"] = findings
    result["n_findings"] = len(findings)
    result["status"] = "warn" if findings else "pass"
    return result


# ---------------------------------------------------------------------------
# Batch entry point (programmatic, used by the orchestrators)
# ---------------------------------------------------------------------------


def find_task_dirs(
    root: Path, task_ids: list[str] | None = None, id_prefix: str = ""
) -> list[Path]:
    if task_ids:
        dirs: list[Path] = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def run(
    root: Path,
    task_ids: list[str] | None = None,
    id_prefix: str = "",
    out_dir: Path | None = None,
) -> dict:
    """Programmatic entry point (the orchestrators use this). Returns the
    report dict with a 'results' list of per-task dicts."""
    dirs = find_task_dirs(root, task_ids, id_prefix)
    t0 = time.time()

    def _safe_analyze(d: Path) -> dict:
        try:
            return analyze_task(d)
        except Exception as exc:  # noqa: BLE001 - broad on purpose
            return {
                "task_id": d.name,
                "status": "error",
                "task_format": "none",
                "n_golden_files": 0,
                "environment_exists": False,
                "findings": [],
                "n_findings": 0,
                "errors": [f"unexpected exception in analyze_task: {exc!r}"],
            }

    results = [_safe_analyze(d) for d in dirs]
    for r in results:
        s = r["status"]
        tid = r["task_id"]
        n = r["n_findings"]
        if s == "error":
            err = (r.get("errors") or [""])[0][:120]
            print(f"  ERROR {tid:<18} {err}", file=sys.stderr)
        elif s == "skip":
            err = (r.get("errors") or [""])[0][:120]
            print(f"  SKIP  {tid:<18} {err}", file=sys.stderr)
        elif s == "warn":
            print(f"  WARN  {tid:<18} {n} finding(s)", file=sys.stderr)
        else:
            print(f"  OK    {tid:<18} clean", file=sys.stderr)

    n_pass = sum(r["status"] == "pass" for r in results)
    n_warn = sum(r["status"] == "warn" for r in results)
    n_skip = sum(r["status"] == "skip" for r in results)
    n_error = sum(r["status"] == "error" for r in results)
    report = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": str(root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_warn": n_warn,
        "n_skip": n_skip,
        "n_error": n_error,
        "results": results,
        "seconds": round(time.time() - t0, 1),
    }

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "source_citation_existence.json"
        out_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("task_ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument(
        "--root",
        required=True,
        help="task package root, one task directory per task",
    )
    ap.add_argument("--out", help="write the full result set here as JSON")
    ap.add_argument("--id-prefix", default="")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2
    if not args.all and not args.task_ids:
        sys.stderr.write("give task ids or --all\n")
        return 2

    task_ids = args.task_ids or None
    report = run(
        root,
        task_ids,
        args.id_prefix,
        out_dir=Path(args.out).parent if args.out else None,
    )

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {args.out}")

    print(
        f"\n{report['n_tasks']} tasks in {report['seconds']}s: "
        f"{report['n_pass']} pass, {report['n_warn']} warn, "
        f"{report['n_skip']} skip, {report['n_error']} error",
        file=sys.stderr,
    )
    return 1 if report["n_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
