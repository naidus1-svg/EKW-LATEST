#!/usr/bin/env python3
"""Triage layer over compound_criterion_check.py's output: auto-tag each flagged
finding with a confidence label BEFORE a human/agent spends fix effort on it.

Why this exists (2026-09-17): manually adjudicating 6 compound_criterion findings that
Comprehensive Review had NOT already confirmed found 4 real (independently-variable
facts bundled under one weight) and 2 false positives of the check itself, both of the
same shape -- the "clauses" the check counted were not independently-variable facts at
all, they were values in one deterministic arithmetic chain (task_120/v1: unaffected
price x share count = equity value; equity value - net cash = EV; EV / EBITDA and
EV / revenue = the two multiples -- four "clauses", one thing to actually get right).

This script does NOT change compound_criterion_check.py's own clause-counting/severity
logic (that logic is heavily calibrated -- see its module docstring and inline round
notes -- and this script must not perturb it). It is a strictly additive, separate pass
over the SAME JSON output, adding one field per finding:

    "triage": {
        "label": "likely_false_positive" | "needs_manual_read",
        "reason": "<short explanation>",
        "derivation_evidence": [...] | null,
    }

Two known false-positive shapes, only one of which is mechanically detectable:

1. DERIVATION CHAIN (mechanically detectable, implemented here): a clause's number is
   arithmetically derived from other clauses' numbers via a simple relationship
   (product, ratio, sum, difference) within tolerance. When every "extra" clause beyond
   the first is explained this way, the finding is tagged `likely_false_positive` --
   there's really one fact to get right (the base inputs), not several independently-
   failable ones.

2. INTEGRATED NARRATIVE (NOT mechanically detectable -- do not attempt to fake this):
   several clauses are facets of one coherent point rather than independently-omittable
   facts (e.g. task_100/v3: three SKU-tier behaviors that all follow from one correct
   mental model of an allocation policy). Distinguishing this from genuine bundling
   requires reading the actual prompt and judging whether a solver could plausibly get
   some facets right and others wrong for UNRELATED reasons. This script tags anything
   not caught by (1) as `needs_manual_read` with the specific litmus-test question to
   ask -- it deliberately does NOT try to guess an answer here, because guessing wrong
   in the "false positive" direction is exactly how a real bundling defect gets waved
   through unfixed.

Usage:
    python3 compound_criterion_triage.py <compound_check_output.json> [--out FILE.json]

Input is whatever compound_criterion_check.py wrote via its own --json flag (a bare
JSON list, one dict per task, each with "compound_fail"/"compound_warn"/"tiered_warn"
lists of finding dicts carrying "requirement_clauses"/"expected_clauses").
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Numeric extraction
# ---------------------------------------------------------------------------

# Matches things like: $170.00, ~$10,778m, 63.40m, 24.6x, 8.9%, 1.42x, $43.96M,
# $165,000. Captures the numeric magnitude and an optional scale/unit suffix.
_NUM_RE = re.compile(
    r"""
    (?<![\w.])              # not preceded by a word char or a dot (avoid mid-token)
    \$?~?                   # optional leading $ and/or ~
    (\d[\d,]*\.?\d*)         # the digits, with optional thousands separators/decimal
    \s*
    (mm|m|bn|b|k|x|%)?      # optional scale/unit suffix
    (?![\w])                # not followed by a word char
    """,
    re.VERBOSE | re.IGNORECASE,
)

_SCALE = {
    "k": 1e3,
    "m": 1e6,
    "mm": 1e6,
    "b": 1e9,
    "bn": 1e9,
}


def extract_numbers(text: str) -> list[tuple[float, str]]:
    """Returns (magnitude, raw_match) for every plausible numeric token in text.

    Magnitude applies k/m/mm/b/bn scale suffixes so "$10,778m" and "10778000000" (were
    it ever written that way) compare equal; "%"/"x" suffixes are kept unscaled (a
    percentage or a multiple is compared on its own literal number, e.g. 24.6 for
    "24.6x", 8.9 for "8.9%") since those are typically an OUTPUT of a different
    derivation (a ratio) rather than a dollar magnitude in the same unit system as the
    others.
    """
    out: list[tuple[float, str]] = []
    for match in _NUM_RE.finditer(text):
        raw_digits, suffix = match.groups()
        cleaned = raw_digits.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if value == 0:
            continue
        suffix = (suffix or "").lower()
        # Bare 4-digit integers in a plausible calendar-year range are categorical
        # labels, not quantities -- validated 2026-09-17 (task_74/v9): "2029"/"2031"/
        # "2027" got summed/ratio'd against unrelated percentages ("2029 + 4.5% ~=
        # 2031"), a meaningless coincidence, not a real derivation. Only bare integers
        # (no scale suffix, no decimal) in 1900-2100 are excluded -- "$2029" or
        # "2029.5" would not be a year reference and are kept.
        if (
            not suffix
            and value == int(value)
            and 1900 <= value <= 2100
            and "." not in raw_digits
            and "$" not in match.group(0)
        ):
            continue
        scale = _SCALE.get(suffix, 1.0)
        out.append((value * scale, match.group(0).strip()))
    return out


# Above this many extracted numbers in one finding, treat any triple-match as noise --
# validated 2026-09-17 (task_97/v13b): 19 part-number records x 2 fields = 38 numbers
# (many of them themselves part-number fragments, not real quantities) produced 409
# "matching" triples by sheer combinatorial volume, none of them meaningful. A real,
# intentional derivation chain in this corpus's criteria involves a handful of named
# figures (2-8), not dozens.
_MAX_NUMBERS_FOR_DERIVATION_SEARCH = 20


def _has_real_precision(value: float) -> bool:
    """Excludes small round numbers (10, 12, 2, 6...) from counting as derivation
    evidence. Validated 2026-09-17: task_116/v8's five independent, unrelated per-
    cluster slot totals (12.0, 10.0, 2...) coincidentally satisfy a subtraction
    relationship purely because small integers frequently do -- there are few enough
    of them that some pairwise combination landing near another is common, not
    evidence of an intended arithmetic link. A number counts as real evidence only if
    it's large post-scale (>=100, which every genuinely-scaled dollar figure like
    "63.40m"->63,400,000 trivially satisfies) or carries a non-trivial fractional part
    (a real computed output, not a round input like "12.0").
    """
    if abs(value) >= 100:
        return True
    frac = abs(value) - int(abs(value))
    return frac > 1e-9


def _significant_figures(value: float) -> int:
    """Counts significant digits after stripping trailing zeros -- distinguishes a
    genuinely-computed figure (10,778 -> 5 sig figs; 63.40 -> 3) from a round number
    that only LOOKS large ($3,000,000 -> 1 sig fig; $25,000/$50,000/$75,000 -> 1-2).
    """
    v = abs(value)
    if v == 0:
        return 0
    if v == int(v):
        s = str(int(v)).rstrip("0")
        return len(s) if s else 1
    s = f"{v:.6f}".rstrip("0")
    digits = s.replace(".", "").lstrip("0")
    return len(digits) if digits else 1


def _is_high_precision_output(value: float) -> bool:
    """Whether a DERIVED value is precise enough to serve as evidence of a genuine
    calculation, as opposed to a round number that trivially satisfies many
    combinations. Validated 2026-09-17: task_86/v14 matched "$25,000 + $3,000,000 (or
    its restatement $3M) ~= $3,000,000/$3M" and similar sum/difference combinations
    across a small set of round dollar figures ($25k/$50k/$75k/$3M) that are all
    multiples of a common $25,000 base -- round numbers like this satisfy sum/
    difference relationships with each other constantly, by construction, regardless
    of whether the prompt intends any relationship at all. Requiring the DERIVED
    value specifically to carry >=3 significant figures (10,778 does; 3,000,000 and
    75,000 do not) rules this class out while still accepting genuinely-computed
    derived outputs like task_120/v1's "$10,778m".
    """
    return _significant_figures(value) >= 3


def _close(a: float, b: float, rel_tol: float = 0.01) -> bool:
    """1% tolerance, not looser. Validated 2026-09-17: a genuine stated derivation
    (task_120/v1's price x shares = equity value, which the prompt literally writes as
    "= 170.00 x 63.40") lands within 0.02% every time -- prompt authors round inputs,
    not outputs. A 3%-tolerance first version produced a false match on task_121/v14
    (two unrelated NOI/tax figures that happened to subtract to within 2.2% of a third,
    unrelated figure) -- coincidental matches cluster in the 1-3% band precisely because
    that's loose enough for real financial figures to coincide by chance across a
    handful of pairwise/triple combinations. Do not loosen this without re-validating
    against that case.
    """
    if a == 0 or b == 0:
        return False
    return abs(a - b) <= rel_tol * max(abs(a), abs(b))


def _dominance_ok(a: float, b: float, min_ratio: float = 0.05) -> bool:
    """Guards sum/difference relations against the "small + huge ~= huge" trap.
    Validated 2026-09-17: task_101/v1 matched "$3,500,000 (band floor) + $46,980
    (other income) ~= $3,549,000 (the actual NOI)" and task_35_fixed/v9 matched
    "$48,810,000 (loan) + 6.25 (the rate, unscaled) ~= $48,810,000 (the SAME loan
    restated elsewhere)" -- neither is the real calculation (real NOI sums ~7 line
    items; the loan figure is just repeated verbatim), they're artifacts of adding a
    much smaller number to a much larger one, which barely moves the total and so
    trivially lands within tolerance of many nearby figures. Product/ratio relations
    are NOT guarded this way -- price x share-count style derivations routinely span
    many orders of magnitude by design (task_120/v1: $170 x 63,400,000 shares).
    """
    if a == 0 or b == 0:
        return False
    lo, hi = sorted((abs(a), abs(b)))
    return (lo / hi) >= min_ratio


def find_derivations(
    all_numbers: list[tuple[float, str, int]],
) -> list[dict[str, Any]]:
    """all_numbers: (magnitude, raw_text, clause_index). Returns evidence for any triple
    (a, b, c) drawn from DIFFERENT clauses where c ~= a*b, a/b, a+b, or a-b -- i.e. one
    clause's number is arithmetically explained by two others, a strong signal those two
    "separate facts" are really one derivation chain rather than independent claims.
    """
    evidence = []
    n = len(all_numbers)
    if n > _MAX_NUMBERS_FOR_DERIVATION_SEARCH:
        # Too many candidate numbers to trust any triple-match found among them --
        # validated 2026-09-17 (task_97/v13b): 19 part-number records x 2 fields each
        # produced 409 "matching" triples, none meaningful (part-number fragments and
        # unrelated per-unit rates coincidentally satisfying product/ratio checks).
        # At this volume, absence of evidence is the honest answer, not a forced guess.
        return []
    for i in range(n):
        a_val, a_raw, a_idx = all_numbers[i]
        for j in range(n):
            if j == i:
                continue
            b_val, b_raw, b_idx = all_numbers[j]
            if a_idx == b_idx:
                continue  # same clause, not a cross-clause relationship
            for k in range(n):
                if k in (i, j):
                    continue
                c_val, c_raw, c_idx = all_numbers[k]
                if c_idx in (a_idx, b_idx):
                    continue
                clause_set = {a_idx, b_idx, c_idx}
                if len(clause_set) < 3:
                    continue
                if not (
                    _has_real_precision(a_val)
                    and _has_real_precision(b_val)
                    and _has_real_precision(c_val)
                ):
                    continue
                if not _is_high_precision_output(c_val):
                    continue
                relation = None
                if _close(a_val * b_val, c_val):
                    relation = "product"
                elif b_val != 0 and _close(a_val / b_val, c_val):
                    relation = "ratio"
                elif _dominance_ok(a_val, b_val) and _close(a_val + b_val, c_val):
                    relation = "sum"
                elif _dominance_ok(a_val, b_val) and _close(a_val - b_val, c_val):
                    relation = "difference"
                if relation:
                    evidence.append(
                        {
                            "relation": relation,
                            "inputs": [
                                {"clause": a_idx, "value": a_raw},
                                {"clause": b_idx, "value": b_raw},
                            ],
                            "derived": {"clause": c_idx, "value": c_raw},
                        }
                    )
    return evidence


def triage_finding(finding: dict[str, Any]) -> dict[str, Any]:
    req_clauses = finding.get("requirement_clauses") or []
    exp_clauses = finding.get("expected_clauses") or []
    clauses = list(req_clauses) + list(exp_clauses)

    numbered: list[tuple[float, str, int]] = []
    clauses_with_numbers: set[int] = set()
    for idx, clause in enumerate(clauses):
        for value, raw in extract_numbers(clause):
            numbered.append((value, raw, idx))
            clauses_with_numbers.add(idx)

    derivations = find_derivations(numbered)

    if derivations:
        # Require the SAME pair of base-input clauses to explain 2+ DISTINCT derived
        # values before treating this as a genuine calculation chain. Validated
        # 2026-09-17: a real chain reuses its inputs across multiple outputs
        # (task_120/v1: price x shares explains BOTH the stated equity value AND the
        # stated enterprise value). A single isolated match -- one input pair
        # "explaining" exactly one derived value, seen nowhere else -- is exactly the
        # shape of the coincidental matches this script produced before this guard
        # (task_86/v14: one limit + one retention landing near the limit's own
        # rounded figure; task_140/v14: one price-return + one dividend-yield landing
        # near a stated total-return percentage). One coincidence proves nothing; a
        # base-input pair reused across 2+ distinct outputs is real structure.
        by_input_pair: dict[frozenset, set[str]] = {}
        for d in derivations:
            pair = frozenset(c["clause"] for c in d["inputs"])
            by_input_pair.setdefault(pair, set()).add(d["derived"]["value"])

        strong_pairs = {pair for pair, vals in by_input_pair.items() if len(vals) >= 2}

        if strong_pairs:
            strong_evidence = [
                d
                for d in derivations
                if frozenset(c["clause"] for c in d["inputs"]) in strong_pairs
            ]
            explained_clauses = {
                d["derived"]["clause"] for d in strong_evidence
            } | {c["clause"] for d in strong_evidence for c in d["inputs"]}
            return {
                "label": "likely_false_positive",
                "reason": (
                    f"The same base input clause(s) {sorted(next(iter(strong_pairs)))} "
                    f"arithmetically explain {sum(len(v) for p, v in by_input_pair.items() if p in strong_pairs)} "
                    "distinct stated values elsewhere in this criterion -- this reads "
                    "as one deterministic calculation chain (reused inputs producing "
                    "multiple correct outputs), not several independently-variable "
                    "facts. Confirm by eye: if a solver gets the base input(s) right, "
                    "do the other clauses follow automatically as arithmetic "
                    "consequences?"
                ),
                "derivation_evidence": strong_evidence,
            }
        return {
            "label": "needs_manual_read",
            "reason": (
                "A numeric relationship was detected between some clauses, but only "
                "as a single, unconfirmed match (the same base inputs don't explain "
                "any OTHER stated value) -- this is exactly the shape of a "
                "coincidental match on unrelated figures, not a confirmed derivation "
                "chain. Read the prompt directly rather than trusting this alone."
            ),
            "derivation_evidence": derivations,
        }

    return {
        "label": "needs_manual_read",
        "reason": (
            "No arithmetic derivation detected between the bundled clauses. This does "
            "NOT mean it's a real defect -- it may still be one integrated narrative "
            "point restated across facets (task_100/v3 precedent: several SKU-tier "
            "behaviors that all follow from one correct mental model, not independently"
            "-omittable facts). Ask: could a solver satisfy some of these clauses and "
            "not others for genuinely UNRELATED reasons? If yes, likely real bundling. "
            "If the clauses are just restating/elaborating one idea, likely a false "
            "positive of this check -- but that judgment needs an actual read of the "
            "prompt, not a guess."
        ),
        "derivation_evidence": None,
    }


def triage_task(task_result: dict[str, Any]) -> dict[str, Any]:
    for bucket in ("compound_fail", "compound_warn", "tiered_warn"):
        for finding in task_result.get(bucket, []) or []:
            finding["triage"] = triage_finding(finding)
    return task_result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Triage compound_criterion_check.py findings into likely_false_positive "
            "vs needs_manual_read, BEFORE any fix effort is spent on them."
        )
    )
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    data = json.loads(args.input_json.read_text())
    if isinstance(data, list):
        results = [triage_task(task) for task in data]
    elif isinstance(data, dict) and "results" in data:
        data["results"] = [triage_task(task) for task in data["results"]]
        results = data
    else:
        print("Unrecognized input shape (expected a list or {'results': [...]})", file=sys.stderr)
        return 2

    out_text = json.dumps(results, indent=2)
    if args.out:
        args.out.write_text(out_text)
        print(f"wrote {args.out}")
    else:
        print(out_text)

    # Summary to stderr so --out usage still gets a quick readout.
    label_counts: dict[str, int] = {}
    task_list = results if isinstance(results, list) else results["results"]
    for task in task_list:
        for bucket in ("compound_fail", "compound_warn", "tiered_warn"):
            for finding in task.get(bucket, []) or []:
                label = finding["triage"]["label"]
                label_counts[label] = label_counts.get(label, 0) + 1
    print(f"triage summary: {label_counts}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
