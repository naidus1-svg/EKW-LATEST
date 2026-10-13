#!/usr/bin/env python3
"""task_order.py - HANDOFF.md section 3 batch order: "main's 14 returned
tasks, then the 47 built zips, then the rest."

Tier 1: the 14 of batch-1's 15 tasks that already have a DataOS verdict.
Batch-1 (15) = SUBMITTED.txt minus SVC-PC-54-2-0 (batch 3, the one task
already through the manual gate-v2 build). "14 of 15 have verdicts, only
5-3-0 is out" (GATE-V2.md 1c) - so tier 1 = batch-1 minus SVC-PC-5-3-0.

Tier 2: every task with an existing zip under /root/qc/out/ (built before
gate v2, per HANDOFF.md section 1: "61 zips in out/ ... need re-gate"),
minus tier 1 and minus SVC-PC-54-2-0 (already gate-v2'd, done, left out of
the pipe queue entirely).

Tier 3: every remaining SVC-PC-* task in the corpus.

Read-only. Prints one task id per line, in order, to stdout (or --out).

Usage:
    python3 task_order.py [--corpus-root PATH] [--submitted PATH]
        [--out-root PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

DEFAULT_CORPUS_ROOT = Path("/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready")
DEFAULT_SUBMITTED = Path("/root/qc/SUBMITTED.txt")
DEFAULT_OUT_ROOT = Path("/root/qc/out")
ALREADY_DONE = {"SVC-PC-54-2-0"}  # already through the manual gate-v2 build; not re-queued


def normalize_task_id(name: str) -> str | None:
    m = re.search(r"(SVC-PC-)?(\d+-\d+-\d+)$", name)
    if not m:
        return None
    return "SVC-PC-" + m.group(2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--submitted", type=Path, default=DEFAULT_SUBMITTED)
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    submitted = [l.strip() for l in args.submitted.read_text().splitlines() if l.strip()]
    tier1 = [t for t in submitted if t not in ALREADY_DONE and t != "SVC-PC-5-3-0"]
    tier1_set = set(tier1)

    zip_ids = set()
    for zp in args.out_root.rglob("*.zip"):
        tid = normalize_task_id(zp.stem)
        if tid:
            zip_ids.add(tid)
    tier2 = sorted(zip_ids - tier1_set - ALREADY_DONE)

    all_tasks = {p.name for p in args.corpus_root.iterdir() if p.is_dir() and p.name.startswith("SVC-PC-")}
    tier3 = sorted(all_tasks - tier1_set - set(tier2) - ALREADY_DONE)

    queue = tier1 + tier2 + tier3

    out_text = "\n".join(queue) + "\n"
    if args.out:
        args.out.write_text(out_text)
    else:
        print(out_text, end="")

    import sys
    sys.stderr.write(
        f"tier1(main's 14 returned)={len(tier1)} tier2(built zips)={len(tier2)} "
        f"tier3(rest)={len(tier3)} total={len(queue)}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
