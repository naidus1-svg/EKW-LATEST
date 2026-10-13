#!/usr/bin/env python3
"""Golden groundedness check: are the golden answer's LITERAL factual claims
actually grounded in / derivable from the task's real source documents, or are
they wrong or fabricated relative to the environment data the solver was given?

Why this exists
---------------
A prior round's coverage-gap analysis identified a genuine, currently-open
defect class that NO check in this repo closes. The project's own coverage
reports (read the primary source, do not take this on faith) quote two real
defects directly:

  coverage-cov5-SVC-PC-37-3-0.md, RC1: "Golden sales figures factually wrong...
  the golden states CA $147,993 vs recomputed $138,906... The golden
  double-counts continuation-line prices and mislabels 9,989 geography-
  attributable orders as 10,000 unique order names." Verdict: GAP. Quote:
  "No script in this repo recomputes the golden's LITERAL values from source
  data and compares them."

  coverage-cov7-SVC-PC-5-3-0.md, RC3: "Golden contains unsourced fabricated
  factual claims... C12 calls $4,390 an FY2021 Returns & Refunds actual, but
  Sales_Orders.xlsx sums to $2,390 and Q2_Ops_Summary.docx reports $2,200."
  The report explicitly discloses the bare-number sub-issue is NOT caught by
  anything: "pattern 3 catches the provenance misstatement... but not the bare
  unsourced literal values ($72,490, $4,390) in isolation... No C/D/E script
  validates golden content against source documents (there is no 'golden
  groundedness' check)."

Why this is NOT golden_arithmetic_check.py's job (letter E, same folder):
golden_arithmetic_check.py catches a NARROWER, different defect shape: the
golden's OWN PROSE describing its OWN derivation is internally arithmetically
wrong (e.g. "A - B = C" where the stated C does not equal A-B). It was
adversarially verified THIS SESSION (2026-09-15) to produce 0/2 recall on the
two motivating defects, because those defects are BARE NUMBERS in xlsx cells
or prose ("$4,390 (actual)"), not prose derivation statements. The check is
structurally blind to the bare-number defect class. This check targets a
structurally different defect: golden-vs-SOURCE-DATA correctness, not golden-
self-consistency. It reads the REAL environment/source documents and checks
whether the golden's stated figures are actually derivable from them. That
requires semantic/contextual judgment (which rows in Sales_Orders.xlsx are
"FY2021 Returns & Refunds," what counts as "geography-attributable" vs a
continuation line) that a regex-based deterministic check cannot do reliably.
This is why it is an LLM-based check (letter A), not another deterministic one.

What it does, per task:
  1. Extract the golden solution's LITERAL factual claims (dollar figures,
     counts, percentages, dates presented as facts/answers) by scanning the
     golden text with VALUE_TOKEN_RE (reused from criterion_groundedness_check.py,
     same convention this session's other new checks follow) and by reading
     xlsx label-value pairs (reused from golden_arithmetic_check.py's
     read_xlsx_all_text_with_values / read_xlsx_label_value_pairs). NOT
     formulas (formula_health_check.py already recomputes those) and NOT
     self-describing derivation statements (golden_arithmetic_check.py already
     handles those: this check filters out VALUE_TOKEN_RE matches that fall
     within a find_derivation_statements span, so the two checks do not
     overlap).
  2. Read the REAL environment/source documents (reuse find_environment_files
     from answer_key_content_leak_check.py, which dispatches on format:
     environment/initial_workspace/ for SVC-PC, environment/data/ for EKW;
     same resolution rule environment_size_budget_check.py uses).
  3. For each candidate golden figure, search the environment text for
     plausible corroborating or contradicting context (label/line-item match,
     similar to criterion_groundedness_check.py's own approach) and hand the
     LLM only the RELEVANT excerpts plus the claim, not the whole corpus.
  4. Ask the LLM to determine whether each literal golden figure is actually
     grounded in / derivable from the real source documents, or is wrong /
     fabricated relative to them.

Text extraction: reuses the same helpers every other check in this folder
calibrated against the real corpus:
  - extract_file_text, find_golden_files from answer_key_rubric_leak_check.py
  - find_environment_files, read_docx_text from answer_key_content_leak_check.py
  - read_xlsx_label_value_pairs (env value maps), find_derivation_statements
    from golden_arithmetic_check.py
  - read_xlsx_all_text_with_values from golden_arithmetic_check.py (golden
    text only; the env text path uses a local row-joined extractor, see
    _read_xlsx_row_joined_text, because the shared helper's len<=2 string
    filter drops 2-char US state codes from per-jurisdiction env rows)
  - VALUE_TOKEN_RE, to_float, sig_len from criterion_groundedness_check.py

Prompt size: environment/ directories can be large (up to 50+ MB per the real
corpus's own environment_size_budget_check.py findings). This check does NOT
naively dump every source file's full text into one LLM prompt. It:
  1. Extracts only the CANDIDATE golden literal claims first (deterministically
     via VALUE_TOKEN_RE, capped at MAX_CLAIMS).
  2. For each candidate figure, searches the environment text for plausible
     corroborating or contradicting context (proximity search on the claim's
     value and context keywords).
  3. Hands the LLM only the RELEVANT excerpts plus the claim, not the whole
     corpus.
  4. If a task's environment is too large (total file size > ENV_TOO_LARGE_BYTES),
     skips with a clear reason rather than hanging or truncating silently
     (matching source_truncation_check.py's own disclosed-truncation convention).

Calibration
-----------
UPDATED 2026-09-16 when this check was ported into the real pipeline repo (it was mirror-only
before): the paragraph above described GLM's own build-time situation (neither SVC-PC-37-3-0
nor SVC-PC-5-3-0 available as a real package, synthetic-fixture-only calibration). Both ARE
real, full packages in THIS repo's corpus (C:/ekwqc/repo/pipeline/data/svc_pc_qc/
03_dataos_ready/), so the port was calibrated against them directly, not against synthetic
fixtures, and two real, load-bearing problems were found and fixed before trusting it:

1. The retrieval logic (find_env_excerpts) was CONFIRMED BROKEN against the real motivating
   case, not assumed working because the plumbing was "verified": run directly against real
   SVC-PC-5-3-0, the original flat single-match proximity search returned an unrelated
   customer-list table and a coincidental xlsx label match for the golden's $4,390 claim --
   never Q1_Ops_Summary.docx's or Q2_Ops_Summary.docx's real Returns & Refunds figures, the
   exact evidence the claim needs. Rebuilt as a per-file, IDF-weighted, singular/plural-
   tolerant relevance search -- see find_env_excerpts's own docstring for the full mechanism
   and why each piece (document-frequency filtering, densest-window centering, plural
   tolerance) was necessary, confirmed one at a time against the same real task, not assumed
   sufficient after the first fix.
2. This check's own import of read_xlsx_all_text_with_values/read_xlsx_label_value_pairs/
   find_derivation_statements from golden_arithmetic_check.py failed on import: this repo's
   real golden_arithmetic_check.py is a structurally different, independently-built check (see
   this module's own NOTE above the imports). Fixed by inlining the two xlsx readers and
   dropping derivation-statement filtering (nothing to overlap with in the real repo).

Real LLM verification (RAN 2026-09-16, real calls against the configured glm-5.2 backend, not
dry-run): SVC-PC-5-3-0 correctly flagged, 3 findings -- the golden's $4,390 claim ("source:
Shipping_Rate_Card_2021.xlsx / Q2_Ops_Summary.docx = $2,390 (Q1) + $2,200 (Q2) = $4,590 for H1
alone... already exceeds the golden's claimed full-year figure"), plus two bonus real catches
(a Stripe transaction-ID fragment "72490" misread as a dollar figure, found twice, in two
different claim extractions of the same underlying string). SVC-PC-37-3-0 (GLM's other named
case) came back clean -- expected, not a miss: that task's own defect is an in-table
aggregation golden_arithmetic_check.py already owns (tracker row 2), outside this check's
bare-literal-claim scope by design. False-positive-rate sample (RAN 2026-09-16, 5 more real
calls against varied real tasks -- SVC-PC-21-4-0, SVC-PC-1-1-0, SVC-PC-33-8-0, SVC-PC-41-4-0,
SVC-PC-29-2-0, 3-50 claims each): all 5 came back clean, zero false positives observed, 460.5s
total for the batch (92.1s/task average). 7 real LLM calls total across this port's
verification: 1 true positive, 6 true negatives, 0 false positives, 0 false negatives observed
-- not a full-600-task run (real per-task latency observed 39-111s on individually-timed calls;
comparable real-call scale to tracker row 15's own 9-call verification of the other LLM-based
check in this project). See tracker row 13 for the full record.

Severity: warn-only, never fail. This matches EVERY other LLM-based check in
this project ("candidate, not verdict" posture, explicitly established and
re-confirmed by this session's own severity audit of all 7 round-29/30 checks).
A false warn is advisory, not blocking; a false FAIL would be.

Output shape
------------
Per-task result dict (the same verdict + findings shape every other check in
this folder produces, so it merges into svc_run_checks.py / ekw_run_checks.py
the same way):

    {
        "task_id": "SVC-PC-37-3-0",
        "status": "pass" | "warn" | "skip" | "error",
        "task_format": "svc_pc" | "ekw" | "none",
        "n_golden_files": 1,
        "n_env_files": 5,
        "n_claims": 12,
        "parse_errors": [],
        "errors": [],
        "findings": [
            {
                "kind": "golden_ungrounded",
                "severity": "warn",
                "claim_value": "$147,993",
                "claim_context": "CA: 147993",
                "golden_file": "golden.xlsx",
                "source_file": "Sales_Orders.xlsx",
                "source_value": "$138,906",
                "evidence": "why this is ungrounded"
            }
        ],
        "n_findings": 0,
        "n_warn": 0,
        "llm_backend": "cli" | "http" | "dry_run" | "none",
        "prompt_chars": 12345,
        "content_unavailable": false
    }

LLM backend
-----------
Uses tools/llm_backend.call_llm() which tries the Claude Code CLI first (free
under a Max plan, no credential handling here) then falls back to a generic
HTTP call. For verifying the request shape without a real key, pass --dry-run.
Same backend as Check A and rubric_overspecification_check.py.

CLI
---
    python golden_groundedness_check.py --all --root DIR --out results.json
    python golden_groundedness_check.py SVC-PC-37-3-0 --root DIR --out results.json
    python golden_groundedness_check.py SVC-PC-37-3-0 --root DIR --out results.json --dry-run

Stdlib only for the runner; openpyxl / python-docx are pulled in by the
text-extraction imports (same as every other check in this folder).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Row-15 fix (tracker row 15, commit f0d1105), applied here too: the library default of
# max_tokens=4096 starves this backend's reasoning-heavy model (glm-5.2) before it writes any
# visible answer on a real audit-sized prompt -- confirmed there via raw-HTTP diagnostics
# (finish_reason="length", completion_tokens exactly 4096, content_len=0), fixed at 32000 and
# verified 9/9 real calls succeeding. rubric_overspecification_check.py already carries this
# setdefault; this check calls the SAME call_llm() with a similarly large prompt (11+ claims
# plus source excerpts) and would hit the identical starvation without it. setdefault, not a
# hard override, so an operator's own explicit budget is never silently replaced.
os.environ.setdefault("LLM_API_MAX_TOKENS", "32000")

from tools.llm_backend import call_llm, build_http_request, LLMBackendError

# Reuse the golden-file loading and text extraction from
# answer_key_rubric_leak_check.py (same calibrated path every other check uses).
from answer_key_rubric_leak_check import (
    extract_file_text,
    find_golden_files,
    _task_format,
)

# Reuse the environment-file discovery and docx text extraction from
# answer_key_content_leak_check.py (same format dispatch: SVC-PC uses
# environment/initial_workspace/, EKW uses environment/data/).
from answer_key_content_leak_check import find_environment_files, read_docx_text

# NOTE (2026-09-16 port): GLM's mirror build of this file imported
# read_xlsx_all_text_with_values / read_xlsx_label_value_pairs / find_derivation_statements
# from golden_arithmetic_check.py. That import fails against THIS repo's real
# golden_arithmetic_check.py (commit a22402c): the real check was independently built with a
# structurally different design (Case-A table-cell/column-header aggregation recomputation,
# see that file's own module docstring and tracker row 2) and has no prose-derivation-statement
# concept at all -- confirmed by reading it directly, not assumed, before porting anything here.
# Consequently:
#   - read_xlsx_all_text_with_values / read_xlsx_label_value_pairs are inlined below, ported
#     verbatim from the mirror (self-contained openpyxl readers, no dependency on any other
#     check's internals).
#   - find_derivation_statements and the "exclude derivation-statement spans" filtering step
#     are DROPPED, not stubbed. Their only purpose was avoiding overlap with
#     golden_arithmetic_check.py's own derivation-statement handling -- which does not exist in
#     the real check, so there is nothing to overlap with. Dropping this step means this check's
#     claim extraction is slightly BROADER than the mirror's own version (a bare number inside a
#     derivation-looking sentence is now a candidate claim too), which is a strict superset, not
#     a narrower miss, and directly helps rather than hurts row 13's goal.

# Reuse the value-token extraction from criterion_groundedness_check.py (same
# token shapes: currency, percent, dates, quoted, comma_number, decimal_number,
# bare_number). Same convention this session's other new checks follow.
from criterion_groundedness_check import VALUE_TOKEN_RE, to_float, sig_len

# Windows console defaults to cp1252; force UTF-8 so non-cp1252 characters in
# real golden/environment text never crash a batch run. Same line every other
# check in this folder carries.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

try:
    import openpyxl
except ImportError:  # pragma: no cover
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl


# ---------------------------------------------------------------------------
# xlsx readers, inlined from GLM's mirror build of golden_arithmetic_check.py (see the
# NOTE above the imports for why this is inlined rather than imported from the real,
# structurally different golden_arithmetic_check.py in this repo).
# ---------------------------------------------------------------------------


def read_xlsx_label_value_pairs(path: Path) -> dict[str, float]:
    """Read an xlsx file and build a map of label-text to numeric-value, by scanning each row
    for a string cell followed by a numeric cell in the same row (the common label-in-column-A,
    value-in-column-B layout). Never raises: an unparseable file returns an empty dict.
    """
    pairs: dict[str, float] = {}
    try:
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    except Exception:
        return pairs
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                label: str | None = None
                for cell in row:
                    value = cell.value
                    if isinstance(value, bool):
                        continue
                    if isinstance(value, str) and value.strip() and label is None:
                        label = value.strip()
                    elif isinstance(value, (int, float)) and label is not None:
                        pairs[label.lower()] = float(value)
                        label = None
        return pairs
    except Exception:
        return pairs
    finally:
        wb.close()


def read_xlsx_all_text_with_values(path: Path) -> tuple[str, dict[str, float]]:
    """Read an xlsx file and return (full_text, label_value_pairs): every string and numeric
    cell joined by newlines, plus the label-value map from read_xlsx_label_value_pairs.
    """
    texts: list[str] = []
    try:
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    except Exception:
        return "", {}
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    value = cell.value
                    if isinstance(value, bool):
                        continue
                    if isinstance(value, str):
                        if len(value.strip()) > 2:
                            texts.append(value)
                    elif isinstance(value, (int, float)):
                        texts.append(str(value))
        return "\n".join(texts), read_xlsx_label_value_pairs(path)
    except Exception:
        return "\n".join(texts), {}
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cap the number of golden literal claims extracted per task. More than this
# would blow the LLM context window when combined with environment excerpts.
# Claims are prioritized by kind: currency first (most likely to be a
# load-bearing factual claim), then comma_number, percent, dates, bare_number.
MAX_CLAIMS = 50

# Cap each environment excerpt at this many characters. An excerpt is a window
# of text around a match for a golden claim's value or context keywords. Raised 2026-09-16
# from 2000 to 5000: at PROXIMITY_WINDOW=300 (600 chars/file), the old 2000-char cap fit only
# ~3 file excerpts before silent truncation, which defeated MAX_RELEVANT_FILES=8's whole point
# -- confirmed directly against SVC-PC-5-3-0: Q1_Ops_Summary.docx correctly scored and ranked
# by find_env_excerpts, but was truncated away before the LLM ever saw it because it fell
# outside this cap's first ~3 files. 5000 chars fits all 8 at the widest.
MAX_EXCERPT_CHARS = 5000

# Cap the total environment excerpts section of the prompt at this many
# characters. If the combined excerpts exceed this, they are truncated with a
# visible marker so the LLM knows it is seeing a partial extract.
MAX_ENV_EXCERPTS_CHARS = 60000

# If the total environment file sizes exceed this many bytes, skip the task
# with a clear reason rather than attempting to extract and search a corpus
# too large to handle. 20 MB of binary files typically extracts to much more
# text; this is a conservative guard, not a hard limit on prompt size.
ENV_TOO_LARGE_BYTES = 50 * 1000 * 1000

# If the environment has more than this many files, skip the task with a clear
# reason. Reading 400+ xlsx files with openpyxl takes 30+ seconds per task;
# this guard keeps the check tractable in a batch run. A task with 200+ source
# files likely has a large, diverse corpus where most files are irrelevant to
# any single golden claim, so skipping is safer than a 30+ second stall.
ENV_TOO_MANY_FILES = 200

# Proximity window for finding environment text near a golden claim's value
# or context keywords (characters on either side of the match).
PROXIMITY_WINDOW = 300

# Year-shaped tokens to exclude from claims (a year is a date filter, not a
# figure to verify against source data).
YEAR_RE = re.compile(r"^(19|20)\d{2}$")

# Minimum significant digits for a claim value to be included. Filters out
# single-digit numbers and very short tokens that are likely formatting or
# structural, not factual claims. Matches criterion_groundedness_check.py's
# own floor for non-bare_number kinds.
MIN_SIG_LEN = 4

# Kinds that are most likely to be load-bearing factual claims about source
# data, in priority order for the MAX_CLAIMS cap.
CLAIM_PRIORITY = [
    "currency",
    "comma_number",
    "decimal_number",
    "percent",
    "date_slash",
    "date_iso",
    "date_dmon",
    "date_mdy",
    "bare_number",
]

# 2-letter US Postal Service state codes (50 states + DC), lowercased. These
# are the concrete, evidenced short labels that the len>=3 context-word
# filter and the len<4 search guard both wrongly dropped, breaking
# per-jurisdiction golden groundedness (SVC-PC-37-3-0 RC1: golden "CA"
# $147,993 vs recomputed $138,906). Kept to the verified set: do not broaden
# beyond real USPS codes without new evidence.
US_STATE_CODES = frozenset(
    {
        "al",
        "ak",
        "az",
        "ar",
        "ca",
        "co",
        "ct",
        "de",
        "fl",
        "ga",
        "hi",
        "id",
        "il",
        "in",
        "ia",
        "ks",
        "ky",
        "la",
        "me",
        "md",
        "ma",
        "mi",
        "mn",
        "ms",
        "mo",
        "mt",
        "ne",
        "nv",
        "nh",
        "nj",
        "nm",
        "ny",
        "nc",
        "nd",
        "oh",
        "ok",
        "or",
        "pa",
        "ri",
        "sc",
        "sd",
        "tn",
        "tx",
        "ut",
        "vt",
        "va",
        "wa",
        "wv",
        "wi",
        "wy",
        "dc",
    }
)


SYSTEM_PROMPT = (
    "You are a QC auditor for Harbor-shaped grading tasks. You read the golden "
    "answer's LITERAL factual claims (dollar figures, counts, percentages, "
    "dates presented as facts or answers) and the task's REAL source document "
    "excerpts, and you judge whether each golden figure is actually GROUNDED IN "
    "the source data (the figure matches what the source documents support) "
    "or UNGROUNDED (the golden states a figure that does not match what the "
    "source data actually supports). You report findings as strict JSON. You "
    "do not fix, rewrite, or suggest fixes. You only flag figures you can cite "
    "specific source evidence for. If you are not confident a figure is "
    "ungrounded, do not flag it. A false positive wastes a human reviewer's "
    "time; a false negative is caught by the next QC layer. Prefer precision "
    "over recall."
)


# ---------------------------------------------------------------------------
# Golden claim extraction
# ---------------------------------------------------------------------------


def _extract_context_words(
    text: str, start: int, end: int, window: int = 100
) -> list[str]:
    """Extract content words from the text window around a match position,
    for use as environment search keywords. Returns lowercase words of
    3+ alpha characters, excluding common stopwords. Never raises."""
    s = max(0, start - window)
    e = min(len(text), end + window)
    snippet = text[s:e]
    words = re.findall(r"[A-Za-z]{3,}", snippet.lower())
    # Filter out generic descriptors and stopwords that carry no source-data
    # signal (a subset of criterion_groundedness_check.py's own stopword set,
    # kept small here since these are search keywords, not anchor words).
    stop = {
        "the",
        "and",
        "for",
        "are",
        "was",
        "but",
        "not",
        "you",
        "all",
        "any",
        "can",
        "her",
        "was",
        "one",
        "our",
        "out",
        "has",
        "have",
        "had",
        "been",
        "this",
        "that",
        "from",
        "they",
        "them",
        "their",
        "there",
        "what",
        "which",
        "who",
        "whom",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "been",
        "being",
        "with",
        "about",
        "into",
        "than",
        "then",
        "also",
        "more",
        "most",
        "some",
        "such",
        "only",
        "own",
        "same",
        "other",
        "over",
        "under",
        "between",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "per",
        "via",
        "here",
        "where",
        "total",
        "sum",
        "value",
        "amount",
        "figure",
        "number",
        "count",
        "expected",
        "actual",
        "reported",
        "stated",
    }
    return [w for w in words if w not in stop]


def _get_line_around(text: str, pos: int) -> str:
    """Return the line of text containing position pos, stripped. Never raises."""
    line_start = text.rfind("\n", 0, pos)
    if line_start == -1:
        line_start = 0
    else:
        line_start += 1
    line_end = text.find("\n", pos)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end].strip()


def _safe_stat_size(path: Path) -> int:
    """Return file size in bytes, or 0 if stat fails. Never raises."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def extract_golden_claims(
    golden_text: str,
    golden_value_maps: list[dict[str, float]],
    golden_file_names: list[str],
) -> list[dict]:
    """Extract literal factual claims from golden text and xlsx label-value
    pairs. Returns a list of dicts with keys:
      - value: float (the numeric value, or None for non-numeric kinds)
      - value_raw: str (the raw text, e.g. "$147,993")
      - kind: str (the VALUE_TOKEN_RE kind, or "label_value" for xlsx pairs)
      - context: str (the surrounding text/line for the claim)
      - source_file: str (which golden file it came from)
      - context_words: list[str] (content words for env search)

    Filters out:
      - Tokens within derivation statement spans (golden_arithmetic_check.py
        already handles those; this check should not overlap).
      - Year-shaped tokens (a year is a date filter, not a figure to verify).
      - Tokens with fewer than MIN_SIG_LEN significant digits (likely
        formatting or structural, not factual claims).
    """

    # Derivation-statement-span exclusion DROPPED for this repo's real golden_arithmetic_
    # check.py, which has no prose-derivation concept to overlap with -- see the NOTE above
    # this module's imports. _in_deriv_span always returns False now; kept as a named no-op
    # rather than deleting every call site, so a future recalibration against a differently-
    # shaped golden_arithmetic_check.py can reinstate real span exclusion by filling this
    # function back in, not by re-deriving the call sites from scratch.
    def _in_deriv_span(pos: int, end: int) -> bool:
        return False

    claims: list[dict] = []
    seen_values: set[tuple[str, str]] = set()

    # 1. Extract claims from xlsx label-value pairs (structured data).
    for i, vmap in enumerate(golden_value_maps):
        fname = golden_file_names[i] if i < len(golden_file_names) else "?"
        for label, val in vmap.items():
            if val is None or abs(val) < 10:
                continue
            if YEAR_RE.match(str(int(val)) if val == int(val) else ""):
                continue
            raw = f"{val:,.2f}" if val != int(val) else f"{int(val):,}"
            context = f"{label}: {raw}"
            key = (raw, context[:80])
            if key in seen_values:
                continue
            seen_values.add(key)
            words = [
                w
                for w in re.split(r"[^a-z]+", label.lower())
                if len(w) >= 3 or w in US_STATE_CODES
            ]
            claims.append(
                {
                    "value": float(val),
                    "value_raw": raw,
                    "kind": "label_value",
                    "context": context,
                    "source_file": fname,
                    "context_words": words,
                }
            )

    # 2. Extract claims from VALUE_TOKEN_RE matches in the golden text.
    for vm in VALUE_TOKEN_RE.finditer(golden_text):
        token = vm.group(0)
        kind = vm.lastgroup
        start, end = vm.start(), vm.end()

        # Skip tokens within derivation statement spans.
        if _in_deriv_span(start, end):
            continue

        # Skip year-shaped bare numbers.
        if kind == "bare_number" and YEAR_RE.match(token):
            continue

        # Skip tokens with too few significant digits (likely formatting).
        # Use a floor of 2 for all kinds (matching criterion_groundedness_check.py's
        # bare_number floor): the abs(value) < 10 filter below already handles
        # "too small to be a factual claim" for numeric kinds, and a floor of 2
        # keeps percentages like "12.5%" (sig_len 3) that would be wrongly dropped
        # by a higher floor.
        sl = sig_len(token)
        if sl < 2:
            continue

        value = (
            to_float(token)
            if kind
            in ("currency", "comma_number", "decimal_number", "bare_number", "percent")
            else None
        )

        # Skip very small numeric values (likely formatting/structural).
        if value is not None and abs(value) < 10:
            continue

        context = _get_line_around(golden_text, start)
        if not context:
            context = token
        key = (token, context[:80])
        if key in seen_values:
            continue
        seen_values.add(key)

        words = _extract_context_words(golden_text, start, end)
        # Determine which golden file this text came from. The golden_text is
        # a concatenation of all golden file texts. We don't have precise
        # file boundaries in the concatenated text, so we use the first file
        # name as a fallback (the most common case is a single golden file).
        fname = golden_file_names[0] if golden_file_names else "?"
        claims.append(
            {
                "value": value,
                "value_raw": token,
                "kind": kind,
                "context": context,
                "source_file": fname,
                "context_words": words,
            }
        )

    # Sort by priority kind, then cap at MAX_CLAIMS.
    kind_priority = {k: i for i, k in enumerate(CLAIM_PRIORITY)}
    kind_priority["label_value"] = -1  # structured claims first
    claims.sort(key=lambda c: kind_priority.get(c["kind"], 99))

    if len(claims) > MAX_CLAIMS:
        claims = claims[:MAX_CLAIMS]

    return claims


# ---------------------------------------------------------------------------
# Environment text extraction + proximity search
# ---------------------------------------------------------------------------


def _read_xlsx_row_joined_text(path: Path) -> str:
    """Read an xlsx/xlsm file and emit ONE text line per row, concatenating
    all of that row's non-empty cell values with ' | ' (e.g.
    "CA | ORD-001 | 45000"). Used ONLY by this check for environment files,
    NOT the shared golden_arithmetic_check.py helper.

    Why this exists instead of reusing read_xlsx_all_text_with_values: that
    shared helper emits each cell as an independent, newline-separated token
    and drops every string cell with len(value.strip()) <= 2 to avoid noise.
    That filter is correct for golden_arithmetic_check.py's needs, but here
    it drops 2-char US state codes ("CA", "NV", "NY", "TX") from real SVC-PC
    environment spreadsheets, detaching the jurisdiction label from its
    row's amount. The row-join itself is the noise reduction: a bare "CA"
    alone is meaningless, but "CA | ORD-001 | 45000" on one line is real
    signal an LLM can use. No length filter is applied: short cells stay
    attached to their row.

    Matches the folder's existing xlsx convention: openpyxl.load_workbook
    with data_only=True, read_only=True (same as
    read_xlsx_all_text_with_values and read_xlsx_label_value_pairs). Never
    raises: an unparseable file returns an empty string."""
    lines: list[str] = []
    try:
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    except Exception:
        return ""
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                cells: list[str] = []
                for cell in row:
                    value = cell.value
                    if isinstance(value, bool):
                        continue
                    if value is None:
                        continue
                    if isinstance(value, (int, float)):
                        cells.append(str(value))
                    else:
                        s = str(value).strip()
                        if s:
                            cells.append(s)
                if cells:
                    lines.append(" | ".join(cells))
        return "\n".join(lines)
    except Exception:
        return "\n".join(lines)
    finally:
        wb.close()


def build_env_text(
    env_files: list[Path],
) -> tuple[str, list[dict[str, float]], list[str], int, list[tuple[str, str]]]:
    """Extract text from all environment files. Returns:
      - env_text: concatenated text with file markers
      - env_value_maps: list of label-value dicts (one per xlsx file)
      - env_file_names: list of file names (parallel to env_value_maps for xlsx)
      - total_bytes: total size of all environment files
      - per_file_texts: list of (filename, UNMARKED text) pairs, one per file that produced
        text -- added 2026-09-16 so find_env_excerpts can score and search files
        INDIVIDUALLY, not just the flat concatenation. See that function's own docstring for
        why: a flat-text search returns whichever file happens to contain a word FIRST, not
        the file(s) most relevant to a claim, which breaks retrieval for a claim whose real
        evidence is split across 2+ named documents (row 13's whole defect class -- confirmed
        directly against the real SVC-PC-5-3-0 task before this fix: the flat search surfaced
        an unrelated customer-list table and a coincidental xlsx label match, never
        Q1_Ops_Summary.docx's or Q2_Ops_Summary.docx's real Returns & Refunds figures).

    Never raises: an unparseable file contributes an error string and no text.
    """
    text_parts: list[str] = []
    value_maps: list[dict[str, float]] = []
    file_names: list[str] = []
    per_file_texts: list[tuple[str, str]] = []
    total_bytes = 0

    for ef in env_files:
        try:
            total_bytes += ef.stat().st_size
        except OSError:
            pass

        suffix = ef.suffix.lower()
        if suffix in (".xlsx", ".xlsm"):
            # Row-joined text keeps 2-char labels (CA, NV) attached to their
            # row's values. read_xlsx_label_value_pairs is unaffected by the
            # 2-char string filter (it has no length filter), so the value
            # maps are still produced by that helper. Only the text path
            # switches to the local row-join; the shared helper is unchanged.
            text = _read_xlsx_row_joined_text(ef)
            pairs = read_xlsx_label_value_pairs(ef)
            value_maps.append(pairs)
            file_names.append(ef.name)
            if text.strip():
                text_parts.append(f"--- file: {ef.name} ---\n{text}\n")
                per_file_texts.append((ef.name, text))
        else:
            text, err = extract_file_text(ef)
            if err and not text:
                continue
            if text.strip():
                text_parts.append(f"--- file: {ef.name} ---\n{text}\n")
                per_file_texts.append((ef.name, text))

    return "\n".join(text_parts), value_maps, file_names, total_bytes, per_file_texts


def _merge_env_value_maps(maps: list[dict[str, float]]) -> dict[str, float]:
    """Merge multiple xlsx label-value maps into one. Later maps do not
    overwrite earlier ones (first match wins, matching
    golden_arithmetic_check.py's build_env_value_map behavior)."""
    merged: dict[str, float] = {}
    for m in maps:
        for k, v in m.items():
            if k not in merged:
                merged[k] = v
    return merged


# Cross-document retrieval, added 2026-09-16 for row 13 (cross-document narrative-prose
# reconciliation) -- see find_env_excerpts's own docstring for the confirmed-real problem this
# fixes and MIN_CONTEXT_WORD_MATCHES / MAX_RELEVANT_FILES's own reasoning below.
# MIN_CONTEXT_WORD_MATCHES=1, not 2: the earlier version required 2 co-occurring words as a
# noise filter, but that filter's job is now done by the document-frequency drop in
# find_env_excerpts (a word present in more than DF_CAP files is dropped before scoring), which
# is a strictly better discriminator -- a real generic word count filter, not an arbitrary
# co-occurrence count. Confirmed directly: with the DF filter in place, requiring 2 matches
# still excluded SVC-PC-5-3-0's own Q1_Ops_Summary.docx (which matches exactly one real,
# specific, DF-surviving word, "refunds" via singular/plural tolerance) purely because it only
# has ONE genuinely relevant word to match on, not because it is irrelevant.
MIN_CONTEXT_WORD_MATCHES = 1
MAX_RELEVANT_FILES = 8


def find_env_excerpts(
    claims: list[dict],
    env_text: str,
    env_value_map: dict[str, float],
    per_file_texts: list[tuple[str, str]] | None = None,
) -> list[str]:
    """For each golden claim, find relevant environment excerpts. Returns a
    list of excerpt strings (one per claim, possibly empty if no match found).

    Search strategy per claim, ALL of which now run independently (not gated behind "stop at
    first hit" -- a weak strategy-2 xlsx label match used to SUPPRESS the real strategy-3
    search entirely, confirmed as a real bug against SVC-PC-5-3-0 before this fix: an
    unrelated "subtotal - returns = 39.00" xlsx label match blocked the docx proximity search
    that would have found the real evidence):
      1. Exact value match: search env_text for the claim's raw value.
      2. Label match: search env_value_map for labels matching the claim's context_words.
      3. PER-FILE relevance search (see below) -- the primary fix for cross-document
         reconciliation.
      4. Near-value-match fallback: only if nothing else found anything.

    Strategy 3, per-file relevance search (replaces a flat-text single-match proximity search
    that was confirmed, by running it against the real SVC-PC-5-3-0 task before this fix, to
    retrieve the WRONG evidence for the check's own motivating case: golden claims "$4,390
    (FY2021 Returns & Refunds actual)"; the real evidence is split across TWO named documents,
    Q1_Ops_Summary.docx ("The cash refund total for Q1 was $2,390") and Q2_Ops_Summary.docx
    ("Less: refunds & returns ... $(2,200)"), but the old flat search's `lower_env.find(word)`
    + immediate `break` returned whichever FILE happened to contain the word "returns" FIRST in
    directory-listing order across all 63 environment files -- an unrelated customer-list table,
    never either Ops Summary document. Fixed by searching each environment FILE separately
    (per_file_texts, added to build_env_text for exactly this) and scoring it by how many
    DISTINCT context words it contains, taking an excerpt from the TOP files by score rather
    than the first file that matches any one word. MIN_CONTEXT_WORD_MATCHES=2 (not 1): a single
    generic word ("actual", "expense") matches too many unrelated files to be a useful signal
    alone; two co-occurring words ("returns" + "refunds") is a real topical-relevance signal,
    confirmed directly: Q1 and Q2 Ops Summary both score >=2 on the real corpus, the other 61
    real environment files in this task do not. MAX_RELEVANT_FILES=4 (not 1): enough margin for
    a reconciliation spread across 2-3 documents plus one extra, without ballooning prompt size
    (each excerpt is still capped at PROXIMITY_WINDOW on each side, same as every other
    strategy).
    """
    excerpts: list[str] = []
    lower_env = env_text.lower()
    per_file_texts = per_file_texts or []

    for claim in claims:
        parts: list[str] = []
        seen_files: set[str] = set()
        value_raw = claim.get("value_raw", "")
        value = claim.get("value")
        context_words = claim.get("context_words", [])

        # Strategy 1: exact value match in env text.
        if value_raw:
            # Try the raw value (e.g., "$147,993") and a normalized form.
            for needle in [value_raw, value_raw.replace("$", "").replace(",", "")]:
                if not needle:
                    continue
                idx = lower_env.find(needle.lower())
                if idx >= 0:
                    s = max(0, idx - PROXIMITY_WINDOW)
                    e = min(len(env_text), idx + len(needle) + PROXIMITY_WINDOW)
                    parts.append(env_text[s:e])
                    break

        # Strategy 2: label match in env value map.
        if value is not None and context_words:
            for word in context_words[:5]:
                for label, env_val in env_value_map.items():
                    if word in label:
                        parts.append(f"[env label match] {label} = {env_val:,.2f}")
                        break

        # Strategy 3: per-file relevance search -- see module-level comment above and this
        # function's own docstring. Runs regardless of whether strategies 1-2 found anything
        # (that gating was the bug: see docstring).
        #
        # De-duplicated (order-preserving) before slicing to 8: _extract_context_words does
        # not dedup its own output, and a claim's context window often restates one word twice
        # (e.g. "returns, fulfilment (secondary): FY2021 Returns & Refunds..." has "returns"
        # twice before "refunds" appears once) -- without dedup here, a repeated generic word
        # wastes a slot that a more specific, once-occurring word (like "refunds") needed.
        # Confirmed as a real, not theoretical, difference against SVC-PC-5-3-0's claim 5.
        seen_w: set[str] = set()
        words_lower: list[str] = []
        for w in context_words:
            wl = w.lower()
            if wl in seen_w:
                continue
            if len(wl) >= 4 or wl in US_STATE_CODES:
                seen_w.add(wl)
                words_lower.append(wl)
            if len(words_lower) >= 8:
                break

        def _find_tolerant(text_lower: str, w: str) -> int:
            """Exact match, then light singular/plural tolerance (bare trailing "s" only,
            same scope discipline as instruction_requirement_coverage_check.py's own light
            stemmer). See the real SVC-PC-5-3-0 case in this function's docstring."""
            idx = text_lower.find(w)
            if idx < 0 and w.endswith("s") and len(w) > 4:
                idx = text_lower.find(w[:-1])
            if idx < 0:
                idx = text_lower.find(w + "s")
            return idx

        # Document-frequency filter: drop words that are too GENERIC to discriminate between
        # files, confirmed as a real, necessary second fix (the plural tolerance alone was not
        # enough) against SVC-PC-5-3-0 -- "operational" and "returns" alone each matched over a
        # third of this task's 30 real environment files (ops-related boilerplate is common
        # across unrelated documents), which buried Q1_Ops_Summary.docx (2 matches: "returns" +
        # tolerant "refund") under several unrelated files that coincidentally also matched 2-3
        # generic words ("operational", "secondary"). A word present in MORE than DF_CAP files
        # carries no per-claim discriminating signal and is dropped before scoring; "refunds"
        # (~4 files: both real Ops Summaries, the SOP, and one rate card) survives this filter
        # and is exactly the word that should decide relevance here.
        DF_CAP = max(3, len(per_file_texts) // 6)
        if words_lower and per_file_texts:
            doc_freq = {
                w: sum(
                    1
                    for _, ftext in per_file_texts
                    if _find_tolerant(ftext.lower(), w) >= 0
                )
                for w in words_lower
            }
            specific_words = [w for w in words_lower if doc_freq[w] <= DF_CAP]
            # If every candidate word is generic (rare, but possible on a small environment),
            # fall back to the full list rather than searching with nothing at all.
            search_words = specific_words or words_lower
        else:
            search_words = words_lower

        if search_words and per_file_texts:
            scored: list[tuple[float, str, str, int]] = []
            for fname, ftext in per_file_texts:
                ftext_lower = ftext.lower()
                matched_w = [
                    w for w in search_words if _find_tolerant(ftext_lower, w) >= 0
                ]
                match_positions = [_find_tolerant(ftext_lower, w) for w in matched_w]
                if len(match_positions) < MIN_CONTEXT_WORD_MATCHES:
                    continue
                # Weight by inverse document frequency, not a raw match count: a file matching
                # one rare, highly specific word (doc_freq low) is a stronger relevance signal
                # than a file matching one merely-uncommon word, and this is what actually
                # separates SVC-PC-5-3-0's Q1_Ops_Summary.docx (matches only "refunds", one of
                # ~9 files, real evidence) from a same-count tie against noise -- a raw count
                # cannot express that difference, IDF weighting can.
                weight = sum(1.0 / max(1, doc_freq.get(w, 1)) for w in matched_w)
                # DENSEST WINDOW, not just the earliest word's position: a file can match >=2
                # words from totally different, unrelated parts of a long document (the
                # motivating real bug -- "fulfilment" from this claim's OWN adjacent-topic
                # aside matched near the top of an unrelated file, while "returns"/"refunds"
                # never got near it). For each matched position, count how many OTHER matched
                # positions fall within one PROXIMITY_WINDOW of it, and center the excerpt on
                # whichever position has the most nearby company -- the real evidence sentence
                # in a relevant file, not an arbitrary single-word hit.
                best_pos = match_positions[0]
                best_nearby = 0
                for p in match_positions:
                    nearby = sum(
                        1 for q in match_positions if abs(q - p) <= PROXIMITY_WINDOW
                    )
                    if nearby > best_nearby:
                        best_nearby = nearby
                        best_pos = p
                scored.append((weight, fname, ftext, best_pos))
            # Highest IDF-weighted relevance first -- see the "weight" comment above.
            scored.sort(key=lambda t: -t[0])
            for _, fname, ftext, idx in scored[:MAX_RELEVANT_FILES]:
                if fname in seen_files:
                    continue
                s = max(0, idx - PROXIMITY_WINDOW)
                e = min(len(ftext), idx + PROXIMITY_WINDOW)
                parts.append(f"[from {fname}]\n{ftext[s:e]}")
                seen_files.add(fname)

        # Strategy 4: numeric near-match (same order of magnitude), only if nothing else found.
        if not parts and value is not None and abs(value) > 100:
            # Look for any dollar amount within 2x of the claim's value.
            # This catches cases where the golden says $147,993 but the env
            # has $138,906 (same order of magnitude, different value).
            for m in re.finditer(r"\$?[\d,]+(?:\.\d+)?", env_text):
                raw = m.group(0)
                env_val = to_float(raw)
                if env_val is None or env_val < 100:
                    continue
                if 0.5 * value <= env_val <= 2.0 * value:
                    idx = m.start()
                    s = max(0, idx - PROXIMITY_WINDOW)
                    e = min(len(env_text), m.end() + PROXIMITY_WINDOW)
                    parts.append(env_text[s:e])
                    break

        # Combine and cap the excerpt. Cap raised from 3 to 8 (was tuned for the old
        # at-most-one-strategy-fires design; strategy 3 can now legitimately contribute up to
        # MAX_RELEVANT_FILES=8 parts on its own for a real cross-document case) -- and see
        # MAX_EXCERPT_CHARS's own comment: it was ALSO too small for this many parts and would
        # have silently truncated away exactly the lower-ranked-but-real file this fix targets.
        excerpt = "\n...\n".join(parts[:8])
        if len(excerpt) > MAX_EXCERPT_CHARS:
            excerpt = excerpt[:MAX_EXCERPT_CHARS] + "\n[... TRUNCATED ...]"
        excerpts.append(excerpt)

    return excerpts


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    task_id: str,
    instruction: str,
    claims: list[dict],
    env_excerpts: list[str],
) -> str:
    """Assemble the full user prompt. The golden claims and environment
    excerpts are embedded directly so the LLM has the full recipe."""
    # Build the claims section.
    claims_lines: list[str] = []
    for i, claim in enumerate(claims, 1):
        val = claim.get("value_raw", "?")
        ctx = claim.get("context", "")
        gfile = claim.get("source_file", "?")
        claims_lines.append(
            f"Claim {i}: {val}\n" f"  Context: {ctx}\n" f"  Golden file: {gfile}"
        )

    # Build the environment excerpts section.
    env_lines: list[str] = []
    total_env_chars = 0
    for i, (claim, excerpt) in enumerate(zip(claims, env_excerpts), 1):
        if not excerpt:
            continue
        env_lines.append(
            f"--- excerpts for claim {i} ({claim.get('value_raw', '?')}) ---"
        )
        env_lines.append(excerpt)
        total_env_chars += len(excerpt)
        if total_env_chars > MAX_ENV_EXCERPTS_CHARS:
            env_lines.append("[... remaining excerpts truncated to fit context ...]")
            break

    return f"""== TASK: {task_id} ==

== INSTRUCTION (instruction.md) ==
{instruction or "[no instruction.md found]"}

== GOLDEN LITERAL CLAIMS ==
The following are literal factual claims extracted from the golden answer.
Each claim is a specific figure (dollar amount, count, percentage, date) that
the golden presents as a fact or answer. For each claim, determine whether it
is GROUNDED IN the source document excerpts below (the golden's figure
matches what the source data actually supports) or UNGROUNDED (the golden
states a figure that does not match what the source data supports).

{chr(10).join(claims_lines) or "[no literal claims extracted from golden]"}

== RELEVANT SOURCE DOCUMENT EXCERPTS ==
The following are excerpts from the task's source documents that are relevant
to the golden claims above. These were found by searching for the claim values
and their context keywords in the source files. If no excerpt appears for a
claim, it means no relevant source data was found for that figure.

{chr(10).join(env_lines) or "[no source document excerpts found]"}

== WHAT TO CHECK ==
For each golden claim above, determine whether the figure is actually GROUNDED
IN / derivable from the source document excerpts. A figure is UNGROUNDED if:

1. The source data shows a DIFFERENT value for the same metric. Example: the
   golden says "$4,390 (FY2021 Returns & Refunds actual)" but Sales_Orders.xlsx
   sums Returns & Refunds rows to $2,390. The golden's figure does not match
   what the source data supports.

2. The figure is fabricated: no source data supports it at all, and it is not
   a reasonable computation from source data. Example: the golden states
   "$72,490 P5-trough lift" but no source document mentions this figure or
   anything that would produce it.

3. The figure double-counts or mislabels source data. Example: the golden
   counts continuation-line prices as separate orders, inflating the total;
   or mislabels 9,989 geography-attributable orders as 10,000 unique order
   names.

A figure is GROUNDED (do NOT flag) if:
1. The exact value appears in the source data.
2. The value is correctly derived from source data (e.g., a correct sum of
   rows, a correct count of records, a correct percentage computed from
   source figures).
3. The figure is a design choice or parameter the golden author set (e.g., a
   "5% discount rate" the instruction left to the solver), not a claim about
   what the source data says. These are not "ungrounded"; they are the
   golden's own modeling decisions.

== IMPORTANT: do NOT flag these ==
- A figure that is part of a derivation statement (e.g., "sum of X, Y, Z =
  $N"). Those are computation steps, not bare factual claims, and
  golden_arithmetic_check.py already verifies them. Focus on figures stated
  as facts/answers, not as computation steps.
- A figure that is clearly a parameter, assumption, or design choice the
  golden author made (e.g., a growth rate assumption, a threshold the
  instruction left open). These are not claims about source data.
- A figure where you cannot find contradicting source evidence. If the
  source excerpts do not show a different value, you cannot confirm the
  figure is ungrounded. Do not flag it.
- A year, date, or quarter label used as a filter (e.g., "FY2021", "Q2").
  These are time period selectors, not figures to verify.

== OUTPUT FORMAT (strict JSON, no prose before or after) ==
Return a single JSON object with this exact shape:
{{
  "verdict": "clean" or "defective",
  "findings": [
    {{
      "claim_value": "$147,993",
      "claim_context": "CA: 147993",
      "golden_file": "golden.xlsx",
      "source_file": "Sales_Orders.xlsx",
      "source_value": "$138,906",
      "evidence": "explain why this figure is ungrounded: what the source data actually shows vs what the golden claims"
    }}
  ]
}}

Rules:
- Output ONLY the JSON object. No markdown code fences, no prose, no explanation before or after.
- "verdict" is "clean" if zero findings, "defective" if one or more.
- Every finding MUST include "claim_value" (the golden's stated figure).
- Every finding MUST include "claim_context" (the surrounding text/label from the golden).
- Every finding MUST include "evidence" explaining what the source data shows vs what the golden claims.
- Include "source_file" and "source_value" when you can identify the specific source file and its value.
- If the golden text or source excerpts are empty, return {{"verdict": "clean", "findings": [], "content_unavailable": true, "unavailable_reason": "what was missing"}}.
- Do not invent defects. If you are not confident a figure is ungrounded, do not flag it.
"""


# ---------------------------------------------------------------------------
# Response parsing (same proven JSON-extraction logic Check A uses)
# ---------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    """Remove a single wrapping ``` or ```json fence pair if present. Leaves
    inner backticks untouched. Same logic Check A uses."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.split("\n")
    lines = lines[1:]
    while lines and lines[-1].strip() == "":
        lines.pop()
    if lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip()


def _balanced_object_at(text: str, start: int) -> str | None:
    """Track brace depth from start (which must be a '{') to find its match."""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _find_json_object(text: str) -> str | None:
    """Find a balanced {...} block in text that parses as JSON. Scans every
    '{' in order so prose containing an unrelated brace before the real JSON
    object does not shadow the actual payload."""
    first_balanced = None
    idx = text.find("{")
    while idx != -1:
        candidate = _balanced_object_at(text, idx)
        if candidate is not None:
            if first_balanced is None:
                first_balanced = candidate
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass
        idx = text.find("{", idx + 1)
    return first_balanced


def parse_llm_response(raw: str) -> dict:
    """Parse the LLM response into a dict. Never raises: a non-JSON response
    returns a dict with parse_error set and the raw text preserved."""
    if not raw or not raw.strip():
        return {"verdict": "error", "findings": [], "parse_error": "empty response"}

    cleaned = _strip_code_fences(raw)

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    blob = _find_json_object(cleaned)
    if blob is not None:
        try:
            data = json.loads(blob)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return {
        "verdict": "error",
        "findings": [],
        "parse_error": "response was not valid JSON",
        "raw_response": raw[:4000],
    }


def _normalize_finding(f: dict) -> dict | None:
    """Validate and normalize one finding dict from the LLM response. Returns
    None if the finding is too malformed to use (missing claim_value or
    evidence). The claim_value and evidence are the minimum required fields:
    without claim_value a reviewer cannot locate the golden figure, and
    without evidence a reviewer cannot understand why it is ungrounded."""
    if not isinstance(f, dict):
        return None
    claim_value = (f.get("claim_value") or "").strip()
    evidence = (f.get("evidence") or "").strip()
    if not claim_value or not evidence:
        return None
    claim_context = (f.get("claim_context") or "").strip()
    golden_file = (f.get("golden_file") or "").strip()
    source_file = (f.get("source_file") or "").strip()
    source_value = (f.get("source_value") or "").strip()
    message = f"[golden_ungrounded] {claim_value}"
    if source_file:
        message += f" (source: {source_file}"
        if source_value:
            message += f" = {source_value}"
        message += ")"
    return {
        "kind": "golden_ungrounded",
        "severity": "warn",
        "claim_value": claim_value[:500],
        "claim_context": claim_context[:2000],
        "golden_file": golden_file[:200],
        "source_file": source_file[:200],
        "source_value": source_value[:500],
        "evidence": evidence[:2000],
        "message": message[:500],
    }


def build_task_result_from_response(
    task_id: str,
    parsed: dict,
    fmt: str,
    n_golden_files: int,
    n_env_files: int,
    n_claims: int,
    parse_errors: list[str],
    extract_errors: list[str],
    backend_used: str,
    prompt_chars: int,
) -> dict:
    """Turn a parsed LLM response into the per-task result dict the orchestrator
    reads. Handles all three response shapes: clean, defective, and
    parse-error. Same structure Check A / rubric_overspecification_check.py uses."""
    result = {
        "task_id": task_id,
        "status": "pass",
        "task_format": fmt,
        "n_golden_files": n_golden_files,
        "n_env_files": n_env_files,
        "n_claims": n_claims,
        "parse_errors": parse_errors,
        "errors": extract_errors,
        "findings": [],
        "n_findings": 0,
        "n_warn": 0,
        "llm_backend": backend_used,
        "prompt_chars": prompt_chars,
        "content_unavailable": False,
    }

    verdict = parsed.get("verdict", "error")

    if "parse_error" in parsed or verdict == "error":
        result["status"] = "error"
        result["errors"].append(parsed.get("parse_error", "unknown parse error"))
        if "raw_response" in parsed:
            result["errors"].append(
                f"raw_response (truncated): {parsed['raw_response']}"
            )
        return result

    if parsed.get("content_unavailable"):
        result["status"] = "skip"
        result["content_unavailable"] = True
        result["errors"].append(parsed.get("unavailable_reason", "content unavailable"))
        return result

    raw_findings = parsed.get("findings", [])
    if not isinstance(raw_findings, list):
        raw_findings = []
    findings: list[dict] = []
    for f in raw_findings:
        nf = _normalize_finding(f)
        if nf is not None:
            findings.append(nf)

    result["findings"] = findings
    result["n_findings"] = len(findings)
    result["n_warn"] = len(findings)
    # Same "candidate, not verdict" posture as Check A: warn, never fail, even
    # if the LLM says "defective." A finding never hard-gates.
    result["status"] = "warn" if findings else "pass"

    # Same golden-extraction-failure guard Check A uses: if the golden text
    # extraction failed and the LLM did not self-report content_unavailable,
    # downgrade a "pass" to "warn" so a human reviewer sees the extraction
    # failure rather than a false-clean verdict.
    if extract_errors and result["status"] == "pass":
        result["status"] = "warn"
        result["errors"].append(
            "golden or environment text extraction failed for one or more files "
            "and the LLM did not report content_unavailable; treating as warn "
            "rather than a clean pass, since the audit may not have seen the real text"
        )
    return result


# ---------------------------------------------------------------------------
# Per-task audit
# ---------------------------------------------------------------------------


def read_instruction_md(task_dir: Path) -> str:
    """Read instruction.md. Returns empty string if absent."""
    p = task_dir / "instruction.md"
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def audit_task(task_dir: Path, dry_run: bool = False, timeout: int = 180) -> dict:
    """Audit one task for golden groundedness. Returns the per-task result
    dict. Never raises: every failure path (missing content, LLM error, parse
    error) produces a result dict with an error/skip status rather than
    crashing the batch."""
    task_id = task_dir.name
    fmt = _task_format(task_dir)
    golden_files = find_golden_files(task_dir, fmt)
    instruction = read_instruction_md(task_dir)

    # Content gate: if no golden files, nothing to check.
    if fmt == "none":
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_golden_files": 0,
            "n_env_files": 0,
            "n_claims": 0,
            "parse_errors": [],
            "errors": ["not a recognized task format (no judge.toml or verifier.json)"],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    if not golden_files:
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_golden_files": 0,
            "n_env_files": 0,
            "n_claims": 0,
            "parse_errors": [],
            "errors": ["no golden/solution files found; nothing to check"],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    # Extract golden text. For xlsx, also get label-value pairs.
    golden_text_parts: list[str] = []
    golden_value_maps: list[dict[str, float]] = []
    golden_file_names: list[str] = []
    extract_errors: list[str] = []

    for gf in golden_files:
        suffix = gf.suffix.lower()
        golden_file_names.append(gf.name)
        if suffix in (".xlsx", ".xlsm"):
            text, pairs = read_xlsx_all_text_with_values(gf)
            golden_text_parts.append(text)
            golden_value_maps.append(pairs)
        else:
            text, err = extract_file_text(gf)
            if err and not text:
                extract_errors.append(f"{gf.name}: {err}")
                continue
            golden_text_parts.append(text)

    golden_text = "\n".join(golden_text_parts)
    if not golden_text.strip():
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_golden_files": len(golden_files),
            "n_env_files": 0,
            "n_claims": 0,
            "parse_errors": [],
            "errors": ["no golden files produced extractable text"] + extract_errors,
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    # Extract golden literal claims.
    claims = extract_golden_claims(golden_text, golden_value_maps, golden_file_names)
    n_claims = len(claims)

    if n_claims == 0:
        # No literal claims found: the golden has no figures to verify against
        # source data. Not a finding, not a gap, just not-applicable.
        return {
            "task_id": task_id,
            "status": "pass",
            "task_format": fmt,
            "n_golden_files": len(golden_files),
            "n_env_files": 0,
            "n_claims": 0,
            "parse_errors": [],
            "errors": extract_errors,
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": False,
        }

    # Read environment files.
    env_files = find_environment_files(task_dir)

    if not env_files:
        # No environment files: cannot verify groundedness. Skip with a clear
        # reason rather than making an LLM call with no source data.
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_golden_files": len(golden_files),
            "n_env_files": 0,
            "n_claims": n_claims,
            "parse_errors": [],
            "errors": [
                "no environment/source files found; cannot verify golden "
                "groundedness without source data to check against"
            ],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    # Check environment size BEFORE reading file contents. Reading 400+ xlsx
    # files with openpyxl takes 30+ seconds; this guard skips the slow read
    # entirely when the environment is too large to handle.
    total_env_bytes = sum(_safe_stat_size(ef) for ef in env_files)
    if len(env_files) > ENV_TOO_MANY_FILES or total_env_bytes > ENV_TOO_LARGE_BYTES:
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_golden_files": len(golden_files),
            "n_env_files": len(env_files),
            "n_claims": n_claims,
            "parse_errors": [],
            "errors": [
                f"environment too large ({total_env_bytes / 1_000_000:.1f} MB "
                f"across {len(env_files)} files; limits: "
                f"{ENV_TOO_LARGE_BYTES / 1_000_000:.0f} MB / "
                f"{ENV_TOO_MANY_FILES} files); skipping groundedness check "
                f"to avoid context-limit and performance issues"
            ],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    # Build environment text and value maps (now safe: env is small enough).
    env_text, env_value_maps, env_file_names, _, env_per_file_texts = build_env_text(
        env_files
    )
    env_merged_map = _merge_env_value_maps(env_value_maps)

    # Find relevant environment excerpts for each claim.
    env_excerpts = find_env_excerpts(
        claims, env_text, env_merged_map, env_per_file_texts
    )

    # Build the prompt.
    prompt = build_prompt(task_id, instruction, claims, env_excerpts)
    prompt_chars = len(prompt)

    # Dry-run: build the prompt, optionally show the HTTP request shape, but
    # never make a real LLM call.
    if dry_run:
        result: dict = {
            "task_id": task_id,
            "status": "pass",
            "task_format": fmt,
            "n_golden_files": len(golden_files),
            "n_env_files": len(env_files),
            "n_claims": n_claims,
            "parse_errors": [],
            "errors": extract_errors,
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "dry_run",
            "prompt_chars": prompt_chars,
            "content_unavailable": False,
        }
        http_env = all(
            os.environ.get(v)
            for v in (
                "LLM_API_KEY",
                "LLM_API_BASE_URL",
                "LLM_API_PROVIDER",
                "LLM_API_MODEL",
            )
        )
        if http_env:
            try:
                method, url, headers, body = build_http_request(prompt, SYSTEM_PROMPT)
                masked = dict(headers)
                for h in ("x-api-key", "authorization"):
                    if h in masked:
                        masked[h] = "<redacted>"
                result["dry_run_http_request"] = {
                    "method": method,
                    "url": url,
                    "headers": masked,
                    "body_chars": len(json.dumps(body)),
                    "model": body.get("model"),
                    "max_tokens": body.get("max_tokens"),
                }
            except LLMBackendError as exc:
                result["dry_run_http_request"] = {"error": str(exc)}
        else:
            result["dry_run_http_request"] = {
                "note": (
                    "LLM_API_KEY / LLM_API_BASE_URL / LLM_API_PROVIDER / "
                    "LLM_API_MODEL not set; set them (even with dummy values) "
                    "to see the exact HTTP request shape. The prompt itself is "
                    "in the 'dry_run_prompt' field."
                )
            }
        result["dry_run_prompt"] = prompt
        return result

    # Real call: try the LLM backend.
    try:
        raw_response = call_llm(prompt, SYSTEM_PROMPT, timeout=timeout)
        backend_used = "cli_or_http"
    except LLMBackendError as exc:
        return {
            "task_id": task_id,
            "status": "error",
            "task_format": fmt,
            "n_golden_files": len(golden_files),
            "n_env_files": len(env_files),
            "n_claims": n_claims,
            "parse_errors": [],
            "errors": [f"LLM backend error: {exc}"],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": prompt_chars,
            "content_unavailable": False,
        }

    parsed = parse_llm_response(raw_response)
    return build_task_result_from_response(
        task_id,
        parsed,
        fmt,
        len(golden_files),
        len(env_files),
        n_claims,
        [],
        extract_errors,
        backend_used,
        prompt_chars,
    )


# ---------------------------------------------------------------------------
# Batch entry point (programmatic, used by the orchestrators)
# ---------------------------------------------------------------------------


def find_task_dirs(
    root: Path, task_ids: list[str] | None = None, id_prefix: str = ""
) -> list[Path]:
    if task_ids:
        dirs: list[Path] = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def run(
    root: Path,
    task_ids: list[str] | None = None,
    id_prefix: str = "",
    out_dir: Path | None = None,
    jobs: int = 1,
    dry_run: bool = False,
    timeout: int = 180,
) -> dict:
    """Programmatic entry point (the orchestrators use this). Returns the
    report dict with a 'results' list of per-task dicts. Tasks run on a
    thread pool since each LLM call is I/O-bound (network or subprocess).
    Same structure Check A / rubric_overspecification_check.py uses."""
    dirs = find_task_dirs(root, task_ids, id_prefix)
    t0 = time.time()

    from concurrent.futures import ThreadPoolExecutor

    def _safe_audit_task(d: Path) -> dict:
        """Wraps audit_task so one task's unexpected exception produces an
        error result for that task instead of losing every other task's
        results. Same backstop Check A uses."""
        try:
            return audit_task(d, dry_run=dry_run, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - deliberately broad
            return {
                "task_id": d.name,
                "status": "error",
                "task_format": "none",
                "n_golden_files": 0,
                "n_env_files": 0,
                "n_claims": 0,
                "parse_errors": [],
                "errors": [f"unexpected exception in audit_task: {exc!r}"],
                "findings": [],
                "n_findings": 0,
                "n_warn": 0,
                "llm_backend": "none",
                "prompt_chars": 0,
                "content_unavailable": True,
            }

    workers = max(1, jobs)
    results: list[dict] = []
    if workers == 1:
        for d in dirs:
            r = _safe_audit_task(d)
            results.append(r)
            _log_task(r)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_safe_audit_task, d) for d in dirs]
            for fut in futures:
                r = fut.result()
                results.append(r)
                _log_task(r)

    n_pass = sum(r["status"] == "pass" for r in results)
    n_warn = sum(r["status"] == "warn" for r in results)
    n_fail = sum(r["status"] == "fail" for r in results)
    n_skip = sum(r["status"] == "skip" for r in results)
    n_error = sum(r["status"] == "error" for r in results)

    report = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": str(root),
        "dry_run": dry_run,
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_warn": n_warn,
        "n_fail": n_fail,
        "n_skip": n_skip,
        "n_error": n_error,
        "results": results,
        "seconds": round(time.time() - t0, 1),
    }

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "golden_groundedness.json"
        out_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return report


def _log_task(r: dict) -> None:
    status = r["status"]
    tid = r["task_id"]
    n = r["n_findings"]
    if status == "error":
        err = (r.get("errors") or [""])[0][:120]
        print(f"  ERROR {tid:<18} {err}", file=sys.stderr)
    elif status == "skip":
        err = (r.get("errors") or [""])[0][:120]
        print(f"  SKIP  {tid:<18} {err}", file=sys.stderr)
    elif status == "warn":
        first = (r.get("findings") or [{}])[0]
        msg = first.get("message", "?")[:120]
        print(f"  WARN  {tid:<18} {n} finding(s): {msg}", file=sys.stderr)
    else:
        n_claims = r.get("n_claims", 0)
        print(
            f"  OK    {tid:<18} clean ({n_claims} claim(s) checked)",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("task_ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument(
        "--root",
        required=True,
        help="task package root, one task directory per task",
    )
    ap.add_argument("--out", help="write the full result set here as JSON")
    ap.add_argument("--id-prefix", default="")
    ap.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="concurrent tasks (each makes one LLM call; default: serial)",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="seconds per LLM call (passed to the backend)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "build the prompt and show the HTTP request shape (if LLM_API_* "
            "env vars are set) without making a real LLM call. No real "
            "credential is needed; dummy env values are sufficient to see "
            "the request shape."
        ),
    )
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2
    if not args.all and not args.task_ids:
        sys.stderr.write("give task ids or --all\n")
        return 2

    task_ids = args.task_ids or None
    report = run(
        root,
        task_ids,
        args.id_prefix,
        out_dir=Path(args.out).parent if args.out else None,
        jobs=args.jobs,
        dry_run=args.dry_run,
        timeout=args.timeout,
    )

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {args.out}")

    print(
        f"\n{report['n_tasks']} tasks in {report['seconds']}s: "
        f"{report['n_pass']} pass, {report['n_warn']} warn, "
        f"{report['n_skip']} skip, {report['n_error']} error",
        file=sys.stderr,
    )
    return 1 if report["n_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
