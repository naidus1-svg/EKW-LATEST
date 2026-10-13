#!/usr/bin/env python3
"""Scan an SVC/Cirrus task's instruction.md and environment/data/ for leaked
generation-pipeline artifacts, before the task is delivered.

Three pattern classes, in order of how often they've actually been found in
delivered tasks so far:

1. Bracket-style pipeline markers (`[TIE]`, `[SYNTHETIC]`, `[AI-GENERATED]`, …)
   — ported VERBATIM from the post-hoc QC pipeline's own
   `_SYNTHETIC_MARKER_PATTERNS` (gdpval_qc/v18_callbacks.py), so a task that
   passes this script will not fail the equivalent post-hoc check for this
   reason. Any single hit is unambiguous — there is no count threshold.

2. Unrendered template-call syntax — a generation script that computed a
   value but never substituted it into the final text, e.g. a literal
   `$(T20.inYear)` left in a document's narrative. Found verbatim, twice, in
   two different delivered task sets sharing the same corpus file (fixing it
   once at the source clears it everywhere the file is reused).

3. Anachronistic-date sanity — flags any year that appears rarely against an
   otherwise-dominant year elsewhere in the same task's data. This is NOT a
   hard fail: the script can't know a task's intended in-universe year, and
   forward-looking language ("the FY2023 plan") is normal business writing.
   It surfaces a candidate for a human to look at, the same way a real defect
   was found this round — a "2021" shipment record with a "2026" arrival
   date, where month/day were right and only the year was wrong (almost
   certainly the generation script stamping the real wall-clock year instead
   of the task's fictional one).

Findings use the same shape as `check_rubric.py` / `check_references.py`.
Stdlib only; no network.

    python check_synthetic_markers.py <task_dir>
        # task_dir must contain instruction.md and environment/data/
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

GATES = {
    "synthetic_pipeline_marker": {"role": "blocking", "reject_at_severity": 2},
    "unrendered_template_leak":  {"role": "blocking", "reject_at_severity": 2},
    "anachronistic_date":        {"role": "advisory", "reject_at_severity": 3},
}

# ── 1. Bracket-style pipeline markers — verbatim from v18_callbacks.py ──────
# Keep this list in sync with gdpval_qc/v18_callbacks.py's
# _SYNTHETIC_MARKER_PATTERNS by hand; it is a small, deliberately narrow list
# (see that file's docstring for why a broader "meta-commentary" regex was
# rejected as unsafe — real business prose legitimately uses words like
# "model" and "training" all the time).
_MARKER_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("[TIE]",            re.compile(r'\[TIE\]', re.IGNORECASE)),
    ("[SYNTHETIC]",      re.compile(r'\[SYNTHETIC\]', re.IGNORECASE)),
    ("[AI-GENERATED]",   re.compile(r'\[AI-GENERATED\]', re.IGNORECASE)),
    ("[AI_GENERATED]",   re.compile(r'\[AI_GENERATED\]', re.IGNORECASE)),
    ("[LLM-GENERATED]",  re.compile(r'\[LLM-GENERATED\]', re.IGNORECASE)),
    ("[LLM_GENERATED]",  re.compile(r'\[LLM_GENERATED\]', re.IGNORECASE)),
    ("[FABRICATED]",     re.compile(r'\[FABRICATED\]', re.IGNORECASE)),
    ("[GENERATED]",      re.compile(r'\[GENERATED\]', re.IGNORECASE)),
    ("[OMEGA]",          re.compile(r'\[OMEGA\]', re.IGNORECASE)),
    ("[OMEGA-REBORN]",   re.compile(r'\[OMEGA-REBORN\]', re.IGNORECASE)),
    ("[TAG: value]",     re.compile(
        r'\[(?:TIE|SYNTHETIC|AI|LLM|FABRICATED|GENERATED|OMEGA)[^\]]*\]',
        re.IGNORECASE)),
    # Prose fourth-wall break: a document stating outright it's a fabricated/
    # synthetic/AI-generated artifact made for training/eval/benchmark
    # purposes, without a bracket tag (a real miss this pattern was added
    # for: a source PDF read "This document is a FABRICATED artifact created
    # solely for a financial-analysis training case study").
    ("fabricated-for-training prose", re.compile(
        r'\b(fabricat\w*|synthetic(?:ally)?|ai[- ]generated|llm[- ]generated)\b'
        r'[^.]{0,60}\b(training|case study|benchmark|eval(?:uation)?|exercise)\b',
        re.IGNORECASE)),
    ("training-for-fabricated prose", re.compile(
        r'\b(training|case study|benchmark|eval(?:uation)?)\b[^.]{0,60}'
        r'\b(fabricat\w*|synthetic(?:ally)?|ai[- ]generated|llm[- ]generated)\b',
        re.IGNORECASE)),
    # "guide §6.10" / "guide POL.RETURNS" — a business document citing the
    # task's own internal build/spec guide as if it were a source, e.g.
    # "Dec returns ran higher than Q3 per guide POL.RETURNS". Found in a
    # random calibration sample after this script shipped, in a different
    # node's file than the two earlier "guide §6.1" instances this same
    # phrasing was already known to hit — recurring enough to be a pattern,
    # not a one-off.
    ("guide §/POL citation", re.compile(
        r'\bguide\s+(?:§\s?\d+(?:\.\d+)?|POL\.[A-Z]+)\b', re.IGNORECASE)),
]

# ── 2. Unrendered template-call syntax ──────────────────────────────────────
# The real hit this round was Qlik/QlikView-style `$(T20.inYear)` — a
# `$(identifier.property)` call left un-substituted in narrative text. Also
# cover the more common Jinja/shell/Python-format-string leaks in case a
# different generation stack is used elsewhere.
_TEMPLATE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("$(...) BI-tool call",   re.compile(r'\$\([A-Za-z_][\w.]{0,40}\)')),
    ("{{ jinja/mustache }}",  re.compile(r'\{\{\s*[A-Za-z_][\w.\[\]]{0,40}\s*\}\}')),
    ("{% jinja tag %}",       re.compile(r'\{%\s*[A-Za-z_].{0,40}?%\}')),
    ("${shell/template}",     re.compile(r'\$\{[A-Za-z_][\w]{0,30}\}')),
]

# Only match actual date-SHAPED substrings, not any bare 4-digit number — a
# spreadsheet is full of large numbers (inventory counts, IDs, dollar
# amounts) that incidentally fall in the 1900-2099 range but aren't dates.
# Covers MM/DD/YYYY and YYYY-MM-DD — the latter is also what `str()` on a
# genuine date-typed xlsx cell renders as ("2026-02-22 00:00:00"), which is
# exactly the shape of the real defect this check is built to catch.
_DATE_RE = re.compile(
    r'\d{1,2}/\d{1,2}/((?:19|20)\d{2})'
    r'|((?:19|20)\d{2})-\d{1,2}-\d{1,2}'
)


def _finding(dim, severity, headline, justification, fixability, evidence_quote=None):
    g = GATES[dim]
    return {
        "dimension": dim,
        "role": g["role"],
        "reject_at_severity": g["reject_at_severity"],
        "severity": severity,
        "confidence": "high",
        "applicable": True,
        "evidence_quote": evidence_quote,
        "headline": headline,
        "justification": justification,
        "fixability": fixability,
    }


_TEXT_EXT = (".md", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml", ".log")


def _office_text(path: str, skipped: set) -> str:
    """Best-effort text for .xlsx/.docx/.pdf. The real motivating leak this
    script exists to catch (`$(T20.inYear)`) was inside an xlsx cell, not a
    plain-text file, so these three formats matter — but stay optional:
    a missing library degrades to a reported skip, never a crash, mirroring
    check_dag.py's coverage-reporting pattern in the reviewer-side skill.
    """
    suffix = os.path.splitext(path)[1].lower()
    try:
        if suffix == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            out = []
            for sn in wb.sheetnames:
                for row in wb[sn].iter_rows(values_only=True):
                    out.append(" ".join("" if c is None else str(c) for c in row))
            wb.close()
            return "\n".join(out)
        if suffix == ".docx":
            from docx import Document
            return "\n".join(p.text for p in Document(path).paragraphs)
        if suffix == ".pdf":
            from pypdf import PdfReader
            return "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)
        if suffix == ".doc":
            # Legacy binary Word format — no ubiquitous pure-Python reader
            # (python-docx only handles the newer .docx XML format). Unlike
            # a zipped/deflated .docx, a .doc's text runs are mostly stored
            # uncompressed, so a raw latin-1 byte decode (which never
            # raises) still lets substring/regex matching find an embedded
            # marker or template leak verbatim — it just won't read as
            # clean prose. Found the real motivating leak for this script
            # verbatim in a .doc file this way; don't skip this format.
            with open(path, "rb") as fh:
                return fh.read().decode("latin-1", errors="ignore")
    except ImportError as exc:
        skipped.add(f"{suffix} ({exc.name} missing — pip install to close this gap)")
    except Exception as exc:
        skipped.add(f"{os.path.basename(path)} ({type(exc).__name__})")
    return ""


def _iter_text_files(task_dir: str, skipped: set):
    """Yield (relpath, text) for instruction.md and every readable file under
    environment/data/ — plain text formats directly, xlsx/docx/pdf via
    best-effort extraction (see `_office_text`).
    """
    instr = os.path.join(task_dir, "instruction.md")
    if os.path.isfile(instr):
        yield "instruction.md", open(instr, encoding="utf-8", errors="replace").read()

    data_dir = os.path.join(task_dir, "environment", "data")
    for root, _dirs, files in os.walk(data_dir):
        for fn in files:
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, task_dir)
            suffix = os.path.splitext(fn)[1].lower()
            if suffix in _TEXT_EXT:
                try:
                    yield rel, open(path, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
            elif suffix in (".xlsx", ".docx", ".pdf", ".doc"):
                text = _office_text(path, skipped)
                if text:
                    yield rel, text


def check_pipeline_markers(files: list[tuple[str, str]]):
    hits = []
    for rel, text in files:
        for label, pat in _MARKER_PATTERNS:
            m = pat.search(text)
            if m:
                hits.append((rel, label, m.group(0)))
                break  # one hit per file is enough to flag the file
    if not hits:
        return _finding("synthetic_pipeline_marker", 0,
                        f"no pipeline markers found across {len(files)} scanned file(s)",
                        "Programmatic check passed.", "n/a")
    rel, label, matched = hits[0]
    return _finding("synthetic_pipeline_marker", 2,
                    f"{len(hits)} file(s) contain a synthetic-pipeline marker: "
                    f"{[h[0] for h in hits]}",
                    f"e.g. {rel} matched {label!r} ({matched!r}). A single confirmed "
                    "marker means the task-creation tooling's own metadata leaked "
                    "into what the solving agent sees.", "fixable",
                    evidence_quote=matched)


def check_template_leaks(files: list[tuple[str, str]]):
    hits = []
    for rel, text in files:
        for label, pat in _TEMPLATE_PATTERNS:
            m = pat.search(text)
            if m:
                hits.append((rel, label, m.group(0)))
                break
    if not hits:
        return _finding("unrendered_template_leak", 0,
                        f"no unrendered template syntax found across {len(files)} "
                        "scanned file(s)",
                        "Programmatic check passed.", "n/a")
    rel, label, matched = hits[0]
    return _finding("unrendered_template_leak", 2,
                    f"{len(hits)} file(s) contain unrendered template syntax: "
                    f"{[h[0] for h in hits]}",
                    f"e.g. {rel} matched {label!r} ({matched!r}) — a generation script "
                    "computed a value but never substituted it into the final text.",
                    "fixable", evidence_quote=matched)


def check_anachronistic_dates(files: list[tuple[str, str]]):
    """Flag a year that's rare against an otherwise-dominant year elsewhere
    in the same task's data. Advisory only — surfaces a candidate, does not
    assert a defect, since a legitimate forward-looking reference ("the
    FY2023 plan") looks the same to a pure year-frequency count.
    """
    from collections import Counter
    tally: Counter[str] = Counter()
    where: dict[str, list[str]] = {}
    for rel, text in files:
        for m in _DATE_RE.finditer(text):
            y = m.group(1) or m.group(2)
            tally[y] += 1
            where.setdefault(y, [])
            if len(where[y]) < 3:
                ctx = text[max(0, m.start() - 30):m.end() + 15].replace("\n", " ")
                where[y].append(f"{rel}: ...{ctx}...")

    if len(tally) < 2:
        return _finding("anachronistic_date", 0,
                        "fewer than 2 distinct years found — nothing to compare",
                        "Programmatic check passed (not enough signal).", "n/a")

    dominant_year, dominant_count = tally.most_common(1)[0]
    # A year is a candidate if it's later than the dominant year AND rare
    # relative to it (appears in <10% as many places) — the exact shape of
    # the real defect found this round (2021 dominant, 2026 in a handful of
    # cells).
    candidates = {
        y: c for y, c in tally.items()
        if y != dominant_year and int(y) > int(dominant_year)
        and c <= max(1, dominant_count * 0.10)
    }
    if not candidates:
        return _finding("anachronistic_date", 0,
                        f"year {dominant_year} dominates ({dominant_count} "
                        f"occurrence(s)); no rare later-year outliers found",
                        "Programmatic check passed.", "n/a")

    lines = []
    for y, c in sorted(candidates.items()):
        lines.append(f"{y} ({c}x): {where[y][0]}")
    return _finding("anachronistic_date", 1,
                    f"{len(candidates)} later year(s) appear rarely against the "
                    f"dominant {dominant_year}: {sorted(candidates)}",
                    "Not an automatic defect — could be a legitimate forward-looking "
                    "reference. But this is the exact shape of a real defect found "
                    "this round (a generation script stamping the real wall-clock "
                    "year instead of the task's fictional one). Check each occurrence "
                    "by hand:\n" + "\n".join(lines), "fixable")


def run(task_dir: str):
    skipped: set = set()
    files = list(_iter_text_files(task_dir, skipped))
    if not files:
        unrun = ("Cannot run — no instruction.md or readable environment/data/ "
                 "files found at the expected paths.")
        return [_finding(d, 1, "nothing to scan", unrun, "n/a")
                for d in GATES], skipped
    return [
        check_pipeline_markers(files),
        check_template_leaks(files),
        check_anachronistic_dates(files),
    ], skipped


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Scan a task for leaked synthetic-pipeline markers, unrendered "
                    "template syntax, and anachronistic dates")
    ap.add_argument("task_dir", help="Path to the task directory "
                    "(instruction.md + environment/data/)")
    args = ap.parse_args(argv)

    findings, skipped = run(args.task_dir)
    print(f"Synthetic-marker / template-leak / date scan — {args.task_dir}")
    print("=" * 64)
    if skipped:
        print("SKIPPED COVERAGE (install libs to close):", ", ".join(sorted(skipped)))
    for f in findings:
        flag = "PASS" if f["severity"] == 0 else f"sev {f['severity']}"
        print(f"  [{flag:>5}] {f['dimension']:<26} {f['headline']}")
        if f["severity"] > 0:
            print(f"          ↳ {f['justification']}")
    print("\nFold these findings into your self-QC read (JSON):")
    print(json.dumps(findings, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
