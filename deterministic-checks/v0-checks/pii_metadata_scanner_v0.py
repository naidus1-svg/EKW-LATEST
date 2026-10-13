#!/usr/bin/env python3
"""STATUS: v0, UNVALIDATED. No policy decision has been made about what counts as sensitive for this project. This script flags shape-based pattern matches only -- it is a starting point for a human/policy review, never a compliance guarantee.

pii_metadata_scanner_v0.py: a first-pass PII / sensitive-data scanner for a
directory of Harbor-style task packages.

For every task under --root, this looks at two zones per task:
`environment/initial_workspace/` and `solution/`. For every file found in
either zone it does two independent things:

1. Office document metadata. For any `.docx` or `.xlsx` file (both are
   just zip archives of XML), it opens `docProps/core.xml` and
   `docProps/app.xml` if present and looks for a populated `creator` or
   `lastModifiedBy` element, by local tag name regardless of XML
   namespace prefix. It reports whatever value is present. It does not
   decide whether that value is sensitive -- a real person's name, a
   generic service account, a placeholder like "Author", or empty are
   all just reported as-is. That judgment is a policy call for a human.

2. Shape-based text pattern matching. It extracts whatever text it can
   from the file (docx paragraph runs via zipfile + a minimal `<w:t>`
   regex extraction, xlsx cell string values via openpyxl, csv/txt files
   read directly) and runs three regexes over it: an SSN-like pattern
   (\\d{3}-\\d{2}-\\d{4}), an email-address pattern, and a phone-number-like
   pattern. These are shape-based pattern matches, not a verified PII
   classifier: a fake/placeholder SSN in test data will also match, and
   real PII in an unusual format (no dashes, international phone format,
   an obfuscated email) will be missed entirely. Every match is reported
   for a human to look at, none is a confirmed finding of real PII.

Every file outside `.docx`, `.xlsx`, `.csv`, `.txt` inside a scanned zone
is recorded as skipped-for-content (its office-metadata check, if
applicable, is not skipped by this -- only docx/xlsx get that check, and
only docx/xlsx/csv/txt get the pattern-matching check). Files outside
both zones are not visited at all: this tool does not scan tests/,
instruction.md, or anything else at the task root.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple
from xml.etree import ElementTree as ET

try:
    import openpyxl

    HAVE_OPENPYXL = True
except ImportError:
    openpyxl = None  # type: ignore[assignment]
    HAVE_OPENPYXL = False

STATUS_LINE = (
    "STATUS: v0, UNVALIDATED. No policy decision has been made about what "
    "counts as sensitive for this project. This script flags shape-based "
    "pattern matches only -- it is a starting point for a human/policy "
    "review, never a compliance guarantee."
)

PATTERN_CAVEAT = (
    "These are shape-based pattern matches, not a verified PII classifier. "
    "A fake/placeholder SSN in test data will also match, and real PII in "
    "an unusual format will be missed."
)

# Zones scanned per task, relative to the task directory. A file's path is
# checked for these as consecutive path components; anything else under the
# task directory (tests/, instruction.md, ...) is not visited.
ENV_ZONE_PARTS = ("environment", "initial_workspace")
SOLUTION_ZONE_NAME = "solution"

OFFICE_METADATA_FILES = ("docProps/core.xml", "docProps/app.xml")
OFFICE_METADATA_FIELDS = ("creator", "lastModifiedBy")

CONTENT_SCAN_EXTENSIONS = {".docx", ".xlsx", ".csv", ".txt"}

# Regexes are intentionally simple and documented as shape-based, not a PII
# classifier. No capturing groups, so re.findall() returns whole matches.
PATTERNS: Dict[str, "re.Pattern[str]"] = {
    "ssn_like": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone_like": re.compile(
        r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
    ),
}

# Cap how many distinct matches per pattern are kept in the report, so a file
# that is mostly numbers doesn't blow up the JSON output. This caps the
# report, not the detection: pattern_matches still reflects that matches
# exist even when the list is truncated.
MAX_MATCHES_PER_PATTERN = 50

_WT_TAG_RE = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.DOTALL)


class FileRecord(NamedTuple):
    task_id: str
    zone: str
    relative_path: str
    extension: str
    metadata: Optional[dict]
    pattern_matches: Dict[str, List[str]]
    content_scanned: bool
    skip_reason: Optional[str]
    errors: List[str]


def find_zone(
    rel_parts: Tuple[str, ...],
) -> Tuple[Optional[str], Optional[Tuple[str, ...]]]:
    """Return (zone_name, task_dir_parts) for a file's path parts, or (None, None).

    zone_name is "environment/initial_workspace" or "solution". task_dir_parts
    is the path parts of the task directory that zone sits under (i.e. the
    parts before the zone's own anchor components).
    """
    n = len(rel_parts)
    for i in range(n - 1):
        if rel_parts[i] == ENV_ZONE_PARTS[0] and rel_parts[i + 1] == ENV_ZONE_PARTS[1]:
            return "environment/initial_workspace", rel_parts[:i]
    for i in range(n):
        if rel_parts[i] == SOLUTION_ZONE_NAME:
            return "solution", rel_parts[:i]
    return None, None


def local_tag(tag: str) -> str:
    """Strip an XML namespace URI from an ElementTree tag, e.g. '{ns}creator' -> 'creator'."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def extract_office_metadata(zf: zipfile.ZipFile) -> dict:
    """Look at docProps/core.xml and docProps/app.xml for creator/lastModifiedBy.

    Reports whatever is found, empty or not. Does not judge sensitivity --
    that is a policy call for a human, per the module docstring.
    """
    namelist = set(zf.namelist())
    sources_found: List[str] = []
    fields: Dict[str, str] = {}
    parse_errors: List[str] = []

    for candidate in OFFICE_METADATA_FILES:
        if candidate not in namelist:
            continue
        sources_found.append(candidate)
        try:
            root = ET.fromstring(zf.read(candidate))
        except ET.ParseError as exc:
            parse_errors.append(f"{candidate}: {exc}")
            continue
        for el in root.iter():
            name = local_tag(el.tag)
            if name in OFFICE_METADATA_FIELDS and el.text and el.text.strip():
                # First non-empty value wins if the same field somehow
                # appears in both files; both files are still listed in
                # sources_found regardless.
                fields.setdefault(name, el.text.strip())

    return {
        "sources_found": sources_found,
        "fields": fields,
        "parse_errors": parse_errors,
    }


def extract_docx_text(zf: zipfile.ZipFile) -> str:
    """Minimal text extraction from word/document.xml: pull <w:t> run contents.

    This is deliberately not a full DOCX parser. It grabs the text inside
    every <w:t> element via regex and unescapes XML entities. It will miss
    text in headers/footers/footnotes and in structures the regex doesn't
    anticipate; it is a best-effort text source for pattern scanning, not a
    faithful document render.
    """
    if "word/document.xml" not in zf.namelist():
        return ""
    raw = zf.read("word/document.xml").decode("utf-8", errors="replace")
    runs = _WT_TAG_RE.findall(raw)
    return "\n".join(html.unescape(r) for r in runs)


def extract_xlsx_text(path: Path) -> Tuple[str, List[str]]:
    """Read all string cell values out of an xlsx via openpyxl.

    Returns (joined_text, errors). If openpyxl is unavailable or the file
    fails to load, returns ("", [<error>]) rather than raising.
    """
    if not HAVE_OPENPYXL:
        return "", ["openpyxl not installed; xlsx content scan skipped"]
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001 - report, don't crash the scan
        return "", [f"openpyxl could not open workbook: {type(exc).__name__}: {exc}"]

    chunks: List[str] = []
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    value = cell.value
                    if isinstance(value, str) and value:
                        chunks.append(value)
    finally:
        try:
            wb.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup only
            pass
    return "\n".join(chunks), []


def extract_plain_text(path: Path) -> Tuple[str, List[str]]:
    """Read a csv/txt file as text, falling back to latin-1 on decode failure."""
    try:
        return path.read_text(encoding="utf-8", errors="replace"), []
    except OSError as exc:
        return "", [f"could not read file: {type(exc).__name__}: {exc}"]


def scan_text_for_patterns(text: str) -> Dict[str, List[str]]:
    """Run every PATTERNS regex over text, capped at MAX_MATCHES_PER_PATTERN each."""
    matches: Dict[str, List[str]] = {}
    for name, pattern in PATTERNS.items():
        found = sorted(set(pattern.findall(text)))
        if found:
            matches[name] = found[:MAX_MATCHES_PER_PATTERN]
    return matches


def process_file(path: Path, task_id: str, zone: str, rel_path: str) -> FileRecord:
    ext = path.suffix.lower()
    errors: List[str] = []
    metadata: Optional[dict] = None
    pattern_matches: Dict[str, List[str]] = {}
    content_scanned = False
    skip_reason: Optional[str] = None

    if ext not in CONTENT_SCAN_EXTENSIONS:
        skip_reason = (
            f"extension {ext!r} is not one of {sorted(CONTENT_SCAN_EXTENSIONS)}"
        )
        return FileRecord(
            task_id,
            zone,
            rel_path,
            ext,
            metadata,
            pattern_matches,
            content_scanned,
            skip_reason,
            errors,
        )

    if ext in (".docx", ".xlsx"):
        try:
            with zipfile.ZipFile(path) as zf:
                metadata = extract_office_metadata(zf)
                text = extract_docx_text(zf) if ext == ".docx" else ""
        except zipfile.BadZipFile as exc:
            errors.append(f"not a valid zip/office file: {exc}")
            text = ""
        except OSError as exc:
            errors.append(f"could not open file: {type(exc).__name__}: {exc}")
            text = ""

        if ext == ".xlsx" and not errors:
            text, xlsx_errors = extract_xlsx_text(path)
            errors.extend(xlsx_errors)

        pattern_matches = scan_text_for_patterns(text)
        content_scanned = True
    else:
        text, read_errors = extract_plain_text(path)
        errors.extend(read_errors)
        pattern_matches = scan_text_for_patterns(text)
        content_scanned = True

    return FileRecord(
        task_id,
        zone,
        rel_path,
        ext,
        metadata,
        pattern_matches,
        content_scanned,
        skip_reason,
        errors,
    )


def scan_root(root: Path) -> Tuple[List[FileRecord], List[str], int]:
    """Walk root, find files inside the two scanned zones per task, process each.

    Returns (records, sorted task_ids seen, files_outside_scanned_zones count).
    """
    records: List[FileRecord] = []
    task_ids: set = set()
    files_outside_zones = 0

    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            try:
                rel = fpath.relative_to(root)
            except ValueError:
                continue
            zone, task_parts = find_zone(rel.parts)
            if zone is None or task_parts is None:
                files_outside_zones += 1
                continue
            task_id = "/".join(task_parts) if task_parts else "."
            task_ids.add(task_id)
            records.append(process_file(fpath, task_id, zone, rel.as_posix()))

    return records, sorted(task_ids), files_outside_zones


def build_report(root: Path) -> dict:
    records, task_ids, files_outside_zones = scan_root(root)

    files_with_metadata_fields = sum(
        1 for r in records if r.metadata and r.metadata.get("fields")
    )
    files_with_pattern_matches = sum(1 for r in records if r.pattern_matches)
    files_with_errors = sum(1 for r in records if r.errors)

    return {
        "status": STATUS_LINE,
        "tool": "pii_metadata_scanner_v0",
        "root": str(root),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scanned_zones": ["environment/initial_workspace", "solution"],
        "content_scan_extensions": sorted(CONTENT_SCAN_EXTENSIONS),
        "office_metadata_fields_checked": list(OFFICE_METADATA_FIELDS),
        "office_metadata_sources_checked": list(OFFICE_METADATA_FILES),
        "pattern_definitions": {
            name: pattern.pattern for name, pattern in PATTERNS.items()
        },
        "pattern_caveat": PATTERN_CAVEAT,
        "openpyxl_available": HAVE_OPENPYXL,
        "summary": {
            "tasks_found": len(task_ids),
            "files_scanned": len(records),
            "files_outside_scanned_zones": files_outside_zones,
            "files_with_populated_creator_or_lastmodifiedby": files_with_metadata_fields,
            "files_with_pattern_matches": files_with_pattern_matches,
            "files_with_processing_errors": files_with_errors,
        },
        "task_ids": task_ids,
        "findings": [
            {
                "task_id": r.task_id,
                "zone": r.zone,
                "relative_path": r.relative_path,
                "extension": r.extension,
                "content_scanned": r.content_scanned,
                "skip_reason": r.skip_reason,
                "metadata": r.metadata,
                "pattern_matches": r.pattern_matches,
                "errors": r.errors,
            }
            for r in records
        ],
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pii_metadata_scanner_v0.py",
        description=(
            "v0, UNVALIDATED first-pass PII/sensitive-data scanner for Harbor "
            "task packages. For every task under --root, scans "
            "environment/initial_workspace/ and solution/ for (1) populated "
            "creator/lastModifiedBy metadata in docx/xlsx office documents "
            "and (2) shape-based regex matches (SSN-like, email, "
            "phone-like) in docx/xlsx/csv/txt content. Reports matches for "
            "human review; makes no sensitivity judgment itself."
        ),
        epilog=STATUS_LINE,
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help=(
            "Directory containing task packages (one subdirectory per task, "
            "each with its own environment/initial_workspace/ and/or "
            "solution/ subdirectory). Required, no default."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Path to write the JSON report to. If omitted, prints to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if not args.root.exists():
        print(f"error: --root does not exist: {args.root}", file=sys.stderr)
        return 2
    if not args.root.is_dir():
        print(f"error: --root is not a directory: {args.root}", file=sys.stderr)
        return 2

    print(f"[{STATUS_LINE}]", file=sys.stderr)
    if not HAVE_OPENPYXL:
        print(
            "warning: openpyxl is not installed; xlsx content pattern-scanning "
            "will be skipped (xlsx office-metadata checks still run).",
            file=sys.stderr,
        )

    root = args.root.resolve()
    report = build_report(root)

    print(
        f"Scanned {report['summary']['files_scanned']} file(s) across "
        f"{report['summary']['tasks_found']} task(s) under {root}.",
        file=sys.stderr,
    )

    output_text = json.dumps(report, indent=2)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output_text, encoding="utf-8")
        print(f"Wrote report to {args.out}", file=sys.stderr)
    else:
        print(output_text)

    print(
        f"{report['summary']['files_with_populated_creator_or_lastmodifiedby']} "
        "file(s) with a populated creator/lastModifiedBy field, "
        f"{report['summary']['files_with_pattern_matches']} file(s) with at "
        "least one pattern match. Every one of those needs a human to look "
        "at it -- see the module docstring and the report's own 'status' "
        "field.",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
