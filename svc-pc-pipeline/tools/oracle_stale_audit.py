#!/usr/bin/env python3
"""For every task on lanes/ZIP_ONLY_LIST: is probes/oracle.json older than the task's newest shipped byte (so its reward was
never computed on these bytes), and did bytes change after the zip was built. Read-only. Written 2026-09-20 00:37Z after 21-2-0
was BLOCKED on an 18:54Z probe following a 00:17Z golden edit."""

import json
import os
import sys
import time

sys.path.insert(0, "/root/qc/_prompts/verify/dataos-old")
import task_fingerprint as tf  # noqa: E402

LIST = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/lanes/ZIP_ONLY_LIST"
tasks = [l.strip() for l in open(LIST) if l.strip()]


def ts(x):
    return time.strftime("%m-%d %H:%M:%S", time.gmtime(x)) if x else "-"


print(f"{'task':14} {'oracle.json':>15} {'newest byte':>15} {'zip':>15}  verdict")
stale = 0
for t in tasks:
    p = f"/root/qc/stream-pipe/{t}/probes/oracle.json"
    z = f"/root/qc/out/pipe/{t}.zip"
    om = os.path.getmtime(p) if os.path.exists(p) else None
    nb = tf.newest_mtime(t)
    zm = os.path.getmtime(z) if os.path.exists(z) else None
    try:
        rew = json.load(open(p)).get("total_reward")
    except Exception:
        rew = None
    if om is None:
        v = "NO PROBE"
    elif nb > om:
        v = f"STALE: bytes newer than probe by {int((nb - om) / 60)} min (probe reward {rew})"
        stale += 1
    else:
        v = f"fresh (reward {rew})"
    if zm and nb > zm:
        v += " | BYTES CHANGED AFTER ZIP"
    print(f"{t:14} {ts(om):>15} {ts(nb):>15} {ts(zm):>15}  {v}")
print(f"stale probes: {stale} of {len(tasks)}")
