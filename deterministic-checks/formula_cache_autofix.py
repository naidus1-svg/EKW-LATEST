"""Mechanical fixer for the uncached-formula-value defect class (formula_health_check.py findings).

Provenance: extracted and generalized from a QC pipeline built for one benchmark; no
benchmark-specific assumptions remain (see formula_health_check.py's own provenance note).
Status: v1, battle-tested at scale in its source project.

Companion to formula_health_check.py (read that module's docstring first -- this
script reuses its task/file discovery, per-cell classification, and whole-file cache-wipe
detection so a task's eligibility here matches that check's own pass/fail gate exactly). This
script is deliberately dumber than the health check: it makes NO judgment calls about whether a
formula's LOGIC is correct. It only ever does one thing -- take a formula cell whose live,
freshly-recomputed value (via the `formulas` library, same engine the health check uses) is a
real value, and whose file-on-disk cached <v> disagrees with or is missing that value, and
overwrite ONLY that <v> element via raw zip/XML surgery. The formula text itself
(<f>...</f>) is never touched. No other cell, no styling, no sharedStrings, no other zip entry
is ever rewritten.

Why this exists: a golden .xlsx can have entirely correct live formulas but a stale or null
cached <v> because it was saved (by openpyxl, or an upstream xlsm->xlsx conversion step) without
a real Excel recalculation. openpyxl's own save() strips every cached formula result
unconditionally on load+save, regardless of whether the formula is broken -- see
svc_formula_health_check.py's "whole-file cache wipe" section. The production read path
(the pipeline's converters.py _xlsx_to_text, and harbor's xlsx.py ExtractText) opens workbooks
with data_only=True, so it only ever sees the cache -- never re-derives it from the formula. A
grading pass over such a file sees blank/null cells for perfectly good formulas. This script
patches exactly that gap, mechanically, with no LLM judgment involved.

What counts as "mechanical" here, and what does not
----------------------------------------------------
The health check classifies every formula cell into one of: recompute_error, recompute_blank,
stale_cache_blank, value_mismatch, or unresolved_by_engine (see that module's docstring for the
full definitions). Only two of those are things this script can EVER validly fix, because only
for those two does a live recompute actually hand back a concrete, usable value to write:

  - stale_cache_blank : cache is blank, live recompute is a real value -> write the recompute.
  - value_mismatch     : cache holds a real-but-wrong number, live recompute is a different real
                          number -> write the recompute. This script never audits whether the
                          FORMULA is the right formula for the rubric; it only ever asserts "the
                          cell's own formula, evaluated for real, produces X" and writes X. A
                          task where the formula itself is wrong (not just its cache) is a
                          content/design defect for a human to fix, not a caching gap -- but this
                          script has no way to distinguish that from a plain stale cache by
                          looking at one file in isolation, so treat any external signal that a
                          task's formula LOGIC (not its cache) is suspect as a reason to route
                          that task through judgment instead (see --root task selection notes).

recompute_error and unresolved_by_engine are never touched -- there is no valid value to write.

recompute_blank is ALSO never touched, and is treated as a **skip trigger** (same bucket as
recompute_error), even though the task brief that commissioned this script listed
"stale_cache_blank / recompute_blank / value_mismatch-where-formula-logic-is-correct" together
as "pure caching gaps." That grouping does not survive contact with the health check's own
definition: recompute_blank means the LIVE, freshly-recomputed value is itself None/NaN -- i.e.
the formulas engine resolved the cell but got nothing real out of it. There is no correct value
to write into the cache for a cell like that; writing anything would be fabricating a number, not
recovering one. Any task carrying a recompute_blank finding is reported as "needs judgment", not
silently auto-fixed and not silently skipped-without-explanation. This is a deliberate, disclosed
deviation from the literal brief, not an oversight -- see validate() and the module-level
docstring test in this file's own validation run.

Two more safety nets beyond the kind-based gate:
  1. Even for stale_cache_blank/value_mismatch findings, the RAW recomputed value (before any
     JSON-serialization) is checked with is_patchable(): reject None, NaN, an Excel error token,
     or (importantly) an empty/whitespace-only string. A formula that legitimately evaluates to
     "" can never be made to look "non-blank" to the health check's own is-blank test (which
     treats "" as blank) -- no value this script could write would ever change that cell's
     classification, so such a task is reported as unfixable-by-this-tool rather than silently
     writing a no-op.
  2. Whole-file cache-wipe suppression (SVC-PC-58-7-0's own documented false-positive shape) is
     inherited verbatim from the health check's _finalize_findings -- a file where almost every
     formula cell is blank-cache and none are hard breaks is already "pass" under Check E, so
     this script finds zero actionable findings and makes zero writes. Confirmed in validation.

Fix mechanism (never openpyxl.save())
--------------------------------------
openpyxl's Workbook.save() rewrites the ENTIRE file structure -- it silently drops every other
cached formula result in the workbook (see the health check's whole-file-wipe note), can reflow
styles, and is exactly the operation that created this defect class upstream in the first place.
Never used here. Instead:
  1. Open the .xlsx/.xlsm as a plain zip (zipfile), read every entry's raw bytes verbatim.
  2. Parse xl/workbook.xml + xl/_rels/workbook.xml.rels to map sheet NAME -> the exact
     xl/worksheets/sheetN.xml zip entry that sheet lives in.
  3. For each cell to patch, parse only that one sheet's XML with lxml, locate the <c r="..">
     element, and set/replace its <v> child text (and its `t` type attribute if the value's
     Excel type changed -- e.g. was never cached at all, so had no `t`, now holds a string
     result and needs t="str"). The <f> formula text is never modified. No other <c> in that
     sheet, and no other zip entry at all, is touched.
  4. Rewrite the zip, copying every untouched entry's bytes byte-for-byte and substituting only
     the edited sheet XML(s).
  5. Re-open the patched file fresh and re-run the exact same health-check analysis on it,
     confirming 0 actionable findings, AND independently re-running `formulas` on the patched
     file to confirm every value now cached matches a brand new recompute (not just trusting the
     in-memory values computed before the write). Any mismatch reverts the file from its backup
     and reports the task as failed, rather than leaving a half-fixed file on disk.

Originals are always backed up to "<file>.orig" next to the file before the first write (never
overwritten by a later run, so a second run's backup is never clobbered by an already-patched
copy). --dry-run makes no writes and no backups at all.

CLI (mirrors formula_health_check.py):
    python formula_cache_autofix.py TASK-1 TASK-2 --root <path> --out report.json
    python formula_cache_autofix.py --all --root <path> --dry-run
"""

import argparse
import io
import json
import math
import shutil
import subprocess
import sys
import warnings
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

# Reuse the health check's own discovery, classification, and cache-wipe-suppression logic
# verbatim, so a task's eligibility here can never silently drift from what the health check
# itself considers pass/fail. See module docstring.
import formula_health_check as health  # noqa: E402

try:
    import openpyxl
except ImportError:  # pragma: no cover
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl

try:
    import formulas
except ImportError:  # pragma: no cover
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "formulas", "--quiet"], check=True
    )
    import formulas

try:
    from lxml import etree as ET
except ImportError:  # pragma: no cover
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "lxml", "--quiet"], check=True
    )
    from lxml import etree as ET

ERR_TOKENS = health.ERR_TOKENS

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_DOC_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NSMAP = {"m": MAIN_NS}

# Findings of these kinds mean "this file needs a human, not this script" -- see module
# docstring for why recompute_blank is grouped here despite the originating brief's wording.
BLOCKING_KINDS = {"recompute_error", "unresolved_by_engine", "recompute_blank"}
FIXABLE_KINDS = {"stale_cache_blank", "value_mismatch"}

EXCEL_EPOCH = datetime(
    1899, 12, 30
)  # Excel's day-0, accounting for the 1900 leap-year bug


# ---------------------------------------------------------------------------
# raw-value analysis (mirrors health.analyze_workbook, but keeps RAW python values
# instead of running them through health.to_jsonable, which is lossy for our purposes --
# e.g. it stringifies NaN to "NaN" and datetimes to an ISO string, either of which would
# break the numeric/date formatting this script needs to write back into the XML).
# ---------------------------------------------------------------------------


def analyze_workbook_raw(path):
    """Returns (findings, meta, recomputed_map) exactly like health.analyze_workbook, PLUS:
      - each finding here carries an extra 'raw_recomputed' key holding the un-serialized python
        value (not run through to_jsonable), so patch values keep their real type
        (int/float/bool/str/datetime).
      - recomputed_map: {(SHEET_UPPER, cell_ref): raw_normalized_value} for EVERY live formula
        cell in the file (not just the ones with findings) -- lets a caller (verify_fix) reuse
        this ONE fresh `formulas` evaluation to spot-check specific cells instead of re-loading
        and re-calculating the whole workbook again per cell (that repeated-reload was a real
        bug here during validation: reloading a 775-cell, 5-sheet workbook once per candidate
        cell instead of once per file made a full-corpus run impractically slow).
    Classification, matching-criteria (skipped -- irrelevant to autofix), and the whole-file
    cache-wipe actionable/suppression logic are identical to the health check's own, achieved by
    calling health._finalize_findings directly rather than reimplementing it.
    """
    findings = []
    meta = {"n_formula_cells": 0, "load_error": None}
    recomputed_map = {}

    try:
        wb_formula = openpyxl.load_workbook(str(path), data_only=False)
        wb_cached = openpyxl.load_workbook(str(path), data_only=True)
    except Exception as e:
        meta["load_error"] = f"openpyxl could not open this file: {e}"
        return findings, meta, recomputed_map

    formula_map = {}
    for ws in wb_formula.worksheets:
        if ws.title not in wb_cached.sheetnames:
            continue
        ws_cached = wb_cached[ws.title]
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    key = (ws.title.upper(), cell.coordinate)
                    formula_map[key] = {
                        "sheet": ws.title,
                        "cell": cell.coordinate,
                        "formula": cell.value,
                        "label": health.nearest_left_label(ws, cell.row, cell.column),
                        "cached": ws_cached.cell(
                            row=cell.row, column=cell.column
                        ).value,
                    }
    meta["n_formula_cells"] = len(formula_map)

    if not formula_map:
        return findings, meta, recomputed_map

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            xl_model = formulas.ExcelModel().loads(str(path)).finish()
            solution = xl_model.calculate()
    except Exception as e:
        meta["load_error"] = (
            f"`formulas` library could not load/calculate this file: {e}"
        )
        for info in formula_map.values():
            findings.append(
                {
                    "sheet": info["sheet"],
                    "cell": info["cell"],
                    "formula": info["formula"],
                    "row_label": info["label"],
                    "cached_value": health.to_jsonable(info["cached"]),
                    "recomputed_value": None,
                    "raw_recomputed": None,
                    "kind": "unresolved_by_engine",
                    "severity": "info",
                    "error": None,
                }
            )
        return health._finalize_findings(findings, meta), meta, recomputed_map

    recomputed = {}
    for k, v in solution.items():
        m = health.SOLUTION_KEY_RE.match(k)
        if not m:
            continue
        recomputed[(m.group("sheet").upper(), m.group("cell"))] = (
            health.unwrap_formulas_value(v)
        )

    for key, info in formula_map.items():
        resolved = key in recomputed
        rv = recomputed.get(key)
        raw_rv = normalize_scalar(rv) if resolved else None
        recomputed_map[key] = raw_rv
        c = health.classify_cell(info["formula"], info["cached"], rv, resolved=resolved)
        if c is None:
            continue
        findings.append(
            {
                "sheet": info["sheet"],
                "cell": info["cell"],
                "formula": info["formula"],
                "row_label": info["label"],
                "cached_value": health.to_jsonable(info["cached"]),
                "recomputed_value": health.to_jsonable(rv),
                "raw_recomputed": raw_rv,
                "kind": c["kind"],
                "severity": c["severity"],
                "error": c.get("error"),
            }
        )

    return health._finalize_findings(findings, meta), meta, recomputed_map


def normalize_scalar(v):
    """Collapse numpy scalar types down to plain python (int/float/bool/str/datetime/None),
    keeping NaN as a real float NaN (never stringified) so is_patchable can detect it.
    """
    if v is None or isinstance(v, (bool, str, datetime)):
        return v
    if isinstance(v, (int, float)):
        return v
    try:
        import numpy as np

        if isinstance(v, np.bool_):
            return bool(v)
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, np.floating):
            return float(v)
        if isinstance(v, np.str_):
            return str(v)
    except ImportError:
        pass
    return v


def is_patchable(v):
    """Whether `v` is a concrete value this script may legally write into a cache <v> element.
    See module docstring point 1 for why empty-string is excluded."""
    if v is None:
        return False
    if isinstance(v, float) and math.isnan(v):
        return False
    if isinstance(v, str):
        if v.strip() == "":
            return False
        if any(tok in v for tok in ERR_TOKENS):
            return False
    return True


# ---------------------------------------------------------------------------
# eligibility
# ---------------------------------------------------------------------------


def classify_task(findings):
    """Decide, from a task's pooled findings across every spreadsheet, whether this task is
    mechanically fixable, already clean, or needs a human. Returns a dict:
        status: "clean" | "fixable" | "needs_judgment"
        reasons: [str, ...]  (populated for needs_judgment)
        to_patch: [finding, ...]  (populated for fixable -- exactly the cells to write)
    """
    reasons = []
    blocking = [f for f in findings if f["kind"] in BLOCKING_KINDS]
    if blocking:
        by_kind = {}
        for f in blocking:
            by_kind.setdefault(f["kind"], []).append(
                f"{f['file']}:{f['sheet']}!{f['cell']}"
            )
        for kind, cells in by_kind.items():
            if kind == "recompute_blank":
                reasons.append(
                    f"{len(cells)} recompute_blank cell(s) ({', '.join(cells[:5])}"
                    f"{', ...' if len(cells) > 5 else ''}): the LIVE recomputed value is itself "
                    "blank/NaN, so there is no valid value this script could write -- needs a "
                    "human, not treated as a caching gap despite the kind name overlapping with "
                    "the caching-gap list (see module docstring)."
                )
            elif kind == "recompute_error":
                reasons.append(
                    f"{len(cells)} recompute_error cell(s) ({', '.join(cells[:5])}"
                    f"{', ...' if len(cells) > 5 else ''}): genuine broken formula chain."
                )
            else:
                reasons.append(
                    f"{len(cells)} unresolved_by_engine cell(s) ({', '.join(cells[:5])}"
                    f"{', ...' if len(cells) > 5 else ''}): the `formulas` engine could not "
                    "evaluate these at all; this script cannot confirm what they should be."
                )
        return {"status": "needs_judgment", "reasons": reasons, "to_patch": []}

    # Deliberately NOT gated on health._finalize_findings' `actionable` flag. That flag exists
    # so Check E's corpus-wide sweep doesn't fail a task over a whole-file cache wipe it can't
    # attribute to a targeted defect (the documented xlsm->xlsx build-time conversion shim --
    # see SVC-PC-58-7-0). It is a reporting decision about whether to gate the TASK to fail, not
    # a safety verdict about whether WRITING the recomputed value is correct. Writing a cell's
    # own freshly-recomputed value into its own cache is safe regardless of what fraction of the
    # file is blank -- confirmed empirically: SVC-PC-50-3-0/50-4-0/50-5-0's real pre-fix state
    # (ekw/.scratch_975_backup/*.orig) was ALSO a >=90%-blank uniform-cache-wipe shape
    # (91.5%/100% blank, 0 hard breaks) by this exact heuristic, and were patched anyway -- the
    # suppression flag would have wrongly reported them "clean" if honored here. So: every
    # finding of a FIXABLE_KINDS kind is a candidate, actionable-suppressed or not. The
    # cache_blank_fraction/uniform_cache_wipe shape is still surfaced per-file in the report
    # (files_analyzed) for a reader's own judgment -- e.g. to recognize "this looks like the
    # known shim artifact" -- but it never silently withholds a fix.
    candidates = [f for f in findings if f["kind"] in FIXABLE_KINDS]
    if not candidates:
        return {"status": "clean", "reasons": [], "to_patch": []}

    unpatchable = [f for f in candidates if not is_patchable(f["raw_recomputed"])]
    if unpatchable:
        for f in unpatchable:
            reasons.append(
                f"{f['file']}:{f['sheet']}!{f['cell']} is classified '{f['kind']}' but its "
                f"recomputed value ({f['recomputed_value']!r}) is not a concrete value this "
                "script may write (blank/NaN/empty-string) -- the health check's own is-blank "
                "test can never be satisfied by anything this script writes here, so this task "
                "cannot be mechanically closed out; needs a human."
            )
        return {"status": "needs_judgment", "reasons": reasons, "to_patch": []}

    return {"status": "fixable", "reasons": [], "to_patch": candidates}


# ---------------------------------------------------------------------------
# XML / zip surgery
# ---------------------------------------------------------------------------


def _local(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def map_sheet_name_to_zip_path(zip_data):
    wb_root = ET.fromstring(zip_data["xl/workbook.xml"])
    rels_root = ET.fromstring(zip_data["xl/_rels/workbook.xml.rels"])

    rid_to_target = {}
    for rel in rels_root:
        if _local(rel.tag) != "Relationship":
            continue
        rid_to_target[rel.get("Id")] = rel.get("Target")

    sheet_map = {}
    sheets_el = wb_root.find(f"{{{MAIN_NS}}}sheets")
    for sheet_el in sheets_el:
        name = sheet_el.get("name")
        rid = sheet_el.get(f"{{{REL_DOC_NS}}}id")
        target = rid_to_target.get(rid)
        if not target:
            continue
        if target.startswith("/"):
            full = target.lstrip("/")
        else:
            # Targets are relative to xl/ -- normalize any ../ segments defensively.
            parts = ("xl/" + target).split("/")
            stack = []
            for p in parts:
                if p == "..":
                    if stack:
                        stack.pop()
                elif p and p != ".":
                    stack.append(p)
            full = "/".join(stack)
        sheet_map[name] = full
    return sheet_map


def excel_serial(dt):
    delta = dt - EXCEL_EPOCH
    return delta.days + delta.seconds / 86400.0 + delta.microseconds / 86400000000.0


def format_number(f):
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return repr(float(f))


def format_value_for_xml(value):
    """Returns (v_text, t_attr_or_None) for a python scalar. t_attr_or_None is the OOXML cell
    type to set on <c t="...">; None means "remove the t attribute" (plain numeric, OOXML's
    default when t is absent)."""
    if isinstance(value, bool):
        return ("1" if value else "0"), "b"
    if isinstance(value, datetime):
        return format_number(excel_serial(value)), None
    if isinstance(value, (int, float)):
        return format_number(float(value)), None
    if isinstance(value, str):
        return value, "str"
    return str(value), "str"


def patch_sheet_xml(xml_bytes, cell_patches):
    """cell_patches: list of (cell_ref, value). Returns (new_xml_bytes, applied, not_found)."""
    root = ET.fromstring(xml_bytes)
    applied = []
    not_found = []
    for cell_ref, value in cell_patches:
        c_el = root.find(f'.//{{{MAIN_NS}}}c[@r="{cell_ref}"]')
        if c_el is None:
            not_found.append(cell_ref)
            continue
        v_text, t_attr = format_value_for_xml(value)
        v_el = c_el.find(f"{{{MAIN_NS}}}v")
        if v_el is None:
            v_el = ET.SubElement(c_el, f"{{{MAIN_NS}}}v")
        v_el.text = v_text
        if t_attr is None:
            if "t" in c_el.attrib:
                del c_el.attrib["t"]
        else:
            c_el.set("t", t_attr)
        applied.append(cell_ref)
    new_bytes = ET.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    return new_bytes, applied, not_found


def patch_workbook_file(path, patches_by_sheet, backup=True):
    """patches_by_sheet: {sheet_name: [(cell_ref, value), ...]}. Rewrites `path` in place,
    touching only the affected xl/worksheets/sheetN.xml entries; every other zip entry is
    copied byte-for-byte. Returns a report dict."""
    path = Path(path)
    report = {"applied": {}, "not_found": {}, "sheet_not_mapped": []}

    with zipfile.ZipFile(path, "r") as z:
        infos = z.infolist()
        zip_data = {info.filename: z.read(info.filename) for info in infos}

    sheet_map = map_sheet_name_to_zip_path(zip_data)

    touched = {}  # zip_path -> new bytes
    for sheet_name, cell_patches in patches_by_sheet.items():
        zip_path = sheet_map.get(sheet_name)
        if not zip_path or zip_path not in zip_data:
            report["sheet_not_mapped"].append(sheet_name)
            continue
        source = touched.get(zip_path, zip_data[zip_path])
        new_bytes, applied, not_found = patch_sheet_xml(source, cell_patches)
        touched[zip_path] = new_bytes
        report["applied"][sheet_name] = applied
        if not_found:
            report["not_found"][sheet_name] = not_found

    if not touched:
        return report

    if backup:
        orig_backup = path.with_suffix(path.suffix + ".orig")
        if not orig_backup.exists():
            shutil.copy2(path, orig_backup)
        report["backup"] = str(orig_backup)

    buf = io.BytesIO()
    with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(
        buf, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            data = touched.get(info.filename, zip_data[info.filename])
            # Preserve original ZipInfo (compression type, date_time, external_attr) so the
            # rewritten archive stays structurally identical apart from the edited bytes.
            new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new_info.compress_type = info.compress_type
            new_info.external_attr = info.external_attr
            new_info.internal_attr = info.internal_attr
            new_info.create_system = info.create_system
            zout.writestr(new_info, data)

    bad = None
    with zipfile.ZipFile(buf) as ztest:
        bad = ztest.testzip()
    if bad is not None:
        raise RuntimeError(f"patched zip failed integrity check on entry: {bad}")

    with open(path, "wb") as f:
        f.write(buf.getvalue())

    return report


# ---------------------------------------------------------------------------
# per-task orchestration
# ---------------------------------------------------------------------------


def gather_task_findings(task_dir):
    """Runs analyze_workbook_raw over every spreadsheet under task_dir/solution/, returns the
    pooled findings list (each tagged with 'file') plus per-file meta, mirroring
    health.analyze_task's file loop but keeping raw values."""
    spreadsheets = health.find_spreadsheets(task_dir)
    all_findings = []
    files_meta = []
    errors = []
    for path in spreadsheets:
        rel = str(path.relative_to(task_dir)).replace("\\", "/")
        findings, meta, _recomputed_map = analyze_workbook_raw(path)
        for f in findings:
            f["file"] = rel
        all_findings.extend(findings)
        files_meta.append(
            {
                "path": rel,
                "n_formula_cells": meta["n_formula_cells"],
                "n_findings": len(findings),
                "load_error": meta["load_error"],
                "cache_blank_fraction": meta.get("cache_blank_fraction", 0.0),
                "uniform_cache_wipe": meta.get("uniform_cache_wipe", False),
            }
        )
        if meta["load_error"]:
            errors.append(f"{rel}: {meta['load_error']}")
    return spreadsheets, all_findings, files_meta, errors


def apply_fix(task_dir, to_patch):
    """to_patch: findings (each has file/sheet/cell/raw_recomputed). Groups by file, patches
    each file, returns per-file patch reports keyed by relative file path."""
    by_file = {}
    for f in to_patch:
        by_file.setdefault(f["file"], {}).setdefault(f["sheet"], []).append(
            (f["cell"], f["raw_recomputed"])
        )

    reports = {}
    for rel_file, patches_by_sheet in by_file.items():
        abs_path = task_dir / rel_file
        reports[rel_file] = patch_workbook_file(abs_path, patches_by_sheet, backup=True)
    return reports


def verify_fix(task_dir, patched_files, expected):
    """Re-runs analyze_workbook_raw fresh -- ONE brand-new `formulas` load+calculate per patched
    FILE, independent of anything computed before the write -- and checks two things per file:
      1. 0 actionable findings remain (the health check's own gate).
      2. Every cell we intended to patch now reads back (data_only=True) as a value that
         matches that SAME fresh recompute's own value for that cell -- not just "whatever we
         wrote", an independent second evaluation, not merely trusting the write.
    Both checks are answered from the ONE analyze_workbook_raw call per file (it already does a
    fresh load+calculate and returns recomputed_map for every formula cell) -- deliberately not
    a second reload per cell. An earlier version of this function called
    formulas.ExcelModel().loads(...).finish().calculate() inside the per-candidate loop, i.e.
    once per CELL rather than once per FILE; on a large multi-sheet workbook (SVC-PC-58-7-0,
    775 candidate cells) that reloaded and recalculated the entire workbook 775 times and made a
    full-corpus run impractical. Confirmed during this script's own validation run.
    Returns (ok: bool, detail: dict).
    """
    detail = {"remaining_actionable": [], "value_check": []}
    ok = True

    expected_by_file = {}
    for f in expected:
        expected_by_file.setdefault(f["file"], []).append(f)

    for rel_file in patched_files:
        abs_path = task_dir / rel_file
        findings, meta, recomputed_map = analyze_workbook_raw(abs_path)

        remaining = [f for f in findings if f.get("actionable", True)]
        if remaining:
            ok = False
            detail["remaining_actionable"].extend(
                {
                    "file": rel_file,
                    "sheet": f["sheet"],
                    "cell": f["cell"],
                    "kind": f["kind"],
                }
                for f in remaining
            )

        for f in expected_by_file.get(rel_file, []):
            key_target = (f["sheet"].upper(), f["cell"])
            found = key_target in recomputed_map
            fresh_val = recomputed_map.get(key_target)
            expected_val = f["raw_recomputed"]
            agree = found and _values_agree(fresh_val, expected_val)
            if not agree:
                ok = False
            detail["value_check"].append(
                {
                    "file": rel_file,
                    "sheet": f["sheet"],
                    "cell": f["cell"],
                    "written": health.to_jsonable(expected_val),
                    "fresh_recompute": health.to_jsonable(fresh_val),
                    "agree": agree,
                }
            )
    return ok, detail


def _values_agree(a, b):
    if (
        isinstance(a, (int, float))
        and not isinstance(a, bool)
        and isinstance(b, (int, float))
        and not isinstance(b, bool)
    ):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-6)
        except (TypeError, ValueError):
            return a == b
    return a == b


def revert_files(task_dir, patched_files):
    for rel_file in patched_files:
        abs_path = task_dir / rel_file
        backup = abs_path.with_suffix(abs_path.suffix + ".orig")
        if backup.exists():
            shutil.copy2(backup, abs_path)


# ---------------------------------------------------------------------------
# per-task driver
# ---------------------------------------------------------------------------


def process_task(task_dir, dry_run):
    task_id = task_dir.name
    result = {
        "task_id": task_id,
        "status": None,
        "reasons": [],
        "patched_files": [],
        "errors": [],
    }

    if not (task_dir / "solution").is_dir():
        result["status"] = "clean"
        result["reasons"] = ["no solution/ dir -- nothing for this script to check"]
        return result

    spreadsheets, findings, files_meta, errors = gather_task_findings(task_dir)
    result["errors"] = errors
    result["files_analyzed"] = files_meta

    if not spreadsheets:
        result["status"] = "clean"
        result["reasons"] = ["no .xlsx/.xlsm under solution/"]
        return result

    verdict = classify_task(findings)
    result["status"] = verdict["status"]
    result["reasons"] = verdict["reasons"]

    if verdict["status"] != "fixable":
        return result

    to_patch = verdict["to_patch"]
    result["cells_to_patch"] = [
        {
            "file": f["file"],
            "sheet": f["sheet"],
            "cell": f["cell"],
            "kind": f["kind"],
            "cached_value": f["cached_value"],
            "recomputed_value": f["recomputed_value"],
        }
        for f in to_patch
    ]

    if dry_run:
        result["status"] = "would_fix"
        return result

    patch_reports = apply_fix(task_dir, to_patch)
    result["patch_reports"] = patch_reports
    patched_files = list(patch_reports.keys())
    result["patched_files"] = patched_files

    ok, verify_detail = verify_fix(task_dir, patched_files, to_patch)
    result["verify"] = verify_detail

    if not ok:
        revert_files(task_dir, patched_files)
        result["status"] = "failed_reverted"
        result["reasons"].append(
            "post-fix verification failed (either the health check still found an actionable "
            "finding, or a fresh independent `formulas` recompute disagreed with what was "
            "written) -- file(s) reverted from .orig backup, no changes left on disk"
        )
        return result

    result["status"] = "fixed"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Mechanically patch stale/blank cached formula <v> values in golden "
        "workbooks (caching-gap findings only -- never touches formula logic)."
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="one or more task ids (directory names under --root)",
    )
    ap.add_argument(
        "--all", action="store_true", help="run every task dir found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        help="root directory containing one subdirectory per task (REQUIRED)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix as tasks",
    )
    ap.add_argument(
        "--out", type=Path, default=None, help="write the aggregate JSON report here"
    )
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    if args.root is None:
        ap.error(
            "--root is required (point it at the directory containing your task folders)"
        )

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    task_dirs = health.find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        sys.exit(1)

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = process_task(task_dir, args.dry_run)
        except Exception as e:
            r = {
                "task_id": task_dir.name,
                "status": "error",
                "reasons": [f"unhandled exception: {e}"],
            }
        results.append(r)
        print(f"    -> {r['status']}", file=sys.stderr)

    by_status = {}
    for r in results:
        by_status.setdefault(r["status"], []).append(r["task_id"])

    aggregate = {
        "tool": "svc_formula_cache_autofix",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "dry_run": args.dry_run,
        "n_tasks": len(results),
        "by_status": {k: len(v) for k, v in by_status.items()},
        "results": results,
    }

    print(
        f"\n{len(results)} task(s) processed" + (" (dry run)" if args.dry_run else "")
    )
    for status, ids in sorted(by_status.items()):
        print(
            f"  {status}: {len(ids)}  {ids if len(ids) <= 10 else ids[:10] + ['...']}"
        )
    for r in results:
        if r["status"] == "needs_judgment":
            print(f"  {r['task_id']} needs judgment:")
            for reason in r["reasons"]:
                print(f"      ! {reason}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
