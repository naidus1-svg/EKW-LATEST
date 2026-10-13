#!/usr/bin/env python3
"""needs Python 3.11+ for tomllib

Criterion condition-count check: does a single rubric criterion actually bundle several
separately-checkable conditions into one pass/fail slot?

Why this exists: an external QC review found that about 13% of the rubrics it sampled carry
criteria with eight or more separately-checkable conditions bundled into a single criterion,
one criterion running as high as 27, and recommended capping authoring at roughly three
conditions per criterion. The stated reasons: reproducibility (a judge grading "A and B and C
and D..." in one pass/fail slot has more chances to disagree with itself run-to-run than five
single-condition criteria would), and contradiction-visibility (a bundled criterion can hide an
internal contradiction between two of its own conditions that would be obvious if they were two
separate, individually-reviewable rows).

This is a LINT against condition COUNT, not a rewriter -- splitting an over-bundled criterion
into several correctly-weighted ones is an authoring decision (how to redistribute the original
weight, whether to keep one grading_role or split it, whether the split criteria are still
mutually independent) this script has no business making unilaterally. It only ever counts and
reports; there is no --apply/fix mode.

Counting heuristic (deliberately conservative -- see Known limits): within one criterion's
description/prompt text, count:
  1. Sentence-ending punctuation (`.`, `!`, `?` followed by whitespace or end of string) --
     each sentence is treated as at least one condition.
  2. Within each sentence, additional conditions introduced by a coordinating conjunction
     joining two clause-shaped things to check ("X and Y", "X, Y, and Z", "X or Y") -- counted
     via `\\band\\b|\\bor\\b` occurrences OUTSIDE of a parenthetical (a parenthetical aside like
     "(exact)" or "(e.g. A, B, or C)" is not itself a second condition to check, it is usually
     elaborating ONE condition -- see Known limits for where this heuristic still overcounts).
  3. Explicit enumeration markers: a semicolon-separated clause list, or an inline
     `1)`/`2)`/`a)`/`b)`-style enumeration.
Each sentence contributes `1 + (conjunctions outside parens) + (enumeration items - 1 if any)`
to that criterion's total; a criterion's condition count is the sum across all its sentences.

Status: v1, new, uncalibrated -- built and self-tested against small synthetic examples and the
real `pipeline/data/sample_corpus/task_11` fixture in this repo during development (see that
task's own `tests/verifier.json` for real multi-condition criteria this heuristic was checked
against by hand), not yet run over a real corpus at scale. Given the conservative design (see
Known limits), expect this to UNDER-count relative to a careful human read in some cases and to
mildly OVER-count in others (e.g. a genuine "and" inside one indivisible clause, like "cost and
benefit analysis" as a named concept) -- read a flagged criterion's own text before treating a
high count as a confirmed defect, exactly as the review itself frames this as an authoring
GUIDELINE (roughly three), not an exact, non-negotiable ceiling.

Usage:
    python criterion_condition_count_check.py <TASK-ID> [<TASK-ID> ...] --root <path> \\
        --out report.json
    python criterion_condition_count_check.py --all --root <path> --max-conditions 3 \\
        --out report.json

What it does, in order:
    1. Reuses `judge_determinism_config_lint.py`'s own multi-schema config discovery
       (`discover_config_specs`) to find every judge.toml / verifier.json / manifest.json for a
       task, exactly the same file set that script and `judge_panel_size_check.py` scan.
    2. Extracts every criterion's description text: judge.toml `[[criterion]].description`;
       verifier.json `verifiers[].assertion.rubric.prompt` (falling back to
       `verifiers[].metadata.how_justification` if no rubric prompt is present); manifest.json
       and other formats are scanned generically for the first string-valued field literally
       named description/prompt/rubric_prompt/how_justification found on each list item.
    3. Runs the condition-count heuristic above on that text.
    4. A criterion fails if its count exceeds --max-conditions (default 3, the review's own
       stated guideline). A task fails if any of its criteria fail.

Known limits, disclosed rather than silently dropped:
    - This is a syntactic, not semantic, count. "Pass if the value is $500 (exact) and the
      currency is USD" counts as 2 conditions (one sentence + one "and"), which is probably
      correct; "Pass if the cost and benefit analysis is present" would ALSO count 2 (the "and"
      inside a compound noun phrase is not a second condition) -- a real overcount this
      heuristic does not attempt to fix, because distinguishing "and joining two checks" from
      "and inside one named concept" reliably needs semantics, not syntax.
    - The parenthetical-aside exclusion for conjunctions is a simple depth-1 paren-matcher; it
      does not handle nested parentheses beyond one level, and a conjunction that spans a
      paren's boundary (opens outside, the "and" is inside) is handled by the exclusion, but a
      malformed/unbalanced parenthetical in the source text falls back to counting the
      conjunction (conservative in the fail-loud direction, not silently dropped).
    - Enumeration-marker detection (`1)`, `a)`, `;`-joined clauses) is a fixed set of shapes; a
      rubric using a different enumeration convention (bullet dashes inside one string field,
      for instance) is invisible to this specific signal, though its sentences and conjunctions
      still count normally.
    - Only reads whichever ONE text field this script picked per format (see step 2) --
      auxiliary text fields on the same criterion (e.g. verifier.json's
      `metadata.why_justification`, which is about WHY the check exists, not WHAT it checks)
      are deliberately not folded into the count, since they are not (Attempted) part of what
      the judge is actually asked to evaluate pass/fail against.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    print(
        "This script requires Python 3.11+ (tomllib is stdlib-only from 3.11 on). "
        "Run it with python3.11/python3.12, or the repo's pipeline/.venv.",
        file=sys.stderr,
    )
    raise SystemExit(1)

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

# Reuse judge_determinism_config_lint.py's own multi-schema config discovery verbatim.
import judge_determinism_config_lint as detlint  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_MAX_CONDITIONS = 3

SENTENCE_SPLIT_RE = re.compile(r"[^.!?]*[.!?]+(?:\s+|$)|[^.!?]+$")
CONJUNCTION_RE = re.compile(r"\b(?:and|or)\b", re.IGNORECASE)
ENUM_ITEM_RE = re.compile(r"(?:^|\s)(?:\d+\)|[a-z]\))\s+\S", re.IGNORECASE)
SEMICOLON_RE = re.compile(r";")


def strip_parentheticals(text: str) -> str:
    """Removes depth-1 `(...)` spans so a conjunction inside a parenthetical aside (e.g. "(e.g.
    A, B, or C)") is not counted as a second top-level condition. Unbalanced parens are left
    as-is (conservative: falls back to counting anything inside, per module docstring)."""
    out = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            if depth > 0:
                depth -= 1
                continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def count_conditions_in_sentence(sentence: str) -> int:
    without_parens = strip_parentheticals(sentence)
    n = 1  # the sentence itself is at least one condition
    n += len(CONJUNCTION_RE.findall(without_parens))
    semicolons = len(SEMICOLON_RE.findall(without_parens))
    if semicolons:
        n += semicolons  # N semicolons -> N+1 clauses, but the sentence already counted 1
    enum_items = len(ENUM_ITEM_RE.findall(without_parens))
    if enum_items >= 2:
        n += enum_items - 1
    return n


def count_conditions(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {"total": 0, "sentences": []}
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.findall(text) if s.strip()]
    per_sentence = []
    total = 0
    for s in sentences:
        c = count_conditions_in_sentence(s)
        total += c
        per_sentence.append({"text": s, "count": c})
    return {"total": total, "sentences": per_sentence}


# ---------------------------------------------------------------------------
# criterion extraction per format
# ---------------------------------------------------------------------------

GENERIC_TEXT_FIELDS = ("description", "prompt", "rubric_prompt", "how_justification")


def extract_criteria_judge_toml(data: dict) -> list[dict]:
    out = []
    criteria = data.get("criterion")
    if isinstance(criteria, list):
        for c in criteria:
            if isinstance(c, dict):
                out.append({"name": c.get("name"), "text": c.get("description")})
    return out


def extract_criteria_verifier_json(data: dict) -> list[dict]:
    out = []
    verifiers = data.get("verifiers")
    if not isinstance(verifiers, list):
        return out
    for v in verifiers:
        if not isinstance(v, dict):
            continue
        name = v.get("name")
        text = None
        assertion = v.get("assertion")
        if isinstance(assertion, dict):
            rubric = assertion.get("rubric")
            if isinstance(rubric, dict):
                text = rubric.get("prompt")
        if text is None:
            metadata = v.get("metadata")
            if isinstance(metadata, dict):
                text = metadata.get("how_justification")
        out.append({"name": name, "text": text})
    return out


def extract_criteria_generic(data) -> list[dict]:
    """Fallback for manifest.json / other_json / other_toml: scans any list found anywhere in
    the structure for dict items carrying one of GENERIC_TEXT_FIELDS, first match wins per
    item."""
    out = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    for field in GENERIC_TEXT_FIELDS:
                        if isinstance(item.get(field), str):
                            out.append({"name": item.get("name"), "text": item[field]})
                            break
                walk(item)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)

    walk(data)
    return out


def extract_criteria(data, fmt: str) -> list[dict]:
    if fmt == "judge_toml":
        return extract_criteria_judge_toml(data)
    if fmt == "verifier_json":
        return extract_criteria_verifier_json(data)
    return extract_criteria_generic(data)


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir: Path, max_conditions: int) -> dict:
    task_id = task_dir.name
    result = {"task_id": task_id, "config_files": [], "status": None, "errors": []}

    specs = detlint.discover_config_specs(task_dir)
    if not specs:
        result["status"] = "skip"
        result["errors"].append("no grading-config file found under tests/ for this task")
        return result

    any_over = False
    any_criteria = False
    for path, fmt in specs:
        rel = str(path.relative_to(task_dir)).replace("\\", "/")
        cfg = {"path": rel, "format": fmt, "parse_error": None, "criteria": []}
        try:
            text = path.read_text(encoding="utf-8")
            data = tomllib.loads(text) if fmt in ("judge_toml", "other_toml") else json.loads(text)
        except Exception as e:
            cfg["parse_error"] = f"{type(e).__name__}: {e}"
            result["config_files"].append(cfg)
            continue

        for crit in extract_criteria(data, fmt):
            any_criteria = True
            counted = count_conditions(crit.get("text"))
            over = counted["total"] > max_conditions
            any_over = any_over or over
            cfg["criteria"].append(
                {
                    "name": crit.get("name"),
                    "text": crit.get("text"),
                    "condition_count": counted["total"],
                    "sentences": counted["sentences"],
                    "over_limit": over,
                }
            )
        result["config_files"].append(cfg)

    if any_over:
        result["status"] = "fail"
    elif any_criteria:
        result["status"] = "pass"
    else:
        result["status"] = "no_criteria_found"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Counts separately-checkable conditions bundled into each rubric criterion and "
            "flags any criterion over --max-conditions (default 3, per an external QC "
            "review's own recommendation). Lint only -- never rewrites a criterion."
        )
    )
    ap.add_argument("task_ids", nargs="*", help="one or more task ids (directory names under --root)")
    ap.add_argument("--all", action="store_true", help="run every task directory found under --root")
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        help="root directory containing one subdirectory per task (REQUIRED -- no default)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix as tasks",
    )
    ap.add_argument(
        "--max-conditions",
        type=int,
        default=DEFAULT_MAX_CONDITIONS,
        help=f"flag any criterion strictly over this many counted conditions (default {DEFAULT_MAX_CONDITIONS})",
    )
    ap.add_argument("--out", type=Path, default=None, help="write the aggregate JSON report here")
    args = ap.parse_args()

    if args.root is None:
        ap.error("--root is required (point it at the directory containing your task folders)")
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    task_dirs = detlint.find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 1

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(task_dir, args.max_conditions)
        except Exception as e:
            r = {
                "task_id": task_dir.name,
                "status": "fail",
                "errors": [f"unhandled exception analyzing this task: {e}"],
                "config_files": [],
            }
        results.append(r)
        n_over = sum(
            1
            for cfg in r.get("config_files", [])
            for c in cfg.get("criteria", [])
            if c.get("over_limit")
        )
        print(f"    -> {r['status']}  ({n_over} criterion/criteria over limit)", file=sys.stderr)

    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_none = sum(1 for r in results if r["status"] == "no_criteria_found")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "max_conditions": args.max_conditions,
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_no_criteria_found": n_none,
        "n_skip": n_skip,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_none} no_criteria_found / {n_skip} skip "
        f"out of {len(results)} task(s)"
    )
    for r in results:
        if r["status"] != "fail":
            continue
        for cfg in r["config_files"]:
            for c in cfg.get("criteria", []):
                if c["over_limit"]:
                    print(
                        f"  {r['task_id']}: fail  [{cfg['path']}: "
                        f"{c['name']!r} has {c['condition_count']} conditions (max {args.max_conditions})]"
                    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
