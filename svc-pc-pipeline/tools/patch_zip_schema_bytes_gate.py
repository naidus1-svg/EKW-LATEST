#!/usr/bin/env python3
"""zip_when_ready.sh: block packaging when any judge group's compiled strict schema is at or over 4,000 bytes
(tools/judge_schema_bytes.py, rewardkit's own builder). Why (2026-09-20 01:10Z): DataOS's grading of SVC-PC-38-1-0 failed with
Anthropic's "compiled grammar is too large" on a 24-criterion group (4,574 bytes); judge_group_size_scan.py counts criteria and
called 24 safe. Four already-packaged tasks (26-8-0, 82-1-0, 73-3-0, 92-4-0) compile between 4,490 and 6,707 bytes and would
fail the same way. The local oracle emulator does not reproduce the limit, so the check has to be deterministic and blocking.
Usage: python3 patch_zip_schema_bytes_gate.py [SCRIPT=/root/qc/tools/zip_when_ready.sh] -> writes SCRIPT.new, bash -n checked.
"""

import subprocess
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/zip_when_ready.sh"
ANCHOR = (
    '    if [ "$oracle_needs_run" = "0" ] && [ -f "$d/probes/oracle.json" ]; then\n'
)
INSERT = (
    "    # 01:10Z: rewardkit compiles each judge group into one strict schema; Anthropic rejects large ones and the run scores 0\n"
    "    # (DataOS 1.8 on 38-1-0). Measured with rewardkit's own builder; block at 4,000 bytes, the failing group was 4,574.\n"
    '    mkdir -p "$d/checks"\n'
    '    python3 tools/judge_schema_bytes.py "$C/$t" > "$d/checks/judge_schema_bytes.txt" 2>&1\n'
    "    jsb=$?\n"
    '    if [ "$jsb" -ge 2 ]; then\n'
    "      log \"BLOCK $t judge group schema too large for the Anthropic judge: $(grep ' BLOCK$' \"$d/checks/judge_schema_bytes.txt\" | awk '{print $2\"=\"$4\"B\"}' | tr '\\n' ' ')(rewardkit compile, limit 4000)\"\n"
    "      continue\n"
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
print(f"wrote {SCRIPT}.new: judge-schema byte gate before the oracle step; bash -n ok")
