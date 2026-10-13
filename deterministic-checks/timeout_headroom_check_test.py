#!/usr/bin/env python3
"""Tests for timeout_headroom_check.py.

Synthetic tests cover the arithmetic, the genre branches and the honest-skip paths; the
corpus tests at the bottom pin the two CONFIRMED real 3600 s verifier timeouts (task_157,
task_LGL-160) and the sampled worst case (task_LGL-168) against the real shipped v7 packages.
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

import timeout_headroom_check as T  # noqa: E402


# ---------------------------------------------------------------------------
# synthetic package builders
# ---------------------------------------------------------------------------


def _native_pkg(root: Path, task_id: str, n_rubric: int, n_samples: int = 3,
                timeout_sec: float = 3600.0, n_deterministic: int = 0) -> Path:
    pkg = root / task_id
    (pkg / "tests" / "__verifier_lib").mkdir(parents=True)
    verifiers = [
        {"name": f"v{i}", "metadata": {"weight": 0.1},
         "assertion": {"type": "rubric", "rubric": {"prompt": "does it?"}}}
        for i in range(n_rubric)
    ]
    verifiers += [
        {"name": f"d{i}", "metadata": {"weight": 0.1},
         "assertion": {"type": "deterministic", "expected": "X",
                       "deterministic": {"path": "$.a", "comparison": "equals"}}}
        for i in range(n_deterministic)
    ]
    (pkg / "tests" / "verifier.json").write_text(json.dumps({
        "task_id": task_id,
        "config": {"models": ["openai/gpt-5.4"] * n_samples, "temperature": 1.0},
        "verifiers": verifiers,
    }), encoding="utf-8")
    if timeout_sec is not None:
        (pkg / "task.toml").write_text(
            f'version = "1.0"\n\n[verifier]\ntimeout_sec = {timeout_sec}\n', encoding="utf-8")
    return pkg


def _rewardkit_pkg(root: Path, task_id: str, chunks: list[tuple[int, float | None]]) -> Path:
    pkg = root / task_id
    (pkg / "tests").mkdir(parents=True)
    (pkg / "task.toml").write_text(
        'version = "1.0"\n\n[verifier]\ntimeout_sec = 3600.0\n', encoding="utf-8")
    (pkg / "tests" / "reward.toml").write_text(
        '[[reward]]\nname = "reward"\naggregation = "weighted_mean"\n', encoding="utf-8")
    for i, (n_crit, timeout) in enumerate(chunks, 1):
        d = pkg / "tests" / f"deliverables_{i:02d}"
        d.mkdir()
        lines = ['[judge]', 'judge = "anthropic/claude-sonnet-4-6"', 'files = ["/app/x.xlsx"]']
        if timeout is not None:
            lines.append(f"timeout = {timeout:g}")
        for j in range(n_crit):
            lines += ["", "[[criterion]]", f'name = "c{j}"',
                      "description = '''does it?'''", 'type = "binary"', "weight = 0.1"]
        d.joinpath("judge.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return pkg


# ---------------------------------------------------------------------------
# arithmetic
# ---------------------------------------------------------------------------


def test_counts_rubric_criteria_times_samples_and_computes_headroom():
    with tempfile.TemporaryDirectory() as td:
        pkg = _native_pkg(Path(td), "task_x", n_rubric=10, n_samples=3)
        r = T.analyze_task(pkg, seconds_per_call=25.0, min_headroom=1.5)
    assert r["genre"] == "native"
    assert r["rubric_criteria"] == 10
    assert r["judge_samples"] == 3
    assert r["judge_calls"] == 30
    assert r["est_serial_sec"] == 750.0
    assert r["headroom"] == pytest.approx(4.8)
    assert r["status"] == "pass"


def test_deterministic_assertions_are_counted_but_not_charged():
    """A deterministic assertion makes no LLM call -- it must not inflate the estimate."""
    with tempfile.TemporaryDirectory() as td:
        pkg = _native_pkg(Path(td), "task_x", n_rubric=10, n_deterministic=25)
        r = T.analyze_task(pkg, seconds_per_call=25.0)
    assert r["rubric_criteria"] == 10
    assert r["deterministic_criteria"] == 25
    assert r["judge_calls"] == 30  # 10 rubric x 3, NOT 35 x 3


def test_below_margin_fails_with_a_finding():
    with tempfile.TemporaryDirectory() as td:
        pkg = _native_pkg(Path(td), "task_x", n_rubric=40, n_samples=3)
        r = T.analyze_task(pkg, seconds_per_call=46.0, min_headroom=1.5)
    assert r["status"] == "fail"
    assert [f["kind"] for f in r["findings"]] == ["verifier_timeout_headroom_below_margin"]
    assert r["findings"][0]["judge_calls"] == 120


def test_margin_is_configurable_in_both_directions():
    with tempfile.TemporaryDirectory() as td:
        pkg = _native_pkg(Path(td), "task_x", n_rubric=20, n_samples=3)
        assert T.analyze_task(pkg, 25.0, min_headroom=1.5)["status"] == "pass"   # 2.4x
        assert T.analyze_task(pkg, 25.0, min_headroom=3.0)["status"] == "fail"
        assert T.analyze_task(pkg, 46.0, min_headroom=1.5)["status"] == "fail"   # 1.30x


def test_sample_count_comes_from_the_real_config_not_an_assumption():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        one = T.analyze_task(_native_pkg(root, "task_one", 10, n_samples=1), 25.0)
        five = T.analyze_task(_native_pkg(root, "task_five", 10, n_samples=5), 25.0)
    assert one["judge_calls"] == 10
    assert five["judge_calls"] == 50


def test_missing_models_list_falls_back_to_one_sample_and_says_so():
    with tempfile.TemporaryDirectory() as td:
        pkg = _native_pkg(Path(td), "task_x", n_rubric=10)
        cfg = json.loads((pkg / "tests" / "verifier.json").read_text())
        cfg["config"] = {"temperature": 1.0}
        (pkg / "tests" / "verifier.json").write_text(json.dumps(cfg), encoding="utf-8")
        r = T.analyze_task(pkg, 25.0)
    assert r["judge_samples"] == 1
    assert any("no non-empty `models` list" in n for n in r["notes"])


# ---------------------------------------------------------------------------
# skip paths -- each must say why, never silently pass
# ---------------------------------------------------------------------------


def test_missing_task_toml_skips_rather_than_passing():
    with tempfile.TemporaryDirectory() as td:
        pkg = _native_pkg(Path(td), "task_x", n_rubric=40, timeout_sec=None)
        r = T.analyze_task(pkg, 46.0)
    assert r["status"] == "skip"
    assert any("task.toml missing" in n for n in r["notes"])


def test_zero_rubric_criteria_skips():
    with tempfile.TemporaryDirectory() as td:
        pkg = _native_pkg(Path(td), "task_x", n_rubric=0, n_deterministic=5)
        r = T.analyze_task(pkg, 46.0)
    assert r["status"] == "skip"
    assert any("zero LLM-judged rubric criteria" in n for n in r["notes"])


def test_unknown_genre_skips():
    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "task_x"
        (pkg / "tests").mkdir(parents=True)
        r = T.analyze_task(pkg, 46.0)
    assert r["status"] == "skip"
    assert r["genre"] == "unknown"


def test_rewardkit_genre_is_disclosed_but_never_graded():
    """Its chunks are judged concurrently -- the serial model does not apply (see docstring)."""
    with tempfile.TemporaryDirectory() as td:
        pkg = _rewardkit_pkg(Path(td), "task_x", [(16, 600.0), (9, None)])
        r = T.analyze_task(pkg, 46.0, 1.5)
    assert r["genre"] == "rewardkit"
    assert r["status"] == "skip"
    assert r["findings"] == []
    rk = r["rewardkit"]
    assert rk["n_chunks"] == 2
    assert rk["criteria"] == 25
    assert rk["chunks"][0]["judge_timeout_sec"] == 600.0
    # absent [judge] timeout -> rewardkit's documented 300 s default, labelled as such
    assert rk["chunks"][1]["judge_timeout_sec"] == T.REWARDKIT_DEFAULT_JUDGE_TIMEOUT
    assert "default" in rk["chunks"][1]["judge_timeout_source"]
    assert rk["reward_toml_present"] is True
    assert "upper bound" in rk["serial_upper_bound_note"]


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_writes_a_report_and_exits_zero_by_default():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "pkgs"
        root.mkdir()
        _native_pkg(root, "task_big", 55)
        _native_pkg(root, "task_small", 5)
        out = Path(td) / "r.json"
        rc = T.main(["--all", "--root", str(root), "--id-prefix", "task_", "--out", str(out)])
        assert rc == 0
        report = json.loads(out.read_text())
    assert report["status_counts"] == {"fail": 1, "pass": 1}
    assert report["seconds_per_call"] == T.DEFAULT_SECONDS_PER_CALL


def test_cli_can_be_used_as_a_hard_gate():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "pkgs"
        root.mkdir()
        _native_pkg(root, "task_big", 55)
        assert T.main(["--all", "--root", str(root), "--exit-nonzero-on-fail"]) == 1


# ---------------------------------------------------------------------------
# regression fixtures: the real 2026-09-22 timeouts
# ---------------------------------------------------------------------------

SUBMITTED = (HERE.parent / "dataos_qc_runs" / "74-ekw-sprint" / "ready_to_upload_v7"
             / "submitted")

# task_157 and task_LGL-160 each have a real oracle run that died with
# "Verifier execution timed out after 3600.0 seconds"; task_LGL-168 is the third worst case
# the fix session sampled. All three must land in the flagged set at the defaults.
KNOWN_TIMEOUTS = ["task_157", "task_LGL-160", "task_LGL-168"]


@pytest.mark.skipif(not SUBMITTED.is_dir(), reason="v7 submitted corpus not present")
@pytest.mark.parametrize("task_id", KNOWN_TIMEOUTS)
def test_known_real_timeouts_are_flagged_at_the_defaults(task_id: str):
    r = T.analyze_task(SUBMITTED / task_id, T.DEFAULT_SECONDS_PER_CALL, T.DEFAULT_MIN_HEADROOM)
    assert r["status"] == "fail", r
    assert r["headroom"] < T.DEFAULT_MIN_HEADROOM
    assert r["judge_samples"] == 3


@pytest.mark.skipif(not SUBMITTED.is_dir(), reason="v7 submitted corpus not present")
def test_corpus_distribution_is_stable():
    """The measured 2026-09-22 baseline. A change here means the corpus or the model moved."""
    results = [T.analyze_task(d, T.DEFAULT_SECONDS_PER_CALL, T.DEFAULT_MIN_HEADROOM)
               for d in sorted(SUBMITTED.glob("task_*")) if d.is_dir()]
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    # 75 native + 4 rewardkit (skip). At the p90 default only task_LGL-177 (17 criteria) clears
    # the 1.5x margin -- the finding is batch-wide, see the module docstring.
    assert counts == {"fail": 74, "pass": 1, "skip": 4}
    # Every native package ships the same template budget and the G9-mandated 3 samples.
    native = [r for r in results if r["genre"] == "native"]
    assert len(native) == 75
    assert {r["timeout_sec"] for r in native} == {3600.0}
    assert {r["judge_samples"] for r in native} == {3}


@pytest.mark.skipif(not SUBMITTED.is_dir(), reason="v7 submitted corpus not present")
def test_median_latency_view_is_a_usable_per_task_ranking():
    """`--seconds-per-call 25` (measured median) separates the batch instead of failing it."""
    results = [T.analyze_task(d, 25.0, 1.5) for d in sorted(SUBMITTED.glob("task_*"))
               if d.is_dir()]
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    assert counts == {"fail": 23, "pass": 52, "skip": 4}
