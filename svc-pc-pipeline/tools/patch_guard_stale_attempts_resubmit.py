#!/usr/bin/env python3
"""guard_rt.py: check_stale_attempts and check_zip_validity stop skipping tasks that are being RE-submitted.
Why (2026-09-20 00:35Z): both rules start with `if t in sub` (SUBMITTED.txt). Every one of the 22 calibration tasks is on that list
from batches 6-8, so the stale-attempt cleaner never dropped their ZIP_ATTEMPTED markers: 21-3-0 and 17-2-0 sat with fresh clean
round-2 pairs behind markers written for older files of the same names (the third SUBMITTED-keyed rule found today; the gate
re-open and the zip loop got the same exemption at 19:35Z and 20:05Z). Same exemption: a task on lanes/ZIP_ONLY_LIST is not
"submitted" for these rules. The zip-validity rule gets it too, so a resubmit zip that goes stale is quarantined like any other.
Usage: python3 patch_guard_stale_attempts_resubmit.py [GUARD=/root/qc/tools/guard_rt.py] -> writes GUARD.new, compile-checked.
"""

import py_compile
import sys

GUARD = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/guard_rt.py"

A1 = """    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    for d in glob.glob(f"{SP}/SVC-PC-*"):
        t = os.path.basename(d)
        if t in sub or os.path.exists(f"{Q}/out/pipe/{t}.zip"):
            continue
        g, s = _latest_verdict_file(t, "glm"), _latest_verdict_file(t, "sonnet")
"""
R1 = """    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    # 00:35Z: a task on lanes/ZIP_ONLY_LIST is being re-submitted; its old markers must be cleaned like any other task's.
    sub -= {x.strip() for x in rd(f"{LN}/ZIP_ONLY_LIST").split() if x.strip()}
    for d in glob.glob(f"{SP}/SVC-PC-*"):
        t = os.path.basename(d)
        if t in sub or os.path.exists(f"{Q}/out/pipe/{t}.zip"):
            continue
        g, s = _latest_verdict_file(t, "glm"), _latest_verdict_file(t, "sonnet")
"""

A2 = """    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    dr = set(rd(f"{LN}/DATAOS_REJECTED").split())
    seen = ST.setdefault("zv_seen", {})
"""
R2 = """    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    # 00:35Z: a re-submitted task's zip is validated like any other (it can go stale or lose its marker before upload).
    sub -= {x.strip() for x in rd(f"{LN}/ZIP_ONLY_LIST").split() if x.strip()}
    dr = set(rd(f"{LN}/DATAOS_REJECTED").split())
    seen = ST.setdefault("zv_seen", {})
"""

src = open(GUARD, encoding="utf-8").read()
for name, a in (("A1", A1), ("A2", A2)):
    n = src.count(a)
    if n != 1:
        print(f"REFUSED: anchor {name} occurs {n} times (need exactly 1)")
        sys.exit(2)
out = src.replace(A1, R1).replace(A2, R2)
open(GUARD + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(GUARD + ".new", doraise=True)
print(f"wrote {GUARD}.new ({len(out) - len(src):+d} bytes), compiled")
