#!/usr/bin/env python3
"""Aggregate SVC false-positive screen results by task to identify repeat-defect tasks.

Input is the flat list of screened verdicts (one dict per finding: dataset, task_id,
name, verdict, etc.). This script groups findings by task and counts verdict types,
then sorts tasks ascending by confirmed defects to surface near-clean tasks first.
A task can appear under multiple datasets and will list all of them.

    python tools/svc_defect_rollup.py --input ekw/svc-fp-verdicts-2026-09-11.json

Output includes a short stdout summary and a JSON file with the full per-task tally.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "ekw" / "svc-fp-verdicts-2026-09-11.json"
DEFAULT_OUTPUT = REPO_ROOT / "ekw" / "svc-defect-rollup-2026-09-12.json"


def normalize_task_id(raw_id: str) -> str:
    """Strip task_ prefix if present, then lowercase for grouping."""
    normalized = raw_id.lower()
    if normalized.startswith("task_"):
        normalized = normalized[5:]
    return normalized


def load_verdicts(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = next(v for v in data.values() if isinstance(v, list))
    if len(data) == 0:
        raise ValueError(f"{path} parsed to zero findings")
    return data


def rollup_findings(verdicts: list[dict]) -> list[dict]:
    task_data = defaultdict(
        lambda: {
            "datasets": set(),
            "TRUE_POSITIVE": 0,
            "PARTIAL": 0,
            "UNCERTAIN": 0,
            "FALSE_POSITIVE": 0,
        }
    )

    for verdict in verdicts:
        task_id = normalize_task_id(verdict.get("task_id", ""))
        dataset = verdict.get("dataset", "")
        verdict_type = verdict.get("verdict", "")

        task_data[task_id]["datasets"].add(str(dataset))
        if verdict_type in task_data[task_id]:
            task_data[task_id][verdict_type] += 1

    tasks = []
    for task_id, data in task_data.items():
        confirmed_defect_count = data["TRUE_POSITIVE"] + data["PARTIAL"]
        total_findings = sum(
            data[v] for v in ["TRUE_POSITIVE", "PARTIAL", "UNCERTAIN", "FALSE_POSITIVE"]
        )
        tasks.append(
            {
                "task_id": task_id,
                "datasets": sorted(data["datasets"]),
                "confirmed_defect_count": confirmed_defect_count,
                "true_positive": data["TRUE_POSITIVE"],
                "partial": data["PARTIAL"],
                "uncertain": data["UNCERTAIN"],
                "false_positive": data["FALSE_POSITIVE"],
                "total_findings": total_findings,
            }
        )

    tasks.sort(key=lambda t: (t["confirmed_defect_count"], t["total_findings"]))
    return tasks


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args()

    verdicts = load_verdicts(args.input)
    tasks = rollup_findings(verdicts)

    output_data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": str(args.input.relative_to(REPO_ROOT)),
        "task_count": len(tasks),
        "tasks": tasks,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_data, indent=2), encoding="utf-8")

    clean_tasks = sum(1 for t in tasks if t["confirmed_defect_count"] == 0)
    one_defect = sum(1 for t in tasks if t["confirmed_defect_count"] == 1)
    top_10 = tasks[-10:] if len(tasks) > 10 else []
    top_10.reverse()

    print(f"Wrote {args.output}")
    print(f"  {len(tasks)} tasks in rollup")
    print(f"  {clean_tasks} tasks with confirmed_defect_count == 0 (fully clean)")
    print(f"  {one_defect} tasks with confirmed_defect_count == 1")
    if top_10:
        print(f"  Top 10 tasks by confirmed_defect_count (worst offenders):")
        for task in top_10:
            datasets_str = ", ".join(task["datasets"])
            print(
                f"    {task['task_id']}: {task['confirmed_defect_count']} confirmed "
                f"(TP={task['true_positive']} PARTIAL={task['partial']}), "
                f"total findings={task['total_findings']}, datasets=[{datasets_str}]"
            )


if __name__ == "__main__":
    main()
