#!/usr/bin/env python3
"""Post-build check for a built SVC-PC package.

The gap this fills: nothing in the pipeline verifies a task AFTER it is built.
`gdpval_qc/tools/check_rubric.py` looks like the tool for this and is not; it targets
the other SVC front's `tests/rubric.json`, and SVC-PC packages carry
`tests/deliverables_NN/judge.toml` instead. Running it here is a type mismatch.

What it asserts, per task directory under an `03_dataos_ready` root:

  1. At least one `tests/deliverables_*/judge.toml` exists.
  2. Every `[[criterion]]` carries a non-blank `description`.
  3. No description is a bare tier stub. That is the 2026-08-29 converter defect:
     a rubric whose column header reads "Criterion Type" had that column claimed for
     the description slot before the real "Requirement" column was reached, so the
     judge saw "Judgment Expected: <value>" with no requirement sentence. 151 criteria
     across six tasks shipped that way and were scored on it.
  4. Each file's own `[judge].weight` equals the sum of its own criteria weights.
  5. The task's weights across all its judge files sum to 1.0.

Exit 0 clean, 1 findings, 2 bad usage. Stdlib only.

    python tools/svc_verify_package.py <03_dataos_ready_root> [--task SVC-PC-1-3-0] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.stderr.write("needs Python 3.11+ for tomllib\n")
    raise SystemExit(2)

# A description that opens with a tier word and goes straight to "Expected:" never
# reached its Requirement column. Matching on the opening is deliberate: a legitimate
# description may well contain the word "Expected:" later on.
BARE_TIER_RE = re.compile(
    r"^\s*(judgment|objective|structural|binary)\s+expected\s*:", re.I
)

WEIGHT_TOL = 0.001


def check_task(task_dir: Path) -> dict:
    """One task. Returns a result dict; never raises on a malformed package."""
    res = {
        "task": task_dir.name,
        "judge_files": 0,
        "criteria": 0,
        "weight_sum": 0.0,
        "blank_desc": [],
        "bare_tier": [],
        "file_weight_mismatch": [],
        "parse_errors": [],
        "ok": False,
    }

    # Both layouts are real and in use. Multi-deliverable tasks chunk into
    # tests/deliverables_01..NN/; single-deliverable tasks write a bare
    # tests/deliverables/. Globbing only the numbered form reports 0 criteria on a
    # perfectly good package, which is the same shape of bug as the 2026-08-29
    # weight check that keyed off a Category Weights tab and silently skipped the two
    # rubrics that had none. A check that only sees one layout is not a check.
    judge_files = sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )
    if not judge_files:
        res["parse_errors"].append(
            "no judge.toml under tests/deliverables/ or tests/deliverables_*/"
        )
        return res
    res["judge_files"] = len(judge_files)

    total = 0.0
    for jf in judge_files:
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception as exc:
            res["parse_errors"].append(f"{jf.name}: {exc}")
            continue

        crits = data.get("criterion") or []
        declared = (data.get("judge") or {}).get("weight")
        subtotal = 0.0

        for c in crits:
            res["criteria"] += 1
            name = c.get("name", "?")
            desc = (c.get("description") or "").strip()
            w = c.get("weight")
            if isinstance(w, (int, float)):
                subtotal += float(w)
            where = f"{jf.parent.name}/{name}"
            if not desc:
                res["blank_desc"].append(where)
            elif BARE_TIER_RE.match(desc):
                res["bare_tier"].append(where)

        total += subtotal
        # The file's own declared weight should equal what its criteria actually add to.
        # A drift here means the chunker and the criteria disagree, which the task-level
        # sum can mask when two files drift in opposite directions.
        if isinstance(declared, (int, float)):
            if abs(float(declared) - subtotal) > WEIGHT_TOL:
                res["file_weight_mismatch"].append(
                    {
                        "file": jf.parent.name,
                        "declared": round(float(declared), 6),
                        "criteria_sum": round(subtotal, 6),
                    }
                )

    res["weight_sum"] = round(total, 6)
    res["ok"] = (
        not res["blank_desc"]
        and not res["bare_tier"]
        and not res["file_weight_mismatch"]
        and not res["parse_errors"]
        and abs(total - 1.0) <= WEIGHT_TOL
    )
    return res


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "root", help="an 03_dataos_ready directory, or a single task directory"
    )
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        help="limit to these task ids (repeatable)",
    )
    ap.add_argument("--json", help="also write the full result set here")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2

    # Accept either a root of task dirs or one task dir directly.
    if (root / "tests").is_dir():
        task_dirs = [root]
    else:
        task_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.task:
        want = set(args.task)
        task_dirs = [d for d in task_dirs if d.name in want]
    if not task_dirs:
        sys.stderr.write(f"no task directories matched under {root}\n")
        return 2

    results = [check_task(d) for d in task_dirs]

    bad = [r for r in results if not r["ok"]]
    for r in results:
        flag = "OK  " if r["ok"] else "FAIL"
        print(
            f"{flag} {r['task']:<18} {r['criteria']:>4} criteria  "
            f"{r['judge_files']:>2} files  weight_sum={r['weight_sum']}"
        )
        for w in r["parse_errors"]:
            print(f"       parse: {w}")
        for w in r["blank_desc"]:
            print(f"       blank description: {w}")
        for w in r["bare_tier"]:
            print(f"       requirement text missing (bare tier stub): {w}")
        for m in r["file_weight_mismatch"]:
            print(
                f"       file weight mismatch: {m['file']} declares {m['declared']}, "
                f"criteria add to {m['criteria_sum']}"
            )
        if (
            not r["ok"]
            and abs(r["weight_sum"] - 1.0) > WEIGHT_TOL
            and not r["parse_errors"]
        ):
            print(f"       task weight sum {r['weight_sum']} is not 1.0")

    print(f"\n{len(results) - len(bad)}/{len(results)} clean")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
