"""M5 — end-to-end framework run on a 3-task subset of the omega corpus.

Validates the full pipeline (loader → preconditions → judging via
MockLLMClient → aggregation → verdict → synthesizer → batch summary →
calibration → emitters) without any real API calls.

Also covers calibration runner edge cases (empty goldens, missing path,
matching/drifting expected verdicts) and the four built-in programmatic
callbacks.
"""

from __future__ import annotations

import os

import json
from pathlib import Path

import pytest

from gdpval_qc.finding import DimensionFinding
from gdpval_qc.mock_llm import MockLLMClient, make_attempt_json
from gdpval_qc.review import BatchReview
from gdpval_qc.v18_callbacks import (
    BUILTIN_CALLBACKS,
    check_metadata_completeness,
    check_verifier_count_in_range,
    check_verifier_outcome_grader_present,
    check_verifier_parseable,
)
from gdpval_qc.v18_calibration import run_calibration
from gdpval_qc.v18_emitter import write_batch_artifacts
from gdpval_qc.v18_engine import V18Engine
from gdpval_qc.v18_loader import Sample, TaskCorpusLoader
from gdpval_qc.v18_spec import V18Spec


REPO_ROOT     = Path(__file__).resolve().parent.parent
V18_SPEC_PATH = REPO_ROOT / "specs" / "gdpval_task_quality_v18.md"
OMEGA_ROOT    = Path(os.environ.get("GDPVAL_TEST_CORPUS") or (Path(__file__).resolve().parent.parent / "data" / "sample_corpus"))


@pytest.fixture(scope="session")
def spec() -> V18Spec:
    return V18Spec.from_markdown(V18_SPEC_PATH)


# ── Programmatic callbacks ─────────────────────────────────────────────────

def test_check_metadata_completeness_pass(spec: V18Spec) -> None:
    dim = spec.get_dimension("metadata_completeness")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={"category": "Finance"})
    f = check_metadata_completeness(s, dim)
    assert f.severity == 0
    assert f.applicable is True


def test_check_metadata_completeness_empty(spec: V18Spec) -> None:
    dim = spec.get_dimension("metadata_completeness")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={"category": ""})
    f = check_metadata_completeness(s, dim)
    assert f.severity == 2
    assert "empty" in f.headline.lower()


def test_check_verifier_parseable_pass(spec: V18Spec) -> None:
    dim = spec.get_dimension("verifier_spec_parseable")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "verifier_spec_json": json.dumps({"verifiers": [{"name": "x"}]}),
    })
    f = check_verifier_parseable(s, dim)
    assert f.severity == 0


def test_check_verifier_parseable_bad_json(spec: V18Spec) -> None:
    dim = spec.get_dimension("verifier_spec_parseable")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "verifier_spec_json": "{not json",
    })
    f = check_verifier_parseable(s, dim)
    assert f.severity == 2


def test_check_verifier_count_in_range_inside(spec: V18Spec) -> None:
    dim = spec.get_dimension("verifier_count_in_range")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "verifier_spec_json": json.dumps({
            "verifiers": [{"name": f"v{i}"} for i in range(10)],
        }),
    })
    f = check_verifier_count_in_range(s, dim)
    assert f.severity == 0


def test_check_verifier_count_just_outside_returns_sev1(spec: V18Spec) -> None:
    dim = spec.get_dimension("verifier_count_in_range")
    # Spec: min 6, max 20. 5 is 1 outside.
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "verifier_spec_json": json.dumps({
            "verifiers": [{"name": f"v{i}"} for i in range(5)],
        }),
    })
    f = check_verifier_count_in_range(s, dim)
    assert f.severity == 1


def test_check_verifier_count_far_outside_returns_sev2(spec: V18Spec) -> None:
    dim = spec.get_dimension("verifier_count_in_range")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "verifier_spec_json": json.dumps({"verifiers": []}),
    })
    f = check_verifier_count_in_range(s, dim)
    assert f.severity == 2


def test_check_outcome_grader_present_legacy_classification_yes(spec: V18Spec) -> None:
    """GDPVal-216 legacy schema: classification='core' is an outcome marker."""
    dim = spec.get_dimension("verifier_outcome_grader_present")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "verifier_spec_json": json.dumps({
            "verifiers": [{"name": "v", "metadata": {"classification": "core"}}],
        }),
    })
    f = check_verifier_outcome_grader_present(s, dim)
    assert f.severity == 0


def test_check_outcome_grader_present_omega_grading_role_yes(spec: V18Spec) -> None:
    """Omega schema: grading_role='outcome' is an outcome marker."""
    dim = spec.get_dimension("verifier_outcome_grader_present")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "verifier_spec_json": json.dumps({
            "verifiers": [
                {"name": "v", "metadata": {
                    "importance": "core", "grading_role": "outcome",
                }},
            ],
        }),
    })
    f = check_verifier_outcome_grader_present(s, dim)
    assert f.severity == 0
    assert "outcome-grading" in f.headline


def test_check_outcome_grader_present_omega_secondary_outcome_still_counts(spec: V18Spec) -> None:
    """A `secondary` rubric that still grades outcomes counts as an
    outcome-grader (the check is about outcome vs process, not core vs
    secondary). One omega task_11 verifier has importance=secondary +
    grading_role=outcome and is correctly counted."""
    dim = spec.get_dimension("verifier_outcome_grader_present")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "verifier_spec_json": json.dumps({
            "verifiers": [
                {"name": "v_proc",      "metadata": {"importance": "core",      "grading_role": "process"}},
                {"name": "v_sec_outc",  "metadata": {"importance": "secondary", "grading_role": "outcome"}},
            ],
        }),
    })
    f = check_verifier_outcome_grader_present(s, dim)
    assert f.severity == 0
    assert "1 outcome-grading" in f.headline


def test_check_outcome_grader_present_no_legacy(spec: V18Spec) -> None:
    """Legacy schema with all-secondary verifiers → no outcome grader."""
    dim = spec.get_dimension("verifier_outcome_grader_present")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "verifier_spec_json": json.dumps({
            "verifiers": [{"name": "v", "metadata": {"classification": "secondary"}}],
        }),
    })
    f = check_verifier_outcome_grader_present(s, dim)
    assert f.severity == 2


def test_check_outcome_grader_present_no_omega(spec: V18Spec) -> None:
    """Omega schema with no grading_role=outcome rubrics → fail."""
    dim = spec.get_dimension("verifier_outcome_grader_present")
    s = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "verifier_spec_json": json.dumps({
            "verifiers": [
                {"name": "v1", "metadata": {"importance": "core",      "grading_role": "process"}},
                {"name": "v2", "metadata": {"importance": "secondary", "grading_role": "process"}},
            ],
        }),
    })
    f = check_verifier_outcome_grader_present(s, dim)
    assert f.severity == 2
    assert "no outcome-grading" in f.headline


def test_check_outcome_grader_present_real_omega_task_11(spec: V18Spec) -> None:
    """Smoke test against the real omega task_11 verifier.json. Task_11 has
    11 importance=core+grading_role=outcome verifiers + 1 secondary+outcome
    (total 12 outcome graders out of 17 verifiers) so the check must pass."""
    # Look first at GDPVAL_TEST_CORPUS/task_11 (matches OMEGA_ROOT used elsewhere
    # in this file), then fall back to the bundled sample corpus shipped at
    # data/sample_corpus/task_11.
    candidates = [OMEGA_ROOT / "task_11"]
    bundled = Path(__file__).resolve().parent.parent / "data" / "sample_corpus" / "task_11"
    if bundled.is_dir() and bundled not in candidates:
        candidates.append(bundled)
    omega = next((c for c in candidates if c.is_dir()), None)
    if omega is None:
        pytest.skip("omega task_11 not present at any known location")

    spec_path = omega / "tests" / "verifier.json"
    s = Sample(task_id="task_11", task_dir=omega, fields={
        "verifier_spec_json": spec_path.read_text(encoding="utf-8"),
    })
    dim = spec.get_dimension("verifier_outcome_grader_present")
    f = check_verifier_outcome_grader_present(s, dim)
    assert f.severity == 0, f"task_11 should have outcome graders, got severity={f.severity}"
    assert "12" in f.headline, \
        f"task_11 has 12 outcome-grading verifiers, but headline says {f.headline!r}"


# ── Calibration runner ─────────────────────────────────────────────────────

def test_calibration_disabled_returns_disabled_report(spec: V18Spec) -> None:
    # Build a custom-spec object where calibration is disabled
    spec.calibration.enabled = False
    engine = V18Engine(
        spec=spec,
        judge_client_factory=lambda m: MockLLMClient(default=make_attempt_json()),
        synthesizer_client=None,
    )
    rpt = run_calibration(spec, engine)
    assert rpt.enabled is False
    assert rpt.goldens_count == 0
    spec.calibration.enabled = True  # restore


def test_calibration_warns_when_path_missing(spec: V18Spec, tmp_path: Path) -> None:
    spec.calibration.goldens_path = str(tmp_path / "absent_dir")
    engine = V18Engine(
        spec=spec,
        judge_client_factory=lambda m: MockLLMClient(default=make_attempt_json()),
    )
    rpt = run_calibration(spec, engine)
    assert rpt.enabled is True
    assert rpt.goldens_count == 0
    assert "does not exist" in (rpt.warning or "")


def test_calibration_warns_when_no_goldens_found(spec: V18Spec, tmp_path: Path) -> None:
    # Empty dir
    empty = tmp_path / "empty"
    empty.mkdir()
    spec.calibration.goldens_path = str(empty)
    engine = V18Engine(
        spec=spec,
        judge_client_factory=lambda m: MockLLMClient(default=make_attempt_json()),
    )
    rpt = run_calibration(spec, engine)
    assert rpt.enabled is True
    assert rpt.goldens_count == 0
    assert "empty" in (rpt.warning or "")


# ── Full pipeline E2E on 3 omega tasks (mock LLMs) ─────────────────────────

_TASK_COUNT = len(list(OMEGA_ROOT.glob("task_*"))) if OMEGA_ROOT.is_dir() else 0


def _skip_if_omega_missing() -> None:
    if not OMEGA_ROOT.is_dir():
        pytest.skip(f"omega dataset not present at {OMEGA_ROOT}")


def _skip_if_corpus_smaller_than(n: int) -> None:
    if _TASK_COUNT < n:
        pytest.skip(f"e2e test needs ≥{n} tasks; corpus at {OMEGA_ROOT} has {_TASK_COUNT}")


def _all_clean_judge() -> MockLLMClient:
    """A mock judge that always returns severity 0 / applicable=True."""
    return MockLLMClient(default=make_attempt_json(
        severity=0, confidence="high", applicable=True,
        headline="no issue", justification="clean.", fixability="n/a",
    ))


def test_e2e_omega_subset_all_judges_clean(spec: V18Spec, tmp_path: Path) -> None:
    """End-to-end smoke: with all-clean judges + clean programmatic checks,
    every sample should land at ACCEPT and the full artifacts get written."""
    _skip_if_corpus_smaller_than(3)

    # Disable calibration for this test — we only want to verify the per-sample pipeline.
    spec.calibration.enabled = False

    loader = TaskCorpusLoader(OMEGA_ROOT, spec)
    samples = [loader.load_sample(tid) for tid in loader.task_ids()[:3]]

    judge = _all_clean_judge()
    synth = MockLLMClient(default=json.dumps({
        "one_line": "Clean across all dimensions.",
        "issues": [],
    }))
    engine = V18Engine(
        spec=spec,
        judge_client_factory=lambda m: judge,
        synthesizer_client=synth,
    )

    batch = engine.assess_batch(samples)
    assert batch.batch_summary.sample_count == 3

    # `verifier_outcome_grader_present` must NOT appear in the failure-mode
    # histogram for any omega sample. Prior to the v18.3 schema fix, this
    # check incorrectly fired on every omega task because the callback only
    # accepted metadata.classification=='core' (legacy GDPVal-216 schema)
    # and not metadata.grading_role=='outcome' (omega schema). Each omega
    # task_N/tests/verifier.json uses the omega schema so the dim now
    # correctly reports outcome graders as present.
    assert "verifier_outcome_grader_present" not in batch.batch_summary.failure_mode_histogram, (
        "verifier_outcome_grader_present should NOT fire on omega tasks "
        "after the v18.3 schema fix"
    )

    # No LLM-judge findings on this run (judges are all-clean mocks).
    # The only remaining source of non-zero findings is the other programmatic
    # callbacks (e.g. verifier_count_in_range when a task has > 20 verifiers).
    # We don't assert a specific verdict mix, but we do require no rejects
    # since judges are clean and there are no structural problems.
    for s in batch.samples:
        assert s.verdict in ("accept", "accept_with_fixes"), \
            f"unexpected verdict {s.verdict} for {s.sample_id} on all-clean judges"

    # Write artifacts
    paths = write_batch_artifacts(batch, tmp_path, top_issues_cap=3)
    for name in ("batch_review.json", "reviewer_queue.csv", "batch_summary.md"):
        assert paths[name].is_file()
    assert any((tmp_path / "raw").glob("sample_*.json"))

    # restore calibration setting
    spec.calibration.enabled = True


def test_e2e_omega_subset_with_blocking_finding(spec: V18Spec, tmp_path: Path) -> None:
    """E2E: inject a single blocking finding on overall_gdpval_fit. The
    sample should land in NEEDS_REVIEW or REJECT_STRUCTURAL (sev 2 with
    structural fixability on a dim with reject_at_severity=2)."""
    _skip_if_corpus_smaller_than(3)
    spec.calibration.enabled = False

    loader = TaskCorpusLoader(OMEGA_ROOT, spec)
    samples = [loader.load_sample(tid) for tid in loader.task_ids()[:3]]

    # Two judges per spec, both saying severity=2 / structural on
    # overall_gdpval_fit, severity=0 on everything else.
    def factory(model: str) -> MockLLMClient:
        canned: dict[tuple, str] = {}
        canned[(model, "Overall GDPVal Fit")] = make_attempt_json(
            severity=2, confidence="high", applicable=True,
            evidence_quote="Acme Corporation",
            headline="reads as constructed/benchmark-shaped",
            justification="generic stakeholders + round numbers + benchmark-like scope",
            fixability="structural",
        )
        return MockLLMClient(canned=canned, default=make_attempt_json(
            severity=0, confidence="high", applicable=True,
            headline="no issue", justification="clean.", fixability="n/a",
        ))

    # The blocking finding is overall_gdpval_fit at sev-2 structural, which is
    # verdict-determinative (reject_at_severity=2) — the hard guard keeps it
    # blocking regardless of classification. If other (programmatic) candidates
    # are present and go unclassified, the synthesizer falls back to surfacing
    # all candidates as blocking; either way overall_gdpval_fit is surfaced.
    synth = MockLLMClient(default=json.dumps({
        "one_line": "Task feels benchmark-shaped, not real delegated work.",
        "issues": [{
            "index": 0,
            "classification": "blocking",
            "reason": "reads as benchmark-shaped, not authentic delegated work",
            "action": "Revise the scenario to use realistic stakeholders and figures.",
        }],
    }))
    engine = V18Engine(
        spec=spec,
        judge_client_factory=factory,
        synthesizer_client=synth,
    )
    batch = engine.assess_batch(samples)

    # overall_gdpval_fit has reject_at_severity=2 + structural fixability → REJECT_STRUCTURAL
    assert all(s.verdict == "reject_structural" for s in batch.samples), \
        f"unexpected verdicts: {[s.verdict for s in batch.samples]}"

    # Each sample's top_issues should include overall_gdpval_fit
    for s in batch.samples:
        assert any(i.dimension == "overall_gdpval_fit" for i in s.top_issues)

    # Failure-mode histogram counts overall_gdpval_fit 3 times
    assert batch.batch_summary.failure_mode_histogram.get("overall_gdpval_fit") == 3

    spec.calibration.enabled = True


def test_e2e_omega_subset_judge_disagreement_routes_to_review(
    spec: V18Spec,
) -> None:
    """E2E: one judge says sev 0, the other sev 2 on a blocking dim → judges
    disagree → NEEDS_REVIEW per the verdict rules."""
    _skip_if_omega_missing()
    spec.calibration.enabled = False

    loader = TaskCorpusLoader(OMEGA_ROOT, spec)
    samples = [loader.load_sample(loader.task_ids()[0])]

    def factory(model: str) -> MockLLMClient:
        if model == spec.models[0].model:
            # First judge — clean
            return MockLLMClient(default=make_attempt_json(severity=0))
        else:
            # Second judge — blocking sev 2 with evidence
            canned: dict[tuple, str] = {
                (model, "Overall GDPVal Fit"): make_attempt_json(
                    severity=2, confidence="high", evidence_quote="Acme Corp",
                    headline="constructed", justification="...",
                    fixability="structural",
                ),
            }
            return MockLLMClient(canned=canned, default=make_attempt_json(severity=0))

    engine = V18Engine(
        spec=spec, judge_client_factory=factory, synthesizer_client=None,
    )
    batch = engine.assess_batch(samples)
    s = batch.samples[0]
    assert s.verdict == "needs_review", f"expected needs_review, got {s.verdict}"
    assert "disagreement" in (s.review_required_because or "").lower()

    spec.calibration.enabled = True
