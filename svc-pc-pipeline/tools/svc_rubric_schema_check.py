#!/usr/bin/env python3
"""Rubric schema check: validate the judge.toml rubric files in a built Harbor task package.

Why this exists: nothing else in a typical build pipeline re-verifies a task's rubric files
AFTER the task is built. A schema or weight defect introduced upstream (a converter mapping the
wrong source column, a chunker splitting a rubric across files inconsistently) can ship
completely silently if nothing re-checks the built package itself.

Copied into turing-context on 2026-09-14 from harbor-qc-checks/rubric_schema_check.py.
See tools/svc_qc_tracker_build.py CHECK_META["D"]["subchecks"]["D2"]. No logic changed.

What it asserts, per task directory under a package root:

  1. At least one `tests/deliverables_*/judge.toml` exists.
  2. Every `[[criterion]]` carries a non-blank `description`.
  3. No description is a bare tier stub. This is a real converter defect seen in the source
     project: a rubric whose column header read "Criterion Type" had that column claimed for the
     description slot before the real "Requirement" column was reached, so the judge saw
     "Judgment Expected: <value>" with no requirement sentence at all. It shipped across many
     criteria, on multiple tasks, and was scored on as-is before this check existed.
  4. No description has a placeholder "Expected:" value. Distinct from #3: the requirement
     sentence IS present and reads like a real criterion, but the "Expected:" slot right after it
     was never populated -- "Expected: .", "Expected: ..", or a bare "Expected:" with nothing
     after. The requirement text made it through the converter; the expected value did not, so
     the grader has a sentence to judge against but no value to check it against.
  5. Each file's own `[judge].weight` equals the sum of its own criteria weights.
  6. The task's weights across all its judge files sum to 1.0.

Exit 0 clean, 1 findings, 2 bad usage. Stdlib only (needs Python 3.11+ for tomllib).

    python rubric_schema_check.py <package_root> [--task TASK-ID] [--json out.json]

Provenance: extracted and generalized from a QC pipeline built for one benchmark (SVC-PC /
Cirrus Sleep). The validation logic below is unchanged from the source version -- per an earlier
audit it already made no benchmark-specific assumption beyond the generic
`tests/deliverables*/judge.toml` + `[[criterion]]` package shape, the same shape
`formula_health_check.py` in this repo expects. Only the docstring, comments, and CLI help text
were reworded here to drop the source project's benchmark name and example task/path IDs.

Status: v1, ported as-is. The validation logic has been run at real scale against built packages
in its source project; this generalized copy has only been smoke-tested (`--help`, and a run
against a small sample package) since the rename, not yet run at scale under this name.
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

# A real requirement sentence whose "Expected:" value slot is itself empty: the label is
# there, but nothing describing a value -- no digit, no $, no %, no word -- sits between the
# colon and the next sentence boundary. Seen in the wild as "Expected: .", "Expected: ..",
# and a bare "Expected:" with nothing after (optionally followed by unrelated fixed
# boilerplate like "This is a must-pass criterion." that carries no value either). Matching
# with `search`, not `match`: unlike the bare-tier stub this can sit anywhere in the
# description, most often right after a real requirement sentence.
#
# The alternation matters: `\.{1,2}(?:\s|$)` requires an actual period (one or two) before
# the boundary, and the bare `$` alternative only fires with nothing at all after the colon
# (true end of string). A single `\.{0,2}(?:\s|$)` looks equivalent but is not -- `{0,2}`
# lets the period count go to zero, so the whole thing degenerates to "colon then any one
# whitespace character," which is satisfied by every real "Expected: <value>" too and
# flags nearly the entire corpus. The `\s*` right after the colon must fail to reach a
# period or the string's end when real content -- a digit, $, %, a word -- sits there, and
# that failure is what keeps this off multi-clause descriptions like "Expected: $1,204,900
# (exact, $0 variance).." where a value comes first.
PLACEHOLDER_EXPECTED_RE = re.compile(r"\bexpected\s*:\s*(?:\.{1,2}(?:\s|$)|$)", re.I)

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
        "placeholder_expected": [],
        "file_weight_mismatch": [],
        "parse_errors": [],
        "ok": False,
    }

    # Both layouts are real and in use. Multi-deliverable tasks chunk into
    # tests/deliverables_01..NN/; single-deliverable tasks write a bare
    # tests/deliverables/. Globbing only the numbered form reports 0 criteria on a
    # perfectly good package, which is the same shape of bug as a weight check that
    # keyed off a single expected tab name and silently skipped rubrics that had none.
    # A check that only sees one layout is not a check.
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
            elif PLACEHOLDER_EXPECTED_RE.search(desc):
                res["placeholder_expected"].append(where)

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
        and not res["placeholder_expected"]
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
        "root",
        help="a directory containing one subdirectory per task, or a single task directory",
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
        for w in r["placeholder_expected"]:
            print(f'       expected value missing (placeholder "Expected:"): {w}')
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
