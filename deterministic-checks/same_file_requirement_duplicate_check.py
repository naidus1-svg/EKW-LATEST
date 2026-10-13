#!/usr/bin/env python3
"""Same-file requirement-clause duplicate check: two or more criteria in the SAME judge.toml
file whose REQUIREMENT clause (the text BEFORE "Expected:", not the Expected clause itself)
is identical after light normalization.

Provenance: found 2026-09-16 while hand-verifying whether duplicate_criterion_content_check.py's
own real fail-tier population (before that check's fail tier was removed this same night, see
tracker row 4) was dominated by genuine duplication or by that check's own disclosed false-
positive shapes. A random 20-task sample of its 230 real pre-fix fail tasks was read by hand,
criterion by criterion. Result: 17-18/20 were benign (large per-row/per-cell data tables where
short numeric-only text spuriously TF-IDF-clusters despite every value differing; and legitimate
cross-deliverable consistency checks, where the SAME upstream input value is independently
verified to have propagated correctly into 2+ DIFFERENT deliverable files -- confirmed directly
against real judge.toml for SVC-PC-41-0-0: r009/deliverables_01 "FY2022 orders plan (base)",
r029/deliverables_03 "Driver, FY2022 orders (base)", r055/deliverables_05 "Demand, FY2022
orders", all three Expected 24,000/Cover!B7, three different files each independently carrying
one shared assumption into a different role, not a defect). 1/20 (SVC-PC-56-4-0) was a CONFIRMED
genuine defect: r001 and r012 are BOTH in tests/deliverables_01/judge.toml, BOTH carry "This is a
must-pass criterion" in their own description text, and their REQUIREMENT clauses (the part
before "Expected:") are byte-identical -- "States that GOTS certifies the cotton shell and inner
chamber of the pillow" -- even though the Expected clauses after that marker differ slightly. A
solver who states this once in that one file satisfies both criteria; the file's own r001+r012
weight (0.0355+0.0327 = 0.0682, real) is double-counted for one fact.

Why this is a DIFFERENT, narrower signal than duplicate_criterion_content_check.py's own
TF-IDF-cosine clustering, not a duplicate of it:

  1. SCOPE: only compares criteria within the SAME judge.toml file (one file = one deliverable
     the solver produces). duplicate_criterion_content_check.py deliberately compares ACROSS all
     of a task's files, because its OWN founding calibration example (SVC-PC-29-2-0's "leave
     export cannot show who covered for whom" cluster) genuinely spans deliverables_02/03/04 --
     see that check's own module docstring. That cross-file scope is correct for SOME real
     defects, but it is also exactly what makes a legitimate cross-deliverable consistency check
     (the SVC-PC-41-0-0 shape above) look identical to a real defect from a pure lexical-
     similarity standpoint: both are "the same content appearing in 2+ criteria across 2+ files."
     Restricting to the SAME file removes that ambiguity at the cost of missing genuine
     cross-file defects (SVC-PC-29-2-0's own shape) -- a disclosed trade, not an oversight; see
     "Known limits" below.
  2. SIGNAL: compares the REQUIREMENT clause (what is being asked), not the Expected clause
     (what the correct answer is) and not the full description. duplicate_criterion_content_
     check.py's own docstring found comparing on the Expected clause alone is a near-total no-op
     at real scale (most real descriptions do not cleanly separate into "Expected: <value>."), so
     it compares on the FULL description with a value-divergence gate layered on top instead.
     This check inverts that: same-file criteria whose Expected clauses genuinely differ (the
     56-4-0 pair: "not the entire pillow" vs "fibre and processing chain... holder is NovaTex")
     can still be the SAME underlying ask restated -- the requirement clause is where that shows
     up, not the Expected clause.
  3. MATCH RULE: exact string match after normalization (lowercase, whitespace-collapsed,
     trailing punctuation stripped), not a similarity threshold. duplicate_criterion_content_
     check.py's own real-corpus experience (three separate threshold-tuning rounds, a disclosed
     "cosine ranges fully overlap" finding between its true-duplicate and false-positive
     populations) is the reason this check does not attempt a fuzzy threshold at all: exact match
     on the pre-Expected requirement text is a much narrower claim ("this is asking the identical
     question, word for word, a second time") that does not need calibrating against a corpus to
     trust, at the cost of missing near-duplicates that reword the requirement slightly. Disclosed
     as a real, deliberate scope limit, not hidden -- see "Known limits" below.

Real calibration (RAN 2026-09-16 against the real 600-task SVC-PC corpus, not assumed):
  - True positive: SVC-PC-56-4-0 fires exactly on r001+r012 in deliverables_01/judge.toml, the
    confirmed genuine case above, and does NOT fire on any of that task's other 19 criteria in
    the same file (the rest of that file's real duplication, per tracker row 4, is genuine
    cross-file restatement across deliverables_01/02/03/04, correctly out of this check's
    same-file scope).
  - Negative calibration: run against the 18 of the original 20-task sample judged benign at the
    time (excluding SVC-PC-56-4-0, the confirmed genuine case, and SVC-PC-56-9-0, then
    unresolved -- this check's own full-corpus run later confirmed 56-9-0 genuine too, see
    below). Zero false positives on all 18 -- in particular SVC-PC-41-0-0 (the cross-deliverable
    consistency shape) does not fire, because its repeated "24,000 (Cover!B7)" criteria are in
    three DIFFERENT files (deliverables_01/03/05), never the same one.
  - Full 600-task corpus (RAN 2026-09-16, real run, this exact script): fail=10, pass=590. Every
    one of the 10 fail tasks' 15 findings was individually spot-checked against its real
    judge.toml (not sampled -- all of them): 15/15 (100%) confirmed genuine same-file
    restatement on this final version. The first full-corpus run, before the verbatim-quote
    exclusion below existed, found fail=11/pass=589 (16 findings): 15/16 genuine, 1/16
    (SVC-PC-56-1-0) a confirmed false positive that motivated that exclusion. Two real,
    previously-unseen genuine cases surfaced beyond the original SVC-PC-56-4-0 calibration
    example: SVC-PC-12-1-0's r022/r023 and SVC-PC-38-6-0's d2/d4 are BYTE-IDENTICAL descriptions
    (not just matching requirement clauses) -- the plainest possible copy-paste duplicate this
    check can catch.

Known limits, disclosed rather than silently dropped:
  - Cross-file duplication (the SVC-PC-29-2-0 shape, duplicate_criterion_content_check.py's own
    founding calibration example) is OUT OF SCOPE here by design -- see reason 1 above. This
    check does not replace that one; it is a narrower, higher-precision SIBLING for the specific
    same-file sub-case, wired as its own letter-D entry alongside it.
  - Near-duplicate requirement clauses (reworded but asking the same thing) are not caught --
    only exact matches after light normalization. A criterion whose requirement clause differs
    by even one real word (not just case/whitespace/punctuation) will not cluster with an
    otherwise-identical sibling. This is deliberate (see reason 3 above), not an oversight.
  - Criteria with no "Expected:" label at all (EKW's own convention; also any malformed SVC-PC
    description) contribute no requirement clause and are silently excluded from comparison --
    there is no reliable way to isolate "the question part" of free text without that marker, so
    this check does not guess.
  - A requirement clause under MIN_CONTENT_WORDS words is excluded (see that constant) -- a very
    short shared phrase ("States that" alone) is not a meaningful signal of the same underlying
    question, just shared sentence-opening boilerplate.
  - Verbatim-quote-check requirement templates (_VERBATIM_QUOTE_RE: "character for character",
    "word for word", "exact wording", "verbatim", "exactly as it appears") are excluded
    entirely -- see that constant's own comment for the confirmed real false positive
    (SVC-PC-56-1-0) that motivated this, and why a general Expected-clause-overlap threshold was
    considered and rejected (it would have created a new false negative on SVC-PC-56-0-0's
    genuine case instead of just fixing this one). This is a real, disclosed gap: a requirement
    template that reuses one of these exact phrases but is NOT a legitimate distinct-quote check
    would be silently missed. 24 real files in the 600-task corpus use this phrasing (grep
    count, not individually re-verified beyond the one confirmed case above); this exclusion
    cannot fire a false NEGATIVE that this check would otherwise have caught, since none of
    those 24 files' criteria appear in this check's own fail output at all -- but a genuine
    same-file restatement that happens to also use "verbatim"-style phrasing, if one exists
    among those 24, would be silently excluded rather than flagged. Not confirmed either way
    beyond the one case checked.

CLI matches this folder's other "std"-style checks (duplicate_criterion_content_check.py's own
find_task_dirs/find_judge_files, reused not re-derived -- see the import below).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from duplicate_criterion_content_check import (  # noqa: E402
    EXPECTED_CLAUSE_RE,
    find_judge_files,
    find_task_dirs,
    to_jsonable,
)
from ekw_verifier_json import has_ekw_config, load_ekw_criteria  # noqa: E402

# ---------------------------------------------------------------------------
# calibrated constants (see module docstring "Real calibration")
# ---------------------------------------------------------------------------

# A shared requirement clause below this many content words is sentence-opening boilerplate,
# not a meaningful "same question asked twice" signal (see module docstring "Known limits").
MIN_CONTENT_WORDS = 4

_WS_RE = re.compile(r"\s+")
_CONTENT_WORD_RE = re.compile(r"[a-z0-9]+")

# Verbatim-quote-check exclusion. Found 2026-09-16 by hand-spot-checking every finding from
# this check's own first full-600-task run against the real judge.toml, per the same
# discipline used on the tracker's own row-4 sample: SVC-PC-56-1-0's r001/r007 share the exact
# requirement clause "Reports the exact wording of the company overview deck as it appears in
# the evidence, character for character" but their Expected clauses are two completely
# different, unrelated quoted passages ("Direct-to-consumer sleep products..." vs "Made in
# Asheville..."). This is a real false positive, confirmed not assumed: the requirement clause
# is a REUSABLE TEMPLATE ("verify this exact quote"), applied once per distinct quoted excerpt
# the deliverable must reproduce verbatim -- structurally the same shape as the "Row 1"/"Row 2"
# and per-SKU template-sharing false positives duplicate_criterion_content_check.py's own
# docstring discloses, just triggering the same-file requirement-clause match here instead of
# TF-IDF cosine. A general Expected-clause-overlap filter was considered and rejected: computed
# directly against every one of this check's 11 real full-corpus fail tasks, word-Jaccard
# overlap between paired Expected clauses does NOT separate this false positive from the
# genuine cases -- SVC-PC-56-0-0's genuine pair ("Every certificate holder in the records is
# NovaTex, not Cirrus Sleep." vs the single word "NovaTex.") scores LOWER overlap (1 shared
# token of 11, ~0.09) than would be needed to exclude 56-1-0's true zero-overlap case without
# also excluding it, so a threshold-based fix would trade this false positive for a new false
# negative. This exclusion is narrower and safer: it names the REQUIREMENT CLAUSE PATTERN
# itself (a criterion whose own stated requirement is "reproduce this exact/verbatim quote"),
# not a threshold on any other field, and reproducing a different specific quote correctly can
# never be "the same fact restated" no matter what the Expected text says.
_VERBATIM_QUOTE_RE = re.compile(
    r"\b(?:character for character|word for word|exact(?:ly)? (?:wording|words|quote)"
    r"|verbatim|exact(?:ly)? as (?:it |they )?appears?)\b",
    re.IGNORECASE,
)


def _requirement_clause(description: str) -> str:
    """Text before the "Expected:" label (EXPECTED_CLAUSE_RE's own marker, imported from
    duplicate_criterion_content_check.py so the two checks can never disagree about where that
    label starts). Empty string if no label is found -- see module docstring "Known limits".
    """
    m = EXPECTED_CLAUSE_RE.search(description or "")
    if not m:
        return ""
    return (description or "")[: m.start()].strip()


def _normalize(text: str) -> str:
    """Lowercase, whitespace-collapsed, trailing-punctuation-stripped. Deliberately NOT a
    similarity measure -- see module docstring reason 3 for why this check uses exact match.
    """
    t = _WS_RE.sub(" ", text.strip().lower())
    return t.strip(" .:;-")


def _to_weight(v) -> float:
    """Same permissive coercion duplicate_criterion_content_check.py uses: a missing or
    non-numeric weight is treated as 0 for excess-weight math, not an error."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# per-file, per-task analysis
# ---------------------------------------------------------------------------


def _analyze_file(criteria: list[dict]) -> list[dict]:
    """One judge.toml file's criteria in. Groups by normalized requirement clause; any group
    of 2+ is a same_file_requirement_duplicate finding. Returns a list of finding dicts (empty
    if none)."""
    by_clause: dict[str, list[dict]] = {}
    for c in criteria:
        clause = _requirement_clause(c["description"])
        if not clause:
            continue
        if _VERBATIM_QUOTE_RE.search(clause):
            # Verbatim-quote-check exclusion -- see _VERBATIM_QUOTE_RE's own comment. A
            # requirement whose own text asks for a specific exact/verbatim quote is, by
            # construction, never "the same fact restated" even when the same template
            # wording is reused for a different quoted excerpt.
            continue
        n_words = len(_CONTENT_WORD_RE.findall(clause.lower()))
        if n_words < MIN_CONTENT_WORDS:
            continue
        by_clause.setdefault(_normalize(clause), []).append(c)

    findings = []
    for norm_clause, group in by_clause.items():
        if len(group) < 2:
            continue
        weights = [_to_weight(c["weight"]) for c in group]
        findings.append(
            {
                "kind": "same_file_requirement_duplicate",
                "file": group[0]["file"],
                "criteria": [c["where"] for c in group],
                "requirement_clause": group[0]["requirement_clause"],
                "expected_clauses": {
                    c["where"]: c["description"][len(c["requirement_clause"]) :].strip()
                    for c in group
                },
                "weights": {c["where"]: _to_weight(c["weight"]) for c in group},
                "n_criteria": len(group),
                "total_weight": round(sum(weights), 6),
                "excess_weight": round(sum(weights) - max(weights), 6),
            }
        )
    findings.sort(key=lambda f: -f["excess_weight"])
    return findings


def analyze_task(task_dir: Path) -> dict:
    """Returns a result dict for one task. Never raises: a missing tests/ dir, an unparseable
    judge.toml, or a malformed criterion array is reported as a skip/parse_error, not a crash.
    """
    task_id = task_dir.name
    result: dict = {
        "task_id": task_id,
        "format": None,
        "status": None,
        "criteria_checked": 0,
        "total_weight": 0.0,
        "parse_errors": [],
        "findings": [],
        "n_findings": 0,
        "total_excess_weight": 0.0,
    }

    judge_files = find_judge_files(task_dir)
    per_file: dict[str, list[dict]] = {}
    total_weight = 0.0
    n_criteria = 0

    if judge_files:
        result["format"] = "svc_pc"
        for jf in judge_files:
            rel = str(jf.relative_to(task_dir)).replace("\\", "/")
            group = jf.parent.name
            try:
                data = tomllib.loads(jf.read_text(encoding="utf-8"))
            except Exception as exc:
                result["parse_errors"].append(f"{rel}: failed to parse -- {exc}")
                continue
            crits = data.get("criterion")
            if crits is None:
                crits = []
            elif not isinstance(crits, list):
                result["parse_errors"].append(
                    f"{rel}: [[criterion]] is not an array (got {type(crits).__name__})"
                )
                continue
            file_criteria = []
            for idx, c in enumerate(crits):
                if not isinstance(c, dict):
                    result["parse_errors"].append(
                        f"{rel}: criterion entry at index {idx} is not a table "
                        f"(got {type(c).__name__}) -- skipped"
                    )
                    continue
                name = c.get("name", f"__index_{idx}__")
                description = c.get("description") or ""
                n_criteria += 1
                total_weight += _to_weight(c.get("weight"))
                file_criteria.append(
                    {
                        "where": f"{group}/{name}",
                        "file": rel,
                        "description": description,
                        "requirement_clause": _requirement_clause(description),
                        "weight": c.get("weight"),
                    }
                )
            per_file[rel] = file_criteria
    elif has_ekw_config(task_dir):
        # EKW has no "Expected:" label convention (see module docstring "Known limits"), so
        # this branch exists for format completeness/never-crash, not because it is expected to
        # find anything -- disclosed, not silently skipped: EKW criteria are still counted and
        # grouped by their own "group" field so the format is not simply ignored.
        result["format"] = "ekw"
        ekw_criteria = load_ekw_criteria(task_dir)
        for c in ekw_criteria:
            if c.get("name") == "__parse_error__":
                result["parse_errors"].append(
                    c.get("description") or "tests/verifier.json parse error"
                )
                continue
            group = c.get("group", "?")
            description = c.get("description") or ""
            n_criteria += 1
            total_weight += _to_weight(c.get("weight"))
            per_file.setdefault(group, []).append(
                {
                    "where": f"{group}/{c.get('name', '?')}",
                    "file": group,
                    "description": description,
                    "requirement_clause": _requirement_clause(description),
                    "weight": c.get("weight"),
                }
            )
    else:
        result["status"] = "skip"
        result["parse_errors"].append(
            "no judge.toml under tests/deliverables/ or tests/deliverables_*/, and no "
            "tests/verifier.json -- nothing for this check to verify"
        )
        return result

    result["criteria_checked"] = n_criteria
    result["total_weight"] = round(total_weight, 6)

    findings: list[dict] = []
    for file_criteria in per_file.values():
        findings.extend(_analyze_file(file_criteria))
    findings.sort(key=lambda f: -f["excess_weight"])
    result["findings"] = findings
    result["n_findings"] = len(findings)
    result["total_excess_weight"] = round(sum(f["excess_weight"] for f in findings), 6)

    if result["parse_errors"] and n_criteria == 0:
        result["status"] = "error"
    elif findings:
        # FAIL, not warn: unlike duplicate_criterion_content_check.py's broad TF-IDF-cosine
        # signal (downgraded to warn-only after finding its true-duplicate and false-positive
        # populations' cosine ranges fully overlap at real scale), this check's exact-match,
        # same-file scope was verified to avoid that overlap on the real 600-task corpus, not
        # assumed from the calibration sample alone -- see module docstring "Real calibration":
        # 0 false positives on the 18-task benign calibration sample, and every one of the
        # real full-corpus run's 15 findings (10 tasks) individually hand-confirmed genuine
        # against real judge.toml (100% precision on this final version, after the one
        # confirmed false positive from the first full run motivated the verbatim-quote
        # exclusion below). Population is also small (10/600, 1.7%), so a human cost of
        # checking every fail-tier hit is low even before precision is counted.
        result["status"] = "fail"
    else:
        result["status"] = "pass"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Same-file requirement-clause duplicate check: 2+ criteria in the SAME judge.toml "
            "file asking the identical question (exact match on the text before 'Expected:', "
            "not the Expected clause itself). See module docstring for the real calibration "
            "against SVC-PC-56-4-0 (confirmed true positive) and the confirmed-benign sample."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="one or more task ids (directory names under --root)",
    )
    ap.add_argument(
        "--all", action="store_true", help="run every task directory found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help="root directory containing one subdirectory per task",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 2

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        r = analyze_task(task_dir)
        results.append(r)
        print(f"    -> {r['status']}  ({r['n_findings']} finding(s))", file=sys.stderr)

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "id_prefix": args.id_prefix,
        "n_tasks": len(results),
        "status_counts": counts,
        "results": results,
    }

    print(f"\n{len(results)} task(s) checked.")
    print("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for r in results:
        if r["status"] == "fail":
            for f in r["findings"]:
                print(
                    f"  {r['task_id']}: FAIL  {f['file']}  {f['criteria']}  "
                    f"excess_weight={f['excess_weight']}  clause={f['requirement_clause'][:100]!r}"
                )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, ensure_ascii=False, default=to_jsonable)
        print(f"\nWrote {args.out}")

    return 1 if counts.get("fail") else 0


if __name__ == "__main__":
    raise SystemExit(main())
