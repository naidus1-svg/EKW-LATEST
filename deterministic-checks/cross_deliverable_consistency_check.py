#!/usr/bin/env python3
"""Cross-deliverable consistency check: for a task with 2+ deliverable files, does EVERY
single criterion source only one of them -- meaning nothing in the rubric ever cross-checks
that the deliverables agree with each other?

Why this exists. A 2026-09-17 verification pass across 54 real EKW tasks' Comprehensive
Review findings confirmed a recurring true-positive defect pattern, distinct from anything an
existing check catches: task_78, task_100, task_130 (each a memo + a workbook, or a memo + a
deck) have a rubric where EVERY criterion's own `source` config names exactly one deliverable
file, and none of them ever grades whether the two deliverables' stated conclusions actually
agree. A response that states "BUY" in the memo and models "AVOID" in the workbook's own
number could pass every single criterion, because no criterion ever opens both files at once
to compare them.

Confirmed NOT the same question judge_file_scope_breadth_check.py answers (read its full
source, not just its docstring, before concluding this): that script asks whether the judge's
configured file scope excludes SOURCE material the prompt tells the solver to ground in
(named-filename-in-instruction.md vs judge/verifier file scope). It has no concept of "this
task has N>=2 of its OWN deliverables and no criterion reads more than one of them" -- running
it directly against task_78/task_100/task_130 confirms this: all three come back clean (0
findings), because none of them name an external corpus source file in instruction.md at all
-- the gap this check closes is entirely different and orthogonal.

What this check reads, per task:
    - EKW: tests/verifier.json via ekw_verifier_json.load_ekw_criteria() (already dual-format-
      shared with judge_file_scope_breadth_check.py and extraction_groundedness_check.py) --
      each criterion's own `files` list (every path in its `source`, already flattened across
      all 7 real shapes _extract_file_paths() handles).
    - SVC-PC: tests/deliverables*/judge.toml, parsed directly via tomllib (same reason
      judge_file_scope_breadth_check.py re-parses directly rather than reusing
      rubric_text_lint.load_judge_files: this check needs each judge GROUP's own files=[...]
      scope, which that shared loader does not carry through). SVC-PC has no per-criterion
      file scoping -- a judge group's files=[...] applies to every criterion in that group --
      so the per-criterion signal EKW gets natively is approximated at the group level: a
      group whose OWN files=[...] already lists 2+ of the task's deliverables is the SVC-PC
      equivalent of an EKW criterion citing >1 file.

Deliverable-file identification: a "deliverable" is any file path a criterion's own source
config names (EKW: source.file...path; SVC-PC: a judge group's files=[...]) that is NOT itself
graded input from environment/ or solution/ -- in practice, every real path seen in this
corpus's confirmed-affected tasks is an `output/...` path (the solver's own produced file), so
this check treats the UNION of all distinct file paths named across every criterion/group as
the task's deliverable set, without trying to separately classify "graded output" vs "source
material" (that classification is deliverable_filename_check.py's and
judge_file_scope_breadth_check.py's territory respectively, not reinvented here).

Static proxy chosen, and why (documented per the commissioning brief's own instruction to pick
one and explain the reasoning): "does any single criterion's own source reference 2+ files" is
used as the primary signal, NOT "does any pair of criteria cross-reference matching content
between two files" -- the latter would require semantic content comparison (an LLM-judge-shaped
task, exactly what this whole check exists to AVOID needing), whereas the former is a pure
structural fact readable straight from the rubric's own file-scope config with zero ambiguity.
A task where every criterion's source config touches only one file, despite the task itself
producing 2+ deliverables, is a purely mechanical, zero-false-positive signal that literally no
criterion CAN cross-check consistency between them -- it is a necessary (not sufficient)
condition for the defect, exactly parallel to how compound_criterion_check.py's clause-count
proxy is a necessary-not-sufficient signal for judge brittleness. A task that DOES have >=1
multi-file criterion is not proven to genuinely cross-check consistency (the criterion could
open both files for an unrelated reason) -- that residual is disclosed below, not swept under
a false "pass".

Classification per task:
    "warn"  -- 2+ distinct deliverable files are named across this task's own criteria/groups,
              AND every single criterion/group sources only one of them. Warn, not fail: this
              is a rubric-authoring gap the same tier as the sprint's own systemic findings
              (compound_criterion, judge_panel_size) -- a real coverage hole, not a per-task
              content defect an individual author introduced by mistake.
    "pass"  -- 2+ deliverables exist and at least one criterion/group's own source already
              spans 2+ of them (the necessary condition for a real cross-check is at least
              present; see Known limits for why this is not proof one truly happens).
    "skip"  -- fewer than 2 distinct deliverable files named across the task's criteria (a
              single-deliverable task has nothing to cross-check by construction).
    "error" -- verifier.json / judge.toml exists but could not be parsed.

Exit code: 0 always (same warn-tier convention as judge_file_scope_breadth_check.py's own
`possible_judge_scope_excludes_named_sources` and every other non-hard-gating check in this
folder -- this is a disclosure for human/authoring review, not a check that fails a task on
its own say-so).

Known limits, disclosed rather than silently dropped:
    - This is a STRUCTURAL proxy (file-scope breadth per criterion), not a semantic one. A
      "pass" here (some criterion's source spans 2+ files) does NOT prove that criterion
      actually grades cross-file agreement -- it could open both files for an unrelated
      reason (e.g. reading a shared template alongside the main deliverable). This check
      cannot tell those apart without reading the criterion's own rubric prompt text, which
      is a judgment call, not a mechanical fact -- same disclosed asymmetry
      judge_file_scope_breadth_check.py's own docstring accepts for its "possible" finding.
    - Only sees deliverables that are actually NAMED in a criterion's own source/files config.
      A task with 2 deliverables where NEITHER is ever named anywhere in the rubric (both
      graded by, say, a directory-listing command) reports "skip", not "warn" -- a different,
      not-yet-covered gap.
    - Does not attempt content extraction or comparison itself. It answers "can any single
      criterion even see both deliverables at once," not "do the deliverables actually agree."

Usage (same CLI shape as compound_criterion_check.py / judge_file_scope_breadth_check.py --
style="rubric_schema" in ekw_run_checks.py's registry):
    python cross_deliverable_consistency_check.py <package_root> [--task TASK-ID] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from ekw_verifier_json import has_ekw_config, load_ekw_criteria


def _basename(p) -> str:
    return Path(str(p).replace("\\", "/")).name.lower()


# ---------------------------------------------------------------------------
# SVC-PC: judge.toml groups, parsed directly (files-scope preserving, same reason
# judge_file_scope_breadth_check.py re-parses rather than reusing rubric_text_lint's loader)
# ---------------------------------------------------------------------------


def _load_svc_pc_groups(task_dir: Path):
    """Every tests/deliverables*/judge.toml under a task dir. Returns a list of
    {path, files, n_criteria, parse_error}."""
    out = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return out
    for jt in sorted(tests_dir.glob("deliverables*/judge.toml")):
        rel = str(jt.relative_to(task_dir)).replace("\\", "/")
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 -- one bad file must not kill the batch
            out.append({"path": rel, "files": [], "n_criteria": 0, "parse_error": str(e)})
            continue
        judge = data.get("judge") or {}
        files = judge.get("files") or []
        n_criteria = len(data.get("criterion") or [])
        out.append({"path": rel, "files": files, "n_criteria": n_criteria, "parse_error": None})
    return out


def _has_svc_pc_config(task_dir: Path) -> bool:
    tests_dir = task_dir / "tests"
    return tests_dir.is_dir() and any(tests_dir.glob("deliverables*/judge.toml"))


# ---------------------------------------------------------------------------
# shared analysis: a list of "scopes", each {label, files, n_criteria}, one per EKW criterion
# or one per SVC-PC judge group -- the unit that either does or doesn't span 2+ deliverables
# ---------------------------------------------------------------------------


def _base_result(task_dir: Path, fmt: str) -> dict:
    return {
        "task": task_dir.name,
        "format": fmt,
        "deliverable_files": [],
        "n_scopes_checked": 0,
        "multi_file_scopes": [],
        "status": None,
        "parse_errors": [],
    }


def _analyze_scopes(res: dict, scopes: list[dict]) -> None:
    all_files: set[str] = set()
    for s in scopes:
        all_files |= {_basename(f) for f in s["files"] if f}
    res["deliverable_files"] = sorted(all_files)
    res["n_scopes_checked"] = len(scopes)

    if len(all_files) < 2:
        res["status"] = "skip"
        return

    multi = [s for s in scopes if len({_basename(f) for f in s["files"] if f}) >= 2]
    res["multi_file_scopes"] = [
        {"scope": s["label"], "files": sorted({_basename(f) for f in s["files"] if f})}
        for s in multi
    ]
    res["status"] = "pass" if multi else "warn"


def check_task_ekw(task_dir: Path) -> dict:
    res = _base_result(task_dir, "ekw")
    criteria = load_ekw_criteria(task_dir)
    parse_error_entries = [c for c in criteria if c["name"] == "__parse_error__"]
    if parse_error_entries:
        res["parse_errors"].extend(c["description"] for c in parse_error_entries)
        res["status"] = "error"
        return res
    if not criteria:
        res["parse_errors"].append("tests/verifier.json has zero verifiers")
        res["status"] = "error"
        return res

    scopes = [
        {"label": f"{c['group']}/{c['name']}", "files": c.get("files") or []}
        for c in criteria
    ]
    _analyze_scopes(res, scopes)
    return res


def check_task_svc_pc(task_dir: Path) -> dict:
    res = _base_result(task_dir, "svc_pc")
    groups = _load_svc_pc_groups(task_dir)
    if not groups:
        res["parse_errors"].append("no tests/deliverables*/judge.toml found for this task")
        res["status"] = "error"
        return res

    parse_errors = [g for g in groups if g["parse_error"]]
    if parse_errors:
        for g in parse_errors:
            res["parse_errors"].append(f"{g['path']}: judge.toml failed to parse: {g['parse_error']}")
    usable = [g for g in groups if not g["parse_error"]]
    if not usable:
        res["status"] = "error"
        return res

    scopes = [{"label": g["path"], "files": g["files"]} for g in usable]
    _analyze_scopes(res, scopes)
    return res


def check_task_dispatch(task_dir: Path) -> dict:
    """SVC-PC's judge.toml takes precedence whenever present, matching every other dual-format
    check in this folder (compound_criterion_check.py, judge_file_scope_breadth_check.py)."""
    if _has_svc_pc_config(task_dir):
        return check_task_svc_pc(task_dir)
    if has_ekw_config(task_dir):
        return check_task_ekw(task_dir)
    res = _base_result(task_dir, "unknown")
    res["parse_errors"].append(
        "no tests/deliverables*/judge.toml or tests/verifier.json found"
    )
    res["status"] = "error"
    return res


# ---------------------------------------------------------------------------
# CLI -- same shape as compound_criterion_check.py / judge_file_scope_breadth_check.py
# ---------------------------------------------------------------------------


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

    results = [check_task_dispatch(d) for d in task_dirs]

    for r in results:
        flag = {"warn": "WARN", "pass": "OK  ", "skip": "SKIP", "error": "FAIL"}.get(
            r["status"], "????"
        )
        print(
            f"{flag} {r['task']:<20} [{r['format']:<6}] "
            f"{len(r['deliverable_files']):>2} deliverable file(s)  "
            f"{r['n_scopes_checked']:>3} scope(s) checked  "
            f"{len(r['multi_file_scopes']):>2} multi-file scope(s)"
        )
        for w in r["parse_errors"]:
            print(f"       parse: {w}")
        if r["status"] == "warn":
            print(
                f"       NO_CROSS_CHECK: deliverables {r['deliverable_files']} -- every "
                "single criterion/group sources exactly one of them; nothing in this "
                "rubric can ever compare the two deliverables against each other."
            )

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    print(
        f"\n{len(results)} task(s) checked  |  status counts: "
        + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    )
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 1 if counts.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
