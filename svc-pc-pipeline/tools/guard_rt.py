#!/usr/bin/env python3
"""guard_rt.py - near-real-time guard for the SVC-PC gate-v2 pipeline. Zero model tokens, except one tiny
probe call on a backup account at the moment a lane is swapped, and one on a parked account at restore time.

Loop every 30 s. ALERTS.log gets every alert; ALERTS.crit gets CRIT lines only (the laptop streams that file).
Self-heal, disabled by touching lanes/GUARD_ACTIONS_OFF:
  - relaunch a dead fix dispatcher or zip step after 3 absent minutes (max 3 per hour)
  - re-arm oracle probes whose criteria all errored (timeouts, lane refusals) instead of scoring 0.0
  - sweep round0 reviews that have no verdict and no live process (max 3 tries per pair)
  - swap a limit-hit pool lane onto a backup account listed in lanes/BACKUPS (backups are never polled)
CLI: guard_rt.py [run] | once [--dry] | status | swap <lane> | restore <lane>
"""

import os, re, sys, json, time, glob, subprocess, shutil
from datetime import datetime, timezone, timedelta

Q = "/root/qc"
SP = f"{Q}/stream-pipe"
LN = f"{Q}/lanes"
PR = f"{Q}/_prompts"
ALOG = f"{Q}/ALERTS.log"
ACRIT = f"{Q}/ALERTS.crit"
STATEF = f"{LN}/GUARD_STATE.json"
HB = f"{LN}/GUARD_HEARTBEAT"
OFF = f"{LN}/GUARD_ACTIONS_OFF"
PIDF = f"{LN}/GUARD.pid"
LOOP = 30
DRY = False
LIMIT_RE = re.compile(
    r"usage limit|hit your [a-z ]*limit|limit reached|weekly limit|session limit", re.I
)
SESS_LIMIT_RE = re.compile(
    r"hit your [a-z ]*limit|limit reached|usage limit reached", re.I
)
ERR_RE = re.compile(
    r"timed out|CLI backend error|rate.?limit|overloaded|" + LIMIT_RE.pattern, re.I
)
# engineering-session lanes, the duplicate account, and the default dir (its .claude.json lives outside the dir)
RESERVED = {".claude-m", ".claude-n", ".claude-p", ".claude-s", ".claude"}
POOL = [".claude-" + x for x in "bcdefgijklqr"]
ST = {}
RAISED = set()


def now():
    return time.time()


def iso(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t if t else now()))


def epoch(s):
    try:
        return (
            datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except Exception:
        return 0


def sh(cmd, t=25):
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=t
        ).stdout
    except Exception:
        return ""


def rd(p, n=None):
    try:
        with open(p, errors="replace") as f:
            return f.read() if n is None else f.read(n)
    except Exception:
        return ""


def spawn(cmd):
    if DRY:
        print("   [dry] would run:", cmd)
        return
    subprocess.Popen(
        cmd,
        shell=True,
        cwd=Q,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def actions_on():
    return not os.path.exists(OFF)


# ---------------------------------------------------------------- state and alerts
def load():
    global ST
    try:
        ST = json.load(open(STATEF))
    except Exception:
        ST = {}
    for k, d in (
        ("alerts", {}),
        ("events", {}),
        ("seen_zipped", []),
        ("absent", {}),
        ("relaunch", {}),
        ("swaps", {}),
        ("attempts", {}),
        ("heal", {}),
        ("prompt_seen", {}),
        ("load_hist", []),
        ("last", {}),
        ("seen_hits", []),
        ("lane_hits", {}),
    ):
        ST.setdefault(k, d)


def save():
    if DRY:
        return
    try:
        with open(STATEF + ".tmp", "w") as f:
            json.dump(ST, f)
        os.replace(STATEF + ".tmp", STATEF)
    except Exception:
        pass


def emit(level, text):
    line = f"{iso()} GUARD {level} {text}"
    if DRY:
        print(line)
        return
    with open(ALOG, "a") as f:
        f.write(line + "\n")
    if level == "CRIT":
        with open(ACRIT, "a") as f:
            f.write(line + "\n")


def event(level, msg, dedup=None, gap=1800):
    """One-shot fact (something happened). Logged once per dedup key per `gap` seconds."""
    k = dedup or msg[:90]
    if now() - ST["events"].get(k, 0) < gap:
        return
    ST["events"][k] = now()
    for old in [x for x, t in ST["events"].items() if now() - t > 86400]:
        del ST["events"][old]
    emit(level, msg)


def alert(key, level, msg, repeat=None):
    """Standing condition. Logged when it starts, re-logged every `repeat` s while true, and 'cleared' when it ends."""
    RAISED.add(key)
    rep = repeat or {"CRIT": 900, "WARN": 3600, "INFO": 7200}[level]
    a = ST["alerts"].setdefault(key, {"active": False, "last": 0})
    t = now()
    if (not a["active"]) or (t - a["last"] >= rep):
        emit(level, f"[{key}] {msg}")
        a["last"] = t
    a.update(active=True, level=level, msg=msg[:220], seen=t)


def keep(prefix):
    for k, a in ST["alerts"].items():
        if a.get("active") and k.startswith(prefix):
            RAISED.add(k)


def due(name, secs):
    t = now()
    if t - ST["last"].get(name, 0) >= secs:
        ST["last"][name] = t
        return True
    return False


def end_pass():
    for k, a in ST["alerts"].items():
        if a.get("active") and k not in RAISED:
            a["active"] = False
            emit(
                "CRIT" if a.get("level") == "CRIT" else "OK",
                f"[{k}] cleared (was {a.get('level')}: {a.get('msg', '')[:90]})",
            )
    RAISED.clear()


# ---------------------------------------------------------------- process helpers
def procs():
    rows = []
    for l in sh("ps -eo pid,etimes,args --no-headers", 15).splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(.*)", l)
        if m:
            rows.append((int(m.group(1)), int(m.group(2)), m.group(3)))
    return rows


def live_pairs(rows):
    live = set()
    for _, _, a in rows:
        m = re.search(
            r"run_workspace_review\.py --task (SVC-PC-\S+) .*--reviewer (glm|sonnet|opus)",
            a,
        )
        if m:
            live.add((m.group(1), m.group(2)))
    return live


# ---------------------------------------------------------------- checks
def check_loops(rows):
    args = [a for p, _, a in rows if "guard_rt" not in a]
    pid = None
    for m in re.finditer(
        r"FIX-FROM-REVIEWS START pid=(\d+)",
        sh(f"tail -n 400 {PR}/fix_from_reviews.log", 10),
    ):
        pid = int(m.group(1))
    alive_fix = (pid is not None and os.path.exists(f"/proc/{pid}")) or any(
        "fix_from_reviews.sh" in a and re.match(r"\s*(/bin/)?(bash|setsid)\b", a)
        for a in args
    )
    alive_zip = any(
        "zip_when_ready.sh" in a and re.match(r"\s*(/bin/)?bash\b", a) for a in args
    )
    # touch lanes/FIX_PRIORITY_LOOP_OFF to stop the priority loop for good: kill it once, then the guard leaves it alone
    # (2026-09-19 22:58Z: the direct and Fable fix agents own the 22 open tasks; the loop's fixer took 88-0-0's lock 1 s after
    # the guard relaunched it)
    alive_prio = os.path.exists(f"{LN}/FIX_PRIORITY_LOOP_OFF") or any(
        "fix_priority_loop.sh" in a and re.match(r"\s*(/bin/)?bash\b", a) for a in args
    )
    # touch lanes/ADJUDICATE_LOOP_OFF to stop the adjudication loop for good (it exits on the flag and the guard then leaves it alone)
    alive_adj = os.path.exists(f"{LN}/ADJUDICATE_LOOP_OFF") or any(
        "adjudicate_loop.sh" in a and re.match(r"\s*(/bin/)?bash\b", a) for a in args
    )
    for name, alive, cmd in (
        (
            "adjudicate_loop",
            alive_adj,
            "bash tools/adjudicate_loop.sh > _prompts/adjudicate_loop.out 2>&1",
        ),
        (
            "fix_priority_loop",
            alive_prio,
            "bash tools/fix_priority_loop.sh > _prompts/fix_priority_loop.out 2>&1",
        ),
        (
            "fix_from_reviews",
            alive_fix,
            "bash tools/fix_from_reviews.sh > _prompts/fix_from_reviews.nohup.log 2>&1",
        ),
        (
            "zip_when_ready",
            alive_zip,
            "bash tools/zip_when_ready.sh > _prompts/zip_when_ready.nohup.log 2>&1",
        ),
    ):
        if alive:
            ST["absent"][name] = 0
            continue
        ST["absent"][name] = ST["absent"].get(name, 0) + 1
        n = ST["absent"][name]
        if n < 2:
            continue
        recent = [t for t in ST["relaunch"].get(name, []) if now() - t < 3600]
        ST["relaunch"][name] = recent
        if n < 6:
            alert(
                f"loop_absent_{name}",
                "WARN",
                f"{name} not running for {n * LOOP}s; relaunch after 180s",
            )
        elif not actions_on():
            alert(
                f"loop_dead_{name}",
                "CRIT",
                f"{name} is dead and actions are off (lanes/GUARD_ACTIONS_OFF)",
            )
        elif len(recent) >= 3:
            alert(
                f"loop_dead_{name}",
                "CRIT",
                f"{name} died {len(recent)} times in the last hour; not relaunching again, read its .nohup.log",
            )
        else:
            spawn(f"setsid nohup {cmd} < /dev/null &")
            recent.append(now())
            ST["relaunch"][name] = recent
            ST["absent"][name] = 0
            event(
                "CRIT",
                f"[loop_dead_{name}] {name} was dead for 3 min; relaunched it ({len(recent)} of 3 this hour)",
                dedup=f"relaunch-{name}-{len(recent)}",
                gap=60,
            )


def check_zip_integrity():
    seen = set(ST["seen_zipped"])
    for l in sh(f"tail -n 300 {PR}/zip_when_ready.log", 10).splitlines():
        m = re.match(r"(\S+) ZIPPED (SVC-PC-\S+)", l)
        if not m or (m.group(1) + m.group(2)) in seen:
            continue
        seen.add(m.group(1) + m.group(2))
        t = m.group(2)
        z = f"{Q}/out/pipe/{t}.zip"
        if not (os.path.exists(z) and os.path.getsize(z) > 1000):
            event(
                "CRIT",
                f"[zip_missing] {t} was logged ZIPPED but {z} is missing or empty",
                dedup=f"zipmiss-{t}",
            )
        elif len(rd(f"{Q}/out/pipe/{t}.sha256").strip()) != 64:
            event(
                "CRIT",
                f"[zip_nosha] {t} zip exists but its .sha256 is empty or malformed",
                dedup=f"zipsha-{t}",
            )
    ST["seen_zipped"] = sorted(seen)[-300:]
    blank = [
        l
        for l in rd(f"{Q}/out/pipe/SHA256SUMS.txt").splitlines()
        if re.match(r"^SVC-PC-\S+\s*$", l)
    ]
    if blank:
        alert(
            "sha_sums_blank",
            "CRIT",
            f"{len(blank)} lines in out/pipe/SHA256SUMS.txt have no size or hash: {blank[0][:60]}",
        )


def check_host():
    try:
        load1 = float(rd("/proc/loadavg").split()[0])
    except Exception:
        return
    h = ST["load_hist"]
    h.append(load1)
    del h[:-10]
    avg = sum(h) / len(h)
    if len(h) >= 6 and avg > 160:
        alert(
            "host_load",
            "CRIT",
            f"load average {avg:.0f} on 32 cores over 3+ min; judge probes time out above ~64, 22 agents died at 341",
        )
    elif len(h) >= 6 and avg > 96:
        alert(
            "host_load",
            "WARN",
            f"load average {avg:.0f} on 32 cores over 3+ min (probes start timing out above ~64)",
        )
    mem = re.search(r"MemAvailable:\s+(\d+) kB", rd("/proc/meminfo"))
    if mem:
        gb = int(mem.group(1)) / 1048576
        if gb < 8:
            alert("host_mem", "CRIT", f"only {gb:.1f} GB memory available")
        elif gb < 20:
            alert("host_mem", "WARN", f"{gb:.1f} GB memory available")
    st = os.statvfs("/")
    used = 100 - 100 * st.f_bavail / st.f_blocks
    if used > 94:
        alert("host_disk", "CRIT", f"root disk {used:.0f}% full")
    elif used > 88:
        alert("host_disk", "WARN", f"root disk {used:.0f}% full")


def bulk_finishes(minutes):
    cut = now() - minutes * 60
    rows = []
    for l in sh(f"tail -n 1500 {PR}/bulk_review.log", 10).splitlines():
        m = re.match(r"(\S+Z) FINISH (SVC-PC-\S+) (\w+) rc=(\d+) (.*)", l)
        if m and epoch(m.group(1)) >= cut:
            rows.append(
                (
                    epoch(m.group(1)),
                    m.group(2),
                    m.group(3),
                    int(m.group(4)),
                    "maj" in m.group(5),
                )
            )
    return rows


def check_reviews(rows_ps):
    rows = bulk_finishes(20)
    kills = sorted(t for t, _, _, rc, _ in rows if rc == 137)
    for k in kills:
        n = sum(1 for j in kills if k <= j <= k + 180)
        if n >= 6:
            event(
                "CRIT",
                f"[mass_sigkill] {n} review runs were SIGKILLed (rc=137) within 3 min from {iso(k)}; something ran a broad kill; the sweeper re-runs them",
                dedup=f"kill-{int(k // 600)}",
                gap=3600,
            )
            break
    for r in ("glm", "sonnet"):
        rr = [x for x in rows if x[2] == r]
        if len(rr) >= 8:
            bad = [x for x in rr if x[3] != 0]
            ratio = len(bad) / len(rr)
            codes = {}
            for x in bad:
                codes[x[3]] = codes.get(x[3], 0) + 1
            if ratio > 0.6:
                alert(
                    f"review_fail_{r}",
                    "CRIT",
                    f"{r} reviews failing {len(bad)}/{len(rr)} in 20 min, rc {codes}",
                )
            elif ratio > 0.35:
                alert(
                    f"review_fail_{r}",
                    "WARN",
                    f"{r} reviews failing {len(bad)}/{len(rr)} in 20 min, rc {codes}",
                )
    agents = len(live_pairs(rows_ps))
    load1 = ST["load_hist"][-1] if ST["load_hist"] else 0
    fix_recent = 0
    for logf in ("fix_from_reviews.log", "fix_from_dataos.log"):
        for l in sh(f"tail -n 400 {PR}/{logf}", 10).splitlines():
            m = re.match(
                r"(\S+Z) (?:FINISH (SVC-PC-\S+) (?:glm|sonnet)\b|DONE (SVC-PC-\S+) .*reviews (?:both )?finished)",
                l,
            )
            if m and epoch(m.group(1)) >= now() - 1200:
                fix_recent += 1
    if agents >= 6 and not rows and not fix_recent and load1 < 96:
        alert(
            "reviews_stalled",
            "WARN",
            f"{agents} review agents alive but none finished in 20 min",
        )


def parse_reset(txt):
    m = re.search(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)", txt, re.I)
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
        n = datetime.now(timezone.utc)
        t = n.replace(hour=h, minute=int(m.group(2) or 0), second=0, microsecond=0)
        if t <= n:
            t += timedelta(days=1)
        return t.timestamp() + 90
    if re.search(r"weekly", txt, re.I):
        return now() + 12 * 3600
    return None


def backups():
    return [
        l.strip()
        for l in rd(f"{LN}/BACKUPS").splitlines()
        if l.strip() and not l.startswith("#")
    ]


def swap(lane_dir, reason):
    name = os.path.basename(lane_dir)
    if name in RESERVED:
        event(
            "CRIT",
            f"[lane_limit] {name} is limit-hit ({reason[:70]}) but it is reserved or the default lane; not swappable, needs a person",
            dedup=f"res-{name}",
        )
        return False
    if os.path.islink(lane_dir) or name in ST["swaps"]:
        return True
    used = {v["backup"] for v in ST["swaps"].values()}
    for b in backups():
        if b in used or not os.path.isdir(b):
            continue
        if DRY:
            print(f"   [dry] would swap {lane_dir} -> {b}")
            return True
        out = sh(
            f"CLAUDE_CONFIG_DIR={b} timeout 90 claude -p 'reply with the single word ok' --model sonnet < /dev/null 2>&1",
            100,
        )
        if "ok" not in out.lower() or SESS_LIMIT_RE.search(out):
            event(
                "CRIT",
                f"[backup_bad] backup {os.path.basename(b)} failed its swap-time probe: {out.strip()[:100]}",
                dedup=f"bb-{b}",
            )
            continue
        parked = lane_dir + ".limited"
        if os.path.exists(parked):
            event(
                "CRIT",
                f"[lane_limit] {parked} already exists; refusing to overwrite. Swap {name} by hand",
                dedup=f"pe-{name}",
            )
            return False
        os.rename(lane_dir, parked)
        os.symlink(b, lane_dir)
        ST["swaps"][name] = {
            "backup": b,
            "parked": parked,
            "at": now(),
            "reason": reason[:120],
            "next_probe": ST["lane_hits"].get(name, {}).get("resets") or now() + 3300,
        }
        f = f"{LN}/{name}.limited_until"
        if os.path.exists(f):
            os.remove(f)
        event(
            "CRIT",
            f"[lane_swapped] {name} limit-hit ({reason[:70]}); it now runs on backup {os.path.basename(b)}; original parked at {parked}; restore with guard_rt.py restore {name}",
            dedup=f"swap-{name}",
            gap=60,
        )
        return True
    event(
        "CRIT",
        f"[no_backup] {name} limit-hit and no healthy backup account is left in lanes/BACKUPS; it fails until its reset",
        dedup=f"nb-{name}",
        gap=3600,
    )
    return False


def restore(name, force=False):
    sw = ST["swaps"].get(name)
    if not sw:
        return False
    lane_dir = f"/root/{name}"
    out = sh(
        f"CLAUDE_CONFIG_DIR={sw['parked']} timeout 90 claude -p 'reply with the single word ok' --model sonnet < /dev/null 2>&1",
        100,
    )
    if not force and ("ok" not in out.lower() or SESS_LIMIT_RE.search(out)):
        sw["next_probe"] = now() + (21600 if re.search(r"weekly", out, re.I) else 2700)
        return False
    if os.path.islink(lane_dir):
        os.unlink(lane_dir)
    os.rename(sw["parked"], lane_dir)
    del ST["swaps"][name]
    event(
        "INFO",
        f"[lane_restored] {name} is back on its own account; backup {os.path.basename(sw['backup'])} is free",
        dedup=f"rest-{name}",
        gap=60,
    )
    return True


def note_hit(lane, txt, src):
    key = f"{lane}|{int(now() // 900)}"
    if key in ST["seen_hits"]:
        return
    ST["seen_hits"] = (ST["seen_hits"] + [key])[-200:]
    reset = parse_reset(txt)
    ST["lane_hits"][lane] = {"at": now(), "msg": txt.strip()[:120], "resets": reset}
    if not DRY:
        with open(f"{LN}/{lane}.limited_until", "w") as f:
            f.write(str(int(reset or now() + 3600)) + "\n")
    event(
        "WARN",
        f"[lane_hit] {lane} hit its usage limit ({src}): {txt.strip()[:90]}",
        dedup=f"hit-{lane}",
        gap=900,
    )
    if actions_on():
        swap(f"/root/{lane}", txt.strip())
    else:
        event(
            "CRIT",
            f"[lane_limit] {lane} limit-hit and actions are off; swap by hand: guard_rt.py swap {lane}",
            dedup=f"off-{lane}",
        )


def probe_sweep(reason):
    """One tiny Haiku call per pool lane (in parallel) to find which accounts are limit-hit. Only runs after an
    unattributed limit message, at most once per 10 minutes; backups are not probed."""
    if DRY or not due("probe_sweep", 600):
        return
    import concurrent.futures as cf

    def probe(lane):
        out = sh(
            f"CLAUDE_CONFIG_DIR=/root/{lane} timeout 60 claude -p 'reply with the single word ok' --model haiku < /dev/null 2>&1",
            70,
        )
        return lane, out

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(probe, [x for x in POOL if x not in ST["swaps"]]))
    hit = [(lane, out) for lane, out in results if SESS_LIMIT_RE.search(out)]
    event(
        "INFO",
        f"[probe_sweep] after {reason}: {len(hit)} of {len(results)} pool lanes limit-hit ({', '.join(x[0] for x in hit) or 'none'})",
        dedup=f"ps-{int(now() // 600)}",
        gap=300,
    )
    for lane, out in hit:
        note_hit(lane, out, f"probe sweep after {reason}")


def check_lanes():
    starts = {}
    for l in sh(f"tail -n 2500 {PR}/bulk_review.log", 10).splitlines():
        m = re.match(r"\S+ START (SVC-PC-\S+) (glm|sonnet) lane=(\S+)", l)
        if m:
            starts[(m.group(1), m.group(2))] = m.group(3)
    for _, t, r, rc, _ in bulk_finishes(30):
        if rc != 4 or r != "sonnet":
            continue
        raw = rd(f"{SP}/{t}/CR.{r}.round0.json.raw.txt", 400)
        lane = starts.get((t, r))
        if lane and LIMIT_RE.search(raw):
            note_hit(lane, raw, f"review {t}")
    for l in sh(f"tail -n 60 {PR}/zip_when_ready.log", 10).splitlines():
        m = re.match(r"(\S+Z) ORACLE (SVC-PC-\S+) on (\S+)", l)
        p = f"{SP}/{m.group(2)}/probes/oracle.json" if m else None
        if (
            m
            and now() - epoch(m.group(1)) < 1800
            and os.path.exists(p)
            and os.path.getmtime(p) > epoch(m.group(1))
        ):
            j = rd(p)
            hit = SESS_LIMIT_RE.search(j)
            if hit:
                i = j.find(hit.group(0))
                note_hit(m.group(3), j[max(0, i - 20) : i + 90], f"oracle {m.group(2)}")
    # fix dispatcher re-reviews and fix plans: the lane is not logged, so a limit message triggers one probe sweep of the pool
    for l in sh(f"tail -n 400 {PR}/fix_from_reviews.log", 10).splitlines():
        m = re.match(r"(\S+Z) FINISH (SVC-PC-\S+) sonnet round(\d+) rc=4 ", l)
        if m and now() - epoch(m.group(1)) < 900:
            raw = rd(f"{SP}/{m.group(2)}/CR.sonnet.round{m.group(3)}.json.raw.txt", 400)
            if SESS_LIMIT_RE.search(raw):
                probe_sweep(f"round{m.group(3)} review {m.group(2)}")
                break
    for name, sw in list(ST["swaps"].items()):
        if now() >= sw.get("next_probe", 0) and actions_on() and not DRY:
            restore(name)
    limited = [
        os.path.basename(f)[: -len(".limited_until")]
        for f in glob.glob(f"{LN}/.claude-*.limited_until")
        if int(rd(f).strip() or 0) > now()
    ]
    lim_pool = [x for x in limited if x in POOL and x not in ST["swaps"]]
    if len(lim_pool) >= 4:
        alert(
            "capacity_crunch",
            "CRIT",
            f"{len(lim_pool)} of {len(POOL)} pool lanes are limit-hit with no backup covering them ({', '.join(lim_pool)}); their reviews fail until reset; the sweeper waits",
        )
    for f in glob.glob(f"{LN}/.claude-*.limited_until"):
        if int(rd(f).strip() or 0) <= now() and not DRY:
            os.remove(f)


def check_sessions():
    for s in ("pipe2", "verify", "fixes"):
        if "yes" not in sh(f"tmux has-session -t {s} 2>/dev/null && echo yes"):
            alert(f"sess_gone_{s}", "CRIT", f"tmux session {s} is gone")
            continue
        lines = [
            x
            for x in sh(f"tmux capture-pane -p -t {s} -S -40 2>/dev/null").splitlines()
            if x.strip()
        ]
        tail = "\n".join(lines[-22:])
        last6 = "\n".join(lines[-6:])
        if re.search(r"\b1\. Yes\b", tail) and re.search(
            r"\b3\. No\b|Esc to cancel", tail
        ):
            first = ST["prompt_seen"].setdefault(s, now())
            if now() - first >= 90:
                alert(
                    f"sess_prompt_{s}",
                    "CRIT",
                    f"session {s} has waited {int(now() - first)}s on a permission prompt; answer with: tmux send-keys -t {s} 1",
                    repeat=600,
                )
        else:
            ST["prompt_seen"].pop(s, None)
        if SESS_LIMIT_RE.search(last6):
            alert(
                f"sess_limit_{s}",
                "CRIT",
                f"session {s} shows a usage-limit message on its last lines: {last6.strip()[-90:]}",
                repeat=900,
            )
        m = re.search(r"(\d+)% until auto-compact", tail)
        if m and int(m.group(1)) <= 3:
            alert(
                f"sess_compact_{s}",
                "INFO",
                f"session {s} is {m.group(1)}% from auto-compact",
                repeat=3600,
            )


def check_false_oracle_blocks():
    for l in sh(f"tail -n 200 {PR}/zip_when_ready.log", 10).splitlines():
        m = re.match(r"(\S+Z) BLOCK (SVC-PC-\S+) rc=8 oracle=0\.0", l)
        if not m or ST["heal"].get(m.group(2), 0) >= 3:
            continue
        t = m.group(2)
        p = f"{SP}/{t}/probes/oracle.json"
        try:
            j = json.load(open(p))
        except Exception:
            continue
        if os.path.getmtime(p) > epoch(m.group(1)) + 600:
            continue
        crit = [c for g in (j.get("groups") or []) for c in (g.get("criteria") or [])]
        nerr = sum(
            1 for c in crit if c.get("error") and ERR_RE.search(str(c.get("error")))
        )
        if crit and nerr >= max(1, len(crit) // 2):
            ST["heal"][t] = ST["heal"].get(t, 0) + 1
            if actions_on() and not DRY:
                os.replace(p, f"{SP}/{t}/probes/oracle.infra-{int(now())}.json")
                for mk in glob.glob(f"{SP}/{t}/ZIP_ATTEMPTED.*"):
                    os.remove(mk)
            event(
                "WARN",
                f"[oracle_reprobe] {t} oracle 0.0 was {nerr}/{len(crit)} judge-call errors, not a golden failure; probe cleared for re-run (try {ST['heal'][t]} of 3)",
                dedup=f"orc-{t}-{ST['heal'][t]}",
                gap=60,
            )


def _latest_verdict_file(t, r):
    fs = [
        f
        for f in glob.glob(f"{SP}/{t}/CR.{r}.round*.json")
        if re.search(r"round\d+\.json$", f)
    ]
    return (
        max(fs, key=lambda x: int(re.search(r"round(\d+)\.json$", x).group(1)))
        if fs
        else None
    )


def _latest_major(t, r):
    fs = [
        f
        for f in glob.glob(f"{SP}/{t}/CR.{r}.round*.json")
        if re.search(r"round\d+\.json$", f)
    ]
    if not fs:
        return None
    f = max(fs, key=lambda x: int(re.search(r"round(\d+)\.json$", x).group(1)))
    try:
        j = json.load(open(f))
        return (
            j["major_count"]
            if isinstance(j.get("major_count"), int) and "checks" in j
            else None
        )
    except Exception:
        return None


def _gate_only_park(line):
    """True when a fix-from-reviews 'MAX_ROUNDS reached' park line lists only deterministic actuator gate cells."""
    m = re.search(r"MAX_ROUNDS reached\): (.*)$", line)
    if not m:
        return False
    parts = re.split(r"; (?=\d+\.\d+: )", m.group(1))
    return bool(parts) and all(
        p.split(": ", 1)[-1].startswith("Deterministic actuator check") for p in parts
    )


def check_zip_validity():
    """An unsubmitted zip must belong to a task that still passes: both latest verdicts at zero majors, no DataOS
    rejection without its resolved marker, no live park. 92-0-0 had a zip and was parked with a surviving major at 05:42Z.
    A zip that fails this on two consecutive checks is moved to out/pipe/_quarantine so it cannot be pulled into a batch.
    """
    if not due("zipvalid", 120):
        keep("zipvalid_")
        return
    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    # 01:05Z: the resubmit set stays out of this rule until its park test matches zip_when_ready.sh's (a fix-from-reviews park is
    # stale there); with the exemption it quarantined six finished zips over stale parks.
    dr = set(rd(f"{LN}/DATAOS_REJECTED").split())
    seen = ST.setdefault("zv_seen", {})
    for f in glob.glob(f"{Q}/out/pipe/SVC-PC-*.zip"):
        t = os.path.basename(f)[:-4]
        if t in sub:
            continue
        g, s = _latest_major(t, "glm"), _latest_major(t, "sonnet")
        why = []
        if g is None or s is None:
            why.append("a reviewer verdict is missing or unreadable")
        elif g != 0 or s != 0:
            why.append(f"latest verdict has majors (glm {g}, sonnet {s})")
        if t in dr and not os.path.exists(f"{SP}/{t}/DATAOS_MAJORS_RESOLVED"):
            why.append("DataOS-rejected without a resolved marker")
        try:
            oj = json.load(open(f"{SP}/{t}/probes/oracle.json"))
            orw = oj.get("total_reward")
            if (
                isinstance(orw, (int, float))
                and not oj.get("infra_failure")
                and orw < 1.0
            ):
                why.append(f"oracle probe scores {orw} < 1.0")
                ST.setdefault("zv_oracle", {})[t] = True
        except Exception:
            pass
        # a shipped file changed after the zip was built (14-3-0: zipped 06:07, judge.toml rewritten 06:22 by a fix round):
        # the zip no longer holds the reviewed bytes, and the zip step never rebuilds a task that already has a zip
        try:
            if f"{Q}/tools" not in sys.path:
                sys.path.insert(0, f"{Q}/tools")
            import oracle_refresh as _orf

            nm, nrel = _orf.newest_staged(t)
            if nm > os.path.getmtime(f) + 60:
                why.append(f"shipped file {nrel} changed after the zip was built")
                ST.setdefault("zv_stale", {})[t] = True
            # a reviewer whose newest verdict predates the newest shipped file has not read the bytes in the zip: the zip step
            # can zip mid-fix, on the old verdict, while the re-review is still running (42-3-0 at 07:22, 5-1-0 at 07:24)
            for rv in ("glm", "sonnet"):
                vf = _latest_verdict_file(t, rv)
                if vf and os.path.getmtime(vf) + 5 < nm:
                    why.append(f"{rv} verdict predates {nrel}")
                    ST.setdefault("zv_stale", {})[t] = True
        except Exception:
            pass
        pk = rd(f"{SP}/{t}/PARKED.md")
        if pk and not re.search(
            r"majors still present after|failed, rc=10|check-fix: still blocked", pk
        ):
            last = pk.strip().splitlines()[-1]
            # a park whose surviving findings are all deterministic gate cells says nothing about a zip the actuator already
            # passed: the cells come from a copy taken at re-open time that nothing refreshed after the fix (92-0-0 and 92-1-0
            # were zipped 04:21 by an actuator that passed, then parked 05:42 and 05:52 for the stale cell). A changed file is
            # caught by the rule above.
            if not _gate_only_park(last):
                why.append("parked: " + last[:70])
        if not why:
            seen.pop(t, None)
            ST.get("zv_stale", {}).pop(t, None)
            continue
        seen[t] = seen.get(t, 0) + 1
        if seen[t] < 2 or not actions_on() or DRY:
            continue
        qd = f"{Q}/out/pipe/_quarantine"
        os.makedirs(qd, exist_ok=True)
        shutil.move(f, f"{qd}/{t}.zip")
        if os.path.exists(f"{Q}/out/pipe/{t}.sha256"):
            shutil.move(f"{Q}/out/pipe/{t}.sha256", f"{qd}/{t}.sha256")
        seen.pop(t, None)
        reopen = ST.get("zv_oracle", {}).pop(t, None)
        ST.get("zv_stale", {}).pop(t, None)
        # Only an oracle re-open clears the attempt markers. For a stale zip (a file changed after the zip, or a verdict older
        # than the newest file) the markers stay: clearing them let the zip step re-zip the same stale state within minutes and
        # the guard quarantine it again (16-1-0, 07:36 to 07:56). check_stale_attempts drops the marker when a newer clean
        # verdict pair lands, which is the moment a retry is worth an attempt.
        if reopen:
            for mk in glob.glob(f"{SP}/{t}/ZIP_ATTEMPTED.*"):
                os.remove(mk)
        if reopen:
            _clear_fix_markers(t)
            _prioritize(t)
        event(
            "WARN",
            f"[zip_quarantined] {t} zip moved to out/pipe/_quarantine: {'; '.join(why)[:160]}",
            dedup=f"zq-{t}",
            gap=600,
        )


def _prioritize(t):
    """Put a re-opened task first in the fix dispatcher's next pass (lanes/FIX_FROM_REVIEWS_PRIORITY, read before the
    alphabetical sweep). Without this a task late in the alphabet waits for the whole ~90 minute sweep.
    """
    pf = f"{LN}/FIX_FROM_REVIEWS_PRIORITY"
    if t in [x.strip() for x in rd(pf).splitlines()]:
        return
    with open(pf, "a") as f:
        f.write(t + "\n")


def _promoted_blocking_kinds(t):
    """The BLOCKING kinds in stream-pipe/<t>/checks/promoted_kinds.txt (the promoted-kinds gate's output), sorted; [] when absent."""
    out = set()
    for l in rd(f"{SP}/{t}/checks/promoted_kinds.txt").splitlines():
        m = re.match(r"BLOCKING\s+\S+\s+(\S+)", l)
        if m:
            out.add(m.group(1))
    return sorted(out)


def _block_signature(t, rc, line):
    """What the zip gate blocks on, as a comparable string: the blocked cells (rc=5), the promoted kinds (rc=5 from the
    promoted-kinds gate, whose BLOCK line names no cell; 20:05Z) or the failing criteria of the oracle probe (rc=8)."""
    if rc == "5":
        cells = sorted(set(re.findall(r"\('([a-z_0-9]+)', '\w+'\)", line)))
        kinds = _promoted_blocking_kinds(t) if "promoted kinds" in line else []
        return "cells:" + ",".join(cells) + ("|promoted:" + ",".join(kinds) if kinds else "")
    try:
        oj = json.load(open(f"{SP}/{t}/probes/oracle.json"))
        names = sorted(
            str(c.get("name"))
            for g in oj.get("groups", [])
            for c in (g.get("criteria") or [])
            if isinstance(c, dict) and not c.get("passed")
        )
        return "oracle:" + ",".join(names)
    except Exception:
        return "oracle:?"


def _archive_high_rounds(t):
    """A re-opened task starts a new review cycle, but its old round-2 (or higher) verdict files stay on disk and outrank the
    new round-1 files: the zip step and the actuator take the highest round number per reviewer, so they keep validating the
    old bytes (12-5-0, 10-5-0 and 1-5-0 were re-opened after round 2 and would stall on the old pair, or ship on it if the new
    round-1 reviews found majors). Rename them aside; neither reads a name that does not end in round<N>.json.
    """
    stamp = int(now())
    for r in ("glm", "sonnet"):
        for f in glob.glob(f"{SP}/{t}/CR.{r}.round*.json"):
            m = re.search(r"round(\d+)\.json$", f)
            if m and int(m.group(1)) >= 2:
                os.replace(f, f"{f[:-5]}.pre-reopen-{stamp}.json")


def check_dataos_reviews_promoted():
    """fix_from_dataos.sh re-reviews each task it edits, but writes CR.<r>.dataos.json, a name the zip step and the actuator never
    read: they take the highest CR.<r>.round<N>.json, which is still the pair from before the DataOS fix. Once the verify session
    writes DATAOS_MAJORS_RESOLVED the zip step would ship on the old pair (bytes equal the refreshed workspace) or loop against the
    stale-zip rule. Copy both dataos reviews to the next round number when they are canonical and newer than the newest shipped file
    and newer than the current latest pair, so the latest pair describes the bytes that will ship. mtimes are preserved.
    """
    if not due("promotedataos", 120):
        return
    if f"{Q}/tools" not in sys.path:
        sys.path.insert(0, f"{Q}/tools")
    import oracle_refresh as _orf

    def canon(p):
        try:
            j = json.load(open(p))
        except Exception:
            return False
        return (
            isinstance(j, dict)
            and "overall_verdict" in j
            and isinstance(j.get("checks"), list)
        )

    for d in glob.glob(f"{SP}/SVC-PC-*"):
        gd, sd = f"{d}/CR.glm.dataos.json", f"{d}/CR.sonnet.dataos.json"
        if not (os.path.exists(gd) and os.path.exists(sd)):
            continue
        t = os.path.basename(d)
        if not (canon(gd) and canon(sd)):
            continue
        # 22:20Z: not while a fix cycle is pending (re-open cleared FIX_FROM_REVIEWS_1) or running (lock held): the copy would
        # land in the round slot the re-open just freed, and the cycle then reads it as its own round-2 verdict (17-2-0, 92-4-0).
        if _task_busy(t) or "FIX_FROM_REVIEWS_1" not in rd(f"{SP}/{t}/STATE").split():
            continue
        nm, _rel = _orf.newest_staged(t)
        if min(os.path.getmtime(gd), os.path.getmtime(sd)) + 5 < nm:
            continue
        lg, ls = _latest_verdict_file(t, "glm"), _latest_verdict_file(t, "sonnet")
        if (
            lg
            and ls
            and os.path.getmtime(lg) + 1 >= os.path.getmtime(gd)
            and os.path.getmtime(ls) + 1 >= os.path.getmtime(sd)
        ):
            continue
        n = (
            max(int(re.search(r"round(\d+)\.json$", f).group(1)) for f in (lg, ls) if f)
            + 1
            if (lg or ls)
            else 0
        )
        if actions_on() and not DRY:
            shutil.copy2(gd, f"{d}/CR.glm.round{n}.json")
            shutil.copy2(sd, f"{d}/CR.sonnet.round{n}.json")
            # 21:30Z: a promoted pair with majors has no owner. The dispatcher's FIX_FROM_REVIEWS markers say its cycle is done and
            # the zip loop refuses a pair with majors, so no BLOCK line is written and no gate re-open follows (82-1-0: glm 1 major
            # from 20:13Z, lock free, idle). Hand it back like a gate block, two tries per task, then a person.
            mg, ms = _latest_major_of(gd) or 0, _latest_major_of(sd) or 0
            if (mg or ms) and not _task_busy(t):
                rh = ST.setdefault("reviewer_majors_heal", {})
                rh[t] = rh.get(t, 0) + 1
                if rh[t] <= 2:
                    _clear_fix_markers(t)
                    _prioritize(t)
                    event(
                        "INFO",
                        f"[reviewer_majors_reopen] {t}: the promoted DataOS re-reviews carry majors (glm {mg}, sonnet {ms}); fix markers cleared and the task put first in the dispatcher's next pass (try {rh[t]} of 2)",
                        dedup=f"rmr-{t}-{n}",
                        gap=60,
                    )
                else:
                    event(
                        "CRIT",
                        f"[reviewer_majors_stuck] {t}: majors after the DataOS fix survived {rh[t] - 1} dispatcher cycles (glm {mg}, sonnet {ms}); needs a person",
                        dedup=f"rms-{t}",
                        gap=3600,
                    )
        event(
            "INFO",
            f"[dataos_reviews_promoted] {t}: the fix-from-DataOS reviews (glm maj {_latest_major_of(gd)}, sonnet maj {_latest_major_of(sd)}) are now round {n}, the latest pair the zip step reads",
            dedup=f"dp-{t}-{int(os.path.getmtime(gd))}",
            gap=3600,
        )


def _latest_major_of(path):
    try:
        return json.load(open(path)).get("major_count")
    except Exception:
        return None


def check_stale_attempts():
    """ZIP_ATTEMPTED.<glm file>.<sonnet file> is keyed by file names, so a task whose verdict pair was rewritten after the
    attempt (a re-opened task reruns its rounds under the same names) is never retried by the zip step: 16-1-0 sat behind a 04:42
    marker after its round-2 verdicts were rewritten at 06:20. Drop the marker when the latest pair is clean and newer than it.
    """
    if not due("staleatt", 60):
        keep("review_missing_after_change")
        return
    if f"{Q}/tools" not in sys.path:
        sys.path.insert(0, f"{Q}/tools")
    import oracle_refresh as _orf

    live = live_pairs(procs())
    waiting = []
    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    # 00:35Z: a task on lanes/ZIP_ONLY_LIST is being re-submitted; its old markers must be cleaned like any other task's.
    sub -= {x.strip() for x in rd(f"{LN}/ZIP_ONLY_LIST").split() if x.strip()}
    for d in glob.glob(f"{SP}/SVC-PC-*"):
        t = os.path.basename(d)
        if t in sub or os.path.exists(f"{Q}/out/pipe/{t}.zip"):
            continue
        g, s = _latest_verdict_file(t, "glm"), _latest_verdict_file(t, "sonnet")
        if not g or not s:
            continue
        # a clean pair that predates the task's newest shipped file, with no review running and no re-review after 45 minutes:
        # a hand edit (or a fix whose re-review never started) leaves the task looking reviewed but stuck, and nothing else
        # notices. The zip step skips it, the guard's stale-zip rule pulls any zip, and the dispatcher only re-reviews after
        # its own fix rounds.
        if (
            _latest_major(t, "glm") == 0
            and _latest_major(t, "sonnet") == 0
            and (t, "glm") not in live
            and (t, "sonnet") not in live
        ):
            nm, nrel = _orf.newest_staged(t)
            if (
                min(os.path.getmtime(g), os.path.getmtime(s)) + 5 < nm
                and now() - nm > 2700
            ):
                waiting.append(t.replace("SVC-PC-", ""))
        mk = f"{d}/ZIP_ATTEMPTED.{os.path.basename(g)}.{os.path.basename(s)}"
        if not os.path.exists(mk):
            continue
        newest = max(os.path.getmtime(g), os.path.getmtime(s))
        if os.path.getmtime(mk) + 1 >= newest:
            continue
        if _latest_major(t, "glm") != 0 or _latest_major(t, "sonnet") != 0:
            continue
        if actions_on() and not DRY:
            os.remove(mk)
        event(
            "INFO",
            f"[attempt_marker_stale] {t}: the verdict pair was rewritten after the zip step's last attempt; marker removed so the zip step retries it",
            dedup=f"ams-{t}-{int(newest)}",
            gap=3600,
        )
    if waiting:
        alert(
            "review_missing_after_change",
            "WARN",
            f"{len(waiting)} tasks have clean reviews older than their newest shipped file and nothing is re-reviewing them (a hand edit, or a fix whose re-review never started); the zip step will not take them: {' '.join(waiting[:14])}",
            repeat=3600,
        )


def check_stale_recheck():
    """checks/recheck/summary.csv is a static copy of the actuator's cells taken when a task was re-opened, and
    build_review_union.py folds it into every later union. Nothing refreshes it after the fix, so round 2 kept counting cells
    the fix had cleared, ran a fix round with nothing to fix and parked the task: 44 tasks carry a 'MAX_ROUNDS reached' park,
    13 of them only for gate cells, and 92-0-0 and 92-1-0 had zips the actuator passed at 04:21 before being parked at 05:42
    and 05:52. Expire the copy once a fix has been applied after it: the zip step's next actuator run regenerates the truth,
    and a new block re-opens the task with fresh cells."""
    if not due("stalerecheck", 60):
        return
    for d in glob.glob(f"{SP}/SVC-PC-*/checks/recheck"):
        task_dir = os.path.dirname(os.path.dirname(d))
        t = os.path.basename(task_dir)
        sm = f"{d}/summary.csv"
        stp = f"{task_dir}/STATE"
        if not os.path.exists(sm) or "FIX_FROM_REVIEWS_1" not in rd(stp).split():
            continue
        copied = os.path.getmtime(sm)
        if os.path.getmtime(stp) <= copied:
            continue
        if actions_on() and not DRY:
            os.replace(d, f"{d}.expired-{int(now())}")
        event(
            "INFO",
            f"[recheck_expired] {t}: a fix round was applied after its gate-cell copy was taken; the copy no longer describes the bytes, moved aside",
            dedup=f"rce-{t}-{int(copied)}",
            gap=3600,
        )


def check_review_shapes():
    """A reviewer file that is a complete verdict in a non-canonical shape (checks as an object keyed by id, "verdict" for
    "overall_verdict") is discarded by fix_from_reviews.sh's canon_ok and the whole review is re-run; the re-run often ends as a
    fragment because the sonnet reviewer hit the CLI's default output cap and the extractor kept only the continuation message.
    tools/normalize_reviews.py recovers the complete verdicts without a model call. Also raise the tasks whose reviewer keeps failing.
    """
    if not due("normreviews", 90):
        keep("review_fragments")
        return
    if actions_on() and not DRY:
        out = sh(f"cd {Q} && python3 tools/normalize_reviews.py apply 2>&1", 120)
        for l in out.splitlines():
            m = re.match(
                r"(SVC-PC-\S+) (glm|sonnet) round\d+: recover (in place|quarantined) (\S+) \((.*?)\)",
                l,
            )
            if m:
                _prioritize(m.group(1))
                event(
                    "INFO",
                    f"[review_normalized] {m.group(1)} {m.group(2)}: {m.group(4)} was a complete verdict in a non-canonical shape ({m.group(5)}); recovered without re-running the review",
                    dedup=f"rn-{m.group(1)}-{m.group(2)}-{m.group(4)}",
                    gap=3600,
                )
    stuck = []
    for d in sorted(glob.glob(f"{SP}/SVC-PC-*")):
        for r in ("glm", "sonnet"):
            if len(glob.glob(f"{d}/CR.{r}.round0.bad.*.json")) < 3:
                continue
            try:
                j = json.load(open(f"{d}/CR.{r}.round0.json"))
                if (
                    isinstance(j, dict)
                    and "overall_verdict" in j
                    and isinstance(j.get("checks"), list)
                ):
                    continue
            except Exception:
                pass
            stuck.append(f"{os.path.basename(d).replace('SVC-PC-', '')}:{r}")
    if stuck:
        alert(
            "review_fragments",
            "WARN",
            f"{len(stuck)} reviewer runs have failed to produce a canonical round-0 verdict three or more times: {' '.join(stuck[:12])}",
            repeat=7200,
        )


def _clear_fix_markers(t):
    sp = f"{SP}/{t}/STATE"
    keep_lines = [
        x
        for x in rd(sp).splitlines()
        if not re.fullmatch(r"FIX_FROM_REVIEWS_\d+", x.strip())
    ]
    with open(sp + ".tmp", "w") as f:
        f.write("\n".join(keep_lines) + "\n")
    os.replace(sp + ".tmp", sp)


def _task_busy(t):
    """A fix cycle is running for the task: its per-task lock (fix_from_reviews.lock, taken with flock -n by process_task) is held, or a
    review of it is alive. A shared, non-blocking flock on the existing file conflicts with the dispatcher's exclusive one and creates nothing.
    """
    lp = f"{SP}/{t}/fix_from_reviews.lock"
    if os.path.exists(lp):
        try:
            import fcntl

            fd = os.open(lp, os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                return True
            finally:
                os.close(fd)
        except OSError:
            pass
    return bool(
        sh(
            f"ps -eo args --no-headers | grep -E '[r]un_workspace_review.py --task {t} ' | head -n 1",
            10,
        ).strip()
    )


def check_gate_blocks():
    """The zip gates block a task both reviewers passed (rc=5 a gate check, rc=8 oracle below 1.0). Hand it back to the
    fix dispatcher: persist the actuator's check output where build_review_union.py reads it (rc=5 only; the union builder
    reads probes/oracle.json itself for rc=8), clear the FIX_FROM_REVIEWS markers, and put the task first in the
    dispatcher's priority list. Two tries per task, then a person."""
    gh = ST.setdefault("gate_heal", {})
    seen = ST.setdefault("gate_heal_seen", {})
    sigs = ST.setdefault("gate_sig", {})
    tot = ST.setdefault("gate_total", {})
    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    # 20:05Z: a task on lanes/ZIP_ONLY_LIST is being RE-submitted (batches 6-8's 22 rejected tasks are all on SUBMITTED.txt),
    # so the SUBMITTED skip does not apply to it; the same exemption tools/zip_when_ready.sh got at 19:35Z. Without it,
    # 2-6-0's 19:30:17Z promoted-kinds block was never handed back to the fixer.
    sub -= {x.strip() for x in rd(f"{LN}/ZIP_ONLY_LIST").split() if x.strip()}
    if f"{Q}/tools" not in sys.path:
        sys.path.insert(0, f"{Q}/tools")
    import oracle_refresh as _orf

    # lanes/GATE_HEAL_RESET (one task id per line, with or without the SVC-PC- prefix) gives a task its two tries back, for when a new fix
    # capability or a better instruction means the earlier tries proved nothing (2026-09-19: metadata_leak and rubric_schema blocks the
    # fixer could not express, 12:00). The file is consumed on the pass that reads it.
    rf = f"{LN}/GATE_HEAL_RESET"
    ids = [x.strip() for x in rd(rf).split() if x.strip()]
    if ids and actions_on() and not DRY:
        for x in ids:
            x = x if x.startswith("SVC-PC-") else f"SVC-PC-{x}"
            gh.pop(x, None)
            seen.pop(x, None)
            sigs.pop(x, None)
            tot.pop(x, None)
        with open(rf, "w"):
            pass
        event(
            "INFO",
            f"[gate_heal_reset] {len(ids)} tasks got their gate re-open tries back: {' '.join(ids[:20])}",
            dedup="ghr",
            gap=60,
        )
    # Only a task's NEWEST block line matters: acting on every BLOCK line in the tail would spend both tries of a task in one pass.
    last = {}
    # 2000 lines, not 300: a block older than the tail is invisible, and 35-1-0, 35-6-0, 17-5-0, 26-7-0 and 13-3-0 sat blocked with no line in a 300-line tail
    for l in sh(f"tail -n 2000 {PR}/zip_when_ready.log", 10).splitlines():
        m = re.match(r"(\S+Z) BLOCK (SVC-PC-\S+) rc=([58]) ", l)
        if m:
            last[m.group(2)] = (m.group(1), m.group(3), l)
    for t, (ev, rc, l) in last.items():
        # ISO stamps sort as text: skip a block that is not newer than the newest event already handled for the task. The old test
        # (seen == ev) let two BLOCK lines of one task in the tail take turns resetting "seen", which re-raised the same
        # gate_block_stuck CRIT every hour for 38-6-0.
        if t in sub or ev <= seen.get(t, ""):
            continue
        blk = epoch(ev)
        try:
            newest, _rel = _orf.newest_staged(t)
        except Exception:
            newest = 0
        if rc == "8":
            # An oracle block is acted on while the probe on disk still describes the task as it stands and says below 1.0: a real score
            # (not an infra_failure 0.0) written no earlier than the newest shipped file. The rule this replaces dropped any block older than 25
            # minutes, which left 25-2-0, 70-4-0 and 94-8-0 (the golden misses 1-2 low-weight criteria) unhandled for hours (2026-09-19).
            try:
                pj = f"{SP}/{t}/probes/oracle.json"
                oj = json.load(open(pj))
                cur = oj.get("total_reward")
                pm = os.path.getmtime(pj)
            except Exception:
                continue
            if (
                not isinstance(cur, (int, float))
                or oj.get("infra_failure")
                or cur >= 1.0
                or pm + 5 < newest
            ):
                continue
        # Is the block still about the task as it stands? Four cases say no, and the zip step will retry the task on its own:
        # a file changed after the block; a newer verdict pair landed after it; a verdict is missing; a fix cycle is running or round 2 is
        # still to be decided. The rule this replaces compared the verdict times with STATE's mtime, but the dispatcher appends
        # FIX_FROM_REVIEWS_2 to STATE after the re-reviews land, so a finished task looked mid-fix forever and never got its re-open
        # (10 tasks with two rounds done and zero tries used, 2026-09-19 12:00; 35-1-0, 7-3-0, 8-4-0 and others).
        # A task that already has a zip is not blocked at all.
        vt = []
        for r in ("glm", "sonnet"):
            vf = _latest_verdict_file(t, r)
            if vf:
                try:
                    vt.append(os.path.getmtime(vf))
                except OSError:
                    pass
        st_marks = rd(f"{SP}/{t}/STATE").split()
        if (
            newest > blk + 5
            or len(vt) < 2
            or min(vt) > blk + 5
            or (
                "FIX_FROM_REVIEWS_1" in st_marks
                and "FIX_FROM_REVIEWS_2" not in st_marks
            )
            # 20:35Z: re-opened (markers cleared by this rule) and the fixer has not run yet: the zip loop re-attempts the
            # task as soon as the archive step changes its newest verdict pair (17-2-0: block 56 s after the re-open, fix lock
            # taken 12 s after it), and that block is the pre-fix state, not a new failure. Wait for FIX_FROM_REVIEWS_1.
            or ("FIX_FROM_REVIEWS_1" not in st_marks and gh.get(t, 0) >= 1)
            or _task_busy(t)
        ):
            seen[t] = ev
            continue
        if os.path.exists(f"{Q}/out/pipe/{t}.zip"):
            seen[t] = ev
            continue
        seen[t] = ev
        why = l[l.find("BLOCKED") :][:110]
        sig = _block_signature(t, rc, l)
        # A block that changed shape since the last re-open means that try worked: it cleared what it was aimed at and exposed the next layer
        # (82-4-0: restoring the deliverable heading let judge_scope_over_inclusion see the deliverable, so a hidden over-inclusion showed up). Such
        # a try does not count against the two; six re-opens in total is the ceiling either way.
        if sigs.get(t) is not None and sigs[t] != sig and gh.get(t, 0) >= 1:
            gh[t] = 1
        if gh.get(t, 0) >= 2 or tot.get(t, 0) >= 6:
            event(
                "CRIT",
                f"[gate_block_stuck] {t} was blocked at the zip gates again after {tot.get(t, gh.get(t, 0))} re-opens with no change in what blocks it; needs a person: {why}",
                dedup=f"gbs-{t}",
                gap=3600,
            )
            continue
        src = f"{Q}/_recheck/{t}"
        have_recheck = os.path.exists(f"{src}/summary.csv")
        # A promoted-kinds block (stage_and_zip.sh's gate after the cell gate) leaves its finding in checks/promoted_kinds.txt,
        # which build_review_union.py reads itself; it needs no recheck copy (20:05Z).
        have_promoted = _promoted_blocking_kinds(t) != []
        if rc == "5" and not have_recheck and not have_promoted:
            continue
        if actions_on() and not DRY:
            dst = f"{SP}/{t}/checks/recheck"
            shutil.rmtree(dst, ignore_errors=True)
            if rc == "5" and have_recheck:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copytree(src, dst)
            _clear_fix_markers(t)
            _archive_high_rounds(t)
            _prioritize(t)
        gh[t] = gh.get(t, 0) + 1
        tot[t] = tot.get(t, 0) + 1
        sigs[t] = sig
        event(
            "INFO",
            f"[gate_reopen] {t} blocked at the zip gates (rc={rc}: {why[:80]}); fix markers cleared and the task put first in the dispatcher's next pass (try {gh[t]} of 2, {tot[t]} in total)",
            dedup=f"gro-{t}-{tot[t]}",
            gap=60,
        )


def check_adjudication():
    """Step A, the part the guard owns. tools/adjudicate_loop.sh keeps stream-pipe/<T>/ADJUDICATE.json fresh for every unsubmitted zip: it grades both GLM
    solver runs against the CURRENT rubric and adjudicates each criterion both runs failed (solver error, or a false rejection: the criterion asks for
    something the instruction never asked for, a major at any weight in DataOS 1.5). A zip whose task has a FRESH adjudication (newer than every file of the
    task) with at least one false rejection is moved to out/pipe/_quarantine and the task goes back to the fix dispatcher, whose union builder reads that
    adjudication as a finding. Two tries per task, then a person. A task listed in lanes/ADJUDICATION_CONTROL is left alone (the control group: uploaded
    unchanged so DataOS's verdict measures the adjudicator's precision). A zip with no fresh adjudication is NOT touched here: that is the advisory phase;
    requiring one is a separate switch. A task with a fix running is skipped (the fix changes the files and the adjudication goes stale anyway).
    """
    if not due("adjudication", 120):
        return
    ah = ST.setdefault("adj_heal", {})
    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    ctrl = set(rd(f"{LN}/ADJUDICATION_CONTROL").split())
    if f"{Q}/tools" not in sys.path:
        sys.path.insert(0, f"{Q}/tools")
    import oracle_refresh as _orf

    for f in sorted(glob.glob(f"{Q}/out/pipe/SVC-PC-*.zip")):
        t = os.path.basename(f)[:-4]
        if t in sub or t in ctrl or t.replace("SVC-PC-", "") in ctrl:
            continue
        pipe = f"{SP}/{t}"
        aj = f"{pipe}/ADJUDICATE.json"
        if rd(f"{pipe}/ADJUDICATE.status").strip() != "OK" or not os.path.exists(aj):
            continue
        try:
            newest, _rel = _orf.newest_staged(t)
        except Exception:
            newest = 0
        if os.path.getmtime(aj) + 5 < newest:
            continue
        try:
            d = json.load(open(aj))
        except Exception:
            continue
        frs = [
            str(a.get("criterion_id"))
            for a in d.get("adjudications", [])
            if isinstance(a, dict) and a.get("verdict") == "false_rejection"
        ]
        if not frs or _task_busy(t):
            continue
        if ah.get(t, 0) >= 2:
            event(
                "CRIT",
                f"[adjudication_stuck] {t} still has {len(frs)} false rejection(s) ({', '.join(frs[:6])}) after 2 fix rounds; needs a person",
                dedup=f"adjs-{t}",
                gap=3600,
            )
            continue
        if actions_on() and not DRY:
            qd = f"{Q}/out/pipe/_quarantine"
            os.makedirs(qd, exist_ok=True)
            shutil.move(f, f"{qd}/{t}.zip")
            if os.path.exists(f"{Q}/out/pipe/{t}.sha256"):
                shutil.move(f"{Q}/out/pipe/{t}.sha256", f"{qd}/{t}.sha256")
            _clear_fix_markers(t)
            _archive_high_rounds(t)
            _prioritize(t)
        ah[t] = ah.get(t, 0) + 1
        event(
            "INFO",
            f"[adjudication_reopen] {t}: a fresh adjudication found {len(frs)} false rejection(s) ({', '.join(frs[:6])}); zip quarantined and the task sent back to the fixer (try {ah[t]} of 2)",
            dedup=f"adjr-{t}-{ah[t]}",
            gap=60,
        )


def check_oracle_freshness():
    """zip_when_ready.sh reuses probes/oracle.json whenever it parses, so a task fixed after its probe would ship on a
    pre-fix score (15-2-0, 2026-09-19: probe written 2026-09-18 21:54, golden .docx rewritten 04:30, zipped 06:09 as
    oracle=1.0). Re-probe every unsubmitted task that has a zip or a clean latest verdict pair and whose shipped files are
    newer than its probe (tools/oracle_refresh.py; the new probe replaces the old only when it is a real score). Also
    raise the deterministic 'Prompt is too long' case, which the zip step retries forever.
    """
    if not due("oraclefresh", 300):
        keep("oracle_stale")
        keep("oracle_prompt_too_long")
        return
    out = sh(f"cd {Q} && python3 tools/oracle_refresh.py scan-json", 180)
    try:
        stale = json.loads(out)
    except Exception:
        stale = None
    if stale is None:
        alert(
            "oracle_stale_scan",
            "WARN",
            "tools/oracle_refresh.py scan-json did not return JSON; the oracle freshness check is blind",
            repeat=3600,
        )
    else:
        att = ST.setdefault("orf", {})
        first = ST.setdefault("orf_first", {})
        names = [x["task"] for x in stale]
        for t in list(first):
            if t not in names:
                del first[t]
        for t in names:
            first.setdefault(t, now())
        # [o] keeps pgrep from matching the sh -c that carries this very command line
        running = sh("pgrep -f '[o]racle_refresh.py run'", 5).strip()
        todo = [
            t
            for t in names
            if att.get(t, {}).get("n", 0) < 6
            and now() - att.get(t, {}).get("t", 0) > 1800
        ][:8]
        if todo and not running and actions_on() and not DRY:
            spawn(
                f"python3 tools/oracle_refresh.py run {' '.join(todo)} >> {PR}/oracle_refresh.out 2>&1"
            )
            for t in todo:
                a = att.setdefault(t, {"n": 0, "t": 0})
                a["n"] += 1
                a["t"] = now()
            event(
                "INFO",
                f"[oracle_refresh] re-probing {len(todo)} tasks whose files changed after their oracle probe: {' '.join(x.replace('SVC-PC-', '') for x in todo)}",
                dedup="orf-" + ",".join(todo),
                gap=600,
            )
        old = [
            t
            for t in names
            if now() - first.get(t, now()) > 2400
            and any(x["task"] == t and x["zip"] for x in stale)
        ]
        if old:
            alert(
                "oracle_stale",
                "WARN",
                f"{len(old)} zipped tasks still have an oracle probe older than their files after 40 minutes, so 'oracle 1.0' is unverified for the bytes in the zip: {' '.join(x.replace('SVC-PC-', '') for x in old[:12])}",
            )
    # the deterministic judge-input failure: the emulator prompt exceeds the model window, every pass, forever
    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    bad = []
    for lg in sorted(glob.glob(f"{SP}/SVC-PC-*/probes/oracle*.log")):
        t = lg.split("/")[-3]
        if t in sub or t in bad or os.path.exists(f"{Q}/out/pipe/{t}.zip"):
            continue
        try:
            with open(lg, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 8000))
                has_err = b"Prompt is too long" in f.read()
        except Exception:
            continue
        if not has_err:
            continue
        try:
            oj = json.load(open(f"{SP}/{t}/probes/oracle.json"))
            if oj.get("total_reward") is not None and not oj.get("infra_failure"):
                continue  # a later probe produced a real score
        except Exception:
            pass
        bad.append(t)
    if bad:
        alert(
            "oracle_prompt_too_long",
            "WARN",
            f"{len(bad)} tasks can never finish the oracle probe (the judge prompt is too long for the emulator, the zip step retries them every pass): {' '.join(x.replace('SVC-PC-', '') for x in bad)}. Needs a decision: a larger-context judge for the probe, or a smaller judge input",
            repeat=7200,
        )


DUP_LOOPS = (
    ("zip_when_ready", r"^\s*(/bin/)?bash (/root/qc/)?tools/zip_when_ready\.sh"),
    ("watchdog", r"^\s*(/bin/)?bash (/root/qc/)?tools/watchdog\.sh"),
    ("fix_priority_loop", r"^\s*(/bin/)?bash (/root/qc/)?tools/fix_priority_loop\.sh"),
    ("fix_from_reviews", r"^\s*(/bin/)?bash (/root/qc/)?tools/fix_from_reviews\.sh"),
    ("adjudicate_loop", r"^\s*(/bin/)?bash (/root/qc/)?tools/adjudicate_loop\.sh"),
)


def dup_roots(rows, pat):
    """rows: (pid, ppid, sid, etimes, args). Root instances of the loop matching pat, oldest first (see the 17:20Z note)."""
    ids = {p for p, pp, sid, et, a in rows if re.match(pat, a)}
    roots = [(et, p) for p, pp, sid, et, a in rows if p in ids and pp not in ids and (sid == p or pp != 1)]
    return [p for et, p in sorted(roots, reverse=True)]


def check_dups():
    rows = []
    for l in sh("ps -eo pid,ppid,sid,etimes,args --no-headers", 15).splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.*)", l)
        if m:
            rows.append((int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5)))
    n = ST.setdefault("dup_seen", {})
    for name, pat in DUP_LOOPS:
        roots = dup_roots(rows, pat)
        if len(roots) <= 1:
            n[name] = 0
            continue
        n[name] = n.get(name, 0) + 1
        if n[name] < 2:
            continue
        keep, extra = roots[-1], roots[:-1]
        if actions_on() and not DRY and due(f"dup_kill_{name}", 600):
            for p in extra:
                try:
                    os.kill(p, 15)
                except OSError:
                    pass
            n[name] = 0
            event(
                "CRIT",
                f"[dup_{name}] {len(roots)} root instances of {name} were running (pids {roots}); TERM sent to the older {extra}, kept {keep}; in-flight per-task cycles keep running",
                dedup=f"dupkill-{name}-{keep}",
                gap=600,
            )
        else:
            alert(
                f"dup_{name}",
                "WARN",
                f"{len(roots)} root instances of {name} are running (pids {roots}); two loops can act on the same task twice",
            )


def present(f):
    try:
        json.load(open(f))
        return True
    except Exception:
        return False


def check_sweeper(rows_ps):
    if not due("sweep", 180):
        keep("review_stuck_")
        keep("sweep_")
        return
    if any("bulk_review.sh _prompts/sweep" in a for _, _, a in rows_ps):
        keep("review_stuck_")
        return
    live = live_pairs(rows_ps)
    started, queued = {}, set()
    for l in rd(f"{PR}/bulk_review.log").splitlines():
        m = re.match(r"(\S+Z) START (SVC-PC-\S+) (glm|sonnet) ", l)
        if m:
            started[(m.group(2), m.group(3))] = epoch(m.group(1))
    for _, _, a in rows_ps:
        m = re.search(r"bulk_review\.sh (_prompts/wave\d+\.txt)", a)
        if m:
            for t in rd(f"{Q}/{m.group(1)}").split():
                for r in ("glm", "sonnet"):
                    if (t, r) not in started:
                        queued.add((t, r))
    limited = [
        x
        for x in glob.glob(f"{LN}/.claude-*.limited_until")
        if int(rd(x).strip() or 0) > now()
    ]
    gaps, stuck = {}, []
    for d in sorted(os.listdir(SP)):
        if not d.startswith("SVC-PC-") or "." in d:
            continue
        for r in ("glm", "sonnet"):
            if (
                present(f"{SP}/{d}/CR.{r}.round0.json")
                or (d, r) in live
                or (d, r) in queued
            ):
                continue
            if now() - started.get((d, r), 0) < 900:
                continue
            k = f"{d}|{r}"
            if ST["attempts"].get(k, 0) >= 3:
                stuck.append(k)
            else:
                gaps[d] = gaps.get(d, 0) + 1
    for k in stuck[:10]:
        alert(
            f"review_stuck_{k}",
            "CRIT",
            f"{k} failed 3 sweep attempts and still has no verdict; needs a person",
            repeat=3600,
        )
    if not gaps:
        return
    if len(limited) >= 4 and not backups():
        alert(
            "sweep_paused",
            "WARN",
            f"{len(gaps)} tasks have review gaps but {len(limited)} lanes are limit-hit; the sweep waits for the reset",
        )
        return
    if not actions_on():
        alert(
            "sweep_off",
            "WARN",
            f"{len(gaps)} tasks have review gaps and actions are off",
        )
        return
    if not DRY:
        with open(f"{PR}/sweep_auto.txt", "w") as f:
            f.write("\n".join(sorted(gaps)) + "\n")
    for d in gaps:
        for r in ("glm", "sonnet"):
            if not present(f"{SP}/{d}/CR.{r}.round0.json") and (d, r) not in live:
                ST["attempts"][f"{d}|{r}"] = ST["attempts"].get(f"{d}|{r}", 0) + 1
    spawn(
        "setsid nohup bash tools/bulk_review.sh _prompts/sweep_auto.txt 16 > _prompts/bulk_sweep_auto.nohup.log 2>&1 < /dev/null &"
    )
    event(
        "INFO",
        f"[sweep] review sweep launched for {len(gaps)} tasks with a missing round0 verdict",
        dedup=f"sweep-{int(now() // 600)}",
        gap=300,
    )


def check_stuck_states():
    if not due("stuck", 600):
        keep("stuck_")
        return
    last_zip = {}
    for l in sh(f"tail -n 400 {PR}/zip_when_ready.log", 10).splitlines():
        m = re.match(r"(\S+) (ZIPPED|BLOCK|SKIP|ORACLE) (SVC-PC-\S+) ?(rc=\d+)?", l)
        if m:
            last_zip[m.group(3)] = (m.group(2), m.group(4), epoch(m.group(1)))
    blocked, no_r2 = [], []
    for d in sorted(os.listdir(SP)):
        if not d.startswith("SVC-PC-") or "." in d:
            continue
        fr = [
            int(x) for x in re.findall(r"FIX_FROM_REVIEWS_(\d+)", rd(f"{SP}/{d}/STATE"))
        ]
        if not fr:
            continue
        v = {}
        for r in ("glm", "sonnet"):
            fs = [
                f
                for f in glob.glob(f"{SP}/{d}/CR.{r}.round*.json")
                if re.search(r"round\d+\.json$", f)
            ]
            if fs:
                f = max(
                    fs, key=lambda x: int(re.search(r"round(\d+)\.json$", x).group(1))
                )
                try:
                    v[r] = (
                        int(re.search(r"round(\d+)\.json$", f).group(1)),
                        json.load(open(f)).get("major_count"),
                    )
                except Exception:
                    pass
        if len(v) < 2 or not all(isinstance(x[1], int) for x in v.values()):
            continue
        short = d.replace("SVC-PC-", "")
        clean = all(x[1] == 0 for x in v.values())
        if (
            clean
            and max(fr) == 1
            and last_zip.get(d, ("", "", 0))[:2] == ("BLOCK", "rc=5")
            and now() - last_zip[d][2] > 5400
            and not any(
                os.path.getmtime(f) > last_zip[d][2]
                for f in glob.glob(f"{SP}/{d}/CR.*.round*.json")
            )
            and not os.path.exists(f"{Q}/out/pipe/{d}.zip")
        ):
            blocked.append(short)
        if not clean and max(fr) == 1 and min(x[0] for x in v.values()) >= 1:
            no_r2.append(short)
    if blocked:
        alert(
            "stuck_gate_blocked",
            "WARN",
            f"{len(blocked)} tasks are clean on both reviewers but the zip gates block them and nothing re-opens them: {' '.join(blocked[:12])}",
            repeat=1800,
        )
    first = ST.setdefault("no_r2_first", {})
    for k in [k for k in first if k not in no_r2]:
        del first[k]
    for k in no_r2:
        first.setdefault(k, now())
    stale = [k for k in no_r2 if now() - first[k] > 7200]
    if stale:
        alert(
            "stuck_no_round2",
            "WARN",
            f"{len(stale)} tasks have had majors after round 1 for over 2 hours with no round 2 started: {' '.join(stale[:12])}",
            repeat=1800,
        )


def housekeeping():
    if not due("house", 3600):
        return
    for f in glob.glob(f"{LN}/.claude-*.benched"):
        n = os.path.basename(f)[: -len(".benched")]
        if (
            not os.path.exists(f"{LN}/{n}.reset_at")
            and now() - os.path.getmtime(f) > 5400
            and not DRY
        ):
            os.remove(f)
    pl = f"{SP}/PIPE.log"
    if (
        os.path.exists(pl)
        and "queue drained" not in sh(f"tail -n 3 {pl}", 5)
        and not any("pipe_batch.sh" in a for _, _, a in procs())
        and not DRY
    ):
        with open(pl, "a") as f:
            f.write(
                f"{iso()} queue drained (pipe_batch.sh retired 2026-09-19, replaced by bulk_review, fix_from_reviews, zip_when_ready; silences the watchdog PIPE DEAD alert)\n"
            )


# ---------------------------------------------------------------- main
# ---------------------------------------------------------------- scan storm (2026-09-19 16:40Z)
# 15:59Z: 15 scans x 24 workers = 553 processes on a 10-core cgroup, every CPU period throttled, 874 per-file timeouts, load
# near 190, and the host_load alert fired three times with nothing acting on it. scan_slots.py now bounds the scans at the
# source; these rules watch that bound and the CPU it protects. Read-only, except that the slotted cgroup is re-created
# (cgroups vanish on reboot) unless lanes/GUARD_ACTIONS_OFF exists.
HEAVY_SCAN_RE = re.compile(
    r"tools/(source_reliability_scan|answer_preexposure_scan)\.py"
)
SLOT_CG_PATH = "/sys/fs/cgroup/qc-scans-slotted"
SCAN_CG_PATHS = ("/sys/fs/cgroup/qc-scans", SLOT_CG_PATH)
FIXLOG = f"{PR}/fix_from_reviews.log"
SLOTLOG = f"{PR}/scan_slots.log"


def scan_storm_findings(s, held):
    """Pure rules. s: snapshot dict from scan_snapshot; held: {condition: seconds it has been continuously true}."""
    out = []
    allowed = s["slots"] * (s["workers"] + 1)
    detail = (
        f"{s['procs']} heavy scan processes in {s['jobs']} jobs (slot limit {s['slots']} x {s['workers']} workers = {allowed}), "
        f"{s['unslotted']} outside the slots, scan cgroups {s['throttle_pct']}% throttled"
    )
    if held.get("many", 0) >= 600:
        out.append(
            (
                "scan_storm",
                "CRIT",
                detail
                + "; the limit is not holding (a scan bypassing scan_slots.py, SCAN_SLOTS_OFF, or a fail-open)",
            )
        )
    elif held.get("unslotted", 0) >= 1800:
        out.append(
            (
                "scan_storm",
                "WARN",
                detail
                + "; scans that started before the slot limit or bypassed it are still running",
            )
        )
    if held.get("throttled", 0) >= 600 and s["waiters"] > 0:
        out.append(
            (
                "scan_cpu_saturated",
                "WARN",
                f"scan CPU groups throttled for 10+ min with {s['waiters']} scans queued for a slot, so scans run slow (the per-file limit is CPU time; only the 1200 s wall backstop fires on starvation); {detail}",
            )
        )
    if s["timeouts_10m"] >= 1:
        lvl = "CRIT" if s["timeouts_10m"] >= 20 else "WARN"
        out.append(
            (
                "scan_timeouts",
                lvl,
                f"{s['timeouts_10m']} scan files skipped in 10 min: {s.get('wall_10m', 0)} on the wall backstop (starvation), the rest over the per-file CPU budget (an expensive file; raise PER_FILE_TIMEOUT_S in the scan if it recurs); each is listed in that scan's <out>.skipped sidecar and the task's scan verdict was computed without it; {detail}",
            )
        )
    if s["oldest_wait"] > 1200:
        out.append(
            (
                "scan_slot_wait",
                "WARN",
                f"a scan has waited {int(s['oldest_wait'] // 60)} min for a slot ({s['waiters']} waiting, {s['held']} of {s['slots']} slots held): raise lanes/SCAN_SLOTS or look for a stuck holder",
            )
        )
    if s["oldest_hold"] > 1800:
        out.append(
            (
                "scan_slot_stuck",
                "WARN",
                f"a scan has held a slot for {int(s['oldest_hold'] // 60)} min (normal is seconds to a few minutes)",
            )
        )
    if s["slots_off"]:
        out.append(
            (
                "scan_slots_off",
                "WARN",
                "lanes/SCAN_SLOTS_OFF exists: scan admission control is switched off",
            )
        )
    if s["failopen"] > 0:
        out.append(
            (
                "scan_slots_failopen",
                "WARN",
                f"scan_slots.py failed open {s['failopen']} time(s) in 10 min (see _prompts/scan_slots.log): scans ran without a slot",
            )
        )
    return out


def _int_of(text, default):
    try:
        return int(text.split()[0])
    except Exception:
        return default


def scan_snapshot(rows):
    t = now()
    waiting_pids = set()
    for w in glob.glob(f"{LN}/scan_slots/wait.*"):
        try:
            waiting_pids.add(int(w.rsplit(".", 1)[1]))
        except ValueError:
            pass
    heavy = [(p, e, a) for p, e, a in rows if HEAVY_SCAN_RE.search(a) and p not in waiting_pids]
    jobs, unslotted = set(), 0
    for p, _, a in heavy:
        m, k = HEAVY_SCAN_RE.search(a), re.search(r"--task (\S+)", a)
        jobs.add((m.group(1), k.group(1) if k else ""))
        if "qc-scans-slotted" not in rd(f"/proc/{p}/cgroup"):
            unslotted += 1
    per = thr = 0
    prev = ST.setdefault("scan_prev", {})
    for cg in SCAN_CG_PATHS:
        cur = {}
        for line in rd(f"{cg}/cpu.stat").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit():
                cur[parts[0]] = int(parts[1])
        old = prev.get(cg)
        if old and cur.get("nr_periods", 0) >= old.get("nr_periods", 0):
            per += cur.get("nr_periods", 0) - old.get("nr_periods", 0)
            thr += cur.get("nr_throttled", 0) - old.get("nr_throttled", 0)
        prev[cg] = {k: cur.get(k, 0) for k in ("nr_periods", "nr_throttled")}
    slots = _int_of(rd(f"{LN}/SCAN_SLOTS"), 3)
    held_n, oldest_hold = 0, 0
    for i in range(16):
        f = rd(f"{LN}/scan_slots/slot.{i}").split()
        try:
            if len(f) >= 4 and os.path.exists(f"/proc/{int(f[0])}"):
                held_n += 1
                oldest_hold = max(oldest_hold, t - int(f[3]))
        except ValueError:
            pass
    waits = []
    for w in glob.glob(f"{LN}/scan_slots/wait.*"):
        f = rd(w).split()
        try:
            if len(f) >= 3 and os.path.exists(f"/proc/{int(w.rsplit('.', 1)[1])}"):
                waits.append(t - int(f[2]))
        except ValueError:
            pass
    try:
        size = os.path.getsize(FIXLOG)
    except OSError:
        size = 0
    pos, n_new, n_wall = ST.get("scan_log_pos"), 0, 0
    if pos is not None and 0 <= pos <= size and size - pos <= 16_000_000:
        with open(FIXLOG, "rb") as f:
            f.seek(pos)
            chunk = f.read()
            n_new, n_wall = chunk.count(b"TIMEOUT>"), chunk.count(b"(wall-backstop)")
    ST["scan_log_pos"] = size
    ST["scan_to"] = [x for x in ST.get("scan_to", []) if t - x[0] <= 600] + (
        [[t, n_new, n_wall]] if n_new else []
    )
    failopen = sum(
        1
        for l in rd(SLOTLOG)[-65536:].splitlines()
        if "FAIL-OPEN" in l and t - epoch(l.split()[0]) <= 600
    )
    return {
        "procs": len(heavy),
        "jobs": len(jobs),
        "unslotted": unslotted,
        "slots": slots,
        "workers": _int_of(rd(f"{LN}/SCAN_WORKERS"), 4),
        "throttle_pct": int(100 * thr / per) if per else 0,
        "held": held_n,
        "oldest_hold": oldest_hold,
        "waiters": len(waits),
        "oldest_wait": max(waits) if waits else 0,
        "timeouts_10m": sum(x[1] for x in ST["scan_to"]),
        "wall_10m": sum(x[2] for x in ST["scan_to"] if len(x) > 2),
        "failopen": failopen,
        "slots_off": os.path.exists(f"{LN}/SCAN_SLOTS_OFF"),
    }


def _adopt_stray_holders():
    """A slot holder outside the slotted cgroup (module loaded before the cgroup code existed, or a failed cgroup write) is moved in
    with its workers, so it competes for the slotted cores it was admitted for and not for the unslotted group's."""
    moved = []
    for i in range(16):
        f = rd(f"{LN}/scan_slots/slot.{i}").split()
        try:
            pid = int(f[0])
        except (IndexError, ValueError):
            continue
        if not os.path.exists(f"/proc/{pid}") or "qc-scans-slotted" in rd(f"/proc/{pid}/cgroup"):
            continue
        todo, seen = [pid], []
        while todo:
            p = todo.pop()
            seen.append(p)
            todo += [int(c) for c in rd(f"/proc/{p}/task/{p}/children").split() if c.isdigit()]
        for p in seen:
            try:
                with open(f"{SLOT_CG_PATH}/cgroup.procs", "w") as fh:
                    fh.write(str(p))
            except OSError:
                pass
        moved.append(pid)
    if moved:
        event("INFO", f"[scan_holder_adopted] moved slot holders {moved} and their workers into {SLOT_CG_PATH}", dedup=f"adopt-{moved}", gap=600)


def check_scan_storm(rows):
    if actions_on() and not DRY:
        try:
            os.makedirs(SLOT_CG_PATH, exist_ok=True)
            cores = max(1, min(32, _int_of(rd(f"{LN}/SCAN_CORES"), 16)))
            for fname, want in (("cpu.weight", "50"), ("cpu.max", f"{cores * 100000} 100000")):
                p = f"{SLOT_CG_PATH}/{fname}"
                if rd(p).strip() != want:
                    with open(p, "w") as f:
                        f.write(want)
        except OSError:
            pass
    if actions_on() and not DRY:
        _adopt_stray_holders()
    s = scan_snapshot(rows)
    since, held = ST.setdefault("scan_since", {}), {}
    conds = {
        "many": s["procs"] > max(60, 2 * s["slots"] * (s["workers"] + 1)),
        "unslotted": s["unslotted"] > 0,
        "throttled": s["throttle_pct"] >= 90,
    }
    for k, on in conds.items():
        if on:
            since.setdefault(k, now())
            held[k] = now() - since[k]
        else:
            since.pop(k, None)
    for key, level, msg in scan_storm_findings(s, held):
        alert(key, level, msg)


def one_pass():
    rows = procs()
    for fn in (
        lambda: check_loops(rows),
        check_zip_integrity,
        check_zip_validity,
        check_host,
        lambda: check_scan_storm(rows),
        lambda: check_reviews(rows),
        check_lanes,
        check_sessions,
        check_false_oracle_blocks,
        check_gate_blocks,
        check_adjudication,
        check_dataos_reviews_promoted,
        check_stale_attempts,
        check_stale_recheck,
        check_review_shapes,
        check_oracle_freshness,
        check_dups,
        lambda: check_sweeper(rows),
        check_stuck_states,
        housekeeping,
    ):
        try:
            fn()
        except Exception as e:
            alert(
                "guard_check_error",
                "WARN",
                f"a check raised {type(e).__name__}: {str(e)[:120]}",
                repeat=1800,
            )
    end_pass()
    save()
    if not DRY:
        with open(HB, "w") as f:
            f.write(str(int(now())) + "\n")


def status():
    load()
    act = {k: v for k, v in ST["alerts"].items() if v.get("active")}
    print(
        f"heartbeat age: {int(now() - float(rd(HB).strip() or 0))}s | active conditions: {len(act)} | swaps: {list(ST['swaps'])} | actions {'ON' if actions_on() else 'OFF'} | backups {[os.path.basename(b) for b in backups()]}"
    )
    for k, v in sorted(act.items()):
        print(f"  {v['level']:4s} [{k}] {v['msg'][:170]}")


def main():
    global DRY
    args = sys.argv[1:]
    cmd = args[0] if args else "run"
    if "--dry" in args:
        DRY = True
    if cmd == "status":
        return status()
    load()
    if cmd == "swap" and len(args) > 1:
        print(swap(f"/root/{args[1]}", "manual"))
        return save()
    if cmd == "restore" and len(args) > 1:
        print(restore(args[1], force=True))
        return save()
    if cmd == "once":
        one_pass()
        return
    if os.path.exists(PIDF):
        try:
            p = int(rd(PIDF).strip())
            if (
                p != os.getpid()
                and os.path.exists(f"/proc/{p}")
                and "guard_rt" in rd(f"/proc/{p}/cmdline")
            ):
                print("guard already running", p)
                return
        except Exception:
            pass
    with open(PIDF, "w") as f:
        f.write(str(os.getpid()))
    if "gate_heal_seen" not in ST:
        # blocks already in the log (12-6-0 and 15-5-0) were re-opened by hand at 03:12Z; only new rc=5 blocks are handled
        ST["gate_heal_seen"], ST["gate_heal"] = {}, {}
        for l in rd(f"{PR}/zip_when_ready.log").splitlines():
            m = re.match(r"(\S+Z) BLOCK (SVC-PC-\S+) rc=5 ", l)
            if m:
                ST["gate_heal_seen"][m.group(2)] = m.group(1)
                ST["gate_heal"][m.group(2)] = 1
    if not ST["seen_zipped"]:
        # first start: ZIPPED lines already in the log were handled by hand (false ZIPPED, 02:42Z), only new ones are checked
        for l in rd(f"{PR}/zip_when_ready.log").splitlines():
            m = re.match(r"(\S+) ZIPPED (SVC-PC-\S+)", l)
            if m:
                ST["seen_zipped"].append(m.group(1) + m.group(2))
    emit(
        "INFO",
        f"guard_rt START pid={os.getpid()} loop={LOOP}s actions={'on' if actions_on() else 'off'}",
    )
    while True:
        one_pass()
        time.sleep(LOOP)


if __name__ == "__main__":
    main()
