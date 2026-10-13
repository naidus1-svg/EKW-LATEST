#!/usr/bin/env python3
"""Cell-address-pinned check: flags rubric criteria that pin an exact numeric
answer AND the exact source cell address it came from, e.g. "18.33 (Cover!B5)".

Why this exists
---------------
`rubric_overspecification_check.py` already recognises three over-specification
categories (count_pinned, name_pinned, value_pinned) via LLM judgment, plus a
fourth (format_pinned). This check catches a fifth, mechanically-detectable
category the LLM check has no pattern for: a criterion whose Expected text
contains BOTH a pinned numeric value AND a spreadsheet cell-address token in the
same vicinity, e.g. "Expected: 18.33 (Cover!B5)." This is worse than a plain
value-pin because it also tells the solver exactly which sheet and cell to read
rather than requiring the solver to build the analysis. Confirmed real example:
SVC-PC-41-4-0, where 34 of 37 criteria pin a numeric value plus a cell address
(23 unique value/cell pairs; many criteria repeat the same pin across
deliverables).

This is the mechanically-detectable case per the project owner's own framing:
the shape is regex-matchable (a number followed by a parenthesised
Sheet!CellRef or bare CellRef), not a semantic judgment. It is therefore a
deterministic script, not an LLM call, matching the architectural choice
`pinned_value_prescreen_check.py` already made for its own mechanically-
detectable patterns.

Architecture choice: standalone script, NOT a new category inside
`rubric_overspecification_check.py`
-------------------------------------------------------------------
`rubric_overspecification_check.py` is LLM-based (one call per task, 50-100s
each). Adding a deterministic regex category there would mix two fundamentally
different detection methods in one file and would either waste an LLM call to
run a regex or need a separate code path that bypasses the LLM entirely. The
existing codebase already established the precedent: `rubric_overspecification
_check.py`'s own docstring explains why it is a sibling script rather than a
7th pattern inside `content_audit_check.py` (different detection method,
different maturity, different cost profile). This script follows the same
logic: it is a sibling of `rubric_overspecification_check.py` (same defect
family) but methodologically a sibling of `pinned_value_prescreen_check.py`
(deterministic regex, dual-format, same CLI shape, same orchestrator
registration shape).

Detection logic
---------------
Two patterns, each producing its own finding kind:

  1. cell_address_pinned_sheet_qualified (primary, high precision): the
     Expected clause contains a number immediately followed by a parenthesised
     sheet-qualified cell reference, e.g. "18.33 (Cover!B5)" or "439,920
     (Cost!C6)". The sheet-qualified form (SheetName!ColumnRow) is inherently
     high-precision: the `!` separator and the combination of a sheet name with
     a column-letter/row-number reference is unambiguous spreadsheet syntax.
     This is the shape all 34 ground-truth criteria in SVC-PC-41-4-0 use.

  2. cell_address_pinned_bare (secondary, lower precision): the Expected clause
     contains a number immediately followed by a parenthesised bare cell
     reference, e.g. "18.33 (B5)". The bare form (ColumnRow without a sheet
     qualifier) is less specific and may false-positive on section/footnote
     references that happen to look like cell refs (e.g. "5 (B2)" where B2 is a
     footnote). The false-positive rate is measured on the real corpus (see
     ROUND62-ROW16-REPORT.md) rather than assumed.

A criterion can trigger both patterns (if it has both a sheet-qualified and a
bare cell ref); each match is reported separately.

The number can be a decimal (18.33), a comma-separated thousands number
(439,920), a dollar amount ($129.07), a percent with a decimal (64.9%), or a
bare integer (440). The cell reference is one to three column letters followed
by one or more row digits (B5, C6, AA10, B11), optionally preceded by a sheet
name and `!`.

Dual-format design (identical to pinned_value_prescreen_check.py):
check_task() for SVC-PC (tests/deliverables*/judge.toml via tomllib),
check_task_ekw() for EKW (tests/verifier.json via ekw_verifier_json.
load_ekw_criteria()), check_task_dispatch() picks SVC-PC first.

Exit 0 clean (zero findings), 1 if any findings, 2 bad usage. Stdlib only
(Python 3.11+ for tomllib); reuses ekw_verifier_json.py for the EKW read per
this folder's convention.

    python cell_address_pinned_check.py <package_root> [--task TASK-ID] [--json out.json]

Status: v1, built 2026-09-17 (round 62, row 16). Validated against the real
SVC-PC-41-4-0 ground truth (34/34 criteria found, 0 false positives, 0 false
negatives) and the full 600-task SVC-PC corpus; see ROUND62-ROW16-REPORT.md for
precision/recall, corpus-wide counts, and the false-positive spot-check.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.stderr.write("needs Python 3.11+ for tomllib\n")
    raise SystemExit(2)

from ekw_verifier_json import has_ekw_config, load_ekw_criteria

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# A spreadsheet cell reference: 1-3 column letters followed by 1+ row digits.
# Excel columns go up to XFD (3 letters); allowing 1-3 covers the full range.
# Case-insensitive to catch both "B5" and "b5".
_CELL_REF = r"[A-Za-z]{1,3}[0-9]+"

# A bare cell ref for the secondary pattern: same as _CELL_REF but the row
# number must NOT start with zero. Real Excel cell refs never have leading
# zeros (B5, not B05). Source citations in this corpus do use leading zeros
# (S07, B08, C02, C06, C08), so this exclusion removes that known
# false-positive class discovered during the corpus-wide spot-check
# (ROUND62-ROW16-REPORT.md, false-positive spot-check).
_BARE_CELL_REF = r"[A-Za-z]{1,3}[1-9][0-9]*"

# A sheet name: starts with a letter or underscore, followed by letters/digits/
# underscores. Matches real sheet names in the corpus: Cover, Cost, Throughput,
# Quality_Watch, SRC_Fulfillment.
_SHEET_NAME = r"[A-Za-z_][A-Za-z0-9_]*"

# Sheet-qualified cell reference: SheetName!CellRef (e.g., Cover!B5)
_SHEET_QUALIFIED_CELL = _SHEET_NAME + r"!" + _CELL_REF

# A number: dollar amount, percent-with-decimal, comma-separated thousands,
# decimal, or bare integer. Order matters: more-specific patterns first so a
# comma-number like "16,800" is matched as one number, not as "16" + ",800".
# Reuses the same number shapes pinned_value_prescreen_check.py already
# calibrated against this corpus, plus bare integers (which that check
# deliberately excludes for its decimal-precision signal but this check needs,
# since "440 (Cost!B8)" is just as much a cell-address pin as "18.33
# (Cover!B5)").
_NUMBER = (
    r"\$\d[\d,]*\.?\d*"        # dollar: $129.07, $2,186,512
    r"|\d+\.\d+%"              # percent with decimal: 64.9%, 0.08%
    r"|\d{1,3}(?:,\d{3})+"     # comma-separated: 439,920; 16,800; 1,204,900
    r"|\d+\.\d+"               # decimal: 18.33, 0.994, 1.6
    r"|\d+"                    # bare integer: 440, 156, 250
)

# Primary pattern: number + (Sheet!Cell) in parentheses.
# e.g., "18.33 (Cover!B5)", "439,920 (Cost!C6)", "16,800 (Cost!B4)"
# The sheet-qualified form is inherently high-precision: the `!` separator is
# specific to spreadsheet cell references, and SheetName!ColumnRow is
# unambiguous.
_SHEET_QUALIFIED_PIN_RE = re.compile(
    r"(" + _NUMBER + r")\s*\(\s*(" + _SHEET_QUALIFIED_CELL + r")\s*\)"
)

# Secondary pattern: number + (bare Cell) in parentheses.
# e.g., "18.33 (B5)", "440 (C6)"
# Lower precision: a bare ColumnRow in parens could be a footnote, section
# reference, fiscal-year label, or quarter label, not a cell address. Two
# exclusions applied after matching (see _is_false_positive_bare_cell):
#   1. The bare cell ref must not have a leading zero in the row (excludes
#      source citations like S07, B08, C02).
#   2. The matched cell ref must not be a fiscal-year (FY2021) or quarter
#      (Q1-Q4) label.
# Even with these exclusions, the bare pattern had 0 true positives and 1
# residual false positive (K12, a source citation indistinguishable from a
# cell ref without semantic context) on the real 600-task corpus. See
# ROUND62-ROW16-REPORT.md for the full false-positive analysis.
_BARE_CELL_PIN_RE = re.compile(
    r"(" + _NUMBER + r")\s*\(\s*(" + _BARE_CELL_REF + r")\s*\)"
)

# Exclusion patterns for the bare cell match: strings that match the
# cell-ref shape but are NOT cell references.
_FISCAL_YEAR_RE = re.compile(r"^FY\d{4}$", re.I)
_QUARTER_RE = re.compile(r"^Q[1-4]$", re.I)

# Extract the Expected clause from a criterion description: everything after the
# first "Expected:" (case-insensitive) to the end of the description. If no
# "Expected:" is found, the full description is searched as a fallback (some
# criteria may use a different label or none at all).
_EXPECTED_CLAUSE_RE = re.compile(r"\bexpected\s*:\s*", re.I)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_expected_clause(description: str) -> str | None:
    """Pull the text after the first 'Expected:' label to the end of the
    description. Returns None if there is no Expected: label, in which case
    the caller searches the full description as a fallback."""
    m = _EXPECTED_CLAUSE_RE.search(description)
    if not m:
        return None
    return description[m.end():].strip()


def _find_sheet_qualified_pins(text: str) -> list[dict]:
    """Find all sheet-qualified cell-address pins in the text. Returns a list
    of dicts with the matched number, cell_ref, and position."""
    findings: list[dict] = []
    seen_spans: list[tuple[int, int]] = []
    for m in _SHEET_QUALIFIED_PIN_RE.finditer(text):
        if any(
            m.start() < s_end and m.end() > s_start
            for s_start, s_end in seen_spans
        ):
            continue
        findings.append({
            "number": m.group(1),
            "cell_ref": m.group(2),
            "qualified": True,
            "pos": m.start(),
        })
        seen_spans.append((m.start(), m.end()))
    return findings


def _is_excluded_bare_cell(cell_ref: str) -> bool:
    """Check whether a bare cell-ref match is a known false-positive class:
    a fiscal-year label (FY2021, FY2022) or a quarter label (Q1, Q2, Q3, Q4).
    These match the cell-ref shape but are not spreadsheet cell references."""
    if _FISCAL_YEAR_RE.match(cell_ref):
        return True
    if _QUARTER_RE.match(cell_ref):
        return True
    return False


def _find_bare_cell_pins(text: str) -> list[dict]:
    """Find all bare cell-address pins in the text, excluding known
    false-positive classes (fiscal-year labels, quarter labels). Also
    deduplicates against sheet-qualified matches by span overlap."""
    findings: list[dict] = []
    seen_spans: list[tuple[int, int]] = []
    for m in _BARE_CELL_PIN_RE.finditer(text):
        if any(
            m.start() < s_end and m.end() > s_start
            for s_start, s_end in seen_spans
        ):
            continue
        cell_ref = m.group(2)
        if _is_excluded_bare_cell(cell_ref):
            continue
        findings.append({
            "number": m.group(1),
            "cell_ref": cell_ref,
            "qualified": False,
            "pos": m.start(),
        })
        seen_spans.append((m.start(), m.end()))
    return findings


def _classify_criterion(description: str, name: str, group: str) -> list[dict]:
    """Run both patterns against one criterion's description. Searches the
    Expected clause first (the user's definition says "Expected text"); if no
    Expected: label is found, searches the full description as a fallback.
    Returns a list of finding dicts."""
    clause = _extract_expected_clause(description)
    search_text = clause if clause is not None else description

    findings: list[dict] = []

    # Primary: sheet-qualified pins
    for pin in _find_sheet_qualified_pins(search_text):
        findings.append({
            "kind": "cell_address_pinned_sheet_qualified",
            "criterion": name,
            "group": group,
            "expected_clause": search_text[:500],
            "number": pin["number"],
            "cell_ref": pin["cell_ref"],
            "qualified": True,
        })

    # Secondary: bare cell pins (deduplicated against sheet-qualified matches)
    sheet_qualified_spans = [
        (m.start(), m.end()) for m in _SHEET_QUALIFIED_PIN_RE.finditer(search_text)
    ]
    for pin in _find_bare_cell_pins(search_text):
        # Skip if this bare match overlaps a sheet-qualified match (the bare
        # regex could match the cell-ref part of a sheet-qualified pin if the
        # number happens to sit right before the open paren in a different
        # context; deduplicate by checking span overlap).
        pin_span = (pin["pos"], pin["pos"] + len(pin["number"]) + len(pin["cell_ref"]) + 5)
        if any(
            pin_span[0] < sq_end and pin_span[1] > sq_start
            for sq_start, sq_end in sheet_qualified_spans
        ):
            continue
        findings.append({
            "kind": "cell_address_pinned_bare",
            "criterion": name,
            "group": group,
            "expected_clause": search_text[:500],
            "number": pin["number"],
            "cell_ref": pin["cell_ref"],
            "qualified": False,
        })

    return findings


# ---------------------------------------------------------------------------
# Per-task
# ---------------------------------------------------------------------------


def check_task(task_dir: Path) -> dict:
    """SVC-PC: read tests/deliverables*/judge.toml via tomllib."""
    res = {
        "task": task_dir.name,
        "format": "svc-pc",
        "judge_files": 0,
        "criteria": 0,
        "findings": [],
        "parse_errors": [],
        "ok": False,
    }
    judge_files = sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )
    if not judge_files:
        res["parse_errors"].append(
            "no judge.toml under tests/deliverables/ or tests/deliverables_*/"
        )
        return res
    res["judge_files"] = len(judge_files)

    for jf in judge_files:
        group = jf.parent.name
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception as exc:
            res["parse_errors"].append(f"{group}/judge.toml: {exc}")
            continue
        for c in data.get("criterion") or []:
            res["criteria"] += 1
            cname = c.get("name", "?")
            desc = (c.get("description") or "").strip()
            res["findings"].extend(_classify_criterion(desc, cname, group))

    res["ok"] = not res["findings"] and not res["parse_errors"]
    return res


def check_task_ekw(task_dir: Path) -> dict:
    """EKW: read tests/verifier.json via ekw_verifier_json.load_ekw_criteria()."""
    res = {
        "task": task_dir.name,
        "format": "ekw",
        "judge_files": 0,
        "criteria": 0,
        "findings": [],
        "parse_errors": [],
        "ok": False,
    }
    criteria = load_ekw_criteria(task_dir)
    if not criteria:
        res["parse_errors"].append("tests/verifier.json has no verifiers")
        return res
    parse_error_entries = [c for c in criteria if c["name"] == "__parse_error__"]
    if parse_error_entries:
        for c in parse_error_entries:
            res["parse_errors"].append(c["description"])
        return res

    res["judge_files"] = 1
    for c in criteria:
        res["criteria"] += 1
        desc = (c.get("description") or "").strip()
        res["findings"].extend(
            _classify_criterion(desc, c["name"], c["group"])
        )
    res["ok"] = not res["findings"] and not res["parse_errors"]
    return res


def _has_svc_pc_config(task_dir: Path) -> bool:
    return bool(
        list(task_dir.glob("tests/deliverables/judge.toml"))
        or list(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def check_task_dispatch(task_dir: Path) -> dict:
    """SVC-PC judge.toml takes precedence when both exist, matching every other
    dual-format script in this folder."""
    if _has_svc_pc_config(task_dir):
        return check_task(task_dir)
    if has_ekw_config(task_dir):
        return check_task_ekw(task_dir)
    return check_task(task_dir)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "root",
        help="a directory containing one subdirectory per task, or a single task directory",
    )
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        help="limit to these task ids (repeatable)",
    )
    ap.add_argument("--json", help="also write the full result set here")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2

    if (root / "tests").is_dir():
        task_dirs = [root]
    else:
        task_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.task:
        want = set(args.task)
        task_dirs = [d for d in task_dirs if d.name in want]
    if not task_dirs:
        sys.stderr.write(f"no task directories matched under {root}\n")
        return 2

    results = [check_task_dispatch(d) for d in task_dirs]

    kind_counts: dict[str, int] = {}
    total_findings = 0
    tasks_with_findings = 0

    for r in results:
        if r["findings"]:
            tasks_with_findings += 1
        total_findings += len(r["findings"])
        for f in r["findings"]:
            kind_counts[f["kind"]] = kind_counts.get(f["kind"], 0) + 1

    for r in results:
        flag = "OK  " if r["ok"] else "FAIL"
        print(
            f"{flag} {r['task']:<20} {r['criteria']:>4} criteria  "
            f"{r['judge_files']:>2} files  {len(r['findings']):>3} findings"
        )
        for w in r["parse_errors"]:
            print(f"       parse: {w}")
        for f in r["findings"]:
            q = "sheet-qualified" if f["qualified"] else "bare"
            print(
                f"       {f['kind']}: {f['group']}/{f['criterion']}  "
                f"{f['number']} -> {f['cell_ref']} ({q})"
            )

    print()
    print(f"{len(results) - tasks_with_findings}/{len(results)} clean")
    print(f"{tasks_with_findings}/{len(results)} tasks with findings")
    print(f"{total_findings} total findings across all tasks")
    print("  by kind:")
    for kind, count in sorted(kind_counts.items()):
        print(f"    {kind}: {count}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"wrote {args.json}")

    return 1 if total_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
