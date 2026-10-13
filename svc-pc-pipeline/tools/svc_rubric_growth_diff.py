#!/usr/bin/env python3
"""Flag criteria a rebuild ADDED or GREW versus the last-graded rubric (the delete-direction guard).

Why this exists
---------------
The v7 fix direction for a 1.4 over-enforcement rejection is DELETE / LOOSEN, never add: on a task
being fixed for grading more than the instruction asks, a NEW criterion or a newly-added FAIL clause
is the exact shape that becomes the next round's rejection. But a rebuild agent, told to delete, can
still silently re-introduce constraints while fixing other findings. A real case: SVC-PC-16-1-0's
rebuild closed all its named findings and then added three new over-enforcements (r026, r031b, r010)
that an adversarial reviewer had to catch by hand before a DataOS grade was spent. This makes that
catch mechanical: diff the current rubric against the baseline the task was last graded on.

It reports, per criterion name:
  ADDED   - present now, absent in the baseline (suspect on an over-enforcement fix; a genuine
            coverage addition is legitimate, so this is a flag to review, not proof of a defect)
  GREW    - same name, current description longer than the baseline's (a rebuild that ADDED text to a
            criterion, the opposite of loosening; the delta is where an added FAIL clause hides)
  REMOVED - present in the baseline, gone now (the intended direction; reported for completeness)

Advisory by default (exit 0). `--fail-on-growth` exits 2 when any criterion is ADDED or GREW, so the
gate or CI can block a rebuild that grew the rubric until a human signs off on each addition.

Baseline may be a built task package directory OR a DataOS `*_with_runs*.zip` (the graded return).

Usage
-----
    python svc_rubric_growth_diff.py --current <03_dataos_ready>/<task> --baseline <dir|with_runs.zip> [--task <id>] [--fail-on-growth]
"""

import argparse
import re
import sys
import zipfile
from pathlib import Path

_CRIT_RE = re.compile(
    r"\[\[\s*(?:criteria|criterion)\s*\]\](.*?)(?=\[\[\s*(?:criteria|criterion)\s*\]\]|\Z)",
    re.S,
)
_NAME_RE = re.compile(r"name\s*=\s*['\"]([^'\"]+)['\"]")
_DESC_RE = re.compile(r"(?:description|expected)\s*=\s*('''|\"\"\"|['\"])(.*?)\1", re.S)


def _criteria_from_text(toml_text: str) -> dict:
    out = {}
    for m in _CRIT_RE.finditer(toml_text):
        block = m.group(1)
        nm = _NAME_RE.search(block)
        if not nm:
            continue
        dm = _DESC_RE.search(block)
        out[nm.group(1)] = dm.group(2).strip() if dm else ""
    return out


def criteria_from_dir(task_dir: Path) -> dict:
    out = {}
    for j in sorted((task_dir / "tests").glob("deliverables*/judge.toml")):
        d = j.parent.name
        for name, desc in _criteria_from_text(
            j.read_text(encoding="utf-8", errors="replace")
        ).items():
            out["%s/%s" % (d, name)] = desc
    return out


def criteria_from_zip(zip_path: Path, task: str) -> dict:
    out = {}
    z = zipfile.ZipFile(zip_path)
    pat = re.compile(re.escape(task) + r"/.*tests/(deliverables[^/]*)/judge\.toml$")
    for n in z.namelist():
        m = pat.search(n)
        if not m:
            continue
        for name, desc in _criteria_from_text(
            z.read(n).decode("utf-8", "replace")
        ).items():
            out["%s/%s" % (m.group(1), name)] = desc
    return out


def diff_criteria(cur: dict, base: dict):
    """Return (added, grew, removed) sorted name lists. ADDED = in cur not base; GREW = same name,
    longer description in cur (a rebuild that added text); REMOVED = in base not cur."""
    added = sorted(k for k in cur if k not in base)
    removed = sorted(k for k in base if k not in cur)
    grew = sorted(k for k in cur if k in base and len(cur[k]) > len(base[k]))
    return added, grew, removed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--current",
        type=Path,
        required=True,
        help="current task package dir (root/<task>)",
    )
    ap.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="a task package dir OR a *_with_runs*.zip",
    )
    ap.add_argument(
        "--task",
        help="task id (needed when --baseline is a zip; else inferred from --current)",
    )
    ap.add_argument(
        "--fail-on-growth",
        action="store_true",
        help="exit 2 if any criterion is ADDED or GREW",
    )
    a = ap.parse_args()

    task = a.task or a.current.name
    cur = criteria_from_dir(a.current)
    if a.baseline.suffix == ".zip":
        base = criteria_from_zip(a.baseline, task)
    else:
        # baseline dir is either the task package itself (has tests/) or a parent holding <task>/
        base_dir = (
            a.baseline if (a.baseline / "tests").exists() else (a.baseline / task)
        )
        base = criteria_from_dir(base_dir)

    added, grew, removed = diff_criteria(cur, base)

    print("=== rubric growth: %s (current vs baseline) ===" % task)
    print("baseline criteria: %d   current criteria: %d" % (len(base), len(cur)))
    if not base:
        print(
            "WARNING: baseline had 0 criteria - check the --baseline path/task id; diff is meaningless."
        )
    for k in added:
        print(
            "  ADDED   %s  (absent in baseline; verify it is a real coverage need, not a new over-constraint)"
            % k
        )
    for k in grew:
        print(
            "  GREW    %s  (+%d chars vs baseline; inspect the added text for a new FAIL clause)"
            % (k, len(cur[k]) - len(base[k]))
        )
    for k in removed:
        print("  removed %s  (intended delete direction)" % k)
    if not added and not grew:
        print("  no criteria added or grown vs baseline (delete/loosen only)")

    if a.fail_on_growth and (added or grew):
        print(
            "\nFAIL: rubric grew (%d added, %d grew). Each addition needs sign-off; a fix for "
            "over-enforcement should shrink, not grow, the rubric."
            % (len(added), len(grew))
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
