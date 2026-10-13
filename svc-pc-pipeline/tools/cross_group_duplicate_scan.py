#!/usr/bin/env python3
"""
cross_group_duplicate_scan.py - GATE-V2 class B: duplicate and compound
criteria, within and across judge groups.

Parses every tests/deliverables*/judge.toml per task and flags:
  (a) duplicate criteria: near-identical description text between two
      criteria, whether in the same judge group (dup-within) or in different
      groups (dup-cross). Similarity is difflib.SequenceMatcher ratio on
      normalized (lowercased, whitespace-collapsed) description text,
      threshold 0.75.
  (b) compound criteria: one criterion asserting multiple independently
      gradable facts. Heuristics (any one flags it):
        - an uppercase "AND" connector in the description (the corpus's own
          compound marker, e.g. "Rent & Office $46,000 AND Payment
          Processing $37,942, each present")
        - more than one "Expected:" clause in one description
        - two or more distinct dollar figures joined by a lowercase "and"
          with no arithmetic operator between them (arithmetic operators
          like "=", "-", "+" mean it's one derived figure, not two facts)

This is what compound_criterion and criterion_groundedness are meant to
catch (GATE-V2 2.5, 3.4 re-enables them). Detection here is heuristic on
description text, not a substitute for the checks re-enabled at ship time;
treat findings as a work list, not a final verdict.

READ-ONLY: only reads tests/deliverables*/judge.toml, never modifies them.

Output: CSV [task, kind, group(s), criterion_ids, note] where kind is one of
dup-within, dup-cross, compound.

Usage:
    python3 cross_group_duplicate_scan.py [--corpus-root PATH] [--out PATH] [--threshold FLOAT]
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_CORPUS_ROOT, DEFAULT_REPORTS_DIR, iter_deliverable_groups, list_tasks, write_csv

DEFAULT_THRESHOLD = 0.75


def normalize_desc(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def load_all_criteria(task_dir: Path) -> list[dict]:
    criteria = []
    for group_dir in iter_deliverable_groups(task_dir):
        toml_path = group_dir / "judge.toml"
        if not toml_path.is_file():
            continue
        try:
            with toml_path.open("rb") as f:
                data = tomllib.load(f)
        except Exception:
            continue
        for c in data.get("criterion", []):
            criteria.append(
                {
                    "group": group_dir.name,
                    "name": c.get("name", "?"),
                    "description": c.get("description", "") or "",
                    "weight": c.get("weight"),
                }
            )
    return criteria


def detect_compound(desc: str) -> list[str]:
    reasons = []
    if re.search(r"\bAND\b", desc):
        reasons.append("uppercase AND connector")
    if desc.count("Expected:") > 1:
        reasons.append("multiple 'Expected:' clauses")
    money_vals = re.findall(r"\$\(?-?[\d,]+(?:\.\d+)?\)?", desc)
    distinct_money = set(money_vals)
    arithmetic_join = bool(re.search(r"\$[\d,.()-]+\s*[=+\-−×*]\s*\$?[\d,.()-]+", desc))
    if len(distinct_money) >= 2 and not arithmetic_join and re.search(r"\band\b", desc, re.IGNORECASE):
        reasons.append("multiple independent dollar figures joined by 'and'")
    return reasons


def detect_duplicates(criteria: list[dict], threshold: float) -> list[tuple[str, dict, dict, float]]:
    rows = []
    for i in range(len(criteria)):
        for j in range(i + 1, len(criteria)):
            a, b = criteria[i], criteria[j]
            if not a["description"] or not b["description"]:
                continue
            ratio = SequenceMatcher(None, normalize_desc(a["description"]), normalize_desc(b["description"])).ratio()
            if ratio >= threshold:
                kind = "dup-within" if a["group"] == b["group"] else "dup-cross"
                rows.append((kind, a, b, ratio))
    return rows


def scan_task(task_dir: Path, threshold: float) -> list[tuple[str, str, str, str, str]]:
    criteria = load_all_criteria(task_dir)
    rows: list[tuple[str, str, str, str, str]] = []

    for c in criteria:
        reasons = detect_compound(c["description"])
        if reasons:
            rows.append((task_dir.name, "compound", c["group"], c["name"], "; ".join(reasons)))

    for kind, a, b, ratio in detect_duplicates(criteria, threshold):
        groups = a["group"] if a["group"] == b["group"] else f"{a['group']}+{b['group']}"
        criterion_ids = f"{a['name']}|{b['name']}"
        note = f"similarity={ratio:.2f}"
        rows.append((task_dir.name, kind, groups, criterion_ids, note))

    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT, help="corpus root directory")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "duplicates.csv", help="output CSV path")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="duplicate similarity threshold (0-1)")
    ap.add_argument("--task", type=str, default=None, help="restrict to a single task name (debugging)")
    ap.add_argument("--verdict-out", type=Path, default=None, help="write task_id,cross_group_duplicate_scan pass|warn|fail summary CSV")
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple[str, str, str, str, str]] = []
    errors: list[str] = []
    for task_dir in tasks:
        try:
            all_rows.extend(scan_task(task_dir, args.threshold))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")

    n = write_csv(args.out, ["task", "kind", "groups", "criterion_ids", "note"], all_rows)

    by_kind: dict[str, set[str]] = {}
    for r in all_rows:
        by_kind.setdefault(r[1], set()).add(r[0])

    print(f"cross_group_duplicate_scan: {n} findings across {len(tasks)} tasks, written to {args.out}")
    for kind in ("compound", "dup-within", "dup-cross"):
        count = sum(1 for r in all_rows if r[1] == kind)
        print(f"  {kind}: {count} findings, {len(by_kind.get(kind, set()))} tasks affected")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        fail_tasks = by_kind.get("dup-cross", set()) | by_kind.get("compound", set())
        warn_tasks = by_kind.get("dup-within", set()) - fail_tasks

        def _verdict(name: str) -> str:
            if name in fail_tasks:
                return "fail"
            if name in warn_tasks:
                return "warn"
            return "pass"

        verdict_rows = sorted((t.name, _verdict(t.name)) for t in tasks)
        vn = write_csv(args.verdict_out, ["task_id", "cross_group_duplicate_scan"], verdict_rows)
        print(f"cross_group_duplicate_scan: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
