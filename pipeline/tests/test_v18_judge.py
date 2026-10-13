"""M3 tests — prompt building, response parsing, judge invocation, and
ensemble + aggregation logic (anti-overcall, confidence demotion, judge
disagreement). All judge calls go through MockLLMClient."""

from __future__ import annotations

import os

from pathlib import Path

import pytest

from gdpval_qc.finding import JudgeAttempt, DimensionFinding
from gdpval_qc.mock_llm import MockLLMClient, make_attempt_json
from gdpval_qc.v18_aggregate import (
    aggregate_attempts, enforce_evidence_quote, make_skipped_finding,
)
from gdpval_qc.v18_judge import (
    build_system_prompt, build_user_prompt, parse_judge_response,
    run_one_judge, run_ensemble, evaluate_applies_when, ParseError,
)
from gdpval_qc.v18_loader import FileContent, Sample, TaskCorpusLoader
from gdpval_qc.v18_spec import V18Spec


REPO_ROOT     = Path(__file__).resolve().parent.parent
V18_SPEC_PATH = REPO_ROOT / "specs" / "gdpval_task_quality_v18.md"
OMEGA_ROOT    = Path(os.environ.get("GDPVAL_TEST_CORPUS") or (Path(__file__).resolve().parent.parent / "data" / "sample_corpus"))


@pytest.fixture(scope="session")
def spec() -> V18Spec:
    return V18Spec.from_markdown(V18_SPEC_PATH)


@pytest.fixture(scope="session")
def omega_task_1(spec: V18Spec) -> Sample:
    if not OMEGA_ROOT.is_dir():
        pytest.skip(f"omega dataset not present at {OMEGA_ROOT}")
    return TaskCorpusLoader(OMEGA_ROOT, spec).load_sample("task_1")


# ── Prompt building ────────────────────────────────────────────────────────

def test_system_prompt_includes_severity_scale(spec: V18Spec) -> None:
    sys = build_system_prompt(spec)
    assert "Severity scale" in sys
    for level, text in spec.severity_scale.items():
        assert text in sys, f"severity level {level} text missing from system prompt"
    # JSON shape requirement is present
    assert '"severity"' in sys
    assert '"evidence_quote"' in sys
    assert '"confidence"' in sys
    assert '"fixability"' in sys


def test_system_prompt_states_evidence_policy(spec: V18Spec) -> None:
    sys = build_system_prompt(spec)
    assert "REQUIRED when severity" in sys
    assert "verbatim" in sys.lower()


def test_user_prompt_includes_dimension_name_and_inputs(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    assert dim is not None
    sample = Sample(
        task_id="t1",
        task_dir=Path("/tmp/t1"),
        fields={
            "instruction": "Write a memo on Q3 results.",
            "category":    "Finance",
            "solution_files": [
                FileContent(name="memo.docx", path=Path("/tmp/memo.docx"),
                             text="Q3 revenue increased 8%."),
            ],
        },
    )
    user = build_user_prompt(dim, sample)
    assert "<dimension>" in user
    assert "Overall GDPVal Fit" in user
    assert "<instruction>" in user
    assert "Q3 results" in user
    assert "<solution_files>" in user
    assert "memo.docx" in user


def test_user_prompt_truncates_overlarge_field(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    huge = "X" * 200_000
    sample = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "instruction": huge, "category": "Finance", "solution_files": [],
    })
    user = build_user_prompt(dim, sample)
    assert "truncated" in user
    assert len(user) < 200_000


# ── Response parsing ───────────────────────────────────────────────────────

def test_parse_valid_response() -> None:
    text = make_attempt_json(
        severity=2, confidence="high", applicable=True,
        evidence_quote="we should consider",
        headline="tentative language", justification="evidence",
        fixability="fixable",
    )
    a = parse_judge_response(text, model="m1")
    assert a.severity == 2
    assert a.confidence == "high"
    assert a.applicable is True
    assert a.evidence_quote == "we should consider"
    assert a.fixability == "fixable"
    assert a.error is None


def test_parse_response_inside_code_fence() -> None:
    text = "```json\n" + make_attempt_json(severity=1) + "\n```"
    a = parse_judge_response(text, model="m1")
    assert a.severity == 1


def test_parse_response_with_preamble() -> None:
    text = "Sure, here is my analysis:\n" + make_attempt_json(severity=0)
    a = parse_judge_response(text, model="m1")
    assert a.severity == 0


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ParseError):
        parse_judge_response("not json at all", model="m1")


def test_parse_out_of_range_severity_raises() -> None:
    with pytest.raises(ParseError):
        parse_judge_response(make_attempt_json(severity=5), model="m1")


def test_parse_unknown_confidence_raises() -> None:
    bad = '{"severity":0,"confidence":"meh","applicable":true,"evidence_quote":null,"headline":"x","justification":"y","fixability":"n/a"}'
    with pytest.raises(ParseError):
        parse_judge_response(bad, model="m1")


def test_parse_unknown_fixability_raises() -> None:
    bad = make_attempt_json(severity=2, evidence_quote="q",
                              fixability="x")  # type: ignore
    with pytest.raises(ParseError):
        parse_judge_response(bad, model="m1")


# ── Single-judge invocation ────────────────────────────────────────────────

def _make_sample(dim_inputs: list[str] | None = None) -> Sample:
    return Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "instruction": "Test instruction.",
        "category":    "Test",
        "solution_files": [],
        "input_files":    [],
        "verifier_spec_json": '{"verifiers": [{"assertion": {"type": "rubric"}}]}',
    })


def test_run_one_judge_success(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    canned = make_attempt_json(
        severity=2, confidence="high",
        evidence_quote="benchmark-shaped",
        headline="materially test-like",
        justification="...", fixability="structural",
    )
    client = MockLLMClient(default=canned)
    attempt = run_one_judge(client, spec, dim, _make_sample(),
                             model="gpt-5.5", max_tokens=4096)
    assert attempt.error is None
    assert attempt.severity == 2
    assert attempt.fixability == "structural"


def test_run_one_judge_handles_parse_error(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    client = MockLLMClient(default="this is not JSON")
    attempt = run_one_judge(client, spec, dim, _make_sample(), model="m1")
    assert attempt.error is not None
    assert "ParseError" in attempt.error
    assert attempt.severity == 0
    assert attempt.applicable is False


def test_run_one_judge_handles_client_exception(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    client = MockLLMClient(raise_on_call=RuntimeError("boom"))
    attempt = run_one_judge(client, spec, dim, _make_sample(), model="m1")
    assert attempt.error is not None
    assert "RuntimeError: boom" in attempt.error


# ── Ensemble invocation ────────────────────────────────────────────────────

def test_run_ensemble_calls_each_model_once(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    canned = make_attempt_json(severity=0)
    client = MockLLMClient(default=canned)

    def factory(model: str) -> MockLLMClient:
        return client

    attempts = run_ensemble(spec, dim, _make_sample(), factory)
    models_called = {c.model for c in client.calls}
    spec_models = {m.model for m in spec.models}
    assert models_called == spec_models
    assert len(attempts) == len(spec.models)


# ── Preconditions ──────────────────────────────────────────────────────────

def test_evaluate_applies_when_unconditional(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    # No applies_when → always applies
    assert evaluate_applies_when(dim, _make_sample()) is True


def test_evaluate_applies_when_builtin(spec: V18Spec) -> None:
    dim = spec.get_dimension("solution_format_match")
    # solution_present should return False on a sample with no solution_files
    empty = Sample(task_id="t", task_dir=Path("/tmp"),
                    fields={"solution_files": []})
    assert evaluate_applies_when(dim, empty) is False

    # And True when solution_files has content
    with_sol = Sample(task_id="t", task_dir=Path("/tmp"), fields={
        "solution_files": [FileContent("x.docx", Path("/tmp/x.docx"), "hello")],
    })
    assert evaluate_applies_when(dim, with_sol) is True


# ── Evidence enforcement ───────────────────────────────────────────────────

def test_evidence_quote_required_demotes_unquoted(spec: V18Spec) -> None:
    attempts = [
        JudgeAttempt(model="m1", severity=2, confidence="high", applicable=True,
                     headline="bad", justification="...", fixability="fixable",
                     evidence_quote=None),
        JudgeAttempt(model="m2", severity=1, confidence="medium", applicable=True,
                     headline="meh", justification="...", fixability="trivial",
                     evidence_quote="quoted thing"),
    ]
    enforced, demoted = enforce_evidence_quote(attempts, require_evidence_quote=True)
    assert enforced[0].severity == 0
    assert enforced[1].severity == 1
    assert "no evidence quote" in demoted[0]


def test_evidence_quote_not_required_keeps_severity() -> None:
    attempts = [
        JudgeAttempt(model="m1", severity=2, confidence="high", applicable=True,
                     headline="bad", justification="...", fixability="fixable",
                     evidence_quote=None),
    ]
    enforced, demoted = enforce_evidence_quote(attempts, require_evidence_quote=False)
    assert enforced[0].severity == 2
    assert demoted == []


# ── Aggregation rules ──────────────────────────────────────────────────────

def _attempt(model: str, severity: int, *, conf: str = "high",
              applicable: bool = True, evidence: str | None = "q",
              fixability: str = "fixable") -> JudgeAttempt:
    return JudgeAttempt(
        model=model, severity=severity, confidence=conf, applicable=applicable,
        headline=f"sev={severity}", justification=f"j-{model}",
        fixability=fixability, evidence_quote=evidence,
    )


def test_aggregate_max_severity(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    attempts = [_attempt("m1", 1), _attempt("m2", 3)]
    f = aggregate_attempts(dim, attempts, spec)
    assert f.severity == 3
    assert f.headline == "sev=3"


def test_aggregate_low_confidence_demotion_at_sev1(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    # Both judges at sev 1 with low confidence
    attempts = [
        _attempt("m1", 1, conf="low"),
        _attempt("m2", 1, conf="low"),
    ]
    f = aggregate_attempts(dim, attempts, spec)
    assert f.severity == 0
    assert any("low confidence at severity 1" in d for d in f.demoted_because)


def test_aggregate_low_confidence_routes_review_at_sev2(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    attempts = [
        _attempt("m1", 2, conf="low"),
        _attempt("m2", 2, conf="medium"),
    ]
    f = aggregate_attempts(dim, attempts, spec)
    assert f.severity == 2
    assert f.needs_review_signal is True


def test_aggregate_judges_agreed_when_within_one(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    f = aggregate_attempts(dim, [_attempt("m1", 1), _attempt("m2", 2)], spec)
    assert f.judges_agreed is True


def test_aggregate_judges_disagree_when_two_apart(spec: V18Spec) -> None:
    dim = spec.get_dimension("overall_gdpval_fit")
    f = aggregate_attempts(dim, [_attempt("m1", 0), _attempt("m2", 2)], spec)
    assert f.judges_agreed is False
    assert "disagreed" in f.detail.lower() or "ensemble" in f.detail.lower()


def test_aggregate_evidence_quote_carries_through(spec: V18Spec) -> None:
    dim = spec.get_dimension("instruction_authenticity")
    attempts = [_attempt("m1", 2, evidence="we should consider"),
                _attempt("m2", 0, evidence=None)]
    f = aggregate_attempts(dim, attempts, spec)
    assert f.severity == 2
    assert f.evidence_quote == "we should consider"


def test_aggregate_majority_not_applicable_yields_skipped(spec: V18Spec) -> None:
    dim = spec.get_dimension("solution_chart_quality")
    attempts = [
        _attempt("m1", 0, applicable=False, evidence=None, fixability="n/a"),
        _attempt("m2", 0, applicable=False, evidence=None, fixability="n/a"),
    ]
    f = aggregate_attempts(dim, attempts, spec)
    assert f.applicable is False
    assert f.severity == 0
    assert f.skipped_because == "not_applicable"


def test_aggregate_all_attempts_failed(spec: V18Spec) -> None:
    """If every judge errored, applicability defaults to False and the
    finding is treated as skipped."""
    dim = spec.get_dimension("overall_gdpval_fit")
    failed = JudgeAttempt(
        model="m1", severity=0, confidence="low", applicable=False,
        headline="failed", justification="oops", fixability="n/a",
        evidence_quote=None, error="RuntimeError: x",
    )
    f = aggregate_attempts(dim, [failed, failed], spec)
    assert f.applicable is False
    assert f.skipped_because == "not_applicable"


def test_aggregate_evidence_demotion_is_recorded(spec: V18Spec) -> None:
    """A judge missing its evidence quote should produce a demoted_because line."""
    dim = spec.get_dimension("overall_gdpval_fit")
    attempts = [
        _attempt("m1", 2, evidence=None),     # no evidence — gets demoted
        _attempt("m2", 1, evidence="quoted"), # legitimate sev 1
    ]
    f = aggregate_attempts(dim, attempts, spec)
    # After enforcement, m1 has sev 0; the aggregate is now max(0, 1) = 1
    assert f.severity == 1
    assert any("no evidence quote" in d for d in f.demoted_because)


# ── make_skipped_finding ───────────────────────────────────────────────────

def test_make_skipped_finding(spec: V18Spec) -> None:
    dim = spec.get_dimension("solution_chart_quality")
    f = make_skipped_finding(dim, "solution_has_charts=False")
    assert f.applicable is False
    assert f.severity == 0
    assert "solution_has_charts" in f.detail
    assert f.skipped_because == "solution_has_charts=False"


# ── Integration smoke: ensemble + aggregation end-to-end ───────────────────

def test_ensemble_then_aggregate_smoke(spec: V18Spec) -> None:
    """One full ensemble call + aggregation. Two models disagree on severity."""
    dim = spec.get_dimension("overall_gdpval_fit")
    canned = {
        ("gpt-5.5", "Overall GDPVal Fit"): make_attempt_json(
            severity=2, confidence="high", evidence_quote="ABC Corp" ,
            headline="reads as test-like", justification="generic stakeholders",
            fixability="structural",
        ),
        ("gemini-3.1-pro-preview", "Overall GDPVal Fit"): make_attempt_json(
            severity=1, confidence="high", evidence_quote="ABC Corp",
            headline="mild constructed feel",
            justification="generic-feel inputs",
            fixability="structural",
        ),
    }
    client = MockLLMClient(canned=canned)
    attempts = run_ensemble(spec, dim, _make_sample(), lambda m: client)
    f = aggregate_attempts(dim, attempts, spec)
    assert f.severity == 2
    assert f.judges_agreed is True
    assert f.applicable is True
    assert len(f.raw_attempts) == 2
