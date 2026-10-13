#!/usr/bin/env python3
"""build_dataos_union.py - laptop coordinator, 2026-09-19 04:22Z: DataOS's own
answer key (the verify session's status.csv + majors.csv) as the reviewer,
for the 30 tasks where it still holds true on current bytes and nobody has
fed it to a fix round.

status.csv (task, reviewer, check, still_true, evidence, caught_by,
caught_severity, caught_check, fix_note) and majors.csv (task, reviewer,
check, check_name, evidence_status, claim, points_at, source_file) are
row-for-row positionally aligned (verified: all 186 data rows match on
(task, reviewer, check) at the same index; 8 keys repeat in each file so a
dict join would silently collapse distinct majors - positional zip is the
only safe join here).

One finding per still_true=yes row (no dedup across reviewers, same
philosophy as build_review_union.py): class = the DataOS check id,
description = the verify session's own `evidence` (why this is STILL a real
defect on current bytes), fix_direction = the verify session's `fix_note`
(empty for every still-true row observed - there IS no fix yet, that's the
whole point), evidence = the DataOS claim + points_at + check_name so the
fix-plan model sees what was originally alleged, criterion_ids parsed off
points_at's trailing "| criteria r1,r2,..." tag when present.

Usage:
    python3 build_dataos_union.py --task TASK \
        --status-csv status.csv --majors-csv majors.csv --out OUT.json
Exit 0 always (0 findings if the task has no still_true=yes rows, or the
task is entirely on the do-not-auto-fix list).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_review_union import extract_affected_files  # noqa: E402 - reuse the same heuristic

CRITERIA_SUFFIX_RE = re.compile(r"\|\s*criteria\s+([\w,]+)\s*$")

# Laptop coordinator, 2026-09-19 04:22Z: "verify flagged 36-5-0 check 1.7 ...
# as possibly by design: do not fix that one without asking." Hard-excluded
# here rather than left to fix_plan.md's own judgment - the instruction was
# explicit that a human decides this one, not the fix-plan model.
DO_NOT_AUTO_FIX = {("SVC-PC-36-5-0", "1.7")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--status-csv", type=Path, required=True)
    ap.add_argument("--majors-csv", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    status_rows = list(csv.DictReader(open(args.status_csv, encoding="utf-8", errors="replace")))
    major_rows = list(csv.DictReader(open(args.majors_csv, encoding="utf-8", errors="replace")))
    if len(status_rows) != len(major_rows):
        print(f"ERROR: {args.status_csv} has {len(status_rows)} rows, {args.majors_csv} has "
              f"{len(major_rows)} - not positionally aligned, refusing to guess a join", file=sys.stderr)
        return 2

    findings = []
    skipped_do_not_fix = []
    for i, (s, m) in enumerate(zip(status_rows, major_rows)):
        if s.get("task") != args.task:
            continue
        key = (s.get("task"), s.get("reviewer"), s.get("check"))
        mkey = (m.get("task"), m.get("reviewer"), m.get("check"))
        if key != mkey:
            print(f"WARN: row {i} status/majors key mismatch ({key} vs {mkey}), skipping", file=sys.stderr)
            continue
        if (s.get("still_true") or "").strip().lower() != "yes":
            continue

        check_id = s.get("check", "?")
        if (args.task, check_id) in DO_NOT_AUTO_FIX:
            skipped_do_not_fix.append(check_id)
            continue

        reviewer = s.get("reviewer", "?")
        claim = m.get("claim", "") or ""
        points_at = m.get("points_at", "") or ""
        check_name = m.get("check_name", "") or ""
        evidence_text = s.get("evidence", "") or ""
        fix_note = s.get("fix_note", "") or ""

        crit_ids: list[str] = []
        cm = CRITERIA_SUFFIX_RE.search(points_at)
        if cm:
            crit_ids = [c.strip() for c in cm.group(1).split(",") if c.strip()]

        reviewer_slug = re.sub(r"[^A-Za-z0-9]+", "-", reviewer).strip("-").lower()
        findings.append({
            "id": f"dataos-{reviewer_slug}-{check_id}-{i}",
            "class": check_id,
            "severity": "major",
            "criterion_ids": crit_ids,
            "affected_files": extract_affected_files(claim + "\n" + points_at + "\n" + evidence_text),
            "description": evidence_text,
            "evidence": (f"DataOS claim (reviewer={reviewer!r}, check={check_id} {check_name!r}): "
                         f"{claim} | points_at: {points_at}"),
            "fix_direction": fix_note,
        })

    out = {
        "task": args.task,
        "source": "DataOS answer-key verify session (status.csv + majors.csv), still_true=yes rows only",
        "findings": findings,
        "majors_present": bool(findings),
        "major_count": len(findings),
    }
    if skipped_do_not_fix:
        out["do_not_auto_fix_skipped"] = skipped_do_not_fix

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"[build_dataos_union] {args.task}: {len(findings)} still-true DataOS major(s), wrote {args.out}"
          + (f" (SKIPPED do-not-auto-fix: {skipped_do_not_fix})" if skipped_do_not_fix else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
