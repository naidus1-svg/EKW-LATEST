#!/usr/bin/env python3
"""zip_when_ready.sh: a fix-from-reviews park no longer blocks an attempt, and the two remaining silent skips log.
Why (2026-09-19 21:20Z): the dispatcher appends PARKED.md in the same second its last re-review lands (21-3-0: sonnet verdict
19:54:36Z, park 19:54:37Z), so the 20:10Z rule "park older than both latest verdicts" never matched the parks it was written
for, and 21-3-0 sat marked, 0/0, oracle 1.0, unattempted, with no log line. Since 20:12Z the union ranks non-promoted scan
findings as minor, so a fix-from-reviews park reached with a 0/0 reviewer pair means only gate-visible findings (or none)
survived, and the promoted-kinds gate decides that at the zip step; a park with reviewer majors never reaches the attempt
anyway (the 0/0 check follows). The park skip and the attempt-marker skip were the last two `continue`s with no log line.
Usage: python3 patch_zip_park_and_logs.py [SCRIPT=/root/qc/tools/zip_when_ready.sh] -> writes SCRIPT.new, `bash -n` checked.
"""

import subprocess
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/zip_when_ready.sh"

A1 = """  grep -qE 'majors still present after [0-9]+ fix rounds|failed, rc=10|check-fix: still blocked' "$1" && return 0
"""
R1 = """  # 21:20Z: a fix-from-reviews park is stale too. It is written in the same second as the last re-review, so the verdict-age
  # test below never matched it (21-3-0), and since the 20:12Z union change its surviving majors are gate-visible findings the
  # actuator adjudicates at the zip step; a park with reviewer majors never reaches the attempt (the 0/0 check follows).
  grep -qE 'majors still present after [0-9]+ fix rounds|fix-from-reviews - [0-9]+ major finding|failed, rc=10|check-fix: still blocked' "$1" && return 0
"""

A2 = """    if [ -f "$d/PARKED.md" ] && ! stale_park "$d/PARKED.md"; then continue; fi
"""
R2 = """    if [ -f "$d/PARKED.md" ] && ! stale_park "$d/PARKED.md"; then
      [ -f lanes/ZIP_ONLY_LIST ] && log "SKIP $t parked: $(tail -1 "$d/PARKED.md" | cut -c1-100)"
      continue
    fi
"""

A3 = """    [ -f "$d/ZIP_ATTEMPTED.$(basename "$g").$(basename "$s")" ] && continue
"""
R3 = """    if [ -f "$d/ZIP_ATTEMPTED.$(basename "$g").$(basename "$s")" ]; then
      [ -f lanes/ZIP_ONLY_LIST ] && log "SKIP $t pair already attempted ($(basename "$g") $(basename "$s"))"
      continue
    fi
"""

src = open(SCRIPT, encoding="utf-8").read()
for name, a in (("A1", A1), ("A2", A2), ("A3", A3)):
    n = src.count(a)
    if n != 1:
        print(f"REFUSED: anchor {name} occurs {n} times (need exactly 1)")
        sys.exit(2)
out = src.replace(A1, R1).replace(A2, R2).replace(A3, R3)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
r = subprocess.run(["bash", "-n", SCRIPT + ".new"], capture_output=True, text=True)
if r.returncode != 0:
    print("REFUSED: bash -n failed:", r.stderr.strip())
    sys.exit(2)
print(f"wrote {SCRIPT}.new ({len(out) - len(src):+d} bytes), bash -n ok")
