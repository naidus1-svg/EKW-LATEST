"""Where does lane time go? Parse /root/qc/_v7/logs/*.log (runner log) for runs in the last 24h:
per task attempts, wall time, time per phase, and what sent each attempt back (the loop-back reason).
"""

import glob, os, re, collections, datetime as dt

TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) (SVC-PC-[\d-]+)\[(\w)\] (.*)$")
now = dt.datetime.utcnow()
phase_tot = collections.Counter()
back = collections.Counter()
rows = []
for p in glob.glob("/root/qc/_v7/logs/SVC-PC-*.log"):
    ev = []
    for ln in open(p, errors="replace"):
        m = TS.match(ln.rstrip())
        if m:
            t = dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ")
            if (now - t).total_seconds() < 86400:
                ev.append((t, m.group(4)))
    if not ev:
        continue
    task = os.path.basename(p)[:-4]
    attempts = sum(1 for _, s in ev if s.startswith("=== attempt"))
    # phase durations: fix = attempt start -> "fix/rebuild step rc"; oracle = -> "oracle total_reward";
    # regrade = -> "eval-regrade verdict"; verify = -> "adversarial verify"
    marks = [
        ("fix", "fix/rebuild step rc"),
        ("oracle", "oracle total_reward"),
        ("regrade", "eval-regrade verdict"),
        ("verify", "adversarial verify"),
    ]
    last = None
    for t, s in ev:
        if s.startswith("=== attempt"):
            last = t
            continue
        for name, key in marks:
            if s.startswith(key) and last:
                phase_tot[name] += (t - last).total_seconds()
                last = t
        for key in (
            "eval-regrade not PASS",
            "adversarial verify NOT-READY",
            "gated zip refused",
            "golden stuck",
            "PARKED",
            "DEFERRED",
            "transient",
            "READY ->",
        ):
            if key.lower() in s.lower():
                back[key] += 1
        if "oracle total_reward=" in s and "=1.0" not in s:
            back["oracle < 1.0"] += 1
    wall = (ev[-1][0] - ev[0][0]).total_seconds() / 3600
    level = "L3" if task.endswith("-0-0") else "L2"
    final = ev[-1][1][:70]
    rows.append((level, task, attempts, wall, final))

rows.sort(key=lambda r: -r[3])
for lv in ("L2", "L3"):
    rs = [r for r in rows if r[0] == lv]
    if not rs:
        continue
    print(
        "%s: %d tasks, median attempts %s, mean wall %.1fh"
        % (
            lv,
            len(rs),
            sorted(r[2] for r in rs)[len(rs) // 2],
            sum(r[3] for r in rs) / len(rs),
        )
    )
tot = sum(phase_tot.values()) or 1
print(
    "time by phase (all lanes, 24h): "
    + ", ".join(
        "%s %.0fh (%d%%)" % (k, v / 3600, 100 * v / tot)
        for k, v in phase_tot.most_common()
    )
)
print(
    "loop-back / outcome counts: "
    + ", ".join("%s=%d" % kv for kv in back.most_common())
)
print("longest L2 runs:")
for r in [r for r in rows if r[0] == "L2"][:12]:
    print("  %s attempts=%d wall=%.1fh last: %s" % (r[1], r[2], r[3], r[4]))
