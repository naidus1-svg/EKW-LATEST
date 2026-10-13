#!/usr/bin/env python3
"""Build the SVC false-positive screen results workbook from the combined verdicts.

Input is the flat list produced by screening trainer-owned QC findings through Andrew
Ma's fp_screen.py/fp_screen.md prompt (one dict per finding: dataset, task_id, name,
verdict, fp_class, confidence, evidence, reasoning, surviving_defect). This script does
not run the screen itself - it only lays out an already-screened result set for a human
to read and act on.

    python tools/svc_fp_screen_sheet.py --verdicts ekw/svc-fp-verdicts-2026-09-11.json

The Summary tab's narrative fields (609 root cause, timeout-dataset diagnosis, the
uncertain-bucket disposition, the dataset-450 note) are passed in as arguments rather
than hardcoded, so the sheet can be rebuilt once each finding is ready without touching
this script.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VERDICTS = REPO_ROOT / "ekw" / "svc-fp-verdicts-2026-09-11.json"
DEFAULT_OUT = REPO_ROOT / "ekw" / "svc-fp-screen-results-2026-09-11.xlsx"
DEFAULT_COVERAGE = REPO_ROOT / "ekw" / "svc-task-coverage-2026-09-11.json"

TASK_ID_PATTERN = re.compile(r"SVC-PC-(\d+)-(\d+)-0", re.IGNORECASE)


def normalize_task_id(raw_id: str) -> str | None:
    """Normalize a task id to SVC-PC-N-N-0, or None if it doesn't match any known convention."""
    match = TASK_ID_PATTERN.search(raw_id.upper())
    if not match:
        return None
    return f"SVC-PC-{match.group(1)}-{match.group(2)}-0"


def load_coverage(path: Path) -> dict:
    """Load the durable per-dataset task-coverage file and compute the real distinct-task union.

    Returns a dict: total (int), non_matching (list of raw ids that fit no known convention),
    per_dataset_task_count (dict). This is the reproducible replacement for a hand-typed number.
    """
    if not path.exists():
        return {"total": None, "non_matching": [], "per_dataset_task_count": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    datasets = data.get("datasets", {})
    all_normalized: set[str] = set()
    non_matching: list[str] = []
    per_dataset_task_count = {}
    for dataset_id, raw_ids in datasets.items():
        per_dataset_task_count[dataset_id] = len(raw_ids)
        for raw_id in raw_ids:
            normalized = normalize_task_id(raw_id)
            if normalized is None:
                non_matching.append(f"{dataset_id}/{raw_id}")
            else:
                all_normalized.add(normalized)
    return {
        "total": len(all_normalized),
        "non_matching": non_matching,
        "per_dataset_task_count": per_dataset_task_count,
        "dataset_count": len(datasets),
    }


COLUMNS = [
    "dataset",
    "task_id",
    "name",
    "verdict",
    "fp_class",
    "confidence",
    "evidence",
    "reasoning",
    "surviving_defect",
]
HEADER_LABELS = {
    "dataset": "Dataset",
    "task_id": "Task",
    "name": "Criterion",
    "verdict": "Verdict",
    "fp_class": "FP class",
    "confidence": "Confidence",
    "evidence": "Evidence",
    "reasoning": "Reasoning",
    "surviving_defect": "Surviving defect",
}
COLUMN_WIDTHS = {
    "dataset": 10,
    "task_id": 16,
    "name": 12,
    "verdict": 16,
    "fp_class": 14,
    "confidence": 12,
    "evidence": 55,
    "reasoning": 65,
    "surviving_defect": 40,
}
VERDICT_FILL = {
    "TRUE_POSITIVE": PatternFill("solid", fgColor="F8D7DA"),
    "FALSE_POSITIVE": PatternFill("solid", fgColor="D4EDDA"),
    "PARTIAL": PatternFill("solid", fgColor="FFF3CD"),
    "UNCERTAIN": PatternFill("solid", fgColor="E2E3E5"),
}
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="343A40")
WRAP_TOP = Alignment(wrap_text=True, vertical="top")


def load_verdicts(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = next(v for v in data.values() if isinstance(v, list))
    if len(data) == 0:
        raise ValueError(f"{path} parsed to zero findings")
    return data


def style_header(ws, labels: list[str]) -> None:
    ws.append(labels)
    for col in range(1, len(labels) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = WRAP_TOP
    ws.freeze_panes = "A2"


def write_finding_rows(ws, rows: list[dict]) -> None:
    verdict_col = COLUMNS.index("verdict") + 1
    for r, row in enumerate(rows, start=2):
        for c, key in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=r, column=c, value=row.get(key, ""))
            cell.alignment = WRAP_TOP
        fill = VERDICT_FILL.get(row.get("verdict"))
        if fill:
            ws.cell(row=r, column=verdict_col).fill = fill
    for i, key in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = COLUMN_WIDTHS[key]


def build_all_findings(wb, verdicts: list[dict]):
    ws = wb.active
    ws.title = "All findings"
    style_header(ws, [HEADER_LABELS[c] for c in COLUMNS])
    write_finding_rows(ws, verdicts)


def build_dataset_cluster(wb, verdicts: list[dict], dataset_id: str) -> int:
    rows = [
        v
        for v in verdicts
        if str(v.get("dataset")) == str(dataset_id)
        and v.get("verdict") == "FALSE_POSITIVE"
    ]
    ws = wb.create_sheet(f"Dataset {dataset_id} cluster")
    style_header(ws, [HEADER_LABELS[c] for c in COLUMNS])
    write_finding_rows(ws, rows)
    return len(rows)


def build_needs_review(wb, verdicts: list[dict]) -> int:
    rows = [v for v in verdicts if v.get("verdict") == "UNCERTAIN"]
    ws = wb.create_sheet("Needs review (UNCERTAIN)")
    style_header(ws, [HEADER_LABELS[c] for c in COLUMNS])
    write_finding_rows(ws, rows)
    return len(rows)


def build_true_positives_by_task(wb, verdicts: list[dict]) -> None:
    ws = wb.create_sheet("True positives by task")
    counts = Counter(
        (v.get("dataset"), v.get("task_id"))
        for v in verdicts
        if v.get("verdict") == "TRUE_POSITIVE"
    )
    style_header(ws, ["Dataset", "Task", "True-positive findings"])
    for r, ((dataset, task), n) in enumerate(
        sorted(counts.items(), key=lambda kv: -kv[1]), start=2
    ):
        ws.cell(row=r, column=1, value=dataset)
        ws.cell(row=r, column=2, value=task)
        ws.cell(row=r, column=3, value=n)
    for i, width in enumerate((10, 16, 20), start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def build_summary(
    wb, verdicts: list[dict], counts_609: int, args: argparse.Namespace, coverage: dict
):
    ws = wb.create_sheet("Summary", 0)
    total = len(verdicts)
    tally = Counter(v.get("verdict") for v in verdicts)
    n_dataset_task_pairs = len({(v.get("dataset"), v.get("task_id")) for v in verdicts})
    n_datasets_with_findings = len({v.get("dataset") for v in verdicts})

    if coverage["total"] is not None:
        non_matching_ids = {raw.split("/", 1)[1] for raw in coverage["non_matching"]}
        non_matching_with_findings = {
            v.get("task_id")
            for v in verdicts
            if str(v.get("task_id", "")).lower() in non_matching_ids
        }
        non_matching_finding_count = sum(
            1 for v in verdicts if str(v.get("task_id", "")).lower() in non_matching_ids
        )
        coverage_line = (
            f"{coverage['total']} distinct tasks across {coverage['dataset_count']} datasets "
            f"(with real review data, whether or not they have a finding) - computed by "
            f"normalizing every raw task id in ekw/svc-task-coverage-2026-09-11.json against the "
            f"SVC-PC-N-N-0 convention and deduplicating. {len(coverage['non_matching'])} raw ids "
            f"matched no known convention and are NOT folded into this count because their "
            f"identity relative to an SVC-PC-N-N-0 task isn't established - "
            f"{len(non_matching_with_findings)} of those {len(non_matching_ids)} ids "
            f"({non_matching_finding_count} findings) are real tasks under a 4th convention "
            f"(task_svc-pc-N-l2-NN, seen in dataset 519) that DOES appear in this workbook's "
            f"per-task delivery - they are excluded from the coverage number above, not from the "
            f"findings pool. See ekw/svc-task-coverage-2026-09-11.json for the full non-matching "
            f"id list. Separately, {n_dataset_task_pairs} (dataset, task) pairs and "
            f"{n_datasets_with_findings} datasets appear in the findings pool specifically (a task "
            f"can have zero findings and still count toward the coverage total above)."
        )
    else:
        coverage_line = (
            f"{n_dataset_task_pairs} (dataset, task) pairs across {n_datasets_with_findings} "
            f"datasets IN THE FINDINGS POOL ONLY - ekw/svc-task-coverage-2026-09-11.json was not "
            f"found, so the broader real-review-data coverage number could not be computed. This "
            f"is NOT a distinct-task count (a task in more than one dataset is counted per pair)."
        )

    rows = [
        ("SVC false-positive screen: results summary", ""),
        ("Generated", args.generated_date),
        ("", ""),
        ("Total findings screened", total),
        ("TRUE_POSITIVE", tally.get("TRUE_POSITIVE", 0)),
        ("FALSE_POSITIVE", tally.get("FALSE_POSITIVE", 0)),
        ("PARTIAL", tally.get("PARTIAL", 0)),
        ("UNCERTAIN", tally.get("UNCERTAIN", 0)),
        ("", ""),
        ("Coverage", coverage_line),
        ("", ""),
        (
            f"Dataset {args.cluster_dataset} false-positive cluster",
            f"{counts_609} of the {tally.get('FALSE_POSITIVE', 0)} false positives",
        ),
        ("Root cause", args.cluster_root_cause),
        ("", ""),
        ("Dataset 450 (QCR_SVC_20082026)", args.dataset_450_note),
        ("", ""),
        ("Datasets 849 / 934 / 519 diagnosis", args.timeout_diagnosis),
        ("", ""),
        ("UNCERTAIN bucket disposition", args.uncertain_disposition),
        ("", ""),
        ("Methodology", args.methodology),
    ]
    for r, (label, value) in enumerate(rows, start=1):
        lc = ws.cell(row=r, column=1, value=label)
        vc = ws.cell(row=r, column=2, value=value)
        lc.alignment = WRAP_TOP
        vc.alignment = WRAP_TOP
        if label and not value and label.isupper() is False and r > 3:
            lc.font = Font(bold=True)
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 90


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--verdicts", type=Path, default=DEFAULT_VERDICTS)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--cluster-dataset", default="609")
    p.add_argument(
        "--cluster-root-cause",
        default="(pending diagnosis)",
        help="One-paragraph, cited root cause for the cluster-dataset false-positive concentration.",
    )
    p.add_argument("--dataset-450-note", default="(pending)")
    p.add_argument("--timeout-diagnosis", default="(pending diagnosis)")
    p.add_argument("--uncertain-disposition", default="(pending)")
    p.add_argument(
        "--methodology",
        default=(
            'Comprehensive-review data pulled via DataOS "Download > Dataset with runs" '
            "export. Findings screened with Andrew Ma's fp_screen.py/fp_screen.md prompt, "
            "dispatched in parallel batches. Task ids normalized across three naming "
            "conventions (SVC-PC-N-N-0, cirrus-y1-task-svc-pc-N-N-0-l2-NN, task_SVC-PC-N-N-0)."
        ),
    )
    p.add_argument("--generated-date", default="2026-09-11")
    p.add_argument("--coverage-json", type=Path, default=DEFAULT_COVERAGE)
    args = p.parse_args()

    verdicts = load_verdicts(args.verdicts)
    coverage = load_coverage(args.coverage_json)

    wb = openpyxl.Workbook()
    build_all_findings(wb, verdicts)
    n_cluster = build_dataset_cluster(wb, verdicts, args.cluster_dataset)
    n_uncertain = build_needs_review(wb, verdicts)
    build_true_positives_by_task(wb, verdicts)
    build_summary(wb, verdicts, n_cluster, args, coverage)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out)

    tally = Counter(v.get("verdict") for v in verdicts)
    print(f"Wrote {args.out}")
    print(f"  {len(verdicts)} findings: {dict(tally)}")
    print(f"  dataset {args.cluster_dataset} FALSE_POSITIVE cluster: {n_cluster}")
    print(f"  UNCERTAIN needing review: {n_uncertain}")
    if coverage["total"] is not None:
        print(
            f"  coverage: {coverage['total']} distinct tasks across "
            f"{coverage['dataset_count']} datasets ({len(coverage['non_matching'])} "
            f"non-matching raw ids excluded)"
        )
    else:
        print(
            f"  coverage: {args.coverage_json} not found, coverage number not computed"
        )


if __name__ == "__main__":
    main()
