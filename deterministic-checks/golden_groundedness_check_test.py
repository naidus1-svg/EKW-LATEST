#!/usr/bin/env python3
"""Unit tests for golden_groundedness_check.py, focused on the 2026-09-16 port and its real,
necessary adaptations for THIS repo (see that module's own docstring NOTE and this file's
own module docstring "Real calibration" for the full real-corpus story). Does NOT make any LLM
call -- these cover claim extraction and the cross-document retrieval rebuild only, the parts
verifiable without a backend. The LLM-judgment step itself was verified with real calls against
SVC-PC-5-3-0 and SVC-PC-37-3-0 directly (see tracker row 13), not re-tested here.

Run:
    python deterministic-checks/golden_groundedness_check_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from golden_groundedness_check import (
    build_env_text,
    extract_golden_claims,
    find_env_excerpts,
    read_xlsx_all_text_with_values,
    read_xlsx_label_value_pairs,
)


def test_extract_claim_finds_bare_currency_figure():
    """A bare dollar figure presented as a fact (not a derivation statement) must be extracted
    as a claim, with its context words including the topic vocabulary around it -- the shape
    SVC-PC-5-3-0's real $4,390 claim has."""
    golden_text = (
        "returns, fulfilment (secondary): FY2021 Returns & Refunds expense was $4,390 "
        "(actual), a modest operating drag; any forward effect is an analyst estimate."
    )
    claims = extract_golden_claims(golden_text, [], [])
    values = [c["value_raw"] for c in claims]
    assert "$4,390" in values, f"expected $4,390 among claims, got {values}"
    claim = next(c for c in claims if c["value_raw"] == "$4,390")
    words = set(claim["context_words"])
    assert "returns" in words or "refunds" in words, claim["context_words"]
    print("  test_extract_claim_finds_bare_currency_figure: PASS")


def test_build_env_text_returns_per_file_texts():
    """build_env_text's 2026-09-16 addition: per_file_texts must be a (filename, text) list
    that reconstructs the same content as the flat env_text, just not pre-joined."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="_gg_test_") as tmp:
        d = Path(tmp)
        f1 = d / "a.txt"
        f2 = d / "b.txt"
        f1.write_text("alpha content here", encoding="utf-8")
        f2.write_text("beta content here", encoding="utf-8")
        env_text, value_maps, file_names, total_bytes, per_file_texts = build_env_text(
            [f1, f2]
        )
        names = [n for n, _ in per_file_texts]
        assert "a.txt" in names and "b.txt" in names, names
        texts = dict(per_file_texts)
        assert "alpha content" in texts["a.txt"]
        assert "beta content" in texts["b.txt"]
        assert "alpha content" in env_text and "beta content" in env_text
        print("  test_build_env_text_returns_per_file_texts: PASS")


def test_cross_document_retrieval_finds_both_real_files():
    """The core fix this port shipped: SVC-PC-5-3-0's real shape, synthesized. A claim's real
    evidence is split across TWO named documents (Q1 states the actual figure differently
    worded/singular, Q2 states a different actual figure), plus a decoy file that shares only
    a generic word. Both real files must appear in the returned excerpt; the decoy must not
    dominate them."""
    claims = [
        {
            "value": 4390.0,
            "value_raw": "$4,390",
            "kind": "currency",
            "context": "FY2021 Returns & Refunds expense was $4,390 (actual), a modest operating drag",
            "source_file": "golden.xlsx",
            "context_words": [
                "returns",
                "refunds",
                "expense",
                "actual",
                "modest",
                "operating",
                "drag",
            ],
        }
    ]
    per_file_texts = [
        (
            "Q1_Ops_Summary.docx",
            "Apex processed returns at $3.10 per RMA. The cash refund total for Q1 was "
            "$2,390 (source records ratified Jun 10). The full restock decision tree is "
            "documented in the Returns SOP.",
        ),
        (
            "Q2_Ops_Summary.docx",
            "Net revenue came in at $195.5K. Less: refunds & returns $(2,200). Operations "
            "held up well this quarter with modest softening in AOV.",
        ),
        (
            "Unrelated_Decoy.docx",
            "Operational excellence is our top priority this year. " * 5
            + "We drag our feet on nothing.",
        ),
    ]
    env_text = "\n".join(f"--- file: {n} ---\n{t}" for n, t in per_file_texts)
    excerpts = find_env_excerpts(claims, env_text, {}, per_file_texts)
    assert len(excerpts) == 1
    excerpt = excerpts[0]
    assert "Q1_Ops_Summary.docx" in excerpt, excerpt
    assert "Q2_Ops_Summary.docx" in excerpt, excerpt
    assert "2,390" in excerpt, "Q1's real figure must appear in the excerpt text"
    assert "2,200" in excerpt, "Q2's real figure must appear in the excerpt text"
    print("  test_cross_document_retrieval_finds_both_real_files: PASS")


def test_generic_word_does_not_dominate_specific_word():
    """A word matching MOST files (here, "operational") must not out-rank a file matching
    only a RARE, specific word (here, "refunds") -- the document-frequency filter's whole job.
    Regression guard for the real SVC-PC-5-3-0 bug: before this filter, "operational" alone
    let several unrelated files outrank the one real file with the specific evidence."""
    claims = [
        {
            "value": 100.0,
            "value_raw": "$100",
            "kind": "currency",
            "context": "operational refunds figure",
            "source_file": "golden.xlsx",
            "context_words": ["operational", "refunds"],
        }
    ]
    per_file_texts = [
        (f"generic_{i}.docx", "operational review notes here") for i in range(6)
    ]
    per_file_texts.append(
        ("the_real_one.docx", "operational note: refunds total is $100 exactly")
    )
    env_text = "\n".join(f"--- file: {n} ---\n{t}" for n, t in per_file_texts)
    excerpts = find_env_excerpts(claims, env_text, {}, per_file_texts)
    assert "the_real_one.docx" in excerpts[0], excerpts[0]
    print("  test_generic_word_does_not_dominate_specific_word: PASS")


def test_singular_plural_tolerance():
    """A claim's context word "refunds" (plural) must still match a source file that says
    "refund" (singular) -- the real SVC-PC-5-3-0 Q1_Ops_Summary.docx shape ("cash refund
    total"), confirmed as a real miss before this tolerance was added."""
    claims = [
        {
            "value": 50.0,
            "value_raw": "$50",
            "kind": "currency",
            "context": "returns and refunds total",
            "source_file": "golden.xlsx",
            "context_words": ["returns", "refunds"],
        }
    ]
    per_file_texts = [
        ("singular_form.docx", "the cash refund amount recorded was $50 flat")
    ]
    env_text = (
        "--- file: singular_form.docx ---\nthe cash refund amount recorded was $50 flat"
    )
    excerpts = find_env_excerpts(claims, env_text, {}, per_file_texts)
    assert "singular_form.docx" in excerpts[0], excerpts[0]
    print("  test_singular_plural_tolerance: PASS")


def test_xlsx_readers_self_contained():
    """read_xlsx_all_text_with_values / read_xlsx_label_value_pairs must work standing alone
    (inlined 2026-09-16, no dependency on this repo's differently-shaped
    golden_arithmetic_check.py -- see the port's own NOTE comment)."""
    try:
        import openpyxl
    except ImportError:
        print("  test_xlsx_readers_self_contained: SKIP (openpyxl not installed)")
        return
    import tempfile

    with tempfile.TemporaryDirectory(prefix="_gg_test_") as tmp:
        p = Path(tmp) / "t.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Returns total", 2390])
        ws.append(["Refunds total", 2200])
        wb.save(str(p))
        pairs = read_xlsx_label_value_pairs(p)
        assert pairs.get("returns total") == 2390.0, pairs
        text, pairs2 = read_xlsx_all_text_with_values(p)
        assert "Returns total" in text
        assert pairs2.get("refunds total") == 2200.0, pairs2
    print("  test_xlsx_readers_self_contained: PASS")


if __name__ == "__main__":
    tests = [
        test_extract_claim_finds_bare_currency_figure,
        test_build_env_text_returns_per_file_texts,
        test_cross_document_retrieval_finds_both_real_files,
        test_generic_word_does_not_dominate_specific_word,
        test_singular_plural_tolerance,
        test_xlsx_readers_self_contained,
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
