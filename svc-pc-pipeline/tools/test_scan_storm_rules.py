#!/usr/bin/env python3
"""Tests for the scan-storm guard rules. Usage: python3 test_scan_storm_rules.py [PATH to a patched guard_rt.py]
The rules are a pure function of a snapshot, so cases run with no filesystem access; the last case builds a real snapshot
from the live process table (read-only). Exit code = number of failures."""

import importlib.machinery
import importlib.util
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/guard_rt.py.new"
spec = importlib.util.spec_from_loader(
    "guard_rt_under_test",
    importlib.machinery.SourceFileLoader("guard_rt_under_test", path),
)
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

BASE = dict(
    procs=12,
    jobs=3,
    unslotted=0,
    slots=3,
    workers=4,
    throttle_pct=40,
    held=3,
    oldest_hold=30,
    waiters=2,
    oldest_wait=60,
    timeouts_10m=0,
    wall_10m=0,
    failopen=0,
    slots_off=False,
)
FAILS = []


def got(held=None, **kw):
    s = dict(BASE, **kw)
    return {(k, lvl) for k, lvl, _ in G.scan_storm_findings(s, held or {})}


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)


check("quiet snapshot raises nothing", got() == set())
check(
    "205 processes held 700 s is CRIT scan_storm",
    got(procs=205, held={"many": 700}) == {("scan_storm", "CRIT")},
)
check(
    "205 processes held only 500 s is silent",
    got(procs=205, held={"many": 500}) == set(),
)
check(
    "unslotted scans held 2000 s is WARN scan_storm",
    got(unslotted=25, held={"unslotted": 2000}) == {("scan_storm", "WARN")},
)
check(
    "unslotted scans held 100 s is silent",
    got(unslotted=25, held={"unslotted": 100}) == set(),
)
check(
    "CRIT replaces the WARN for the same key",
    got(procs=205, unslotted=200, held={"many": 700, "unslotted": 2000})
    == {("scan_storm", "CRIT")},
)
check(
    "0 timeouts silent, 1 WARN, 20 CRIT",
    (got(timeouts_10m=0), got(timeouts_10m=1), got(timeouts_10m=20))
    == (set(), {("scan_timeouts", "WARN")}, {("scan_timeouts", "CRIT")}),
)
check(
    "wall-backstop count appears in the timeouts text",
    "3 on the wall backstop"
    in G.scan_storm_findings(dict(BASE, timeouts_10m=5, wall_10m=3), {})[0][2],
)
check(
    "slot wait: 1000 s silent, 1300 s WARN",
    (got(oldest_wait=1000), got(oldest_wait=1300))
    == (set(), {("scan_slot_wait", "WARN")}),
)
check(
    "a slot held 2000 s is WARN scan_slot_stuck",
    got(oldest_hold=2000) == {("scan_slot_stuck", "WARN")},
)
check(
    "kill switch file present is WARN",
    got(slots_off=True) == {("scan_slots_off", "WARN")},
)
check("fail-open lines are WARN", got(failopen=2) == {("scan_slots_failopen", "WARN")})
check(
    "throttled 700 s with waiters WARN; without waiters or for 100 s silent",
    (
        got(held={"throttled": 700}),
        got(waiters=0, held={"throttled": 700}),
        got(held={"throttled": 100}),
    )
    == ({("scan_cpu_saturated", "WARN")}, set(), set()),
)
msg = G.scan_storm_findings(dict(BASE, procs=205, jobs=41), {"many": 700})[0][2]
check(
    "CRIT text names the counts and the limit",
    "205 heavy scan processes in 41 jobs" in msg
    and "slot limit 3 x 4 workers = 15" in msg,
)
snap = G.scan_snapshot(G.procs())
check(
    "a live snapshot builds with every key",
    set(snap) == set(BASE) and all(v is not None for v in snap.values()),
)
print(f"{len(FAILS)} failure(s)")
sys.exit(len(FAILS))
