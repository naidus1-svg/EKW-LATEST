#!/usr/bin/env python3
"""Unit tests for rubric_overspecification_check.py response parsing and
finding normalization. Tests hand-written LLM response fixtures covering the
three real SVC-PC-33-8-0 over-specification cases (name_pinned for "4 named
people", count_pinned for "5 checks vs four", value_pinned for
"tolerance=None") plus a clean negative (a criterion whose pinned value IS
supported by instruction language) and edge cases (code-fenced JSON, JSON
embedded in prose, missing fields, unrecognized overspec_type). Also tests
prompt construction against the REAL staged SVC-PC-33-8-0 data to confirm the
real instruction text and rubric criteria are correctly surfaced.

Does NOT make any real LLM call; all response fixtures are hand-written
strings fed directly to parse_llm_response / build_task_result_from_response.
The prompt-construction test reads the real files from disk but never calls
an LLM. Matches content_audit_check_test.py's own test strategy.

Run:
    python deterministic-checks/rubric_overspecification_check_test.py
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from rubric_overspecification_check import (
    parse_llm_response,
    build_task_result_from_response,
    build_prompt,
    collect_rubric_text,
    OVERSPEC_TYPES,
)


def _make_base_kwargs(**overrides):
    """Default per-task metadata the orchestrator would pass."""
    kw = dict(
        task_id="SVC-PC-33-8-0",
        fmt="svc_pc",
        n_criteria=50,
        n_golden_files=1,
        parse_errors=[],
        extract_errors=[],
        backend_used="cli_or_http",
        prompt_chars=8000,
    )
    kw.update(overrides)
    return kw


def json_fixture(**kwargs) -> str:
    """Build a JSON fixture string from kwargs."""
    return json.dumps(kwargs)


# ---------------------------------------------------------------------------
# Negative: a criterion whose pinned value IS supported by instruction text
# ---------------------------------------------------------------------------


def test_clean_response():
    """A clean LLM response with zero findings parses to status=pass.

    Models the negative case: the LLM correctly returns clean because the
    criterion (e.g. r019/r046 about evidence artifacts / six months) IS
    supported by specific instruction language ("I also want to know what
    evidence the routine leaves behind. If someone asks in six months...").
    The check should NOT flag a supported criterion."""
    raw = '{"verdict": "clean", "findings": []}'
    parsed = parse_llm_response(raw)
    assert parsed["verdict"] == "clean", f"expected clean, got {parsed.get('verdict')}"
    assert parsed["findings"] == [], f"expected empty findings, got {parsed.get('findings')}"

    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["status"] == "pass", f"expected pass, got {result['status']}"
    assert result["n_findings"] == 0
    assert result["n_warn"] == 0
    assert result["findings"] == []
    print("  test_clean_response: PASS (clean -> pass, 0 findings)")


# ---------------------------------------------------------------------------
# Positive: name_pinned (4 named people vs "the people we currently have")
# ---------------------------------------------------------------------------


def test_overspec_name_finding():
    """A response flagging name_pinned for pinning 4 specific named people
    when the instruction says 'from the people we currently have'.

    Real data: r013 says 'Each check has a named owner: Jessica Liu, Priya
    Patel, David Nguyen, or James Okafor.' The instruction says 'Who runs it,
    by name, from the people we currently have.' The instruction requires
    naming a person by name but does NOT name specific individuals. The rubric
    pins exactly four specific names the instruction never listed."""
    raw = json_fixture(
        verdict="defective",
        findings=[
            {
                "overspec_type": "name_pinned",
                "severity": "warn",
                "criterion": "deliverables_02/r013",
                "quote": "Each check has a named owner: Jessica Liu, Priya Patel, David Nguyen, or James Okafor.",
                "pinned_value": "Jessica Liu, Priya Patel, David Nguyen, or James Okafor",
                "instruction_text": "Who runs it, by name, from the people we currently have.",
                "evidence": "The instruction says 'from the people we currently have' without naming specific individuals. The rubric pins exactly four named people, a specificity the instruction left open.",
            }
        ],
    )
    parsed = parse_llm_response(raw)
    assert parsed["verdict"] == "defective"
    assert len(parsed["findings"]) == 1

    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["status"] == "warn", f"expected warn, got {result['status']}"
    assert result["n_findings"] == 1
    f = result["findings"][0]
    assert f["kind"] == "rubric_overspecification"
    assert f["overspec_type"] == "name_pinned"
    assert f["severity"] == "warn"
    assert f["criterion"] == "deliverables_02/r013"
    assert "Jessica Liu" in f["quote"]
    assert "Priya Patel" in f["quote"]
    assert "from the people we currently have" in f["instruction_text"]
    assert "specific" in f["evidence"].lower() or "open" in f["evidence"].lower()
    print("  test_overspec_name_finding: PASS (name_pinned -> warn, 1 finding)")


# ---------------------------------------------------------------------------
# Positive: count_pinned (5 checks vs "I would rather run four")
# ---------------------------------------------------------------------------


def test_overspec_count_finding():
    """A response flagging count_pinned for requiring 5 checks when the
    instruction says 'I would rather run four.'

    Real data: r012 says 'Each of the 5 checks has an A source and a B
    source.' The instruction says 'I would rather run four checks that
    actually happen than twelve that do not.' The rubric pins exactly 5,
    contradicting the instruction's own stated preference for four."""
    raw = json_fixture(
        verdict="defective",
        findings=[
            {
                "overspec_type": "count_pinned",
                "severity": "warn",
                "criterion": "deliverables_01/r012",
                "quote": "Each of the 5 checks has an A source and a B source with ledger references.",
                "pinned_value": "5 checks",
                "instruction_text": "I would rather run four checks that actually happen than twelve that do not.",
                "evidence": "The instruction states a preference for four checks. The rubric requires exactly 5, contradicting the instruction's own stated count.",
            }
        ],
    )
    parsed = parse_llm_response(raw)
    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["status"] == "warn"
    assert result["n_findings"] == 1
    f = result["findings"][0]
    assert f["overspec_type"] == "count_pinned"
    assert f["criterion"] == "deliverables_01/r012"
    assert "5 checks" in f["quote"]
    assert "four" in f["instruction_text"].lower()
    print("  test_overspec_count_finding: PASS (count_pinned -> warn, 1 finding)")


# ---------------------------------------------------------------------------
# Positive: value_pinned (tolerance=None vs "James is working out the tolerance")
# ---------------------------------------------------------------------------


def test_overspec_value_finding():
    """A response flagging value_pinned for requiring tolerance=None when the
    instruction defers the tolerance to James.

    Real data: r042 says 'Tolerance is None or explicitly references the
    governing reconciliation control.' The instruction says 'James is working
    out how that comparison is built and what the tolerance should be.' The
    instruction explicitly defers the tolerance value to another person; the
    rubric pins a specific value (None) anyway."""
    raw = json_fixture(
        verdict="defective",
        findings=[
            {
                "overspec_type": "value_pinned",
                "severity": "warn",
                "criterion": "deliverables_04/r042",
                "quote": "Tolerance is None or explicitly references the governing reconciliation control, not a self-assigned number.",
                "pinned_value": "tolerance=None",
                "instruction_text": "James is working out how that comparison is built and what the tolerance should be, so you do not need to construct it.",
                "evidence": "The instruction explicitly defers the tolerance to James ('James is working out what the tolerance should be'). The rubric pins a specific value (None), a decision the instruction left to someone else.",
            }
        ],
    )
    parsed = parse_llm_response(raw)
    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["status"] == "warn"
    assert result["n_findings"] == 1
    f = result["findings"][0]
    assert f["overspec_type"] == "value_pinned"
    assert f["criterion"] == "deliverables_04/r042"
    assert "None" in f["quote"]
    assert "James" in f["instruction_text"]
    print("  test_overspec_value_finding: PASS (value_pinned -> warn, 1 finding)")


# ---------------------------------------------------------------------------
# Multiple findings of different types
# ---------------------------------------------------------------------------


def test_multiple_overspec_types():
    """A response with name_pinned and count_pinned findings parses to two
    findings, each with the correct overspec_type."""
    raw = json_fixture(
        verdict="defective",
        findings=[
            {
                "overspec_type": "count_pinned",
                "criterion": "deliverables_01/r012",
                "quote": "Each of the 5 checks has an A source and a B source.",
                "pinned_value": "5 checks",
                "instruction_text": "I would rather run four checks that actually happen.",
                "evidence": "Instruction says four, rubric says 5.",
            },
            {
                "overspec_type": "name_pinned",
                "criterion": "deliverables_02/r013",
                "quote": "Each check has a named owner: Jessica Liu, Priya Patel, David Nguyen, or James Okafor.",
                "pinned_value": "Jessica Liu, Priya Patel, David Nguyen, or James Okafor",
                "instruction_text": "from the people we currently have",
                "evidence": "Instruction does not name specific people.",
            },
            {
                "overspec_type": "format_pinned",
                "criterion": "deliverables_04/r047",
                "quote": "Company Shared Drive/Operations/Metric Checks/YYYY-MM/ or YYYY-QN for quarterly checks.",
                "pinned_value": "Company Shared Drive/Operations/Metric Checks/YYYY-MM/",
                "instruction_text": "[no path specified in instruction]",
                "evidence": "The instruction gives no shared folder path. The rubric pins a specific path string.",
            },
        ],
    )
    parsed = parse_llm_response(raw)
    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["status"] == "warn"
    assert result["n_findings"] == 3
    types = [f["overspec_type"] for f in result["findings"]]
    assert "count_pinned" in types
    assert "name_pinned" in types
    assert "format_pinned" in types
    # Each finding should have the right kind
    for f in result["findings"]:
        assert f["kind"] == "rubric_overspecification"
    print("  test_multiple_overspec_types: PASS (3 findings, count/name/format)")


# ---------------------------------------------------------------------------
# Edge cases (mirror content_audit_check_test.py's coverage)
# ---------------------------------------------------------------------------


def test_malformed_response():
    """A non-JSON response parses to an error result, not a crash."""
    raw = "I cannot analyze this task because the files are too large to read."
    parsed = parse_llm_response(raw)
    assert "parse_error" in parsed, f"expected parse_error, got {parsed}"
    assert parsed["verdict"] == "error"

    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["status"] == "error", f"expected error, got {result['status']}"
    assert result["n_findings"] == 0
    assert len(result["errors"]) >= 1
    print("  test_malformed_response: PASS (non-JSON -> error, no crash)")


def test_code_fenced_json():
    """A JSON response wrapped in ```json fences parses correctly."""
    raw = '```json\n{"verdict": "clean", "findings": []}\n```'
    parsed = parse_llm_response(raw)
    assert parsed["verdict"] == "clean"
    assert parsed["findings"] == []
    print("  test_code_fenced_json: PASS (fenced JSON parsed)")


def test_json_embedded_in_prose():
    """A JSON object embedded in surrounding prose is extracted and parsed."""
    raw = (
        "Here is my analysis of the task.\n"
        '{"verdict": "defective", "findings": ['
        '{"overspec_type": "count_pinned", "criterion": "deliverables_01/r012", '
        '"quote": "Each of the 5 checks has an A source and a B source.", '
        '"pinned_value": "5 checks", '
        '"instruction_text": "I would rather run four checks.", '
        '"evidence": "Instruction says four, rubric says 5."}'
        "]}\n"
        "That is all."
    )
    parsed = parse_llm_response(raw)
    assert parsed["verdict"] == "defective"
    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["status"] == "warn"
    assert result["n_findings"] == 1
    assert result["findings"][0]["overspec_type"] == "count_pinned"
    print("  test_json_embedded_in_prose: PASS (JSON extracted from prose)")


def test_empty_response():
    """An empty string parses to an error, not a crash."""
    parsed = parse_llm_response("")
    assert parsed["verdict"] == "error"
    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["status"] == "error"
    print("  test_empty_response: PASS (empty -> error, no crash)")


def test_findings_not_a_list():
    """A response where 'findings' is a string instead of a list does not
    crash; the malformed findings are dropped."""
    raw = '{"verdict": "defective", "findings": "name_pinned on r013"}'
    parsed = parse_llm_response(raw)
    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["status"] == "pass", f"expected pass (no valid findings), got {result['status']}"
    assert result["n_findings"] == 0
    print("  test_findings_not_a_list: PASS (malformed findings dropped -> pass)")


def test_finding_missing_quote():
    """A finding dict without a 'quote' field is dropped."""
    raw = json_fixture(
        verdict="defective",
        findings=[
            {
                "overspec_type": "count_pinned",
                "criterion": "deliverables_01/r012",
                "pinned_value": "5 checks",
                "instruction_text": "I would rather run four checks.",
                "evidence": "Instruction says four, rubric says 5.",
            },
        ],
    )
    parsed = parse_llm_response(raw)
    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["n_findings"] == 0, "finding without quote should be dropped"
    assert result["status"] == "pass"
    print("  test_finding_missing_quote: PASS (finding without quote dropped)")


def test_finding_unrecognized_overspec_type():
    """A finding with an unrecognized overspec_type is kept (defaulting to
    'overspecification') rather than dropped, since the type is a
    categorization aid, not a validation gate."""
    raw = json_fixture(
        verdict="defective",
        findings=[
            {
                "overspec_type": "something_unexpected",
                "criterion": "deliverables_02/r013",
                "quote": "Each check has a named owner: Jessica Liu.",
                "pinned_value": "Jessica Liu",
                "instruction_text": "from the people we currently have",
                "evidence": "Instruction does not name specific people.",
            },
        ],
    )
    parsed = parse_llm_response(raw)
    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["n_findings"] == 1, "finding with unrecognized overspec_type should be kept"
    assert result["status"] == "warn"
    f = result["findings"][0]
    assert f["overspec_type"] == "overspecification", (
        f"expected default 'overspecification', got {f['overspec_type']}"
    )
    print("  test_finding_unrecognized_overspec_type: PASS (unrecognized type -> kept with default)")


def test_finding_missing_overspec_type():
    """A finding with no overspec_type at all is kept (defaulting to
    'overspecification') rather than dropped."""
    raw = json_fixture(
        verdict="defective",
        findings=[
            {
                "criterion": "deliverables_01/r012",
                "quote": "Each of the 5 checks has an A source and a B source.",
                "pinned_value": "5 checks",
                "instruction_text": "I would rather run four checks.",
                "evidence": "Instruction says four, rubric says 5.",
            },
        ],
    )
    parsed = parse_llm_response(raw)
    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["n_findings"] == 1, "finding without overspec_type should be kept"
    assert result["findings"][0]["overspec_type"] == "overspecification"
    print("  test_finding_missing_overspec_type: PASS (missing type -> kept with default)")


def test_content_unavailable():
    """A response marking content_unavailable maps to status=skip."""
    raw = json_fixture(
        verdict="clean",
        findings=[],
        content_unavailable=True,
        unavailable_reason="instruction.md was empty",
    )
    parsed = parse_llm_response(raw)
    result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
    assert result["status"] == "skip", f"expected skip, got {result['status']}"
    assert result["content_unavailable"] is True
    print("  test_content_unavailable: PASS (content_unavailable -> skip)")


def test_all_overspec_types_recognized():
    """Every overspec_type in OVERSPEC_TYPES is recognized by the
    normalizer."""
    for t in OVERSPEC_TYPES:
        raw = json_fixture(
            verdict="defective",
            findings=[
                {
                    "overspec_type": t,
                    "criterion": "test/c01",
                    "quote": "some pinned value here",
                    "pinned_value": "the pinned value",
                    "instruction_text": "the instruction text",
                    "evidence": "the evidence",
                }
            ],
        )
        parsed = parse_llm_response(raw)
        result = build_task_result_from_response(parsed=parsed, **_make_base_kwargs())
        assert result["n_findings"] == 1, f"overspec_type {t} should produce a finding"
        assert result["findings"][0]["overspec_type"] == t
    print("  test_all_overspec_types_recognized: PASS (all 4 types recognized)")


# ---------------------------------------------------------------------------
# Prompt construction against the REAL SVC-PC-33-8-0 data
# ---------------------------------------------------------------------------


def _real_task_dir() -> Path | None:
    """Locate the real staged SVC-PC-33-8-0 data in the defect archive.
    Returns the directory path or None if not found (test skips gracefully)."""
    candidate = (
        HERE.parent
        / "khiem-202-data"
        / "comprehensive-review-9-real-defects"
        / "SVC-PC-33-8-0"
    )
    return candidate if candidate.is_dir() else None


def _load_real_criteria(task_dir: Path) -> list[dict]:
    """Load criteria from the real defect-archive layout (flat
    deliverables_NN__judge.toml files at the task root, NOT the standard
    tests/deliverables_NN/judge.toml layout the pipeline uses). Parses each
    with tomllib and returns a list of {name, description, judge_group} dicts,
    the same shape collect_rubric_text expects."""
    criteria = []
    for jt in sorted(task_dir.glob("deliverables_*__judge.toml")):
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
        except Exception:
            continue
        group = jt.stem.replace("__judge", "")
        for c in data.get("criterion", []):
            criteria.append(
                {
                    "name": c.get("name", "?"),
                    "description": c.get("description") or "",
                    "judge_group": group,
                }
            )
    return criteria


def test_prompt_construction_real_data():
    """Verify that build_prompt correctly surfaces the real SVC-PC-33-8-0
    instruction text and rubric criteria, including the three known
    over-specification cases.

    This test does NOT make an LLM call. It reads the real files from the
    defect archive, builds the prompt via the same build_prompt function the
    real check uses, and asserts the prompt contains the key instruction
    language and rubric text an LLM judge would need to see to flag
    over-specification.

    Skips gracefully if the real data directory is not present."""
    task_dir = _real_task_dir()
    if task_dir is None:
        print("  test_prompt_construction_real_data: SKIP (real data dir not found)")
        return

    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8", errors="replace")
    criteria = _load_real_criteria(task_dir)
    assert len(criteria) > 0, "expected to parse criteria from the real judge.toml files"

    rubric_text = collect_rubric_text(criteria)
    prompt = build_prompt("SVC-PC-33-8-0", instruction, "", rubric_text)

    # The instruction text must surface the open/flexible/deferred language
    # that makes the over-specification detectable:
    assert "from the people we currently have" in prompt, (
        "prompt must contain the instruction's open-roster language"
    )
    assert "I would rather run four" in prompt, (
        "prompt must contain the instruction's stated preference for four checks"
    )
    assert "James is working out" in prompt, (
        "prompt must contain the instruction's tolerance deferral to James"
    )

    # The rubric text must surface the specific pinned values that
    # over-specify what the instruction left open:
    assert "Jessica Liu" in prompt, (
        "prompt must contain the rubric's pinned person name (Jessica Liu)"
    )
    assert "Priya Patel" in prompt, (
        "prompt must contain the rubric's pinned person name (Priya Patel)"
    )
    assert "David Nguyen" in prompt, (
        "prompt must contain the rubric's pinned person name (David Nguyen)"
    )
    assert "James Okafor" in prompt, (
        "prompt must contain the rubric's pinned person name (James Okafor)"
    )
    assert "5 checks" in prompt or "the 5 checks" in prompt, (
        "prompt must contain the rubric's pinned count of 5 checks"
    )
    assert "None" in rubric_text, (
        "rubric text must contain the tolerance=None pin"
    )

    # The prompt must contain the over-specification methodology instructions
    # so the LLM knows what to check for:
    assert "OVER-SPECIFICATION" in prompt.upper() or "over-specification" in prompt.lower(), (
        "prompt must contain the over-specification definition"
    )
    assert "count_pinned" in prompt, "prompt must list count_pinned as a type"
    assert "name_pinned" in prompt, "prompt must list name_pinned as a type"
    assert "value_pinned" in prompt, "prompt must list value_pinned as a type"
    assert "format_pinned" in prompt, "prompt must list format_pinned as a type"

    # The prompt must label the golden as "ONE valid implementation, not the
    # authority" so the LLM does not treat the golden's design choices as
    # binding requirements:
    assert "not the authority" in prompt.lower(), (
        "prompt must label the golden as non-authoritative"
    )

    print(
        f"  test_prompt_construction_real_data: PASS "
        f"({len(criteria)} criteria, {len(prompt)} chars, all 3 real "
        f"over-spec cases surfaced)"
    )


if __name__ == "__main__":
    tests = [
        test_clean_response,
        test_overspec_name_finding,
        test_overspec_count_finding,
        test_overspec_value_finding,
        test_multiple_overspec_types,
        test_malformed_response,
        test_code_fenced_json,
        test_json_embedded_in_prose,
        test_empty_response,
        test_findings_not_a_list,
        test_finding_missing_quote,
        test_finding_unrecognized_overspec_type,
        test_finding_missing_overspec_type,
        test_content_unavailable,
        test_all_overspec_types_recognized,
        test_prompt_construction_real_data,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  {t.__name__}: FAIL - {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{passed + failed} tests passed")
    sys.exit(1 if failed else 0)
