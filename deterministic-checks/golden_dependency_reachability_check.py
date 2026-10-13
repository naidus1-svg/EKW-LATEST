#!/usr/bin/env python3
"""needs Python 3.11+ for tomllib

Golden-dependency reachability check: does a rubric criterion's own text lean on an analysis
script, notebook, or tool that the solver was never given?

Why this exists: an external QC review quarantined one task whose answer key was grounded in
two Python scripts the solver never receives -- the golden was produced by running those
scripts, and roughly 90% of the task's rubric marks depend on values only those scripts could
have derived, making that share of the task unwinnable no matter how well a solver reasons from
what it was actually given. That is a different failure shape from
`environment_input_check.py`'s pattern 1 (instruction.md NAMES a file that's missing) -- here,
instruction.md may say nothing about the script at all; the dependency surfaces only in the
RUBRIC's own description text (an expected value or method that reads as "per analysis4.py" or
"as computed by the simulation script"), which environment_input_check.py never scans (it reads
only instruction.md, by design).

This is a LINT, not a fixer: whether the right remedy is shipping the script's OUTPUTS as a
solver-visible input, or rewriting the criterion to grade what the instruction actually asks
for instead, is a task-authoring decision this script has no basis for making -- it only
surfaces the unreachable-dependency signal for a human to route.

Reuses `judge_determinism_config_lint.py`'s own multi-schema config discovery
(`discover_config_specs`) via import, same as the other new checks in this batch.

Detection heuristic (deliberately narrow -- see Known limits):
    A criterion's description/prompt text is scanned for a script-shaped token: a bare
    filename ending in .py/.r/.R/.ipynb/.sql/.do/.m/.jl, OR a phrase pattern
    "(?:per|via|using|from|by|per the)\\s+(?:the\\s+)?(\\S+?)\\s+script" naming the script by a
    bare word even without an extension (e.g. "as derived by the reinsurance simulation
    script"). Each match's literal filename token (when an extension was present) is checked
    against every file actually shipped under `environment/` (recursively, basename match) --
    if the exact basename is not shipped anywhere in the environment, the criterion is flagged.
    A phrase-only match with no literal filename (no extension token) is reported separately as
    `named_but_unresolvable` -- disclosed, not silently dropped, since this script has no
    filename to check existence for.

Status: v1, new, uncalibrated -- built and self-tested against a synthetic fixture reproducing
the review's own described shape (a criterion whose expected value cites a script filename not
present anywhere in a synthetic environment/), and run cleanly (zero findings, as expected -- no
scripted-dependency language exists in that task's real rubric) against
`pipeline/data/sample_corpus/task_11` during development. Not run over a real corpus with an
actual instance of this defect at scale; this check's real-world hit rate is unknown.

Usage:
    python golden_dependency_reachability_check.py <TASK-ID> [<TASK-ID> ...] --root <path> \\
        --out report.json
    python golden_dependency_reachability_check.py --all --root <path> --out report.json

Known limits, disclosed rather than silently dropped:
    - Extension list is fixed (.py/.r/.R/.ipynb/.sql/.do/.m/.jl) -- a script in another
      language/extension, or referenced without any extension AND without matching the
      "X script" phrase pattern, is invisible to this check.
    - Bare single-letter ".m" stems matching "a.m"/"p.m" (any case) are excluded from
      named_script_file matches -- a time-of-day phrase like "6:00 a.m. to 3:00 p.m." would
      otherwise false-positive as a MATLAB script reference, since the stem "a"/"p" alone
      satisfies the filename token shape. A real MATLAB script's stem is never a bare single
      letter, so this costs no real detection power. (Caught on task_37, tests/verifier.json
      criteria v5/v18.)
    - Only checks `environment/` for the named file, recursively, by BASENAME -- a script that
      exists elsewhere in the task package (e.g. accidentally left under `solution/` instead of
      `environment/`) is still reported as missing from the solver's actual inputs, which is
      the literally correct read: `solution/` and `tests/` are never shipped to a solver.
    - A criterion that references a script BY NAME but does not actually depend on that
      script's specific output for its own expected value (e.g. citing it only as background
      methodology, not as the source of a graded number) still gets flagged -- this script
      cannot tell "the golden's expected value came from this script" from "this script is
      mentioned in passing," so a flag here is a lead to read the criterion, not a confirmed
      unreachable-dependency defect.
    - `named_but_unresolvable` findings (a phrase match with no literal filename) are neither
      confirmed present nor confirmed missing -- reported as a distinct status specifically so
      it is never miscounted as either a pass or a confirmed fail.
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

import judge_determinism_config_lint as detlint  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_EXTS = r"py|r|R|ipynb|sql|do|m|jl"
SCRIPT_FILE_RE = re.compile(rf"\b([\w\-]+\.(?:{SCRIPT_EXTS}))\b", re.IGNORECASE)
SCRIPT_PHRASE_RE = re.compile(
    r"\b(?:per|via|using|from|by)\s+(?:the\s+)?(\S+(?:\s+\S+){0,3}?)\s+script\b",
    re.IGNORECASE,
)
# False-positive guard, not a detection weakening: the `.m` extension (MATLAB script) is the
# only one in SCRIPT_EXTS that collides with a common English abbreviation -- "a.m." / "p.m."
# in a time-of-day phrase ("6:00 a.m. to 3:00 p.m.") satisfies `[\w\-]+\.m` because the stem
# "a"/"p" is a single word character. A real MATLAB filename stem naming an actual script is
# never a bare single letter, so this narrowly excludes just that shape -- multi-character `.m`
# stems (e.g. "analysis.m", "sim_2.m") are untouched and still flagged as before. Caught on
# task_37 (tests/verifier.json criteria v5 and v18: "6:00 a.m. to 3:00 p.m." / "9:00 a.m. to
# 6:00 p.m."), which have no script dependency at all -- see qc-results/gen1 review.
TIME_OF_DAY_AM_PM_RE = re.compile(r"^[ap]\.m$", re.IGNORECASE)

GENERIC_TEXT_FIELDS = ("description", "prompt", "rubric_prompt", "how_justification")


def extract_criteria(data, fmt: str) -> list[dict]:
    out = []
    if fmt == "judge_toml":
        criteria = data.get("criterion")
        if isinstance(criteria, list):
            for c in criteria:
                if isinstance(c, dict):
                    out.append({"name": c.get("name"), "text": c.get("description")})
        return out
    if fmt == "verifier_json":
        verifiers = data.get("verifiers")
        if isinstance(verifiers, list):
            for v in verifiers:
                if not isinstance(v, dict):
                    continue
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
                out.append({"name": v.get("name"), "text": text})
        return out

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


def collect_environment_basenames(task_dir: Path) -> set[str]:
    env_dir = task_dir / "environment"
    names: set[str] = set()
    if env_dir.is_dir():
        for p in env_dir.rglob("*"):
            if p.is_file():
                names.add(p.name.lower())
    return names


def analyze_criterion_text(text: str, env_basenames: set[str]) -> list[dict]:
    if not text:
        return []
    findings = []
    seen_files = set()
    for m in SCRIPT_FILE_RE.finditer(text):
        fname = m.group(1)
        if TIME_OF_DAY_AM_PM_RE.match(fname):
            continue
        key = fname.lower()
        if key in seen_files:
            continue
        seen_files.add(key)
        shipped = key in env_basenames
        findings.append(
            {
                "kind": "named_script_file",
                "reference": fname,
                "shipped_in_environment": shipped,
                "flagged": not shipped,
            }
        )
    for m in SCRIPT_PHRASE_RE.finditer(text):
        phrase = m.group(1)
        # Skip phrase matches that are just re-describing a filename already caught above
        # (e.g. "via analysis4.py script" matches both regexes on "analysis4.py").
        if any(phrase.lower() in f["reference"].lower() for f in findings):
            continue
        findings.append(
            {
                "kind": "named_but_unresolvable",
                "reference": phrase,
                "shipped_in_environment": None,
                "flagged": False,
            }
        )
    return findings


def analyze_config_file(path: Path, fmt: str, task_dir: Path, env_basenames: set[str]) -> dict:
    rel = str(path.relative_to(task_dir)).replace("\\", "/")
    cfg = {"path": rel, "format": fmt, "parse_error": None, "criteria": []}
    try:
        text = path.read_text(encoding="utf-8")
        data = tomllib.loads(text) if fmt in ("judge_toml", "other_toml") else json.loads(text)
    except Exception as e:
        cfg["parse_error"] = f"{type(e).__name__}: {e}"
        return cfg

    for crit in extract_criteria(data, fmt):
        findings = analyze_criterion_text(crit.get("text"), env_basenames)
        if findings:
            cfg["criteria"].append(
                {"name": crit.get("name"), "text": crit.get("text"), "findings": findings}
            )
    return cfg


def analyze_task(task_dir: Path) -> dict:
    task_id = task_dir.name
    result = {"task_id": task_id, "config_files": [], "status": None, "errors": []}

    specs = detlint.discover_config_specs(task_dir)
    if not specs:
        result["status"] = "skip"
        result["errors"].append("no grading-config file found under tests/ for this task")
        return result

    env_basenames = collect_environment_basenames(task_dir)
    any_flagged = False
    any_findings = False
    for path, fmt in specs:
        cfg = analyze_config_file(path, fmt, task_dir, env_basenames)
        result["config_files"].append(cfg)
        for c in cfg["criteria"]:
            any_findings = True
            if any(f["flagged"] for f in c["findings"]):
                any_flagged = True

    if any_flagged:
        result["status"] = "fail"
    elif any_findings:
        result["status"] = "review"  # named_but_unresolvable only -- see module docstring
    else:
        result["status"] = "pass"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Flags rubric criteria that lean on an analysis script/notebook by name, and "
            "checks whether that script is actually shipped anywhere under environment/ -- "
            "catching the 'golden depends on a script the solver never received' failure "
            "shape from an external QC review."
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
        except Exception as e:
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
    n_review = sum(1 for r in results if r["status"] == "review")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_review": n_review,
        "n_skip": n_skip,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_review} review / {n_skip} skip "
        f"out of {len(results)} task(s)"
    )
    for r in results:
        if r["status"] != "fail":
            continue
        for cfg in r["config_files"]:
            for c in cfg.get("criteria", []):
                for f in c["findings"]:
                    if f["flagged"]:
                        print(
                            f"  {r['task_id']}: fail  [{cfg['path']}: {c['name']!r} -- "
                            f"references {f['reference']!r}, not shipped under environment/]"
                        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
