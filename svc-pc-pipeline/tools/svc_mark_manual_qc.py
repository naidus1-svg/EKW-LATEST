#!/usr/bin/env python3
"""svc_mark_manual_qc.py - surgically set the Status column to "submit for manual QC"
for a fixed list of tasks on the live SVC QC Tracker, without a whole-file replace.

The tracker (1JmpP38...) is edited by 30-60 people at once, so a drive.py-put whole-file
round-trip can clobber a concurrent editor. This does a Sheets API v4 values:batchUpdate on
only the specific Status cells, after snapshotting their current values and reading them back.

Column discovery is by header text (Task ID column, Status column), not a hardcoded letter,
so a reordered sheet does not write the wrong column. Task ids match on the numeric suffix
(SVC-PC-11-4-0 == 11-4-0). Reads fetch only the two needed columns, not the whole wide grid.

Needs a gcloud token WITH Drive scope:
    gcloud.cmd auth login --enable-gdrive-access
Verify first: python C:/Users/khiem.doan_turing/.claude/drive.py check

Usage:
    python tools/svc_mark_manual_qc.py            # dry run: shows exactly what it would change
    python tools/svc_mark_manual_qc.py --apply    # writes, then reads back to confirm
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SHEET = "1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4"
# The live tab since the 2026-09-21 reassignment. "SVC QC Tracker A" was renamed "SVC QC Tracker A(see combined"
# and a request for the old name 400s. Override with --tab if the sheet is restructured again.
TAB = "SVC QC Tracker Combined"
STATUS_VALUE = "submit for manual QC"
API = "https://sheets.googleapis.com/v4/spreadsheets"
MAXROW = 2000

# The 8 DataOS-confirmed passes (batch_of_27) not yet submitted for manual QC.
TARGET_TASKS = [
    "SVC-PC-11-4-0",
    "SVC-PC-2-6-0",
    "SVC-PC-20-8-0",
    "SVC-PC-21-3-0",
    "SVC-PC-21-4-0",
    "SVC-PC-38-1-0",
    "SVC-PC-46-4-0",
    "SVC-PC-73-2-0",
]


def norm(s) -> str:
    return str(s).strip().upper().replace("SVC-PC-", "").replace("SVC_PC_", "")


def token() -> str:
    p = subprocess.run(
        ["gcloud.cmd", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if p.returncode != 0 or not p.stdout.strip():
        sys.exit(
            "gcloud has no token. Run: gcloud.cmd auth login --enable-gdrive-access\n"
            + (p.stderr or "")[:400]
        )
    return p.stdout.strip()


def api(method: str, path: str, tok: str, body=None):
    url = f"{API}/{SHEET}{path}"
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {tok}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            sys.exit(
                f"Sheets API {method} {path} failed: {e.code}\n{e.read().decode()[:600]}"
            )
        except Exception as e:  # IncompleteRead, timeout, transient network
            last = e
            time.sleep(1.5 * (attempt + 1))
    sys.exit(f"Sheets API {method} {path} failed after retries: {last}")


def col_letter(idx0: int) -> str:
    s, n = "", idx0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def qrange(a1: str) -> str:
    return f"/values/{urllib.parse.quote(chr(39) + TAB + chr(39) + '!' + a1)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (default is dry run)")
    ap.add_argument(
        "--tasks",
        nargs="+",
        help="task ids to mark (default: the built-in TARGET_TASKS). e.g. --tasks SVC-PC-2-6-0 SVC-PC-20-8-0",
    )
    ap.add_argument(
        "--assignee",
        help="also set the 'Assigned to' column to this exact name for the tasks "
        "(e.g. --assignee 'Khiem Doan'). Overwrites any existing value; dry run shows old -> new first.",
    )
    ap.add_argument("--tab", default=TAB, help="tracker tab name (default %(default)r)")
    args = ap.parse_args()
    globals()["TAB"] = args.tab
    targets = args.tasks if args.tasks else TARGET_TASKS

    tok = token()

    # 1) small header block to locate the Task ID, Status, and (optional) Assigned-to columns by header text
    # 2026-09-24: the Combined tab was rearranged so the header sits at row 397 with task rows above AND below
    # it; search the whole used range, and require the header's Task ID cell to read exactly "task id".
    head = api("GET", qrange(f"A1:Z{MAXROW}"), tok).get("values", [])
    hdr_i = task_c = status_c = None
    for i, row in enumerate(head):
        if not any(str(c).strip().lower() == "task id" for c in row):
            continue
        low = [str(c).strip().lower() for c in row]
        tc = next((j for j, c in enumerate(low) if "task" in c and "id" in c), None)
        if tc is None:
            tc = next(
                (j for j, c in enumerate(low) if c in ("task", "task id", "id")), None
            )
        sc = next((j for j, c in enumerate(low) if c == "status"), None)
        if sc is None:
            sc = next((j for j, c in enumerate(low) if "status" in c), None)
        if tc is not None and sc is not None:
            hdr_i, task_c, status_c = i, tc, sc
            break
    if hdr_i is None:
        sys.exit("no header row with both a Task ID column and a Status column")
    assignee_c = None
    if args.assignee:
        hrow = [str(c).strip().lower() for c in head[hdr_i]]
        assignee_c = next((j for j, c in enumerate(hrow) if "assign" in c), None)
    msg = (
        f"tab {TAB!r}: header row {hdr_i+1}, Task ID col {col_letter(task_c)}, "
        f"Status col {col_letter(status_c)}"
    )
    if args.assignee:
        msg += f", Assigned-to col {col_letter(assignee_c) if assignee_c is not None else '(NOT FOUND)'}"
    print(msg)

    # 2) fetch ONLY the columns we need (small payloads), aligned by row
    tcol = col_letter(task_c)
    scol = col_letter(status_c)
    tvals = api("GET", qrange(f"{tcol}1:{tcol}{MAXROW}"), tok).get("values", [])
    svals = api("GET", qrange(f"{scol}1:{scol}{MAXROW}"), tok).get("values", [])
    avals = []
    if args.assignee and assignee_c is not None:
        acol = col_letter(assignee_c)
        avals = api("GET", qrange(f"{acol}1:{acol}{MAXROW}"), tok).get("values", [])

    def cell(vals, i):
        return vals[i][0] if i < len(vals) and vals[i] else ""

    want = {norm(t) for t in targets}
    plan, seen = [], set()
    for i in range(MAXROW):  # task rows live above and below the header now
        if i == hdr_i:
            continue
        tid = cell(tvals, i)
        if tid and norm(tid) in want:
            plan.append((tid, i + 1, cell(svals, i), cell(avals, i)))
            seen.add(norm(tid))

    missing = want - seen
    print(
        f"\nmatched {len(plan)} of {len(targets)} target rows"
        + (f"; NOT FOUND in this tab: {sorted(missing)}" if missing else "")
    )

    # status changes
    for tid, rown, old, _a in plan:
        change = (
            "(already set)"
            if str(old).strip() == STATUS_VALUE
            else f"{old!r} -> {STATUS_VALUE!r}"
        )
        print(f"  row {rown:>4}  {tid:16}  status    {change}")
    s_write = [(t, r) for (t, r, o, _a) in plan if str(o).strip() != STATUS_VALUE]

    # assignee changes (opt-in)
    a_write = []
    if args.assignee:
        if assignee_c is None:
            print("  (no 'Assigned to' column found; skipping assignee write)")
        else:
            for tid, rown, _o, olda in plan:
                change = (
                    "(already set)"
                    if str(olda).strip() == args.assignee
                    else f"{olda!r} -> {args.assignee!r}"
                )
                print(f"  row {rown:>4}  {tid:16}  assignee  {change}")
            a_write = [
                (t, r)
                for (t, r, _o, olda) in plan
                if str(olda).strip() != args.assignee
            ]

    if not s_write and not a_write:
        print("\nnothing to write (all already set or none matched).")
        return 0
    if not args.apply:
        print(
            f"\nDRY RUN. {len(s_write)} status + {len(a_write)} assignee cell(s) would be written. "
            "Re-run with --apply."
        )
        return 0

    data = [
        {"range": f"'{TAB}'!{scol}{rown}", "values": [[STATUS_VALUE]]}
        for (_t, rown) in s_write
    ]
    if a_write:
        acol = col_letter(assignee_c)
        data += [
            {"range": f"'{TAB}'!{acol}{rown}", "values": [[args.assignee]]}
            for (_t, rown) in a_write
        ]
    api(
        "POST",
        "/values:batchUpdate",
        tok,
        {"valueInputOption": "USER_ENTERED", "data": data},
    )
    print(
        f"\nwrote {len(s_write)} status + {len(a_write)} assignee cell(s). Reading back to confirm..."
    )
    ok = tot = 0
    for _t, rown in s_write:
        got = api("GET", qrange(f"{scol}{rown}"), tok).get("values", [[""]])
        val = got[0][0] if got and got[0] else ""
        good = str(val).strip() == STATUS_VALUE
        ok += good
        tot += 1
        print(f"  row {rown:>4}  status    {val!r}  {'OK' if good else 'MISMATCH'}")
    if a_write:
        acol = col_letter(assignee_c)
        for _t, rown in a_write:
            got = api("GET", qrange(f"{acol}{rown}"), tok).get("values", [[""]])
            val = got[0][0] if got and got[0] else ""
            good = str(val).strip() == args.assignee
            ok += good
            tot += 1
            print(f"  row {rown:>4}  assignee  {val!r}  {'OK' if good else 'MISMATCH'}")
    print(f"\nconfirmed {ok}/{tot} cell(s).")
    return 0 if ok == tot else 1


if __name__ == "__main__":
    raise SystemExit(main())
