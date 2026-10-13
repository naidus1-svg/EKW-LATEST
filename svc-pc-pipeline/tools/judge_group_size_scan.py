#!/usr/bin/env python3
"""
judge_group_size_scan.py - C1 refinement (laptop, 18:55Z 2026-09-19): a judge group whose
criteria count exceeds a safe threshold crashes rewardkit's default batched judge schema (one
required property per criterion compiled into a single strict schema). Confirmed on 2 tasks in
the DataOS batch: SVC-PC-26-4-0 (44 criteria, 1 group) and SVC-PC-26-8-0 (29 criteria, 1 group) -
"the same 400 invalid_request_error on every run with distinct request ids... no shipped
evaluation, including the Oracle, was graded and no reward is trustworthy" (severity-addendum-v2.md
check 1.8) - 9 DataOS majors between the two tasks (both entire tasks unscoreable).

N=24: the largest group size that ran cleanly across the 23-task batch DataOS actually processed
(22 dataos-fresh + SVC-PC-2-7-0, excluding the 2 that crashed) - SVC-PC-92-4-0's single group, 24
criteria. The smallest observed crash was 29 (26-8-0). 25-28 is an untested gap between the two;
N=24 is the defensible, empirically-grounded safe threshold, not a guess.

READ-ONLY: only reads corpus judge.toml files, never modifies them.

Output: CSV [task, judge_toml, n_criteria, mode]
Verdict: fail if any group in the task exceeds N, else pass.

Usage:
    python3 judge_group_size_scan.py [--corpus-root PATH] [--out PATH] [--task NAME] [--verdict-out PATH] [--max-criteria N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_CORPUS_ROOT, DEFAULT_REPORTS_DIR, iter_deliverable_groups, list_tasks, write_csv

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

DEFAULT_MAX_CRITERIA = 24


def scan_task(task_dir: Path, max_criteria: int) -> list[tuple[str, str, int, str]]:
    rows: list[tuple[str, str, int, str]] = []
    for group_dir in iter_deliverable_groups(task_dir):
        jt = group_dir / "judge.toml"
        if not jt.is_file():
            continue
        try:
            d = tomllib.load(open(jt, "rb"))
        except Exception:
            continue
        n = len(d.get("criterion", []) or [])
        if n > max_criteria:
            mode = (d.get("judge") or {}).get("mode", "") if isinstance(d.get("judge"), dict) else ""
            rows.append((task_dir.name, str(jt.relative_to(task_dir)), n, str(mode)))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "judge_group_size.csv")
    ap.add_argument("--task", type=str, default=None)
    ap.add_argument("--verdict-out", type=Path, default=None)
    ap.add_argument("--max-criteria", type=int, default=DEFAULT_MAX_CRITERIA)
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple[str, str, int, str]] = []
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        try:
            all_rows.extend(scan_task(task_dir, args.max_criteria))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 25 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned", file=sys.stderr)

    n = write_csv(args.out, ["task", "judge_toml", "n_criteria", "mode"], all_rows)
    flagged_tasks = {r[0] for r in all_rows}
    print(f"judge_group_size_scan: {n} oversized group(s) (>{args.max_criteria} criteria) across {len(tasks)} tasks, written to {args.out}")
    print(f"  {len(flagged_tasks)} tasks flagged")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = sorted((t.name, "fail" if t.name in flagged_tasks else "pass") for t in tasks)
        vn = write_csv(args.verdict_out, ["task_id", "judge_group_size_scan"], verdict_rows)
        print(f"judge_group_size_scan: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
