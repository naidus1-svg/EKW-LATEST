#!/usr/bin/env python3
"""Reject a review/re-check whose criterion x mechanism matrix is incomplete.

A reviewer that stops at the first instance of a mechanism leaves siblings for the next round. The
REVIEW_BRIEF (v6+) requires a matrix: one row per criterion in the package's rubric (plus `_task`),
one column per mechanism M1..M6, every cell `clean` or `finding: ...`. This check compares the
matrix against the actual rubric and fails on any missing row, missing column, or empty cell.

Run: review_matrix_check.py --package <task_dir> --review <task>_EXPERT_RECHECK.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from reward_signal_gate import load_criteria, resolve_package_dir  # noqa: E402

MECHS = ["M1", "M2", "M3", "M4", "M5", "M6"]


def check(package: Path, review: Path) -> dict:
    pkg = resolve_package_dir(package) or package
    crits, _ = load_criteria(pkg)
    names = [c["name"] for c in crits]
    try:
        r = json.loads(review.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "fail", "evidence": [f"review unreadable: {exc}"]}
    m = r.get("matrix")
    if not isinstance(m, dict):
        return {"status": "fail", "evidence": ["no `matrix` in review — reviewer did not do the exhaustive pass"]}
    ev = []
    missing_rows = [n for n in names + ["_task"] if n not in m]
    if missing_rows:
        ev.append(f"missing rows: {missing_rows[:12]}{' …' if len(missing_rows) > 12 else ''}")
    for row, cells in m.items():
        if not isinstance(cells, dict):
            ev.append(f"{row}: not a dict")
            continue
        for k in MECHS:
            v = str(cells.get(k, "")).strip()
            if not v:
                ev.append(f"{row}.{k}: empty")
            elif not (v.lower() == "clean" or v.lower().startswith("finding")):
                ev.append(f"{row}.{k}: must be 'clean' or 'finding: …' (got {v[:40]!r})")
    extra = [row for row in m if row != "_task" and row not in names]
    if extra:
        ev.append(f"rows not in rubric (stale names?): {extra[:8]}")
    n_find = sum(1 for cells in m.values() if isinstance(cells, dict) for v in cells.values() if str(v).lower().startswith("finding"))
    return {"status": "fail" if ev else "pass", "evidence": ev or [f"{len(names)} criteria × {len(MECHS)} mechanisms complete; {n_find} finding cells"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--review", type=Path, required=True)
    a = ap.parse_args(argv)
    r = check(a.package, a.review)
    print(r["status"], *r["evidence"], sep="\n  ")
    return 1 if r["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
