#!/usr/bin/env python3
"""
citation_unverifiable_scan.py - C1 addendum (b): a criterion that grades
citations, sources or provenance ("cites", "source", "traceable", "reconcile
to", "traces to", "provenance") while its judge group's files=[...] lists
only the graded deliverable(s) and no environment source file or source
manifest. The judge is handed nothing to verify the citation against: it can
only take the deliverable's own say-so, which is not what "traces to a
source" is supposed to mean.

Fix direction (DataOS C1, laptop, 2026-09-19): add the specific source
file(s) the criterion needs to files= (respecting the judge's 1 MiB
per-file cap and, for an oversized source, the *_judge_extract convention
established earlier in this corpus), or grade the deliverable's own
trace/source-register table instead of an external source. Never remove the
criterion.

READ-ONLY: only reads corpus judge.toml files and solution/files/ listings,
never modifies anything.

Output: CSV [task, judge_toml, criterion, weight, matched_phrase, files_in_scope, description]
Verdict: fail if any criterion in the task matched, else pass.

Usage:
    python3 citation_unverifiable_scan.py [--corpus-root PATH] [--out PATH] [--task NAME] [--verdict-out PATH]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import (
    DEFAULT_CORPUS_ROOT,
    DEFAULT_REPORTS_DIR,
    extract_filename_tokens,
    iter_deliverable_groups,
    list_tasks,
    write_csv,
)

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

CITATION_RE = re.compile(
    r"\b(cites?|cited|citation|traceable|traces?\s+to|reconciles?\s+to|provenance|sourced\s+from|"
    r"per\s+the\s+source|matches?\s+the\s+source|named\s+source)\b",
    re.IGNORECASE,
)

# A criterion checking the deliverable's OWN internal citation completeness/format ("each figure cites a
# section, not just a filename") is gradable from the deliverable alone - not a defect. The genuine defect
# is a criterion that points at a specific external record/ledger/source the judge cannot see. Require
# either (a) a real filename-shaped token in the description that is NOT already in files=, or (b) an
# explicit external-record noun (ledger, GL, trial balance, bank statement, source data/record) - a bare
# "cites"/"traceable" with no external pointer is too broad and mostly self-referential in this corpus
# (confirmed: dropped the flagged-task rate from 127/202 to a much smaller, evidence-backed set).
_EXTERNAL_RECORD_RE = re.compile(
    r"\b(ledger|general ledger|\bGL\b|trial balance|bank statement|source (?:data|record|file)|"
    r"underlying record|data[- ]room (?:file|record))\b",
    re.IGNORECASE,
)

FILES_RE = re.compile(r"^files\s*=\s*\[(.*?)\]", re.MULTILINE | re.DOTALL)


def _files_entries(judge_toml_text: str) -> list[str]:
    m = FILES_RE.search(judge_toml_text)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def scan_task(task_dir: Path) -> list[tuple[str, str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str, str]] = []
    solution_dir = task_dir / "solution" / "files"
    deliverable_basenames = set()
    if solution_dir.is_dir():
        deliverable_basenames = {p.name for p in solution_dir.rglob("*") if p.is_file()}
    if not deliverable_basenames:
        return rows

    for group_dir in iter_deliverable_groups(task_dir):
        jt = group_dir / "judge.toml"
        if not jt.is_file():
            continue
        text = jt.read_text(encoding="utf-8", errors="replace")
        entries = _files_entries(text)
        if not entries:
            continue
        basenames = [os.path.basename(e) for e in entries]
        # "only deliverables in scope": every listed file's basename is a solution/files/ deliverable,
        # and nothing under /tests/.../judge_inputs/ (a source extract/manifest) is present.
        only_deliverables = bool(basenames) and all(b in deliverable_basenames for b in basenames)
        has_judge_inputs_manifest = any("judge_inputs" in e for e in entries)
        if not only_deliverables or has_judge_inputs_manifest:
            continue
        try:
            d = tomllib.load(open(jt, "rb"))
        except Exception:
            continue
        rel = str(jt.relative_to(task_dir))
        for c in d.get("criterion", []) or []:
            desc = c.get("description") or ""
            m = CITATION_RE.search(desc)
            if not m:
                continue
            named_files = extract_filename_tokens(desc) - set(basenames)
            record_m = _EXTERNAL_RECORD_RE.search(desc)
            if not named_files and not record_m:
                continue  # self-referential citation check (grades the deliverable's own citation format), not this defect
            pointer = ", ".join(sorted(named_files)) if named_files else record_m.group(0)
            rows.append(
                (
                    task_dir.name,
                    rel,
                    str(c.get("name", "?")),
                    str(c.get("weight", "")),
                    m.group(0),
                    ", ".join(basenames),
                    f"[external pointer: {pointer}] {desc[:450]}",
                )
            )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "citation_unverifiable.csv")
    ap.add_argument("--task", type=str, default=None)
    ap.add_argument("--verdict-out", type=Path, default=None)
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple[str, str, str, str, str, str, str]] = []
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        try:
            all_rows.extend(scan_task(task_dir))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 25 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned", file=sys.stderr)

    n = write_csv(
        args.out,
        ["task", "judge_toml", "criterion", "weight", "matched_phrase", "files_in_scope", "description"],
        all_rows,
    )
    flagged_tasks = {r[0] for r in all_rows}
    print(f"citation_unverifiable_scan: {n} unverifiable-citation criteria across {len(tasks)} tasks, written to {args.out}")
    print(f"  {len(flagged_tasks)} tasks flagged")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = sorted((t.name, "fail" if t.name in flagged_tasks else "pass") for t in tasks)
        vn = write_csv(args.verdict_out, ["task_id", "citation_unverifiable_scan"], verdict_rows)
        print(f"citation_unverifiable_scan: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
