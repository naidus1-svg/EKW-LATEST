#!/usr/bin/env python3
"""Structural audit check (LLM-judge): independently applies the six structural
defect patterns a manual "structural audit" methodology found on real SVC-PC
tasks that every existing deterministic + LLM check in this repo missed.

Why this exists
---------------
A manual, human/LLM-applied "structural audit" methodology (six patterns, see
`structural-audit/SKILL.md` in this directory) has been running ad hoc against a
handful of tasks and found real defects that ALL existing checks missed. Two
known real defect tasks passed every existing deterministic + LLM check with
zero fail/error, yet carry real structural defects that would score 0 silently
on a real DataOS Comprehensive Review:

  - SVC-PC-72-3-0 (tracker row 28): instruction.md names the SAME deliverable
    two different ways in two different sections. The "Deliverable" section
    (line 17) names `Unit_Economics_Guardrail_Accuracy_Workpaper.docx` (no
    prefix); the "Graded deliverable filenames" section (line 23) names
    `L2-03_Unit_Economics_Guardrail_Accuracy_Workpaper.docx` (with the L2-03_
    prefix). judge.toml reads ONLY the prefixed name. An agent that follows the
    earlier section produces the unprefixed file and scores 0 silently, because
    the grader never opens it.
  - SVC-PC-82-2-0 (tracker row 29): instruction.md has an "Assigned corpus files"
    heading that promises a list, then jumps to the next section ("Boundaries")
    with zero items actually given. judge.toml criterion l2-02-r09 requires
    stating "Six assigned files only" - a specific count the instruction never
    states.

Neither defect is caught by any existing check. deliverable_filename_check.py
catches a filename the instruction COMMANDS that judge.toml never reads, but it
does NOT catch the narrower row-28 case where the instruction names the same
deliverable two ways and judge.toml reads only one of the two names (both names
appear in instruction.md, so a naive "is the judge's filename anywhere in the
instruction" pass is satisfied; the defect is that the two sections DISAGREE
with each other on the name). environment_input_check.py catches missing
environment inputs but not a heading that promises a list and delivers none.

This check automates the manual methodology: it feeds the LLM the task's real
instruction.md (full text, with line numbers so it can cite the two disagreeing
sections by line), the real judge.toml files= list (the verifier's graded
read-scope, with each entry marked as a solver-produced deliverable vs a
judge read-scope source), the real judge.toml criteria, and a real environment
file manifest, then asks it to independently apply the six patterns and report
per-pattern pass/fail/warn with a short justification citing the specific text
that fired.

This is LLM-judgment territory, like golden_groundedness_check.py and
rubric_overspecification_check.py. The question "does instruction.md name the
same deliverable two different ways, and does judge.toml read only one of
those names?" requires reading two sections of prose and comparing them
semantically, not keyword matching. This script reuses tools/llm_backend.py's
call_llm() (the same backend those checks use) and the text-extraction helpers
from answer_key_rubric_leak_check.py and deliverable_filename_check.py, so the
instruction, judge files, criteria, and environment listing this check sends to
the LLM are byte-identical to what those checks already read.

Relationship to content-audit/SKILL.md (the pipeline's "Check A"): content-audit
is a different layer. Its six patterns check INTERNAL consistency among the
prompt/golden/rubric TEXT. This check's six patterns check the BUILT PACKAGE:
instruction.md vs the real judge.toml files= list vs the real environment
listing. The two are complementary, not overlapping (see structural-audit/
SKILL.md's own three-layer table). content-audit/SKILL.md has no CLI and no
CHECKS entry in either orchestrator (confirmed by reading both); this check
ships a real CLI and a real registration, so the structural patterns run
automatically in the normal process, not only when a human remembers.

Output shape
------------
Per-task result dict (the same verdict + findings shape every other check in
this folder produces, so it merges into svc_run_checks.py / ekw_run_checks.py
the same way):

    {
        "task_id": "SVC-PC-72-3-0",
        "status": "pass" | "warn" | "skip" | "error",
        "task_format": "svc_pc" | "ekw" | "none",
        "n_criteria": 12,
        "n_judge_deliverables": 1,
        "n_judge_readscope": 0,
        "n_env_files": 25,
        "parse_errors": [],
        "errors": [],
        "findings": [
            {
                "kind": "structural_audit",
                "pattern": 2,
                "pattern_name": "deliverable_filename_two_ways",
                "severity": "warn",
                "message": "one-line summary",
                "instruction_quote": "verbatim text from instruction.md (with line)",
                "judge_quote": "verbatim text from judge.toml (if applicable)",
                "environment_note": "what is missing/different in environment (if applicable)",
                "evidence": "why this is a defect"
            }
        ],
        "n_findings": 0,
        "n_warn": 0,
        "llm_backend": "cli_or_http" | "dry_run" | "none",
        "prompt_chars": 12345,
        "content_unavailable": false
    }

Severity is always "warn" for every finding, never "fail". This matches every
other LLM-based check in this project ("candidate, not verdict" posture; see
content-audit/SKILL.md). A finding never hard-gates a task on its own.

LLM backend
-----------
Uses tools/llm_backend.call_llm() which tries the Claude Code CLI first (free
under a Max plan, no credential handling here) then a caller-configured HTTP
backend. Same backend as golden_groundedness_check.py and
rubric_overspecification_check.py. The LLM_API_MAX_TOKENS=32000 setdefault
near the imports carries the same row-15 fix those checks carry (a reasoning
model starved at the 4096 library default returns empty content; 32000 was
verified 9/9 real calls succeeding).

CLI
---
    python structural_audit_check.py --all --root DIR --out results.json
    python structural_audit_check.py SVC-PC-72-3-0 --root DIR --out results.json
    python structural_audit_check.py SVC-PC-72-3-0 --root DIR --out results.json --dry-run
    python structural_audit_check.py SVC-PC-72-3-0 --root DIR --out results.json --timeout 300

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

# Row-15 fix (tracker row 15, commit f0d1105): the configured backend (glm-5.2,
# an OpenAI-compatible reasoning model) spends hidden reasoning tokens against
# the SAME max_tokens ceiling the visible answer draws from. At the library
# default of 4096, a real audit-sized prompt comes back finish_reason="length"
# with zero visible content. 32000 was verified 9/9 real calls succeeding.
# setdefault, not a hard override, so an operator's own explicit budget is never
# silently replaced. Same line golden_groundedness_check.py and
# rubric_overspecification_check.py both carry.
os.environ.setdefault("LLM_API_MAX_TOKENS", "32000")

from tools.llm_backend import call_llm, build_http_request, LLMBackendError

# Reuse the criterion/golden extraction from answer_key_rubric_leak_check.py
# (same calibrated path every other LLM check uses).
from answer_key_rubric_leak_check import (
    extract_file_text,
    find_golden_files,
    load_criteria_for_task,
)

# Reuse the judge.toml files= loader and the deliverable-vs-readscope
# discriminator from deliverable_filename_check.py. load_deliverable_files()
# is format-dispatching (SVC-PC judge.toml + EKW verifier.json) and returns
# (sources, parse_errors) where each source is {"group", "path", "files": [...]}.
# basename() reduces a files= entry to its bare filename. _load_solution_files()
# and _is_readscope_source() distinguish a solver-produced deliverable from a
# judge read-scope source (a judge.toml files= entry that is an environment
# input the judge reads as context, not a file the solver produces). This
# distinction is load-bearing for pattern 2: the LLM should compare
# instruction.md's named deliverables against the files= entries that are TRUE
# deliverables, not against read-scope sources.
from deliverable_filename_check import (
    load_deliverable_files,
    basename,
    _load_solution_files,
    _is_readscope_source,
    _environment_filenames,
)

# find_environment_files from answer_key_content_leak_check.py: same
# format dispatch (SVC-PC environment/initial_workspace/, EKW environment/data/).
from answer_key_content_leak_check import find_environment_files

# Windows console defaults to cp1252; force UTF-8 so non-cp1252 characters in
# real instruction/judge text never crash a batch run. Same line every other
# check in this folder carries.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The six structural defect patterns. The number is the authoritative key the
# LLM returns in each finding's "pattern" field; the name is a short
# machine-readable label used in the finding's "pattern_name". PATTERN_NAMES
# drives _normalize_finding's validation: a finding with an out-of-range
# pattern number is dropped (not defaulted), since a mis-numbered finding is
# meaningless for triage, unlike an unrecognized overspec_type which still
# carries a quote.
PATTERN_NAMES = {
    1: "placeholder_env_vs_named_files",
    2: "deliverable_filename_mismatch",
    3: "unhydrated_drive_dependency",
    4: "golden_or_pipeline_leak_in_prompt",
    5: "unstated_deliverable_count_or_format",
    6: "internal_contradiction_in_instruction",
}

# Cap the instruction.md text sent to the LLM. instruction.md is always small
# in this corpus (the real corpus's largest is a few KB), but the cap protects
# against a hypothetical malformed task and matches the discipline every other
# LLM check follows.
MAX_INSTRUCTION_CHARS = 60000

# Cap the environment file manifest. A flat recursive basename list is the
# useful signal for patterns 1 and 3 (is a named file present?); the full
# _corpus_subtree can be large, so the basename list is capped with a visible
# marker and a remaining count.
MAX_ENV_BASENAMES = 600

# Cap the rubric criteria text. Criteria are always small; this is a guard.
MAX_RUBRIC_CHARS = 60000


SYSTEM_PROMPT = (
    "You are a QC auditor for Harbor-shaped grading task packages. You read a "
    "task's real instruction.md, its real judge.toml files= list (the verifier's "
    "graded read-scope, with each entry marked as a solver-produced deliverable "
    "or a judge read-scope source), its real judge.toml criteria, and a real "
    "environment file manifest, and you judge whether the BUILT PACKAGE is "
    "structurally sound. You report findings as strict JSON. You do not fix, "
    "rewrite, or suggest fixes. You only flag defects you can cite specific "
    "text for, quoting instruction.md (with its line number) and/or the judge "
    "config verbatim. Every finding is reviewed by a human before any action, "
    "so a candidate flag is far cheaper than a missed structural defect that "
    "ships to graders. Flag any pattern you can support with the evidence "
    "below; do not suppress a flag merely because you are less than fully "
    "certain, as long as you can name the pattern number, quote the "
    "instruction text (with its line number), and state why the pattern fired."
)


# ---------------------------------------------------------------------------
# Text extraction (same helpers + semantics the other LLM checks use)
# ---------------------------------------------------------------------------


def read_instruction_md(task_dir: Path) -> tuple[str, str]:
    """Read instruction.md and return (raw_text, text_with_line_numbers).

    The line-numbered form prefixes every line with its 1-based line number
    (right-aligned, e.g. "  17: ..."), so the LLM can cite the exact line where
    a defect fires. The row-28 acceptance case (SVC-PC-72-3-0) is precisely a
    two-sections-disagree defect: line 17 names the deliverable without a
    prefix, line 23 names it with the L2-03_ prefix. Line numbers let the LLM
    name both lines in its evidence rather than paraphrasing.

    Returns ("", "") if instruction.md is absent (the caller decides whether
    that is a skip or an error)."""
    p = task_dir / "instruction.md"
    if not p.is_file():
        return "", ""
    raw = p.read_text(encoding="utf-8", errors="replace")
    if len(raw) > MAX_INSTRUCTION_CHARS:
        raw = raw[:MAX_INSTRUCTION_CHARS] + "\n[... TRUNCATED ...]\n"
    lines = raw.splitlines()
    width = len(str(len(lines)))
    numbered = "\n".join(
        f"{str(i+1).rjust(width)}: {line}" for i, line in enumerate(lines)
    )
    return raw, numbered


def collect_rubric_text(criteria: list[dict]) -> str:
    """Format criteria as labeled lines: '[group/name] description'. The
    bracketed label is what the LLM returns in a finding's 'criterion' field,
    so it maps straight back to the exact judge.toml entry. Same format
    rubric_overspecification_check.py uses."""
    lines: list[str] = []
    for c in criteria:
        label = f"{c.get('judge_group', '?')}/{c.get('name', '?')}"
        desc = c.get("description", "")
        lines.append(f"[{label}] {desc}")
    text = "\n".join(lines)
    if len(text) > MAX_RUBRIC_CHARS:
        text = text[:MAX_RUBRIC_CHARS] + "\n[... TRUNCATED ...]\n"
    return text


def build_judge_files_section(task_dir: Path) -> tuple[str, list[dict], int, list[str]]:
    """Build the judge.toml files= section for the prompt, splitting each entry
    into DELIVERABLES (solver must produce) vs READ-SCOPE SOURCES (judge reads
    as context). Returns (section_text, deliverable_entries, n_readscope,
    parse_errors).

    deliverable_entries is a list of {path, basename} for the true deliverables
    (used by audit_task for the result's n_judge_deliverables count). n_readscope
    is the count of read-scope entries (kept as a separate int, not the length
    of a list we would then discard, so audit_task does not re-call
    load_deliverable_files just to count them). The read-scope distinction uses
    deliverable_filename_check.py's _is_readscope_source, which prefers
    solution/files/ membership (route 2) and falls back to /app/_corpus_subtree/
    or environment presence (route 1).

    This distinction is load-bearing: for SVC-PC-82-2-0, judge.toml files=
    lists the solver's memo PLUS Fulfillment_SOP.docx and Inventory_Policy.docx
    as read-scope context. Pattern 2 (deliverable filename mismatch) only
    applies to the memo, not to the two SOP files. Marking them read-scope
    stops the LLM from mis-firing pattern 2 on context files."""
    sources, parse_errors = load_deliverable_files(task_dir)
    solution_files = _load_solution_files(task_dir)
    env_files = _environment_filenames(task_dir)

    deliverables: list[dict] = []
    readscope: list[dict] = []
    for src in sources:
        group = src.get("group", "?")
        for f in src.get("files", []):
            fname = basename(f)
            is_readscope = _is_readscope_source(fname, [f], solution_files, env_files)
            entry = {"path": f, "basename": fname, "group": group}
            if is_readscope:
                readscope.append(entry)
            else:
                deliverables.append(entry)
    n_readscope = len(readscope)

    parts: list[str] = []
    if deliverables:
        parts.append("DELIVERABLES the solver must produce (the verifier opens these as the graded answer):")
        for e in deliverables:
            parts.append(f"  - {e['path']}  [basename: {e['basename']}]")
    if readscope:
        parts.append("READ-SCOPE sources the judge reads as grading context (NOT files the solver produces):")
        for e in readscope:
            parts.append(f"  - {e['path']}  [basename: {e['basename']}]")
    if not deliverables and not readscope:
        parts.append("[no files= entries parsed from any judge.toml / verifier.json]")
    section = "\n".join(parts)
    return section, deliverables, n_readscope, [pe.get("error", str(pe)) for pe in parse_errors]


def build_environment_manifest(task_dir: Path) -> tuple[str, int, list[str]]:
    """Build the environment file manifest for the prompt. Returns
    (manifest_text, n_env_files, notes).

    The manifest has three parts:
      1. Directly-staged files: files directly under environment/
         initial_workspace/ (or environment/data/ for EKW), NOT inside the
         _corpus_subtree/ folder. These are the explicitly-staged inputs the
         solver sees at the top level.
      2. Corpus subtree summary: if a _corpus_subtree/ folder exists, list its
         top-level subfolders with file counts (capped), so the LLM can see the
         broader corpus shape without a multi-thousand-file listing.
      3. All staged file basenames: a flat sorted list of every file's basename
         under environment/ (capped at MAX_ENV_BASENAMES), so the LLM can answer
         "is the file instruction.md names actually present?" for patterns 1
         and 3.

    Placeholder marker detection: any directly-staged file whose name suggests
    "no input files" is called out explicitly, since pattern 1 fires when such
    a marker is the only thing staged while instruction.md names specific
    required files."""
    env_files = find_environment_files(task_dir)
    n_env_files = len(env_files)

    # Determine the environment root (initial_workspace vs data) by reusing the
    # same dispatch find_environment_files uses, without re-deriving it.
    from answer_key_content_leak_check import _task_format as _aakcl_task_format

    fmt = _aakcl_task_format(task_dir)
    env_root = task_dir / "environment" / ("data" if fmt == "ekw" else "initial_workspace")

    notes: list[str] = []
    parts: list[str] = []

    if not env_root.is_dir():
        parts.append("[environment directory not found]")
        return "\n".join(parts), 0, notes

    # 1. Directly-staged files (not inside _corpus_subtree).
    direct: list[Path] = []
    subtree_root: Path | None = None
    for p in sorted(env_root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(env_root)
        parts_rel = rel.parts
        if parts_rel and parts_rel[0] == "_corpus_subtree":
            if subtree_root is None:
                subtree_root = env_root / "_corpus_subtree"
            continue
        direct.append(p)

    if direct:
        parts.append("Directly staged files (top level of the environment, not inside _corpus_subtree/):")
        for p in direct:
            parts.append(f"  - {p.relative_to(env_root).as_posix()}")
    else:
        parts.append("Directly staged files: [none at top level]")

    # Placeholder marker detection on directly-staged files.
    placeholder_re = re.compile(
        r"no[_-]?input|no[_-]?files|placeholder|_no_input_files_required|"
        r"empty|not[_-]?required|placeholder_input",
        re.IGNORECASE,
    )
    placeholders = [p.name for p in direct if placeholder_re.search(p.name)]
    if placeholders:
        parts.append(f"Placeholder marker files detected at top level: {placeholders}")
        notes.append(f"placeholder_markers: {placeholders}")

    # 2. Corpus subtree summary (subfolder names + file counts, capped).
    if subtree_root is not None and subtree_root.is_dir():
        subfolders = sorted(
            p for p in subtree_root.iterdir() if p.is_dir()
        )
        parts.append(f"Corpus subtree ({subtree_root.name}/): {len(subfolders)} top-level subfolders")
        shown = 0
        for sf in subfolders:
            if shown >= 40:
                parts.append(f"  ... {len(subfolders) - shown} more subfolders omitted")
                break
            count = sum(1 for _ in sf.rglob("*") if _.is_file())
            parts.append(f"  - {sf.name}/  ({count} files)")
            shown += 1

    # 3. All staged file basenames (flat, sorted, capped).
    all_names = sorted({p.name for p in env_files})
    if len(all_names) > MAX_ENV_BASENAMES:
        shown_names = all_names[:MAX_ENV_BASENAMES]
        parts.append(
            f"All staged file basenames (searchable; first {MAX_ENV_BASENAMES} of "
            f"{len(all_names)} shown): " + ", ".join(shown_names)
        )
        parts.append(f"... {len(all_names) - MAX_ENV_BASENAMES} more basenames omitted")
    else:
        parts.append(
            "All staged file basenames (searchable): "
            + (", ".join(all_names) if all_names else "[none]")
        )

    return "\n".join(parts), n_env_files, notes


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    task_id: str,
    instruction_numbered: str,
    judge_files_section: str,
    rubric_text: str,
    env_manifest: str,
) -> str:
    """Assemble the full user prompt. The six patterns and the methodology are
    embedded directly so the LLM has the full recipe without needing to read
    any external doc."""
    return f"""== TASK: {task_id} ==

== INSTRUCTION (instruction.md, with line numbers) ==
{instruction_numbered or "[instruction.md absent or empty]"}

== JUDGE FILES (judge.toml [judge].files = [...], the verifier's graded read-scope) ==
{judge_files_section}

== RUBRIC CRITERIA (judge.toml [[criterion]] / verifier.json) ==
{rubric_text or "[no criteria parsed]"}

== ENVIRONMENT FILE MANIFEST (what is actually staged for the solver) ==
{env_manifest}

== THE SIX STRUCTURAL PATTERNS TO CHECK ==
You are auditing the BUILT PACKAGE: does instruction.md, the judge's files=
list, the judge criteria, and the actual environment listing AGREE with each
other? Each pattern is a distinct way they can disagree. Apply all six
independently.

1. placeholder_env_vs_named_files: The environment is a placeholder or generic
   description while instruction.md names specific required files that are not
   present anywhere in the environment. A placeholder marker file (e.g. a
   "_no_input_files_required.txt" style file) at the top level, or an
   environment whose top level has none of the specific files instruction.md
   names as required inputs, is this pattern. The defect is the GAP between
   what instruction.md says the solver needs and what the environment actually
   staged.

2. deliverable_filename_mismatch: instruction.md names a deliverable filename
   in its body text that does not match what judge.toml files= actually reads.
   This has two shapes:
   (a) instruction.md tells the solver to produce filename X, but judge.toml
       files= reads a different filename Y. An agent following the instruction
       writes X, the grader opens Y, and the agent scores 0 silently.
   (b) the NARROWER row-28 case: instruction.md names the SAME deliverable two
       DIFFERENT ways in two different sections (e.g. one section names it
       without a prefix, another section names it with an "L2-03_" prefix), and
       judge.toml files= reads only ONE of the two names. An agent following
       the section that names the OTHER form produces a differently-named file
       and scores 0 silently. Compare EVERY filename instruction.md associates
       with the deliverable across ALL its sections (the "Deliverable" body
       text AND any "Graded deliverable filenames" list) against the
       DELIVERABLE entries in the JUDGE FILES section (not the read-scope
       sources). If the same deliverable is named two ways and judge.toml
       reads only one of them, flag it.

3. unhydrated_drive_dependency: instruction.md points to a live cloud-storage
   (Google Drive, OneDrive, Dropbox, a "shared drive" URL, or any
   https://drive.google.com/ / https://...sharepoint... style link) folder or
   file that is never actually staged into the solver-visible environment.
   Look for a URL in instruction.md that names an input the solver needs, then
   confirm the named file/folder is NOT in the environment manifest. A Drive
   link left as the only reference to a required input, with nothing hydrated
   locally, is this pattern.

4. golden_or_pipeline_leak_in_prompt: GOLDEN / internal-pipeline text leaked
   into the solver-facing instruction.md. Look for a literal "GOLDEN"/"Golden"
   reference-solution filename the solver is told to produce, OR raw
   pipeline/build-system text inside instruction.md that does not read like
   task content. Triggers include: a NODE IDENTIFIER or task/deliverable
   numbering that is a pipeline artifact, not task content (e.g. an
   instruction heading like "# L2-02 - Prompt" where "L2-02" is a pipeline
   node/deliverable identifier and "Prompt" is a pipeline stage label);
   internal stage labels; eval-only vocabulary the solver should never see
   (golden, rubric, grader, must-pass, seed, engine); bracketed build-system
   language; template placeholders like {{variable}}; pipeline path markers.
   CROSS-CHECK the rubric criteria: if any criterion explicitly requires "zero
   occurrences" of a "node identifier" or "eval-only vocabulary" in the
   visible text, and instruction.md contains text that IS a node identifier or
   eval-only vocabulary, that text is a pattern 4 firing. The solver should
   never see answer-key naming, node identifiers, or pipeline scaffolding in
   their prompt.

5. unstated_deliverable_count_or_format: instruction.md asks for multiple
   named outputs or references a set of inputs but never states the count or
   format, while a judge criterion requires stating a specific count or format
   the instruction never gives. The row-29 case: instruction.md has a heading
   like "Assigned corpus files" that promises a list, then jumps to the next
   section with ZERO items actually listed, while a judge criterion requires
   stating a specific count (e.g. "six assigned files"). Cross-check the
   rubric criteria: if a criterion expects the solver to state a specific
   count, list, or format that instruction.md never actually provides or
   enumerates, flag it. Also flag if instruction.md promises a list/section
   ("Use only these files...") and then delivers none.

6. internal_contradiction_in_instruction: instruction.md contradicts ITSELF.
   Two parts of the instruction text disagree on a requirement, a filename, a
   count, a scope boundary, or a deliverable shape. The row-28 case (pattern
   2b) is also an internal contradiction (two sections name the deliverable
   differently), but it is filed under pattern 2 because the JUDGE makes one
   name binding and the other silently scores 0. Use pattern 6 for
   contradictions the judge does not resolve either way (e.g. the "Scope
   boundaries" section says "NOT a FY2022 plan" while a later section asks for
   a FY2022 plan; or the "Inputs" section names one set of files while a later
   paragraph names a different set as the only allowed sources).

== METHODOLOGY (follow every step; do not skip the enumeration) ==
1. Read the INSTRUCTION in full first. Note every filename it names as a
   required input or as a deliverable, and every heading that promises a list
   or a count. Pay attention to whether the SAME deliverable is named in more
   than one section, and whether those sections agree on the name.
2. Read the JUDGE FILES section. Separate the DELIVERABLES (solver must
   produce) from the READ-SCOPE SOURCES (judge reads as context). Pattern 2
   only compares instruction.md's named deliverables against the DELIVERABLE
   entries, never against read-scope sources.
3. Read the RUBRIC CRITERIA. Note any criterion that expects the solver to
   state a specific count, list, or format (pattern 5 cross-check), and any
   criterion that names a specific filename or value.
4. Read the ENVIRONMENT MANIFEST. Check whether every specific file
   instruction.md names as a required input is actually present (pattern 1),
   and whether any Drive/cloud URL in instruction.md points at something not
   hydrated locally (pattern 3).

== MANDATORY PER-PATTERN ENUMERATION ==
You MUST now consider each of the six patterns IN ORDER, one at a time, and
record an explicit per-pattern decision BEFORE you assemble the final
findings list. Do NOT scan the inputs once and report whatever jumps out; a
pattern you never explicitly consider is a pattern you never check, and a
borderline signal (a single leaked heading, one unhydrated URL, one promised
list that delivers none) is exactly the signal an implicit scan silently
skips on a bad roll.

For EACH pattern number 1 through 6, in order, do the following:
  (a) Name the pattern and restate its trigger in your own words against the
      REAL instruction.md / judge files / rubric / environment content above
      (not a generic restatement of the pattern definition).
  (b) Quote the specific instruction.md text (with its line number) that is a
      candidate for this pattern, or state that no candidate text exists. If
      the pattern cross-checks against judge files or the rubric, quote that
      text too. If the pattern checks the environment, name what you looked
      for and whether it was present.
  (c) Decide: does this pattern FIRE or NOT FIRE on this task? State the
      decision and a one-sentence reason grounded in the quoted text.

Work all six patterns. Do NOT stop after the first one that fires. A task can
carry zero, one, or several findings across different patterns, and a clean
task requires you to have explicitly considered and rejected all six.

After all six per-pattern decisions are recorded, emit the findings list
containing every pattern you decided FIREs, each with the verbatim quote,
the judge quote if relevant, the environment note if relevant, and the
evidence sentence. Patterns you decided NOT FIRE produce no finding.

You MUST record all six per-pattern decisions in the "pattern_review" array
of the output JSON (see OUTPUT FORMAT below), one entry per pattern number
1-6, BEFORE the verdict and findings. The pattern_review array is the
enumeration: it forces you to commit to a per-pattern decision against the
real content rather than silently skipping a borderline pattern on a bad
roll. A pattern_review with fewer than six entries, or one that skips a
pattern number, means you never considered that pattern.

== IMPORTANT: do NOT flag these ==
- An environment that DOES contain the specific files instruction.md names.
  That is pattern 1 NOT firing, not a defect.
- A read-scope source in judge.toml files= whose basename differs from
  instruction.md's named deliverable. Read-scope sources are judge context,
  not solver deliverables; a name difference there is not pattern 2.
- A "Graded deliverable filenames" section in instruction.md that names the
  SAME filename judge.toml reads, even if the earlier "Deliverable" body text
  described the deliverable by a generic description rather than a filename.
  Pattern 2 fires only when two sections NAME DIFFERENT FILENAMES for the same
  deliverable, or when the named filename does not match what judge.toml
  reads.
- A judge criterion that expects a count the instruction DOES state. Pattern
  5 fires only when the instruction promises or implies a count/list but
  never actually gives it, while a criterion requires it.
- A Drive URL in instruction.md that points at a file/folder that IS hydrated
  in the environment. Pattern 3 fires only when the Drive dependency is NOT
  staged locally.

== OUTPUT FORMAT (strict JSON, no prose before or after) ==
Return a single JSON object with this exact shape. The "pattern_review"
array MUST come FIRST and MUST contain exactly six entries (pattern 1
through 6, in order). Emit pattern_review, then verdict, then findings.
{{
  "pattern_review": [
    {{
      "pattern": 1,
      "decision": "fires" or "not_fires",
      "text_considered": "the specific instruction.md text (with line number) and/or judge text you checked against this pattern, or empty string if the pattern had no candidate text",
      "reason": "one sentence: why this pattern fires or does not fire, grounded in the text_considered"
    }},
    {{
      "pattern": 2,
      "decision": "fires" or "not_fires",
      "text_considered": "...",
      "reason": "..."
    }},
    {{
      "pattern": 3,
      "decision": "fires" or "not_fires",
      "text_considered": "...",
      "reason": "..."
    }},
    {{
      "pattern": 4,
      "decision": "fires" or "not_fires",
      "text_considered": "...",
      "reason": "..."
    }},
    {{
      "pattern": 5,
      "decision": "fires" or "not_fires",
      "text_considered": "...",
      "reason": "..."
    }},
    {{
      "pattern": 6,
      "decision": "fires" or "not_fires",
      "text_considered": "...",
      "reason": "..."
    }}
  ],
  "verdict": "clean" or "defective",
  "findings": [
    {{
      "pattern": 2,
      "pattern_name": "deliverable_filename_mismatch",
      "severity": "warn",
      "criterion": "deliverables/r01 or empty if not criterion-specific",
      "instruction_quote": "verbatim text from instruction.md including the line number, e.g. 'line 17: Unit_Economics_Guardrail_Accuracy_Workpaper.docx'",
      "judge_quote": "verbatim text from judge.toml files= or a criterion, if applicable, else empty string",
      "environment_note": "what is missing or different in the environment, if applicable, else empty string",
      "evidence": "one or two sentences: why this pattern fired, citing the specific disagreement"
    }}
  ]
}}

Rules:
- Output ONLY the JSON object. No markdown code fences, no prose, no explanation before or after.
- pattern_review MUST contain exactly six entries, one per pattern 1 through 6, in numeric order. Every entry must have a "decision" of "fires" or "not_fires" and a "reason" grounded in the real text. This is mandatory: a missing pattern_review entry means you skipped that pattern, which is a methodology violation.
- "verdict" is "clean" if zero findings, "defective" if one or more.
- "findings" contains one entry per pattern you marked "fires" in pattern_review. A pattern marked "not_fires" in pattern_review MUST NOT appear in findings.
- "pattern" is an integer 1-6 matching one of the six patterns above.
- "pattern_name" is the pattern's short label (e.g. "deliverable_filename_mismatch", "unstated_deliverable_count_or_format").
- "severity" is always "warn".
- Every finding MUST include an "instruction_quote" with the verbatim text (including line number) that fired.
- "judge_quote" and "environment_note" are required keys but may be empty strings when the pattern is instruction-internal (pattern 6) or environment-only.
- "evidence" MUST explain the specific disagreement in one or two sentences.
- If instruction.md is absent, return {{"pattern_review": [], "verdict": "clean", "findings": [], "content_unavailable": true, "unavailable_reason": "instruction.md absent"}}.
- If the judge files= list is empty AND the rubric is empty, return {{"pattern_review": [], "verdict": "clean", "findings": [], "content_unavailable": true, "unavailable_reason": "no judge config and no rubric parsed"}}.
- Do not invent defects. Every finding is reviewed by a human before any
  action, so a candidate flag is far cheaper than a missed structural defect
  that ships to graders. Flag any pattern you can support with a verbatim
  instruction quote (with line number) and a one-sentence reason; do not
  suppress a borderline flag merely because you are less than fully certain.
"""


# ---------------------------------------------------------------------------
# Response parsing (same proven JSON-extraction logic the other LLM checks use)
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
    """Find a balanced {...} block in text that parses as JSON. Scans every
    '{' in order (not just the first) so prose containing an unrelated brace
    before the real JSON object does not shadow the actual payload. Returns
    the first candidate that parses successfully, or the first
    balanced-but-unparseable candidate if none parse."""
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
    parse_error (set when parsing failed). Never raises: a non-JSON response
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
    None if the finding is too malformed to use (missing instruction_quote, or
    an out-of-range pattern number).

    Unlike rubric_overspecification_check.py (which defaults an unrecognized
    overspec_type), this check DROPS a finding whose pattern number is not in
    1-6. A mis-numbered structural finding is meaningless for triage: pattern
    2 and pattern 6 call for different reviewer actions, and a finding that
    cannot be placed on the right pattern is not actionable. The important
    validation is that the finding carries a verbatim instruction_quote (the
    evidence a reviewer needs to locate the defect)."""
    if not isinstance(f, dict):
        return None
    try:
        pattern = int(f.get("pattern", -1))
    except (TypeError, ValueError):
        return None
    if pattern not in PATTERN_NAMES:
        return None
    instruction_quote = (f.get("instruction_quote") or "").strip()
    if not instruction_quote:
        return None
    pattern_name = (f.get("pattern_name") or "").strip()
    if pattern_name not in PATTERN_NAMES.values():
        pattern_name = PATTERN_NAMES[pattern]
    evidence = (f.get("evidence") or "").strip()
    criterion = (f.get("criterion") or "").strip()
    judge_quote = (f.get("judge_quote") or "").strip()
    environment_note = (f.get("environment_note") or "").strip()
    message = f"[structural_audit/p{pattern}/{pattern_name}] {instruction_quote[:160]}"
    if criterion:
        message += f" ({criterion})"
    return {
        "kind": "structural_audit",
        "pattern": pattern,
        "pattern_name": pattern_name,
        "severity": "warn",
        "criterion": criterion[:200],
        "message": message[:500],
        "instruction_quote": instruction_quote[:2000],
        "judge_quote": judge_quote[:2000],
        "environment_note": environment_note[:1000],
        "evidence": evidence[:2000],
    }


def build_task_result_from_response(
    task_id: str,
    parsed: dict,
    fmt: str,
    n_criteria: int,
    n_judge_deliverables: int,
    n_judge_readscope: int,
    n_env_files: int,
    parse_errors: list[str],
    extract_errors: list[str],
    backend_used: str,
    prompt_chars: int,
) -> dict:
    """Turn a parsed LLM response into the per-task result dict the orchestrator
    reads. Handles all three response shapes: clean, defective, and
    parse-error. Same structure the other LLM checks use."""
    result = {
        "task_id": task_id,
        "status": "pass",
        "task_format": fmt,
        "n_criteria": n_criteria,
        "n_judge_deliverables": n_judge_deliverables,
        "n_judge_readscope": n_judge_readscope,
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

    # Preserve the per-pattern review the LLM emitted (the mandatory
    # enumeration from the row-28/29 run-to-run determinism fix). The
    # pattern_review array is the LLM's explicit, per-pattern commitment
    # before its verdict; keeping it in the result lets a reviewer see
    # which patterns the LLM considered and rejected, not only what it
    # flagged. Normalized to a compact, bounded shape so a malformed or
    # oversized entry never blows the result dict.
    raw_review = parsed.get("pattern_review", [])
    pattern_review: list[dict] = []
    if isinstance(raw_review, list):
        for pr in raw_review:
            if not isinstance(pr, dict):
                continue
            try:
                pn = int(pr.get("pattern", -1))
            except (TypeError, ValueError):
                continue
            if pn not in PATTERN_NAMES:
                continue
            pattern_review.append({
                "pattern": pn,
                "decision": str(pr.get("decision", ""))[:20],
                "text_considered": str(pr.get("text_considered", ""))[:1000],
                "reason": str(pr.get("reason", ""))[:1000],
            })
    result["pattern_review"] = pattern_review

    result["findings"] = findings
    result["n_findings"] = len(findings)
    result["n_warn"] = len(findings)
    # Same "candidate, not verdict" posture as every other LLM check: warn,
    # never fail, even if the LLM says "defective." A finding never hard-gates.
    result["status"] = "warn" if findings else "pass"

    # Same extraction-failure guard the other LLM checks use: if extraction
    # failed and the LLM did not self-report content_unavailable, downgrade a
    # "pass" to "warn" so a human reviewer sees the extraction failure rather
    # than a false-clean verdict.
    if extract_errors and result["status"] == "pass":
        result["status"] = "warn"
        result["errors"].append(
            "extraction failed for one or more inputs and the LLM did not "
            "report content_unavailable; treating as warn rather than a clean "
            "pass, since the audit may not have seen the real inputs"
        )
    return result


# ---------------------------------------------------------------------------
# Per-task audit
# ---------------------------------------------------------------------------


def audit_task(task_dir: Path, dry_run: bool = False, timeout: int = 240) -> dict:
    """Audit one task for the six structural patterns. Returns the per-task
    result dict. Never raises: every failure path (missing content, LLM error,
    parse error) produces a result dict with an error/skip status rather than
    crashing the batch."""
    task_id = task_dir.name
    criteria, parse_errors, fmt = load_criteria_for_task(task_dir)
    n_golden_files = len(find_golden_files(task_dir, fmt))
    _raw_instruction, instruction_numbered = read_instruction_md(task_dir)
    judge_files_section, deliverables, n_judge_readscope, judge_parse_errors = (
        build_judge_files_section(task_dir)
    )
    rubric_text = collect_rubric_text(criteria)
    env_manifest, n_env_files, env_notes = build_environment_manifest(task_dir)

    n_judge_deliverables = len(deliverables)

    extract_errors: list[str] = []
    extract_errors.extend(judge_parse_errors)
    extract_errors.extend(env_notes)

    # Content gate: if instruction.md is absent, there is nothing to audit.
    # Every pattern reads instruction.md; without it, there is no question.
    if not instruction_numbered:
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_criteria": len(criteria),
            "n_judge_deliverables": n_judge_deliverables,
            "n_judge_readscope": n_judge_readscope,
            "n_env_files": n_env_files,
            "parse_errors": parse_errors,
            "errors": ["instruction.md absent; cannot audit the built package"]
            + extract_errors,
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }
    # If the judge files= list is empty AND the rubric is empty, patterns 2
    # and 5 (which cross-check against the judge) have nothing to compare
    # against; skip rather than ask the LLM to hallucinate a judge config.
    if not deliverables and not criteria:
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_criteria": len(criteria),
            "n_judge_deliverables": n_judge_deliverables,
            "n_judge_readscope": n_judge_readscope,
            "n_env_files": n_env_files,
            "parse_errors": parse_errors,
            "errors": ["no judge files= deliverables and no rubric criteria; "
                       "cannot audit instruction-vs-judge agreement"]
            + extract_errors,
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    prompt = build_prompt(
        task_id, instruction_numbered, judge_files_section, rubric_text, env_manifest
    )
    prompt_chars = len(prompt)

    # Dry-run: build the prompt, optionally show the HTTP request shape, but
    # never make a real LLM call.
    if dry_run:
        result: dict = {
            "task_id": task_id,
            "status": "pass",
            "task_format": fmt,
            "n_criteria": len(criteria),
            "n_judge_deliverables": n_judge_deliverables,
            "n_judge_readscope": n_judge_readscope,
            "n_env_files": n_env_files,
            "parse_errors": parse_errors,
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
            "n_criteria": len(criteria),
            "n_judge_deliverables": n_judge_deliverables,
            "n_judge_readscope": n_judge_readscope,
            "n_env_files": n_env_files,
            "parse_errors": parse_errors,
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
        len(criteria),
        n_judge_deliverables,
        n_judge_readscope,
        n_env_files,
        parse_errors,
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
    timeout: int = 240,
) -> dict:
    """Programmatic entry point (the orchestrators use this). Returns the
    report dict with a 'results' list of per-task dicts. Tasks run on a
    thread pool since each LLM call is I/O-bound (network or subprocess).
    Same structure the other LLM checks use."""
    dirs = find_task_dirs(root, task_ids, id_prefix)
    t0 = time.time()

    from concurrent.futures import ThreadPoolExecutor

    def _safe_audit_task(d: Path) -> dict:
        """Wraps audit_task so one task's unexpected exception produces an
        error result for that task instead of losing every other task's
        results. Same backstop the other LLM checks use."""
        try:
            return audit_task(d, dry_run=dry_run, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - deliberately broad
            return {
                "task_id": d.name,
                "status": "error",
                "task_format": "none",
                "n_criteria": 0,
                "n_judge_deliverables": 0,
                "n_judge_readscope": 0,
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
        out_path = out_dir / "structural_audit.json"
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
        p = first.get("pattern", "?")
        pname = first.get("pattern_name", "?")
        print(f"  WARN  {tid:<18} {n} finding(s): p{p}/{pname}", file=sys.stderr)
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
        default=240,
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
