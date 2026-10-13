#!/usr/bin/env python3
"""Make tools/zip_when_ready.sh skip a task that has been re-opened and not yet fixed.
Why (2026-09-19 21:00Z): a gate re-open clears the task's FIX_FROM_REVIEWS_<n> markers and archives its round>=2 verdicts,
which changes the newest verdict pair, and the loop keys its attempt marker by pair file names, so it re-attempted 92-4-0
three times in 2.5 minutes (20:28:13, 20:29:xx, 20:30:40Z) on the same cell block before the fixer had touched it; 17-2-0
the same at 20:20:17Z. Each attempt is a full actuator run for nothing, and only the guard's busy and re-open-wait rules
keep it from spending the task's second try. A task on lanes/FIX_FROM_REVIEWS_PRIORITY whose STATE has no FIX_FROM_REVIEWS_1
is exactly "re-opened, fixer has not run": skip it, logged once per pass per task.
Usage: python3 patch_zip_fix_pending.py [SCRIPT=/root/qc/tools/zip_when_ready.sh] -> writes SCRIPT.new, `bash -n` checked.
"""

import subprocess
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/zip_when_ready.sh"

ANCHOR = """    [ -f "out/pipe/$t.zip" ] && continue
"""

NEW = """    [ -f "out/pipe/$t.zip" ] && continue
    # 21:00Z: re-opened by the guard (or un-parked by hand) and the fixer has not run yet: the re-open cleared the
    # FIX_FROM_REVIEWS markers and archived round>=2 verdicts, so the newest pair looks new to the attempt marker and the
    # loop re-attempted 92-4-0 three times in 2.5 minutes on one block. Wait for the fix cycle to mark FIX_FROM_REVIEWS_1.
    if grep -qx "$t" lanes/FIX_FROM_REVIEWS_PRIORITY 2>/dev/null && ! grep -qx FIX_FROM_REVIEWS_1 "$d/STATE" 2>/dev/null; then
      log "SKIP $t fix pending (re-opened, fixer has not run yet)"; continue
    fi
"""

src = open(SCRIPT, encoding="utf-8").read()
n = src.count(ANCHOR)
if n != 1:
    print(f"REFUSED: anchor occurs {n} times (need exactly 1)")
    sys.exit(2)
out = src.replace(ANCHOR, NEW)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
r = subprocess.run(["bash", "-n", SCRIPT + ".new"], capture_output=True, text=True)
if r.returncode != 0:
    print("REFUSED: bash -n failed:", r.stderr.strip())
    sys.exit(2)
print(f"wrote {SCRIPT}.new ({len(out) - len(src):+d} bytes), bash -n ok")
