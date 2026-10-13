#!/usr/bin/env python3
"""gate_groups_fire.py TASK [TASK...]  (or --all-zip-list)
BLOCK any task whose rubric has more deliverable groups than the oracle actually scored. A dropped group means its criteria never
run, so the oracle's 1.0 is on a partial rubric and a whole class of checks (often source-fidelity) silently passes. This is the
defect that shipped 82-1-0 (3 groups, 1 scored) and 38-1-0/17-2-0 after the schema-size split created group folders that did not
all fire. Root cause varies (test.sh glob, reward.toml, or rewardkit discovery); the symptom is the gate: scored < authored.
Exit 2 if any task has a dropped group, else 0. Read-only.
"""

from __future__ import annotations

import glob
import json
import os
import sys

CORPUS = "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
PIPE = "/root/qc/stream-pipe"


def check(task: str):
    td = f"{CORPUS}/{task}"
    authored = sorted(
        os.path.basename(os.path.dirname(p))
        for p in glob.glob(f"{td}/tests/deliverables*/judge.toml")
    )
    orc = f"{PIPE}/{task}/probes/oracle.json"
    if not os.path.exists(orc):
        return task, len(authored), None, authored, [], "no oracle.json"
    try:
        o = json.load(open(orc))
    except Exception as e:  # noqa: BLE001
        return task, len(authored), None, authored, [], f"oracle unreadable: {e}"
    scored = sorted(g.get("name", "?") for g in o.get("groups", []))
    dropped = [g for g in authored if g not in scored]
    return task, len(authored), len(scored), authored, dropped, ""


def main():
    args = sys.argv[1:]
    if "--all-zip-list" in args:
        tasks = [l.strip() for l in open("/root/qc/lanes/ZIP_ONLY_LIST") if l.strip()]
    else:
        tasks = [a if a.startswith("SVC-PC-") else f"SVC-PC-{a}" for a in args]
    bad = 0
    print(f"{'task':16} {'authored':>8} {'scored':>6}  verdict")
    for t in tasks:
        task, na, ns, authored, dropped, err = check(t)
        if err and ns is None and "no oracle" in err:
            print(f"{task:16} {na:>8} {'-':>6}  SKIP ({err})")
            continue
        if dropped:
            bad += 1
            print(f"{task:16} {na:>8} {ns:>6}  *** BLOCK: dropped {dropped} ***")
        else:
            print(f"{task:16} {na:>8} {ns:>6}  ok")
    sys.exit(2 if bad else 0)


if __name__ == "__main__":
    main()
