"""Regression tests for tools/rubric_xlsx_to_verifier.py's header detection
and cell-value extraction.

Real-world incident (2026-09-02): task SVC-PC-1-3-0's rubric used a 7th,
previously-unsupported header vocabulary ("Criterion Type" / "Requirement" /
"Acceptance Standard" instead of "Tier" / "Description" / "Expected value").
"Criterion Type" matched the "description" field's bare "criterion" substring
before "tier" got a chance, so every criterion's description was reduced to
just its tier value ("Structural"/"Objective"/"Judgment") and the real
Requirement/Acceptance Standard text was dropped entirely (no field matched
either header) -- confirmed against the actual delivered rubric, which had
fully populated Requirement/Acceptance Standard columns the whole time.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"


def _load_rxv():
    spec = importlib.util.spec_from_file_location(
        "rubric_xlsx_to_verifier", TOOLS_DIR / "rubric_xlsx_to_verifier.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rubric_xlsx_to_verifier"] = module
    spec.loader.exec_module(module)
    return module


rxv = _load_rxv()


def _sheet_with_rows(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    return ws


def test_criterion_type_column_maps_to_tier_not_description():
    """SVC-PC-1-3-0's actual header row and first two data rows."""
    ws = _sheet_with_rows(
        [
            ["SVC-PC-1-3-0 Grading Rubric"],
            ["Maximum 100 points"],
            [],
            [
                "Criterion ID", "Category", "Criterion Type", "Requirement",
                "Acceptance Standard", "Points", "Must-pass", "Source",
            ],
            [
                "C001", "Deliverable structure", "Structural",
                "Delivered as a working .xlsx workbook that opens.",
                "One .xlsx present; opens cleanly", 2.0, "Yes", "1, 2",
            ],
            [
                "C005", "Monthly COGS", "Objective", "FY COGS correct.",
                "423359", 7.0, "Yes", "9, 10, 11",
            ],
        ]
    )
    header_row, col_map = rxv.find_header_row(ws)
    rows = rxv.parse_rows(ws, header_row, col_map)

    assert col_map[3] == "tier"
    assert col_map[4] == "description"
    assert col_map[5] == "expected_value"

    c001, c005 = rows
    assert c001["tier"] == "Structural"
    assert c001["description"] == "Delivered as a working .xlsx workbook that opens."
    assert c001["expected_value"] == "One .xlsx present; opens cleanly"
    assert c005["expected_value"] == "423359"


def test_bare_criterion_header_variant_still_maps_to_description():
    """Pre-existing task_svc-pc-9-* family variant must keep working: a bare
    "Criterion" header (not "Criterion Type") is this variant's own
    description column."""
    ws = _sheet_with_rows(
        [
            [
                "ID", "Category", "Tier", "Criterion",
                "Expected value + source file", "Points", "Must-pass?",
            ],
            ["C1", "Cat", "objective", "Some criterion text.", "42", 1.0, "No"],
        ]
    )
    header_row, col_map = rxv.find_header_row(ws)
    rows = rxv.parse_rows(ws, header_row, col_map)

    assert col_map[4] == "description"
    assert rows[0]["description"] == "Some criterion text."
    assert rows[0]["expected_value"] == "42"


def test_expected_value_of_literal_zero_is_not_dropped():
    """Real-world incident: SVC-PC-5-5-0 criterion E05 ("Insolvency ($0)
    buffer about $0") and SVC-PC-5-4-0 criterion Q17 ("P(insolvency,
    trough<0) reported about 0%.") both have an authored expected_value of
    exactly 0 -- `str(v or "").strip()` treats 0 as falsy and silently
    produces an empty string, indistinguishable from a genuinely blank cell."""
    ws = _sheet_with_rows(
        [
            ["ID", "Category", "Tier", "Description", "Expected value", "Points", "Must-pass?"],
            ["E05", "Buffer", "objective", "Insolvency ($0) buffer about $0.", 0, 1.0, "No"],
        ]
    )
    header_row, col_map = rxv.find_header_row(ws)
    rows = rxv.parse_rows(ws, header_row, col_map)

    assert rows[0]["expected_value"] == "0"


def test_expected_value_genuinely_blank_stays_blank():
    """A truly empty Expected-value cell must still come through as "" (so
    the existing check_rubric.py rubric_criteria_not_blank gate can catch
    it) -- the literal-zero fix must not mask real blanks as some other
    placeholder value."""
    ws = _sheet_with_rows(
        [
            ["ID", "Category", "Tier", "Description", "Expected value", "Points", "Must-pass?"],
            ["R012", "Structure", "structural", "CC revenue computed via SUMPRODUCT.", None, 2.0, "No"],
        ]
    )
    header_row, col_map = rxv.find_header_row(ws)
    rows = rxv.parse_rows(ws, header_row, col_map)

    assert rows[0]["expected_value"] == ""


def _minimal_row(**overrides):
    row = {
        "criterion_id": "C001",
        "category": "Cat",
        "tier": "objective",
        "description": "FY COGS correct.",
        "expected_value": "423359",
        "points": 1.0,
        "must_pass": False,
        "claim_status": None,
    }
    row.update(overrides)
    return row


def test_build_verifier_json_does_not_invent_expected_label():
    """Same fix, same reasoning as to_rewardkit.py's _svc_criteria: no
    invented "Expected:" label -- the source rubric's own Description and
    Expected-value text, concatenated as-is."""
    verifier = rxv.build_verifier_json(
        "task_1", [_minimal_row()], ["report.docx"]
    )
    prompt = verifier["verifiers"][0]["assertion"]["rubric"]["prompt"]

    assert prompt == "FY COGS correct. 423359"
    assert "Expected:" not in prompt


def test_build_verifier_json_leaves_description_untouched_when_expected_value_blank():
    """A blank expected_value must not grow a dangling "... Expected: .\""""
    verifier = rxv.build_verifier_json(
        "task_1", [_minimal_row(expected_value="")], ["report.docx"]
    )
    prompt = verifier["verifiers"][0]["assertion"]["rubric"]["prompt"]

    assert prompt == "FY COGS correct."
    assert "Expected" not in prompt


def test_build_verifier_json_drops_must_pass_and_claim_status_sentences():
    """must_pass and claim_status carry zero unique content beyond what
    metadata.must_pass/metadata.claim_status already store structurally --
    least-change fix: remove the invented sentences entirely rather than
    just de-labeling them, since there's no real per-criterion wording
    underneath either one."""
    verifier = rxv.build_verifier_json(
        "task_1",
        [
            _minimal_row(must_pass=True, claim_status="Open item"),
            _minimal_row(criterion_id="C002"),
        ],
        ["report.docx"],
    )
    v = verifier["verifiers"][0]
    prompt = v["assertion"]["rubric"]["prompt"]

    assert prompt == "FY COGS correct. 423359"
    assert "must-pass" not in prompt.lower()
    assert "claim status" not in prompt.lower()
    # the structured signal still reaches downstream tools via metadata
    assert v["metadata"]["must_pass"] is True
    assert v["metadata"]["claim_status"] == "Open item"


def test_build_verifier_json_keeps_response_criteria_content_without_label():
    """Response-criteria guidance and blocked-if ARE real, substantive
    human-authored text (Claire's Response Criteria workbook) -- unlike
    must_pass/claim_status, the content itself is kept, just without an
    invented label glued in front."""
    verifier = rxv.build_verifier_json(
        "task_1",
        [_minimal_row()],
        ["report.docx"],
        response_criteria={
            "C001": {
                "satisfactory_response": "Ties to the trusted monthly series.",
                "blocked_if": "COGS is negative in any month.",
            }
        },
    )
    prompt = verifier["verifiers"][0]["assertion"]["rubric"]["prompt"]

    assert "Ties to the trusted monthly series." in prompt
    assert "COGS is negative in any month." in prompt
    assert "Response criteria guidance:" not in prompt
    assert "Blocked if:" not in prompt
