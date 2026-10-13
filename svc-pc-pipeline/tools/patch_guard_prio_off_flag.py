#!/usr/bin/env python3
"""guard_rt.py: touch lanes/FIX_PRIORITY_LOOP_OFF to stop the priority loop for good (same shape as ADJUDICATE_LOOP_OFF).
Why (2026-09-19 22:58Z): the coordinator stopped fix_priority_loop.sh at 22:51Z because the direct and Fable fix agents own the 22
open tasks; the guard relaunched it 3 minutes later and its Opus plan-and-apply fixer took 88-0-0's lock one second after that.
Usage: python3 patch_guard_prio_off_flag.py [SCRIPT=/root/qc/tools/guard_rt.py] -> writes SCRIPT.new, py_compile checked.
"""

import py_compile
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/guard_rt.py"
OLD = (
    "    alive_prio = any(\n"
    '        "fix_priority_loop.sh" in a and re.match(r"\\s*(/bin/)?bash\\b", a) for a in args\n'
    "    )\n"
)
NEW = (
    "    # touch lanes/FIX_PRIORITY_LOOP_OFF to stop the priority loop for good: kill it once, then the guard leaves it alone\n"
    "    # (2026-09-19 22:58Z: the direct and Fable fix agents own the 22 open tasks; the loop's fixer took 88-0-0's lock 1 s after\n"
    "    # the guard relaunched it)\n"
    '    alive_prio = os.path.exists(f"{LN}/FIX_PRIORITY_LOOP_OFF") or any(\n'
    '        "fix_priority_loop.sh" in a and re.match(r"\\s*(/bin/)?bash\\b", a) for a in args\n'
    "    )\n"
)

src = open(SCRIPT, encoding="utf-8").read()
if src.count(OLD) != 1:
    print(f"REFUSED: anchor count {src.count(OLD)} != 1")
    sys.exit(2)
out = src.replace(OLD, NEW)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(SCRIPT + ".new", doraise=True)
print(f"wrote {SCRIPT}.new: FIX_PRIORITY_LOOP_OFF flag honoured; py_compile ok")
