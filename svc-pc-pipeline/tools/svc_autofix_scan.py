#!/usr/bin/env python3
"""Bucket yesterday's SVC QC findings into the auto-fix boundary.

Reads every ekw/qc-validation-2026-09-11/task_*_qc_validation.xlsx (one workbook
per task, columns per Luiz's real schema). When ekw/svc-defect-rollup-2026-09-12.json
exists it is used only to pick which tasks --sample pulls first (lowest
confirmed_defect_count first) -- the rollup carries per-task counts, never a
per-finding Defect Class, so every finding is still read from its own xlsx
regardless of whether the rollup is present.

Defect Class values are bucketed per the tp-fp-classification taxonomy at
C:\\ekwqc\\repo\\automation\\tp-fp-classification\\SKILL.md, mapped onto the
auto-fix boundary decided for this skill:

    mechanical      format_convention, pipeline_packaging     -> auto-apply
    content_review  content_substance, design_intent          -> diff artifact
    no_action       dataos_format_artifact, agent_capability  -> already resolved
    needs_human     false_positive("none")/uncertain("unresolved") rows, and
                    any Defect Class this scan doesn't recognize

    python tools/svc_autofix_scan.py
    python tools/svc_autofix_scan.py --sample 5
"""

from __future__ import annotations

import argparse
import glob
import json
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VALIDATION_DIR = REPO_ROOT / "ekw" / "qc-validation-2026-09-11"
DEFAULT_ROLLUP = REPO_ROOT / "ekw" / "svc-defect-rollup-2026-09-12.json"
DEFAULT_OUT = REPO_ROOT / "ekw" / "svc-autofix-scan-2026-09-12.json"

MECHANICAL_CLASSES = {"format_convention", "pipeline_packaging"}
CONTENT_CLASSES = {"content_substance", "design_intent"}
NO_ACTION_CLASSES = {"dataos_format_artifact", "agent_capability"}
BUCKET_NAMES = ["mechanical", "content_review", "no_action", "needs_human"]


def task_filename(task_id: str) -> str:
    lowered = task_id.lower()
    stem = lowered if lowered.startswith("task_") else f"task_{lowered}"
    return f"{stem}_qc_validation.xlsx"


def bucket_for(defect_class: str) -> str:
    dc = (defect_class or "").strip().lower()
    if dc in MECHANICAL_CLASSES:
        return "mechanical"
    if dc in CONTENT_CLASSES:
        return "content_review"
    if dc in NO_ACTION_CLASSES:
        return "no_action"
    return "needs_human"


def load_rollup(path: Path) -> "list[dict] | None":
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("tasks", [])


def select_task_files(
    validation_dir: Path, rollup_tasks: "list[dict] | None", sample: "int | None"
) -> list[Path]:
    all_files = sorted(
        Path(p) for p in glob.glob(str(validation_dir / "task_*_qc_validation.xlsx"))
    )
    if sample is None:
        return all_files
    if rollup_tasks is None:
        return all_files[:sample]
    existing_names = {p.name for p in all_files}
    ordered = sorted(
        rollup_tasks,
        key=lambda t: (t.get("confirmed_defect_count", 0), t.get("task_id", "")),
    )
    picked = []
    for t in ordered:
        fn = task_filename(t["task_id"])
        if fn in existing_names:
            picked.append(validation_dir / fn)
        if len(picked) == sample:
            break
    return picked


def read_findings(xlsx_path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []
    header = list(rows[0])
    findings = []
    for i, row in enumerate(rows[1:], start=2):
        entry = {header[c]: row[c] for c in range(min(len(header), len(row)))}
        entry["_source_file"] = str(xlsx_path.relative_to(REPO_ROOT))
        entry["_row"] = i
        entry["_finding_id"] = f"{xlsx_path.stem}::{i}"
        findings.append(entry)
    return findings


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--validation-dir", type=Path, default=DEFAULT_VALIDATION_DIR)
    p.add_argument("--rollup", type=Path, default=DEFAULT_ROLLUP)
    p.add_argument("--sample", type=int, default=None)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()

    rollup_tasks = load_rollup(args.rollup)
    rollup_used = rollup_tasks is not None

    task_files = select_task_files(args.validation_dir, rollup_tasks, args.sample)
    if not task_files:
        raise SystemExit(
            f"no qc_validation.xlsx files found under {args.validation_dir}"
        )

    buckets: dict[str, list[dict]] = {name: [] for name in BUCKET_NAMES}
    for xlsx_path in task_files:
        for entry in read_findings(xlsx_path):
            buckets[bucket_for(entry.get("Defect Class", ""))].append(entry)

    result = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "rollup_used": rollup_used,
        "rollup_path": str(args.rollup) if rollup_used else None,
        "validation_dir": str(args.validation_dir),
        "sample_requested": args.sample,
        "tasks_scanned": [p.name for p in task_files],
        "task_count": len(task_files),
        "counts": {name: len(buckets[name]) for name in BUCKET_NAMES},
        "total_findings": sum(len(v) for v in buckets.values()),
        "buckets": buckets,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    print(f"Wrote {args.out}")
    print(
        f"Source for task selection: "
        f"{'rollup JSON (' + str(args.rollup) + ')' if rollup_used else 'xlsx files directly, rollup not found'}"
    )
    print(
        f"Tasks scanned: {len(task_files)} of {len(glob.glob(str(args.validation_dir / 'task_*_qc_validation.xlsx')))} total"
    )
    for name in BUCKET_NAMES:
        print(f"  {name}: {result['counts'][name]}")
    print(f"  total findings: {result['total_findings']}")


if __name__ == "__main__":
    main()
