#!/usr/bin/env python3
"""Build the Jafar-ready review package from the 22 full-corpus SVC audit batch files.

Reuses the tab pattern from tools/svc_fp_screen_sheet.py and tools/svc_autofix_report.py:
a narrative Summary tab first, then per-disposition tabs a reader can act on directly, plus
a combined reviewer sign-off tab so Jafar's team can fill in agree/disagree without a
separate document per task.

Every count in this workbook is recomputed from the 22 batch JSON files directly - it does
not trust ekw/svc-full-audit-report-2026-09-12.md's own prose numbers, which the report
itself flags as approximate for the fixable-tier split.

    python tools/svc_full_audit_review_package.py \\
        --batches-dir ekw \\
        --out ekw/svc-full-audit-review-package-2026-09-12.xlsx
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BATCHES_DIR = REPO_ROOT / "ekw"
DEFAULT_OUT = REPO_ROOT / "ekw" / "svc-full-audit-review-package-2026-09-12.xlsx"
BATCH_COUNT = 22

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="343A40")
WRAP_TOP = Alignment(wrap_text=True, vertical="top")
TIER_FILL = {
    1: PatternFill("solid", fgColor="D4EDDA"),
    2: PatternFill("solid", fgColor="FFF3CD"),
    3: PatternFill("solid", fgColor="F8D7DA"),
}

TASK_ID_RE = re.compile(r"^SVC-PC-(\d+)-(\d+)-(\d+)$")
TIER2_RE = re.compile(r"\bmov(e|es|ed|ing)\b|duplicate|misrouted")
TIER3_RE = re.compile(r"\brebuild|\bauthor|write a |create a ")

SOURCE_PATTERNS = [
    re.compile(r"matching[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"per (?:the|this)[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"sourced from[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"pulled from[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"inferable[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"cross-check(?:ed|ing)?[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"sibling task[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"the golden'?s? own[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"the tracker'?s? own[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"already named in[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"already correct[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"referenced? elsewhere[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"the prompt'?s? (?:explicit )?instruction[^.;]{0,150}", re.IGNORECASE),
    re.compile(r"invoice[- ]sum path[^.;]{5,150}", re.IGNORECASE),
    re.compile(r"own formula[^.;]{0,100}", re.IGNORECASE),
    re.compile(r"from context[^.;]{0,100}", re.IGNORECASE),
    re.compile(r"as SVC-PC-\d+-\d+-\d+[^.;]{0,80}", re.IGNORECASE),
    re.compile(r"SVC-PC-\d+-\d+-\d+[^.;]{0,80}", re.IGNORECASE),
]
SOURCE_FALLBACK = (
    "(no explicit source phrase found in proposed_fixes text; see Proposed Fix)"
)

BLOCKER_CUES = [
    "genuine input dependency",
    "not present in the room",
    "did not find",
    "did not have access",
    "irreducible dependency",
    "not available",
]
BLOCKER_FALLBACK = "(none noted)"

UNREACHABLE_CATEGORIES = [
    (re.compile(r"requested entity was not found|stale, deleted"), "broken link"),
    (re.compile(r"corrupt"), "unreadable/corrupt file"),
    (re.compile(r"4-row|not the reference answer itself"), "wrong content in file"),
    (re.compile(r"missing prompt"), "missing prompt only (golden/rubric reachable)"),
    (
        re.compile(r"literal placeholder|literal string"),
        "not-yet-built (placeholder tracker cell)",
    ),
]
UNREACHABLE_DEFAULT = "not-yet-built (blank tracker row, no Drive folder)"


def task_sort_key(task_id: str):
    m = TASK_ID_RE.match(task_id)
    return tuple(int(g) for g in m.groups())


def load_all_tasks(batches_dir: Path) -> list[dict]:
    tasks = []
    for i in range(BATCH_COUNT):
        path = batches_dir / f"svc-full-audit-batch-{i}.json"
        batch = json.loads(path.read_text(encoding="utf-8"))
        tasks.extend(batch)
    ids = [t["task_id"] for t in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate task_id found across the 22 batch files")
    return tasks


def sanitize(text: str) -> str:
    return text.replace("—", "-").replace("–", "-")


def joined(field) -> str:
    if field is None:
        return ""
    if isinstance(field, list):
        raw = "; ".join(str(x) for x in field if x)
    else:
        raw = str(field)
    return sanitize(raw)


def fixable_tier(task: dict) -> int:
    text = joined(task.get("proposed_fixes")).lower()
    if TIER2_RE.search(text):
        return 2
    if TIER3_RE.search(text):
        return 3
    return 1


def extract_source(text: str) -> str:
    for pat in SOURCE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0).strip()
    return SOURCE_FALLBACK


def extract_blocker(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    lowered_cues = BLOCKER_CUES
    for sentence in sentences:
        low = sentence.lower()
        if any(cue in low for cue in lowered_cues):
            return sentence.strip()
    return BLOCKER_FALLBACK


def unreachable_category(task: dict) -> str:
    text = (joined(task.get("notes")) + " " + joined(task.get("defects_found"))).lower()
    for pat, label in UNREACHABLE_CATEGORIES:
        if pat.search(text):
            return label
    return UNREACHABLE_DEFAULT


def style_header(ws, labels: list[str]) -> None:
    ws.append(labels)
    for col in range(1, len(labels) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = WRAP_TOP
    ws.freeze_panes = "A2"


def set_widths(ws, widths: list[int]) -> None:
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def wrap_all_rows(ws, min_row: int = 2) -> None:
    for row in ws.iter_rows(min_row=min_row):
        for cell in row:
            cell.alignment = WRAP_TOP


def build_summary(wb, counts: dict, tier_counts: dict, unreach_counts: dict) -> None:
    ws = wb.active
    ws.title = "Summary"
    rows = [
        ("SVC full-corpus audit: Jafar review package", ""),
        ("Generated", "2026-09-12"),
        (
            "Source",
            "22 batch files, ekw/svc-full-audit-batch-0.json through -21.json, "
            "635 SVC tracker tasks (535 L2 + 100 L3), recounted directly in this "
            "script rather than trusted from the report's own prose",
        ),
        ("", ""),
        (
            "Headline counts (recomputed, verified against ekw/svc-full-audit-report-2026-09-12.md)",
            "",
        ),
        ("Total tasks", counts["total"]),
        ("Clean (Tier 0, ready now)", counts["clean"]),
        ("Fixable", counts["fixable"]),
        ("Genuinely blocked", counts["genuinely_blocked"]),
        ("Unreachable content", counts["unreachable_content"]),
        ("", ""),
        (
            "Fixable tier breakdown (keyword classification over each task's proposed_fixes "
            "text, checked in this order: Tier 2 keywords first, then Tier 3, else Tier 1 - "
            "this is a fast approximation, not a hand re-audit, matching the report's own "
            "caveat about its tier splits)",
            "",
        ),
        (
            "Tier 1: one-cell edits (stated single replacement value, no move, no authoring)",
            tier_counts[1],
        ),
        (
            "Tier 2: file moves (proposed_fixes mentions move/duplicate/misrouted)",
            tier_counts[2],
        ),
        (
            "Tier 3: needs authored content (proposed_fixes mentions rebuild/author/"
            "write a/create a)",
            tier_counts[3],
        ),
        ("", ""),
        (
            "Unreachable content breakdown (categorized from each task's own notes/"
            "defects_found text)",
            "",
        ),
        (
            "Not-yet-built, placeholder tracker cell",
            unreach_counts.get("not-yet-built (placeholder tracker cell)", 0),
        ),
        (
            "Not-yet-built, blank tracker row / no Drive folder",
            unreach_counts.get("not-yet-built (blank tracker row, no Drive folder)", 0),
        ),
        ("Broken link", unreach_counts.get("broken link", 0)),
        ("Unreadable/corrupt file", unreach_counts.get("unreadable/corrupt file", 0)),
        ("Wrong content in file", unreach_counts.get("wrong content in file", 0)),
        (
            "Missing prompt only (golden/rubric reachable)",
            unreach_counts.get("missing prompt only (golden/rubric reachable)", 0),
        ),
        ("", ""),
        (
            "Methodology",
            "Audited directly from source content (prompt/golden/rubric read "
            "from Drive), independent of the DataOS pipeline and independent of tracker "
            "status. Does not include oracle certification and does not include DataOS "
            "upload status for any task.",
        ),
        (
            "What this package does NOT establish",
            "A clean or Tier 1/2/3 classification "
            "here means the source content is internally consistent or has a stated fix - it "
            "does not mean the task has been uploaded to DataOS, has passed an oracle run, or "
            "has Jafar's sign-off. Those are separate, later gates this package does not "
            "check. Tab 7 exists so that sign-off gate has a place to land.",
        ),
    ]
    for r, (label, value) in enumerate(rows, start=1):
        lc = ws.cell(row=r, column=1, value=label)
        vc = ws.cell(row=r, column=2, value=value)
        lc.alignment = WRAP_TOP
        vc.alignment = WRAP_TOP
        if label and not value and r > 3:
            lc.font = Font(bold=True)
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 92


def build_clean(wb, clean_tasks: list[dict]) -> int:
    ws = wb.create_sheet("Ready now (Tier 0 - clean)")
    style_header(ws, ["Task ID", "Notes (what was checked)"])
    for task in sorted(clean_tasks, key=lambda t: task_sort_key(t["task_id"])):
        ws.append([task["task_id"], joined(task.get("notes"))])
    set_widths(ws, [18, 110])
    wrap_all_rows(ws)
    return len(clean_tasks)


def build_tier1(wb, tier1_tasks: list[dict]) -> int:
    ws = wb.create_sheet("One-cell fixes (Tier 1)")
    style_header(ws, ["Task ID", "Issue", "Proposed Fix", "Source"])
    for task in sorted(tier1_tasks, key=lambda t: task_sort_key(t["task_id"])):
        fix_text = joined(task.get("proposed_fixes"))
        ws.append(
            [
                task["task_id"],
                joined(task.get("defects_found")),
                fix_text,
                extract_source(fix_text),
            ]
        )
    set_widths(ws, [18, 55, 65, 45])
    wrap_all_rows(ws)
    return len(tier1_tasks)


def build_tier2(wb, tier2_tasks: list[dict]) -> int:
    ws = wb.create_sheet("File-move fixes (Tier 2)")
    style_header(ws, ["Task ID", "Issue", "What to move/delete/where"])
    for task in sorted(tier2_tasks, key=lambda t: task_sort_key(t["task_id"])):
        ws.append(
            [
                task["task_id"],
                joined(task.get("defects_found")),
                joined(task.get("proposed_fixes")),
            ]
        )
    set_widths(ws, [18, 55, 65])
    wrap_all_rows(ws)
    return len(tier2_tasks)


def build_tier3(wb, tier3_tasks: list[dict]) -> int:
    ws = wb.create_sheet("Needs authored content (Tier 3)")
    style_header(ws, ["Task ID", "Issue", "What needs to be built", "Blocker (if any)"])
    for task in sorted(tier3_tasks, key=lambda t: task_sort_key(t["task_id"])):
        fix_text = joined(task.get("proposed_fixes"))
        combined = fix_text + " " + joined(task.get("defects_found"))
        ws.append(
            [
                task["task_id"],
                joined(task.get("defects_found")),
                fix_text,
                extract_blocker(combined),
            ]
        )
    set_widths(ws, [18, 55, 65, 55])
    wrap_all_rows(ws)
    return len(tier3_tasks)


def build_unreachable(wb, unreach_tasks: list[dict]) -> tuple[int, dict]:
    ws = wb.create_sheet("Not in near-term pool (unreach)")
    style_header(ws, ["Task ID", "Why"])
    counts: dict[str, int] = {}
    for task in sorted(unreach_tasks, key=lambda t: task_sort_key(t["task_id"])):
        category = unreachable_category(task)
        counts[category] = counts.get(category, 0) + 1
        detail = joined(task.get("notes")) or joined(task.get("defects_found"))
        why = f"{category} - {detail}"
        ws.append([task["task_id"], why])
    set_widths(ws, [18, 110])
    wrap_all_rows(ws)
    return len(unreach_tasks), counts


def build_signoff(wb, tier1_tasks, tier2_tasks, tier3_tasks) -> int:
    ws = wb.create_sheet("Reviewer sign-off")
    style_header(
        ws,
        [
            "Task ID",
            "Tier",
            "Issue",
            "Proposed Fix / Action",
            "Expert Verdict (fill in)",
            "Expert Proposed Fix (fill in)",
        ],
    )
    all_rows = (
        [(1, t) for t in tier1_tasks]
        + [(2, t) for t in tier2_tasks]
        + [(3, t) for t in tier3_tasks]
    )
    all_rows.sort(key=lambda pair: (pair[0], task_sort_key(pair[1]["task_id"])))
    for tier, task in all_rows:
        r = ws.max_row + 1
        ws.append(
            [
                task["task_id"],
                tier,
                joined(task.get("defects_found")),
                joined(task.get("proposed_fixes")),
                "",
                "",
            ]
        )
        fill = TIER_FILL.get(tier)
        if fill:
            ws.cell(row=r, column=2).fill = fill
    set_widths(ws, [18, 8, 50, 60, 22, 30])
    wrap_all_rows(ws)
    return len(all_rows)


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--batches-dir", type=Path, default=DEFAULT_BATCHES_DIR)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()

    tasks = load_all_tasks(args.batches_dir)

    clean = [t for t in tasks if t["classification"] == "clean"]
    fixable = [t for t in tasks if t["classification"] == "fixable"]
    blocked = [t for t in tasks if t["classification"] == "genuinely_blocked"]
    unreachable = [t for t in tasks if t["classification"] == "unreachable_content"]

    counts = {
        "total": len(tasks),
        "clean": len(clean),
        "fixable": len(fixable),
        "genuinely_blocked": len(blocked),
        "unreachable_content": len(unreachable),
    }

    tier1 = [t for t in fixable if fixable_tier(t) == 1]
    tier2 = [t for t in fixable if fixable_tier(t) == 2]
    tier3 = [t for t in fixable if fixable_tier(t) == 3]
    tier_counts = {1: len(tier1), 2: len(tier2), 3: len(tier3)}

    wb = openpyxl.Workbook()
    n_clean = build_clean(wb, clean)
    n_tier1 = build_tier1(wb, tier1)
    n_tier2 = build_tier2(wb, tier2)
    n_tier3 = build_tier3(wb, tier3)
    n_unreach, unreach_counts = build_unreachable(wb, unreachable)
    n_signoff = build_signoff(wb, tier1, tier2, tier3)
    build_summary(wb, counts, tier_counts, unreach_counts)
    wb.move_sheet("Summary", offset=-(len(wb.sheetnames) - 1))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out)

    print(f"Wrote {args.out}")
    print(
        f"  total tasks {counts['total']}: clean {counts['clean']}, "
        f"fixable {counts['fixable']}, genuinely_blocked {counts['genuinely_blocked']}, "
        f"unreachable {counts['unreachable_content']}"
    )
    print(
        f"  fixable tiers: Tier1 {tier_counts[1]}, Tier2 {tier_counts[2]}, "
        f"Tier3 {tier_counts[3]}"
    )
    print(
        f"  tab rows: clean {n_clean}, tier1 {n_tier1}, tier2 {n_tier2}, "
        f"tier3 {n_tier3}, unreachable {n_unreach}, signoff {n_signoff}"
    )
    print(f"  tabs 2-6 total: {n_clean + n_tier1 + n_tier2 + n_tier3 + n_unreach}")
    print(f"  unreachable categories: {unreach_counts}")


if __name__ == "__main__":
    main()
