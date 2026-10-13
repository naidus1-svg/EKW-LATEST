#!/usr/bin/env python3
"""Repair criterion ids that lost a trailing zero, e.g. 1.10 stored as 1.1.

Why this matters beyond tidiness. `normalize_weights` in rubric_xlsx_to_verifier.py
builds `weight_by_id = {r["criterion_id"]: w}`, a dict keyed by criterion id. Two rows
sharing an id collapse: both then receive the LAST row's weight, and the two real weights
are lost. On SVC-PC-3-6-0 that produced a normalized weight sum of 0.9776 and a hard
ConversionError, so the package would not build at all.

Worse than the build failure: when the per-pair gains and losses happen to cancel, the
total still lands on 1.0 and the task builds clean while individual criteria carry the
wrong weight. Nothing warns. SVC-PC-3-6-0 only surfaced because its residuals did not
cancel.

The id is unambiguous from position: the row sits between 1.9 and 1.11, so it is 1.10.
This repairs the data. The converter's dict-keyed-by-id remains a latent trap for any
other rubric with duplicate ids, and that is a pipeline fix somebody should make
separately.

    python tools/svc_fix_duplicate_criterion_ids.py <rubric.xlsx> [--apply]
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

import openpyxl


def criteria_sheet(wb):
    for ws in wb.worksheets:
        hdr = [str(c.value).strip().lower() if c.value else "" for c in ws[1]]
        if any(h.startswith("criterion") for h in hdr):
            return ws
    return wb[wb.sheetnames[-1]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rubric")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    p = Path(args.rubric)
    wb = openpyxl.load_workbook(p, data_only=False)
    ws = criteria_sheet(wb)

    ids = {}
    for r in range(2, ws.max_row + 1):
        v = ws.cell(row=r, column=1).value
        if v is None or str(v).strip() == "":
            continue
        ids[r] = str(v).strip()

    dupes = {k for k, n in collections.Counter(ids.values()).items() if n > 1}
    if not dupes:
        print(f"{p.name}: no duplicate criterion ids")
        return 0

    print(f"{p.name}: duplicate ids {sorted(dupes)}")
    fixes = []
    for row, cid in ids.items():
        if cid not in dupes:
            continue
        prev = ids.get(row - 1, "")
        nxt = ids.get(row + 1, "")
        m_prev = re.fullmatch(r"(\d+)\.(\d+)", prev or "")
        m_next = re.fullmatch(r"(\d+)\.(\d+)", nxt or "")
        # The trailing-zero case: previous is <major>.9 and next is <major>.11, so this
        # row is <major>.10. Only claim the fix when BOTH neighbours agree.
        if (
            m_prev
            and m_next
            and m_prev.group(1) == m_next.group(1)
            and m_prev.group(2) == "9"
            and m_next.group(2) == "11"
        ):
            fixes.append((row, cid, f"{m_prev.group(1)}.10"))

    if not fixes:
        print("  position does not determine the intended id; not guessing")
        return 1

    for row, old, new in fixes:
        print(
            f"  row {row}: {old!r} -> {new!r}   (between {ids.get(row-1)!r} and {ids.get(row+1)!r})"
        )

    if not args.apply:
        print("  dry run, pass --apply to write")
        return 1

    for row, _old, new in fixes:
        ws.cell(row=row, column=1).value = new
    wb.save(p)

    ws2 = criteria_sheet(openpyxl.load_workbook(p, data_only=False))
    after = [
        str(ws2.cell(row=r, column=1).value).strip()
        for r in range(2, ws2.max_row + 1)
        if ws2.cell(row=r, column=1).value not in (None, "")
    ]
    still = {k for k, n in collections.Counter(after).items() if n > 1}
    print(f"  readback: {len(after)} ids, duplicates now {sorted(still) or 'none'}")
    return 0 if not still else 1


if __name__ == "__main__":
    raise SystemExit(main())
