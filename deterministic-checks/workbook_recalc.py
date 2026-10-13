#!/usr/bin/env python3
"""Retroactive formula-cache recalc for ALREADY-COLLECTED spreadsheets outside the
solution/-only task shape formula_cache_autofix.py assumes -- most usefully, agent-submitted
deliverables from a completed eval run (03_evals/task_<id>/evals/<model>/trial_1/deliverables/,
or wherever a harness's own eval-output layout puts them), not just a task's golden.

Why this is a SEPARATE script instead of a flag on formula_cache_autofix.py: that script's own
file discovery (`health.find_spreadsheets`) is hardcoded to `task_dir / "solution"` by design --
see its own module docstring and `formula_health_check.py`'s `find_spreadsheets()`. Everything
DOWNSTREAM of discovery in that script (`classify_task`, `apply_fix`, `verify_fix`,
`revert_files`) is plain relative-path logic against whatever `task_dir` you hand it, with no
"solution/" assumption baked in anywhere below discovery. This script reuses every one of those
functions completely unchanged (imported, not reimplemented) and only swaps in a different
discovery step: any .xlsx/.xlsm file found recursively under --root, not just
solution/**/*.xlsx. --root itself plays the role of "task_dir" for every reused function below.

Why this exists at all, and what it does NOT fix: an external QC review found that reading
submitted workbooks with `data_only=True` before grading -- the same defect class
`formula_cache_autofix.py` already patches for goldens -- graded 28 submissions across 18 tasks
with every calculation invisible, concentrated on whichever submissions leaned more heavily on
live formulas. The real, forward-looking fix for a harbor-shaped benchmark's own grading pass is
`pipeline/templates/harbor/verifier_lib/sources/xlsx.py`'s `extract_xlsx()`, which now
recomputes formulas live on every read (see that file's own module-level comment) -- so future
grading runs need nothing further once a task is rebuilt with the fixed template. This script
covers the gap that leaves: any batch of submissions that was ALREADY collected (and possibly
already graded under the old behavior) before that fix landed, or that is fed to a harness this
repo does not control and cannot patch. Point this script at that batch's deliverables directory
to mechanically fix the cache in place, so a re-grading pass sees correct values immediately
without re-running any model -- exactly the remediation path the review itself describes
("only the grading pass repeats").

Status: v1, new. The reused logic (`classify_task`/`apply_fix`/`verify_fix`/`revert_files`,
`analyze_workbook_raw`) is `formula_cache_autofix.py`'s own battle-tested-at-scale code,
unmodified. What is NEW and UNCALIBRATED here is only the discovery step (arbitrary directory
of xlsx/xlsm files instead of a task's solution/) and this CLI -- exercised against a synthetic
stale-cache fixture during development (a plain openpyxl-saved workbook with one formula cell,
which openpyxl itself always leaves cache-blank on save -- see formula_cache_autofix.py's own
module docstring for why), not yet run over a real batch of submitted deliverables.

Usage:
    # Report only -- see what WOULD be patched, without writing anything
    python workbook_recalc.py --root <dir_of_submitted_files> --dry-run --out report.json

    # Actually patch (backs up every file it touches to <file>.orig first, same as
    # formula_cache_autofix.py)
    python workbook_recalc.py --root <dir_of_submitted_files> --out report.json

    # A single file instead of a directory
    python workbook_recalc.py --root <path/to/one_submission.xlsx> --out report.json

What it does, in order (identical decision logic to formula_cache_autofix.py, just fed a
different file list):
    1. Finds every .xlsx/.xlsm file under --root (recursively, if --root is a directory; --root
       itself if it is a single file).
    2. Runs `formula_cache_autofix.analyze_workbook_raw()` on each (imported, not
       reimplemented), tagging every finding with `file` (path relative to --root).
    3. `formula_cache_autofix.classify_task()` sorts the pooled findings into clean / fixable /
       needs_judgment, using that script's own eligibility rules verbatim -- a recompute that
       comes back blank/NaN/error is NEVER treated as fixable here either; see that function's
       own docstring for exactly which kinds qualify.
    4. If fixable and not --dry-run: `formula_cache_autofix.apply_fix()` patches only the
       affected cells' cached `<v>` XML value (never the formula text, never any other cell),
       backing up every touched file to `<file>.orig` first. `formula_cache_autofix.verify_fix()`
       then re-recomputes each patched file fresh and confirms the write matches; a mismatch
       triggers `formula_cache_autofix.revert_files()` automatically, same auto-revert safety
       net as the source script.
    5. Writes one JSON result per file plus an aggregate report, and exits 1 if any file ended
       up needs_judgment or failed_reverted (0 otherwise), so this can gate a batch re-grade.

Known limits, disclosed rather than silently dropped:
    - Inherits every known limit of `formula_cache_autofix.py` and `formula_health_check.py`
      verbatim (see those modules) -- this script changes nothing about the underlying
      recompute/classification/patch logic, only what directory it is pointed at.
    - Does not itself re-run any grading/judge pass -- it only fixes the file on disk. Re-
      grading the now-patched deliverables is a separate step outside this script's scope.
    - Has not been run against a real batch of agent-submitted deliverables (only a synthetic
      fixture) -- submitted files may carry shapes/conventions (embedded charts, external
      references, non-standard sheet layouts) the source corpus this logic was calibrated
      against did not exercise. Run with --dry-run first on any new batch and read the report
      before trusting --out for anything but review.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

# Reuse formula_cache_autofix.py's own recompute/classification/patch/verify/revert logic
# verbatim -- see module docstring for exactly which pieces and why none of it is reimplemented.
import formula_cache_autofix as autofix  # noqa: E402

SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm"}


def find_spreadsheets(root: Path) -> list[Path]:
    """Every .xlsx/.xlsm file under `root`: `root` itself if it is a file, or every matching
    file found recursively if it is a directory. Deliberately NOT restricted to any
    subdirectory name (unlike formula_health_check.py's solution/-only find_spreadsheets) --
    this script's whole reason to exist is covering files outside that shape."""
    if root.is_file():
        return [root] if root.suffix.lower() in SPREADSHEET_SUFFIXES else []
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SPREADSHEET_SUFFIXES
    )


def gather_findings(root: Path, spreadsheets: list[Path]):
    """Same shape as formula_cache_autofix.gather_task_findings(), fed an arbitrary file list
    instead of health.find_spreadsheets(task_dir)."""
    all_findings = []
    files_meta = []
    errors = []
    for path in spreadsheets:
        rel = str(path.relative_to(root)).replace("\\", "/")
        findings, meta, _recomputed_map = autofix.analyze_workbook_raw(path)
        for f in findings:
            f["file"] = rel
        all_findings.extend(findings)
        files_meta.append(
            {
                "path": rel,
                "n_formula_cells": meta["n_formula_cells"],
                "n_findings": len(findings),
                "load_error": meta["load_error"],
            }
        )
        if meta["load_error"]:
            errors.append(f"{rel}: {meta['load_error']}")
    return all_findings, files_meta, errors


def process_root(root: Path, dry_run: bool) -> dict:
    """Mirrors formula_cache_autofix.process_task(), against --root instead of a task_dir's
    solution/. Returns one result dict, same shape as that function's per-task result."""
    spreadsheets = find_spreadsheets(root)
    result = {
        "root": str(root),
        "n_spreadsheets": len(spreadsheets),
        "files": [],
        "status": None,
        "reasons": [],
        "patched": [],
        "dry_run": dry_run,
    }
    if not spreadsheets:
        result["status"] = "clean"
        result["reasons"] = ["no .xlsx/.xlsm files found under --root"]
        return result

    findings, files_meta, load_errors = gather_findings(root, spreadsheets)
    result["files"] = files_meta
    if load_errors:
        result["status"] = "needs_judgment"
        result["reasons"] = load_errors
        return result

    verdict = autofix.classify_task(findings)
    result["status"] = verdict["status"]
    result["reasons"] = verdict["reasons"]

    if verdict["status"] != "fixable":
        return result

    if dry_run:
        result["status"] = "would_fix"
        result["patched"] = [
            {
                "file": f["file"],
                "sheet": f["sheet"],
                "cell": f["cell"],
                "cached_value": f["cached_value"],
                "recomputed_value": f["recomputed_value"],
            }
            for f in verdict["to_patch"]
        ]
        return result

    patch_reports = autofix.apply_fix(root, verdict["to_patch"])
    patched_files = list(patch_reports.keys())
    ok, verify_detail = autofix.verify_fix(root, patched_files, verdict["to_patch"])

    if ok:
        result["status"] = "fixed"
        result["patched"] = [
            {
                "file": f["file"],
                "sheet": f["sheet"],
                "cell": f["cell"],
                "cached_value": f["cached_value"],
                "recomputed_value": f["recomputed_value"],
            }
            for f in verdict["to_patch"]
        ]
    else:
        autofix.revert_files(root, patched_files)
        result["status"] = "failed_reverted"
        result["reasons"] = [
            "patch verification disagreed with a fresh recompute -- every touched file was "
            "reverted from its .orig backup automatically",
            verify_detail,
        ]
    result["patch_reports"] = patch_reports
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Retroactively recompute and patch stale/blank formula caches in ALREADY-"
            "COLLECTED spreadsheets (e.g. agent-submitted deliverables from a completed eval "
            "run), reusing formula_cache_autofix.py's own recompute/classify/patch/verify "
            "logic against an arbitrary directory instead of a task's solution/. Default "
            "WRITES to matching files (backed up to <file>.orig first) -- pass --dry-run to "
            "only report what would change."
        )
    )
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help=(
            "a single .xlsx/.xlsm file, or a directory to search recursively (REQUIRED -- no "
            "default, this must never silently assume a project-specific path)"
        ),
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be patched, without writing anything",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

    if not args.root.exists():
        print(f"--root does not exist: {args.root}", file=sys.stderr)
        return 1

    result = process_root(args.root, args.dry_run)
    result["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"root:   {result['root']}")
    print(f"status: {result['status']}  ({result['n_spreadsheets']} spreadsheet(s) found)")
    if result["reasons"]:
        for r in result["reasons"]:
            print(f"  ! {r}")
    for p in result.get("patched", []):
        verb = "would patch" if args.dry_run else "patched"
        print(f"  {verb}: {p['file']}:{p['sheet']}!{p['cell']}  -> {p['recomputed_value']!r}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0 if result["status"] in ("clean", "fixed", "would_fix") else 1


if __name__ == "__main__":
    raise SystemExit(main())
