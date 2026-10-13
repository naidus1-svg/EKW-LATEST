#!/usr/bin/env python3
"""ooxml_edit.py - byte-preserving text edits inside ONE part of an .xlsx / .xlsm / .docx / .pptx zip.

Why this exists (laptop, 2026-09-19): apply_plan.py could write text files and could edit a GOLDEN workbook cell or a
GOLDEN docx paragraph, but it had no op for any other binary file. A metadata_leak block is a string inside an ENVIRONMENT
file the solver receives (a cell comment in an .xlsx, a speaker note in a .pptx, a header or footer in a .docx), so a fix
plan that named it could not be applied; 1-5-0, 8-4-0, 77-7-0, 10-5-0 and 2-4-0 sat blocked with zero applicable edits.

What the op does:
  - resolves ONE target part of the zip (the comments part of a named sheet, a notes slide, a header or footer),
  - finds `find` in the decoded text of that part's containers (an xlsx <comment>, a docx or pptx paragraph),
  - matches with ALL WHITESPACE IGNORED on both sides (the check reports text with runs joined and whitespace collapsed, so a
    copy of its `text` field must match even when the raw runs are split or padded),
  - requires exactly one match in the searched scope (zero or several is refused, never guessed),
  - rewrites only the <t> / <w:t> / <a:t> text nodes the match touches, splicing into the RAW xml text so every other byte of
    the part, and every other member of the zip, is unchanged (no ElementTree round trip: it drops namespace declarations that
    mc:Ignorable names and Excel then reports the file as corrupt),
  - writes atomically and verifies: zip test, modified part parses as XML, every other member byte-identical, the new text is
    present and the old text absent in that container, and the file re-opens with openpyxl / python-docx / python-pptx.

Not supported, by design: sheet titles (renaming a sheet breaks every formula and criterion that names it), defined names,
threaded comments (xl/threadedComments), tracked-change text, and any part other than the ones listed above.

Usage as a module:  replace_text(path, find, replace, part=None, location=None, kind=None) -> (outcome, detail)
  outcome is "applied", "noop" (find absent and the replacement already present) or "failed".
CLI (for tests):  python3 ooxml_edit.py FILE --find TEXT --replace TEXT [--location LOC] [--part PART] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

XLSX_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# A text node is <t>, <w:t> or <a:t> with optional attributes. <w:tab/>, <w:tbl>, <a:tcPr>, <text> and <w:delText> do not match
# because the character after "t" must be whitespace or ">".
_TEXT_NODE_RE = re.compile(
    r"(<(?P<pfx>w:|a:)?t(?P<attrs>(?:\s[^>]*)?)>)(?P<text>[^<]*)(</(?:w:|a:)?t>)"
)
_XLSX_COMMENT_RE = re.compile(
    r"<comment\b(?P<attrs>[^>]*)>(?P<body>.*?)</comment>", re.S
)
_PARA_RE = re.compile(
    r"<(?P<pfx>w|a):p(?:\s[^>]*?)?(?<!/)>(?P<body>.*?)</(?P=pfx):p>", re.S
)
_REF_RE = re.compile(r'\bref="([^"]+)"')
_NUMERIC_REF_RE = re.compile(r"&#(x[0-9a-fA-F]+|[0-9]+);")
_ILLEGAL_XML_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

EDIT_EXTS = (".xlsx", ".xlsm", ".docx", ".pptx")


def _unescape(s: str) -> str:
    s = _NUMERIC_REF_RE.sub(
        lambda m: chr(
            int(m.group(1)[1:], 16) if m.group(1)[0] == "x" else int(m.group(1))
        ),
        s,
    )
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _squash(s: str) -> tuple[str, list[int]]:
    """s without any whitespace, plus for each kept character its index in s."""
    chars, idx = [], []
    for i, ch in enumerate(s):
        if not ch.isspace():
            chars.append(ch)
            idx.append(i)
    return "".join(chars), idx


def _resolve_rel_target(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def _xlsx_sheet_part(zf: zipfile.ZipFile, sheet_name: str) -> str:
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rid = None
    names = []
    for s in wb.iter(f"{{{XLSX_MAIN_NS}}}sheet"):
        names.append(s.get("name"))
        if s.get("name") == sheet_name:
            rid = s.get(f"{{{XLSX_REL_NS}}}id")
    if rid is None:
        raise ValueError(f"sheet {sheet_name!r} not in workbook (has {names})")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.iter(f"{{{PKG_REL_NS}}}Relationship"):
        if rel.get("Id") == rid:
            return _resolve_rel_target("xl/workbook.xml", rel.get("Target", ""))
    raise ValueError(f"no workbook relationship {rid!r} for sheet {sheet_name!r}")


def _xlsx_comments_part(zf: zipfile.ZipFile, sheet_name: str) -> str:
    sheet_part = _xlsx_sheet_part(zf, sheet_name)
    rels_part = posixpath.join(
        posixpath.dirname(sheet_part), "_rels", posixpath.basename(sheet_part) + ".rels"
    )
    if rels_part not in zf.namelist():
        raise ValueError(
            f"sheet {sheet_name!r} has no relationships part, so it has no comments"
        )
    rels = ET.fromstring(zf.read(rels_part))
    for rel in rels.iter(f"{{{PKG_REL_NS}}}Relationship"):
        if (rel.get("Type") or "").endswith("/comments"):
            return _resolve_rel_target(sheet_part, rel.get("Target", ""))
    raise ValueError(f"sheet {sheet_name!r} has no comments relationship")


def _default_parts(names: list[str], ext: str) -> list[str]:
    if ext in (".xlsx", ".xlsm"):
        return [
            n
            for n in names
            if re.fullmatch(r"xl/comments[^/]*\.xml|xl/comments/[^/]+\.xml", n)
        ]
    if ext == ".docx":
        return [
            n
            for n in names
            if re.fullmatch(r"word/(header|footer)\d*\.xml|word/comments\.xml", n)
        ]
    if ext == ".pptx":
        return [
            n for n in names if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n)
        ]
    return []


def _containers(raw: str, ext: str, ref: str | None) -> list[dict]:
    """Text containers of one part: each has its text nodes with absolute offsets into raw."""
    found = []
    if ext in (".xlsx", ".xlsm"):
        for m in _XLSX_COMMENT_RE.finditer(raw):
            rm = _REF_RE.search(m.group("attrs"))
            cref = rm.group(1) if rm else None
            if ref and (cref or "").upper() != ref.upper():
                continue
            found.append(
                {"label": f"comment {cref}", "lo": m.start("body"), "hi": m.end("body")}
            )
    else:
        for m in _PARA_RE.finditer(raw):
            found.append(
                {
                    "label": f"paragraph@{m.start()}",
                    "lo": m.start("body"),
                    "hi": m.end("body"),
                }
            )
    out = []
    for c in found:
        nodes = []
        for m in _TEXT_NODE_RE.finditer(raw, c["lo"], c["hi"]):
            nodes.append(
                {
                    "open_lo": m.start(1),
                    "open_hi": m.end(1),
                    "text_lo": m.start("text"),
                    "text_hi": m.end("text"),
                    "close_hi": m.end(),
                    "pfx": m.group("pfx") or "",
                    "attrs": m.group("attrs") or "",
                    "text": _unescape(m.group("text")),
                }
            )
        if nodes:
            c["nodes"] = nodes
            c["text"] = "".join(n["text"] for n in nodes)
            out.append(c)
    return out


def _load_check(path: str, ext: str) -> str | None:
    """Re-open the edited file with the library that matches its type; None means fine or the library is absent."""
    try:
        if ext in (".xlsx", ".xlsm"):
            import openpyxl

            openpyxl.load_workbook(
                path, read_only=False, keep_vba=(ext == ".xlsm")
            ).close()
        elif ext == ".docx":
            import docx

            docx.Document(path)
        elif ext == ".pptx":
            import pptx

            pptx.Presentation(path)
    except ImportError:
        return None
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    return None


def replace_text(
    path,
    find: str,
    replace: str,
    part: str | None = None,
    location: str | None = None,
    kind: str | None = None,
    dry_run: bool = False,
) -> tuple[str, str]:
    path = str(path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in EDIT_EXTS:
        return (
            "failed",
            f"unsupported file type {ext!r} (supported: {', '.join(EDIT_EXTS)})",
        )
    if not os.path.isfile(path):
        return "failed", f"file not found: {path}"
    if not isinstance(find, str) or len(_squash(find)[0]) < 3:
        return "failed", "find must contain at least 3 non-space characters"
    if not isinstance(replace, str):
        return "failed", 'replace must be a string (use "" to blank the matched text)'
    if _ILLEGAL_XML_CHARS_RE.search(replace):
        return "failed", "replace contains a control character that is not legal in XML"
    if kind == "sheet_title" or (
        location
        and not part
        and ext in (".xlsx", ".xlsm")
        and "!" not in location
        and not location.endswith(".xml")
    ):
        return "failed", (
            "sheet titles cannot be edited by this op: renaming a sheet breaks every formula and every criterion "
            "that names it. Leave the title and report it in notes (a generic label is not a leak)."
        )

    try:
        with zipfile.ZipFile(path, "r") as zf:
            infos = zf.infolist()
            names = [i.filename for i in infos]
            ref = None
            targets: list[str]
            if part:
                if part not in names:
                    return "failed", f"part {part!r} is not in the archive"
                targets = [part]
            elif location and ext in (".xlsx", ".xlsm") and "!" in location:
                sheet, ref = location.rsplit("!", 1)
                targets = [_xlsx_comments_part(zf, sheet)]
                if targets[0] not in names:
                    return (
                        "failed",
                        f"comments part {targets[0]!r} named by the sheet's relationships is not in the archive",
                    )
            elif location and location in names:
                targets = [location]
            else:
                targets = _default_parts(names, ext)
            if not targets:
                return (
                    "failed",
                    "no comment / notes / header / footer part to search in this file",
                )

            sq_find, _ = _squash(find)
            matches = (
                []
            )  # (part, container, span_lo, span_hi) in container-text offsets
            already = False
            sq_replace = _squash(replace)[0]
            raws = {}
            for tp in targets:
                raw_bytes = zf.read(tp)
                bom = raw_bytes.startswith(b"\xef\xbb\xbf")
                try:
                    raw = (
                        raw_bytes[3:].decode("utf-8")
                        if bom
                        else raw_bytes.decode("utf-8")
                    )
                except UnicodeDecodeError as exc:
                    return "failed", f"part {tp} is not UTF-8 ({exc})"
                raws[tp] = (raw, bom)
                for c in _containers(raw, ext, ref):
                    sq, idx = _squash(c["text"])
                    if sq_replace and sq_replace in sq and sq_find not in sq:
                        already = True
                    start = 0
                    while True:
                        p = sq.find(sq_find, start)
                        if p < 0:
                            break
                        matches.append((tp, c, idx[p], idx[p + len(sq_find) - 1] + 1))
                        start = p + len(sq_find)
            if not matches:
                if already:
                    return (
                        "noop",
                        "replacement text already present and find text absent",
                    )
                where = ", ".join(targets[:4]) + (" ..." if len(targets) > 4 else "")
                return (
                    "failed",
                    f"find text not found in {where} (matching ignores whitespace; copy find from the finding's text)",
                )
            if len(matches) > 1:
                labels = "; ".join(
                    f"{tp}:{c['label']}" for tp, c, _a, _b in matches[:6]
                )
                return "failed", (
                    f"find text matches {len(matches)} places ({labels}); give `part` and a longer `find` "
                    f"(or a `location` like Sheet!D10) so exactly one matches"
                )

            tp, c, a, b = matches[0]
            raw, bom = raws[tp]
            old_text = c["text"][a:b]
            # new text per node
            pos = 0
            edits = []  # (node, new_text)
            for n in c["nodes"]:
                lo, hi = pos, pos + len(n["text"])
                pos = hi
                if hi <= a or lo >= b:
                    continue
                # the node holding the span start keeps its head and takes the replacement; the node holding the span
                # end keeps its tail; nodes wholly inside the span are emptied (their run elements stay in place)
                new = (
                    n["text"][: max(a - lo, 0)]
                    + (replace if lo <= a else "")
                    + (n["text"][b - lo :] if hi > b else "")
                )
                edits.append((n, new))
            new_raw = raw
            for n, new in sorted(edits, key=lambda e: -e[0]["open_lo"]):
                open_tag = raw[n["open_lo"] : n["open_hi"]]
                if (
                    n["pfx"] != "a:"
                    and "xml:space" not in n["attrs"]
                    and (new != new.strip() or "  " in new)
                ):
                    open_tag = open_tag[:-1] + ' xml:space="preserve">'
                close_tag = raw[n["text_hi"] : n["close_hi"]]
                new_raw = (
                    new_raw[: n["open_lo"]]
                    + open_tag
                    + _escape(new)
                    + close_tag
                    + new_raw[n["close_hi"] :]
                )
            try:
                ET.fromstring(new_raw.encode("utf-8"))
            except ET.ParseError as exc:
                return (
                    "failed",
                    f"edit would leave {tp} malformed XML ({exc}); nothing written",
                )
            new_bytes = (b"\xef\xbb\xbf" if bom else b"") + new_raw.encode("utf-8")

            # Sanity: the container's text after the edit must contain the replacement and no longer match find.
            new_containers = _containers(new_raw, ext, ref)
            joined = " ".join(nc["text"] for nc in new_containers)
            if sq_find in _squash(joined)[0] and sq_find not in sq_replace:
                return (
                    "failed",
                    "find text still present after the edit; nothing written",
                )

            if dry_run:
                return (
                    "applied",
                    f"DRY RUN {tp} {c['label']}: {old_text!r} -> {replace!r}",
                )

            # the library check below refuses an unknown extension, so the temp file keeps the real one
            tmp = path[: -len(ext)] + ".tmp_ooxml" + ext
            other_hash_before = {
                i.filename: hashlib.sha256(zf.read(i.filename)).hexdigest()
                for i in infos
                if i.filename != tp
            }
            try:
                with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
                    zo.comment = zf.comment
                    for info in infos:
                        data = (
                            new_bytes if info.filename == tp else zf.read(info.filename)
                        )
                        zo.writestr(info, data, compress_type=info.compress_type)
            except OSError as exc:
                if os.path.exists(tmp):
                    os.remove(tmp)
                return "failed", f"write failed: {exc}"

        # verification runs on the temp file, the original is replaced only when every check passes
        try:
            with zipfile.ZipFile(tmp, "r") as zv:
                bad = zv.testzip()
                if bad is not None:
                    raise ValueError(f"zip test failed on {bad}")
                if [i.filename for i in zv.infolist()] != names:
                    raise ValueError("member list or order changed")
                for nm, h in other_hash_before.items():
                    if hashlib.sha256(zv.read(nm)).hexdigest() != h:
                        raise ValueError(f"member {nm} changed but was not the target")
                ET.fromstring(zv.read(tp))
            err = _load_check(tmp, ext)
            if err:
                raise ValueError(f"edited file does not re-open: {err}")
        except (ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
            os.remove(tmp)
            return "failed", f"verification failed, original left untouched: {exc}"
        os.replace(tmp, path)
    except (zipfile.BadZipFile, KeyError, ValueError, ET.ParseError) as exc:
        return "failed", f"could not read {path}: {exc}"

    return "applied", f"{tp} {c['label']}: {old_text!r} -> {replace!r}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("file")
    ap.add_argument("--find", required=True)
    ap.add_argument("--replace", required=True)
    ap.add_argument("--location")
    ap.add_argument("--part")
    ap.add_argument("--kind")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    outcome, detail = replace_text(
        a.file,
        a.find,
        a.replace,
        part=a.part,
        location=a.location,
        kind=a.kind,
        dry_run=a.dry_run,
    )
    print(f"{outcome.upper()}: {detail}")
    return 0 if outcome in ("applied", "noop") else 1


if __name__ == "__main__":
    raise SystemExit(main())
