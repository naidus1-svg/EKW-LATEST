#!/usr/bin/env python3
"""Tests for guard_rt.dup_roots (pure function). Usage: python3 test_dup_roots.py [PATH to a patched guard_rt.py]. Exit = failures."""

import importlib.machinery
import importlib.util
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/guard_rt.py.new"
spec = importlib.util.spec_from_loader(
    "g", importlib.machinery.SourceFileLoader("g", path)
)
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
PAT = dict(G.DUP_LOOPS)["fix_priority_loop"]
L = "bash tools/fix_priority_loop.sh"
FAILS = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)


# (pid, ppid, sid, etimes, args)
rows = [
    (100, 1, 100, 5000, L),  # setsid launch, oldest root
    (101, 100, 100, 4000, L),  # its per-task cycle
    (
        102,
        1,
        100,
        3000,
        L,
    ),  # orphaned cycle of a dead launcher with sid 100 style: not a root
    (200, 1, 200, 1000, L),  # second setsid launch
    (
        300,
        250,
        250,
        10,
        L,
    ),  # launched from a live interactive shell (ppid 250 does not match)
    (
        400,
        1,
        77,
        900,
        "/bin/bash /root/qc/tools/fix_priority_loop.sh",
    ),  # orphan of a nohup launch from a dead shell: invisible, never killed
    (500, 1, 500, 50, "bash tools/zip_when_ready.sh"),  # a different loop
]
check(
    "three roots, oldest first, orphans and cycles excluded",
    G.dup_roots(rows, PAT) == [100, 200, 300],
)
check(
    "a single root with orphans is one root",
    G.dup_roots([r for r in rows if r[0] in (100, 101, 102)], PAT) == [100],
)
check("no matching process gives no roots", G.dup_roots([rows[-1]], PAT) == [])
check(
    "the other loop's pattern sees only its own root",
    G.dup_roots(rows, dict(G.DUP_LOOPS)["zip_when_ready"]) == [500],
)
check(
    "dispatcher pattern accepts the /bin/bash and /root/qc/ forms",
    G.dup_roots(
        [(9, 1, 9, 1, "/bin/bash /root/qc/tools/fix_from_reviews.sh")],
        dict(G.DUP_LOOPS)["fix_from_reviews"],
    )
    == [9],
)
print(f"{len(FAILS)} failure(s)")
sys.exit(len(FAILS))
