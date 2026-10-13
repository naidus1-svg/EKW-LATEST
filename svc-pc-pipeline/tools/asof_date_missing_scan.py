#!/usr/bin/env python3
"""
asof_date_missing_scan.py - C1 addendum (c): instruction.md uses "today",
"current", "now" or "as of" without stating a scenario date, while the
task's own environment sources carry real dates (this is a FY2021/FY2022
corpus; every environment tree has dated files). A solver has no fixed
"today" to compute against (an ambiguous "as of" produces a different
correct answer depending on when it's read), and the golden was necessarily
built against ONE specific date - the instruction just never says which.

Fix direction (DataOS C1, laptop, 2026-09-19): state the scenario date in
instruction.md (and tests/task_prompt.txt, kept byte-identical to it per
this corpus's convention), consistent with the date the golden was actually
built against. Never leave the ambiguity and change the golden or the
criteria to match a guess.

READ-ONLY: only reads corpus instruction.md and environment file names/text,
never modifies anything.

Output: CSV [task, phrase, sentence, source_date_evidence]
Verdict: fail if any bare today/current/now/as-of phrase is found (and the
task's sources do carry a real date, so the ambiguity is a genuine defect,
not a dateless scenario), else pass.

Usage:
    python3 asof_date_missing_scan.py [--corpus-root PATH] [--out PATH] [--task NAME] [--verdict-out PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_CORPUS_ROOT, DEFAULT_REPORTS_DIR, list_tasks, write_csv

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

# A bare temporal-deixis word/phrase with no adjacent explicit date is the defect.
# The explicit-date guard below (has an adjacent YYYY / Month YYYY / MM/DD/YYYY token
# within the same sentence) is what keeps "as of December 31, 2021" from firing.
_DEIXIS_RE = re.compile(r"\b(today|as of now|right now)\b", re.IGNORECASE)
_ASOF_RE = re.compile(r"\bas of\b", re.IGNORECASE)
# "current"/"currently" alone is ordinary business-content phrasing in this corpus ("the current DTC
# price", "current pipeline by stage") and not itself evidence of an unstated scenario date; dropped.

_EXPLICIT_DATE_RE = re.compile(
    r"\b(19|20)\d{2}\b|"
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b|"
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|"
    r"\bQ[1-4]\b|"
    r"\bFY\s?\d{2,4}\b",
    re.IGNORECASE,
)

_SOURCE_DATE_RE = re.compile(r"(19|20)\d{2}")


def _sources_carry_dates(task_dir: Path) -> str:
    """Cheap evidence that this task's sources ARE dated (filenames or a quick content sniff),
    so a bare today/current/as-of really is an unresolved ambiguity, not a genuinely dateless task."""
    env = task_dir / "environment"
    if not env.is_dir():
        return ""
    hits = []
    for p in env.rglob("*"):
        if not p.is_file():
            continue
        if _SOURCE_DATE_RE.search(p.name):
            hits.append(p.name)
            if len(hits) >= 3:
                break
    return ", ".join(hits)


def scan_task(task_dir: Path) -> list[tuple[str, str, str, str]]:
    instr = task_dir / "instruction.md"
    if not instr.is_file():
        return []
    text = instr.read_text(encoding="utf-8", errors="replace")
    rows: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for pat in (_DEIXIS_RE, _ASOF_RE):
            m = pat.search(sentence)
            if not m:
                continue
            if _EXPLICIT_DATE_RE.search(sentence):
                continue  # the sentence already names a date next to the deictic phrase
            key = (m.group(0).lower(), sentence)
            if key in seen:
                continue
            seen.add(key)
            rows.append((task_dir.name, m.group(0), sentence[:400], ""))
    if not rows:
        return []
    evidence = _sources_carry_dates(task_dir)
    if not evidence:
        return []  # no corroborating dated sources found: don't flag a genuinely dateless task
    return [(t, p, s, evidence) for (t, p, s, _) in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "asof_date_missing.csv")
    ap.add_argument("--task", type=str, default=None)
    ap.add_argument("--verdict-out", type=Path, default=None)
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple[str, str, str, str]] = []
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        try:
            all_rows.extend(scan_task(task_dir))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 25 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned", file=sys.stderr)

    n = write_csv(args.out, ["task", "phrase", "sentence", "source_date_evidence"], all_rows)
    flagged_tasks = {r[0] for r in all_rows}
    print(f"asof_date_missing_scan: {n} unstated-date phrases across {len(tasks)} tasks, written to {args.out}")
    print(f"  {len(flagged_tasks)} tasks flagged")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = sorted((t.name, "fail" if t.name in flagged_tasks else "pass") for t in tasks)
        vn = write_csv(args.verdict_out, ["task_id", "asof_date_missing_scan"], verdict_rows)
        print(f"asof_date_missing_scan: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
