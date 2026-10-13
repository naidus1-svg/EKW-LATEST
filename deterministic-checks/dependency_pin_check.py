"""Dependency pin check: does test.sh install grading-critical Python
packages without an exact version pin?

Why this exists. GLM's round 27/28 coverage synthesis (analyzing 9 real
SVC-PC tasks with confirmed DataOS Comprehensive Review defects) found this
as Class 3, GAP in 3/9 tasks (cov2-29-2-0 RC1, cov5 RC2, cov7 RC4): test.sh
installs `harbor-rewardkit[all]` from PyPI at grading time with no version
pin, even though a comment earlier in the SAME file names a specific tested
version (e.g. "harbor-rewardkit 0.1.7, latest on PyPI" at test.sh:7,
confirmed on SVC-PC-29-2-0). A future PyPI release of that package can
silently change extraction or scoring behavior despite the task's own files
never changing -- the exact non-reproducibility failure mode
harness_fragility_check.py's unpinned_judge_model finding already covers for
the JUDGE MODEL string; this check covers the same class of risk for the
PACKAGE INSTALL itself, which no existing check reads.

No existing check catches this (confirmed by the round 27/28 synthesis):
    - harness_fragility_check.py reads test.sh but only for three specific
      patterns (unpinned judge model string, infra-failure-scores-zero,
      config-file preflight) -- none of them scan for unversioned pip
      install commands.
    - ekw_check_b.py / svc_check_b.py check missing_test_sh (file existence)
      but not the content of pip install commands.
    - verifier_executability_check.py checks that test.sh parses under bash
      and rewardkit.discover() succeeds, not that dependencies are pinned.

What this check reads, per task:
    - tests/test.sh (SVC-PC and EKW both use a single task-level test.sh,
      confirmed by direct inspection of the real corpus -- not one per
      deliverable)

Classification per task:
    "warn"  -- at least one `pip install` line installs a package with no
              exact version pin. Warn, not fail: an unpinned install is a
              real reproducibility risk, not a per-task content defect, and
              (like harness_fragility_check.py's findings) is likely to fire
              identically across every task sharing the same test.sh
              template -- a platform-level property to disclose, not
              something an individual task author can fix.
    "pass"  -- every `pip install` line in test.sh pins an exact version.
    "skip"  -- no tests/test.sh found.
    "error" -- test.sh exists but cannot be read.

Exit code: 0 always (warn-tier, same convention as harness_fragility_check.py
and rubric_text_lint.py -- these findings never gate on their own).

Known limits, disclosed rather than silently dropped:
    - Parses test.sh as TEXT (regex), not as a shell AST. A pip install
      invoked through an indirect path (a variable holding the package
      spec, a requirements.txt file this check doesn't also read, a
      Makefile or wrapper script test.sh calls into) will not be detected.
      Every real test.sh in the corpus uses a direct, literal
      `pip install ... 'package[extras]'` line, so this is a disclosed
      limit rather than a known false negative on the real corpus as of
      this check's build.
    - A version RANGE pin (`>=1.0,<2.0`, `~=1.2`) is treated as UNPINNED for
      this check's purposes, even though it is more reproducible than a
      completely open install. The synthesis's own real examples are fully
      open installs with no pin at all; this check's bar is deliberately
      the strict one (exact `==`) rather than trying to judge whether a
      given range is narrow enough to be safe.
    - Does not attempt to verify that a pinned version and a "tested
      version" comment elsewhere in the file actually agree with each
      other -- it only checks whether the install itself is pinned at all.
      A task that pins to the WRONG version (rather than no version) is out
      of this check's scope.

Provenance: built 2026-09-15, GLM round 27/28 coverage synthesis Class 3.
Calibrated against the real corpus at
C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready.

Usage:
    python dependency_pin_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python dependency_pin_check.py --all --root <path> --out report.json
    python dependency_pin_check.py --all --root <path> --id-prefix SVC-PC- --out report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------

# Matches a `pip install` (or `pip3 install` / `python -m pip install`) line
# and captures the rest of the arguments so package specs can be pulled out.
PIP_INSTALL_LINE_RE = re.compile(
    r"^\s*(?:if\s+!\s*)?(?:python3?\s+-m\s+)?pip3?\s+install\b(?P<args>.*)$",
    re.MULTILINE | re.IGNORECASE,
)

# A single package spec token: optional quotes, package name, optional
# [extras], optional version constraint. Examples this must parse:
#   'harbor-rewardkit[all]'          -> unpinned
#   'harbor-rewardkit[all]==0.1.7'   -> pinned
#   harbor-rewardkit==0.1.7          -> pinned
#   harbor-rewardkit>=0.1.0          -> NOT pinned (range, see Known limits)
PACKAGE_SPEC_RE = re.compile(
    r"""['"]?
        (?P<name>[A-Za-z0-9._-]+)
        (?P<extras>\[[A-Za-z0-9,_-]+\])?
        (?P<constraint>==[A-Za-z0-9.*+!-]+)?
        (?P<other_constraint>(?:>=|<=|~=|>|<)[A-Za-z0-9.*+!-]+)?
        ['"]?
    """,
    re.VERBOSE,
)

# Flags / bare options on a pip install line that are not package specs.
PIP_FLAG_RE = re.compile(r"^--?[A-Za-z]")


def extract_package_specs(args_str: str) -> list[str]:
    """Pull individual package-spec tokens out of a pip install line's
    argument string, skipping flags like --quiet, -q, --no-cache-dir."""
    tokens = args_str.strip().split()
    specs = []
    for tok in tokens:
        stripped = tok.strip("'\"")
        if not stripped or PIP_FLAG_RE.match(stripped):
            continue
        # Skip requirements-file references and bare URLs/paths -- out of
        # scope for this check (see Known limits).
        if stripped.startswith("-") or stripped.startswith("http") or "/" in stripped:
            continue
        specs.append(stripped)
    return specs


def is_pinned(spec: str) -> bool:
    """True if a package spec has an exact `==` version pin. A range
    constraint (>=, <=, ~=, >, <) is treated as unpinned -- see the module
    docstring's Known limits section for why."""
    return "==" in spec


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_test_sh(test_sh: Path) -> dict:
    result = {
        "exists": test_sh.is_file(),
        "install_lines": [],
    }
    if not result["exists"]:
        return result

    text = test_sh.read_text(encoding="utf-8", errors="replace")
    for m in PIP_INSTALL_LINE_RE.finditer(text):
        args_str = m.group("args")
        specs = extract_package_specs(args_str)
        if not specs:
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        for spec in specs:
            result["install_lines"].append(
                {
                    "line": line_no,
                    "spec": spec,
                    "pinned": is_pinned(spec),
                }
            )
    return result


def analyze_task(task_dir: Path) -> dict:
    """Returns one result dict for one task. Never raises."""
    task_id = task_dir.name
    test_sh = task_dir / "tests" / "test.sh"
    result = {
        "task_id": task_id,
        "test_sh_exists": False,
        "findings": [],
        "n_findings": 0,
        "status": None,
        "errors": [],
    }

    try:
        analysis = analyze_test_sh(test_sh)
    except Exception as e:
        result["status"] = "error"
        result["errors"].append(f"could not read test.sh: {e}")
        return result

    result["test_sh_exists"] = analysis["exists"]
    if not analysis["exists"]:
        result["status"] = "skip"
        result["errors"].append("no tests/test.sh found for this task")
        return result

    unpinned = [i for i in analysis["install_lines"] if not i["pinned"]]
    if not analysis["install_lines"]:
        result["status"] = "skip"
        result["errors"].append("test.sh has no pip install line to check")
        return result

    if unpinned:
        specs = ", ".join(f"{i['spec']} (line {i['line']})" for i in unpinned)
        result["findings"].append(
            {
                "kind": "unpinned_dependency_install",
                "severity": "warn",
                "detail": (
                    f"test.sh installs the following package(s) with no exact "
                    f"version pin: {specs}. A future release of any of these "
                    "packages can change extraction or scoring behavior at "
                    "grading time despite the task's own files never "
                    "changing."
                ),
                "unpinned": unpinned,
            }
        )

    result["n_findings"] = len(result["findings"])
    result["status"] = "warn" if result["findings"] else "pass"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HOW_TO_READ_THIS_REPORT = {
    "purpose": (
        "Detects test.sh pip-install lines for grading-critical packages "
        "that have no exact version pin -- a future package release can "
        "silently change extraction or scoring behavior."
    ),
    "task_status": {
        "warn": (
            "At least one pip install line has no exact version pin. "
            "Platform-level, likely to fire identically across every task "
            "sharing the same test.sh template."
        ),
        "pass": "Every pip install line in test.sh pins an exact version.",
        "skip": "No tests/test.sh found, or no pip install line present.",
        "error": "test.sh exists but could not be read.",
    },
    "finding_kinds": {
        "unpinned_dependency_install": (
            "A pip install line installs a package with no `==` version "
            "pin (a range constraint like >=/~= is also treated as "
            "unpinned by this check's deliberately strict bar)."
        ),
    },
    "the_one_thing_this_check_cannot_see": (
        "An install invoked indirectly (a requirements.txt file this check "
        "does not also read, a variable holding the package spec, a "
        "wrapper script test.sh calls into). Only direct, literal "
        "`pip install ...` lines in test.sh itself are scanned."
    ),
}


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "") -> list[Path]:
    if task_ids:
        dirs = []
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


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Dependency pin check: flags test.sh pip-install lines for "
            "grading-critical packages with no exact version pin."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("task_ids", nargs="*", help="one or more task ids")
    ap.add_argument("--all", action="store_true", help="run every task under --root")
    ap.add_argument("--root", type=Path, default=None, required=False)
    ap.add_argument("--id-prefix", default="")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if args.root is None:
        ap.error("--root is required")
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")
    if not args.root.is_dir():
        print(
            f"--root does not exist or is not a directory: {args.root}", file=sys.stderr
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
                "test_sh_exists": False,
                "findings": [],
                "n_findings": 0,
            }
        results.append(r)
        kinds = [f["kind"] for f in r.get("findings", [])]
        print(
            f"    -> {r['status']}" + (f": {', '.join(kinds)}" if kinds else ""),
            file=sys.stderr,
        )

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    finding_counts: dict[str, int] = {}
    for r in results:
        for f in r.get("findings", []):
            finding_counts[f["kind"]] = finding_counts.get(f["kind"], 0) + 1

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
        print(
            "finding counts: "
            + ", ".join(f"{k}={v}" for k, v in sorted(finding_counts.items()))
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
