#!/usr/bin/env python3
"""Judge file-scope UNDER-INCLUSION check (failure-mode tracker row 32): does the judge's
own configured file scope -- judge.toml's [judge].files=[...] list (SVC-PC) or a verifier's
own source.file list (EKW) -- OMIT source/reference documents that specific criteria's
Expected text actually depends on, so the judge grades self-declared, unverifiable claims?

Why this exists, and why it is NOT judge_scope_over_inclusion_check.py's territory: that
script (its own module docstring names this explicitly) closes the OPPOSITE end of the same
files= axis -- files=[...] too WIDE, including the deliverable AND pre-existing sources
undifferentiated, so source content can be credited as if the deliverable contained it. This
script closes the NARROW end: files=[...] too NARROW, omitting source/reference documents a
criterion's own Expected text implies the judge must check against. A criterion can require
"cites the catalog page" or "matches the source workbook" when the judge was never given the
catalog or workbook to check against, so the judge can only accept the deliverable's
self-declared claim at face value. judge_file_scope_breadth_check.py (row 33's sibling
sibling) catches a NAMED-FILENAME-LITERAL slice of this (a criterion that literally names a
file in its description that is absent from scope); this check catches the SEMANTIC slice a
regex cannot: a criterion whose Expected text references a specific fact, document, or
comparison that implies a source none of the listed files could verify, even when no
filename is named literally (e.g. "Expected: 80 vs 25 unresolved" implies Q2/Q3 product
catalog counts the judge was never given).

Real, confirmed positive controls (read from the LIVE C:/ekwqc/repo corpus, not a mirror):
  SVC-PC-82-2-0 / SVC-PC-82-3-0: judge.toml files= supplies only the memo plus
    Fulfillment_SOP.docx and Inventory_Policy.docx, NEVER the four Product_Catalog_Q1-4.pdf
    files that live under environment/initial_workspace/_corpus_subtree/Company Shared
    Drive/Marketing/Product/Catalogs/. Criteria r01/r06/r08 (82-2-0) and r02/r09 (82-3-0)
    grade against FY2021 change-type evidence and the "Q2/Q3 count conflict ... 80 vs 25"
    that can only be confirmed against the product catalogs the judge never sees.
  SVC-PC-52-3-0: files= supplies only Idle_Cash_Position_Analysis.xlsx; only December's
    monthly balance is checkable; the other 11 months (Bank_Statement_2021-{01..11}.pdf,
    AP_Aging_2021-{01..12}.xlsx, etc. under _corpus_subtree) are self-declared and ungraded.
  SVC-PC-46-3-0: files= supplies only the deliverable xlsx plus
    FY2021_Engineering_Demand_and_Interrupt_Assessment.docx, NEVER the 18
    Sprint_01-18_Backlog.xlsx files nor Incident_Log_2021.xlsx that the analysis is built
    from; criteria r03/r04/r06/r07 (the August Apex episode, Sprint 16 status conflict, the
    Sprint 3 punt, the Sprint 5 deferral) reference specific sprint evidence the judge can't
    open.

Why this is LLM-judgment territory, not a mechanical pattern match: the question "does
THIS criterion's Expected text reference a specific fact, document, or comparison that
none of the listed files could verify" requires reasoning about what evidence the
criterion's OWN wording implies is checkable ("matches the source workbook" implies the
source workbook must be in files=) versus what's actually listed. A keyword match cannot
do this: "Expected: 80 vs 25 unresolved" names no file, yet clearly implies a Q2 and Q3
product catalog. This was deliberately scoped out of a MECHANICAL checker at round 55
(row 33's over-inclusion sibling) for exactly this reason. This check is wired into the
orchestrator as an automated check (called on every run via svc_run_checks.py /
ekw_run_checks.py, letter D, same family as judge_scope_over_inclusion and
judge_file_scope_breadth), not a manual pass.

What it does, per task, per judge group (SVC-PC: one group per tests/deliverables*/judge.toml;
EKW: one group per verifier, since ekw_verifier_json.py confirms EKW has no judge.toml-style
shared grouping):
  1. Loads each group's files=[...] list (path-stripped to basenames) and every criterion's
     full description (which carries the requirement AND the "Expected: ..." clause), reusing
     judge_file_scope_breadth_check.py's own _load_svc_pc_groups / _has_svc_pc_config /
     _load_instruction / _basename / _weight_sum and DELIVERABLE_MARKER_RE, and
     criterion_groundedness_check.py's FILENAME_RE -- the same reuse convention
     judge_scope_over_inclusion_check.py follows.
  2. Builds the environment basename set (every file under environment/initial_workspace/
     (SVC-PC) or environment/data/ (EKW), recursive), mirroring
     judge_scope_over_inclusion_check.py's _env_basenames (rglob + file_listing.txt fallback).
  3. SUMMARIZES that environment set into a compact list for the LLM prompt: a real
     environment can carry 794 unique basenames (hundreds of dated slack json logs), which
     would blow the context window and bury the meaningful source documents. Dated/numbered
     families (Bank_Statement_2021-01.pdf .. 2021-12.pdf; 2021-10-01.json ..) collapse into
     one representative line with up to 6 example members, so the meaningful source
     filenames (Product_Catalog_Q1.pdf .. Q4.pdf; Sprint_01_Backlog.xlsx .. Sprint_18) stay
     visible. See _summarize_env_basenames's own docstring for the collapse rules.
  4. Identifies the deliverable filename(s) from instruction.md's deliverable-naming section
     (reusing DELIVERABLE_MARKER_RE + FILENAME_RE, same extraction
     judge_scope_over_inclusion_check.py's _instruction_deliverable_filenames uses) so the
     LLM is told which files= entries are the graded OUTPUT (never a source that can verify
     claims) versus pre-existing sources the judge was given.
  5. Feeds the LLM, per task: each group's files= list, the summarized environment file list
     (what sources EXIST, so the LLM can confirm an implied source was actually withheld
     rather than absent from the task entirely), and every criterion's full description. The
     LLM is asked to identify criteria whose Expected text references a specific fact,
     document, or comparison that NONE of the listed files could verify, naming the implied
     source when it is visible in the environment list.

Severity: warn-only, never fail. This matches EVERY other LLM-based check in this project
(rubric_overspecification_check.py, golden_groundedness_check.py, content-audit/SKILL.md):
"candidate, not verdict" posture. A false warn is advisory, not blocking; a false FAIL
would be. Many criteria legitimately do not need every referenced fact to be independently
file-verifiable (a reasoned judgment call, an internal-coherence check), so a real
false-positive rate is expected and reported, not assumed zero.

Output shape
------------
Per-task result dict (the same verdict + findings shape every LLM check in this folder
produces, so it merges into svc_run_checks.py / ekw_run_checks.py the same way):

    {
        "task_id": "SVC-PC-82-2-0",
        "status": "pass" | "warn" | "skip" | "error",
        "task_format": "svc_pc" | "ekw" | "none",
        "n_groups": 1,
        "n_criteria": 9,
        "judge_files": ["l2-02_..._memo(1).docx", "fulfillment_sop.docx", ...],
        "env_file_count": 794,
        "parse_errors": [],
        "errors": [],
        "findings": [
            {
                "kind": "judge_scope_under_inclusion",
                "severity": "warn",
                "group": "tests/deliverables/judge.toml",
                "criterion": "l2-02-r08",
                "quote": "Preserves the Q2/Q3 count conflict ...",
                "expected_text": "80 vs 25 unresolved.",
                "implied_source": "Product_Catalog_Q2.pdf, Product_Catalog_Q3.pdf",
                "reason": "the Q2/Q3 count conflict (80 vs 25) implies Q2/Q3 product ..."
            }
        ],
        "n_findings": 1,
        "n_warn": 1,
        "llm_backend": "cli" | "http" | "dry_run" | "none",
        "prompt_chars": 12345,
        "content_unavailable": false
    }

LLM backend
-----------
Uses tools/llm_backend.call_llm() which tries the Claude Code CLI first (free under a Max
plan, no credential handling here) then falls back to a generic HTTP call. For verifying
the request shape without a real key, pass --dry-run. Same backend as rubric_overspecification
and golden_groundedness. Same LLM_API_MAX_TOKENS=32000 setdefault (row-15 token-starvation
fix) every LLM check in this folder carries.

CLI
---
    python judge_scope_under_inclusion_check.py --all --root DIR --out results.json
    python judge_scope_under_inclusion_check.py SVC-PC-82-2-0 --root DIR --out results.json
    python judge_scope_under_inclusion_check.py SVC-PC-82-2-0 --root DIR --out results.json --dry-run
    python judge_scope_under_inclusion_check.py SVC-PC-82-2-0 --root DIR --out results.json --timeout 300

Stdlib only for the runner; the reused helpers pull openpyxl/python-docx on first run only
if the breadth check's environment_signals() is imported, which this check does NOT call
(it builds env basenames by rglob, no content extraction) -- so this check has no optional
dependency beyond tomllib (stdlib 3.11+).
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

# Row-15 fix (tracker row 15, commit f0d1105), applied by every LLM check in this folder:
# the library default of max_tokens=4096 starves this backend's reasoning-heavy model
# (glm-5.2) before it writes any visible answer on a real audit-sized prompt. setdefault,
# not a hard override, so an operator's own explicit budget is never silently replaced.
os.environ.setdefault("LLM_API_MAX_TOKENS", "32000")

from tools.llm_backend import call_llm, build_http_request, LLMBackendError  # noqa: E402

# Reuse the judge.toml / instruction.md helpers from judge_file_scope_breadth_check.py --
# the same canonical, weight-preserving SVC-PC group loader judge_scope_over_inclusion_check.py
# imports. These are the load-bearing helpers, not a reinvention.
from judge_file_scope_breadth_check import (  # noqa: E402
    _load_svc_pc_groups,
    _has_svc_pc_config,
    _load_instruction,
    _basename,
    _weight_sum,
    DELIVERABLE_MARKER_RE,
)
from criterion_groundedness_check import FILENAME_RE  # noqa: E402
from ekw_verifier_json import has_ekw_config, load_ekw_criteria  # noqa: E402

# Windows console defaults to cp1252; force UTF-8 so non-cp1252 characters in real
# rubric text never crash a batch run. Same line every other check in this folder carries.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cap the summarized environment file list at this many lines. A real environment can carry
# 794 unique basenames; the summarizer collapses dated/numbered families first, and this cap
# is the backstop so a pathologically varied environment still fits the prompt. The
# meaningful source documents (catalogs, monthly statements, sprint backlogs) survive the
# collapse because they are few and distinct; the cap only ever trims the long tail of
# unrelated dated logs after the summarizer already grouped them.
MAX_ENV_LINES = 150

# Cap the full prompt at this many characters so a task with many criteria plus a large
# summarized environment cannot exceed the model's context window. The criterion
# descriptions and files= lists are always small; this guards the summarized env block and
# the rare 100-criteria task. 120000 chars (~30K tokens) is comfortably inside the configured
# glm-5.2 backend's context window with the 32000-token output budget; the previous 60000 cap
# truncated SVC-PC-59-0-0's 100-criterion prompt mid-list and produced an unparseable response
# (caught as "error", never a false pass, but a real coverage gap on large-criteria tasks).
MAX_PROMPT_CHARS = 120000

SYSTEM_PROMPT = (
    "You are a QC auditor for Harbor-shaped grading tasks. You are given a judge group's "
    "configured file scope (the files= list -- the ONLY files the judge can open), the "
    "task's available environment file list (every source file that EXISTS in the task, "
    "so you can tell what was WITHHELD from the judge versus absent from the task "
    "entirely), and every grading criterion's full description including its 'Expected:' "
    "clause. Your job: identify any criterion whose Expected text references a specific "
    "fact, document, or comparison that NONE of the files in the judge's files= list could "
    "actually verify -- so the judge would have to accept the deliverable's self-declared "
    "claim at face value. You report findings as strict JSON. You do not fix, rewrite, or "
    "suggest fixes. You only flag criteria you can cite specific wording for. If you are "
    "not confident a criterion references an unverifiable external fact, do not flag it. "
    "A false positive wastes a human reviewer's time; a false negative is caught by the "
    "next QC layer. Prefer precision over recall."
)


# ---------------------------------------------------------------------------
# Environment basename collection + summarization
# ---------------------------------------------------------------------------


def _env_basenames(task_dir: Path, ekw: bool) -> set[str]:
    """Set of lowercased basenames of every file under environment/initial_workspace/
    (SVC-PC) or environment/data/ (EKW), recursive. Mirrors
    judge_scope_over_inclusion_check.py's _env_basenames (basename-only branch of
    environment_signals, no text/content extraction this check does not need). Falls back
    to file_listing.txt when the environment directory is absent (flattened mirror)."""
    env_subdir = "data" if ekw else "initial_workspace"
    env_dir = task_dir / "environment" / env_subdir
    out: set[str] = set()
    if env_dir.is_dir():
        for p in env_dir.rglob("*"):
            if p.is_file():
                out.add(p.name.lower())
    if not out:
        listing = task_dir / "file_listing.txt"
        if listing.is_file():
            prefix = f"environment/{env_subdir}/"
            for line in listing.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    rel = parts[1].replace("\\", "/")
                    if rel.startswith(prefix):
                        out.add(Path(rel).name.lower())
    return out


# Patterns whose trailing token is a date or numeric id, so a family of files
# (Bank_Statement_2021-01.pdf .. 2021-12.pdf, Sprint_01_Backlog.xlsx .. Sprint_18, dated
# 2021-10-01.json logs) collapses to one representative line. Order matters: longest /
# most-specific date shape first so a full ISO date is not half-stripped by the YYYY-MM
# rule. The captured group is stripped; the stem before it is the family key.
_DATE_SUFFIX_RES = [
    re.compile(r"^(.*?)[-_](\d{4}-\d{2}-\d{2})(?=\.[^.]+$|$)"),  # 2021-10-01
    re.compile(r"^(.*?)[-_](\d{4}-\d{2})(?=\.[^.]+$|$)"),  # 2021-01
    re.compile(r"^(.*?)[-_](\d{4})(?=\.[^.]+$|$)"),  # 2021
]
# A quarter suffix (Product_Catalog_Q1.pdf .. Q4.pdf, 2021-q1_investor_update.docx). Collapses
# the four quarterly product catalogs -- the named implied source for SVC-PC-82-2-0/82-3-0's
# r08 "Q2/Q3 count conflict" -- into one family line that survives the cap, with Q1-Q4 shown
# in the examples so the LLM sees which quarters exist. Tried AFTER the date rules so a year
# is not half-matched, BEFORE the bare numeric id so "Q1" is not read as a number.
_QUARTER_SUFFIX_RE = re.compile(r"^(.*?)[_-]?q[1-4](?=\.[^.]+$|$)", re.IGNORECASE)
# A bare numeric id suffix (Sprint_01, Backlog_03). Kept after the date and quarter rules so a
# year or quarter is not mistaken for a bare id.
_NUMID_SUFFIX_RE = re.compile(r"^(.*?)[-_](\d{2,4})(?=\.[^.]+$|$)")
# A pure-date filename (2021-10-01.json) -- no stem before the date.
_PURE_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.[^.]+$")


def _family_key(name: str) -> tuple[str, str]:
    """Return (stem, ext) family key for a basename, stripping a trailing date, quarter, or
    numeric id so siblings collapse together. 'Product_Catalog_Q1.pdf' -> ('product_
    catalog', 'pdf') so Q1-Q4 collapse to one family line (with Q1.pdf..Q4.pdf in the
    examples). 'Bank_Statement_2021-01.pdf' -> ('bank_statement', 'pdf') (12 siblings
    collapse). '2021-10-01.json' -> ('<dated-log>', 'json') (hundreds of slack logs
    collapse). 'Sprint_01_Backlog.xlsx' keeps its 01 only if there are siblings sharing the
    'sprint_'' stem after the numeric strip -- Sprint_01..Sprint_18 collapse to one family."""
    ext = ""
    if "." in name:
        ext = name.rsplit(".", 1)[1]
    for rx in _DATE_SUFFIX_RES:
        m = rx.match(name)
        if m:
            return (m.group(1).rstrip("-_.").lower() or "<dated>", ext)
    m = _QUARTER_SUFFIX_RE.match(name)
    if m:
        stem = m.group(1).rstrip("-_.").lower()
        if stem:
            return (stem, ext)
    m = _NUMID_SUFFIX_RE.match(name)
    if m:
        stem = m.group(1).rstrip("-_.").lower()
        if stem:
            return (stem, ext)
    if _PURE_DATE_RE.match(name):
        return ("<dated-log>", ext)
    return (name.lower(), ext)


_QUARTER_TOKENS = {"q1", "q2", "q3", "q4"}
_WORD_RE = re.compile(r"[a-z][a-z0-9]{3,}")


def _line_tokens(line: str) -> set[str]:
    """Content tokens from an env summary line, for relevance matching against criterion
    text. Lowercased alpha tokens of length >=4, plus quarter tokens q1-q4 (short but
    load-bearing: 'Q2/Q3' in a criterion matches 'product_catalog_q2.pdf' in the env)."""
    toks = set(_WORD_RE.findall(line.lower()))
    # Pull quarter tokens that the len>=4 word regex would miss (q1-q4 are 2 chars).
    for m in re.finditer(r"q[1-4]", line.lower()):
        toks.add(m.group(0))
    return toks


def _summarize_env_basenames(
    basenames: set[str],
    criterion_text: str = "",
    cap: int = MAX_ENV_LINES,
) -> tuple[list[str], int]:
    """Collapse dated/numbered/quarterly env basenames into compact groups so a 794-file
    environment fits in an LLM prompt without losing the meaningful source documents.

    Returns (lines, total_omitted_after_cap). Each line is one of:
      - a single basename (a family with exactly one member)
      - a collapsed family: 'bank_statement_*.pdf (12 files: bank_statement_2021-01.pdf,
        ...)' with up to 6 example members

    Lines are RELEVANCE-RANKED before the cap: a line whose tokens share any token with the
    criterion descriptions (e.g. 'q2' matching a criterion's 'Q2/Q3 count conflict', or
    'sprint' matching 'Sprint 16 status') is promoted to the front, so the implied-source
    candidates the LLM most needs to see survive the cap even when the environment carries
    hundreds of unrelated dated logs. Within the same relevance band, larger families come
    first (one line conveys N siblings), then alphabetical. Pure-noise singletons
    (.DS_Store, Thumbs.db, desktop.ini, .localized) are dropped outright."""
    noise = {".ds_store", "thumbs.db", "desktop.ini", ".localized"}
    crit_tokens = _line_tokens(criterion_text)

    groups: dict[tuple[str, str], list[str]] = {}
    for b in sorted(basenames):
        if b in noise:
            continue
        key = _family_key(b)
        groups.setdefault(key, []).append(b)

    built: list[tuple[int, str]] = []  # (relevance, line)
    for (stem, ext), members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0][0])):
        members = sorted(members)
        if len(members) == 1:
            line = members[0]
        else:
            shown = members[:6]
            tail = "" if len(members) <= 6 else f", ... (+{len(members) - 6} more)"
            line = f"{stem}_*.{ext} ({len(members)} files: {', '.join(shown)}{tail})"
        ltoks = _line_tokens(line)
        # Relevance: count of distinct tokens shared with the criterion text. Quarter
        # tokens (q1-q4) and >=4-char words both count.
        rel = len(ltoks & crit_tokens)
        built.append((rel, line))

    # Relevance band first (descending), then family size is already baked into the sort
    # above; re-sort by (-relevance, original order) to keep families-before-singletons
    # within each band.
    built.sort(key=lambda t: -t[0])
    lines = [line for _, line in built]
    if len(lines) > cap:
        omitted = len(lines) - cap
        lines = lines[:cap]
    else:
        omitted = 0
    return lines, omitted


# ---------------------------------------------------------------------------
# instruction.md: deliverable-filename extraction (label which files= entries are the
# graded OUTPUT, never a verifying source -- same extraction judge_scope_over_inclusion
# uses, kept local to avoid importing the over-inclusion check)
# ---------------------------------------------------------------------------

_EKW_DELIVERABLE_HEADING_RE = re.compile(
    r"produce the following deliverables in [^\n:]*:",
    re.IGNORECASE | re.MULTILINE,
)


def _deliverable_section(instr_text: str) -> str:
    """instruction.md text from the first deliverable-naming marker onward (the solver's
    own OUTPUT-naming section). Same extraction judge_scope_over_inclusion_check.py's
    _deliverable_section uses; re-implemented locally so this check depends only on the
    breadth check's canonical helpers, not on the over-inclusion check."""
    m = DELIVERABLE_MARKER_RE.search(instr_text)
    if not m:
        m = _EKW_DELIVERABLE_HEADING_RE.search(instr_text)
    return instr_text[m.start():] if m else ""


def _instruction_deliverable_filenames(instr_text: str) -> set[str]:
    """Every filename-shaped token in instruction.md's deliverable-naming section,
    lowercased. The set the solver is told to PRODUCE -- these files= entries are the
    graded output, not sources the judge can verify claims against."""
    section = _deliverable_section(instr_text)
    return {m.group(0).lower() for m in FILENAME_RE.finditer(section)}


# ---------------------------------------------------------------------------
# Per-group collection: gather files= + criteria into a serializable shape for the prompt
# ---------------------------------------------------------------------------


def _collect_svc_pc_groups(task_dir: Path) -> tuple[list[dict], list[str]]:
    """Return (groups, parse_errors). Each group dict: {label, files (basenames),
    deliverable_files (basenames in files that match instruction deliverables),
    criteria: [{name, description, weight}]}. Mirrors the breadth check's group
    iteration but keeps the description verbatim for the LLM."""
    instr = _load_instruction(task_dir)
    deliverable_names = (
        _instruction_deliverable_filenames(instr) if instr is not None else set()
    )
    out: list[dict] = []
    errs: list[str] = []
    for g in _load_svc_pc_groups(task_dir):
        if g["parse_error"]:
            errs.append(f"{g['path']}: judge.toml failed to parse: {g['parse_error']}")
            continue
        files_b = [_basename(f) for f in g["files"] if f]
        out.append(
            {
                "label": g["path"],
                "files": files_b,
                "deliverable_files": sorted(set(files_b) & deliverable_names),
                "criteria": [
                    {
                        "name": c.get("name") or "?",
                        "description": c.get("description") or "",
                        "weight": c.get("weight"),
                    }
                    for c in g["criteria"]
                ],
                "weight_sum": _weight_sum(g["criteria"]),
            }
        )
    return out, errs


def _collect_ekw_groups(task_dir: Path) -> tuple[list[dict], list[str]]:
    """EKW: each verifier is its own group (no judge.toml-style shared scope). Same
    per-verifier convention judge_scope_over_inclusion_check.py's check_task_ekw uses."""
    instr = _load_instruction(task_dir)
    deliverable_names = (
        _instruction_deliverable_filenames(instr) if instr is not None else set()
    )
    criteria = load_ekw_criteria(task_dir)
    errs: list[str] = []
    parse_errs = [c for c in criteria if c["name"] == "__parse_error__"]
    if parse_errs:
        for c in parse_errs:
            errs.append(c["description"])
        return [], errs
    if not criteria:
        errs.append("tests/verifier.json has zero verifiers")
        return [], errs
    # Group criteria by their verifier group label.
    by_group: dict[str, list[dict]] = {}
    group_files: dict[str, list[str]] = {}
    for c in criteria:
        label = c.get("group") or "verifier"
        by_group.setdefault(label, []).append(
            {
                "name": c.get("name") or "?",
                "description": c.get("description") or "",
                "weight": c.get("weight"),
            }
        )
        group_files.setdefault(label, [_basename(f) for f in (c.get("files") or []) if f])
    out: list[dict] = []
    for label, crits in by_group.items():
        files_b = group_files.get(label, [])
        out.append(
            {
                "label": label,
                "files": files_b,
                "deliverable_files": sorted(set(files_b) & deliverable_names),
                "criteria": crits,
                "weight_sum": _weight_sum(crits),
            }
        )
    return out, errs


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    task_id: str,
    groups: list[dict],
    env_lines: list[str],
    env_omitted: int,
    env_total: int,
) -> str:
    """Assemble the full user prompt. Each group's files= list and criteria are embedded
    directly. The summarized environment list is auxiliary context that lets the LLM
    confirm an implied source was withheld (present in env, absent from files=) rather
    than absent from the task entirely."""
    group_blocks: list[str] = []
    n_criteria_total = 0
    for gi, g in enumerate(groups, 1):
        n_criteria_total += len(g["criteria"])
        files_listing = ", ".join(g["files"]) if g["files"] else "(empty)"
        deliv_listing = (
            ", ".join(g["deliverable_files"]) if g["deliverable_files"] else "(none identified)"
        )
        crit_lines: list[str] = []
        for ci, c in enumerate(g["criteria"], 1):
            crit_lines.append(
                f"  [{gi}.{ci}] criterion '{c['name']}': {c['description']}"
            )
        group_blocks.append(
            f"--- GROUP {gi}: {g['label']} ---\n"
            f"Judge files= (the ONLY files this judge can open): {files_listing}\n"
            f"Of those, the graded DELIVERABLE output (NOT a verifying source): "
            f"{deliv_listing}\n"
            f"Criteria ({len(g['criteria'])}):\n" + "\n".join(crit_lines)
        )

    env_block = "\n".join(env_lines) if env_lines else "(no environment files found)"
    if env_omitted:
        env_block += f"\n[... plus {env_omitted} more files omitted to fit; mostly dated logs/exports]"

    prompt = f"""== TASK: {task_id} ==

== JUDGE GROUPS ({len(groups)} group(s), {n_criteria_total} criteria total) ==
{chr(10).join(group_blocks)}

== AVAILABLE ENVIRONMENT FILES ({env_total} total; summarized, dated/numbered families collapsed) ==
These are the source files that EXIST in the task. A file here that is NOT in a group's
files= list was WITHHELD from that judge -- it exists, the solver had it, but the judge
cannot open it. Use this list to confirm an implied source was actually withheld rather
than absent from the task entirely (a criterion referencing a source that does not exist
anywhere is a different defect, not this one).

{env_block}

== WHAT TO CHECK ==
For each criterion, ask: does its Expected text (the "Expected: ..." clause, and the
requirement text before it) reference a specific fact, document, or comparison that the
judge would need to verify against a SOURCE file -- and is that source ABSENT from the
criterion's own group's files= list?

A criterion is UNDER-INCLUSIVE (flag it) when ALL of these hold:
1. Its wording references a SPECIFIC external fact, document, or comparison that implies
   a source the judge must check against. Strong tells:
   - a concrete number/count the deliverable must match ("Expected: 80 vs 25", "Expected:
     2,186,512", "Expected: 12 monthly balances") that must come from a source record;
   - a named or described source document ("the source workbook", "the catalog page",
     "the records", "the backlog", "the incident log") the judge must open;
   - a cross-document comparison ("agrees with the package cash figure", "matches ...
     rather than the year being averaged") that requires both documents in view;
   - a specific event/episode tied to a named source ("the August Apex episode",
     "the Sprint 3 punt", "Sprint 16 status") that lives in a sprint/incident log.
2. NONE of the files in THAT group's files= list could plausibly contain or verify that
   fact. Reason from the filenames and the criterion's own wording: a Fulfillment_SOP.docx
   cannot verify product-catalog counts; an Inventory_Policy.docx cannot verify sprint
   backlogs; the deliverable itself (the graded output) is NEVER a verifying source.
3. (Strengthens the finding, not required) the implied source IS visible in the
   AVAILABLE ENVIRONMENT FILES list above -- confirming the source exists and was withheld
   from the judge rather than absent from the task.

A criterion is NOT under-inclusive (do NOT flag) when:
- It grades the deliverable's internal coherence, structure, presence, or reasoning:
  "Expected: present", "Expected: stated", "Expected: computed", "Expected: tabular",
  "Expected: none found", "Expected: Yes" -- these check the deliverable's own content,
  not an external fact, so no source file is needed.
- Its referenced fact could plausibly be IN one of the listed files. If a criterion says
  "per the Fulfillment SOP" and Fulfillment_SOP.docx IS in files=, that is covered, not
  under-inclusive. Do not flag a criterion just because an additional source would help;
  flag only when NO listed file could verify the referenced fact.
- It asks for a reasoned judgment call, recommendation, or design choice the solver makes
  ("recommends a single documented intake queue", "an overall judgment that ..."). These
  are not verifiable against a source file at all; they are the deliverable's own
  reasoning.
- The files= list already includes the implied source (even under a different name). When
  uncertain whether a listed file could contain the fact, do not flag.

== METHODOLOGY ==
1. For each group, read its files= list and note which are the deliverable output (never a
   verifying source) versus pre-existing sources the judge was given.
2. For each criterion, identify whether its Expected text references a specific external
   fact/document/comparison. If it only checks the deliverable's own content, skip it.
3. If it does reference an external fact, check whether any file in THAT group's files=
   (excluding the deliverable) could plausibly contain it. If none could, and ideally the
   implied source appears in the AVAILABLE ENVIRONMENT FILES list, flag it.
4. For each flagged criterion, record: the group's index (the GROUP N header), the
   criterion name, a verbatim quote of the Expected text (or the requirement text that
   references the unverifiable fact), the implied source (name it from the environment
   list when visible, else describe it), and your reason explaining why no listed file
   could verify it.

== OUTPUT FORMAT (strict JSON, no prose before or after) ==
Return a single JSON object with this exact shape:
{{
  "verdict": "clean" or "under_inclusive",
  "findings": [
    {{
      "group_index": 1,
      "criterion": "l2-02-r08",
      "quote": "Preserves the Q2/Q3 count conflict and other unresolved evidence limitations. Expected: 80 vs 25 unresolved.",
      "implied_source": "Product_Catalog_Q2.pdf, Product_Catalog_Q3.pdf",
      "reason": "The Q2/Q3 count conflict (80 vs 25) is a product-catalog count the judge must verify against the Q2 and Q3 catalogs; files= contains only the memo plus Fulfillment_SOP.docx and Inventory_Policy.docx, none of which is a product catalog. The catalogs exist in the environment list but were withheld."
    }}
  ]
}}

Rules:
- Output ONLY the JSON object. No markdown code fences, no prose, no explanation before or after.
- "verdict" is "clean" if zero findings, "under_inclusive" if one or more.
- "group_index" is the 1-based GROUP N index from the prompt (integer).
- "criterion" is the criterion's name as shown (e.g. "l2-02-r08").
- Every finding MUST include a verbatim "quote" from the criterion's own text (the Expected
  clause or the requirement sentence that references the unverifiable fact).
- Every finding MUST include "implied_source": name the source file(s) from the
  environment list when visible, otherwise describe the source the criterion implies.
- Every finding MUST include "reason": explain which specific fact is unverifiable and why
  no file in that group's files= list could contain it.
- If the files= list or criteria text is empty, return
  {{"verdict": "clean", "findings": [], "content_unavailable": true, "unavailable_reason": "what was missing"}}.
- Do not invent defects. If you are not confident a criterion references an unverifiable
  external fact, do not flag it.
"""
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS] + "\n[... PROMPT TRUNCATED ...]\n"
    return prompt


# ---------------------------------------------------------------------------
# Response parsing (same proven JSON-extraction logic every LLM check uses)
# ---------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
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


def _normalize_finding(f: dict, groups: list[dict]) -> dict | None:
    """Validate and normalize one finding. Returns None if too malformed (missing quote
    or criterion). Maps the 1-based group_index back to the group label so a reviewer can
    locate the judge.toml/verifier the finding is about."""
    if not isinstance(f, dict):
        return None
    criterion = (f.get("criterion") or "").strip()
    quote = (f.get("quote") or "").strip()
    if not criterion or not quote:
        return None
    reason = (f.get("reason") or "").strip()
    implied_source = (f.get("implied_source") or "").strip()
    gidx = f.get("group_index")
    label = "?"
    if isinstance(gidx, int) and 1 <= gidx <= len(groups):
        label = groups[gidx - 1]["label"]
    message = f"[judge_scope_under_inclusion] {label}/{criterion}: {quote[:120]}"
    return {
        "kind": "judge_scope_under_inclusion",
        "severity": "warn",
        "group": label,
        "criterion": criterion[:200],
        "quote": quote[:2000],
        "expected_text": quote[:2000],
        "implied_source": implied_source[:500],
        "reason": reason[:2000],
        "message": message[:500],
    }


def build_task_result_from_response(
    task_id: str,
    parsed: dict,
    fmt: str,
    groups: list[dict],
    judge_files: list[str],
    env_total: int,
    parse_errors: list[str],
    backend_used: str,
    prompt_chars: int,
) -> dict:
    n_criteria = sum(len(g["criteria"]) for g in groups)
    result = {
        "task_id": task_id,
        "status": "pass",
        "task_format": fmt,
        "n_groups": len(groups),
        "n_criteria": n_criteria,
        "judge_files": judge_files,
        "env_file_count": env_total,
        "parse_errors": parse_errors,
        "errors": [],
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
            result["errors"].append(f"raw_response (truncated): {parsed['raw_response']}")
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
        nf = _normalize_finding(f, groups)
        if nf is not None:
            findings.append(nf)
    result["findings"] = findings
    result["n_findings"] = len(findings)
    result["n_warn"] = len(findings)
    # Same "candidate, not verdict" posture as every other LLM check: warn, never fail.
    result["status"] = "warn" if findings else "pass"
    return result


# ---------------------------------------------------------------------------
# Per-task audit
# ---------------------------------------------------------------------------


def _detect_format(task_dir: Path) -> str:
    if _has_svc_pc_config(task_dir):
        return "svc_pc"
    if has_ekw_config(task_dir):
        return "ekw"
    return "none"


def audit_task(task_dir: Path, dry_run: bool = False, timeout: int = 180) -> dict:
    """Audit one task for judge-scope under-inclusion. Returns the per-task result dict.
    Never raises: every failure path produces an error/skip result, not a crash."""
    task_id = task_dir.name
    fmt = _detect_format(task_dir)
    if fmt == "none":
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": "none",
            "n_groups": 0,
            "n_criteria": 0,
            "judge_files": [],
            "env_file_count": 0,
            "parse_errors": [],
            "errors": ["not a recognized task format (no judge.toml or verifier.json)"],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    if fmt == "svc_pc":
        groups, perrs = _collect_svc_pc_groups(task_dir)
    else:
        groups, perrs = _collect_ekw_groups(task_dir)

    if perrs and not groups:
        return {
            "task_id": task_id,
            "status": "error",
            "task_format": fmt,
            "n_groups": 0,
            "n_criteria": 0,
            "judge_files": [],
            "env_file_count": 0,
            "parse_errors": perrs,
            "errors": [],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": False,
        }
    if not groups:
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_groups": 0,
            "n_criteria": 0,
            "judge_files": [],
            "env_file_count": 0,
            "parse_errors": perrs,
            "errors": ["no judge groups with parseable criteria found"],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    env = _env_basenames(task_dir, ekw=(fmt == "ekw"))
    # Relevance-rank the env summary against the criteria text so implied-source candidates
    # (Product_Catalog_Q2 matching a "Q2/Q3" criterion, Sprint_01_Backlog matching a "Sprint
    # 16" criterion) survive the cap on a 794-file environment.
    criterion_text = " ".join(
        c.get("description", "") for g in groups for c in g["criteria"]
    )
    env_lines, env_omitted = _summarize_env_basenames(env, criterion_text)
    judge_files = sorted({f for g in groups for f in g["files"]})

    prompt = build_prompt(task_id, groups, env_lines, env_omitted, len(env))
    prompt_chars = len(prompt)

    if dry_run:
        result: dict = {
            "task_id": task_id,
            "status": "pass",
            "task_format": fmt,
            "n_groups": len(groups),
            "n_criteria": sum(len(g["criteria"]) for g in groups),
            "judge_files": judge_files,
            "env_file_count": len(env),
            "parse_errors": perrs,
            "errors": [],
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

    try:
        raw_response = call_llm(prompt, SYSTEM_PROMPT, timeout=timeout)
        backend_used = "cli_or_http"
    except LLMBackendError as exc:
        return {
            "task_id": task_id,
            "status": "error",
            "task_format": fmt,
            "n_groups": len(groups),
            "n_criteria": sum(len(g["criteria"]) for g in groups),
            "judge_files": judge_files,
            "env_file_count": len(env),
            "parse_errors": perrs,
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
        groups,
        judge_files,
        len(env),
        perrs,
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
    """Programmatic entry point (the orchestrators use this). Returns the report dict with
    a 'results' list of per-task dicts. Tasks run on a thread pool since each LLM call is
    I/O-bound. Same structure rubric_overspecification_check.py / golden_groundedness_check.py
    use."""
    dirs = find_task_dirs(root, task_ids, id_prefix)
    t0 = time.time()

    from concurrent.futures import ThreadPoolExecutor

    def _safe_audit_task(d: Path) -> dict:
        try:
            return audit_task(d, dry_run=dry_run, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - deliberately broad
            return {
                "task_id": d.name,
                "status": "error",
                "task_format": "none",
                "n_groups": 0,
                "n_criteria": 0,
                "judge_files": [],
                "env_file_count": 0,
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
    n_skip = sum(r["status"] == "skip" for r in results)
    n_error = sum(r["status"] == "error" for r in results)

    report = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": str(root),
        "dry_run": dry_run,
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_warn": n_warn,
        "n_skip": n_skip,
        "n_error": n_error,
        "results": results,
        "seconds": round(time.time() - t0, 1),
    }

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "judge_scope_under_inclusion.json"
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
        crit = first.get("criterion", "?")
        print(f"  WARN  {tid:<18} {n} finding(s): {crit}", file=sys.stderr)
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
