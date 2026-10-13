#!/usr/bin/env python3
"""pipe_stages.py - where every one of the 202 tasks stands, in one table.

Stage per task (highest reached):
  untouched | mechanical | CR round N | fix round N | probes | parked | done
plus: majors left in the latest CR.json, GLM runs valid against the CURRENT
instruction hash (0/1/2), zip present, minutes since last log line, running now.
Run:  python3 /root/qc/tools/pipe_stages.py            (summary + parked + stale)
      python3 /root/qc/tools/pipe_stages.py --all      (every task)
"""

import hashlib, json, os, re, subprocess, sys, time
from pathlib import Path

QC = Path("/root/qc")
PIPE = QC / "stream-pipe"
RUNS = QC / "runs"
CORPUS = Path("/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready")
queue = (
    [l.strip() for l in (PIPE / "QUEUE.txt").read_text().splitlines() if l.strip()]
    if (PIPE / "QUEUE.txt").exists()
    else []
)
if not queue:
    queue = sorted(p.name for p in CORPUS.iterdir() if p.name.startswith("SVC-PC-"))
running = set()
try:
    out = subprocess.run(
        ["pgrep", "-fa", "bash /root/qc/tools/gate_task.sh"],
        capture_output=True,
        text=True,
    ).stdout
    running = {l.split()[-1] for l in out.splitlines() if l.strip()}
except Exception:
    pass


def instr_sha(task):
    p = CORPUS / task / "instruction.md"
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def glm_valid(task):
    sha = instr_sha(task)
    n = 0
    for k in ("glm-1", "glm-2"):
        d = RUNS / task / k
        ec = d / "claude_exit_code.txt"
        sh = d / "instruction.sha256"
        if (
            ec.exists()
            and ec.read_text().strip() == "0"
            and sh.exists()
            and sh.read_text().strip() == sha
        ):
            n += 1
    return n


def majors(task):
    f = PIPE / task / "CR.json"
    if not f.exists():
        return None
    try:
        d = json.load(open(f))
        return sum(
            1
            for x in d.get("findings", [])
            if str(x.get("severity", "")).lower() == "major"
        )
    except Exception:
        return -1


rows = []
now = time.time()
for t in queue:
    d = PIPE / t
    log = d / "pipeline.log"
    state = (d / "STATE").read_text().split() if (d / "STATE").exists() else []
    stage = "untouched"
    last_min = None
    if log.exists():
        lines = [
            l for l in log.read_text(errors="replace").splitlines() if l.startswith("[")
        ]
        last_min = int((now - log.stat().st_mtime) / 60)
        for l in lines:
            m = re.search(r"step 3: blind CR \(round (\d)", l)
            if m:
                stage = f"CR round {m.group(1)}"
            m = re.search(r"step 4: fix round (\d)", l)
            if m:
                stage = f"fix round {m.group(1)}"
            if "step 5" in l or "probe" in l.lower() and "step" in l:
                stage = "probes"
            if "step 6" in l or "stage_and_zip" in l:
                stage = "zip"
        if stage == "untouched" and "MECHANICAL" in state:
            stage = "mechanical"
        elif stage == "untouched" and state:
            stage = "mechanical"
    if (d / "PARKED.md").exists():
        stage = "parked"
    if "DONE" in state or (QC / "out" / "pipe" / f"{t}.zip").exists():
        stage = "done"
    rows.append(
        dict(
            task=t,
            stage=stage,
            majors=majors(t),
            glm=glm_valid(t),
            zip=(QC / "out" / "pipe" / f"{t}.zip").exists(),
            running=t in running,
            last_min=last_min,
        )
    )

order = [
    "done",
    "zip",
    "probes",
    "fix round 2",
    "CR round 2",
    "fix round 1",
    "CR round 1",
    "CR round 0",
    "mechanical",
    "untouched",
    "parked",
]
from collections import Counter

c = Counter(r["stage"] for r in rows)
print(
    f"TASKS {len(rows)}   running now {sum(r['running'] for r in rows)}   zips {sum(r['zip'] for r in rows)}   GLM: 2 valid runs {sum(r['glm']==2 for r in rows)}, 1 run {sum(r['glm']==1 for r in rows)}, 0 runs {sum(r['glm']==0 for r in rows)}"
)
print()
print(
    f"{'stage':14} {'tasks':>5} {'running':>7}   majors left (latest CR): min/median/max"
)
for s in order:
    rs = [r for r in rows if r["stage"] == s]
    if not rs:
        continue
    ms = sorted(r["majors"] for r in rs if r["majors"] is not None and r["majors"] >= 0)
    mstr = f"{ms[0]}/{ms[len(ms)//2]}/{ms[-1]}" if ms else "-"
    print(f"{s:14} {len(rs):>5} {sum(r['running'] for r in rs):>7}   {mstr}")
parked = [r for r in rows if r["stage"] == "parked"]
if parked:
    print(
        "\nPARKED (need a human):",
        " ".join(f"{r['task'][7:]}({r['majors']}M)" for r in parked),
    )
stale = [
    r
    for r in rows
    if r["running"] and r["last_min"] is not None and r["last_min"] >= 30
]
if stale:
    print(
        "\nSTALE (running, no log line for 30+ min):",
        " ".join(f"{r['task'][7:]}({r['last_min']}m)" for r in stale),
    )
if "--all" in sys.argv:
    print()
    for r in sorted(
        rows,
        key=lambda r: (
            order.index(r["stage"]) if r["stage"] in order else 99,
            r["task"],
        ),
    ):
        print(
            f"{r['task']:16} {r['stage']:12} majors={r['majors'] if r['majors'] is not None else '-':>3} glm={r['glm']} {'RUN' if r['running'] else '   '} {'' if r['last_min'] is None else str(r['last_min'])+'m'}"
        )
