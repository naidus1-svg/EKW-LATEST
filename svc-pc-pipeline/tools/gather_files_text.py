#!/usr/bin/env python3
"""gather_files_text.py - collect the CURRENT content of every editable file
in the task, for the step-4 fix-plan prompt's {{FILES_TEXT}} (so the fix-plan
model edits against real, current bytes, not its memory of the CR-context
excerpt).

Redirect build (2026-09-18): the canon ekw-svc-comprehensive-review.md §5
schema has no per-finding `affected_files` field (its `checks[]` entries
carry prose `justification`/`suggested_fix`, not a file list), so file
selection no longer depends on parsing the CR.json's shape at all - it
always gathers the fixed, small set of files a fix plan could ever touch:
instruction.md, tests/task_prompt.txt, tests/reward.toml, every
tests/*/judge.toml, and every file under solution/files/. These tasks are
small enough (rewardkit-hybrid SVC-PC packages) that always including the
full set costs little and is far more robust than re-deriving "which files
are affected" from prose. cr_json is still accepted positionally (gate_task.sh
already passes it) but is now used only to log the major/minor count for the
console; it is never required to have any particular shape.

A plain text/toml/md file is shown as its raw content, same as before. An
.xlsx or .docx golden is shown as an ADDRESSABLE STRUCTURED DUMP instead of
raw bytes-as-text garbage, since apply_plan.py's binary ops need an exact
sheet+cell (set_xlsx_cell) or exact paragraph text (replace_docx_text), not
a byte offset:
  - .xlsx: one line per non-empty cell, "SHEET!CELL: formula=... cached=..."
    for a formula cell or "SHEET!CELL: value=..." for a literal, so the fix
    plan can cite a real sheet name and cell reference that actually exists.
  - .docx: one line per non-empty paragraph (including every table cell's
    paragraphs, via apply_plan.py's own _iter_all_paragraphs so the fix step
    sees exactly the same paragraph boundaries the applier will match
    against), "[para N] <full paragraph text>".

Usage:
    python3 gather_files_text.py CR.json --task TASK --corpus-root PATH --out FILES_TEXT.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 2026-09-19 (laptop): the old 40,000 cap cut 94 of 220 workbook dumps (audit), so the fix-plan model was asked to edit a cell it could not
# see. The cap is now 120,000 per file with a 360,000 total; over the total, every file falls back to the old 40,000. Sheets that the
# findings name ("Variance Analysis!B6") are dumped FIRST, so a cut never removes the sheet the fix is about.
PER_FILE_CHAR_CAP = 120_000
TOTAL_CHAR_CAP = 360_000
FALLBACK_PER_FILE_CAP = 40_000
BINARY_SUFFIXES = {
    ".pptx",
    ".pdf",
    ".zip",
    ".xls",
    ".doc",
    ".ppt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".xlsm",
}


def dump_xlsx_structured(path: Path, priority_blob: str = "") -> str:
    import openpyxl

    wb_f = openpyxl.load_workbook(path, data_only=False)
    wb_v = openpyxl.load_workbook(path, data_only=True)
    blob = (priority_blob or "").lower()
    names = list(wb_f.sheetnames)
    named = [
        s
        for s in names
        if blob and (f"{s.lower()}!" in blob or f"'{s.lower()}'" in blob)
    ]
    ordered = named + [s for s in names if s not in named]
    blocks = []
    for sheet_name in ordered:
        wsf, wsv = wb_f[sheet_name], wb_v[sheet_name]
        lines = [f"--- sheet: {sheet_name!r} ---"]
        for rowf, rowv in zip(wsf.iter_rows(), wsv.iter_rows()):
            for cf, cv in zip(rowf, rowv):
                if cf.value is None and cv.value is None:
                    continue
                if isinstance(cf.value, str) and cf.value.startswith("="):
                    lines.append(
                        f"{sheet_name}!{cf.coordinate}: formula={cf.value!r} cached_value={cv.value!r}"
                    )
                else:
                    lines.append(f"{sheet_name}!{cf.coordinate}: value={cf.value!r}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def dump_docx_structured(path: Path) -> str:
    from docx import Document

    from apply_plan import (
        _iter_all_paragraphs,
    )  # single source of truth for paragraph boundaries

    doc = Document(str(path))
    lines = []
    for i, p in enumerate(_iter_all_paragraphs(doc)):
        text = p.text
        if text.strip():
            lines.append(f"[para {i}] {text}")
    return "\n".join(lines)


def render_file(
    path: Path, cap: int = PER_FILE_CHAR_CAP, priority_blob: str = ""
) -> str:
    if not path.is_file():
        return f"[file not found: {path}]"
    suffix = path.suffix.lower()
    if suffix in BINARY_SUFFIXES:
        return (
            f"[binary {suffix} file, {path.stat().st_size} bytes: not dumped as text]"
        )
    try:
        if suffix == ".xlsx":
            body = dump_xlsx_structured(path, priority_blob)
        elif suffix == ".docx":
            body = dump_docx_structured(path)
        else:
            body = path.read_text(errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"[could not read {path}: {exc}]"
    if len(body) > cap:
        body = body[:cap] + f"\n...[truncated {len(body) - cap} chars]"
    return body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cr_json", type=Path)
    ap.add_argument("--task", required=True)
    ap.add_argument("--corpus-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    # major/minor count is logged only; file selection never depends on the
    # CR.json's shape (see module docstring).
    try:
        cr = json.loads(args.cr_json.read_text())
        n_major = cr.get("major_count")
        n_minor = cr.get("minor_count")
        if n_major is None:  # old-schema fallback, harmless if absent
            n_major = sum(
                1 for f in cr.get("findings", []) if f.get("severity") == "major"
            )
    except Exception:  # noqa: BLE001
        n_major, n_minor = "?", "?"

    task_dir = args.corpus_root / args.task
    files: list[str] = []
    for rel in ("instruction.md", "tests/task_prompt.txt", "tests/reward.toml"):
        if (task_dir / rel).is_file():
            files.append(rel)
    for p in sorted(task_dir.glob("tests/*/judge.toml")):
        files.append(str(p.relative_to(task_dir)))
    for p in sorted(task_dir.glob("solution/files/*")):
        if p.is_file():
            files.append(str(p.relative_to(task_dir)))

    # Additive extension (2026-09-18, oversize_source_scan.py): a finding can
    # name a file outside the fixed set above - e.g. an oversized SOURCE
    # workbook under environment/initial_workspace/, which the fixed set
    # never covers, but the fix-plan model needs to see (structured dump) to
    # pick which columns a create_xlsx_extract should keep. Purely additive
    # and a no-op for any CR.json whose findings carry no affected_files (the
    # canon-CR/checkfix/oracle/adjudication callers all pass [] here today).
    try:
        for f in cr.get("findings", []) or []:
            for rel in f.get("affected_files", []) or []:
                if rel not in files:
                    files.append(rel)
    except Exception:  # noqa: BLE001
        pass

    # the findings' own text names the sheets the fix is about ("Variance Analysis!B6"); dump those first
    try:
        blob = json.dumps(cr, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        blob = ""
    bodies = {
        rel: render_file(task_dir / rel, PER_FILE_CHAR_CAP, blob) for rel in files
    }
    if sum(len(b) for b in bodies.values()) > TOTAL_CHAR_CAP:
        cap = FALLBACK_PER_FILE_CAP
        bodies = {rel: render_file(task_dir / rel, cap, blob) for rel in files}
    parts = []
    for rel in files:
        parts.append(f"\n{'=' * 80}\n{rel}\n{'=' * 80}\n{bodies[rel]}\n")

    if not parts:
        parts.append(f"\n[no editable files found under {task_dir}]\n")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(parts))
    print(f"wrote {args.out} ({len(files)} files, CR major={n_major} minor={n_minor})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
