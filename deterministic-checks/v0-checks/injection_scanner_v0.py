#!/usr/bin/env python3
"""STATUS: v0, UNVALIDATED. This pattern list is not derived from any real threat model for a specific judge model -- it's a generic starting set. False positives are likely (e.g. a task legitimately discussing prompt injection as its subject matter). Treat every hit as something to look at, not a confirmed attack.

injection_scanner_v0.py: a first-pass prompt-injection / judge-manipulation
scanner for a directory of Harbor-style task packages.

For every task under --root (a directory containing an instruction.md,
found recursively so --root can point at one task or at a directory of
many), this reads that task's instruction.md and every text-extractable
file under its environment/initial_workspace/, and scans the raw text for
four categories of suspicious pattern:

  1. suspicious_phrase - a curated set of short phrases associated with
     prompt-injection or "jailbreak" attempts: "ignore previous
     instructions" (this pattern also matches the very common "ignore all
     previous instructions" wording, since that specific phrasing is
     arguably the single best-known injection string and a literal-only
     match would miss it; every other phrase below is matched exactly as
     listed, with no broadening), "ignore all prior", "disregard the
     above", "you are now", "system prompt", and "act as". Matching is
     case-insensitive and tolerant of extra whitespace/newlines between
     the words, so a phrase split across a line wrap still hits.
  2. zero_width_unicode - the zero-width control characters commonly used
     to hide text from a human reviewer while an LLM still reads it:
     U+200B (ZERO WIDTH SPACE), U+200C (ZERO WIDTH NON-JOINER), U+200D
     (ZERO WIDTH JOINER), and U+FEFF (ZERO WIDTH NO-BREAK SPACE / BOM,
     flagged only when it appears somewhere other than byte offset 0,
     since a leading BOM is an ordinary encoding marker, not a hidden
     character).
  3. long_base64_like_string - a contiguous run of 40 or more characters
     drawn from the base64 alphabet (A-Z, a-z, 0-9, +, /), optionally
     followed by "=" padding. This is a blunt heuristic: it also fires on
     long hex hashes, git SHAs, minified-code identifiers, and URLs with
     long query strings, none of which are injection payloads. It exists
     to surface "something encoded is sitting in this file" for a human
     to decode and judge, not to claim the string IS an encoded payload.
  4. directive_html_comment - an HTML comment (<!-- ... -->) or the
     markdown reference-style pseudo-comment idiom ([//]: # (...) or
     [comment]: <> (...); markdown has no native comment syntax of its
     own, so both conventions are checked) whose body contains one of the
     same suspicious_phrase patterns above. Comments are invisible when a
     document is rendered but still present in the raw text an LLM reads,
     which is what makes this category worth a separate check rather than
     folding it into suspicious_phrase.

Every one of the four categories is a heuristic, not a detector. The
phrase list was written from general knowledge of publicly discussed
injection techniques, not calibrated against any labeled corpus of real
attacks against any specific judge or grading model. "act as" in
particular is common, unremarkable English in ordinary task prompts
("act as a project manager") and will produce frequent false positives by
design; it is included anyway because it is also a common jailbreak
opener, and a v0 screen is expected to over-flag rather than under-flag.

Known limitations, so a human reviewing the output knows what was and was
not covered:

  - File selection is extension-based only, not content-sniffed. A file
    is scanned only if its suffix is in TEXT_EXTENSIONS below. Binary
    deliverable and source formats (.xlsx, .xlsm, .docx, .pdf, .pptx,
    .zip, images, and anything else not on that list) are NOT extracted
    or scanned in this v0; they are listed under "skipped_files" in the
    report with a reason, precisely so this scanner does not silently
    claim a package is clean when it only ever looked at the text files
    in it. Extracting those formats needs their own libraries and is out
    of scope for a zero-dependency v0.
  - A file larger than MAX_FILE_SIZE_BYTES is skipped rather than scanned,
    to keep a stray large binary that happens to carry a text extension
    (or a large data file) from making a single run pathologically slow.
  - Matching is purely lexical. Nothing here understands intent, and
    nothing here confirms a match actually reaches or affects a judge
    model; it only says the string is present in a file this task ships.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
import unicodedata
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import re

STATUS_LINE = (
    "STATUS: v0, UNVALIDATED. This pattern list is not derived from any "
    "real threat model for a specific judge model -- it's a generic "
    "starting set. False positives are likely (e.g. a task legitimately "
    "discussing prompt injection as its subject matter). Treat every hit "
    "as something to look at, not a confirmed attack."
)

INSTRUCTION_FILENAME = "instruction.md"
WORKSPACE_RELATIVE_PARTS = ("environment", "initial_workspace")

MAX_FILE_SIZE_BYTES = 5_000_000  # 5 MB; see docstring "Known limitations"

TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".rst",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".sh",
    ".bash",
    ".ps1",
    ".sql",
    ".html",
    ".htm",
    ".xml",
    ".css",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".go",
    ".rb",
    ".php",
    ".r",
    ".log",
}

ZERO_WIDTH_CHARS: Dict[str, str] = {
    "​": "ZERO WIDTH SPACE (U+200B)",
    "‌": "ZERO WIDTH NON-JOINER (U+200C)",
    "‍": "ZERO WIDTH JOINER (U+200D)",
    "﻿": "ZERO WIDTH NO-BREAK SPACE / BOM (U+FEFF)",
}

# Named, curated phrase patterns. Each tuple is (pattern_name, compiled regex).
# See the module docstring category 1 for what each one covers and the one
# deliberate broadening (ignore_previous_instructions also catches the
# "ignore all previous instructions" wording).
PHRASE_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    (
        "ignore_previous_instructions",
        re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    ),
    ("ignore_all_prior", re.compile(r"ignore\s+all\s+prior", re.IGNORECASE)),
    ("disregard_the_above", re.compile(r"disregard\s+the\s+above", re.IGNORECASE)),
    ("you_are_now", re.compile(r"you\s+are\s+now", re.IGNORECASE)),
    ("system_prompt", re.compile(r"system\s+prompt", re.IGNORECASE)),
    ("act_as", re.compile(r"\bact\s+as\b", re.IGNORECASE)),
]

LONG_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")

HTML_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
MARKDOWN_PSEUDO_COMMENT_RE = re.compile(
    r"\[(?://|comment)\]:\s*(?:#|<>)\s*\(([^)]*)\)", re.IGNORECASE
)

MATCHED_TEXT_TRUNCATE_AT = 200


class LineIndex:
    """Maps an absolute character offset into a text to a (line, column).

    Both line and column are 1-based, matching how a human reading the
    file in an editor would refer to them.
    """

    def __init__(self, text: str) -> None:
        self._starts: List[int] = [0]
        for line in text.splitlines(keepends=True):
            self._starts.append(self._starts[-1] + len(line))

    def locate(self, offset: int) -> Tuple[int, int]:
        line_idx = bisect.bisect_right(self._starts, offset) - 1
        line_idx = max(0, min(line_idx, len(self._starts) - 2))
        line_no = line_idx + 1
        col_no = offset - self._starts[line_idx] + 1
        return line_no, col_no


def truncate(text: str, limit: int = MATCHED_TEXT_TRUNCATE_AT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(truncated, {len(text)} chars total)"


def line_text_at(text: str, offset: int) -> str:
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end].strip()


def find_task_dirs(root: Path) -> List[Path]:
    """Every directory under root that directly contains an instruction.md.

    Uses rglob so --root may point at a single task (instruction.md
    directly under root) or at a directory holding many task
    subdirectories, matching the convention used elsewhere in this folder
    (see duplicate_task_detector_v0.py).
    """
    return sorted({p.parent for p in root.rglob(INSTRUCTION_FILENAME) if p.is_file()})


def task_id_for(task_dir: Path, root: Path) -> str:
    try:
        relative = task_dir.relative_to(root)
        return relative.as_posix() if str(relative) != "." else task_dir.name
    except ValueError:
        return task_dir.name


def iter_candidate_files(task_dir: Path) -> Iterator[Path]:
    """instruction.md plus every file under environment/initial_workspace/."""
    instruction_path = task_dir / INSTRUCTION_FILENAME
    if instruction_path.is_file():
        yield instruction_path

    workspace_dir = task_dir.joinpath(*WORKSPACE_RELATIVE_PARTS)
    if workspace_dir.is_dir():
        for path in sorted(workspace_dir.rglob("*")):
            if path.is_file():
                yield path


def read_text_or_skip(path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Returns (text, skip_reason). Exactly one of the two is not None."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"could not stat file: {exc}"

    if size > MAX_FILE_SIZE_BYTES:
        return (
            None,
            f"file too large for v0 text scan ({size} bytes > {MAX_FILE_SIZE_BYTES})",
        )

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"could not read file: {exc}"

    return text, None


def scan_phrases(text: str, index: LineIndex) -> List[dict]:
    findings = []
    for name, pattern in PHRASE_PATTERNS:
        for match in pattern.finditer(text):
            line_no, col_no = index.locate(match.start())
            findings.append(
                {
                    "category": "suspicious_phrase",
                    "pattern": name,
                    "line": line_no,
                    "column": col_no,
                    "matched_text": match.group(0),
                    "context": truncate(line_text_at(text, match.start())),
                }
            )
    return findings


def scan_zero_width(text: str, index: LineIndex) -> List[dict]:
    findings = []
    for offset, ch in enumerate(text):
        if ch not in ZERO_WIDTH_CHARS:
            continue
        if ch == "﻿" and offset == 0:
            continue  # ordinary BOM at file start, not a hidden character
        line_no, col_no = index.locate(offset)
        findings.append(
            {
                "category": "zero_width_unicode",
                "pattern": ZERO_WIDTH_CHARS[ch],
                "line": line_no,
                "column": col_no,
                "matched_text": f"U+{ord(ch):04X} ({unicodedata.name(ch, 'UNKNOWN')})",
                "context": truncate(line_text_at(text, offset)),
            }
        )
    return findings


def scan_long_base64(text: str, index: LineIndex) -> List[dict]:
    findings = []
    for match in LONG_BASE64_RE.finditer(text):
        line_no, col_no = index.locate(match.start())
        matched = match.group(0)
        findings.append(
            {
                "category": "long_base64_like_string",
                "pattern": "base64_alphabet_40plus",
                "line": line_no,
                "column": col_no,
                "matched_text": truncate(matched),
                "matched_length": len(matched),
                "context": truncate(line_text_at(text, match.start())),
            }
        )
    return findings


def scan_directive_comments(text: str, index: LineIndex) -> List[dict]:
    findings = []

    def check_comment(comment_start: int, body: str) -> None:
        for name, pattern in PHRASE_PATTERNS:
            phrase_match = pattern.search(body)
            if not phrase_match:
                continue
            line_no, col_no = index.locate(comment_start)
            findings.append(
                {
                    "category": "directive_html_comment",
                    "pattern": name,
                    "line": line_no,
                    "column": col_no,
                    "matched_text": phrase_match.group(0),
                    "context": truncate(body.strip()),
                }
            )

    for match in HTML_COMMENT_RE.finditer(text):
        check_comment(match.start(), match.group(1))
    for match in MARKDOWN_PSEUDO_COMMENT_RE.finditer(text):
        check_comment(match.start(), match.group(1))

    return findings


def scan_text(text: str) -> List[dict]:
    index = LineIndex(text)
    findings: List[dict] = []
    findings.extend(scan_phrases(text, index))
    findings.extend(scan_zero_width(text, index))
    findings.extend(scan_long_base64(text, index))
    findings.extend(scan_directive_comments(text, index))
    findings.sort(key=lambda f: (f["line"], f["column"]))
    return findings


def scan_task(task_dir: Path, root: Path) -> Tuple[List[dict], List[dict]]:
    """Returns (hits, skipped) for one task directory."""
    task_id = task_id_for(task_dir, root)
    hits: List[dict] = []
    skipped: List[dict] = []

    for path in iter_candidate_files(task_dir):
        rel_path = (
            str(path.relative_to(root)) if _is_relative(path, root) else str(path)
        )

        if path.suffix.lower() not in TEXT_EXTENSIONS:
            skipped.append(
                {
                    "task": task_id,
                    "file": rel_path,
                    "reason": (
                        f"extension '{path.suffix or '(none)'}' is not in "
                        "TEXT_EXTENSIONS; not extracted in this v0"
                    ),
                }
            )
            continue

        text, skip_reason = read_text_or_skip(path)
        if skip_reason is not None:
            skipped.append({"task": task_id, "file": rel_path, "reason": skip_reason})
            continue

        for finding in scan_text(text):
            finding["task"] = task_id
            finding["file"] = rel_path
            hits.append(finding)

    return hits, skipped


def _is_relative(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def build_report(
    root: Path, task_dirs: List[Path], hits: List[dict], skipped: List[dict]
) -> dict:
    hits_by_category: Dict[str, int] = {}
    for hit in hits:
        hits_by_category[hit["category"]] = hits_by_category.get(hit["category"], 0) + 1

    return {
        "status": STATUS_LINE,
        "root": str(root),
        "pattern_categories": [
            "suspicious_phrase",
            "zero_width_unicode",
            "long_base64_like_string",
            "directive_html_comment",
        ],
        "tasks_scanned": len(task_dirs),
        "task_ids": [task_id_for(d, root) for d in task_dirs],
        "files_skipped": len(skipped),
        "skipped_files": skipped,
        "total_hits": len(hits),
        "hits_by_category": hits_by_category,
        "hits": hits,
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="injection_scanner_v0.py",
        description=(
            "v0, UNVALIDATED first-pass prompt-injection / judge-manipulation "
            "scanner. Reads each task's instruction.md and every "
            "text-extractable file under its environment/initial_workspace/ "
            "under --root, and flags suspicious phrases, zero-width Unicode "
            "characters, long base64-looking strings, and HTML/markdown "
            "comments carrying directive-sounding language. This pattern "
            "list is a generic starting set, not derived from any real "
            "threat model for a specific judge model. Every hit is a "
            "candidate for human review, never a confirmed attack."
        ),
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help=(
            "Directory to search recursively for task instruction.md files. "
            "May point at a single task (instruction.md directly under "
            "--root) or at a directory containing many task subdirectories."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Path to write the JSON report to. If omitted, the report is "
            "printed to stdout."
        ),
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

    task_dirs = find_task_dirs(args.root)
    print(
        f"Found {len(task_dirs)} task(s) with an instruction.md under {args.root}",
        file=sys.stderr,
    )
    if not task_dirs:
        print(
            "warning: no instruction.md found under --root; nothing to scan.",
            file=sys.stderr,
        )

    all_hits: List[dict] = []
    all_skipped: List[dict] = []
    for task_dir in task_dirs:
        hits, skipped = scan_task(task_dir, args.root)
        all_hits.extend(hits)
        all_skipped.extend(skipped)

    report = build_report(args.root, task_dirs, all_hits, all_skipped)
    output_text = json.dumps(report, indent=2)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output_text, encoding="utf-8")
        print(f"Wrote report to {args.out}", file=sys.stderr)
    else:
        print(output_text)

    print(
        f"{len(all_hits)} hit(s) across {len(task_dirs)} task(s), "
        f"{len(all_skipped)} file(s) skipped (see skipped_files for why).",
        file=sys.stderr,
    )
    print(
        "Reminder: every hit is a candidate for human review, not a "
        "confirmed attack. See the module docstring.",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
