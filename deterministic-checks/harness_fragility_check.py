"""Harness fragility check (Andrew pattern 9): is the grading harness itself
fragile or non-reproducible, independent of task content?

Why this exists. Andrew Ma's QC artifact (`ekw/andrew-11-pattern-qc-artifact-
2026-09-15.md`) named pattern 9 as "Harness is fragile or can't be reproduced"
(7/19 tasks): "Single unpinned judge, no checks that the file exists or is
valid, and infra failures that score as 0." The only existing check touching
this territory, `judge_determinism_config_lint.py`, covers only the
temperature/panel determinism slice. This check covers the three sub-issues
Andrew's real description actually names, each of which is a different kind of
harness fragility than an unpinned sampling temperature:

  1. unpinned_judge_model: the judge model string (judge.toml's [judge].judge
     or verifier.json's config.models) has no version pin. A floating alias
     like "anthropic/claude-sonnet-4-6" or "openai/gpt-5.4" can resolve to
     different underlying model weights or system prompts across time, making
     the same task's score non-reproducible between a run today and a run in
     six months. The provider controls what the alias points to, not the
     benchmark. A pinned model includes a date suffix ("model:2026-09-01"),
     a version tag ("model:v1.2.3"), a snapshot hash ("model@abc12345"), or
     a similar immutable identifier. This check fires when none of those are
     present in the model string.

  2. infra_failure_scores_zero: test.sh's infra-failure handler writes
     reward=0.0 when the grading infrastructure fails (pip install fails,
     judge API errors, missing credentials, rewardkit crash). A reward of
     0.0 is indistinguishable from a genuine zero-score submission in the
     reward field itself. The error message may go to runtime.log (SVC-PC,
     unstructured text) or to verifier-report.json (EKW, structured with an
     "errored" field), but the REWARD is still 0.0 in both cases. Andrew's
     description: "infra failures that score as 0." This check fires when
     test.sh has a write_infra_failure-style handler that writes 0.0 to a
     reward file. The structured-error-report detail is noted in the
     finding but does not suppress it: 0.0 in the reward is still
     indistinguishable from a genuine zero, even if a sidecar report has
     more context.

  3. no_grading_config_preflight: test.sh does not verify that the grading
     config file (judge.toml for SVC-PC, verifier.json for EKW) exists
     before running the judge. A missing config file causes the judge to
     silently produce no output or crash, which the infra-failure fallback
     then scores as 0.0. Andrew's description: "no checks that the file
     exists or is valid." This check fires when test.sh has no file-existence
     check (`-f`) referencing the benchmark's config file before the judge
     invocation. EKW's test.sh has this preflight (`if [ ! -f
     "$TESTS_DIR/verifier.json" ]`); SVC-PC's does not.

What this check reads, per task:
  - tests/deliverables*/judge.toml (SVC-PC) for [judge].judge (model string)
  - tests/verifier.json (EKW) for config.models (list of model strings)
  - tests/test.sh for the infra-failure handler and config-file preflight

Classification per task:
    "warn"  -- at least one of the three findings fired. These are
              platform-level harness-fragility properties, not per-task
              defects. They may fire universally within a benchmark (all
              SVC-PC tasks share the same test.sh, all EKW tasks share the
              same test.sh). The fix is at the platform level, not the
              per-task level.
    "pass"  -- no findings. All three sub-issues are mitigated.
    "skip"  -- no tests/ directory, or no test.sh AND no config files found.
    "error" -- a required file exists but cannot be read or parsed.

Exit code: 0 always. These findings are warn-level disclosures about
platform-level harness properties; they never gate on their own (same
convention as rubric_text_lint, answer_key_content_leak's "candidate" tier).

Known limits, disclosed rather than silently dropped:
    - CANNOT see harness-level or runner-level settings. If a benchmark
      pins the judge model at the HARNESS level (a launcher flag, an
      environment variable, code in the eval runner) rather than in the
      task-level config, this check cannot see that pin and will report
      the task-level model string as unpinned. Confirming a harness-level
      pin requires reading the harness/eval-runner code, not this check's
      output. Same blind spot `judge_determinism_config_lint.py` discloses
      for temperature/panel.
    - test.sh is parsed as TEXT (regex pattern matching), not as a
      structured format. A test.sh that handles infra failures through a
      different mechanism than a `write_infra_failure`-named function, or
      that writes the zero reward through an indirect path this check's
      patterns don't match, will not be detected. Every real test.sh in
      both the 27-task SVC-PC sample and the 14-task EKW sample uses the
      exact `write_infra_failure` pattern this check matches, so this is a
      disclosed limit rather than a known false negative on the real corpus.
    - The "unpinned" classification is based on the model string's textual
      content, not on a query to the provider's API. A model string that
      looks pinned (has a date suffix) but has been deprecated by the
      provider would still pass this check. Conversely, a provider that
      guarantees a floating alias never changes would make the "unpinned"
      finding a false positive in practice. This check reports what the
      string says, not what the provider does.
    - The config-preflight check looks for `-f` file-existence tests on the
      config file NAME (judge.toml / verifier.json) in test.sh. A preflight
      that checks a DIFFERENT name (a symlink, a wrapper script) or uses a
      different test (`-e`, `-r`) will not be detected. Both real test.sh
      files use `-f` on the exact config file name, so this matches the real
      corpus.
    - These findings are UNIVERSAL within each benchmark on the real
      corpus: all 27 SVC-PC tasks get all three findings, all 14 EKW tasks
      get unpinned_judge_model and infra_failure_scores_zero (but NOT
      no_grading_config_preflight, since EKW's test.sh has the preflight).
      This is a real platform-level property, not an over-firing check. The
      check's value is in distinguishing benchmarks that have the preflight
      (EKW) from those that don't (SVC-PC), and in providing a deterministic
      artifact that the harness's three fragility properties have been
      inspected, not assumed.

Provenance: built 2026-09-15 (round 17) in response to Andrew Ma's pattern 9
(harness fragile/irreproducible, 7/19 tasks). Reads the real test.sh and
judge config files from the 27-task SVC-PC and 14-task EKW samples directly,
not from assumptions about the pattern's shape. Follows the CLI/output
conventions of sibling checks in this folder (argparse with required --root,
--all + --id-prefix for batch runs, UTF-8 stdout/stderr reconfigure, per-task
result + aggregate JSON, batch run that never crashes on one task's malformed
file).

Usage:
    python harness_fragility_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python harness_fragility_check.py --all --root <path> --out report.json
    python harness_fragility_check.py --all --root <path> --id-prefix SVC-PC- --out report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------

# Model-string pinning indicators. If ANY of these match, the model is
# considered pinned (has an immutable version/date/hash identifier). If
# none match, the model is a floating alias the provider can update.
PIN_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")  # YYYY-MM-DD
PIN_DATE_COMPACT_RE = re.compile(r"\d{8}")  # YYYYMMDD
PIN_DATE_SHORT_RE = re.compile(r"-\d{4}$")  # -0125 (OpenAI month shorthand)
PIN_VERSION_RE = re.compile(r":v?\d+\.\d+\.\d+")  # :1.2.3 or :v1.2.3
PIN_HASH_RE = re.compile(r"@[a-f0-9]{8,}", re.I)  # @abc12345
PIN_SNAPSHOT_RE = re.compile(r":snapshot-|@snapshot:", re.I)

# test.sh infra-failure handler detection. Both real test.sh files in the
# corpus define a function named `write_infra_failure` that writes reward=0.0.
INFRA_FAILURE_FUNC_RE = re.compile(r"write_infra_failure\s*\(\)\s*\{", re.I)
REWARD_FILE_RE = re.compile(r"reward\.(txt|json)", re.I)
REWARD_ZERO_RE = re.compile(r"0\.0")
# Structured error report: EKW writes verifier-report.json with an "errored"
# field; SVC-PC only writes to runtime.log (unstructured).
STRUCTURED_REPORT_RE = re.compile(r"verifier-report\.json|errored", re.I)

# Config-file preflight: a file-existence check (-f) referencing the
# benchmark's config file name anywhere in test.sh.
PREFLIGHT_TEMPLATE = r"-f\s.*{config_name}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def is_model_pinned(model_str: str) -> bool:
    """True if the model string includes a version pin (date, hash, version,
    or snapshot suffix). False if it's a floating alias the provider can
    update. Empty string returns False (can't confirm pinned)."""
    if not model_str or not model_str.strip():
        return False
    s = model_str.strip()
    for pat in (
        PIN_DATE_RE,
        PIN_DATE_COMPACT_RE,
        PIN_DATE_SHORT_RE,
        PIN_VERSION_RE,
        PIN_HASH_RE,
        PIN_SNAPSHOT_RE,
    ):
        if pat.search(s):
            return True
    return False


def find_judge_models(task_dir: Path) -> list[dict]:
    """Find judge model strings from judge.toml (SVC-PC) and/or verifier.json
    (EKW). Returns [{"model": str, "source": str}, ...]. Every config file
    found is scanned, not just the first."""
    tests_dir = task_dir / "tests"
    models: list[dict] = []

    # judge.toml (SVC-PC): [judge].judge is a model string.
    judge_paths = sorted(
        set(tests_dir.glob("deliverables/judge.toml"))
        | set(tests_dir.glob("deliverables_*/judge.toml"))
    )
    for p in judge_paths:
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
            judge_table = data.get("judge", {})
            if isinstance(judge_table, dict):
                model = judge_table.get("judge")
                if model:
                    rel = str(p.relative_to(task_dir)).replace("\\", "/")
                    models.append({"model": str(model), "source": rel})
        except Exception:
            pass

    # verifier.json (EKW): config.models is a list of model strings.
    vp = tests_dir / "verifier.json"
    if vp.is_file():
        try:
            data = json.loads(vp.read_text(encoding="utf-8"))
            config = data.get("config", {})
            if isinstance(config, dict):
                model_list = config.get("models", [])
                if isinstance(model_list, list):
                    for m in model_list:
                        if m:
                            models.append(
                                {"model": str(m), "source": "tests/verifier.json"}
                            )
        except Exception:
            pass

    return models


def analyze_test_sh(
    task_dir: Path, config_names: list[str]
) -> dict:
    """Read test.sh and detect infra-failure handling and config preflight.
    config_names is the list of config file names this task uses
    (["judge.toml"], ["verifier.json"], or both)."""
    test_sh = task_dir / "tests" / "test.sh"
    result = {
        "exists": test_sh.is_file(),
        "infra_failure_handler": False,
        "infra_failure_reward_zero": False,
        "structured_error_report": False,
        "config_preflight": False,
        "preflight_checked_configs": [],
    }
    if not result["exists"]:
        return result

    text = test_sh.read_text(encoding="utf-8", errors="replace")

    # 1. infra-failure handler: look for write_infra_failure() or similar.
    if INFRA_FAILURE_FUNC_RE.search(text):
        result["infra_failure_handler"] = True
        # Check if it writes reward=0.0 (reward file reference + zero value).
        if REWARD_FILE_RE.search(text) and REWARD_ZERO_RE.search(text):
            result["infra_failure_reward_zero"] = True
        # Check for a structured error report alongside the zero reward.
        if STRUCTURED_REPORT_RE.search(text):
            result["structured_error_report"] = True

    # 2. config preflight: look for -f checks referencing any config file name.
    for config_name in config_names:
        pat = re.compile(
            PREFLIGHT_TEMPLATE.format(config_name=re.escape(config_name)),
            re.I,
        )
        if pat.search(text):
            result["config_preflight"] = True
            result["preflight_checked_configs"].append(config_name)

    return result


def to_jsonable(v):
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, list):
        return [to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): to_jsonable(x) for k, x in v.items()}
    return str(v)


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir: Path) -> dict:
    """Returns one result dict for one task. Never raises."""
    task_id = task_dir.name
    tests_dir = task_dir / "tests"
    result = {
        "task_id": task_id,
        "tests_dir_exists": False,
        "test_sh_exists": False,
        "models_checked": [],
        "findings": [],
        "n_findings": 0,
        "status": None,
        "errors": [],
    }

    if not tests_dir.is_dir():
        result["status"] = "skip"
        result["errors"].append("no tests/ directory found for this task")
        return result
    result["tests_dir_exists"] = True

    # Find judge models from all config files.
    models = find_judge_models(task_dir)
    result["models_checked"] = models

    # Determine which config file names this task uses (for preflight check).
    config_names = []
    if any(m["source"].endswith("judge.toml") for m in models):
        config_names.append("judge.toml")
    if any(m["source"].endswith("verifier.json") for m in models):
        config_names.append("verifier.json")
    # Also check if the files exist even if no model was extracted (parse error).
    if not config_names:
        if (tests_dir / "verifier.json").is_file():
            config_names.append("verifier.json")
        elif list(tests_dir.glob("deliverables*/judge.toml")) or (
            tests_dir / "deliverables" / "judge.toml"
        ).is_file():
            config_names.append("judge.toml")

    # Analyze test.sh.
    test_sh_result = analyze_test_sh(task_dir, config_names)
    result["test_sh_exists"] = test_sh_result["exists"]

    # If nothing to check at all, skip.
    if not models and not test_sh_result["exists"]:
        result["status"] = "skip"
        result["errors"].append(
            "no judge models found and no test.sh present -- nothing to check"
        )
        return result

    findings: list[dict] = []

    # Finding 1: unpinned judge model.
    unpinned = [m for m in models if not is_model_pinned(m["model"])]
    if unpinned:
        model_strs = ", ".join(m["model"] for m in unpinned)
        sources = sorted({m["source"] for m in unpinned})
        findings.append(
            {
                "kind": "unpinned_judge_model",
                "severity": "warn",
                "detail": (
                    f"Judge model(s) have no version pin: {model_strs}. The "
                    "provider can update what this alias resolves to, making "
                    "the same task's score non-reproducible across time. A "
                    "pinned model includes a date suffix, version tag, or "
                    "snapshot hash."
                ),
                "unpinned_models": unpinned,
                "sources": sources,
            }
        )

    # Finding 2: infra failure scores zero.
    if test_sh_result["infra_failure_reward_zero"]:
        if test_sh_result["structured_error_report"]:
            detail = (
                "test.sh's infra-failure handler writes reward=0.0 to "
                "reward.json, indistinguishable from a genuine zero score in "
                "the reward field. A structured error report (verifier-report"
                ".json with an errored field) IS also written, making the "
                "failure distinguishable in the sidecar report but NOT in the "
                "reward itself."
            )
        else:
            detail = (
                "test.sh's infra-failure handler writes reward=0.0 to "
                "reward.json, indistinguishable from a genuine zero score. "
                "The error message goes to runtime.log (unstructured text), "
                "not to a machine-readable error field in any reward file."
            )
        findings.append(
            {
                "kind": "infra_failure_scores_zero",
                "severity": "warn",
                "detail": detail,
                "structured_error_report": test_sh_result[
                    "structured_error_report"
                ],
            }
        )

    # Finding 3: no grading config preflight.
    if (
        test_sh_result["exists"]
        and config_names
        and not test_sh_result["config_preflight"]
    ):
        expected = ", ".join(config_names)
        findings.append(
            {
                "kind": "no_grading_config_preflight",
                "severity": "warn",
                "detail": (
                    f"test.sh does not verify that {expected} exists before "
                    "running the judge. A missing config file may cause a "
                    "silent judge failure that the infra-failure fallback "
                    "then scores as 0.0."
                ),
                "expected_configs": config_names,
            }
        )

    result["findings"] = findings
    result["n_findings"] = len(findings)
    result["status"] = "warn" if findings else "pass"

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HOW_TO_READ_THIS_REPORT = {
    "purpose": (
        "Detects the three sub-issues of Andrew pattern 9 (harness "
        "fragile/irreproducible): unpinned judge model, infra failures that "
        "score as 0, and no grading-config preflight in test.sh."
    ),
    "task_status": {
        "warn": (
            "At least one harness-fragility finding fired. These are "
            "platform-level properties, not per-task defects. They may fire "
            "universally within a benchmark."
        ),
        "pass": "No findings. All three sub-issues are mitigated.",
        "skip": "No tests/ directory, or no test.sh and no config files.",
        "error": "A required file exists but cannot be read or parsed.",
    },
    "finding_kinds": {
        "unpinned_judge_model": (
            "The judge model string has no version pin (date, hash, or "
            "snapshot suffix). The provider can update what this alias "
            "resolves to, making scores non-reproducible across time."
        ),
        "infra_failure_scores_zero": (
            "test.sh's infra-failure handler writes reward=0.0, "
            "indistinguishable from a genuine zero score. The error message "
            "may go to runtime.log (unstructured) or verifier-report.json "
            "(structured), but the REWARD is still 0.0 in both cases."
        ),
        "no_grading_config_preflight": (
            "test.sh does not verify that the grading config file (judge.toml "
            "or verifier.json) exists before running the judge. A missing "
            "config may cause a silent failure scored as 0.0."
        ),
    },
    "the_one_thing_this_check_cannot_see": (
        "Harness-level or runner-level settings that live outside the task's "
        "tests/ directory. If the judge model is pinned at the HARNESS level "
        "(a launcher flag, an env var, code in the eval runner), this check "
        "cannot see that pin and will report the task-level model string as "
        "unpinned. Same blind spot judge_determinism_config_lint.py discloses "
        "for temperature/panel."
    ),
}


def find_task_dirs(
    root: Path, task_ids=None, id_prefix: str = ""
) -> list[Path]:
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(
                    f"WARNING: task dir not found, skipping: {p}",
                    file=sys.stderr,
                )
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Harness fragility check (Andrew pattern 9): detects unpinned "
            "judge model, infra-failure-scores-zero, and no grading-config "
            "preflight from the task's judge config and test.sh."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "task_ids", nargs="*", help="one or more task ids (directory names under --root)"
    )
    ap.add_argument(
        "--all", action="store_true", help="run every task directory found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        required=False,
        help="root directory containing one subdirectory per task (REQUIRED)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error("--root is required")
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")
    if not args.root.is_dir():
        print(
            f"--root does not exist or is not a directory: {args.root}",
            file=sys.stderr,
        )
        return 2

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 2

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(task_dir)
        except Exception as e:
            r = {
                "task_id": task_dir.name,
                "status": "error",
                "errors": [f"unhandled exception: {e}"],
                "tests_dir_exists": False,
                "test_sh_exists": False,
                "models_checked": [],
                "findings": [],
                "n_findings": 0,
            }
        results.append(r)
        kinds = [f["kind"] for f in r.get("findings", [])]
        print(
            f"    -> {r['status']}  ({len(r.get('models_checked', []))} model(s), "
            f"{r['n_findings']} finding(s)"
            + (f": {', '.join(kinds)}" if kinds else "")
            + (f", test_sh={'yes' if r.get('test_sh_exists') else 'no'}"),
            file=sys.stderr,
        )

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    finding_counts: dict[str, int] = {}
    for r in results:
        for f in r.get("findings", []):
            k = f["kind"]
            finding_counts[k] = finding_counts.get(k, 0) + 1

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "id_prefix": args.id_prefix,
        "n_tasks": len(results),
        "status_counts": counts,
        "finding_counts": finding_counts,
        "how_to_read_this_report": HOW_TO_READ_THIS_REPORT,
        "results": results,
    }

    print(f"\n{len(results)} task(s) checked.")
    print("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if finding_counts:
        print("finding counts: " + ", ".join(
            f"{k}={v}" for k, v in sorted(finding_counts.items())
        ))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
