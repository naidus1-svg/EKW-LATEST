#!/usr/bin/env python3
"""zip_when_ready.sh: a valid oracle probe that is OLDER than the task's newest shipped byte is re-run, not reused.
Why (2026-09-20 00:35Z): the loop re-ran the oracle only when probes/oracle.json was missing or infra-tainted. SVC-PC-21-2-0 was
BLOCKED at 00:31Z "golden scores 0.97" on a probe from 18:54Z the previous day, 13 minutes after a golden edit that addressed
exactly the failing criterion; the verdict text was byte-identical to the pre-fix one. The same reuse can ship a zip on a
pre-fix score (the 15-2-0 incident). Rule now: bytes newer than the probe means the probe has not run on these bytes.
Usage: python3 patch_zip_oracle_stale.py [SCRIPT=/root/qc/tools/zip_when_ready.sh] -> writes SCRIPT.new, bash -n checked.
"""

import subprocess
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/zip_when_ready.sh"
ANCHOR = '    if [ "$oracle_needs_run" = "1" ]; then\n'
INSERT = (
    "    # 00:35Z: a probe older than the newest shipped byte has not run on these bytes (21-2-0 blocked on an 18:54Z probe\n"
    "    # after a 00:17Z golden edit). Compare with the same fingerprint the verify loop uses.\n"
    '    if [ "$oracle_needs_run" = "0" ] && [ -f "$d/probes/oracle.json" ]; then\n'
    '      if python3 - "$t" "$d/probes/oracle.json" <<\'PY\' 2>/dev/null\n'
    "import os, sys\n"
    'sys.path.insert(0, "/root/qc/_prompts/verify/dataos-old")\n'
    "import task_fingerprint as tf\n"
    "sys.exit(0 if tf.newest_mtime(sys.argv[1]) > os.path.getmtime(sys.argv[2]) else 1)\n"
    "PY\n"
    "      then\n"
    '        log "ORACLE $t probe is older than the newest shipped byte, re-running (stale probe never counts)"\n'
    '        mv "$d/probes/oracle.json" "$d/probes/oracle.stale-$(date -u +%H%M%S).json"\n'
    "        oracle_needs_run=1\n"
    "      fi\n"
    "    fi\n"
)

src = open(SCRIPT, encoding="utf-8").read()
if src.count(ANCHOR) != 1:
    print(f"REFUSED: anchor count {src.count(ANCHOR)} != 1")
    sys.exit(2)
out = src.replace(ANCHOR, INSERT + ANCHOR)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
r = subprocess.run(["bash", "-n", SCRIPT + ".new"], capture_output=True, text=True)
if r.returncode != 0:
    print("REFUSED: bash -n failed:", r.stderr.strip())
    sys.exit(2)
print(
    f"wrote {SCRIPT}.new: stale oracle probe (bytes newer) is moved aside and re-run; bash -n ok"
)
