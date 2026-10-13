#!/usr/bin/env python3
"""zip_when_ready.sh: after the oracle passes, BLOCK if any authored judge group did not fire (gate_groups_fire.py).
Why (2026-09-20 03:30Z): 82-1-0 shipped in a batch with 3 rubric groups but only 1 scored; 38-1-0 (11 authored, 4 scored) and
17-2-0 (5, 4) the same. The oracle scores 1.0 on only the groups that run, so a dropped group looks clean. Usually the cause is a
stale oracle predating a group split, which the stale-oracle rule re-runs first; this gate is the backstop that a fresh oracle
scored every authored group before the zip ships. Exit 2 from gate_groups_fire = a dropped group.
Usage: python3 patch_zip_groups_fire.py [SCRIPT=/root/qc/tools/zip_when_ready.sh] -> writes SCRIPT.new, bash -n checked.
"""

import subprocess
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/zip_when_ready.sh"
# anchor on the stage_and_zip line (the zip is built there); insert the gate immediately before it, on the fresh oracle.json.
ANCHOR = '    out=$(bash stage_and_zip.sh "$C" "$t" out/pipe --accept-skip golden_arithmetic,deliverable_count,source_truncation 2>&1); rc=$?'
INSERT = (
    '    mkdir -p "$d/checks"\n'
    '    if ! python3 tools/gate_groups_fire.py "$t" > "$d/checks/groups_fire.txt" 2>&1; then\n'
    '      log "BLOCK $t judge group did not fire: $(grep BLOCK "$d/checks/groups_fire.txt" | head -1 | cut -c1-120)"\n'
    '      rm -rf "$S"; continue\n'
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
print(f"wrote {SCRIPT}.new: groups-fire gate before ZIPPED; bash -n ok")
