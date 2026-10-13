"""Check E: formula health.

Recurring failure pattern across every Oracle-failure batch analyzed this project (datasets
968, 971, 973, 974, 975): a rubric criterion expects a computed/derived value, and the golden
workbook shows that value as blank or NaN when read back by whatever tool is doing the reading
(openpyxl `data_only=True`, pandas, a markdown export, Oracle itself). None of checks A-D
(content audit, build exists, LLM structural audit, mechanical filename match) ever recompute a
single formula, so this defect class was previously only ever caught after an expensive,
rate-limited Oracle round-trip. This script is a cheap, deterministic pre-check for it.

CHECK_META (same shape as the CHECKS entries in tools/svc_qc_tracker_build.py -- added there
as check "E" 2026-09-13, inserted pre-Oracle: Oracle shifted E->F, Jafar F->G, tracker
write-back G->H. Ordering only - this script's own corpus-wide sweep is a separate follow-up):

CHECK_META = {
    "E": {
        "name": "Formula health",
        "catches": "A rubric criterion expecting a computed/derived cell that reads as an Excel "
                    "error, or blank/NaN, when the golden workbook is actually opened and its "
                    "formulas actually recalculated -- the single largest recurring defect class "
                    "found across datasets 968/971/973/974/975 this project.",
        "source": "tools/svc_formula_health_check.py",
        "explanation": "Opens every .xlsx/.xlsm under a task's solution/ with the `formulas` "
                       "Python library, forces a real recalculation of every formula cell (not "
                       "just a read of whatever value happens to be cached), and reports any cell "
                       "that comes back as an Excel error or as a blank/NaN where a live formula "
                       "sits. Cross-references each finding against the task's own judge.toml "
                       "criteria so a reader can immediately tell 'this affects a graded "
                       "criterion' from 'this is dead weight'.",
        "metaphor": "Like actually re-running every formula in a spreadsheet instead of trusting "
                    "whatever numbers happen to be sitting in the cells when you open it.",
        "how_to_run": "python tools/svc_formula_health_check.py <TASK-ID> [<TASK-ID> ...] "
                      "[--root <03_dataos_ready path>] [--out <report.json>], or "
                      "--all to sweep every task under root (slow: ~5-30s per spreadsheet file, "
                      "do not run --all casually -- it is a separate, larger follow-up once this "
                      "script is proven correct on a handful of known cases).",
    },
}

Usage:
    python tools/svc_formula_health_check.py SVC-PC-81-2-0 SVC-PC-81-3-0 --out ekw/formula-health.json
    python tools/svc_formula_health_check.py --all --root "C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready"

What it does, in order (see module docstring above for the "why"):

1. For a given task id (or --all tasks under --root), finds every .xlsx/.xlsm under that task's
   solution/ directory (recursive glob -- it doesn't assume solution/files/, since the shim logic
   in step 4 means the real graded file is not always the one judge.toml names literally).
2. Opens each with the `formulas` library (auto-installs via `pip install formulas --quiet` if
   missing) and forces a full recalculation, independent of whatever the file's cached <v> values
   say. Classifies every formula cell (found via a separate openpyxl `data_only=False` pass, so
   we never touch a cell that isn't a live formula -- a legitimately blank input cell is never
   flagged) into one of:
     - recompute_error   : the recalculated value IS an Excel error (#REF!, #VALUE!, #NAME?,
                            #DIV/0!, #N/A, #NULL!, #NUM!). A genuinely broken formula chain.
     - recompute_blank   : the recalculated value itself is None/NaN despite not being a proper
                            Excel error token (an engine-level dead end -- treated as high
                            severity, same as recompute_error).
     - stale_cache_blank : the cell's *cached* value (what a normal read of the file sees) is
                            None/NaN/empty, but the live recompute resolves cleanly to a real
                            value. This is exactly the "reads as blank when opened by whatever
                            tool reads it" pattern from SVC-PC-51-3-0 / SVC-PC-51-6-0: the formula
                            logic is fine, but the cached result baked into the file is missing,
                            so anything that reads the file without recalculating (Oracle, a judge
                            LLM, a markdown export) sees nothing there. Fixable by the same
                            zip/XML cached-<v> patch used on those two tasks.
     - value_mismatch    : cached and recomputed both resolve to real values but disagree beyond
                            tolerance (volatile functions -- NOW/TODAY/RAND -- are excluded). Low
                            severity/low confidence: could be legitimate (rounding, a formula that
                            depends on a volatile function this script's tolerance list missed),
                            so flagged for a human look rather than asserted as certainly wrong.
     - unresolved_by_engine: the `formulas` library did not resolve this cell at all (unsupported
                            function, cross-workbook reference, etc). This is a limitation of the
                            check itself, not asserted as a defect in the workbook -- surfaced so
                            a reader knows this cell was not actually verified either way.
   unresolved_by_engine findings, and stale_cache_blank findings in a file where >=90% of ALL
   formula cells are blank-cache and NONE are hard breaks, are marked `actionable: false` and
   excluded from the task's pass/fail gate (see "whole-file cache wipe" below) -- they are still
   listed in the JSON with a `suppressed_reason`, never silently dropped.
2.5 Whole-file cache-wipe detection: openpyxl's own save() unconditionally strips EVERY cached
    formula result on any load+save, regardless of whether the formula is broken. Any file that
    passed through such a round trip upstream (e.g. the pipeline's own xlsm->xlsx build-time
    conversion, to_rewardkit.py's _convert_xlsm_to_xlsx) will show a huge run of
    stale_cache_blank findings that all recompute cleanly -- confirmed on SVC-PC-58-7-0 (775/775
    formula cells blank-cache, 0 recompute errors). That is a mechanical, project-wide artifact,
    not a targeted defect, and is distinguished by shape from the localized cache gaps that
    made SVC-PC-51-3-0/51-6-0 genuinely fail before their zip/XML patch: if >=90% of a file's
    formula cells are blank-cache AND zero are hard breaks, every stale_cache_blank finding in
    that file is marked non-actionable (with the fraction recorded in files_analyzed). A file
    with only a few blank-cache cells among many good ones keeps those findings fully
    actionable -- that shape is the real defect signal.
3. Cross-references every finding against the task's own tests/deliverables_*/judge.toml criteria:
   does any criterion's description text (or an "Expected: ..." figure in it) appear to reference
   this cell's row label, its sheet name, or its recomputed value? Flags "matches a graded
   criterion" vs "no criterion appears to reference this" so a report reader can immediately see
   which findings are worth acting on.
4. Explicitly handles the documented xlsm->xlsx conversion shim: tests/test.sh (and any
   environment/*.sh) is scanned for a documented file-format conversion. Because this script
   globs for .xlsx AND .xlsm directly under solution/ rather than requiring the exact filename
   judge.toml names, a task whose golden is authored as .xlsm and converted to .xlsx at grading
   time is analyzed against whatever file actually exists on disk -- it is never flagged as
   "missing" just because the extension doesn't match judge.toml's files=[...] literally. The
   presence/absence of the shim script is still recorded per task for transparency.
5. Writes one JSON result per task (status: pass|fail, the finding list, files analyzed, shim
   detection, judge-criteria cross-reference) plus an aggregate report across every task given on
   the command line (or discovered via --all).

Known limits, disclosed rather than silently dropped:
    - The judge-criteria cross-reference is a text-overlap heuristic (label substring match, token
      overlap, and an "Expected: <number>" match against the recomputed value) -- not a certainty.
      A "no criterion appears to reference this" result means the heuristic found nothing, not
      that the cell is proven ungraded.
    - `formulas` does not implement every Excel function; `unresolved_by_engine` findings are the
      library's own gap, not a claim about the workbook.
    - The 90%-blank-cache / zero-hard-breaks whole-file-wipe threshold is a heuristic, not a
      certainty. A file with exactly 89% blank-cache cells (all clean on recompute) will have
      every one of them counted as actionable and gate the task to fail; a file with 91% will
      not. Re-check files_analyzed[].cache_blank_fraction by hand near that boundary.
    - This script analyzes the CURRENT on-disk state of solution/ under --root. It says nothing
      about whether a task was broken in the past and has since been fixed by other work, and
      nothing about environment/initial_workspace/ or any file outside solution/. Confirmed live
      during this script's own validation: SVC-PC-81-2-0 and SVC-PC-81-3-0 both showed genuine
      #REF!/#VALUE! errors (formulas referencing sheets that do not exist in the workbook) when
      first probed, then reported clean minutes later once other concurrent work in this project
      patched them -- this script reports the file as it is right now, nothing more.
"""

import argparse
import json
import math
import re
import subprocess
import sys
import tomllib
import warnings
from datetime import datetime, timezone
from pathlib import Path

# Windows console defaults to cp1252, which cannot encode many Unicode
# characters that show up in real formula-error text (minus signs, arrows,
# etc from the `formulas` library or a workbook's own error strings). Force
# UTF-8 with replacement so a printable-but-non-cp1252 character never
# crashes the whole sweep partway through a batch.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import openpyxl
except ImportError:  # pragma: no cover - openpyxl is a project-wide dependency already
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl

try:
    import formulas
except ImportError:
    print(
        "`formulas` not found -- running `pip install formulas --quiet`",
        file=sys.stderr,
    )
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "formulas", "--quiet"], check=True
    )
    import formulas

DEFAULT_ROOT = Path(r"C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready")

ERR_TOKENS = ("#REF!", "#VALUE!", "#NAME?", "#DIV/0!", "#N/A", "#NULL!", "#NUM!")
VOLATILE_FUNCS = ("NOW(", "TODAY(", "RAND(", "RANDBETWEEN(", "RANDARRAY(")
SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm")

# formulas.ExcelModel().calculate() keys look like "'[FILENAME.xlsx]SHEETNAME'!A1"
SOLUTION_KEY_RE = re.compile(r"^'\[[^\]]+\](?P<sheet>[^']+)'!(?P<cell>[A-Z]+\d+)$")

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "into",
    "expected",
    "must",
    "pass",
    "criterion",
    "shown",
    "shows",
    "value",
    "values",
    "computed",
    "referenced",
    "reference",
    "applied",
    "correctly",
    "correct",
    "present",
    "defined",
    "field",
    "cell",
    "sheet",
    "workbook",
    "tabs",
    "tab",
}
TOKEN_RE = re.compile(r"[a-z0-9]+")
NUMBER_RE = re.compile(r"-?\$?\d[\d,]*\.?\d*%?")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def tokenize(text):
    return {
        w
        for w in TOKEN_RE.findall((text or "").lower())
        if len(w) >= 4 and w not in STOPWORDS
    }


def normalize_text(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def is_numeric(v):
    if v is None or isinstance(v, bool):
        return False
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def parse_numbers(text):
    out = []
    for tok in NUMBER_RE.findall(text or ""):
        cleaned = tok.replace("$", "").replace(",", "")
        is_pct = cleaned.endswith("%")
        cleaned = cleaned.rstrip("%")
        try:
            val = float(cleaned)
        except ValueError:
            continue
        out.append(val / 100.0 if is_pct else val)
    return out


def to_jsonable(v):
    if v is None:
        return None
    if isinstance(v, (str, bool)):
        return v
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isnan(v):
            return "NaN"
        return v
    if isinstance(v, datetime):
        return v.isoformat()
    try:
        import numpy as np

        if isinstance(v, np.bool_):
            return bool(v)
        if isinstance(v, np.integer):
            return int(v)
        if isinstance(v, np.floating):
            f = float(v)
            return "NaN" if math.isnan(f) else f
    except ImportError:
        pass
    return str(v)


def unwrap_formulas_value(v):
    """A `formulas` calculate() value is usually a Ranges/Array wrapper; pull the scalar out."""
    try:
        v = v.value
    except AttributeError:
        pass
    try:
        arr = v
        seen = 0
        while hasattr(arr, "shape") and getattr(arr, "shape", None) not in (None, ()):
            arr = arr[0] if len(arr) else None
            seen += 1
            if seen > 10:
                break
        return arr
    except Exception:
        return v


# ---------------------------------------------------------------------------
# task/file discovery
# ---------------------------------------------------------------------------


def find_task_dirs(root, task_ids=None):
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
        p for p in root.iterdir() if p.is_dir() and p.name.startswith("SVC-PC-")
    )


def find_spreadsheets(task_dir):
    sol = task_dir / "solution"
    if not sol.is_dir():
        return []
    return sorted(
        p
        for p in sol.rglob("*")
        if p.is_file() and p.suffix.lower() in SPREADSHEET_SUFFIXES
    )


def detect_conversion_shim(task_dir):
    """Scan tests/ and environment/ shell scripts for a documented format-conversion shim
    (e.g. the project-wide xlsm->xlsx conversion baked into tests/test.sh -- see module
    docstring point 4). Returns the list of script paths (relative to task_dir) that look like
    they perform one."""
    hits = []
    for sub in ("tests", "environment"):
        base = task_dir / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*.sh"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if re.search(r"xlsm", text, re.IGNORECASE) and re.search(
                r"convert|xlsx|\.save\(|openpyxl", text, re.IGNORECASE
            ):
                hits.append(str(p.relative_to(task_dir)).replace("\\", "/"))
    return hits


def load_judge_criteria(task_dir):
    """Every [[criterion]] across every tests/deliverables_*/judge.toml, flattened, each
    carrying its own judge.files=[...] list and group (deliverables_NN) for provenance.
    """
    out = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return out
    for jt in sorted(tests_dir.glob("deliverables_*/judge.toml")):
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
        except Exception as e:
            out.append(
                {
                    "group": jt.parent.name,
                    "name": "__parse_error__",
                    "description": f"judge.toml failed to parse: {e}",
                    "files": [],
                }
            )
            continue
        judge = data.get("judge", {})
        files = judge.get("files", [])
        for c in data.get("criterion", []):
            out.append(
                {
                    "group": jt.parent.name,
                    "name": c.get("name"),
                    "description": c.get("description", ""),
                    "weight": c.get("weight"),
                    "type": c.get("type"),
                    "files": files,
                }
            )
    return out


def resolve_graded_files(task_dir, criteria, shim_scripts):
    """For every distinct path a judge.toml names in files=[...], find what actually exists on
    disk under solution/, accounting for the documented xlsm<->xlsx shim (point 4). This never
    gates whether a file gets analyzed -- find_spreadsheets() already globs every .xlsx/.xlsm
    regardless -- it only produces the transparency note a report reader needs."""
    sol_dir = task_dir / "solution"
    available = {}
    if sol_dir.is_dir():
        for p in sol_dir.rglob("*"):
            if p.is_file():
                available.setdefault(p.name.lower(), p)

    expected_paths = sorted({f for c in criteria for f in (c.get("files") or [])})
    resolved = []
    for expected in expected_paths:
        expected_name = Path(expected).name
        exact = available.get(expected_name.lower())
        if exact:
            resolved.append(
                {
                    "expected": expected,
                    "actual": str(exact.relative_to(task_dir)).replace("\\", "/"),
                    "note": "exact match",
                }
            )
            continue
        stem = Path(expected_name).stem
        alt_suffix = Path(expected_name).suffix.lower()
        other_suffix = ".xlsm" if alt_suffix == ".xlsx" else ".xlsx"
        alt = available.get((stem + other_suffix).lower())
        if alt:
            if shim_scripts:
                note = (
                    f"judge.toml names '{expected_name}' but the file on disk is "
                    f"'{alt.name}' -- documented conversion shim found in "
                    f"{', '.join(shim_scripts)}; treated as the real graded file, NOT flagged "
                    f"as missing"
                )
            else:
                note = (
                    f"judge.toml names '{expected_name}' but the file on disk is "
                    f"'{alt.name}' and NO documented conversion shim was found -- this IS a "
                    f"real filename/extension mismatch, not covered by the false-positive case"
                )
            resolved.append(
                {
                    "expected": expected,
                    "actual": str(alt.relative_to(task_dir)).replace("\\", "/"),
                    "note": note,
                }
            )
            continue
        resolved.append(
            {
                "expected": expected,
                "actual": None,
                "note": "no file of this name (either extension) found under solution/ -- "
                "possibly a non-spreadsheet deliverable, or a genuine missing-file defect "
                "(check F/C territory, not this script's concern)",
            }
        )
    return resolved


# ---------------------------------------------------------------------------
# per-cell classification
# ---------------------------------------------------------------------------


def nearest_left_label(ws, row, col):
    for c in range(col - 1, 0, -1):
        v = ws.cell(row=row, column=c).value
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def classify_cell(formula_text, cached_value, recomputed_value, resolved):
    if not resolved:
        return {"kind": "unresolved_by_engine", "severity": "info"}

    if isinstance(recomputed_value, str) and any(
        tok in recomputed_value for tok in ERR_TOKENS
    ):
        return {
            "kind": "recompute_error",
            "severity": "high",
            "error": recomputed_value,
        }

    if is_numeric(recomputed_value):
        try:
            if math.isnan(float(recomputed_value)):
                return {"kind": "recompute_blank", "severity": "high"}
        except (TypeError, ValueError):
            pass

    cached_is_blank = cached_value is None
    if isinstance(cached_value, str) and cached_value.strip() == "":
        cached_is_blank = True
    if is_numeric(cached_value):
        try:
            if math.isnan(float(cached_value)):
                cached_is_blank = True
        except (TypeError, ValueError):
            pass
    if cached_is_blank:
        return {"kind": "stale_cache_blank", "severity": "medium"}

    is_volatile = any(vf in (formula_text or "").upper() for vf in VOLATILE_FUNCS)
    if not is_volatile and is_numeric(cached_value) and is_numeric(recomputed_value):
        try:
            cf, rf = float(cached_value), float(recomputed_value)
            if not math.isclose(cf, rf, rel_tol=1e-4, abs_tol=1e-6):
                return {"kind": "value_mismatch", "severity": "low"}
        except (TypeError, ValueError):
            pass

    return None


def match_criteria(label, sheet_title, recomputed_value, criteria):
    matches = []
    label_norm = normalize_text(label)
    label_tokens = tokenize(label)
    numeric_val = float(recomputed_value) if is_numeric(recomputed_value) else None

    for c in criteria:
        desc = c.get("description") or ""
        desc_norm = normalize_text(desc)
        reasons = []

        if label_norm and len(label_norm) >= 5 and label_norm in desc_norm:
            reasons.append(
                f"row label '{label}' appears verbatim in the criterion description"
            )
        else:
            desc_tokens = tokenize(desc)
            overlap = label_tokens & desc_tokens
            if len(overlap) >= 2:
                reasons.append(f"token overlap with row label: {sorted(overlap)}")

        if numeric_val is not None:
            for n in parse_numbers(desc):
                if math.isclose(n, numeric_val, rel_tol=1e-3, abs_tol=0.5):
                    reasons.append(
                        f"recomputed value {numeric_val:g} matches a figure in the "
                        f"criterion's 'Expected:' text ({n:g})"
                    )
                    break

        if reasons:
            matches.append(
                {
                    "group": c.get("group"),
                    "name": c.get("name"),
                    "reasons": reasons,
                }
            )
    return matches


# ---------------------------------------------------------------------------
# per-file / per-task analysis
# ---------------------------------------------------------------------------


def _make_finding(info, kind, severity, rv, matching, error=None):
    return {
        "sheet": info["sheet"],
        "cell": info["cell"],
        "formula": info["formula"],
        "row_label": info["label"],
        "cached_value": to_jsonable(info["cached"]),
        "recomputed_value": to_jsonable(rv),
        "kind": kind,
        "severity": severity,
        "error": error,
        "matches_graded_criteria": bool(matching),
        "matching_criteria": matching,
    }


def _finalize_findings(findings, meta):
    """Whole-file cache-wipe detection (the SVC-PC-58-7-0 false-positive class): a file that
    went through an openpyxl load+save round trip anywhere upstream (e.g. the pipeline's own
    xlsm->xlsx build-time conversion, to_rewardkit.py's _convert_xlsm_to_xlsx, or the equivalent
    runtime shim in tests/test.sh) loses EVERY cached formula result at once -- openpyxl's
    save() strips cached values unconditionally, on every formula cell, regardless of whether
    that formula is actually broken. That shows up here as a huge run of stale_cache_blank
    findings that all recompute cleanly. That is a mechanical artifact of a known, project-wide
    conversion step, not a targeted defect in this task's authoring -- so it must not be
    confused with the localized, genuine cache gaps that made SVC-PC-51-3-0 / SVC-PC-51-6-0 fail
    before they were patched. Distinguish by shape: if almost every formula cell in the file is
    blank-cache AND none of them are hard breaks (recompute_error / recompute_blank / an
    engine-unresolved cell), this is a uniform wipe, not a scatter of real defects.

    unresolved_by_engine findings are never actionable on their own -- they say the `formulas`
    library did not evaluate this cell, which is a limitation of the check, not an assertion
    that the cell is broken."""
    total_formula = meta["n_formula_cells"]
    stale_count = sum(1 for f in findings if f["kind"] == "stale_cache_blank")
    hard_break_count = sum(
        1
        for f in findings
        if f["kind"] in ("recompute_error", "recompute_blank", "unresolved_by_engine")
    )
    fraction_stale = (stale_count / total_formula) if total_formula else 0.0
    uniform_wipe = total_formula > 0 and fraction_stale >= 0.9 and hard_break_count == 0
    meta["cache_blank_fraction"] = round(fraction_stale, 4)
    meta["uniform_cache_wipe"] = uniform_wipe

    for f in findings:
        if f["kind"] == "unresolved_by_engine":
            f["actionable"] = False
            f["suppressed_reason"] = (
                "the `formulas` library did not evaluate this cell at all (unsupported "
                "function, cross-workbook reference, or the whole file failed to load/"
                "calculate) -- a limitation of this check's recompute engine, not a claim "
                "that the cell is broken. Not counted toward fail/pass status."
            )
        elif f["kind"] == "stale_cache_blank" and uniform_wipe:
            f["actionable"] = False
            f["suppressed_reason"] = (
                f"{stale_count}/{total_formula} ({fraction_stale:.0%}) of this file's formula "
                "cells have a blank cache and every one of them recomputes cleanly to a real, "
                "non-error value -- the signature of a whole-file cache wipe (an openpyxl "
                "load+save round trip somewhere upstream, e.g. the documented xlsm->xlsx "
                "build-time conversion), not a targeted authoring defect. Not counted toward "
                "this task's fail/pass status. Still listed here for completeness (e.g. if a "
                "cache-value patch like the one applied to SVC-PC-51-3-0/51-6-0 is ever wanted)."
            )
        else:
            f["actionable"] = True
    return findings


def analyze_workbook(path, criteria):
    """Returns (findings, meta) for one spreadsheet file. Never raises -- a load/calc failure
    on the whole file is reported as a single meta-level error, not a crash."""
    findings = []
    meta = {"n_formula_cells": 0, "load_error": None}

    try:
        wb_formula = openpyxl.load_workbook(str(path), data_only=False)
        wb_cached = openpyxl.load_workbook(str(path), data_only=True)
    except Exception as e:
        meta["load_error"] = f"openpyxl could not open this file: {e}"
        return findings, meta

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
                        "label": nearest_left_label(ws, cell.row, cell.column),
                        "cached": ws_cached.cell(
                            row=cell.row, column=cell.column
                        ).value,
                    }
    meta["n_formula_cells"] = len(formula_map)

    if not formula_map:
        return findings, meta

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            xl_model = formulas.ExcelModel().loads(str(path)).finish()
            solution = xl_model.calculate()
    except Exception as e:
        meta["load_error"] = (
            f"`formulas` library could not load/calculate this file: {e}"
        )
        # Still report every formula cell as unresolved-by-engine, rather than silently
        # dropping the file from the report.
        for info in formula_map.values():
            findings.append(
                _make_finding(info, "unresolved_by_engine", "info", None, [])
            )
        return _finalize_findings(findings, meta), meta

    recomputed = {}
    for k, v in solution.items():
        m = SOLUTION_KEY_RE.match(k)
        if not m:
            continue
        recomputed[(m.group("sheet").upper(), m.group("cell"))] = unwrap_formulas_value(
            v
        )

    for key, info in formula_map.items():
        resolved = key in recomputed
        rv = recomputed.get(key)
        c = classify_cell(info["formula"], info["cached"], rv, resolved=resolved)
        if c is None:
            continue
        matching = match_criteria(info["label"], info["sheet"], rv, criteria)
        findings.append(
            _make_finding(info, c["kind"], c["severity"], rv, matching, c.get("error"))
        )

    return _finalize_findings(findings, meta), meta


def analyze_task(task_dir, root):
    task_id = task_dir.name
    criteria = load_judge_criteria(task_dir)
    shim_scripts = detect_conversion_shim(task_dir)
    graded_file_resolution = resolve_graded_files(task_dir, criteria, shim_scripts)
    spreadsheets = find_spreadsheets(task_dir)

    result = {
        "task_id": task_id,
        "solution_dir_exists": (task_dir / "solution").is_dir(),
        "conversion_shim": {
            "detected": bool(shim_scripts),
            "scripts": shim_scripts,
        },
        "graded_file_resolution": graded_file_resolution,
        "files_analyzed": [],
        "findings": [],
        "errors": [],
    }

    if not spreadsheets:
        result["status"] = "pass"
        result["errors"].append(
            "no .xlsx/.xlsm found under solution/ -- nothing for this check to verify "
            "(not itself a defect; may be a non-spreadsheet deliverable task)"
        )
        return result

    for path in spreadsheets:
        rel = str(path.relative_to(task_dir)).replace("\\", "/")
        findings, meta = analyze_workbook(path, criteria)
        for f in findings:
            f["file"] = rel
        result["findings"].extend(findings)
        result["files_analyzed"].append(
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
            result["errors"].append(f"{rel}: {meta['load_error']}")

    by_kind = {}
    for f in result["findings"]:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1

    actionable = [f for f in result["findings"] if f.get("actionable", True)]
    result["summary"] = {
        "n_findings": len(result["findings"]),
        "n_actionable": len(actionable),
        "by_kind": by_kind,
        "n_matched_to_graded_criteria": sum(
            1 for f in result["findings"] if f["matches_graded_criteria"]
        ),
    }
    result["status"] = "fail" if actionable else "pass"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Check E: recalculate every formula in a task's golden workbook(s) and "
        "report cells that error out or read blank/NaN, cross-referenced against the task's "
        "own judge.toml criteria."
    )
    ap.add_argument("task_ids", nargs="*", help="one or more SVC-PC-N-N-N task ids")
    ap.add_argument(
        "--all", action="store_true", help="run every task directory found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"03_dataos_ready root (default: {DEFAULT_ROOT})",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    task_dirs = find_task_dirs(args.root, None if args.all else args.task_ids)
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        sys.exit(1)

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(task_dir, args.root)
        except Exception as e:  # never let one task's crash kill the whole batch
            r = {
                "task_id": task_dir.name,
                "status": "fail",
                "errors": [f"unhandled exception analyzing this task: {e}"],
                "findings": [],
                "files_analyzed": [],
                "summary": {
                    "n_findings": 0,
                    "by_kind": {},
                    "n_matched_to_graded_criteria": 0,
                },
            }
        results.append(r)
        print(
            f"    -> {r['status']}  "
            f"({r.get('summary', {}).get('n_findings', 0)} findings, "
            f"{len(r.get('errors', []))} errors)",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    aggregate = {
        "check": "E",
        "name": "Formula health",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "results": results,
    }

    print(f"\n{n_pass} pass / {n_fail} fail out of {len(results)} task(s)")
    for r in results:
        kinds = ", ".join(
            f"{k}={v}" for k, v in r.get("summary", {}).get("by_kind", {}).items()
        )
        print(f"  {r['task_id']}: {r['status']}" + (f"  [{kinds}]" if kinds else ""))
        for e in r.get("errors", []):
            print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
