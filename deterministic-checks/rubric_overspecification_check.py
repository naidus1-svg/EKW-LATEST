#!/usr/bin/env python3
"""Rubric over-specification check: does each criterion's pinned
value/count/name/format have instruction-level support, or did the criterion
author invent a specificity the instruction never asked for?

Why this exists
---------------
A prior round's coverage-gap analysis (see
ekw/pipeline-mirror/khiem-202-data/comprehensive-review-qc-feedback-2026-09-15/
coverage-cov4-SVC-PC-33-8-0.md, root cause RC2) found that 5 of 9 real tasks
reviewed have criteria that grade content the instruction never actually
requested, or pin exact values/names/counts the instruction deliberately left
open or flexible. The real evidence, from the staged SVC-PC-33-8-0 task:

  - The rubric requires exactly 4 named people (Jessica Liu, Priya Patel,
    David Nguyen, James Okafor) when the instruction says "from the people we
    currently have" (open-ended, not a fixed roster of 4).
  - The rubric requires exactly 5 checks when the instruction says "I would
    rather run four checks that actually happen than twelve that do not"
    (the instruction's stated preference is four, the rubric pins five).
  - The rubric requires tolerance=None when the instruction says "James is
    working out how that comparison is built and what the tolerance should be"
    (the instruction explicitly defers this value to James, the rubric pins
    it anyway).

This is the OPPOSITE direction of `instruction_requirement_coverage_check.py`
(same directory): that check asks "does every instruction requirement have a
covering criterion?" This check asks "does every criterion's pinned
specificity have instruction-level support, or did the rubric narrow what the
instruction left open?" The two are structural mirror images.

It is also distinct from `content_audit_check.py` (Check A, same directory).
Check A's six patterns all check INTERNAL consistency among the three texts
(prompt/golden/rubric). Pattern 1 ("rubric asks for a fact neither document
establishes") does NOT fire on over-specification because the golden typically
DOES establish the specific value (the golden made the design choice the
rubric then locked in). Pattern 6 ("prompt-rubric contradiction on sourced
vs invented") does NOT fire because the instruction leaves choices open rather
than explicitly forbidding invention. Over-specification is a different defect:
the rubric treats the golden's private design choice as a binding requirement
the instruction never made. That is why this is a separate check, not a 7th
pattern inside content_audit_check.py. The existing check's prompt/validation
is tightly coupled to exactly six patterns (PATTERN_NAMES keys 1-6,
_normalize_finding rejects anything outside 1-6, the system prompt says
"exactly six defect patterns, no more, no less"); extending it would change a
calibrated, in-production check's semantics. A sibling script avoids that
risk and mirrors instruction_requirement_coverage_check.py's own sibling
pattern for the reverse direction.

This is LLM-judgment territory, like Check A. The question "did the
instruction leave this dimension open or did it specifically require this
value?" requires semantic understanding, not keyword matching. This script
reuses `tools/llm_backend.py`'s `call_llm()` (the same backend Check A uses)
and the text-extraction helpers from `answer_key_rubric_leak_check.py` (the
same extraction path Check A uses), so the instruction, golden, and rubric
text sent to the LLM are byte-identical to what Check A already reads.

Output shape
------------
Per-task result dict (the same verdict + findings shape every other check in
this folder produces, so it merges into svc_run_checks.py / ekw_run_checks.py
the same way):

    {
        "task_id": "SVC-PC-33-8-0",
        "status": "pass" | "warn" | "skip" | "error",
        "task_format": "svc_pc" | "ekw" | "none",
        "n_criteria": 50,
        "n_golden_files": 1,
        "parse_errors": [],
        "errors": [],
        "findings": [
            {
                "kind": "rubric_overspecification",
                "overspec_type": "count_pinned",
                "severity": "warn",
                "criterion": "deliverables_01/r012",
                "message": "one-line summary",
                "quote": "verbatim text from the rubric",
                "pinned_value": "what the rubric pins",
                "instruction_text": "the instruction language that leaves it open",
                "evidence": "why this is over-specified"
            }
        ],
        "n_findings": 0,
        "n_warn": 0,
        "llm_backend": "cli" | "http" | "dry_run" | "none",
        "prompt_chars": 12345,
        "content_unavailable": false
    }

Severity is always "warn" for every finding, never "fail". This matches Check
A's own "candidate, not verdict" posture (see content-audit/SKILL.md: "treat
every finding this skill produces as a candidate for a human or a second
independent pass to confirm, not as a verdict"). The task-level status mirrors
that: "warn" if findings exist, "pass" if clean. A finding never hard-gates a
task on its own.

LLM backend
-----------
Uses `tools/llm_backend.call_llm()` which tries the Claude Code CLI first
(free under a Max plan, no credential handling here) then falls back to a
generic HTTP call using LLM_API_KEY / LLM_API_BASE_URL / LLM_API_PROVIDER /
LLM_API_MODEL env vars the CALLER sets. This script never hardcodes,
generates, guesses, or defaults a real key or any of those values. For
verifying the request shape without a real key, pass --dry-run: it builds
the prompt and calls build_http_request() (which needs the env vars present
but does not send anything) to show the exact request, or prints the prompt
alone if the env vars are absent.

Known operational gotchas (from testing content_audit_check.py's real LLM
path, apply here too if you make real LLM calls during testing):
  - `LLM_API_MAX_TOKENS` must be set to roughly 32000 (not the 4096 library
    default) for a reasoning-heavy model on a real audit-sized prompt, or the
    call silently returns empty content. This was already fixed in
    tools/llm_backend.py itself via a `timeout` parameter and better defaults
    are documented in its own docstring.
  - If `claude` CLI happens to be on PATH, `call_llm()` tries it before any
    configured HTTP backend unless `LLM_BACKEND_FORCE=http` is set. Set that
    env var explicitly if you do any real-call testing to avoid an unexpected
    nested-CLI hang.
  - If no real LLM backend is configured, test via `--dry-run` and
    hand-written response fixtures (see rubric_overspecification_check_test.py,
    same directory). Do not fabricate a real LLM call result, and do not add
    any real credential.

CLI
---
    python rubric_overspecification_check.py --all --root DIR --out results.json
    python rubric_overspecification_check.py SVC-PC-33-8-0 --root DIR --out results.json
    python rubric_overspecification_check.py SVC-PC-33-8-0 --root DIR --out results.json --dry-run
    python rubric_overspecification_check.py SVC-PC-33-8-0 --root DIR --out results.json --timeout 300

Stdlib only for the runner; openpyxl / python-docx are pulled in by the
text-extraction imports from answer_key_rubric_leak_check.py (same as Check A).
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

# Root cause of the empty-completion failures found during real verification (2026-09-16,
# svc-dataos-failure-mode-tracker row 15): the configured backend (glm-5.2, an OpenAI-compatible
# reasoning model) spends hidden reasoning tokens against the SAME max_tokens ceiling the visible
# answer draws from. Confirmed directly against the real HTTP response, not inferred: at the
# library default of 4096, a real audit-sized prompt against this check came back
# finish_reason="length", completion_tokens=4096 (exactly the ceiling), content_len=0 -- every
# token was spent reasoning, none were left to write the answer. This module's own docstring
# already named "roughly 32000" as the number that works and claimed it "was already fixed in
# tools/llm_backend.py itself" -- that claim was false (llm_backend.py had no override point that
# reached this far), so the fix belongs here instead: setdefault, not a hard override, so an
# operator who has deliberately set a different budget is never silently overridden. Verified at
# 32000 against the same real prompt this failed against at 4096.
os.environ.setdefault("LLM_API_MAX_TOKENS", "32000")

from tools.llm_backend import call_llm, build_http_request, LLMBackendError

# Reuse the text-extraction and rubric-loading helpers from
# answer_key_rubric_leak_check.py rather than reimplementing them. Those
# functions (extract_file_text, find_golden_files, load_criteria_for_task) are
# the same extraction path Check A already calibrated against the real corpus,
# so the golden text and rubric criteria this check sends to the LLM are
# byte-identical to what Check A reads.
from answer_key_rubric_leak_check import (
    extract_file_text,
    find_golden_files,
    load_criteria_for_task,
)

# Windows console defaults to cp1252; force UTF-8 so non-cp1252 characters in
# real rubric/golden text never crash a batch run. Same line every other check
# in this folder carries.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The over-specification types the LLM is asked to classify each finding into.
# These help a human reviewer triage the finding by defect shape. A finding
# with an unrecognized or missing overspec_type is still kept (defaulting to
# "overspecification") rather than dropped, since the type is a categorization
# aid, not a validation gate. The important validation is that the finding
# carries a verbatim quote and evidence (see _normalize_finding).
OVERSPEC_TYPES = {
    "count_pinned": "count_pinned",
    "name_pinned": "name_pinned",
    "value_pinned": "value_pinned",
    "format_pinned": "format_pinned",
}

# Cap the prompt at this many characters of golden text so a very large
# workbook does not blow the LLM context window. The instruction.md and rubric
# criteria are sent in full (they are always small); only the golden text is
# truncated, with a visible truncation marker so the LLM knows it is seeing a
# partial extract. Same cap Check A uses.
MAX_GOLDEN_CHARS = 60000


SYSTEM_PROMPT = (
    "You are a QC auditor for Harbor-shaped grading tasks. You read three "
    "texts (a task instruction, a golden/reference answer, and grading "
    "rubric criteria) and judge whether each rubric criterion pins a "
    "specific value, count, name, or format that the instruction left open, "
    "flexible, or contradicted. You report findings as strict JSON. You do "
    "not fix, rewrite, or suggest fixes. You only flag over-specification you "
    "can quote exact text for. If you are not confident a criterion is "
    "over-specified, do not flag it. A false positive wastes a human "
    "reviewer's time; a false negative is caught by the next QC layer. "
    "Prefer precision over recall."
)


# ---------------------------------------------------------------------------
# Text extraction (same helpers Check A uses, same semantics)
# ---------------------------------------------------------------------------


def read_instruction_md(task_dir: Path) -> str:
    """Read instruction.md. Returns empty string if absent (the caller decides
    whether that is a skip or an error)."""
    p = task_dir / "instruction.md"
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def collect_golden_text(task_dir: Path, fmt: str) -> tuple[str, list[str]]:
    """Extract readable text from every supported golden file under the task's
    solution directory. Returns (combined_text, errors). Each file's text is
    prefixed with a '--- file: <name> ---' marker so the LLM can cite which
    file a finding comes from. Never raises: an unparseable file contributes
    an error string and no text rather than crashing the task. Same logic
    Check A uses."""
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


def collect_rubric_text(criteria: list[dict]) -> str:
    """Format criteria as labeled lines: '[group/name] description'. The
    bracketed label is what the LLM returns in the 'criterion' field of each
    finding, so it maps straight back to the exact judge.toml entry. Same
    format Check A uses."""
    lines: list[str] = []
    for c in criteria:
        label = f"{c.get('judge_group', '?')}/{c.get('name', '?')}"
        desc = c.get("description", "")
        lines.append(f"[{label}] {desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    task_id: str,
    instruction: str,
    golden_text: str,
    rubric_text: str,
) -> str:
    """Assemble the full user prompt. The over-specification definition and
    the four sub-types are embedded directly so the LLM has the full recipe
    without needing to read any external doc."""
    return f"""== TASK: {task_id} ==

== INSTRUCTION (instruction.md) ==
{instruction}

== GOLDEN ANSWER (extracted from solution files; ONE valid implementation, not the authority) ==
{golden_text or "[no golden files found or all unreadable]"}

== RUBRIC CRITERIA (judge.toml / verifier.json) ==
{rubric_text or "[no criteria parsed]"}

== WHAT TO CHECK ==
For each rubric criterion, ask: does the INSTRUCTION'S OWN TEXT specifically
support the exact value, count, name, or format the criterion pins, or did the
instruction leave that dimension open, flexible, or contradicted?

The instruction is the authority for what a solver MUST produce. The golden
answer is ONE valid implementation of the instruction. The golden's specific
design choices (which person to name, how many checks to propose, what value
to set a tolerance to) are not binding on other solvers unless the instruction
required them. A criterion that pins the golden's specific design choice as a
requirement, when the instruction left that choice open or expressed a
different preference, is OVER-SPECIFIED: a correct, alternative solution that
makes a different valid choice the instruction allowed would be rejected by
that criterion.

This is NOT the same as Check A's pattern 1 ("rubric asks for a fact neither
document establishes"). The golden typically DOES establish the specific
value. The defect is that the rubric treats the golden's private choice as a
binding requirement the instruction never made. It is also NOT pattern 6
("prompt forbids inventing"). The instruction does not forbid invention; it
leaves choices open, which is ambiguity, not prohibition.

== THE FOUR OVER-SPECIFICATION TYPES ==

1. count_pinned: The criterion requires a specific count (exactly N items,
   people, checks, rows, columns) that the instruction left open or
   contradicted with its own stated number. Example: instruction says "I
   would rather run four checks" and the rubric requires "Each of the 5
   checks." Example: instruction says "from the people we currently have"
   (no count given) and the rubric requires exactly 4 named owners.

2. name_pinned: The criterion requires specific named entities (person
   names, place names, system names) that the instruction did not name. The
   instruction may require naming someone ("by name") without specifying WHO.
   Pinning specific names the instruction never listed is over-specification.
   Example: instruction says "from the people we currently have" and the
   rubric requires "Jessica Liu, Priya Patel, David Nguyen, or James Okafor."

3. value_pinned: The criterion requires a specific numeric value, threshold,
   tolerance, or setting that the instruction explicitly deferred to someone
   else or left open. Example: instruction says "James is working out what the
   tolerance should be" and the rubric requires "tolerance=None."

4. format_pinned: The criterion requires a specific file path, folder
   structure, naming convention, check title, or format string that the
   instruction never specified. Example: the instruction gives no path and
   the rubric requires "Company Shared Drive/Operations/Metric Checks/
   YYYY-MM/."

== METHODOLOGY (follow in order) ==
1. Read the INSTRUCTION in full first. Note every requirement it states and
   every dimension it leaves open, flexible, or defers to someone else. Pay
   special attention to language like "from the people we currently have"
   (open roster), "I would rather run four" (stated preference, not a hard
   count), "James is working out the tolerance" (deferred value), or "you
   decide how often it runs" (explicitly left to the solver).
2. Read every RUBRIC CRITERION. For each, identify whether it pins a specific
   value, count, name, or format. Then check: does the instruction's text
   specifically support that pinned value (not just the general requirement
   area, but the specific choice)? If the instruction left it open, was
   flexible about it, or stated a different value, flag it.
3. Read the GOLDEN ANSWER for context: it shows what design choices were
   actually made. But remember: the golden is ONE valid implementation. The
   question is whether the INSTRUCTION required the golden's specific choice,
   not whether the golden happened to make it.
4. For each criterion you flag, record: the overspec_type (1-4), the
   criterion's bracketed label, a verbatim quote of the pinned text from the
   rubric, the specific pinned value, the instruction text that leaves it
   open or contradicts it, and your evidence explaining the gap.

== IMPORTANT: do NOT flag these ==
- A criterion whose pinned value IS specifically supported by instruction
  text. If the instruction says "revenue, order count, customer count, and
  support ticket volume" and the criterion requires exactly those four
  metrics, that is SUPPORTED, not over-specified.
- A criterion that requires a general property the instruction asked for
  (e.g. "names a person as owner") even if the specific name differs. The
  over-specification is in pinning the SPECIFIC name, not in requiring a name.
- A criterion that elaborates a source reference (e.g. "Shopify orders
  export sum of order-level Total") when the instruction mentions the source
  ("what Shopify says we sold"). Source elaboration is grounding, not
  over-specification, unless the rubric pins a specific value the instruction
  left open.
- A criterion whose specificity comes from the data structure, not a design
  choice (e.g. "4000 Sales Revenue" is the account number in QuickBooks, not
  a value the instruction deferred).

== OUTPUT FORMAT (strict JSON, no prose before or after) ==
Return a single JSON object with this exact shape:
{{
  "verdict": "clean" or "defective",
  "findings": [
    {{
      "overspec_type": "count_pinned",
      "severity": "warn",
      "criterion": "deliverables_01/r012",
      "quote": "the exact verbatim text from the rubric that pins the specificity",
      "pinned_value": "what the rubric pins (e.g. '5 checks', 'Jessica Liu, Priya Patel, David Nguyen, or James Okafor', 'tolerance=None')",
      "instruction_text": "the instruction language that leaves it open or contradicts it",
      "evidence": "why this is over-specified: explain the gap between what the instruction required and what the rubric pins"
    }}
  ]
}}

Rules:
- Output ONLY the JSON object. No markdown code fences, no prose, no explanation before or after.
- "verdict" is "clean" if zero findings, "defective" if one or more.
- "overspec_type" is one of: "count_pinned", "name_pinned", "value_pinned", "format_pinned".
- "severity" is always "warn".
- "criterion" is the bracketed label from the RUBRIC CRITERIA section (e.g. "deliverables_01/r012").
- Every finding MUST include a verbatim "quote" from the rubric's actual text, not a paraphrase.
- Every finding MUST include "pinned_value" naming what the rubric pins.
- Every finding MUST include "instruction_text" quoting the instruction language that leaves it open or contradicts it.
- Every finding MUST include "evidence" explaining the gap.
- If the instruction, golden, or rubric text is empty or unreadable, return {{"verdict": "clean", "findings": [], "content_unavailable": true, "unavailable_reason": "what was missing"}}.
- Do not invent defects. If you are not confident a criterion is over-specified, do not flag it.
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
    None if the finding is too malformed to use (missing quote).

    Unlike Check A's _normalize_finding (which drops findings with an invalid
    pattern number), this check keeps findings with an unrecognized or
    missing overspec_type by defaulting to "overspecification". The
    overspec_type is a categorization aid for human reviewers, not a
    validation gate. The important validation is that the finding carries a
    verbatim quote (without which a reviewer cannot locate the rubric text)."""
    if not isinstance(f, dict):
        return None
    quote = (f.get("quote") or "").strip()
    if not quote:
        return None
    evidence = (f.get("evidence") or "").strip()
    criterion = (f.get("criterion") or "").strip()
    pinned_value = (f.get("pinned_value") or "").strip()
    instruction_text = (f.get("instruction_text") or "").strip()
    overspec_type = (f.get("overspec_type") or "").strip()
    if overspec_type not in OVERSPEC_TYPES:
        overspec_type = "overspecification"
    message = f"[rubric_overspecification/{overspec_type}] {criterion}: {quote}"
    if pinned_value:
        message += f" (pins: {pinned_value})"
    return {
        "kind": "rubric_overspecification",
        "overspec_type": overspec_type,
        "severity": "warn",
        "criterion": criterion,
        "message": message[:500],
        "quote": quote[:2000],
        "pinned_value": pinned_value[:500],
        "instruction_text": instruction_text[:1000],
        "evidence": evidence[:2000],
    }


def build_task_result_from_response(
    task_id: str,
    parsed: dict,
    fmt: str,
    n_criteria: int,
    n_golden_files: int,
    parse_errors: list[str],
    extract_errors: list[str],
    backend_used: str,
    prompt_chars: int,
) -> dict:
    """Turn a parsed LLM response into the per-task result dict the orchestrator
    reads. Handles all three response shapes: clean, defective, and
    parse-error. Same structure Check A uses."""
    result = {
        "task_id": task_id,
        "status": "pass",
        "task_format": fmt,
        "n_criteria": n_criteria,
        "n_golden_files": n_golden_files,
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
            "golden text extraction failed for one or more files and the LLM "
            "did not report content_unavailable; treating as warn rather than "
            "a clean pass, since the audit may not have seen the real golden text"
        )
    return result


# ---------------------------------------------------------------------------
# Per-task audit
# ---------------------------------------------------------------------------


def audit_task(task_dir: Path, dry_run: bool = False, timeout: int = 180) -> dict:
    """Audit one task for rubric over-specification. Returns the per-task
    result dict. Never raises: every failure path (missing content, LLM
    error, parse error) produces a result dict with an error/skip status
    rather than crashing the batch."""
    task_id = task_dir.name
    criteria, parse_errors, fmt = load_criteria_for_task(task_dir)
    instruction = read_instruction_md(task_dir)
    golden_text, extract_errors = collect_golden_text(task_dir, fmt)
    rubric_text = collect_rubric_text(criteria)
    n_golden_files = len(find_golden_files(task_dir, fmt))

    # Content gate: if the instruction or rubric is absent, there is nothing
    # to audit. Over-specification is an instruction-vs-rubric check; without
    # both, there is no question to ask.
    if not instruction and not criteria:
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_criteria": len(criteria),
            "n_golden_files": n_golden_files,
            "parse_errors": parse_errors,
            "errors": ["instruction.md and rubric both absent; nothing to audit"],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }
    if not instruction:
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_criteria": len(criteria),
            "n_golden_files": n_golden_files,
            "parse_errors": parse_errors,
            "errors": [
                "instruction.md absent; cannot audit instruction-rubric alignment"
            ],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }
    if not criteria:
        return {
            "task_id": task_id,
            "status": "skip",
            "task_format": fmt,
            "n_criteria": 0,
            "n_golden_files": n_golden_files,
            "parse_errors": parse_errors,
            "errors": ["no rubric criteria parsed; cannot audit rubric specificity"],
            "findings": [],
            "n_findings": 0,
            "n_warn": 0,
            "llm_backend": "none",
            "prompt_chars": 0,
            "content_unavailable": True,
        }

    prompt = build_prompt(task_id, instruction, golden_text, rubric_text)
    prompt_chars = len(prompt)

    # Dry-run: build the prompt, optionally show the HTTP request shape, but
    # never make a real LLM call.
    if dry_run:
        result: dict = {
            "task_id": task_id,
            "status": "pass",
            "task_format": fmt,
            "n_criteria": len(criteria),
            "n_golden_files": n_golden_files,
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
            "n_golden_files": n_golden_files,
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
        n_golden_files,
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
    timeout: int = 180,
) -> dict:
    """Programmatic entry point (the orchestrators use this). Returns the
    report dict with a 'results' list of per-task dicts. Tasks run on a
    thread pool since each LLM call is I/O-bound (network or subprocess).
    Same structure Check A uses."""
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
                "n_criteria": 0,
                "n_golden_files": 0,
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
        out_path = out_dir / "rubric_overspecification.json"
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
        otype = first.get("overspec_type", "?")
        crit = first.get("criterion", "?")
        print(f"  WARN  {tid:<18} {n} finding(s): {otype} on {crit}", file=sys.stderr)
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
