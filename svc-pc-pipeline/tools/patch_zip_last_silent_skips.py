#!/usr/bin/env python3
"""zip_when_ready.sh: the last two unlogged skips (a reviewer verdict missing; the latest pair not clean or not canonical) log.
Why (2026-09-19 23:25Z): 67-3-0 sat marked and unattempted with no log line because its glm round-2 verdict had no major_count
(not canonical), which the clean-pair check drops with a bare `|| continue`; the missing-verdict check on the line before it is
the same shape. Both now log when ZIP_ONLY_LIST is active, like the park and attempt-marker skips.
Usage: python3 patch_zip_last_silent_skips.py [SCRIPT=/root/qc/tools/zip_when_ready.sh] -> writes SCRIPT.new, `bash -n` checked.
"""

import re
import subprocess
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/zip_when_ready.sh"

A1 = """    g=$(latest "$d" glm); s=$(latest "$d" sonnet); [ -n "$g" ] && [ -n "$s" ] || continue
"""
R1 = """    g=$(latest "$d" glm); s=$(latest "$d" sonnet)
    if [ -z "$g" ] || [ -z "$s" ]; then
      [ -f lanes/ZIP_ONLY_LIST ] && log "SKIP $t no canonical verdict pair (glm=${g:-none} sonnet=${s:-none})"
      continue
    fi
"""

lines = open(SCRIPT, encoding="utf-8").read().splitlines(keepends=True)
src = "".join(lines)
if src.count(A1) != 1:
    print(f"REFUSED: anchor A1 occurs {src.count(A1)} times")
    sys.exit(2)
idx = [
    i
    for i, l in enumerate(lines)
    if "major_count')==0" in l and l.rstrip().endswith("|| continue")
]
if len(idx) != 1:
    print(
        f"REFUSED: clean-pair line with a trailing '|| continue' occurs {len(idx)} times"
    )
    sys.exit(2)
i = idx[0]
lines[i] = re.sub(
    r"\|\| continue\s*$",
    '|| { [ -f lanes/ZIP_ONLY_LIST ] && log "SKIP $t pair not clean or not canonical ($(basename "$g") $(basename "$s"))"; continue; }\n',
    lines[i],
)
out = "".join(lines).replace(A1, R1)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
r = subprocess.run(["bash", "-n", SCRIPT + ".new"], capture_output=True, text=True)
if r.returncode != 0:
    print("REFUSED: bash -n failed:", r.stderr.strip())
    sys.exit(2)
print(f"wrote {SCRIPT}.new ({len(out) - len(src):+d} bytes), bash -n ok")
