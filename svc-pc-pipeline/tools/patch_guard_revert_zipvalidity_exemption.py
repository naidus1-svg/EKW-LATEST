#!/usr/bin/env python3
"""Revert the zip-validity half of patch_guard_stale_attempts_resubmit.py; keep the stale-attempts half.
Why (2026-09-20 01:05Z): letting check_zip_validity see the re-submitted tasks made it quarantine six finished zips (9-5-0, 21-3-0,
38-1-0, 17-2-0, 2-6-0, 12-6-0) over "live park" lines that the corrected park rule (patch_zip_park_and_logs.py) already treats
as stale; the validity rule still reads a fix-from-reviews park as live. Until its park test is aligned, the resubmit set is
excluded from it again, as it was before 00:35Z.
Usage: python3 patch_guard_revert_zipvalidity_exemption.py [GUARD=/root/qc/tools/guard_rt.py] -> edits GUARD in place after a
compile check of the result; refuses unless the anchor occurs exactly once.
"""

import py_compile
import sys

GUARD = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/guard_rt.py"

BAD = """    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    # 00:35Z: a re-submitted task's zip is validated like any other (it can go stale or lose its marker before upload).
    sub -= {x.strip() for x in rd(f"{LN}/ZIP_ONLY_LIST").split() if x.strip()}
    dr = set(rd(f"{LN}/DATAOS_REJECTED").split())
"""
GOOD = """    sub = set(rd(f"{Q}/SUBMITTED.txt").split())
    # 01:05Z: the resubmit set stays out of this rule until its park test matches zip_when_ready.sh's (a fix-from-reviews park is
    # stale there); with the exemption it quarantined six finished zips over stale parks.
    dr = set(rd(f"{LN}/DATAOS_REJECTED").split())
"""

src = open(GUARD, encoding="utf-8").read()
n = src.count(BAD)
if n != 1:
    print(f"REFUSED: anchor occurs {n} times (need exactly 1)")
    sys.exit(2)
out = src.replace(BAD, GOOD)
open(GUARD + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(GUARD + ".new", doraise=True)
import os

os.replace(GUARD + ".new", GUARD)
print("reverted the zip-validity exemption; compiled")
