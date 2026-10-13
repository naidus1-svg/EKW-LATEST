#!/usr/bin/env python3
"""Run the 2026-09-17 QCR tracer gates without touching ``ekw_run_checks --all``.

Package gates (no evaluations needed):
  - accepted_alternative_compatibility_check.py
  - xlsx_extraction_budget_check.py
  - harbor_rubric_gate.py  (platform QC rubric: instruction form, extraneous files,
    schema block, deterministic assertions, judge guard, criterion trace)
  - reward_signal_gate.py  (expert reward-signal mechanisms: source-blind criteria,
    phrase/numeric pins, FAIL-clause contradictions, duplicate grading, uncached
    formulas, compound criteria, coverage ledger, judge samples)
  - layout_formula_advisory_check.py  (ADVISORY, never blocks: G1 sheet/cell_range pin under
    free tab naming, H1 formula floor at the golden's own count, H2 formula gate the prompt
    never asks for, I1 rewardkit formula criteria with no LibreOffice recalc step)

Post-run gates (need ``evaluations/`` and/or ``verifications/``):
  - oracle_reward_details_audit.py  (warn-only; includes F2 oracle reward < 1.0 / grammar too
    large and F3 verifier traceback / rewardkit exit 1 / timeout in ANY run)
  - comprehensive_review_evidence_gate.py

``--root`` may be a harbor task tree, a single revision directory, or a
``with_runs`` batch. Parallel work in ``ekw_run_checks.py`` is not required
to use this runner.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from accepted_alternative_compatibility_check import (  # noqa: E402
    check_task as check_alternatives,
)
from comprehensive_review_evidence_gate import (  # noqa: E402
    check_submission,
    discover_submissions,
)
from harbor_rubric_gate import check_task as check_harbor_rubric  # noqa: E402
from layout_formula_advisory_check import check_task as check_layout_formula  # noqa: E402
from oracle_reward_details_audit import check_task as check_oracle_details  # noqa: E402
from reward_signal_gate import check_task as check_reward_signal  # noqa: E402
from xlsx_extraction_budget_check import check_task as check_xlsx_budget  # noqa: E402


def discover_task_dirs(root: Path, task_ids: list[str] | None) -> list[Path]:
    root = root.resolve()
    if (root / "task_files").is_dir() or (root / "tests").is_dir():
        return [root]
    children = sorted(p for p in root.iterdir() if p.is_dir())
    if task_ids:
        wanted = set(task_ids)
        children = [p for p in children if p.name in wanted]
    return children


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--task", action="append", dest="task_ids")
    parser.add_argument("--evidence", type=Path, help="with_runs bundle for the uncached-formula run scan")
    args = parser.parse_args(argv)

    task_dirs = discover_task_dirs(args.root, args.task_ids)
    package_rows = []
    for path in task_dirs:
        package_rows.append(
            {
                "path": str(path),
                "accepted_alternative": check_alternatives(path),
                "xlsx_extraction_budget": check_xlsx_budget(path),
                "oracle_reward_details": check_oracle_details(path),
                "harbor_rubric": check_harbor_rubric(path),
                "reward_signal": check_reward_signal(path, args.evidence),
                # advisory only (status warn/pass/skip): deliberately NOT in the blocking tuple below
                "layout_formula_advisory": check_layout_formula(path),
            }
        )

    submissions = []
    try:
        submissions = [check_submission(p) for p in discover_submissions(args.root)]
    except Exception as exc:  # noqa: BLE001
        submissions = [{"status": "error", "evidence": str(exc)}]

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "root": str(args.root.resolve()),
        "n_tasks": len(package_rows),
        "n_submissions": len(submissions),
        "tasks": package_rows,
        "evidence_gate": submissions,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {args.out} ({len(package_rows)} task(s), {len(submissions)} submission(s))")
    blocking = any(
        row[name].get("status") == "fail"
        for row in package_rows
        for name in ("accepted_alternative", "xlsx_extraction_budget", "oracle_reward_details", "harbor_rubric", "reward_signal")
    ) or any(row.get("status") == "fail" for row in submissions)
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
