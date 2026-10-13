#!/usr/bin/env python3
"""v3digest_build.py TASKDIR OUT_MD [--budget CHARS]

Deterministic digest of one SVC-PC/EKW harbor task package (sev2_corpus/<task>/)
for the digest-review measurement (see /root/qc/_prompts/v3digest/RESULT.md).

Walks TASKDIR and writes one Markdown file to OUT_MD containing:
  (a) a file index (path, disk bytes, digest chars, estimated tokens = chars/4)
  (b) instruction.md, tests/task_prompt.txt, tests/reward.toml, every
      tests/**/judge.toml, and environment/Dockerfile - verbatim, always first
  (c) every .xlsx/.xlsm via openpyxl loaded TWICE (data_only=True and False),
      per sheet: hidden/visible state, dimensions, merged ranges, image/chart
      counts, then one "coord = cached_value | formula" line per non-empty cell
      (non-empty = cached value is not None OR the cell carries a formula -
      this deliberately catches a formula cell with NO cached value, the
      openpyxl-written-workbook defect class the review spec's own 1.2 check
      names)
  (d) every .docx via python-docx: paragraphs prefixed by style name, tables
      as pipe rows, plus a tracked-changes (w:ins/w:del) and comments
      (word/comments.xml) flag read from the raw part XML
  (e) every .pdf via pdftotext -layout
  (f) .csv/.txt/.md/.json/.toml (not already emitted under (b)) and any other
      file that decodes cleanly as text - verbatim
  (g) everything else (images, zip, and anything that fails a text decode, plus
      any extraction that raised) - listed by name and size only

Golden/solution files and environment corpus files both get full extraction;
(b)'s named files are pulled out once and never duplicated under (f).

--budget CHARS: if the first full build exceeds CHARS, drop environment/**
files (never tests/**, instruction.md, environment/Dockerfile, or
solution/**) largest-digest-chars-first, replacing each dropped file's body
with a stub and "[omitted, N bytes]" in the index, until the digest fits or
there is nothing left under environment/ to drop. Always reports what was
dropped, on stdout and in a trailing "## Omitted files" section.

Extras beyond the letter of (a)-(g), noted here since the task spec doesn't
name these formats: .doc in this corpus is Word's MHTML "Web Page" export
(confirmed via `file`), not legacy OLE - handled via email/bs4, falling back
to antiword, falling back to (g). .pptx handled via python-pptx (slide +
notes text). .html treated as verbatim text under (f). Anything else that
decodes cleanly as UTF-8/latin-1 text also falls under (f) rather than being
hardcoded per-extension.

Prints total digest chars to stdout at the end.
"""

from __future__ import annotations

import argparse
import email
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import openpyxl
except ImportError:
    openpyxl = None
try:
    import docx as python_docx
except ImportError:
    python_docx = None
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
try:
    import pptx as python_pptx
except ImportError:
    python_pptx = None

BEGIN = "----- BEGIN FILE: {} -----"
END = "----- END FILE: {} -----"

SPREADSHEET_EXT = {".xlsx", ".xlsm"}
DOCX_EXT = {".docx"}
PDF_EXT = {".pdf"}
DOC_EXT = {".doc"}
PPTX_EXT = {".pptx"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".ico", ".svg"}
ALWAYS_BINARY_EXT = {
    ".zip",
    ".xls",
    ".ppt",
}  # legacy OLE binary / archive - no cheap text path here


def is_core_spec_path(relpath: str) -> bool:
    p = relpath.replace("\\", "/")
    if p == "instruction.md":
        return True
    if p == "tests/task_prompt.txt":
        return True
    if p == "tests/reward.toml":
        return True
    if p == "environment/Dockerfile":
        return True
    if p.startswith("tests/") and p.endswith("/judge.toml"):
        return True
    return False


def try_text_decode(data: bytes) -> str | None:
    if b"\x00" in data:
        return None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def extract_xlsx(path: Path) -> str:
    out = []
    try:
        wb_val = openpyxl.load_workbook(path, data_only=True, read_only=False)
        wb_frm = openpyxl.load_workbook(path, data_only=False, read_only=False)
    except Exception as e:
        return f"[extraction error: {type(e).__name__}: {e}]"
    for sheet_name in wb_val.sheetnames:
        ws_v = wb_val[sheet_name]
        ws_f = wb_frm[sheet_name] if sheet_name in wb_frm.sheetnames else None
        n_images = len(getattr(ws_v, "_images", []) or [])
        n_charts = len(getattr(ws_v, "_charts", []) or [])
        try:
            merged = [str(r) for r in ws_v.merged_cells.ranges]
        except Exception:
            merged = []
        out.append(
            f"### sheet: {sheet_name}\n"
            f"state={ws_v.sheet_state} dimensions={ws_v.dimensions} "
            f"merged={merged} images={n_images} charts={n_charts}\n"
        )
        lines = []
        try:
            max_row = ws_v.max_row or 0
            max_col = ws_v.max_column or 0
        except Exception:
            max_row = max_col = 0
        for row in ws_v.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
            for cell in row:
                v = cell.value
                f = None
                if ws_f is not None:
                    try:
                        fc = ws_f.cell(row=cell.row, column=cell.column)
                        if fc.data_type == "f":
                            f = fc.value
                    except Exception:
                        f = None
                if v is None and f is None:
                    continue
                v_str = "" if v is None else str(v)
                f_str = "" if f is None else str(f)
                lines.append(f"{cell.coordinate} = {v_str} | {f_str}")
        out.append("\n".join(lines))
    try:
        wb_val.close()
        wb_frm.close()
    except Exception:
        pass
    return "\n".join(out)


def extract_docx(path: Path) -> str:
    out = []
    try:
        doc = python_docx.Document(str(path))
    except Exception as e:
        return f"[extraction error: {type(e).__name__}: {e}]"
    tracked = False
    comments = False
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "word/document.xml" in names:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
                if "w:ins" in xml or "w:del" in xml:
                    tracked = True
            if "word/comments.xml" in names:
                cxml = z.read("word/comments.xml").decode("utf-8", errors="replace")
                if "<w:comment " in cxml or "<w:comment>" in cxml:
                    comments = True
    except Exception:
        pass
    out.append(f"tracked_changes={tracked} comments={comments}")
    body_parts = []
    # Walk block items in document order (paragraphs + tables) so structure is preserved.
    from docx.oxml.ns import qn  # local import, python-docx internal but stable

    body = doc.element.body
    para_iter = iter(doc.paragraphs)
    table_iter = iter(doc.tables)
    para_map = {p._p: p for p in doc.paragraphs}
    table_map = {t._tbl: t for t in doc.tables}
    for child in body.iterchildren():
        if child.tag == qn("w:p") and child in para_map:
            p = para_map[child]
            text = p.text
            if text.strip():
                body_parts.append(f"[{p.style.name if p.style else 'Normal'}] {text}")
        elif child.tag == qn("w:tbl") and child in table_map:
            t = table_map[child]
            for row in t.rows:
                cells = [c.text.replace("\n", " ") for c in row.cells]
                body_parts.append("| " + " | ".join(cells) + " |")
    out.append("\n".join(body_parts))
    return "\n".join(out)


def extract_pdf(path: Path) -> str:
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            timeout=120,
        )
        if r.returncode != 0:
            return f"[extraction error: pdftotext exit {r.returncode}: {r.stderr.decode(errors='replace')[:500]}]"
        return r.stdout.decode("utf-8", errors="replace")
    except Exception as e:
        return f"[extraction error: {type(e).__name__}: {e}]"


def extract_doc(path: Path) -> str:
    data = path.read_bytes()
    head = data[:600]
    if b"MIME-Version" in head or b"multipart" in head.lower():
        try:
            msg = email.message_from_bytes(data)
            html_part = None
            text_part = None
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    if ctype == "text/html" and html_part is None:
                        html_part = part
                    elif ctype == "text/plain" and text_part is None:
                        text_part = part
            else:
                if msg.get_content_type() == "text/html":
                    html_part = msg
            if html_part is not None and BeautifulSoup is not None:
                payload = html_part.get_payload(decode=True) or b""
                charset = html_part.get_content_charset() or "utf-8"
                html = payload.decode(charset, errors="replace")
                return BeautifulSoup(html, "html.parser").get_text("\n")
            if text_part is not None:
                payload = text_part.get_payload(decode=True) or b""
                charset = text_part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        except Exception as e:
            pass  # fall through to antiword
    try:
        r = subprocess.run(["antiword", str(path)], capture_output=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", errors="replace")
    except Exception:
        pass
    return None  # signal: treat as binary (g)


def extract_pptx(path: Path) -> str:
    try:
        prs = python_pptx.Presentation(str(path))
    except Exception as e:
        return f"[extraction error: {type(e).__name__}: {e}]"
    out = []
    for i, slide in enumerate(prs.slides, 1):
        out.append(f"### slide {i}")
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(r.text for r in para.runs) or para.text
                    if text.strip():
                        out.append(text)
            if shape.has_table:
                for row in shape.table.rows:
                    cells = [c.text.replace("\n", " ") for c in row.cells]
                    out.append("| " + " | ".join(cells) + " |")
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            note_text = slide.notes_slide.notes_text_frame.text
            if note_text.strip():
                out.append(f"[notes] {note_text}")
    return "\n".join(out)


def _basename_variants(p: Path) -> list[str]:
    name = p.name.lower()
    variants = {name}
    if p.suffix:
        variants.add(name[: -len(p.suffix)])
    return [v for v in variants if v]


def _lightweight_xlsx_index(path: Path) -> str:
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as e:
        return f"[index error: {type(e).__name__}: {e}]"
    out = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        header = []
        try:
            for row in ws.iter_rows(min_row=1, max_row=1):
                header = ["" if c.value is None else str(c.value) for c in row]
        except Exception:
            header = []
        out.append(
            f"sheet={sheet_name!r} rows={ws.max_row} cols={ws.max_column} header={header}"
        )
    try:
        wb.close()
    except Exception:
        pass
    return "\n".join(out)


def _lightweight_text_index(full_text: str) -> str:
    snippet = full_text[:300]
    return f"[first 300 chars of {len(full_text)}]\n{snippet}"


def build_digest_cited(task_dir: Path, budget: int | None):
    """--mode cited: verbatim for core spec files and everything under
    solution/** regardless of size; verbatim for any environment/** file
    whose basename (with or without extension, case-insensitive) is cited by
    the golden's own extracted text, instruction.md, tests/task_prompt.txt,
    or any tests/**/judge.toml (raw text, which also catches basenames named
    inside a judge.toml `files = [...]` list); index-only (sheet
    names+dims+header row for spreadsheets, first 300 extracted chars for
    everything else text-extractable, name+size only for genuine binaries)
    for every other environment file. --budget CHARS, if still exceeded,
    demotes CITED environment files (never core, never solution/**)
    largest-digest-chars-first to the same index-only treatment, recording
    what was demoted."""
    all_files = [p for p in sorted(task_dir.rglob("*")) if p.is_file()]

    def rel_of(p: Path) -> str:
        return str(p.relative_to(task_dir)).replace("\\", "/")

    core_paths = [p for p in all_files if is_core_spec_path(rel_of(p))]
    solution_paths = [p for p in all_files if rel_of(p).startswith("solution/")]
    environment_paths = [
        p
        for p in all_files
        if rel_of(p).startswith("environment/") and not is_core_spec_path(rel_of(p))
    ]
    other_paths = [
        p
        for p in all_files
        if p not in core_paths
        and p not in solution_paths
        and p not in environment_paths
    ]  # task.toml and anything else outside the three trees

    entries = {}

    def full_body_for(p: Path) -> tuple[str, str]:
        """Returns (category, body) using the SAME extraction functions as
        full mode, for any file regardless of location."""
        ext = p.suffix.lower()
        if ext in SPREADSHEET_EXT:
            return "spreadsheet", extract_xlsx(p)
        if ext in DOCX_EXT:
            return "docx", extract_docx(p)
        if ext in PDF_EXT:
            return "pdf", extract_pdf(p)
        if ext in DOC_EXT:
            body = extract_doc(p)
            return ("doc", body) if body is not None else ("binary", None)
        if ext in PPTX_EXT:
            return "pptx", extract_pptx(p)
        if ext in IMAGE_EXT or ext in ALWAYS_BINARY_EXT:
            return "binary", None
        try:
            data = p.read_bytes()
        except Exception as e:
            return "text", f"[read error: {type(e).__name__}: {e}]"
        text = try_text_decode(data)
        return ("text", text) if text is not None else ("binary", None)

    def add_full_entry(p: Path, tag: str, droppable_as_cited: bool):
        rel = rel_of(p)
        cat, body = full_body_for(p)
        entries[rel] = {
            "path": p,
            "size": p.stat().st_size,
            "category": cat,
            "body": body,
            "tag": tag,
            "cited_droppable": droppable_as_cited,
            "omitted": False,
            "index_only": False,
        }

    def add_index_entry(p: Path, tag: str):
        rel = rel_of(p)
        size = p.stat().st_size
        ext = p.suffix.lower()
        if ext in SPREADSHEET_EXT:
            body = _lightweight_xlsx_index(p)
            cat = "spreadsheet-index"
        elif ext in IMAGE_EXT or ext in ALWAYS_BINARY_EXT:
            body = None
            cat = "binary"
        else:
            _, full_text = full_body_for(p)
            if full_text is None:
                body, cat = None, "binary"
            else:
                body, cat = _lightweight_text_index(full_text), "index"
        entries[rel] = {
            "path": p,
            "size": size,
            "category": cat,
            "body": body,
            "tag": tag,
            "cited_droppable": False,
            "omitted": False,
            "index_only": True,
        }

    # 1. Core spec files: always full, verbatim (same as full mode).
    for p in core_paths:
        add_full_entry(p, "core", droppable_as_cited=False)
    # Anything outside core/solution/environment (e.g. task.toml): treat like full mode's "text" bucket.
    for p in other_paths:
        add_full_entry(p, "other", droppable_as_cited=False)

    # 2. Solution/golden: always full, verbatim, regardless of size, never dropped.
    for p in solution_paths:
        add_full_entry(p, "solution", droppable_as_cited=False)

    # Build the citation corpus: golden text + instruction.md + task_prompt.txt + every judge.toml, raw.
    citation_parts = []
    for rel, e in entries.items():
        if e["tag"] == "solution" and isinstance(e["body"], str):
            citation_parts.append(e["body"])
    instruction_p = task_dir / "instruction.md"
    if instruction_p.is_file():
        citation_parts.append(try_text_decode(instruction_p.read_bytes()) or "")
    prompt_p = task_dir / "tests" / "task_prompt.txt"
    if prompt_p.is_file():
        citation_parts.append(try_text_decode(prompt_p.read_bytes()) or "")
    for jt in task_dir.glob("tests/**/judge.toml"):
        citation_parts.append(try_text_decode(jt.read_bytes()) or "")
    citation_corpus = "\n".join(citation_parts).lower()

    def is_cited(p: Path) -> bool:
        return any(v in citation_corpus for v in _basename_variants(p))

    # 3. Environment files: full if cited, index-only otherwise.
    n_index_only = 0
    index_only_bytes = 0
    for p in environment_paths:
        if is_cited(p):
            add_full_entry(p, "environment-cited", droppable_as_cited=True)
        else:
            add_index_entry(p, "environment-uncited")
            n_index_only += 1
            index_only_bytes += p.stat().st_size

    def block_text(rel, e):
        if e["omitted"] or e["body"] is None:
            return ""
        if e["index_only"]:
            return (
                f"----- INDEX: {rel} -----\n{e['body']}\n----- END INDEX: {rel} -----\n"
            )
        return BEGIN.format(rel) + "\n" + e["body"] + "\n" + END.format(rel) + "\n"

    for rel, e in entries.items():
        e["digest_chars"] = len(block_text(rel, e))

    demoted = []
    if budget is not None:

        def total_chars():
            return sum(e["digest_chars"] for e in entries.values())

        cited_sorted = sorted(
            (
                rel
                for rel, e in entries.items()
                if e["cited_droppable"] and not e["omitted"]
            ),
            key=lambda r: entries[r]["digest_chars"],
            reverse=True,
        )
        idx = 0
        while total_chars() > budget and idx < len(cited_sorted):
            rel = cited_sorted[idx]
            e = entries[rel]
            p = e["path"]
            ext = p.suffix.lower()
            if ext in SPREADSHEET_EXT:
                new_body, new_cat = _lightweight_xlsx_index(p), "spreadsheet-index"
            elif ext in IMAGE_EXT or ext in ALWAYS_BINARY_EXT:
                new_body, new_cat = None, "binary"
            else:
                full_text = e["body"] if isinstance(e["body"], str) else None
                new_body = (
                    _lightweight_text_index(full_text)
                    if full_text is not None
                    else None
                )
                new_cat = "index" if new_body is not None else "binary"
            demoted.append((rel, e["size"]))
            e["body"], e["category"], e["index_only"], e["cited_droppable"] = (
                new_body,
                new_cat,
                True,
                False,
            )
            e["digest_chars"] = len(block_text(rel, e))
            n_index_only += 1
            index_only_bytes += e["size"]
            idx += 1

    lines = []
    lines.append(f"# Digest (cited mode): {task_dir.name}")
    lines.append("")
    lines.append(
        f"Built {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} by "
        f"v3digest_build.py --mode cited from {task_dir}"
    )
    lines.append(
        f"Index-only environment files (uncited, or demoted by --budget): {n_index_only}, "
        f"totaling {index_only_bytes} disk bytes."
    )
    if demoted:
        lines.append(
            f"--budget {budget}: demoted {len(demoted)} previously-cited file(s) to index-only "
            f"to fit: {[r for r, _ in demoted]}"
        )
    lines.append("")
    lines.append("## File index")
    lines.append("")
    lines.append(
        "| path | disk bytes | digest chars | est. tokens (chars/4) | category | tag | note |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for rel in sorted(entries):
        e = entries[rel]
        note = "binary, listed only" if e["category"] == "binary" else ""
        lines.append(
            f"| {rel} | {e['size']} | {e['digest_chars']} | {e['digest_chars'] // 4} | "
            f"{e['category']} | {e['tag']} | {note} |"
        )
    total_chars_val = sum(e["digest_chars"] for e in entries.values())
    total_size = sum(e["size"] for e in entries.values())
    lines.append("")
    lines.append(
        f"Total files: {len(entries)}. Total disk bytes: {total_size}. "
        f"Total digest chars: {total_chars_val}. Total estimated tokens: {total_chars_val // 4}."
    )
    lines.append("")

    def section(title, pred):
        lines.append(f"## {title}")
        lines.append("")
        any_emitted = False
        for rel in sorted(entries):
            e = entries[rel]
            if not pred(e) or e["category"] == "binary":
                continue
            any_emitted = True
            lines.append(block_text(rel, e))
        if not any_emitted:
            lines.append("(none)")
        lines.append("")

    section("Core spec files (verbatim)", lambda e: e["tag"] == "core")
    section("Other top-level files (verbatim)", lambda e: e["tag"] == "other")
    section("Solution/golden (verbatim, always full)", lambda e: e["tag"] == "solution")
    section(
        "Cited environment files (verbatim, same extraction as full mode)",
        lambda e: e["tag"] == "environment-cited" and not e["index_only"],
    )
    section(
        "Index-only environment files (uncited, or budget-demoted)",
        lambda e: e["index_only"],
    )

    lines.append("## Binaries (name and size only, no content available)")
    lines.append("")
    any_bin = False
    for rel in sorted(entries):
        e = entries[rel]
        if e["category"] == "binary":
            any_bin = True
            lines.append(f"- {rel} ({e['size']} bytes, tag={e['tag']})")
    if not any_bin:
        lines.append("(none)")
    lines.append("")

    doc_text = "\n".join(lines)
    return doc_text, total_chars_val, demoted


def build_digest(task_dir: Path, budget: int | None):
    all_files = []
    for p in sorted(task_dir.rglob("*")):
        if p.is_file():
            all_files.append(p)

    core_paths = []
    other_paths = []
    for p in all_files:
        rel = str(p.relative_to(task_dir))
        if is_core_spec_path(rel):
            core_paths.append(p)
        else:
            other_paths.append(p)

    # entries: relpath -> dict(size, category, block_body, digest_chars, droppable)
    entries = {}

    def render_entry(p: Path, category: str):
        rel = str(p.relative_to(task_dir))
        size = p.stat().st_size
        ext = p.suffix.lower()
        body = None
        cat = category
        if cat == "spreadsheet":
            body = extract_xlsx(p)
        elif cat == "docx":
            body = extract_docx(p)
        elif cat == "pdf":
            body = extract_pdf(p)
        elif cat == "doc":
            body = extract_doc(p)
            if body is None:
                cat = "binary"
        elif cat == "pptx":
            body = extract_pptx(p)
        elif cat in ("text", "core"):
            try:
                data = p.read_bytes()
            except Exception as e:
                body = f"[read error: {type(e).__name__}: {e}]"
            else:
                text = try_text_decode(data)
                if text is None:
                    # a "core" path (instruction.md, judge.toml, ...) is always
                    # plain text by construction; if this ever fails to decode
                    # something is badly wrong with the file, so surface the
                    # raw bytes as latin-1 rather than silently demoting a
                    # required spec file to the binary-listing bucket.
                    body = data.decode("latin-1") if cat == "core" else None
                    if body is None:
                        cat = "binary"
                else:
                    body = text
        droppable = rel.replace("\\", "/").startswith(
            "environment/"
        ) and not is_core_spec_path(rel)
        entries[rel] = {
            "path": p,
            "size": size,
            "category": cat,
            "body": body,
            "droppable": droppable,
            "omitted": False,
        }

    for p in core_paths:
        render_entry(p, "core")

    for p in other_paths:
        ext = p.suffix.lower()
        if ext in SPREADSHEET_EXT:
            render_entry(p, "spreadsheet")
        elif ext in DOCX_EXT:
            render_entry(p, "docx")
        elif ext in PDF_EXT:
            render_entry(p, "pdf")
        elif ext in DOC_EXT:
            render_entry(p, "doc")
        elif ext in PPTX_EXT:
            render_entry(p, "pptx")
        elif ext in IMAGE_EXT or ext in ALWAYS_BINARY_EXT:
            render_entry(p, "binary")
        else:
            render_entry(p, "text")

    def block_text(rel, e):
        if e["category"] == "binary" or e["omitted"]:
            return ""
        return (
            BEGIN.format(rel) + "\n" + (e["body"] or "") + "\n" + END.format(rel) + "\n"
        )

    for rel, e in entries.items():
        e["digest_chars"] = len(block_text(rel, e))

    omitted_list = []
    if budget is not None:

        def total_chars():
            return sum(e["digest_chars"] for e in entries.values())

        droppable_sorted = sorted(
            (rel for rel, e in entries.items() if e["droppable"]),
            key=lambda r: entries[r]["digest_chars"],
            reverse=True,
        )
        idx = 0
        while total_chars() > budget and idx < len(droppable_sorted):
            rel = droppable_sorted[idx]
            e = entries[rel]
            e["omitted"] = True
            e["digest_chars"] = 0
            omitted_list.append((rel, e["size"]))
            idx += 1

    # Assemble document
    lines = []
    lines.append(f"# Digest: {task_dir.name}")
    lines.append("")
    lines.append(
        f"Built {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} by v3digest_build.py from {task_dir}"
    )
    lines.append("")
    lines.append("## File index")
    lines.append("")
    lines.append(
        "| path | disk bytes | digest chars | est. tokens (chars/4) | category | note |"
    )
    lines.append("|---|---|---|---|---|---|")
    for rel in sorted(entries):
        e = entries[rel]
        note = ""
        if e["omitted"]:
            note = f"[omitted, {e['size']} bytes]"
        elif e["category"] == "binary":
            note = "binary, listed only"
        lines.append(
            f"| {rel} | {e['size']} | {e['digest_chars']} | {e['digest_chars'] // 4} | {e['category']} | {note} |"
        )
    total_chars_val = sum(e["digest_chars"] for e in entries.values())
    total_size = sum(e["size"] for e in entries.values())
    lines.append("")
    lines.append(
        f"Total files: {len(entries)}. Total disk bytes: {total_size}. "
        f"Total digest chars: {total_chars_val}. Total estimated tokens: {total_chars_val // 4}."
    )
    lines.append("")

    def section(title, cats):
        lines.append(f"## {title}")
        lines.append("")
        any_emitted = False
        for rel in sorted(entries):
            e = entries[rel]
            if e["category"] not in cats or e["omitted"]:
                continue
            any_emitted = True
            lines.append(block_text(rel, e))
        if not any_emitted:
            lines.append("(none)")
        lines.append("")

    section("(b) Core spec files (verbatim)", {"core"})
    section("(c) Spreadsheets (openpyxl, cached value | formula)", {"spreadsheet"})
    section("(d) Word documents", {"docx", "doc"})
    section("(e) PDFs", {"pdf"})
    section("(f) Other text files (verbatim)", {"text"})
    section("(g) Presentations", {"pptx"})

    lines.append("## Other binaries (name and size only)")
    lines.append("")
    any_bin = False
    for rel in sorted(entries):
        e = entries[rel]
        if e["category"] == "binary" and not e["omitted"]:
            any_bin = True
            lines.append(f"- {rel} ({e['size']} bytes)")
    if not any_bin:
        lines.append("(none)")
    lines.append("")

    if omitted_list:
        lines.append("## Omitted files (budget trim)")
        lines.append("")
        lines.append(
            f"--budget {budget} exceeded on the untrimmed build; dropped largest-first from environment/**:"
        )
        for rel, size in omitted_list:
            lines.append(f"- {rel} ({size} bytes)")
        lines.append("")

    doc_text = "\n".join(lines)
    return doc_text, total_chars_val, omitted_list


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("taskdir")
    ap.add_argument("out_md")
    ap.add_argument(
        "--budget",
        type=int,
        default=None,
        help="max digest chars; drops (mode=full: environment/** files; mode=cited: cited "
        "environment/** files) largest-first to fit",
    )
    ap.add_argument(
        "--mode",
        choices=("full", "cited"),
        default="full",
        help="full: extract every environment file in full (original spec). "
        "cited: full extraction only for environment files cited by the golden/"
        "instruction/task_prompt/judge.toml; everything else index-only.",
    )
    args = ap.parse_args()

    task_dir = Path(args.taskdir).resolve()
    if not task_dir.is_dir():
        print(f"ERROR: not a directory: {task_dir}", file=sys.stderr)
        return 2

    builder = build_digest_cited if args.mode == "cited" else build_digest
    doc_text, total_chars_val, omitted_list = builder(task_dir, args.budget)
    Path(args.out_md).write_text(doc_text, encoding="utf-8", newline="\n")
    print(
        f"{task_dir.name}: total_chars={total_chars_val} est_tokens={total_chars_val // 4} omitted={len(omitted_list)} -> {args.out_md}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
