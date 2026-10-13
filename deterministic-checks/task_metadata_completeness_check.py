#!/usr/bin/env python3
"""task.toml [metadata] completeness check (shared, letter D, warn-only).

Why this file exists
--------------------
The coverage-gap synthesis over 9 real SVC-PC tasks with Comprehensive-Review
confirmed defects (comprehensive-review-qc-feedback-2026-09-15/coverage-
synthesis.md, "Class 1: task.toml [metadata] completeness") found that task.toml's
[metadata] block is incomplete in ALL 9 of 9 tasks reviewed: it carries only
`category = "SVC-PC"` and `tags = []`. Five required descriptive fields (domain,
occupation, sector, subdomain, task_type) are absent in every case. No existing
check anywhere in this pipeline reads task.toml's metadata block for
completeness:

  - Check A (content_audit_check.py) reads prompt/golden/rubric text, not task.toml
    metadata.
  - Check B (svc_check_b.py / ekw_check_b.py) reads task.toml only for
    missing_task_toml, task_toml_parse_error, and task_id_mismatch. No
    metadata-completeness finding kind exists.
  - All 27 C/D/E scripts operate on instruction.md, judge.toml, environment/,
    solution/, or tests/. None opens task.toml's [metadata] block.

This check closes that gap. It is the second of two new checks from round 29
(the first, the higher-impact duplicate-criterion-content check, runs in a
sibling worktree).

What it asserts (finding kinds, severity in brackets)
-------------------------------------------------------
  metadata_field_missing [warn]   a required [metadata] field is absent, or its
                                  value is the empty string / whitespace-only. One
                                  finding per missing/empty field (field-level
                                  granularity, see "Granularity choice" below).
  metadata_block_absent [warn]    task.toml itself is missing, so the [metadata]
                                  block cannot be inspected. Single finding (Check
                                  B already owns the fail-tier missing_task_toml
                                  finding for the same file; this check stays
                                  warn-only and never duplicates a hard fail).
  task_toml_unparseable [warn]    task.toml exists but does not parse under tomllib,
                                  so [metadata] cannot be inspected. Single finding
                                  (Check B owns the fail-tier task_toml_parse_error;
                                  this check stays warn-only).
  not_a_task_dir [info]           none of instruction.md/task.toml/environment/
                                  solution/tests present; status=skip, not a defect.

Status is `warn` if any warn-severity finding fired, otherwise `pass`. `skip`
means the task directory has none of the package files at all (not a task).
This check NEVER sets status to `fail`: per coverage-synthesis.md the defect has
"no scoring effect... cataloguing and discoverability, not grading correctness",
so a task never hard-fails on metadata alone. Warn is a disclosure, never a gate.

Granularity choice
-------------------
One finding per missing/empty field (field-level), not a single combined finding
listing every missing field. Rationale:

  - Field-level findings are directly actionable: each names the exact field a
    maintainer must fill in, so a fixer can track which fields got populated
    across revisions without re-reading the whole message.
  - It matches the per-item reporting style the rest of this directory already
    uses (judge_criterion_name_duplicate_check reports one finding per collision;
    criterion_field_missing in svc_check_b reports one finding per missing
    criterion field).
  - The roll-up is unaffected by the count: 1 missing field or 5 all roll up to
    `warn` for the task either way, so the extra findings cost nothing at the
    summary layer and gain precision at the finding layer.

The trade-off is up to 5 findings per task on the empty-metadata shape (the real
SVC-PC shape: category + tags only), but all are warn/minor, so this is
informational volume, not noise that changes any verdict.

Calibration (2026-09-15, real task.toml samples in this worktree)
------------------------------------------------------------------
No synthesis was needed: real task.toml files for BOTH shapes are present in this
worktree.

  - Real empty-metadata shape (SVC-PC): svc-task-samples-56/SVC-PC-*/task.toml
    carry exactly `category = "SVC-PC"` and `tags = []` under [metadata] and
    nothing else (confirmed on SVC-PC-12-6-0, 12-7-0, 14-4-0, 15-5-0). This is
    the exact shape coverage-synthesis.md describes. Produces 5
    metadata_field_missing findings, status=warn.
  - Real complete-metadata shape (EKW):
    ekw-task-samples/task_175-full-for-verifier-execution/task.toml carries all
    five fields (domain, occupation, sector, subdomain, task_type) non-empty.
    Produces 0 findings, status=pass.

What it does NOT check
----------------------
  - Whether task.toml itself exists / parses (Check B's job; this check only
    notes the metadata consequence when it cannot inspect, at warn tier).
  - Whether the field VALUES are correct or meaningful (it checks presence and
    non-emptiness only; "Finance" vs "finance" vs a wrong sector is out of
    scope, by design, since there is no authoritative vocabulary list to
    validate against).
  - Anything about prompt/golden/rubric content (Check A's job).
  - Anything about the build package shape (Check B's job).

Usage
-----
    python task_metadata_completeness_check.py --all --root DIR --out report.json
    python task_metadata_completeness_check.py SVC-PC-12-6-0 SVC-PC-14-4-0 --root DIR --out report.json

`--root` is required, no default, on purpose (same convention as svc_check_b.py).
CLI is the "std" shape the orchestrators use: positional task_ids + --root +
--out, so it registers as style="std" in both svc_run_checks.py and
ekw/ekw_run_checks.py. Exit 0 when every task passes, 1 when any task warns,
2 on bad usage. Stdlib only (Python 3.11+ for tomllib).

Output shape (--out)
--------------------
    {generated, root, n_tasks, n_pass, n_warn, n_skip, findings_by_kind,
     results: [ {task_id, status, n_fail, n_warn, n_info,
     findings: [{kind, severity, message, field, ...}], seconds} ]}

(n_pass / n_warn / n_skip instead of n_pass / n_fail / n_skip because this check
never fails a task; the keys stay the same names the other "std" checks use so
the orchestrator merge logic counts them without special-casing.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.stderr.write("needs Python 3.11+ for tomllib\n")
    raise SystemExit(2)

# Task filenames carry cp437 mojibake and spaces; a cp1252 Windows console would
# raise UnicodeEncodeError on the first finding (and on --help). Print what can
# be printed, same guard svc_check_b.py uses.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

HERE = Path(__file__).resolve().parent

# The five required descriptive fields under [metadata], per coverage-synthesis.md
# Class 1. Category and tags are platform-recognized fields the build pipeline
# already emits; they are NOT in this list because their presence is expected and
# not part of the confirmed defect (the defect is the five descriptive fields
# being absent in 9/9 reviewed tasks).
REQUIRED_METADATA_FIELDS = ("domain", "occupation", "sector", "subdomain", "task_type")

# A task directory is recognized as a real task (not skipped) if it has any of
# these, same heuristic svc_check_b.py uses.
TASK_MARKERS = ("instruction.md", "task.toml", "environment", "solution", "tests")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _finding(kind: str, severity: str, message: str, **extra) -> dict:
    d = {"kind": kind, "severity": severity, "message": message}
    d.update(extra)
    return d


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _is_empty(value) -> bool:
    """A metadata field counts as missing when the key is absent, None, or an
    empty/whitespace-only string. A non-string non-empty value (a number or
    list, unusual but not forbidden by TOML) is treated as present: this check
    validates presence and non-emptiness, not type correctness, by design."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


# ---------------------------------------------------------------------------
# the check proper
# ---------------------------------------------------------------------------


def check_task(task_dir: Path) -> dict:
    """Metadata completeness for one task. Never raises on a malformed package."""
    t0 = time.time()
    tid = task_dir.name
    findings: list[dict] = []
    res = {
        "task_id": tid,
        "status": "pass",
        "n_fail": 0,
        "n_warn": 0,
        "n_info": 0,
        "findings": findings,
        "metadata_present_fields": [],
        "seconds": 0.0,
    }

    has_any = any((task_dir / x).exists() for x in TASK_MARKERS)
    if not has_any:
        res["status"] = "skip"
        findings.append(
            _finding(
                "not_a_task_dir",
                "info",
                "none of instruction.md/task.toml/environment/solution/tests present",
            )
        )
        _finalize(res)
        res["seconds"] = round(time.time() - t0, 3)
        return res

    toml_p = task_dir / "task.toml"
    if not toml_p.is_file():
        # Check B owns the fail-tier missing_task_toml finding; this check only
        # notes the metadata consequence, at warn tier, never a hard fail.
        findings.append(
            _finding(
                "metadata_block_absent",
                "warn",
                "task.toml missing; [metadata] block cannot be inspected",
            )
        )
        _finalize(res)
        res["seconds"] = round(time.time() - t0, 3)
        return res

    try:
        task_toml = tomllib.loads(_read_text(toml_p))
    except Exception as e:
        findings.append(
            _finding(
                "task_toml_unparseable",
                "warn",
                f"task.toml does not parse; [metadata] block cannot be inspected: {e}",
            )
        )
        _finalize(res)
        res["seconds"] = round(time.time() - t0, 3)
        return res

    metadata = task_toml.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    present = []
    for field in REQUIRED_METADATA_FIELDS:
        if field in metadata and not _is_empty(metadata[field]):
            present.append(field)
            continue
        findings.append(
            _finding(
                "metadata_field_missing",
                "warn",
                f"[metadata].{field} is missing or empty",
                field=field,
            )
        )
    res["metadata_present_fields"] = present

    _finalize(res)
    res["seconds"] = round(time.time() - t0, 3)
    return res


def _finalize(res: dict) -> None:
    sev = [f["severity"] for f in res["findings"]]
    res["n_fail"], res["n_warn"], res["n_info"] = (
        sev.count("fail"),
        sev.count("warn"),
        sev.count("info"),
    )
    if res["status"] != "skip":
        # warn-only: any warn finding -> warn, else pass. Never fail.
        res["status"] = "warn" if res["n_warn"] else "pass"


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


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


def run(
    root: Path,
    task_ids=None,
    id_prefix: str = "",
    quiet: bool = False,
    jobs: int | None = None,
) -> dict:
    """Programmatic entry point (the orchestrators use this). Returns the report
    dict. Tasks are independent and the work is trivially-light file I/O (one
    small TOML parse per task), so a thread pool is used only for large corpora
    (`jobs`, default one per CPU), same pattern svc_check_b.py uses."""
    dirs = find_task_dirs(root, task_ids, id_prefix)

    def one(d: Path) -> dict:
        return check_task(d)

    from concurrent.futures import ThreadPoolExecutor

    workers = max(1, jobs or (os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, dirs))
    if not quiet:
        for r in results:
            note = next(
                (f["message"] for f in r["findings"] if f["severity"] == "warn"), ""
            )
            print(
                f"{r['status']:<4} {r['task_id']:<20} warn={r['n_warn']} {note}",
                file=sys.stderr,
            )
    by_kind: dict[str, int] = {}
    for r in results:
        for f in r["findings"]:
            k = f"{f['kind']} [{f['severity']}]"
            by_kind[k] = by_kind.get(k, 0) + 1
    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": str(root),
        "n_tasks": len(results),
        "n_pass": sum(r["status"] == "pass" for r in results),
        "n_warn": sum(r["status"] == "warn" for r in results),
        "n_skip": sum(r["status"] == "skip" for r in results),
        "findings_by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "task_ids", nargs="*", help="task directory names under --root (omit with --all)"
    )
    ap.add_argument(
        "--all", action="store_true", help="every task directory under --root"
    )
    ap.add_argument(
        "--root",
        required=True,
        help="directory holding one task package per subdirectory (native contract shape)",
    )
    ap.add_argument(
        "--id-prefix", default="", help="with --all, only directories starting with this prefix"
    )
    ap.add_argument("--out", help="write the JSON report here")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="tasks checked concurrently (default: one per CPU)",
    )
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2
    if not args.all and not args.task_ids:
        sys.stderr.write("give task ids or --all\n")
        return 2

    report = run(
        root,
        args.task_ids or None,
        args.id_prefix,
        quiet=args.quiet,
        jobs=args.jobs,
    )
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {args.out}", file=sys.stderr)
    print(
        f"{report['n_pass']}/{report['n_tasks']} pass, {report['n_warn']} warn, "
        f"{report['n_skip']} skip",
        file=sys.stderr,
    )
    for k, n in list(report["findings_by_kind"].items())[:25]:
        print(f"  {n:>4}  {k}", file=sys.stderr)
    # exit 1 when any task warned (no task can fail), 0 when all pass/skip, 2 on
    # bad usage (handled above). Matches the "non-zero on findings" convention
    # the other checks use, while staying consistent with warn-only semantics.
    return 1 if report["n_warn"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
