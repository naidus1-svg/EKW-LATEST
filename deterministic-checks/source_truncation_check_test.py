#!/usr/bin/env python3
"""Unit tests for source_truncation_check.py, focused on the 2026-09-16 fix to
_check_svc_pc_truncation's oversized_file_marked_skip sub-check (see _environment_basenames's
own docstring for the real, confirmed pattern this closes: 543 of 545 real judge.toml-referenced
files not found under solution/files/ in Khiem's full 600-task corpus actually live under
environment/initial_workspace/, and 23 of those were genuinely oversized and invisible to this
check before the fix). Synthetic fixtures only -- does not touch rewardkit or the real corpus.

Run:
    python deterministic-checks/source_truncation_check_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from source_truncation_check import _check_svc_pc_truncation, _environment_basenames


def _make_task(root: Path, name: str) -> Path:
    task = root / name
    (task / "tests").mkdir(parents=True, exist_ok=True)
    (task / "solution" / "files").mkdir(parents=True, exist_ok=True)
    return task


def test_environment_basenames_flat():
    """A file directly under environment/initial_workspace/ (no nesting) must be found."""
    with tempfile.TemporaryDirectory(prefix="_st_test_") as tmp:
        task = _make_task(Path(tmp), "SYN-FLAT")
        env_dir = task / "environment" / "initial_workspace"
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "Sales_Orders.xlsx").write_text("xlsx content", encoding="utf-8")
        names = _environment_basenames(task)
        assert "Sales_Orders.xlsx" in names, names
        print("  test_environment_basenames_flat: PASS")


def test_environment_basenames_nested():
    """A file nested under a build-time subtree must still be found (rglob, not a flat
    listdir) -- the real SVC-PC-5-3-0-shaped case."""
    with tempfile.TemporaryDirectory(prefix="_st_test_") as tmp:
        task = _make_task(Path(tmp), "SYN-NESTED")
        nested = task / "environment" / "initial_workspace" / "_corpus_subtree" / "Ops"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "orders_export_1.csv").write_text("csv content", encoding="utf-8")
        names = _environment_basenames(task)
        assert "orders_export_1.csv" in names, names
        print("  test_environment_basenames_nested: PASS")


def test_environment_basenames_missing_dir():
    """No environment/initial_workspace/ directory at all returns an empty dict, never raises."""
    with tempfile.TemporaryDirectory(prefix="_st_test_") as tmp:
        task = _make_task(Path(tmp), "SYN-NOENV")
        names = _environment_basenames(task)
        assert names == {}, names
        print("  test_environment_basenames_missing_dir: PASS")


def test_solution_file_wins_over_environment_same_name():
    """When a same-named file exists under BOTH directories, solution/files/ wins -- the
    fallback is tried only after solution/'s own check misses, same precedence as
    formula_health_check.py's resolve_graded_files and verifier_executability_check.py's fix.
    """
    with tempfile.TemporaryDirectory(prefix="_st_test_") as tmp:
        task = _make_task(Path(tmp), "SYN-BOTH")
        # solution copy: small, under the size cap
        (task / "solution" / "files" / "Report.xlsx").write_text(
            "small", encoding="utf-8"
        )
        # environment copy: same name, deliberately oversized
        env_dir = task / "environment" / "initial_workspace"
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "Report.xlsx").write_bytes(b"x" * 2_000_000)
        (task / "tests").mkdir(parents=True, exist_ok=True)
        judge_dir = task / "tests" / "deliverables_01"
        judge_dir.mkdir(parents=True, exist_ok=True)
        (judge_dir / "judge.toml").write_text(
            '[judge]\nfiles = ["/app/Report.xlsx"]\n', encoding="utf-8"
        )
        result = _check_svc_pc_truncation(task)
        sub = result["oversized_file_marked_skip"]
        assert sub["n_resolved_solution"] == 1, sub
        assert sub["n_resolved_environment"] == 0, sub
        assert (
            sub["n_oversized"] == 0
        ), sub  # the small solution/ copy wins, not the big one
        print("  test_solution_file_wins_over_environment_same_name: PASS")


def test_environment_fallback_surfaces_oversized_file():
    """A referenced file absent from solution/files/ but present (and oversized) under
    environment/initial_workspace/ must now be flagged, source-tagged 'environment/
    initial_workspace' -- the exact real-corpus pattern this fix closes."""
    with tempfile.TemporaryDirectory(prefix="_st_test_") as tmp:
        task = _make_task(Path(tmp), "SYN-ENVFALLBACK")
        env_dir = task / "environment" / "initial_workspace"
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "Vendor_Agreement.pdf").write_bytes(b"x" * 2_000_000)
        judge_dir = task / "tests" / "deliverables_01"
        judge_dir.mkdir(parents=True, exist_ok=True)
        (judge_dir / "judge.toml").write_text(
            '[judge]\nfiles = ["/app/Vendor_Agreement.pdf"]\n', encoding="utf-8"
        )
        result = _check_svc_pc_truncation(task)
        sub = result["oversized_file_marked_skip"]
        assert sub["n_resolved_environment"] == 1, sub
        assert sub["n_oversized"] == 1, sub
        assert sub["files"][0]["source"] == "environment/initial_workspace", sub
        print("  test_environment_fallback_surfaces_oversized_file: PASS")


def test_file_absent_from_both_stays_unresolved_not_oversized():
    """A referenced file missing from both directories is counted n_unresolved, never flagged
    oversized (existence is a different check's territory, not this one's)."""
    with tempfile.TemporaryDirectory(prefix="_st_test_") as tmp:
        task = _make_task(Path(tmp), "SYN-MISSING")
        judge_dir = task / "tests" / "deliverables_01"
        judge_dir.mkdir(parents=True, exist_ok=True)
        (judge_dir / "judge.toml").write_text(
            '[judge]\nfiles = ["/app/Nowhere.csv"]\n', encoding="utf-8"
        )
        result = _check_svc_pc_truncation(task)
        sub = result["oversized_file_marked_skip"]
        assert sub["n_unresolved"] == 1, sub
        assert sub["n_oversized"] == 0, sub
        print("  test_file_absent_from_both_stays_unresolved_not_oversized: PASS")


if __name__ == "__main__":
    tests = [
        test_environment_basenames_flat,
        test_environment_basenames_nested,
        test_environment_basenames_missing_dir,
        test_solution_file_wins_over_environment_same_name,
        test_environment_fallback_surfaces_oversized_file,
        test_file_absent_from_both_stays_unresolved_not_oversized,
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
