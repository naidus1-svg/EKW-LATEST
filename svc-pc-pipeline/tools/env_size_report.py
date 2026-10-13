#!/usr/bin/env python3
"""
env_size_report.py - GATE-V2 class G: per-task environment/ size.

For each task under the corpus root, sums the bytes of everything under
<task>/environment/ and flags any task over 10 MB (10,485,760 bytes exactly,
per GATE-V2 3.3: "Until answered, ship nothing over 10 MB").

READ-ONLY: only stats and reads file sizes, never modifies the corpus.

Output: CSV with columns [task, bytes, MB, over_10mb], sorted by bytes desc.

Known (GATE-V2 section 1, class G): SVC-PC-12-8-0 ~11.8MB, SVC-PC-70-6-0
~13.1MB, SVC-PC-72-4-0 ~23.4MB, SVC-PC-24-7-0 ~24.8MB.

Usage:
    python3 env_size_report.py [--corpus-root PATH] [--out PATH] [--threshold-bytes N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_CORPUS_ROOT, DEFAULT_REPORTS_DIR, list_tasks, write_csv

THRESHOLD_BYTES = 10_485_760  # 10 MB, per GATE-V2 3.3
VERDICT_THRESHOLD_BYTES = 10_000_000  # summary.csv verdict column: fail if >10,000,000 bytes


def dir_size_bytes(root: Path) -> int:
    total = 0
    if not root.is_dir():
        return 0
    for p in root.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT, help="corpus root directory")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "env_size.csv", help="output CSV path")
    ap.add_argument("--threshold-bytes", type=int, default=THRESHOLD_BYTES, help="over-limit threshold in bytes")
    ap.add_argument("--verdict-out", type=Path, default=None, help="write task_id,env_size_report pass|warn|fail summary CSV")
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if not tasks:
        print(f"ERROR: no SVC-PC-* task directories found under {args.corpus_root}", file=sys.stderr)
        return 1

    rows = []
    for task_dir in tasks:
        env_dir = task_dir / "environment"
        size = dir_size_bytes(env_dir)
        mb = round(size / (1024 * 1024), 2)
        over = size > args.threshold_bytes
        rows.append((task_dir.name, size, mb, over))

    rows.sort(key=lambda r: r[1], reverse=True)
    n = write_csv(args.out, ["task", "bytes", "MB", "over_10mb"], rows)

    over_count = sum(1 for r in rows if r[3])
    print(f"env_size_report: {n} tasks scanned, {over_count} over 10 MB, written to {args.out}")
    if over_count:
        print("Over-limit tasks:")
        for r in rows:
            if r[3]:
                print(f"  {r[0]}: {r[2]} MB")

    if args.verdict_out:
        verdict_rows = sorted(
            (name, "fail" if size > VERDICT_THRESHOLD_BYTES else "pass") for name, size, mb, over in rows
        )
        vn = write_csv(args.verdict_out, ["task_id", "env_size_report"], verdict_rows)
        print(f"env_size_report: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
