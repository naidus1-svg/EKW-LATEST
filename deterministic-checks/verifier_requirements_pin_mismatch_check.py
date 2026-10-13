"""Verifier-requirements pin-mismatch check: do the two requirements files that feed the
verifier's Python environment pin DIFFERENT exact versions of the SAME package?

Why this exists. A 2026-09-17 verification pass across 54 real EKW tasks' Comprehensive
Review findings confirmed a recurring true-positive defect, distinct from
dependency_pin_check.py's territory (that script flags an UNPINNED pip-install line in
test.sh; this one flags TWO files that are both pinned, but pinned to DIFFERENT exact
versions of the same package): `environment/verifier-requirements.txt` and
`tests/__verifier_lib/requirements.txt` disagree on the exact version of one or more shared
packages. Confirmed via direct diff on task_1, task_126, task_133, task_141, task_37,
task_35_fixed -- consistently pypdf and litellm, e.g. task_1: `litellm==1.83.7` in
environment/verifier-requirements.txt vs `litellm==1.93.0` in
tests/__verifier_lib/requirements.txt; `pypdf==6.4.2` vs `pypdf==6.15.0` on the same task.

Why this matters even though both are pinned (so dependency_pin_check.py's own "is anything
unpinned" bar reports these tasks clean): the harness pre-warms a venv and hash-checks it
against one of these two files to decide whether it can reuse the cache or must rebuild from
scratch. When the two files disagree, whichever one the pre-warm step didn't key off of no
longer matches what actually gets installed at grading time -- defeating the hash-check and
forcing a slow rebuild on every run, and worse, meaning the actually-installed package version
depends on WHICH of the two files the harness happened to read last, not a single source of
truth either file's own author could have verified by reading their own file alone.

Confirmed NOT already covered by dependency_pin_check.py (its own module docstring and CLI
help say so explicitly, verified by reading its source, not just its docstring): that script
reads only `tests/test.sh` for direct `pip install` lines and classifies a spec as pinned/
unpinned; it never reads either requirements.txt file this check reads, and has no concept of
two files disagreeing with each other.

What this check reads, per task (checks both the SVC-PC/EKW-legacy `initial_workspace` path
and the flatter path seen in the 2026-09-17 review batch; either present is enough to compare
if both files exist):
    - environment/verifier-requirements.txt
    - tests/__verifier_lib/requirements.txt

Each is parsed as a plain pip-requirements file: one `package==version` (or bare `package`,
unpinned in that file) per non-blank, non-comment line; `package[extras]==version` extras are
stripped before comparing names. Package name comparison is case-insensitive and normalizes
`_`/`-` (PEP 503-ish) so `Some_Package` and `some-package` are treated as the same package.

Classification per task:
    "fail"  -- at least one package name appears in BOTH files with an exact `==` pin in
              EACH, and the two pinned versions differ. This is the confirmed real defect:
              a silent hash-check bypass at grading time, not a hypothetical.
    "warn"  -- at least one package appears in both files but only one side has an exact pin
              (so they cannot be proven to disagree, but also cannot be proven to agree) --
              disclosed as a softer, non-definitive signal, never gating.
    "pass"  -- both files exist, every shared package pins identically (or neither file pins
              any shared package -- nothing to disagree on).
    "skip"  -- fewer than two of these files exist for this task (nothing to compare).
    "error" -- a file exists but could not be read.

Exit code: 0 always (same convention as dependency_pin_check.py -- these are disclosure
findings for a human/downstream policy call about which file the harness treats as
authoritative, not a task-authoring defect this check can adjudicate on its own).

Known limits, disclosed rather than silently dropped:
    - Text-parses requirements.txt as line-oriented pip syntax, not a full requirements-file
      grammar (no `-r other.txt` includes, no environment markers, no hash pins). Every real
      instance seen in this corpus is a flat, direct `pkg==version` list.
    - Does not know which of the two files the harness actually keys its venv hash-check off
      of -- reports the disagreement itself, not which side is "wrong". Deciding which file
      should be authoritative (or whether they should be merged into one) is a platform/harness
      policy call, out of this check's scope.

Usage (same CLI shape as dependency_pin_check.py):
    python verifier_requirements_pin_mismatch_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python verifier_requirements_pin_mismatch_check.py --all --root <path> --out report.json
    python verifier_requirements_pin_mismatch_check.py --all --root <path> --id-prefix task_ --out report.json
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
# requirements.txt parsing
# ---------------------------------------------------------------------------

# One requirement line: optional extras, optional exact `==` pin. Deliberately narrow -- see
# module docstring's Known limits. Skips -r/-e/--hash/etc. lines and blank/comment lines.
REQ_LINE_RE = re.compile(
    r"""^\s*
        (?P<name>[A-Za-z0-9._-]+)
        (?:\[[A-Za-z0-9,_-]+\])?
        \s*
        (?:==\s*(?P<version>[A-Za-z0-9.*+!_-]+))?
    """,
    re.VERBOSE,
)


def _normalize_name(name: str) -> str:
    """PEP 503-ish normalization so `Some_Package` and `some-package` compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(text: str) -> dict[str, str | None]:
    """package (normalized name) -> exact pinned version, or None if the line names the
    package with no `==` pin (a bare name or a range constraint, both treated the same as
    dependency_pin_check.py's own "not exactly pinned" bar). Last occurrence of a duplicate
    name wins, matching pip's own last-line-wins behavior for a requirements file."""
    out: dict[str, str | None] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = REQ_LINE_RE.match(line)
        if not m or not m.group("name"):
            continue
        name = _normalize_name(m.group("name"))
        version = m.group("version")
        out[name] = version
    return out


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------

# Both known real path shapes for the two requirements files, checked in order; the first
# that exists for a task is used. Confirmed real corpus layout (2026-09-17 review batch) uses
# the plain paths below directly under the task root.
FILE_A_CANDIDATES = ("environment/verifier-requirements.txt",)
# BOTH spellings of the vendored library dir are real in this corpus: 28 of the 79 shipped v7
# tasks (the whole LGL batch, plus task_78/79/81/86/97/98) use the SINGLE-underscore
# `tests/verifier_lib/`. Listing only the double-underscore path made this check report `skip`
# -- not `fail` -- on 35% of the corpus, including task_LGL-168, whose drift (litellm 1.83.7 vs
# 1.93.0, pypdf 6.4.2 vs 6.15.0, missing formulas==1.3.4) is the exact example in this file's
# own docstring and which shipped, failed dependency install, and scored reward 0.0.
FILE_B_CANDIDATES = (
    "tests/__verifier_lib/requirements.txt",
    "tests/verifier_lib/requirements.txt",
)


def _first_existing(task_dir: Path, candidates: tuple[str, ...]) -> Path | None:
    for rel in candidates:
        p = task_dir / rel
        if p.is_file():
            return p
    return None


def analyze_task(task_dir: Path) -> dict:
    """Returns one result dict for one task. Never raises."""
    task_id = task_dir.name
    result: dict = {
        "task_id": task_id,
        "file_a": None,
        "file_b": None,
        "findings": [],
        "n_findings": 0,
        "status": None,
        "errors": [],
    }

    file_a = _first_existing(task_dir, FILE_A_CANDIDATES)
    file_b = _first_existing(task_dir, FILE_B_CANDIDATES)
    result["file_a"] = str(file_a.relative_to(task_dir)) if file_a else None
    result["file_b"] = str(file_b.relative_to(task_dir)) if file_b else None

    if not file_a or not file_b:
        result["status"] = "skip"
        missing = []
        if not file_a:
            missing.append(FILE_A_CANDIDATES[0])
        if not file_b:
            missing.append(FILE_B_CANDIDATES[0])
        result["errors"].append(
            "fewer than two requirements files found for this task, nothing to "
            f"compare (missing: {', '.join(missing)})"
        )
        return result

    try:
        reqs_a = parse_requirements(file_a.read_text(encoding="utf-8", errors="replace"))
        reqs_b = parse_requirements(file_b.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        result["status"] = "error"
        result["errors"].append(f"could not read a requirements file: {e}")
        return result

    shared = sorted(set(reqs_a) & set(reqs_b))
    hard_mismatches = []
    soft_mismatches = []
    for pkg in shared:
        va, vb = reqs_a[pkg], reqs_b[pkg]
        if va is None or vb is None:
            if va != vb:
                soft_mismatches.append({"package": pkg, "file_a_version": va, "file_b_version": vb})
            continue
        if va != vb:
            hard_mismatches.append({"package": pkg, "file_a_version": va, "file_b_version": vb})

    if hard_mismatches:
        specs = ", ".join(
            f"{m['package']} ({result['file_a']}=={m['file_a_version']} vs "
            f"{result['file_b']}=={m['file_b_version']})"
            for m in hard_mismatches
        )
        result["findings"].append(
            {
                "kind": "verifier_requirements_pin_mismatch",
                "severity": "fail",
                "detail": (
                    f"{result['file_a']} and {result['file_b']} pin DIFFERENT exact "
                    f"versions of the same package(s): {specs}. Whichever file the "
                    "harness's pre-warmed-venv hash-check does not key off of will "
                    "silently diverge from what actually gets installed at grading "
                    "time, defeating the cache and forcing a rebuild -- or worse, "
                    "making the installed version depend on read order rather than "
                    "a single source of truth."
                ),
                "mismatches": hard_mismatches,
            }
        )
    if soft_mismatches:
        specs = ", ".join(
            f"{m['package']} ({result['file_a']}={m['file_a_version']!r} vs "
            f"{result['file_b']}={m['file_b_version']!r})"
            for m in soft_mismatches
        )
        result["findings"].append(
            {
                "kind": "verifier_requirements_pin_ambiguous",
                "severity": "warn",
                "detail": (
                    f"{result['file_a']} and {result['file_b']} both name the same "
                    f"package(s) but only one side pins an exact version, so "
                    f"agreement cannot be confirmed: {specs}."
                ),
                "mismatches": soft_mismatches,
            }
        )

    result["n_findings"] = len(result["findings"])
    if hard_mismatches:
        result["status"] = "fail"
    elif soft_mismatches:
        result["status"] = "warn"
    else:
        result["status"] = "pass"
    return result


# ---------------------------------------------------------------------------
# CLI -- same shape as dependency_pin_check.py
# ---------------------------------------------------------------------------

HOW_TO_READ_THIS_REPORT = {
    "purpose": (
        "Detects environment/verifier-requirements.txt and "
        "tests/__verifier_lib/requirements.txt pinning DIFFERENT exact versions of the "
        "same package -- defeats a pre-warmed-venv hash-check and can make the "
        "installed version depend on file read order."
    ),
    "task_status": {
        "fail": (
            "At least one shared package is pinned to two different exact versions "
            "across the two files -- confirmed real defect, not a hypothesis."
        ),
        "warn": (
            "A shared package is pinned on only one side, so agreement can't be "
            "confirmed either way."
        ),
        "pass": "Both files exist and every shared package agrees (or nothing overlaps).",
        "skip": "Fewer than two of the two requirements files exist for this task.",
        "error": "A requirements file exists but could not be read.",
    },
    "finding_kinds": {
        "verifier_requirements_pin_mismatch": (
            "Two files pin the same package to two different exact `==` versions."
        ),
        "verifier_requirements_pin_ambiguous": (
            "Two files name the same package but only one pins an exact version."
        ),
    },
    "the_one_thing_this_check_cannot_see": (
        "Which of the two files the harness's own pre-warm/hash-check step actually "
        "treats as authoritative -- it reports the disagreement, not which side is wrong."
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
            "Verifier-requirements pin-mismatch check: flags environment/"
            "verifier-requirements.txt and tests/__verifier_lib/requirements.txt "
            "pinning different exact versions of the same package."
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
                "file_a": None,
                "file_b": None,
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
