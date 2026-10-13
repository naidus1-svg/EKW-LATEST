#!/usr/bin/env python3
"""Bring oversized golden databooks under rewardkit's 1MB judge attachment cap.

The problem, measured rather than assumed: rewardkit skips any judge attachment over
1,048,576 bytes, SILENTLY, and every criterion checking that file then scores "no".
SVC-PC-4-3-0's databook is 1,309,162 bytes and SVC-PC-4-5-0's is 1,170,446. Both are
over. The warning that should surface this exists in to_rewardkit.py but its stderr
never reaches the operator, so the degradation is invisible.

98 to 99 percent of each file is one pasted raw sheet, SRC_SalesOrders, 12,168 rows by
26 columns. That sheet cannot be dropped: formulas reference it 131 times in 4-3-0. But
only 6 of its 26 columns are referenced in 4-3-0, and only 4 of 26 in 4-5-0. The rest are
dead weight, and two of the dead columns are `Customer name` and `Email`, so trimming
also removes 12,168 rows of PII from a customer deliverable.

Order of operations matters. openpyxl cannot evaluate formulas, so saving through it
strips every cached value and the judge, which reads values, sees blanks. So after the
trim the workbook is recalculated in Excel, which restores the caches without touching a
single formula. Skipping that step is how four goldens reached Drive blank earlier in
this same cycle.

    python tools/svc_trim_oversized_databooks.py --check
    python tools/svc_trim_oversized_databooks.py
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter

CAP = 1024 * 1024
STAGE = Path("C:/b/_fetched_all32")
BACKUP = Path("C:/b/_trim_backups")

TARGETS = [
    ("SVC-PC-4-3-0", "Launches_Promo_Databook.xlsx", "SRC_SalesOrders"),
    ("SVC-PC-4-5-0", "Branding_CircuitCool_Databook.xlsx", "SRC_SalesOrders"),
]


def referenced_columns(wb, sheet: str) -> set[str]:
    """Every column of `sheet` any formula touches, via A1 refs or ranges."""
    cols: set[str] = set()
    esc = re.escape(sheet)
    single = re.compile(rf"'?{esc}'?!\$?([A-Z]{{1,2}})\$?\d*", re.I)
    span = re.compile(rf"'?{esc}'?!\$?([A-Z]{{1,2}})\$?\d*:\$?([A-Z]{{1,2}})", re.I)
    for sn in wb.sheetnames:
        for row in wb[sn].iter_rows():
            for c in row:
                v = c.value
                if not (isinstance(v, str) and v.startswith("=") and sheet in v):
                    continue
                for m in span.finditer(v):
                    for i in range(
                        column_index_from_string(m.group(1).upper()),
                        column_index_from_string(m.group(2).upper()) + 1,
                    ):
                        cols.add(get_column_letter(i))
                for m in single.finditer(v):
                    cols.add(m.group(1).upper())
    return cols


def cache_state(p: Path) -> tuple[int, int]:
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
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    BACKUP.mkdir(parents=True, exist_ok=True)
    rc = 0
    for task, fname, srcsheet in TARGETS:
        p = STAGE / task / "Golden Solution" / fname
        if not p.exists():
            print(f"FAIL {task}: {p} missing")
            rc = 1
            continue

        before = p.stat().st_size
        wb = openpyxl.load_workbook(p, data_only=False)
        used = referenced_columns(wb, srcsheet)
        ws = wb[srcsheet]
        have = {get_column_letter(i) for i in range(1, ws.max_column + 1)}
        drop = sorted(have - used, key=column_index_from_string)
        hdr = {
            get_column_letter(i): ws.cell(row=2, column=i).value
            for i in range(1, ws.max_column + 1)
        }
        dropped_names = [hdr.get(c) for c in drop if hdr.get(c)]

        print(f"=== {task}  {before:,} bytes, cap {CAP:,}")
        print(f"    {srcsheet}: {ws.max_row:,} rows x {ws.max_column} cols")
        print(f"    referenced, keeping: {sorted(used, key=column_index_from_string)}")
        print(f"    dropping {len(drop)} unreferenced: {dropped_names}")

        if args.check:
            print("    --check, nothing changed\n")
            continue

        shutil.copy2(p, BACKUP / f"{task}__{fname}")
        for col in sorted(drop, key=column_index_from_string, reverse=True):
            ws.delete_cols(column_index_from_string(col))
        wb.save(p)
        mid = p.stat().st_size

        recalc(p)
        after = p.stat().st_size
        total, live = cache_state(p)
        under = after < CAP
        ok = under and total > 0 and live == total
        print(
            f"    trimmed {before:,} -> {mid:,}, after recalc {after:,} "
            f"({'UNDER' if under else 'STILL OVER'} cap)"
        )
        print(f"    formula cells {live}/{total} cached")
        print(f"    {'OK' if ok else 'FAIL'}\n")
        if not ok:
            rc = 1

    if not args.check:
        print(f"backups of the pre-trim originals in {BACKUP}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
