#!/usr/bin/env python3
"""Tests for the 20:05Z gate re-open change. Usage: python3 test_gate_resubmit.py [PATH to the patched guard_rt.py]
Loads the module from the path, stubs rd() so no live file is read, checks the two helpers and the ZIP_ONLY_LIST
exemption logic as text. Exit code = number of failures."""

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

FAILS = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)


FILES = {}
G.rd = lambda p: FILES.get(p, "")

T = "SVC-PC-2-6-0"
PK = f"{G.SP}/{T}/checks/promoted_kinds.txt"

# helper 1: no file -> []
check("kinds: absent file -> []", G._promoted_blocking_kinds(T) == [])
FILES[PK] = (
    f"# {T}: 1 blocking-safe finding(s), 13 excluded finding(s)\n"
    f"BLOCKING  {T}  fabricated_unfilenamed_fact/absent_record  names absent record 'Stock Plan'\n"
    f"EXCLUDED  {T}  criterion_groundedness/unreachable_criterion  deliverables_02/c8b: token '$95'\n"
    f"BLOCKING  {T}  aaa/first  something else\n"
)
check(
    "kinds: BLOCKING lines only, sorted",
    G._promoted_blocking_kinds(T)
    == ["aaa/first", "fabricated_unfilenamed_fact/absent_record"],
)

# helper 2: signature keeps the old cell format when the block is a cell block
cell_line = "2026-09-19T12:00:00Z BLOCK SVC-PC-2-6-0 rc=5 oracle=1.0 [gate] BLOCKED cells [('metadata_leak', 'FAIL'), ('rubric_schema', 'FAIL')]"
check(
    "sig: cell block unchanged format",
    G._block_signature(T, "5", cell_line) == "cells:metadata_leak,rubric_schema",
)
pk_line = "2026-09-19T19:30:17Z BLOCK SVC-PC-2-6-0 rc=5 oracle=1.0 [gate] BLOCKED by promoted kinds: 1 blocking finding(s), see checks/promoted_kinds.txt"
check(
    "sig: promoted block names the kinds",
    G._block_signature(T, "5", pk_line)
    == "cells:|promoted:aaa/first,fabricated_unfilenamed_fact/absent_record",
)
FILES[PK] = f"# {T}: 0 blocking-safe finding(s)\nEXCLUDED  {T}  x/y  z\n"
check(
    "sig: promoted block with no BLOCKING line falls back to the cell format",
    G._block_signature(T, "5", pk_line) == "cells:",
)

# exemption: the patched text subtracts ZIP_ONLY_LIST from the SUBMITTED set inside check_gate_blocks, before the tail scan
src = open(path, encoding="utf-8").read()
i = src.find("def check_gate_blocks")
j = src.find("def check_adjudication")
body = src[i:j]
check(
    "exemption: ZIP_ONLY_LIST subtracted inside check_gate_blocks",
    'sub -= {x.strip() for x in rd(f"{LN}/ZIP_ONLY_LIST")' in body,
)
check(
    "exemption: before the BLOCK-line scan",
    body.find("ZIP_ONLY_LIST") < body.find("tail -n 2000"),
)
check(
    "recheck: promoted block accepted without a recheck copy",
    'if rc == "5" and not have_recheck and not have_promoted:' in body,
)
check(
    "recheck: copy only when the recheck exists",
    'if rc == "5" and have_recheck:' in body,
)

print(f"{len(FAILS)} failure(s)")
sys.exit(len(FAILS))
