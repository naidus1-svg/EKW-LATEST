#!/usr/bin/env python3
"""Duplicate criterion-ID detector: flags any two rows in a rubric whose criterion ID
collides after normalization, so a human can look at both full rows side by side and
decide whether it's a real duplicate, an ID typo, or something intentional.

Copied into turing-context on 2026-09-14 from harbor-qc-checks/duplicate_criterion_check.py.
See tools/svc_qc_tracker_build.py CHECK_META["D"]["subchecks"]["D4"]. No logic changed. Note
this check reads SOURCE rubric .xlsx workbooks (00_fetched/<ID>/Rubric/*.xlsx in this repo's
build tree), not the built judge.toml package under 03_dataos_ready - see --root guidance below.

Why this exists, and why a weight-sum check does not cover it. A rubric-to-verifier
converter that builds a dict keyed by criterion id -- `weight_by_id = {row["criterion_id"]:
w for row in rows}` is the shape seen in the source pipeline -- silently collapses any two
rows that share an id. Only the LAST row's weight survives; the other row's weight is gone
and nobody raised an exception. If the pipeline then re-normalizes so all surviving weights
sum to 1.0, that check passes cleanly: 1.0 is still 1.0, it is just missing a criterion's
worth of grading and carrying someone else's weight instead. The failure only becomes loud
when the two dropped/duplicated weights happen NOT to cancel out (seen on one real task,
where they didn't, and it hard-failed a weight-sum check) -- which means for every task
where they DO happen to cancel, a weight-sum-to-1.0 check is not evidence of a healthy
rubric. It is exactly the kind of arithmetic coincidence a second, independent check has to
exist to catch. This script is that second check: it looks at criterion ids directly,
never at weights, so a cancelling pair cannot hide from it the way it hides from a sum.

Provenance: generalized from tools/svc_fix_duplicate_criterion_ids.py in the turing-context
repo (a QC pipeline built for the SVC-PC / Cirrus Sleep benchmark). That script is a FIXER,
not a checker: confirmed by reading its full source directly, it opens a rubric workbook with
openpyxl (`import openpyxl`, `openpyxl.load_workbook(...)`) and nothing else -- there is no
`tomllib`/`toml` import and no other format ever touched. It is xlsx-only. It can safely
auto-repair exactly one specific defect shape (a decimal-looking id like "1.10" that Excel's
own number formatting silently dropped the trailing zero from, leaving it stored as "1.1"),
and only when both neighbouring rows agree on the surrounding numbering (previous row is
"<n>.9", next row is "<n>.11", so the middle row is unambiguously "<n>.10"). Any collision
that doesn't fit that exact shape makes the source script print "position does not determine
the intended id; not guessing" and bail with a non-zero exit -- it deliberately never guesses
at an unrepaired collision beyond that one case.

This copy is REPORT-ONLY. There is no --apply flag and no repair path of any kind: it never
writes to the rubric file it reads. It generalizes the source in two ways. First, input
handling: --root takes either one rubric file or a directory to search, not one hardcoded
path passed as a positional argument. Second, and more importantly, detection scope: it
surfaces EVERY id collision under the same normalization the source uses (`str(value).strip()`,
case-sensitive, read from column A), not only the one trailing-zero-loss shape the source
knew how to safely auto-fix. A collision from a straight copy-paste mistake, a renumbering
that skipped updating one row, or two unrelated criteria that both ended up labeled the same
thing would all have hit the source's "not guessing" bailout and gone unrepaired without
necessarily being surfaced to a person; this script's whole job is to put every such
collision, fixable by pattern-matching or not, in front of a human with enough context (both
full rows, every column) to make the call.

A note on a format this script deliberately does NOT cover: `tests/deliverables_*/judge.toml`
files (the verifier config the rubric eventually becomes) use `[[criterion]] name = "..."`,
not an "id" field, confirmed by reading a real one directly. A duplicate `name` there is a
different defect against a different data shape and is not this script's concern -- it
would need its own check against the toml criterion list, not against an xlsx rubric sheet.

Status: v1, report-only. No known false negatives against the defect class it targets (an
exact, post-strip string collision in column A of a header-sniffed criteria sheet). The one
way a real collision could be missed is if a rubric ever puts its criterion ids in a column
other than A -- see Known limits below, this is inherited unchanged from the source script.

Usage:
    python duplicate_criterion_check.py --root <rubric.xlsx>
    python duplicate_criterion_check.py --root <path/to/rubric/directory>
    python duplicate_criterion_check.py --root <path> --glob "**/*rubric*.xlsx" --out report.json

What it does, in order:

1. Resolves --root to a list of rubric files: the path itself if it is a file, or every file
   under it matching --glob (default "*.xlsx", the same extension the source script handles;
   pass e.g. --glob "*.xlsm" to widen it) if it is a directory. Excel lock files (the
   "~$..." temp files Excel creates while a workbook is open) are always skipped.
2. For each file, finds every worksheet whose header row (row 1) has a column starting with
   "criterion" (case-insensitive) -- the same header sniff `criteria_sheet()` uses in the
   source. Difference from the source: the source picks exactly ONE such sheet (the first
   match, or the workbook's last sheet if nothing matches) and stops there, because it is
   only ever fixing one sheet at a time. This script checks EVERY matching sheet in the
   workbook, since nothing about the defect is sheet-scoped and a rubric workbook that
   splits criteria across more than one tab (e.g. one per deliverable group) deserves the
   same check on all of them. If no sheet's header matches, it falls back to the workbook's
   last sheet, exactly like the source, and marks that sheet's "header_confirmed" as false in
   the report so a reader knows the sheet identification is a guess, not a confirmed read.
3. Within each such sheet, reads column A from row 2 down (same as the source: the id is
   always assumed to live in column A -- see Known limits), skipping blank cells, and
   normalizes every value with `str(value).strip()` -- the exact same normalization the
   source's own duplicate detection uses (`collections.Counter(ids.values())` over
   `str(v).strip()` values). Two rows whose normalized id is equal are a collision,
   regardless of whether their RAW values are byte-identical (a numeric 1.1 and a text "1.1"
   normalize the same way here, matching the source).
4. For every collision, records the full row (every column in that row, keyed by that
   column's own header text) for EACH colliding occurrence, not just the id. A human reading
   the report sees, side by side, both rows' Category/Tier/Description/Expected value/etc
   (or whatever columns this particular rubric actually has -- column layout is read from
   the header row, never assumed) and can judge whether this is the same criterion duplicated,
   a genuine typo, or two different criteria that were mistakenly given the same label.
5. Writes one JSON result per file (status: pass|fail, every sheet checked, every collision
   found) plus an aggregate report across every file discovered under --root, and exits 1 if
   any file has at least one collision (0 if none do), so this can gate a build the same way
   the source script's own exit code does.

Known limits, disclosed rather than silently dropped:
    - Assumes the criterion id lives in column A, exactly like the source script -- the
      header sniff only decides which SHEET counts as a criteria table, it does not search
      for which COLUMN holds the id. A rubric that puts ids anywhere else needs this script
      changed (or its column reworked), same limit the source fixer already carried.
    - Normalization is exactly `str(value).strip()`, case-sensitive: "A1" and "a1" are NOT
      treated as a collision here, because they were not treated as one in the source's own
      detection either. If your conversion pipeline's dict key is case-insensitive, this
      check would under-report relative to that pipeline; it has not been asked to guess
      about a normalization step it was never shown.
    - Each matching sheet is checked independently, mirroring the source's per-sheet
      dict-by-id build. If your rubric-to-verifier conversion merges criteria from more than
      one sheet in the SAME workbook into one shared id-keyed dict, a collision across two
      different sheets would also collapse downstream and this script would not catch it --
      it only ever compares ids within a single sheet. Confirm your own pipeline's merge
      scope before treating a "pass" across multiple sheets as proof there is no cross-sheet
      collision.
    - A collision being reported is not itself proof of a defect -- see the whole point of
      this being report-only rather than a fixer: it might be intentional in some rubric this
      script has not seen yet. It is reported, with full context, for a human to judge, never
      auto-resolved either way.
    - This only reads the CURRENT on-disk state of whatever --root points at. It says nothing
      about whether a rubric was fixed by other work after this check last ran.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import openpyxl
except ImportError:  # pragma: no cover
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl

RUBRIC_LOCK_PREFIX = "~$"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def to_jsonable(v):
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def find_rubric_files(root: Path, pattern: str) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.rglob(pattern)
        if p.is_file() and not p.name.startswith(RUBRIC_LOCK_PREFIX)
    )


def sheet_header_confirmed(ws) -> bool:
    """Same header sniff as the source fixer's `criteria_sheet()`: does row 1 have any
    column whose text starts with "criterion" (case-insensitive)?"""
    hdr = [str(c.value).strip().lower() if c.value else "" for c in ws[1]]
    return any(h.startswith("criterion") for h in hdr)


def find_criteria_sheets(wb):
    """Every worksheet that looks like a criteria table, generalized from the source's
    single-sheet `criteria_sheet()` to check ALL matches instead of stopping at the first.
    Falls back to the workbook's last sheet (same fallback the source uses) only when NO
    sheet's header matches anything."""
    matches = [ws for ws in wb.worksheets if sheet_header_confirmed(ws)]
    if matches:
        return matches
    return [wb.worksheets[-1]] if wb.worksheets else []


def row_cells(ws, row: int) -> dict:
    """Every column of one row, keyed by that column's own header text (falling back to a
    column-letter label when the header cell is blank), so the report shows a colliding
    row's full content regardless of a specific rubric's column layout."""
    out = {}
    for col in range(1, ws.max_column + 1):
        h = ws.cell(row=1, column=col).value
        key = (
            str(h).strip()
            if h not in (None, "")
            else f"col_{openpyxl.utils.get_column_letter(col)}"
        )
        out[key] = to_jsonable(ws.cell(row=row, column=col).value)
    return out


# ---------------------------------------------------------------------------
# per-file check
# ---------------------------------------------------------------------------


def check_file(path: Path) -> dict:
    """Returns one result dict for one rubric file. Never raises -- a load failure on the
    whole file is reported as a single load_error, not a crash that would kill the batch.
    """
    result = {
        "file": str(path),
        "load_error": None,
        "sheets_checked": [],
        "collisions": [],
    }

    try:
        wb = openpyxl.load_workbook(path, data_only=False)
    except Exception as e:
        result["load_error"] = f"openpyxl could not open this file: {e}"
        result["status"] = "fail"
        return result

    for ws in find_criteria_sheets(wb):
        header_confirmed = sheet_header_confirmed(ws)
        by_norm_id = collections.defaultdict(list)
        for r in range(2, ws.max_row + 1):
            v = ws.cell(row=r, column=1).value
            if v is None or str(v).strip() == "":
                continue
            norm = str(v).strip()
            by_norm_id[norm].append(
                {
                    "row": r,
                    "raw_id": to_jsonable(v),
                    "cells": row_cells(ws, r),
                }
            )

        result["sheets_checked"].append(
            {
                "sheet": ws.title,
                "header_confirmed": header_confirmed,
                "n_ids": sum(len(occ) for occ in by_norm_id.values()),
            }
        )

        for norm, occurrences in by_norm_id.items():
            if len(occurrences) > 1:
                result["collisions"].append(
                    {
                        "sheet": ws.title,
                        "normalized_id": norm,
                        "occurrences": occurrences,
                    }
                )

    result["status"] = "fail" if result["collisions"] else "pass"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Report-only detector for duplicate criterion ids in a rubric workbook. "
            "Detects any two rows whose id collides after str(value).strip() normalization "
            "(the same normalization the source fixer uses) and prints both full rows so a "
            "human can judge whether it's a real duplicate or an id typo. Never writes to "
            "the file it reads -- there is no --apply/fix mode."
        )
    )
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help=(
            "a single rubric .xlsx file, or a directory to search recursively for rubric "
            "files (REQUIRED -- no default, this must never silently assume a "
            "project-specific path)"
        ),
    )
    ap.add_argument(
        "--glob",
        default="*.xlsx",
        help=(
            "glob pattern used to find rubric files when --root is a directory "
            "(default: *.xlsx, matching the source fixer's own file scope; pass e.g. "
            "--glob '*.xlsm' or --glob '**/*rubric*.xlsx' to widen or narrow the search)"
        ),
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

    root: Path = args.root
    if not root.exists():
        print(f"--root does not exist: {root}", file=sys.stderr)
        return 1

    files = find_rubric_files(root, args.glob)
    if not files:
        print(
            f"No rubric files found under {root} (glob={args.glob!r}).",
            file=sys.stderr,
        )
        return 1

    results = []
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path} ...", file=sys.stderr)
        try:
            r = check_file(path)
        except Exception as e:  # never let one file's crash kill the whole batch
            r = {
                "file": str(path),
                "status": "fail",
                "load_error": f"unhandled exception checking this file: {e}",
                "sheets_checked": [],
                "collisions": [],
            }
        results.append(r)
        print(
            f"    -> {r['status']}  ({len(r['collisions'])} colliding id group(s))",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(root),
        "glob": args.glob,
        "n_files": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "results": results,
    }

    print(f"\n{n_pass} pass / {n_fail} fail out of {len(results)} rubric file(s)")
    for r in results:
        tag = (
            f"  [{len(r['collisions'])} colliding id group(s)]"
            if r["collisions"]
            else ""
        )
        print(f"  {r['file']}: {r['status']}{tag}")
        if r.get("load_error"):
            print(f"      ! {r['load_error']}")
        for c in r["collisions"]:
            where = ", ".join(
                f"row {o['row']} = {o['raw_id']!r}" for o in c["occurrences"]
            )
            print(
                f"      sheet {c['sheet']!r}: id {c['normalized_id']!r} collides -- {where}"
            )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
