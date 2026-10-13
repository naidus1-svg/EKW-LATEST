#!/usr/bin/env python3
"""Semantic consistency check: does a criterion's required answer follow from the task
instruction's own stated logic, or does it contradict it -- "verdict-flipping," the one
confirmed, unowned defect class in COVERAGE-MATRIX.md Part 4 that no deterministic script in
this folder can catch, because the mechanism requires reading two documents and reasoning
about entailment, not matching keywords, structure, or filenames.

Full design, evidence, and validation bar: `semantic-consistency-design-2026-09-14.md`
(721 lines, written before this harness, not revised to match it). This file implements that
design; where the two disagree, the design document is the source of truth and this docstring
should be corrected, not the other way round.

Status: harness built 2026-09-14. The `prompt-file` backend (this file's `prepare-stage1`,
`prepare-stage2`, and `ingest` subcommands) is code-complete. The `cli` backend (direct
`claude -p` invocation) is NOT implemented here -- it is blocked on the user completing
`claude /login` (design section 5.1), and is out of scope until that exists to test against.
Nothing in this file has been run against a real LLM response yet as of the initial commit;
see the accompanying validation run for whether it passed.

## Why "prompt-file" and not a bare skill or a live API call

Two hard constraints, both from the design document, both still true:

1. No paid Anthropic API usage. This process cannot embed an `ANTHROPIC_API_KEY` or call
   `anthropic.Anthropic()` directly -- see `~/.claude/hooks/block_paid_anthropic.py` and the
   project's own no-spend rule. The only Max-plan-compute paths are a Claude Code session
   (interactive or subagent) or the `claude` CLI under an interactive login, and the CLI path
   is blocked today (design 5.1).
2. The validation bar (design 7.1-7.4) needs machine-checkable output -- named criteria,
   verbatim quotes, a stated recall and false-positive rate, two-run stability agreement. A
   skill applied freehand by a session produces prose a human has to re-read for every
   property above; only a harness with a real JSON schema and a real quote-check can assert
   any of that mechanically.

So the harness owns everything deterministic (prompt construction from the exact templates
below, JSON schema validation, the verbatim-quote check, the downgrade rules, the two-run
stability merge, chunking, cost bookkeeping, and reporting) and delegates only the actual
entailment judgment to an LLM, via files on disk: `prepare-stage1`/`prepare-stage2` write a
prompt file; something else (a Claude Code session, or Sonnet subagents dispatched in
batches, per the design's recommendation) reads it and writes a matching `*.response.json`;
`ingest` reads the response, validates it byte-for-byte against the instruction text, applies
the downgrade rules, and produces the final per-task report. Every stage's prompt bytes are
identical regardless of who or what fills the response, so a future `cli` backend (once
`claude /login` exists) is a drop-in replacement for the human/subagent step, not a rewrite.

## Answer-key safety

Prompt and report files quote `Expected:` values by design (the whole point is comparing a
criterion's expected value against the instruction). They are QC-internal and must never be
solver-facing or committed under a task directory. `--out-dir` is refused if it resolves
inside `--root` (see `_refuse_out_dir_inside_root`). Default output root is
`_ekw_verification_reports/semantic_consistency/`, matching this folder's existing convention
(`extraction_groundedness_check.py` and friends do not write reports next to source tasks
either). Add `_ekw_verification_reports/semantic_consistency/**/*.prompt.md` to `.gitignore`
before committing any real run's output -- the prompts are QC-internal working files, not
source.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from ekw_verifier_json import has_ekw_config, load_ekw_criteria

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Matches certification_gate_check.py's MUST_PASS_RE exactly. Defined locally rather than
# imported: this script only needs the pattern, and importing a sibling top-level script (as
# opposed to the shared, dependency-free ekw_verifier_json.py) for one regex would make this
# file's own importability depend on certification_gate_check.py's, for no real benefit.
MUST_PASS_RE = re.compile(r"must[\s-]*pass", re.IGNORECASE)

# Design 3.4 originally set this to 40, estimating ~120 output tokens/criterion (design
# section 6.2). Real corpus data (2026-09-15, this session) contradicts that estimate: the
# 48-criterion chunk of SVC-PC-80-7-0 hit the CLI's 64,000 output-token ceiling and failed
# outright (real reasoning text per criterion runs far more verbose than the design's
# planning-figure estimate). Lowered to 15 with a large safety margin -- confirmed-successful
# real chunks ran 2 to 24 criteria with no output-limit failures, but 24 is close enough to
# whatever the real per-criterion rate is that a task with slightly more verbose criteria at
# the same count could still overflow. 15 leaves headroom even at several times the observed
# per-criterion byte rate. Chunk-size safety, not a design change to what's asked per chunk.
MAX_CHUNK_SIZE = 15

# ---------------------------------------------------------------------------
# Stage 1: ledger extraction
# ---------------------------------------------------------------------------

STAGE1_SYSTEM_PROMPT = """You are auditing a benchmark task's solver-facing instruction. Your only job in this step is
to extract every sentence in the instruction that states LOGIC a compliant solver must
apply: which outcomes are allowed, which source wins when sources conflict, what basis or
method sizes a number, what formula to use, what is in or out of scope, and where the
instruction explicitly leaves a decision open to the solver. Quote each verbatim. Do not
evaluate the task, do not propose answers, do not read into the instruction anything it does
not say. If the instruction states no such logic, say so."""

STAGE1_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string"},
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {
                        "enum": [
                            "allowed_outcome_enumeration",
                            "priority_or_conflict_rule",
                            "sizing_basis_or_method",
                            "formula",
                            "explicit_scope_or_prohibition",
                            "freedom_statement",
                            "other",
                        ]
                    },
                    "quote": {"type": "string"},
                    "paraphrase": {"type": "string"},
                    "governs": {"type": "string"},
                },
                "required": ["id", "kind", "quote", "paraphrase", "governs"],
            },
        },
        "rule_documents": {"type": "array", "items": {"type": "string"}},
        "no_rules_found": {"type": "boolean"},
    },
    "required": ["task_id", "rules", "rule_documents", "no_rules_found"],
}


def build_stage1_prompt(task_id: str, instruction_md: str) -> str:
    """Design section 4.1, verbatim. Returns one markdown file's full text: a SYSTEM section
    and a USER section, clearly delineated, so whoever fills the response (a session or a
    subagent) sees exactly what a `cli` backend would pass as --system-prompt and stdin,
    without this harness needing two separate files for the prompt-file backend."""
    user = f"""TASK: {task_id}
INSTRUCTION (verbatim, solver-facing):
<<<
{instruction_md}
>>>
Return JSON matching the schema. For each rule give: id (L1, L2, ...), kind, the verbatim
quote (an exact substring of the text above, no paraphrase inside the quote), a one-sentence
paraphrase, and the decision or value it governs. Under rule_documents list, by filename,
any file the instruction names as carrying rules the solver must follow (a policy excerpt,
terms, an agreement, a rate card). Set no_rules_found only if the rules list is empty."""
    return (
        f"# Stage 1 prompt: {task_id}\n\n"
        f"## SYSTEM\n\n{STAGE1_SYSTEM_PROMPT}\n\n"
        f"## USER\n\n{user}\n\n"
        f"## OUTPUT SCHEMA (write your answer as JSON matching this exactly, no other text)\n\n"
        f"```json\n{json.dumps(STAGE1_SCHEMA, indent=2)}\n```\n"
    )


# ---------------------------------------------------------------------------
# Stage 2: per-criterion entailment
# ---------------------------------------------------------------------------

STAGE2_SYSTEM_PROMPT = """You are auditing whether grading criteria agree with the instruction they grade against.
The grader that applies these criteria never sees the instruction; this audit is the only
place the two texts meet. For each criterion, decide whether the answer it requires is what
a solver who follows the instruction's stated logic would produce.

Rules:
1. Judge entailment, not truth. Do not decide whether the expected value is factually
   correct. Decide whether it FOLLOWS from the instruction's stated logic (the ledger plus
   the instruction text), CONTRADICTS it, or is NOT ADDRESSED by it.
2. A "contradicts" verdict needs three things: the instruction sentence quoted verbatim, the
   criterion's requirement quoted verbatim, and one sentence stating what a compliant solver
   would produce instead. Without all three, do not answer "contradicts".
3. If the instruction's own wording admits two or more reasonable readings that lead to
   different answers, and the criterion pays for only one, answer "ambiguous_instruction"
   and list the readings. A formula whose literal direction a practitioner would call
   backwards counts: say which reading is literal and which is the practical one.
4. If you find textual support for both "follows" and "contradicts" and the instruction plus
   the criteria cannot settle it, answer "contested", list both readings, and name the one
   fact that would settle it and where it lives (a named corpus file, the golden, or
   nowhere). Do not force a side.
5. If a criterion inherits its expected value from another criterion's assumption (a
   downstream figure computed from an upstream haircut or rate), name that criterion in
   depends_on and do not re-argue the upstream point.
6. If a criterion requires content the instruction never asks the solver to produce, set
   not_requested to true. That is reported separately; it is not a contradiction.
7. Do not assume the criterion author is right. Do not assume the instruction is right. Do
   not use outside knowledge of what the answer should be.
8. Every quote must be an exact substring of text you were given in this message. The
   harness rejects any quote it cannot find and downgrades the verdict.
9. Grade every criterion in the chunk, in the order given, one entry each."""

STAGE2_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {"type": "string"},
        "chunk": {"type": "integer"},
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string"},
                    "verdict": {
                        "enum": [
                            "follows",
                            "contradicts",
                            "ambiguous_instruction",
                            "contested",
                            "not_addressed",
                        ]
                    },
                    "shape": {
                        "enum": [
                            "allowed_outcome_enumeration",
                            "priority_or_conflict_rule",
                            "sizing_basis_or_method",
                            "formula",
                            "explicit_scope_or_prohibition",
                            "freedom_statement",
                            "other",
                            "none",
                        ]
                    },
                    "confidence": {"enum": ["high", "medium", "low"]},
                    "ledger_rule_ids": {"type": "array", "items": {"type": "string"}},
                    "instruction_quote": {"type": ["string", "null"]},
                    "criterion_quote": {"type": ["string", "null"]},
                    "compliant_solver_would_produce": {"type": ["string", "null"]},
                    "readings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "reading": {"type": "string"},
                                "consistent_with_criterion": {"type": "boolean"},
                            },
                            "required": ["reading", "consistent_with_criterion"],
                        },
                    },
                    "resolving_evidence": {
                        "type": ["object", "null"],
                        "properties": {
                            "question": {"type": "string"},
                            "where": {"type": "string"},
                        },
                        "required": ["question", "where"],
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "not_requested": {"type": "boolean"},
                    "justification_misquotes_instruction": {
                        "type": ["boolean", "null"]
                    },
                    "fix_target": {
                        "enum": ["criterion", "instruction", "both", "none", "unknown"]
                    },
                    "reasoning": {"type": "string"},
                },
                "required": [
                    "criterion",
                    "verdict",
                    "shape",
                    "confidence",
                    "ledger_rule_ids",
                    "instruction_quote",
                    "criterion_quote",
                    "compliant_solver_would_produce",
                    "readings",
                    "resolving_evidence",
                    "depends_on",
                    "not_requested",
                    "fix_target",
                    "reasoning",
                ],
            },
        },
    },
    "required": ["task_id", "chunk", "criteria"],
}


def build_stage2_prompt(
    task_id: str,
    fmt: str,
    chunk_i: int,
    chunk_n: int,
    instruction_md: str,
    stage1_json: dict,
    file_names: list[str],
    criteria_chunk: list[dict],
) -> str:
    """Design section 4.2, verbatim structure. `criteria_chunk` items are this file's own
    unified criterion dicts (see load_task_criteria) -- for EKW, why_justification/
    how_justification/importance are included per criterion when present; for SVC-PC those
    three fields are always None and are omitted from the rendered block entirely (never
    printed as 'None', which would read as a claim about the criterion rather than an absent
    field)."""
    lines = []
    for c in criteria_chunk:
        lines.append(
            f"- name: {c['name']} | file: {c['group']} | weight: {c['weight']} | "
            f"must_pass: {c['must_pass']} | graded files: {c['files']}"
        )
        lines.append(f"  description: '''{c['description']}'''")
        if fmt == "ekw" and (c.get("why_justification") or c.get("how_justification")):
            lines.append(
                f"  why_justification: '''{c.get('why_justification') or ''}''' | "
                f"how_justification: '''{c.get('how_justification') or ''}''' | "
                f"importance: {c.get('importance')}"
            )
    criteria_block = "\n".join(lines)

    user = f"""TASK: {task_id}    FORMAT: {fmt}    CHUNK: {chunk_i} of {chunk_n}
INSTRUCTION (verbatim):
<<<
{instruction_md}
>>>
STATED-LOGIC LEDGER (from step 1, JSON):
{json.dumps(stage1_json, indent=2)}
ENVIRONMENT FILE NAMES (names only; contents not shown; truncated to {len(file_names)} entries):
{json.dumps(file_names)}
CRITERIA:
{criteria_block}
Return JSON matching the schema."""
    return (
        f"# Stage 2 prompt: {task_id}, chunk {chunk_i} of {chunk_n}\n\n"
        f"## SYSTEM\n\n{STAGE2_SYSTEM_PROMPT}\n\n"
        f"## USER\n\n{user}\n\n"
        f"## OUTPUT SCHEMA (write your answer as JSON matching this exactly, no other text)\n\n"
        f"```json\n{json.dumps(STAGE2_SCHEMA, indent=2)}\n```\n"
    )


# ---------------------------------------------------------------------------
# Dual-format loading (design section 8.1: reuses the existing shared loaders)
# ---------------------------------------------------------------------------


def _has_svc_pc_config(task_dir: Path) -> bool:
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return False
    return any(tests_dir.glob("deliverables*/judge.toml"))


def _load_svc_pc_criteria(task_dir: Path) -> tuple[list[dict], list[str]]:
    """One unified criterion dict per [[criterion]] block, full (untruncated) description,
    real weight, must_pass from the description-text marker (judge.toml has no native field --
    certification_gate_check.py's own finding, matched here with the identical regex).
    `group` is the judge.toml's parent dir name (e.g. "deliverables_01"), matching this
    folder's established `group/name` provenance convention (rubric_schema_check.py,
    certification_gate_check.py)."""
    out: list[dict] = []
    errors: list[str] = []
    for jf in sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    ):
        group = jf.parent.name
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{group}/judge.toml: {exc}")
            continue
        files = (data.get("judge") or {}).get("files", []) or []
        for c in data.get("criterion") or []:
            name = str(c.get("name") or "").strip()
            desc = str(c.get("description") or "").strip()
            w = c.get("weight")
            out.append(
                {
                    "group": group,
                    "name": name,
                    "description": desc,
                    "weight": float(w) if isinstance(w, (int, float)) else None,
                    "must_pass": bool(MUST_PASS_RE.search(desc)),
                    "files": list(files),
                    "why_justification": None,
                    "how_justification": None,
                    "importance": None,
                }
            )
    return out, errors


def load_task_criteria(
    task_dir: Path,
) -> tuple[str | None, list[dict], list[str]]:
    """Returns (format, criteria, parse_errors). format is "svc-pc", "ekw", or None if
    neither config shape is present. SVC-PC takes precedence when both exist, matching every
    other dual-format check in this folder (extraction_groundedness_check.py's
    analyze_task())."""
    if _has_svc_pc_config(task_dir):
        criteria, errors = _load_svc_pc_criteria(task_dir)
        return "svc-pc", criteria, errors
    if has_ekw_config(task_dir):
        criteria = load_ekw_criteria(task_dir)
        errors = [c["description"] for c in criteria if c["name"] == "__parse_error__"]
        criteria = [c for c in criteria if c["name"] != "__parse_error__"]
        return "ekw", criteria, errors
    return None, [], ["no tests/deliverables*/judge.toml or tests/verifier.json found"]


def list_environment_file_names(task_dir: Path, limit: int = 200) -> list[str]:
    """Relative paths only, environment/ and solution/ -- design 3.3: "environment file NAMES
    only... contents not shown." Solution/ names are included too (not its contents), since
    the resolving-evidence question in a `contested` verdict sometimes names a golden-adjacent
    file (design 2.4's obj-01 case). Sorted for reproducibility; truncated at `limit` with a
    marker rather than silently dropped, since a truncated list is a real fact the model
    should see, not an implementation detail to hide."""
    names: list[str] = []
    for sub in ("environment", "solution"):
        base = task_dir / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                names.append(str(p.relative_to(task_dir)).replace("\\", "/"))
    if len(names) > limit:
        return names[:limit] + [f"...({len(names) - limit} more, truncated)"]
    return names


def chunk_criteria(
    criteria: list[dict], max_size: int = MAX_CHUNK_SIZE
) -> list[list[dict]]:
    """Design 3.4: one chunk if <= max_size, else ceil(n/max_size) chunks. Splits on the
    existing `group` boundaries where possible (judge.toml file boundaries) so a chunk never
    silently cuts a group in half when the corpus's own structure already gives a natural
    seam; falls back to a flat slice once a group boundary would make a chunk exceed
    max_size by itself (a single oversized group)."""
    if len(criteria) <= max_size:
        return [criteria]
    chunks: list[list[dict]] = []
    current: list[dict] = []
    for c in criteria:
        if current and len(current) >= max_size and c["group"] != current[-1]["group"]:
            chunks.append(current)
            current = []
        current.append(c)
        if len(current) >= max_size * 1.5:  # a single oversized group; force a cut
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Quote check and downgrade rules (design 3.2, 4.3, 7.5)
# ---------------------------------------------------------------------------


def _exact_substring(quote: str | None, source: str) -> bool:
    """True if quote is a non-empty exact substring of source. None/empty is NOT a pass --
    callers that allow a null quote (e.g. a `follows` verdict) check for None separately
    before calling this."""
    return isinstance(quote, str) and len(quote) > 0 and quote in source


def validate_stage1_response(raw: dict, instruction_md: str) -> dict:
    """Schema-shape check plus a quote check on every rule's `quote` field against the real
    instruction text. Returns raw with an added `_quote_check` list: one entry per rule,
    {id, ok}. Does not mutate rules; Stage 1 has no downgrade concept (that's a Stage 2
    property) -- a bad Stage 1 quote is surfaced for a human to see before Stage 2 ever
    runs, per design 3.1 ("A human can correct it before Stage 2 runs")."""
    checks = []
    for rule in raw.get("rules") or []:
        checks.append(
            {
                "id": rule.get("id"),
                "ok": _exact_substring(rule.get("quote"), instruction_md),
            }
        )
    raw["_quote_check"] = checks
    raw["_quote_check_all_ok"] = all(c["ok"] for c in checks)
    return raw


def _downgrade_to_contested(entry: dict, reason: str) -> dict:
    entry["verdict_final"] = "contested"
    entry.setdefault("downgrade_reasons", []).append(reason)
    return entry


def validate_and_downgrade_entry(entry: dict, instruction_md: str) -> dict:
    """Design 3.2 + 4.3's quote_check field + 7.5's downgrade rules, applied to one Stage 2
    criterion entry. Sets verdict_final (defaults to the model's own verdict, downgraded to
    "contested" when a rule below fires) and quote_check
    (ok | instruction_quote_not_found | criterion_quote_not_found | missing). Never raises on
    a malformed entry -- missing/wrong-typed fields degrade to the safest reading (missing
    quotes fail the quote check; an unrecognized verdict string is left as-is for a human to
    see rather than coerced).
    """
    entry = dict(entry)
    entry["verdict_final"] = entry.get("verdict")
    entry["downgrade_reasons"] = []

    verdict = entry.get("verdict")
    iq = entry.get("instruction_quote")
    cq = entry.get("criterion_quote")
    csw = entry.get("compliant_solver_would_produce")

    if verdict == "contradicts":
        if not (iq and cq and csw):
            entry["quote_check"] = "missing"
            return _downgrade_to_contested(
                entry, "contradicts missing required evidence field"
            )
        iq_ok = _exact_substring(iq, instruction_md)
        # criterion_quote is checked against the criterion's OWN description by the caller,
        # which has that text; this function only has the instruction, so it defers that half
        # of the check to validate_stage2_response() below and only records the instruction
        # half here. Overwritten by the caller once both halves are known.
        entry["quote_check"] = "ok" if iq_ok else "instruction_quote_not_found"
        if not iq_ok:
            return _downgrade_to_contested(
                entry, "instruction_quote not a verbatim substring"
            )
        if entry.get("confidence") == "low":
            return _downgrade_to_contested(entry, "low confidence contradicts")
    else:
        entry["quote_check"] = "ok"  # no quote requirement for non-contradicts verdicts

    return entry


def validate_stage2_response(
    raw: dict, instruction_md: str, criteria_by_name: dict[str, dict]
) -> dict:
    """Runs validate_and_downgrade_entry on every criterion entry, then completes the
    criterion-quote half of the quote check (needs the criterion's own description, which
    only this function -- not validate_and_downgrade_entry -- has access to via
    criteria_by_name). Also attaches file/weight/must_pass from the harness's own reading of
    the config (design 4.3: "The harness adds, per criterion, from its own reading of the
    config"), not from the model's response, so a hallucinated weight can never reach the
    report."""
    out_criteria = []
    for entry in raw.get("criteria") or []:
        entry = validate_and_downgrade_entry(entry, instruction_md)
        cname = entry.get("criterion")
        real = criteria_by_name.get(cname)
        if real is None:
            entry["harness_error"] = (
                f"criterion '{cname}' not found in this task's own config"
            )
        else:
            entry["file"] = real["group"]
            entry["weight"] = real["weight"]
            entry["must_pass"] = real["must_pass"]
            if entry.get("verdict") == "contradicts" and entry.get("criterion_quote"):
                cq_ok = _exact_substring(entry["criterion_quote"], real["description"])
                if not cq_ok and entry["quote_check"] == "ok":
                    entry["quote_check"] = "criterion_quote_not_found"
                    entry = _downgrade_to_contested(
                        entry,
                        "criterion_quote not a verbatim substring of the description",
                    )
        out_criteria.append(entry)
    raw = dict(raw)
    raw["criteria"] = out_criteria
    return raw


def merge_stability(run1: dict, run2: dict) -> dict:
    """Design 3.5: two identical-prompt runs, per-criterion verdict agreement, any
    disagreement downgrades verdict_final to "contested" with stability="disagree". Matches
    entries by criterion name; a criterion present in one run and not the other is its own
    disagreement (stability="disagree", reason recorded) rather than silently paired with
    nothing."""
    run2_by_name = {e.get("criterion"): e for e in run2.get("criteria", [])}
    merged = []
    for e1 in run1.get("criteria", []):
        e2 = run2_by_name.get(e1.get("criterion"))
        e = dict(e1)
        if e2 is None:
            e["stability"] = "disagree"
            e["downgrade_reasons"] = e.get("downgrade_reasons", []) + [
                "criterion missing from run 2"
            ]
            e["verdict_final"] = "contested"
        elif e1.get("verdict_final") == e2.get("verdict_final"):
            e["stability"] = "agree"
        else:
            e["stability"] = "disagree"
            e["run2_verdict_final"] = e2.get("verdict_final")
            e["downgrade_reasons"] = e.get("downgrade_reasons", []) + [
                f"run 1/run 2 disagreement ({e1.get('verdict_final')} vs {e2.get('verdict_final')})"
            ]
            e["verdict_final"] = "contested"
        merged.append(e)
    return {**run1, "criteria": merged}


def rollup_task_status(criteria: list[dict], no_rules_found: bool) -> str:
    """Design 3.2's status distinction: flagged (any final contradicts) > attention (only
    contested/ambiguous_instruction) > clean (all follows/not_addressed) > not_applicable
    (Stage 1 found no rules at all -- distinct from clean, since clean over zero rules would
    overclaim; see design 7.6, 'a clean result does not establish' groundedness elsewhere).
    """
    if no_rules_found:
        return "not_applicable"
    finals = [c.get("verdict_final") for c in criteria]
    if "contradicts" in finals:
        return "flagged"
    if any(v in ("contested", "ambiguous_instruction") for v in finals):
        return "attention"
    return "clean"


# ---------------------------------------------------------------------------
# CLI: prepare-stage1 / prepare-stage2 / ingest
# ---------------------------------------------------------------------------


def _refuse_out_dir_inside_root(out_dir: Path, root: Path) -> None:
    out_r = out_dir.resolve()
    root_r = root.resolve()
    if out_r == root_r or root_r in out_r.parents:
        raise SystemExit(
            f"--out-dir ({out_r}) resolves inside --root ({root_r}). Refused: prompt/report "
            "files quote Expected: values by design and must never land under a task "
            "directory or a corpus root (design section 9)."
        )


def _default_out_dir() -> Path:
    return Path(__file__).parent / "_ekw_verification_reports" / "semantic_consistency"


def cmd_prepare_stage1(args: argparse.Namespace) -> int:
    root = Path(args.root)
    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir()
    _refuse_out_dir_inside_root(out_dir, root)
    rc = 0
    for task_id in args.task:
        task_dir = root / task_id
        instr = task_dir / "instruction.md"
        if not instr.is_file():
            print(f"SKIP {task_id}: no instruction.md", file=sys.stderr)
            rc = 1
            continue
        instruction_md = instr.read_text(encoding="utf-8")
        prompt = build_stage1_prompt(task_id, instruction_md)
        task_out = out_dir / task_id
        task_out.mkdir(parents=True, exist_ok=True)
        (task_out / "stage1.prompt.md").write_text(prompt, encoding="utf-8")
        print(f"wrote {task_out / 'stage1.prompt.md'}")
    return rc


def cmd_prepare_stage2(args: argparse.Namespace) -> int:
    root = Path(args.root)
    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir()
    _refuse_out_dir_inside_root(out_dir, root)
    rc = 0
    for task_id in args.task:
        task_dir = root / task_id
        task_out = out_dir / task_id
        stage1_resp_path = task_out / "stage1.response.json"
        if not stage1_resp_path.is_file():
            print(
                f"SKIP {task_id}: no stage1.response.json in {task_out}",
                file=sys.stderr,
            )
            rc = 1
            continue
        stage1_json = json.loads(stage1_resp_path.read_text(encoding="utf-8"))
        fmt, criteria, errors = load_task_criteria(task_dir)
        if errors and not criteria:
            print(f"SKIP {task_id}: {errors}", file=sys.stderr)
            rc = 1
            continue
        instruction_md = (task_dir / "instruction.md").read_text(encoding="utf-8")
        file_names = list_environment_file_names(task_dir)
        chunks = chunk_criteria(criteria)
        for i, chunk in enumerate(chunks, 1):
            prompt = build_stage2_prompt(
                task_id,
                fmt,
                i,
                len(chunks),
                instruction_md,
                stage1_json,
                file_names,
                chunk,
            )
            (task_out / f"stage2.{i}.prompt.md").write_text(prompt, encoding="utf-8")
            print(f"wrote {task_out / f'stage2.{i}.prompt.md'} ({len(chunk)} criteria)")
    return rc


def cmd_ingest(args: argparse.Namespace) -> int:
    root = Path(args.root)
    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir()
    _refuse_out_dir_inside_root(out_dir, root)
    results = []
    for task_id in args.task:
        task_dir = root / task_id
        task_out = out_dir / task_id
        instruction_md = (task_dir / "instruction.md").read_text(encoding="utf-8")
        fmt, criteria, load_errors = load_task_criteria(task_dir)
        criteria_by_name = {c["name"]: c for c in criteria}

        stage1_path = task_out / "stage1.response.json"
        if not stage1_path.is_file():
            results.append(
                {
                    "task_id": task_id,
                    "status": "error",
                    "error": "no stage1.response.json",
                }
            )
            continue
        stage1 = validate_stage1_response(
            json.loads(stage1_path.read_text(encoding="utf-8")), instruction_md
        )

        chunk_paths = sorted(task_out.glob("stage2.*.response.json"))
        if not chunk_paths:
            results.append(
                {"task_id": task_id, "status": "error", "error": "no stage2 responses"}
            )
            continue
        run1_criteria: list[dict] = []
        for cp in chunk_paths:
            raw = json.loads(cp.read_text(encoding="utf-8"))
            validated = validate_stage2_response(raw, instruction_md, criteria_by_name)
            run1_criteria.extend(validated["criteria"])
        run1 = {"task_id": task_id, "criteria": run1_criteria}

        run2_paths = sorted(task_out.glob("stage2.*.run2.response.json"))
        if run2_paths:
            run2_criteria: list[dict] = []
            for cp in run2_paths:
                raw = json.loads(cp.read_text(encoding="utf-8"))
                validated = validate_stage2_response(
                    raw, instruction_md, criteria_by_name
                )
                run2_criteria.extend(validated["criteria"])
            merged = merge_stability(run1, {"criteria": run2_criteria})
        else:
            merged = run1
            for e in merged["criteria"]:
                e["stability"] = "not_run"

        status = rollup_task_status(
            merged["criteria"], stage1.get("no_rules_found", False)
        )
        results.append(
            {
                "task_id": task_id,
                "format": fmt,
                "status": status,
                "stage1_quote_check_all_ok": stage1.get("_quote_check_all_ok"),
                "n_criteria": len(criteria),
                "n_graded": len(merged["criteria"]),
                "load_errors": load_errors,
                "ledger": stage1.get("rules", []),
                "criteria": merged["criteria"],
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / (args.report_name or "report.json")
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    for r in results:
        if r.get("status") == "error":
            print(f"ERROR {r['task_id']}: {r['error']}")
            continue
        flagged = [
            c["criterion"]
            for c in r["criteria"]
            if c.get("verdict_final") == "contradicts"
        ]
        attn = [
            c["criterion"]
            for c in r["criteria"]
            if c.get("verdict_final") in ("contested", "ambiguous_instruction")
        ]
        print(
            f"{r['status'].upper():<14} {r['task_id']:<20} {r['n_graded']} criteria  "
            f"contradicts={flagged}  attention={attn}"
        )
    print(f"\nwrote {report_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, fn in (
        ("prepare-stage1", cmd_prepare_stage1),
        ("prepare-stage2", cmd_prepare_stage2),
        ("ingest", cmd_ingest),
    ):
        sp = sub.add_parser(name)
        sp.add_argument(
            "task", nargs="+", help="task id(s), directory names under --root"
        )
        sp.add_argument(
            "--root",
            required=True,
            help="directory containing one subdirectory per task",
        )
        sp.add_argument(
            "--out-dir",
            default=None,
            help="default: <this folder>/_ekw_verification_reports/semantic_consistency/",
        )
        if name == "ingest":
            sp.add_argument("--report-name", default="report.json")
        sp.set_defaults(func=fn)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
