#!/usr/bin/env python3
"""Restore cached formula values in goldens that an openpyxl round-trip stripped.

openpyxl does not evaluate formulas. When it saves a workbook it writes the formula
and drops the cached result Excel had stored alongside it. Anything that reads VALUES
rather than formulas then sees nothing: the rewardkit judge extracts text, so every
computed figure in the document silently disappears and any criterion checking one
scores "no".

Measured on SVC-PC-1-3-0: the pre-edit Drive revision had 347 of 347 formula cells
carrying a cached value; after the edit, 0 of 347.

Excel is the only engine on this machine that can recalculate (LibreOffice is not
installed). It opens the file, recalculates in full, and saves, which restores the
cached values without altering a single formula.

Usage:
    python tools/svc_recalc_goldens.py --check
    python tools/svc_recalc_goldens.py
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import openpyxl

STAGE = Path("C:/b/_fetched_all32")
BACKUP = Path("C:/b/_recalc_backups")


def formula_cache_state(p: Path) -> tuple[int, int]:
    """(formula cells, how many carry a cached value)."""
    F = openpyxl.load_workbook(p, data_only=False)
    V = openpyxl.load_workbook(p, data_only=True)
    total = live = 0
    for sn in F.sheetnames:
        vs = V[sn]
        for row in F[sn].iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    total += 1
                    if vs[c.coordinate].value is not None:
                        live += 1
    return total, live


def recalc(p: Path) -> None:
    """Open in Excel, force a full recalculate, save. Formulas are never touched."""
    import win32com.client as win32

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wbk = excel.Workbooks.Open(str(p.resolve()))
        excel.CalculateFullRebuild()
        wbk.Save()
        wbk.Close(SaveChanges=True)
    finally:
        excel.Quit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        help="limit to these task ids (repeatable). Without it, every damaged "
        "golden is listed but only ones we actually edited should be "
        "repaired: a golden we never touched arrived from Drive already "
        "missing its cached values, and recalculating it is a change "
        "nobody asked for.",
    )
    args = ap.parse_args()

    targets = []
    for p in sorted(STAGE.glob("SVC-PC-*/Golden Solution/*.xls*")):
        if p.name.startswith("~$"):
            continue
        task = p.parent.parent.name
        if args.task and task not in args.task:
            continue
        total, live = formula_cache_state(p)
        if total and live == 0:
            targets.append((p, total))

    if not targets:
        print("no golden has lost its cached formula values")
        return 0

    print(f"{len(targets)} golden(s) with formulas but zero cached values:")
    for p, total in targets:
        print(f"  {p.parent.parent.name:<16} {total:>4} formula cells  {p.name}")

    if args.check:
        print("\n--check, nothing changed")
        return 1

    BACKUP.mkdir(parents=True, exist_ok=True)
    failures = []
    for p, total in targets:
        task = p.parent.parent.name
        shutil.copy2(p, BACKUP / f"{task}__{p.name}")
        try:
            recalc(p)
        except Exception as exc:
            failures.append((task, f"recalc failed: {exc}"))
            print(f"FAIL {task}: {exc}")
            continue
        total2, live2 = formula_cache_state(p)
        ok = live2 == total2 and total2 > 0
        print(
            f"{'OK  ' if ok else 'FAIL'} {task:<16} {live2}/{total2} formula cells now cached"
        )
        if not ok:
            failures.append((task, f"only {live2}/{total2} restored"))

    print(f"\nbackups of the pre-recalc state in {BACKUP}")
    if failures:
        print("FAILURES:")
        for t, why in failures:
            print(f"  {t}: {why}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
