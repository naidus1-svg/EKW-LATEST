#!/usr/bin/env python3
"""
golden_citation_scan.py - GATE-V2 class C/D: golden provenance citations that
point at files absent from the corpus.

For each task, extracts from solution/files/* text:
  - filename-shaped tokens (*.xlsx/.docx/.csv/.pdf/.doc/.pptx), and
  - "per <file/source>" provenance phrases (including non-extension
    descriptive references, e.g. "per Jessica's memo").

Each citation is checked for existence:
  - exact filename match anywhere under <task>/environment/ or
    <task>/solution/files/, else
  - fuzzy keyword-overlap match against basenames in those trees
    (catches "Jessica's memo" -> "Jessica_Memo_FY2022.docx").
If neither matches, the citation is MISSING (GATE-V2 class C: e.g. 72-4-0's
four investor updates and annual letter, 24-7-0's Jessica's memo / Priya's
principles / James's mechanism, absent from the environment).

READ-ONLY: only reads corpus files, never modifies them.

Output: CSV [task, cited_name, found_where] where found_where is either the
resolved path (relative to the task dir) or the literal string "MISSING".

Usage:
    python3 golden_citation_scan.py [--corpus-root PATH] [--out PATH] [--task NAME]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import (
    DEFAULT_CORPUS_ROOT,
    DEFAULT_REPORTS_DIR,
    build_file_index,
    extract_document_text,
    extract_filename_tokens,
    extract_provenance_phrases,
    find_exact_filename,
    find_fuzzy_filename,
    list_tasks,
    write_csv,
)


def scan_task(task_dir: Path) -> list[tuple[str, str, str]]:
    """Return (task, cited_name, found_where|MISSING) rows for one task."""
    solution_files_dir = task_dir / "solution" / "files"
    if not solution_files_dir.is_dir():
        return []

    # Build the existence index once: environment/ + solution/files/.
    index = build_file_index(task_dir / "environment") + build_file_index(solution_files_dir)

    citations: set[str] = set()
    for f in sorted(solution_files_dir.rglob("*")):
        if not f.is_file():
            continue
        text = extract_document_text(f)
        if not text:
            continue
        citations |= extract_filename_tokens(text)
        citations |= extract_provenance_phrases(text)

    rows = []
    for name in sorted(citations):
        hit = find_exact_filename(name, index)
        if hit is None:
            hit = find_fuzzy_filename(name, index)
        found_where = str(hit.relative_to(task_dir)) if hit else "MISSING"
        rows.append((task_dir.name, name, found_where))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT, help="corpus root directory")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "golden_citations.csv", help="output CSV path")
    ap.add_argument("--task", type=str, default=None, help="restrict to a single task name (debugging)")
    ap.add_argument("--verdict-out", type=Path, default=None, help="write task_id,golden_citation_scan pass|fail summary CSV")
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple[str, str, str]] = []
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        try:
            all_rows.extend(scan_task(task_dir))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 25 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned", file=sys.stderr)

    n = write_csv(args.out, ["task", "cited_name", "found_where"], all_rows)
    missing = [r for r in all_rows if r[2] == "MISSING"]
    tasks_with_missing = {r[0] for r in missing}

    print(f"golden_citation_scan: {n} citations extracted across {len(tasks)} tasks, written to {args.out}")
    print(f"  {len(missing)} citations MISSING, across {len(tasks_with_missing)} tasks")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = sorted(
            (t.name, "fail" if t.name in tasks_with_missing else "pass") for t in tasks
        )
        vn = write_csv(args.verdict_out, ["task_id", "golden_citation_scan"], verdict_rows)
        print(f"golden_citation_scan: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
