#!/usr/bin/env python3
"""unpark_more_rounds.py - give tasks parked with 'majors still present after N fix
rounds' the extra rounds allowed by /root/qc/lanes/MAX_ROUNDS, without re-spending
the rounds already done.

For each such task: seed the checkpoint files and STATE markers the new gate_task.sh
expects (CR.round0..N.json, FIX_ROUND_k, CR_ROUND_k), drop CR_AND_FIX and PARKED.md,
and append the task to stream-pipe/QUEUE.txt so the running launcher picks it up.
Idempotent. Prints what it did. Used by hand and by watchdog.sh.
"""

import json, re, shutil, sys
from pathlib import Path

PIPE = Path("/root/qc/stream-pipe")
maxr = int(
    re.sub(
        r"\D",
        "",
        (
            Path("/root/qc/lanes/MAX_ROUNDS").read_text()
            if Path("/root/qc/lanes/MAX_ROUNDS").exists()
            else "4"
        ),
    )
    or 4
)
queue = PIPE / "QUEUE.txt"
queued = set(queue.read_text().split()) if queue.exists() else set()
done = []
for pk in sorted(PIPE.glob("SVC-PC-*/PARKED.md")):
    d = pk.parent
    t = d.name
    m = re.search(r"majors still present after (\d+) fix rounds", pk.read_text())
    if not m:
        continue
    n = int(m.group(1))
    if n >= maxr:
        continue
    cr = d / "CR.json"
    if not cr.exists():
        continue
    try:
        json.load(open(cr))
    except Exception:
        continue
    # seed checkpoints: CR.round{k}.json for k<n comes from CR.round{k+1}.before-fix.json; round n is CR.json
    state = set((d / "STATE").read_text().split()) if (d / "STATE").exists() else set()
    for k in range(0, n):
        src = d / f"CR.round{k+1}.before-fix.json"
        dst = d / f"CR.round{k}.json"
        if not dst.exists() and src.exists():
            shutil.copy(src, dst)
        state.add(f"CR_ROUND_{k}")
    if not (d / f"CR.round{n}.json").exists():
        shutil.copy(cr, d / f"CR.round{n}.json")
    state.add(f"CR_ROUND_{n}")
    for k in range(1, n + 1):
        if (d / f"PLAN.round{k}.json").exists():
            state.add(f"FIX_ROUND_{k}")
    state.discard("CR_AND_FIX")
    state.discard("DONE")
    keep = [s for s in ["CLAIM", "MECHANICAL"] if s in state] + sorted(
        s for s in state if s not in ("CLAIM", "MECHANICAL")
    )
    (d / "STATE").write_text("\n".join(keep) + "\n")
    pk.rename(d / f"PARKED.after{n}.md")
    # always append: the launcher reads QUEUE.txt sequentially and has passed this task's
    # first line; a repeat line is harmless (DONE/PARKED exit at once, running -> SKIP)
    with open(queue, "a") as f:
        f.write(t)
        f.write(chr(10))
    done.append(f"{t}(after {n}, now up to {maxr})")
print(
    f"unparked {len(done)} tasks for extra rounds: {' '.join(done)}"
    if done
    else "nothing to unpark"
)
