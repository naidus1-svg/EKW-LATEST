"""
Shared helpers for the GATE-V2 section-4-step-1 corpus-wide scan scripts.

Not a standalone script. Imported by env_size_report.py, golden_citation_scan.py,
instruction_input_scan.py, cross_group_duplicate_scan.py, rewardkit_pin.py,
metadata_fill.py and (12:30 UTC addition) formula_cache_scan.py,
quantifier_scope_scan.py and rubric_consistency_scan.py.

All functions here are READ-ONLY: nothing in this module writes to the corpus.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_CORPUS_ROOT = Path(
    "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
)
DEFAULT_REPORTS_DIR = Path("/root/qc/tools/reports")

FILENAME_EXTENSIONS = ("xlsx", "docx", "csv", "pdf", "doc", "pptx")

_STOPWORDS = {
    "the", "a", "an", "per", "of", "and", "or", "for", "to", "from", "in",
    "on", "at", "with", "is", "are", "this", "that", "these", "those",
    "as", "by", "its", "it's", "was", "were", "be", "been",
}

# Suffix nouns that mark a descriptive (non-extension) document reference,
# e.g. "the payroll/ADP register", "Jessica's memo", "the annual letter".
_DOC_SUFFIXES = (
    "register", "ledger", "statement", "statements", "schedule", "build",
    "export", "detail", "details", "memo", "letter", "update", "updates",
    "principles", "mechanism", "workbook", "worksheet", "report", "policy",
    "plan", "model", "reconciliation", "aging", "journal", "invoice",
    "contract", "agreement", "narrative", "summary", "workpaper",
)

# Common rate/unit nouns that make "per <word>" NOT a provenance phrase
# (e.g. "$40 per week", "5 minutes per agent") -- filtered out of
# extract_provenance_phrases so they don't drown out real citations.
_RATE_UNIT_WORDS = {
    "week", "day", "month", "year", "hour", "minute", "second", "agent",
    "unit", "order", "contact", "item", "employee", "sku", "transaction",
    "ticket", "call", "shift", "rep", "person", "customer", "hire",
    "quarter", "session", "case", "seat", "user", "record", "line",
}


def list_tasks(corpus_root: Path) -> list[Path]:
    """Return sorted task directories directly under corpus_root."""
    return sorted(p for p in corpus_root.iterdir() if p.is_dir() and p.name.startswith("SVC-PC-"))


def iter_deliverable_groups(task_dir: Path) -> list[Path]:
    """Return tests/deliverables* directories (both 'deliverables' and 'deliverables_NN')."""
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return []
    return sorted(p for p in tests_dir.iterdir() if p.is_dir() and p.name.startswith("deliverables"))


def read_text_safe(path: Path, max_bytes: int = 5_000_000) -> str:
    """Best-effort plain-text read, never raises."""
    try:
        if path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


_MARKITDOWN = None


def _get_markitdown():
    global _MARKITDOWN
    if _MARKITDOWN is None:
        from markitdown import MarkItDown

        _MARKITDOWN = MarkItDown()
    return _MARKITDOWN


def extract_document_text(path: Path) -> str:
    """
    Best-effort text extraction for a solution/environment file.
    Returns "" on any failure (never raises) so scans keep going corpus-wide.
    """
    ext = path.suffix.lower().lstrip(".")
    try:
        if ext == "xlsx":
            import openpyxl

            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
            chunks = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    for val in row:
                        if isinstance(val, str) and val.strip():
                            chunks.append(val)
            wb.close()
            return "\n".join(chunks)
        elif ext == "docx":
            import docx

            d = docx.Document(str(path))
            parts = [p.text for p in d.paragraphs]
            for table in d.tables:
                for row in table.rows:
                    for cell in row.cells:
                        parts.append(cell.text)
            return "\n".join(parts)
        else:
            # doc, pdf, pptx, csv, md, json, orig, etc.
            result = _get_markitdown().convert(str(path))
            return result.text_content or ""
    except Exception:
        # Fall back to a plain-text sniff before giving up entirely.
        return read_text_safe(path)


def normalize_keywords(phrase: str) -> set[str]:
    """Lowercase word set, possessive/punctuation stripped, stopwords removed."""
    phrase = phrase.replace("’", "'")
    words = re.findall(r"[A-Za-z0-9]+", phrase.lower())
    words = [w[:-1] if w.endswith("s") and w not in {"as", "gs"} and len(w) > 3 and False else w for w in words]
    # (possessive 's already dropped by \w+ regex not matching the apostrophe)
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def extract_filename_tokens(text: str) -> set[str]:
    """
    Extract filename-shaped tokens ending in a known office/doc extension.

    Two patterns, deliberately not merged into one greedy regex:
      - strict no-space tokens (`orders_export_1.csv`, `Payroll_Register_
        2021-01.xlsx`): covers the vast majority of real filenames in this
        corpus, which are underscore/hyphen separated with no spaces. Using
        a word boundary in front means a citation embedded in a sentence
        ("...sourced from orders_export_1.csv") yields the clean filename,
        not the whole leading clause.
      - backtick/quote-wrapped filenames: the few real filenames that do
        contain spaces (e.g. docx titles) are only reliably delimited when
        quoted or backticked in source text; unquoted multi-word filenames
        in running prose are not extracted (precision over recall here --
        the loose version produced sentence-fragment "citations").
    """
    found: set[str] = set()
    ext_alt = "|".join(FILENAME_EXTENSIONS)
    for m in re.finditer(r"\b([A-Za-z0-9][A-Za-z0-9_.\-]{1,120}\.(?:%s))\b" % ext_alt, text, re.IGNORECASE):
        candidate = m.group(1)
        stem = candidate.rsplit(".", 1)[0]
        # Drop pure-digit/date-fragment noise ("12.pdf", "03.pdf"): a real
        # filename stem has at least one letter.
        if re.search(r"[A-Za-z]", stem) and len(stem) >= 2:
            found.add(candidate)
    for m in re.finditer(r"[`\"']([^`\"'\n]{3,140}\.(?:%s))[`\"']" % ext_alt, text, re.IGNORECASE):
        found.add(m.group(1).strip())
    return found


def extract_provenance_phrases(text: str) -> set[str]:
    """
    Extract 'per <file/source>' provenance phrases (golden citation scan).
    Filters out rate/unit noise ("$40 per week") that shares the "per X"
    shape but isn't a source citation: keeps a phrase only if it ends in a
    known document-noun suffix, carries a file extension, or is a
    multi-word phrase led by a capitalized (proper-noun-shaped) word.
    """
    found: set[str] = set()
    ext_alt = "|".join(FILENAME_EXTENSIONS)
    for m in re.finditer(
        r"\bper\s+(?:the\s+)?([A-Za-z0-9][A-Za-z0-9/&'\-., ]{2,80}?)(?=[.,;:\n]|$)",
        text,
    ):
        phrase = m.group(1).strip()
        if not phrase or len(phrase.split()) > 12:
            continue
        words = phrase.split()
        first_norm = re.sub(r"[^a-z]", "", words[0].lower())
        if len(words) == 1 and first_norm in _RATE_UNIT_WORDS:
            continue
        last_norm = re.sub(r"[^a-z]", "", words[-1].lower())
        ends_doc_suffix = last_norm in _DOC_SUFFIXES or last_norm.rstrip("s") in _DOC_SUFFIXES
        has_extension = bool(re.search(r"\.(?:%s)$" % ext_alt, phrase, re.IGNORECASE))
        proper_noun_lead = len(words) >= 2 and words[0][:1].isupper()
        if ends_doc_suffix or has_extension or proper_noun_lead:
            found.add(phrase)
    return found


def extract_named_documents(text: str) -> set[str]:
    """
    Extract descriptive references to named source documents that don't carry
    a file extension, e.g. 'the payroll/ADP register', 'Jessica's memo',
    'the annual letter'. Heuristic, deliberately narrow to hold down false
    positives: a 1-4 word qualifier run ending in a known document-noun
    suffix, anchored to a literal leading "the " (drops verb-led clause
    captures like "Book payroll from the ADP schedule") or to a possessive
    name ("Jessica's memo"). A bare suffix with no qualifier ("the plan")
    is not captured -- too generic to be a citation.
    """
    found: set[str] = set()
    suffix_alt = "|".join(_DOC_SUFFIXES)
    qualifier = r"[A-Za-z0-9][A-Za-z0-9/&\-]*(?:\s+[A-Za-z0-9/&\-]+){0,3}"
    patterns = [
        # "the <qualifier> <suffix>", anchored on a literal leading "the".
        re.compile(r"\bthe\s+(%s\s+(?:%s))\b" % (qualifier, suffix_alt), re.IGNORECASE),
        # "<Name>'s <suffix>" (possessive proper-noun lead).
        re.compile(r"\b([A-Z][a-zA-Z]*'s\s+(?:%s))\b" % suffix_alt),
    ]
    for pattern in patterns:
        for m in pattern.finditer(text):
            phrase = re.sub(r"\s+", " ", m.group(1)).strip()
            if phrase:
                found.add(phrase)
    return found


def build_file_index(root: Path) -> list[Path]:
    """All files under root (recursive), skipping nothing but capped for safety."""
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def find_exact_filename(name: str, index: Iterable[Path]) -> Path | None:
    target = name.strip().lower()
    for p in index:
        if p.name.lower() == target:
            return p
    return None


def find_fuzzy_filename(phrase: str, index: list[Path], min_overlap: float = 0.6) -> Path | None:
    """
    Keyword-overlap fuzzy match for descriptive (non-extension) provenance
    phrases against real file basenames. Returns the best match above
    min_overlap, or None.
    """
    kws = normalize_keywords(phrase)
    if not kws:
        return None
    best: tuple[float, Path] | None = None
    for p in index:
        stem_kws = normalize_keywords(p.stem.replace("_", " ").replace("-", " "))
        if not stem_kws:
            continue
        overlap = len(kws & stem_kws) / len(kws)
        if overlap >= min_overlap and (best is None or overlap > best[0]):
            best = (overlap, p)
    return best[1] if best else None


_QUANTIFIER_RE = re.compile(
    r"\b(each|every|all|per|complete|full)\b|\bcurrent line\b", re.IGNORECASE
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def extract_quantifier_phrases(text: str) -> list[tuple[str, str]]:
    """
    Find quantifier-scope phrases (GATE-V2 class L / map (c): each, every,
    all, per, complete, full, "current line") and the sentence each occurs
    in. Splits on sentence-ending punctuation and blank lines (a heading or
    bullet fragment with no terminal punctuation is still its own
    "sentence" via the newline split). Returns (matched_phrase_lowercased,
    sentence) pairs, one per match -- a sentence with two quantifiers
    yields two rows; callers dedupe by (phrase, sentence) per task. "per"
    fires on rate phrases too ("$40 per week") -- left as a candidate for
    the CR per the task instructions, not filtered here.
    """
    out: list[tuple[str, str]] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for m in _QUANTIFIER_RE.finditer(sentence):
            out.append((m.group(0).lower(), sentence))
    return out


@dataclass
class TableInfo:
    source_label: str  # "<file>!<sheet>", "<file>" (csv) or "<file>#table<N>" (docx)
    header: tuple[str, ...]
    row_count: int


_TABLE_EXTENSIONS = {"xlsx", "csv", "docx"}


def iter_tables(path: Path, max_rows: int = 20_000) -> list[TableInfo]:
    """
    Heuristic single-table-per-sheet/file extraction for row-count
    comparison (quantifier_scope_scan.py). Deliberately simple:
      - xlsx: per worksheet, header = first row with >=1 non-empty cell;
        row_count = count of subsequent rows with >=1 non-empty cell. Does
        NOT detect multiple stacked tables in one sheet or a multi-row
        header -- both would misattribute the header row. Cells are read
        data_only=True (cached values); a formula column with no cached
        value reads empty and can undercount -- cross-check against
        formula_cache_scan.py findings for the same file.
      - csv: header = first row; row_count = remaining non-empty rows.
      - docx: one TableInfo per <w:tbl>; header = first row's cell text;
        row_count = len(rows) - 1. A table with <2 rows is skipped (no
        data rows to count).
      - anything else (pdf, pptx, doc, json, xlsm, ...): returns [] --
        not a structured-table source for this heuristic.
    Never raises; returns whatever was collected so far on any read error.
    """
    ext = path.suffix.lower().lstrip(".")
    if ext not in _TABLE_EXTENSIONS:
        return []
    tables: list[TableInfo] = []
    try:
        if ext == "xlsx":
            import openpyxl

            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
            for ws in wb.worksheets:
                header: tuple[str, ...] | None = None
                row_count = 0
                for row in ws.iter_rows(values_only=True):
                    cells = [str(v).strip() for v in row if v is not None and str(v).strip()]
                    if not cells:
                        continue
                    if header is None:
                        header = tuple(cells)
                        continue
                    row_count += 1
                    if row_count >= max_rows:
                        break
                if header is not None and row_count > 0:
                    tables.append(TableInfo(f"{path.name}!{ws.title}", header, row_count))
            wb.close()
        elif ext == "csv":
            with path.open(newline="", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                header = None
                row_count = 0
                for row in reader:
                    cells = [c.strip() for c in row if c and c.strip()]
                    if not cells:
                        continue
                    if header is None:
                        header = tuple(cells)
                        continue
                    row_count += 1
                    if row_count >= max_rows:
                        break
                if header is not None and row_count > 0:
                    tables.append(TableInfo(path.name, header, row_count))
        elif ext == "docx":
            import docx

            d = docx.Document(str(path))
            for i, table in enumerate(d.tables):
                rows = table.rows
                if len(rows) < 2:
                    continue
                header = tuple(c.text.strip() for c in rows[0].cells if c.text.strip())
                row_count = len(rows) - 1
                if header:
                    tables.append(TableInfo(f"{path.name}#table{i}", header, row_count))
    except Exception:
        return tables
    return tables


def best_header_match(
    header: tuple[str, ...], candidates: list[TableInfo], min_overlap: float = 0.4
) -> TableInfo | None:
    """
    Best keyword-overlap match for a golden table's header against a list of
    candidate (source) TableInfo. Jaccard-over-the-smaller-header-set, same
    shape as find_fuzzy_filename; min_overlap=0.4 is looser than the 0.6
    filename default because table headers vary more in wording than
    filenames ("SKU" vs "Product Code").
    """
    kws = normalize_keywords(" ".join(header))
    if not kws:
        return None
    best: tuple[float, TableInfo] | None = None
    for cand in candidates:
        cand_kws = normalize_keywords(" ".join(cand.header))
        if not cand_kws:
            continue
        overlap = len(kws & cand_kws) / min(len(kws), len(cand_kws))
        if overlap >= min_overlap and (best is None or overlap > best[0]):
            best = (overlap, cand)
    return best[1] if best else None


def write_csv(path: Path, header: list[str], rows: Iterable[Iterable]) -> int:
    """Write rows to CSV, creating parent dirs. Returns row count written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow(row)
            n += 1
    return n
