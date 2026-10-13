"""M4 tests — verdict, synthesizer, emitters, end-to-end engine drive."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

import pytest

from gdpval_qc.finding import DimensionFinding, Issue, JudgeAttempt
from gdpval_qc.mock_llm import MockLLMClient, make_attempt_json
from gdpval_qc.review import BatchReview, BatchSummary, SampleReview, VERDICT_ORDER
from gdpval_qc.v18_aggregate import aggregate_attempts
from gdpval_qc.v18_emitter import (
    collect_judge_errors,
    to_csv, to_json, to_markdown_summary, write_batch_artifacts,
)
from gdpval_qc.v18_engine import V18Engine
from gdpval_qc.v18_loader import Sample
from gdpval_qc.v18_spec import V18Spec
from gdpval_qc.v18_synthesizer import synthesize_sample_review
from gdpval_qc.v18_verdict import (
    compute_verdict, pre_rank_findings, reject_at_severity_for,
)


REPO_ROOT     = Path(__file__).resolve().parent.parent
V18_SPEC_PATH = REPO_ROOT / "specs" / "gdpval_task_quality_v18.md"


@pytest.fixture(scope="session")
def spec() -> V18Spec:
    return V18Spec.from_markdown(V18_SPEC_PATH)


# ── Helpers ────────────────────────────────────────────────────────────────

def _finding(
    *,
    dim: str = "x",
    role: str = "blocking",
    severity: int = 0,
    fix: str = "fixable",
    confidence: str = "high",
    applicable: bool = True,
    judges_agreed: bool = True,
    needs_review_signal: bool = False,
    headline: str = "no issue",
) -> DimensionFinding:
    return DimensionFinding(
        dimension=dim,
        dimension_name=dim,
        gate_role=role,                       # type: ignore
        applicable=applicable,
        severity=severity,
        fixability=fix,                       # type: ignore
        confidence=confidence,                # type: ignore
        headline=headline,
        detail="…",
        evidence_quote="q" if severity >= 1 else None,
        judges_agreed=judges_agreed,
        raw_attempts=[],
        demoted_because=[],
        skipped_because=None,
        needs_review_signal=needs_review_signal,
    )


# ── Verdict tier 1 & 2: REJECT ─────────────────────────────────────────────

def test_verdict_reject_structural(spec: V18Spec) -> None:
    findings = [
        _finding(dim="overall_gdpval_fit", role="blocking", severity=2,
                  fix="structural"),
    ]
    v, reason = compute_verdict(findings, spec)
    assert v == "reject_structural"
    assert reason is None


def test_verdict_reject_fixable(spec: V18Spec) -> None:
    findings = [
        _finding(dim="solution_format_match", role="blocking", severity=3,
                  fix="fixable"),
    ]
    v, _ = compute_verdict(findings, spec)
    assert v == "reject_fixable"


# ── Verdict tier 3: NEEDS_REVIEW (three sub-cases) ─────────────────────────

def test_verdict_needs_review_judge_disagreement(spec: V18Spec) -> None:
    findings = [
        _finding(dim="overall_gdpval_fit", role="blocking", severity=1,
                  judges_agreed=False),
    ]
    v, reason = compute_verdict(findings, spec)
    assert v == "needs_review"
    assert "judge disagreement" in reason


def test_verdict_needs_review_low_confidence_signal(spec: V18Spec) -> None:
    findings = [
        _finding(dim="solution_format_match", role="blocking", severity=2,
                  needs_review_signal=True),
    ]
    v, reason = compute_verdict(findings, spec)
    assert v == "needs_review"
    assert "low-confidence" in reason


def test_verdict_needs_review_borderline(spec: V18Spec) -> None:
    # solution_format_match has reject_at_severity=3; sev 2 is borderline
    findings = [
        _finding(dim="solution_format_match", role="blocking", severity=2,
                  fix="fixable"),
    ]
    v, reason = compute_verdict(findings, spec)
    assert v == "needs_review"
    assert "borderline" in reason


# ── Verdict tier 4 & 5: ACCEPT_WITH_FIXES / ACCEPT ─────────────────────────

def test_verdict_accept_with_fixes_advisory_only(spec: V18Spec) -> None:
    findings = [
        _finding(dim="solution_layout_professionalism", role="advisory",
                  severity=1, fix="trivial"),
    ]
    v, _ = compute_verdict(findings, spec)
    assert v == "accept_with_fixes"


def test_verdict_accept_when_only_informational_or_clean(spec: V18Spec) -> None:
    findings = [
        _finding(dim="metadata_completeness", role="informational",
                  severity=2, fix="trivial"),
        _finding(dim="overall_gdpval_fit", role="blocking", severity=0),
    ]
    v, _ = compute_verdict(findings, spec)
    assert v == "accept"


def test_verdict_disagreement_takes_priority_over_reject(spec: V18Spec) -> None:
    """Judge disagreement on a blocking dim ROUTES TO REVIEW even when the
    severity would otherwise trigger REJECT. We defer contested findings to
    a human rather than auto-rejecting on a non-consensus signal."""
    findings = [
        _finding(dim="overall_gdpval_fit", role="blocking", severity=3,
                  fix="structural", judges_agreed=False),   # disagreement
    ]
    v, reason = compute_verdict(findings, spec)
    assert v == "needs_review"
    assert "disagreement" in reason


def test_verdict_reject_when_judges_agree(spec: V18Spec) -> None:
    """When judges agree on a reject-worthy finding, REJECT wins."""
    findings = [
        _finding(dim="overall_gdpval_fit", role="blocking", severity=3,
                  fix="structural", judges_agreed=True),
        _finding(dim="solution_layout_professionalism", role="advisory",
                  severity=2, fix="fixable"),
    ]
    v, _ = compute_verdict(findings, spec)
    assert v == "reject_structural"


# ── Pre-rank ordering ──────────────────────────────────────────────────────

def test_pre_rank_orders_by_role_then_severity_then_fixability(spec: V18Spec) -> None:
    findings = [
        _finding(dim="advisory_minor", role="advisory", severity=1, fix="trivial"),
        _finding(dim="block_lowsev",   role="blocking", severity=1, fix="fixable"),
        _finding(dim="block_hisev",    role="blocking", severity=3, fix="fixable"),
        _finding(dim="block_struc",    role="blocking", severity=3, fix="structural"),
        _finding(dim="info_ignored",   role="informational", severity=3, fix="fixable"),
        _finding(dim="block_zero",     role="blocking", severity=0, fix="fixable"),
    ]
    ranked = pre_rank_findings(findings)
    names = [f.dimension for f in ranked]
    # Expected order:
    #   block_struc (blocking, sev3, structural)
    #   block_hisev (blocking, sev3, fixable)
    #   block_lowsev (blocking, sev1)
    #   advisory_minor (advisory, sev1)
    # block_zero excluded (sev0), info_ignored excluded (informational)
    assert names == ["block_struc", "block_hisev", "block_lowsev", "advisory_minor"]


def test_pre_rank_excludes_skipped_and_informational(spec: V18Spec) -> None:
    findings = [
        _finding(dim="block_active", role="blocking", severity=2, fix="fixable",
                  applicable=True),
        _finding(dim="block_skipped", role="blocking", severity=0, fix="n/a",
                  applicable=False),
        _finding(dim="info_loud", role="informational", severity=3, fix="fixable"),
    ]
    ranked = pre_rank_findings(findings)
    assert [f.dimension for f in ranked] == ["block_active"]


# ── Synthesizer: deterministic fallback path (no client) ───────────────────

def test_synthesize_no_findings_returns_accept_one_line(spec: V18Spec) -> None:
    review = synthesize_sample_review(
        sample_id="t1",
        findings=[
            _finding(dim="overall_gdpval_fit", role="blocking", severity=0),
        ],
        spec=spec,
        client=None,
    )
    assert review.verdict == "accept"
    assert review.top_issues == []
    assert "No findings" in review.one_line


def test_synthesize_deterministic_fallback_when_client_is_none(spec: V18Spec) -> None:
    """v18.6: with no client the synthesizer surfaces EVERY applicable sev>=1
    finding as blocking (conservative — it never filters without LLM reasoning)."""
    findings = [
        _finding(dim="solution_format_match", role="blocking", severity=3,
                  fix="fixable", headline="wrong file type"),
        _finding(dim="solution_layout_professionalism", role="advisory",
                  severity=1, fix="trivial", headline="formatting nit"),
    ]
    review = synthesize_sample_review(
        sample_id="t2", findings=findings, spec=spec, client=None,
    )
    assert review.verdict == "reject_fixable"
    assert {i.dimension for i in review.top_issues} == {
        "solution_format_match", "solution_layout_professionalism"}
    assert all(i.blocking for i in review.top_issues)
    assert all(i.action for i in review.top_issues)  # non-empty fallback actions
    assert review.filtered_issues == []
    assert review.suggested_fixes == []
    assert review.synthesizer_fell_back is False


def test_deterministic_fallback_surfaces_all_candidates_uncapped(spec: V18Spec) -> None:
    """No numeric cap: all 8 must-fix findings surface as blocking (was capped at 3)."""
    findings = [
        _finding(dim=f"d{i}", role="advisory", severity=2, fix="fixable",
                  headline=f"finding {i}")
        for i in range(8)
    ]
    review = synthesize_sample_review(
        sample_id="t_overflow", findings=findings, spec=spec, client=None,
    )
    assert len(review.top_issues) == 8
    assert review.filtered_issues == []
    assert review.suggested_fixes == []


def test_deterministic_fallback_includes_minor_findings_as_blocking(spec: V18Spec) -> None:
    """In the no-client fallback, even sev-1 advisory findings surface as
    blocking — the fallback is conservative and does not filter."""
    findings = [
        _finding(dim="solution_layout_professionalism", role="advisory",
                  severity=1, fix="trivial", headline="minor formatting"),
        _finding(dim="solution_chart_quality", role="advisory",
                  severity=1, fix="trivial", headline="minor chart nit"),
    ]
    review = synthesize_sample_review(
        sample_id="t_minor", findings=findings, spec=spec, client=None,
    )
    assert len(review.top_issues) == 2
    assert all(i.blocking for i in review.top_issues)


def test_severity_1_blocking_surfaced(spec: V18Spec) -> None:
    findings = [
        _finding(dim="overall_gdpval_fit", role="blocking", severity=1,
                  fix="structural", headline="constructed feel"),
    ]
    review = synthesize_sample_review(
        sample_id="t_sev1_blocking", findings=findings, spec=spec, client=None,
    )
    assert len(review.top_issues) == 1
    assert review.top_issues[0].dimension == "overall_gdpval_fit"


# ── Synthesizer: LLM path (classify blocking vs cosmetic) ──────────────────

def _llm_synth_response(issues: list[dict], one_line: str = "needs fixing") -> str:
    return json.dumps({"one_line": one_line, "issues": issues})


def test_synthesizer_llm_path_classifies_blocking_and_cosmetic(spec: V18Spec) -> None:
    # pre_rank orders by severity desc → sev2 is index 0, sev1 is index 1
    findings = [
        _finding(dim="verifier_rubric_clarity", role="advisory", severity=2,
                  fix="fixable", headline="unanchored threshold"),
        _finding(dim="solution_layout_professionalism", role="advisory",
                  severity=1, fix="trivial", headline="formatting nit"),
    ]
    client = MockLLMClient(default=_llm_synth_response(
        issues=[
            {"index": 0, "classification": "blocking",
             "reason": "unanchored subjective threshold", "action": "Anchor rubric v2."},
            {"index": 1, "classification": "cosmetic",
             "reason": "minor formatting nit", "action": ""},
        ],
        one_line="One real verifier issue; one nit.",
    ))
    review = synthesize_sample_review(
        sample_id="t3", findings=findings, spec=spec, client=client,
    )
    assert review.synthesizer_fell_back is False
    assert review.one_line == "One real verifier issue; one nit."
    assert [i.dimension for i in review.top_issues] == ["verifier_rubric_clarity"]
    assert review.top_issues[0].blocking is True
    assert review.top_issues[0].action.startswith("Anchor")
    assert [i.dimension for i in review.filtered_issues] == ["solution_layout_professionalism"]
    assert review.filtered_issues[0].blocking is False
    assert review.filtered_issues[0].classification_reason == "minor formatting nit"


# ── Synthesizer: hard guard + fallback ─────────────────────────────────────

def test_synthesizer_hard_guard_forces_verdict_determinative_blocking(spec: V18Spec) -> None:
    """A finding at >= reject_at_severity on a blocking dim can NEVER be
    filtered — the hard guard forces it blocking even if the LLM says cosmetic
    (this is NOT a fallback)."""
    findings = [
        _finding(dim="solution_format_match", role="blocking", severity=3,
                  fix="fixable", headline="wrong file type"),
    ]
    client = MockLLMClient(default=_llm_synth_response(issues=[
        {"index": 0, "classification": "cosmetic", "reason": "looks fine", "action": ""},
    ]))
    review = synthesize_sample_review(
        sample_id="t4", findings=findings, spec=spec, client=client,
    )
    assert review.synthesizer_fell_back is False
    assert len(review.top_issues) == 1
    assert review.top_issues[0].dimension == "solution_format_match"
    assert review.top_issues[0].forced_blocking is True
    assert review.filtered_issues == []


def test_synthesizer_falls_back_on_invalid_json(spec: V18Spec) -> None:
    findings = [
        _finding(dim="solution_format_match", role="blocking", severity=3,
                  fix="fixable", headline="wrong file type"),
    ]
    client = MockLLMClient(default="garbage not JSON at all")
    review = synthesize_sample_review(
        sample_id="t6", findings=findings, spec=spec, client=client,
    )
    assert review.synthesizer_fell_back is True
    assert len(review.top_issues) == 1  # conservative fallback surfaces it


def test_synthesizer_falls_back_when_finding_unclassified(spec: V18Spec) -> None:
    """Every candidate must be classified; a missing index triggers the
    conservative fallback (surface all as blocking)."""
    findings = [
        _finding(dim="d0", role="advisory", severity=2, fix="fixable", headline="a"),
        _finding(dim="d1", role="advisory", severity=2, fix="fixable", headline="b"),
    ]
    client = MockLLMClient(default=_llm_synth_response(issues=[
        {"index": 0, "classification": "blocking", "reason": "x", "action": "y"},
    ]))
    review = synthesize_sample_review(
        sample_id="t7", findings=findings, spec=spec, client=client,
    )
    assert review.synthesizer_fell_back is True
    assert len(review.top_issues) == 2


def test_synthesizer_falls_back_on_out_of_range_index(spec: V18Spec) -> None:
    findings = [
        _finding(dim="d0", role="advisory", severity=2, fix="fixable", headline="a"),
    ]
    client = MockLLMClient(default=_llm_synth_response(issues=[
        {"index": 5, "classification": "blocking", "reason": "x", "action": "y"},
    ]))
    review = synthesize_sample_review(
        sample_id="t8", findings=findings, spec=spec, client=client,
    )
    assert review.synthesizer_fell_back is True


# ── Emitters ───────────────────────────────────────────────────────────────

def _mini_batch(spec: V18Spec) -> BatchReview:
    review = synthesize_sample_review(
        sample_id="t1",
        findings=[
            _finding(dim="solution_format_match", role="blocking", severity=3,
                      fix="fixable", headline="wrong file type"),
            _finding(dim="solution_layout_professionalism", role="advisory",
                      severity=1, fix="trivial", headline="minor nit"),
        ],
        spec=spec, client=None,
    )
    review2 = synthesize_sample_review(
        sample_id="t2",
        findings=[_finding(dim="overall_gdpval_fit", role="blocking", severity=0)],
        spec=spec, client=None,
    )
    return BatchReview(
        spec_name=spec.name, spec_version=spec.version,
        samples=[review, review2],
        batch_summary=BatchSummary(
            verdict_counts={"reject_fixable": 1, "accept": 1},
            verdict_percentages={"reject_fixable": 50.0, "accept": 50.0},
            failure_mode_histogram={"solution_format_match": 1},
            judge_agreement_rate=1.0,
            sample_count=2,
            samples_with_findings=1,
        ),
        calibration=None,
    )


def test_to_json_round_trip(spec: V18Spec) -> None:
    batch = _mini_batch(spec)
    d = to_json(batch)
    # Round trip via json
    s = json.dumps(d)
    parsed = json.loads(s)
    assert parsed["spec_name"] == spec.name
    assert len(parsed["samples"]) == 2


def test_to_csv_row_per_issue(spec: V18Spec) -> None:
    batch = _mini_batch(spec)
    csv_text = to_csv(batch)
    header = csv_text.splitlines()[0]
    for col in ("sample_id", "verdict", "one_line", "issue_rank", "classification",
                 "dimension", "severity", "action", "classification_reason",
                 "evidence_quote", "detail", "judges_agreed", "judge_trace_path"):
        assert col in header, f"{col} missing from CSV header"
    rows = list(csv.reader(io.StringIO(csv_text)))
    data = rows[1:]
    # reject_fixable (t1) sorts above accept (t2)
    assert data[0][0] == "t1"
    # t1 has two blocking issues (sev-3 blocking + sev-1 advisory, both surfaced
    # by the no-client conservative fallback) → one row each
    t1_rows = [r for r in data if r[0] == "t1"]
    assert len(t1_rows) == 2
    idx = {h: i for i, h in enumerate(rows[0])}
    assert all(r[idx["classification"]] == "blocking" for r in t1_rows)


def test_to_csv_populates_evidence_and_detail_from_findings(spec: V18Spec) -> None:
    """The evidence_quote and detail columns must pull from the underlying
    DimensionFinding, not from the synthesizer-written Issue."""
    from gdpval_qc.review import SampleReview, BatchSummary

    finding = _finding(
        dim="instruction_authenticity", role="blocking", severity=2,
        fix="structural",
        headline="reads as benchmark, not delegated work",
    )
    finding.evidence_quote = "this benchmark case for the model to grade"
    finding.detail = (
        "The clinical packet's preamble identifies it as a 'benchmark case' "
        "rather than a real patient record."
    )
    issue = Issue(
        rank=1, dimension="instruction_authenticity",
        gate_role="blocking", severity=2, fixability="structural",
        headline="reads as benchmark, not delegated work",
        action="Strip the 'benchmark case' phrase from the radiology PDF.",
        evidence_quote=finding.evidence_quote,
        judges_agreed=True,
        blocking=True, classification_reason="contamination — not authentic source",
    )
    review = SampleReview(
        sample_id="t1", verdict="reject_structural",
        one_line="…", top_issues=[issue], all_findings=[finding],
    )
    batch = BatchReview(
        spec_name=spec.name, spec_version=spec.version,
        samples=[review], batch_summary=BatchSummary(sample_count=1),
    )
    rows = list(csv.reader(io.StringIO(to_csv(batch))))
    header, data = rows[0], rows[1]
    idx = {h: i for i, h in enumerate(header)}
    assert data[idx["evidence_quote"]] == finding.evidence_quote
    assert data[idx["detail"]] == finding.detail
    assert data[idx["judges_agreed"]] == "Y"
    assert data[idx["classification"]] == "blocking"
    assert data[idx["classification_reason"]] == "contamination — not authentic source"


def test_to_csv_emits_cosmetic_rows_and_noissue_rows(spec: V18Spec) -> None:
    """Cosmetic (filtered) issues get their own rows; a sample with no issues
    still emits a single row with empty issue columns."""
    from gdpval_qc.review import SampleReview, BatchSummary
    blocking = Issue(
        rank=1, dimension="verifier_rubric_clarity", gate_role="advisory",
        severity=2, fixability="fixable", headline="unanchored threshold",
        action="Anchor rubric v2.", evidence_quote="q", judges_agreed=True,
        blocking=True, classification_reason="unanchored subjective threshold",
    )
    cosmetic = Issue(
        rank=1, dimension="input_prompt_leakage", gate_role="advisory",
        severity=1, fixability="trivial", headline="minor overlap",
        action="", evidence_quote="q", judges_agreed=True,
        blocking=False, classification_reason="incidental overlap, no answer leak",
    )
    r1 = SampleReview(
        sample_id="t1", verdict="needs_review", one_line="…",
        top_issues=[blocking], filtered_issues=[cosmetic], all_findings=[],
    )
    r2 = SampleReview(
        sample_id="t2", verdict="accept", one_line="No findings.",
        top_issues=[], filtered_issues=[], all_findings=[],
    )
    batch = BatchReview(
        spec_name=spec.name, spec_version=spec.version,
        samples=[r1, r2], batch_summary=BatchSummary(sample_count=2),
    )
    rows = list(csv.reader(io.StringIO(to_csv(batch))))
    idx = {h: i for i, h in enumerate(rows[0])}
    data = rows[1:]
    t1 = [r for r in data if r[idx["sample_id"]] == "t1"]
    assert {r[idx["classification"]] for r in t1} == {"blocking", "cosmetic"}
    t2 = [r for r in data if r[idx["sample_id"]] == "t2"]
    assert len(t2) == 1
    assert t2[0][idx["classification"]] == ""
    assert t2[0][idx["dimension"]] == ""
    # every row must have exactly the header's column count (no misalignment)
    assert all(len(r) == len(rows[0]) for r in data), "ragged CSV row(s)"


def test_to_markdown_summary_contains_verdict_table(spec: V18Spec) -> None:
    batch = _mini_batch(spec)
    md = to_markdown_summary(batch)
    assert "Batch summary" in md
    assert "Verdict distribution" in md
    assert "reject_fixable" in md
    assert "accept" in md


def test_write_batch_artifacts_creates_all_outputs(spec: V18Spec, tmp_path: Path) -> None:
    batch = _mini_batch(spec)
    paths = write_batch_artifacts(batch, tmp_path, top_issues_cap=3)
    for name in ("batch_review.json", "reviewer_queue.csv", "batch_summary.md"):
        assert paths[name].is_file(), f"{name} not written"
    # Raw transcripts
    assert (tmp_path / "raw" / "sample_t1.json").is_file()
    assert (tmp_path / "raw" / "sample_t2.json").is_file()


# ── Engine end-to-end ──────────────────────────────────────────────────────

def _judge_client_returning(severity: int, evidence: str = "q") -> MockLLMClient:
    return MockLLMClient(default=make_attempt_json(
        severity=severity, confidence="high", applicable=True,
        evidence_quote=evidence if severity >= 1 else None,
        headline=f"sev {severity}", justification="...",
        fixability="fixable" if severity >= 1 else "n/a",
    ))


def _trivial_programmatic_callback(sample: Sample, dim) -> DimensionFinding:
    return _finding(dim=dim.name, role=dim.gate.role, severity=0)


def test_engine_grades_each_dim_and_synthesizes(spec: V18Spec) -> None:
    judge_client = _judge_client_returning(severity=0)
    synth_client = MockLLMClient(default=_llm_synth_response(
        issues=[], one_line="All clean",
    ))
    engine = V18Engine(
        spec=spec,
        judge_client_factory=lambda model: judge_client,
        synthesizer_client=synth_client,
        programmatic_callbacks={
            "check_metadata_completeness":         _trivial_programmatic_callback,
            "check_verifier_parseable":            _trivial_programmatic_callback,
            "check_verifier_count_in_range":       _trivial_programmatic_callback,
            "check_verifier_outcome_grader_present": _trivial_programmatic_callback,
        },
    )

    sample = Sample(task_id="task_demo", task_dir=Path("/tmp"), fields={
        "task_id": "task_demo",
        "instruction": "Test", "category": "Test",
        "solution_files": [],            # no solution → solution_* dims skipped
        "verifier_spec_json": None,      # no verifier → verifier_* dims skipped
        "verifier_assertion_summary": None,
        "solution_reasoning": None,
        "input_files": [],
    })

    review = engine.assess_sample(sample)
    assert review.sample_id == "task_demo"
    assert review.verdict in VERDICT_ORDER
    # All applicable LLM dims should have at least one judge call recorded.
    # The conditional dims should NOT have been called.
    called_dims = {c.dim_name_from_user for c in judge_client.calls}
    # solution_format_match is conditional on solution_present — should be skipped
    assert "Solution Format Match" not in called_dims
    # overall_gdpval_fit is unconditional — should be called
    assert "Overall GDPVal Fit" in called_dims


def test_engine_batch_summary_aggregates_verdicts(spec: V18Spec) -> None:
    judge_client = _judge_client_returning(severity=0)
    engine = V18Engine(
        spec=spec,
        judge_client_factory=lambda m: judge_client,
        synthesizer_client=None,
        programmatic_callbacks={
            "check_metadata_completeness":         _trivial_programmatic_callback,
            "check_verifier_parseable":            _trivial_programmatic_callback,
            "check_verifier_count_in_range":       _trivial_programmatic_callback,
            "check_verifier_outcome_grader_present": _trivial_programmatic_callback,
        },
    )
    samples = [
        Sample(task_id=f"t{i}", task_dir=Path("/tmp"), fields={
            "task_id": f"t{i}", "instruction": "x", "category": "c",
            "solution_files": [], "verifier_spec_json": None,
            "input_files": [], "solution_reasoning": None,
            "verifier_assertion_summary": None,
        })
        for i in range(3)
    ]
    batch = engine.assess_batch(samples)
    assert batch.batch_summary.sample_count == 3
    # All sev-0 across the board → all accept
    assert batch.batch_summary.verdict_counts.get("accept", 0) == 3


# ── Judge-error surfacing ──────────────────────────────────────────────────

def _attempt(model: str, error: str | None = None) -> JudgeAttempt:
    return JudgeAttempt(
        model=model,
        severity=0,
        confidence="low" if error else "high",
        applicable=False if error else True,
        headline="judge call failed" if error else "ok",
        justification=error or "ok",
        fixability="n/a",
        evidence_quote=None,
        raw_response="",
        error=error,
    )


def _finding_with_attempts(dim: str, attempts: list[JudgeAttempt]) -> DimensionFinding:
    f = _finding(dim=dim, severity=0, applicable=False, judges_agreed=True)
    f.raw_attempts = attempts
    return f


def _batch_review_for_errors(samples_spec: list[tuple[str, int, int]]) -> BatchReview:
    """Build a BatchReview where each sample has the given (errored, total)
    judge-attempt counts across all dims combined."""
    samples = []
    for sid, n_err, n_total in samples_spec:
        # Spread the attempts across two dims for realism (2 attempts/dim).
        attempts_per_dim = 2
        n_dims = max(1, n_total // attempts_per_dim)
        findings = []
        remaining_err = n_err
        for di in range(n_dims):
            atts = []
            for _ in range(attempts_per_dim):
                if remaining_err > 0:
                    atts.append(_attempt("gpt-5.5",
                        error="ModuleNotFoundError: No module named 'gdpval_qc.context_limiter'"))
                    remaining_err -= 1
                else:
                    atts.append(_attempt("gemini-3.1-pro-preview"))
            findings.append(_finding_with_attempts(f"dim_{di}", atts))
        samples.append(SampleReview(
            sample_id=sid, verdict="accept", one_line="…",
            all_findings=findings,
        ))
    return BatchReview(
        spec_name="gdpval_task_quality",
        spec_version="18.5",
        samples=samples,
        batch_summary=BatchSummary(sample_count=len(samples),
                                    verdict_counts={"accept": len(samples)},
                                    verdict_percentages={"accept": 100.0}),
    )


def test_collect_judge_errors_no_errors() -> None:
    br = _batch_review_for_errors([("task_1", 0, 4), ("task_2", 0, 4)])
    errs = collect_judge_errors(br)
    assert errs["total_errors"] == 0
    assert errs["total_attempts"] == 8
    assert errs["by_sample"] == {}
    assert errs["by_reason"] == {}


def test_collect_judge_errors_tallies_per_sample_and_reason() -> None:
    br = _batch_review_for_errors([
        ("task_1", 4, 4),  # 100% errored
        ("task_2", 2, 4),  # 50% errored
        ("task_3", 0, 4),  # clean
    ])
    errs = collect_judge_errors(br)
    assert errs["total_errors"] == 6
    assert errs["total_attempts"] == 12
    assert set(errs["by_sample"]) == {"task_1", "task_2"}
    assert errs["by_sample"]["task_1"] == {"errors": 4, "attempts": 4}
    assert errs["by_sample"]["task_2"] == {"errors": 2, "attempts": 4}
    # Reason aggregation should bucket identical first-lines together
    assert sum(errs["by_reason"].values()) == 6
    assert any("ModuleNotFoundError" in r for r in errs["by_reason"])


def test_to_markdown_summary_renders_errors_section_loudly() -> None:
    br = _batch_review_for_errors([("task_1", 4, 4), ("task_2", 0, 4)])
    md = to_markdown_summary(br)
    assert "Judge-call errors" in md
    assert "task_1" in md
    # Per-sample table column header should be present
    assert "judge errors" in md
    # Reason should be rendered in a backtick-wrapped row
    assert "`ModuleNotFoundError" in md
    # Don't render the section when there are zero errors
    br_clean = _batch_review_for_errors([("task_1", 0, 4)])
    assert "Judge-call errors" not in to_markdown_summary(br_clean)


def test_write_batch_artifacts_includes_errors_in_md(tmp_path) -> None:
    br = _batch_review_for_errors([("task_1", 4, 4)])
    paths = write_batch_artifacts(br, tmp_path, top_issues_cap=3)
    md = paths["batch_summary.md"].read_text(encoding="utf-8")
    assert "Judge-call errors" in md


# ── CLI exit code on judge errors ─────────────────────────────────────────

def test_judge_error_exit_code_clean_run_returns_zero() -> None:
    from gdpval_qc.cli import judge_error_exit_code
    br = _batch_review_for_errors([("task_1", 0, 4), ("task_2", 0, 4)])
    assert judge_error_exit_code(br, threshold=0.5) == 0


def test_judge_error_exit_code_returns_3_when_any_sample_exceeds_threshold() -> None:
    from gdpval_qc.cli import judge_error_exit_code
    # task_1 is 100% errored, way above the 0.5 threshold
    br = _batch_review_for_errors([("task_1", 4, 4), ("task_2", 0, 4)])
    assert judge_error_exit_code(br, threshold=0.5) == 3


def test_judge_error_exit_code_returns_0_when_all_samples_below_threshold() -> None:
    from gdpval_qc.cli import judge_error_exit_code
    # task_1 is 25% errored — below the 0.5 threshold. Errors are still
    # printed to stderr, but the exit code stays 0.
    br = _batch_review_for_errors([("task_1", 1, 4), ("task_2", 0, 4)])
    assert judge_error_exit_code(br, threshold=0.5) == 0


def test_judge_error_exit_code_threshold_above_1_disables_check() -> None:
    from gdpval_qc.cli import judge_error_exit_code
    # Even 100% error rate doesn't trip the exit code when disabled.
    br = _batch_review_for_errors([("task_1", 4, 4)])
    assert judge_error_exit_code(br, threshold=1.5) == 0


def test_judge_error_exit_code_threshold_zero_trips_on_any_error() -> None:
    from gdpval_qc.cli import judge_error_exit_code
    # threshold=0 means "any error rate >= 0" -> trip on first errored sample.
    br = _batch_review_for_errors([("task_1", 1, 4)])
    assert judge_error_exit_code(br, threshold=0.0) == 3
