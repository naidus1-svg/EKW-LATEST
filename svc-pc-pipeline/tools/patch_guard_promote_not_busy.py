#!/usr/bin/env python3
"""guard_rt.check_dataos_reviews_promoted: never promote while a fix cycle is pending or running.
Why (2026-09-19 22:20Z): a gate re-open archives round>=2 and clears FIX_FROM_REVIEWS markers; the promotion then copied the
DataOS-fixer re-reviews (older bytes) into the freed round-2 slot before the cycle started (17-2-0 at 20:19:58Z, 92-4-0 at
20:29:43Z). When the cycle reached its own round 2 it found canon-shaped round-2 files already there and parked on them
(17-2-0: "5 majors still present after round2", pair mtimes 18:31/18:41Z against bytes fixed 20:22 to 20:39Z). Rule: skip the
task while its fix lock is held or its STATE has no FIX_FROM_REVIEWS_1 (re-open pending); the pair is promoted on a later pass.
Usage: python3 patch_guard_promote_not_busy.py [GUARD=/root/qc/tools/guard_rt.py] -> writes GUARD.new, compile-checked.
"""

import py_compile
import sys

GUARD = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/guard_rt.py"

ANCHOR = """        t = os.path.basename(d)
        if not (canon(gd) and canon(sd)):
            continue
        nm, _rel = _orf.newest_staged(t)
"""

NEW = """        t = os.path.basename(d)
        if not (canon(gd) and canon(sd)):
            continue
        # 22:20Z: not while a fix cycle is pending (re-open cleared FIX_FROM_REVIEWS_1) or running (lock held): the copy would
        # land in the round slot the re-open just freed, and the cycle then reads it as its own round-2 verdict (17-2-0, 92-4-0).
        if _task_busy(t) or "FIX_FROM_REVIEWS_1" not in rd(f"{SP}/{t}/STATE").split():
            continue
        nm, _rel = _orf.newest_staged(t)
"""

src = open(GUARD, encoding="utf-8").read()
n = src.count(ANCHOR)
if n != 1:
    print(f"REFUSED: anchor occurs {n} times (need exactly 1)")
    sys.exit(2)
out = src.replace(ANCHOR, NEW)
open(GUARD + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(GUARD + ".new", doraise=True)
print(f"wrote {GUARD}.new ({len(out) - len(src):+d} bytes), compiled")
