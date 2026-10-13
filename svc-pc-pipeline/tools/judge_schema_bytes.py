#!/usr/bin/env python3
"""judge_schema_bytes.py TASKDIR [TASKDIR...] [--block 4000] [--warn 3500]
Compile every judge group's strict response schema with rewardkit's OWN builder (rewardkit.judges._build_response_schema) and
print its byte size. Why (2026-09-20 01:05Z): DataOS's oracle run on SVC-PC-38-1-0 failed in rewardkit with Anthropic's
"The compiled grammar is too large" on group deliverables_03, which has exactly 24 criteria, the count judge_group_size_scan.py
treats as safe. The limit is on the compiled grammar's size, so the check has to measure bytes, not count criteria. Calibration
points: SVC-PC-26-4-0's 44-criterion group compiled to 8,977 bytes and failed; a live probe passed at 22 criteria (about 4.5 KB)
and failed at 26. Exit 2 when any group is at or over --block, 1 when any is at or over --warn, else 0. Read-only.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import tomllib

try:
    import rewardkit.judges as J
    from rewardkit.models import Criterion  # type: ignore
except Exception as e:  # noqa: BLE001
    print(f"rewardkit not importable: {e}")
    sys.exit(3)


def load_criteria(path: str) -> list:
    d = tomllib.load(open(path, "rb"))
    raw = d.get("criterion") or d.get("criteria") or []
    out = []
    for c in raw:
        kw = {
            k: v for k, v in c.items() if k in ("name", "description", "type", "weight")
        }
        try:
            out.append(Criterion(**kw))
        except Exception:  # noqa: BLE001
            # fall back to the fields the schema builder actually reads
            class _C:  # minimal stand-in with the attributes _criterion_entry_schema uses
                pass

            o = _C()
            for k, v in c.items():
                setattr(o, k, v)
            out.append(o)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("taskdirs", nargs="+")
    ap.add_argument("--block", type=int, default=4000)
    ap.add_argument("--warn", type=int, default=3500)
    a = ap.parse_args()
    worst = 0
    print(f"{'task':14} {'group':18} {'criteria':>8} {'schema bytes':>12}  verdict")
    for td in a.taskdirs:
        task = os.path.basename(td.rstrip("/"))
        for jt in sorted(glob.glob(os.path.join(td, "tests", "*", "judge.toml"))):
            group = os.path.basename(os.path.dirname(jt))
            crit = load_criteria(jt)
            try:
                schema = J._build_response_schema(crit)
                size = len(json.dumps(schema, separators=(",", ":")))
            except Exception as e:  # noqa: BLE001
                print(f"{task:14} {group:18} {len(crit):>8} {'ERR':>12}  {e}")
                worst = max(worst, 2)
                continue
            v = "BLOCK" if size >= a.block else ("warn" if size >= a.warn else "ok")
            worst = max(worst, 2 if v == "BLOCK" else (1 if v == "warn" else 0))
            print(f"{task:14} {group:18} {len(crit):>8} {size:>12}  {v}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
