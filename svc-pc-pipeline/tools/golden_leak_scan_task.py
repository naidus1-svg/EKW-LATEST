#!/usr/bin/env python3
"""golden_leak_scan_task.py - single-task wrapper around golden_leak_scan.py's own
scan() (canon check 1.6, answer-exposure/solver-isolation - "block leaks no graded
value (re-run 1.6 after any instruction edit)"). golden_leak_scan.py itself always
scans the full 202-task corpus (no --task filter, ~2+ minutes measured) and is
shared/owned tooling, not to be edited; this wrapper imports its scan()/extract()
functions directly (sys.argv neutralized during import so its own top-level
`a = ap.parse_args()` doesn't choke on THIS script's argv) and calls scan() for
exactly one task directory, so "run the answer-key leak scan on every change" is
affordable to do after every single-task fix-plan edit instead of paying a full
corpus sweep each time.

Usage: python3 golden_leak_scan_task.py --task TASK --corpus-root PATH [--threshold 0.25]
Exit 0 and prints the task's own row always; exit 1 additionally if
top_coverage >= threshold, so a caller can gate on the exit code.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def load_golden_leak_scan():
    saved_argv = sys.argv
    sys.argv = ["golden_leak_scan.py"]  # neutralize its own top-level ap.parse_args()
    try:
        spec = importlib.util.spec_from_file_location(
            "golden_leak_scan", str(Path(__file__).resolve().parent / "golden_leak_scan.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.argv = saved_argv


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--corpus-root", required=True)
    ap.add_argument("--threshold", type=float, default=0.25)
    args = ap.parse_args()

    gls = load_golden_leak_scan()
    td = str(Path(args.corpus_root) / args.task)
    tid, golden_shingles, top_file, top_coverage, second_file, second_coverage, env_files = gls.scan(td)

    print(f"{tid}: golden_shingles={golden_shingles} top_file={top_file!r} top_coverage={top_coverage} "
          f"second_file={second_file!r} second_coverage={second_coverage} env_files={env_files}")

    if top_coverage >= args.threshold:
        print(f"FLAGGED: {tid} top_file={top_file!r} covers {top_coverage:.1%} of the golden's shingles "
              f"(threshold {args.threshold:.0%})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
