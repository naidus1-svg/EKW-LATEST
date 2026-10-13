#!/usr/bin/env python3
"""guard_rt.check_dataos_reviews_promoted: a promoted DataOS re-review pair that carries majors is handed back to the dispatcher.
Why (2026-09-19 21:30Z): after fix_from_dataos.sh edits a task, its glm+sonnet re-reviews are promoted to the next round number.
When that pair has majors nobody owns the task: the dispatcher's FIX_FROM_REVIEWS_1/2 markers say its cycle is done, the zip loop
refuses a pair with majors, so no BLOCK line is ever written and no gate re-open follows. 82-1-0 sat like that from 20:13Z
(glm round 3, 1 major, lock free) until a hand-off by hand at 21:25Z; 5-4-0 (2/2) and 88-0-0 (1/1) were heading the same way.
Rule: at promotion time, if either promoted verdict has major_count > 0 and no fix is running, clear the FIX_FROM_REVIEWS
markers and put the task first in the priority list, twice per task, then a CRIT for a person.
Usage: python3 patch_guard_reviewer_majors.py [GUARD=/root/qc/tools/guard_rt.py] -> writes GUARD.new, compile-checked.
"""

import py_compile
import sys

GUARD = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/guard_rt.py"

ANCHOR = """        if actions_on() and not DRY:
            shutil.copy2(gd, f"{d}/CR.glm.round{n}.json")
            shutil.copy2(sd, f"{d}/CR.sonnet.round{n}.json")
"""

NEW = """        if actions_on() and not DRY:
            shutil.copy2(gd, f"{d}/CR.glm.round{n}.json")
            shutil.copy2(sd, f"{d}/CR.sonnet.round{n}.json")
            # 21:30Z: a promoted pair with majors has no owner. The dispatcher's FIX_FROM_REVIEWS markers say its cycle is done and
            # the zip loop refuses a pair with majors, so no BLOCK line is written and no gate re-open follows (82-1-0: glm 1 major
            # from 20:13Z, lock free, idle). Hand it back like a gate block, two tries per task, then a person.
            mg, ms = _latest_major_of(gd) or 0, _latest_major_of(sd) or 0
            if (mg or ms) and not _task_busy(t):
                rh = ST.setdefault("reviewer_majors_heal", {})
                rh[t] = rh.get(t, 0) + 1
                if rh[t] <= 2:
                    _clear_fix_markers(t)
                    _prioritize(t)
                    event(
                        "INFO",
                        f"[reviewer_majors_reopen] {t}: the promoted DataOS re-reviews carry majors (glm {mg}, sonnet {ms}); fix markers cleared and the task put first in the dispatcher's next pass (try {rh[t]} of 2)",
                        dedup=f"rmr-{t}-{n}",
                        gap=60,
                    )
                else:
                    event(
                        "CRIT",
                        f"[reviewer_majors_stuck] {t}: majors after the DataOS fix survived {rh[t] - 1} dispatcher cycles (glm {mg}, sonnet {ms}); needs a person",
                        dedup=f"rms-{t}",
                        gap=3600,
                    )
"""

src = open(GUARD, encoding="utf-8").read()
n = src.count(ANCHOR)
if n != 1:
    print(f"REFUSED: anchor occurs {n} times (need exactly 1)")
    sys.exit(2)
for helper in (
    "def _latest_major_of(",
    "def _task_busy(",
    "def _clear_fix_markers(",
    "def _prioritize(",
):
    if helper not in src:
        print(f"REFUSED: {helper} missing")
        sys.exit(2)
out = src.replace(ANCHOR, NEW)
open(GUARD + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(GUARD + ".new", doraise=True)
print(f"wrote {GUARD}.new ({len(out) - len(src):+d} bytes), compiled")
