#!/usr/bin/env python3
"""render_guard_apply.py - GATE-V2 (laptop, 2026-09-18 23:20Z), item 3, the
solver-deliverable half: rewardkit silently replaces any files= entry over
1 MiB with "[skipped: file too large]" before the judge ever sees it (the
DataOS reviewer's own finding on SVC-PC-67-1-0). A compliant solver's actual
deliverable size cannot be known ahead of time, so the fix cannot be
conditional on the CURRENT golden's size - it has to make grading immune to
size unconditionally, for every files= entry that names a solver deliverable
(a bare `/app/<name>.<ext>` reference, ext in xlsx/xlsm/docx - a .csv/.txt/.pdf
is already judge-readable as plain text and out of scope here).

Mechanical, no model call (unlike the source-side create_xlsx_extract fix,
which needs per-task judgment about which columns matter): for every such
entry, (1) point judge.toml's files= at `/app/<name>.<ext>.judgetext.txt`
instead of the original, and (2) ensure tests/test.sh has a render-guard
block (openpyxl/python-docx, the same libraries test.sh's existing
xlsm->xlsx conversion block already uses and therefore already has available
inside the grading container - this script never assumes a library beyond
what that existing block already proves is present) that ALWAYS produces
`<name>.<ext>.judgetext.txt` from whatever actually lands at `/app/<name>.<ext>`,
regardless of its size: every non-empty xlsx/xlsm cell as `SHEET!CELL: value`
(cached value, not formula text - the judge only ever needs to read the
value), every non-empty docx paragraph as `[para N] text`. This is the same
representation gather_files_text.py already uses for FIX-round context, for
the same reason: a full, unambiguous, LLM-judge-readable dump of everything
the original file contained, immune to rewardkit's binary-file-size gate
because it is a plain .txt file.

Idempotent: re-running is a no-op on a task whose test.sh already has the
`# RENDER_GUARD_1MIB_V1` marker and whose judge.toml already names the
rendered path.

Usage:
    python3 render_guard_apply.py --apply-task TASK --confirm-apply --corpus-root PATH
"""
from __future__ import annotations

import argparse
import glob
import re
from pathlib import Path

MARKER = "# RENDER_GUARD_1MIB_V1 (GATE-V2, 2026-09-18)"
RENDER_EXTS = ("xlsx", "xlsm", "docx")

RENDER_BLOCK = f"""
{MARKER}
# rewardkit silently replaces any files= entry over 1 MiB with
# "[skipped: file too large]" before the judge ever reads it - a compliant
# solver's deliverable size is not knowable in advance, so this always
# produces a judge-readable text rendering of every /app/*.xlsx/*.xlsm/*.docx
# deliverable, regardless of its actual size, and judge.toml's files= names
# the rendering (<name>.<ext>.judgetext.txt), never the original.
python3 - <<'PYEOF'
import glob, os
try:
    import openpyxl
except ImportError:
    openpyxl = None
try:
    from docx import Document
except ImportError:
    Document = None

def render_xlsx(src, dst):
    wb = openpyxl.load_workbook(src, data_only=True, read_only=True)
    lines = []
    for name in wb.sheetnames:
        ws = wb[name]
        lines.append(f"--- sheet: {{name!r}} ---")
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None:
                    lines.append(f"{{name}}!{{cell.coordinate}}: value={{cell.value!r}}")
    open(dst, "w").write("\\n".join(lines))

def render_docx(src, dst):
    doc = Document(src)
    lines = []
    i = 0
    for p in doc.paragraphs:
        if p.text.strip():
            lines.append(f"[para {{i}}] {{p.text}}")
        i += 1
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    if p.text.strip():
                        lines.append(f"[para {{i}}] {{p.text}}")
                    i += 1
    open(dst, "w").write("\\n".join(lines))

for ext, renderer, avail in (("xlsx", render_xlsx, openpyxl), ("xlsm", render_xlsx, openpyxl), ("docx", render_docx, Document)):
    if avail is None:
        continue
    for src in glob.glob(f"/app/*.{{ext}}"):
        dst = src + ".judgetext.txt"
        try:
            renderer(src, dst)
        except Exception as e:
            open(dst, "w").write(f"[render error: {{e}}]")
PYEOF
"""


def resolve_files_line(text: str) -> tuple[str, str] | None:
    m = re.search(r'^(files\s*=\s*\[)(.*?)(\])', text, re.M | re.S)
    if not m:
        return None
    return m.group(0), m.group(2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply-task", required=True, dest="task")
    ap.add_argument("--corpus-root", type=Path, required=True)
    ap.add_argument("--confirm-apply", action="store_true", help="required, else dry-run only")
    args = ap.parse_args()

    task_dir = args.corpus_root / args.task
    changed_any = False
    any_app_deliverable = False

    for jt_path in sorted(Path(task_dir).glob("tests/deliverables*/judge.toml")):
        text = jt_path.read_text()
        found = resolve_files_line(text)
        if not found:
            continue
        full_line, entries_blob = found
        entries = re.findall(r'"([^"]+)"', entries_blob)
        new_entries = []
        touched = False
        for e in entries:
            m = re.match(r"^/app/([^/]+)\.(xlsx|xlsm|docx)$", e)
            if m and not e.endswith(".judgetext.txt"):
                new_entries.append(f"{e}.judgetext.txt")
                touched = True
                any_app_deliverable = True
            else:
                new_entries.append(e)
                if e.endswith(".judgetext.txt"):
                    any_app_deliverable = True  # already-applied, idempotent re-run
        if touched:
            new_blob = ", ".join(f'"{e}"' for e in new_entries)
            new_line = full_line.replace(entries_blob, new_blob)
            if args.confirm_apply:
                jt_path.write_text(text.replace(full_line, new_line))
            print(f"[render-guard] {jt_path.relative_to(task_dir)}: files= updated to point at .judgetext.txt renderings")
            changed_any = True

    if any_app_deliverable:
        test_sh = task_dir / "tests" / "test.sh"
        if test_sh.is_file():
            content = test_sh.read_text(newline="")
            if MARKER not in content:
                if args.confirm_apply:
                    sep = "" if content.endswith("\n") else "\n"
                    test_sh.write_text(content + sep + RENDER_BLOCK, newline="")
                print(f"[render-guard] tests/test.sh: render-guard block {'appended' if args.confirm_apply else '(dry-run, would append)'}")
                changed_any = True
            else:
                print("[render-guard] tests/test.sh: render-guard block already present, no-op")

    if not changed_any:
        print(f"[render-guard] {args.task}: nothing to do (no /app/*.xlsx|xlsm|docx files= entries found)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
