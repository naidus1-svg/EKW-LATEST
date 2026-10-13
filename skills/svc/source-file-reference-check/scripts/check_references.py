#!/usr/bin/env python3
"""Deterministic reference check for one SVC/Cirrus task's `instruction.md`.

Mirrors two of the post-hoc QC pipeline's LLM-judged dimensions
(`instruction_input_consistency`, `self_containedness`) for the single
mechanical half either dimension is built on: does every file the
instruction names by filename actually exist under `environment/data/`?
This is the single most common real defect found across delivered SVC
task sets so far — an instruction references a specific source file
("the KPI report", "Year_1_Marketing_Annual_Review.xlsx", "the governed
revenue-adjustment bridge") that was never bundled into the data room.

Also flags `environment/data/` containing zero real files (only a
`SOURCES.md` pointer, or nothing) — added after a calibration miss where an
instruction referenced files only by category ("the four OpEx handoff
files"), never by literal filename, so the name-matching check above passed
vacuously while the folder was functionally empty.

This script does NOT attempt the harder semantic half of either dimension
— whether a present file's *content* actually matches what the instruction
asks for. That still needs a human (or the authenticity-and-substance-review
checklist). Treat a clean run here as "nothing is missing by name," not
"the task is solvable."

Findings use the same shape as `check_rubric.py` (dimension/role/severity/
evidence_quote/headline/justification/fixability) so outputs compose.
Stdlib only; no network.

    python check_references.py <task_dir>
        # task_dir must contain instruction.md and environment/data/
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

GATES = {
    "source_file_reference_missing":      {"role": "blocking", "reject_at_severity": 2},
    "source_file_reference_unreferenced": {"role": "advisory", "reject_at_severity": 3},
    "source_data_dir_pointer_only":       {"role": "blocking", "reject_at_severity": 2},
}

# Filename-shaped tokens: a run of filename characters ending in a known
# extension. Deliberately extension-anchored rather than trying to parse
# free-text phrases ("the attached export") — every real missing-file defect
# found so far named the file explicitly, so this stays a low-false-positive,
# high-precision check rather than a fuzzy one.
_EXTENSIONS = (
    "xlsx", "xls", "docx", "doc", "pdf", "csv", "tsv", "pptx", "ppt",
    "json", "txt", "md",
)
# No space in the character class on purpose — real filenames in this corpus
# consistently use underscores/hyphens (`Sales_Order_Receipts.pdf`,
# `Q4_GL_Detail_updated.xlsx`), never literal spaces. Allowing spaces here
# made the regex swallow whole surrounding phrases before hitting an
# unrelated extension elsewhere in the sentence (e.g. "cross-check against
# payroll_register.csv" instead of just "payroll_register.csv").
_FILENAME_RE = re.compile(
    r"[A-Za-z0-9][\w\-.]*\.(?:" + "|".join(_EXTENSIONS) + r")\b",
    re.IGNORECASE,
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


def _referenced_filenames(instruction_text: str) -> dict[str, str]:
    """{basename.lower(): the sentence-ish context it was found in}.

    Skips any match preceded by `workspace/output` — the SVC harness
    convention for the REQUIRED DELIVERABLE path, which by definition never
    exists in environment/data/ (it's what the agent is asked to produce, not
    consume). Checking those against environment/data/ is a category error,
    not a real "missing source" finding — and doing so was actually how this
    script first noticed a separate, real defect (a garbled auto-generated
    output filename), which belongs to a different check, not this one.
    """
    out: dict[str, str] = {}
    for m in _FILENAME_RE.finditer(instruction_text):
        name = m.group(0)
        line_start = instruction_text.rfind("\n", 0, m.start()) + 1
        preceding = instruction_text[line_start:m.start()].lower()
        if "workspace/output" in preceding or "workspace\\output" in preceding:
            continue
        base = os.path.basename(name.strip()).lower()
        if base not in out:
            start = max(0, m.start() - 40)
            end = min(len(instruction_text), m.end() + 10)
            out[base] = instruction_text[start:end].replace("\n", " ").strip()
    return out


def _actual_files(data_dir: str) -> dict[str, str]:
    """{basename.lower(): relative path} for every file under environment/data/."""
    out: dict[str, str] = {}
    for root, _dirs, files in os.walk(data_dir):
        for fn in files:
            if fn.lower() in (".ds_store", "sources.md"):
                continue
            rel = os.path.relpath(os.path.join(root, fn), data_dir)
            out.setdefault(fn.lower(), rel)
    return out


def check_data_dir_not_pointer_only(data_dir: str, actual: dict[str, str]):
    """Flag environment/data/ containing zero real files.

    Found by a calibration miss: an instruction referenced files only by
    category ("the four OpEx handoff files"), never by a literal filename,
    so `check_references_resolved` had nothing to check against and passed
    vacuously — while the folder actually contained only a `SOURCES.md`
    pointer whose own text read "items referenced but not saved in this
    folder (see Google Drive / QuickBooks)". `_actual_files` already
    excludes SOURCES.md/.DS_Store from the real-file count, so an empty
    `actual` here means the folder is functionally empty regardless of what
    instruction.md says or doesn't say by name.
    """
    if actual:
        return _finding("source_data_dir_pointer_only", 0,
                        f"environment/data/ has {len(actual)} real file(s)",
                        "Programmatic check passed.", "n/a")
    sources_md = os.path.join(data_dir, "SOURCES.md")
    note = ""
    if os.path.isfile(sources_md):
        try:
            first_line = open(sources_md, encoding="utf-8", errors="replace").readline().strip()
            note = f" SOURCES.md's own first line: {first_line!r}."
        except OSError:
            pass
    return _finding("source_data_dir_pointer_only", 2,
                    "environment/data/ contains no real files, only a pointer "
                    "(or nothing at all)",
                    "A task cannot be solved from a data room with no actual "
                    "data in it, regardless of whether the instruction names a "
                    "specific missing file or only refers to files by "
                    "category." + note, "structural")


def check_references_resolved(referenced: dict[str, str], actual: dict[str, str]):
    """Every filename instruction.md names must exist under environment/data/."""
    missing = {name: ctx for name, ctx in referenced.items() if name not in actual}
    if not missing:
        return _finding("source_file_reference_missing", 0,
                        f"all {len(referenced)} instruction-referenced filename(s) "
                        "resolve to a file in environment/data/",
                        "Programmatic check passed.", "n/a")
    names = sorted(missing)
    quote = missing[names[0]]
    return _finding("source_file_reference_missing", 2,
                    f"{len(missing)} filename(s) named in instruction.md are not in "
                    f"environment/data/: {names}",
                    "The instruction refers to a specific file that a solving agent "
                    "cannot locate — this is the single most common real defect found "
                    "across delivered SVC tasks so far. Either bundle the file or "
                    "remove the reference.", "fixable", evidence_quote=quote)


def check_all_inputs_referenced(referenced: dict[str, str], actual: dict[str, str]):
    """Files under environment/data/ that instruction.md never names.

    Low severity by design: some SVC tasks (confirmed this round — Task-2 and
    Task-5) deliberately hand a node the entire shared company data room and
    expect the solving agent to find the relevant file itself, so an
    unreferenced file is not automatically a defect. Treat this as a prompt
    to double-check "did I mean to name this file, or is a full-data-room
    design intentional here" rather than a hard requirement.
    """
    orphans = sorted(set(actual) - set(referenced))
    if not orphans:
        return _finding("source_file_reference_unreferenced", 0,
                        f"every file in environment/data/ is named somewhere in "
                        "instruction.md",
                        "Programmatic check passed.", "n/a")
    shown = orphans[:10]
    more = f" (+{len(orphans) - 10} more)" if len(orphans) > 10 else ""
    return _finding("source_file_reference_unreferenced", 1,
                    f"{len(orphans)} file(s) in environment/data/ are never named in "
                    f"instruction.md: {shown}{more}",
                    "Not automatically wrong — some tasks intentionally hand over a "
                    "full data room for the agent to search. Confirm that's the "
                    "actual design here, not an accidental leftover file.", "fixable")


def run(task_dir: str):
    instr_path = os.path.join(task_dir, "instruction.md")
    data_dir = os.path.join(task_dir, "environment", "data")

    if not os.path.isfile(instr_path):
        unrun = "Cannot run — instruction.md not found at the expected path."
        return [
            _finding("source_file_reference_missing", 2,
                    "instruction.md not found", unrun, "structural"),
            _finding("source_file_reference_unreferenced", 2,
                    "instruction.md not found", unrun, "structural"),
            _finding("source_data_dir_pointer_only", 2,
                    "instruction.md not found", unrun, "structural"),
        ]
    if not os.path.isdir(data_dir):
        unrun = "Cannot run — environment/data/ not found at the expected path."
        return [
            _finding("source_file_reference_missing", 2,
                    "environment/data/ not found", unrun, "structural"),
            _finding("source_file_reference_unreferenced", 2,
                    "environment/data/ not found", unrun, "structural"),
            _finding("source_data_dir_pointer_only", 2,
                    "environment/data/ not found", unrun, "structural"),
        ]

    with open(instr_path, encoding="utf-8", errors="replace") as fh:
        instruction_text = fh.read()

    referenced = _referenced_filenames(instruction_text)
    actual = _actual_files(data_dir)
    return [
        check_references_resolved(referenced, actual),
        check_all_inputs_referenced(referenced, actual),
        check_data_dir_not_pointer_only(data_dir, actual),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Check instruction.md file references against environment/data/")
    ap.add_argument("task_dir", help="Path to the task directory "
                    "(must contain instruction.md and environment/data/)")
    args = ap.parse_args(argv)

    findings = run(args.task_dir)
    print(f"Source-file reference check — {args.task_dir}")
    print("=" * 64)
    for f in findings:
        flag = "PASS" if f["severity"] == 0 else f"sev {f['severity']}"
        print(f"  [{flag:>5}] {f['dimension']:<32} {f['headline']}")
        if f["severity"] > 0:
            print(f"          ↳ {f['justification']}")
    print("\nFold these findings into your self-QC read (JSON):")
    print(json.dumps(findings, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
