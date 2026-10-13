#!/usr/bin/env python3
"""Build one task_<id>_qc_validation.xlsx per task, matching the real column schema used by
Luiz's own QC validation reports (confirmed live example: task_LGL-110_qc_validation.xlsx,
Drive id 1Z6eQDES0tnqks8iOH7QawyNqj0xpyOUk, read in full 2026-09-11).

Columns (exact order, from the real example):
QC Issues Task ID, Source, Issue Description, Auto-Verdict, Defect Class, Fix Owner,
Verdict Reasoning, Evidence Excerpt, Evidence Reference (path), Scoring Impact,
Authoring Effort, Fix Title, Actionable Fix Guidance, Expert Verdict (fill in),
Expert Proposed Fix (fill in), Last Run

Mechanical fields (Auto-Verdict, Verdict Reasoning, Evidence Excerpt, Last Run) come straight
from the verdicts JSON. Source is stated honestly as automated, not manual - nobody has
human-reviewed these findings individually yet, which is exactly why Expert Verdict/Expert
Proposed Fix are left blank for a human to fill in.

Authored fields (Defect Class, Fix Owner, Scoring Impact, Authoring Effort, Fix Title,
Actionable Fix Guidance) come from a separate authoring-pass JSON, keyed by finding id, produced
by parallel LLM agents per docs/plans/partitioned-purring-origami.md step 5. Only TRUE_POSITIVE
and PARTIAL findings get the full authored treatment, matching what Luiz's own example actually
contains (his file held only true_positive rows) - FALSE_POSITIVE and UNCERTAIN rows get a short
note instead, since there's no fix to guide toward for a cleared or unresolved finding.

    python tools/svc_qc_validation_sheet.py \\
        --verdicts ekw/svc-fp-verdicts-2026-09-11.json \\
        --authoring ekw/svc-qc-authoring-2026-09-11.json \\
        --out-dir ekw/qc-validation-2026-09-11/
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VERDICTS = REPO_ROOT / "ekw" / "svc-fp-verdicts-2026-09-11.json"
DEFAULT_AUTHORING = REPO_ROOT / "ekw" / "svc-qc-authoring-2026-09-11.json"
DEFAULT_OUT_DIR = REPO_ROOT / "ekw" / "qc-validation-2026-09-11"

COLUMNS = [
    "QC Issues Task ID",
    "Source",
    "Issue Description",
    "Auto-Verdict",
    "Defect Class",
    "Fix Owner",
    "Verdict Reasoning",
    "Evidence Excerpt",
    "Evidence Reference (path)",
    "Scoring Impact",
    "Authoring Effort",
    "Fix Title",
    "Actionable Fix Guidance",
    "Expert Verdict (fill in)",
    "Expert Proposed Fix (fill in)",
    "Last Run",
]
COLUMN_WIDTHS = [18, 24, 40, 14, 16, 14, 45, 45, 40, 12, 14, 30, 60, 16, 20, 12]
SOURCE = "dataos_automated+claude_fp_screen_automated"
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="343A40")
WRAP_TOP = Alignment(wrap_text=True, vertical="top")

FILE_REF_PATTERN = re.compile(
    r"[\w./\\-]+\.(?:xlsx|xlsm|docx|doc|pdf|csv|json|toml|txt|pptx)", re.IGNORECASE
)


def finding_key(entry: dict) -> str:
    return f"{entry.get('dataset')}::{entry.get('task_id')}::{entry.get('name')}"


def task_filename(task_id: str) -> str:
    lowered = task_id.lower()
    stem = lowered if lowered.startswith("task_") else f"task_{lowered}"
    return f"{stem}_qc_validation.xlsx"


def extract_evidence_reference(entry: dict) -> str:
    text = f"{entry.get('evidence', '')} {entry.get('reasoning', '')}"
    matches = FILE_REF_PATTERN.findall(text)
    if matches:
        seen = []
        for m in matches:
            if m not in seen:
                seen.append(m)
        return "; ".join(seen[:5])
    return (
        f"dataset {entry.get('dataset')}, task {entry.get('task_id')}, "
        f"criterion {entry.get('name')} (no specific file path found in evidence/reasoning text)"
    )


def load_json(path: Path) -> dict | list:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_row(entry: dict, authored: dict, generated_date: str) -> list:
    verdict = entry.get("verdict", "")
    auto_verdict = verdict.lower()
    if verdict in ("TRUE_POSITIVE", "PARTIAL"):
        defect_class = authored.get("defect_class", "(authoring pending)")
        fix_owner = authored.get("fix_owner", "(authoring pending)")
        scoring_impact = authored.get("scoring_impact", "(authoring pending)")
        authoring_effort = authored.get("authoring_effort", "(authoring pending)")
        fix_title = authored.get("fix_title", "(authoring pending)")
        guidance = authored.get("actionable_fix_guidance", "(authoring pending)")
    elif verdict == "FALSE_POSITIVE":
        defect_class, fix_owner, scoring_impact, authoring_effort = (
            "none",
            "n/a",
            "n/a",
            "n/a",
        )
        fix_title = "Cleared - no fix needed"
        guidance = (
            f"Screened FALSE_POSITIVE, class {entry.get('fp_class', 'none')}, confidence "
            f"{entry.get('confidence', 'n/a')}. Route to a human for confirmation before treating "
            f"as fully closed (screen's own measured FALSE_POSITIVE precision is 0.40)."
        )
    else:  # UNCERTAIN
        defect_class, fix_owner, scoring_impact, authoring_effort = (
            "unresolved",
            "n/a",
            "n/a",
            "n/a",
        )
        fix_title = "Needs human file access to resolve"
        guidance = (
            "The automated screen could not settle this from the bounded evidence it had. "
            "Needs someone with real file access to the task package to check further, not "
            "another automated pass on the same snapshot."
        )
    return [
        entry.get("task_id", ""),
        SOURCE,
        entry.get("description", "") or entry.get("evidence", ""),
        auto_verdict,
        defect_class,
        fix_owner,
        entry.get("reasoning", ""),
        entry.get("evidence", ""),
        extract_evidence_reference(entry),
        scoring_impact,
        authoring_effort,
        fix_title,
        guidance,
        "",
        "",
        generated_date,
    ]


def build_task_workbook(
    task_id: str, entries: list[dict], authoring: dict, generated_date: str
):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "QC Issues Task Overview"
    ws.append(COLUMNS)
    for col in range(1, len(COLUMNS) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = WRAP_TOP
    ws.freeze_panes = "A2"
    for r, entry in enumerate(entries, start=2):
        authored = authoring.get(finding_key(entry), {})
        row = build_row(entry, authored, generated_date)
        for c, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.alignment = WRAP_TOP
    for i, width in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    return wb


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--verdicts", type=Path, default=DEFAULT_VERDICTS)
    p.add_argument("--authoring", type=Path, default=DEFAULT_AUTHORING)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--generated-date", default="2026-09-11")
    args = p.parse_args()

    verdicts = load_json(args.verdicts)
    authoring = load_json(args.authoring)
    if isinstance(authoring, list):
        authoring = {finding_key(e): e for e in authoring}

    by_task: dict[str, list[dict]] = defaultdict(list)
    for entry in verdicts:
        by_task[entry.get("task_id", "unknown")].append(entry)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    missing_authoring = 0
    for task_id, entries in sorted(by_task.items()):
        wb = build_task_workbook(task_id, entries, authoring, args.generated_date)
        out_path = args.out_dir / task_filename(task_id)
        wb.save(out_path)
        written.append(out_path)
        for entry in entries:
            if entry.get("verdict") in ("TRUE_POSITIVE", "PARTIAL"):
                if finding_key(entry) not in authoring:
                    missing_authoring += 1

    print(f"Wrote {len(written)} per-task workbooks to {args.out_dir}")
    print(
        f"Total findings: {len(verdicts)} across {len(by_task)} distinct raw task ids"
    )
    if missing_authoring:
        print(
            f"WARNING: {missing_authoring} TRUE_POSITIVE/PARTIAL findings had no authoring-pass "
            f"entry and fell back to '(authoring pending)' placeholders."
        )
    else:
        print("All TRUE_POSITIVE/PARTIAL findings have authored content.")


if __name__ == "__main__":
    main()
