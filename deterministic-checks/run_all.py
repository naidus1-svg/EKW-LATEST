#!/usr/bin/env python3
"""needs Python 3.11+ for tomllib (several of the checks this orchestrates require it)

Batch runner: invokes every applicable deterministic check in this folder against one --root
of task packages, in one command, and aggregates every script's own JSON report into one
combined result -- instead of running each of the ~17 scripts here by hand, once per task or
once per --all sweep, and cross-referencing their outputs yourself.

Why this is a SEPARATE script rather than a change to any check: every check in this folder is
deliberately standalone (its own CLI, its own JSON schema, importable on its own) so it can be
run, read, and trusted independently -- see this folder's own README.md. This script does not
change that; it only drives them, unmodified, and normalizes their differing CLI shapes and
report schemas into one place. No check script is imported for its logic here, only invoked as
a subprocess exactly as a person would run it by hand.

What it does NOT run, and why:
    - `formula_cache_autofix.py` and `workbook_recalc.py` are excluded by default -- both WRITE
      to files (they patch stale formula caches), which is a fix step, not a check, and this
      script's whole job is read-only triage. Run them yourself, deliberately, once you've read
      `formula_health_check.py`'s findings and decided a batch is worth auto-patching. Pass
      --include-autofix to also run `formula_cache_autofix.py` here in --dry-run (report-only)
      mode alongside the read-only checks; it is never run in write mode by this script.
    - `duplicate_criterion_check.py` scans for xlsx-format rubrics (the older Excel-rubric
      shape), not the judge.toml/verifier.json shape most other checks here expect. It is still
      run (against the same --root, recursively) since a batch may mix formats, but its result
      is reported as a single BATCH-level finding, not per-task, because that script has no
      per-task filtering of its own -- see its own --help.
    - `rubric_schema_check.py` only understands `judge.toml` (the SVC-PC package shape); on a
      verifier.json-shaped (EKW) task it reports `parse_errors: ["no judge.toml under
      tests/..."]`, which this script recognizes and reports as `not_applicable` for that task,
      never as a fail -- confirmed against this repo's own `pipeline/data/sample_corpus/task_11`
      (a real verifier.json task) during development.

Every OTHER check here shares one CLI shape (`--all|task_ids... --root ROOT [--id-prefix P]
[--out OUT]`), confirmed directly against each script's own `--help` while building this runner,
not assumed: `environment_input_check.py`, `answer_key_leakage_check.py`,
`answer_key_content_leak_check.py`, `deliverable_count_check.py`, `deliverable_filename_check.py`,
`deliverable_integrity_check.py`, `judge_criterion_name_duplicate_check.py`,
`judge_determinism_config_lint.py`, `rubric_text_lint.py`, `tab_naming_check.py`,
`formula_health_check.py`, plus this batch's own additions (`judge_panel_size_check.py`,
`criterion_condition_count_check.py`, `invention_detection_input_check.py`,
`golden_dependency_reachability_check.py`). Each is invoked once per run_all.py invocation
(never once per task), exactly like calling it by hand with --all or an explicit task list.

Status: v1, new. Exercised end-to-end against this repo's own real
`pipeline/data/sample_corpus/task_11` fixture during development (every applicable check ran,
`rubric_schema_check.py`'s format mismatch correctly read as not_applicable rather than a false
fail) -- not yet run against a real multi-hundred-task batch.

Usage:
    # Every task under --root
    python run_all.py --all --root <path> --out-dir results/

    # An explicit list
    python run_all.py TASK-1 TASK-2 TASK-3 --root <path> --out-dir results/

    # A list from a file, one id per line
    python run_all.py $(cat tasklist.txt) --root <path> --out-dir results/

    # Also run formula_cache_autofix.py in --dry-run (report what it WOULD patch, writes nothing)
    python run_all.py --all --root <path> --out-dir results/ --include-autofix

Output: one `<check_name>.json` per check under --out-dir (that check's own, unmodified report),
plus `summary.json` (the normalized per-task-per-check grid this script builds) and a printed
table. Exit code is 1 if any check reported a real `fail` for any task, 0 otherwise
(`not_applicable`/`skip`/`error` never count toward the exit code alone -- see the printed
summary for those, they are disclosed, not swallowed).

Known limits, disclosed rather than silently dropped:
    - This script does not run the two checks that need a human or an LLM
      (`content-audit/SKILL.md`, `structural-audit/SKILL.md`) -- those are methodology
      checklists, not scripts with a CLI to invoke; run them separately per this folder's
      README.md and docs/QC-SOP-first-run.md.
    - `v0-checks/*.py` are excluded entirely -- they are explicitly unvalidated per their own
      docstrings (see GAP-ANALYSIS.md); running them alongside calibrated checks in one combined
      summary risks a reader treating their output with the same trust as the rest.
    - Every check here still runs at its own pace and cost independently (most are instant,
      zero-LLM); this script does not parallelize across checks or tasks -- straightforward to
      add later if batch size makes serial runtime a real problem, not done here to keep the
      first version simple and its behavior easy to reason about.
    - A check that this script fails to invoke at all (missing dependency, crashes before
      writing its own JSON) is reported as `error` for every task in the batch for that check,
      with the captured stderr attached -- never silently dropped from the summary.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib  # noqa: F401
except ImportError:  # pragma: no cover
    print(
        "This script requires Python 3.11+ (several checks it orchestrates need tomllib, "
        "stdlib-only from 3.11 on). Run it with python3.11/python3.12, or the repo's "
        "pipeline/.venv.",
        file=sys.stderr,
    )
    raise SystemExit(1)

HERE = Path(__file__).resolve().parent

# Every check confirmed (against its own --help, not assumed) to share the standard
# --all|task_ids...--root ROOT [--id-prefix P] [--out OUT] shape.
STANDARD_CHECKS = [
    "environment_input_check.py",
    "answer_key_leakage_check.py",
    "answer_key_content_leak_check.py",
    "deliverable_count_check.py",
    "deliverable_filename_check.py",
    "deliverable_integrity_check.py",
    "judge_criterion_name_duplicate_check.py",
    "judge_determinism_config_lint.py",
    "rubric_text_lint.py",
    "tab_naming_check.py",
    "formula_health_check.py",
    # this batch's own additions -- same CLI shape by design
    "judge_panel_size_check.py",
    "criterion_condition_count_check.py",
    "invention_detection_input_check.py",
    "golden_dependency_reachability_check.py",
    # Added 2026-09-22 after a 30-task fix session shipped defects that these checks already
    # covered but nothing invoked -- the fix skill named only three gates, so ~87 of the ~90
    # checks here never ran. Each CLI below was confirmed to accept --all/--root/--out/--id-prefix
    # by running its own --help, not assumed from this file's docstring.
    "verifier_requirements_pin_mismatch_check.py",
    "source_truncation_check.py",
    "xlsx_extraction_budget_check.py",
    "harness_fragility_check.py",
]

# LLM-BACKED, deliberately NOT in the default sweep: judge_scope_under_inclusion_check.py and
# sibling_criterion_asymmetry_check.py both call out to an LLM backend and report `error` for
# every task when none is configured (confirmed by running them here: "No LLM backend available
# after 2 attempts"). Including them would put a row of `error` in every summary and dilute the
# signal from the deterministic checks around them. Run them deliberately, with a backend, when
# you want their judgment -- they cover real mechanisms (G1 judge-scope under-inclusion, G4
# sibling asymmetry) that no deterministic check in this folder replaces.
LLM_BACKED_NOT_RUN = [
    "judge_scope_under_inclusion_check.py",
    "sibling_criterion_asymmetry_check.py",
]

# A SECOND real CLI shape in this folder: positional root, --task (repeatable), --json.
# Same shape as RUBRIC_SCHEMA_CHECK below; confirmed against each script's own --help.
POSITIONAL_ROOT_CHECKS = [
    "compound_criterion_check.py",
    "pinned_value_prescreen_check.py",
]

# weight_aggregation_check.py is deliberately NOT run here: it requires --run <run_root>
# (a directory of real eval reward artifacts), not just a package root, so it cannot answer
# anything from a package-only sweep. Run it yourself when you have a with_runs bundle.

# rubric_schema_check.py: positional root, --task (repeatable), --json -- not --all/--root/--out.
RUBRIC_SCHEMA_CHECK = "rubric_schema_check.py"

# duplicate_criterion_check.py: --root (file or xlsx dir), --glob, --out -- no task concept.
DUPLICATE_CRITERION_CHECK = "duplicate_criterion_check.py"

# Writes files -- excluded unless --include-autofix, and even then only in --dry-run.
AUTOFIX_CHECK = "formula_cache_autofix.py"


CHECK_TIMEOUT_SECONDS = 600


def run(cmd: list[str]) -> tuple[int, str, str]:
    """Never lets one check hang the whole batch: a check that runs past
    CHECK_TIMEOUT_SECONDS is killed and reported as returncode -1 with a clear stderr message,
    rather than blocking every remaining check (and every remaining task) indefinitely. Found
    necessary the hard way: duplicate_criterion_check.py has no per-task scoping of its own (see
    run_duplicate_criterion_check below) and a first version of this caller pointed it at an
    entire multi-hundred-task --root even when only one task_id was requested, making it scan
    every task's xlsx files -- slow enough on a real corpus (274 tasks, files freshly downloaded
    and likely still carrying an macOS quarantine flag that adds a per-file scan delay on first
    open) to look indistinguishable from a genuine hang without a timeout to bound it."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CHECK_TIMEOUT_SECONDS)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return -1, stdout, stderr + f"\n[run_all.py] killed after exceeding {CHECK_TIMEOUT_SECONDS}s timeout"


def run_standard_check(script: str, root: Path, task_ids: list[str] | None, out_dir: Path) -> dict:
    out_path = out_dir / f"{Path(script).stem}.json"
    cmd = [sys.executable, str(HERE / script), "--root", str(root), "--out", str(out_path)]
    cmd += task_ids if task_ids else ["--all"]
    rc, _stdout, stderr = run(cmd)
    report = None
    if out_path.exists():
        try:
            report = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception as e:
            stderr += f"\n[run_all.py] could not parse {out_path}: {e}"
    return {"script": script, "returncode": rc, "report": report, "stderr": stderr.strip()}


def run_rubric_schema_check(root: Path, task_ids: list[str] | None, out_dir: Path) -> dict:
    out_path = out_dir / "rubric_schema_check.json"
    cmd = [sys.executable, str(HERE / RUBRIC_SCHEMA_CHECK), str(root), "--json", str(out_path)]
    for t in task_ids or []:
        cmd += ["--task", t]
    rc, _stdout, stderr = run(cmd)
    report = None
    if out_path.exists():
        try:
            report = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception as e:
            stderr += f"\n[run_all.py] could not parse {out_path}: {e}"
    return {"script": RUBRIC_SCHEMA_CHECK, "returncode": rc, "report": report, "stderr": stderr.strip()}


def run_positional_root_check(script: str, root: Path, task_ids: list[str] | None,
                              out_dir: Path) -> dict:
    """Same invocation shape as run_rubric_schema_check: positional root, repeatable --task,
    --json. Added 2026-09-22 for compound_criterion_check.py and pinned_value_prescreen_check.py,
    whose CLIs were confirmed by running their own --help rather than assumed from this file's
    docstring (which asserts every non-special check takes --all/--root -- true when written, no
    longer true for every script in the folder)."""
    out_path = out_dir / script.replace(".py", ".json")
    cmd = [sys.executable, str(HERE / script), str(root), "--json", str(out_path)]
    for t in task_ids or []:
        cmd += ["--task", t]
    rc, _stdout, stderr = run(cmd)
    report = None
    if out_path.exists():
        try:
            report = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception as e:
            stderr += f"\n[run_all.py] could not parse {out_path}: {e}"
    return {"script": script, "returncode": rc, "report": report, "stderr": stderr.strip()}


def run_duplicate_criterion_check(root: Path, task_ids: list[str] | None, out_dir: Path) -> dict:
    """duplicate_criterion_check.py has no --all/task_ids of its own (it globs rubric xlsx
    files under whatever --root it's given, recursively, with no per-task concept -- see its
    own --help). Pointing it at the FULL multi-hundred-task root when the caller only asked
    about a handful of task_ids would scan every OTHER task's xlsx files too -- wasted work at
    best, and on a real multi-hundred-task corpus, slow enough to look like a hang (see `run()`
    above). When explicit task_ids are given, this runs the script once per task directory
    instead and merges the per-file results; --all still points it at the whole root in one
    call, since that's the same set of files either way."""
    out_path = out_dir / "duplicate_criterion_check.json"

    if task_ids is None:
        cmd = [sys.executable, str(HERE / DUPLICATE_CRITERION_CHECK), "--root", str(root), "--out", str(out_path)]
        rc, _stdout, stderr = run(cmd)
        report = None
        if out_path.exists():
            try:
                report = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception as e:
                stderr += f"\n[run_all.py] could not parse {out_path}: {e}"
        return {"script": DUPLICATE_CRITERION_CHECK, "returncode": rc, "report": report, "stderr": stderr.strip()}

    merged_results = []
    stderrs = []
    any_ran = False
    for tid in task_ids:
        task_dir = root / tid
        if not task_dir.is_dir():
            continue
        per_task_out = out_dir / f"duplicate_criterion_check.{tid}.json"
        cmd = [sys.executable, str(HERE / DUPLICATE_CRITERION_CHECK), "--root", str(task_dir), "--out", str(per_task_out)]
        rc, _stdout, stderr = run(cmd)
        if rc not in (0, 1):
            stderrs.append(f"{tid}: {stderr.strip()}")
            continue
        any_ran = True
        if per_task_out.exists():
            try:
                sub = json.loads(per_task_out.read_text(encoding="utf-8"))
                for r in sub.get("results", []):
                    r["_task_id"] = tid
                    merged_results.append(r)
            except Exception as e:
                stderrs.append(f"{tid}: could not parse {per_task_out}: {e}")
            finally:
                per_task_out.unlink(missing_ok=True)

    if not any_ran:
        # Every per-task call reported "No rubric files found" (exit 1, no report) -- the
        # normal case for a batch of judge.toml/verifier.json tasks with no xlsx rubric at all.
        return {
            "script": DUPLICATE_CRITERION_CHECK,
            "returncode": 1,
            "report": None,
            "stderr": "No rubric files found" if not stderrs else "\n".join(stderrs),
        }

    aggregate = {
        "n_files": len(merged_results),
        "n_fail": sum(1 for r in merged_results if r.get("status") == "fail"),
        "results": merged_results,
    }
    out_path.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    return {"script": DUPLICATE_CRITERION_CHECK, "returncode": 0, "report": aggregate, "stderr": "\n".join(stderrs)}


def run_autofix_dry_run(root: Path, task_ids: list[str] | None, out_dir: Path) -> dict:
    out_path = out_dir / "formula_cache_autofix.json"
    cmd = [
        sys.executable, str(HERE / AUTOFIX_CHECK),
        "--root", str(root), "--out", str(out_path), "--dry-run",
    ]
    cmd += task_ids if task_ids else ["--all"]
    rc, _stdout, stderr = run(cmd)
    report = None
    if out_path.exists():
        try:
            report = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception as e:
            stderr += f"\n[run_all.py] could not parse {out_path}: {e}"
    return {"script": AUTOFIX_CHECK, "returncode": rc, "report": report, "stderr": stderr.strip()}


# ---------------------------------------------------------------------------
# normalization: build a per-task-per-check status grid from each script's own report shape
# ---------------------------------------------------------------------------


# Not every check in this folder actually emits a "status" field on each result item (confirmed
# by reading real output during development, not assumed) -- rubric_text_lint.py's per-task
# result carries `errors`/`findings` instead. This is the fallback used only when "status" is
# genuinely absent, never as a substitute for a check's own explicit status when one exists.
NO_JUDGE_TOML_MARKERS = ("no judge.toml", "no tests/deliverables")


def infer_status_from_errors_and_findings(r: dict) -> str:
    errors = r.get("errors") or r.get("parse_errors") or []
    if any(any(marker in e for marker in NO_JUDGE_TOML_MARKERS) for e in errors):
        return "not_applicable"
    if errors:
        return "error"
    findings = r.get("findings") or r.get("high_findings") or []
    return "fail" if findings else "pass"


def normalize_standard(result: dict) -> dict:
    """Standard-shape reports carry {"results": [{"task_id":..., ...}, ...]}, but the field
    naming a per-task verdict, and its vocabulary, is NOT uniform across scripts -- confirmed by
    reading each script's real output during development:
        - "status" with pass/fail/skip (most scripts)
        - "status" with clean/candidate/flagged/error (answer_key_content_leak_check.py)
        - "status" with flag/clean/parse_error/no_determinism_fields_found/...
          (judge_determinism_config_lint.py)
        - no "status" field at all (rubric_text_lint.py) -- see infer_status_from_errors_and_findings
    This function returns whatever the script's own vocabulary is (or the inferred fallback),
    UNCHANGED -- see SAFE_STATUSES below for how that raw value gets classified as a real
    finding or not for the summary/exit-code, without trying to force every script's own
    vocabulary into one fake shared enum.
    """
    grid = {}
    report = result["report"]
    if report is None:
        return grid  # error case handled separately
    for r in report.get("results", []):
        status = r.get("status")
        if status is None:
            status = infer_status_from_errors_and_findings(r)
        grid[r.get("task_id", "?")] = status
    return grid


# Status tokens, across every check's own vocabulary (confirmed by reading real output, not
# assumed), that mean "nothing here needs attention" -- everything else (fail, flag, flagged,
# candidate, error, parse_error, ...) counts as a real finding for the exit code and is left
# un-normalized in the table so a reader sees the check's own word for what happened.
SAFE_STATUSES = {
    "pass",
    "clean",
    "skip",
    "not_applicable",
    "no_determinism_fields_found",
    "no_criteria_found",
    "no_invention_criteria_found",
    "no_models_field",
}


def normalize_rubric_schema(result: dict) -> dict:
    grid = {}
    report = result["report"]
    if report is None:
        return grid
    for item in report:
        task = item.get("task", "?")
        if item.get("ok"):
            grid[task] = "pass"
            continue
        parse_errors = item.get("parse_errors") or []
        if any("no judge.toml" in e for e in parse_errors):
            grid[task] = "not_applicable"
        else:
            grid[task] = "fail"
    return grid


def normalize_positional_root(result: dict) -> dict:
    """compound_criterion_check.py and pinned_value_prescreen_check.py both emit the same
    report shape as rubric_schema_check.py -- a list of per-task dicts carrying `task`, `ok`
    and `parse_errors` -- confirmed by running each against a real package and reading the
    JSON, not assumed from the shared CLI shape.

    Both are LINTS, not gates: they flag candidates for a human to disposition (a compound
    criterion or a pinned value can be perfectly correct), so a `fail` here means "has
    candidates", not "is broken". The three blocking gates stay harbor_rubric_gate.py,
    reward_signal_gate.py and container_build_check.py."""
    grid = {}
    report = result["report"]
    if report is None:
        return grid
    for item in report:
        task = item.get("task", "?")
        if item.get("parse_errors"):
            grid[task] = "fail"
        else:
            grid[task] = "pass" if item.get("ok") else "fail"
    return grid


def build_summary(check_name: str, result: dict) -> dict:
    if result["report"] is None and result["returncode"] not in (0, 1):
        # A genuine invocation failure (crash, missing dep) -- distinct from "ran fine, 1 task
        # failed", which also exits 1 for these scripts by convention.
        return {"_error": result["stderr"] or f"exit code {result['returncode']}, no report written"}
    if check_name == RUBRIC_SCHEMA_CHECK:
        return normalize_rubric_schema(result)
    if check_name in POSITIONAL_ROOT_CHECKS:
        return normalize_positional_root(result)
    return normalize_standard(result)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Runs every applicable deterministic check in this folder against one --root of "
            "task packages, in one command, and aggregates their reports. Excludes "
            "formula_cache_autofix.py and workbook_recalc.py by default (both write files) -- "
            "pass --include-autofix to also run the autofix check in --dry-run only."
        )
    )
    ap.add_argument("task_ids", nargs="*", help="one or more task ids (directory names under --root)")
    ap.add_argument("--all", action="store_true", help="run against every task directory found under --root")
    ap.add_argument("--root", type=Path, required=True, help="root directory containing one subdirectory per task")
    ap.add_argument("--out-dir", type=Path, required=True, help="directory to write every check's report plus summary.json into")
    ap.add_argument("--include-autofix", action="store_true", help="also run formula_cache_autofix.py in --dry-run (report-only, writes nothing)")
    args = ap.parse_args()

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")
    if not args.root.exists():
        print(f"--root does not exist: {args.root}", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    task_ids = None if args.all else args.task_ids

    results = {}
    n_checks = (len(STANDARD_CHECKS) + len(POSITIONAL_ROOT_CHECKS) + 2
                + (1 if args.include_autofix else 0))
    i = 0

    for script in STANDARD_CHECKS:
        i += 1
        print(f"[{i}/{n_checks}] {script} ...", file=sys.stderr)
        results[script] = run_standard_check(script, args.root, task_ids, args.out_dir)

    for script in POSITIONAL_ROOT_CHECKS:
        i += 1
        print(f"[{i}/{n_checks}] {script} ...", file=sys.stderr)
        results[script] = run_positional_root_check(script, args.root, task_ids, args.out_dir)

    i += 1
    print(f"[{i}/{n_checks}] {RUBRIC_SCHEMA_CHECK} ...", file=sys.stderr)
    results[RUBRIC_SCHEMA_CHECK] = run_rubric_schema_check(args.root, task_ids, args.out_dir)

    i += 1
    print(f"[{i}/{n_checks}] {DUPLICATE_CRITERION_CHECK} (batch-level, not per-task) ...", file=sys.stderr)
    results[DUPLICATE_CRITERION_CHECK] = run_duplicate_criterion_check(args.root, task_ids, args.out_dir)

    if args.include_autofix:
        i += 1
        print(f"[{i}/{n_checks}] {AUTOFIX_CHECK} (--dry-run only) ...", file=sys.stderr)
        results[AUTOFIX_CHECK] = run_autofix_dry_run(args.root, task_ids, args.out_dir)

    # --- normalize into a per-task-per-check grid ---
    grid: dict[str, dict[str, str]] = {}  # task_id -> check -> status
    check_errors: dict[str, str] = {}
    batch_level: dict[str, object] = {}

    for check_name, result in results.items():
        if check_name == DUPLICATE_CRITERION_CHECK:
            report = result["report"]
            if report is None:
                # duplicate_criterion_check.py exits 1 with NO report written when --root has
                # no matching rubric files at all -- its own designed "nothing to check" path,
                # confirmed by reading its main(), not a crash. Recognized by message rather
                # than treated as an invocation error.
                if "No rubric files found" in (result["stderr"] or ""):
                    batch_level[check_name] = {"note": "not_applicable -- no .xlsx rubric files under --root"}
                else:
                    check_errors[check_name] = result["stderr"] or "no report written"
            else:
                batch_level[check_name] = {
                    "n_files": report.get("n_files", 0),
                    "n_fail": report.get("n_fail", 0),
                    "note": "xlsx-rubric collisions are batch-level, not per-task -- see report file",
                }
            continue
        summary = build_summary(check_name, result)
        if "_error" in summary:
            check_errors[check_name] = summary["_error"]
            continue
        for task_id, status in summary.items():
            grid.setdefault(task_id, {})[check_name] = status

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "checks_run": list(results.keys()),
        "check_errors": check_errors,
        "batch_level": batch_level,
        "per_task": grid,
    }
    (args.out_dir / "summary.json").write_text(json.dumps(aggregate, indent=2), encoding="utf-8")

    # --- print a readable table ---
    checks_ordered = [c for c in results if c != DUPLICATE_CRITERION_CHECK]
    print(f"\n{'task_id':30s} " + " ".join(f"{Path(c).stem[:12]:12s}" for c in checks_ordered))
    any_fail = False
    for task_id in sorted(grid):
        row = grid[task_id]
        cells = []
        for c in checks_ordered:
            status = row.get(c, "-")
            if status not in SAFE_STATUSES and status != "-":
                any_fail = True
            cells.append(f"{status[:12]:12s}")
        print(f"{task_id[:30]:30s} " + " ".join(cells))

    if check_errors:
        print("\nChecks that failed to run at all (not reflected in the table above):")
        for c, err in check_errors.items():
            print(f"  {c}: {err.splitlines()[0] if err else '(no detail)'}")

    if batch_level:
        print("\nBatch-level (not per-task) results:")
        for c, info in batch_level.items():
            print(f"  {c}: {info}")

    print(f"\nWrote {args.out_dir}/summary.json plus one report per check.")

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
