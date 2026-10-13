#!/usr/bin/env python3
"""seed_checkpoints.py - before or after a VM stop, give every stream-pipe task that ran on the
pre-checkpoint gate_task.sh the STATE markers the checkpointed script expects, from the files and
pipeline.log lines it left behind, so a re-run re-spends no finished model call.

Evidence used (all written by the old script):
  CR.json                       round-0 review, until a re-check overwrites it
  CR.round{N}.before-fix.json   copy of the review that fix round N acted on (= review of round N-1)
  PLAN.round{N}.json            fix plan N
  pipeline.log "apply_plan.py round N exit="   fix N applied and scans re-run
  pipeline.log "blind CR (round N, re-check after fix)" followed by a later step line  re-check N done

Idempotent, prints one line per task it touched. Run with --dry-run first.
"""

import glob, json, os, re, sys

PIPE = "/root/qc/stream-pipe"
dry = "--dry-run" in sys.argv


def ok(p):
    try:
        json.load(open(p))
        return True
    except Exception:
        return False


n = 0
for d in sorted(glob.glob(f"{PIPE}/SVC-PC-*")):
    st = f"{d}/STATE"
    if not os.path.exists(st):
        continue
    state = set(open(st).read().split())
    if (
        any(s.startswith("CR_ROUND") for s in state)
        or "CR_AND_FIX" in state
        or "DONE" in state
    ):
        continue
    log = (
        open(f"{d}/pipeline.log", errors="replace").read()
        if os.path.exists(f"{d}/pipeline.log")
        else ""
    )
    added = []
    # round 0 review: the earliest before-fix copy, else CR.json if no fix round ever started
    bf = sorted(glob.glob(f"{d}/CR.round*.before-fix.json"))
    r0 = None
    if bf and ok(bf[0]):
        r0 = bf[0]
    elif (
        os.path.exists(f"{d}/CR.json")
        and ok(f"{d}/CR.json")
        and "fix round 1" not in log
    ):
        r0 = f"{d}/CR.json"
    if not r0:
        continue
    if not os.path.exists(f"{d}/CR.round0.json"):
        if not dry:
            os.system(f"cp '{r0}' '{d}/CR.round0.json'")
    added.append("CR_ROUND_0")
    # fix rounds and re-checks
    k = 1
    while True:
        plan = f"{d}/PLAN.round{k}.json"
        if not (os.path.exists(plan) and ok(plan)):
            break
        if f"apply_plan.py round {k} exit=" in log:
            added.append(f"FIX_ROUND_{k}")
        else:
            break
        # re-check k done if a later step line follows it
        m = re.search(rf"blind CR \(round {k}, re-check after fix\)(.*)", log, re.S)
        later = m and re.search(
            r"fix round \d|steps 3-4|step 5|PARKED|step 4\.5", m.group(1)
        )
        nxt_bf = f"{d}/CR.round{k+1}.before-fix.json"
        src = (
            nxt_bf
            if os.path.exists(nxt_bf) and ok(nxt_bf)
            else (f"{d}/CR.json" if later and ok(f"{d}/CR.json") else None)
        )
        if src:
            if not os.path.exists(f"{d}/CR.round{k}.json") and not dry:
                os.system(f"cp '{src}' '{d}/CR.round{k}.json'")
            added.append(f"CR_ROUND_{k}")
        else:
            break
        k += 1
    if not dry:
        keep = [s for s in ("CLAIM", "MECHANICAL") if s in state] + sorted(
            set(added) | {s for s in state if s not in ("CLAIM", "MECHANICAL")}
        )
        open(st, "w").write("\n".join(keep) + "\n")
    n += 1
    print(os.path.basename(d), "+", " ".join(added))
print(("would seed" if dry else "seeded"), n, "tasks")
