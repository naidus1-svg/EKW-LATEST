#!/usr/bin/env python3
"""svc_pipeline_report.py - one-screen live state of the SVC-PC gate-v2 pipeline. Read-only.

Run from the laptop:  ssh -i ~/.ssh/kiem_sandbox -p 2222 root@136.113.78.105 'cd /root/qc && python3 - table' < svc_pipeline_report.py
Layouts: table (lanes, calibration set per task, corpus buckets, throughput) | funnel (stage counts with arrows and ETAs) | owners (who is
doing what, next output, blocked on). `all` prints the three. Every number is computed at run time from the sandbox: /proc, lanes/, stream-pipe/,
out/pipe/, the logs under _prompts/ and the verify session's CSVs. The corpus bucket section shells out to tools/status_snapshot.py (about 20 s).
"""

import collections
import csv
import glob
import json
import os
import re
import subprocess
import sys
import time

Q = "/root/qc"
SP = f"{Q}/stream-pipe"
LN = f"{Q}/lanes"
PR = f"{Q}/_prompts"
CORPUS = "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
FRESH = f"{PR}/verify/dataos-fresh"
NOW = time.time()
LAYOUT = (sys.argv[1] if len(sys.argv) > 1 else "table").lower()


def rd(p):
    try:
        return open(p, errors="replace").read()
    except OSError:
        return ""


def mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def hhmm(t):
    return time.strftime("%H:%M", time.gmtime(t)) if t else "-"


def ago(t):
    return f"{int((NOW - t) // 60)}m" if t else "-"


# ------------------------------------------------------------------ processes and lanes
PROCS = {}
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        st = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
        cmd = (
            open(f"/proc/{pid}/cmdline", "rb")
            .read()
            .replace(b"\0", b" ")
            .decode("utf-8", "replace")
        )
        PROCS[int(pid)] = (int(st[1]), cmd)
    except OSError:
        pass


def ancestors(pid):
    out = []
    while pid in PROCS and pid > 1 and len(out) < 12:
        out.append(PROCS[pid][1])
        pid = PROCS[pid][0]
    return out


def purpose(pid, cmd):
    chain = " || ".join(ancestors(pid))
    if "run_workspace_review_sev2" in chain:
        return "sev2 review"
    if "run_workspace_review_thorough" in chain:
        return "thorough review"
    m = re.search(r"run_workspace_review\.py .*?--reviewer (\w+)", chain)
    if m:
        return f"{m.group(1)} review"
    if "judge_emulate" in chain or "oracle_refresh" in chain:
        return "oracle probe"
    if "adjudicate" in chain:
        return "adjudication"
    if "pin_probe" in chain:
        return "pin probe"
    if "solver_run" in chain or "solver_batch" in chain:
        return "GLM solver run"
    if (
        "fix_from_dataos" in chain
        or "fix_from_reviews" in chain
        or "fix_priority" in chain
    ):
        return "fix plan"
    m = re.search(r"--model (\S+)", cmd)
    return f"other ({m.group(1) if m else '?'})"


def lane_of(pid):
    try:
        env = open(f"/proc/{pid}/environ", "rb").read()
    except OSError:
        return None
    m = re.search(rb"CLAUDE_CONFIG_DIR=/root/(\.claude[^\0]*)", env)
    if m:
        return m.group(1).decode()
    return "proxy" if b"34.41.10.8" in env else ".claude"


SESSIONS = collections.defaultdict(list)
for pid, (ppid, cmd) in PROCS.items():
    if "claude -p" in cmd:
        SESSIONS[lane_of(pid)].append(purpose(pid, cmd))

ROLE = {".claude": "pool (default)"}
ROLE.update({f".claude-{c}": "pool" for c in "bcdefghijkl"})
ROLE.update(
    {
        ".claude-m": "fixes session",
        ".claude-n": "verify session",
        ".claude-o": "pool",
        ".claude-p": "pipe2 + pool",
        ".claude-q": "fix plans",
        ".claude-r": "fix plans",
        ".claude-s": "duplicate of p",
        ".claude-t": "backup",
        ".claude-u": "backup",
    }
)
LANES = [".claude"] + [f".claude-{c}" for c in "bcdefghijklmnopqrstu"]


def lane_state(n):
    bits = []
    if os.path.exists(f"{LN}/{n}.benched"):
        try:
            bits.append(
                "BENCHED until "
                + time.strftime(
                    "%m-%d %H:%MZ",
                    time.gmtime(int(rd(f"{LN}/{n}.reset_at").split()[0])),
                )
            )
        except Exception:
            bits.append("BENCHED")
    if os.path.exists(f"{LN}/{n}.limited_until"):
        bits.append("limited")
    if os.path.exists(f"/root/{n}.limited"):
        bits.append("SWAPPED to backup")
    if os.path.islink(f"/root/{n}"):
        bits.append("-> " + os.readlink(f"/root/{n}"))
    return ", ".join(bits) or "up"


# ------------------------------------------------------------------ calibration set
CAL = [l.strip() for l in rd(f"{FRESH}/tasks.txt").splitlines() if l.strip()] + [
    "SVC-PC-2-7-0"
]
ROWS = collections.defaultdict(lambda: {"yes": 0, "no": 0})
_SEEN = (
    set()
)  # the verify session merges the addendum into its status.csv; count each (task, reviewer, check) once
for f in (f"{FRESH}/status.csv", f"{FRESH}/opus-addendum/status.csv"):
    try:
        for r in csv.DictReader(open(f, newline="", encoding="utf-8")):
            k = (r["task"], r.get("reviewer", ""), r.get("check", ""))
            if k in _SEEN:
                continue
            _SEEN.add(k)
            ROWS[r["task"]][
                ("no" if r.get("still_true", "").strip().lower() == "no" else "yes")
            ] += 1
    except OSError:
        pass
PRED = rd(f"{FRESH}/prediction.md")
ZIPLOG = rd(f"{PR}/zip_when_ready.log").splitlines()
SUBMITTED = set(rd(f"{Q}/SUBMITTED.txt").split())


def newest_shipped(task):
    best = 0
    for root, _, files in os.walk(f"{CORPUS}/{task}"):
        for fn in files:
            if fn == "test.sh":
                continue
            best = max(best, mtime(os.path.join(root, fn)))
    return best


def latest_verdict(task, r):
    fs = [
        f
        for f in glob.glob(f"{SP}/{task}/CR.{r}.*.json")
        if re.search(r"\.(round\d+|dataos)\.json$", f)
    ]
    if not fs:
        return None, 0
    f = max(fs, key=mtime)
    try:
        return json.load(open(f)).get("major_count"), mtime(f)
    except Exception:
        return "bad", mtime(f)


def last_zip_event(task):
    for l in reversed(ZIPLOG):
        if f" {task} " in l or l.rstrip().endswith(f" {task}"):
            m = re.match(r"\S+ (ZIPPED|BLOCK|SKIP) \S+ ?(.*)", l)
            if m:
                return m.group(1), m.group(2)[:60]
    return "-", ""


def task_row(t):
    p = f"{SP}/{t}"
    state = rd(f"{p}/STATE")
    a_done = "DATAOS_MAJORS_1" in state.split()
    shipped = newest_shipped(t)
    g, gt = latest_verdict(t, "glm")
    s, st_ = latest_verdict(t, "sonnet")
    stale = (gt and gt < shipped) or (st_ and st_ < shipped)
    pk = rd(f"{p}/checks/promoted_kinds.txt")
    blocking = len(re.findall(r"^BLOCKING", pk, re.M)) if pk else None
    orc = {}
    try:
        orc = json.load(open(f"{p}/probes/oracle.json"))
    except Exception:
        pass
    reward = orc.get("total_reward")
    runs = orc.get("oracle_runs")
    flips = len(orc.get("flips") or [])
    zpath = f"{Q}/out/pipe/{t}.zip"
    zipped = (
        os.path.exists(zpath)
        and mtime(zpath) > shipped
        and mtime(zpath) > mtime(f"{p}/FIX-FROM-DATAOS.md")
    )
    ev, detail = last_zip_event(t)
    rows = ROWS.get(t, {"yes": 0, "no": 0})
    predicted = t in PRED
    if t in SUBMITTED and t == "SVC-PC-2-7-0":
        stage = "accepted by DataOS"
    elif zipped:
        stage = "8 zipped, awaiting upload"
    elif rows["yes"] and not a_done:
        stage = "1 fix round pending"
    elif g is None or s is None or stale:
        stage = "2 re-review pending" if a_done else "1 fix round running"
    elif (g or 0) > 0 or (s or 0) > 0:
        stage = "3 majors after fix"
    elif blocking:
        stage = f"4 gate: {blocking} promoted finding(s)"
    elif reward is None or (isinstance(reward, (int, float)) and reward < 1.0) or flips:
        stage = "5 oracle: " + (
            f"{reward} flips {flips}" if reward is not None else "no probe"
        )
    elif rows["yes"]:
        stage = f"6 verify: {rows['no']}/{rows['yes'] + rows['no']} rows fixed"
    elif not predicted:
        stage = "7 prediction pending"
    else:
        stage = "7 ready for zip"
    return dict(
        task=t,
        majors=rows["yes"] + rows["no"],
        fixed_rows=rows["no"],
        a="yes" if a_done else "no",
        glm=g,
        sonnet=s,
        verdict_age=ago(max(gt, st_)),
        stale="stale" if stale else "",
        gate=blocking,
        oracle=reward,
        runs=runs,
        flips=flips,
        zip_event=f"{ev} {detail}".strip(),
        predicted="yes" if predicted else "no",
        zipped="yes" if zipped else "no",
        stage=stage,
    )


# ------------------------------------------------------------------ throughput
def count_since(path, pat, minutes=60):
    cut = NOW - minutes * 60
    n = 0
    for l in rd(path).splitlines():
        m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)Z", l)
        if not m:
            continue
        try:
            ts = (
                time.mktime(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"))
                - time.timezone
            )
        except Exception:
            continue
        if ts >= cut and re.search(pat, l):
            n += 1
    return n


def throughput():
    fx = f"{PR}/fix_from_reviews.log"
    return {
        "fix rounds applied (all fixers)": count_since(
            fx, r" DONE \S+ fix-from-reviews (ROUND2 )?(round )?applied"
        )
        + count_since(f"{PR}/fix_from_dataos_fresh.log", r"round applied")
        + count_since(f"{PR}/fix_from_dataos_fresh2.log", r"round applied"),
        "re-reviews finished": count_since(fx, r" FINISH SVC-PC"),
        "tasks cleaned": count_since(fx, r" CLEAN SVC-PC"),
        "tasks parked": count_since(fx, r" PARKED SVC-PC"),
        "zipped": count_since(f"{PR}/zip_when_ready.log", r" ZIPPED "),
        "zip attempts": count_since(
            f"{PR}/zip_when_ready.log", r" (ZIPPED|BLOCK|SKIP) "
        ),
    }


def corpus_buckets():
    snap = next(
        (
            c
            for c in (
                f"{Q}/tools/status_snapshot.py",
                f"{Q}/_prompts/status_snapshot.py",
            )
            if os.path.exists(c)
        ),
        None,
    )
    if not snap:
        return [
            "status_snapshot.py not found on the sandbox (copy it to /root/qc/tools/ from the repo guards dir)"
        ]
    try:
        r = subprocess.run(
            ["python3", snap], capture_output=True, text=True, timeout=180, cwd=Q
        )
        out = r.stdout
        if r.returncode != 0:
            return [f"status_snapshot.py rc={r.returncode}: {r.stderr.strip()[-200:]}"]
    except Exception as e:
        return [f"status_snapshot.py failed: {e}"]
    return [
        l.rstrip()
        for l in out.splitlines()
        if re.match(r"\s+\d+\s+\d[a-z]?\.", l)
        or l.startswith("   both reviewers")
        or l.startswith("   of the")
    ]


# ------------------------------------------------------------------ layouts
def render_table(cal):
    print(
        f"# SVC-PC pipeline report, {time.strftime('%Y-%m-%d %H:%MZ', time.gmtime())} (sandbox clock), load {rd('/proc/loadavg').split()[0]}, {sum(len(v) for v in SESSIONS.values())} model sessions"
    )
    print("\n## Lanes")
    print("| lane | role | state | live sessions |\n|---|---|---|---|")
    for n in LANES:
        s = collections.Counter(SESSIONS.get(n, []))
        print(
            f"| {n[1:]} | {ROLE.get(n, '?')} | {lane_state(n)} | {', '.join(f'{k} x{v}' if v > 1 else k for k, v in s.items()) or '-'} |"
        )
    px = collections.Counter(SESSIONS.get("proxy", []))
    print(
        f"| GLM proxy | 5 keys, rotation by task | up | {', '.join(f'{k} x{v}' for k, v in px.items()) or '-'} |"
    )
    print("\n## Calibration set (22 rejected + 2-7-0)")
    print(
        "| task | DataOS majors (fixed) | A | glm/sonnet majors (age) | gate | oracle (runs, flips) | last zip event | predicted | stage |\n|---|---|---|---|---|---|---|---|---|"
    )
    for r in cal:
        print(
            f"| {r['task'][7:]} | {r['majors']} ({r['fixed_rows']}) | {r['a']} | {r['glm']}/{r['sonnet']} ({r['verdict_age']}{' ' + r['stale'] if r['stale'] else ''}) | {r['gate'] if r['gate'] is not None else '-'} | {r['oracle']} ({r['runs'] or '-'}, {r['flips']}) | {r['zip_event'][:40] or '-'} | {r['predicted']} | {r['stage']} |"
        )
    print("\n## Corpus buckets (tools/status_snapshot.py)")
    for l in corpus_buckets():
        print(l)
    print("\n## Last 60 minutes")
    for k, v in throughput().items():
        print(f"- {k}: {v}")


def render_funnel(cal):
    n = len(cal)
    stages = collections.Counter(r["stage"].split(":")[0].split(",")[0] for r in cal)
    order = [
        "1 fix round pending",
        "1 fix round running",
        "2 re-review pending",
        "3 majors after fix",
        "4 gate",
        "5 oracle",
        "6 verify",
        "7 prediction pending",
        "7 ready for zip",
        "8 zipped, awaiting upload",
        "accepted by DataOS",
    ]
    print(
        f"# Funnel, {time.strftime('%H:%MZ', time.gmtime())}: calibration set {n} tasks"
    )
    print(" -> ".join(f"[{k}: {stages.get(k, 0)}]" for k in order if stages.get(k, 0)))
    done_rows = sum(r["fixed_rows"] for r in cal)
    all_rows = sum(r["majors"] for r in cal)
    print(
        f"DataOS major rows verified fixed on bytes: {done_rows}/{all_rows}; predictions written: {sum(1 for r in cal if r['predicted'] == 'yes')}/{n}; zipped: {sum(1 for r in cal if r['zipped'] == 'yes')}/{n}"
    )
    tp = throughput()
    print(
        f"Pace, last hour: {tp['fix rounds applied (all fixers)']} fix rounds, {tp['re-reviews finished']} re-reviews, {tp['zipped']} zips. A fix-plus-re-review cycle is about 25 minutes; the zip loop does about 15 to 20 attempts an hour."
    )
    print("Corpus (other 179), from status_snapshot.py:")
    for l in corpus_buckets():
        print("  " + l.strip())
    busy = sum(len(v) for v in SESSIONS.values())
    print(
        f"Lanes: {busy} model sessions on {sum(1 for n in LANES if SESSIONS.get(n))} lanes; benched: {', '.join(n[1:] for n in LANES if os.path.exists(f'{LN}/{n}.benched')) or 'none'}"
    )


def render_owners(cal):
    stages = collections.Counter(r["stage"] for r in cal)
    print(f"# Owners board, {time.strftime('%H:%MZ', time.gmtime())}")
    fixer_alive = any("fix_from_dataos.sh" in c for _, c in PROCS.values())
    prio_alive = any("fix_priority_loop.sh" in c for _, c in PROCS.values())
    zip_alive = any("zip_when_ready.sh" in c for _, c in PROCS.values())
    main_state = "-"
    m = re.findall(
        r"FIX-FROM-REVIEWS START pid=(\d+)", rd(f"{PR}/fix_from_reviews.log")
    )
    if m:
        try:
            main_state = open(f"/proc/{m[-1]}/stat").read().rsplit(")", 1)[1].split()[0]
        except OSError:
            main_state = "gone"
    rows = [
        (
            "Fixer (fix_from_dataos.sh, lanes q r then pool)",
            "running" if fixer_alive else "idle",
            f"{stages.get('1 fix round running', 0) + stages.get('1 fix round pending', 0)} calibration tasks still to fix",
            "DataOS rows in dataos-fresh/fixer/",
        ),
        (
            "Priority loop (later rounds on the 22)",
            "running" if prio_alive else "DOWN",
            f"{sum(v for k, v in stages.items() if k.startswith('3') or k.startswith('4'))} tasks need another round",
            "promoted-kinds findings in the union",
        ),
        (
            "Main fix loop (corpus)",
            {"T": "PAUSED (SIGSTOP)", "S": "running", "R": "running"}.get(
                main_state, main_state
            ),
            "nothing until the 22 are uploaded",
            "Khiem's go after batch 10 returns",
        ),
        (
            "Reviews (pool lanes, GLM proxy)",
            f"{sum(len(v) for v in SESSIONS.values())} sessions",
            f"{stages.get('2 re-review pending', 0)} calibration tasks awaiting a clean pair",
            "fix rounds landing",
        ),
        (
            "Zip loop (ZIP_ONLY_LIST = the 22)",
            "running" if zip_alive else "DOWN",
            f"{stages.get('7 ready for zip', 0)} ready, {sum(v for k, v in stages.items() if k.startswith('4') or k.startswith('5'))} blocked at a gate",
            "gate and oracle results",
        ),
        (
            "Verify session (lane n)",
            "tmux verify",
            f"{sum(r['fixed_rows'] for r in cal)}/{sum(r['majors'] for r in cal)} rows ruled fixed, {sum(1 for r in cal if r['predicted'] == 'yes')} predictions",
            "DATAOS_MAJORS_1 markers",
        ),
        (
            "Fixes session (lane m)",
            "tmux fixes",
            "C1 follow-ups: kind filter in the union, final_document tightening, sample of judge_scope_under_inclusion",
            "-",
        ),
        (
            "pipe2 session (lane p)",
            "tmux pipe2",
            "three-run oracle on the 22, ZIP_ONLY_LIST gate",
            "-",
        ),
        (
            "Khiem",
            "-",
            f"upload batch 10 when {len(cal) - 1} zips exist; DataOS verdicts back",
            "the pipeline",
        ),
    ]
    print("| owner | state | now / next output | blocked on |\n|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(r) + " |")


CAL_ROWS = [task_row(t) for t in CAL]
if LAYOUT in ("table", "all"):
    render_table(CAL_ROWS)
if LAYOUT in ("funnel", "all"):
    print()
    render_funnel(CAL_ROWS)
if LAYOUT in ("owners", "all"):
    print()
    render_owners(CAL_ROWS)
