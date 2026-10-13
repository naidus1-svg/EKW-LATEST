"""Judge criterion-name duplicate detector: flags any two `[[criterion]]` blocks in a task's
judge.toml file(s) whose `name` collides, so a human can look at both full criterion entries
side by side and decide whether it's a real duplicate, a copy-paste typo, or something benign.

Why this exists, and how it relates to duplicate_criterion_check.py. That script detects the
same underlying defect shape -- a downstream harness that builds a dict keyed by criterion
identifier, silently collapsing any two rows/entries that share a key -- but only in the xlsx
rubric SHEET, before it's converted to a judge.toml. Its own docstring names the exact gap this
script closes, quoted directly from that file:

    "A note on a format this script deliberately does NOT cover: `tests/deliverables_*/judge.toml`
    files (the verifier config the rubric eventually becomes) use `[[criterion]] name = "..."`,
    not an "id" field, confirmed by reading a real one directly. A duplicate `name` there is a
    different defect against a different data shape and is not this script's concern -- it
    would need its own check against the toml criterion list, not against an xlsx rubric sheet."

This is that check. The risk is the same one the xlsx script's docstring lays out at length: if
any code downstream of the build (a grading harness, a report generator, a re-scoring tool) ever
loads a judge.toml's criteria into a dict keyed by `name` -- a natural thing to do, since `name`
is the only human-readable label a criterion carries -- two criteria sharing a name silently
collapse to one, and the dropped one's weight is gone with no exception raised. And exactly like
the xlsx case, a weight-sum-to-1.0 check (`rubric_schema_check.py`'s own check 5) does not catch
this when the dropped and surviving weights happen to add up to something a renormalization step
smooths over: 1.0 is still 1.0, it is just missing a criterion's worth of grading. That is the
same "arithmetic coincidence can hide a real bug" logic `duplicate_criterion_check.py`'s docstring
uses to justify its own existence as a second, independent check; this script exists for the same
reason, against the toml shape instead of the xlsx shape.

Two scopes, reported separately, because neither is safe to assume away. A `[[criterion]].name`
collision matters at (at least) two different scopes, and this script does not know -- and none
of `rubric_schema_check.py`, `deliverable_filename_check.py`, or `formula_health_check.py` say --
which scope any given downstream harness actually builds its dict over:

  - PER FILE (primary, higher confidence): two criteria in the SAME judge.toml sharing a name.
    This is the scope any single dict-build over one file's own criteria list would collide on --
    `{c["name"]: c for c in data["criterion"]}` run against one file's own `criterion` array --
    and is reported as the primary finding because it needs no assumption about how multiple
    judge.toml files in a task relate to each other.
  - CROSS FILE (secondary, lower confidence): the same name reused across two or more DIFFERENT
    judge.toml files in the same task (e.g. one criterion named "c05" under
    tests/deliverables_01/ and another criterion also named "c05" under tests/deliverables_02/).
    This only collides downstream if some harness merges criteria from every judge.toml in a task
    into one shared dict before grading -- plausible (a task-level reward rollup would need to
    see every criterion at once) but not confirmed against any real harness this script has been
    shown, so it is reported as a distinct, lower-confidence finding rather than silently folded
    into the primary one or silently dropped. Mirrors this folder's general practice (see
    `duplicate_criterion_check.py`'s own "Known limits" on cross-sheet merges) of disclosing scope
    uncertainty instead of guessing which scope is the "real" one.

For every collision, in either scope, this script reports the FULL criterion entry (every field
present on that `[[criterion]]` block -- name, description, weight, type, and anything else it
carries, such as a criterion-level `files` override) for EACH colliding occurrence, exactly like
`duplicate_criterion_check.py`'s `row_cells()` reports every column of a colliding xlsx row. A
human reading the report sees both full entries side by side and can judge same-criterion-
duplicated vs typo vs different-criteria-that-happen-to-share-a-label.

This is a REPORT-ONLY check. There is no --apply flag and no repair path of any kind: it never
writes to any judge.toml it reads, matching its xlsx sibling exactly.

Parsing convention, matched to this folder's other judge.toml readers rather than invented fresh:
    - `tomllib`, never regex -- same as `rubric_schema_check.py` and `deliverable_filename_check.py`.
    - Both real package layouts are globbed: a bare `tests/deliverables/judge.toml` (single-
      deliverable tasks) and one or more numbered `tests/deliverables_NN/judge.toml` (multi-
      deliverable tasks) -- the exact `set(...) | set(...)` union `rubric_schema_check.py`'s
      `check_task()` uses, with the same comment this script inherits: a check that only globs
      the numbered form reports zero criteria on a perfectly good single-deliverable package,
      "the same shape of bug as a weight check that keyed off a single expected tab name."
    - CLI shape (`<TASK-ID...> --root <path> [--all] [--id-prefix] [--out report.json]`),
      `find_task_dirs()`, the UTF-8 stdout/stderr reconfigure, and the per-task JSON + aggregate
      report shape are all taken directly from `deliverable_filename_check.py`, the sibling this
      script is closest to in both purpose (a single mechanical presence/uniqueness check over a
      task's judge.toml files) and CLI surface.

Provenance: built new for this folder (no scratch-file or source-pipeline predecessor the way
`deliverable_filename_check.py` and `duplicate_criterion_check.py` had) -- the gap it closes was
named, not implemented, in `duplicate_criterion_check.py`'s docstring. Its detection logic
(collect names per file, per task; a collision is >1 occurrence after `str(value).strip()`
normalization) deliberately mirrors that script's own normalization choice so the two checks
agree on what counts as "the same name" wherever they overlap conceptually.

Status: v1, report-only, unverified against any real collision (the real corpus this script was
checked against -- 600 tasks / 2,252 judge.toml files -- had zero per-file and zero cross-file
name collisions at the time of that sweep; see this folder's own verification notes rather than
this docstring for the up-to-date count). Verified against a hand-built synthetic fixture instead
(two `[[criterion]]` blocks sharing a name in one file) to confirm the detection logic itself is
sound, since the real corpus offered no positive example to test against.

Usage:
    python judge_criterion_name_duplicate_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python judge_criterion_name_duplicate_check.py --all --root <path> --out report.json
    python judge_criterion_name_duplicate_check.py --all --root <path> --id-prefix MYBENCH- --out report.json

What it does, in order:

1. For a given task id (or --all tasks under --root), finds every judge.toml under that task
   using the same two-layout glob `rubric_schema_check.py` uses: `tests/deliverables/judge.toml`
   union `tests/deliverables_*/judge.toml`.
2. Parses each with `tomllib` (never regex) and reads the `[[criterion]]` array. A judge.toml
   that fails to parse, or whose `criterion` key exists but isn't a list, is recorded in that
   task's `parse_errors` and skipped -- it does not by itself fail the task if other judge.toml
   files under the same task parse fine (mirrors `deliverable_filename_check.py`'s handling of a
   malformed `[judge].files`).
3. Within each file, reads every `[[criterion]].name`, skipping entries with a blank or missing
   name (a missing name is a different defect -- schema completeness -- and not this script's
   concern; noted, not silently swallowed, in `skipped_unnamed`) and normalizing every present
   name with `str(value).strip()`, the same normalization `duplicate_criterion_check.py` uses for
   xlsx criterion ids. Two entries in the SAME file whose normalized name is equal are a
   PER-FILE collision.
4. Across all of a task's judge.toml files, a normalized name that appears in two or more
   DIFFERENT files (regardless of how many times within any one of them) is a CROSS-FILE
   collision, reported separately from -- not merged into, not deduplicated against -- the
   per-file findings, since a name can trigger both at once (duplicated within one file AND also
   reused in a different file) and a human should see both facts.
5. For every collision in either scope, records the full criterion entry (every key the
   `[[criterion]]` table actually carries, whatever they are for this particular task) for EACH
   colliding occurrence, plus which file and which position in that file's `criterion` array it
   came from.
6. Writes one JSON result per task (status: pass|fail|skip, files checked, criteria counted, both
   collision lists) plus an aggregate pass/fail/skip summary across every task given on the
   command line (or discovered via --all), and exits 1 if any task has at least one collision in
   EITHER scope (0 if none do, 2 on bad usage) -- same three-way exit contract
   `rubric_schema_check.py` documents for itself.

Known limits, disclosed rather than silently dropped:
    - Normalization is exactly `str(value).strip()`, case-sensitive: "C05" and "c05" are NOT
      treated as a collision here, matching `duplicate_criterion_check.py`'s own choice for the
      same reason -- it has not been shown a pipeline that lowercases before keying its dict, so
      it does not guess at a normalization step it was never shown.
    - An entry with a blank or missing `name` is skipped entirely (not compared, not reported as
      a collision with other blank-named entries). Whether every criterion HAS a name is a schema-
      completeness question, not a duplicate-name question, and is out of this script's scope --
      it would need its own check, the way `rubric_schema_check.py` already owns blank-description
      detection.
    - Cross-file scope assumes a hypothetical harness that merges every judge.toml in a TASK into
      one dict. If your actual harness only ever loads judge.toml files one at a time and never
      merges across deliverable groups, a cross-file finding here is a false alarm relative to
      your specific pipeline -- which is exactly why it is reported as the secondary, lower-
      confidence list rather than folded into the primary one. Confirm your own harness's merge
      scope before treating a cross-file finding as an urgent defect, or before treating a report
      with only cross-file findings and no per-file findings as safe to ignore.
    - A criterion-level `files = [...]` override, if a task ever uses one, is not itself
      inspected for anything -- it shows up automatically in the dumped entry (since every key on
      the criterion table is included) but this script does nothing with it beyond that. Resolving
      which file(s) a criterion actually grades is `formula_health_check.py`'s
      `resolve_graded_files()` territory, not this script's.
    - A collision being reported is not itself proof of a defect, exactly like its xlsx sibling:
      it is reported, with full context, for a human to judge, never auto-resolved either way.
    - This only reads the CURRENT on-disk state of whatever --root points at. It says nothing
      about whether a task was fixed by other work after this check last ran.

EKW PORT (2026-09-14), additive branch, SVC-PC path unchanged:

A task is analyzed as SVC-PC if it has a judge.toml under tests/deliverables/ or
tests/deliverables_*/ (find_judge_files() non-empty) -- checked FIRST, so a task carrying
both shapes during a format migration is still analyzed as SVC-PC, exactly as before this
port. Only when no judge.toml is found and `ekw_verifier_json.has_ekw_config()` is true does
this script read `tests/verifier.json` via `load_ekw_criteria()` and feed each verifier's
own `name` field through the identical collision-detection logic (same `_detect_collisions()`
helper, same `str(value).strip()` normalization, same per-file/cross-file split) -- the input
is redirected, the detection logic itself is not rewritten.

Two things this redirection makes true for EKW that are not true for SVC-PC, both worth
stating plainly rather than leaving implicit in the report:

  - There is exactly ONE tests/verifier.json per task -- EKW has no tests/deliverables_NN/
    equivalent, confirmed in ekw_verifier_json.py's own docstring. That means
    cross_file_collisions is STRUCTURALLY always empty for an EKW task: "cross file" requires
    the same name to appear in two different config files, and an EKW task never has more
    than one. Only per_file_collisions (two verifiers inside the same, single verifier.json
    sharing a name) can ever fire for EKW. A report with an EKW task showing zero cross-file
    findings is not evidence of anything; it could not have shown any other result.
  - EKW's "group" field is not a real grouping. In SVC-PC, `group` is the shared parent
    directory name (e.g. "deliverables_02") that MULTIPLE criteria in one file have in
    common. `load_ekw_criteria()` sets `group` to the verifier's own `name` (its docstring:
    "each verifier is its own group for provenance"), so for EKW `group` and `name` are
    always identical, and a per-file collision's reported `group` is therefore just the
    colliding name again, not independent information. Not a bug, just a field that carries
    no extra signal for this format the way it does for SVC-PC.

A `verifier.json` entry that ekw_verifier_json.py itself could not parse (either the whole
file, via its `name: "__parse_error__"` sentinel) is recorded in this task's `parse_errors`
and excluded from `criteria_checked` and from collision detection, mirroring exactly how a
malformed SVC-PC `[[criterion]]` entry (not a table) is handled -- never silently dropped,
never treated as a real criterion.

A new `format` field ("svc_pc" | "ekw" | None) is added to every per-task result so a reader
of the JSON report can tell which parser produced a given task's findings without having to
infer it from `judge_files_found` alone. This is the only additive field; every field the
original SVC-PC result carried is unchanged in both name and meaning.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from ekw_verifier_json import has_ekw_config, load_ekw_criteria

# Windows console defaults to cp1252, which can't encode every character that shows up in a
# real task's judge.toml (curly quotes, em dashes in vendored description text, etc). Force
# UTF-8 with replacement so a printable-but-non-cp1252 character never crashes a batch run
# partway through. Same guard `deliverable_filename_check.py` uses.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def to_jsonable(v):
    """Same conversion duplicate_criterion_check.py uses: toml can carry a datetime value
    (an unquoted date/time literal), which json.dumps cannot serialize on its own."""
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, (list, dict)):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def find_task_dirs(root, task_ids=None, id_prefix=""):
    """Identical shape to deliverable_filename_check.py's own find_task_dirs()."""
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def find_judge_files(task_dir: Path) -> list[Path]:
    """Both real layouts, same union rubric_schema_check.py's check_task() uses: a bare
    tests/deliverables/judge.toml (single-deliverable tasks) and one or more numbered
    tests/deliverables_NN/judge.toml (multi-deliverable tasks)."""
    return sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def _detect_collisions(criteria_by_file: "dict[str, list[tuple]]"):
    """Format-agnostic collision detector shared by the SVC-PC (judge.toml) and EKW
    (verifier.json) branches of analyze_task(). Neither branch reimplements this logic --
    each just parses its own format into the same shape and hands it here, per this script's
    own EKW-port docstring ("redirect its input... don't rewrite that logic").

    criteria_by_file: dict mapping a file's task-relative path (str, forward slashes) to a
    list of (group, index, raw_name, entry) tuples IN THE ORDER the criteria/verifiers were
    encountered in that file. `entry` is whatever full-record dict should be shown to a human
    for that occurrence (every judge.toml criterion key for SVC-PC; the flattened
    group/name/description/weight/type/files dict for EKW).

    Returns (criteria_checked, skipped_unnamed, per_file_collisions, cross_file_collisions),
    each in exactly the shape analyze_task's result dict already carries -- this function only
    factors out the shared computation, it does not change what gets reported.
    """
    criteria_checked = 0
    skipped_unnamed: list[dict] = []
    per_file_collisions: list[dict] = []
    # by_name_task: normalized name -> list of occurrence dicts across the WHOLE task, each
    # carrying which file it came from -- built once, then sliced two ways below (per-file,
    # then across the files that remain after per-file grouping).
    by_name_task: dict[str, list[dict]] = collections.defaultdict(list)

    for rel, items in criteria_by_file.items():
        by_name_file: dict[str, list[dict]] = collections.defaultdict(list)
        for group, idx, raw_name, entry in items:
            criteria_checked += 1
            if raw_name is None or str(raw_name).strip() == "":
                skipped_unnamed.append({"file": rel, "index": idx})
                continue
            norm = str(raw_name).strip()
            occ = {
                "file": rel,
                "group": group,
                "index": idx,
                "raw_name": raw_name,
                "entry": entry,
            }
            by_name_file[norm].append(occ)
            by_name_task[norm].append(occ)

        # PER FILE (primary): two-or-more occurrences of the same normalized name within
        # this one file's own criteria list.
        for norm, occs in by_name_file.items():
            if len(occs) > 1:
                per_file_collisions.append(
                    {
                        "file": rel,
                        "group": occs[0]["group"],
                        "normalized_name": norm,
                        "occurrences": occs,
                    }
                )

    # CROSS FILE (secondary): the same normalized name appearing in two-or-more DIFFERENT
    # files anywhere in this task, regardless of how many times within any single file.
    # Not deduplicated against per-file collisions above -- a name can legitimately trigger
    # both findings at once, and a human should see both facts rather than have one silently
    # absorbed into the other. For EKW this is structurally always empty (see module
    # docstring's EKW PORT section) since an EKW task has exactly one config file.
    cross_file_collisions: list[dict] = []
    for norm, occs in by_name_task.items():
        distinct_files = {o["file"] for o in occs}
        if len(distinct_files) > 1:
            cross_file_collisions.append(
                {
                    "normalized_name": norm,
                    "files": sorted(distinct_files),
                    "occurrences": occs,
                }
            )

    return criteria_checked, skipped_unnamed, per_file_collisions, cross_file_collisions


def _parse_svc_pc_criteria(task_dir: Path, judge_files: "list[Path]", result: dict):
    """Parses every judge.toml this task has into the (group, index, raw_name, entry) shape
    _detect_collisions() expects. Malformed-file and malformed-entry handling is byte-for-byte
    what analyze_task() used to do inline before this port -- moved, not changed -- so the
    SVC-PC path's behavior is unchanged."""
    criteria_by_file: dict[str, list[tuple]] = {}
    for jf in judge_files:
        rel = str(jf.relative_to(task_dir)).replace("\\", "/")
        group = jf.parent.name
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception as e:
            result["parse_errors"].append(f"{rel}: failed to parse -- {e}")
            continue

        crits = data.get("criterion")
        if crits is None:
            crits = []
        elif not isinstance(crits, list):
            result["parse_errors"].append(
                f"{rel}: [[criterion]] is not an array (got {type(crits).__name__})"
            )
            continue

        items = []
        for idx, c in enumerate(crits):
            if not isinstance(c, dict):
                result["parse_errors"].append(
                    f"{rel}: criterion entry at index {idx} is not a table "
                    f"(got {type(c).__name__}) -- skipped"
                )
                continue
            raw_name = c.get("name")
            entry = {k: to_jsonable(v) for k, v in c.items()}
            items.append((group, idx, raw_name, entry))
        criteria_by_file[rel] = items
    return criteria_by_file


def _parse_ekw_criteria(task_dir: Path, result: dict):
    """Parses tests/verifier.json (via ekw_verifier_json.load_ekw_criteria) into the same
    (group, index, raw_name, entry) shape _detect_collisions() expects, redirecting the
    verifier's own `name` field through the identical detection logic used for SVC-PC's
    `[[criterion]].name`. There is always exactly one file, "tests/verifier.json", so the
    returned dict always has (at most) one key -- see module docstring's EKW PORT section for
    what that means for cross_file_collisions."""
    rel = "tests/verifier.json"
    criteria = load_ekw_criteria(task_dir)
    items = []
    for idx, c in enumerate(criteria):
        if c.get("name") == "__parse_error__":
            # Either the whole file failed to parse, or one entry in its "verifiers" array
            # wasn't a proper object -- ekw_verifier_json.py's own parse-error convention.
            # Recorded, not counted as a criterion and not fed into collision detection,
            # mirroring how a malformed SVC-PC [[criterion]] table is handled above.
            result["parse_errors"].append(f"{rel}: {c.get('description')}")
            continue
        raw_name = c.get("name")
        entry = {
            "group": c.get("group"),
            "name": c.get("name"),
            "description": c.get("description"),
            "weight": c.get("weight"),
            "type": c.get("type"),
            "files": c.get("files"),
        }
        items.append((c.get("group"), idx, raw_name, entry))
    return {rel: items} if criteria else {}


def analyze_task(task_dir: Path) -> dict:
    """Returns a result dict for one task. Never raises -- a missing tests/ dir, an
    unparseable judge.toml/verifier.json, or a malformed criterion/verifier array is reported
    as a skip/parse_error, not a crash that would kill the batch.

    Format detection (see module docstring's EKW PORT section for the full rationale):
    SVC-PC's judge.toml is checked FIRST and, if found, analyzed exactly as before this port.
    Only when no judge.toml exists is tests/verifier.json (EKW) tried."""
    task_id = task_dir.name
    result = {
        "task_id": task_id,
        "format": None,
        "judge_files_found": 0,
        "criteria_checked": 0,
        "skipped_unnamed": [],
        "parse_errors": [],
        "per_file_collisions": [],
        "cross_file_collisions": [],
        "status": None,
    }

    judge_files = find_judge_files(task_dir)
    if judge_files:
        result["format"] = "svc_pc"
        result["judge_files_found"] = len(judge_files)
        criteria_by_file = _parse_svc_pc_criteria(task_dir, judge_files, result)
    elif has_ekw_config(task_dir):
        result["format"] = "ekw"
        result["judge_files_found"] = 1
        criteria_by_file = _parse_ekw_criteria(task_dir, result)
    else:
        result["status"] = "skip"
        result["parse_errors"].append(
            "no judge.toml under tests/deliverables/ or tests/deliverables_*/, and no "
            "tests/verifier.json -- nothing for this check to verify"
        )
        return result

    checked, skipped_unnamed, per_file, cross_file = _detect_collisions(
        criteria_by_file
    )
    result["criteria_checked"] = checked
    result["skipped_unnamed"] = skipped_unnamed
    result["per_file_collisions"] = per_file
    result["cross_file_collisions"] = cross_file

    result["status"] = (
        "fail"
        if (result["per_file_collisions"] or result["cross_file_collisions"])
        else "pass"
    )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Report-only detector for [[criterion]].name collisions across a task's "
            "judge.toml file(s). Reports per-file collisions (primary, higher confidence) "
            "and cross-file collisions within the same task (secondary, lower confidence) "
            "separately, each with the full criterion entry for every colliding occurrence "
            "so a human can judge whether it's a real duplicate, a typo, or benign reuse. "
            "Never writes to any file it reads -- there is no --apply/fix mode."
        )
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="one or more task ids (directory names under --root)",
    )
    ap.add_argument(
        "--all", action="store_true", help="run every task directory found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        required=False,
        help="root directory containing one subdirectory per task (REQUIRED -- no default, "
        "this must never silently assume a project-specific path)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix as tasks "
        "(default: empty, i.e. every subdirectory is treated as a task)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error(
            "--root is required (point it at the directory containing your task folders)"
        )

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    if not args.root.is_dir():
        print(f"--root is not a directory: {args.root}", file=sys.stderr)
        return 2

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 2

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(task_dir)
        except Exception as e:  # never let one task's crash kill the whole batch
            r = {
                "task_id": task_dir.name,
                "status": "fail",
                "judge_files_found": 0,
                "criteria_checked": 0,
                "skipped_unnamed": [],
                "parse_errors": [f"unhandled exception analyzing this task: {e}"],
                "per_file_collisions": [],
                "cross_file_collisions": [],
            }
        results.append(r)
        n_pf = len(r.get("per_file_collisions", []))
        n_cf = len(r.get("cross_file_collisions", []))
        print(
            f"    -> {r['status']}  ({n_pf} per-file collision group(s), "
            f"{n_cf} cross-file collision group(s))",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    total_per_file = sum(len(r.get("per_file_collisions", [])) for r in results)
    total_cross_file = sum(len(r.get("cross_file_collisions", [])) for r in results)
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_skip": n_skip,
        "total_per_file_collision_groups": total_per_file,
        "total_cross_file_collision_groups": total_cross_file,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_skip} skip out of {len(results)} task(s)  "
        f"({total_per_file} per-file collision group(s), "
        f"{total_cross_file} cross-file collision group(s) total)"
    )
    for r in results:
        note = ""
        if r["status"] == "fail":
            names = sorted(
                {c["normalized_name"] for c in r.get("per_file_collisions", [])}
                | {c["normalized_name"] for c in r.get("cross_file_collisions", [])}
            )
            note = f"  [colliding names: {', '.join(names)}]"
        print(f"  {r['task_id']}: {r['status']}{note}")
        for pe in r.get("parse_errors", []):
            print(f"      ! {pe}")
        for c in r.get("per_file_collisions", []):
            where = ", ".join(
                f"index {o['index']} = {o['raw_name']!r}" for o in c["occurrences"]
            )
            print(
                f"      PER-FILE  {c['file']}: name {c['normalized_name']!r} collides -- {where}"
            )
        for c in r.get("cross_file_collisions", []):
            where = ", ".join(
                f"{o['file']} index {o['index']} = {o['raw_name']!r}"
                for o in c["occurrences"]
            )
            print(
                f"      CROSS-FILE  name {c['normalized_name']!r} spans "
                f"{len(c['files'])} files -- {where}"
            )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
