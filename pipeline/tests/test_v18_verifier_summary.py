"""Tests for the verifier_assertion_summary callback that synthesises
pass/fail patterns from a task's evals/<model>/trial_*/verifier-report.json
files."""

from __future__ import annotations

import os

import json
from pathlib import Path

import pytest

from gdpval_qc.v18_loader import Sample, TaskCorpusLoader
from gdpval_qc.v18_spec import V18Spec
from gdpval_qc.v18_verifier_summary import (
    build_verifier_assertion_summary,
    _classify_pattern,
)


REPO_ROOT     = Path(__file__).resolve().parent.parent
V18_SPEC_PATH = REPO_ROOT / "specs" / "gdpval_task_quality_v18.md"
OMEGA_ROOT    = Path(os.environ.get("GDPVAL_TEST_CORPUS") or (Path(__file__).resolve().parent.parent / "data" / "sample_corpus"))


@pytest.fixture(scope="session")
def spec() -> V18Spec:
    return V18Spec.from_markdown(V18_SPEC_PATH)


# ── Pattern classification ─────────────────────────────────────────────────

def test_classify_pattern_always_passes() -> None:
    assert _classify_pattern({"m1": [True, True], "m2": [True]}) == "always_passes"


def test_classify_pattern_always_fails() -> None:
    assert _classify_pattern({"m1": [False, False], "m2": [False]}) == "always_fails"


def test_classify_pattern_judge_unreliable_intra_model() -> None:
    """Within-model disagreement signals an unreliable judge."""
    assert _classify_pattern({"m1": [True, False, True]}) == "judge_unreliable"


def test_classify_pattern_discriminates_across_models() -> None:
    """Different models produce different pass rates → discriminates."""
    assert _classify_pattern({"m1": [True], "m2": [False]}) == "discriminates"


# ── Synthesised report from real omega data ────────────────────────────────

def test_build_summary_returns_none_when_no_evals(tmp_path: Path) -> None:
    """No evals/ dir → no summary."""
    td = tmp_path / "task"
    td.mkdir()
    sample = Sample(task_id="t", task_dir=td, fields={})
    assert build_verifier_assertion_summary(sample) is None


def test_build_summary_returns_none_when_evals_empty(tmp_path: Path) -> None:
    """evals/ dir but no readable reports → None."""
    td = tmp_path / "task"
    (td / "evals" / "m1" / "trial_1").mkdir(parents=True)
    sample = Sample(task_id="t", task_dir=td, fields={})
    assert build_verifier_assertion_summary(sample) is None


def test_build_summary_synthetic_report(tmp_path: Path) -> None:
    """Construct a synthetic 2-model × 2-trial layout and verify the
    summary lists per-verifier pass rates and aggregate patterns."""
    td = tmp_path / "task"
    evals = td / "evals"

    def _write(model: str, trial: int, results: list[dict]) -> None:
        d = evals / model / f"trial_{trial}" / "verifier"
        d.mkdir(parents=True, exist_ok=True)
        report = {
            "task_id":            "t",
            "reward":             sum(r["result"]["success"] for r in results) / len(results),
            "summary":            {"total_verifiers": len(results), "passed": 0, "failed": 0},
            "assertion_results":  results,
        }
        (d / "verifier-report.json").write_text(json.dumps(report))

    # Build outcomes that exercise every pattern:
    #   v_always_pass : passes for both models, both trials
    #   v_always_fail : fails for both models, both trials
    #   v_discrim     : passes for m1, fails for m2
    #   v_unreliable  : flips within m1's trials
    def _r(name: str, cls: str, success: bool) -> dict:
        return {
            "name":   name,
            "definition": {"metadata": {"classification": cls}},
            "result": {"success": success, "score": 1.0 if success else 0.0},
        }

    _write("m1", 1, [_r("v_always_pass", "core", True),
                       _r("v_always_fail", "core", False),
                       _r("v_discrim",     "core", True),
                       _r("v_unreliable",  "core", True)])
    _write("m1", 2, [_r("v_always_pass", "core", True),
                       _r("v_always_fail", "core", False),
                       _r("v_discrim",     "core", True),
                       _r("v_unreliable",  "core", False)])  # flipped
    _write("m2", 1, [_r("v_always_pass", "core", True),
                       _r("v_always_fail", "core", False),
                       _r("v_discrim",     "core", False),
                       _r("v_unreliable",  "core", True)])
    _write("m2", 2, [_r("v_always_pass", "core", True),
                       _r("v_always_fail", "core", False),
                       _r("v_discrim",     "core", False),
                       _r("v_unreliable",  "core", True)])

    sample = Sample(task_id="t", task_dir=td, fields={})
    summary = build_verifier_assertion_summary(sample)

    assert summary is not None
    assert "v_always_pass" in summary
    assert "v_always_fail" in summary
    assert "v_discrim" in summary
    assert "v_unreliable" in summary

    # Pattern labels appear
    assert "always_passes" in summary
    assert "always_fails" in summary
    assert "judge_unreliable" in summary
    assert "discriminates" in summary

    # Aggregate counts: 1 always-passes, 1 always-fails, 1 unreliable, 1 discriminates
    aggregate_section = summary.split("Aggregate patterns:")[1]
    assert "v_always_pass" in aggregate_section
    assert "v_always_fail" in aggregate_section


# ── Wiring through TaskCorpusLoader on real omega data ─────────────────────

def _skip_if_omega_missing() -> None:
    if not OMEGA_ROOT.is_dir():
        pytest.skip(f"omega dataset not present at {OMEGA_ROOT}")


def test_loader_auto_registers_callback_and_populates_field(spec: V18Spec) -> None:
    """The loader must auto-register build_verifier_assertion_summary so
    the field gets populated on real omega data without the CLI needing
    to register it explicitly.

    Picks the first task in the corpus with at least one
    evals/<model>/trial_*/verifier-report.json present. Skips when no such
    task is found (e.g. against a minimal bundled sample whose evals dir
    has been redacted)."""
    _skip_if_omega_missing()
    loader = TaskCorpusLoader(OMEGA_ROOT, spec)

    # Pick the first task that actually has verifier reports — otherwise
    # the build callback returns None.
    chosen_tid = None
    chosen_summary = None
    for tid in loader.task_ids():
        candidate = loader.load_sample(tid)
        summary = candidate.fields.get("verifier_assertion_summary")
        if isinstance(summary, str) and summary:
            chosen_tid = tid
            chosen_summary = summary
            break
    if chosen_tid is None:
        pytest.skip(f"no task in {OMEGA_ROOT} has verifier reports")

    assert "Verifier outcomes" in chosen_summary
    assert "Per-verifier pass rates" in chosen_summary
    # At least one model directory should be referenced in the summary
    # (the omega corpus uses names like expert_improved, gpt55, opus48; the
    # set will differ across corpora, so we don't assert specific names).


def test_loader_user_callbacks_override_builtins(spec: V18Spec, tmp_path: Path) -> None:
    """A user-supplied callback for the same name must take precedence
    over the built-in."""
    td = tmp_path / "task"
    (td / "environment").mkdir(parents=True)
    (td / "solution" / "golden_outputs").mkdir(parents=True)
    (td / "instruction.md").write_text("Test", encoding="utf-8")
    (td / "task.toml").write_text('[metadata]\ndomain = "Test"\n', encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    td.rename(root / "task_demo")

    def custom(sample: Sample) -> str:
        return "OVERRIDDEN"

    loader = TaskCorpusLoader(
        root, spec,
        callbacks={"build_verifier_assertion_summary": custom},
    )
    sample = loader.load_sample("task_demo")
    assert sample.fields["verifier_assertion_summary"] == "OVERRIDDEN"


# ── Spec wires verifier_assertion_summary into the right dims ──────────────

def test_v18_spec_dims_consume_verifier_assertion_summary(spec: V18Spec) -> None:
    """Four verifier-quality dims should consume the summary as input."""
    expected_dims_with_summary = {
        "verifier_rubric_construct_validity",
        "verifier_outcome_coverage",
        "verifier_missing_critical_dimensions",
        "verifier_discriminative_power",
    }
    for dim_name in expected_dims_with_summary:
        d = spec.get_dimension(dim_name)
        assert d is not None, f"{dim_name} missing from spec"
        assert "verifier_assertion_summary" in d.inputs, \
            f"{dim_name} should consume verifier_assertion_summary"
