#!/usr/bin/env python3
"""needs Python 3.11+ for tomllib

Invention-detection visibility check: when a criterion asks the judge "did the candidate make
this up / add something not provided," is the judge actually shown the source material it would
need to answer that -- or only the candidate's own output?

Why this exists: an external QC review's own example -- one task's criterion asks the judge to
distinguish data the candidate was PROVIDED from data the candidate INVENTED, while that
criterion's own grading config shows the judge only the candidate's memo, never the source
material the candidate was given. A judge with no access to "what was actually provided" cannot
tell invention from correct-but-unfamiliar-sounding synthesis, and the review's own finding was
that in practice this penalized specificity itself -- a judge with nothing to compare against
treats any sufficiently specific-sounding claim as suspect. This is a visibility bug in the
grading config, not a wording bug in the criterion text: the fix is showing the judge the
source, not rewording the question.

This is a LINT, not an autofix: adding the right source file(s) to a criterion's graded
`files=[...]` (judge.toml) / `source` (verifier.json) is an authoring decision about WHICH of a
task's environment files are the relevant "provided data" for that specific criterion -- this
script has no reliable way to guess that from the criterion text alone, so it only ever reports
the gap for a human to close.

Reuses `judge_determinism_config_lint.py`'s own multi-schema config discovery
(`discover_config_specs`) via import, exactly as `judge_panel_size_check.py` and
`criterion_condition_count_check.py` do, so all three checks agree on which files count as "the"
grading config for a task.

Detection heuristic (deliberately narrow -- see Known limits):
    1. A criterion is treated as an INVENTION-DETECTION criterion if its description/prompt
       text matches any of: invent(ed/ing)?, made up, make up, fabricat(e/ed/ion), hallucinat(e/
       ed/ion), not (?:in|from|present in) (?:the )?(?:source|provided|given|input), unsupported
       (?:claim|symptom|fact|figure|number), (?:not|never) (?:provided|given|stated) -- see the
       regex constant below for the exact pattern.
    2. For that criterion, resolve which file(s) the judge is actually shown: judge.toml's own
       `[judge].files` (the criterion inherits its containing file's judge table, per
       BUILD-CONTRACT.md) or verifier.json's `source.file.arguments.path` /
       `source.text`/`source.response` equivalents. A criterion is flagged if EVERY resolved
       path looks like a candidate-output/deliverable path (matches the task's own graded
       deliverable filename(s), or a path prefixed `output/`, matching the one real example
       this check was built from) and NONE of them looks like an environment/source-material
       path (anything else the task ships, e.g. under `environment/`) -- i.e. the judge is
       shown ONLY the candidate's own work product for a question that is inherently about
       comparing that work product against something else.

Status: v1, new, uncalibrated -- built and self-tested against a synthetic fixture reproducing
the review's own described shape (an invention-detection criterion whose `source` names only an
`output/`-prefixed file) and spot-checked against `pipeline/data/sample_corpus/task_11`'s real
`tests/verifier.json` during development (that task's own invention-adjacent criteria, e.g. "do
not add unsupported symptoms," are graded from `output/clinical_note.pdf` alone -- flagged by
this check as a real instance of the exact pattern this review described, not yet confirmed
against a human read of whether the environment's source documents were meant to be graded
alongside it here). Not run over a real corpus at scale.

Usage:
    python invention_detection_input_check.py <TASK-ID> [<TASK-ID> ...] --root <path> \\
        --out report.json
    python invention_detection_input_check.py --all --root <path> --out report.json

Known limits, disclosed rather than silently dropped:
    - Keyword/regex detection of "this criterion is about invention" will both miss phrasings
      not in the pattern list (false negative) and occasionally fire on a criterion that uses
      one of these words in an unrelated sense (false positive) -- read the flagged criterion's
      own text before treating a hit as confirmed.
    - The "is this an environment/source path" classification is itself a path-shape heuristic
      (contains `environment/`, or does not match `output/`-prefixed / the task's own graded
      filenames) -- a task whose source documents happen to live under a differently-named
      directory is invisible to the "has source visibility" half of this check and could read
      as flagged even if the judge legitimately does see the source material under an
      unrecognized path.
    - Only checks WHICH FILES a criterion is configured to see, never whether the judge's
      SYSTEM PROMPT or the criterion's own instructions separately paste source content inline
      as literal text (a task authoring pattern this script cannot detect from config alone).
    - verifier.json's `source` block shapes vary by `source.type` (file/text/response/...); this
      script recognizes `file` (checks `arguments.path`) and `text`/`response` (checked, but a
      literal `text` source is rarely the candidate's own output, so a `text`-type source is
      never itself flagged as a candidate-output-only signal) -- an unrecognized `source.type`
      is reported as `source_type_not_understood`, not silently treated as either safe or
      flagged.
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

INVENTION_RE = re.compile(
    r"\binvent(?:ed|ing|s)?\b"
    r"|\bmade[\s-]up\b|\bmake[\s-]up\b"
    r"|\bfabricat(?:e|ed|ion|ing)\b"
    r"|\bhallucinat(?:e|ed|ion|ing)\b"
    r"|\bunsupported\s+(?:claim|symptom|fact|figure|number|detail)s?\b"
    r"|\bnot\s+(?:in|from|present\s+in)\s+(?:the\s+)?(?:source|provided|given|input)\b"
    r"|\b(?:not|never)\s+(?:provided|given|stated)\b",
    re.IGNORECASE,
)

CANDIDATE_OUTPUT_PATH_RE = re.compile(r"^output/", re.IGNORECASE)
SOURCE_PATH_HINT_RE = re.compile(r"\benvironment\b", re.IGNORECASE)


def is_invention_criterion(text: str | None) -> bool:
    return bool(text) and bool(INVENTION_RE.search(text))


def classify_path(path: str) -> str:
    if CANDIDATE_OUTPUT_PATH_RE.search(path):
        return "candidate_output"
    if SOURCE_PATH_HINT_RE.search(path):
        return "source_material"
    return "unknown"


# ---------------------------------------------------------------------------
# per-format criterion + visible-files extraction
# ---------------------------------------------------------------------------


def analyze_judge_toml(data: dict) -> list[dict]:
    out = []
    judge = data.get("judge") if isinstance(data.get("judge"), dict) else {}
    files = judge.get("files") if isinstance(judge.get("files"), list) else []
    criteria = data.get("criterion")
    if not isinstance(criteria, list):
        return out
    for c in criteria:
        if not isinstance(c, dict):
            continue
        text = c.get("description")
        if not is_invention_criterion(text):
            continue
        classes = {classify_path(str(f)) for f in files}
        out.append(
            {
                "name": c.get("name"),
                "text": text,
                "visible_files": [str(f) for f in files],
                "file_classes": sorted(classes),
                "flagged": bool(files)
                and "source_material" not in classes
                and "unknown" not in classes,
            }
        )
    return out


def analyze_verifier_json(data: dict) -> list[dict]:
    out = []
    verifiers = data.get("verifiers")
    if not isinstance(verifiers, list):
        return out
    for v in verifiers:
        if not isinstance(v, dict):
            continue
        assertion = v.get("assertion") if isinstance(v.get("assertion"), dict) else {}
        rubric = assertion.get("rubric") if isinstance(assertion.get("rubric"), dict) else {}
        text = rubric.get("prompt")
        if not is_invention_criterion(text):
            continue

        source = v.get("source") if isinstance(v.get("source"), dict) else {}
        source_type = source.get("type")
        visible_paths: list[str] = []
        understood = True
        if source_type == "file":
            file_block = source.get("file") if isinstance(source.get("file"), dict) else {}
            args = file_block.get("arguments") if isinstance(file_block.get("arguments"), dict) else {}
            path = args.get("path")
            if isinstance(path, str):
                visible_paths.append(path)
        elif source_type in ("text", "response"):
            # Not a candidate-deliverable path at all -- inline text or a chat response is
            # neither classified as candidate_output nor as source_material by path shape; see
            # module docstring's Known limits for why this is reported, not silently treated as
            # safe.
            visible_paths = []
        else:
            understood = False

        classes = {classify_path(p) for p in visible_paths}
        out.append(
            {
                "name": v.get("name"),
                "text": text,
                "source_type": source_type,
                "visible_files": visible_paths,
                "file_classes": sorted(classes),
                "flagged": (
                    bool(visible_paths)
                    and "source_material" not in classes
                    and "unknown" not in classes
                ),
                "source_type_not_understood": not understood,
            }
        )
    return out


def analyze_config_file(path: Path, fmt: str, task_dir: Path) -> dict:
    rel = str(path.relative_to(task_dir)).replace("\\", "/")
    cfg = {"path": rel, "format": fmt, "parse_error": None, "criteria": []}
    try:
        text = path.read_text(encoding="utf-8")
        data = tomllib.loads(text) if fmt in ("judge_toml", "other_toml") else json.loads(text)
    except Exception as e:
        cfg["parse_error"] = f"{type(e).__name__}: {e}"
        return cfg

    if fmt == "judge_toml":
        cfg["criteria"] = analyze_judge_toml(data)
    elif fmt == "verifier_json":
        cfg["criteria"] = analyze_verifier_json(data)
    # manifest.json / other_toml / other_json: no known invention-criterion shape yet: reported
    # with zero criteria found rather than guessed at.
    return cfg


def analyze_task(task_dir: Path) -> dict:
    task_id = task_dir.name
    result = {"task_id": task_id, "config_files": [], "status": None, "errors": []}

    specs = detlint.discover_config_specs(task_dir)
    if not specs:
        result["status"] = "skip"
        result["errors"].append("no grading-config file found under tests/ for this task")
        return result

    any_flagged = False
    any_invention_criteria = False
    for path, fmt in specs:
        cfg = analyze_config_file(path, fmt, task_dir)
        result["config_files"].append(cfg)
        for c in cfg["criteria"]:
            any_invention_criteria = True
            if c.get("flagged"):
                any_flagged = True

    if any_flagged:
        result["status"] = "fail"
    elif any_invention_criteria:
        result["status"] = "pass"
    else:
        result["status"] = "no_invention_criteria_found"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Flags invention/fabrication-detection criteria whose grading config shows the "
            "judge only the candidate's own deliverable, never the source material a judge "
            "would need to actually tell invented content from correctly-sourced content."
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
    n_none = sum(1 for r in results if r["status"] == "no_invention_criteria_found")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_no_invention_criteria_found": n_none,
        "n_skip": n_skip,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_none} no_invention_criteria_found / {n_skip} skip "
        f"out of {len(results)} task(s)"
    )
    for r in results:
        if r["status"] != "fail":
            continue
        for cfg in r["config_files"]:
            for c in cfg.get("criteria", []):
                if c.get("flagged"):
                    print(
                        f"  {r['task_id']}: fail  [{cfg['path']}: {c['name']!r} -- "
                        f"visible files {c['visible_files']!r}, no source material shown]"
                    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
