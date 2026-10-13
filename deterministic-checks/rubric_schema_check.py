#!/usr/bin/env python3
"""Rubric schema check: validate the judge.toml rubric files in a built Harbor task package.

Why this exists: nothing else in a typical build pipeline re-verifies a task's rubric files
AFTER the task is built. A schema or weight defect introduced upstream (a converter mapping the
wrong source column, a chunker splitting a rubric across files inconsistently) can ship
completely silently if nothing re-checks the built package itself.

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
`formula_health_check.py` in this folder expects. Only the docstring, comments, and CLI help text
were reworded here to drop the source project's benchmark name and example task/path IDs.

Status: v1, ported as-is. The validation logic has been run at real scale against built packages
in its source project; this generalized copy has only been smoke-tested (`--help`, and a run
against a small sample package) since the rename, not yet run at scale under this name.

EKW port (2026-09-14): everything above this paragraph describes the original SVC-PC-only script
and is unchanged in behaviour. `check_task_ekw()` (new, just below `check_task()`) is the EKW
counterpart of `check_task()`: it reads `tests/verifier.json` via
`ekw_verifier_json.load_ekw_criteria()` instead of `tests/deliverables_*/judge.toml` via
`tomllib`, then feeds each criterion's (weight, description) through `_classify_description()` --
the exact same blank/bare-tier/placeholder-expected classification `check_task()` itself now
calls, pulled out verbatim rather than reimplemented, so the two formats cannot silently drift
apart on what counts as a defect. `check_task_dispatch()` picks whichever of the two functions
applies to a given task directory and is the only thing `main()` calls; SVC-PC detection (any
`tests/deliverables/judge.toml` or `tests/deliverables_*/judge.toml`) takes precedence over EKW
detection, mirroring `deliverable_filename_check.py`'s own EKW-port precedence rule, so this port
cannot change SVC-PC behaviour for any task that already has one.

`check_task_ekw()` intentionally has no `file_weight_mismatch` check: SVC-PC's judge.toml
declares a weight per judge.toml file (`[judge].weight`) separate from the sum of its own
`[[criterion]].weight` entries, so the two can drift and that drift is worth catching. EKW's
verifier.json has no analogous per-file declared total to drift against -- `metadata.weight` IS
each verifier's only weight, so there is nothing to cross-check it against. `judge_files` is
fixed at 1 for a task with a parseable verifier.json (EKW has exactly one config file per task,
unlike SVC-PC's `deliverables_NN` fan-out) and 0 otherwise.

Header-alias task-level fraction (2026-09-14): a separate, real defect class from anything
above -- a non-empty rubric spreadsheet header cell that maps to no recognized field gets
silently converted into a blank criterion downstream, in the xlsx-to-judge.toml/verifier.json
converter (a different file, out of scope here; not fixed by anything in this script). This
script never reads the source xlsx, so it cannot see which header caused the corruption -- but
it can see the downstream fingerprint: when the bug hits a task, it does not hit one criterion,
it hits every criterion the affected column touched, because the column itself is what's
unmapped. `blank_fraction` and `header_alias_suspect` below make that fingerprint an explicit,
named, task-level finding instead of leaving it implicit in "this task has N placeholder_expected
findings somewhere in its criterion list," which does not by itself distinguish one stray bad
row from a task that went through the converter bug wholesale.

Threshold calibrated against real data, not guessed: a full run of this script (unmodified,
before this addition) against the real 600-task SVC-PC production corpus
(`C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready`, 2026-09-14) found 38 tasks with at
least one blank/bare-tier/placeholder-expected criterion, and those 38 split into two clusters
with nothing between them: 30 tasks at EXACTLY 100% (every single criterion in the task landed
in one of the three buckets) and 8 tasks between 0.91% and 7.41% (a handful of criteria each,
the shape of an isolated authoring defect, not a corrupted column). The 30-task, 100% cluster
is also an exact match for COVERAGE-MATRIX.md's independently-sourced count ("30 of 600 shipped
tasks with every criterion blank," from that day's separate build-pipeline corruption sweep) --
a second, differently-derived source landing on the identical number. HIGH_BLANK_FRACTION (0.5)
sits at the midpoint of the empty 7.41%-100% gap, so on this corpus it cannot misclassify either
real cluster; SVC-PC-96-2-0, documented elsewhere as a 40/40-blank positive control, is one of
the 30 and confirmed by direct execution (see the validation run this addition was checked
against). The EKW production corpus checked the same day (`C:/ekwqc/_merged274/files`, 274
tasks) had zero criteria in any of the three buckets at all -- no positive or negative EKW
example exists yet to calibrate against independently, so `header_alias_suspect` on the EKW
side reuses the identical threshold and classification rather than a second, EKW-specific
number invented without evidence.
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

from ekw_verifier_json import has_ekw_config, load_ekw_criteria

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

# See the module docstring's "Header-alias task-level fraction" section for the calibration
# behind this number: real 600-task SVC-PC corpus, 30 tasks at exactly 100%, next-highest
# 7.41%, nothing observed between 8% and 90%. 0.5 sits in the middle of that gap.
HIGH_BLANK_FRACTION = 0.5


def _classify_description(desc: str) -> str | None:
    """Classify one already-`.strip()`ed criterion description into exactly one bucket, or
    None if clean. Extracted verbatim from check_task()'s original inline if/elif/elif so
    check_task() (SVC-PC) and check_task_ekw() (EKW) share the identical classification --
    same regexes, same precedence (blank checked first, then bare-tier, then
    placeholder-expected; only one bucket per description) -- rather than each carrying its own
    copy that could silently drift from the other."""
    if not desc:
        return "blank_desc"
    if BARE_TIER_RE.match(desc):
        return "bare_tier"
    if PLACEHOLDER_EXPECTED_RE.search(desc):
        return "placeholder_expected"
    return None


def _apply_blank_fraction(res: dict) -> None:
    """Task-level severity signal, computed from the SAME three per-criterion buckets
    check_task()/check_task_ekw() already populate (blank_desc, bare_tier,
    placeholder_expected) -- this adds no new per-criterion classification, only a task-wide
    rollup of one already-detected. Mutates `res` in place: sets `blank_fraction` (the share of
    this task's own criteria that landed in any of the three buckets, 0.0 on a task with no
    criteria) and `header_alias_suspect` (True when that fraction meets HIGH_BLANK_FRACTION AND
    the task has at least one criterion -- the guard against a criteria=0 parse-error task
    reading as 0/0 "suspect").

    Called identically by both check_task() and check_task_ekw() after their per-criterion
    loop, before `ok` is computed, so SVC-PC and EKW can't silently diverge on what counts.
    Does NOT feed into `ok`: `ok` already goes False on a single placeholder_expected/bare_tier/
    blank_desc finding (a stricter bar than 50%), so this is a purely additive triage label --
    the answer to "is this the wholesale header-alias-converter symptom, or one stray bad row,"
    not a new pass/fail gate. See module docstring for the corpus calibration behind 0.5.
    """
    n = res["criteria"]
    symptom = len(res["blank_desc"]) + len(res["bare_tier"]) + len(res["placeholder_expected"])
    res["blank_fraction"] = round(symptom / n, 4) if n else 0.0
    res["header_alias_suspect"] = n > 0 and res["blank_fraction"] >= HIGH_BLANK_FRACTION


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
        _apply_blank_fraction(res)
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
            bucket = _classify_description(desc)
            if bucket:
                res[bucket].append(where)

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
    _apply_blank_fraction(res)
    res["ok"] = (
        not res["blank_desc"]
        and not res["bare_tier"]
        and not res["placeholder_expected"]
        and not res["file_weight_mismatch"]
        and not res["parse_errors"]
        and abs(total - 1.0) <= WEIGHT_TOL
    )
    return res


def check_task_ekw(task_dir: Path) -> dict:
    """EKW counterpart to check_task(): tests/verifier.json instead of
    tests/deliverables_*/judge.toml. Same result-dict shape, same three description checks
    (via the shared _classify_description()), same task-level weight-sum-to-1.0 check, same
    WEIGHT_TOL. No file_weight_mismatch check and judge_files fixed at 1 (0 on parse failure) --
    see the module docstring's EKW port note for why those two have no EKW equivalent.
    """
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

    criteria = load_ekw_criteria(task_dir)
    if not criteria:
        res["parse_errors"].append("tests/verifier.json has no verifiers")
        _apply_blank_fraction(res)
        return res

    # load_ekw_criteria()'s own convention for a verifier.json that failed to parse, has a
    # non-list 'verifiers' field, or a malformed entry inside it (see ekw_verifier_json.py) --
    # one or more __parse_error__ placeholder entries rather than raising. Surface each as a
    # parse error here exactly as check_task() surfaces a tomllib exception.
    parse_error_entries = [c for c in criteria if c["name"] == "__parse_error__"]
    if parse_error_entries:
        for c in parse_error_entries:
            res["parse_errors"].append(c["description"])
        _apply_blank_fraction(res)
        return res

    res["judge_files"] = 1
    total = 0.0
    for c in criteria:
        res["criteria"] += 1
        desc = (c.get("description") or "").strip()
        w = c.get("weight")
        if isinstance(w, (int, float)):
            total += float(w)
        where = f"{c['group']}/{c['name']}"
        bucket = _classify_description(desc)
        if bucket:
            res[bucket].append(where)

    res["weight_sum"] = round(total, 6)
    _apply_blank_fraction(res)
    res["ok"] = (
        not res["blank_desc"]
        and not res["bare_tier"]
        and not res["placeholder_expected"]
        and not res["parse_errors"]
        and abs(total - 1.0) <= WEIGHT_TOL
    )
    return res


def _has_svc_pc_config(task_dir: Path) -> bool:
    """True if this task has judge.toml under either accepted SVC-PC layout -- the same glob
    check_task() itself uses, so detection can never disagree with what that function would
    find."""
    return bool(
        list(task_dir.glob("tests/deliverables/judge.toml"))
        or list(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def check_task_dispatch(task_dir: Path) -> dict:
    """Format-dispatching wrapper: SVC-PC's tests/deliverables*/judge.toml takes precedence
    whenever it exists, so this port cannot change SVC-PC behaviour for any task that already
    has one, even in the unobserved case where a task dir somehow carries both shapes. A task
    with neither shape falls through to check_task(), which reports its own "no judge.toml
    found" parse error unchanged -- not a new code path."""
    if _has_svc_pc_config(task_dir):
        return check_task(task_dir)
    if has_ekw_config(task_dir):
        return check_task_ekw(task_dir)
    return check_task(task_dir)


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

    results = [check_task_dispatch(d) for d in task_dirs]

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
        if r["header_alias_suspect"]:
            print(
                f"       HEADER-ALIAS SUSPECT: {r['blank_fraction']:.0%} of {r['criteria']} "
                f"criteria are blank/bare-tier/placeholder-expected "
                f"(>= {HIGH_BLANK_FRACTION:.0%} threshold) -- likely the whole task went "
                f"through the converter's unmapped-header bug, not an isolated bad row"
            )

    alias_suspect = [r for r in results if r["header_alias_suspect"]]
    print(f"\n{len(results) - len(bad)}/{len(results)} clean")
    if alias_suspect:
        print(
            f"{len(alias_suspect)}/{len(results)} header-alias suspect "
            f"(>= {HIGH_BLANK_FRACTION:.0%} of criteria blank/placeholder): "
            + ", ".join(r["task"] for r in alias_suspect)
        )
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
