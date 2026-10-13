#!/usr/bin/env python3
"""fix_from_reviews.sh: the round counters and the park decision count MAJOR findings, not every finding.
Why (2026-09-20 01:40Z): the union builder ranks non-promoted scan rows and advisory cells as minor since 20:12Z, but the dispatcher
still computed `len(findings)` for its "N major finding(s) still present" park (92-4-0 parked at 22:35:45Z on 4 minors with 0 majors)
and for its "run one fix round" decisions, so it spends fix rounds and parks on rows the gate never blocks on.
Usage: python3 patch_dispatcher_park_majors_only.py [SCRIPT=/root/qc/tools/fix_from_reviews.sh] -> writes SCRIPT.new, `bash -n` checked.
Every `len(json.load(open(...)).get('findings', []))` becomes a count of findings whose severity is major.
"""

import re
import subprocess
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/fix_from_reviews.sh"
OLD = r"len\(json\.load\(open\('([^']+)'\)\)\.get\('findings', \[\]\)\)"
NEW = r"sum(1 for f in json.load(open('\1')).get('findings', []) if f.get('severity') == 'major')"

src = open(SCRIPT, encoding="utf-8").read()
hits = re.findall(OLD, src)
if not hits:
    print("REFUSED: no len(findings) counters found")
    sys.exit(2)
out = re.sub(OLD, NEW, src)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
r = subprocess.run(["bash", "-n", SCRIPT + ".new"], capture_output=True, text=True)
if r.returncode != 0:
    print("REFUSED: bash -n failed:", r.stderr.strip())
    sys.exit(2)
print(f"wrote {SCRIPT}.new: {len(hits)} counter(s) now count majors only; bash -n ok")
