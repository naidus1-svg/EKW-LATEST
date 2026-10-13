"""Formula health check: recalculate every formula in a task's golden workbook(s) and report
cells that error out or read blank/NaN when actually recomputed.

Why this exists: a rubric criterion can expect a computed/derived value, and the golden
workbook can show that value as blank or NaN when read back by whatever tool does the reading
(openpyxl `data_only=True`, pandas, a markdown export, an LLM judge). A structural or content
audit that only reads the file's cached values never catches this -- it has to actually
recompute the formulas. This script does that recomputation deterministically, with zero LLM
cost, so the defect is caught before an expensive judge/grading round-trip rather than after.

Provenance: extracted from a QC pipeline built for one benchmark (SVC-PC / Cirrus Sleep); this
copy has been generalized (no hardcoded task-ID prefix, no hardcoded root path) and has no
benchmark-specific assumptions left in its logic. It expects a generic package shape: for each
task, a `<task_dir>/solution/` folder holding golden `.xlsx`/`.xlsm` files, and
`<task_dir>/tests/deliverables*/judge.toml` files with `[[criterion]]` blocks (a `judge.files`
list plus `name`/`description`/`weight`/`type` per criterion) -- the same generic Harbor task
package shape the accompanying structural-audit skill checks. If your package shape differs,
the file/judge discovery functions (`find_spreadsheets`, `load_judge_criteria`) are the two
places to adapt.

Status: v1, battle-tested -- this script (not the wrapper skill) has been run at real scale
against hundreds of tasks in its source project with no known false negatives on the defect
class it targets.

Usage:
    python formula_health_check.py <TASK-ID> [<TASK-ID> ...] --root <path-to-task-dirs> --out report.json
    python formula_health_check.py --all --root <path-to-task-dirs> --out report.json
    python formula_health_check.py --all --root <path> --id-prefix MYBENCH- --out report.json

What it does, in order:

1. For a given task id (or --all tasks under --root), finds every .xlsx/.xlsm under that task's
   solution/ directory (recursive glob -- it doesn't assume solution/files/, since a grading
   shim can mean the real graded file isn't the one judge.toml names literally).
2. Opens each with the `formulas` library (auto-installs via `pip install formulas --quiet` if
   missing) and forces a full recalculation, independent of whatever the file's cached <v> values
   say. Classifies every formula cell (found via a separate openpyxl `data_only=False` pass, so
   a legitimately blank input cell is never flagged) into one of:
     - recompute_error   : the recalculated value IS an Excel error (#REF!, #VALUE!, #NAME?,
                            #DIV/0!, #N/A, #NULL!, #NUM!). A genuinely broken formula chain.
     - recompute_blank   : the recalculated value itself is None/NaN despite not being a proper
                            Excel error token (an engine-level dead end -- treated as high
                            severity, same as recompute_error).
     - stale_cache_blank : the cell's *cached* value (what a normal read of the file sees) is
                            None/NaN/empty, but the live recompute resolves cleanly to a real
                            value. The formula logic is fine, but the cached result baked into
                            the file is missing, so anything that reads the file without
                            recalculating sees nothing there. Fixable by a cached-<v> XML patch
                            (see the companion formula_cache_autofix.py).
     - value_mismatch    : cached and recomputed both resolve to real values but disagree beyond
                            tolerance (volatile functions -- NOW/TODAY/RAND -- are excluded). Low
                            severity/low confidence: could be legitimate (rounding), so flagged
                            for a human look rather than asserted as certainly wrong.
     - unresolved_by_engine: the `formulas` library did not resolve this cell at all (unsupported
                            function, cross-workbook reference, etc). This is a limitation of the
                            check itself, not asserted as a defect in the workbook -- surfaced so
                            a reader knows this cell was not actually verified either way.
   unresolved_by_engine findings, and stale_cache_blank findings in a file where >=90% of ALL
   formula cells are blank-cache and NONE are hard breaks, are marked `actionable: false` and
   excluded from the task's pass/fail gate (see "whole-file cache wipe" below) -- they are still
   listed in the JSON with a `suppressed_reason`, never silently dropped.

1.5 Three purely syntactic heuristics run automatically alongside the recompute-based
    classification above, on every formula cell (and, for the third, every worksheet), for a
    defect shape the recompute step is structurally blind to: a formula that resolves to a real,
    non-error, non-blank number because a reference is missing its sheet-qualifier and silently
    falls back to a same-named cell on the WRONG sheet. Recompute-based classification cannot see
    this -- the formula evaluates cleanly, it just evaluates the wrong thing. These run
    independently of whether `formulas` resolved the cell, and independently of whatever
    classify_cell() found for the same cell (a cell can carry both a recompute-based finding and
    one of these):
     - mixed_qualifier_smell: the formula string contains at least one explicit 'SheetName!'
                            reference AND at least one bare (unqualified) cell reference in the
                            same expression, e.g. '=Channel_Model!B17*$B$7'. Confirmed real-world
                            precedent: a 210x overstatement (SVC-PC-58-2-0, Working_Capital!B5 and
                            siblings) where the bare ref silently resolved to the current sheet
                            instead of the intended cross-sheet cell. Severity: medium -- it is a
                            smell, not a certainty (see Known limits: the same shape also matches
                            a common, legitimate pattern).
     - out_of_bounds_unqualified_ref: a bare (unqualified), non-range cell reference in a formula
                            whose row number exceeds the CURRENT sheet's own used range
                            (ws.max_row). A bare reference is resolved by Excel against the
                            sheet the formula lives on; one that points past every row that sheet
                            has ever had content in is almost never intentional. Confirmed
                            real-world precedent: SVC-PC-78-6-0, Cost_Comparison!B5 = '=B32' on a
                            sheet whose used range ends at row 12 -- silently read blank-as-zero.
                            Severity: high. Scoped to single (non-range) bare references only --
                            see Known limits.
     - cross_scenario_monotonicity: best-effort, row/sheet-level rather than per-cell. See its
                            own docstring (monotonicity_findings_for_sheet) and Known limits.
                            Severity: medium when it fires. When a scenario header row is found
                            but no nearby driver-quantity row can be linked to it, this heuristic
                            emits monotonicity_check_skipped_no_driver_link (severity info,
                            actionable: false) instead of guessing -- confirmed real-world
                            precedent for the anomaly shape: SVC-PC-58-2-0's Downside-exceeds-Base
                            cash flow.
2.5 Whole-file cache-wipe detection: openpyxl's own save() unconditionally strips EVERY cached
    formula result on any load+save, regardless of whether the formula is broken. Any file that
    passed through such a round trip upstream (e.g. an xlsm->xlsx build-time conversion step)
    will show a huge run of stale_cache_blank findings that all recompute cleanly. That is a
    mechanical, pipeline-wide artifact, not a targeted defect, and is distinguished by shape from
    localized cache gaps that are genuine failures: if >=90% of a file's formula cells are
    blank-cache AND zero are hard breaks, every stale_cache_blank finding in that file is marked
    non-actionable (with the fraction recorded in files_analyzed). A file with only a few
    blank-cache cells among many good ones keeps those findings fully actionable -- that shape is
    the real defect signal.
2.6 Guarded-blank detection: a formula authored as IF(<condition>, <expr>, "") deliberately
    returns a literal blank when <condition> is false -- the standard, correct way to write "this
    derived metric is undefined for this row's current inputs" (a zero-orders-month AOV, a
    reconciliation difference with no counterpart figure to diff against, a guard that only
    computes once every referenced input is numeric). Recompute-based classification cannot tell
    that apart from a genuine dead end on formula/cache text alone -- both land in
    stale_cache_blank (or, if the engine happens to resolve the blank branch as a bare NaN rather
    than an empty string, recompute_blank) with no further distinction. This heuristic re-checks
    every such finding: if the WHOLE formula is a single top-level IF(...) call whose third
    argument is the literal "", every cell reference inside the first argument (the condition) is
    extracted, and each is looked up in the file's own cached values. If EVERY referenced cell is
    genuinely PRESENT (a real value, whether that's numeric zero, a negative number, or
    non-numeric text -- anything that is not itself None/blank/NaN), the blank result is this
    formula's own designed handling of the current input combination, and the finding is marked
    non-actionable. If ANY referenced cell is itself blank/missing, the finding is left exactly as
    classified -- a guard that fails because its own input never arrived is still a real defect,
    not a designed edge case, and this heuristic does not touch it. Confirmed real-world
    precedent: SVC-PC-1-2-0 (Monthly Board Model!C5, '=IF(B5>0,D5/B5,"")', B5=0 for a documented
    zero-orders January -- 'January is a zero-orders month: Orders = 0, AOV undefined (left
    blank)' is stated in-workbook) and SVC-PC-6-1-0 (Reconciliation Log!H218/H219: the guard
    inputs are present TEXT annotations, e.g. F218='Defective row/label mapping', not numbers --
    ISNUMBER() fails by design, not by omission). The same file's Balance Sheet Support!D22 is the
    negative control that confirms this heuristic does NOT over-fire: its guard references C22,
    which is genuinely empty (no value at all, not zero, not text), so the finding stays flagged.
3. Cross-references every finding against the task's own tests/deliverables_*/judge.toml criteria:
   does any criterion's description text (or an "Expected: ..." figure in it) appear to reference
   this cell's row label, its sheet name, or its recomputed value? Flags "matches a graded
   criterion" vs "no criterion appears to reference this" so a report reader can immediately see
   which findings are worth acting on.
4. Explicitly handles a documented xlsm->xlsx conversion shim, if your pipeline has one:
   tests/test.sh (and any environment/*.sh) is scanned for a documented file-format conversion.
   Because this script globs for .xlsx AND .xlsm directly under solution/ rather than requiring
   the exact filename judge.toml names, a task whose golden is authored as .xlsm and converted to
   .xlsx at grading time is analyzed against whatever file actually exists on disk.
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
      certainty. Re-check files_analyzed[].cache_blank_fraction by hand near that boundary.
    - This script analyzes the CURRENT on-disk state of solution/ under --root. It says nothing
      about whether a task was broken in the past and has since been fixed by other work, and
      nothing about environment/initial_workspace/ or any file outside solution/.
    - mixed_qualifier_smell is a syntactic pattern match, not a proof of a wrong reference, and is
      deliberately scoped to a FULLY-$-ANCHORED bare reference (e.g. '$B$7'), not any bare
      reference -- see find_mixed_qualifier_smell's own docstring for why. A same-sheet RELATIVE
      bare reference that shifts naturally with the formula's own column (e.g.
      '=B5-SRC_PL!B10', or '=B6*Assumptions!$B$24', repeated across a whole column block) is the
      normal, correct way to write "take a subtotal already computed on this sheet and
      compare/combine it with a value pulled from another sheet", and this session's own broader
      testing found it common enough (dozens of instances in one real task) that the looser,
      any-bare-ref version of this heuristic would have been mostly noise; that version is not
      what shipped. The narrower, $-anchored version can still fire on a formula that
      legitimately pins a same-sheet constant (e.g. a same-sheet tax rate cell referenced as
      '$B$2') alongside an unrelated cross-sheet lookup -- it is a prompt for a human look, not a
      verdict, just a much less frequent one. A regex cell-reference tokenizer, not a real Excel
      formula parser: it strips double-quoted string literals first so quoted text is never
      mistaken for a reference, and it treats a whole 'Sheet!A1:A10' range as one qualified
      occurrence (not a bare second endpoint), but it can still mis-tokenize an unusual formula
      shape it was not tested against.
    - out_of_bounds_unqualified_ref is deliberately scoped to a single bare cell reference, not a
      range endpoint (e.g. it will not flag the '...:A1000' end of a defensively oversized
      '=SUM(A1:A1000)'), specifically to avoid that common defensive-range pattern becoming a wall
      of false positives. A workbook that uses an oversized bare RANGE (not a single bare cell) to
      reach past its own used range for the same wrong-sheet-fallback reason will not be caught by
      this heuristic.
    - cross_scenario_monotonicity only looks for the scenario-header row and the driver-quantity
      row on the SAME sheet, downward from the header (data follows its header, not the reverse),
      bounded at MONOTONICITY_SEARCH_WINDOW (30) rows or the first "alternate header" row it hits
      first -- a row that reuses the SAME columns for a different axis (e.g. "Year 1 | Year 2 |
      Year 3" reusing the exact columns a "Base | Upside | Downside" row used higher up), which
      this session's testing confirmed is a real shape (one real task's Channel_Model sheet does
      exactly this) that would otherwise silently mislink an unrelated block's numbers into the
      comparison. The driver-keyword match also excludes a per-unit RATE phrasing ("cost / unit",
      "price per unit") -- confirmed to be the dominant false-positive source before that
      exclusion was added, since almost every per-unit-economics row in a typical model contains
      the word "unit". None of this makes the heuristic follow a formula's own cross-sheet
      reference to a driver-quantity row that lives on a DIFFERENT sheet, or in a
      differently-shaped layout (e.g. one Units row per scenario BLOCK, stacked vertically, rather
      than one Units row with scenarios as adjacent columns) -- that stays out of scope. When no
      same-sheet, same-block link is confidently discoverable, it reports
      monotonicity_check_skipped_no_driver_link rather than guessing -- a workbook can have a real
      cross-scenario anomaly and still get only the skip marker if the driver data lives
      elsewhere. It also reads CACHED values only (not the `formulas` engine's recompute), so it
      runs even when the recompute step fails, but a stale
      cache could in principle mask or fabricate an apparent anomaly.
    - Guarded-blank detection (section 2.6) only resolves single-cell (non-range) references
      inside an IF's condition, and only when the WHOLE formula is exactly one top-level
      IF(...,"") call -- see find_guarded_blank_cause's own docstring for the precise shape. It
      decides "present vs blank" for a condition input from the file's own CACHED values (not a
      second recompute pass), so a condition input that is itself a stale-cache formula cell
      (blank cache, would recompute to something real) reads as blank/missing here and the
      finding is conservatively left flagged rather than guessed at. It also does not evaluate
      the condition itself (no AND/OR/comparison logic implemented) -- it only checks that every
      cell the condition MENTIONS is present, and trusts the already-computed recompute/cache
      result to say whether the blank branch was actually taken.
"""

import argparse
import concurrent.futures
import json
import math
import os
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
except ImportError:  # pragma: no cover
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

# EKW's tests/verifier.json reader (JSON, not judge.toml/TOML) -- lives next to this script in
# the same folder. Optional: SVC-PC-only deployments of this script never need it, so a missing
# copy degrades to "EKW tasks are treated as having no criteria" (load_judge_criteria's original
# empty-list behavior) rather than crashing on import.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
try:
    import ekw_verifier_json
except ImportError:  # pragma: no cover
    ekw_verifier_json = None

ERR_TOKENS = ("#REF!", "#VALUE!", "#NAME?", "#DIV/0!", "#N/A", "#NULL!", "#NUM!")
VOLATILE_FUNCS = ("NOW(", "TODAY(", "RAND(", "RANDBETWEEN(", "RANDARRAY(")
SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm")

# --check-extraction-loss mode: what the REAL extractor call is, for both formats, and why it's
# the same underlying mechanism reached two different ways. Confirmed by direct read of both
# code paths against the real packages on this machine, 2026-09-15 (not assumed from either
# library's docs/name):
#   EKW:    tests/verifier_lib/sources/xlsx.py (a real task's own vendored copy, task_1
#           confirmed) line ~81: `load_workbook(path, data_only=True, read_only=True)`, called
#           directly by the "extract_text" source command.
#   SVC-PC: harbor-rewardkit's judges.py `_read_file_blocks()` calls `_convert_with_markitdown()`
#           for a `.xlsx` file, which is markitdown's `XlsxConverter.convert()`
#           (markitdown/converters/_xlsx_converter.py), which calls
#           `pandas.read_excel(file_stream, sheet_name=None, engine="openpyxl")`. pandas' own
#           openpyxl reader (pandas/io/excel/_openpyxl.py, line 577, confirmed by direct read)
#           hardcodes `default_kwargs = {"read_only": True, "data_only": True, "keep_links":
#           False}` -- the identical two kwargs, reached through three extra layers of
#           indirection (rewardkit -> markitdown -> pandas -> openpyxl) rather than called
#           directly. Same root cause, different call site -- NOT assumed symmetric, verified.
#           Caveat, also confirmed by direct read: markitdown's `_DOCUMENT_EXTENSIONS` (the set
#           `_read_file_blocks` checks before routing to `_convert_with_markitdown` at all) lists
#           ".xlsx" but NOT ".xlsm" -- a `.xlsm` graded file never reaches this mechanism at all;
#           `_read_file_blocks` falls through to a plain `p.read_text()`, hits
#           `UnicodeDecodeError` on the binary content, and returns an EMPTY block, silently. A
#           `.xlsm` graded file's real failure mode is therefore NOT selective by formula-cache
#           state -- it's total, unconditional blindness to the file's content, a different and
#           more severe defect this check's per-cell mechanism does not target. See
#           analyze_task_extraction_loss()'s svc_pc_applicability field.
EXTRACTION_CALL_NOTE = (
    "EKW: tests/verifier_lib/sources/xlsx.py calls "
    "openpyxl.load_workbook(path, data_only=True, read_only=True) directly (confirmed by direct "
    "read against task_1's own vendored copy). SVC-PC: harbor-rewardkit's "
    "judges._read_file_blocks() routes a .xlsx file through markitdown's XlsxConverter, which "
    "calls pandas.read_excel(path, engine='openpyxl'); pandas' own openpyxl reader "
    "(pandas/io/excel/_openpyxl.py) hardcodes the identical read_only=True, data_only=True pair "
    "-- same underlying mechanism, reached through rewardkit->markitdown->pandas->openpyxl "
    "instead of called directly. A .xlsm graded file does NOT go through this path at all -- "
    "markitdown's _DOCUMENT_EXTENSIONS excludes .xlsm, so extraction silently returns nothing "
    "for the whole file, formula-selective or not."
)

# formulas.ExcelModel().calculate() keys look like "'[FILENAME.xlsx]SHEETNAME'!A1"
SOLUTION_KEY_RE = re.compile(r"^'\[[^\]]+\](?P<sheet>[^']+)'!(?P<cell>[A-Z]+\d+)$")

# --- syntactic-heuristic constants (mixed_qualifier_smell / out_of_bounds_unqualified_ref /
# cross_scenario_monotonicity) ---------------------------------------------------------------

# Matches one cell reference or range, sheet-qualified or bare. Deliberately conservative:
# `(?<![A-Za-z0-9_.])` blocks a match starting mid-identifier (so "ATAN2(" is never torn into a
# fake ref), and `(?![A-Za-z0-9_(])` blocks a match ending right before "(" (so a short
# function name immediately followed by digits, e.g. "LOG10(", is never mistaken for a cell
# reference). A qualified range's own end (e.g. the "A10" in "Sheet1!A1:A10") is captured inside
# the same match as its start, so it is never miscounted as a second, bare reference.
_SHEET_NAME = r"(?:'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)"
_ONE_REF = r"\$?[A-Za-z]{1,3}\$?[0-9]{1,7}"
CELL_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_.])"
    rf"(?:(?P<sheet>{_SHEET_NAME})!)?"
    rf"(?P<ref>{_ONE_REF})"
    rf"(?P<range_end>\s*:\s*(?:{_SHEET_NAME}!)?{_ONE_REF})?"
    r"(?![A-Za-z0-9_(])"
)
STRING_LITERAL_RE = re.compile(r'"[^"]*"')
REF_ROW_RE = re.compile(r"[0-9]+")
# Both axes dollar-anchored, e.g. "$B$7" -- see find_mixed_qualifier_smell for why this, not any
# bare ref, is the precision-filtered trigger for mixed_qualifier_smell.
FULLY_ABSOLUTE_REF_RE = re.compile(r"^\$[A-Za-z]{1,3}\$[0-9]{1,7}$")

SCENARIO_TOKENS = {
    "base",
    "downside",
    "upside",
    "conservative",
    "optimistic",
    "pessimistic",
    "bull",
    "bear",
    "worst case",
    "best case",
    "worst-case",
    "best-case",
}
# Word-boundary match on a driver-quantity keyword, EXCLUDING a rate-denominator use of the same
# word ("cost / unit", "price per unit", "unit cost", "landed unit cost") -- a per-unit RATE row
# is not a driver-quantity row, and a plain substring match on "unit" catches almost every
# per-unit economics label in a typical model, which was confirmed to misfire in exactly this
# shape during this session's testing (see module docstring Known limits for
# cross_scenario_monotonicity). Covers both word orders ("cost / unit" and "unit cost") since
# both were observed in real task data during this session's testing; a rate phrased neither way
# (e.g. a bare "$/unit" header with no cost/price/rate word) can still slip through.
DRIVER_KEYWORD_RE = re.compile(r"\b(?:unit|units|volume|quantity|qty)\b", re.IGNORECASE)
_RATE_WORD = r"(?:cost|price|rate|fee|margin|contribution)"
RATE_DENOMINATOR_RE = re.compile(
    rf"(?:\bper\s+|/\s*)(?:unit|units|volume|quantity|qty)\b"
    rf"|\b(?:unit|units)\s+{_RATE_WORD}\b"
    rf"|\b{_RATE_WORD}\s+(?:per\s+)?(?:unit|units)\b",
    re.IGNORECASE,
)
COST_METRIC_KEYWORDS = (
    "cost",
    "expense",
    "spend",
    "cogs",
    "fee",
    "opex",
    "capex",
    "cash flow",
    "cash outflow",
    "outflow",
)
MONOTONICITY_SEARCH_WINDOW = (
    30  # rows, downward from the header, bounded by a block boundary
)

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
    # Exact type, not isinstance: `formulas.tokens.operand.XlError` (an Excel error constant
    # like #NAME?/#NUM!/#VALUE!, what unwrap_formulas_value() returns for an errored cell) is a
    # `str` SUBCLASS via schedula's Token base class, so `isinstance(v, str)` was true and this
    # returned the raw XlError instance unconverted -- looks like a plain string (same repr),
    # but isn't one, and the Token class itself is not picklable (confirmed: even a bare
    # `XlError('#NAME?')` fails `pickle.dumps()` with "cannot pickle 'module' object", a
    # property of the class, not of how this script uses it). That crashed 4 of 8
    # `--jobs`-sharded workers on the real EKW corpus (2026-09-15) whenever a shard's result
    # dict carried one of these all the way back through ProcessPoolExecutor's pickle-based
    # IPC. `type(v) is str` forces any subclass through the `str(v)` fallback below instead,
    # which produces a genuine, picklable plain string with the same visible text.
    if type(v) is str or type(v) is bool:
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


def find_task_dirs(root, task_ids=None, id_prefix=""):
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
    """Scan tests/ and environment/ shell scripts for a documented format-conversion shim.
    Returns the list of script paths (relative to task_dir) that look like they perform one.
    """
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


def _detect_format(task_dir):
    """ "ekw" if tests/verifier.json exists, "svc_pc" if any tests/**/judge.toml exists, else
    "unknown" (reported, not raised). Mirrors verifier_executability_check.py's own
    `_detect_format` exactly -- same folder, same convention, kept as a literal duplicate rather
    than a cross-script import so this script has no import-time dependency on that one. Used
    only by --check-extraction-loss mode below; the script's default mode never needed format
    detection as its own step because load_judge_criteria() already branches on judge.toml vs
    verifier.json internally."""
    if (task_dir / "tests" / "verifier.json").is_file():
        return "ekw"
    if any(task_dir.glob("tests/**/judge.toml")):
        return "svc_pc"
    return "unknown"


def load_judge_criteria(task_dir):
    """Every [[criterion]] across every tests/deliverables/judge.toml or
    tests/deliverables_*/judge.toml, flattened, each carrying its own judge.files=[...] list
    and group (deliverables or deliverables_NN) for provenance.

    Format detection (additive, SVC-PC path unchanged): if a judge.toml is found under either
    naming, that TOML path runs exactly as before -- nothing below this comment changed. Only
    when NO judge.toml is found, and tests/verifier.json IS present (EKW's shape -- see
    ekw_verifier_json.py's module docstring), this delegates to
    ekw_verifier_json.load_ekw_criteria(task_dir), whose output already matches this function's
    {group, name, description, weight, type, files} shape. Neither shape present: returns []
    (same as the original SVC-PC-only behavior).

    2026-09-16 fix (tracker row 20): the glob only ever matched `deliverables_*` (a literal
    underscore required), never the plain `deliverables` directory name with no suffix.
    Confirmed real and silent, not a false pass but a complete skip: 89/600 real tasks
    (14.8%) use the plain `tests/deliverables/judge.toml` naming (e.g. SVC-PC-10-0-0 through
    SVC-PC-10-5-0, confirmed directly against the real corpus), and every one of them returned
    zero criteria from this function -- `resolve_graded_files` then had nothing to attribute
    findings to, and `matches_graded_criteria` was False on every finding for these 89 tasks
    regardless of whether a broken cell actually feeds a graded criterion. Same
    `set(...) | set(...)` two-glob convention already used elsewhere in this folder
    (criterion_groundedness_check.py's `check_task`, compound_criterion_check.py's
    `check_task`) for the identical plain-vs-suffixed naming split, not a new pattern invented
    here.
    """
    out = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return out
    judge_tomls = sorted(
        set(tests_dir.glob("deliverables/judge.toml"))
        | set(tests_dir.glob("deliverables_*/judge.toml"))
    )
    if not judge_tomls:
        if ekw_verifier_json is not None and ekw_verifier_json.has_ekw_config(task_dir):
            return ekw_verifier_json.load_ekw_criteria(task_dir)
        return out
    for jt in judge_tomls:
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
    disk under solution/ or, failing that, environment/ (accounting for a documented
    xlsm<->xlsx shim if present). This never gates whether a file gets analyzed --
    find_spreadsheets() already globs every .xlsx/.xlsm regardless -- it only produces the
    transparency note a report reader needs.

    2026-09-16 fix: a judge.toml files=[...] entry is not always a solver-produced
    deliverable -- many are source/input files the solver reads from
    environment/initial_workspace/ (sometimes nested under a _corpus_subtree/ mirror),
    included in files=[...] so the judge has them as grading context, not because the solver
    is meant to produce them into solution/. solution/ never holds these, so a solution/-only
    search misreported every such entry as "no file... found" even though the real judge reads
    it from environment/ just fine. Confirmed real, not theoretical, against this corpus: of
    the 125 "no resolved file on disk" instances across every real fail-tier
    --check-extraction-loss task in a full 202-task run (2026-09-16, before this fix),
    125/125 (100%) resolved to a real file under environment/ on direct existence check, zero
    genuinely absent -- see formula_health_extraction_loss fix note in the failure-mode
    tracker for the full verification. environment/ is only ever consulted as a fallback,
    after solution/'s own exact and shim checks both miss, so a solution/ file always wins if
    one exists with the same name."""
    sol_dir = task_dir / "solution"
    env_dir = task_dir / "environment"
    available = {}
    if sol_dir.is_dir():
        for p in sol_dir.rglob("*"):
            if p.is_file():
                available.setdefault(p.name.lower(), p)
    available_env = {}
    if env_dir.is_dir():
        for p in env_dir.rglob("*"):
            if p.is_file():
                available_env.setdefault(p.name.lower(), p)

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
        env_exact = available_env.get(expected_name.lower())
        if env_exact:
            resolved.append(
                {
                    "expected": expected,
                    "actual": str(env_exact.relative_to(task_dir)).replace("\\", "/"),
                    "note": (
                        f"judge.toml names '{expected_name}' but no file of this name exists "
                        "under solution/ -- found instead under environment/ "
                        f"({str(env_exact.relative_to(task_dir)).replace(chr(92), '/')}), "
                        "consistent with a source/input file the solver reads rather than a "
                        "deliverable the solver produces; treated as the real graded file for "
                        "extraction-loss purposes, NOT flagged as missing"
                    ),
                }
            )
            continue
        resolved.append(
            {
                "expected": expected,
                "actual": None,
                "note": "no file of this name (either extension) found under solution/ or "
                "environment/ -- possibly a non-spreadsheet deliverable, or a genuine "
                "missing-file defect (a structural-audit check's territory, not this script's "
                "concern)",
            }
        )
    return resolved


def _criteria_referencing_path(criteria, expected_path):
    """Every criterion dict (load_judge_criteria's {group, name, description, weight, type,
    files[, commands]} shape) whose own `files` list names this exact expected path string --
    used by --check-extraction-loss mode to scope its cross-reference to only the criteria that
    actually grade a given graded xlsx/xlsm, rather than the whole task's criteria (a tighter
    scope than analyze_workbook()'s own match_criteria() calls elsewhere in this file, which
    pass the full task criteria list -- deliberate here, since we already know precisely which
    criteria reference this file from resolve_graded_files()'s own `expected` key)."""
    return [c for c in criteria if expected_path in (c.get("files") or [])]


# ---------------------------------------------------------------------------
# --check-extraction-loss mode: does the file AS SHIPPED hand the real extractor a cached value
# for every formula cell, independent of whether the formula recomputes correctly (see
# EXTRACTION_CALL_NOTE above and analyze_extraction_loss_workbook's own docstring for why this
# is a different question than the recompute-based classify_cell()/analyze_workbook() above).
# ---------------------------------------------------------------------------


def analyze_extraction_loss_workbook(path):
    """Open `path` TWICE with openpyxl and compare, for every formula cell, what the LIVE
    formula source says (data_only=False -- used only to find formula cells via
    `cell.data_type == "f"`, confirmed empirically against this script's own existing formula
    detection convention -- `isinstance(cell.value, str) and cell.value.startswith("=")` -- to
    give an identical cell count on a real task, task_1/tronox_credit_model.xlsx: 142/142,
    2026-09-15) against what the REAL extractor's own call actually returns for that same cell
    (data_only=True, read_only=True -- see EXTRACTION_CALL_NOTE for exactly which real code path
    this matches, for each format).

    This is a structurally different question from classify_cell()/analyze_workbook() above:
    those ask "does this formula recompute to a correct value" (via the `formulas` library, a
    fresh calculation independent of anything cached in the file). This asks "does the file,
    EXACTLY AS IT SITS ON DISK RIGHT NOW -- no resave, no recompute, no `formulas` library
    involved at all -- hand the real judge a value for this cell." A formula can recompute
    perfectly (clean by every measure analyze_workbook() checks, including its own
    stale_cache_blank classification, which ALSO reads data_only=True cached values but not with
    read_only=True, and which analyze_workbook()'s own _finalize_findings() will actively mark
    non-actionable, as a presumed "uniform cache wipe" artifact, once a file's blank-cache
    fraction crosses 90% -- see module docstring section 2.5) and still arrive blank here: this
    function makes no such actionability judgment, because the shape that
    analyze_workbook()/_finalize_findings() treats as "just a wipe artifact, not a targeted
    defect" is EXACTLY the shape (near-total or total cache loss) that reproduces the real
    production failure this mode targets -- whatever caused the cache to be missing, a blank
    cached value under the real extractor's own call is what the judge sees, full stop.

    Returns (n_formula_cells, n_no_cached_value, blank_cells, load_error). blank_cells is a list
    of {"sheet", "cell", "formula", "row_label"} dicts, one per formula cell whose data_only=True
    reading is None or an empty string. Never raises -- a load failure on either pass is reported
    as load_error, matching analyze_workbook()'s own convention, never a crash."""
    try:
        wb_formula = openpyxl.load_workbook(str(path), data_only=False)
    except Exception as e:
        return (
            0,
            0,
            [],
            f"openpyxl could not open this file (data_only=False pass): {e}",
        )
    try:
        wb_extract = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    except Exception as e:
        return (
            0,
            0,
            [],
            "openpyxl could not open this file (data_only=True, read_only=True -- the real "
            f"extractor's own call): {e}",
        )

    n_formula = 0
    blank_cells = []
    try:
        for ws in wb_formula.worksheets:
            if ws.title not in wb_extract.sheetnames:
                continue
            ws_x = wb_extract[ws.title]
            # Build the extractor's cached-value lookup for this sheet in ONE forward pass,
            # then look up each formula cell in the resulting dict -- NOT
            # ws_x.cell(row=,column=) per formula cell. Found empirically necessary, not a
            # style preference: a read_only worksheet's `.cell(row=,column=)` calls
            # `_get_cell()` -> `_cells_by_row()`, which re-opens the workbook's underlying zip
            # entry and re-parses the sheet's XML from row 1 up to the requested row on EVERY
            # call (openpyxl.worksheet._read_only.ReadOnlyWorksheet._cells_by_row, confirmed by
            # reading its source, this installed version, 2026-09-15) -- there is no persistent
            # cursor or cache between calls. A first version of this function called `.cell()`
            # once per formula cell and made zero progress in 25+ minutes against the 274-task
            # EKW corpus (killed after reaching 270/274 -- confirmed empirically: 20 random
            # `.cell()` calls on one real sheet took 0.097s while building a dict for that
            # SAME SHEET's entire content via one iter_rows() pass took 0.046s FOR THE WHOLE
            # WORKBOOK, all sheets -- roughly 2x at task_1's modest scale alone (corrected here
            # after adversarial review caught the original comment's arithmetic: it does not
            # support the ">40x" figure it originally cited at this specific data point). The
            # real >40x number does hold, just not at this scale: on task_296's larger
            # 5,468-cell sheet, extrapolated per-cell `.cell()` cost came to roughly 128x the
            # actual `iter_rows()` time. So the per-call cost scales with row position, and it
            # gets worse on a larger sheet, not better -- the fix is necessary at real-corpus
            # scale even though the task_1 data point alone understates it. A single
            # `ws_x.iter_rows()` pass is exactly what read_only mode is
            # designed for (sequential streaming access) and gives correct results because a
            # missing key in `cached_by_coord` (a row/cell openpyxl's read-only iteration
            # skipped as fully empty) means "no value here" -- the same conclusion `.get()`'s
            # default already encodes, so no gap in coverage from skipping the random-access
            # API.
            cached_by_coord = {}
            for row in ws_x.iter_rows():
                for xcell in row:
                    if xcell.value is not None:
                        cached_by_coord[(xcell.row, xcell.column)] = xcell.value

            for row in ws.iter_rows():
                for cell in row:
                    if cell.data_type != "f":
                        continue
                    n_formula += 1
                    xv = cached_by_coord.get((cell.row, cell.column))
                    blank = xv is None or (isinstance(xv, str) and xv.strip() == "")
                    if blank:
                        # cell.value for an ARRAY formula (data_type == "f" same as a plain
                        # formula) is an openpyxl.worksheet.formula.ArrayFormula OBJECT, not a
                        # str -- its own str()/repr() is the unhelpful default object repr, not
                        # the formula text, and json.dump() cannot serialize it at all (crashed
                        # the first full SVC-PC run, TypeError: Object of type ArrayFormula is
                        # not JSON serializable, 2026-09-15, after ~2 minutes of otherwise-
                        # correct analysis across the whole 609-task corpus -- confirmed the
                        # crash was purely at the json.dump() boundary, not in the analysis
                        # itself, by re-running with --jobs 1 on the one task that hit it).
                        # `.text` is the real formula string for that object; a plain formula
                        # cell's `.value` is already the string directly.
                        formula_text = getattr(cell.value, "text", None)
                        if formula_text is None:
                            formula_text = cell.value
                        blank_cells.append(
                            {
                                "sheet": ws.title,
                                "cell": cell.coordinate,
                                "formula": formula_text,
                                "row_label": nearest_left_label(
                                    ws, cell.row, cell.column
                                ),
                            }
                        )
    finally:
        wb_extract.close()
    return n_formula, len(blank_cells), blank_cells, None


def analyze_task_extraction_loss(task_dir):
    """--check-extraction-loss mode, one task. For every xlsx/xlsm path actually named as a
    graded source in this task's own verifier.json (EKW) or judge.toml (SVC-PC) -- not every
    xlsx/xlsm under solution/ the way find_spreadsheets() globs for the default mode, since the
    question here is specifically what the real judge reads, and an ungraded xlsx sitting in
    solution/ is not read by anything -- resolve it to the actual on-disk file (reusing
    resolve_graded_files(), so a documented xlsm<->xlsx conversion shim is honored identically
    to the default mode) and run analyze_extraction_loss_workbook() against it.

    Status framing, deliberately calibrated against this file's OWN other checks rather than
    copied from either extreme (test_coverage_absence_check.py's "candidate, not confirmed" vs
    verifier_executability_check.py's "hard gate, no interpretation step"): the PER-CELL fact
    this reports -- "the real extractor's own call returns no cached value for this formula
    cell, in the file as it sits on disk right now" -- is mechanically confirmed, not an
    inference; there is no judgment call in "is this cell's data_only=True reading None". That
    part is asserted as `"confidence": "confirmed"` on every finding, same register as
    verifier_executability_check.py's gold-replay gate. What is NOT confirmed, and this function
    does not claim: whether any graded rubric criterion's actual verdict depends on this
    specific cell's value -- that needs a human (or a much deeper per-criterion grounding pass)
    to look at `matching_criteria` and decide, same caveat classify_cell()'s own
    "matches_graded_criteria" heuristic already carries elsewhere in this file. A task's
    `status` is "fail" if ANY graded formula cell has no cached value -- this reflects that the
    STRUCTURAL PRECONDITION for the S-3 defect is present, not a claim that this task's judge
    round will necessarily score it wrong.
    """
    task_id = task_dir.name
    fmt = _detect_format(task_dir)
    criteria = load_judge_criteria(task_dir)
    shim_scripts = detect_conversion_shim(task_dir)
    graded = resolve_graded_files(task_dir, criteria, shim_scripts)
    xlsx_graded = [
        g for g in graded if Path(g["expected"]).suffix.lower() in SPREADSHEET_SUFFIXES
    ]

    result = {
        "task_id": task_id,
        "format": fmt,
        "files_analyzed": [],
        "findings": [],
        "errors": [],
    }

    if fmt not in ("ekw", "svc_pc"):
        result["status"] = "not_applicable"
        result["errors"].append(
            f"format detection returned '{fmt}' (neither tests/verifier.json nor "
            "tests/**/judge.toml found under this task) -- cannot determine which extraction "
            "mechanism applies, so this check has nothing to test"
        )
        return result

    if not xlsx_graded:
        result["status"] = "pass"
        result["errors"].append(
            "no .xlsx/.xlsm path is named as a graded source in this task's own "
            "verifier.json/judge.toml -- nothing for this check to verify (not itself a "
            "defect; may be a non-spreadsheet-graded task)"
        )
        return result

    any_blank = False
    any_load_error = False
    for g in xlsx_graded:
        matching_criteria = _criteria_referencing_path(criteria, g["expected"])
        entry = {
            "expected": g["expected"],
            "actual": g["actual"],
            "resolution_note": g["note"],
            "matching_criteria": [
                {"group": c.get("group"), "name": c.get("name")}
                for c in matching_criteria
            ],
        }

        if fmt == "ekw":
            ekw_commands = sorted(
                {c for crit in matching_criteria for c in (crit.get("commands") or [])}
            )
            entry["extraction_commands"] = ekw_commands
            # tests/verifier_lib/sources/xlsx.py's data_only=True/read_only=True call is
            # confirmed for the "extract_text" command specifically (direct source read). A
            # minority of EKW criteria opt into "extract_formulas"/"extract_xlsx" instead (see
            # ekw_verifier_json.py's own _extract_commands docstring) -- those read LIVE
            # formulas and are not confirmed to share this mechanism. Still measured below for
            # completeness (not excluded), but flagged distinctly rather than assumed identical.
            entry["vulnerable_command"] = (not ekw_commands) or (
                "extract_text" in ekw_commands
            )
            if ekw_commands and "extract_text" not in ekw_commands:
                entry["command_note"] = (
                    f"every matching criterion reads this file via {ekw_commands}, not "
                    "extract_text -- the data_only=True mechanism is confirmed for extract_text "
                    "only; a finding below for this file is not confirmed to reach the real "
                    "judge the same way an extract_text file's finding would"
                )
        else:
            entry["svc_pc_extraction_path"] = EXTRACTION_CALL_NOTE
            if Path(g["expected"]).suffix.lower() == ".xlsm":
                entry["svc_pc_applicability"] = "different_mechanism"
                entry["command_note"] = (
                    "markitdown's _DOCUMENT_EXTENSIONS excludes .xlsm and its XlsxConverter."
                    "accepts() only matches the '.xlsx' extension, so rewardkit's own "
                    "_read_file_blocks() never routes a .xlsm file through "
                    "_convert_with_markitdown() at all -- it falls through to a plain "
                    "p.read_text() call, hits UnicodeDecodeError on the binary content, and "
                    "returns EMPTY content blocks. The real failure for a .xlsm graded file is "
                    "therefore total and unconditional (the judge gets nothing for the whole "
                    "file), not selective by formula-cache state the way this check's mechanism "
                    "is -- a different, more severe defect this check does not target. Not "
                    "observed in the SVC-PC corpus as of 2026-09-15 (0 .xlsm paths in any "
                    "judge.toml files=[...] entry) -- reported for completeness, not as a live "
                    "finding."
                )
            else:
                entry["svc_pc_applicability"] = "applicable_same_mechanism"

        if g["actual"] is None:
            entry["n_formula_cells"] = None
            entry["n_no_cached_value"] = None
            entry["pct_no_cached_value"] = None
            entry["load_error"] = "no resolved file on disk (see resolution_note)"
            result["files_analyzed"].append(entry)
            any_load_error = True
            result["errors"].append(
                f"{g['expected']}: no resolved file on disk (see resolution_note)"
            )
            continue

        path = task_dir / g["actual"]
        n_formula, n_blank, blank_cells, load_error = analyze_extraction_loss_workbook(
            path
        )
        pct = round(100.0 * n_blank / n_formula, 2) if n_formula else 0.0
        entry["n_formula_cells"] = n_formula
        entry["n_no_cached_value"] = n_blank
        entry["pct_no_cached_value"] = pct
        entry["load_error"] = load_error
        result["files_analyzed"].append(entry)

        if load_error:
            result["errors"].append(f"{g['actual']}: {load_error}")
            any_load_error = True
            continue

        if n_blank:
            any_blank = True
            for bc in blank_cells:
                matching = match_criteria(
                    bc["row_label"], bc["sheet"], None, matching_criteria
                )
                result["findings"].append(
                    {
                        "file": g["actual"],
                        "sheet": bc["sheet"],
                        "cell": bc["cell"],
                        "formula": bc["formula"],
                        "row_label": bc["row_label"],
                        "kind": "extraction_cache_loss",
                        "confidence": "confirmed",
                        "note": (
                            "openpyxl.load_workbook(path, data_only=True, read_only=True) -- "
                            "the real extractor's own call -- returns no cached value for this "
                            "formula cell in the file AS SHIPPED. Mechanically confirmed fact "
                            "about what the real judge reads, not an inference. NOT confirmed "
                            "by this check: whether any graded criterion actually depends on "
                            "this exact cell -- see matches_graded_criteria (same text-overlap "
                            "heuristic, and the same limitation, as the rest of this script)."
                        ),
                        "matches_graded_criteria": bool(matching),
                        "matching_criteria": matching,
                    }
                )

    result["summary"] = {
        "n_graded_xlsx_files": len(xlsx_graded),
        "n_files_with_extraction_loss": sum(
            1
            for fa in result["files_analyzed"]
            if (fa.get("n_no_cached_value") or 0) > 0
        ),
        "n_findings": len(result["findings"]),
    }
    # A load error means this task's clean-ness was never actually established -- reporting it
    # as "pass" (found and fixed by adversarial review: 3 of 4 corrupt-xlsx SVC-PC cases were
    # silently passing, invisible in the CLI stdout summary since the printer only shows
    # `errors` when status != "pass") would be a false-negative-by-omission, not a real finding.
    result["status"] = "fail" if (any_blank or any_load_error) else "pass"
    return result


def _analyze_task_extraction_loss_safe(task_dir):
    """Module-level wrapper so ProcessPoolExecutor can pickle it (Windows spawn requires a
    top-level, importable target). Never lets one task's crash kill the whole batch -- mirrors
    _analyze_task_safe's own convention exactly."""
    try:
        return analyze_task_extraction_loss(task_dir)
    except Exception as e:
        return {
            "task_id": task_dir.name,
            "format": "unknown",
            "status": "fail",
            "errors": [f"unhandled exception analyzing this task: {e}"],
            "findings": [],
            "files_analyzed": [],
            "summary": {
                "n_graded_xlsx_files": 0,
                "n_files_with_extraction_loss": 0,
                "n_findings": 0,
            },
        }


# ---------------------------------------------------------------------------
# per-cell classification
# ---------------------------------------------------------------------------


def nearest_left_label(ws, row, col):
    for c in range(col - 1, 0, -1):
        v = ws.cell(row=row, column=c).value
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def strip_string_literals(formula_text):
    """Blank out double-quoted string literal contents so cell-ref-shaped text inside a literal
    (e.g. the B5 in ="Error B5") is never mistaken for an actual reference. Keeps the string the
    same length (irrelevant here, just avoids reflowing positions) by replacing with an empty
    literal rather than deleting the span."""
    return STRING_LITERAL_RE.sub('""', formula_text or "")


def iter_cell_refs(formula_text):
    """Yield one dict per cell reference / range found in a formula string, sheet-qualified or
    bare: {"text", "qualified": bool, "is_range": bool, "row": int|None}. Best-effort regex
    tokenizer, not a real Excel formula parser -- see the module docstring's Known limits for
    mixed_qualifier_smell / out_of_bounds_unqualified_ref."""
    for m in CELL_TOKEN_RE.finditer(strip_string_literals(formula_text)):
        row_match = REF_ROW_RE.search(m.group("ref"))
        yield {
            "text": m.group(0),
            "qualified": m.group("sheet") is not None,
            "is_range": m.group("range_end") is not None,
            "row": int(row_match.group()) if row_match else None,
        }


def find_mixed_qualifier_smell(formula_text):
    """Heuristic 1: the formula contains at least one explicit 'SheetName!' reference AND at
    least one FULLY-$-ANCHORED bare (unqualified) cell reference (e.g. '$B$7', not 'B7' or
    '$B7') in the same expression.

    The full-anchoring requirement is a deliberate precision filter, confirmed against real data
    in this session, not part of a looser literal reading of "any bare reference": a same-sheet
    RELATIVE bare reference that shifts naturally with the formula's own column (e.g.
    '=B6*Assumptions!$B$24' in column B, '=C6*Assumptions!$C$24' in column C -- the bare side
    tracks the formula's own position) is the ordinary, correct way to combine a same-sheet
    subtotal with a cross-sheet lever, and this session's own broader testing found it to be
    common: one real task's Working_Capital/Channel_Model sheets alone carried dozens of such
    legitimate cells. A bare reference anchored on BOTH axes ('$B$7'), by contrast, is a
    same-sheet cell an author deliberately pinned so it would NOT shift when the formula is
    copied across columns -- exactly the shape of "a constant lookup value", which is also
    exactly what an author reaching across sheets writes when the qualifier survives. Confirmed
    on the real precedent (SVC-PC-58-2-0, Working_Capital!B5/C5/D5 and its siblings at rows
    16 and 27, all using '$B$7'/'$C$7'/'$D$7' unchanged across the row) that this narrower test
    still catches the true positive with zero loss, while eliminating every false positive found
    in this session's own testing of the looser (any-bare-ref) version. See the module
    docstring's Known limits for what this narrower test can still miss."""
    refs = list(iter_cell_refs(formula_text))
    bare_refs = [
        r["text"]
        for r in refs
        if not r["qualified"] and FULLY_ABSOLUTE_REF_RE.match(r["text"])
    ]
    if bare_refs and any(r["qualified"] for r in refs):
        return {
            "kind": "mixed_qualifier_smell",
            "severity": "medium",
            "bare_refs": sorted(set(bare_refs)),
        }
    return None


def find_out_of_bounds_unqualified_ref(formula_text, current_sheet_max_row):
    """Heuristic 2: a bare (unqualified), single (non-range) cell reference whose row number
    exceeds the CURRENT sheet's own used range. Deliberately excludes range endpoints -- see the
    module docstring's Known limits."""
    if not current_sheet_max_row:
        return None
    offenders = sorted(
        {
            r["text"]
            for r in iter_cell_refs(formula_text)
            if not r["qualified"]
            and not r["is_range"]
            and r["row"] is not None
            and r["row"] > current_sheet_max_row
        }
    )
    if offenders:
        return {
            "kind": "out_of_bounds_unqualified_ref",
            "severity": "high",
            "offending_refs": offenders,
            "sheet_max_row": current_sheet_max_row,
        }
    return None


# ---------------------------------------------------------------------------
# heuristic 3: cross_scenario_monotonicity (row/sheet-level, not per-cell)
# ---------------------------------------------------------------------------


def scenario_header_rows(ws):
    """Find every row on this sheet with 2+ cells, in ADJACENT columns, whose string value
    (case-insensitive, exact match) is a known scenario token (Base/Downside/Upside/
    Conservative/Optimistic/... -- see SCENARIO_TOKENS). Returns a list of
    (row_number, {column_index: token}). Requiring adjacency (not just 2+ anywhere in the row)
    is what the module docstring's heuristic-3 description means by "adjacent columns of the
    same row" -- it is what distinguishes a real scenario-comparison table header from two
    unrelated cells that happen to share a row."""
    headers = []
    for row in ws.iter_rows():
        matches = {}
        for cell in row:
            if isinstance(cell.value, str):
                norm = cell.value.strip().lower()
                if norm in SCENARIO_TOKENS:
                    matches[cell.column] = norm
        if len(matches) < 2:
            continue
        cols = sorted(matches)
        if any(b - a == 1 for a, b in zip(cols, cols[1:])):
            headers.append((row[0].row, matches))
    return headers


def _is_alternate_header_row(ws, row_idx, columns):
    """True if EVERY one of the scenario header's own columns holds a non-blank string on this
    row, and at least one of them is NOT itself a scenario token. Signals that the sheet has
    moved into a new table block that reuses the same column letters for a different axis (e.g.
    a "Year 1 | Year 2 | Year 3" row reusing the exact columns a "Base | Upside | Downside" row
    used higher up) -- confirmed in this session's testing (Channel_Model row 16 reuses row 5's
    columns for years, not scenarios). Used to bound the driver/metric search to the SAME table
    block as the header, never past a row that redefines what the columns mean."""
    vals = []
    for col in columns:
        v = ws.cell(row=row_idx, column=col).value
        if not (isinstance(v, str) and v.strip()):
            return False
        vals.append(v.strip().lower())
    return any(v not in SCENARIO_TOKENS for v in vals)


def _block_end_row(ws, header_row, columns):
    """Last row of the table block that starts at header_row: scan downward (data follows its
    header, not the reverse) up to MONOTONICITY_SEARCH_WINDOW rows, stopping one row short of the
    first alternate-header boundary if one is found."""
    limit = min(ws.max_row, header_row + MONOTONICITY_SEARCH_WINDOW)
    for r in range(header_row + 1, limit + 1):
        if _is_alternate_header_row(ws, r, columns):
            return r - 1
    return limit


def _looks_like_driver_label(label):
    """A driver-QUANTITY row (e.g. "Units (order-equivalent)"), not a per-unit RATE row (e.g.
    "Cost / unit", "Price per unit") -- a plain substring match on "unit" catches almost every
    per-unit-economics label in a typical model and was confirmed to misfire in exactly that
    shape during this session's testing (see module docstring Known limits)."""
    if not label:
        return False
    if RATE_DENOMINATOR_RE.search(label):
        return False
    return bool(DRIVER_KEYWORD_RE.search(label))


def find_driver_row_and_values(ws_cached, header_row, block_end, columns):
    """Best-effort: from directly below a scenario header down to block_end (the same table
    block, never past a column-redefinition boundary -- see _block_end_row), find a row whose
    left-hand label looks like a driver-QUANTITY row (_looks_like_driver_label) and has a real
    number in every one of the header's scenario columns. Returns (row_number, label,
    {column_index: float}) or (None, None, None) if nothing confidently matches -- callers must
    not guess past that, per the module docstring."""
    min_col = min(columns)
    for r in range(header_row + 1, block_end + 1):
        label = nearest_left_label(ws_cached, r, min_col)
        if not _looks_like_driver_label(label):
            continue
        values = {}
        for col in columns:
            v = ws_cached.cell(row=r, column=col).value
            if not is_numeric(v):
                values = None
                break
            values[col] = float(v)
        if values:
            return r, label, values
    return None, None, None


def monotonicity_findings_for_sheet(ws_formula, ws_cached, sheet_title):
    """Heuristic 3, best-effort: for every scenario-header row found on this sheet, look for a
    driver-quantity row in the SAME table block (find_driver_row_and_values, bounded by
    _block_end_row so a lower block that reuses the same columns for a different axis is never
    mistaken for this header's own data); if none is found, emit one
    monotonicity_check_skipped_no_driver_link finding for that header rather than silently doing
    nothing. Otherwise, for every OTHER row in that SAME block whose left-hand label suggests a
    cost/volume-driven metric (COST_METRIC_KEYWORDS), compare every pair of scenario columns by
    cached value: if the column with the SMALLER driver quantity has a LARGER magnitude in the
    metric row than the column with the larger driver, emit cross_scenario_monotonicity. Reads
    cached values only (see module docstring Known limits) so it runs even when the `formulas`
    recompute step fails."""
    findings = []
    # Header/boundary/label detection all reads the CACHED workbook, never the formula one: a
    # formula cell's ws_formula.value is its "=..." source text (a str), which would otherwise
    # make _is_alternate_header_row see a "string" in every formula cell and treat the row right
    # after almost any header as an immediate block boundary -- confirmed to misfire exactly this
    # way during this session's testing. ws_cached shows what a reader actually sees: a number
    # for a formula cell, the literal text for a static label.
    for header_row, columns in scenario_header_rows(ws_cached):
        block_end = _block_end_row(ws_cached, header_row, columns)
        driver_row, driver_label, driver_values = find_driver_row_and_values(
            ws_cached, header_row, block_end, columns
        )
        if driver_row is None:
            findings.append(
                {
                    "sheet": sheet_title,
                    "cell": f"row {header_row}",
                    "formula": None,
                    "row_label": None,
                    "cached_value": None,
                    "recomputed_value": None,
                    "kind": "monotonicity_check_skipped_no_driver_link",
                    "severity": "info",
                    "error": None,
                    "matches_graded_criteria": False,
                    "matching_criteria": [],
                    "note": (
                        "found a scenario header row ("
                        + ", ".join(sorted(set(columns.values())))
                        + f") at row {header_row}, table block through row {block_end}, but no "
                        "row in that block has a label that looks like a driver-QUANTITY row "
                        "(unit/units/volume/quantity/qty, excluding a per-unit RATE phrasing "
                        "like 'cost / unit') with a real number in every scenario column -- "
                        "skipped rather than guessing which value represents each scenario's "
                        "driver quantity."
                    ),
                }
            )
            continue

        cols_sorted = sorted(columns)
        for r in range(header_row + 1, block_end + 1):
            if r == driver_row:
                continue
            label = nearest_left_label(ws_cached, r, cols_sorted[0])
            if not label or not any(k in label.lower() for k in COST_METRIC_KEYWORDS):
                continue
            metric_values = {}
            for col in columns:
                v = ws_cached.cell(row=r, column=col).value
                if not is_numeric(v):
                    metric_values = None
                    break
                metric_values[col] = float(v)
            if not metric_values:
                continue

            for i, col_a in enumerate(cols_sorted):
                for col_b in cols_sorted[i + 1 :]:
                    da, db = driver_values[col_a], driver_values[col_b]
                    if abs(da) == abs(db):
                        continue
                    smaller_col, larger_col = (
                        (col_a, col_b) if abs(da) < abs(db) else (col_b, col_a)
                    )
                    m_small, m_large = (
                        metric_values[smaller_col],
                        metric_values[larger_col],
                    )
                    if abs(m_small) <= abs(m_large):
                        continue
                    cell_coord = ws_formula.cell(row=r, column=smaller_col).coordinate
                    findings.append(
                        {
                            "sheet": sheet_title,
                            "cell": cell_coord,
                            "formula": ws_formula.cell(row=r, column=smaller_col).value,
                            "row_label": label,
                            "cached_value": to_jsonable(m_small),
                            "recomputed_value": None,
                            "kind": "cross_scenario_monotonicity",
                            "severity": "medium",
                            "error": None,
                            "matches_graded_criteria": False,
                            "matching_criteria": [],
                            "note": (
                                f"scenario '{columns[smaller_col]}' (driver '{driver_label}'="
                                f"{driver_values[smaller_col]:g}) shows a LARGER magnitude "
                                f"({abs(m_small):g}) in row '{label}' than scenario "
                                f"'{columns[larger_col]}' (driver={driver_values[larger_col]:g}, "
                                f"magnitude={abs(m_large):g}) -- a smaller driver quantity "
                                "should not produce a bigger cost/volume-driven value. "
                                "Best-effort heuristic (see module docstring Known limits); "
                                "verify by hand."
                            ),
                        }
                    )
    return findings


# ---------------------------------------------------------------------------
# heuristic 4 (section 2.6): guarded-blank detection -- reclassifies an existing
# stale_cache_blank/recompute_blank finding rather than creating a new one. See module docstring
# section 2.6 and Known limits.
# ---------------------------------------------------------------------------


def _is_blank_value(v):
    """Same 'blank' test classify_cell() already applies to a cached value inline (None, an
    empty/whitespace string, or NaN) -- pulled out here as its own function rather than
    refactoring classify_cell's existing inline version, so this addition cannot change that
    function's own, already-battle-tested behavior."""
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    if is_numeric(v):
        try:
            return math.isnan(float(v))
        except (TypeError, ValueError):
            return False
    return False


def _split_top_level_commas(s):
    """Split s on commas that are not inside parens or a double-quoted string literal.
    Best-effort, not a real Excel parser -- consistent with this module's other syntactic
    heuristics (see find_mixed_qualifier_smell / find_out_of_bounds_unqualified_ref)."""
    parts, depth, in_str, buf = [], 0, False, []
    for ch in s:
        if in_str:
            buf.append(ch)
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _match_whole_if_call(formula_text):
    """If formula_text (with or without its leading '=') is, in its entirety, a single
    top-level IF(...) call -- nothing before it, nothing after its own closing paren -- return
    the paren-and-quote-aware split of its top-level arguments. Returns None otherwise
    (including: not an IF call at all, or an IF call wrapped inside/followed by anything else).
    Deliberately conservative, same spirit as this module's other syntactic-only heuristics: a
    formula this doesn't recognize is left alone, never guessed at."""
    s = (formula_text or "").strip()
    if s.startswith("="):
        s = s[1:]
    m = re.match(r"^IF\s*\(", s, re.IGNORECASE)
    if not m or not s.endswith(")"):
        return None
    body = s[m.end() : -1]
    depth = 0
    in_str = False
    for ch in body:
        if in_str:
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                # this IF( closed before the string's own final ')' -- that final paren
                # belongs to something else, so the whole-formula shape this function looks
                # for does not hold.
                return None
    if depth != 0:
        return None
    return _split_top_level_commas(body)


def _iter_condition_refs(condition_text):
    """Yield (sheet_qualifier_or_None, ref_text) for every single-cell (non-range) reference in
    an IF condition string. Deliberately a separate, smaller scan rather than reusing
    iter_cell_refs()'s exact return shape, so find_mixed_qualifier_smell /
    find_out_of_bounds_unqualified_ref (which already depend on that shape) stay untouched.
    """
    for m in CELL_TOKEN_RE.finditer(strip_string_literals(condition_text)):
        if m.group("range_end") is not None:
            continue
        yield m.group("sheet"), m.group("ref")


def _lookup_cached_value(wb_cached, current_sheet_title, sheet_qualifier, ref):
    """Look up one cell's CACHED value (not a recompute) in wb_cached. `ref` may carry $
    anchors (e.g. '$B$5'); `sheet_qualifier` is the raw regex-captured sheet name (possibly
    single-quoted) or None for a bare, same-sheet reference. Returns (value, found) -- found is
    False when the sheet or the ref itself can't be resolved, so the caller can stay
    conservative (a reference this can't resolve is never treated as 'confirmed present').
    """
    sheet_name = sheet_qualifier.strip("'") if sheet_qualifier else current_sheet_title
    if sheet_name not in wb_cached.sheetnames:
        return None, False
    try:
        col_str, row_num = openpyxl.utils.cell.coordinate_from_string(ref)
        col_idx = openpyxl.utils.column_index_from_string(col_str)
    except ValueError:
        return None, False
    ws = wb_cached[sheet_name]
    return ws.cell(row=row_num, column=col_idx).value, True


def find_guarded_blank_cause(formula_text, current_sheet_title, wb_cached):
    """Heuristic 4 (module docstring section 2.6): formula_text is IF(<condition>, <expr>, "")
    in its entirety, and the caller already knows (via classify_cell) that this cell's blank
    branch was the one taken. If every cell <condition> itself references resolves to a
    genuinely PRESENT cached value -- real, non-blank, whether that's numeric zero, a negative
    number, or non-numeric text -- the blank result is this formula's own designed handling of
    the current inputs, not an engine dead end or a missing cached value: returns a
    human-readable cause string naming the qualifying cell(s) and their values. Returns None
    (leave the finding exactly as classified) when the formula doesn't match this shape, the
    condition references no resolvable single cell, or ANY referenced cell is itself
    blank/missing -- a guard whose own input never arrived is still a real defect (see
    SVC-PC-6-1-0's Balance Sheet Support!D22, the negative-control precedent in the module
    docstring)."""
    args = _match_whole_if_call(formula_text)
    if not args or len(args) != 3:
        return None
    condition, _true_expr, false_expr = args
    if false_expr.strip() != '""':
        return None
    refs = list(_iter_condition_refs(condition))
    if not refs:
        return None
    resolved_inputs = []
    for sheet_q, ref in refs:
        val, found = _lookup_cached_value(wb_cached, current_sheet_title, sheet_q, ref)
        if not found or _is_blank_value(val):
            return None
        resolved_inputs.append(f"{(sheet_q + '!') if sheet_q else ''}{ref}={val!r}")
    return (
        'formula is IF(<condition>,...,"") and every cell the condition references is '
        f"present, not blank ({', '.join(resolved_inputs)})"
    )


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


def _make_finding(info, kind, severity, rv, matching, error=None, **extra):
    finding = {
        "sheet": info["sheet"],
        "cell": info["cell"],
        "formula": info["formula"],
        "row_label": info["label"],
        "cached_value": to_jsonable(info["cached"]),
        "recomputed_value": to_jsonable(rv),
        "kind": kind,
        "severity": severity,
        # to_jsonable(), not raw -- classify_cell()'s "recompute_error" path sets this straight
        # from `recomputed_value` (the same unwrapped formulas value `rv` above already goes
        # through to_jsonable() for), so an XlError here needs the identical conversion or it
        # leaks through this second, easy-to-miss field instead. Confirmed this was still
        # crashing end-to-end on the real failing tasks even after fixing to_jsonable() alone.
        "error": to_jsonable(error),
        "matches_graded_criteria": bool(matching),
        "matching_criteria": matching,
    }
    finding.update(extra)
    return finding


def _finalize_findings(findings, meta):
    """Whole-file cache-wipe detection: a file that went through an openpyxl load+save round
    trip anywhere upstream loses EVERY cached formula result at once -- openpyxl's save() strips
    cached values unconditionally, on every formula cell, regardless of whether that formula is
    actually broken. That shows up here as a huge run of stale_cache_blank findings that all
    recompute cleanly. That is a mechanical artifact of a known conversion step, not a targeted
    defect in this task's authoring, so it must not be confused with localized, genuine cache
    gaps. Distinguish by shape: if almost every formula cell in the file is blank-cache AND none
    of them are hard breaks (recompute_error / recompute_blank / an engine-unresolved cell), this
    is a uniform wipe, not a scatter of real defects.

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
        elif f["kind"] == "monotonicity_check_skipped_no_driver_link":
            f["actionable"] = False
            f["suppressed_reason"] = (
                "a scenario header row was found on this sheet but no nearby row's label "
                "contains a driver-quantity keyword (unit/units/volume/quantity/qty) with a "
                "real number in every scenario column -- the cross_scenario_monotonicity "
                "heuristic will not guess which value represents each scenario's driver, so it "
                "skipped this header block rather than asserting an anomaly it could not "
                "confidently ground. Not counted toward this task's fail/pass status."
            )
        elif f["kind"] in ("stale_cache_blank", "recompute_blank") and f.get(
            "guarded_blank_cause"
        ):
            f["actionable"] = False
            f["suppressed_reason"] = (
                f"{f['guarded_blank_cause']} -- this is the formula's own designed handling of "
                "the current input combination (see module docstring section 2.6), not an "
                "engine dead end or a missing cached value. Not counted toward this task's "
                "fail/pass status. Still listed here for completeness; re-check by hand if this "
                "cell matches a graded criterion (matches_graded_criteria)."
            )
        elif f["kind"] == "stale_cache_blank" and uniform_wipe:
            f["actionable"] = False
            f["suppressed_reason"] = (
                f"{stale_count}/{total_formula} ({fraction_stale:.0%}) of this file's formula "
                "cells have a blank cache and every one of them recomputes cleanly to a real, "
                "non-error value -- the signature of a whole-file cache wipe (an openpyxl "
                "load+save round trip somewhere upstream), not a targeted authoring defect. Not "
                "counted toward this task's fail/pass status. Still listed here for "
                "completeness (e.g. if a cache-value patch is ever wanted)."
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

    # max_row per sheet, captured once, up front -- used by out_of_bounds_unqualified_ref below.
    # Taken from wb_formula (not wb_cached): both reflect the same on-disk used range, but the
    # formula-bearing workbook is the one already open for the cell loop right below.
    max_row_by_sheet = {ws.title: ws.max_row for ws in wb_formula.worksheets}

    formula_map = {}
    for ws in wb_formula.worksheets:
        if ws.title not in wb_cached.sheetnames:
            continue
        ws_cached = wb_cached[ws.title]

        # cross_scenario_monotonicity (heuristic 3) is row/sheet-level, not per-formula-cell, and
        # needs no successful recompute -- run it here, per worksheet, independent of whether
        # this sheet (or this workbook) has any formula cells at all.
        findings.extend(monotonicity_findings_for_sheet(ws, ws_cached, ws.title))

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
        return _finalize_findings(findings, meta), meta

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
                _make_finding(info, "unresolved_by_engine", "info", None, [])
            )
            # the syntactic heuristics below need no recompute at all -- run them even on this
            # engine-failure path, same as they run on the success path further down.
            smell = find_mixed_qualifier_smell(info["formula"])
            if smell is not None:
                matching = match_criteria(info["label"], info["sheet"], None, criteria)
                findings.append(
                    _make_finding(
                        info,
                        smell["kind"],
                        smell["severity"],
                        None,
                        matching,
                        bare_refs=smell["bare_refs"],
                    )
                )
            oob = find_out_of_bounds_unqualified_ref(
                info["formula"], max_row_by_sheet.get(info["sheet"])
            )
            if oob is not None:
                matching = match_criteria(info["label"], info["sheet"], None, criteria)
                findings.append(
                    _make_finding(
                        info,
                        oob["kind"],
                        oob["severity"],
                        None,
                        matching,
                        offending_refs=oob["offending_refs"],
                        sheet_max_row=oob["sheet_max_row"],
                    )
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
        matching = (
            None  # computed lazily, at most once per cell, shared across findings below
        )

        c = classify_cell(info["formula"], info["cached"], rv, resolved=resolved)
        if c is not None:
            matching = match_criteria(info["label"], info["sheet"], rv, criteria)
            extra = {}
            if c["kind"] in ("stale_cache_blank", "recompute_blank"):
                # heuristic 4 / section 2.6: does not change c["kind"] or c["severity"] --
                # _finalize_findings() is the single place that turns this into
                # actionable=False, same as every other downgrade in this module.
                guard_cause = find_guarded_blank_cause(
                    info["formula"], info["sheet"], wb_cached
                )
                if guard_cause:
                    extra["guarded_blank_cause"] = guard_cause
            findings.append(
                _make_finding(
                    info,
                    c["kind"],
                    c["severity"],
                    rv,
                    matching,
                    c.get("error"),
                    **extra,
                )
            )

        # mixed_qualifier_smell / out_of_bounds_unqualified_ref (heuristics 1 & 2): purely
        # syntactic, so these run regardless of `resolved` and regardless of classify_cell's own
        # result above -- a cell can carry both a recompute-based finding and one of these.
        smell = find_mixed_qualifier_smell(info["formula"])
        if smell is not None:
            if matching is None:
                matching = match_criteria(info["label"], info["sheet"], rv, criteria)
            findings.append(
                _make_finding(
                    info,
                    smell["kind"],
                    smell["severity"],
                    rv,
                    matching,
                    bare_refs=smell["bare_refs"],
                )
            )

        oob = find_out_of_bounds_unqualified_ref(
            info["formula"], max_row_by_sheet.get(info["sheet"])
        )
        if oob is not None:
            if matching is None:
                matching = match_criteria(info["label"], info["sheet"], rv, criteria)
            findings.append(
                _make_finding(
                    info,
                    oob["kind"],
                    oob["severity"],
                    rv,
                    matching,
                    offending_refs=oob["offending_refs"],
                    sheet_max_row=oob["sheet_max_row"],
                )
            )

    return _finalize_findings(findings, meta), meta


def _analyze_task_safe(task_dir):
    """Module-level wrapper so ProcessPoolExecutor can pickle it (Windows spawn requires a
    top-level, importable target). Never lets one task's crash kill the whole batch."""
    try:
        return analyze_task(task_dir)
    except Exception as e:
        return {
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


def analyze_task(task_dir):
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


def _run_extraction_loss_mode(task_dirs, args):
    """--check-extraction-loss mode's own run loop, printing, and JSON output -- kept separate
    from main()'s default-mode loop rather than interleaved with it, so the default mode's
    control flow is untouched (additive, per this mode's own design goal)."""
    results = []
    if args.jobs <= 1 or len(task_dirs) <= 1:
        for i, task_dir in enumerate(task_dirs, 1):
            print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
            r = _analyze_task_extraction_loss_safe(task_dir)
            results.append(r)
            print(
                f"    -> {r['status']}  "
                f"({r.get('summary', {}).get('n_findings', 0)} findings, "
                f"{len(r.get('errors', []))} errors)",
                file=sys.stderr,
            )
    else:
        print(
            f"Checking extraction loss for {len(task_dirs)} tasks with {args.jobs} parallel "
            f"workers (each task's own graded xlsx/xlsm files, independent)...",
            file=sys.stderr,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as ex:
            future_to_dir = {
                ex.submit(_analyze_task_extraction_loss_safe, td): td
                for td in task_dirs
            }
            done = 0
            for fut in concurrent.futures.as_completed(future_to_dir):
                task_dir = future_to_dir[fut]
                done += 1
                r = fut.result()  # _analyze_task_extraction_loss_safe never raises
                results.append(r)
                print(
                    f"[{done}/{len(task_dirs)}] {task_dir.name} -> {r['status']}  "
                    f"({r.get('summary', {}).get('n_findings', 0)} findings, "
                    f"{len(r.get('errors', []))} errors)",
                    file=sys.stderr,
                )
        results.sort(key=lambda r: r.get("task_id", ""))

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_na = sum(1 for r in results if r["status"] == "not_applicable")
    by_format = {}
    for r in results:
        fmt = r.get("format", "unknown")
        d = by_format.setdefault(
            fmt, {"n_tasks": 0, "n_pass": 0, "n_fail": 0, "n_na": 0}
        )
        d["n_tasks"] += 1
        d[
            (
                "n_pass"
                if r["status"] == "pass"
                else "n_fail" if r["status"] == "fail" else "n_na"
            )
        ] += 1

    total_formula_cells = 0
    total_blank_cells = 0
    for r in results:
        for fa in r.get("files_analyzed", []):
            total_formula_cells += fa.get("n_formula_cells") or 0
            total_blank_cells += fa.get("n_no_cached_value") or 0

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "mode": "check-extraction-loss",
        "extraction_call_note": EXTRACTION_CALL_NOTE,
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_not_applicable": n_na,
        "by_format": by_format,
        "total_formula_cells_checked": total_formula_cells,
        "total_cells_with_no_cached_value": total_blank_cells,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_na} not_applicable out of {len(results)} task(s)"
    )
    print(
        f"{total_blank_cells}/{total_formula_cells} graded formula cells have no cached value "
        "under the real extractor's own call, across all tasks checked"
    )
    for fmt, d in sorted(by_format.items()):
        print(
            f"  format={fmt}: {d['n_pass']} pass / {d['n_fail']} fail / {d['n_na']} n/a "
            f"({d['n_tasks']} tasks)"
        )
    for r in results:
        if r["status"] == "fail":
            print(f"  {r['task_id']}: FAIL")
            for fa in r.get("files_analyzed", []):
                if (fa.get("n_no_cached_value") or 0) > 0:
                    print(
                        f"      {fa['actual']}: {fa['n_no_cached_value']}/"
                        f"{fa['n_formula_cells']} ({fa['pct_no_cached_value']}%) formula cells "
                        "have no cached value"
                    )
        for e in r.get("errors", []):
            if r["status"] != "pass":
                print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


def main():
    ap = argparse.ArgumentParser(
        description="Recalculate every formula in a task's golden workbook(s) and report cells "
        "that error out or read blank/NaN, cross-referenced against the task's own judge.toml "
        "criteria."
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
        "this is a generalized copy that must not silently assume a project-specific path)",
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
    ap.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=max(1, (os.cpu_count() or 4) - 1),
        help="parallel worker processes for task analysis (default: cpu_count-1 on this "
        "machine, %(default)s; pass 1 to force serial). Each task recalculates its own "
        "workbook independently -- this is embarrassingly parallel, not a --all-only "
        "optimization, so it applies whether you pass --all or explicit task ids.",
    )
    ap.add_argument(
        "--check-extraction-loss",
        action="store_true",
        help="ADDITIVE alternate mode -- runs INSTEAD of the default recompute-based check, "
        "does not change or remove it. For every xlsx/xlsm path actually named as a graded "
        "source in this task's own verifier.json/judge.toml, opens it twice with openpyxl "
        "(data_only=False to find formula cells; data_only=True, read_only=True -- the real "
        "extractor's own call, see EXTRACTION_CALL_NOTE -- to see what a real judge actually "
        "reads) and reports every formula cell whose real-extractor reading has no cached "
        "value, AS THE FILE SITS ON DISK RIGHT NOW, independent of whether the formula itself "
        "recomputes correctly. No `formulas` library recompute involved in this mode at all. "
        "See analyze_extraction_loss_workbook()'s docstring for why this is a structurally "
        "different question than the script's default mode.",
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error(
            "--root is required (point it at the directory containing your task folders)"
        )

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        sys.exit(1)

    if args.check_extraction_loss:
        _run_extraction_loss_mode(task_dirs, args)
        return

    results = []
    if args.jobs <= 1 or len(task_dirs) <= 1:
        for i, task_dir in enumerate(task_dirs, 1):
            print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
            r = _analyze_task_safe(task_dir)
            results.append(r)
            print(
                f"    -> {r['status']}  "
                f"({r.get('summary', {}).get('n_findings', 0)} findings, "
                f"{len(r.get('errors', []))} errors)",
                file=sys.stderr,
            )
    else:
        print(
            f"Analyzing {len(task_dirs)} tasks with {args.jobs} parallel workers "
            f"(each task recalculates its own workbook independently, so this is "
            f"embarrassingly parallel)...",
            file=sys.stderr,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as ex:
            future_to_dir = {ex.submit(_analyze_task_safe, td): td for td in task_dirs}
            done = 0
            for fut in concurrent.futures.as_completed(future_to_dir):
                task_dir = future_to_dir[fut]
                done += 1
                r = fut.result()  # _analyze_task_safe never raises
                results.append(r)
                print(
                    f"[{done}/{len(task_dirs)}] {task_dir.name} -> {r['status']}  "
                    f"({r.get('summary', {}).get('n_findings', 0)} findings, "
                    f"{len(r.get('errors', []))} errors)",
                    file=sys.stderr,
                )
        # worker completion order isn't task order; sort for stable, diffable output
        results.sort(key=lambda r: r.get("task_id", ""))

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    aggregate = {
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
