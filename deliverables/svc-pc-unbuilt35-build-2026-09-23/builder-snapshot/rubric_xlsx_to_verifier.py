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
import hashlib
import json
import re
import sys
from pathlib import Path

import docx
import openpyxl

MODEL_SKIP_RE = re.compile(r"gpt|gemini|claude|chatgpt|codex", re.IGNORECASE)
RUBRIC_NAME_RE = re.compile(r"rubric", re.IGNORECASE)
# Matches a stale "_old"/"_old2"/... copy suffix on a file stem (before the extension),
# e.g. "L2-05_Response_Criteria_old2" -- see pick_unique_file's superseded-copy filter.
SUPERSEDED_COPY_RE = re.compile(r"_old\d*$", re.IGNORECASE)
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
    # "section" is a 7th observed sheet-layout variant (the SVC-PC-38-* and SVC-PC-52-*
    # families, confirmed by inspecting SVC-PC-38-0-0_Grading_Rubric.xlsx and
    # SVC-PC-52-1-0_Grading_Rubric.xlsx directly): the grouping column is headed "Section"
    # rather than "Category", carrying values like "A. Grant population and authorization".
    # Corpus-scanned before adding (scan_headers.py over every rubric xlsx's first 10 rows):
    # a bare "Section" header cell occurs only in this family plus its L2-0x sibling
    # (SVC-PC-46-4-0); every other "section" hit anywhere in the corpus is prose inside a
    # Description/Expected cell, never a header, so this alias cannot steal a column from
    # any other family.
    "category": ["category", "section"],
    "tier": ["tier"],
    # "criterion" as a bare column header (not "criterion id") is a 6th observed
    # sheet-layout variant (task_svc-pc-9-* family) that uses "Criterion" for the
    # descriptive text itself rather than a "Description" column -- confirmed by
    # inspecting the actual header row (['ID', 'Category', 'Tier', 'Criterion',
    # 'Expected value + source file', 'Points', 'Must-pass?']). Safe to add: no
    # other field's substrings overlap with a bare "criterion" token, and
    # "criterion id" is still claimed first by the criterion_id field above.
    # Claimed BEFORE description so a "Criterion Type" header cannot be swallowed by the
    # bare "criterion" alias below. That swallowing is the 2026-08-29 defect that
    # svc_verify_package.py check 3 exists to catch: the judge received
    # "Judgment Expected: <value>" as the whole requirement and 151 criteria across six
    # tasks were scored against it. It recurred on 2026-09-08 for SVC-PC-1-2-0 and
    # SVC-PC-14-2-0, whose header is
    # "Criterion ID | Category | Criterion Type | Requirement | Acceptance Standard | ...".
    "criterion_type": ["criterion type"],
    # "requirement" is the description slot in that same layout. It is listed after
    # "description" so a workbook carrying both keeps the column it uses today; the 9-*
    # family is unaffected either way, its header has no Requirement column at all.
    "description": ["description", "requirement", "criterion"],
    "expected_value": ["expected value", "expected", "acceptance standard"],
    # "weight" is the SVC-PC-90-*/SVC-PC-91-*/SVC-PC-92-2-0 families' own header for this
    # column ("Weight (%)"/"Weight %"), used exactly like a Points column -- their rows
    # carry no separate Points header at all (confirmed by inspecting
    # SVC-PC-90-0-0_Grading_Rubric.xlsx and SVC-PC-91-0-0_Grading_Rubric.xlsx directly).
    # Column-order-safe to add: any row that ALSO has a real "Points"/"pts" column
    # (SVC-PC-75-*'s own "Max Points" + a separate, redundant "Weight (%)" column is the
    # corpus's one such case) claims 'points' from that column first, since columns are
    # matched left-to-right and a field already in col_map is skipped -- "weight" only
    # fires when nothing else already claimed 'points'. Corpus-scanned
    # (scan_new_aliases.py) before adding: every other "weight"-containing header-shaped
    # cell in the corpus lives on a "Category Weights"/"Weighting & Notes" auxiliary sheet
    # (already excluded from the criteria sheet by SKIP_SHEET_RE, and read separately by
    # apply_section_weight_fallback) or is prose inside a data row on an already-converting
    # task, never a competing header on the sheet this function actually parses.
    "points": ["pts", "points", "weight"],
    # "gate" is the SVC-PC-19-2-0 Scoring Form's own name for this column (header
    # "Gate", values "Yes"/"No") -- the same release-critical-gate concept its own Read Me
    # tab calls "10 release-critical gates". Checked against every other rubric header cell
    # in the corpus (scan_headers.py "gate"): no other family uses "gate" for anything else
    # in a header row, so this cannot steal a column elsewhere.
    # "required" is the SVC-PC-47-* family's own name for this column (header "Required?",
    # values "Yes"/"No", e.g. SVC-PC-47-0-0 row R-01). Before this alias existed, none of
    # the 9 SVC-PC-47-* tasks resolved a must_pass field at all, so every criterion in the
    # family silently shipped must_pass=False regardless of the source rubric's own Yes/No
    # marking -- one of the two confirmed causes behind the 23-task zero-must-pass-text
    # defect (2026-09-15 corpus scan: every "required"-containing header cell in the corpus,
    # 9 total, is this exact family and column, and none of the 9 was already mapped to
    # anything else, so this cannot steal a column anywhere).
    "must_pass": ["must-pass", "must pass", "gate", "required"],
    "src_refs": ["src #", "src#", "response criteria number", "source"],
}
# fields matched by exact (post-strip) header text rather than substring, since the
# substring is too short/generic to safely match anywhere in a longer header (e.g. "id").
FIELD_HEADER_EXACT = {
    # "#" is the SVC-PC-38-* family's (and SVC-PC-46-1-0's) own header for the ID column --
    # confirmed by inspecting SVC-PC-38-0-0_Grading_Rubric.xlsx and
    # L2-01_Grading_Rubric.xlsx directly. Corpus-scanned (scan_exact_header.py "#") before
    # adding: every other exact "#" header cell in the corpus lives on an "Input Manifest"/
    # "OS Data Manifest"/"Required Output Manifest"/"Release Control" sheet that is never
    # selected as the criteria sheet (a "*rubric*"-named sheet always wins first), so this
    # alias cannot steal a column from any sheet that currently converts correctly.
    # "ref." is the SVC-PC-63-* family's own header for the ID column (values "F01",
    # "F02", ... in a "Ref." column, with "Criterion" reused for the descriptive text --
    # see the bare-"criterion" handling in find_header_row's _map_row below). Confirmed
    # by inspecting SVC-PC-63-0-0_Grading_Rubric.xlsx directly. Corpus-scanned
    # (scan_new_aliases.py "ref."/"ref"): the only bare "ref."-shaped header cell anywhere
    # in the corpus is this one family, so this cannot steal a column elsewhere.
    "criterion_id": ["id", "#", "ref."],
    # "mp" is the same SVC-PC-38-*/SVC-PC-52-* family's header for the must-pass column
    # (values are the literal marker "MP", not "Yes"/"No" -- see parse_rows' must_pass
    # value logic below). Exact-match only, like "id" above, since "mp" as a substring
    # would match plenty of unrelated header prose (e.g. "Company", "template").
    # Corpus-scanned (scan_exact_header.py "mp"): every exact "mp" header/value hit in the
    # corpus is this one family.
    "must_pass": ["mp"],
    # "src" (SVC-PC-13-1/13-2/13-5/13-8-0 Grading Rubric, values like
    # "Year_End_TB / Year_1_Annual_PnL") and "lens" (SVC-PC-60-1-0 Scoring Form, values
    # "Form"/...) are exact-match only so neither can claim a longer header elsewhere.
    # Added 2026-09-23 for the 35-unbuilt build; without them the fail-loud check routes
    # those five tasks to messy over informational columns.
    "src_refs": ["src"],
    "category": ["lens"],
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

    # Drop stale "_old"/"_old2"-suffixed copies before any other tie-break: SVC-PC-88-5-0
    # ships L2-05_Response_Criteria.xlsx alongside L2-05_Response_Criteria_old.xlsx and
    # _old2.xlsx, all three at the same directory depth and all three matching the
    # "response_criteria" name hint (the suffix comes after, not instead of, the hinted
    # text), so neither existing tie-break below ever narrowed it and this raised
    # "ambiguous ... file" for a task whose real file was unambiguous by name alone.
    # Corpus-scanned (every filename containing "_old" anywhere under 00_fetched): this
    # family is the only hit, so this cannot discard a real candidate elsewhere. Only
    # narrows when it leaves exactly one file -- if every candidate (or none) carries the
    # suffix, that's not this defect and the normal tie-break chain still runs on the
    # original list.
    not_superseded = [p for p in candidates if not SUPERSEDED_COPY_RE.search(p.stem)]
    if len(not_superseded) == 1:
        return not_superseded[0]

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

    # Byte-identical duplicates: the SVC-PC-88-2-0 through 88-7-0 family ships every
    # Prompt file twice under two names -- one plain (e.g.
    # "L2-02_State_Withholding_Correction_Prompt.docx") and one repeating the task id
    # (e.g. "SVC-PC-88-L2-02_State_Withholding_Correction_Prompt.docx") -- both sitting at
    # the same depth inside Prompt/, so neither tie-break above narrows it and this used
    # to raise "ambiguous prompt file" for six tasks whose actual content was never in
    # question. Confirmed by hashing every pair (sha256, 2026-09-13): both copies are
    # byte-for-byte identical in all six cases. When that holds, the filename disagreement
    # carries no information, so pick deterministically (shortest name, then
    # lexicographic) rather than refuse to guess. This only fires once every other
    # tie-break has already failed to narrow the pool, so it cannot change which file a
    # currently-resolving task gets -- it only resolves cases that previously raised.
    hashes = {_file_sha256(p) for p in pool}
    if len(hashes) == 1:
        return sorted(pool, key=lambda p: (len(p.name), str(p)))[0]

    raise ConversionError(
        f"ambiguous {kind} file for {task_dir}: {[str(p.relative_to(task_dir)) for p in candidates]}"
    )


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_rubric_file(task_dir: Path) -> Path:
    # .xlsm belongs alongside .xlsx here for the same reason it was added to
    # DELIVERABLE_EXTS below: a macro-enabled Grading Rubric (e.g.
    # SVC-PC-39-6-0_Grading_Rubric.xlsm) is invisible to a bare "*.xlsx" rglob,
    # so the task fails at "rubric conversion: no rubric file found" even
    # though the file is sitting right there in Rubric/. openpyxl reads
    # .xlsm natively, so no format conversion is needed here, just discovery.
    candidates = [
        p
        for p in task_dir.rglob("*")
        if p.suffix.lower() in (".xlsx", ".xlsm")
        and RUBRIC_NAME_RE.search(p.name)
        and not any(
            MODEL_SKIP_RE.search(part) for part in p.relative_to(task_dir).parts[:-1]
        )
    ]

    # SVC-PC-25-0-0 ships both SVC-PC-25-0-0_Grading_Rubric.xlsx and
    # SVC-PC-25-0-0_Grading_Rubric.xlsm side by side in Rubric/ -- same stem, same
    # depth, same name-hint match, so none of pick_unique_file's tie-breaks narrow it
    # and this used to raise "ambiguous rubric file" for a task that converted fine
    # before .xlsm support was added above. The .xlsm branch exists so a task whose
    # ONLY rubric is macro-enabled isn't invisible to a bare *.xlsx rglob (see the
    # comment above); it was never meant to compete with an .xlsx that's already
    # present for the same rubric. When both exist for the same stem, drop the
    # .xlsm copy and keep .xlsx -- the pre-.xlsm-support behavior, so this narrows
    # only the newly-introduced ambiguity, not any pre-existing resolution.
    # Corpus-scanned (2026-09-15): SVC-PC-25-0-0 is the only task in the 612-task
    # corpus with a same-stem .xlsx/.xlsm rubric pair, so this cannot change which
    # file any other task resolves to.
    xlsx_stems = {p.stem.lower() for p in candidates if p.suffix.lower() == ".xlsx"}
    if xlsx_stems:
        candidates = [
            p
            for p in candidates
            if not (p.suffix.lower() == ".xlsm" and p.stem.lower() in xlsx_stems)
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
    if not candidates:
        # Fallback: some tasks (the SVC-PC-18-* family) name the prompt file
        # descriptively instead of putting "prompt" in the filename, but still
        # place it directly inside a folder literally named "Prompt". Only
        # engaged when the filename-based match above finds nothing, so this
        # cannot change the resolution for any task that already matches.
        candidates = [
            p
            for p in task_dir.rglob("*")
            if p.is_file()
            and p.suffix.lower() in {".docx", ".md", ".txt"}
            and p.parent.name.strip().lower() == "prompt"
            and not any(
                MODEL_SKIP_RE.search(part)
                for part in p.relative_to(task_dir).parts[:-1]
            )
        ]
    return pick_unique_file(task_dir, candidates, "prompt")


def extract_prompt_text(prompt_path: Path) -> str:
    if prompt_path.suffix.lower() == ".docx":
        d = docx.Document(str(prompt_path))
        return "\n".join(p.text for p in d.paragraphs)
    return prompt_path.read_text(encoding="utf-8", errors="replace")


REQUIRED_CRITERIA_FIELDS = {"criterion_id", "description", "points"}


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
    # Multiple unlabeled candidates and none say "rubric": row count alone is not a
    # reliable tiebreaker. SVC-PC-19-2-0 (Claire's "Scoring Form" template) ships three
    # such sheets -- "Read Me", "Scoring Form" (the real 47-row criteria table), and
    # "Input Manifest" (an 82-row list of permitted source paths, not a criteria table at
    # all) -- and the old max-row-count rule picked "Input Manifest" because it happens to
    # be the longest, which is how this task failed with "no header row found in first 30
    # rows of sheet 'Input Manifest'". The rest of this same template family (SVC-PC-19-0,
    # 19-1, 19-3..19-7, SVC-PC-37-*) converts fine today only because their own "Scoring
    # Form" happens to outsize their own "Input Manifest" -- an accident of row count, not
    # a rule. Score every candidate by how much of an actual rubric header it resolves
    # instead: a criteria table resolves criterion_id/description/points; a file manifest
    # resolves at most an ID-shaped first column and nothing else.
    scored = []
    for name in candidates:
        try:
            _, col_map = find_header_row(wb[name])
        except ConversionError:
            continue
        resolved = set(col_map.values())
        if not REQUIRED_CRITERIA_FIELDS <= resolved:
            continue
        scored.append((len(resolved), wb[name].max_row, name))
    if scored:
        _, _, best_name = max(scored)
        return wb[best_name]
    # Nothing resolved a usable header -- fall back to the original row-count heuristic so
    # a workbook this scoring can't help still converts exactly the way it did before this
    # existed (find_header_row raises its own clear error downstream if the pick is wrong).
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
    # A keyword count alone picks the wrong row in both directions, which is how all 10
    # tasks in the 2026-09-08 Final L2 rebuild failed to convert:
    #
    #   too loose  SVC-PC-1-2-0 and SVC-PC-14-2-0 carry a prose banner at row 2
    #              ("Maximum 100 points ... must-pass ...") that clears >=3 keywords while
    #              naming no columns at all. Being first, it beat the real header at row 4
    #              and the task died on "missing required field(s)".
    #   too tight  The SVC-PC-9-* family's real header is
    #              "ID | Scoring criterion | ... | Tolerance or fail rule | Must-pass gate",
    #              which hits only 2 keywords. It was skipped, and for 9-3-0, 9-4-0 and
    #              9-5-0 a later DATA row reached 3 and was taken as the header instead.
    #
    # So score every candidate row by how many logical FIELDS it actually resolves, and
    # require the id column, since every caller keys its rows by criterion_id. A prose
    # banner resolves nothing and a data row resolves almost nothing, while a real header
    # resolves several.
    #
    # The original first-match-wins rule stays as the primary so this cannot disturb any
    # workbook that converts today: those necessarily resolve criterion_id at that row,
    # because convert() and parse_response_criteria() both reject a header without one.
    # Only inputs that currently raise can reach the fallback.
    def _map_row(cells: list[str]) -> dict[int, str]:
        col_map: dict[int, str] = {}
        # A bare "Criterion" header cell is genuinely ambiguous across this corpus.
        # Most families use a SEPARATE id column ("ID", "#", "Criterion ID", "Ref.")
        # and use "Criterion" for the descriptive requirement text instead (that is
        # what the "criterion" entry in the description field's substrings above is
        # for). But SVC-PC-61-*/62-* have NO other id-shaped column at all: "Criterion"
        # itself holds the identifier ("F01", "F02", ...), confirmed by inspecting
        # SVC-PC-61-0-0_Grading_Rubric.xlsx directly, and the same shape recurs in
        # SVC-PC-96-3-0..96-6-0's "Scoring Criteria" sheet. Disambiguate the only way
        # the header text allows: if this row carries NO other cell that already
        # signals an id column via field_substrings/field_exact's own criterion_id
        # entries (whatever those are for this call -- Claire's Response Criteria
        # form reuses this same function with a different field map), a bare
        # "criterion" cell must be doing that job itself. Checked once per row,
        # before any column claims "description", so the freed-up description slot
        # still goes to whichever OTHER column actually holds the requirement text
        # ("Observable requirement", "Pass condition", ...) via the normal loop below.
        id_substrings = field_substrings.get("criterion_id", [])
        id_exacts = field_exact.get("criterion_id", [])
        strong_id_signal = any(
            any(sub in text for sub in id_substrings) or text in id_exacts
            for text in cells
            if text
        )
        for col_idx, text in enumerate(cells, start=1):
            if not text:
                continue
            if (
                text == "criterion"
                and not strong_id_signal
                and "criterion_id" not in col_map.values()
            ):
                col_map[col_idx] = "criterion_id"
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
        return col_map

    scanned: list[tuple[int, int, dict[int, str]]] = []
    for row_idx in range(1, min(30, ws.max_row + 1)):
        cells = [
            str(c.value).strip().lower() if c.value is not None else ""
            for c in ws[row_idx]
        ]
        hits = sum(1 for kw in HEADER_KEYWORDS if any(kw in cell for cell in cells))
        scanned.append((row_idx, hits, _map_row(cells)))

    for row_idx, hits, col_map in scanned:
        if hits >= 3 and "criterion_id" in col_map.values():
            return row_idx, col_map

    usable = [entry for entry in scanned if "criterion_id" in entry[2].values()]
    if usable:
        # most fields resolved wins; then keyword count; then the earliest row
        row_idx, _hits, col_map = max(usable, key=lambda e: (len(e[2]), e[1], -e[0]))
        return row_idx, col_map

    # Last resort: some workbooks ship NO header row at all -- a one-cell title
    # ("Grading Rubric") in row 1, then real criteria data starting immediately in row
    # 2 (the SVC-PC-78-* family: confirmed by inspecting
    # SVC-PC-78-0-0_Grading_Rubric.xlsx and its four siblings directly, all five
    # identical in shape). `usable` above is already empty here -- no row in 1..30
    # resolved criterion_id under either field map this function has ever been called
    # with -- so there is no header text left to keyword-match against. (An earlier
    # version of this fallback also required every row's col_map to be entirely empty;
    # that broke on this exact family, because ordinary business prose two rows down
    # -- "Volume Tier Analysis", "three tiers defined..." -- contains the bare word
    # "tier" and the 'tier' field's substring match fired on it. A DATA row coincidentally
    # matching one unrelated field is not evidence of a real header, so this only checks
    # what actually matters: no row resolved criterion_id.) The only signal left is the
    # corpus's own dominant column convention, which dozens of HEADERED tasks in this
    # same corpus already use (ID, Category, Tier, Description, Expected value, Points,
    # Must-pass, Source -- e.g. SVC-PC-49-0-0, SVC-PC-91-0-0). Applying that positionally
    # is only safe when the shape actually matches it: a lone-cell title row, immediately
    # followed by a row whose 1st column looks like a criterion id (carries a digit,
    # matching parse_rows' own id/digit convention below), 6th column is a real number,
    # and 7th is a bare Y/N-shaped must-pass token in exactly that layout. Anything short
    # of that exact shape still raises rather than guessing -- this is the same
    # "don't guess, flag for review" posture as apply_section_weight_fallback.
    title_cells = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    if sum(1 for v in title_cells if v) == 1 and (ws.max_row or 0) >= 2:
        data_cells = [c.value for c in ws[2]]
        id_text = (
            str(data_cells[0]).strip()
            if data_cells and data_cells[0] is not None
            else ""
        )
        points_val = data_cells[5] if len(data_cells) > 5 else None
        gate_text = (
            str(data_cells[6]).strip().lower()
            if len(data_cells) > 6 and data_cells[6] is not None
            else ""
        )
        try:
            float(points_val)
            points_ok = True
        except (TypeError, ValueError):
            points_ok = False
        if (
            any(ch.isdigit() for ch in id_text)
            and points_ok
            and gate_text in ("y", "n", "yes", "no")
        ):
            return 1, {
                1: "criterion_id",
                2: "category",
                3: "tier",
                4: "description",
                5: "expected_value",
                6: "points",
                7: "must_pass",
                8: "src_refs",
            }

    raise ConversionError(f"no header row found in first 30 rows of sheet '{ws.title}'")


# Values a QC-review scorecard column ships with before anyone has actually reviewed it --
# e.g. SVC-PC-59-*/60-*'s own "Issue status" column reads the literal "Not assessed" for
# every one of its 100/100 (etc.) rows, never anything else (2026-09-15 corpus scan: 0 of 7
# SVC-PC-59-* tasks has ANY other value in that column). That is a template default, not
# per-criterion authored content -- there is nothing for check_unmapped_headers to lose by
# not flagging it, unlike a column such as "Pass condition" whose text actually varies
# criterion to criterion.
UNREVIEWED_PLACEHOLDER_VALUES = {"not assessed", "n/a", "na", "tbd", "pending"}


def _matches_known_field(header_text: str) -> "str | None":
    """Would this header text resolve to a field if that field weren't already claimed by
    an earlier column? Used only to tell apart two very different reasons a column ends up
    unmapped -- see check_unmapped_headers."""
    for field, substrings in FIELD_HEADER_SUBSTRINGS.items():
        if any(sub in header_text for sub in substrings):
            return field
    for field, exacts in FIELD_HEADER_EXACT.items():
        if header_text in exacts:
            return field
    return None


def check_unmapped_headers(
    ws, header_row: int, col_map: dict[int, str], task_id: str
) -> None:
    """A non-empty header cell that resolves to no known field used to be silently
    dropped: the mapping loop in find_header_row's _map_row just skips it, so the column
    -- and every value in it -- vanishes with no trace anywhere in verifier.json. Confirmed
    real and costly: SVC-PC-96-2-0's "Scoring Criteria" sheet carries a "Pass condition"
    column (the actual pass/fail guidance for all 40 of its criteria, e.g. "Must be
    satisfied; a gate failure blocks PASS.") and an "Output component" column, neither
    recognized by any current field alias -- both silently dropped for every single row
    before this check existed. Corpus-scanned 2026-09-15 (all 612 fetched SVC-PC tasks,
    live find_header_row/find_criteria_sheet): 138 tasks carry at least one such column
    with real, varying, non-placeholder content in it.

    Fail loud instead: raise ConversionError naming the exact header cell, sheet, and an
    example row/value, so a human decides whether this needs a new field alias (like
    "required" or "section" before it) or is genuinely disposable -- never let the parser
    make that call silently, matching every other ambiguity in this module ("don't guess,
    flag for review").

    Two classes of unmapped header are deliberately NOT flagged, both confirmed against
    real corpus data rather than assumed:
      1. Text that WOULD match a known field's alias if that field weren't already claimed
         by an earlier column -- e.g. SVC-PC-75-*'s "Weight (%)" only goes unmapped because
         its own "Max Points" column already claimed 'points' first (see the "weight" alias
         comment on FIELD_HEADER_SUBSTRINGS above); the data is redundant with an already-
         captured column, not lost. Re-derived here via _matches_known_field rather than
         re-litigated per family.
      2. A column whose every value is an unreviewed-QC-scorecard placeholder (see
         UNREVIEWED_PLACEHOLDER_VALUES) -- e.g. SVC-PC-59-*'s "Issue status", always
         "Not assessed". Template boilerplate, not authored rubric content; nothing is
         actually lost by not capturing it.
    """
    header_cells = [
        str(c.value).strip() if c.value is not None else "" for c in ws[header_row]
    ]
    findings = []
    for col_idx, text in enumerate(header_cells, start=1):
        if not text or col_idx in col_map:
            continue
        if _matches_known_field(text.lower()) is not None:
            continue  # class 1: redundant duplicate, see docstring
        examples = []
        for row in ws.iter_rows(min_row=header_row + 1):
            val = row[col_idx - 1].value
            if val in (None, ""):
                continue
            if str(val).strip().lower() in UNREVIEWED_PLACEHOLDER_VALUES:
                continue
            id_cell = row[0].value
            examples.append((id_cell, val))
            if len(examples) >= 3:
                break
        if not examples:
            continue  # blank, or class 2: placeholder-only, see docstring
        col_letter = ws.cell(row=header_row, column=col_idx).column_letter
        sample = "; ".join(f"row {rid!r}: {val!r}" for rid, val in examples)
        findings.append(f"{col_letter}{header_row} ({text!r}) -- e.g. {sample}")
    if findings:
        raise ConversionError(
            f"{task_id}: sheet {ws.title!r} has header cell(s) that map to no known "
            f"field and carry real data that would be silently dropped: "
            + "; ".join(findings)
        )


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
        # A trailing metadata/footer row below the real criteria (SVC-PC-73-*'s own
        # "Grades prompt" / "<task id>" / "<deliverable filename>" row, appended after its
        # rubric's last real criterion and its own TOTAL line) can still slip past the
        # check above whenever its ID and description columns both happen to be
        # non-blank. Every real criterion ID observed anywhere in this corpus carries at
        # least one digit (R001, OBJ-01, A1, C28, J3a, ...); a footer label like "Grades
        # prompt" does not. Checked against all 435 already-converting tasks
        # (id_no_digit_scan.py) before adding this: the only ID+description rows with no
        # digit anywhere in the ID are these 6 SVC-PC-73-* footer rows, so this cannot
        # drop a real criterion elsewhere.
        if not any(ch.isdigit() for ch in criterion_id):
            continue
        raw_points = values.get("points")
        # A genuinely blank Points cell (None or "") is not the same defect as a garbage,
        # unparseable one. SVC-PC-38-* and SVC-PC-52-* leave Points blank for EVERY
        # criterion on purpose -- weight is authored per-Section on the companion
        # "Weighting & Notes" sheet instead (see apply_section_weight_fallback below).
        # Keep the row with points=None here so convert() can still resolve it that way;
        # only an actually-malformed value (text that isn't a number) is a real per-row
        # data problem worth the existing WARN-and-skip.
        if raw_points in (None, ""):
            points = None
        else:
            try:
                points = float(raw_points)
            except (TypeError, ValueError):
                print(
                    f"  WARN: skipping row {criterion_id!r} -- unparseable points {raw_points!r}",
                    file=sys.stderr,
                )
                continue
        # Must-pass VALUE conventions differ by family, not just the header word: the
        # "must-pass"/"must pass" schema marks a gate with "Yes"/"Y", but the
        # SVC-PC-38-*/SVC-PC-52-* "MP" column marks one with the literal token "MP" in an
        # otherwise-blank column (blank means "not a gate"). Recognize both rather than
        # assuming "Yes"-shaped values everywhere -- a bare startswith("y") check left
        # every gate in that family silently false.
        #
        # SVC-PC-61-*/SVC-PC-62-* (14 tasks) use a THIRD value convention on their own
        # "Gate" column: the literal two-word value "Must pass" for a gate row and
        # "Standard" for a non-gate row -- never "Yes"/"Y"/"MP". Confirmed directly against
        # the source (SVC-PC-61-0-0: 14 "must pass" rows, 86 "standard" rows; same shape
        # across all 14 siblings, 2026-09-15). None of "must pass"'s own words start with
        # "y", so every one of those 14 tasks shipped zero must_pass=True criteria despite
        # the source rubric marking real gates -- the other confirmed cause (alongside the
        # SVC-PC-47-* header-alias gap above) behind the 23-task zero-must-pass-text defect.
        # "standard" correctly stays unmatched, no change needed there.
        must_pass_text = str(values.get("must_pass") or "").strip().lower()
        must_pass = (
            must_pass_text.startswith("y")
            or must_pass_text == "mp"
            or must_pass_text == "must pass"
        )
        rows.append(
            {
                "criterion_id": criterion_id,
                "category": str(values.get("category") or "").strip(),
                "tier": str(values.get("tier") or "").strip(),
                "description": description,
                "expected_value": str(values.get("expected_value") or "").strip(),
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


SECTION_WEIGHT_SHEET_RE = re.compile(r"weight", re.IGNORECASE)
SECTION_WEIGHT_FIELDS = {
    "section": ["section"],
    "weight": ["weight", "allocation", "share"],
}
SECTION_CODE_RE = re.compile(r"^\s*([A-Za-z]+(?:\s*/\s*[A-Za-z]+)*)\s*\.")


def find_section_weight_sheet(
    wb: openpyxl.Workbook,
) -> "openpyxl.worksheet.worksheet.Worksheet | None":
    """The companion sheet SVC-PC-38-*/SVC-PC-52-* ship alongside a Grading Rubric whose
    own Points column is blank for every criterion (confirmed by inspecting
    SVC-PC-38-0-0_Grading_Rubric.xlsx and SVC-PC-52-1-0_Grading_Rubric.xlsx directly, then
    verified across all 14 tasks in both families with verify_section_match.py: 0 of 14
    have any Points value at all) -- weight is authored per-Section here instead (e.g.
    "D. Service period and attribution | 18%"), not per-criterion. Returns None when no
    such sheet exists, the normal case for every other rubric layout this module already
    handles; that None is the caller's signal that a blank-Points rubric truly has no
    weight source anywhere, not a reason to guess."""
    names = [n for n in wb.sheetnames if SECTION_WEIGHT_SHEET_RE.search(n)]
    return wb[names[0]] if names else None


def _section_code(text) -> "frozenset[str] | None":
    """The stable join key between a criteria row's own Section cell and the weighting
    sheet's Section cell is the leading letter code before the first '.', NOT the full
    text -- the two sheets restate the same section in different words. Confirmed on
    SVC-PC-38-0-0: the Rubric sheet's own Section reads "F. Pool reconciliation,
    capitalization discipline, and the ISO limit" while its Weighting & Notes sheet reads
    "F. Pool, capitalization discipline, and the ISO limit" for the identical section --
    matching by full text found 2 "missing" sections there and up to 9 on SVC-PC-38-5-0
    (verify_section_match.py), matching by this leading code found zero on any of the 14.
    The weighting sheet can also fold multiple rubric sections into one combined bucket:
    SVC-PC-38-1-0's weighting sheet has one "F/G. limit population and construction" row
    covering the Rubric sheet's separate "F. Award types..." and "G. Construction
    quality" sections, and SVC-PC-38-5-0 combines three ("C/G/I. cancellations, conflicts,
    construction"). Returned as a frozenset of every letter in the code so a subset check
    on either side finds the right bucket regardless of which side did the grouping."""
    m = SECTION_CODE_RE.match(str(text or ""))
    if not m:
        return None
    letters = frozenset(
        tok.strip().upper() for tok in m.group(1).split("/") if tok.strip()
    )
    return letters or None


def parse_section_weights(ws) -> "list[tuple[frozenset, float]]":
    """[(section-code-letters, weight-percent), ...] from a Weighting & Notes-style sheet,
    stopping naturally at the first row whose Section cell isn't itself coded "X. ..." --
    that is how the real per-section rows end and the sheet's own trailing "Total" /
    "Must-pass gates" / "Discrimination note" rows (none of which are themselves coded)
    get excluded without hardcoding those particular labels, which would break the moment
    a future workbook phrases its own trailing notes differently."""
    header_row, col_map = None, {}
    for row_idx in range(1, min(10, ws.max_row) + 1):
        cells = [
            str(c.value).strip().lower() if c.value is not None else ""
            for c in ws[row_idx]
        ]
        mapped: dict[int, str] = {}
        for col_idx, text in enumerate(cells, start=1):
            if not text:
                continue
            for field, substrings in SECTION_WEIGHT_FIELDS.items():
                if field in mapped.values():
                    continue
                if any(sub in text for sub in substrings):
                    mapped[col_idx] = field
                    break
        if {"section", "weight"} <= set(mapped.values()):
            header_row, col_map = row_idx, mapped
            break
    if header_row is None:
        return []

    out = []
    for row in ws.iter_rows(min_row=header_row + 1):
        values = {col_map[c.column]: c.value for c in row if c.column in col_map}
        letters = _section_code(values.get("section"))
        if letters is None:
            break
        pct_match = THRESHOLD_PERCENT_RE.search(str(values.get("weight") or ""))
        if not pct_match:
            continue
        out.append((letters, float(pct_match.group(1))))
    return out


def apply_section_weight_fallback(
    rows: list[dict], buckets: "list[tuple[frozenset, float]]"
) -> None:
    """Fill in row["points"] (currently None -- see parse_rows' blank-Points handling)
    from the matching Section's declared percentage on the Weighting & Notes sheet, split
    evenly across every criterion that maps into that bucket. A no-op when there is no
    such sheet at all (buckets == []) -- convert() tries a different fallback next (see
    apply_must_pass_zero_weight_fallback), since a blank Points column has more than one
    legitimate cause. Mutates rows in place; still raises ConversionError naming the
    offending row when buckets ARE declared but a specific row's own Section doesn't
    resolve to any of them -- that combination means the workbook itself is internally
    inconsistent, not that this mechanism doesn't apply -- the same "don't guess, flag for
    review" posture as every other ambiguity check in this module."""
    if not buckets:
        return
    unresolved = [r for r in rows if r["points"] is None]
    if not unresolved:
        return

    def bucket_for(letters: "frozenset"):
        for bucket_letters, weight in buckets:
            if letters <= bucket_letters:
                return bucket_letters, weight
        return None, None

    assignments = []  # (row, bucket_letters, weight)
    for row in unresolved:
        letters = _section_code(row["category"])
        if letters is None:
            raise ConversionError(
                f"row {row['criterion_id']!r} has blank Points and its Section "
                f"{row['category']!r} isn't coded 'X. ...' so no weight bucket applies"
            )
        bucket_letters, weight = bucket_for(letters)
        if bucket_letters is None:
            declared = [f"{'/'.join(sorted(b))} ({w}%)" for b, w in buckets]
            raise ConversionError(
                f"row {row['criterion_id']!r}'s section {row['category']!r} (code "
                f"{'/'.join(sorted(letters))}) matches no bucket on the weighting sheet: "
                f"{declared}"
            )
        assignments.append((row, bucket_letters, weight))

    bucket_size: dict[frozenset, int] = {}
    for _row, bucket_letters, _weight in assignments:
        bucket_size[bucket_letters] = bucket_size.get(bucket_letters, 0) + 1

    for row, bucket_letters, weight in assignments:
        row["points"] = weight / bucket_size[bucket_letters]


def apply_must_pass_zero_weight_fallback(rows: list[dict]) -> None:
    """Give every remaining blank-Points row that is must_pass a weight of exactly 0.0,
    rather than asking a weighting mechanism to explain a number that was never meant to
    exist. SVC-PC-21-0-0's own "Category Weights" sheet states the convention directly:
    "30 rules: 8 must-pass gates plus 22 scoring criteria", and its declared 100-point
    total (cross-checked against parse_rows' own output: exactly the 22 non-gate rows sum
    to 100) covers only the scored rows -- a must-pass GATE criterion is a binary
    pass/fail check (see grading_role_for and evaluate_release_outcome's hard
    BLOCKED-on-any-failed-gate rule) and legitimately carries no share of the
    weighted-mean scoring pool.

    Verified this is a consistent pattern, not a one-off guess, across every task it was
    found in (verify_gate_zero_points.py, run against SVC-PC-21-0-0 and the SVC-PC-73-*
    family before this function existed): every blank-Points row in SVC-PC-21-0-0 is
    must-pass and every must-pass row in it is blank-Points, with zero exceptions either
    way. SVC-PC-73-*'s own single blank-Points row per task turned out to be a different
    defect entirely -- a trailing footer row, not a criterion at all -- excluded upstream
    by parse_rows' no-digit-in-ID check, so it never reaches this function once that fix
    is in place; only a row that is NOT must-pass and still has no resolved weight is left
    for convert() to raise on, since that combination has no known legitimate explanation
    anywhere in this corpus."""
    for row in rows:
        if row["points"] is None and row["must_pass"]:
            row["points"] = 0.0


def parse_response_criteria(path: Path) -> "dict[str, dict] | None":
    """Claire's Rubric Response Criteria workbook -> {criterion_id: row dict},
    or None when the file is not that form at all (see the schema note in the body).
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
    try:
        header_row, col_map = find_header_row(
            ws, RESPONSE_CRITERIA_FIELDS, RESPONSE_CRITERIA_FIELDS_EXACT
        )
    except ConversionError:
        # No id column anywhere in the sheet. See the schema note below: this is a
        # differently-shaped workbook, not a broken one.
        return None
    fields = set(col_map.values())
    if "criterion_id" not in fields:
        return None
    # Three of the ten Final L2 tasks (SVC-PC-5-2-0, 10-1-0, 16-4-0) ship a file whose NAME
    # matches RESPONSE_CRITERIA_NAME_RE but whose content is a different artifact: a
    # strength/weakness annotation list keyed by S#, the same S1/S2 tokens the Grading
    # Rubric's own "Source" column cites. It is source commentary, not one row of
    # interpretation guidance per criterion, so there is nothing here to merge by
    # criterion_id and forcing a parse either fails outright or invents empty rows.
    #
    # find_response_criteria_file is already documented as OPTIONAL, and the caller already
    # treats a partial match as a warning rather than an error, so the honest result for a
    # workbook that is not this form is None. Returning it keeps the task buildable and
    # leaves the annotation file for whoever wants to wire S# refs up properly.
    if not (
        fields
        & {
            "lens",
            "satisfactory_response",
            "tolerance_rule",
            "pass_with_open_items",
            "blocked_if",
        }
    ):
        return None
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


# .csv and .json are graded deliverable formats, not incidental data. verifier_lib ships
# sources/csv.py and sources/json.py to read them. Leaving them out silently dropped golden
# files from the package, which oracle caught on 2026-09-08: SVC-PC-9-3-0 failed criterion
# r17, "Exactly the six named files ... no additional files", because
# Fulfillment_Units_CrossCheck.csv never made it out of the Golden folder. SVC-PC-9-5-0 lost
# three .json goldens the same way. Both scored otherwise-clean runs, so the only symptom was
# a manifest criterion failing for a reason that looked like a task defect and was ours.
#
# .xlsm belongs here too, and its absence is the same bug one layer up. Downstream already
# expects it: to_rewardkit._convert_xlsm_to_xlsx exists specifically to handle a macro-enabled
# golden, and verifier_lib/sources/xlsx.py accepts ".xlsx" or ".xlsm". Neither ever sees the
# file if this set drops it first, which is what happens to SVC-PC-3-7-0's
# Capitalization_Workbook.xlsm.
DELIVERABLE_EXTS = {
    ".docx",
    ".xlsx",
    ".xlsm",
    ".pptx",
    ".pdf",
    ".md",
    ".txt",
    ".csv",
    ".json",
}
GOLDEN_CONTAINER_RE = re.compile(
    r"^golden[ _](solution|response|deliverables?)$", re.IGNORECASE
)
LEAF_SUBTASK_RE = re.compile(r"^L1-\d+-\d+", re.IGNORECASE)
NON_DELIVERABLE_NAME_RE = re.compile(
    # NOT a bare "criteria" alternative: SVC-PC-52-4-0's real golden deliverable is
    # "Permitted_Instruments_and_Credit_Criteria.xlsx" -- a genuine business-content
    # filename that happens to contain the word "Criteria" ("Credit Criteria"), and
    # the bare alternative excluded it as if it were a stray rubric artifact,
    # producing "no golden-solution deliverable file found" for a task whose golden
    # file was sitting right there. Corpus-scanned (every Golden-folder filename
    # containing "criteria" anywhere in 00_fetched): this is the ONLY hit in the
    # whole corpus, so dropping the bare alternative and keeping the specific
    # "response(_| )criteria" pattern (which is what this exists to catch -- a stray
    # Response Criteria copy saved into the Golden folder) cannot let a real rubric
    # artifact back in anywhere else.
    r"rubric|prompt|response.?criteria",
    re.IGNORECASE,
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
    # match the source handlers verifier_lib actually ships, so a graded .csv or .json is
    # read as structured data rather than falling through to "any"
    ".csv": "csv",
    ".json": "json",
    # verifier_lib's xlsx source reads .xlsm directly, and to_rewardkit converts the file to
    # .xlsx on the way into the package, so the graded type is xlsx either way
    ".xlsm": "xlsx",
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
    # a macro-enabled workbook is a workbook. Without this it gets no format synonyms at all,
    # so a criterion saying "the workbook shows X" carries no signal toward it.
    ".xlsm": {"workbook", "databook", "spreadsheet", "model"},
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


# The default target for a criterion carrying no filename signal. A missing extension falls
# back to 9 and therefore loses to everything listed, which is how SVC-PC-3-7-0 put all 60 of
# its criteria on CFO_Capitalization_Certification.docx and none on Capitalization_Workbook.xlsm:
# .xlsm was absent here, so the quantitative deliverable could never win the default even
# though the docstring below says the most quantitative file should. Oracle then failed 28
# criteria reading "Drift Ventures is not mentioned anywhere in the document", because the
# cap-table content they grade lives in the workbook.
# Only .xlsm is added to the original table. Putting .csv and .json in here as well looked
# tidy and was a regression: .csv at 0 ties with .xlsx, and min() then resolves the tie by
# sorted filename, which moved SVC-PC-9-3-0's unsignaled criteria off
# Inventory_KPI_Dashboard_Restated.xlsx and onto Fulfillment_Units_CrossCheck.csv. That task
# scored 20 of 20 twice with the old assignment, so changing it risked a passing task for no
# stated reason. A missing extension still falls back to 9, which is the behaviour every task
# other than the .xlsm case was already relying on.
EXT_PRIORITY = {
    ".xlsx": 0,
    ".xlsm": 0,
    ".docx": 1,
    ".pptx": 2,
    ".md": 3,
    ".pdf": 4,
    ".txt": 5,
}


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

# A later revision of the template moved the input manifest OUT of the Read Me tab and onto
# its own sheet, so a workbook can declare every source file it needs and still parse as
# "0 declared input(s)". That is not cosmetic: declared_manifest_paths() is one of the three
# hydration sources, so the whole SVC-PC-9-* family built with an EMPTY environment/data on
# 2026-09-08, which is a package the model cannot do the task from.
DATA_MANIFEST_SHEET_RE = re.compile(r"data manifest", re.IGNORECASE)
DATA_MANIFEST_FIELDS = {
    "path": ["source file", "path and filename", "relative path", "filename"],
    "context": ["required records", "record, sheet", "page"],
    "rationale": ["why this source", "why included"],
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


def parse_data_manifest_sheet(wb: openpyxl.Workbook) -> list[dict]:
    """Input-manifest rows from a dedicated manifest SHEET, e.g. 'OS Data Manifest'.

    Returns entries in the same shape parse_read_me builds from the Read Me tab, so
    declared_manifest_paths() consumes them without knowing which layout produced them.

    Every row on this sheet is a source the evaluator states the task needs, so `included`
    is True; the sheet has no Included column to consult. Placeholder detection still runs,
    because an unfilled template row must not be hydrated as if it were a real path.
    """
    names = [n for n in wb.sheetnames if DATA_MANIFEST_SHEET_RE.search(n)]
    if not names:
        return []
    ws = wb[names[0]]

    header_row, col_map = None, {}
    for row_idx in range(1, min(30, ws.max_row + 1)):
        cells = [
            str(c.value).strip().lower() if c.value is not None else ""
            for c in ws[row_idx]
        ]
        mapped: dict[int, str] = {}
        for col_idx, text in enumerate(cells, start=1):
            if not text:
                continue
            for field, substrings in DATA_MANIFEST_FIELDS.items():
                if field in mapped.values():
                    continue
                if any(sub in text for sub in substrings):
                    mapped[col_idx] = field
                    break
        # the path column is the only one worth having; without it there is nothing to hydrate
        if "path" in mapped.values():
            header_row, col_map = row_idx, mapped
            break
    if header_row is None:
        return []

    out = []
    for row in ws.iter_rows(min_row=header_row + 1):
        values = {col_map[c.column]: c.value for c in row if c.column in col_map}
        path = str(values.get("path") or "").strip()
        if not path:
            continue
        out.append(
            {
                "path": path,
                "context": str(values.get("context") or "").strip(),
                "included": True,
                "is_placeholder": bool(PLACEHOLDER_RE.match(path)),
            }
        )
    return out


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

    # Fall back to a dedicated manifest sheet only when the Read Me tab declared nothing, so
    # a workbook using the original layout keeps exactly the entries it has today.
    if not input_manifest:
        input_manifest = parse_data_manifest_sheet(wb)

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

        prompt = f"{row['description']} Expected: {row['expected_value']}."
        if row["must_pass"]:
            prompt += " This is a must-pass criterion."
        if response_entry and response_entry.get("satisfactory_response"):
            prompt += f" Response criteria guidance: {response_entry['satisfactory_response']}"
        if response_entry and response_entry.get("blocked_if"):
            prompt += f" Blocked if: {response_entry['blocked_if']}"
        if tolerance:
            prompt += (
                f" Tolerance: within {tolerance['max_percent']}% only when population, "
                "period, unit, and basis all match; never average across a mismatched basis."
            )
        if row["claim_status"]:
            prompt += f" Claim status: {row['claim_status']}."

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
    check_unmapped_headers(ws, header_row, col_map, task_id)
    rows = parse_rows(ws, header_row, col_map)
    if not rows:
        raise ConversionError(f"zero parseable criteria rows in {rubric_path}")
    n_blank_points = sum(1 for r in rows if r["points"] is None)
    if n_blank_points:
        # A blank Points column has two distinct, unrelated legitimate causes in this
        # corpus, tried in order:
        #  1. SVC-PC-38-*/SVC-PC-52-*: every row's Points cell is blank by design; weight
        #     is authored per-Section on the companion "Weighting & Notes" sheet instead.
        #     See find_section_weight_sheet/apply_section_weight_fallback for the
        #     evidence.
        #  2. SVC-PC-21-0-0 (and structurally identical tasks): only the must-pass GATE
        #     rows are blank; those criteria carry no weight at all by design. See
        #     apply_must_pass_zero_weight_fallback for the evidence.
        # Neither is assumed -- a row still blank after both is a real ConversionError.
        weight_sheet = find_section_weight_sheet(wb)
        buckets = (
            parse_section_weights(weight_sheet) if weight_sheet is not None else []
        )
        if buckets:
            apply_section_weight_fallback(rows, buckets)
            print(
                f"  Points column blank for {n_blank_points}/{len(rows)} criteria -- "
                f"derived weight from {weight_sheet.title!r}'s per-section allocation"
            )
        remaining_blank = sum(1 for r in rows if r["points"] is None)
        if remaining_blank:
            apply_must_pass_zero_weight_fallback(rows)
            n_gate_defaulted = remaining_blank - sum(
                1 for r in rows if r["points"] is None
            )
            if n_gate_defaulted:
                print(
                    f"  {n_gate_defaulted} must-pass criteria carry no Points value -- "
                    "treated as zero-weight gates"
                )
        still_blank = [r["criterion_id"] for r in rows if r["points"] is None]
        if still_blank:
            raise ConversionError(
                f"criteria row(s) {still_blank} have blank Points, are not must-pass "
                "gates, and no usable section-weight sheet was found to derive weight "
                "from"
            )
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
        response_criteria = parse_response_criteria(response_criteria_path)
        if response_criteria is None:
            # named like a Response Criteria form, shaped like something else
            print(
                "  response criteria: skipped, not a criterion-keyed form "
                "(no ID column or none of the interpretation fields)"
            )
        else:
            unmatched = [
                r["criterion_id"]
                for r in rows
                if r["criterion_id"] not in response_criteria
            ]
            if unmatched:
                print(
                    f"  WARN: response criteria has no row for {unmatched}",
                    file=sys.stderr,
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
