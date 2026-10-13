#!/usr/bin/env python3
"""Tests for accepted_alternative_compatibility_check.py."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from accepted_alternative_compatibility_check import check_task


def _verifier(criteria: list[tuple[str, str]]) -> dict:
    return {
        "task_id": "t",
        "config": {},
        "verifiers": [
            {
                "name": name,
                "metadata": {"weight": 0.1},
                "source": {
                    "type": "file",
                    "file": {
                        "type": "docx",
                        "command": "extract_text",
                        "arguments": {"path": "output/memo.docx"},
                    },
                },
                "assertion": {
                    "type": "rubric",
                    "expected": True,
                    "rubric": {"prompt": prompt},
                },
            }
            for name, prompt in criteria
        ],
    }


def _task(tmp: Path, criteria: list[tuple[str, str]]) -> Path:
    task = tmp / "task_x"
    tests = task / "tests"
    tests.mkdir(parents=True)
    (tests / "verifier.json").write_text(json.dumps(_verifier(criteria)), encoding="utf-8")
    return task


def test_numeric_alternative_revoked_by_delta_requirement() -> None:
    with tempfile.TemporaryDirectory() as td:
        task = _task(
            Path(td),
            [
                (
                    "v2",
                    "accept either 32,394 or 32,380; either value is correct.",
                ),
                (
                    "v1",
                    "Pass if the memo recognizes the ~14-unit late-receipt shortfall.",
                ),
            ],
        )
        result = check_task(task)
        kinds = {f["kind"] for f in result["findings"]}
        assert result["status"] == "warn"
        assert "accepted_numeric_alternative_revoked" in kinds
        assert result["findings"][0]["sibling"] == "v1"


def test_joined_tab_alternative_revoked_by_table_itself() -> None:
    with tempfile.TemporaryDirectory() as td:
        task = _task(
            Path(td),
            [
                (
                    "v10",
                    "checks may be shown either as columns in this same table OR in a "
                    "separately visible tab that joins back by Placement_ID.",
                ),
                (
                    "v12",
                    "The judge must verify this grain from the table itself.",
                ),
            ],
        )
        result = check_task(task)
        kinds = {f["kind"] for f in result["findings"]}
        assert result["status"] == "warn"
        assert "accepted_presentation_alternative_revoked" in kinds


def test_compatible_siblings_pass() -> None:
    with tempfile.TemporaryDirectory() as td:
        task = _task(
            Path(td),
            [
                ("v2", "accept either 32,394 or 32,380."),
                ("v9", "Pass if the dashboard reports store counts."),
            ],
        )
        result = check_task(task)
        assert result["status"] == "pass"
        assert result["findings"] == []


if __name__ == "__main__":
    for test in (
        test_numeric_alternative_revoked_by_delta_requirement,
        test_joined_tab_alternative_revoked_by_table_itself,
        test_compatible_siblings_pass,
    ):
        test()
        print(f"{test.__name__}: PASS")
