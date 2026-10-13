#!/usr/bin/env python3
"""Refuse to ship a rebuilt SVC-PC package that silently regressed.

The gap this fills: nothing in the pipeline compares a freshly built package
against the last version that was actually confirmed good before it ships to
Data-OS or Data Hub. Four independent rebuilds hit this exact failure shape on
2026-09-10/11, each one reintroducing a defect that had already been fixed:

  - SVC-PC-3-7-0's rebuild read an older cached copy of Amit Payan's rubric, so
    his already-landed fix (three deliverables, not two) never reached the
    graded package.
  - A fresh Drive-to-Data-Hub conversion of 12 tasks reintroduced a failing
    criterion on SVC-PC-1-6-0 (c17) and SVC-PC-24-5-0, both clean on an
    2026-08-28 build (Data-OS dataset 586, oracle batch #2152, 24/24 passed).
  - A "Final L2 folders" rebuild of the 30-task published set (2026-09-08)
    came out with 9 tasks failing oracle that were not known-broken before.
  - The first rebuild of the "10 pulled" tasks (dataset 829) silently dropped
    .csv/.json goldens because the extension whitelist did not carry them;
    fixed only in a second pass (dataset 833).

Every one of these was invisible to a check that only inspects the NEW
package in isolation, because the new package is internally well-formed - it
just quietly differs from the version someone already verified. This script
makes that difference visible before the package ships anywhere.

What it compares, per task directory present in BOTH the candidate root and
the reference root:

  1. Every judge.toml criterion, by (deliverable group, criterion name):
     description text, weight, and expected value if the schema carries one.
     A changed description or weight is reported even if the file's own
     weight-sum still validates - see svc_verify_package.py for that check;
     this one is about DRIFT from a prior good state, not internal
     consistency of the new state alone.
  2. Every file under solution/ and tests/: sha256 content hash. A byte-for-
     byte identical rename is not flagged (see the SVC-PC-2-2-0 case: a
     rename is a real fix that no byte-diff can see, and is out of scope for
     this tool by design).
  3. The count of files under environment/initial_workspace/. A corpus that
     shrank is exactly the "1,008 input files across 8 tasks" failure mode
     from rebuilding off 03_dataos_ready instead of overlaying the shipped
     package - see svc_stage_upload.py's own docstring caveat.

A task present in only one root is reported, not silently skipped: MISSING
IN CANDIDATE means something that used to ship no longer would; MISSING IN
REFERENCE means there is nothing to check this task's rebuild against, which
is worth knowing on its own.

Any difference not named in --allow-change is a FAIL. This is a refusal
gate, not a report: a clean exit means "nothing changed that wasn't supposed
to," not "the package looks fine in isolation."

Exit 0 clean (or every diff allow-listed), 1 unexplained diff or a missing
counterpart, 2 bad usage. Stdlib only.

    python tools/svc_diff_before_ship.py <candidate_root> <reference_root> \\
        [--task SVC-PC-1-3-0] [--allow-change SVC-PC-3-7-0:criterion:c07] \\
        [--json out.json]

--allow-change takes "<task_id>:<kind>:<name>" where kind is one of
criterion, file, corpus-count. Repeatable. Use it to record a deliberate,
reviewed edit - never to silence a diff you have not looked at.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.stderr.write("needs Python 3.11+ for tomllib\n")
    raise SystemExit(2)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_criteria(task_dir: Path) -> dict[tuple[str, str], dict]:
    """Every criterion, keyed by (deliverable group dir name, criterion name)."""
    out: dict[tuple[str, str], dict] = {}
    judge_files = sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )
    for jf in judge_files:
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue  # svc_verify_package.py is the tool for parse errors
        group = jf.parent.name
        for c in data.get("criterion") or []:
            name = c.get("name", "?")
            out[(group, name)] = {
                "description": (c.get("description") or "").strip(),
                "weight": c.get("weight"),
                "expected": c.get("expected"),
            }
    return out


def _hash_tree(root: Path, *subdirs: str) -> dict[str, str]:
    """relative-path -> sha256, for every file under any of the given subdirs."""
    out: dict[str, str] = {}
    for sub in subdirs:
        base = root / sub
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if f.is_file():
                out[f.relative_to(root).as_posix()] = _sha256(f)
    return out


def _corpus_count(task_dir: Path) -> int:
    base = task_dir / "environment" / "initial_workspace"
    if not base.is_dir():
        return 0
    return sum(1 for f in base.rglob("*") if f.is_file())


def diff_task(
    candidate_dir: Path, reference_dir: Path, allowed: set[tuple[str, str, str]]
) -> dict:
    task = candidate_dir.name
    res = {
        "task": task,
        "criterion_diffs": [],
        "file_diffs": [],
        "corpus_count_diff": None,
        "ok": True,
    }

    cand_crit = _load_criteria(candidate_dir)
    ref_crit = _load_criteria(reference_dir)
    for key in sorted(set(cand_crit) | set(ref_crit)):
        group, name = key
        c = cand_crit.get(key)
        r = ref_crit.get(key)
        if c is None:
            change = "removed"
        elif r is None:
            change = "added"
        elif c != r:
            change = "changed"
        else:
            continue
        allow_key = (task, "criterion", name)
        entry = {
            "group": group,
            "name": name,
            "change": change,
            "candidate": c,
            "reference": r,
        }
        if allow_key not in allowed:
            res["ok"] = False
            res["criterion_diffs"].append(entry)

    cand_files = _hash_tree(candidate_dir, "solution", "tests")
    ref_files = _hash_tree(reference_dir, "solution", "tests")
    for rel in sorted(set(cand_files) | set(ref_files)):
        c = cand_files.get(rel)
        r = ref_files.get(rel)
        if c == r:
            continue
        change = (
            "removed" if c is None else ("added" if r is None else "content changed")
        )
        allow_key = (task, "file", rel)
        entry = {"path": rel, "change": change}
        if allow_key not in allowed:
            res["ok"] = False
            res["file_diffs"].append(entry)

    cand_n = _corpus_count(candidate_dir)
    ref_n = _corpus_count(reference_dir)
    if cand_n != ref_n:
        allow_key = (task, "corpus-count", task)
        entry = {"candidate": cand_n, "reference": ref_n}
        res["corpus_count_diff"] = entry
        if allow_key not in allowed:
            res["ok"] = False

    return res


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "candidate", help="the freshly built 03_dataos_ready root, about to ship"
    )
    ap.add_argument("reference", help="the last confirmed-good 03_dataos_ready root")
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        help="limit to these task ids (repeatable)",
    )
    ap.add_argument(
        "--allow-change",
        action="append",
        default=[],
        metavar="TASK:KIND:NAME",
        help="a reviewed, deliberate change to not flag; repeatable",
    )
    ap.add_argument("--json", help="also write the full result set here")
    args = ap.parse_args()

    candidate_root = Path(args.candidate)
    reference_root = Path(args.reference)
    if not candidate_root.is_dir():
        sys.stderr.write(f"not a directory: {candidate_root}\n")
        return 2
    if not reference_root.is_dir():
        sys.stderr.write(f"not a directory: {reference_root}\n")
        return 2

    allowed: set[tuple[str, str, str]] = set()
    for spec in args.allow_change:
        parts = spec.split(":", 2)
        if len(parts) != 3:
            sys.stderr.write(f"--allow-change must be TASK:KIND:NAME, got: {spec}\n")
            return 2
        allowed.add(tuple(parts))

    cand_tasks = {d.name for d in candidate_root.iterdir() if d.is_dir()}
    ref_tasks = {d.name for d in reference_root.iterdir() if d.is_dir()}
    if args.task:
        want = set(args.task)
        cand_tasks &= want
        ref_tasks &= want
        for t in want - cand_tasks - ref_tasks:
            sys.stderr.write(f"task not found in either root: {t}\n")

    both = sorted(cand_tasks & ref_tasks)
    only_candidate = sorted(cand_tasks - ref_tasks)
    only_reference = sorted(ref_tasks - cand_tasks)

    results = [diff_task(candidate_root / t, reference_root / t, allowed) for t in both]
    bad = [r for r in results if not r["ok"]]

    for r in results:
        flag = "OK     " if r["ok"] else "CHANGED"
        print(f"{flag} {r['task']}")
        for d in r["criterion_diffs"]:
            print(f"       criterion {d['group']}/{d['name']}: {d['change']}")
            if d["change"] == "changed":
                print(f"           was: {d['reference']}")
                print(f"           now: {d['candidate']}")
        for d in r["file_diffs"]:
            print(f"       file {d['path']}: {d['change']}")
        if r["corpus_count_diff"] is not None:
            d = r["corpus_count_diff"]
            print(
                f"       corpus file count: reference {d['reference']} -> candidate {d['candidate']}"
            )

    for t in only_candidate:
        print(f"MISSING IN REFERENCE  {t}  (nothing to check this rebuild against)")
    for t in only_reference:
        print(f"MISSING IN CANDIDATE  {t}  (this task would no longer ship)")

    print(f"\n{len(results) - len(bad)}/{len(results)} unchanged")
    if only_candidate or only_reference:
        print(
            f"{len(only_candidate)} only in candidate, {len(only_reference)} only in reference"
        )

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "results": results,
                    "only_in_candidate": only_candidate,
                    "only_in_reference": only_reference,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.json}")

    return 1 if (bad or only_candidate or only_reference) else 0


if __name__ == "__main__":
    raise SystemExit(main())
