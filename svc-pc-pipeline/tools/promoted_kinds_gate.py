#!/usr/bin/env python3
"""
promoted_kinds_gate.py - C1 refinement (laptop, 18:55Z 2026-09-19). Read-only CLI over a single
task's checks/*.csv, its newest available recheck summary (checks/recheck/summary.csv, an archived
checks/recheck.expired-*/, /root/qc/_recheck/<task>/, or the newest
review_workspace*/*/prior_verifications/) and the scan CSVs, applying promoted_kinds.py's kind-level
detectors. Prints one line per finding (every promoted kind, including the ones excluded from the
blocking set - marked EXCLUDED - for full transparency) and exits 5 if any BLOCKING-SAFE kind
fired, 0 otherwise. Coordinator accepted this gate for the 22 dataos-fresh tasks (18:55Z result,
12/12) and wired it into stage_and_zip.sh, restricted to those 22 (2026-09-19 19:15Z).

Status as of the 19:15Z precision follow-ups: SVC-PC-2-7-0 (the one DataOS-accepted control) is
still clean. The 12-task acceptance set (mapping-96.csv confidence=exact on a listed cell/scan) is
now **10/12**, not 12/12: removing `judge_scope_under_inclusion` from the blocking-safe set (2/10
true positive on a 10-task precision sample, below the coordinator's 8/10 bar) left
SVC-PC-82-1-0 and SVC-PC-9-5-0 with no blocking-safe signal - both are among the 22 the gate is
wired for. See promoted_kinds.py's module docstring for this and the 3 earlier exclusions (kinds
that empirically fire on SVC-PC-2-7-0 despite Fable's README describing them as safe separators),
and fixes-1720-report.md's C1 19:15Z section for the full detail. Not silently patched to force
12/12 - reported for the coordinator's own call on these 2 tasks.

Usage:
    python3 promoted_kinds_gate.py --task SVC-PC-6-2-0
Exit codes: 0 = clean, 5 = at least one blocking-safe promoted kind fired, 1 = usage/other error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import promoted_kinds as PK


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True)
    args = ap.parse_args()

    findings = PK.promoted_findings(args.task)
    blocking = [f for f in findings if f["promoted_kind"] in PK.BLOCKING_SAFE_KIND_NAMES]
    excluded = [f for f in findings if f["promoted_kind"] not in PK.BLOCKING_SAFE_KIND_NAMES]

    for f in blocking:
        print(f"BLOCKING  {args.task}  {f['promoted_kind']}  {f['detail']}")
    for f in excluded:
        print(f"EXCLUDED  {args.task}  {f['promoted_kind']}  {f['detail']}  (empirically fires on SVC-PC-2-7-0; see promoted_kinds.py docstring)")

    if not findings:
        print(f"CLEAN  {args.task}  no promoted kind fired")

    print(f"# {args.task}: {len(blocking)} blocking-safe finding(s), {len(excluded)} excluded finding(s)", file=sys.stderr)
    return 5 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
