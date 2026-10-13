#!/usr/bin/env python3
"""direct_fix_brief.py: a task with ZERO open DataOS rows but a DIRECT-FIX-NOTE.md still gets a brief (rules + note), instead of exit 1.
Why (2026-09-19 23:28Z): 82-1-0 closed every DataOS complaint and was then BLOCKED at the zip step by the deterministic
answer_key_rubric_leak cell (a criterion sentence copies 8+ consecutive words of the golden). The fix is authoring work for a
task agent (paraphrase the criterion, never the golden, per gate_playbooks.py), but direct_fix.sh refuses to launch when the
brief builder finds no open rows. With this patch the coordinator note alone is enough to launch.
Usage: python3 patch_brief_note_only.py [SCRIPT=/root/qc/tools/direct_fix_brief.py] -> writes SCRIPT.new, py_compile checked.
"""

import py_compile
import re
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/root/qc/tools/direct_fix_brief.py"
src = open(SCRIPT, encoding="utf-8").read()

# anchor: the `if not open_rows:` block that exits 1 (two lines: a message and sys.exit(1))
m = re.search(r"    if not open_rows:\n(        .*\n)*?        sys\.exit\(1\)\n", src)
if not m:
    print("REFUSED: `if not open_rows:` ... sys.exit(1) block not found")
    sys.exit(2)
old = m.group(0)
new = (
    '    if not open_rows and not os.path.exists(f"/root/qc/stream-pipe/{task}/DIRECT-FIX-NOTE.md"):\n'
    + old[len("    if not open_rows:\n") :]
)
if src.count(old) != 1:
    print("REFUSED: anchor not unique")
    sys.exit(2)
out = src.replace(old, new)
if "import os" not in out:
    out = out.replace("import sys\n", "import os\nimport sys\n", 1)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(SCRIPT + ".new", doraise=True)
print(
    f"wrote {SCRIPT}.new: zero open rows no longer exits when a coordinator note exists; py_compile ok"
)
