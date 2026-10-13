#!/usr/bin/env python3
"""rubric_xlsx_to_verifier.py -- convert a loose "Grading Rubric" xlsx into
this project's verifier.json format (consumed by assemble_task.py's
--verifier flag and, downstream, by to_rewardkit.py).

Every prior corpus this repo has processed arrived with verifier.json
already written by the task author. The SVC-PC batch is the first where the
rubric only exists as a loose Excel file -- this is the missing bridge.

Usage:
    python3 rubric_xlsx_to_verifier.py <task_dir> [--out verifier.json]

<task_dir> is a directory containing (recursively) exactly one Grading
Rubric xlsx and exactly one Golden Solution deliverable file -- the shape
produced by the SVC-PC download/organize step
(pipeline/data/svc_pc_qc/00_fetched/<TaskID>/). This project only supports
single-file delivery: a task that resolves to more than one deliverable
file raises ConversionError rather than guessing which one is "the"
deliverable -- route those to manual review instead.

See specs/... (n/a) -- design rationale lives in the plan that produced this
script; the short version: rubric row schema is consistent across five
observed sheet-layout variants (header-name synonyms only), so this parses
by keyword-matching header text rather than assuming a fixed layout.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import docx
import openpyxl

MODEL_SKIP_RE = re.compile(r"gpt|gemini|claude|chatgpt|codex", re.IGNORECASE)
RUBRIC_NAME_RE = re.compile(r"rubric", re.IGNORECASE)
SKIP_SHEET_RE = re.compile(
    r"category weight|source key|rubric score analysis|atomicity notes|ground truth",
    re.IGNORECASE,
)
SHEET_PREFERRED_RE = re.compile(r"rubric", re.IGNORECASE)

HEADER_KEYWORDS = [
    "criterion",
    "category",
    "description",
    "point",
    "must-pass",
    "must pass",
    "expected",
]

# logical field -> substrings that identify its column header (checked in order, first match wins)
FIELD_HEADER_SUBSTRINGS = {
    "criterion_id": ["criterion id"],
    "category": ["category"],
    # "criterion type" is a 7th observed sheet-layout variant (SVC-PC-1-3-0
    # family, confirmed 2026-09-02) that uses "Criterion Type" for the same
    # structural/objective/judgment tier a "Tier" column carries elsewhere --
    # its values (Structural/Objective/Judgment) are exactly tier values, not
    # criterion text. This MUST be listed (and therefore matched) before the
    # "description" field's bare "criterion" substring below, or "Criterion
    # Type" gets misclaimed as the description column (confirmed real
    # incident: task SVC-PC-1-3-0 shipped with every criterion's description
    # reduced to just "Structural"/"Objective"/"Judgment" and expected_value
    # silently blank, because "Requirement" and "Acceptance Standard" --
    # this variant's real description/expected-value columns -- matched no
    # field at all and were dropped).
    "tier": ["tier", "criterion type"],
    # "criterion" as a bare column header (not "criterion id"/"criterion type")
    # is a 6th observed sheet-layout variant (task_svc-pc-9-* family) that uses
    # "Criterion" for the descriptive text itself rather than a "Description"
    # column -- confirmed by inspecting the actual header row (['ID',
    # 'Category', 'Tier', 'Criterion', 'Expected value + source file',
    # 'Points', 'Must-pass?']). "Requirement" is the SVC-PC-1-3-0 family's own
    # name for this same descriptive-text column. "criterion id" and
    # "criterion type" are claimed first by the fields above, so the bare
    # "criterion" substring only ever fires on an actual bare "Criterion"
    # header.
    "description": ["description", "requirement", "criterion"],
    "expected_value": ["expected value", "expected", "acceptance standard"],
    "points": ["pts", "points"],
    "must_pass": ["must-pass", "must pass"],
    "src_refs": ["src #", "src#", "response criteria number", "source"],
}
# fields matched by exact (post-strip) header text rather than substring, since the
# substring is too short/generic to safely match anywhere in a longer header (e.g. "id").
FIELD_HEADER_EXACT = {
    "criterion_id": ["id"],
}

# Claire's Rubric Response Criteria Form (companion workbook to the Grading
# Rubric -- same 15 IDs, one row of interpretation guidance per row of the
# rubric) reuses find_header_row's >=3-keyword detection ("criterion",
# "points", "must-pass" all appear in its header row too) with this field map
# instead of FIELD_HEADER_SUBSTRINGS. See parse_response_criteria().
RESPONSE_CRITERIA_NAME_RE = re.compile(r"response.?criteria", re.IGNORECASE)
RESPONSE_CRITERIA_FIELDS = {
    "lens": ["lens"],
    "satisfactory_response": ["satisfactory response", "satisfactory evidence"],
    "tolerance_rule": ["tolerance or review rule", "tolerance"],
    "pass_with_open_items": ["pass with open items"],
    "blocked_if": ["blocked if"],
    "points": ["points"],
    "must_pass": ["must-pass", "must pass"],
}
RESPONSE_CRITERIA_FIELDS_EXACT = {
    "criterion_id": ["id"],
}

GOLDEN_HINT_RE = re.compile(r"golden", re.IGNORECASE)


class ConversionError(Exception):
    pass


def pick_unique_file(
    task_dir: Path,
    candidates: list[Path],
    kind: str,
    tiebreak_name_re: "re.Pattern | None" = None,
) -> Path:
    """Disambiguate a list of candidate files down to one, for cases where a
    task has a stray duplicate copy (e.g. nested under a Golden Solution/
    folder alongside the real deliverable). Same tie-break order for every
    file kind this module looks up (rubric, prompt): prefer root-level, then
    an optional kind-specific name hint, then shallowest path; otherwise
    refuse to guess."""
    if not candidates:
        raise ConversionError(f"no {kind} file found under {task_dir}")
    if len(candidates) == 1:
        return candidates[0]

    root_level = [p for p in candidates if p.parent == task_dir]
    if len(root_level) == 1:
        return root_level[0]
    pool = root_level or candidates

    if tiebreak_name_re is not None:
        hinted = [p for p in pool if tiebreak_name_re.search(p.name)]
        if len(hinted) == 1:
            return hinted[0]
        pool = hinted or pool

    shallowest = sorted(pool, key=lambda p: len(p.relative_to(task_dir).parts))
    if len(shallowest) == 1 or len(shallowest[0].relative_to(task_dir).parts) < len(
        shallowest[1].relative_to(task_dir).parts
    ):
        return shallowest[0]

    raise ConversionError(
        f"ambiguous {kind} file for {task_dir}: {[str(p.relative_to(task_dir)) for p in candidates]}"
    )


def find_rubric_file(task_dir: Path) -> Path:
    candidates = [
        p
        for p in task_dir.rglob("*.xlsx")
        if RUBRIC_NAME_RE.search(p.name)
        and not any(
            MODEL_SKIP_RE.search(part) for part in p.relative_to(task_dir).parts[:-1]
        )
    ]
    return pick_unique_file(
        task_dir, candidates, "rubric", re.compile("grading_rubric", re.IGNORECASE)
    )


def find_response_criteria_file(task_dir: Path) -> "Path | None":
    """Claire's Rubric Response Criteria xlsx, if the task has one -- OPTIONAL,
    unlike find_rubric_file/find_prompt_file: every pre-Claire-template task
    converted so far has no such file, and that must stay a clean no-op, not
    a ConversionError. Returns None on zero candidates instead of routing
    through pick_unique_file (which treats zero candidates as an error)."""
    candidates = [
        p
        for p in task_dir.rglob("*.xlsx")
        if RESPONSE_CRITERIA_NAME_RE.search(p.name)
        and not any(
            MODEL_SKIP_RE.search(part) for part in p.relative_to(task_dir).parts[:-1]
        )
    ]
    if not candidates:
        return None
    return pick_unique_file(
        task_dir,
        candidates,
        "response criteria",
        re.compile("response_criteria", re.IGNORECASE),
    )


PROMPT_NAME_RE = re.compile(r"prompt", re.IGNORECASE)


def find_prompt_file(task_dir: Path) -> Path:
    candidates = [
        p
        for p in task_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in {".docx", ".md", ".txt"}
        and PROMPT_NAME_RE.search(p.name)
        and not any(
            MODEL_SKIP_RE.search(part) for part in p.relative_to(task_dir).parts[:-1]
        )
    ]
    return pick_unique_file(task_dir, candidates, "prompt")


def extract_prompt_text(prompt_path: Path) -> str:
    if prompt_path.suffix.lower() == ".docx":
        d = docx.Document(str(prompt_path))
        return "\n".join(p.text for p in d.paragraphs)
    return prompt_path.read_text(encoding="utf-8", errors="replace")


def find_criteria_sheet(
    wb: openpyxl.Workbook,
) -> "openpyxl.worksheet.worksheet.Worksheet":
    candidates = [name for name in wb.sheetnames if not SKIP_SHEET_RE.search(name)]
    if not candidates:
        raise ConversionError(
            f"no candidate sheet (all sheets matched the skip pattern): {wb.sheetnames}"
        )
    preferred = [name for name in candidates if SHEET_PREFERRED_RE.search(name)]
    if preferred:
        return wb[preferred[0]]
    if len(candidates) == 1:
        return wb[candidates[0]]
    # Multiple unlabeled candidates and none say "rubric" -- pick the one with the most rows.
    return max((wb[name] for name in candidates), key=lambda ws: ws.max_row)


def find_header_row(
    ws,
    field_substrings: dict[str, list[str]] = FIELD_HEADER_SUBSTRINGS,
    field_exact: dict[str, list[str]] = FIELD_HEADER_EXACT,
) -> tuple[int, dict[int, str]]:
    # Some workbooks stack a "Category Weights" summary block above the real
    # per-criterion table in the SAME sheet (SVC-PC-13-*) -- the real header
    # can land well past row 5, so scan generously rather than assume it's near
    # the top.
    #
    # field_substrings/field_exact default to the Grading Rubric's own field
    # map but are swappable -- the Rubric Response Criteria Form (Claire's
    # template) uses the same header-row-detection heuristic (HEADER_KEYWORDS
    # below still hits >=3 on its header row: "criterion", "points",
    # "must-pass") over a DIFFERENT column set ("Satisfactory response and
    # check", "BLOCKED if", ...), so parse_response_criteria() reuses this
    # function with RESPONSE_CRITERIA_FIELDS instead of duplicating the scan.
    for row_idx in range(1, min(30, ws.max_row + 1)):
        cells = [
            str(c.value).strip().lower() if c.value is not None else ""
            for c in ws[row_idx]
        ]
        # Count DISTINCT cells that carry a header keyword, not keyword
        # occurrences anywhere in the row: a single wordy subtitle cell like
        # "Maximum 100 points - 6 must-pass criteria ..." packs three keywords
        # into one merged cell and used to be mistaken for the header row
        # (SVC-PC-1-4-0, 2026-08-27). A real header row spreads keywords
        # across columns, so require three keyword-bearing cells.
        hits = sum(
            1 for cell in cells if cell and any(kw in cell for kw in HEADER_KEYWORDS)
        )
        if hits >= 3:
            col_map = {}
            for col_idx, text in enumerate(cells, start=1):
                if not text:
                    continue
                for field, substrings in field_substrings.items():
                    if field in col_map.values():
                        continue
                    if any(sub in text for sub in substrings):
                        col_map[col_idx] = field
                        break
                else:
                    for field, exacts in field_exact.items():
                        if field in col_map.values():
                            continue
                        if text in exacts:
                            col_map[col_idx] = field
                            break
            return row_idx, col_map
    raise ConversionError(f"no header row found in first 30 rows of sheet '{ws.title}'")


def parse_rows(ws, header_row: int, col_map: dict[int, str]) -> list[dict]:
    rows = []
    for row in ws.iter_rows(min_row=header_row + 1):
        values = {col_map[c.column]: c.value for c in row if c.column in col_map}
        if not any(v not in (None, "") for v in values.values()):
            continue
        criterion_id = str(values.get("criterion_id") or "").strip()
        description = str(values.get("description") or "").strip()
        if not criterion_id or not description:
            continue
        raw_points = values.get("points")
        try:
            points = float(raw_points)
        except (TypeError, ValueError):
            print(
                f"  WARN: skipping row {criterion_id!r} -- unparseable points {raw_points!r}",
                file=sys.stderr,
            )
            continue
        must_pass = str(values.get("must_pass") or "").strip().lower().startswith("y")
        # `... or ""` (used for every other field above) silently drops a
        # legitimate expected value of literal 0 -- Python treats 0 as falsy,
        # so `0 or ""` evaluates to "" -- confirmed real incident: SVC-PC-5-5-0
        # criterion E05 ("Insolvency ($0) buffer about $0") and SVC-PC-5-4-0
        # criterion Q17 ("P(insolvency, trough<0) reported about 0%.") both
        # have an authored expected_value of exactly 0 that this pattern threw
        # away. Use an explicit None-check for this field instead.
        raw_expected = values.get("expected_value")
        expected_value = "" if raw_expected is None else str(raw_expected).strip()
        rows.append(
            {
                "criterion_id": criterion_id,
                "category": str(values.get("category") or "").strip(),
                "tier": str(values.get("tier") or "").strip(),
                "description": description,
                "expected_value": expected_value,
                "points": points,
                "must_pass": must_pass,
                # Filled in by convert() from the Read Me's Expected Value Setup
                # table when present -- see parse_read_me(). None means either
                # there's no Read Me tab, or this criterion has no expected-value
                # row (both are normal, not gaps).
                "claim_status": None,
            }
        )
    return rows


def parse_response_criteria(path: Path) -> dict[str, dict]:
    """Claire's Rubric Response Criteria workbook -> {criterion_id: row dict},
    keyed the same way the Grading Rubric's own rows are keyed, so
    build_verifier_json can merge one into the other by ID -- this workbook
    explains what SATISFYING each Grading Rubric row means (a "Satisfactory
    response and check" description, a tolerance/review rule, a PASS WITH
    OPEN ITEMS allowance, and a BLOCKED-if condition), it doesn't carry its
    own point totals that matter for scoring (Points/Must-pass here duplicate
    the Grading Rubric's own columns; kept for reference, not reused as the
    weight source)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = find_criteria_sheet(wb)
    header_row, col_map = find_header_row(
        ws, RESPONSE_CRITERIA_FIELDS, RESPONSE_CRITERIA_FIELDS_EXACT
    )
    if "criterion_id" not in col_map.values():
        raise ConversionError(
            f"Response Criteria header row {header_row} in {ws.title!r} has no ID column"
        )
    out: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=header_row + 1):
        values = {col_map[c.column]: c.value for c in row if c.column in col_map}
        criterion_id = str(values.get("criterion_id") or "").strip()
        if not criterion_id:
            continue
        out[criterion_id] = {
            field: str(value).strip()
            for field, value in values.items()
            if field != "criterion_id" and value not in (None, "")
        }
    return out


DELIVERABLE_EXTS = {".docx", ".xlsx", ".xlsm", ".pptx", ".pdf", ".md", ".txt"}
GOLDEN_CONTAINER_RE = re.compile(
    r"^golden([ _](solution|response|deliverables?))?$", re.IGNORECASE
)
LEAF_SUBTASK_RE = re.compile(r"^L1-\d+-\d+", re.IGNORECASE)
NON_DELIVERABLE_NAME_RE = re.compile(
    r"rubric|prompt|response.?criteria|criteria", re.IGNORECASE
)


def find_deliverable_files(task_dir: Path) -> list[str]:
    """The task's OWN deliverable(s) only -- not L1-XX-NN leaf subtasks' golden
    files (those are upstream reference material feeding this task's prompt,
    not something the agent is asked to produce).

    Two signals, either is sufficient: the file lives directly inside a
    folder literally named "Golden Solution"/"Golden Response" (the folder
    name itself is the signal -- the file's own name doesn't need to say
    "golden", e.g. "L2-01_Channel_Segmentation_Pipeline.xlsx"), OR the file
    sits at the task root and its own filename contains "golden" (the
    flat-layout convention, e.g. "L2-07 Golden Solution.docx")."""
    names = set()
    for child in task_dir.iterdir():
        if (
            child.is_dir()
            and GOLDEN_CONTAINER_RE.match(child.name)
            and not LEAF_SUBTASK_RE.match(child.name)
        ):
            for p in child.iterdir():
                if (
                    p.is_file()
                    and p.suffix.lower() in DELIVERABLE_EXTS
                    and not NON_DELIVERABLE_NAME_RE.search(p.name)
                ):
                    names.add(p.name)

    for p in task_dir.iterdir():
        if (
            p.is_file()
            and GOLDEN_HINT_RE.search(p.name)
            and p.suffix.lower() in DELIVERABLE_EXTS
            and not NON_DELIVERABLE_NAME_RE.search(p.name)
        ):
            names.add(p.name)

    return _finalize_deliverable_names(names)


def resolve_deliverable_path(task_dir: Path, deliverable_name: str) -> Path:
    """Map a deliverable filename (as returned by find_deliverable_files) back
    to its actual on-disk path -- there's exactly one real location per name
    once find_deliverable_files has deduplicated by filename."""
    for p in task_dir.rglob(deliverable_name):
        if p.is_file():
            return p
    raise ConversionError(
        f"deliverable {deliverable_name!r} not found under {task_dir} (should be unreachable)"
    )


def _finalize_deliverable_names(names: set) -> list[str]:
    if not names:
        raise ConversionError("no golden-solution deliverable file found")

    # Collapse accidental duplicate saves that differ only by stray leading/trailing
    # whitespace in the filename (observed: SVC-PC-15-3-0 has the same deliverable
    # saved twice, one copy with a leading space) -- these are the same file, not
    # two deliverables. Prefer the whitespace-clean name as canonical.
    by_stripped: dict[str, set] = {}
    for name in names:
        by_stripped.setdefault(name.strip(), set()).add(name)
    names = {
        stripped if stripped in variants else sorted(variants)[0]
        for stripped, variants in by_stripped.items()
    }

    # Multiple deliverables ARE supported at the task level -- the constraint is
    # per-VERIFIER: every criterion must resolve to exactly one target file, never
    # an array. See assign_deliverable_per_criterion().
    return sorted(names)


EXT_TO_FILE_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".md": "text",
    ".txt": "text",
}


def build_source(deliverable_name: str) -> dict:
    ext = Path(deliverable_name).suffix.lower()
    return {
        "type": "file",
        "file": {
            "type": EXT_TO_FILE_TYPE.get(ext, "any"),
            "command": "extract_text",
            "arguments": {"path": f"output/{deliverable_name}"},
        },
    }


EXT_SYNONYMS = {
    # Only unambiguous, format-specific words -- generic ones like "presentation"
    # or "report" get used rhetorically ("analytical judgment in the presentation
    # of results") without meaning "the .pptx file", and falsely swing the
    # per-criterion assignment (confirmed on SVC-PC-4-1-0's "Presentation &
    # Analytical Judgment" category, which is about analysis quality, not slides).
    ".xlsx": {"workbook", "databook", "spreadsheet", "model"},
    ".pptx": {"slide", "slides", "deck"},
    ".docx": {"memo", "note", "letter"},
    ".md": {"slack", "email"},
}
TOKEN_SPLIT_RE = re.compile(r"[_\-\s]+")


def _tokenize(name: str) -> set:
    return {t for t in TOKEN_SPLIT_RE.split(Path(name).stem.lower()) if t}


def deliverable_signal_tokens(deliverable_names: list[str]) -> dict[str, set]:
    """Per-deliverable keyword signals used to match each criterion to its ONE
    target file: filename tokens that are unique to this file among the
    task's deliverables (e.g. "databook" vs "slides"), plus generic
    extension-implied synonyms (e.g. any .pptx implies "slide"/"deck")."""
    token_sets = {name: _tokenize(name) for name in deliverable_names}
    signals = {}
    for name, toks in token_sets.items():
        others = (
            set().union(*(t for n, t in token_sets.items() if n != name))
            if len(token_sets) > 1
            else set()
        )
        distinguishing = toks - others
        generic = EXT_SYNONYMS.get(Path(name).suffix.lower(), set())
        signals[name] = distinguishing | generic
    return signals


EXT_PRIORITY = {".xlsx": 0, ".docx": 1, ".pptx": 2, ".md": 3, ".pdf": 4, ".txt": 5}


def assign_deliverable_per_criterion(
    rows: list[dict], deliverable_names: list[str]
) -> list[str]:
    """Every verifier must target exactly one file -- never an array (project
    constraint). When a task has multiple deliverables, match each criterion
    to the one its own text unambiguously names (e.g. "Slack draft leads with
    headline numbers" -> the Slack draft file; "Deck contains a cash-waterfall
    chart" -> the slide deck).

    Criteria with no signal, or a tied signal across files, default to the
    task's most quantitative deliverable (xlsx > docx > pptx > md > pdf >
    txt) rather than a majority vote of whatever few criteria happened to
    carry a keyword -- a majority vote is unreliable when one file's content
    (e.g. required-chart criteria explicitly saying "deck") dominates the
    resolved sample even though most of the OTHER, unsignaled criteria (e.g.
    financial control totals) are more naturally checked against the
    quantitative source of truth (confirmed by inspection on SVC-PC-1-0-0,
    where both files share an identical stem so filename tokens carry zero
    signal at all, and pure majority-of-resolved wrongly favored the slide
    deck over the financial model)."""
    if len(deliverable_names) == 1:
        return [deliverable_names[0]] * len(rows)

    signals = deliverable_signal_tokens(deliverable_names)
    default = min(
        deliverable_names, key=lambda n: EXT_PRIORITY.get(Path(n).suffix.lower(), 9)
    )

    assignments = []
    for row in rows:
        text = f"{row['category']} {row['description']} {row['expected_value']}".lower()
        scores = {
            name: sum(1 for tok in toks if tok in text)
            for name, toks in signals.items()
        }
        best = max(scores.values())
        winners = [n for n, s in scores.items() if s == best]
        assignments.append(winners[0] if best > 0 and len(winners) == 1 else default)

    return assignments


def grading_role_for(tier: str) -> str:
    return "process" if "structural" in tier.lower() else "outcome"


# ── Read Me contract parsing (Claire's Central Task Platform template) ─────
# Both of Claire's workbooks (Grading Rubric and Response Criteria) carry an
# identical companion "Read Me" tab: PACKAGE CONTROL SUMMARY, INPUT MANIFEST,
# OUTPUT CONTRACT, EXPECTED VALUE SETUP, STATUS VOCABULARY, and RELEASE
# DECISION sections, confirmed by inspection of the actual SVC-PC-2-3-0
# swap-in test files. Every section shares one row rhythm: a one-populated-
# cell TITLE row, a column-header row, then data rows -- terminated by the
# sheet's next one-populated-cell row (either the following section's own
# title, or this section's trailing prose note; both look identical from the
# "how many cells does this row populate" test, which is what
# _read_section_table below actually keys off instead of guessing content
# shape per section).
READ_ME_SHEET_RE = re.compile(r"read\s*me", re.IGNORECASE)
PACKAGE_SUMMARY_TITLE_RE = re.compile(r"package control summary", re.IGNORECASE)
INPUT_MANIFEST_TITLE_RE = re.compile(r"input manifest", re.IGNORECASE)
EXPECTED_VALUE_TITLE_RE = re.compile(r"expected value setup", re.IGNORECASE)
STATUS_VOCAB_TITLE_RE = re.compile(r"status vocabulary", re.IGNORECASE)
PLACEHOLDER_RE = re.compile(r"^\s*\[.*\]\s*$")
THRESHOLD_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

PACKAGE_SUMMARY_FIELDS = {"item": ["item"], "requirement": ["requirement"]}
INPUT_MANIFEST_FIELDS = {
    "no": ["no."],
    "path": ["path and filename", "relative path"],
    "context": ["record, sheet", "page"],
    "permitted_use": ["permitted"],
    "included": ["included"],
}
EXPECTED_VALUE_FIELDS = {
    "criterion_ids": ["criterion"],
    "material_value": ["material value"],
    "expected": ["expected value"],
    "source_method": ["source or method"],
    "population_period_unit_basis": ["population"],
    "tolerance": ["tolerance"],
    "if_unresolved": ["if unresolved"],
}
STATUS_VOCAB_FIELDS = {
    "status": ["status"],
    "meaning": ["meaning"],
    "required_trace_fields": ["required trace", "trace field"],
}
# The Read Me's own STATUS VOCABULARY table names these five labels -- an
# Expected Value Setup row whose "expected value" cell IS one of them (rather
# than an actual value) means the author explicitly left that criterion
# unresolved, using the vocabulary the template itself defines for that.
STATUS_LABELS = [
    "Confirmed",
    "Derived",
    "Proposed pending approval",
    "Open item",
    "Not evidenced or out of scope",
]

_ID_TOKEN_RE = re.compile(r"\b([A-Za-z]{1,3})(\d{1,3})\b")
_ID_THROUGH_RE = re.compile(
    r"\b([A-Za-z]{1,3})(\d{1,3})\s+through\s+([A-Za-z]{1,3})(\d{1,3})\b", re.IGNORECASE
)
_ID_DASH_RANGE_RE = re.compile(
    r"\b([A-Za-z]{1,3})(\d{1,3})\s*[-–—]\s*([A-Za-z]{1,3})(\d{1,3})\b"
)


def extract_criterion_ids(text: str) -> list[str]:
    """Expand every way this template names a SET of criterion IDs into the
    flat list of IDs: a bare "C01", a dash range "C03-C05"/"C03–C05"
    (an Expected Value Setup table cell), or a prose range "F01 through F07"
    (the PACKAGE CONTROL SUMMARY's gate-count sentence). Same consumed-span-
    then-residual-scan technique as
    hydrate_environment.extract_candidate_filenames, for the same reason:
    the range notations use separators ("-"/"through") the generic
    single-ID regex would otherwise fragment into spurious partial matches."""
    text = str(text or "")
    ids: list[str] = []
    consumed: list[tuple[int, int]] = []
    for pattern in (_ID_THROUGH_RE, _ID_DASH_RANGE_RE):
        for m in pattern.finditer(text):
            p1, n1, p2, n2 = m.groups()
            if p1.upper() == p2.upper():
                width = len(n1)
                for n in range(int(n1), int(n2) + 1):
                    cid = f"{p1.upper()}{n:0{width}d}"
                    if cid not in ids:
                        ids.append(cid)
            consumed.append(m.span())
    residual = list(text)
    for start, end in consumed:
        for i in range(start, end):
            residual[i] = " "
    for m in _ID_TOKEN_RE.finditer("".join(residual)):
        cid = f"{m.group(1).upper()}{m.group(2)}"
        if cid not in ids:
            ids.append(cid)
    return ids


def _map_columns(header_values, field_map: dict[str, list[str]]) -> dict[int, str]:
    col_map: dict[int, str] = {}
    for col_idx, raw in enumerate(header_values, start=1):
        text = str(raw or "").strip().lower()
        if not text:
            continue
        for field, substrings in field_map.items():
            if field in col_map.values():
                continue
            if any(sub in text for sub in substrings):
                col_map[col_idx] = field
                break
    return col_map


def _read_me_rows(ws) -> list[tuple[int, list]]:
    rows = []
    for row in ws.iter_rows():
        values = [c.value for c in row]
        if any(v not in (None, "") for v in values):
            rows.append((row[0].row, values))
    return rows


def _read_section_table(
    rows: list[tuple[int, list]], title_re: "re.Pattern", field_map: dict
) -> list[dict]:
    """One Read Me section's data rows as field-mapped dicts, or [] if the
    section isn't present (missing sections are normal for a Read Me tab
    that predates a template revision -- not a ConversionError)."""
    for i, (_, values) in enumerate(rows):
        populated = [v for v in values if v not in (None, "")]
        if len(populated) != 1 or not title_re.search(str(populated[0])):
            continue
        header_i = i + 1
        if header_i >= len(rows):
            return []
        col_map = _map_columns(rows[header_i][1], field_map)
        out = []
        for _, data_values in rows[header_i + 1 :]:
            populated = [v for v in data_values if v not in (None, "")]
            if len(populated) < 2:
                break
            out.append(
                {
                    field: str(data_values[col_idx - 1]).strip()
                    for col_idx, field in col_map.items()
                    if data_values[col_idx - 1] not in (None, "")
                }
            )
        return out
    return []


def find_read_me_sheet(
    wb: openpyxl.Workbook,
) -> "openpyxl.worksheet.worksheet.Worksheet | None":
    names = [n for n in wb.sheetnames if READ_ME_SHEET_RE.search(n)]
    return wb[names[0]] if names else None


def parse_read_me(wb: openpyxl.Workbook) -> "dict | None":
    """Parse the Read Me tab's scoring contract into structured data instead
    of leaving it as prose a judge (or this converter) can silently skip --
    the gap the evaluation doc calls out for all six of: the input manifest,
    the Response Criteria mapping's tolerance/status inputs, the status
    vocabulary, the structured tolerance, and the must-pass gate count.
    Returns None when the workbook has no Read Me tab (pre-template rubrics)
    rather than erroring -- this contract is additive metadata, never
    required for a successful conversion."""
    ws = find_read_me_sheet(wb)
    if ws is None:
        return None
    rows = _read_me_rows(ws)

    summary_rows = _read_section_table(
        rows, PACKAGE_SUMMARY_TITLE_RE, PACKAGE_SUMMARY_FIELDS
    )
    summary = {
        r.get("item", "").strip().lower(): r.get("requirement", "")
        for r in summary_rows
    }

    input_manifest = []
    for entry in _read_section_table(
        rows, INPUT_MANIFEST_TITLE_RE, INPUT_MANIFEST_FIELDS
    ):
        path = entry.get("path", "")
        entry["included"] = (
            str(entry.get("included") or "").strip().lower().startswith("y")
        )
        entry["is_placeholder"] = bool(PLACEHOLDER_RE.match(path))
        input_manifest.append(entry)

    expected_value_setup: dict[str, dict] = {}
    for entry in _read_section_table(
        rows, EXPECTED_VALUE_TITLE_RE, EXPECTED_VALUE_FIELDS
    ):
        raw_ids = entry.pop("criterion_ids", "")
        expected_text = entry.get("expected", "")
        entry["claim_status"] = next(
            (s for s in STATUS_LABELS if s.lower() == expected_text.strip().lower()),
            None,
        )
        for cid in extract_criterion_ids(raw_ids):
            expected_value_setup[cid] = entry

    status_vocabulary = _read_section_table(
        rows, STATUS_VOCAB_TITLE_RE, STATUS_VOCAB_FIELDS
    )

    # Pull the gate-count sentence from the already-parsed PACKAGE CONTROL
    # SUMMARY table by its OWN "Item" label ("Must-pass gates") rather than
    # re-scanning the whole sheet for a cell matching that label text --
    # a whole-sheet scan matches the LABEL cell itself first (column A says
    # "Must-pass gates" too, verbatim), which carries no IDs at all and
    # silently produces zero declared gates (confirmed while testing this
    # function against a synthetic fixture).
    gate_sentence = summary.get("must-pass gates", "")
    declared_gate_ids = extract_criterion_ids(gate_sentence)

    threshold_text = summary.get("release threshold", "")
    threshold_match = THRESHOLD_PERCENT_RE.search(threshold_text)
    release_policy = {
        "score_threshold_percent": (
            float(threshold_match.group(1)) if threshold_match else None
        ),
        "permitted_outcomes": summary.get("permitted release outcomes", ""),
        "release_threshold_text": threshold_text,
        "gate_ids": declared_gate_ids,
    }

    return {
        "input_manifest": input_manifest,
        "expected_value_setup": expected_value_setup,
        "status_vocabulary": status_vocabulary,
        "release_policy": release_policy,
    }


def check_gate_count(read_me: dict, rows: list[dict]) -> None:
    """Read Me's PACKAGE CONTROL SUMMARY states this template's own
    invariant in plain language ("The gate count in this instruction must
    match the rows marked Yes"). Enforce it at convert time as a hard
    failure: this is the converter-level half of the must-pass hard gate --
    if the authored gate list and the rubric's actual must-pass rows
    disagree, the SOURCE workbook is internally inconsistent and conversion
    must not silently proceed on ambiguous gate scope (same "don't guess,
    flag for review" posture as every other ambiguity check in this
    module)."""
    declared = set(read_me["release_policy"]["gate_ids"])
    if not declared:
        return
    actual = {r["criterion_id"] for r in rows if r["must_pass"]}
    if declared != actual:
        raise ConversionError(
            f"must-pass gate mismatch: Read Me declares {sorted(declared)} "
            f"but the rubric marks {sorted(actual)} as must-pass"
        )


def parse_structured_tolerance(entry: "dict | None") -> "dict | None":
    """Read Me's Expected Value Setup row -> a machine-readable tolerance
    threshold, when the row states one (e.g. "0% to +/-5% only if all four
    attributes match"). The template ties every numeric tolerance to a hard
    same-population/period/unit/basis requirement (Read Me: "A tolerance
    cannot cure different populations, periods, units, or bases") -- keep
    that requirement attached to the threshold itself, as data, so a judge
    can't apply the percent band across a mismatched basis the way prose
    alone lets it silently do."""
    if not entry:
        return None
    text = entry.get("tolerance", "")
    # "0% to +/-5%" carries TWO percent numbers (the band's floor and its
    # ceiling) -- take the max, not the first match, or "0%" wins and the
    # actual +/-5% ceiling this row is naming gets silently dropped.
    percents = [float(p) for p in THRESHOLD_PERCENT_RE.findall(text)]
    if not percents:
        return None
    return {
        "type": "relative_percent",
        "max_percent": max(percents),
        "requires_matching": ["population", "period", "unit", "basis"],
        "basis_note": entry.get("population_period_unit_basis", ""),
        "source_text": text,
    }


def evaluate_release_outcome(verifier: dict, criterion_results: dict[str, bool]) -> str:
    """Compute PASS / PASS WITH OPEN ITEMS / BLOCKED the way the Read Me's
    RELEASE DECISION table specifies, from an ALREADY-GRADED submission's
    per-criterion pass/fail results (criterion_results: verifier name ->
    passed). This is the hard-gate half of the scoring contract that
    weighted_mean alone can't express (see to_rewardkit.py's own
    must-pass-approximated-by-weight note).

    Not called anywhere in the convert() pipeline: this function scores a
    COMPLETED judge run, which happens downstream of this repo (on DataOS),
    after a package this converter built has actually been attempted. It's
    exposed here, unit-tested, and ready for that integration -- see
    claire-template-converter-run-2026-08-27.md for the precise scope note
    on why the live instance run in this fork doesn't exercise it end to
    end."""
    policy = (verifier.get("read_me_contract") or {}).get("release_policy") or {}
    threshold = policy.get("score_threshold_percent")
    verifiers = verifier.get("verifiers") or []

    failed_gates = [
        v["name"]
        for v in verifiers
        if (v.get("metadata") or {}).get("must_pass")
        and not criterion_results.get(v["name"], False)
    ]
    if failed_gates:
        return "BLOCKED"

    total_weight = sum(
        (v.get("metadata") or {}).get("weight") or 0.0 for v in verifiers
    )
    earned_weight = sum(
        (v.get("metadata") or {}).get("weight") or 0.0
        for v in verifiers
        if criterion_results.get(v["name"], False)
    )
    score_percent = (earned_weight / total_weight * 100.0) if total_weight else 0.0
    if threshold is not None and score_percent < threshold:
        return "BLOCKED"

    open_items = [
        v["name"]
        for v in verifiers
        if (v.get("metadata") or {}).get("claim_status") == "Open item"
    ]
    return "PASS WITH OPEN ITEMS" if open_items else "PASS"


def normalize_weights(rows: list[dict]) -> list[float]:
    # Open item criteria are explicitly unscored (Read Me: an unresolved
    # expected value carries no expected value to check against) -- they get
    # weight 0.0 and are excluded from the normalization base, rather than
    # counted like every other row and left for a judge to guess at an
    # unauthored expected value.
    scored_rows = [r for r in rows if r.get("claim_status") != "Open item"]
    total = sum(r["points"] for r in scored_rows)
    if total <= 0:
        raise ConversionError("sum of points is <= 0; cannot normalize weights")
    scored_weights = [round(r["points"] / total, 6) for r in scored_rows]
    residual = round(1.0 - sum(scored_weights), 6)
    if scored_weights:
        scored_weights[-1] = round(scored_weights[-1] + residual, 6)
    weight_by_id = {r["criterion_id"]: w for r, w in zip(scored_rows, scored_weights)}
    return [weight_by_id.get(r["criterion_id"], 0.0) for r in rows]


def build_verifier_json(
    task_id: str,
    rows: list[dict],
    deliverable_names: list[str],
    read_me: "dict | None" = None,
    response_criteria: "dict[str, dict] | None" = None,
) -> dict:
    weights = normalize_weights(rows)
    assignments = assign_deliverable_per_criterion(rows, deliverable_names)
    expected_value_setup = (read_me or {}).get("expected_value_setup", {})
    verifiers = []
    for i, (row, weight, deliverable_name) in enumerate(
        zip(rows, weights, assignments), start=1
    ):
        expected_value_entry = expected_value_setup.get(row["criterion_id"])
        response_entry = (response_criteria or {}).get(row["criterion_id"])
        tolerance = parse_structured_tolerance(expected_value_entry)

        # Concatenate the source rubric's own Description and Expected-value
        # columns as-is -- no invented "Expected:" label. Same fix and same
        # reasoning as to_rewardkit.py's _svc_criteria (2026-09-02): this
        # repo's own verifier.json schema has room for expected_value as its
        # own metadata field (see how_justification/why_justification below),
        # so folding it into the prompt string at all is a format-alignment
        # choice for the grading judge's benefit, not something dictated by
        # an external schema -- inventing connective wording on top of that
        # isn't required either, and previously produced a dangling
        # "... Expected: ." when expected_value was blank.
        prompt = row["description"]
        if row["expected_value"]:
            prompt = f"{prompt} {row['expected_value']}".strip()
        # must_pass and claim_status are NOT appended here -- both are pure
        # tool-invented sentences with no unique content ("This is a
        # must-pass criterion." / "Claim status: X.") that metadata.must_pass
        # and metadata.claim_status below already carry structurally, for
        # exactly the downstream tools (evaluate_release_outcome(),
        # normalize_weights()'s Open-item handling) that need to key off
        # them. Response-criteria guidance and blocked-if ARE real,
        # substantive human-authored text (Claire's Response Criteria
        # workbook) -- kept, but as-is, with no invented label glued in
        # front (same treatment as expected_value above).
        if response_entry and response_entry.get("satisfactory_response"):
            prompt = f"{prompt} {response_entry['satisfactory_response']}".strip()
        if response_entry and response_entry.get("blocked_if"):
            prompt = f"{prompt} {response_entry['blocked_if']}".strip()
        # Tolerance is left as its existing labeled sentence, deliberately:
        # unlike the fields above, there's no verbatim source wording to
        # fall back to here -- parse_structured_tolerance() already reduces
        # whatever the Read Me's Expected Value Setup table said down to a
        # bare max_percent number, and the surrounding sentence is the only
        # thing telling the judge HOW to apply that number (which population/
        # period/unit/basis it's scoped to). Removing it would be a real
        # information loss, not just a cosmetic label, for no verbatim-
        # fidelity gain.
        if tolerance:
            prompt += (
                f" Tolerance: within {tolerance['max_percent']}% only when population, "
                "period, unit, and basis all match; never average across a mismatched basis."
            )

        metadata = {
            "tag": row["criterion_id"].lower(),
            "grading_role": grading_role_for(row["tier"]),
            "importance": "core" if row["must_pass"] else "secondary",
            "weight": weight,
            "how_justification": row["description"],
            "why_justification": row["category"] or "n/a",
            # Explicit boolean gate flag -- previously the ONLY signal a must-pass
            # gate left in verifier.json was this same text folded into the prompt
            # string and the "core"/"secondary" importance label, neither of which
            # a downstream tool can key off without re-parsing prose. See
            # evaluate_release_outcome() and check_gate_count().
            "must_pass": row["must_pass"],
        }
        if row["claim_status"]:
            metadata["claim_status"] = row["claim_status"]
        if tolerance:
            metadata["tolerance"] = tolerance
        if response_entry:
            metadata["response_criteria"] = response_entry

        verifiers.append(
            {
                "name": f"v{i}",
                "metadata": metadata,
                "source": build_source(deliverable_name),
                "assertion": {
                    "type": "rubric",
                    "expected": True,
                    "rubric": {"prompt": prompt},
                },
            }
        )
    return {
        "task_id": task_id,
        "config": {
            "models": ["openai/gpt-5.4"],
            "temperature": 1.0,
            "reasoning_effort": "xhigh",
        },
        "verifiers": verifiers,
        "read_me_contract": read_me,
    }


def convert(task_dir: Path) -> dict:
    task_id = task_dir.name
    rubric_path = find_rubric_file(task_dir)
    print(f"  rubric file: {rubric_path.relative_to(task_dir)}")
    wb = openpyxl.load_workbook(rubric_path, data_only=True)
    ws = find_criteria_sheet(wb)
    print(f"  criteria sheet: {ws.title!r} (of {wb.sheetnames})")
    header_row, col_map = find_header_row(ws)
    missing = [
        f
        for f in ("criterion_id", "description", "points")
        if f not in col_map.values()
    ]
    if missing:
        raise ConversionError(
            f"header row {header_row} in {ws.title!r} missing required field(s): {missing}"
        )
    rows = parse_rows(ws, header_row, col_map)
    if not rows:
        raise ConversionError(f"zero parseable criteria rows in {rubric_path}")
    deliverable_names = find_deliverable_files(task_dir)
    print(f"  deliverable file(s): {deliverable_names}")

    read_me = parse_read_me(wb)
    if read_me is None:
        print("  Read Me tab: none (pre-template rubric)")
    else:
        check_gate_count(read_me, rows)
        for row in rows:
            entry = read_me["expected_value_setup"].get(row["criterion_id"])
            row["claim_status"] = entry.get("claim_status") if entry else None
        declared_inputs = sum(
            1
            for entry in read_me["input_manifest"]
            if entry["included"] and not entry["is_placeholder"]
        )
        open_items = sum(1 for r in rows if r["claim_status"] == "Open item")
        print(
            f"  Read Me tab: {declared_inputs} declared input(s), "
            f"{len(read_me['release_policy']['gate_ids'])} declared gate(s) "
            f"(cross-checked ok), {open_items} Open item criterion/criteria (unscored)"
        )

    response_criteria_path = find_response_criteria_file(task_dir)
    response_criteria = None
    if response_criteria_path is not None:
        print(
            f"  response criteria file: {response_criteria_path.relative_to(task_dir)}"
        )
        try:
            response_criteria = parse_response_criteria(response_criteria_path)
        except ConversionError as exc:
            # A pre-Claire-template task can ship a Response Criteria workbook in
            # a shape this parser does not recognize (no ID column, or no header
            # row it can find). That file is supplementary: the Grading Rubric
            # alone carries every criterion, id, point value and must-pass flag
            # the verifier needs. Before the Claire template support landed,
            # these files were ignored entirely and the tasks converted fine, so
            # failing the whole conversion here is a regression: it took the
            # 2026-08-27 pilot batch from 7 ready to 0. Warn and convert without
            # the enrichment instead.
            print(
                f"  WARN: response criteria not in template shape, converting "
                f"without it ({exc})",
                file=sys.stderr,
            )
            response_criteria = None
        unmatched = (
            []
            if response_criteria is None
            else [
                r["criterion_id"]
                for r in rows
                if r["criterion_id"] not in response_criteria
            ]
        )
        if unmatched:
            print(
                f"  WARN: response criteria has no row for {unmatched}", file=sys.stderr
            )

    verifier = build_verifier_json(
        task_id, rows, deliverable_names, read_me, response_criteria
    )

    if len(deliverable_names) > 1:
        per_file_counts = {name: 0 for name in deliverable_names}
        for v in verifier["verifiers"]:
            per_file_counts[Path(v["source"]["file"]["arguments"]["path"]).name] += 1
        print(f"  per-file verifier assignment: {per_file_counts}")

    weight_sum = round(sum(v["metadata"]["weight"] for v in verifier["verifiers"]), 4)
    n_outcome = sum(
        1 for v in verifier["verifiers"] if v["metadata"]["grading_role"] == "outcome"
    )
    print(
        f"  {len(rows)} verifiers, weight sum={weight_sum}, "
        f"outcome={n_outcome}/{len(rows)}, must-pass={sum(r['must_pass'] for r in rows)}"
    )
    if abs(weight_sum - 1.0) > 0.001:
        raise ConversionError(
            f"normalized weight sum {weight_sum} deviates from 1.0 by more than 0.001"
        )
    if len(rows) < 6:
        print(
            f"  WARN: only {len(rows)} verifiers (project convention recommends >= 6)",
            file=sys.stderr,
        )

    return verifier


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("task_dir", type=Path)
    ap.add_argument(
        "--out", type=Path, default=None, help="defaults to <task_dir>/verifier.json"
    )
    args = ap.parse_args()

    if not args.task_dir.is_dir():
        print(f"ERROR: not a directory: {args.task_dir}", file=sys.stderr)
        return 1

    out_path = args.out or (args.task_dir / "verifier.json")
    print(f"converting {args.task_dir} ...")
    try:
        verifier = convert(args.task_dir)
    except ConversionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    out_path.write_text(json.dumps(verifier, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
