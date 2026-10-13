#!/usr/bin/env python3
"""Tests for comprehensive_review_evidence_gate.py."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from comprehensive_review_evidence_gate import check_submission, parse_review


def _review(
    verdict: str = "accept", severities: list[str] | None = None
) -> str:
    severities = severities or []
    checks = [
        {
            "id": f"1.{i}",
            "name": f"check {i}",
            "result": "pass" if i > len(severities) else "fail",
            "severity": severities[i - 1] if i <= len(severities) else "good",
            "evidence_status": "confirmed",
            "related_checks": [],
            "justification": "verified",
            "suggested_fix": None,
        }
        for i in range(1, 11)
    ]
    payload = {
        "benchmark": "ekw",
        "task_id": "1",
        "overall_verdict": verdict,
        "summary": "clean",
        "major_count": severities.count("major"),
        "minor_count": severities.count("minor"),
        "checks": checks,
    }
    return "review prose\n" + json.dumps(payload)


def _submission(tmp: Path) -> Path:
    rev = tmp / "task_1" / "rev_1__1"
    (rev / "task_files").mkdir(parents=True)
    (rev / "verifications").mkdir()
    (rev / "verifications" / "comprehensive_review_test.md").write_text(
        _review(), encoding="utf-8"
    )
    return rev


def _oracle(rev: Path, run: str, reward: float) -> None:
    verifier = rev / "evaluations" / run / "eval_files" / "verifier"
    verifier.mkdir(parents=True)
    (verifier / "reward.txt").write_text(str(reward), encoding="utf-8")
    (verifier / "reward-details.json").write_text("{}", encoding="utf-8")


def test_parse_review_rejects_schema_template() -> None:
    parsed, errors = parse_review(
        '{"benchmark":"ekw","overall_verdict":"accept | reject | invalid | needs_revision"}'
    )
    assert parsed is None
    assert errors


def test_clean_submission_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = _submission(Path(td))
        _oracle(rev, "eval_1__oracle", 1.0)
        result = check_submission(rev)
        assert result["status"] == "pass"
        assert result["findings"] == []


def test_nonperfect_and_disagreeing_oracles_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = _submission(Path(td))
        _oracle(rev, "eval_1__oracle", 1.0)
        _oracle(rev, "eval_2__oracle", 0.94)
        result = check_submission(rev)
        kinds = {f["kind"] for f in result["findings"]}
        assert result["status"] == "fail"
        assert kinds == {"golden_below_full_reward", "oracle_reward_disagreement"}


def test_malformed_review_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = _submission(Path(td))
        report = rev / "verifications" / "comprehensive_review_test.md"
        report.write_text(
            '{"benchmark":"ekw","overall_verdict":"accept | reject | invalid | needs_revision"}',
            encoding="utf-8",
        )
        _oracle(rev, "eval_1__oracle", 1.0)
        result = check_submission(rev)
        assert result["status"] == "fail"
        assert [f["kind"] for f in result["findings"]] == ["malformed_comprehensive_review"]


def test_missing_review_and_oracle_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = _submission(Path(td))
        (rev / "verifications" / "comprehensive_review_test.md").unlink()
        result = check_submission(rev)
        assert result["status"] == "fail"
        assert {f["kind"] for f in result["findings"]} == {
            "missing_comprehensive_review",
            "missing_oracle_run",
        }


def test_rejected_review_fails_release_bar() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = _submission(Path(td))
        report = rev / "verifications" / "comprehensive_review_test.md"
        report.write_text(_review("reject"), encoding="utf-8")
        _oracle(rev, "eval_1__oracle", 1.0)
        result = check_submission(rev)
        assert result["status"] == "fail"
        assert [f["kind"] for f in result["findings"]] == [
            "comprehensive_review_not_accepted"
        ]


def test_three_minor_issues_fail_release_bar() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = _submission(Path(td))
        report = rev / "verifications" / "comprehensive_review_test.md"
        report.write_text(
            _review("accept", ["minor", "minor", "minor"]),
            encoding="utf-8",
        )
        _oracle(rev, "eval_1__oracle", 1.0)
        result = check_submission(rev)
        assert result["status"] == "fail"
        assert result["findings"][0]["kind"] == "comprehensive_review_not_accepted"
        assert result["findings"][0]["minor_count"] == 3


if __name__ == "__main__":
    tests = [
        test_parse_review_rejects_schema_template,
        test_clean_submission_passes,
        test_nonperfect_and_disagreeing_oracles_fail,
        test_malformed_review_fails,
        test_missing_review_and_oracle_fail,
        test_rejected_review_fails_release_bar,
        test_three_minor_issues_fail_release_bar,
    ]
    for test in tests:
        test()
        print(f"{test.__name__}: PASS")
