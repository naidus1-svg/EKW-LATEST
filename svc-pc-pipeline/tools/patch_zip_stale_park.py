#!/usr/bin/env python3
"""Make tools/zip_when_ready.sh's stale_park() treat a park as stale when both latest reviewer verdicts are newer than it.
Why (2026-09-19 20:10Z): the dispatcher writes "N major finding(s) still present after round2 (MAX_ROUNDS reached)", which
the phrase list in stale_park never matched, so every fix-from-reviews park skipped its task in the zip loop for good,
whatever later reviews said. 17-2-0: parked 03:19Z, clean round-3 verdicts, DATAOS_MAJORS_RESOLVED set at 19:03Z, never
attempted. The reviewers re-read the bytes after a park and the actuator re-checks the deterministic side at the zip step,
so a park older than the current verdict pair is not evidence about the bytes as they stand.
Usage: python3 patch_zip_stale_park.py [SCRIPT=/root/qc/tools/zip_when_ready.sh] -> writes SCRIPT.new, `bash -n` checked,
SCRIPT untouched. Refuses unless the anchor occurs exactly once and `latest()` is defined before it.
"""

import subprocess
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/zip_when_ready.sh"

ANCHOR = """stale_park() { grep -qE 'majors still present after [0-9]+ fix rounds|failed, rc=10|check-fix: still blocked' "$1"; }
"""

NEW = """# 20:10Z: a park is also stale when BOTH latest reviewer verdicts are newer than it (the reviewers re-read the bytes after the
# park, and the actuator re-checks the deterministic side at the zip step). The dispatcher writes "N major finding(s) still
# present after round2 (MAX_ROUNDS reached)", which the phrase list never matched, so every fix-from-reviews park skipped its
# task here for good (17-2-0: parked 03:19Z, clean round-3 verdicts, DATAOS_MAJORS_RESOLVED set 19:03Z, never attempted).
stale_park() {
  grep -qE 'majors still present after [0-9]+ fix rounds|failed, rc=10|check-fix: still blocked' "$1" && return 0
  local d g s
  d=$(dirname "$1"); g=$(latest "$d" glm); s=$(latest "$d" sonnet)
  [ -n "$g" ] && [ -n "$s" ] && [ "$1" -ot "$g" ] && [ "$1" -ot "$s" ]
}
"""

src = open(SCRIPT, encoding="utf-8").read()
n = src.count(ANCHOR)
if n != 1:
    print(f"REFUSED: anchor occurs {n} times (need exactly 1)")
    sys.exit(2)
if src.find("latest() {") < 0 or src.find("latest() {") > src.find(ANCHOR):
    print("REFUSED: latest() is not defined before stale_park()")
    sys.exit(2)
out = src.replace(ANCHOR, NEW)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
r = subprocess.run(["bash", "-n", SCRIPT + ".new"], capture_output=True, text=True)
if r.returncode != 0:
    print("REFUSED: bash -n failed:", r.stderr.strip())
    sys.exit(2)
print(f"wrote {SCRIPT}.new ({len(out) - len(src):+d} bytes), bash -n ok")
