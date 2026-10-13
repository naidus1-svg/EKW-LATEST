#!/usr/bin/env python3
"""After a gate re-open, ignore further zip-gate blocks on the task until the fixer has run once.
Why (2026-09-19 20:35Z): the re-open archives round>=2 verdicts, which makes an older pair the newest; the zip loop keys its
attempt marker by file names, so it re-attempted 17-2-0 at 20:19:58Z, 56 seconds after the re-open and before any fix, and
logged a second BLOCK at 20:20:17Z. Only the fix lock (taken 12 seconds after the re-open) kept the guard from spending the
task's second and last try on it. Rule: a block on a task that has been re-opened (gate_heal >= 1) and whose STATE carries no
FIX_FROM_REVIEWS_1 yet is the pre-fix state, not a new failure; mark it seen and wait.
Usage: python3 patch_guard_reopen_wait.py [GUARD=/root/qc/tools/guard_rt.py] -> writes GUARD.new, compile-checked, GUARD
untouched. Refuses unless the anchor occurs exactly once.
"""

import py_compile
import sys

GUARD = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/guard_rt.py"

ANCHOR = """        if (
            newest > blk + 5
            or len(vt) < 2
            or min(vt) > blk + 5
            or (
                "FIX_FROM_REVIEWS_1" in st_marks
                and "FIX_FROM_REVIEWS_2" not in st_marks
            )
            or _task_busy(t)
        ):
            seen[t] = ev
            continue"""

NEW = """        if (
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
            continue"""

src = open(GUARD, encoding="utf-8").read()
n = src.count(ANCHOR)
if n != 1:
    print(f"REFUSED: anchor occurs {n} times (need exactly 1)")
    sys.exit(2)
out = src.replace(ANCHOR, NEW)
open(GUARD + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(GUARD + ".new", doraise=True)
print(f"wrote {GUARD}.new ({len(out) - len(src):+d} bytes), compiled")
