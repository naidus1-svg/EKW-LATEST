#!/usr/bin/env python3
"""Fabricated unfiled-named-fact check: does the golden solution state, as an
established fact, a specific checkable-sounding claim (a named vendor/system/bank,
a PO/invoice/document number, a named internal process, a specific figure
attributed to a named document) that has NO corresponding file in the task's real
environment AND is NOT transparently flagged by the golden itself as open or
unverified?

Why this exists
----------------
Tracker row 35 (round 62). A golden solution can fabricate a specific factual
claim as prose with no filename attached to cite. This is NARROWER and distinct
from row 8's `source_citation_existence_check.py`, which requires a filename or
path-shaped token to key on:

  - source_citation_existence sub-case A: a golden CELL cites a file-PATH-shaped
    string (ends in a recognized extension) absent from the environment. It
    needs a `word.ext` or `dir/file.ext` token to extract.
  - source_citation_existence sub-case B: instruction.md names a file by
    CATEGORY (a category word like "report" preceded by a proper noun). It
    needs a proper-noun-plus-category-word pair to key on.

When the golden fabricates a claim as plain prose with NO filename token and NO
category-plus-proper-noun pair, BOTH sub-cases of row 8 structurally cannot
catch it. There is no regex for "sounds suspiciously specific and
unverifiable" (round 60's own dispatch said so explicitly). That gap is what
this check closes, by handing the judgment to an LLM.

The three independently confirmed real instances this was built against (all
verified against the real task files in this repo's corpus, not a mirror):

  - SVC-PC-21-0-0: the golden invents a "Close Authority and Review Map" process,
    names "Mercury / SVB" as bank systems with a recorded admin owner, and cites
    a "Licence inventory" record, all as established facts, all by category or
    system name only, never a filename. No file named Mercury, Close Authority,
    Review Map, or Licence inventory exists in the 318-file environment. (SVB
    has svb_statement.csv/.ofx, but Mercury has nothing, and the named
    internal process and licence inventory have nothing.)
  - SVC-PC-24-6-0: the golden states "GOTS organic, OEKO-TEX, CertiPUR-US" and
    "certs on file" as established facts under the "NovaTex QSA". No file
    anywhere in the 306-file environment contains those cert names; the only
    "cert" file is Certificate_of_Incorporation.pdf (a corporate filing, not a
    product certification), and the golden abbreviates the one real nearby file
    as "QSA", which does not filename-match.
  - SVC-PC-73-3-0: the golden states a "$4-5M for FY2022" board-approved range
    as an established fact, citing "Jan 18 2022 board minutes" by description.
    The environment has NO board-minutes file at all (only Board_Talking_Points
    and Q1/Q3/Q4_Board_Deck files, which are decks, not minutes), so neither a
    matching nor a clearly-related filename exists.

The one named TRUE NEGATIVE this must NOT flag:

  - SVC-PC-52-5-0: the golden cites "Processor annual summary, totals row" for a
    receipts figure. This was independently judged NOT an instance of this
    pattern because the golden transparently flags the reading as an OPEN,
    UNRESOLVED issue ("Open item, rows 17 and 18", "Difference unresolved",
    "Carried open", "A remittance trace or corrected processor statement would
    close it") rather than asserting it as settled fact. This check's exclusion
    (b) below encodes exactly that distinction: do NOT flag transparent
    uncertainty the same way as confident fabrication.

What it does, per task:
  1. Extract the golden solution's readable text (reuse find_golden_files +
     extract_file_text from answer_key_rubric_leak_check.py, the same path every
     other check in this folder uses).
  2. Build a REAL environment file listing: resolve the environment directory
     (SVC-PC: environment/initial_workspace/, EKW: environment/data/, same
     dispatch answer_key_content_leak_check.py uses) and walk it RECURSIVELY,
     collecting EVERY file of EVERY extension (PDFs included), as relative
     paths from the environment root. This is ground truth, not a hint. The
     prompt task brief warned that a mirror's file_listing.txt was found to
     OMIT an entire real subdirectory, so file_listing.txt is treated as a hint
     to merge in if present, never as the only source. The real corpus carries
     no file_listing.txt at all; the recursive walk is the source of truth.
  3. Hand the LLM the golden text plus the real environment file listing, and
     ask it to identify any specific, checkable-sounding factual claim that the
     golden states as an established fact, where NEITHER:
       (a) a corresponding file with a matching or clearly-related name exists
           in the environment file listing, OR
       (b) the golden itself explicitly flags the claim as an open item /
           unverified / unresolved / a judgment call / a working assumption to
           be confirmed.
  4. Warn-only, never fail. Same "candidate, not verdict" posture as every
     other LLM-based check in this project (content-audit/SKILL.md,
     rubric_overspecification, golden_groundedness).

Scope boundary vs source_citation_existence_check.py (row 8)
-------------------------------------------------------------
This check is the COMPLEMENT of row 8, not an overlapping reimplementation. Row
8 catches a golden claim that NAMES a file (by path or by category-plus-proper-
noun). This check catches a golden claim that names a FACT (a vendor, a number,
a process) as prose with NO file name to key on. The two do not overlap: a claim
that cites a filename is row 8's job; a claim that asserts a fact with no
filename is this check's job. The LLM prompt says so explicitly so the model
does not re-flag what row 8 already catches.

LLM backend
-----------
Uses tools/llm_backend.call_llm() which tries the Claude Code CLI first (free
under a Max plan, no credential handling here) then a caller-configured HTTP
backend. Same backend as rubric_overspecification_check.py and
golden_groundedness_check.py. LLM_API_MAX_TOKENS is set to 32000 near the
imports (setdefault, not a hard override) for the same reason those two checks
set it: the configured reasoning model (glm-5.2) spends hidden reasoning tokens
against the same max_tokens ceiling the visible answer draws from, and the
library default of 4096 starves it before any visible answer is written
(confirmed real, tracker row 15). Pass --dry-run to build the prompt without a
real call.

Output shape
------------
Per-task result dict (the same verdict + findings shape every other check in
this folder produces, so it merges into svc_run_checks.py / ekw_run_checks.py
the same way):

    {
        "task_id": "SVC-PC-21-0-0",
        "status": "pass" | "warn" | "skip" | "error",
        "task_format": "svc_pc" | "ekw" | "none",
        "n_golden_files": 3,
        "n_env_files": 318,
        "parse_errors": [],
        "errors": [],
        "findings": [
            {
                "kind": "fabricated_unfilenamed_fact",
                "severity": "warn",
                "claim": "Close Authority and Review Map",
                "claim_context": "the surrounding golden sentence",
                "golden_file": "Authority_Risk_Register_and_Remediation.xlsx",
                "matched_env_file": "",
                "evidence": "why no corresponding file exists and the claim is stated as fact"
            }
        ],
        "n_findings": 0,
        "n_warn": 0,
        "llm_backend": "cli" | "http" | "dry_run" | "none",
        "prompt_chars": 12345,
        "content_unavailable": false
    }

CLI
---
    python fabricated_unfilenamed_fact_check.py --all --root DIR --out results.json
    python fabricated_unfilenamed_fact_check.py SVC-PC-21-0-0 --root DIR --out results.json
    python fabricated_unfilenamed_fact_check.py SVC-PC-21-0-0 --root DIR --out results.json --dry-run
    python fabricated_unfilenamed_fact_check.py SVC-PC-21-0-0 --root DIR --out results.json --timeout 300

Stdlib only for the runner; openpyxl / python-docx are pulled in by the
text-extraction imports (same as every other check in this folder).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Row-15 token-budget fix (commit f0d1105), applied by rubric_overspecification
# and golden_groundedness too: the configured reasoning backend (glm-5.2)
# spends hidden reasoning tokens against the same max_tokens ceiling the visible
# answer draws from, so the library default of 4096 starves it before any
# visible answer is written on a real audit-sized prompt. 32000 is verified
# working for both sibling LLM checks. setdefault, not a hard override, so an
# operator's own explicit budget is never silently replaced.
os.environ.setdefault("LLM_API_MAX_TOKENS", "32000")

from tools.llm_backend import call_llm, build_http_request, LLMBackendError

# Reuse the golden-file discovery and text extraction from
# answer_key_rubric_leak_check.py (the same calibrated path every other check
# in this folder uses). find_golden_files knows the SVC-PC (solution/files/)
# and EKW (solution/golden_outputs/) golden directories and the supported
# extensions; extract_file_text dispatches on suffix (xlsx/docx/pptx/txt/...).
from answer_key_rubric_leak_check import (
    extract_file_text,
    find_golden_files,
    _task_format,
)

# Windows console defaults to cp1252; force UTF-8 so non-cp1252 characters in
# real golden text never crash a batch run. Same line every other check in
# this folder carries.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cap the golden text section so a very large workbook does not blow the LLM
# context window when combined with the environment file listing. Same cap
# rubric_overspecification_check.py uses; truncation is marked visibly.
MAX_GOLDEN_CHARS = 60000

# Cap the environment file listing section. A listing of ~600 files at one
# relative path per line is well under this; if a task ships more, the listing
# is truncated with a visible marker so the LLM knows it is seeing a partial
# listing. The recursive walk still counts every file for the n_env_files
# field, so the count is always complete even if the visible listing is capped.
MAX_LISTING_CHARS = 40000

# Skip a task whose environment is too large to walk in reasonable time, with a
# clear reason rather than a multi-minute stall. 200 files / 50 MB matches
# golden_groundedness_check.py's own guard (ENV_TOO_MANY_FILES /
# ENV_TOO_LARGE_BYTES), calibrated against the real corpus where the largest
# tasks carry 300-400 files. A task past this is rare and better skipped than
# stalled.
ENV_TOO_MANY_FILES = 400
ENV_TOO_LARGE_BYTES = 80 * 1000 * 1000


SYSTEM_PROMPT = (
    "You are a QC auditor for Harbor-shaped grading tasks. You read the golden "
    "answer's prose and the task's REAL environment file listing, and you "
    "identify any specific, checkable-sounding factual claim the golden states "
    "as an ESTABLISHED FACT where NO corresponding source file exists and the "
    "golden does NOT itself flag the claim as open or unverified. You report "
    "findings as strict JSON. You do not fix, rewrite, or suggest fixes. You "
    "only flag a claim you can quote the golden text for AND name the specific "
    "fact it asserts AND state why no environment file corresponds. Every "
    "finding is reviewed by a human before any action, so a candidate flag is "
    "far cheaper than a missed fabrication that ships to graders. Flag any "
    "claim you can support with the evidence below; do not suppress a flag "
    "merely because you are less than fully certain, as long as you can name "
    "the claim, quote the golden, and state why no file corresponds."
)


# ---------------------------------------------------------------------------
# Environment file listing (ground truth, not a hint)
# ---------------------------------------------------------------------------


def _resolve_env_dir(task_dir: Path, fmt: str) -> Path:
    """Same dispatch answer_key_content_leak_check.find_environment_files uses:
    SVC-PC (and any task matching neither format) reads environment/
    initial_workspace/, EKW reads environment/data/. Returns the directory path
    whether or not it exists; the caller checks is_dir()."""
    if fmt == "ekw":
        return task_dir / "environment" / "data"
    return task_dir / "environment" / "initial_workspace"


def _walk_all_files(env_dir: Path) -> list[str]:
    """Recursive relative-path listing of EVERY file under env_dir, all
    extensions (PDF, xlsx, docx, csv, txt, everything). Returns sorted relative
    paths from env_dir. This is ground truth: the prompt task brief warned that
    a mirror's file_listing.txt was found to OMIT an entire real subdirectory,
    so the real recursive walk is the source of truth, not any pre-built
    listing file. Never raises."""
    files: list[str] = []
    if not env_dir.is_dir():
        return files
    for root, _dirs, names in os.walk(env_dir):
        for name in names:
            full = os.path.join(root, name)
            try:
                rel = os.path.relpath(full, env_dir)
            except ValueError:
                rel = name
            files.append(rel)
    files.sort()
    return files


def _total_env_bytes(env_dir: Path) -> int:
    """Sum of file sizes under env_dir, or 0. Best-effort, never raises."""
    total = 0
    if not env_dir.is_dir():
        return total
    for root, _dirs, names in os.walk(env_dir):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _read_file_listing_hint(task_dir: Path) -> str:
    """If a file_listing.txt (any case) exists anywhere under the task dir, read
    it as a HINT to merge into the listing. The real corpus carries none; this
    only matters if a task or a mirror ships one. Treated as a hint only, never
    as ground truth (the recursive walk is ground truth). Returns the text or
    empty string. Never raises."""
    for candidate in task_dir.rglob("file_listing*"):
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
    return ""


def build_env_listing(env_dir: Path, task_dir: Path) -> tuple[str, int, int]:
    """Build the environment file-listing text for the prompt. Returns
    (listing_text, n_files, total_bytes). listing_text is one relative path per
    line, capped at MAX_LISTING_CHARS with a visible marker if truncated.
    Includes a file_listing.txt hint section if one exists (clearly labelled as
    a hint, not ground truth). Never raises."""
    files = _walk_all_files(env_dir)
    n_files = len(files)
    total_bytes = _total_env_bytes(env_dir)

    lines = [f"--- real environment file listing ({n_files} files, recursive "
             f"walk of {env_dir.name}) ---"]
    body = "\n".join(files)
    if len(body) > MAX_LISTING_CHARS:
        body = body[:MAX_LISTING_CHARS] + "\n[... listing truncated ...]"
    lines.append(body)

    hint = _read_file_listing_hint(task_dir)
    if hint.strip():
        h = hint.strip()
        if len(h) > MAX_LISTING_CHARS // 2:
            h = h[: MAX_LISTING_CHARS // 2] + "\n[... hint truncated ...]"
        lines.append(
            "--- file_listing.txt hint (a pre-built listing, merged for "
            "completeness; the recursive walk above is ground truth) ---"
        )
        lines.append(h)

    return "\n".join(lines), n_files, total_bytes


# ---------------------------------------------------------------------------
# Golden text extraction (same helpers every other check uses)
# ---------------------------------------------------------------------------


def collect_golden_text(task_dir: Path, fmt: str) -> tuple[str, list[str]]:
    """Extract readable text from every supported golden file under the task's
    solution directory. Returns (combined_text, errors). Each file's text is
    prefixed with a '--- file: <name> ---' marker so the LLM can cite which
    file a finding comes from. Capped at MAX_GOLDEN_CHARS with a visible marker.
    Never raises: an unparseable file contributes an error string and no text."""
    golden_files = find_golden_files(task_dir, fmt)
    parts: list[str] = []
    errors: list[str] = []
    total_chars = 0
    for gf in golden_files:
        text, err = extract_file_text(gf)
        if err:
            errors.append(f"{gf.name}: {err}")
            continue
        if not text.strip():
            errors.append(f"{gf.name}: empty extract")
            continue
        chunk = f"--- file: {gf.name} ---\n{text}\n"
        if total_chars + len(chunk) > MAX_GOLDEN_CHARS:
            remaining = MAX_GOLDEN_CHARS - total_chars
            if remaining > 200:
                chunk = chunk[:remaining] + "\n[... TRUNCATED ...]\n"
                parts.append(chunk)
                total_chars += len(chunk)
            errors.append(
                f"golden text truncated at {MAX_GOLDEN_CHARS} chars "
                f"(after {gf.name})"
            )
            break
        parts.append(chunk)
        total_chars += len(chunk)
    return "".join(parts), errors


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    task_id: str,
    golden_text: str,
    env_listing: str,
    n_env_files: int,
) -> str:
    """Assemble the full user prompt. The defect definition, the two exclusion
    conditions, the transparent-uncertainty exclusion, the clearly-related
    precision lever, and the scope boundary vs row 8 are all embedded directly
    so the LLM has the full recipe without needing any external doc."""
    return f"""== TASK: {task_id} ==

== GOLDEN ANSWER (extracted from solution files; the solver's deliverable) ==
{golden_text or "[no golden files found or all unreadable]"}

== ENVIRONMENT FILE LISTING (the real files the solver was given; {n_env_files} files) ==
{env_listing or "[no environment directory found]"}

== WHAT TO CHECK ==
Identify any specific, checkable-sounding FACTUAL CLAIM the golden states as
an ESTABLISHED FACT, where NEITHER of the two conditions below is met:

  (a) a corresponding file with a matching or clearly-related name exists in
      the environment file listing above, OR
  (b) the golden itself explicitly flags the claim, OR the conclusion /
      reading that rests on the claim, as an open item, unverified,
      unresolved, a judgment call, a working assumption, or otherwise to be
      confirmed. Look anywhere in the golden text for this flag, not only in
      the sentence right next to the claim: a claim whose downstream use the
      golden marks "open", "unresolved", "carried open", or "to be confirmed"
      is NOT asserted as settled fact, even if the claim's own sentence reads
      confidently.

A "specific, checkable-sounding factual claim" means one of:
  - a named vendor, system, bank, or service (e.g. "Mercury", "SVB", "NovaTex")
    asserted as real and in use;
  - a PO number, invoice number, document number, or other identifier asserted
    as a real record;
  - a named internal process, register, or map (e.g. "Close Authority and
    Review Map", "Licence inventory") asserted as an established artifact;
  - a specific dollar figure, range, or count attributed to a named document
    (e.g. "$4-5M range per the Jan 18 2022 board minutes") asserted as settled
    fact.

The claim must be stated as an ESTABLISHED FACT. Do NOT flag a claim the golden
itself presents as uncertain. Transparent uncertainty is NOT fabrication. If
the golden's own words mark the claim as an open item, unresolved, carried
open, to be confirmed, a working assumption, "we have not verified", or a
judgment call, condition (b) is met and you MUST NOT flag it.

What counts as "stated as an established fact": the golden's own sourcing or
holding language is a factual assertion, even inside an audit or review
deliverable, and even next to a quoted customer-facing claim. Phrases like
"certs on file", "held under the [X]", "on file", "per the [document]", "the
recorded [X]", "the [X] register", or listing a document in a "Sources" line
are the golden asserting that the named file or record exists. If the golden
quotes a customer-facing product claim ("GOTS organic - OEKO-TEX - CertiPUR-US")
and adds its own annotation ("certs on file"), the annotation is the golden's
factual assertion and IS in scope: flag it when no corresponding file exists
and the annotation is not itself flagged as open.

== SPECIFICITY (what is in scope vs a generic category reference) ==
This check targets SPECIFIC named claims, not bare generic document-category
references. Do NOT flag a claim that names ONLY a generic, standard category of
business document or arrangement (for example "the merchant agreement", "the
lease", "the employment contract", "the rate card", "the purchase order") with
NO specific vendor name, NO specific invented title, NO specific date, and NO
specific identifier. A generic category reference is a standard business
artifact a real company routinely has; it is row 8's territory (category-plus-
proper-noun), not this check's. The fabrication pattern this check targets is
SPECIFIC: a specific named vendor/system/bank (e.g. "Mercury", "NovaTex"); a
specific invented process, register, or map name (e.g. "Close Authority and
Review Map", "Licence inventory"); a specific document by date or title (e.g.
"Jan 18 2022 board minutes", "NovaTex MSA", "Schedule A"); a specific
certification or identifier (e.g. "GOTS organic", "OEKO-TEX", "INC-2021-014").
Flag specific named claims; do not flag bare generic document-category
references like "the merchant agreement".

== THE "CLEARLY-RELATED" RULE (precision lever) ==
A file counts as "corresponding" under condition (a) ONLY IF its name
plausibly identifies it as the source for THAT SPECIFIC claim. A file that
merely shares a generic word root does NOT count:
  - "Certificate_of_Incorporation.pdf" does NOT back a claim about "GOTS
    organic / OEKO-TEX / CertiPUR-US product certifications" (a corporate
    filing is not a product certification).
  - "Q4_Board_Deck_Draft.pptx" or "Board_Talking_Points_Q1.docx" do NOT back a
    claim citing "board minutes" (a deck or talking points is not minutes).
  - "svb_statement.csv" backs an "SVB" bank claim but does NOT back a
    "Mercury" bank claim (a different bank system with no file at all).
When the claim names a document by DESCRIPTION (e.g. "Jan 18 2022 board
minutes") rather than by filename, look for a file whose name clearly
corresponds to that described document. If no file's name clearly corresponds,
condition (a) is not met.

== SCOPE (do not re-flag what row 8 already catches) ==
This check is the COMPLEMENT of source_citation_existence_check (row 8). Do
NOT flag a claim that cites an actual FILENAME (a `word.ext` or `path/file.ext`
token) or that names a file by category-plus-proper-noun; row 8 owns those.
This check targets claims stated as PROSE FACTS with NO filename token to key
on. If the golden's claim already names a file by a recognizable filename,
leave it to row 8.

== METHODOLOGY (follow every step; do not skip the enumeration) ==
  1. SCAN the GOLDEN ANSWER in full and LIST every specific factual claim it
     states as an established fact. Your worklist MUST include every: named
     vendor, system, bank, or service; PO/invoice/document number or other
     identifier; named internal process, register, or map; and specific figure,
     range, or count attributed to a named document. This enumeration is
     mandatory: a claim you never list is a claim you never check.
  2. For EACH item in your worklist, scan the ENVIRONMENT FILE LISTING for a
     file whose name matches or CLEARLY corresponds to the claim's named
     source. Apply the clearly-related rule above strictly: do not accept a
     generic word-root match (a budget file is not board minutes; a deck is
     not minutes; an incorporation certificate is not a product certification;
     an SVB statement does not back a Mercury claim).
  3. If NO corresponding file exists for the item, check whether the golden
     flags the item OR the conclusion that rests on the item as open,
     unverified, unresolved, or a judgment call ANYWHERE in the golden text
     (not only in the item's own sentence). If it does, do NOT flag that item
     (condition b is met).
  4. Flag the item ONLY if BOTH hold: (i) no corresponding file exists AND
     (ii) the golden asserts the item as settled fact with no transparent-
     uncertainty flag in the item's own surrounding text.
  5. Work the whole worklist. Do not stop after the first clean item. A
     short golden can still carry several fabricated claims.
  6. For each finding, record the verbatim claim, its surrounding golden
     context, which golden file it came from, the closest environment file you
     considered (or "none" if none was even a candidate), and your evidence
     explaining why no file corresponds and the claim is stated as fact.

== OUTPUT FORMAT (strict JSON, no prose before or after) ==
Return a single JSON object with this exact shape:
{{
  "verdict": "clean" or "defective",
  "findings": [
    {{
      "severity": "warn",
      "claim": "the specific factual claim the golden states as fact (verbatim or close paraphrase)",
      "claim_context": "the surrounding sentence or clause from the golden",
      "golden_file": "the golden file name the claim came from",
      "matched_env_file": "the closest environment file considered, or empty string if none",
      "evidence": "why no environment file corresponds to the claim AND the golden asserts it as settled fact (not transparently flagged as open)"
    }}
  ]
}}

Rules:
  - Output ONLY the JSON object. No markdown code fences, no prose, no
    explanation before or after.
  - "verdict" is "clean" if zero findings, "defective" if one or more.
  - "severity" is always "warn".
  - Every finding MUST include a "claim" naming the specific fact asserted.
  - Every finding MUST include "claim_context" quoting the golden text.
  - Every finding MUST include "evidence" explaining both halves: no
    corresponding file, and stated as settled fact (not open/unverified).
  - If the golden or environment text is empty or unreadable, return
    {{"verdict": "clean", "findings": [], "content_unavailable": true,
    "unavailable_reason": "what was missing"}}.
  - Do not invent defects. If you are not confident a claim is both unsupported
    by any file AND asserted as settled fact, do not flag it.
"""


# ---------------------------------------------------------------------------
# Response parsing (same proven JSON-extraction logic the sibling checks use)
# ---------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    """Remove a single wrapping ``` or ```json fence pair if present. Leaves
    inner backticks untouched. Same logic rubric_overspecification_check.py
    uses."""
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
    """Track brace depth from `start` (which must be a '{') to find its match.
    Returns the substring or None if the braces never balance."""
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
    """Find a balanced {...} block in text that parses as JSON. Scans every '{'
    in order so prose containing an unrelated brace before the real JSON object
    does not shadow the actual payload. Returns the first candidate that parses
    successfully, or the first balanced-but-unparseable candidate if none
    parse."""
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
    """Parse the LLM response into a dict with keys: verdict, findings,
    content_unavailable (optional), unavailable_reason (optional),
    parse_error (set when parsing failed). Never raises."""
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
    None if the finding is too malformed to use (missing claim). Keeps findings
    with a missing/weak evidence by defaulting to empty rather than dropping,
    since the claim is the load-bearing field a reviewer needs."""
    if not isinstance(f, dict):
        return None
    claim = (f.get("claim") or "").strip()
    if not claim:
        return None
    context = (f.get("claim_context") or "").strip()
    golden_file = (f.get("golden_file") or "").strip()
    matched = (f.get("matched_env_file") or "").strip()
    evidence = (f.get("evidence") or "").strip()
    message = f"[fabricated_unfilenamed_fact] {claim}"
    return {
        "kind": "fabricated_unfilenamed_fact",
        "severity": "warn",
        "claim": claim[:500],
        "claim_context": context[:2000],
        "golden_file": golden_file[:200],
        "matched_env_file": matched[:200],
        "evidence": evidence[:2000],
        "message": message[:500],
    }


def build_task_result_from_response(
    task_id: str,
    parsed: dict,
    fmt: str,
    n_golden_files: int,
    n_env_files: int,
    parse_errors: list[str],
    extract_errors: list[str],
    backend_used: str,
    prompt_chars: int,
) -> dict:
    """Turn a parsed LLM response into the per-task result dict the
    orchestrator reads. Handles all three response shapes: clean, defective,
    and parse-error. Same structure the sibling checks use."""
    result = {
        "task_id": task_id,
        "status": "pass",
        "task_format": fmt,
        "n_golden_files": n_golden_files,
        "n_env_files": n_env_files,
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
    # Same "candidate, not verdict" posture as every LLM check: warn, never
    # fail, even if the LLM says "defective." A finding never hard-gates.
    result["status"] = "warn" if findings else "pass"

    # Same golden-extraction-failure guard the sibling checks use: if the
    # golden text extraction failed and the LLM did not self-report
    # content_unavailable, downgrade a "pass" to "warn" so a human reviewer
    # sees the extraction failure rather than a false-clean verdict.
    if extract_errors and result["status"] == "pass":
        result["status"] = "warn"
        result["errors"].append(
            "golden text extraction failed for one or more files and the LLM "
            "did not report content_unavailable; treating as warn rather than "
            "a clean pass, since the audit may not have seen the real golden text"
        )
    return result


# ---------------------------------------------------------------------------
# Per-task audit
# ---------------------------------------------------------------------------


def audit_task(task_dir: Path, dry_run: bool = False, timeout: int = 180) -> dict:
    """Audit one task for fabricated unfiled-named facts. Returns the per-task
    result dict. Never raises: every failure path (missing content, LLM error,
    parse error) produces a result dict with an error/skip status rather than
    crashing the batch."""
    task_id = task_dir.name
    fmt = _task_format(task_dir)
    golden_text, extract_errors = collect_golden_text(task_dir, fmt)
    env_dir = _resolve_env_dir(task_dir, fmt)
    n_golden_files = len(find_golden_files(task_dir, fmt))

    # Content gate: if there are no golden files, there is nothing to audit.
    if not n_golden_files:
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_golden_files": 0,
            "n_env_files": 0,
            "parse_errors": [],
            "errors": ["no golden files found under solution/ -- nothing to audit"],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    # Environment gate: if the environment directory is absent, there is no
    # file listing to cross-reference against. Skip with a clear reason.
    if not env_dir.is_dir():
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_golden_files": n_golden_files,
            "n_env_files": 0,
            "parse_errors": [],
            "errors": [
                f"environment directory not found: {env_dir} -- no file listing "
                f"to cross-reference claims against"
            ],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    env_listing, n_env_files, total_bytes = build_env_listing(env_dir, task_dir)

    # Too-large environment guard: skip rather than stall. Same discipline as
    # golden_groundedness_check.py's own ENV_TOO_MANY_FILES / ENV_TOO_LARGE_BYTES.
    if n_env_files > ENV_TOO_MANY_FILES or total_bytes > ENV_TOO_LARGE_BYTES:
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_golden_files": n_golden_files,
            "n_env_files": n_env_files,
            "parse_errors": [],
            "errors": [
                f"environment too large to list tractably: {n_env_files} files, "
                f"{total_bytes} bytes (caps: {ENV_TOO_MANY_FILES} files, "
                f"{ENV_TOO_LARGE_BYTES} bytes)"
            ],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    prompt = build_prompt(task_id, golden_text, env_listing, n_env_files)
    prompt_chars = len(prompt)

    # Dry-run: build the prompt, optionally show the HTTP request shape, but
    # never make a real LLM call.
    if dry_run:
        result: dict = {
            "task_id": task_id,
            "status": "pass",
            "task_format": fmt,
            "n_golden_files": n_golden_files,
            "n_env_files": n_env_files,
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

    # Real call: try the LLM backend. call_llm tries the Claude Code CLI first
    # (free, no key handling here), then the HTTP backend. Both raise
    # LLMBackendError on failure; we catch and report, never crash.
    try:
        raw_response = call_llm(prompt, SYSTEM_PROMPT, timeout=timeout)
        backend_used = "cli_or_http"
    except LLMBackendError as exc:
        return {
            "task_id": task_id,
            "status": "error",
            "task_format": fmt,
            "n_golden_files": n_golden_files,
            "n_env_files": n_env_files,
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
        n_golden_files,
        n_env_files,
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
    report dict with a 'results' list of per-task dicts. Tasks run on a thread
    pool since each LLM call is I/O-bound (network or subprocess). Same
    structure the sibling checks use."""
    dirs = find_task_dirs(root, task_ids, id_prefix)
    t0 = time.time()

    from concurrent.futures import ThreadPoolExecutor

    def _safe_audit_task(d: Path) -> dict:
        """Wraps audit_task so one task's unexpected exception produces an error
        result for that task instead of losing every other task's results."""
        try:
            return audit_task(d, dry_run=dry_run, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - deliberately broad
            return {
                "task_id": d.name,
                "status": "error",
                "task_format": "none",
                "n_golden_files": 0,
                "n_env_files": 0,
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
        out_path = out_dir / "fabricated_unfilenamed_fact.json"
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
        claim = first.get("claim", "?")[:80]
        print(f"  WARN  {tid:<18} {n} finding(s): {claim}", file=sys.stderr)
    else:
        print(f"  OK    {tid:<18} clean", file=sys.stderr)


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
