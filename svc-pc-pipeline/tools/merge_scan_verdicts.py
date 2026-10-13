#!/usr/bin/env python3
"""
merge_scan_verdicts.py - GATE-V2 3.4: "every Z scan once it reports into
summary.csv".

Reads every reports/*.verdict.csv (each written by one Z scan's
`--verdict-out`, header `task_id,<scan_stem>`, values pass|warn|fail) and
merges them into one wide table keyed by task_id.

Two modes:

  1. Standalone (default): union of task_id across all verdict CSVs as the
     rows, one column per scan stem, written to reports/scan_summary.csv
     (or --out). A cell is blank if that scan has no row for that task_id
     (e.g. the scan was run with --task and only covers a subset).

  2. `--into <existing summary.csv>`: LEFT-JOIN the scan columns onto an
     existing svc_run_checks summary.csv (task_id-keyed, one column per
     45-check + its _n/_first companions), so main's stage_and_zip actuator
     sees the Z-scan columns alongside the 45-check columns. Rows are
     exactly the existing summary.csv's rows (task_ids not present there
     are dropped, per LEFT JOIN semantics); a task_id present in --into but
     missing from a verdict CSV gets a blank cell for that scan.

Never overwrites the --into input. Writes to --out if given (must differ
from --into), otherwise prints the merged CSV to stdout.

READ-ONLY: only reads reports/*.verdict.csv and (with --into) the existing
summary.csv; never modifies either.

Usage:
    python3 merge_scan_verdicts.py [--reports-dir DIR] [--out PATH]
    python3 merge_scan_verdicts.py --into /path/to/summary.csv [--out PATH]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_REPORTS_DIR


def load_verdict_csvs(reports_dir: Path) -> dict[str, dict[str, str]]:
    """Return {scan_stem: {task_id: verdict}} for every reports/*.verdict.csv."""
    scans: dict[str, dict[str, str]] = {}
    for path in sorted(reports_dir.glob("*.verdict.csv")):
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                continue
            if len(header) < 2:
                print(f"WARNING: {path} has no scan column, skipped", file=sys.stderr)
                continue
            scan_name = header[1]
            rows: dict[str, str] = {}
            for row in reader:
                if len(row) < 2:
                    continue
                task_id, verdict = row[0], row[1]
                rows[task_id] = verdict
            if scan_name in scans:
                print(f"WARNING: duplicate scan column name '{scan_name}' (from {path}), overwriting", file=sys.stderr)
            scans[scan_name] = rows
    return scans


def write_standalone(scans: dict[str, dict[str, str]], out_path: Path) -> tuple[int, int]:
    scan_names = sorted(scans.keys())
    all_tasks = sorted({t for rows in scans.values() for t in rows})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["task_id"] + scan_names)
        for task_id in all_tasks:
            w.writerow([task_id] + [scans[name].get(task_id, "") for name in scan_names])

    return len(all_tasks), len(scan_names)


def write_joined(scans: dict[str, dict[str, str]], into_path: Path, out_path: Path | None) -> tuple[int, int]:
    scan_names = sorted(scans.keys())

    with into_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        base_header = next(reader)
        base_rows = list(reader)

    if "task_id" not in base_header:
        print(f"ERROR: {into_path} has no task_id column, cannot left-join", file=sys.stderr)
        raise SystemExit(1)
    task_id_idx = base_header.index("task_id")

    new_header = base_header + scan_names
    new_rows = []
    for row in base_rows:
        task_id = row[task_id_idx] if task_id_idx < len(row) else ""
        joined = list(row) + [scans[name].get(task_id, "") for name in scan_names]
        new_rows.append(joined)

    out = sys.stdout if out_path is None else out_path.open("w", newline="", encoding="utf-8")
    close_after = out_path is not None
    try:
        w = csv.writer(out)
        w.writerow(new_header)
        w.writerows(new_rows)
    finally:
        if close_after:
            out.close()

    return len(new_rows), len(scan_names)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR, help="directory holding *.verdict.csv files")
    ap.add_argument("--out", type=Path, default=None, help="output CSV path (default: reports-dir/scan_summary.csv in standalone mode; stdout in --into mode)")
    ap.add_argument("--into", type=Path, default=None, help="left-join scan columns onto this existing task_id-keyed summary.csv instead of writing standalone")
    args = ap.parse_args()

    scans = load_verdict_csvs(args.reports_dir)
    if not scans:
        print(f"ERROR: no *.verdict.csv files found under {args.reports_dir}", file=sys.stderr)
        return 1

    if args.into:
        if not args.into.is_file():
            print(f"ERROR: --into path {args.into} does not exist", file=sys.stderr)
            return 1
        out_path = args.out
        if out_path is not None and out_path.resolve() == args.into.resolve():
            print("ERROR: --out must not be the same path as --into (refusing to overwrite the input)", file=sys.stderr)
            return 1
        n_rows, n_cols = write_joined(scans, args.into, out_path)
        dest = str(out_path) if out_path else "stdout"
        print(f"merge_scan_verdicts: left-joined {n_cols} scan columns onto {n_rows} rows from {args.into}, written to {dest}", file=sys.stderr)
    else:
        out_path = args.out or (args.reports_dir / "scan_summary.csv")
        n_rows, n_cols = write_standalone(scans, out_path)
        print(f"merge_scan_verdicts: {n_rows} tasks (rows) x {n_cols} scans (columns), written to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
