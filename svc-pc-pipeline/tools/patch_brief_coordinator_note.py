#!/usr/bin/env python3
"""direct_fix_brief.py: append stream-pipe/<task>/DIRECT-FIX-NOTE.md (if present) as a "## Coordinator note" section.
Why (2026-09-19 23:02Z): direct_fix.sh rebuilds the brief on every launch, so a task-specific instruction (92-4-0: files= has been
narrowed and restored four times; the over-inclusion gate cell is advisory now, so restore the five corpus sources and keep the
tightened criteria) had nowhere to live that survives a relaunch.
Usage: python3 patch_brief_coordinator_note.py [SCRIPT=/root/qc/tools/direct_fix_brief.py] -> writes SCRIPT.new, py_compile checked.
"""

import py_compile
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/direct_fix_brief.py"
OLD = '        out.append("")\n    print("\\n".join(out))\n'
NEW = (
    '        out.append("")\n'
    '    note = f"/root/qc/stream-pipe/{task}/DIRECT-FIX-NOTE.md"\n'
    "    if os.path.exists(note):\n"
    '        out.append("## Coordinator note (task-specific, read before editing)")\n'
    '        out.append(open(note, encoding="utf-8").read().strip())\n'
    '        out.append("")\n'
    '    print("\\n".join(out))\n'
)

src = open(SCRIPT, encoding="utf-8").read()
if src.count(OLD) != 1:
    print(f"REFUSED: anchor count {src.count(OLD)} != 1")
    sys.exit(2)
if "import os" not in src:
    src = src.replace("import sys\n", "import os\nimport sys\n", 1)
    if "import os" not in src:
        print("REFUSED: could not add import os")
        sys.exit(2)
out = src.replace(OLD, NEW)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(SCRIPT + ".new", doraise=True)
print(
    f"wrote {SCRIPT}.new: coordinator note appended when DIRECT-FIX-NOTE.md exists; py_compile ok"
)
