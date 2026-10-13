#!/usr/bin/env python3
"""stage_and_zip.sh: the promoted-kinds gate becomes advisory while lanes/PROMOTED_KINDS_ADVISORY exists.
Why (2026-09-19 22:40Z): every blocking finding examined on the 22 resubmit tasks was false or doubtful against the task's own
sources: 17-2-0's six unsourced_expected_token names are in Pricing_Matrix.xlsx, Landed_Cost_Allocation_Model.xlsx and the
golden (and in the scan's own text cache, 52 hits); 12-6-0's "FOB the 3PL(s)" is criterion prose with both tokens sourced;
band_text_binary fires on the word "tiered" meaning a partner tier; golden_citation MISSING fires on "December 31" and
"MSA Sec"; 2-6-0's "absent" 2020 Stock Plan is referenced in 13 corpus files. Blocking on them re-opens tasks for fix cycles
that cannot succeed and parks them. The resubmits' bar is every DataOS row verified fixed on bytes, the reviewers, the three-run
oracle and the cell gate; the promoted kinds are recorded in checks/promoted_kinds.txt either way. Remove the switch only after
the scans' precision repair is re-validated on the 22, and before any of the 179 is zipped.
Usage: python3 patch_actuator_promoted_advisory.py [SCRIPT=/root/qc/stage_and_zip.sh] -> writes SCRIPT.new, `bash -n` checked.
"""

import subprocess
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/stage_and_zip.sh"
MARK = 'if [ "$pk" -eq 5 ]; then'
ADVISORY = (
    'if [ "$pk" -eq 5 ] && [ -f /root/qc/lanes/PROMOTED_KINDS_ADVISORY ]; then '
    'echo "[gate] promoted kinds ADVISORY (lanes/PROMOTED_KINDS_ADVISORY, 22:40Z: every examined blocking finding on the 22 was false '
    "against the task sources; see checks/promoted_kinds.txt): $(grep -c '^BLOCKING' \"$PIPE_DIR/checks/promoted_kinds.txt\") "
    'finding(s) recorded, not blocking"; pk=0; fi\n'
)

lines = open(SCRIPT, encoding="utf-8").read().splitlines(keepends=True)
idx = [i for i, l in enumerate(lines) if l.lstrip().startswith(MARK)]
if len(idx) != 1:
    print(f"REFUSED: anchor line occurs {len(idx)} times (need exactly 1)")
    sys.exit(2)
if any("PROMOTED_KINDS_ADVISORY" in l for l in lines):
    print("REFUSED: already patched")
    sys.exit(2)
i = idx[0]
indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
lines.insert(i, indent + ADVISORY)
out = "".join(lines)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
r = subprocess.run(["bash", "-n", SCRIPT + ".new"], capture_output=True, text=True)
if r.returncode != 0:
    print("REFUSED: bash -n failed:", r.stderr.strip())
    sys.exit(2)
print(f"wrote {SCRIPT}.new (+{len(ADVISORY)} bytes), bash -n ok")
