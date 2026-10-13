#!/usr/bin/env python3
"""U9 pinned-value pre-screen: flag rubric criteria that mechanically look like they pin one
exact value when an equally defensible alternate reading may exist.

Why this exists: Andrew's external review (AR-07) names U9 as a real, high-prevalence pattern
(44/60 tasks): a criterion locks onto one specific value or format when the source material
genuinely supports an equally defensible alternative reading. A mechanical pre-screen was
proposed but never built: flag whole-line regex anchors, hardcoded decimals with no stated
tolerance, or an "Expected:" clause using absolute language ("exactly", "only") where the
source itself shows ambiguity. This script is that pre-screen, operating on the same
judge.toml / verifier.json files every other check in this folder reads.

What "whole-line regex anchor" concretely means in THIS corpus (decided from reading real
criteria, not assumed): a criterion whose Expected clause, after stripping trailing
boilerplate ("This is a must-pass criterion.", "Source: ...", "Reference: ...", "NOTE: ...",
"Pass = ...", "Response criteria guidance: ...", "Blocked if: ..."), is a COMPACT LITERAL
(<= 120 chars) that pins to one exact answer and carries NO alternative-allowing indicator.
The contrast is with Expected clauses that explicitly allow alternatives ("or equivalent",
"any sound approach qualifies", "paraphrase ok", "reasonable values", "approximately", a
range "X through Y", etc.). The "whole-line anchor" name comes from the fact that such a
criterion is effectively a `^<exact value>$` regex anchored to match the whole line: any
deviation from the one pinned literal fails, with no stated room for an equally valid
alternate. The non-numeric case ("Expected: Tom Baker." for a slot the instruction leaves
open to "anyone other than the 3PL relationship owner") is just as much a U9 pin as the
numeric case ("Expected: 0.94." for a baseline the source might carry as 94% or 0.940).

Three sub-patterns, each producing its own finding kind. A criterion can trigger more than
one (a whole-line decimal anchor with no tolerance fires both Pattern 1 and Pattern 3; the
absolute-language pattern fires independently when "exactly"/"only" pins a value inside a
longer Expected clause that is not itself compact enough to be a whole-line anchor):

  1. hardcoded_decimal_no_tolerance: the Expected clause contains a decimal number, a
     comma-separated thousands number, a dollar amount, or a percentage with a decimal part,
     and NO tolerance indicator appears within 50 characters of that number. Tolerance
     indicators: "+/-", "+/-", "approximately", "approx", "~", "about", "around", "or
     equivalent", "or similar", "or roughly", "within" (followed by a number/percent),
     "accept" (followed by a range), or a Unicode approximately-equal sign. A range
     ("X through Y", "X to Y", "between X and Y", "X-Y" with numbers on both sides) within
     the window also counts as tolerance for the numbers it spans.

  2. absolute_language: the Expected clause contains one of "exactly", "only", "must be
     precisely", "precisely", "exactly equal" as a word-boundary match. These words pin a
     value to one answer with no room for alternates, which is the U9 signal when the source
     supports more than one reading.

  3. whole_line_anchor: the Expected clause, after boilerplate stripping, is <= 120 chars
     AND contains no alternative-allowing indicator. Alternative-allowing indicators: "or
     equivalent", "or similar", "or roughly", "or any", "paraphrase", "any sound", "any
     presentation", "any framing", "any approach", "any correct", "any defended", "any
     finding", "reasonable", "approximately", "approx", "~", "about", "around", "+/-",
     "within", "range", "between", "through", "e.g.", "for example", "such as", "qualifies",
     "may", "either", "or not required", "not keyed", "not required". This is the broadest
     pattern: it catches non-numeric pins ("Expected: Tom Baker.", "Expected: Quarterly
     scorecard.") that Patterns 1 and 2 miss.

Dual-format design (identical to rubric_schema_check.py): check_task() for SVC-PC
(tests/deliverables*/judge.toml via tomllib), check_task_ekw() for EKW (tests/verifier.json
via ekw_verifier_json.load_ekw_criteria()), check_task_dispatch() picks SVC-PC first.

Exit 0 clean (zero findings), 1 if any findings, 2 bad usage. Stdlib only (Python 3.11+
for tomllib); reuses ekw_verifier_json.py for the EKW read per this folder's convention.

    python pinned_value_prescreen_check.py <package_root> [--task TASK-ID] [--json out.json]

Status: v1, built 2026-09-15 (round 8). Validated against the real 56-task mirror
(svc-task-samples-56/) with a manual false-positive spot-check of 15 flagged criteria;
see ekw/pipeline-mirror/results/round8-taskB-2026-09-15.md for the honest verdict on
whether the mechanical signal resolves without LLM judgment.
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

# --------------------------------------------------------------------------- constants

# Window for the "tolerance nearby" check in Pattern 1. 50 chars each side is wide enough
# to catch "approximately 0.94" or "0.94 (+/- 0.02)" but narrow enough that a tolerance
# indicator for a DIFFERENT number in a multi-number Expected clause doesn't suppress the
# flag for the one that actually has no tolerance.
TOLERANCE_WINDOW = 50

# Max length of the Expected value (after boilerplate stripping) for it to count as a
# "whole-line anchor" (Pattern 3). Calibrated from the real corpus: the longest genuine
# whole-line anchor seen is about 90 chars ("Expected: $8.75M at 20% through $11.67M at
# 25%." is 42 chars stripped; "Expected: 2,400,000 / 20.87%." is 28 chars). The longest
# non-anchor (a multi-sentence rubric scale with "Full (N): ... Half (M): ... Zero: ...")
# starts at about 150 chars. 120 sits in the gap, but see the honest verdict in the results
# file: some 80-120 char Expected clauses are genuinely ambiguous between "compact pinned
# literal" and "short prose sentence", which is exactly the kind of thing that needs LLM
# judgment to resolve.
ANCHOR_MAX_LEN = 120

# Pattern 1: numbers that count as "hardcoded decimals" when they appear in an Expected
# clause with no tolerance nearby.
#
# DECIMAL_NUMBER_RE: a number with a decimal point (0.94, 2.0, 2117647.0, 698718.54).
#   Excludes bare integers by requiring the dot + fractional part -- a bare "18" is caught
#   by Pattern 3 (whole-line anchor) if it's the whole Expected value, but Pattern 1 is
#   specifically about DECIMAL precision, where the .Xf part is what pins the value.
# COMMA_NUMBER_RE: a comma-separated thousands number (1,204,900; 84,344; 6,400,000).
#   These carry the same pin signal: the exact number is stated with no tolerance.
# DOLLAR_RE: a dollar amount ($129.07, $2,186,512, $45,000).
# PERCENT_DECIMAL_RE: a percentage with a decimal part (64.9%, 20.87%, 0.08%). A bare "20%"
#   without a decimal is not pinned to a decimal precision and is left to Pattern 3.
DECIMAL_NUMBER_RE = re.compile(r"\d+\.\d+")
COMMA_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
DOLLAR_RE = re.compile(r"\$\d[\d,]*\.?\d*")
PERCENT_DECIMAL_RE = re.compile(r"\d+\.\d+%")

# Pattern 1: tolerance indicators. If any of these appears within TOLERANCE_WINDOW chars
# of a number, that number is considered to have a stated tolerance and is NOT flagged.
# Each entry is a regex; the check is a search within the window substring.
TOLERANCE_INDICATORS = [
    re.compile(r"\+/\s*-"),          # +/- with optional space
    re.compile(r"\\pm\b"),           # LaTeX pm
    re.compile(r"approximately", re.I),
    re.compile(r"\bapprox\b", re.I),
    re.compile(r"~"),                # tilde prefix (~4.7%)
    re.compile(r"\babout\b", re.I),
    re.compile(r"\baround\b", re.I),
    re.compile(r"\bor equivalent\b", re.I),
    re.compile(r"\bor similar\b", re.I),
    re.compile(r"\bor roughly\b", re.I),
    re.compile(r"\bwithin\s+\d", re.I),  # "within 5%", "within 0.1pp"
    re.compile(r"\baccept\s+[\d$]", re.I),  # "accept $29,189-$29,205"
    re.compile(r"\u2248"),           # ≈ approximately equal
    re.compile(r"\u00b1"),           # ± plus-minus sign
]

# A range within the window also counts as tolerance. This regex matches two numbers
# separated by a range connector: "through", "to", "between ... and", or a bare dash/hyphen
# with number-like content on both sides. Checked within the window substring.
RANGE_CONNECTOR_RE = re.compile(
    r"\d\s*(?:through|to|-\s*)\s*\d"  # "20% through 25%", "20%-25%", "20 to 25"
    r"|between\s+\d[^.]*\band\s+\d",  # "between 20 and 25"
    re.I,
)

# Pattern 2: absolute language. Word-boundary matches in the Expected clause.
ABSOLUTE_LANGUAGE_RES = [
    re.compile(r"\bexactly\b", re.I),
    re.compile(r"\bonly\b", re.I),
    re.compile(r"\bmust be precisely\b", re.I),
    re.compile(r"\bprecisely\b", re.I),
    re.compile(r"\bexactly equal\b", re.I),
]

# Pattern 3: boilerplate to strip from the END of the Expected clause before the
# compact-literal check. Each is anchored to the end of the string (after trailing
# whitespace/periods are trimmed). Stripped iteratively: the first match is removed, then
# the remainder is checked again, until no more boilerplate matches.
BOILERPLATE_END_RES = [
    re.compile(r"\s*This is a must[\s-]*pass criterion\.?\s*$", re.I),
    re.compile(r"\s*Source:.*$", re.I),
    re.compile(r"\s*Reference:.*$", re.I),
    re.compile(r"\s*NOTE:.*$", re.I),
    re.compile(r"\s*Note for graders:.*$", re.I),
    re.compile(r"\s*NOTE,\s*not required.*$", re.I),
    re.compile(r"\s*Pass\s*=\s*.*$", re.I),
    re.compile(r"\s*Response criteria guidance:.*$", re.I),
    re.compile(r"\s*Blocked if:.*$", re.I),
    re.compile(r"\s*\(SRC-\d+[^)]*\)\.?\s*$", re.I),       # (SRC-1; SRC-8)
    re.compile(r"\s*\([A-Z]+-\d+[^)]*\)\.?\s*$", re.I),     # (WS-3), (WS-1; WS-2)
]

# Pattern 3: alternative-allowing indicators. If ANY of these appears in the
# boilerplate-stripped Expected value, it is NOT a whole-line anchor (the criterion
# explicitly allows an alternate).
ALTERNATIVE_INDICATORS = [
    re.compile(r"\bor equivalent\b", re.I),
    re.compile(r"\bor similar\b", re.I),
    re.compile(r"\bor roughly\b", re.I),
    re.compile(r"\bor any\b", re.I),
    re.compile(r"\bparaphrase\b", re.I),
    re.compile(r"\bany sound\b", re.I),
    re.compile(r"\bany presentation\b", re.I),
    re.compile(r"\bany framing\b", re.I),
    re.compile(r"\bany approach\b", re.I),
    re.compile(r"\bany correct\b", re.I),
    re.compile(r"\bany defended\b", re.I),
    re.compile(r"\bany finding\b", re.I),
    re.compile(r"\bany sound\b", re.I),
    re.compile(r"\breasonable\b", re.I),
    re.compile(r"\bapproximately\b", re.I),
    re.compile(r"\bapprox\b", re.I),
    re.compile(r"~"),
    re.compile(r"\babout\b", re.I),
    re.compile(r"\baround\b", re.I),
    re.compile(r"\+/-"),
    re.compile(r"\u00b1"),           # ±
    re.compile(r"\u2248"),           # ≈
    re.compile(r"\bwithin\s+\d", re.I),
    re.compile(r"\brange\b", re.I),
    re.compile(r"\bbetween\b", re.I),
    re.compile(r"\bthrough\b", re.I),
    re.compile(r"\be\.g\.", re.I),
    re.compile(r"\bfor example\b", re.I),
    re.compile(r"\bsuch as\b", re.I),
    re.compile(r"\bqualifies\b", re.I),
    re.compile(r"\bnot keyed\b", re.I),
    re.compile(r"\bnot required\b", re.I),
    re.compile(r"\bmay\b", re.I),
    re.compile(r"\beither\b", re.I),
    re.compile(r"\bor not required\b", re.I),
]

# Extract the Expected clause from a criterion description: everything after the first
# "Expected:" (case-insensitive) to the end of the description. If no "Expected:" is found,
# the criterion has no Expected clause and no pattern can fire.
EXPECTED_CLAUSE_RE = re.compile(r"\bexpected\s*:\s*", re.I)


# --------------------------------------------------------------------------- helpers


def _extract_expected_clause(description: str) -> str | None:
    """Pull the text after the first 'Expected:' label to the end of the description.
    Returns None if there is no Expected: label (the criterion uses a different format
    or the label was never populated -- that is rubric_schema_check.py's territory, not
    this script's)."""
    m = EXPECTED_CLAUSE_RE.search(description)
    if not m:
        return None
    return description[m.end():].strip()


def _strip_trailing_boilerplate(text: str) -> str:
    """Iteratively strip known trailing boilerplate from the END of the Expected value.
    Stops when no boilerplate pattern matches the current tail. Trailing
    whitespace/periods are trimmed between rounds."""
    prev = None
    current = text.strip().rstrip(".")
    while prev != current:
        prev = current
        for pat in BOILERPLATE_END_RES:
            m = pat.search(current)
            if m:
                current = current[: m.start()].strip().rstrip(".")
                break
    return current.strip()


def _has_tolerance_nearby(number_match: re.Match, clause: str) -> bool:
    """Check whether any tolerance indicator or range connector appears within
    TOLERANCE_WINDOW chars of the given number match, in either direction."""
    start = max(0, number_match.start() - TOLERANCE_WINDOW)
    end = min(len(clause), number_match.end() + TOLERANCE_WINDOW)
    window = clause[start:end]
    for pat in TOLERANCE_INDICATORS:
        if pat.search(window):
            return True
    if RANGE_CONNECTOR_RE.search(window):
        return True
    return False


def _find_hardcoded_decimals(clause: str) -> list[dict]:
    """Find all decimal/comma/dollar/percent-decimal numbers in the clause that have no
    tolerance indicator within TOLERANCE_WINDOW chars. Returns a list of dicts with the
    matched value and its position, for reporting."""
    findings: list[dict] = []
    seen_spans: list[tuple[int, int]] = []
    for pat in (
        DECIMAL_NUMBER_RE,
        COMMA_NUMBER_RE,
        DOLLAR_RE,
        PERCENT_DECIMAL_RE,
    ):
        for m in pat.finditer(clause):
            # Skip if this span overlaps one already found (e.g. "$1,204,900" matches both
            # DOLLAR_RE and COMMA_NUMBER_RE; count it once, preferring the first pattern).
            if any(
                m.start() < s_end and m.end() > s_start
                for s_start, s_end in seen_spans
            ):
                continue
            if _has_tolerance_nearby(m, clause):
                continue
            findings.append({"value": m.group(), "pos": m.start()})
            seen_spans.append((m.start(), m.end()))
    return findings


def _find_absolute_language(clause: str) -> list[dict]:
    """Find all absolute-language word matches in the Expected clause."""
    findings: list[dict] = []
    for pat in ABSOLUTE_LANGUAGE_RES:
        for m in pat.finditer(clause):
            findings.append({"word": m.group(), "pos": m.start()})
    return findings


def _check_whole_line_anchor(clause: str) -> dict | None:
    """Check whether the Expected clause, after boilerplate stripping, is a compact
    literal (<= ANCHOR_MAX_LEN chars) with no alternative-allowing indicator. Returns a
    dict with the stripped value if it is an anchor, None otherwise."""
    stripped = _strip_trailing_boilerplate(clause)
    if not stripped:
        return None
    if len(stripped) > ANCHOR_MAX_LEN:
        return None
    for pat in ALTERNATIVE_INDICATORS:
        if pat.search(stripped):
            return None
    return {"stripped_value": stripped, "length": len(stripped)}


def _classify_criterion(description: str, name: str, group: str) -> list[dict]:
    """Run all three patterns against one criterion's description. Returns a list of
    finding dicts, each with kind, criterion name, group, the Expected clause, and the
    pattern-specific detail."""
    clause = _extract_expected_clause(description)
    if clause is None:
        return []

    findings: list[dict] = []

    # Pattern 1: hardcoded decimal, no tolerance
    decimals = _find_hardcoded_decimals(clause)
    if decimals:
        findings.append(
            {
                "kind": "hardcoded_decimal_no_tolerance",
                "criterion": name,
                "group": group,
                "expected_clause": clause,
                "detail": decimals,
            }
        )

    # Pattern 2: absolute language
    absolutes = _find_absolute_language(clause)
    if absolutes:
        findings.append(
            {
                "kind": "absolute_language",
                "criterion": name,
                "group": group,
                "expected_clause": clause,
                "detail": absolutes,
            }
        )

    # Pattern 3: whole-line anchor
    anchor = _check_whole_line_anchor(clause)
    if anchor:
        findings.append(
            {
                "kind": "whole_line_anchor",
                "criterion": name,
                "group": group,
                "expected_clause": clause,
                "stripped_value": anchor["stripped_value"],
                "length": anchor["length"],
            }
        )

    return findings


# --------------------------------------------------------------------------- per-task


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


# --------------------------------------------------------------------------- main


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
            detail_str = ""
            if f["kind"] == "hardcoded_decimal_no_tolerance":
                vals = ", ".join(d["value"] for d in f["detail"])
                detail_str = f"  decimals: {vals}"
            elif f["kind"] == "absolute_language":
                words = ", ".join(d["word"] for d in f["detail"])
                detail_str = f"  words: {words}"
            elif f["kind"] == "whole_line_anchor":
                detail_str = f"  stripped: \"{f['stripped_value']}\" ({f['length']} chars)"
            print(
                f"       {f['kind']}: {f['group']}/{f['criterion']}{detail_str}"
            )
            print(f"         Expected clause: {f['expected_clause'][:200]}")

    print()
    print(f"{len(results) - tasks_with_findings}/{len(results)} clean")
    print(f"{tasks_with_findings}/{len(results)} tasks with findings")
    print(f"{total_findings} total findings across all tasks")
    print("  by kind:")
    for kind, count in sorted(kind_counts.items()):
        print(f"    {kind}: {count}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, indent=2, default=str), encoding="utf-8"
        )
        print(f"wrote {args.json}")

    return 1 if total_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
