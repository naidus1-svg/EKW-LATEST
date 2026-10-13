"""M1 tests — v18 spec parser.

Verifies that:
  - the canonical v18 spec parses cleanly
  - v17 specs are rejected with a clear version error
  - unknown frontmatter / per-dim keys are rejected
  - severity_scale must cover 0-3
  - gate config is validated (role, reject_at_severity, on_disagreement)
  - duplicate dim names are rejected
  - spec_hash is deterministic and changes when content changes
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from gdpval_qc.v18_spec import (
    V18Spec, SpecValidationError, MIN_SPEC_VERSION_MAJOR,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
V18_SPEC_PATH = REPO_ROOT / "specs" / "gdpval_task_quality_v18.md"
V17_SPEC_PATH = REPO_ROOT / "specs" / "gdpval_task_quality_v17.md"


# ── Happy path: canonical v18 spec ─────────────────────────────────────────

def test_canonical_v18_spec_parses() -> None:
    spec = V18Spec.from_markdown(V18_SPEC_PATH)

    assert spec.name == "gdpval_task_quality"
    # Loosen the version assertion to v18.* so spec calibrations (18.1, 18.2,
    # ...) don't churn this test. The major-version gate is enforced
    # separately by test_v17_spec_rejected_with_clear_message.
    assert spec.version.startswith("18.")
    assert spec.cache_bust is not None
    assert len(spec.models) == 2
    assert spec.models[0].model == "gpt-5.5"
    assert spec.models[1].model == "gemini-3.1-pro-preview"

    # Severity scale fully populated
    assert set(spec.severity_scale.keys()) >= {0, 1, 2, 3}
    assert "fully meets criterion" in spec.severity_scale[0]

    # Evidence policy + confidence policy parsed
    assert spec.require_evidence_quote is True
    assert spec.confidence_demotion.low_at_sev1 == "demote_to_0"
    assert spec.confidence_demotion.low_at_sev2_or_higher == "route_to_review"

    # Field bindings include (at least) the canonical four. Superset, not
    # equality: the trajectory-QC workstream adds run-digest bindings
    # (passed/failed_trial_deliverable_digest, intermodel_trajectory_digest)
    # and this assertion should not churn when more are added.
    bound_names = {fb.field_name for fb in spec.field_bindings}
    assert bound_names >= {
        "solution_files", "solution_reasoning",
        "verifier_spec_json", "verifier_assertion_summary",
    }
    sf = next(fb for fb in spec.field_bindings if fb.field_name == "solution_files")
    assert sf.source == "directory"
    assert sf.path == "solution/golden_outputs"
    assert "Reasoning.docx" in sf.exclude

    # Synthesis + calibration
    assert spec.synthesis.enabled is True
    assert spec.synthesis.top_issues_cap == 3
    assert spec.calibration.goldens_path == "calibration/v18/"

    # Verdict tiers in expected order
    assert spec.verdict_tiers == [
        "reject_structural", "reject_fixable", "needs_review",
        "accept_with_fixes", "accept",
    ]


def test_canonical_v18_spec_dimension_counts() -> None:
    """25 LLM dims + 11 programmatic dims = 36 total in v18.6 (the shift-left
    deterministic checks added 2026-07-22 — near_miss/sum_mismatch/ratio_invariant/
    doc_citation/deliverable_manifest/cross_artifact_reconciliation — brought
    programmatic from 5 to 11; this assertion was stale from before that landed)."""
    spec = V18Spec.from_markdown(V18_SPEC_PATH)
    assert len(spec.dimensions) == 36

    llm = [d for d in spec.dimensions if d.check_kind == "llm"]
    prog = [d for d in spec.dimensions if d.check_kind == "programmatic"]
    assert len(llm) == 25
    assert len(prog) == 11

    # The core structural blocking dims reject at severity 2. Superset, not
    # equality: later workstreams add more sev-2-reject blocking dims
    # (e.g. input_prompt_leakage, synthetic_marker_scan) and this check should
    # not churn — it guards that the original structural set stays sev-2-reject.
    sev2_reject = [d for d in spec.dimensions
                    if d.gate.role == "blocking" and d.gate.reject_at_severity == 2]
    sev2_names = {d.name for d in sev2_reject}
    assert sev2_names >= {
        "overall_gdpval_fit",
        "instruction_input_consistency",
        "professional_complexity",
        "instruction_authenticity",
        "input_file_authenticity",
        "verifier_spec_parseable",
    }

    # Programmatic dims all reference a callback
    for d in prog:
        assert d.callback, f"Programmatic dim {d.name} missing callback"


def test_canonical_v18_dimension_conditional_dims() -> None:
    spec = V18Spec.from_markdown(V18_SPEC_PATH)

    by_name = {d.name: d for d in spec.dimensions}

    # solution_* dims gated on solution_present (and chart subset on solution_has_charts)
    assert by_name["solution_format_match"].applies_when.builtin == "solution_present"
    assert by_name["solution_chart_quality"].applies_when.builtin == "solution_has_charts"

    # verifier_* dims gated on task_has_verifier
    assert by_name["verifier_rubric_clarity"].applies_when.builtin == "task_has_verifier"
    assert by_name["verifier_spec_parseable"].applies_when.builtin == "task_has_verifier"

    # Task structure dims are unconditional
    assert by_name["overall_gdpval_fit"].applies_when is None
    assert by_name["self_containedness"].applies_when is None


def test_canonical_v18_dimension_prose_carries_severity_rubric() -> None:
    """Sanity check that the parser captured the prose body, not just the YAML."""
    spec = V18Spec.from_markdown(V18_SPEC_PATH)
    d = next(d for d in spec.dimensions if d.name == "overall_gdpval_fit")
    assert "Severity rubric" in d.prose
    assert "Common hard-fail patterns" in d.prose
    # Anti-overcall language should also be present where present in the source
    assert "Anti-overcall" in d.prose


# ── Rejection: v17 specs must fail loudly ──────────────────────────────────

def test_v17_spec_rejected_with_clear_message() -> None:
    if not V17_SPEC_PATH.is_file():
        pytest.skip("v17 spec not present in this checkout")
    with pytest.raises(SpecValidationError) as exc_info:
        V18Spec.from_markdown(V17_SPEC_PATH)
    msg = str(exc_info.value).lower()
    assert "version" in msg
    assert f"{MIN_SPEC_VERSION_MAJOR}" in msg


# ── Hashing ────────────────────────────────────────────────────────────────

def test_spec_hash_is_deterministic() -> None:
    s1 = V18Spec.from_markdown(V18_SPEC_PATH)
    s2 = V18Spec.from_markdown(V18_SPEC_PATH)
    assert s1.spec_hash() == s2.spec_hash()


def test_spec_hash_changes_when_dim_prose_changes(tmp_path: Path) -> None:
    """The spec hash must invalidate when any per-dim prose changes."""
    src = V18_SPEC_PATH.read_text(encoding="utf-8")
    modified = src.replace("Holistically, does this task", "HOLISTIC: does this task")
    assert modified != src
    p2 = tmp_path / "v18_modified.md"
    p2.write_text(modified, encoding="utf-8")

    s1 = V18Spec.from_markdown(V18_SPEC_PATH)
    s2 = V18Spec.from_markdown(p2)
    assert s1.spec_hash() != s2.spec_hash()


# ── Strict-mode failures ───────────────────────────────────────────────────

def _write_spec(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "spec.md"
    p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return p


def test_unknown_frontmatter_key_rejected(tmp_path: Path) -> None:
    p = _write_spec(tmp_path, """
        ---
        name: test
        version: "18.0"
        models:
          - model: gpt-5.5
        field_types: {}
        severity_scale: {0: "ok", 1: "minor", 2: "material", 3: "severe"}
        verdict_tiers: [accept]
        unknown_key: foo
        ---
        # body

        ### dim1

        ```yaml
        dimension_name: "Dim One"
        check_kind: llm
        inputs: [instruction]
        gate:
          role: blocking
          reject_at_severity: 3
        ```

        prose
    """)
    with pytest.raises(SpecValidationError) as exc:
        V18Spec.from_markdown(p)
    assert "unknown_key" in str(exc.value).lower()


def test_missing_severity_level_rejected(tmp_path: Path) -> None:
    p = _write_spec(tmp_path, """
        ---
        name: test
        version: "18.0"
        models:
          - model: gpt-5.5
        field_types: {}
        severity_scale: {0: "ok", 1: "minor"}
        verdict_tiers: [accept]
        ---
        # body

        ### dim1

        ```yaml
        dimension_name: "Dim One"
        check_kind: llm
        inputs: [instruction]
        gate:
          role: blocking
          reject_at_severity: 3
        ```

        prose
    """)
    with pytest.raises(SpecValidationError) as exc:
        V18Spec.from_markdown(p)
    msg = str(exc.value).lower()
    assert "severity level 2" in msg or "severity level 3" in msg


def test_invalid_gate_role_rejected(tmp_path: Path) -> None:
    p = _write_spec(tmp_path, """
        ---
        name: test
        version: "18.0"
        models:
          - model: gpt-5.5
        field_types: {}
        severity_scale: {0: "ok", 1: "minor", 2: "material", 3: "severe"}
        verdict_tiers: [accept]
        ---
        # body

        ### dim1

        ```yaml
        dimension_name: "Dim One"
        check_kind: llm
        inputs: [instruction]
        gate:
          role: pivotal
          reject_at_severity: 3
        ```

        prose
    """)
    with pytest.raises(SpecValidationError) as exc:
        V18Spec.from_markdown(p)
    assert "role" in str(exc.value).lower()


def test_duplicate_dim_name_rejected(tmp_path: Path) -> None:
    p = _write_spec(tmp_path, """
        ---
        name: test
        version: "18.0"
        models:
          - model: gpt-5.5
        field_types: {}
        severity_scale: {0: "ok", 1: "minor", 2: "material", 3: "severe"}
        verdict_tiers: [accept]
        ---
        # body

        ### dup_dim

        ```yaml
        dimension_name: "Dup 1"
        check_kind: llm
        inputs: [instruction]
        gate:
          role: blocking
          reject_at_severity: 3
        ```

        prose

        ### dup_dim

        ```yaml
        dimension_name: "Dup 2"
        check_kind: llm
        inputs: [instruction]
        gate:
          role: blocking
          reject_at_severity: 3
        ```

        prose
    """)
    with pytest.raises(SpecValidationError) as exc:
        V18Spec.from_markdown(p)
    assert "duplicate" in str(exc.value).lower()
