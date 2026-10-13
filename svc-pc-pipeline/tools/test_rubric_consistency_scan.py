#!/usr/bin/env python3
"""Tests for rubric_consistency_scan.py's unsourced_expected_token dash/quote/whitespace
normalization fix (coordinator, 2026-09-19 22:30Z) and band_text_binary's plain-word-match
tightening. Fixture built from the counterexample verified on SVC-PC-17-2-0's real bytes (a minimal
xlsx reproducing the relevant cells - the real task is never touched). Exit code = number of
failures."""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openpyxl

import rubric_consistency_scan as R

FAILS = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# Fixture: a minimal task dir reproducing SVC-PC-17-2-0's Pricing_Matrix.xlsx cells (the "Cirrus
# Pillow"/"Complete Sleep Set" rows the coordinator's counterexample cited), not the real task.
# ---------------------------------------------------------------------------
def _build_fixture() -> Path:
    task_dir = Path(tempfile.mkdtemp(prefix="test_rubric_consistency_scan_"))
    (task_dir / "tests").mkdir()
    (task_dir / "environment" / "initial_workspace").mkdir(parents=True)
    (task_dir / "solution" / "files").mkdir(parents=True)
    (task_dir / "instruction.md").write_text("Build the pricing memo.\n")
    (task_dir / "tests" / "task_prompt.txt").write_text("Build the pricing memo.\n")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pricing Matrix"
    # Reproduces the real structure: product base name and dash-joined variant qualifier as one
    # cell, with an em dash in most rows and one plain-hyphen variant (as the real workbook has).
    rows = [
        ("SKU", "Product"),
        ("CS-STD-01", "Cirrus Pillow — Standard"),
        ("CS-KNG-01", "Cirrus Pillow — King"),
        ("CS-CVR-WHT", "Organic Pillowcase — Cloud White"),
        ("CS-BDL-STD", "Complete Sleep Set - Standard (kit)"),  # plain hyphen variant, as shipped
    ]
    for r in rows:
        ws.append(r)
    wb.save(task_dir / "environment" / "initial_workspace" / "Pricing_Matrix.xlsx")
    return task_dir


FIXTURE = _build_fixture()
BLOB = R.build_task_source_blob(FIXTURE)

# The six counterexample tokens verified false-positive on SVC-PC-17-2-0's real bytes.
COUNTEREXAMPLE_TOKENS = [
    "Pillow Standard",
    "The Cirrus Pillow — Standard",
    "Pillow King",
    "The Cirrus Pillow — King",
    "Pillowcase Cloud White",
    "Complete Sleep Set — Standard (kit)",
]

for tok in COUNTEREXAMPLE_TOKENS:
    criteria = [("r-test", f'Expected: the row names "{tok}".', 0.01, "g", "binary")]
    rows = R.find_unsourced_tokens("SVC-PC-TEST-0", criteria, BLOB)
    check(f"counterexample token now sourced: {tok!r}", rows == [])

# Negative control: a token that genuinely is not in any source must still fire.
criteria_bad = [("r-bad", 'Expected: the row names "Nebula Cloud Duvet".', 0.01, "g", "binary")]
rows_bad = R.find_unsourced_tokens("SVC-PC-TEST-0", criteria_bad, BLOB)
check(
    "a genuinely unsourced token still fires (no over-loosening)",
    len(rows_bad) == 1 and rows_bad[0][1] == "unsourced_expected_token",
)

# _normalize_for_match unit checks: dash variants collapse, quotes fold, whitespace collapses.
check(
    "em dash and plain hyphen normalize to the same string",
    R._normalize_for_match("Cirrus Pillow — King") == R._normalize_for_match("Cirrus Pillow - King"),
)
check(
    "curly quotes fold to straight",
    R._normalize_for_match("‘Cirrus Pillow’") == R._normalize_for_match("'Cirrus Pillow'"),
)
check(
    "whitespace runs collapse to one space",
    R._normalize_for_match("Cirrus   Pillow\n\nKing") == "Cirrus Pillow King",
)
check(
    "leading article stripped only when requested, only from the token",
    R._normalize_for_match("The Cirrus Pillow", strip_leading_article=True) == "Cirrus Pillow"
    and R._normalize_for_match("The Cirrus Pillow", strip_leading_article=False) == "The Cirrus Pillow",
)

shutil.rmtree(FIXTURE, ignore_errors=True)


# ---------------------------------------------------------------------------
# band_text_binary tightening (see step 2 investigation in the report) - added below by the same
# session pass; kept in this one file per the coordinator's "add a test" instruction for each item.
# ---------------------------------------------------------------------------
def _crit(name, desc, crit_type="binary"):
    return (name, desc, 0.01, "g", crit_type)


# A genuine band: the criterion's OWN text pins a third, partial-credit rung on a binary-typed
# criterion (the docstring's own verified example shape) - the real defect band_text_binary exists
# to catch, unaffected by the "tiered" narrowing.
band_criteria = [_crit("r-band", ">=6 = full; 4 = ~4 pts (pro-rata); <3 = zero.")]
band_rows = R.find_band_text_binary("SVC-PC-TEST-0", band_criteria)
check("genuine scoring band (N=full/partial/zero) on a binary criterion still fires", len(band_rows) == 1)

# A genuine band phrased as "tiered" NEAR actual scoring vocabulary (the criterion's own grading
# scale, not business content) must still fire - the tightening is about proximity, not banning the word.
band_criteria2 = [_crit("r-band2", "Scoring is tiered: full credit for A, half credit for B, zero otherwise.")]
band_rows2 = R.find_band_text_binary("SVC-PC-TEST-0", band_criteria2)
check("'tiered' near real scoring vocabulary still fires", len(band_rows2) == 1)

# Regression: SVC-PC-12-6-0 r010b false-fired because "PASS if ..." (ordinary criterion boilerplate)
# sat within 80 chars of "Tier 3)" - "pass" is not scoring-band vocabulary in this corpus (it is the
# generic pass-condition marker nearly every criterion uses).
band_criteria3 = [
    _crit(
        "r010b",
        "The tier quantities stated are consistent with Elena's pricing proposal: a 24-unit opening "
        "order for Boutique (Tier 1), 100 units per reorder for Core (Tier 2), and 250+ units for "
        "Strategic/Hospitality accounts (Tier 3). PASS if the quantities given track the proposal "
        "rather than being invented Expected: Quantities consistent with the proposal's 24 / 100 / 250+ tiers.",
    )
]
band_rows3 = R.find_band_text_binary("SVC-PC-TEST-0", band_criteria3)
check("SVC-PC-12-6-0 r010b regression: 'Tier N ... PASS if' no longer fires", band_rows3 == [])

# A plain word match: "tiered" as ordinary business content (a tiered wholesale/pricing PROGRAM the
# deliverable describes), not the criterion's own grading scale - must NOT fire after tightening.
word_criteria = [
    _crit(
        "r-word",
        "The response states the written-directive and approval chain for inter-account transfers. "
        "Expected: Bookkeeper initiation follows FP&A direction and tiered approval.",
    )
]
word_rows = R.find_band_text_binary("SVC-PC-TEST-0", word_criteria)
check("plain 'tiered' business-content word match no longer fires", word_rows == [])

print(f"{len(FAILS)} failure(s)")
sys.exit(len(FAILS))
