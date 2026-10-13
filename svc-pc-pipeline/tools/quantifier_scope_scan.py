#!/usr/bin/env python3
"""
quantifier_scope_scan.py - GATE-V2 class L / map (c): instruction.md
quantifier phrases ("each", "every", "all", "per", "complete", "full",
"current line") whose golden coverage is narrower than what the source
data actually contains (e.g. GATE-V2.md 1b 12-2-0: instruction says "every
SKU", `Pricing_Matrix.xlsx!A5:D20` has 16 SKUs, golden `SRC_Pricing` has 8
rows including an invented one).

For each task:
  1. Extract quantifier phrases from instruction.md (`_qc_common.
     extract_quantifier_phrases`), one row per DISTINCT phrase found (not
     per occurrence -- a task whose instruction says "each" five times
     still gets one "each" row, since the golden/source comparison below
     is task-level, not phrase-specific).
  2. Find the golden's largest enumerated table: `iter_tables()` over
     every file in solution/files/, keep the one with the most rows.
     "Largest" is a deliberate proxy for "the table the quantifier most
     plausibly refers to" -- the corpus's per-SKU / per-line-item tables
     are consistently the largest table in the golden; a task whose
     quantifier refers to a SMALLER table than the largest one will
     under-flag here (false negative, not false positive -- reviewed by
     the CR either way per GATE-V2's "emit candidates" instruction).
  3. Find the SOURCE table it descends from: every xlsx/csv/docx table
     under environment/initial_workspace/, matched to the golden table's
     header by keyword overlap (`best_header_match`, min_overlap=0.4).
  4. gap = source_rows - golden_rows when a source match is found and
     positive; blank when no source table matched closely enough (no
     candidate table shares >=40% of the golden header's keywords) or the
     golden has no table at all.

HEURISTIC NOTES (read before trusting a row)
----------------------------------------------
- "per" fires on rate phrases ("$5 per unit", "3 per week") as well as
  provenance phrases; occurrences where the word immediately after "per"
  is a known rate/unit noun (`_qc_common._RATE_UNIT_WORDS` -- week, day,
  unit, order, SKU-as-a-unit-of-measure, etc.) are dropped before the
  phrase set is built, matching golden_citation_scan.py's provenance
  filter. This does not catch every rate phrasing; residual "per" rows
  are still just candidates.
- Table extraction is single-table-per-sheet/file (see `iter_tables`
  docstring in _qc_common.py): a sheet with two side-by-side tables, or a
  2-row merged header, is misread. A formula cell with no cached value
  (class K) reads as empty and can undercount a golden table's row_count
  -- cross-check a suspiciously low golden_rows count against
  formula_cache.csv for the same file before treating a gap as real.
- Source-table matching only considers xlsx/csv/docx under
  initial_workspace/ (pdf/pptx/doc/json are not structured tables this
  heuristic can count rows in -- see iter_tables). A quantifier whose
  real source is a PDF or scanned table will show source_table=NO_MATCH,
  gap blank, and needs manual review, not a clean bill of health.
- A source_rows count itself can be an OVER-count relative to what the
  instruction's quantifier actually requires (GATE-V2 1b 22-5-0: source
  has COGS for only 16 of 90 catalog SKUs, so grading "every SKU" against
  90 rows would be a 1.1 solvability problem, not a golden gap) -- the CR
  reads gap alongside the instruction text, this script does not attempt
  that judgment.

READ-ONLY on the corpus: only ever reads files, never writes into a task
directory.

Output: CSV reports/quantifier_scope.csv
  [task, phrase, golden_table, golden_rows, source_table, source_rows, gap]

Usage:
    python3 quantifier_scope_scan.py [--corpus-root PATH] [--out PATH] [--task NAME]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
    DEFAULT_REPORTS_DIR,
    _RATE_UNIT_WORDS,
    best_header_match,
    extract_quantifier_phrases,
    iter_tables,
    list_tasks,
    read_text_safe,
    write_csv,
)

_TABLE_EXT = {"xlsx", "csv", "docx"}
_PER_UNIT_RE = re.compile(r"\bper\s+([a-zA-Z]+)", re.IGNORECASE)


def _filter_phrases(text: str) -> set[str]:
    phrases: set[str] = set()
    for phrase, sentence in extract_quantifier_phrases(text):
        if phrase == "per":
            m = _PER_UNIT_RE.search(sentence)
            if m and m.group(1).lower().rstrip("s") in _RATE_UNIT_WORDS:
                continue
        phrases.add(phrase)
    return phrases


def _tables_under(root: Path) -> list:
    tables = []
    if not root.is_dir():
        return tables
    for f in sorted(root.rglob("*")):
        if f.is_file() and f.suffix.lower().lstrip(".") in _TABLE_EXT:
            tables.extend(iter_tables(f))
    return tables


def scan_task(task_dir: Path) -> list[tuple]:
    instr_text = read_text_safe(task_dir / "instruction.md")
    if not instr_text.strip():
        return []
    phrases = _filter_phrases(instr_text)
    if not phrases:
        return []

    golden_tables = _tables_under(task_dir / "solution" / "files")
    golden_table = max(golden_tables, key=lambda t: t.row_count, default=None)

    source_match = None
    if golden_table is not None:
        source_tables = _tables_under(task_dir / "environment" / "initial_workspace")
        source_match = best_header_match(golden_table.header, source_tables)

    golden_label = golden_table.source_label if golden_table else "NONE"
    golden_rows = golden_table.row_count if golden_table else 0
    source_label = source_match.source_label if source_match else "NO_MATCH"
    source_rows = source_match.row_count if source_match else None
    gap = (source_rows - golden_rows) if source_rows is not None else ""

    return [
        (task_dir.name, phrase, golden_label, golden_rows, source_label, source_rows if source_rows is not None else "", gap)
        for phrase in sorted(phrases)
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT, help="corpus root directory")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "quantifier_scope.csv", help="output CSV path")
    ap.add_argument("--task", type=str, default=None, help="restrict to a single task name (debugging)")
    ap.add_argument("--verdict-out", type=Path, default=None, help="write task_id,quantifier_scope_scan pass|warn summary CSV")
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple] = []
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        try:
            all_rows.extend(scan_task(task_dir))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 10 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned", file=sys.stderr)

    n = write_csv(
        args.out,
        ["task", "phrase", "golden_table", "golden_rows", "source_table", "source_rows", "gap"],
        all_rows,
    )
    gaps = [r for r in all_rows if isinstance(r[6], int) and r[6] > 0]
    tasks_with_gaps = {r[0] for r in gaps}
    no_match = [r for r in all_rows if r[4] == "NO_MATCH"]

    print(f"quantifier_scope_scan: {n} quantifier-phrase rows across {len(tasks)} tasks, written to {args.out}")
    print(f"  {len(gaps)} rows show a positive gap (source_rows > golden_rows), across {len(tasks_with_gaps)} tasks")
    print(f"  {len(no_match)} rows had no source table match (NO_MATCH) -- needs manual review, not a clean result")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = sorted(
            (t.name, "warn" if t.name in tasks_with_gaps else "pass") for t in tasks
        )
        vn = write_csv(args.verdict_out, ["task_id", "quantifier_scope_scan"], verdict_rows)
        print(f"quantifier_scope_scan: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
