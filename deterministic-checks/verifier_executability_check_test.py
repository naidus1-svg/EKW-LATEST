#!/usr/bin/env python3
"""Unit tests for verifier_executability_check.py, focused on the 2026-09-16 fix to
_gold_replay_svc_pc's missing-files check (see _environment_basenames's own docstring for the
real, 100%-confirmed false-positive pattern this closes: 71/202 real tasks in Khiem's Step 2
corpus were flagged "referenced_file_missing" purely because the check only looked in
solution/files/, never environment/initial_workspace/, even though BUILD-CONTRACT.md states
plainly that /app/ starts pre-seeded with the environment, not just the solution overlay).
Synthetic fixtures only -- does not touch rewardkit or the real corpus.

Run:
    python deterministic-checks/verifier_executability_check_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from verifier_executability_check import _environment_basenames


def _make_task(root: Path, name: str) -> Path:
    task = root / name
    (task / "tests").mkdir(parents=True, exist_ok=True)
    (task / "solution" / "files").mkdir(parents=True, exist_ok=True)
    return task


def test_environment_basenames_flat():
    """A file directly under environment/initial_workspace/ (no nesting) must be found --
    the real SVC-PC-20-4-0 shape (inventory_flows.csv, MSA_Apex_2021.pdf sit flat)."""
    with tempfile.TemporaryDirectory(prefix="_ve_test_") as tmp:
        task = _make_task(Path(tmp), "SYN-FLAT")
        env_dir = task / "environment" / "initial_workspace"
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "MSA_Apex_2021.pdf").write_text("pdf content", encoding="utf-8")
        names = _environment_basenames(task)
        assert "MSA_Apex_2021.pdf" in names, names
        print("  test_environment_basenames_flat: PASS")


def test_environment_basenames_nested():
    """A file nested under a build-time subtree (the real SVC-PC-5-3-0 shape:
    _corpus_subtree/Company Shared Drive__Operations/Q1_Ops_Summary.docx) must still be
    found -- the whole reason the search is recursive (rglob), not a flat listdir."""
    with tempfile.TemporaryDirectory(prefix="_ve_test_") as tmp:
        task = _make_task(Path(tmp), "SYN-NESTED")
        nested = (
            task / "environment" / "initial_workspace" / "_corpus_subtree" / "Legal"
        )
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "Rate_Card_Apex_2021.xlsx").write_text(
            "xlsx content", encoding="utf-8"
        )
        names = _environment_basenames(task)
        assert "Rate_Card_Apex_2021.xlsx" in names, names
        print("  test_environment_basenames_nested: PASS")


def test_environment_basenames_missing_dir():
    """A task with no environment/initial_workspace/ directory at all must return an empty
    set, not raise -- never crash the batch over a missing/unusual task shape."""
    with tempfile.TemporaryDirectory(prefix="_ve_test_") as tmp:
        task = _make_task(Path(tmp), "SYN-NOENV")
        names = _environment_basenames(task)
        assert names == set(), names
        print("  test_environment_basenames_missing_dir: PASS")


def test_environment_basenames_does_not_include_directories():
    """Only FILES count -- a directory that happens to share a name with something referenced
    in judge.toml must not produce a false "found" (is_file() gates every entry)."""
    with tempfile.TemporaryDirectory(prefix="_ve_test_") as tmp:
        task = _make_task(Path(tmp), "SYN-DIRNAME")
        env_dir = task / "environment" / "initial_workspace"
        (env_dir / "Vendor_Master_List.xlsx").mkdir(parents=True, exist_ok=True)
        names = _environment_basenames(task)
        assert "Vendor_Master_List.xlsx" not in names, names
        print("  test_environment_basenames_does_not_include_directories: PASS")


if __name__ == "__main__":
    tests = [
        test_environment_basenames_flat,
        test_environment_basenames_nested,
        test_environment_basenames_missing_dir,
        test_environment_basenames_does_not_include_directories,
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
