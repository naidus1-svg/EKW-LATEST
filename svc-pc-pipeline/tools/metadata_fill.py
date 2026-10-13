#!/usr/bin/env python3
"""
metadata_fill.py - GATE-V2 class J: task.toml [metadata] fields absent vs
the expected schema.

The converter emits only category and tags into [metadata] (GATE-V2 1,
class J; confirmed by task.toml's own comment: "Only platform-recognized
[metadata] fields emitted (category, tags). benchmark_type /
expert_time_estimate omitted (no fitting enum value / tracker-sourced).").
The expected schema is {category, tags, benchmark_type, expert_time_estimate}.

For each task.toml, reports which of those four fields are present vs
missing, and proposes a fill template for the missing ones (values are
placeholders for a human to complete; this script asserts nothing about
what the right value is).

This script is REPORT-ONLY. It does not edit any task.toml. Corpus-wide
application is Khiem's PR (GATE-V2 3.3, applied to all 202 by script before
the next batch).

READ-ONLY: only reads task.toml, never modifies the corpus.

Output: CSV [task, missing_fields, proposed_fill].

Usage:
    python3 metadata_fill.py [--corpus-root PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_CORPUS_ROOT, DEFAULT_REPORTS_DIR, list_tasks, write_csv

EXPECTED_SCHEMA = ("category", "tags", "benchmark_type", "expert_time_estimate")

PROPOSED_TEMPLATES = {
    "category": 'category = "SVC-PC"',
    "tags": "tags = []",
    "benchmark_type": 'benchmark_type = ""  # TODO: no fitting enum value yet, needs owner input',
    "expert_time_estimate": "expert_time_estimate = 0.0  # TODO: tracker-sourced, needs owner input",
}


def scan_task(task_dir: Path) -> tuple[str, str, str] | None:
    toml_path = task_dir / "task.toml"
    if not toml_path.is_file():
        return (task_dir.name, "|".join(EXPECTED_SCHEMA), "task.toml MISSING ENTIRELY")
    try:
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as exc:
        return (task_dir.name, "PARSE_ERROR", str(exc))

    metadata = data.get("metadata", {})
    missing = [f for f in EXPECTED_SCHEMA if f not in metadata]
    if not missing:
        return None

    proposed = "; ".join(PROPOSED_TEMPLATES[f] for f in missing)
    return (task_dir.name, "|".join(missing), proposed)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT, help="corpus root directory")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "metadata.csv", help="output CSV path")
    ap.add_argument(
        "--verdict-out",
        type=Path,
        default=None,
        help="write task_id,metadata_fill pass summary CSV. Advisory only per Khiem "
        "13:00 UTC class-J correction: benchmark_type/expert_time_estimate/domain/"
        "occupation/sector/subdomain/task_type are non-scoring in all 14 DataOS "
        "verdicts and the SVC-PC template never had them, so this column is always "
        "'pass' and must never drive a gate.",
    )
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if not tasks:
        print(f"ERROR: no SVC-PC-* task directories found under {args.corpus_root}", file=sys.stderr)
        return 1

    rows = []
    for task_dir in tasks:
        result = scan_task(task_dir)
        if result:
            rows.append(result)

    n = write_csv(args.out, ["task", "missing_fields", "proposed_fill"], rows)

    field_counts = {f: 0 for f in EXPECTED_SCHEMA}
    for _, missing_fields, _ in rows:
        for f in missing_fields.split("|"):
            if f in field_counts:
                field_counts[f] += 1

    print(f"metadata_fill: {len(tasks)} tasks scanned, {n} with missing metadata fields, written to {args.out}")
    for f, count in field_counts.items():
        print(f"  missing '{f}': {count} tasks")

    if args.verdict_out:
        # Always 'pass': report-only, non-scoring (Khiem 13:00 UTC class-J
        # correction). Missing [metadata] fields never fail the gate.
        verdict_rows = sorted((t.name, "pass") for t in tasks)
        vn = write_csv(args.verdict_out, ["task_id", "metadata_fill"], verdict_rows)
        print(f"metadata_fill: verdict CSV written, {vn} rows (all 'pass', advisory-only), to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
