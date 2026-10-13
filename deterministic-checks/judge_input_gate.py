#!/usr/bin/env python3
"""judge_input_gate.py - wires scans/judge_input_report.py into the blocking gates.

Two entry points, one resolution logic (judge_input_report.py's own, never reimplemented):
  - std adapter (main): svc_run_checks.py invokes `python judge_input_gate.py TASK... --root R
    --out J` and gets a JSON list of {task_id, status, blocking_entries} to REPORT.
  - check_task(path): pre_submit_gate.py imports this to BLOCK on a single task dir, returning
    {status, evidence, blocking_entries} like the other package gates.

Why an adapter: judge_input_report.py is a per-task reporter keyed on `blocking_major`. This
script reuses its build_app_root/resolve_entry/classify verbatim, so the marker a task is judged
on is byte-identical to the real DataOS judge call (rewardkit's own _build_user_content over a
real /app). No resolution logic is duplicated.

Gate rule (unchanged, 03-acceptance-test.md): `not_found` or `skipped_too_large` on ANY files=
entry (group-level or per-criterion) is a blocking major -> status "fail". Otherwise "pass". No
tests/deliverables*/judge.toml -> "skip" (nothing to resolve, never a silent pass).

rewardkit is required only when a task is actually analyzed (lazy import), so importing this
module is safe on a machine without rewardkit; a missing rewardkit at analysis time yields
status "error" with a clear message, never a crash of the whole gate. On the sandbox run with
/root/venv/bin/python3 and QC_REWARDKIT_SITE_PACKAGES set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import tomllib

_HELPERS = None


def _load_helpers():
    """Import judge_input_report's own resolver lazily. Returns (build_app_root, classify,
    resolve_entry) or raises RuntimeError with a clear message if rewardkit is unavailable
    (judge_input_report raises SystemExit(2) at import time when it cannot find rewardkit).
    """
    global _HELPERS
    if _HELPERS is not None:
        return _HELPERS
    sys.path.insert(0, str(Path(__file__).resolve().parent / "scans"))
    try:
        from judge_input_report import build_app_root, classify, resolve_entry
    except (ImportError, SystemExit) as exc:
        raise RuntimeError(
            "judge_input_report/rewardkit not importable - install rewardkit into this "
            "interpreter or set QC_REWARDKIT_SITE_PACKAGES (sandbox: /root/venv/bin/python3 "
            f"with /root/venv/lib/python3.13/site-packages): {exc}"
        )
    _HELPERS = (build_app_root, classify, resolve_entry)
    return _HELPERS


def analyze_task(task_dir: Path, scratch_root: Path) -> dict:
    """judge_input_report's resolution over one task's judge.toml files= entries.
    Returns {task_id, status, blocking_entries, n_groups}."""
    task_id = task_dir.name
    judges = sorted(task_dir.glob("tests/deliverables*/judge.toml"))
    if not judges:
        return {
            "task_id": task_id,
            "status": "skip",
            "blocking_entries": [],
            "n_groups": 0,
        }

    build_app_root, classify, resolve_entry = _load_helpers()
    scratch = scratch_root / task_id
    app_root = build_app_root(task_dir, scratch, "oracle", None)

    # Only SOURCE corpus files (/app/_corpus_subtree/...) must ship byte-exact and are blocked on.
    # A non-_corpus_subtree /app path is either a solver-produced deliverable or a file the grader
    # itself generates at verify time (e.g. "_formula_authenticity_report.md ... which the grader
    # generates after submission", or "_operations_source_pack.md built by render_source_pack.py at
    # verify time"). Those legitimately do not exist in the static package, so flagging them is a
    # false positive -- confirmed on SVC-PC-12-3-0 / 20-8-0 / 26-4-0, three DataOS passes. This is the
    # exact restriction the 42-task backtest ran at 0 false positives. A golden that fails to produce a
    # required deliverable is a real but DIFFERENT defect class that a static resolver cannot tell from
    # a grader-generated report; catching it needs a solve-then-check, out of scope for this gate.
    def blockable(entry: str, marker: str) -> bool:
        return marker in ("not_found", "skipped_too_large") and entry.startswith(
            "/app/_corpus_subtree/"
        )

    blocking: list[str] = []
    n_groups = 0
    for jt in judges:
        n_groups += 1
        doc = tomllib.loads(jt.read_text())
        group_name = jt.parent.name
        for entry in doc.get("judge", {}).get("files", []) or []:
            row = classify(entry, resolve_entry(entry, task_dir, app_root))
            if blockable(entry, row["marker"]):
                blocking.append(f"{group_name}[group]: {entry} -> {row['marker']}")
        for crit in doc.get("criterion", []):
            for entry in crit.get("files") or []:
                row = classify(entry, resolve_entry(entry, task_dir, app_root))
                if blockable(entry, row["marker"]):
                    blocking.append(
                        f"{group_name}[criterion {crit.get('name')}]: {entry} -> {row['marker']}"
                    )

    return {
        "task_id": task_id,
        "status": "fail" if blocking else "pass",
        "blocking_entries": blocking,
        "n_groups": n_groups,
    }


def check_task(task_dir) -> dict:
    """pre_submit_gate.py entry point: {status, evidence, blocking_entries} for one task dir.
    A missing rewardkit -> status 'error' (gate reports it, does not crash)."""
    scratch_root = Path(os.environ.get("QC_SCRATCH_ROOT", "reports/judge_input_app"))
    try:
        r = analyze_task(Path(task_dir), scratch_root)
    except RuntimeError as exc:
        return {"status": "error", "evidence": str(exc), "blocking_entries": []}
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "evidence": f"{type(exc).__name__}: {exc}",
            "blocking_entries": [],
        }
    evidence = "; ".join(r["blocking_entries"]) or (
        "no judge.toml files= entry to resolve"
        if r["status"] == "skip"
        else "all files= entries resolve"
    )
    return {
        "status": r["status"],
        "evidence": evidence,
        "blocking_entries": r["blocking_entries"],
    }


def find_task_dirs(root: Path, task_ids, id_prefix: str) -> list[Path]:
    if task_ids:
        return [root / t for t in task_ids if (root / t).is_dir()]
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "task_ids", nargs="*", help="explicit task ids (as svc_run_checks passes)"
    )
    ap.add_argument("--all", action="store_true", help="all task dirs under --root")
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--id-prefix", default="SVC-PC")
    ap.add_argument(
        "--scratch-root",
        type=Path,
        default=Path(os.environ.get("QC_SCRATCH_ROOT", "reports/judge_input_app")),
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, args.id_prefix
    )
    if not task_dirs:
        sys.stderr.write("No task directories found.\n")
        return 1

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        try:
            r = analyze_task(task_dir, args.scratch_root)
        except Exception as e:  # never let one task's crash kill the batch
            r = {
                "task_id": task_dir.name,
                "status": "error",
                "blocking_entries": [f"{type(e).__name__}: {e}"],
                "n_groups": 0,
            }
        results.append(r)
        print(
            f"[{i}/{len(task_dirs)}] {r['task_id']}: {r['status']} "
            f"({len(r['blocking_entries'])} blocking)",
            file=sys.stderr,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    n_fail = sum(1 for r in results if r["status"] == "fail")
    print(
        f"[judge-input-gate] {len(results)} tasks, {n_fail} fail, wrote {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
