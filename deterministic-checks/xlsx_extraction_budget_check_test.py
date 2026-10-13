#!/usr/bin/env python3
"""Tests for xlsx_extraction_budget_check.py."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from xlsx_extraction_budget_check import check_task


def _package(tmp: Path, cap: int, n_cells: int) -> Path:
    from openpyxl import Workbook

    task = tmp / "task_x"
    golden = task / "solution" / "golden_outputs"
    tests = task / "tests"
    golden.mkdir(parents=True)
    tests.mkdir(parents=True)
    (tests / "verifier_runtime.pyrun").write_text(
        f'MAX_CONTENT_CHARS = int(os.environ.get("VERIFIER_MAX_CONTENT", "{cap}"))\n',
        encoding="utf-8",
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "A"
    for i in range(n_cells):
        ws.cell(i + 1, 1, value=("x" * 20))
    wb.save(golden / "plan.xlsx")
    return task


def test_small_workbook_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        task = _package(Path(td), cap=90000, n_cells=3)
        result = check_task(task)
        assert result["status"] == "pass"
        assert result["findings"] == []


def test_low_headroom_warns() -> None:
    with tempfile.TemporaryDirectory() as td:
        task = _package(Path(td), cap=200, n_cells=12)
        result = check_task(task)
        assert result["status"] in {"warn", "fail"}
        assert result["findings"]
        assert result["findings"][0]["kind"] in {
            "xlsx_extraction_low_headroom",
            "xlsx_extraction_at_or_over_cap",
        }


if __name__ == "__main__":
    for test in (test_small_workbook_passes, test_low_headroom_warns):
        test()
        print(f"{test.__name__}: PASS")
