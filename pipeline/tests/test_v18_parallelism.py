"""M3.5 — verify the engine's parallelism preserves correctness + ordering.

We add this *after* the rest of the milestones to lock in behaviour: turning
on dim_parallelism / sample_parallelism must not change the outputs the
sequential pipeline produced. Tests use MockLLMClient so they're fast and
deterministic.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from gdpval_qc.finding import DimensionFinding
from gdpval_qc.mock_llm import MockLLMClient, RecordedCall, make_attempt_json
from gdpval_qc.v18_engine import V18Engine
from gdpval_qc.v18_loader import Sample
from gdpval_qc.v18_spec import V18Spec


REPO_ROOT     = Path(__file__).resolve().parent.parent
V18_SPEC_PATH = REPO_ROOT / "specs" / "gdpval_task_quality_v18.md"


@pytest.fixture(scope="session")
def spec() -> V18Spec:
    return V18Spec.from_markdown(V18_SPEC_PATH)


def _trivial_programmatic_callback(sample: Sample, dim) -> DimensionFinding:
    return DimensionFinding(
        dimension=dim.name, dimension_name=dim.dimension_name,
        gate_role=dim.gate.role, applicable=True, severity=0,
        fixability="n/a", confidence="high",
        headline="ok", detail="programmatic ok",
        evidence_quote=None, judges_agreed=True,
    )


def _make_sample(task_id: str = "t") -> Sample:
    return Sample(task_id=task_id, task_dir=Path("/tmp"), fields={
        "task_id": task_id, "instruction": "do thing", "category": "Test",
        "solution_files": [],            # conditional dims will skip
        "verifier_spec_json": None,      # ditto
        "input_files": [],
        "solution_reasoning": None,
        "verifier_assertion_summary": None,
    })


def _make_engine(spec: V18Spec, *, dim_parallelism: int, sample_parallelism: int,
                  delay_seconds: float = 0.0) -> tuple[V18Engine, MockLLMClient]:
    """Build an engine whose judge client optionally sleeps per call. With a
    non-zero delay, the wall-clock speedup from parallelism is measurable."""

    def responder(call: RecordedCall) -> str:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        return make_attempt_json(
            severity=0, confidence="high", applicable=True,
            headline="ok", justification="ok", fixability="n/a",
        )

    judge_client = MockLLMClient(responder=responder)
    engine = V18Engine(
        spec=spec,
        judge_client_factory=lambda model: judge_client,
        synthesizer_client=None,  # deterministic synth path
        programmatic_callbacks={
            "check_metadata_completeness":         _trivial_programmatic_callback,
            "check_verifier_parseable":            _trivial_programmatic_callback,
            "check_verifier_count_in_range":       _trivial_programmatic_callback,
            "check_verifier_outcome_grader_present": _trivial_programmatic_callback,
        },
        dim_parallelism=dim_parallelism,
        sample_parallelism=sample_parallelism,
    )
    return engine, judge_client


# ── Validation: bad parallelism args ───────────────────────────────────────

def test_engine_rejects_invalid_parallelism(spec: V18Spec) -> None:
    with pytest.raises(ValueError):
        V18Engine(spec=spec, judge_client_factory=lambda m: None,  # type: ignore[arg-type]
                   dim_parallelism=0)
    with pytest.raises(ValueError):
        V18Engine(spec=spec, judge_client_factory=lambda m: None,  # type: ignore[arg-type]
                   sample_parallelism=-1)


# ── Dim parallelism: order preservation ────────────────────────────────────

def test_dim_parallelism_preserves_finding_order(spec: V18Spec) -> None:
    """all_findings must match spec.dimensions order regardless of dim_parallelism."""
    engine_seq, _ = _make_engine(spec, dim_parallelism=1, sample_parallelism=1)
    engine_par, _ = _make_engine(spec, dim_parallelism=8, sample_parallelism=1)

    sample = _make_sample()
    seq = engine_seq.assess_sample(sample)
    par = engine_par.assess_sample(sample)

    seq_order = [f.dimension for f in seq.all_findings]
    par_order = [f.dimension for f in par.all_findings]
    assert seq_order == par_order
    spec_order = [d.name for d in spec.dimensions]
    assert seq_order == spec_order


def test_dim_parallelism_preserves_verdict(spec: V18Spec) -> None:
    """Parallel and sequential must produce identical verdicts on the same input."""
    engine_seq, _ = _make_engine(spec, dim_parallelism=1, sample_parallelism=1)
    engine_par, _ = _make_engine(spec, dim_parallelism=8, sample_parallelism=1)
    sample = _make_sample()
    assert engine_seq.assess_sample(sample).verdict == engine_par.assess_sample(sample).verdict


# ── Sample parallelism: order preservation ─────────────────────────────────

def test_sample_parallelism_preserves_sample_order(spec: V18Spec) -> None:
    """BatchReview.samples must be in input order regardless of sample_parallelism."""
    engine_seq, _ = _make_engine(spec, dim_parallelism=1, sample_parallelism=1)
    engine_par, _ = _make_engine(spec, dim_parallelism=4, sample_parallelism=4)

    samples = [_make_sample(task_id=f"t_{i}") for i in range(8)]

    seq = engine_seq.assess_batch(samples, run_calibration=False)
    par = engine_par.assess_batch(samples, run_calibration=False)

    expected_ids = [s.task_id for s in samples]
    seq_ids = [r.sample_id for r in seq.samples]
    par_ids = [r.sample_id for r in par.samples]
    assert seq_ids == expected_ids
    assert par_ids == expected_ids


def test_sample_parallelism_preserves_batch_summary(spec: V18Spec) -> None:
    engine_seq, _ = _make_engine(spec, dim_parallelism=1, sample_parallelism=1)
    engine_par, _ = _make_engine(spec, dim_parallelism=4, sample_parallelism=4)

    samples = [_make_sample(task_id=f"t_{i}") for i in range(4)]
    seq = engine_seq.assess_batch(samples, run_calibration=False)
    par = engine_par.assess_batch(samples, run_calibration=False)

    assert seq.batch_summary.verdict_counts == par.batch_summary.verdict_counts


# ── Wall-clock check: parallelism actually parallelises ────────────────────

def test_dim_parallelism_provides_speedup(spec: V18Spec) -> None:
    """With a slow mock judge, parallelism must produce measurable speedup.

    21 LLM dims × 2 judges (ensemble parallel) = 21 sequential judge "groups"
    of ~0.05s each at dim_parallelism=1 → ~1.0s.
    At dim_parallelism=8 we expect ≤ ~0.4s.
    """
    delay = 0.05  # 50ms per judge call
    sample = _make_sample()

    engine_seq, _ = _make_engine(spec, dim_parallelism=1, sample_parallelism=1,
                                  delay_seconds=delay)
    t0 = time.time()
    engine_seq.assess_sample(sample)
    t_seq = time.time() - t0

    engine_par, _ = _make_engine(spec, dim_parallelism=8, sample_parallelism=1,
                                  delay_seconds=delay)
    t0 = time.time()
    engine_par.assess_sample(sample)
    t_par = time.time() - t0

    # Conservative bound: parallel should be at least 1.5x faster
    assert t_par * 1.5 < t_seq, \
        f"expected dim_parallelism=8 to be ≥ 1.5x faster than 1; got {t_seq:.2f}s vs {t_par:.2f}s"


def test_sample_parallelism_provides_speedup(spec: V18Spec) -> None:
    """Four samples × dim_parallelism=1 × 50ms ≈ 4 × ~1.0s = ~4s sequential.
    With sample_parallelism=4 we expect ≤ ~1.5s."""
    delay = 0.05
    samples = [_make_sample(task_id=f"t_{i}") for i in range(4)]

    engine_seq, _ = _make_engine(spec, dim_parallelism=4, sample_parallelism=1,
                                  delay_seconds=delay)
    t0 = time.time()
    engine_seq.assess_batch(samples, run_calibration=False)
    t_seq = time.time() - t0

    engine_par, _ = _make_engine(spec, dim_parallelism=4, sample_parallelism=4,
                                  delay_seconds=delay)
    t0 = time.time()
    engine_par.assess_batch(samples, run_calibration=False)
    t_par = time.time() - t0

    assert t_par * 1.5 < t_seq, \
        f"expected sample_parallelism=4 to be ≥ 1.5x faster than 1; got {t_seq:.2f}s vs {t_par:.2f}s"


# ── Concurrency safety: shared MockLLMClient must record every call ───────

def test_concurrent_judge_calls_all_recorded(spec: V18Spec) -> None:
    """If parallel dispatch lost calls due to a thread-safety bug, the call
    count would be wrong. With ~21 LLM dims × 2 judges per sample × 4 samples
    = 168 expected calls, we must see exactly that."""
    engine, client = _make_engine(spec, dim_parallelism=8, sample_parallelism=4)
    samples = [_make_sample(task_id=f"t_{i}") for i in range(4)]
    engine.assess_batch(samples, run_calibration=False)

    n_llm_dims = sum(1 for d in spec.dimensions
                      if d.check_kind == "llm" and d.applies_when is None)
    expected_calls = len(samples) * n_llm_dims * len(spec.models)
    assert len(client.calls) == expected_calls, \
        f"expected {expected_calls} judge calls, got {len(client.calls)}"
