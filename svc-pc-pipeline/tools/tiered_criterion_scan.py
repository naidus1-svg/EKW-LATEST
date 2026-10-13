#!/usr/bin/env python3
"""
tiered_criterion_scan.py - C1 addendum (a): a criterion whose own description
text describes tiers or partial credit (full/half/zero credit, "partial",
"at least N of M", a graded scale) while every criterion in this corpus is
graded type="binary" by rewardkit (confirmed corpus-wide: 6,429/6,429
criteria are type="binary", no scale/numeric type exists). A criterion that
promises partial credit but can only score 0 or 1 is a false promise: a
solver who earns the "half credit" case scores zero, not half.

Fix direction (DataOS C1, laptop, 2026-09-19): split the criterion into
separately weighted binary criteria, one per tier/threshold, dividing the
original weight across them so the group's total weight is unchanged. Never
delete the criterion; never just strip the tier language and leave a single
pass/fail bar that quietly drops the partial-credit case.

READ-ONLY: only reads corpus judge.toml files, never modifies them.

Output: CSV [task, judge_toml, criterion, weight, matched_phrase, description]
Verdict: fail if any criterion in the task matched, else pass.

Usage:
    python3 tiered_criterion_scan.py [--corpus-root PATH] [--out PATH] [--task NAME] [--verdict-out PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_CORPUS_ROOT, DEFAULT_REPORTS_DIR, iter_deliverable_groups, list_tasks, write_csv

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

TIER_PATTERNS = [
    re.compile(r"\bfull credit\b", re.IGNORECASE),
    re.compile(r"\bhalf credit\b", re.IGNORECASE),
    re.compile(r"\bpartial credit\b", re.IGNORECASE),
    re.compile(r"\bzero credit\b", re.IGNORECASE),
    re.compile(r"\bfull marks\b", re.IGNORECASE),
    re.compile(r"\bpartial marks\b", re.IGNORECASE),
    re.compile(r"\bat least \d+\s+of\s+\d+\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*(?:out of|/)\s*\d+\s*(?:points|criteria|items|checks)\b", re.IGNORECASE),
    re.compile(r"\bgraded (?:on a scale|proportionally)\b", re.IGNORECASE),
    re.compile(r"\bproportional credit\b", re.IGNORECASE),
    re.compile(r"\bsliding scale (?:of|for) (?:credit|points|scoring)\b", re.IGNORECASE),
    re.compile(r"\bscale of \d+(?:\s*[-to]+\s*\d+)?\s*points\b", re.IGNORECASE),
    re.compile(r"\b(?:1|one) point (?:for|if)\b.{0,80}\b(?:2|two|another|additional) points? (?:for|if)\b", re.IGNORECASE | re.DOTALL),
    # "tier(ed)" is common as ordinary business content in this corpus (a tiered pricing/approval/wholesale
    # program the DELIVERABLE describes) and is NOT itself evidence of partial-credit grading; only flag it
    # when it sits close to a scoring word, i.e. the RUBRIC's own tiers, not the deliverable's.
    re.compile(r"\btiers?\b.{0,80}\b(?:credit|points?|marks?|scored?)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(?:credit|points?|marks?|scored?)\b.{0,80}\btiers?\b", re.IGNORECASE | re.DOTALL),
]


def scan_task(task_dir: Path) -> list[tuple[str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str]] = []
    for group_dir in iter_deliverable_groups(task_dir):
        jt = group_dir / "judge.toml"
        if not jt.is_file():
            continue
        try:
            d = tomllib.load(open(jt, "rb"))
        except Exception:
            continue
        rel = str(jt.relative_to(task_dir))
        for c in d.get("criterion", []) or []:
            desc = c.get("description") or ""
            if c.get("type", "binary") != "binary":
                continue  # a non-binary type could legitimately carry partial credit; none exist today, but don't flag if one does
            for pat in TIER_PATTERNS:
                m = pat.search(desc)
                if m:
                    rows.append(
                        (
                            task_dir.name,
                            rel,
                            str(c.get("name", "?")),
                            str(c.get("weight", "")),
                            m.group(0),
                            desc[:500],
                        )
                    )
                    break  # one row per criterion is enough evidence
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "tiered_criterion.csv")
    ap.add_argument("--task", type=str, default=None)
    ap.add_argument("--verdict-out", type=Path, default=None)
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple[str, str, str, str, str, str]] = []
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        try:
            all_rows.extend(scan_task(task_dir))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 25 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned", file=sys.stderr)

    n = write_csv(args.out, ["task", "judge_toml", "criterion", "weight", "matched_phrase", "description"], all_rows)
    flagged_tasks = {r[0] for r in all_rows}
    print(f"tiered_criterion_scan: {n} tiered-language criteria across {len(tasks)} tasks, written to {args.out}")
    print(f"  {len(flagged_tasks)} tasks flagged")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = sorted((t.name, "fail" if t.name in flagged_tasks else "pass") for t in tasks)
        vn = write_csv(args.verdict_out, ["task_id", "tiered_criterion_scan"], verdict_rows)
        print(f"tiered_criterion_scan: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
