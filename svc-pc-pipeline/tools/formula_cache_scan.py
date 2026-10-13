#!/usr/bin/env python3
"""
formula_cache_scan.py - GATE-V2 class K: golden xlsx formula cells whose
cached (data_only) value reads None. Extended 12:45 UTC (25-4-0, 53-0-0,
53-5-0) with two more golden-xlsx defect passes: row-caption contradiction
and repeated Sources-column boilerplate.

rewardkit 0.2.0 extracts xlsx with MarkItDown, which reads cached cell
values, never formulas (GATE-V2.md 1b class K). A formula cell with no
cached value therefore extracts as NaN/empty for the judge, whether that
cell sits in the golden or in a compliant agent's own formula-driven
workbook. This script checks the GOLDEN side of that: `formula_cache_scan`
default mode opens every task's golden xlsx twice with openpyxl (once
data_only=False to find formula cells, once data_only=True to read their
cached value) and flags any formula cell whose cached value is None -- a
golden-cache defect, since the golden itself would then extract as NaN.

It also lists every task that ships an xlsx deliverable at all: the
class-K "exposed set" that needs the GATE-V2 3.3/K disclosure sentence in
instruction.md and tests/task_prompt.txt regardless of whether this scan
finds a None cell (a clean golden today can still regress, and a
compliant AGENT's from-scratch workbook is the actual failure mode DataOS
observed, not the golden's).

HEURISTIC / SCOPE NOTES
------------------------
- Only .xlsx is scanned (xlsm golden files, if any, are out of scope here;
  GATE-V2 3.3/K(2) covers xlsm via the LibreOffice recalculation step in
  test.sh, not this script).
- A cell counts as "formula" by openpyxl's own `cell.data_type == 'f'`
  (data_only=False load) -- this already excludes shared-string / literal
  cells and array-formula spill cells that openpyxl exposes as plain
  values, so this scan reports true formula cells only, not a regex guess
  at "=" prefixes.
- Cached value is read from a SEPARATE data_only=True load of the same
  file at the same (sheet, coordinate) -- openpyxl does not expose both
  the formula text and the cached value from one load.
- A formula cell whose cached value is a legitimate 0, "", or FALSE is NOT
  a defect (those are real cached values); only Python None (the XML has
  no <v> child at all) is flagged.

--probe MODE (BUILD ONLY -- NOT RUN AT SCALE IN THIS SESSION)
----------------------------------------------------------------
`--probe <task>` builds the GATE-V2 3.1 "no-cache probe" for one task:
  1. Copies <task>/tests/ and a re-saved copy of <task>/solution/files/
     into a scratch corpus root (default a tempdir under
     /root/qc/tools/reports/_probe_scratch/), so judge_emulate.py's
     `--corpus-root <scratch>` resolves the task the same way it resolves
     a real corpus task (tests/ present, solution/files/ present).
  2. The re-save is the "no-cache" trick GATE-V2 3.1 specifies: loading an
     xlsx with openpyxl (data_only=False, so cell.value is the formula
     text) and writing it back out. openpyxl only round-trips the cached
     <v> value when the workbook is loaded and re-saved without ever
     touching cell.value; assigning nothing and just re-saving after a
     data_only=False load still drops the cached value on write (openpyxl
     does not carry cached results forward from a formula-mode load) --
     this is exactly the workbook shape rewardkit's own reviewer described
     as what an agent produces in the shipped image (GATE-V2.md 1b, K).
  3. Calls judge_emulate.py in `deliverable` mode against that scratch
     copy, wired with `--corpus-root <scratch>` per the task spec, so the
     emulator's own task-resolution path is exercised identically to a
     real corpus run.
  4. Reports which criteria drop below pass relative to the oracle run
     (criteria unaffected by any formula cell should agree with the
     oracle; a flip there is judge nondeterminism, not class K).

Every real judge_emulate.py call costs Max-plan usage (a `claude -p` CLI
call per judge-group bucket). Per this build's instructions, --probe is
NOT executed for real in this session -- only exercised with --dry-run,
which builds the full scratch copy and prints judge_emulate's prompt plan
but places zero LLM calls (judge_emulate.py's own --dry-run guarantee).
Running --probe for real, task by task, is future work for the task
owners.

ROW-CAPTION CHECK (12:45 UTC, 25-4-0)
--------------------------------------
Per golden xlsx, per worksheet row that has both >=1 string cell and >=1
numeric (int/float) cell: find every literal "$<number>[K|M|B]" token in
the row's concatenated string-cell text, then chain consecutive tokens
that have a "+" character somewhere in the gap text between them (the gap
may contain ordinary prose -- "IMS contractor $60K + Q4 warehouse temp
$45K" chains across "Q4 warehouse temp " because a bare "+" sits in that
gap; a NUMBER is never required to look like a chain link on its own,
which is what a naive "number (filler) + number" regex gets wrong: it can
misfire on an unrelated digit inside the filler, e.g. the "4" in "Q4").
Sum a chain of >=2 tokens (respecting each token's K/M/B multiplier) and
compare against every numeric cell in the same row; if the sum matches no
numeric cell within a loose tolerance (max($1, 0.5% of the cell)), flag a
`row_caption_mismatch` naming the closest numeric cell. Real hit: 25-4-0
`Exposure & Data!D25` holds 6780, its own row's caption sums to 4390
("$2,390 cash + $2,000 reserve"), and a neighboring caption cell says the
row "Equals GL returns/refunds" ($4,390 in D22) -- the golden contradicts
its own row. Verified against 53-0-0's `Budget Reconciliation!F22`
("IMS contractor $60K + Q4 warehouse temp $45K + Q4 CS seasonal/BPO
$48K.") and `F28` ("Software $90K + rent $66K + professional services
$85K + admin $35K") -- both chains sum exactly to their row's D-column
cell (153000, 276000): true negatives, not flagged.
HEURISTIC: only handles addition chains (subtraction is ambiguous against
hyphenated dates/labels like "2021-01" without much higher false-positive
risk), only compares against numeric-typed cells in the SAME row (a
caption whose real total lives in a different row is not checked), and
requires every chain link to carry a literal "$" (a bare-number chain like
"15 existing + 5 committed hires" is not a dollar caption and is never
matched) -- a candidate for the CR, not a proof, like every scan in this
family.

REPEATED-BOILERPLATE COLUMN CHECK (12:45 UTC, 25-4-0/42-3-0/42-7-0/42-9-0)
----------------------------------------------------------------------------
Per golden xlsx, per worksheet, per column whose header cell (the first
non-empty row's cell in that column) contains "source" or "authority"
(case-insensitive) -- e.g. `Sources!B5` "Source file / authority": collect
every non-empty string cell below the header in that column. If the single
most common value repeats in >=5 rows AND >=50% of the column's non-empty
rows AND looks sentence-shaped (>=3 words), flag `boilerplate_repeat`.
Real hit: 25-4-0 `Sources!B6:B32`, 27 of 28 rows read "Only underlying
company records are used as evidence." under header "Source file /
authority".

READ-ONLY on the corpus: default mode only opens files under
<task>/solution/files/. --probe mode copies into a scratch directory
under reports/ and never writes back into the corpus tree.

Output (default mode): CSV reports/formula_cache.csv
  [task, file, kind, location, detail]
kind is one of: none_cache_formula (the original None-cache check --
location=sheet!cell, detail carries the formula text), row_caption_mismatch
(location=sheet!row, detail carries the caption expression, its computed
value, and the nearest numeric cell), boilerplate_repeat (location=
sheet!column, detail carries the header text and the repeat count). A
second CSV, reports/formula_cache_exposed_tasks.csv [task, xlsx_file],
lists every task/file with at least one xlsx deliverable -- the class-K
exposed set, unchanged.

Usage:
    python3 formula_cache_scan.py [--corpus-root PATH] [--out PATH] [--task NAME]
        [--verdict-out PATH]
    python3 formula_cache_scan.py --probe SVC-PC-1-1-0 [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import (
    DEFAULT_CORPUS_ROOT,
    DEFAULT_REPORTS_DIR,
    list_tasks,
    write_csv,
)

JUDGE_EMULATE = Path(__file__).resolve().parent / "judge_emulate.py"

# --- row-caption check -------------------------------------------------
# Every literal "$<number>[K|M|B]" token, with its span, for the
# consecutive-token "+"-in-the-gap chaining in find_dollar_chains.
_DOLLAR_TOKEN_RE = re.compile(r"\$-?[\d][\d,]*(?:\.\d+)?\s*([KMB])?\b", re.I)
_ROW_SUFFIX_MULT = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}
# "+$130K OVER the 16% line" states an overage/delta relative to some
# baseline, not a summand -- a token immediately followed by this is
# excluded from chaining even though a bare "+" sits before it.
_OVERAGE_AFTER_RE = re.compile(r"^\s*(over|above|beyond|exceeding)\b", re.I)
# A "+" flanked by a word character on BOTH sides is a label joiner
# ("compute+DB", "IMS+ADP"), not arithmetic addition -- corpus-verified
# false positive on 75-4-0's "$960/mo compute+DB base ... not >$1,680"
# (the label's "+" sits between two dollar tokens with no real
# relationship between them). Requires the "+" to have a non-word
# character (space, comma, start/end of gap, ...) on at least one side.
_ARITH_PLUS_RE = re.compile(r"(?:(?<![A-Za-z0-9])\+)|(?:\+(?![A-Za-z0-9]))")


def _dollar_token_value(match: re.Match) -> float:
    raw = match.group(0)
    digits = re.search(r"-?[\d][\d,]*(?:\.\d+)?", raw).group(0).replace(",", "")
    mult = _ROW_SUFFIX_MULT.get((match.group(1) or "").upper(), 1.0)
    return float(digits) * mult


def find_dollar_chains(text: str) -> list[tuple[int, int, float]]:
    """Return (start, end, computed_sum) for every maximal run of >=2
    "$<number>" tokens joined by an arithmetic "+" (see _ARITH_PLUS_RE)
    somewhere in the text between each consecutive pair (see module
    docstring: the gap may contain ordinary prose, a chain link is never
    inferred from a bare digit that happens to sit in that prose)."""
    tokens = list(_DOLLAR_TOKEN_RE.finditer(text))
    chains: list[tuple[int, int, float]] = []
    i = 0
    while i < len(tokens):
        run = [tokens[i]]
        j = i
        while j + 1 < len(tokens):
            gap = text[tokens[j].end():tokens[j + 1].start()]
            after = text[tokens[j + 1].end():tokens[j + 1].end() + 20]
            if not _ARITH_PLUS_RE.search(gap) or _OVERAGE_AFTER_RE.match(after):
                break
            run.append(tokens[j + 1])
            j += 1
        if len(run) >= 2:
            chains.append((run[0].start(), run[-1].end(), sum(_dollar_token_value(m) for m in run)))
            i = j + 1
        else:
            i += 1
    return chains


# --- boilerplate column check -------------------------------------------
_BOILERPLATE_MIN_REPEATS = 5
_BOILERPLATE_MIN_FRACTION = 0.5


# ---------------------------------------------------------------------------
# Default mode: data_only=True None-cache scan
# ---------------------------------------------------------------------------


def scan_xlsx(path: Path) -> list[tuple[str, str, bool]]:
    """Return (sheet!cell, formula_text, cached_is_none) for every formula
    cell in one xlsx, cached_is_none True only when the None-cache defect
    is present (rows are filtered to defects only by the caller)."""
    import openpyxl

    wb_formula = openpyxl.load_workbook(path, data_only=False, read_only=True)
    wb_cached = openpyxl.load_workbook(path, data_only=True, read_only=True)
    rows: list[tuple[str, str, bool]] = []
    try:
        for ws_f, ws_c in zip(wb_formula.worksheets, wb_cached.worksheets):
            for row_f, row_c in zip(ws_f.iter_rows(), ws_c.iter_rows()):
                for cell_f, cell_c in zip(row_f, row_c):
                    if cell_f.data_type != "f":
                        continue
                    is_none = cell_c.value is None
                    rows.append((f"{ws_f.title}!{cell_f.coordinate}", str(cell_f.value), is_none))
    finally:
        wb_formula.close()
        wb_cached.close()
    return rows


def scan_row_captions(path: Path) -> list[tuple[str, str, str]]:
    """Return (location, detail_summary_expr, detail) for every row whose
    caption text states a "+"-chain arithmetic expression that matches no
    numeric cell in that row. See module docstring for the heuristic."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out: list[tuple[str, str, str]] = []
    try:
        for ws in wb.worksheets:
            grid: dict[int, dict[int, object]] = {}
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        grid.setdefault(cell.row, {})[cell.column] = cell.value
            for r, cols in sorted(grid.items()):
                text_parts = [v for v in cols.values() if isinstance(v, str) and v.strip()]
                numeric_cells = [(c, v) for c, v in cols.items() if isinstance(v, (int, float))]
                if not text_parts or not numeric_cells:
                    continue
                row_text = " | ".join(text_parts)
                for start, end, computed in find_dollar_chains(row_text):
                    expr = row_text[start:end].strip()
                    # Sign-agnostic match: a contra/expense row storing the
                    # caption's positive sum as a negative cell value (a
                    # normal accounting convention, not a contradiction) is
                    # not flagged -- only the MAGNITUDE has to agree.
                    if any(
                        abs(computed - v) <= max(1.0, abs(v) * 0.005) or abs(computed + v) <= max(1.0, abs(v) * 0.005)
                        for _c, v in numeric_cells
                    ):
                        continue  # matches some numeric cell in the row -- fine
                    # Only compare against a numeric cell in the same
                    # order of magnitude as the caption's own sum -- a row
                    # index, a percentage, or an unrelated small ratio
                    # sitting elsewhere in the row is not a candidate
                    # "total" for this caption at all, and comparing
                    # against it (as an earlier version of this check did)
                    # manufactured false positives across the corpus at
                    # scale (e.g. a caption summing to $25,300 flagged
                    # against a row index cell holding 8).
                    if computed:
                        plausible = [(c, v) for c, v in numeric_cells if v and 0.1 <= abs(v) / abs(computed) <= 10]
                    else:
                        plausible = numeric_cells
                    if not plausible:
                        continue
                    best_c, best_v = min(plausible, key=lambda cv: abs(cv[1] - computed))
                    coord = ws.cell(row=r, column=best_c).coordinate
                    out.append(
                        (
                            f"{ws.title}!row{r}",
                            expr,
                            f"caption '{expr}' computes {computed:g}; nearest row cell {coord}={best_v!r}",
                        )
                    )
    finally:
        wb.close()
    return out


def scan_boilerplate_columns(path: Path) -> list[tuple[str, str, str]]:
    """Return (location, header_text, detail) for every Sources/authority
    column whose most common value repeats past the boilerplate
    threshold. See module docstring for the heuristic."""
    import openpyxl
    from openpyxl.utils import get_column_letter

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    out: list[tuple[str, str, str]] = []
    try:
        for ws in wb.worksheets:
            # Indexed by tuple POSITION (1-based), never by cell.row/
            # cell.column -- read_only iter_rows pads sparse rows with
            # EmptyCell placeholders that don't carry those attributes,
            # and a position in the tuple is the column number regardless.
            rows: list[list[object]] = [[c.value for c in row] for row in ws.iter_rows()]
            # Header row = the FIRST row with >=2 non-empty cells (a real
            # multi-column header, not a single-cell sheet title/subtitle
            # like "Source Register" above the real header) that also
            # names a source/authority column -- a plain ">=1 non-empty
            # cell" first-row heuristic picks up title rows on sheets like
            # 25-4-0's "Sources" (title row 1, subtitle row 2, "Evidence
            # index" row 4, real header row 5).
            header_row_idx = None
            header: dict[int, object] = {}
            target_cols: set[int] = set()
            for ridx, row_vals in enumerate(rows, start=1):
                nonempty = [(cidx, v) for cidx, v in enumerate(row_vals, start=1) if v not in (None, "")]
                if len(nonempty) < 2:
                    continue
                cand_cols = {
                    col for col, val in nonempty if isinstance(val, str) and ("source" in val.lower() or "authority" in val.lower())
                }
                if cand_cols:
                    header_row_idx = ridx
                    header = dict(nonempty)
                    target_cols = cand_cols
                    break
            if header_row_idx is None or not target_cols:
                continue
            col_values: dict[int, list[str]] = {c: [] for c in target_cols}
            for ridx, row_vals in enumerate(rows, start=1):
                if ridx <= header_row_idx:
                    continue
                for cidx, v in enumerate(row_vals, start=1):
                    if cidx in target_cols and isinstance(v, str) and v.strip():
                        col_values[cidx].append(v.strip())
            for col, vals in col_values.items():
                if len(vals) < _BOILERPLATE_MIN_REPEATS:
                    continue
                top_val, top_n = Counter(vals).most_common(1)[0]
                if (
                    top_n >= _BOILERPLATE_MIN_REPEATS
                    and top_n / len(vals) >= _BOILERPLATE_MIN_FRACTION
                    and len(top_val.split()) >= 3
                ):
                    header_label = str(header.get(col, ""))
                    col_letter = get_column_letter(col)
                    out.append(
                        (
                            f"{ws.title}!{col_letter}",
                            header_label,
                            f"header={header_label!r} value={top_val!r} repeats {top_n}/{len(vals)} rows",
                        )
                    )
    finally:
        wb.close()
    return out


def scan_task(task_dir: Path) -> tuple[list[tuple[str, str, str, str, str]], list[tuple[str, str]]]:
    """Return (defect_rows, exposed_rows) for one task.
    defect_rows: (task, file, kind, location, detail) across all three
    checks (none_cache_formula, row_caption_mismatch, boilerplate_repeat).
    exposed_rows: (task, xlsx_file) for every xlsx deliverable, defect or not.
    """
    solution_files_dir = task_dir / "solution" / "files"
    if not solution_files_dir.is_dir():
        return [], []
    defect_rows: list[tuple[str, str, str, str, str]] = []
    exposed_rows: list[tuple[str, str]] = []
    for f in sorted(solution_files_dir.rglob("*.xlsx")):
        exposed_rows.append((task_dir.name, f.name))
        for sheet_cell, formula, is_none in scan_xlsx(f):
            if is_none:
                defect_rows.append((task_dir.name, f.name, "none_cache_formula", sheet_cell, f"formula={formula!r} cached=None"))
        for location, _expr, detail in scan_row_captions(f):
            defect_rows.append((task_dir.name, f.name, "row_caption_mismatch", location, detail))
        for location, _header, detail in scan_boilerplate_columns(f):
            defect_rows.append((task_dir.name, f.name, "boilerplate_repeat", location, detail))
    return defect_rows, exposed_rows


# ---------------------------------------------------------------------------
# --probe mode
# ---------------------------------------------------------------------------


def build_probe_scratch(task_dir: Path, scratch_root: Path) -> tuple[Path, Path]:
    """Build a scratch copy of one task under scratch_root, with every
    solution/files/*.xlsx re-saved through a data_only=False openpyxl
    load (drops cached values on write -- the "no-cache" golden copy).
    Non-xlsx deliverables are copied unchanged. Returns
    (scratch_task_dir, scratch_deliverable_dir)."""
    import openpyxl

    task_name = task_dir.name
    scratch_task = scratch_root / task_name
    if scratch_task.exists():
        shutil.rmtree(scratch_task)
    shutil.copytree(task_dir / "tests", scratch_task / "tests")

    solution_files_dir = task_dir / "solution" / "files"
    scratch_solution = scratch_task / "solution" / "files"
    scratch_solution.mkdir(parents=True, exist_ok=True)
    for f in sorted(solution_files_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() == ".xlsx":
            wb = openpyxl.load_workbook(f, data_only=False)
            wb.save(scratch_solution / f.name)
            wb.close()
        else:
            shutil.copy2(f, scratch_solution / f.name)
    return scratch_task, scratch_solution


def run_probe(task_dir: Path, scratch_root: Path, *, dry_run: bool, model: str, out: Path | None) -> int:
    scratch_task, scratch_solution = build_probe_scratch(task_dir, scratch_root)
    cmd = [
        sys.executable,
        str(JUDGE_EMULATE),
        "deliverable",
        task_dir.name,
        str(scratch_solution),
        "--corpus-root",
        str(scratch_root),
        "--model",
        model,
    ]
    if dry_run:
        cmd.append("--dry-run")
    if out is not None:
        cmd += ["--out", str(out)]
    print(f"formula_cache_scan --probe: scratch built at {scratch_task}", file=sys.stderr)
    print(f"  no-cache deliverable dir: {scratch_solution}", file=sys.stderr)
    print(f"  invoking: {' '.join(cmd)}", file=sys.stderr)
    if not dry_run:
        print(
            "  WARNING: this is a REAL judge_emulate.py run (Max-plan CLI calls, "
            "one per judge-group bucket). Not run automatically by this build; "
            "proceeding because --dry-run was not passed.",
            file=sys.stderr,
        )
    result = subprocess.run(cmd)
    return result.returncode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT, help="corpus root directory")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "formula_cache.csv", help="output CSV path (default mode)")
    ap.add_argument(
        "--exposed-out",
        type=Path,
        default=DEFAULT_REPORTS_DIR / "formula_cache_exposed_tasks.csv",
        help="output CSV path for the class-K exposed xlsx-task list (default mode)",
    )
    ap.add_argument("--task", type=str, default=None, help="restrict to a single task name (debugging, default mode)")
    ap.add_argument("--probe", metavar="TASK", default=None, help="build+run the class-K no-cache probe for one task (see docstring)")
    ap.add_argument("--dry-run", action="store_true", help="--probe only: pass through to judge_emulate.py, no LLM calls")
    ap.add_argument("--model", default="opus", help="--probe only: judge_emulate.py --model")
    ap.add_argument(
        "--scratch-root",
        type=Path,
        default=DEFAULT_REPORTS_DIR / "_probe_scratch",
        help="--probe only: scratch corpus root to build the no-cache copy under",
    )
    ap.add_argument("--probe-out", type=Path, default=None, help="--probe only: judge_emulate.py --out JSON path")
    ap.add_argument("--verdict-out", type=Path, default=None, help="write task_id,formula_cache,pass|warn|fail per scanned task (default mode)")
    args = ap.parse_args()

    if args.probe:
        task_dir = args.corpus_root / args.probe
        if not task_dir.is_dir():
            task_dir = Path(args.probe)
        if not task_dir.is_dir():
            print(f"ERROR: task not found: {args.probe}", file=sys.stderr)
            return 1
        args.scratch_root.mkdir(parents=True, exist_ok=True)
        return run_probe(task_dir, args.scratch_root, dry_run=args.dry_run, model=args.model, out=args.probe_out)

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_defects: list[tuple[str, str, str, str, str]] = []
    all_exposed: list[tuple[str, str]] = []
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        try:
            defects, exposed = scan_task(task_dir)
            all_defects.extend(defects)
            all_exposed.extend(exposed)
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 25 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned", file=sys.stderr)

    n = write_csv(args.out, ["task", "file", "kind", "location", "detail"], all_defects)
    n_exposed = write_csv(args.exposed_out, ["task", "xlsx_file"], all_exposed)

    tasks_with_defects = {r[0] for r in all_defects}
    tasks_exposed = {r[0] for r in all_exposed}
    by_kind: dict[str, int] = {}
    tasks_by_kind: dict[str, set[str]] = {}
    for r in all_defects:
        by_kind[r[2]] = by_kind.get(r[2], 0) + 1
        tasks_by_kind.setdefault(r[2], set()).add(r[0])

    print(f"formula_cache_scan: {n} defects found, written to {args.out}")
    print(f"  {len(tasks_with_defects)} tasks have at least one defect")
    for kind in ("none_cache_formula", "row_caption_mismatch", "boilerplate_repeat"):
        print(f"    {kind}: {by_kind.get(kind, 0)} rows, {len(tasks_by_kind.get(kind, set()))} tasks")
    print(f"  {n_exposed} xlsx deliverables across {len(tasks_exposed)} tasks written to {args.exposed_out} (class-K exposed set)")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        # All three kinds here are mechanical/objective checks (an exact
        # None cache cell, an arithmetic mismatch, an exact repeat count)
        # -- see module docstrings -- so any hit is a fail, not a warn.
        defect_tasks = tasks_with_defects
        verdict_rows = [(t.name, "fail" if t.name in defect_tasks else "pass") for t in tasks]
        write_csv(args.verdict_out, ["task_id", "formula_cache"], verdict_rows)
        by_verdict: dict[str, int] = {}
        for _t, v in verdict_rows:
            by_verdict[v] = by_verdict.get(v, 0) + 1
        print(f"formula_cache_scan: verdicts written to {args.verdict_out}: {by_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
