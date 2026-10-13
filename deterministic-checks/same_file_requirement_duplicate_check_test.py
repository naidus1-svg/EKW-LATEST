#!/usr/bin/env python3
"""Unit tests for same_file_requirement_duplicate_check.py. Synthetic fixtures modeled
directly on the real shapes this check was calibrated against 2026-09-16 (see that module's
own docstring "Real calibration" for the real task ids and real corpus numbers): SVC-PC-56-4-0
(same-file exact requirement match, confirmed genuine), SVC-PC-41-0-0 (cross-file same value,
confirmed benign), SVC-PC-56-1-0 (verbatim-quote-check template, confirmed false positive,
now excluded). Does NOT make any LLM call or read the real corpus; all fixtures are
hand-written, synthetic judge.toml text.

Run:
    python deterministic-checks/same_file_requirement_duplicate_check_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from same_file_requirement_duplicate_check import analyze_task


def _write_judge_toml(path: Path, criteria: list[tuple[str, str, float]]) -> None:
    lines = ["[judge]", 'judge = "test"', 'files = ["test.xlsx"]', "weight = 1.0", ""]
    for cname, desc, weight in criteria:
        lines.append("[[criterion]]")
        lines.append(f'name = "{cname}"')
        lines.append(f"description = '''{desc}'''")
        lines.append('type = "binary"')
        lines.append(f"weight = {weight}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _make_task(
    root: Path, name: str, files: dict[str, list[tuple[str, str, float]]]
) -> Path:
    task = root / name
    tests = task / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    for deliv_name, criteria in files.items():
        d = tests / deliv_name
        d.mkdir(exist_ok=True)
        _write_judge_toml(d / "judge.toml", criteria)
    return task


def test_same_file_exact_requirement_flags():
    """SVC-PC-56-4-0's real shape: same file, identical requirement clause, different Expected
    text. Must fire, fail-tier."""
    with tempfile.TemporaryDirectory(prefix="_sfrd_test_") as tmp:
        root = Path(tmp)
        task = _make_task(
            root,
            "SYN-56-4-0",
            {
                "deliverables_01": [
                    (
                        "r001",
                        "States that GOTS certifies the cotton shell and inner chamber of the "
                        "pillow Expected: GOTS covers the cotton shell and inner chamber, not "
                        "the entire pillow. This is a must-pass criterion.",
                        0.0355,
                    ),
                    (
                        "r012",
                        "States that GOTS certifies the cotton shell and inner chamber of the "
                        "pillow Expected: GOTS certifies the fibre and processing chain of the "
                        "textile component; covers the cotton shell and inner chamber of the "
                        "pillow; holder is NovaTex. This is a must-pass criterion.",
                        0.0327,
                    ),
                ]
            },
        )
        r = analyze_task(task)
        assert r["status"] == "fail", f"expected fail, got {r['status']}"
        assert r["n_findings"] == 1, f"expected 1 finding, got {r['n_findings']}"
        f = r["findings"][0]
        assert set(f["criteria"]) == {"deliverables_01/r001", "deliverables_01/r012"}
        assert abs(f["excess_weight"] - 0.0327) < 1e-6, f["excess_weight"]
        print("  test_same_file_exact_requirement_flags: PASS")


def test_cross_file_same_value_does_not_flag():
    """SVC-PC-41-0-0's real shape: the SAME value cited in the SAME way across DIFFERENT
    deliverable files (a legitimate cross-deliverable consistency check). Must NOT fire --
    same-file scope is the whole point of this check, see module docstring reason 1."""
    with tempfile.TemporaryDirectory(prefix="_sfrd_test_") as tmp:
        root = Path(tmp)
        task = _make_task(
            root,
            "SYN-41-0-0",
            {
                "deliverables_01": [
                    (
                        "r009",
                        "FY2022 orders plan (base) Expected: 24,000 (Cover!B7).",
                        0.02,
                    ),
                ],
                "deliverables_03": [
                    (
                        "r029",
                        "Driver, FY2022 orders (base) Expected: 24,000 (Cover!B7).",
                        0.02,
                    ),
                ],
                "deliverables_05": [
                    (
                        "r055",
                        "Demand, FY2022 orders Expected: 24,000 (Cover!B7).",
                        0.02,
                    ),
                ],
            },
        )
        r = analyze_task(task)
        assert r["status"] == "pass", f"expected pass, got {r['status']}"
        assert r["n_findings"] == 0, f"expected 0 findings, got {r['n_findings']}"
        print("  test_cross_file_same_value_does_not_flag: PASS")


def test_verbatim_quote_template_does_not_flag():
    """SVC-PC-56-1-0's real shape: same file, identical requirement clause ("...character for
    character"), but the Expected clauses are two different, unrelated quoted passages. Must
    NOT fire -- confirmed real false positive that motivated _VERBATIM_QUOTE_RE."""
    with tempfile.TemporaryDirectory(prefix="_sfrd_test_") as tmp:
        root = Path(tmp)
        task = _make_task(
            root,
            "SYN-56-1-0",
            {
                "deliverables_01": [
                    (
                        "r001",
                        "Reports the exact wording of the company overview deck as it appears "
                        "in the evidence, character for character Expected: Direct-to-consumer "
                        "sleep products, engineered around cooling technology.",
                        0.02,
                    ),
                    (
                        "r007",
                        "Reports the exact wording of the company overview deck as it appears "
                        "in the evidence, character for character Expected: Made in Asheville, "
                        "manufactured by a named supplier, fully inspected.",
                        0.02,
                    ),
                ]
            },
        )
        r = analyze_task(task)
        assert r["status"] == "pass", f"expected pass, got {r['status']}"
        assert r["n_findings"] == 0, f"expected 0 findings, got {r['n_findings']}"
        print("  test_verbatim_quote_template_does_not_flag: PASS")


def test_short_requirement_clause_does_not_flag():
    """A shared requirement clause under MIN_CONTENT_WORDS content words is sentence-opening
    boilerplate, not a meaningful signal -- must NOT fire."""
    with tempfile.TemporaryDirectory(prefix="_sfrd_test_") as tmp:
        root = Path(tmp)
        task = _make_task(
            root,
            "SYN-SHORT",
            {
                "deliverables_01": [
                    ("c01", "States that Expected: 100.", 0.02),
                    ("c02", "States that Expected: 200.", 0.02),
                ]
            },
        )
        r = analyze_task(task)
        assert r["status"] == "pass", f"expected pass, got {r['status']}"
        print("  test_short_requirement_clause_does_not_flag: PASS")


def test_byte_identical_description_flags():
    """SVC-PC-12-1-0's real shape: the ENTIRE description (requirement AND Expected clause) is
    byte-identical between two differently-named criteria in the same file -- the plainest
    possible copy-paste duplicate. Must fire."""
    with tempfile.TemporaryDirectory(prefix="_sfrd_test_") as tmp:
        root = Path(tmp)
        task = _make_task(
            root,
            "SYN-12-1-0",
            {
                "deliverables_02": [
                    (
                        "r022",
                        "2. Contacted, FY2022 signed Expected: 1 (Pipeline_Forecast!C15).",
                        0.0245,
                    ),
                    (
                        "r023",
                        "2. Contacted, FY2022 signed Expected: 1 (Pipeline_Forecast!C15).",
                        0.0245,
                    ),
                ]
            },
        )
        r = analyze_task(task)
        assert r["status"] == "fail", f"expected fail, got {r['status']}"
        assert r["n_findings"] == 1
        print("  test_byte_identical_description_flags: PASS")


def test_no_expected_marker_does_not_flag():
    """A description with no "Expected:" label at all (EKW's own convention; also malformed
    SVC-PC text) contributes no requirement clause and must be silently excluded, not crash.
    """
    with tempfile.TemporaryDirectory(prefix="_sfrd_test_") as tmp:
        root = Path(tmp)
        task = _make_task(
            root,
            "SYN-NOEXP",
            {
                "deliverables_01": [
                    ("c01", "The gel layer has no certification.", 0.02),
                    ("c02", "The gel layer has no certification.", 0.02),
                ]
            },
        )
        r = analyze_task(task)
        assert r["status"] == "pass", f"expected pass, got {r['status']}"
        print("  test_no_expected_marker_does_not_flag: PASS")


def test_single_criterion_pass():
    """A single criterion (nothing to compare against) must pass cleanly."""
    with tempfile.TemporaryDirectory(prefix="_sfrd_test_") as tmp:
        root = Path(tmp)
        task = _make_task(
            root,
            "SYN-SINGLE",
            {
                "deliverables_01": [
                    ("c01", "States the revenue figure Expected: $100,000.", 1.0)
                ]
            },
        )
        r = analyze_task(task)
        assert r["status"] == "pass", f"expected pass, got {r['status']}"
        assert r["criteria_checked"] == 1
        print("  test_single_criterion_pass: PASS")


def test_no_judge_files_skip():
    """A task directory with no tests/ content at all must skip, not crash or error."""
    with tempfile.TemporaryDirectory(prefix="_sfrd_test_") as tmp:
        root = Path(tmp)
        task = root / "SYN-EMPTY"
        task.mkdir()
        r = analyze_task(task)
        assert r["status"] == "skip", f"expected skip, got {r['status']}"
        print("  test_no_judge_files_skip: PASS")


def test_three_way_duplicate_groups_together():
    """Three criteria in the same file sharing one requirement clause must all land in ONE
    finding, not three separate pairs."""
    with tempfile.TemporaryDirectory(prefix="_sfrd_test_") as tmp:
        root = Path(tmp)
        task = _make_task(
            root,
            "SYN-TRIPLE",
            {
                "deliverables_03": [
                    (
                        "r025",
                        "Marks the test-on-file status as not on file Expected: not on file.",
                        0.006,
                    ),
                    (
                        "r029",
                        "Marks the test-on-file status as not on file Expected: not on file. Must-pass.",
                        0.006,
                    ),
                    (
                        "r099",
                        "Marks the test-on-file status as not on file Expected: absent.",
                        0.006,
                    ),
                ]
            },
        )
        r = analyze_task(task)
        assert r["status"] == "fail"
        assert (
            r["n_findings"] == 1
        ), f"expected 1 combined finding, got {r['n_findings']}"
        assert r["findings"][0]["n_criteria"] == 3
        print("  test_three_way_duplicate_groups_together: PASS")


if __name__ == "__main__":
    tests = [
        test_same_file_exact_requirement_flags,
        test_cross_file_same_value_does_not_flag,
        test_verbatim_quote_template_does_not_flag,
        test_short_requirement_clause_does_not_flag,
        test_byte_identical_description_flags,
        test_no_expected_marker_does_not_flag,
        test_single_criterion_pass,
        test_no_judge_files_skip,
        test_three_way_duplicate_groups_together,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  {t.__name__}: FAIL - {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{passed + failed} tests passed")
    sys.exit(1 if failed else 0)
