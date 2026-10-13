#!/usr/bin/env python3
"""archive_shadowed_rounds.py - put fresh reviewer verdicts back in front of stale higher-round ones.

zip_when_ready.sh, the actuator and the guard all take the HIGHEST round number per reviewer as the latest verdict. A task that went through two
fix rounds keeps CR.<r>.round2.json on disk; when the dispatcher later runs another fix cycle for it (a guard re-open that predates
_archive_high_rounds, a priority-loop pass), the new re-reviews land as round 1 and the old round-2 files, written for older bytes, still outrank
them. The guard then reports review_missing_after_change and the zip step never takes the task (38-6-0, 2026-09-19: fix 09:34:43, fresh round-1
pair 09:43 and 09:55 with 0 majors each, old round-2 pair 06:58 and 07:09).

  archive_shadowed_rounds.py scan            list every task where this applies (read-only)
  archive_shadowed_rounds.py apply TASK ...  rename the stale files aside, the same way guard_rt.py's _archive_high_rounds does

Per reviewer, a file CR.<r>.round<N>.json is archived only when ALL of these hold: it is older than the task's newest shipped file (it describes
older bytes); a canonical verdict for the same reviewer at a LOWER round is at least as new as that newest shipped file (it describes the current
bytes); and no review of that task and reviewer is running. The file becomes CR.<r>.round<N>.pre-reopen-<stamp>.json, which no reader matches.
Nothing is deleted and no verdict is edited.
"""

import glob
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, "/root/qc/tools")
import oracle_refresh as orf  # noqa: E402  (newest_staged)

SP = "/root/qc/stream-pipe"
TOL = 5


def canon(p):
    import json

    try:
        d = json.load(open(p))
    except Exception:
        return False
    return (
        isinstance(d, dict)
        and "overall_verdict" in d
        and isinstance(d.get("checks"), list)
    )


def live(task, reviewer):
    ps = subprocess.run(
        ["ps", "-eo", "args", "--no-headers"], capture_output=True, text=True
    ).stdout
    return (
        re.search(
            rf"run_workspace_review\.py --task {task} .*--reviewer {reviewer}\b", ps
        )
        is not None
    )


def plan(task):
    """[(file, reason)] to archive for this task."""
    newest, rel = orf.newest_staged(task)
    out = []
    for r in ("glm", "sonnet"):
        files = {}
        for p in glob.glob(f"{SP}/{task}/CR.{r}.round*.json"):
            m = re.fullmatch(rf"CR\.{r}\.round(\d+)\.json", os.path.basename(p))
            if m:
                files[int(m.group(1))] = p
        for n in sorted(files):
            p = files[n]
            if os.path.getmtime(p) + TOL >= newest:
                continue  # not stale
            fresh_lower = [
                files[k]
                for k in files
                if k < n
                and os.path.getmtime(files[k]) + TOL >= newest
                and canon(files[k])
            ]
            if not fresh_lower:
                continue
            if live(task, r):
                continue
            out.append(
                (
                    p,
                    f"round{n} written {time.strftime('%H:%M:%S', time.gmtime(os.path.getmtime(p)))} is older than {rel} "
                    f"({time.strftime('%H:%M:%S', time.gmtime(newest))}); fresh canonical round"
                    f"{[k for k in files if files[k] in fresh_lower]} exists",
                )
            )
    return out


mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
if mode == "scan":
    n = 0
    for d in sorted(glob.glob(f"{SP}/SVC-PC-*")):
        t = os.path.basename(d)
        if not re.fullmatch(r"SVC-PC-\d+-\d+-\d+", t):
            continue
        for p, why in plan(t):
            n += 1
            print(f"{t} {os.path.basename(p)}: {why}")
    print(f"{n} stale higher-round file(s) shadow a fresh lower-round verdict")
elif mode == "apply":
    stamp = int(time.time())
    for t in sys.argv[2:]:
        t = t if t.startswith("SVC-PC-") else f"SVC-PC-{t}"
        before = sorted(
            os.path.basename(x)
            for x in glob.glob(f"{SP}/{t}/CR.*.round*.json")
            if re.search(r"round\d+\.json$", x)
        )
        for p, why in plan(t):
            dst = f"{p[:-5]}.pre-reopen-{stamp}.json"
            os.replace(p, dst)
            print(f"{t}: {os.path.basename(p)} -> {os.path.basename(dst)}  ({why})")
        after = sorted(
            os.path.basename(x)
            for x in glob.glob(f"{SP}/{t}/CR.*.round*.json")
            if re.search(r"round\d+\.json$", x)
        )
        print(f"{t}: latest-candidate files before {before}")
        print(f"{t}: latest-candidate files after  {after}")
else:
    sys.exit("usage: archive_shadowed_rounds.py scan | apply TASK ...")
