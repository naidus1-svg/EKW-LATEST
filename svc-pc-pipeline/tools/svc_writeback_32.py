#!/usr/bin/env python3
"""Write edited staging files back to Drive, one at a time, with a full audit trail.

Deliberately not named `_scratch_*`: an agent sweeping the scratch namespace deleted the
first copy of this script mid-batch, which is also why concurrent agents should namespace
their throwaways by task id.

Conservative by design, because this writes to expert-authored customer artifacts:

  * Only files whose md5 actually DIFFERS from the fetch baseline are written. Writing
    identical bytes to a shared artifact is churn in someone's revision history.
  * Every write goes through `drive.py put`, which probes canEdit, snapshots current
    content to ~/.claude/drive-snapshots/, PATCHes, then reads back and diffs.
  * HALTS on first failure. On 08-29 two files reached Drive broken and the record showed
    the first write's fingerprint rather than the live one.
  * 9-2-0 and 10-3-0 are asserted absent by id before anything is sent.

Usage:
    python tools/svc_writeback_32.py --dry-run
    python tools/svc_writeback_32.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("C:/b/_fetched_all32")
DRIVE = Path.home() / ".claude" / "drive.py"
EXCLUDED = {"SVC-PC-9-2-0", "SVC-PC-10-3-0"}


def md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    baseline = json.loads((ROOT / "_fetch_baseline.json").read_text(encoding="utf-8"))

    write_set, missing = [], []
    for task, files in sorted(baseline.items()):
        if task in EXCLUDED:
            continue
        for rel, meta in files.items():
            p = ROOT / task / rel
            if not p.exists():
                missing.append(f"{task} :: {rel}")
                continue
            cur = md5(p)
            if cur != meta["md5"]:
                write_set.append(
                    {
                        "task": task,
                        "rel": rel,
                        "path": str(p),
                        "id": meta["id"],
                        "md5_before": meta["md5"],
                        "md5_after": cur,
                        "bytes_before": meta["bytes"],
                        "bytes_after": p.stat().st_size,
                    }
                )

    if any(w["task"] in EXCLUDED for w in write_set):
        sys.exit("ABORT: an excluded task reached the write set")

    print(
        f"WRITE SET: {len(write_set)} files across "
        f"{len({w['task'] for w in write_set})} tasks"
    )
    for w in write_set:
        print(
            f"  {w['task']:<16} {w['rel'][:56]:<56} "
            f"{w['bytes_before']:>7} -> {w['bytes_after']:>7}"
        )
    if missing:
        print(f"\nnot found locally, skipped ({len(missing)}):")
        for m in missing:
            print(f"  {m}")
    print(f"\nexclusions asserted absent: {sorted(EXCLUDED)}")

    if args.dry_run:
        print("\n--dry-run, nothing sent")
        return 0

    results = []
    for w in write_set:
        r = subprocess.run(
            [sys.executable, str(DRIVE), "put", w["id"], w["path"]],
            capture_output=True,
            text=True,
            timeout=600,
        )
        ok = r.returncode == 0
        results.append(
            {
                **{k: v for k, v in w.items() if k != "path"},
                "put_exit": r.returncode,
                "put_tail": (r.stdout or r.stderr)[-400:],
            }
        )
        print(f"{'OK  ' if ok else 'FAIL'} {w['task']:<16} {w['rel'][:50]}")
        if not ok:
            print((r.stdout or "")[-1200:])
            print((r.stderr or "")[-1200:])
            print(
                "\nHALTED on first failure. Files written before this point are listed "
                "above and are restorable from ~/.claude/drive-snapshots/."
            )
            break

    out = ROOT / "_writeback_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n{sum(1 for r in results if r['put_exit'] == 0)}/{len(write_set)} written")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
