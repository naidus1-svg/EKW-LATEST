#!/usr/bin/env python3
"""apply_plan.py - HANDOFF.md section 3 step 4 (text ops) and section 1c
(binary-golden ops): apply a fix plan's edit list to the corpus byte-exactly
and log each edit to FIX-LOG.md.

Reads a PLAN.json (the parsed output of the step-4 Opus fix-plan call, see
tools/prompts/fix_plan.md for the schema it must follow) and applies each
edit directly to <corpus-root>/<task>/<file>, the same target every other
per-task apply mode in this toolset writes to (rewardkit_pin.py --apply,
muststrip_scan.py --apply-task).

Fixed JSON edit schema (PLAN.json):
{
  "task": "SVC-PC-...",
  "edits": [
    {
      "file": "instruction.md",              # path relative to the task dir
      "op": "replace_literal",               # text ops: "replace_literal" | "append_text"
      "find": "<exact substring, must occur exactly once>",   # replace_literal only
      "replace": "<replacement text>",                         # replace_literal only
      "text": "<text to append>",                               # append_text only
      "reason": "<one line: which CR finding this fixes>",
      "finding_id": "F3"
    },
    {
      "file": "solution/files/Promo_Calendar.xlsx",
      "op": "set_xlsx_cell",                 # binary op: xlsx
      "sheet": "Calendar",                   # exact worksheet name
      "cell": "F4",                          # A1-style cell reference
      "value": 78000,                        # JSON number -> numeric cell, JSON string -> text cell
      "reason": "...", "finding_id": "F5"
    },
    {
      "file": "solution/files/Exception-Triage-Memo.docx",
      "op": "replace_docx_text",             # binary op: docx
      "find": "<exact text, must occur exactly once across all runs/paragraphs/tables>",
      "replace": "<replacement text>",
      "reason": "...", "finding_id": "F2"
    },
    {
      "file": "tests/deliverables/judge_inputs/Sales_Orders_judge_extract.xlsx",
      "op": "create_xlsx_extract",           # binary op: oversized files= SOURCE -> condensed extract
      "source": "environment/initial_workspace/Sales_Orders.xlsx",
      "sheet": "Orders",                     # exact sheet name in the SOURCE workbook
      "columns": ["Order ID", "Order Date", "Category", "Subtotal"],  # exact header text, source's row 1
      "reason": "...", "finding_id": "F6"
    },
    {
      "file": "environment/initial_workspace/_corpus_subtree/Finance/July_PnL.xlsx",
      "op": "replace_ooxml_text",            # binary op: text inside a comment / notes / header / footer part
      "kind": "cell_comment",                # cell_comment | speaker_notes | header_footer (as the metadata_leak finding names it)
      "location": "July P&L!D10",            # the finding's own location: Sheet!Cell for a comment, the part path for notes/footer
      "find": "Q2 $195.5K->$196K rounding",  # a substring of the finding's `text`; whitespace is ignored; must match exactly once
      "replace": "Q2 rounding",              # "" blanks the matched text
      "reason": "...", "finding_id": "metadata_leak"
    }
  ]
}

Per-edit behavior, mirroring rewardkit_pin.py/muststrip_scan.py's own
--apply-task guarantees:
  - text ops: files are read/written with newline="" (LF preserved exactly,
    no CRLF translation). replace_literal: `find` must appear in the file
    EXACTLY ONCE (0 = idempotent no-op, >1 = ambiguous, refused).
    append_text: idempotent if `text` already occurs verbatim.
  - set_xlsx_cell: HANDOFF.md 1c gap. Does NOT use a plain
    openpyxl-load-modify-save round trip on the whole workbook - confirmed
    empirically (and by formula_cache_scan.py's own no-cache-probe builder,
    which exploits exactly this) that openpyxl silently drops the cached
    <v> value of every OTHER formula cell in the file on save whenever it
    was loaded with data_only=False, which is required to keep formula
    TEXT intact elsewhere. On SVC-PC-22-5-0's Promo_Calendar.xlsx a naive
    round trip zeroed out cached values on all 44 formula cells in the
    file, not just the one being edited - a corpus-wide class-K regression
    for one single-cell fix. Instead, this op edits the target worksheet's
    XML directly inside the xlsx zip archive (openpyxl is used only to
    resolve/validate, via the same zip, never to re-save the workbook), so
    every cell other than the one named - in this sheet or any other -
    survives byte-for-byte, formula AND cached value both. The target
    cell's `<f>` (formula) is removed and replaced with a literal `<v>`
    (or `<is>` for a string), and its `s` (style/number-format) attribute
    is left untouched, so the cell's number format is preserved by
    construction (nothing about it is ever written).
  - replace_docx_text: python-docx. Searches every run in every paragraph,
    including every table cell's paragraphs (recursively through nested
    tables), for `find`. Exactly one run containing it -> replaced in that
    run only (formatting untouched). Zero hits at the run level but exactly
    one PARAGRAPH's full text (concatenation of its runs) contains it ->
    the match spans a run boundary; that paragraph's runs are collapsed
    into its first run with the replacement text (formatting simplifies to
    the first run's style for that one paragraph - the only way to do a
    cross-run replace without a raw-XML run-splitter, and logged as such).
    More than one run, or more than one spanning paragraph, is refused as
    ambiguous. Zero hits anywhere is an idempotent no-op.
  - create_xlsx_extract: GATE-V2 (laptop, 2026-09-18 23:20Z), the 54-2-0
    pattern generalized - rewardkit silently replaces any files= entry over
    1 MiB with "[skipped: file too large]" before the judge ever sees it.
    Opens `source` (data_only, read_only - a values snapshot, this is a
    grading-convenience derivative, never a golden), takes exactly the named
    `columns` from its header row (row 1 of `sheet`), and writes a brand new,
    minimal workbook at `file` with just those columns - a plain openpyxl
    save is safe here since there is no pre-existing cached-formula state at
    `file` to lose (it does not exist yet). Does not delete or touch
    `source`; the caller is responsible for repointing the relevant
    judge.toml `files=` entry at the new `file` path (a `replace_literal` on
    that line, planned as a second edit in the same plan).
  - replace_ooxml_text: laptop, 2026-09-19. Text inside ONE part of an .xlsx/.xlsm/.docx/.pptx: an xlsx cell comment, a pptx
    speaker note, a docx header or footer (docx comments too). Allowed only under environment/initial_workspace/ and
    solution/files/. This is what a metadata_leak fix needs: the leaked string lives in a file the solver receives and no
    other op could reach it. Implemented in ooxml_edit.py (see its docstring): whitespace-insensitive exact-once matching,
    raw-XML splice so every other byte of the part and every other member of the zip is unchanged, atomic write, and a
    verification pass (zip test, XML parse, other members byte-identical, file re-opens with openpyxl / python-docx /
    python-pptx). A sheet title cannot be edited by it (a rename breaks every reference); that is refused with a message.
  - every write is read back immediately to confirm the change landed
    before moving to the next edit.

Every edit attempt (applied, no-op, or failed) gets one line in
<pipe-dir>/FIX-LOG.md, timestamped, naming the file, finding_id, reason, and
outcome. Exit code is 0 only if every edit applied or was a no-op; 1 if any
edit failed (ambiguous find, missing file, etc.) - the caller (gate_task.sh)
treats a nonzero exit as "still has majors", not a silent partial success.

Usage:
    python3 apply_plan.py --plan PLAN.json --task SVC-PC-... \
        --corpus-root PATH --fix-log FIX-LOG.md
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

ET.register_namespace("", XLSX_MAIN_NS)
ET.register_namespace("r", XLSX_REL_NS)

_CELL_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def log_line(fix_log: Path, text: str) -> None:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with fix_log.open("a", newline="") as f:
        f.write(f"- {ts} {text}\n")


# ---------------------------------------------------------------------------
# Fake-fix guard (coordinator, 2026-09-19 22:50Z): SVC-PC-21-2-0's third DataOS-fixer pass on r023
# closed a coverage finding by adding "is not graded" to the criterion's own description - the
# criterion's Expected text now excuses the very omission the reviewers filed, so all three rows
# came back "still true" and neither GLM nor Sonnet caught it. A criterion can only gain this kind
# of clause through a text edit to a judge.toml file (replace_literal or append_text - the only two
# ops that write judge.toml); checking every such edit against its own before/after content, right
# where the write happens, catches every path a softening clause could enter, not just the one
# reviewers happened to test on. Deliberately over-inclusive: a false-fire here means "reverted and
# reported for a human to look at", not a shipped task, so the asymmetry favors catching it.
# ---------------------------------------------------------------------------
_SOFTENING_CLAUSE_RE = re.compile(
    r"\bis\s+not\s+graded\b|\bnot\s+graded\b|\bnot\s+scored\b"
    r"|\bnot\s+required\b|\bno\s+longer\s+required\b|\bisn'?t\s+required\b"
    r"|\bany\s+of\b"
    r"|\boptional\b",
    re.I,
)


def _softening_clause_gained(old_text: str, new_text: str) -> str | None:
    """The first softening phrase present in new_text that is NOT already present in old_text, or
    None. Only meaningful for judge.toml - a phrase already in the file before this edit is not
    something this edit introduced, and NOT flagged (an edit that merely moves or quotes existing
    text is not a new fake-fix)."""
    old_hits = {m.group(0).lower() for m in _SOFTENING_CLAUSE_RE.finditer(old_text)}
    for m in _SOFTENING_CLAUSE_RE.finditer(new_text):
        if m.group(0).lower() not in old_hits:
            return m.group(0)
    return None


def _is_judge_toml(path: Path) -> bool:
    return path.name == "judge.toml"


# ---------------------------------------------------------------------------
# Text ops
# ---------------------------------------------------------------------------


def apply_replace_literal(path: Path, find: str, replace: str) -> tuple[str, str]:
    """Returns (outcome, detail). outcome in {applied, noop, failed, reverted}."""
    if not path.is_file():
        return "failed", f"file not found: {path}"
    content = path.read_text(newline="")
    count = content.count(find)
    if count == 0:
        return "noop", "find text absent (already applied or never present)"
    if count > 1:
        return (
            "failed",
            f"find text occurs {count} times, ambiguous (refusing to guess)",
        )
    new_content = content.replace(find, replace, 1)
    if _is_judge_toml(path):
        clause = _softening_clause_gained(content, new_content)
        if clause:
            return (
                "reverted",
                f"FAKE-FIX GUARD: this edit's replace text adds {clause!r} to judge.toml, which is not present before the "
                "edit - a criterion is never closed by narrowing/softening what it grades (coordinator, 2026-09-19 22:50Z, "
                "SVC-PC-21-2-0 r023). File left unchanged; write the row to notes as \"not fixable without a person\" instead.",
            )
    path.write_text(new_content, newline="")
    check = path.read_text(newline="")
    if check != new_content:
        return "failed", "read-back after write did not match (write did not land)"
    return "applied", f"{len(find)} chars -> {len(replace)} chars"


def apply_append_text(path: Path, text: str) -> tuple[str, str]:
    if not path.is_file():
        return "failed", f"file not found: {path}"
    content = path.read_text(newline="")
    if text in content:
        return "noop", "text already present"
    sep = "" if content.endswith("\n") or not content else "\n"
    new_content = content + sep + text
    if not new_content.endswith("\n"):
        new_content += "\n"
    if _is_judge_toml(path):
        clause = _softening_clause_gained(content, new_content)
        if clause:
            return (
                "reverted",
                f"FAKE-FIX GUARD: the appended text adds {clause!r} to judge.toml, which is not present before the edit - "
                "a criterion is never closed by narrowing/softening what it grades (coordinator, 2026-09-19 22:50Z, "
                "SVC-PC-21-2-0 r023). File left unchanged; write the row to notes as \"not fixable without a person\" instead.",
            )
    path.write_text(new_content, newline="")
    check = path.read_text(newline="")
    if check != new_content:
        return "failed", "read-back after write did not match (write did not land)"
    return "applied", f"appended {len(text)} chars"


# ---------------------------------------------------------------------------
# create_xlsx_extract - GATE-V2 (laptop, 2026-09-18 23:20Z): the 54-2-0
# pattern (tests/deliverables/judge_inputs/Sales_Orders_judge_extract.xlsx)
# generalized. Condenses an oversized files= SOURCE workbook to just the
# sheet/columns a judge criterion actually needs, under rewardkit's silent
# 1 MiB skip threshold. Values only (data_only read) - this is a grading
# convenience artifact derived from the source, never a golden requiring live
# formulas, so there is none of set_xlsx_cell's cached-formula-value risk.
# ---------------------------------------------------------------------------


def apply_create_xlsx_extract(
    dest_path: Path, source_path: Path, sheet: str, columns: list[str]
) -> tuple[str, str]:
    if not source_path.is_file():
        return "failed", f"source file not found: {source_path}"
    try:
        import openpyxl
    except ImportError as exc:  # noqa: BLE001
        return "failed", f"openpyxl not available: {exc}"

    try:
        wb_src = openpyxl.load_workbook(source_path, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        return "failed", f"could not open source workbook: {exc}"
    if sheet not in wb_src.sheetnames:
        return "failed", f"sheet {sheet!r} not in source (has: {wb_src.sheetnames})"
    ws_src = wb_src[sheet]

    rows = list(ws_src.iter_rows(values_only=True))
    if not rows:
        return "failed", f"sheet {sheet!r} is empty"
    header = [str(h) if h is not None else "" for h in rows[0]]
    try:
        col_idx = [header.index(c) for c in columns]
    except ValueError as exc:
        return "failed", f"column not found in header {header}: {exc}"

    wb_out = openpyxl.Workbook()
    ws_out = wb_out.active
    ws_out.title = sheet
    ws_out.append(columns)
    for row in rows[1:]:
        ws_out.append([row[i] if i < len(row) else None for i in col_idx])

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    wb_out.save(dest_path)
    size = dest_path.stat().st_size
    return (
        "applied",
        f"extracted {len(columns)} columns x {len(rows) - 1} rows from {source_path.name}!{sheet}, {size} bytes",
    )


# ---------------------------------------------------------------------------
# set_xlsx_cell - direct worksheet-XML surgery inside the zip (see module
# docstring for why a plain openpyxl round trip is unsafe here).
# ---------------------------------------------------------------------------


def _col_letters(cell_ref: str) -> str:
    m = _CELL_RE.match(cell_ref)
    if not m:
        raise ValueError(f"not a valid cell reference: {cell_ref!r}")
    return m.group(1).upper()


def _col_to_num(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _row_num(cell_ref: str) -> int:
    m = _CELL_RE.match(cell_ref)
    if not m:
        raise ValueError(f"not a valid cell reference: {cell_ref!r}")
    return int(m.group(2))


def _resolve_sheet_xml(zf: zipfile.ZipFile, sheet_name: str) -> str:
    wb_xml = ET.fromstring(zf.read("xl/workbook.xml"))
    sheet_el = None
    for s in wb_xml.iter(f"{{{XLSX_MAIN_NS}}}sheet"):
        if s.get("name") == sheet_name:
            sheet_el = s
            break
    if sheet_el is None:
        available = [s.get("name") for s in wb_xml.iter(f"{{{XLSX_MAIN_NS}}}sheet")]
        raise ValueError(f"sheet {sheet_name!r} not found (have: {available})")
    rid = sheet_el.get(f"{{{XLSX_REL_NS}}}id")
    rels_xml = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    target = None
    for rel in rels_xml.iter(f"{{{PKG_REL_NS}}}Relationship"):
        if rel.get("Id") == rid:
            target = rel.get("Target")
            break
    if target is None:
        raise ValueError(f"relationship {rid!r} for sheet {sheet_name!r} not found")
    target = target.lstrip("/")
    if not target.startswith("xl/"):
        target = "xl/" + target
    return target


def _find_or_create_row(sheet_data: ET.Element, row_num: int) -> ET.Element:
    rows = sheet_data.findall(f"{{{XLSX_MAIN_NS}}}row")
    for row in rows:
        if row.get("r") == str(row_num):
            return row
    new_row = ET.Element(f"{{{XLSX_MAIN_NS}}}row", {"r": str(row_num)})
    insert_idx = len(rows)
    for i, row in enumerate(rows):
        if int(row.get("r")) > row_num:
            insert_idx = i
            break
    sheet_data.insert(insert_idx, new_row)
    return new_row


def _find_or_create_cell(row: ET.Element, cell_ref: str) -> ET.Element:
    cells = row.findall(f"{{{XLSX_MAIN_NS}}}c")
    for c in cells:
        if c.get("r") == cell_ref:
            return c
    new_c = ET.Element(f"{{{XLSX_MAIN_NS}}}c", {"r": cell_ref})
    col_num = _col_to_num(_col_letters(cell_ref))
    insert_idx = len(cells)
    for i, c in enumerate(cells):
        if _col_to_num(_col_letters(c.get("r"))) > col_num:
            insert_idx = i
            break
    row.insert(insert_idx, new_c)
    return new_c


def _existing_cell_text(c_el: ET.Element) -> str | None:
    v_el = c_el.find(f"{{{XLSX_MAIN_NS}}}v")
    if v_el is not None:
        return v_el.text
    is_el = c_el.find(f"{{{XLSX_MAIN_NS}}}is")
    if is_el is not None:
        t_el = is_el.find(f"{{{XLSX_MAIN_NS}}}t")
        return t_el.text if t_el is not None else ""
    return None


def _set_cell_literal(c_el: ET.Element, value) -> None:
    for tag in ("f", "v", "is"):
        el = c_el.find(f"{{{XLSX_MAIN_NS}}}{tag}")
        if el is not None:
            c_el.remove(el)
    if isinstance(value, bool):
        c_el.set("t", "b")
        v = ET.SubElement(c_el, f"{{{XLSX_MAIN_NS}}}v")
        v.text = "1" if value else "0"
    elif isinstance(value, (int, float)):
        c_el.set("t", "n")
        v = ET.SubElement(c_el, f"{{{XLSX_MAIN_NS}}}v")
        v.text = str(value)
    else:
        c_el.set("t", "inlineStr")
        is_el = ET.SubElement(c_el, f"{{{XLSX_MAIN_NS}}}is")
        t_el = ET.SubElement(is_el, f"{{{XLSX_MAIN_NS}}}t")
        t_el.text = str(value)


def apply_set_xlsx_cell(path: Path, sheet: str, cell: str, value) -> tuple[str, str]:
    if not path.is_file():
        return "failed", f"file not found: {path}"
    if not sheet:
        return "failed", "missing 'sheet'"
    cell = (cell or "").strip()
    if not _CELL_RE.match(cell):
        return "failed", f"not a valid cell reference: {cell!r}"
    if value is None:
        return "failed", "missing 'value'"

    try:
        with zipfile.ZipFile(path, "r") as zf:
            sheet_path = _resolve_sheet_xml(zf, sheet)
            if sheet_path not in zf.namelist():
                return (
                    "failed",
                    f"resolved sheet path {sheet_path!r} not present in archive",
                )
            sheet_xml_bytes = zf.read(sheet_path)
            infos = {i.filename: i for i in zf.infolist()}
            other_entries = [(n, zf.read(n)) for n in zf.namelist() if n != sheet_path]
    except (zipfile.BadZipFile, KeyError, ValueError, ET.ParseError) as exc:
        return "failed", f"could not read/resolve xlsx sheet: {exc}"

    try:
        tree_root = ET.fromstring(sheet_xml_bytes)
    except ET.ParseError as exc:
        return "failed", f"worksheet XML did not parse: {exc}"
    sheet_data = tree_root.find(f"{{{XLSX_MAIN_NS}}}sheetData")
    if sheet_data is None:
        return "failed", "worksheet has no <sheetData>"

    row_el = _find_or_create_row(sheet_data, _row_num(cell))
    c_el = _find_or_create_cell(row_el, cell)

    had_formula = c_el.find(f"{{{XLSX_MAIN_NS}}}f") is not None
    if not had_formula and _existing_cell_text(c_el) == str(value):
        return "noop", f"{sheet}!{cell} already literal {value!r}, no formula present"

    _set_cell_literal(c_el, value)
    new_sheet_xml = ET.tostring(tree_root, encoding="UTF-8", xml_declaration=True)

    tmp_path = path.with_name(path.name + ".tmp_apply")
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf_out:
            for name, data in other_entries:
                zf_out.writestr(infos[name], data)
            zf_out.writestr(infos[sheet_path], new_sheet_xml)
        tmp_path.replace(path)
    except OSError as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        return "failed", f"write failed: {exc}"

    try:
        with zipfile.ZipFile(path, "r") as zf:
            check_root = ET.fromstring(zf.read(sheet_path))
        check_sheet_data = check_root.find(f"{{{XLSX_MAIN_NS}}}sheetData")
        check_c = None
        for r in check_sheet_data.findall(f"{{{XLSX_MAIN_NS}}}row"):
            if r.get("r") == str(_row_num(cell)):
                for c in r.findall(f"{{{XLSX_MAIN_NS}}}c"):
                    if c.get("r") == cell:
                        check_c = c
                break
        if check_c is None:
            return "failed", "read-back after write: cell not found"
        if check_c.find(f"{{{XLSX_MAIN_NS}}}f") is not None:
            return "failed", "read-back after write: formula still present"
        if _existing_cell_text(check_c) != str(value):
            return "failed", "read-back after write did not match (write did not land)"
    except (zipfile.BadZipFile, ET.ParseError) as exc:
        return "failed", f"read-back verification failed: {exc}"

    detail = (
        f"{sheet}!{cell}: "
        + ("formula removed, " if had_formula else "")
        + f"literal value set to {value!r}"
    )
    return "applied", detail


# ---------------------------------------------------------------------------
# replace_docx_text - run-aware, falls back to paragraph-level collapse only
# when the match spans a run boundary.
# ---------------------------------------------------------------------------


def _iter_all_paragraphs(container):
    """Yield every paragraph in a Document or _Cell, including paragraphs
    inside tables and nested tables (a _Cell has its own .tables)."""
    for p in container.paragraphs:
        yield p
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_all_paragraphs(cell)


def _docx_full_text(path: Path):
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in _iter_all_paragraphs(doc))


def apply_replace_docx_text(path: Path, find: str, replace: str) -> tuple[str, str]:
    if not path.is_file():
        return "failed", f"file not found: {path}"
    if not find:
        return "failed", "missing 'find'"

    try:
        from docx import Document
    except ImportError as exc:
        return "failed", f"python-docx not importable: {exc}"

    try:
        doc = Document(str(path))
    except Exception as exc:  # noqa: BLE001
        return "failed", f"could not open docx: {exc}"

    paragraphs = list(_iter_all_paragraphs(doc))

    run_hits = [(p, r) for p in paragraphs for r in p.runs if find in r.text]
    if len(run_hits) > 1:
        return "failed", f"find text occurs in {len(run_hits)} runs, ambiguous"

    if len(run_hits) == 1:
        p, r = run_hits[0]
        if r.text.count(find) != 1:
            return (
                "failed",
                "find text occurs more than once within a single run, ambiguous",
            )
        r.text = r.text.replace(find, replace, 1)
        mode = "single-run replace (formatting preserved)"
    else:
        para_hits = [p for p in paragraphs if find in p.text]
        if len(para_hits) == 0:
            return "noop", "find text absent (already applied or never present)"
        if len(para_hits) > 1:
            return (
                "failed",
                f"find text occurs across {len(para_hits)} paragraphs, ambiguous",
            )
        p = para_hits[0]
        full_text = p.text
        if full_text.count(find) != 1:
            return (
                "failed",
                "find text occurs more than once within the spanning paragraph, ambiguous",
            )
        new_text = full_text.replace(find, replace, 1)
        if p.runs:
            p.runs[0].text = new_text
            for extra in p.runs[1:]:
                extra.text = ""
        else:
            p.add_run(new_text)
        mode = "cross-run paragraph replace (formatting collapsed to first run in that paragraph)"

    try:
        doc.save(str(path))
    except Exception as exc:  # noqa: BLE001
        return "failed", f"save failed: {exc}"

    if replace:
        try:
            check_text = _docx_full_text(path)
        except Exception as exc:  # noqa: BLE001
            return "failed", f"read-back verification failed: {exc}"
        if replace not in check_text:
            return "failed", "read-back after write: replacement text not found"

    return "applied", mode


def _metadata_residual_note(path: Path, task_dir: Path, location) -> str:
    """Ask the metadata_leak check itself (its own extractors and matcher) whether this file still trips it at `location`. The check stops
    at the first expected value a text matches, so clearing one collision can expose a second; this says so at edit time.
    """
    try:
        import metadata_verify

        left = metadata_verify.residual_findings(path, task_dir, location)
    except Exception as exc:  # noqa: BLE001
        return f" | metadata check not run ({type(exc).__name__}: {exc})"
    high = [f for f in left if f.get("confidence") == "high"]
    if high:
        return " | STILL BLOCKS: " + "; ".join(
            f"matches {f.get('value') or f.get('filename')} (criterion {f.get('criterion', '-')})"
            for f in high[:4]
        )
    if left:
        return f" | metadata check: no blocking finding ({len(left)} candidate warning(s), non-blocking)"
    return " | metadata check: clean"


def apply_normalize_line_endings(path: Path) -> tuple[str, str]:
    """CRLF and lone CR to LF, byte-exact otherwise. verifier_executability fails a tests/test.sh with CRLF (a CRLF shebang names an
    interpreter that does not exist)."""
    if not path.is_file():
        return "failed", f"file not found: {path}"
    raw = path.read_bytes()
    if b"\r" not in raw:
        return "noop", "no CR bytes present"
    new = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    tmp = path.with_name(path.name + ".tmp_apply")
    tmp.write_bytes(new)
    tmp.replace(path)
    if path.read_bytes() != new:
        return "failed", "read-back after write did not match (write did not land)"
    n_cr = raw.count(b"\r")
    return "applied", f"{n_cr} CR byte(s) removed"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--corpus-root", type=Path, required=True)
    ap.add_argument("--fix-log", type=Path, required=True)
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text())
    edits = plan.get("edits", [])

    # `notes` was previously read nowhere - a fixer's "not fixable without a person" (or any other
    # account of what it left unfixed) never reached the fix log. Coordinator, 2026-09-19 22:50Z:
    # the new fake-fix rule tells the fixer to write an unfixable row there instead of softening a
    # criterion, so the row has to actually land somewhere a human can find it.
    notes = plan.get("notes")
    if notes:
        log_line(args.fix_log, f"notes: {notes}")

    if not edits:
        log_line(args.fix_log, "apply_plan.py: PLAN.json has zero edits, nothing to do")
        return 0

    task_dir = args.corpus_root / args.task
    any_failed = False
    args.fix_log.parent.mkdir(parents=True, exist_ok=True)

    for i, edit in enumerate(edits):
        op = edit.get("op")
        rel_file = edit.get("file", "")
        finding_id = edit.get("finding_id", "?")
        reason = edit.get("reason", "")
        path = (task_dir / rel_file).resolve()
        # Refuse to write outside the task dir (defense against a bad rel path).
        try:
            path.relative_to(task_dir.resolve())
        except ValueError:
            log_line(
                args.fix_log,
                f"edit {i} [{finding_id}] file={rel_file!r} FAILED: resolves outside task dir, refused",
            )
            any_failed = True
            continue

        if op == "replace_literal":
            outcome, detail = apply_replace_literal(
                path, edit.get("find", ""), edit.get("replace", "")
            )
        elif op == "append_text":
            outcome, detail = apply_append_text(path, edit.get("text", ""))
        elif op == "set_xlsx_cell":
            outcome, detail = apply_set_xlsx_cell(
                path, edit.get("sheet", ""), edit.get("cell", ""), edit.get("value")
            )
        elif op == "replace_docx_text":
            outcome, detail = apply_replace_docx_text(
                path, edit.get("find", ""), edit.get("replace", "")
            )
        elif op == "replace_ooxml_text":
            rel_norm = rel_file.replace("\\", "/")
            if not rel_norm.startswith(
                ("environment/initial_workspace/", "solution/files/")
            ):
                outcome, detail = (
                    "failed",
                    "replace_ooxml_text only edits files under environment/initial_workspace/ or solution/files/",
                )
            else:
                import ooxml_edit

                outcome, detail = ooxml_edit.replace_text(
                    path,
                    edit.get("find", ""),
                    edit.get("replace"),
                    part=edit.get("part"),
                    location=edit.get("location"),
                    kind=edit.get("kind"),
                )
                if outcome in ("applied", "noop") and edit.get("kind") in (
                    "cell_comment",
                    "speaker_notes",
                    "header_footer",
                ):
                    detail += _metadata_residual_note(
                        path, task_dir, edit.get("location")
                    )
        elif op == "normalize_line_endings":
            rel_norm = rel_file.replace("\\", "/")
            if not (
                rel_norm.startswith("tests/")
                and rel_norm.endswith((".sh", ".py", ".toml", ".txt", ".md"))
            ):
                outcome, detail = (
                    "failed",
                    "normalize_line_endings only edits tests/*.sh|py|toml|txt|md",
                )
            else:
                outcome, detail = apply_normalize_line_endings(path)
        elif op == "create_xlsx_extract":
            rel_source = edit.get("source", "")
            source_path = (task_dir / rel_source).resolve()
            try:
                source_path.relative_to(task_dir.resolve())
            except ValueError:
                outcome, detail = (
                    "failed",
                    f"source={rel_source!r} resolves outside task dir, refused",
                )
            else:
                outcome, detail = apply_create_xlsx_extract(
                    path, source_path, edit.get("sheet", ""), edit.get("columns", [])
                )
        else:
            outcome, detail = "failed", f"unknown op: {op!r}"

        log_line(
            args.fix_log,
            f"edit {i} [{finding_id}] {op} {rel_file}: {outcome.upper()} - {detail} ({reason})",
        )
        if outcome in ("failed", "reverted"):
            any_failed = True

    return 1 if any_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
