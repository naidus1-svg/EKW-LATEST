#!/usr/bin/env python3
"""Tests for oracle_reward_details_audit.py."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from oracle_reward_details_audit import check_task


def _details(score: float, reasoning: str) -> dict:
    return {
        "v11": {
            "kind": "outcome",
            "score": score,
            "criteria": [
                {
                    "name": "yields",
                    "weight": 0.04,
                    "value": score,
                    "reasoning": reasoning,
                }
            ],
        }
    }


def _oracle(rev: Path, name: str, score: float, reasoning: str) -> None:
    folder = rev / "evaluations" / name / "eval_files" / "verifier"
    folder.mkdir(parents=True)
    (folder / "reward-details.json").write_text(
        json.dumps(_details(score, reasoning)), encoding="utf-8"
    )


def test_criterion_disagreement_is_warned() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = Path(td) / "task_1" / "rev_1"
        (rev / "task_files" / "environment").mkdir(parents=True)
        _oracle(rev, "eval_1__oracle", 1.0, "percent formatted correctly")
        _oracle(rev, "eval_2__oracle", 0.0, "raw decimals")
        result = check_task(rev)
        assert result["status"] == "warn"
        assert {f["kind"] for f in result["findings"]} == {
            "oracle_criterion_disagreement"
        }


def test_fabricated_quote_found_in_sources() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = Path(td) / "task_1" / "rev_1"
        env = rev / "task_files" / "environment" / "data"
        env.mkdir(parents=True)
        (env / "notice.md").write_text("Close date 8/15/2025 is confirmed.\n", encoding="utf-8")
        _oracle(
            rev,
            "eval_1__oracle",
            0.0,
            'The date "8/15/2025" is fabricated and unsourced.',
        )
        result = check_task(rev)
        kinds = {f["kind"] for f in result["findings"]}
        assert result["status"] == "warn"
        assert "fabricated_claim_present_in_sources" in kinds


def test_agreeing_full_scores_pass() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = Path(td) / "task_1" / "rev_1"
        (rev / "task_files" / "environment").mkdir(parents=True)
        _oracle(rev, "eval_1__oracle", 1.0, "ok")
        _oracle(rev, "eval_2__oracle", 1.0, "ok")
        result = check_task(rev)
        assert result["status"] == "pass"
        assert result["findings"] == []


def _run(rev: Path, name: str, reward: float | None, files: dict[str, str] | None = None, trial: str | None = None) -> None:
    folder = rev / "evaluations" / name / "eval_files" / "verifier"
    folder.mkdir(parents=True)
    if reward is not None:
        (folder / "reward.json").write_text(json.dumps({"reward": reward}), encoding="utf-8")
    for fname, text in (files or {}).items():
        (folder / fname).write_text(text, encoding="utf-8")
    if trial is not None:
        (folder.parent / "trial.log").write_text(trial, encoding="utf-8")


def _kinds(result: dict) -> set[str]:
    return {f["kind"] for f in result["findings"]}


def test_f2_oracle_reward_below_one_warns() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = Path(td) / "task_1" / "rev_1"
        (rev / "task_files" / "environment").mkdir(parents=True)
        _run(rev, "eval_1__attempt_1__oracle", 0.92)
        result = check_task(rev)
        assert result["status"] == "warn"
        f = next(f for f in result["findings"] if f["kind"] == "oracle_reward_below_one")
        assert "reward.json" in f["evidence"] and "0.92" in f["evidence"] and "Fix:" in f["evidence"]


def test_f2_oracle_full_reward_and_agent_low_reward_pass() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = Path(td) / "task_1" / "rev_1"
        (rev / "task_files" / "environment").mkdir(parents=True)
        _run(rev, "eval_1__attempt_1__oracle", 1.0)
        _run(rev, "eval_2__attempt_1__terminus-2__gpt", 0.3)
        result = check_task(rev)
        assert result["status"] == "pass", result["findings"]


def test_f2_grammar_too_large_in_oracle_log() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = Path(td) / "task_1" / "rev_1"
        (rev / "task_files" / "environment").mkdir(parents=True)
        log = "RuntimeError: Reward 'deliverables_03' failed: The compiled grammar is too large, which would cause performance issues."
        _run(rev, "eval_1__attempt_1__oracle", 0.0, {"runtime.log": log})
        result = check_task(rev)
        assert {"oracle_grammar_too_large", "oracle_reward_below_one", "verifier_crash"} <= _kinds(result)
        crash = next(f for f in result["findings"] if f["kind"] == "verifier_crash")
        assert crash["groups"] == ["deliverables_03"] and "split the judge group" in crash["evidence"]


def test_f3_agent_run_traceback_warns() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = Path(td) / "task_1" / "rev_1"
        (rev / "task_files" / "environment").mkdir(parents=True)
        _run(rev, "eval_1__attempt_1__oracle", 1.0)
        _run(rev, "eval_2__attempt_1__codex", 0.9, {"test-stdout.txt": "Traceback (most recent call last):\n  File x\nKeyError: 'v27'\n"})
        result = check_task(rev)
        crash = [f for f in result["findings"] if f["kind"] == "verifier_crash"]
        assert len(crash) == 1 and crash[0]["run"] == "eval_2__attempt_1__codex" and not crash[0]["oracle"]
        assert "test-stdout.txt" in crash[0]["evidence"]


def test_f3_judge_timeout_names_criterion() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = Path(td) / "task_1" / "rev_1"
        (rev / "task_files" / "environment").mkdir(parents=True)
        details = {"deliverables_02": {"score": 0.0, "criteria": [{"name": "confidentiality", "value": 0.0, "error": "judge timed out after 300s"}]}}
        _run(rev, "eval_2__attempt_1__claude-code", 0.5, {"reward-details.json": json.dumps(details)})
        result = check_task(rev)
        crash = next(f for f in result["findings"] if f["kind"] == "verifier_crash")
        assert "deliverables_02:confidentiality" in crash["evidence"] and "timeout" in crash["evidence"]


def test_f3_trial_log_verifier_timeout() -> None:
    with tempfile.TemporaryDirectory() as td:
        rev = Path(td) / "task_1" / "rev_1"
        (rev / "task_files" / "environment").mkdir(parents=True)
        _run(rev, "eval_1__attempt_1__oracle", None, trial="Verifier execution timed out after 3600.0 seconds")
        assert "verifier_crash" in _kinds(check_task(rev))


def test_f3_clean_logs_pass_and_nested_with_runs_layout_resolves() -> None:
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "SVC-1"
        rev = work / "SVC-1" / "rev_1__9"
        (rev / "task_files" / "environment").mkdir(parents=True)
        _run(rev, "eval_1__attempt_1__oracle", 1.0, {"runtime.log": "rewardkit finished, 12 criteria graded"})
        result = check_task(work)
        assert result["status"] == "pass" and result["revision"].endswith("rev_1__9")


if __name__ == "__main__":
    for test in (
        test_criterion_disagreement_is_warned,
        test_fabricated_quote_found_in_sources,
        test_agreeing_full_scores_pass,
        test_f2_oracle_reward_below_one_warns,
        test_f2_oracle_full_reward_and_agent_low_reward_pass,
        test_f2_grammar_too_large_in_oracle_log,
        test_f3_agent_run_traceback_warns,
        test_f3_judge_timeout_names_criterion,
        test_f3_trial_log_verifier_timeout,
        test_f3_clean_logs_pass_and_nested_with_runs_layout_resolves,
    ):
        test()
        print(f"{test.__name__}: PASS")
