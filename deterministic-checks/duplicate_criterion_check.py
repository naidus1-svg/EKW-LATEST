#!/usr/bin/env python3
"""Duplicate criterion-ID detector: flags any two rows in a rubric whose criterion ID
collides after normalization, so a human can look at both full rows side by side and
decide whether it's a real duplicate, an ID typo, or something intentional.

Why this exists, and why a weight-sum check does not cover it. A rubric-to-verifier
converter that builds a dict keyed by criterion id -- `weight_by_id = {row["criterion_id"]:
w for row in rows}` is the shape seen in the source pipeline -- silently collapses any two
rows that share an id. Only the LAST row's weight survives; the other row's weight is gone
and nobody raised an exception. If the pipeline then re-normalizes so all surviving weights
sum to 1.0, that check passes cleanly: 1.0 is still 1.0, it is just missing a criterion's
worth of grading and carrying someone else's weight instead. The failure only becomes loud
when the two dropped/duplicated weights happen NOT to cancel out (seen on one real task,
where they didn't, and it hard-failed a weight-sum check) -- which means for every task
where they DO happen to cancel, a weight-sum-to-1.0 check is not evidence of a healthy
rubric. It is exactly the kind of arithmetic coincidence a second, independent check has to
exist to catch. This script is that second check: it looks at criterion ids directly,
never at weights, so a cancelling pair cannot hide from it the way it hides from a sum.

Provenance: generalized from tools/svc_fix_duplicate_criterion_ids.py in the turing-context
repo (a QC pipeline built for the SVC-PC / Cirrus Sleep benchmark). That script is a FIXER,
not a checker: confirmed by reading its full source directly, it opens a rubric workbook with
openpyxl (`import openpyxl`, `openpyxl.load_workbook(...)`) and nothing else -- there is no
`tomllib`/`toml` import and no other format ever touched. It is xlsx-only. It can safely
auto-repair exactly one specific defect shape (a decimal-looking id like "1.10" that Excel's
own number formatting silently dropped the trailing zero from, leaving it stored as "1.1"),
and only when both neighbouring rows agree on the surrounding numbering (previous row is
"<n>.9", next row is "<n>.11", so the middle row is unambiguously "<n>.10"). Any collision
that doesn't fit that exact shape makes the source script print "position does not determine
the intended id; not guessing" and bail with a non-zero exit -- it deliberately never guesses
at an unrepaired collision beyond that one case.

This copy is REPORT-ONLY. There is no --apply flag and no repair path of any kind: it never
writes to the rubric file it reads. It generalizes the source in two ways. First, input
handling: --root takes either one rubric file or a directory to search, not one hardcoded
path passed as a positional argument. Second, and more importantly, detection scope: it
surfaces EVERY id collision under the same normalization the source uses (`str(value).strip()`,
case-sensitive, read from column A), not only the one trailing-zero-loss shape the source
knew how to safely auto-fix. A collision from a straight copy-paste mistake, a renumbering
that skipped updating one row, or two unrelated criteria that both ended up labeled the same
thing would all have hit the source's "not guessing" bailout and gone unrepaired without
necessarily being surfaced to a person; this script's whole job is to put every such
collision, fixable by pattern-matching or not, in front of a human with enough context (both
full rows, every column) to make the call.

A note on a format this script deliberately does NOT cover: `tests/deliverables_*/judge.toml`
files (the verifier config the rubric eventually becomes) use `[[criterion]] name = "..."`,
not an "id" field, confirmed by reading a real one directly. A duplicate `name` there is a
different defect against a different data shape and is not this script's concern -- it
would need its own check against the toml criterion list, not against an xlsx rubric sheet.

Status: v1, report-only. No known false negatives against the defect class it targets (an
exact, post-strip string collision in column A of a header-sniffed criteria sheet). The one
way a real collision could be missed is if a rubric ever puts its criterion ids in a column
other than A -- see Known limits below, this is inherited unchanged from the source script.

Usage:
    python duplicate_criterion_check.py --root <rubric.xlsx>
    python duplicate_criterion_check.py --root <path/to/rubric/directory>
    python duplicate_criterion_check.py --root <path> --glob "**/*rubric*.xlsx" --out report.json

What it does, in order:

1. Resolves --root to a list of rubric files: the path itself if it is a file, or every file
   under it matching --glob (default "*.xlsx", the same extension the source script handles;
   pass e.g. --glob "*.xlsm" to widen it) if it is a directory. Excel lock files (the
   "~$..." temp files Excel creates while a workbook is open) are always skipped.
2. For each file, finds every worksheet whose header row has a column starting with
   "criterion" (case-insensitive). The source's own `criteria_sheet()` only ever looks at
   row 1; this script scans each sheet's first HEADER_SCAN_ROWS (20) rows, or all of them if
   the sheet has fewer, because real rubric templates in this corpus have the header lower
   than row 1 and a row-1-only sniff would silently misread the sheet's last row as column A
   instead of raising anything. Difference from the source beyond that: the source picks
   exactly ONE such sheet (the first match, or the workbook's last sheet if nothing matches
   anywhere in the scanned window) and stops there, because it is only ever fixing one sheet
   at a time. This script checks EVERY matching sheet in the workbook, since nothing about
   the defect is sheet-scoped and a rubric workbook that splits criteria across more than one
   tab (e.g. one per deliverable group) deserves the same check on all of them. If no sheet
   has a header anywhere in the scanned window, it falls back to the workbook's last sheet,
   exactly like the source, treats that sheet's header as row 1, and marks that sheet's
   "header_confirmed" as false in the report so a reader knows both the sheet identification
   and the row are a guess, not a confirmed read.
3. Within each such sheet, reads column A from the row AFTER the confirmed header row down
   (same row-after-header convention the source uses, just anchored to wherever the header
   row actually was found instead of always assuming row 2 -- the id is always assumed to
   live in column A -- see Known limits), skipping blank cells, and
   normalizes every value with `str(value).strip()` -- the exact same normalization the
   source's own duplicate detection uses (`collections.Counter(ids.values())` over
   `str(v).strip()` values). Two rows whose normalized id is equal are a collision,
   regardless of whether their RAW values are byte-identical (a numeric 1.1 and a text "1.1"
   normalize the same way here, matching the source).
4. For every collision, records the full row (every column in that row, keyed by that
   column's own header text) for EACH colliding occurrence, not just the id. A human reading
   the report sees, side by side, both rows' Category/Tier/Description/Expected value/etc
   (or whatever columns this particular rubric actually has -- column layout is read from
   the header row, never assumed) and can judge whether this is the same criterion duplicated,
   a genuine typo, or two different criteria that were mistakenly given the same label.
5. Writes one JSON result per file (status: pass|fail, every sheet checked, every collision
   found) plus an aggregate report across every file discovered under --root, and exits 1 if
   any file has at least one collision (0 if none do), so this can gate a build the same way
   the source script's own exit code does.

Known limits, disclosed rather than silently dropped:
    - Assumes the criterion id lives in column A, exactly like the source script -- the
      header sniff only decides which SHEET counts as a criteria table, it does not search
      for which COLUMN holds the id. A rubric that puts ids anywhere else needs this script
      changed (or its column reworked), same limit the source fixer already carried.
    - Normalization is exactly `str(value).strip()`, case-sensitive: "A1" and "a1" are NOT
      treated as a collision here, because they were not treated as one in the source's own
      detection either. If your conversion pipeline's dict key is case-insensitive, this
      check would under-report relative to that pipeline; it has not been asked to guess
      about a normalization step it was never shown.
    - Each matching sheet is checked independently, mirroring the source's per-sheet
      dict-by-id build. If your rubric-to-verifier conversion merges criteria from more than
      one sheet in the SAME workbook into one shared id-keyed dict, a collision across two
      different sheets would also collapse downstream and this script would not catch it --
      it only ever compares ids within a single sheet. Confirm your own pipeline's merge
      scope before treating a "pass" across multiple sheets as proof there is no cross-sheet
      collision.
    - A collision being reported is not itself proof of a defect -- see the whole point of
      this being report-only rather than a fixer: it might be intentional in some rubric this
      script has not seen yet. It is reported, with full context, for a human to judge, never
      auto-resolved either way.
    - This only reads the CURRENT on-disk state of whatever --root points at. It says nothing
      about whether a rubric was fixed by other work after this check last ran.

EKW port (2026-09-14): everything above this paragraph describes the original SVC-PC-only script
and is unchanged in behaviour and in its default invocation (`--root <rubric.xlsx-or-dir>`, no
`--all`, no task ids -- still walks --root for rubric files exactly as before, byte-identical
output). The addition is a second, opt-in mode, entered only when `--all` or one or more task ids
are passed: --root is then treated as a directory of TASK directories (one subdirectory per task,
the same convention `deliverable_filename_check.py` and `judge_criterion_name_duplicate_check.py`
already use) rather than a directory of rubric files directly. In that mode, `check_task_dir()`
detects each task's config format and branches:

  - `tests/deliverables/judge.toml` or `tests/deliverables_*/judge.toml` present (SVC-PC): runs
    the existing, unmodified `find_rubric_files()` + `check_file()` pair, scoped to that one task
    directory instead of the whole --root. No detection logic changed; this is the same rubric-
    xlsx scan the script has always done, just invoked per task.
  - Otherwise, `has_ekw_config(task_dir)` true (EKW): `ekw_verifier_json.load_ekw_criteria()`
    supplies each verifier's `name` field (and its full criterion dict, for report context) and
    these run through `group_by_normalized_id()` -- the exact same normalize-and-count collision
    logic `check_file()` uses for xlsx column-A ids, factored out into its own function so the
    xlsx and EKW paths call one shared implementation rather than two copies that could drift.
    EKW has no per-task sheet/file-group concept (see `ekw_verifier_json.py`'s own docstring), so
    every verifier in a task's single `tests/verifier.json` is one comparison group -- the EKW
    analogue of one xlsx "sheet."
  - Neither format found: reported as `status: "skip"`, not a failure -- there is nothing for
    this check to verify.

`__parse_error__` entries (`load_ekw_criteria()`'s convention for an unparseable verifier.json or
a malformed `verifiers` array entry) are excluded from duplicate comparison and surfaced as a
`parse_error` instead: two independent parse failures in the same task would otherwise share the
literal name `"__parse_error__"` and get reported as a false collision, which is an artifact of
the error-reporting convention, not a real duplicate criterion id.

Run against all 274 real EKW tasks under `C:\\ekwqc\\_merged274\\files` (2026-09-14): 0 crashes,
274/274 completed. See this repo's own verification notes / the porting session's report for the
duplicate count found (structurally expected to be zero or near-zero, since EKW verifier names are
auto-generated sequentially per task -- confirmed, not assumed, by that same run).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ekw_verifier_json import has_ekw_config, load_ekw_criteria

try:
    import openpyxl
except ImportError:  # pragma: no cover
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl

# Windows console defaults to cp1252, which can't encode every character that shows up in real
# rubric/verifier text (curly quotes, em dashes, etc). Force UTF-8 with replacement so a
# printable-but-non-cp1252 character never crashes a batch run partway through -- same guard
# deliverable_filename_check.py and judge_criterion_name_duplicate_check.py use. Additive safety
# only: does not change what the SVC-PC path detects or reports.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

RUBRIC_LOCK_PREFIX = "~$"

# How many rows from the top of a sheet to scan for a header row before giving up on that
# sheet. The source fixer only ever checks row 1; real rubric templates in this corpus have
# the header further down, so a fixed window is scanned instead of assuming row 1.
HEADER_SCAN_ROWS = 20


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def to_jsonable(v):
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def find_rubric_files(root: Path, pattern: str) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.rglob(pattern)
        if p.is_file() and not p.name.startswith(RUBRIC_LOCK_PREFIX)
    )


def find_header_row(ws, max_scan: int = HEADER_SCAN_ROWS) -> int | None:
    """Scans this sheet's first `max_scan` rows (or all of them if the sheet is shorter)
    for a row with any cell whose text starts with "criterion" (case-insensitive) -- the
    same detection text the source fixer's `criteria_sheet()` uses, just no longer
    restricted to row 1. Returns the 1-based row index of the first matching row, or None
    if nothing in the scanned window matches."""
    last_row = min(max_scan, ws.max_row) if ws.max_row else 0
    for row in range(1, last_row + 1):
        for c in ws[row]:
            if c.value and str(c.value).strip().lower().startswith("criterion"):
                return row
    return None


def find_criteria_sheets(wb):
    """Every worksheet that looks like a criteria table, generalized from the source's
    single-sheet `criteria_sheet()` to check ALL matches instead of stopping at the first,
    and from a row-1-only sniff to a scan of each sheet's first HEADER_SCAN_ROWS rows (see
    `find_header_row`), since a real header is not always on row 1.

    Returns a list of (worksheet, header_row, header_confirmed) tuples. Falls back to the
    workbook's last sheet (same fallback the source uses) only when NO sheet in the whole
    workbook has a header anywhere in its scanned window; that fallback sheet is returned
    with header_row=1 and header_confirmed=False exactly as before, so downstream code still
    has a row to key off and the report still flags the read as a guess."""
    matches = []
    for ws in wb.worksheets:
        header_row = find_header_row(ws)
        if header_row is not None:
            matches.append((ws, header_row, True))
    if matches:
        return matches
    if wb.worksheets:
        return [(wb.worksheets[-1], 1, False)]
    return []


def group_by_normalized_id(pairs) -> dict:
    """Groups (raw_id, occurrence) pairs by `str(raw_id).strip()` -- the exact normalization
    this whole script uses everywhere a criterion/verifier id is compared (see module docstring
    point 3). Factored out of check_file()'s inner loop so the SVC-PC xlsx path and the EKW
    verifier-name path (check_task_dir(), below) call one shared implementation instead of two
    copies that could silently drift apart. A blank or missing raw_id is skipped, matching
    check_file()'s pre-existing blank-cell skip; callers may also pre-filter blanks before
    calling this (as check_file() does) -- either way produces the same grouping."""
    by_norm: dict[str, list] = collections.defaultdict(list)
    for raw_id, occ in pairs:
        if raw_id is None or str(raw_id).strip() == "":
            continue
        by_norm[str(raw_id).strip()].append(occ)
    return by_norm


def row_cells(ws, row: int, header_row: int) -> dict:
    """Every column of one row, keyed by that column's own header text read from
    `header_row` (falling back to a column-letter label when the header cell is blank), so
    the report shows a colliding row's full content regardless of a specific rubric's
    column layout or where its header actually sits."""
    out = {}
    for col in range(1, ws.max_column + 1):
        h = ws.cell(row=header_row, column=col).value
        key = (
            str(h).strip()
            if h not in (None, "")
            else f"col_{openpyxl.utils.get_column_letter(col)}"
        )
        out[key] = to_jsonable(ws.cell(row=row, column=col).value)
    return out


# ---------------------------------------------------------------------------
# per-file check
# ---------------------------------------------------------------------------


def check_file(path: Path) -> dict:
    """Returns one result dict for one rubric file. Never raises -- a load failure on the
    whole file is reported as a single load_error, not a crash that would kill the batch.
    """
    result = {
        "file": str(path),
        "load_error": None,
        "sheets_checked": [],
        "collisions": [],
    }

    try:
        wb = openpyxl.load_workbook(path, data_only=False)
    except Exception as e:
        result["load_error"] = f"openpyxl could not open this file: {e}"
        result["status"] = "fail"
        return result

    for ws, header_row, header_confirmed in find_criteria_sheets(wb):
        pairs = []
        for r in range(header_row + 1, ws.max_row + 1):
            v = ws.cell(row=r, column=1).value
            if v is None or str(v).strip() == "":
                continue
            pairs.append(
                (
                    v,
                    {
                        "row": r,
                        "raw_id": to_jsonable(v),
                        "cells": row_cells(ws, r, header_row),
                    },
                )
            )
        by_norm_id = group_by_normalized_id(pairs)

        result["sheets_checked"].append(
            {
                "sheet": ws.title,
                "header_row": header_row,
                "header_confirmed": header_confirmed,
                "n_ids": sum(len(occ) for occ in by_norm_id.values()),
            }
        )

        for norm, occurrences in by_norm_id.items():
            if len(occurrences) > 1:
                result["collisions"].append(
                    {
                        "sheet": ws.title,
                        "normalized_id": norm,
                        "occurrences": occurrences,
                    }
                )

    result["status"] = "fail" if result["collisions"] else "pass"
    return result


# ---------------------------------------------------------------------------
# task-directory mode (EKW port): --all / <TASK-ID...>, entered only when requested on the
# CLI -- see module docstring's "EKW port" paragraph. The default --root-is-a-rubric-file(s)
# mode above is untouched by anything below this point.
# ---------------------------------------------------------------------------


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "") -> list[Path]:
    """Identical shape to deliverable_filename_check.py's and
    judge_criterion_name_duplicate_check.py's own find_task_dirs()."""
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


def _has_svc_pc_config(task_dir: Path) -> bool:
    """True if this task uses SVC-PC's judge.toml shape -- the same two-layout union
    (bare tests/deliverables/ and numbered tests/deliverables_NN/) rubric_schema_check.py and
    judge_criterion_name_duplicate_check.py both use, so format detection here can never
    disagree with theirs. Checked ahead of has_ekw_config() so an SVC-PC task's handling can
    never change even in the unobserved case where a task directory somehow carries both
    config shapes."""
    return bool(
        list(task_dir.glob("tests/deliverables/judge.toml"))
        or list(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def check_task_dir(task_dir: Path, glob: str) -> dict:
    """One task directory in --all/<TASK-ID...> mode. Returns a result dict; never raises --
    an unreadable file or an unparseable verifier.json is reported as a parse_error/skip, not a
    crash that would kill the batch.

    Branches on which config format this task uses (see module docstring's "EKW port"
    paragraph):

      SVC-PC (tests/deliverables[_NN]/judge.toml present): runs the existing, UNMODIFIED
      find_rubric_files() + check_file() pair, scoped to this one task directory -- the exact
      same rubric-xlsx scan this script has always done for any --root, just invoked per task
      instead of once globally. No detection logic here is new for this branch, BUT: only a
      file where check_file() actually found a confirmed "criterion"-headed sheet
      (header_confirmed True on at least one sheet) has its collisions counted. A built SVC-PC
      task directory recursively contains every business-data xlsx under environment/ and
      solution/ too (rate sheets, demand plans, whatever the task's own source documents are),
      none of which are the rubric this check exists to verify -- and check_file()'s own
      last-resort fallback (no sheet anywhere matched a "criterion" header -> guess the
      workbook's last sheet, header_confirmed False) will still scan such a file's column A and
      can "find" a collision in it that has nothing to do with a rubric at all. Confirmed
      empirically, not assumed: spot-checking this exact branch against a real SVC-PC package
      (a650x, copied locally, judge.toml present, zero real rubric xlsx anywhere in the tree)
      reported 8 false "collision" groups -- an insurance rate sheet's repeated carrier names
      ("Anthem Blue Cross" x3, "Guardian" x9) and a demand-planning workbook's repeated row
      labels ("Quarter", "Note", quarter numbers) -- every one of them from an unconfirmed
      fallback guess, none from an actual rubric sheet. The file (and its full check_file()
      result) still appears in files_checked either way, so nothing is hidden; only the
      confirmed-header requirement gates what counts toward collisions/status.

      EKW (has_ekw_config(task_dir) true, no judge.toml): ekw_verifier_json.load_ekw_criteria()
      supplies each verifier's name (for comparison) and full criterion dict (for report
      context); these run through group_by_normalized_id() -- the SAME collision logic
      check_file() uses, not a reimplementation. EKW has no per-task sheet/group concept, so
      every verifier in the task's one tests/verifier.json is a single comparison scope, the
      EKW analogue of one xlsx sheet.

      Neither format found: reported as status "skip" -- nothing for this check to verify.
    """
    result = {
        "task_id": task_dir.name,
        "format": None,
        "status": None,
        "files_checked": [],  # SVC-PC path only: one check_file() result per rubric file found
        "criteria_checked": 0,  # EKW path only: verifiers actually compared (parse errors excl.)
        "parse_errors": [],
        "collisions": [],
    }

    if _has_svc_pc_config(task_dir):
        result["format"] = "svc-pc"
        rubric_files = find_rubric_files(task_dir, glob)
        if not rubric_files:
            result["status"] = "skip"
            result["parse_errors"].append(
                f"SVC-PC task (judge.toml present) but no rubric file matching glob {glob!r} "
                "found under this task directory -- this script checks the pre-conversion "
                "rubric workbook, not judge.toml itself (see module docstring); nothing to "
                "verify here"
            )
            return result
        for fr in (check_file(p) for p in rubric_files):
            result["files_checked"].append(fr)
            if fr.get("load_error"):
                result["parse_errors"].append(f"{fr['file']}: {fr['load_error']}")
                continue
            any_confirmed = any(s["header_confirmed"] for s in fr["sheets_checked"])
            if not any_confirmed:
                # No sheet in this workbook ever matched a real "criterion"-prefixed header --
                # check_file() fell back to guessing at the workbook's last sheet instead (see
                # find_criteria_sheets()). Scanning a whole task directory (this branch's scope)
                # sweeps up every unrelated xlsx a real SVC-PC package ships, and an unconfirmed
                # guess against one of those is noise, not a rubric defect (see this function's
                # own docstring for the exact false-positive case that proved it). Recorded, not
                # silently dropped: the file's full check_file() result is still in
                # files_checked, this just excludes it from collisions/status.
                result["parse_errors"].append(
                    f"{fr['file']}: no confirmed 'criterion'-headed sheet found -- excluded "
                    "from collision reporting (not a rubric-shaped file, or fallback guess only)"
                )
                continue
            for c in fr["collisions"]:
                result["collisions"].append({**c, "file": fr["file"]})
        result["status"] = "fail" if result["collisions"] else "pass"
        return result

    if has_ekw_config(task_dir):
        result["format"] = "ekw"
        criteria = load_ekw_criteria(task_dir)
        pairs = []
        for idx, c in enumerate(criteria):
            if c.get("name") == "__parse_error__":
                # load_ekw_criteria()'s own error convention: every unparseable verifier.json
                # (or malformed array entry) carries the literal name "__parse_error__". Two
                # independent parse failures in the same task would otherwise share that literal
                # string and register as a false duplicate-id collision -- an artifact of the
                # error convention, not a real criterion id, so it is excluded from comparison
                # and surfaced here instead.
                result["parse_errors"].append(
                    c.get("description") or "tests/verifier.json parse error"
                )
                continue
            occ = {"index": idx, "raw_id": c.get("name"), "criterion": c}
            pairs.append((c.get("name"), occ))
        result["criteria_checked"] = len(pairs)
        by_norm_id = group_by_normalized_id(pairs)
        result["collisions"] = [
            {
                "sheet": "tests/verifier.json",
                "normalized_id": norm,
                "occurrences": occurrences,
            }
            for norm, occurrences in by_norm_id.items()
            if len(occurrences) > 1
        ]
        result["status"] = "fail" if result["collisions"] else "pass"
        return result

    result["format"] = "none"
    result["status"] = "skip"
    result["parse_errors"].append(
        "neither tests/deliverables[_NN]/judge.toml (SVC-PC) nor tests/verifier.json (EKW) "
        "found under this task directory -- nothing for this check to verify"
    )
    return result


def run_task_directory_mode(args) -> int:
    """--all / <TASK-ID...> entry point. Mirrors deliverable_filename_check.py's and
    judge_criterion_name_duplicate_check.py's main-loop shape (per-task try/except so one
    task's crash can't kill the batch, aggregate JSON with the same generated/root/n_* fields,
    same stderr progress line, same exit contract: 1 if any task fails, 0 otherwise)."""
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
            r = check_task_dir(task_dir, args.glob)
        except Exception as e:  # never let one task's crash kill the whole batch
            r = {
                "task_id": task_dir.name,
                "format": "error",
                "status": "fail",
                "files_checked": [],
                "criteria_checked": 0,
                "parse_errors": [f"unhandled exception checking this task: {e}"],
                "collisions": [],
            }
        results.append(r)
        print(
            f"    -> {r['status']}  (format={r['format']}, "
            f"{len(r['collisions'])} colliding id group(s))",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    n_svc_pc = sum(1 for r in results if r["format"] == "svc-pc")
    n_ekw = sum(1 for r in results if r["format"] == "ekw")
    total_collisions = sum(len(r["collisions"]) for r in results)
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "mode": "task-directory",
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_skip": n_skip,
        "n_format_svc_pc": n_svc_pc,
        "n_format_ekw": n_ekw,
        "total_collision_groups": total_collisions,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_skip} skip out of {len(results)} task(s)  "
        f"(svc-pc={n_svc_pc}, ekw={n_ekw}, {total_collisions} colliding id group(s) total)"
    )
    for r in results:
        tag = (
            f"  [{len(r['collisions'])} colliding id group(s)]"
            if r["collisions"]
            else ""
        )
        print(f"  {r['task_id']} ({r['format']}): {r['status']}{tag}")
        for pe in r["parse_errors"]:
            print(f"      ! {pe}")
        for c in r["collisions"]:
            where = ", ".join(
                f"{o.get('row', o.get('index'))}={o['raw_id']!r}"
                for o in c["occurrences"]
            )
            print(
                f"      sheet {c['sheet']!r}: id {c['normalized_id']!r} collides -- {where}"
            )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 1 if n_fail else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Report-only detector for duplicate criterion ids in a rubric workbook. "
            "Detects any two rows whose id collides after str(value).strip() normalization "
            "(the same normalization the source fixer uses) and prints both full rows so a "
            "human can judge whether it's a real duplicate or an id typo. Never writes to "
            "the file it reads -- there is no --apply/fix mode."
        )
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help=(
            "one or more task ids (directory names under --root). Passing this or --all "
            "switches --root's meaning from 'a rubric file, or a directory to search "
            "recursively for rubric files' (the original, default usage -- unaffected if "
            "neither is passed) to 'a directory containing one subdirectory per task' (EKW "
            "port's task-directory mode, see module docstring's 'EKW port' paragraph)"
        ),
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="task-directory mode: run every task directory found under --root",
    )
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help=(
            "a single rubric .xlsx file, or a directory to search recursively for rubric "
            "files -- OR, with --all/<TASK-ID...>, a directory containing one subdirectory "
            "per task (REQUIRED -- no default, this must never silently assume a "
            "project-specific path)"
        ),
    )
    ap.add_argument(
        "--glob",
        default="*.xlsx",
        help=(
            "glob pattern used to find rubric files when --root (or, in task-directory mode, "
            "each task directory) is searched (default: *.xlsx, matching the source fixer's "
            "own file scope; pass e.g. --glob '*.xlsm' or --glob '**/*rubric*.xlsx' to widen "
            "or narrow the search)"
        ),
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="task-directory mode only: when using --all, only treat subdirectories starting "
        "with this prefix as tasks (default: empty, i.e. every subdirectory is a task)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

    root: Path = args.root
    if not root.exists():
        print(f"--root does not exist: {root}", file=sys.stderr)
        return 1

    if args.all or args.task_ids:
        return run_task_directory_mode(args)

    files = find_rubric_files(root, args.glob)
    if not files:
        print(
            f"No rubric files found under {root} (glob={args.glob!r}).",
            file=sys.stderr,
        )
        return 1

    results = []
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path} ...", file=sys.stderr)
        try:
            r = check_file(path)
        except Exception as e:  # never let one file's crash kill the whole batch
            r = {
                "file": str(path),
                "status": "fail",
                "load_error": f"unhandled exception checking this file: {e}",
                "sheets_checked": [],
                "collisions": [],
            }
        results.append(r)
        print(
            f"    -> {r['status']}  ({len(r['collisions'])} colliding id group(s))",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(root),
        "glob": args.glob,
        "n_files": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "results": results,
    }

    print(f"\n{n_pass} pass / {n_fail} fail out of {len(results)} rubric file(s)")
    for r in results:
        tag = (
            f"  [{len(r['collisions'])} colliding id group(s)]"
            if r["collisions"]
            else ""
        )
        print(f"  {r['file']}: {r['status']}{tag}")
        if r.get("load_error"):
            print(f"      ! {r['load_error']}")
        for c in r["collisions"]:
            where = ", ".join(
                f"row {o['row']} = {o['raw_id']!r}" for o in c["occurrences"]
            )
            print(
                f"      sheet {c['sheet']!r}: id {c['normalized_id']!r} collides -- {where}"
            )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
