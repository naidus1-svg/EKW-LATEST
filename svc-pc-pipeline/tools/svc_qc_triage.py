#!/usr/bin/env python3
"""Filter Luiz's 102 QC feedback files so experts only see what they can act on.

## Why this exists

Jeff blocked distribution of the batch for one reason: some findings instruct the expert
to write the golden deliverable filenames into the task prompt. Program policy is the
opposite. Prompts stay natural, and filename matching is fixed grader-side in the
converter. The finding's own reasoning says "Same pattern across sibling SVC nodes", and
measured across the batch it appears in 27 of 102 tasks. If experts follow it we
contaminate those prompts and redo the cleanup.

## What the batch actually looks like, measured not assumed

1,022 finding rows across 102 files, 4 to 23 per file. The schema is NOT uniform:

    60 files  15 columns, the full layout
    24 files  13 columns
    11 files  12 columns, no Source column
     5 files  8 columns, using "Check / Dimension" and "Severity" instead
     2 files  prose reports, not tables

An earlier design keyed on Source plus a bracketed QC dimension, which is what one sample
file showed. That covers 138 of 1,022 rows. The field that actually discriminates is
**Fix Title**, present in 95 of 102 files, with 627 distinct values.

## Routing, and why unmatched defaults to expert

    DANGER      the filename-in-prompt class. Relabelled, never shipped as an instruction
    NO_ACTION   the finding already says no fix is needed
    CONVERTER   the fix is ours in the converter or harness, not the expert's
    EXPERT      everything else
    UNTITLED    no Fix Title to key on. Listed for review, not shipped

Unmatched rows default to EXPERT deliberately. That is the status quo, so it adds no new
risk. The job is to positively identify the classes that must be pulled OUT; a novel
finding staying in expert feedback is exactly where it already is today.

    python tools/svc_qc_triage.py [--src C:/b/_qc102] [--out C:/b/_qc102_filtered]

Exit 0 only when the acceptance test passes: zero filtered copies contain the
filename-in-prompt guidance.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

REPO = Path(__file__).resolve().parent.parent

# The class that must never reach an expert as an instruction. Matched on the finding's
# own wording rather than on a label, because the label is not reliable across schemas.
DANGER = re.compile(
    r"name required deliverable|naming each required deliverable"
    r"|exact output filename|required output filename"
    r"|name the expected deliverable|name memo and model filename"
    r"|never named in instruction\.md|state the exact output"
    r"|add .{0,60}filenames?.{0,60}(to the prompt|to instruction\.md)"
    r"|filename.{0,30}(in|into) the (prompt|instruction)",
    re.I,
)

# Already resolved by the finding itself. Checked before DANGER and CONVERTER:
# several titles say both ("No task fix - converter limitation"), and a few DANGER
# hits are false positives whose body text mentions the pattern only to say it is
# already fixed ("No fix - supersession clause resolves it").
NO_ACTION = re.compile(
    r"^\s*(no fix|none needed|n/?a\b|no forced|no change|no action|no task fix"
    r"|not a defect|false positive)"
    r"|already resolved|already authoritative|already works|resolves it",
    re.I,
)

# Ours to fix centrally, once, rather than 100 times by hand.
CONVERTER = re.compile(
    r"converter|harness|judge\.toml|verifier\.json|rewardkit|reward-kit|must_pass"
    r"|must-pass gate|conversion|reward-kit limitation|file cap|attachment cap"
    r"|numeric judge gate|hidden style gate|harness metadata",
    re.I,
)

ROUTE_LABEL = {
    "DANGER": "Known issue, grader-side fix, no expert action needed",
    "CONVERTER": "Handled centrally in the converter, no expert action needed",
    "NO_ACTION": "The reviewer concluded no fix is needed",
}

TITLE_COLS = ("Fix Title", "Check / Dimension")
GUIDE_COLS = ("Actionable Fix Guidance", "Action Required")
FILL_COLS = ("Expert Verdict (fill in)", "Expert Proposed Fix (fill in)")

HEAD = PatternFill("solid", fgColor="1F3A5F")
WARN = PatternFill("solid", fgColor="FFEB9C")


def classify(title: str, blob: str) -> tuple[str, str]:
    """Return (route, why). NO_ACTION wins over DANGER: a handful of findings say
    the conflict is already resolved but still match DANGER's wording in their
    body text rather than their instruction."""
    if NO_ACTION.search(title):
        return "NO_ACTION", "the finding states no fix is needed"
    if DANGER.search(blob):
        return (
            "DANGER",
            "instructs putting golden filenames in the prompt, policy violation",
        )
    if not title.strip():
        return "UNTITLED", "no Fix Title to route on"
    if CONVERTER.search(title):
        return "CONVERTER", "fix is converter or harness side, not task side"
    return "EXPERT", "no rule matched, defaults to expert which is the status quo"


def read_findings(path: Path, task: str) -> tuple[list[dict], list[str], str]:
    """Rows, header, and a schema note. Never raises on a weird file."""
    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return [], [], f"unreadable: {str(exc)[:60]}"
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], [], "empty"
    hdr = [str(h).strip() if h is not None else "" for h in rows[0]]
    if "Issue Description" not in hdr and "Check / Dimension" not in hdr:
        return [], hdr, "prose report, not a finding table"
    idx = {h: i for i, h in enumerate(hdr)}

    def cell(r, *names):
        for n in names:
            i = idx.get(n)
            if i is not None and i < len(r) and r[i] is not None:
                return str(r[i]).strip()
        return ""

    out = []
    for r in rows[1:]:
        if not any(v is not None and str(v).strip() for v in r):
            continue
        title = cell(r, *TITLE_COLS)
        blob = " ".join(str(v) for v in r if v is not None)
        route, why = classify(title, blob)
        out.append(
            {
                "task": task,
                "raw": list(r),
                "title": title,
                "issue": cell(r, "Issue Description"),
                "source": cell(r, "Source"),
                "verdict": cell(r, "Auto-Verdict"),
                "impact": cell(r, "Scoring Impact", "Severity"),
                "guidance": cell(r, *GUIDE_COLS),
                "route": route,
                "why": why,
            }
        )
    return out, hdr, "ok"


def style_header(ws, n):
    for c in range(1, n + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEAD
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        ws.auto_filter.ref = f"A1:{chr(64 + min(n, 26))}{ws.max_row}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="C:/b/_qc102")
    ap.add_argument("--out", default="C:/b/_qc102_filtered")
    ap.add_argument("--sheet", default=str(REPO / "ekw/svc-qc-triage-2026-09-02.xlsx"))
    args = ap.parse_args()

    src, out = Path(args.src), Path(args.out)
    man = json.loads((src / "_manifest.json").read_text(encoding="utf-8"))
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    all_rows, schema_notes, per_task = [], {}, {}
    for f in man["files"]:
        rows, hdr, note = read_findings(Path(f["local"]), f["task"])
        schema_notes[f["task"]] = note
        per_task[f["task"]] = {"rows": rows, "hdr": hdr, "note": note}
        all_rows.extend(rows)

    routes = Counter(r["route"] for r in all_rows)
    print(f"files            : {len(per_task)}")
    print(f"finding rows     : {len(all_rows)}")
    for k in ("EXPERT", "NO_ACTION", "CONVERTER", "DANGER", "UNTITLED"):
        print(f"  {k:<10} {routes.get(k, 0)}")
    odd = {t: n for t, n in schema_notes.items() if n != "ok"}
    if odd:
        print(f"\nnot parsed as a finding table ({len(odd)}), listed in the sheet:")
        for t, n in odd.items():
            print(f"  {t:<16} {n}")

    danger_tasks = sorted({r["task"] for r in all_rows if r["route"] == "DANGER"})
    print(f"\nDANGER rows {routes.get('DANGER', 0)} across {len(danger_tasks)} tasks")

    # ---- filtered copies, expert rows only --------------------------------
    written, nothing_to_do = 0, []
    for task, d in per_task.items():
        keep = [r for r in d["rows"] if r["route"] == "EXPERT"]
        if not keep:
            nothing_to_do.append(task)
            continue
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Expert actions"
        hdr = d["hdr"]
        ws.append(hdr)
        for r in keep:
            ws.append(["" if v is None else v for v in r["raw"]])
        style_header(ws, len(hdr))
        for col, w in (("C", 60), ("F", 50), ("L", 70)):
            ws.column_dimensions[col].width = w

        note = wb.create_sheet("What was filtered out")
        note.append(["This copy contains only the findings an expert should act on."])
        note.append([""])
        dropped = Counter(r["route"] for r in d["rows"] if r["route"] != "EXPERT")
        for k, v in dropped.items():
            note.append([f"{v} finding(s) removed: {ROUTE_LABEL.get(k, k)}"])
        note.append([""])
        note.append(["Removed because they are not task-side work:"])
        note.append(
            [
                f"{ROUTE_LABEL['DANGER']}: instructs naming golden deliverable "
                "filenames in the prompt. Against policy."
            ]
        )
        note.append(
            [f"{ROUTE_LABEL['CONVERTER']}: judge, harness or conversion behaviour."]
        )
        note.append([f"{ROUTE_LABEL['NO_ACTION']}."])
        note.append([""])
        note.append(
            ["Full routing for every finding is in svc-qc-triage-2026-09-02.xlsx."]
        )
        note.column_dimensions["A"].width = 110
        for row in note.iter_rows(min_col=1, max_col=1):
            row[0].alignment = Alignment(wrap_text=True, vertical="top")
        wb.save(out / f"{task}_expert_actions.xlsx")
        written += 1

    print(f"\nfiltered copies written : {written}")
    print(f"nothing for an expert   : {len(nothing_to_do)}")

    # ---- acceptance test ---------------------------------------------------
    leaked = []
    for p in sorted(out.glob("*.xlsx")):
        wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
        for sheet in wb.worksheets:
            if sheet.title != "Expert actions":
                continue
            for r in sheet.iter_rows(values_only=True):
                blob = " ".join(str(v) for v in r if v is not None)
                if DANGER.search(blob):
                    leaked.append((p.name, DANGER.search(blob).group(0)[:60]))
        wb.close()

    # ---- master routing sheet ---------------------------------------------
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "All findings"
    cols = [
        "Task",
        "Route",
        "Why",
        "Fix Title",
        "Source",
        "Auto-Verdict",
        "Scoring Impact",
        "Issue Description",
        "Actionable Fix Guidance",
    ]
    ws.append(cols)
    for r in all_rows:
        ws.append(
            [
                r["task"],
                r["route"],
                r["why"],
                r["title"],
                r["source"],
                r["verdict"],
                r["impact"],
                r["issue"][:600],
                r["guidance"][:900],
            ]
        )
        if r["route"] == "DANGER":
            ws.cell(row=ws.max_row, column=2).fill = WARN
    style_header(ws, len(cols))
    for c, w in (("C", 46), ("D", 40), ("H", 70), ("I", 80)):
        ws.column_dimensions[c].width = w

    ws2 = wb.create_sheet("Per task")
    ws2.append(
        [
            "Task",
            "Findings",
            "Expert",
            "Converter",
            "No action",
            "Danger",
            "Untitled",
            "Schema",
            "Copy written",
        ]
    )
    for task, d in per_task.items():
        c = Counter(r["route"] for r in d["rows"])
        ws2.append(
            [
                task,
                len(d["rows"]),
                c.get("EXPERT", 0),
                c.get("CONVERTER", 0),
                c.get("NO_ACTION", 0),
                c.get("DANGER", 0),
                c.get("UNTITLED", 0),
                d["note"],
                "no" if task in nothing_to_do else "yes",
            ]
        )
    style_header(ws2, 9)

    ws3 = wb.create_sheet("Read me")
    for line in readme(
        len(all_rows), routes, danger_tasks, written, nothing_to_do, odd
    ):
        ws3.append([line])
    ws3.column_dimensions["A"].width = 108
    for row in ws3.iter_rows(min_col=1, max_col=1):
        row[0].alignment = Alignment(wrap_text=True, vertical="top")

    Path(args.sheet).parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.sheet)
    print(f"routing sheet           : {args.sheet}")
    print(f"filtered copies         : {out}")

    print("\n=== acceptance test ===")
    print(f"filtered copies containing the filename-in-prompt guidance: {len(leaked)}")
    if leaked:
        for n, m in leaked[:10]:
            print(f"  LEAK {n}  <- {m}")
        print("\nFAIL, do not ship")
        return 1
    print("PASS")
    return 0


def readme(total, routes, danger_tasks, written, nothing, odd):
    return [
        "SVC QC feedback triage, 2026-09-02",
        "",
        "Jeff blocked the 102 QC feedback files because some findings tell the expert to "
        "write the golden deliverable filenames into the task prompt. That is against "
        "policy: prompts stay natural, and filename matching is fixed grader-side in the "
        "converter. Measured across the batch, that instruction appears in "
        f"{routes.get('DANGER', 0)} findings across {len(danger_tasks)} of 102 tasks.",
        "",
        "WHAT WAS DONE",
        f"Every one of the {total} findings across the 102 files was routed. Filtered "
        f"copies containing only expert-actionable findings were written for {written} "
        f"tasks. {len(nothing)} tasks had nothing for an expert.",
        "",
        "HOW EACH FINDING WAS ROUTED",
        f"EXPERT ({routes.get('EXPERT', 0)}): kept. Leaked pipeline markers in inputs, "
        "compound or subjective criteria, near-miss value conflicts, and everything else "
        "that is task-side work.",
        f"DANGER ({routes.get('DANGER', 0)}): removed. The filename-in-prompt class.",
        f"CONVERTER ({routes.get('CONVERTER', 0)}): removed. Judge, harness or conversion "
        "behaviour, ours to fix centrally rather than 100 times by hand.",
        f"NO_ACTION ({routes.get('NO_ACTION', 0)}): removed. The finding itself says no fix "
        "is needed.",
        f"UNTITLED ({routes.get('UNTITLED', 0)}): kept out and listed. No Fix Title to route on.",
        "",
        "WHY UNMATCHED FINDINGS STAY WITH THE EXPERT",
        "The router positively identifies what must come OUT. Anything it does not "
        "recognise stays in expert feedback, which is exactly where it sits today, so an "
        "unrecognised finding carries no new risk. The opposite default would silently "
        "drop real work.",
        "",
        "THE KEY IS THE FIX TITLE, NOT THE QC DIMENSION",
        "An earlier design keyed on Source plus a bracketed QC dimension, which is what one "
        "sample file showed. Across all 102 that covers 138 of 1,022 rows. The schema is "
        "not uniform either: six header layouts, one using Check / Dimension and Severity "
        "instead of the usual columns, and two files that are prose reports rather than "
        "tables. Fix Title is present in 95 of 102 files and is what the routing uses.",
        "",
        f"FILES THAT ARE NOT FINDING TABLES ({len(odd)})",
        *[f"  {t}: {n}" for t, n in odd.items()],
        "These were not filtered and need a look by hand.",
        "",
        "ORIGINALS ARE UNTOUCHED",
        "Luiz's 102 files were downloaded read-only and never written to. The filtered "
        "copies are new files.",
        "",
        "Rebuild with: python tools/svc_qc_triage.py",
    ]


if __name__ == "__main__":
    sys.exit(main())
