"""Safety checks for the SVC-PC source-to-RewardKit builder."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import openpyxl
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"


def _load_converter():
    sys.path.insert(0, str(TOOLS_DIR))
    spec = importlib.util.spec_from_file_location(
        "svc_pc_batch_convert", TOOLS_DIR / "svc_pc_batch_convert.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["svc_pc_batch_convert"] = module
    spec.loader.exec_module(module)
    return module


converter = _load_converter()


def _paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    input_root = tmp_path / "input"
    corpus_root = tmp_path / "corpus"
    output_root = tmp_path / "output"
    scratch_root = tmp_path / "scratch"
    input_root.mkdir()
    corpus_root.mkdir()
    return input_root, corpus_root, output_root, scratch_root


def _command(
    input_root: Path, corpus_root: Path, output_root: Path, scratch_root: Path
) -> list[str]:
    return [
        "--input-root",
        str(input_root),
        "--corpus-root",
        str(corpus_root),
        "--output-root",
        str(output_root),
        "--scratch-root",
        str(scratch_root),
        "--python",
        sys.executable,
    ]


def test_parser_accepts_explicit_paths_selection_and_reset(tmp_path):
    input_root, corpus_root, output_root, scratch_root = _paths(tmp_path)

    args = converter.parse_args(
        _command(input_root, corpus_root, output_root, scratch_root)
        + ["--only", "SVC-PC-2-3-0,SVC-PC-3-6-0", "--preflight", "--reset"]
    )

    assert args.input_root == input_root
    assert args.corpus_root == corpus_root
    assert args.output_root == output_root
    assert args.scratch_root == scratch_root
    assert args.python == Path(sys.executable)
    assert args.only == "SVC-PC-2-3-0,SVC-PC-3-6-0"
    assert args.preflight is True
    assert args.reset is True


def test_missing_input_does_not_reset_existing_outputs(tmp_path):
    _, corpus_root, output_root, scratch_root = _paths(tmp_path)
    ready = output_root / "03_dataos_ready"
    ready.mkdir(parents=True)
    sentinel = ready / "keep.txt"
    sentinel.write_text("preserve me", encoding="utf-8")

    rc = converter.main(
        _command(tmp_path / "missing-input", corpus_root, output_root, scratch_root)
        + ["--reset"]
    )

    assert rc == 2
    assert sentinel.read_text(encoding="utf-8") == "preserve me"


def test_missing_selected_task_does_not_reset_existing_outputs(tmp_path):
    input_root, corpus_root, output_root, scratch_root = _paths(tmp_path)
    (input_root / "SVC-PC-2-3-0").mkdir()
    ready = output_root / "03_dataos_ready"
    ready.mkdir(parents=True)
    sentinel = ready / "keep.txt"
    sentinel.write_text("preserve me", encoding="utf-8")

    rc = converter.main(
        _command(input_root, corpus_root, output_root, scratch_root)
        + ["--only", "SVC-PC-99-9-9", "--reset"]
    )

    assert rc == 2
    assert sentinel.read_text(encoding="utf-8") == "preserve me"


def test_preflight_does_not_create_output_or_scratch(tmp_path, capsys):
    input_root, corpus_root, output_root, scratch_root = _paths(tmp_path)
    (input_root / "SVC-PC-2-3-0").mkdir()

    rc = converter.main(
        _command(input_root, corpus_root, output_root, scratch_root)
        + ["--only", "SVC-PC-2-3-0", "--preflight"]
    )

    assert rc == 0
    assert "staged task folders: ok  1" in capsys.readouterr().out
    assert not output_root.exists()
    assert not scratch_root.exists()


def test_normal_build_skips_existing_task_output(tmp_path, monkeypatch):
    input_root, corpus_root, output_root, scratch_root = _paths(tmp_path)
    (input_root / "SVC-PC-2-3-0").mkdir()
    ready_task = output_root / "03_dataos_ready" / "SVC-PC-2-3-0"
    ready_task.mkdir(parents=True)
    sentinel = ready_task / "keep.txt"
    sentinel.write_text("preserve me", encoding="utf-8")
    monkeypatch.setattr(converter.he, "build_corpus_index", lambda _: {})

    rc = converter.main(
        _command(input_root, corpus_root, output_root, scratch_root)
        + ["--only", "SVC-PC-2-3-0"]
    )

    assert rc == 0
    assert sentinel.read_text(encoding="utf-8") == "preserve me"
    assert not (scratch_root / "SVC-PC-2-3-0").exists()


def test_reset_only_replaces_selected_task_output(tmp_path, monkeypatch):
    input_root, corpus_root, output_root, scratch_root = _paths(tmp_path)
    (input_root / "SVC-PC-2-3-0").mkdir()
    ready_selected = output_root / "03_dataos_ready" / "SVC-PC-2-3-0"
    ready_other = output_root / "03_dataos_ready" / "SVC-PC-3-6-0"
    messy_selected = output_root / "03_dataos_messy" / "SVC-PC-2-3-0"
    for directory in (ready_selected, ready_other, messy_selected):
        directory.mkdir(parents=True)
    (ready_selected / "old.txt").write_text("old", encoding="utf-8")
    (ready_other / "keep.txt").write_text("keep", encoding="utf-8")
    (messy_selected / "old.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(converter.he, "build_corpus_index", lambda _: {})

    def fake_process(task_dir, scratch, corpus_index, persona_slugs, python):
        rewardkit = scratch / "rewardkit"
        rewardkit.mkdir()
        (rewardkit / "built.txt").write_text("new", encoding="utf-8")
        return rewardkit, {
            "task_id": task_dir.name,
            "resolved": [],
            "not_found": [],
            "ambiguous": [],
            "placeholder": False,
        }

    monkeypatch.setattr(converter, "process_task", fake_process)

    rc = converter.main(
        _command(input_root, corpus_root, output_root, scratch_root)
        + ["--only", "SVC-PC-2-3-0", "--reset"]
    )

    assert rc == 0
    assert not (ready_selected / "old.txt").exists()
    assert (ready_selected / "built.txt").read_text(encoding="utf-8") == "new"
    assert (ready_other / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not messy_selected.exists()


def test_report_path_preserves_existing_report(tmp_path):
    report = tmp_path / "incidents.md"
    report.write_text("first run", encoding="utf-8")

    assert converter._report_path(report) == tmp_path / "incidents_2.md"


def _load_rubric_module():
    spec = importlib.util.spec_from_file_location(
        "rubric_xlsx_to_verifier", TOOLS_DIR / "rubric_xlsx_to_verifier.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rubric_xlsx_to_verifier"] = module
    spec.loader.exec_module(module)
    return module


def test_header_row_skips_wordy_subtitle(tmp_path):
    """A merged one-cell subtitle packing several header keywords must not be
    mistaken for the header row (SVC-PC-1-4-0 pilot-build failure, 2026-08-27)."""
    import openpyxl

    rubric = _load_rubric_module()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rubric"
    ws["A1"] = "SVC-PC-1-4-0 Grading Rubric"
    ws.merge_cells("A1:G1")
    ws["A2"] = (
        "Maximum 100 points. 6 substantive must-pass criteria. A failed "
        "must-pass criterion makes the response unacceptable regardless of "
        "point total."
    )
    ws.merge_cells("A2:G2")
    header = [
        "Criterion ID",
        "Category",
        "Tier",
        "Description",
        "Expected value",
        "Points",
        "Must-pass?",
    ]
    for col, value in enumerate(header, start=1):
        ws.cell(4, col).value = value
    row = ["C001", "Deliverable structure", "Structural", "Delivered as xlsx", "One xlsx present", "2", "Yes"]
    for col, value in enumerate(row, start=1):
        ws.cell(5, col).value = value

    header_row, col_map = rubric.find_header_row(ws)

    assert header_row == 4
    assert "criterion_id" in col_map.values()
    assert "points" in col_map.values()
# ── Claire Central Task Platform template compatibility ────────────────────
# The six changes scoped by
# turing-context/ekw/central-task-platform-rubric-template-evaluation-2026-08-26.md:
# Read Me parsing, input-manifest staging, Response Criteria mapping,
# status-vocabulary handling, structured tolerance, and the must-pass hard
# gate. The fixtures below build minimal synthetic workbooks shaped like
# Claire's actual template (confirmed by inspection of the real
# SVC-PC-2-3-0_Grading_Rubric.xlsx / _Response_Criteria.xlsx swap-in test
# files under C:/ekwqc/claire-template-test/) -- same Read Me section
# headers and Rubric Grading Form / Rubric Response Criteria Form column
# names, trimmed to two criteria (one must-pass gate, one Open-item content
# row) instead of the real template's fifteen.


def _write_grading_rubric_xlsx(path: Path, gate_ids: list[str]) -> None:
    wb = openpyxl.Workbook()
    read_me = wb.active
    read_me.title = "Read Me"
    gate_sentence = "One substantive gate applies: " + " and ".join(gate_ids) + "."
    for row in [
        ["SVC-PC-TEST | Grading Rubric"],
        ["One 100-point scoring form."],
        [],
        ["PACKAGE CONTROL SUMMARY"],
        ["Item", "Requirement"],
        [
            "Release threshold",
            "A score of at least 90% (90 of 100 points) is necessary.",
        ],
        ["Permitted release outcomes", "PASS; PASS WITH OPEN ITEMS; BLOCKED."],
        ["Must-pass gates", gate_sentence],
        [],
        ["INPUT MANIFEST \u2014 CORPUS DATA ONLY"],
        [
            "No.",
            "Exact Corpus Data relative path and filename",
            "Relevant record, sheet, or page",
            "Permitted task use",
            "Included?",
        ],
        [1, "Journal.csv", "All entries", "Read only", "Yes"],
        [2, "[Enter exact path and filename]", "[Enter record]", "[Enter use]", "No"],
        [],
        ["A folder name alone is not an input."],
        [],
        ["EXPECTED VALUE SETUP"],
        [
            "Criterion",
            "Material value or finding",
            "Expected value, range, or evidence test",
            "Source or method definition",
            "Population, period, unit, and basis",
            "Tolerance",
            "If unresolved",
        ],
        [
            "C01",
            "Revenue",
            "$100,000",
            "GL export",
            "FY21, USD, accrual",
            "0% to \u00b15% only if all four attributes match",
            "Open item or Not evidenced",
        ],
        [
            "C02",
            "Headcount",
            "Open item",
            "n/a",
            "n/a",
            "No tolerance across different bases",
            "Open item",
        ],
        [],
        ["A mixed-basis comparison fails."],
        [],
        ["STATUS VOCABULARY \u2014 ONE STATUS FOR EACH MATERIAL CLAIM"],
        ["Status", "Meaning", "Required trace fields"],
        [
            "Confirmed",
            "Directly supported by an identified source.",
            "Source, period, owner.",
        ],
        [
            "Open item",
            "Material question that remains unresolved.",
            "Trace, owner, timing.",
        ],
        [],
        ["A reviewer assesses the evidence."],
    ]:
        read_me.append(row)

    form = wb.create_sheet("Rubric Grading Form")
    for row in [
        ["Rubric Grading Form | 100 points"],
        ["Score each row whole."],
        [],
        [
            "ID",
            "Lens",
            "Criterion",
            "Expected result or check",
            "Available points",
            "Reviewer score",
            "Must-pass gate",
            "Gate result",
            "Issue status",
        ],
        [
            "F01",
            "Form",
            "Input provenance",
            "Every input is identified.",
            40,
            None,
            "Yes" if "F01" in gate_ids else "No",
            "Not assessed",
            "Not assessed",
        ],
        [
            "C01",
            "Content",
            "Primary value",
            "Matches the configured record.",
            30,
            None,
            "Yes" if "C01" in gate_ids else "No",
            "Not assessed",
            "Not assessed",
        ],
        [
            "C02",
            "Content",
            "Headcount check",
            "Matches the configured record.",
            30,
            None,
            "No",
            "Not assessed",
            "Not assessed",
        ],
    ]:
        form.append(row)

    wb.save(path)


def _write_response_criteria_xlsx(path: Path) -> None:
    wb = openpyxl.Workbook()
    wb.active.title = "Read Me"
    form = wb.create_sheet("Rubric Response Criteria Form")
    for row in [
        ["Rubric Response Criteria Form | 100 points"],
        ["One concise interpretation row for each scoring criterion."],
        [],
        [
            "ID",
            "Lens",
            "Criterion",
            "Satisfactory response and check",
            "Tolerance or review rule",
            "PASS WITH OPEN ITEMS",
            "BLOCKED if",
            "Points",
            "Must-pass gate",
        ],
        [
            "F01",
            "Form",
            "Input provenance",
            "Every input is identified by exact path and permitted use.",
            "Structural control: met or not met.",
            "A minor presentation correction remains.",
            "A required input is absent.",
            40,
            "Yes \u2014 failure blocks release",
        ],
        [
            "C01",
            "Content",
            "Primary value",
            "Matches the GL export.",
            "\u00b15% applies only to the same population, period, unit, and basis.",
            "Comparable exports differ within the band.",
            "The configured value is not met.",
            30,
            "No \u2014 scored under the contract",
        ],
    ]:
        form.append(row)
    wb.save(path)


def test_extract_criterion_ids_handles_prose_and_dash_ranges():
    rxv = converter.rxv

    assert rxv.extract_criterion_ids("F01 through F07 and C01, C03, C04, and C05") == [
        "F01",
        "F02",
        "F03",
        "F04",
        "F05",
        "F06",
        "F07",
        "C01",
        "C03",
        "C04",
        "C05",
    ]
    assert rxv.extract_criterion_ids("C03\u2013C05") == ["C03", "C04", "C05"]
    assert rxv.extract_criterion_ids("C01") == ["C01"]


def test_parse_read_me_reads_manifest_expected_values_and_release_policy(tmp_path):
    rxv = converter.rxv
    rubric_path = tmp_path / "SVC-PC-TEST_Grading_Rubric.xlsx"
    _write_grading_rubric_xlsx(rubric_path, gate_ids=["F01"])

    wb = openpyxl.load_workbook(rubric_path, data_only=True)
    read_me = rxv.parse_read_me(wb)

    assert read_me is not None
    included = [
        e["path"]
        for e in read_me["input_manifest"]
        if e["included"] and not e["is_placeholder"]
    ]
    assert included == ["Journal.csv"]

    assert read_me["expected_value_setup"]["C01"]["claim_status"] is None
    assert read_me["expected_value_setup"]["C02"]["claim_status"] == "Open item"

    assert read_me["release_policy"]["score_threshold_percent"] == 90.0
    assert read_me["release_policy"]["gate_ids"] == ["F01"]
    assert {row["status"] for row in read_me["status_vocabulary"]} == {
        "Confirmed",
        "Open item",
    }


def test_parse_read_me_returns_none_without_a_read_me_tab(tmp_path):
    rxv = converter.rxv
    path = tmp_path / "no_read_me.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Rubric Grading Form"
    wb.save(path)

    assert rxv.parse_read_me(openpyxl.load_workbook(path)) is None


def test_check_gate_count_raises_on_mismatch_and_passes_on_match():
    rxv = converter.rxv
    rows = [
        {"criterion_id": "F01", "must_pass": True},
        {"criterion_id": "C01", "must_pass": False},
    ]

    with pytest.raises(rxv.ConversionError, match="must-pass gate mismatch"):
        rxv.check_gate_count({"release_policy": {"gate_ids": ["F01", "C05"]}}, rows)

    rxv.check_gate_count(
        {"release_policy": {"gate_ids": ["F01"]}}, rows
    )  # must not raise
    rxv.check_gate_count(
        {"release_policy": {"gate_ids": []}}, rows
    )  # undeclared -- skipped


def test_normalize_weights_zeroes_open_item_and_keeps_sum_to_one():
    rxv = converter.rxv
    rows = [
        {"criterion_id": "F01", "points": 10.0, "claim_status": None},
        {"criterion_id": "C01", "points": 10.0, "claim_status": None},
        {"criterion_id": "C02", "points": 80.0, "claim_status": "Open item"},
    ]

    weights = rxv.normalize_weights(rows)

    assert weights[-1] == 0.0
    assert weights[0] == pytest.approx(0.5)
    assert sum(weights) == pytest.approx(1.0)


def test_build_verifier_json_carries_must_pass_tolerance_and_response_guidance():
    rxv = converter.rxv
    rows = [
        {
            "criterion_id": "C01",
            "category": "Content",
            "tier": "",
            "description": "Primary value",
            "expected_value": "$100,000",
            "points": 100.0,
            "must_pass": True,
            "claim_status": None,
        },
    ]
    read_me = {
        "input_manifest": [],
        "expected_value_setup": {
            "C01": {
                "tolerance": "0% to \u00b15% only if all four attributes match",
                "population_period_unit_basis": "FY21, USD, accrual",
                "claim_status": None,
            },
        },
        "status_vocabulary": [],
        "release_policy": {
            "score_threshold_percent": 90.0,
            "permitted_outcomes": "",
            "release_threshold_text": "",
            "gate_ids": ["C01"],
        },
    }
    response_criteria = {
        "C01": {
            "satisfactory_response": "Matches the GL export.",
            "blocked_if": "Value is wrong.",
        }
    }

    verifier = rxv.build_verifier_json(
        "T", rows, ["deliverable.docx"], read_me, response_criteria
    )

    v = verifier["verifiers"][0]
    assert v["metadata"]["must_pass"] is True
    assert v["metadata"]["tolerance"]["max_percent"] == 5.0
    assert v["metadata"]["tolerance"]["requires_matching"] == [
        "population",
        "period",
        "unit",
        "basis",
    ]
    assert "Matches the GL export." in v["assertion"]["rubric"]["prompt"]
    assert verifier["read_me_contract"] is read_me


def test_parse_response_criteria_keys_rows_by_criterion_id(tmp_path):
    rxv = converter.rxv
    resp_path = tmp_path / "SVC-PC-TEST_Response_Criteria.xlsx"
    _write_response_criteria_xlsx(resp_path)

    parsed = rxv.parse_response_criteria(resp_path)

    assert set(parsed) == {"F01", "C01"}
    assert "GL export" in parsed["C01"]["satisfactory_response"]
    assert parsed["F01"]["must_pass"].startswith("Yes")


def test_find_response_criteria_file_is_optional(tmp_path):
    rxv = converter.rxv
    task_dir = tmp_path / "SVC-PC-TEST"
    task_dir.mkdir()

    assert rxv.find_response_criteria_file(task_dir) is None

    resp_path = task_dir / "SVC-PC-TEST_Response_Criteria.xlsx"
    _write_response_criteria_xlsx(resp_path)

    assert rxv.find_response_criteria_file(task_dir) == resp_path


def test_evaluate_release_outcome_blocks_on_failed_gate_and_flags_open_items():
    rxv = converter.rxv
    verifier = {
        "read_me_contract": {"release_policy": {"score_threshold_percent": 90.0}},
        "verifiers": [
            {"name": "v1", "metadata": {"must_pass": True, "weight": 0.5}},
            {
                "name": "v2",
                "metadata": {
                    "must_pass": False,
                    "weight": 0.5,
                    "claim_status": "Open item",
                },
            },
        ],
    }

    assert (
        rxv.evaluate_release_outcome(verifier, {"v1": True, "v2": True})
        == "PASS WITH OPEN ITEMS"
    )
    assert (
        rxv.evaluate_release_outcome(verifier, {"v1": False, "v2": True}) == "BLOCKED"
    )


def test_convert_end_to_end_with_claire_template_shape(tmp_path):
    rxv = converter.rxv
    task_dir = tmp_path / "SVC-PC-TEST"
    task_dir.mkdir()
    _write_grading_rubric_xlsx(
        task_dir / "SVC-PC-TEST_Grading_Rubric.xlsx", gate_ids=["F01"]
    )
    _write_response_criteria_xlsx(task_dir / "SVC-PC-TEST_Response_Criteria.xlsx")
    (task_dir / "SVC-PC-TEST_Prompt.txt").write_text("Do the task.", encoding="utf-8")
    golden = task_dir / "Golden Solution"
    golden.mkdir()
    (golden / "Deliverable.docx").write_bytes(b"x")

    verifier = rxv.convert(task_dir)

    assert verifier["read_me_contract"]["release_policy"]["gate_ids"] == ["F01"]
    weight_sum = round(sum(v["metadata"]["weight"] for v in verifier["verifiers"]), 4)
    assert weight_sum == 1.0

    by_tag = {v["metadata"]["tag"]: v for v in verifier["verifiers"]}
    assert by_tag["f01"]["metadata"]["must_pass"] is True
    assert by_tag["c01"]["metadata"]["tolerance"]["max_percent"] == 5.0
    assert "Matches the GL export." in by_tag["c01"]["assertion"]["rubric"]["prompt"]
    assert by_tag["c02"]["metadata"]["claim_status"] == "Open item"
    assert by_tag["c02"]["metadata"]["weight"] == 0.0


def test_hydrate_stages_declared_manifest_path(tmp_path):
    he = converter.he
    task_dir = tmp_path / "SVC-PC-TEST"
    task_dir.mkdir()
    _write_grading_rubric_xlsx(
        task_dir / "SVC-PC-TEST_Grading_Rubric.xlsx", gate_ids=["F01"]
    )
    (task_dir / "SVC-PC-TEST_Prompt.txt").write_text(
        "Prompt names no files.", encoding="utf-8"
    )
    golden = task_dir / "Golden Solution"
    golden.mkdir()
    (golden / "Deliverable.docx").write_bytes(b"x")

    corpus_file = tmp_path / "corpus_root" / "Journal.csv"
    corpus_file.parent.mkdir()
    corpus_file.write_text("date,amount\n", encoding="utf-8")
    corpus_index = {"journal.csv": [corpus_file]}

    out_dir = tmp_path / "staged"
    report = he.hydrate(task_dir, corpus_index, set(), out_dir)

    assert report["manifest_declared_count"] == 1
    assert any(r.startswith("manifest:") for r in report["resolved"])
    assert (out_dir / "Journal.csv").is_file()


def test_hydrate_leaves_no_input_marker_when_manifest_is_all_placeholders(tmp_path):
    he = converter.he
    task_dir = tmp_path / "SVC-PC-TEST"
    task_dir.mkdir()
    # No gate_ids passed to the rubric writer's manifest: reuse the helper's
    # default second manifest row (placeholder, Included=No) by asking for a
    # gate list that leaves the manifest untouched -- Journal.csv (row 1) is
    # still Included=Yes here, so blank it out for this specific case.
    _write_grading_rubric_xlsx(
        task_dir / "SVC-PC-TEST_Grading_Rubric.xlsx", gate_ids=["F01"]
    )
    wb_path = task_dir / "SVC-PC-TEST_Grading_Rubric.xlsx"
    wb = openpyxl.load_workbook(wb_path)
    ws = wb["Read Me"]
    for row in ws.iter_rows():
        if row[0].value == 1 and row[1].value == "Journal.csv":
            row[4].value = "No"
    wb.save(wb_path)
    (task_dir / "SVC-PC-TEST_Prompt.txt").write_text(
        "Prompt names no files.", encoding="utf-8"
    )
    golden = task_dir / "Golden Solution"
    golden.mkdir()
    (golden / "Deliverable.docx").write_bytes(b"x")

    out_dir = tmp_path / "staged"
    report = he.hydrate(task_dir, {}, set(), out_dir)

    assert report["manifest_declared_count"] == 0
    assert report["placeholder"] is True
    assert (out_dir / "_no_input_files_required.txt").is_file()


def test_process_task_dvc_fullcorpus_routes_to_assemble_flag_not_source_dir(tmp_path):
    """Regression: process_task() built a correct per-branch `assemble_args`
    list, but the actual subprocess.run() call a few lines below it ignored
    that list and hardcoded --source-dir unconditionally. `source_dir` is
    only ever assigned in the non-DVC branch, so the dvc_fullcorpus=True path
    raised NameError before ever reaching assemble_task.py. Confirm both
    branches now run for real (through the actual assemble_task.py and
    to_rewardkit.py subprocesses, not mocks) and route to the correct flag.

    Also confirms the DVC pointer is now unconditional (assemble_task.py no
    longer gates it behind --dvc-fullcorpus): both branches' Dockerfiles must
    carry the `dvc pull` block, even the one that never sets the
    `_FULLCORPUS` marker -- a selective-hydration miss on a real task should
    never again leave that task's environment unreachable, which is exactly
    what happened on cirrus-y1-task-svc-pc-47-3-0 and svc-pc-53-2-0 before
    this fix."""
    task_dir = tmp_path / "SVC-PC-TEST"
    task_dir.mkdir()
    _write_grading_rubric_xlsx(
        task_dir / "SVC-PC-TEST_Grading_Rubric.xlsx", gate_ids=["F01"]
    )
    _write_response_criteria_xlsx(task_dir / "SVC-PC-TEST_Response_Criteria.xlsx")
    (task_dir / "SVC-PC-TEST_Prompt.txt").write_text("Do the task.", encoding="utf-8")
    golden = task_dir / "Golden Solution"
    golden.mkdir()
    (golden / "Deliverable.docx").write_bytes(b"x")

    python = Path(sys.executable)

    # Non-DVC path (existing behavior) must still work unchanged, and must
    # now ALSO carry the DVC pointer/Dockerfile block unconditionally.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    rewardkit_out, report = converter.process_task(task_dir, scratch, {}, set(), python)
    assert rewardkit_out.is_dir()
    assert "dvc_fullcorpus" not in report
    dockerfile = (rewardkit_out / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert "dvc pull" in dockerfile

    # DVC full-corpus path -- the one that previously raised NameError.
    (task_dir / "_FULLCORPUS").touch()
    scratch2 = tmp_path / "scratch2"
    scratch2.mkdir()
    rewardkit_out2, report2 = converter.process_task(task_dir, scratch2, {}, set(), python)
    assert rewardkit_out2.is_dir()
    assert report2.get("dvc_fullcorpus") is True
    dockerfile2 = (rewardkit_out2 / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert "dvc pull" in dockerfile2
