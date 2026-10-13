#!/usr/bin/env python3
"""Make guard_rt.py's check_gate_blocks hand a RE-submitted task back to the fixer when the zip gates block it.
Why (2026-09-19 20:05Z): 2-6-0 was blocked by the promoted-kinds gate at 19:30:17Z and nothing re-opened it. Three skips
in check_gate_blocks hit every one of the 22 calibration tasks: (a) `if t in sub` drops any task on SUBMITTED.txt, and
all 22 are on it from batches 6-8 (the zip loop got the same exemption for lanes/ZIP_ONLY_LIST at 19:35Z, the guard did
not); (b) an rc=5 block needs _recheck/<t>/summary.csv, which the cell gate writes, while the promoted-kinds gate writes
checks/promoted_kinds.txt instead (the union builder reads that file itself, so no recheck copy is needed); (c) the block
signature for a promoted-kinds block names no cell, so every such block looked identical and two of them would have
raised gate_block_stuck even when the first re-open cleared what it was aimed at.
Usage: python3 patch_guard_gate_resubmit.py [GUARD=/root/qc/tools/guard_rt.py] -> writes GUARD.new, compile-checked,
GUARD untouched. Refuses unless every anchor occurs exactly once.
"""

import py_compile
import sys

GUARD = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/guard_rt.py"

A1 = """    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    if f"{Q}/tools" not in sys.path:
        sys.path.insert(0, f"{Q}/tools")
    import oracle_refresh as _orf

    # lanes/GATE_HEAL_RESET"""

R1 = """    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    # 20:05Z: a task on lanes/ZIP_ONLY_LIST is being RE-submitted (batches 6-8's 22 rejected tasks are all on SUBMITTED.txt),
    # so the SUBMITTED skip does not apply to it; the same exemption tools/zip_when_ready.sh got at 19:35Z. Without it,
    # 2-6-0's 19:30:17Z promoted-kinds block was never handed back to the fixer.
    sub -= {x.strip() for x in rd(f"{LN}/ZIP_ONLY_LIST").split() if x.strip()}
    if f"{Q}/tools" not in sys.path:
        sys.path.insert(0, f"{Q}/tools")
    import oracle_refresh as _orf

    # lanes/GATE_HEAL_RESET"""

A2 = """        src = f"{Q}/_recheck/{t}"
        have_recheck = os.path.exists(f"{src}/summary.csv")
        if rc == "5" and not have_recheck:
            continue
        if actions_on() and not DRY:
            dst = f"{SP}/{t}/checks/recheck"
            shutil.rmtree(dst, ignore_errors=True)
            if rc == "5":
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copytree(src, dst)"""

R2 = """        src = f"{Q}/_recheck/{t}"
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
                shutil.copytree(src, dst)"""

A3 = '''def _block_signature(t, rc, line):
    """What the zip gate blocks on, as a comparable string: the blocked cells (rc=5) or the failing criteria of the oracle probe (rc=8)."""
    if rc == "5":
        return "cells:" + ",".join(
            sorted(set(re.findall(r"\\('([a-z_0-9]+)', '\\w+'\\)", line)))
        )'''

R3 = '''def _promoted_blocking_kinds(t):
    """The BLOCKING kinds in stream-pipe/<t>/checks/promoted_kinds.txt (the promoted-kinds gate's output), sorted; [] when absent."""
    out = set()
    for l in rd(f"{SP}/{t}/checks/promoted_kinds.txt").splitlines():
        m = re.match(r"BLOCKING\\s+\\S+\\s+(\\S+)", l)
        if m:
            out.add(m.group(1))
    return sorted(out)


def _block_signature(t, rc, line):
    """What the zip gate blocks on, as a comparable string: the blocked cells (rc=5), the promoted kinds (rc=5 from the
    promoted-kinds gate, whose BLOCK line names no cell; 20:05Z) or the failing criteria of the oracle probe (rc=8)."""
    if rc == "5":
        cells = sorted(set(re.findall(r"\\('([a-z_0-9]+)', '\\w+'\\)", line)))
        kinds = _promoted_blocking_kinds(t) if "promoted kinds" in line else []
        return "cells:" + ",".join(cells) + ("|promoted:" + ",".join(kinds) if kinds else "")'''

src = open(GUARD, encoding="utf-8").read()
for name, a in (("A1", A1), ("A2", A2), ("A3", A3)):
    n = src.count(a)
    if n != 1:
        print(f"REFUSED: anchor {name} occurs {n} times (need exactly 1)")
        sys.exit(2)
out = src.replace(A1, R1).replace(A2, R2).replace(A3, R3)
open(GUARD + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(GUARD + ".new", doraise=True)
print(f"wrote {GUARD}.new ({len(out) - len(src):+d} bytes), compiled")
