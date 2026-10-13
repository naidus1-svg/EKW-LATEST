#!/usr/bin/env python3
"""needs Python 3.11+ for tomllib

Judge-panel-size lint: does a task's grading config expose a list of judge/grading models, and
if so, is that list long enough to vote rather than decide on one model's single opinion?

Why this exists, and how it differs from `judge_determinism_config_lint.py`. That script (read
its docstring first) hunts for a `temperature`-shaped field with no `panel`/`sample_count`-
shaped field alongside it -- the PX-01 pattern, an LLM-judge criterion sampled once at nonzero
temperature. This script hunts for a DIFFERENT but related shape from the same external QC
review: a config that names a `models` (or `model_list`/`panel_models`) field intended to hold
MULTIPLE grading models for majority-vote/ensemble judging, but that list currently holds only
one entry. The review's own framing: "Config.models already accepts three models; every task
ships with one." A single-model config is a single point of judgment even at temperature 0 --
one model's systematic bias or blind spot never gets outvoted -- which
`judge_determinism_config_lint.py`'s key-NAME-based PANEL_RE (temperature/sample_count/panel/
votes/repeats) does not catch, because "models" itself matches none of those name patterns.

This is a lint, not an autofix, deliberately: this script has no way to know WHICH additional
models a task's owner wants added to reach a real panel (that is a task/benchmark-owner
decision about model diversity, cost, and rate limits -- not something to invent), so it only
ever reports the gap, never edits a config file.

Reuses `judge_determinism_config_lint.py`'s own multi-schema config discovery
(`discover_config_specs`, `find_task_dirs`) via import, so this check scans the exact same set
of config files that script does, in the same (a)-(d) precedence order, with no risk of the two
checks silently disagreeing about which file is "the" config for a task. The field walk itself
is a new, separate function (not `walk_for_fields`) because that function's field-matching
logic is hardcoded to the temperature/panel-count patterns; duplicating the walk shape (same
recursion guard, same "only dict KEYS are pattern-matched, never string/list/scalar VALUES"
rule) was judged simpler and lower-risk than editing that file to parameterize it.

Status: v1, new, exercised against the real `pipeline/data/sample_corpus/task_11` fixture in
this repo (a real EKW-shaped `tests/verifier.json` with `config.models: ["openai/gpt-5.4"]`,
`config.temperature: 1.0` -- both this check's own gap and `judge_determinism_config_lint.py`'s
PX-01 pattern fire on that one real file) during development. Not yet run over a real corpus at
scale, and not calibrated against any other real task population -- treat findings as a lead to
verify against the task's own config file directly, not a confirmed defect.

Usage:
    python judge_panel_size_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python judge_panel_size_check.py --all --root <path> --out report.json

What it does, in order:
    1. For each task, `discover_config_specs()` finds every judge.toml / verifier.json /
       manifest.json / other tests/*.toml|json config file, exactly as
       `judge_determinism_config_lint.py` does.
    2. Parses each (tomllib for .toml, json for .json -- a parse failure is recorded, not a
       crash) and walks the parsed structure for any dict key matching
       `models?$|model_list|panel_models` (case-insensitive) whose VALUE is a list.
    3. Classifies each match: `single_model` (list length exactly 1 -- the PX-flagged risk
       shape), `multi_model` (length >= 2, not flagged), or `empty_list` (length 0, disclosed
       but not flagged as this specific risk -- an empty models list is a different defect,
       arguably a config completeness bug, outside this check's stated scope).
    4. A task fails if ANY discovered config file has a `single_model` match. `no_models_field`
       (no matching key found in any config file at all) is EXPLICITLY NOT a pass/fail verdict,
       mirroring `judge_determinism_config_lint.py`'s own "no_determinism_fields_found"
       handling -- this check cannot see a panel-size control the harness enforces elsewhere
       (a global default, code outside the task's own config), so absence of the field here
       must never be read as absence of the risk.

Known limits, disclosed rather than silently dropped:
    - Name-pattern matching only (`models?$|model_list|panel_models`), same class of limit as
      `judge_determinism_config_lint.py`'s own PANEL_RE -- a config that spells this field
      something else entirely (`grader_pool`, `judge_ensemble`, ...) is invisible to this
      check.
    - A `models` list holding duplicate entries of the SAME model (`["gpt-5", "gpt-5"]`) reads
      as `multi_model` (length >= 2) here even though it provides no real diversity of
      judgment -- this check counts list length, not distinct models. Not corrected for,
      because "how similar is similar enough to not count" is a judgment call this script is
      not positioned to make silently.
    - Only ever reports; never proposes or writes a specific replacement model list -- see
      module docstring for why.
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

# Reuse judge_determinism_config_lint.py's own multi-schema config discovery verbatim -- see
# module docstring for why the field walk itself is NOT reused the same way.
import judge_determinism_config_lint as detlint  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MODELS_FIELD_RE = re.compile(r"models?$|model_list|panel_models", re.IGNORECASE)
MAX_WALK_DEPTH = 60


def walk_for_model_lists(node, path: str, out: list, depth: int = 0) -> None:
    """Recursively finds every dict key matching MODELS_FIELD_RE whose value is a list. Only
    dict KEYS are pattern-matched; string/list/scalar values are recursed into but never
    matched themselves -- same rule judge_determinism_config_lint.py's walk_for_fields()
    applies, for the same reason (never mistake rubric/criterion prose for a config field)."""
    if depth > MAX_WALK_DEPTH:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            key_str = str(k)
            child_path = f"{path}.{key_str}" if path else key_str
            if MODELS_FIELD_RE.search(key_str) and isinstance(v, list):
                out.append({"field_path": child_path, "value": detlint.to_jsonable(v)})
            walk_for_model_lists(v, child_path, out, depth + 1)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk_for_model_lists(v, f"{path}[{i}]", out, depth + 1)


def analyze_config_file(path: Path, fmt: str, task_dir: Path) -> dict:
    rel = str(path.relative_to(task_dir)).replace("\\", "/")
    cfg = {
        "path": rel,
        "format": fmt,
        "parse_error": None,
        "matches": [],
    }
    try:
        text = path.read_text(encoding="utf-8")
        data = tomllib.loads(text) if fmt in ("judge_toml", "other_toml") else json.loads(text)
    except Exception as e:
        cfg["parse_error"] = f"{type(e).__name__}: {e}"
        return cfg

    matches: list[dict] = []
    if isinstance(data, dict):
        walk_for_model_lists(data, "", matches)

    for m in matches:
        n = len(m["value"])
        m["n_models"] = n
        m["classification"] = (
            "empty_list" if n == 0 else "single_model" if n == 1 else "multi_model"
        )
    cfg["matches"] = matches
    return cfg


def analyze_task(task_dir: Path) -> dict:
    task_id = task_dir.name
    result = {"task_id": task_id, "config_files": [], "status": None, "errors": []}

    specs = detlint.discover_config_specs(task_dir)
    if not specs:
        result["status"] = "skip"
        result["errors"].append("no grading-config file found under tests/ for this task")
        return result

    any_single = False
    any_field_found = False
    for path, fmt in specs:
        cfg = analyze_config_file(path, fmt, task_dir)
        result["config_files"].append(cfg)
        if cfg["parse_error"]:
            continue
        for m in cfg["matches"]:
            any_field_found = True
            if m["classification"] == "single_model":
                any_single = True

    if any_single:
        result["status"] = "fail"
    elif any_field_found:
        result["status"] = "pass"
    else:
        result["status"] = "no_models_field"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Checks whether a task's grading config exposes a models/model_list/panel_models "
            "field holding only a single model -- a single-judge point of failure even at "
            "temperature 0, distinct from judge_determinism_config_lint.py's "
            "temperature/no-panel pattern."
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
            r = analyze_task(task_dir)
        except Exception as e:  # never let one task's crash kill the whole batch
            r = {
                "task_id": task_dir.name,
                "status": "fail",
                "errors": [f"unhandled exception analyzing this task: {e}"],
                "config_files": [],
            }
        results.append(r)
        print(f"    -> {r['status']}", file=sys.stderr)

    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_no_field = sum(1 for r in results if r["status"] == "no_models_field")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_no_models_field": n_no_field,
        "n_skip": n_skip,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_no_field} no_models_field / {n_skip} skip "
        f"out of {len(results)} task(s)"
    )
    for r in results:
        if r["status"] != "fail":
            continue
        for cfg in r["config_files"]:
            for m in cfg.get("matches", []):
                if m["classification"] == "single_model":
                    print(
                        f"  {r['task_id']}: fail  [{cfg['path']}: "
                        f"{m['field_path']} = {m['value']!r} (1 model)]"
                    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
