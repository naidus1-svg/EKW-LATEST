#!/usr/bin/env python3
"""Tests for oracle_reproducibility_check.py.

Synthetic tests cover the two mechanisms, both real bundle nestings, and the checksum guard;
the corpus tests at the bottom pin the four criteria measured non-reproducible on byte-identical
goldens on 2026-09-22 -- task_120 v6c, task_LGL-168 v9, task_LGL-161 v14, task_LGL-131 v13.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import oracle_reproducibility_check as O  # noqa: E402


# ---------------------------------------------------------------------------
# synthetic bundle builders
# ---------------------------------------------------------------------------


def _assertion(name: str, success: bool, true_count: int, false_count: int, weight: float):
    return {
        "name": name,
        "definition": {"metadata": {"weight": weight, "tag": name}},
        "result": {
            "success": success,
            "effective_weight": weight if success else 0.0,
            "evaluation": {
                "judge_models": ["openai/gpt-5.4"] * (true_count + false_count),
                "true_count": true_count,
                "false_count": false_count,
                "attempts": [
                    {"model": "openai/gpt-5.4", "verdict": i < true_count,
                     "justification": f"sample {i} on {name}"}
                    for i in range(true_count + false_count)
                ],
            },
        },
    }


def _oracle_run(rev: Path, run_name: str, reward: float, rows, checksum="deadbeef",
                agent: bool = False):
    """rows: [(criterion, success, true_count, false_count, weight), ...]"""
    name = run_name if (agent or "oracle" in run_name) else f"{run_name}__oracle"
    d = rev / "evaluations" / name / "eval_files"
    (d / "verifier").mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({"task_checksum": checksum}), encoding="utf-8")
    (d / "verifier" / "verifier-report.json").write_text(json.dumps({
        "task_id": "t", "reward": reward,
        "assertion_results": [_assertion(*r) for r in rows],
    }), encoding="utf-8")
    return d


def _details_run(rev: Path, run_name: str, scores: dict[str, float], checksum="deadbeef"):
    """A run with reward-details.json only -- no per-sample votes available."""
    d = rev / "evaluations" / f"{run_name}__oracle" / "eval_files"
    (d / "verifier").mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({"task_checksum": checksum}), encoding="utf-8")
    (d / "verifier" / "reward-details.json").write_text(json.dumps({
        n: {"kind": "outcome", "score": s,
            "criteria": [{"name": n, "weight": 0.05, "value": s, "reasoning": "because"}]}
        for n, s in scores.items()
    }), encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# mechanism 1: cross-run disagreement
# ---------------------------------------------------------------------------


def test_cross_run_disagreement_on_identical_bytes_is_the_strongest_finding():
    with tempfile.TemporaryDirectory() as td:
        task = Path(td) / "task_120"
        rev = task / "rev_2__124196"
        _oracle_run(rev, "eval_501550__attempt_1", 0.98,
                    [("v1", True, 3, 0, 0.5), ("v6c", False, 1, 2, 0.02)])
        _oracle_run(rev, "eval_505918__attempt_1", 1.00,
                    [("v1", True, 3, 0, 0.5), ("v6c", True, 3, 0, 0.02)])
        r = O.analyze_task(task)
    assert r["status"] == "fail"
    assert r["n_oracle_runs"] == 2
    assert [e["criterion"] for e in r["unstable_criteria"]] == ["v6c"]
    assert "oracle_cross_run_disagreement" in r["unstable_criteria"][0]["kinds"]
    assert r["unstable_criteria"][0]["verdicts"] == ["FAIL", "PASS"]
    assert r["weight_at_risk"] == pytest.approx(0.02)


def test_agent_runs_are_ignored_only_oracle_runs_count():
    with tempfile.TemporaryDirectory() as td:
        task = Path(td) / "task_1"
        rev = task / "rev_1"
        _oracle_run(rev, "eval_1__attempt_1", 1.0, [("v1", True, 3, 0, 0.5)])
        _oracle_run(rev, "eval_2__attempt_1__terminus-2__claude-opus-5", 0.0,
                    [("v1", False, 0, 3, 0.5)], agent=True)
        r = O.analyze_task(task)
    assert r["n_oracle_runs"] == 1
    assert r["unstable_criteria"] == []
    assert r["status"] == "pass"
    assert any("fewer than two comparable oracle runs" in n for n in r["notes"])


def test_different_checksums_are_not_treated_as_irreproducibility():
    """Two runs that graded DIFFERENT bytes differing is expected, not a defect."""
    with tempfile.TemporaryDirectory() as td:
        task = Path(td) / "task_1"
        rev = task / "rev_1"
        _oracle_run(rev, "eval_1__attempt_1", 1.0, [("v1", True, 3, 0, 0.5)], checksum="aaa")
        _oracle_run(rev, "eval_2__attempt_1", 0.0, [("v1", False, 0, 3, 0.5)], checksum="bbb")
        r = O.analyze_task(task)
    assert r["unstable_criteria"] == []
    assert any("distinct task_checksum" in n for n in r["notes"])


def test_reward_details_only_run_compares_mean_scores_without_votes():
    with tempfile.TemporaryDirectory() as td:
        task = Path(td) / "task_1"
        rev = task / "rev_1"
        _details_run(rev, "eval_1__attempt_1", {"v1": 1.0, "v11": 1.0})
        _details_run(rev, "eval_2__attempt_1", {"v1": 1.0, "v11": 0.0})
        r = O.analyze_task(task)
    assert [e["criterion"] for e in r["unstable_criteria"]] == ["v11"]
    assert r["unstable_criteria"][0]["kinds"] == ["oracle_cross_run_disagreement"]
    # no per-sample votes exist in this format -- reported as unavailable, not invented
    assert r["unstable_criteria"][0]["votes"] == [None, None]
    assert {run["source"] for run in r["oracle_runs"]} == {"reward-details.json"}


# ---------------------------------------------------------------------------
# mechanism 2: split votes inside a single run
# ---------------------------------------------------------------------------


def test_split_vote_is_caught_even_when_every_run_agrees():
    """task_LGL-161 v14's shape: 1T/2F in BOTH runs -- identical mean, still a coin flip."""
    with tempfile.TemporaryDirectory() as td:
        task = Path(td) / "task_LGL-161"
        rev = task / "rev_1"
        _oracle_run(rev, "eval_1__attempt_1", 0.976, [("v14", False, 1, 2, 0.024)])
        _oracle_run(rev, "eval_2__attempt_1", 0.976, [("v14", False, 1, 2, 0.024)])
        r = O.analyze_task(task)
    assert r["status"] == "fail"
    entry = r["unstable_criteria"][0]
    assert entry["criterion"] == "v14"
    assert entry["kinds"] == ["split_vote_within_run"]
    assert entry["votes"] == ["1T/2F", "1T/2F"]
    assert len(entry["split_vote_runs"]) == 2


def test_unanimous_criteria_are_not_flagged():
    with tempfile.TemporaryDirectory() as td:
        task = Path(td) / "task_1"
        rev = task / "rev_1"
        rows = [("v1", True, 3, 0, 0.5), ("v2", False, 0, 3, 0.5)]
        _oracle_run(rev, "eval_1__attempt_1", 0.5, rows)
        _oracle_run(rev, "eval_2__attempt_1", 0.5, rows)
        r = O.analyze_task(task)
    assert r["status"] == "pass"
    assert r["unstable_criteria"] == []
    assert r["n_criteria"] == 2


def test_weight_at_risk_gate_is_configurable():
    with tempfile.TemporaryDirectory() as td:
        task = Path(td) / "task_1"
        rev = task / "rev_1"
        _oracle_run(rev, "eval_1__attempt_1", 1.0, [("v3", True, 2, 1, 0.01)])
        assert O.analyze_task(task, min_weight_at_risk=0.0)["status"] == "fail"
        soft = O.analyze_task(task, min_weight_at_risk=0.05)
        assert soft["status"] == "pass"
        assert soft["unstable_criteria"]          # still disclosed
        assert any("below --min-weight-at-risk" in n for n in soft["notes"])


# ---------------------------------------------------------------------------
# bundle shapes
# ---------------------------------------------------------------------------


def test_both_real_bundle_nestings_are_discovered():
    with tempfile.TemporaryDirectory() as td:
        flat = Path(td) / "task_120"
        _oracle_run(flat / "rev_2__124196", "eval_1__attempt_1", 1.0,
                    [("v1", True, 2, 1, 0.5)])
        nested = Path(td) / "task_145"
        _oracle_run(nested / "task_145" / "rev_2__124291", "eval_2__attempt_1", 1.0,
                    [("v1", True, 2, 1, 0.5)])
        assert O.analyze_task(flat)["n_oracle_runs"] == 1
        assert O.analyze_task(nested)["n_oracle_runs"] == 1


def test_no_oracle_artifacts_skips_rather_than_passing():
    with tempfile.TemporaryDirectory() as td:
        task = Path(td) / "task_1"
        (task / "rev_1" / "evaluations").mkdir(parents=True)
        r = O.analyze_task(task)
    assert r["status"] == "skip"
    assert any("no readable ORACLE verifier artifacts" in n for n in r["notes"])


def test_cli_writes_a_report_and_can_gate():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "incoming"
        rev = root / "task_1" / "rev_1"
        _oracle_run(rev, "eval_1__attempt_1", 1.0, [("v1", True, 3, 0, 0.5)])
        _oracle_run(rev, "eval_2__attempt_1", 0.5, [("v1", False, 1, 2, 0.5)])
        out = Path(td) / "r.json"
        assert O.main(["--all", "--root", str(root), "--id-prefix", "task_",
                       "--out", str(out)]) == 0
        report = json.loads(out.read_text())
        assert report["status_counts"] == {"fail": 1}
        assert set(report["finding_counts"]) == {
            "oracle_cross_run_disagreement", "split_vote_within_run"}
        assert O.main(["--all", "--root", str(root), "--exit-nonzero-on-fail"]) == 1


# ---------------------------------------------------------------------------
# regression fixtures: the four measured non-reproducible criteria (2026-09-22)
# ---------------------------------------------------------------------------

SPRINT = HERE.parent / "dataos_qc_runs" / "74-ekw-sprint"
REWORK = SPRINT / "qcr_20092026_rework" / "incoming"
QCR21 = SPRINT / "qcr_21092026" / "incoming"

# (bundle root, task, criterion, which mechanisms it must be caught by)
KNOWN_UNSTABLE = [
    (REWORK, "task_120", "v6c", {"oracle_cross_run_disagreement", "split_vote_within_run"}),
    (REWORK, "task_LGL-168", "v9", {"oracle_cross_run_disagreement", "split_vote_within_run"}),
    # v14 has the SAME mean in both runs -- a mean-score comparison cannot see it at all.
    (REWORK, "task_LGL-161", "v14", {"split_vote_within_run"}),
    (QCR21, "task_LGL-131", "v13", {"oracle_cross_run_disagreement", "split_vote_within_run"}),
]


@pytest.mark.skipif(not REWORK.is_dir() or not QCR21.is_dir(),
                    reason="real QCR bundles not present")
@pytest.mark.parametrize("root,task_id,criterion,kinds", KNOWN_UNSTABLE,
                         ids=[f"{t}:{c}" for _, t, c, _ in KNOWN_UNSTABLE])
def test_known_unstable_criteria_are_rediscovered(root: Path, task_id: str, criterion: str,
                                                  kinds: set):
    r = O.analyze_task(root / task_id)
    assert r["status"] == "fail", r
    found = {e["criterion"]: e for e in r["unstable_criteria"]}
    assert criterion in found, sorted(found)
    assert kinds.issubset(set(found[criterion]["kinds"]))
    assert found[criterion]["weight"] > 0


@pytest.mark.skipif(not REWORK.is_dir(), reason="real QCR bundles not present")
def test_task_120_reproduces_the_measured_reward_split():
    """0.98 vs 1.00 on an identical task_checksum, differing on v6c alone."""
    r = O.analyze_task(REWORK / "task_120")
    assert sorted(run["reward"] for run in r["oracle_runs"]) == [0.98, 1.0]
    assert len(r["checksums"]) == 1, "the two runs must have graded identical bytes"
    assert [e["criterion"] for e in r["unstable_criteria"]] == ["v6c"]
    assert r["unstable_criteria"][0]["votes"] == ["1T/2F", "3T/0F"]


@pytest.mark.skipif(not QCR21.is_dir(), reason="real QCR bundles not present")
def test_task_lgl_131_v13_returned_three_different_vote_splits():
    """3-0, 2-1 and 1-2 across three identical copies of the golden."""
    r = O.analyze_task(QCR21 / "task_LGL-131")
    assert r["n_oracle_runs"] == 3
    v13 = {e["criterion"]: e for e in r["unstable_criteria"]}["v13"]
    assert sorted(v13["votes"]) == ["1T/2F", "2T/1F", "3T/0F"]


@pytest.mark.skipif(not REWORK.is_dir() or not QCR21.is_dir(),
                    reason="real QCR bundles not present")
def test_corpus_baselines_are_stable():
    """The measured 2026-09-22 baseline across both real bundles."""
    def counts(root: Path) -> dict:
        out: dict = {}
        for d in sorted(root.glob("task_*")):
            if d.is_dir():
                status = O.analyze_task(d)["status"]
                out[status] = out.get(status, 0) + 1
        return out
    assert counts(REWORK) == {"fail": 10, "pass": 1}
    assert counts(QCR21) == {"fail": 2, "pass": 16, "skip": 1}
