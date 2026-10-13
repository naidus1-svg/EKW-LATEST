"""Golden arithmetic check: recompute a golden workbook's own labeled aggregation cells from the
task's real source data in environment/, and flag when the golden's stated number diverges from
every recomputation beyond a small tolerance.

Why this exists (GLM round 27/28 coverage synthesis, Class 2): the golden solution's OWN numbers
can be computed WRONG from real source data that DOES exist -- not a missing-fact defect
(criterion_groundedness_check.py's territory: does a fact appear anywhere in environment/) and
not a formula-recalculation defect (formula_health_check.py's territory: does a LIVE EXCEL
FORMULA in the golden recompute to what its own cache says). This check targets a third, distinct
shape: a golden cell holds a LITERAL VALUE (zero formulas -- confirmed on both real examples this
script was built and validated against) that the golden's own text says is an aggregation of named
source data, and the aggregation itself is arithmetically wrong. criterion_groundedness_check.py
cannot see this because a wrong SUM still "exists" nowhere near the source text it's supposedly
built from, and a fact that never gets extracted as a criterion-level "Expected:" claim never
enters that check's scope at all; formula_health_check.py cannot see this because there is no
formula to recompute -- the wrong number is typed in directly, not derived by a live cell formula.

What this check actually automates (Case A -- the ONLY case this script fires on):
    A golden spreadsheet under <task_dir>/solution/ has a data table (a header row, data rows
    below) where at least one column's header text itself reads as an aggregation ("Total",
    "Subtotal", "Amount", "Revenue", "Sales", "Sum") -- independent of whatever a same-row
    "Status" cell says, because the real corpus shows the derivation signal can live in EITHER
    place (see Confirmed real examples below, and the design note after them). For every such
    cell, this script:
      1. Finds every spreadsheet under <task_dir>/environment/ (recursive) and builds a table
         model for each (header row via find_header_rows(), amount-like columns, an optional
         filter column such as Province/State/Region, and an optional order/invoice/transaction
         "key" column for deduplication).
      2. Recomputes candidate totals from each source table's matching column: the raw sum over
         every row, a deduplicated sum (first non-null value per unique key -- the shape that
         catches an order-level total silently repeated across a multi-line order's continuation
         rows), and, when the golden cell's own row carries a short, filter-shaped label (e.g. a
         state abbreviation), the same two sums restricted to rows whose filter column equals that
         label.
      3. Compares the golden's stated value against every recomputed candidate with a tolerance
         of max($25, 1% of the golden value). A match anywhere means the cell is grounded (pass).
         No match, with at least one candidate actually computed, is a mismatch finding.
      4. Severity is NOT a flat verdict. A mismatch is "fail" only when the golden itself
         discloses this specific cell as derived/computed (a same-row "Status" cell matching
         DERIVED_STATUS_RE), OR when a candidate source table's row count independently matches a
         count the golden states elsewhere on the same row or sheet (row-count corroboration --
         see the Confirmed real examples: this is what turns the Jurisdiction Summary/CA finding
         from a coincidence into a confirmed bug reproduction). Otherwise it is "warn" (a plausible
         but less certain mismatch). A same-row "Status" cell that instead reads as an explicitly
         RAW, directly-sourced fact (RAW_FACT_STATUS_RE: "Confirmed", "Actual", "Reported",
         "Stated", "source of record") downgrades an uncorroborated mismatch to "info" (recorded,
         never counted toward the task's status) -- a raw fact is not asserted as independently
         re-derivable from a spreadsheet sum in the first place, so a heuristic sum failing to
         reproduce it is far more likely this check's own limitation than a real defect.

Design note -- why the trigger is the COLUMN HEADER, not a same-row "Status" cell, even though
both real examples below carry a "Status" column: the two confirmed examples turned out to need
this. SVC-PC-37-3-0's "Orders and AOV Basis Trace" sheet discloses row 8 via Status="Derived" --
a clean, explicit signal. But the SAME workbook's "Jurisdiction Summary" sheet uses "Status" for a
completely different axis (the jurisdiction/nexus TREATMENT'S review state -- Confirmed / Derived /
Proposed pending approval / Open item / Not evidenced, per the workbook's own "Status Vocabulary"
sheet), and the CA row's status is "Proposed pending approval" -- about whether the tax
CONCLUSION is approved, not about whether the DOLLAR FIGURE was computed. Gating on
Status=="Derived" alone would have missed this row entirely, which is exactly the one that
reproduces bit-for-bit against real source data (see below). The column header
("Line-level Total field") turned out to be the reliable signal in both sheets; "Status" is used
only to set confidence (fail vs. warn vs. info), never as the sole trigger.

Confirmed real examples (both hand-verified against the actual on-disk files before this script
was written, then confirmed to be exactly what the finished script reports):
  - SVC-PC-37-3-0, solution/files/Multi_State_Sales_Tax_Nexus_Assessment.xlsx, sheet
    "Jurisdiction Summary", cell C5 (row label "CA"): golden states $147,993. The task's real
    source, environment/.../Sales_Orders.xlsx (a 12,177-row raw Shopify-style order/line-item
    export), reproduces $147,993 EXACTLY via coalesce(order-level Total, this line's own
    Lineitem price) summed over every CA row -- i.e. the golden's number double-counts a
    continuation line's own price on top of the order-level Total that already includes it,
    for every multi-line-item CA order. The correct figure, deduplicating to one Total per
    unique order (billing or shipping province = CA), is $138,906 -- which also matches the
    golden's OWN adjacent B5 = 1081 unique CA orders exactly (row-count corroboration, confirmed
    by direct count against the same source file). Both figures independently confirmed by
    running the recomputation directly against the real files, not assumed from the golden's
    prose.
  - The same workbook's "Orders and AOV Basis Trace" sheet, cell C8 (Status="Derived", label
    "Shopify export line-level Total field"): golden states $1,374,147. SUM(Lineitem price x
    Lineitem quantity) over the same 12,177-row export gives $1,289,244 -- a $84,903 (6.6%)
    divergence, far beyond tolerance. This script's shipped mechanism does not reproduce the
    EXACT wrong arithmetic behind 1,374,147 the way it does for the CA case (several plausible
    coalesce/fill variants were tried by hand and none hit 1,374,147 precisely -- see this
    script's own commit message for the tried variants) but the divergence itself, and the
    correct $1,289,244 recomputation, are both independently confirmed against the real file.

  - A second, DIFFERENT-SHAPED defect was also hand-confirmed during this script's build, in
    SVC-PC-5-3-0's golden Databook (sheet "Databook", cell C12): a single narrative text cell
    states "FY2021 Returns & Refunds expense was $4,390 (actual)". Two real source documents in
    that task's own environment/ each state a comparable quarterly figure: Q1_Ops_Summary.docx's
    prose states "The cash refund total for Q1 was $2,390 (source records ratified Jun 10)", and
    Q2_Ops_Summary.docx's own P&L bridge table states "Less: refunds & returns ... Q2 Total
    $(2,200)". Neither equals $4,390, and summing the only two quarters that have a comparable
    number gives $4,590, still not $4,390 (Q3 offers only a balance-sheet accrual, a different
    concept, and Q4 explicitly states the data is not available). GLM's own paraphrase of this
    example attributed the $2,390 figure to "Sales_Orders.xlsx" -- that file does not exist
    anywhere in SVC-PC-5-3-0's environment/ at all; the real source is Q1_Ops_Summary.docx's
    prose, found only by reading the actual task files directly rather than trusting the
    paraphrase, exactly as this dispatch's own instructions warned might be necessary.
    THIS SCRIPT DOES NOT CATCH THIS SECOND EXAMPLE, and is not designed to. It is a single flat
    narrative sentence, not a labeled table cell, and reconciling it needs resolving that
    "FY2021 Returns & Refunds expense" is the same subject as two DIFFERENT quarterly documents'
    two DIFFERENTLY-named line items ("cash refund total" vs. "refunds & returns"), each in a
    different file, with two of the four needed quarters simply unavailable. That is exactly the
    "fully general recompute anything" engine this check's own brief said to defer, not the
    narrower table-cell-vs-named-source-file shape Case A targets. It is reported here, in full,
    as a real, hand-confirmed defect this build did not automate a catch for -- not folded into
    the shipped check's false-positive/true-positive counts, and not hard-coded as a
    task-ID-keyed special case (which would not generalize to any other task and would not be a
    real check).

Known limits, disclosed rather than silently dropped:
    - Header detection (find_header_rows) requires >=3 non-empty cells on a row AND at least one
      numeric value in one of the same columns on the very next row. A golden or source table
      that puts its header more than 40 rows down, or that has fewer than 3 labeled columns, is
      invisible to this check -- reported as "skip" (golden) or silently excluded as a candidate
      source (environment), never asserted clean.
    - Amount-column detection is a fixed keyword list (total/subtotal/amount/revenue/sales/sum)
      substring-matched against the header text, case-insensitively. A column meaning the same
      thing under a different word ("Extended price", "Net", "Charge") is invisible. Confirmed
      not to under-fire on either real example (both use "Total"-containing headers on both the
      golden and the source side), but this is a real, disclosed coverage gap on other wording.
    - Filter-column matching (Province/State/Region/Jurisdiction/Territory/Country) requires an
      EXACT, case-insensitive string match between the golden row's own label and the source
      column's cell value ("CA" == "CA"). A spelled-out mismatch ("California" vs. "CA") is not
      resolved and silently produces zero filtered candidates for that row (not an error, just no
      filtered candidate to try -- the unfiltered candidates are still attempted).
    - Deduplication-by-key uses the FIRST non-null amount-column value encountered per unique key,
      in file row order. This is the exact shape that reproduces the SVC-PC-37-3-0 CA example
      (an order-level Total populated only once per order, on whichever line happens to carry it)
      but is not a general "which row is authoritative for this key" resolver -- a source table
      where two rows for the same key both carry different non-null amounts (a genuine data
      conflict, not a continuation-line blank) silently keeps whichever comes first in the file.
    - Row-count corroboration compares an exact integer count (a candidate's row/order count
      against every integer the golden states on the same row or anywhere else on the same sheet,
      10 <= n <= 5,000,000) -- but ONLY for a candidate that also used an actual FILTER match (see
      analyze_task's own comment at the row_count_corroborated assignment). A version that
      corroborated from ANY candidate's row count, filtered or not, was tried first and confirmed
      empirically to produce real false "fail" verdicts: on a financial-close/reconciliation task
      (SVC-PC-14-3-0), 9 ordinary financial-statement line items ("AP aging total", "Bank
      reconciliation in-transit item", a stock plan pool, a net-loss figure) got
      row_count_corroborated=True purely because some UNRELATED candidate's row count happened to
      equal some OTHER number on a busy sheet -- no topical connection to the row's own subject at
      all. Restricting corroboration to filtered candidates removed all 9 false "fail" verdicts on
      that task (confirmed by direct re-run, both before and after) with zero change to
      SVC-PC-37-3-0's 12 real findings. This does not eliminate every possible coincidental
      corroboration -- a task whose environment happens to have a file with a genuinely matching
      filter VALUE (not just a matching row count) for an unrelated reason is not ruled out by
      this fix -- but it removes the single largest false-positive class found during this
      script's own validation sweep. See the module docstring's "Validation" note for where the
      real corpus-scale numbers before and after this fix are recorded.
    - This script loads every candidate spreadsheet with plain openpyxl (data_only=True, NOT
      read_only) rather than the streaming read-only mode formula_health_check.py's own module
      docstring documents as necessary at large-corpus scale (its section 2's block comment: a
      naive per-cell .cell() call pattern measured 40x-128x slower than one sequential
      iter_rows() pass on a large sheet). This script does use iter_rows() for the bulk row read,
      but not read-only mode, trading some memory/startup cost for API simplicity given this
      script's per-task, modest-file-count usage pattern. A sheet whose max_row * max_column
      exceeds 2,000,000 cells is skipped outright (recorded, not silently dropped) rather than
      risking a multi-minute load on one pathological file.
    - Tolerance is max($25, 1% of the golden's stated value) -- a fixed choice, not empirically
      tuned against a large sample of genuinely-correct-but-rounded golden figures. Both real
      divergences this script targets are 6%+ (CA: 6.5%, global: 6.6%), far outside this band, so
      the tolerance was not the deciding factor on either confirmed example.
    - Never validated against EKW-format tasks specifically (tests/verifier.json). The scan
      itself is format-agnostic (it only looks under solution/ and environment/, regardless of
      which judge-config format is present), but this script's build and every false-positive
      measurement below ran against the SVC-PC corpus only.

Validation: see this script's own commit message for the full false-positive sweep (task count,
pass/warn/fail/skip breakdown, and every warn/fail finding's task id and stated vs. recomputed
values) run against a broad sample of the real 202/609-task SVC-PC corpus before this check was
registered, so the numbers can't go stale silently inside this docstring.

Usage:
    python golden_arithmetic_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python golden_arithmetic_check.py --all --root <path> --out report.json
    python golden_arithmetic_check.py --all --root <path> --id-prefix SVC-PC- --out report.json

Exit code: 0 always (same convention as harness_fragility_check.py -- every verdict lives in the
JSON's per-task "status" field, never in the process exit code, since this runs as one shard among
many under svc_run_checks.py / ekw_run_checks.py, which never trusts a subprocess exit code either).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import openpyxl
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl
    from openpyxl.utils import get_column_letter


SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm")

# Amount-like column headers: a column whose header TEXT reads as an aggregation, independent of
# any same-row "Status" cell -- see this module's docstring "Design note" for why the header,
# not the Status cell, is the primary trigger. "price" is included because a raw line-item
# export's own per-line amount is very often named "<Something> price" (Shopify's own "Lineitem
# price"), not "total" -- confirmed necessary on SVC-PC-37-3-0's real Sales_Orders.xlsx: without
# it, the only matching columns are order-level Total/Subtotal, and neither can reproduce the
# golden's line-level aggregation target even approximately (a QUANTITY_COLUMN_KEYWORDS-paired
# product-sum, below, is what actually closes the gap).
SOURCE_COLUMN_KEYWORDS = (
    "total",
    "subtotal",
    "amount",
    "revenue",
    "sales",
    "sum",
    "price",
)

# A companion column: when a row has both an amount-like column (typically a per-unit PRICE) and
# one of these, this check also tries SUM(amount_col * quantity_col) as a candidate -- the
# "extend a per-unit price by quantity" arithmetic a raw order-export line-item table needs and a
# plain column sum cannot express. Confirmed necessary to get within a useful reporting distance
# of SVC-PC-37-3-0's real $1,289,244 correct recomputation (a plain sum of "Lineitem price" alone
# undercounts any line with quantity > 1).
QUANTITY_COLUMN_KEYWORDS = ("quantity", "qty")

# A column meant to slice rows by geography/category, used for the optional per-row filter.
FILTER_COLUMN_KEYWORDS = (
    "province",
    "state",
    "region",
    "jurisdiction",
    "territory",
    "country",
)

# A column identifying "which real-world thing this row belongs to", used for dedup-by-key.
# Specific phrases first (checked with priority); a bare fallback word only if no phrase matches,
# to avoid a generic column like "Phone Number" winning over a real "Order Number" column when
# both exist on the same header row.
ORDER_KEY_PHRASES = (
    "order number",
    "order id",
    "order name",
    "sales order number",
    "invoice number",
    "invoice id",
    "transaction id",
    "receipt number",
)
ORDER_KEY_FALLBACK = ("order", "invoice", "transaction")

# Same-row "Status" text that discloses THIS cell as a computed rollup -- fail-tier trigger.
DERIVED_STATUS_RE = re.compile(
    r"derived|computed|calculated|\bsum of\b|\btotal of\b|aggregat", re.I
)

# Same-row "Status" text that discloses THIS cell as a raw, directly-sourced fact -- an
# uncorroborated mismatch here is downgraded to "info", never "fail" or "warn". See module
# docstring: a fact explicitly marked as NOT computed is not asserted as independently
# re-derivable from a spreadsheet sum, so failing to reproduce it via this check's own sum
# heuristics is far more likely this check's limitation than a real defect.
RAW_FACT_STATUS_RE = re.compile(
    r"\bconfirmed\b|\bactual\b|\breported\b|\bstated\b|source of record", re.I
)

MATCH_REL_TOL = 0.01
MATCH_ABS_FLOOR = 25.0

MAX_HEADER_SCAN_ROWS = 40  # golden sheets: how far down to look for a header row
MAX_SOURCE_HEADER_SCAN_ROWS = (
    10  # source sheets: headers are expected near the very top
)
MAX_GOLDEN_DATA_ROWS = 2000  # per golden table block, safety cap
MAX_SOURCE_ROWS = 200_000  # per source table, safety cap
MAX_SHEET_CELLS = (
    2_000_000  # max_row * max_column safety cap before even trying to read a sheet
)
MAX_ENV_FILES_PER_TASK = (
    400  # safety cap on how many environment spreadsheets get scanned
)
PLAUSIBLE_FILTER_LABEL_MAX_LEN = 20

BASIS_HINT_MIN = 10
BASIS_HINT_MAX = 5_000_000


def _norm(s) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _is_plain_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _to_float(v):
    """Best-effort numeric coercion for a golden/source cell that might be a string like
    '$147,993' or '(2,200)' rather than a native number. Returns None if it can't be read as a
    number at all. Native ints/floats (the common case for both real examples) pass through
    unchanged, just cast to float."""
    if _is_plain_number(v):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    is_negative = s.startswith("(") and s.endswith(")")
    core = re.sub(r"[^0-9.]", "", s)
    if not core or core == ".":
        return None
    try:
        f = float(core)
    except ValueError:
        return None
    return -f if is_negative else f


# ---------------------------------------------------------------------------
# shared table-model helpers (used for BOTH the golden workbook and every candidate source file)
# ---------------------------------------------------------------------------


def find_header_rows(ws, max_scan_row: int) -> list[int]:
    """Row indices that look like a real table header: >=3 non-empty cells, majority strings,
    AND at least one numeric value in one of the SAME columns on the very next row (confirms
    this sits on top of real data, not a title/caption line). See module docstring's Known
    limits for what this misses."""
    headers = []
    max_row = min(ws.max_row or 0, max_scan_row)
    for r in range(1, max_row + 1):
        row_cells = {c.column: c.value for c in ws[r] if c.value is not None}
        str_cells = {
            col: v for col, v in row_cells.items() if isinstance(v, str) and v.strip()
        }
        if len(str_cells) < 3:
            continue
        next_row = r + 1
        if next_row > (ws.max_row or 0):
            continue
        has_data_below = any(
            _is_plain_number(ws.cell(row=next_row, column=col).value)
            for col in str_cells
        )
        if has_data_below:
            headers.append(r)
    return headers


def build_header_info(ws, header_row: int) -> dict:
    cols = {}
    for c in ws[header_row]:
        if isinstance(c.value, str) and c.value.strip():
            cols[c.column] = _norm(c.value)

    amount_cols = {
        col: t
        for col, t in cols.items()
        if any(kw in t for kw in SOURCE_COLUMN_KEYWORDS)
    }
    filter_cols = {
        col: t
        for col, t in cols.items()
        if any(kw in t for kw in FILTER_COLUMN_KEYWORDS)
    }
    status_col = next((col for col, t in cols.items() if t == "status"), None)
    basis_col = next((col for col, t in cols.items() if t == "basis"), None)
    quantity_col = next(
        (
            col
            for col, t in cols.items()
            if any(kw in t for kw in QUANTITY_COLUMN_KEYWORDS)
        ),
        None,
    )

    key_col = None
    for col, t in cols.items():
        if any(p in t for p in ORDER_KEY_PHRASES):
            key_col = col
            break
    if key_col is None:
        for col, t in cols.items():
            if any(p in t for p in ORDER_KEY_FALLBACK):
                key_col = col
                break

    # Deliberately does NOT exclude filter_cols here: a column can be BOTH the row's own
    # label/category (e.g. "State") AND, separately, the column this check will later try to
    # match against a source file's own Province/State column when filtering. Excluding it from
    # label_col would leave the row's real label (a string) undiscovered, silently falling
    # through to the next candidate column instead -- which is very often itself numeric (e.g.
    # "Unique orders") and therefore fails the isinstance(str) check downstream, leaving the row
    # with NO label and NO filtered candidates ever attempted. Confirmed as a real bug during
    # this script's own validation run against SVC-PC-37-3-0's "Jurisdiction Summary" sheet,
    # 2026-09-15: column A ("State") was being excluded as a filter column, column B ("Unique
    # orders", numeric) won label_col instead, every row's label came back None, and the CA row's
    # own filtered recomputation against Sales_Orders.xlsx (which reproduces the golden's wrong
    # $147,993 exactly) was never tried at all -- only irrelevant unfiltered candidates were.
    excluded = set(amount_cols)
    if status_col is not None:
        excluded.add(status_col)
    if basis_col is not None:
        excluded.add(basis_col)
    if quantity_col is not None:
        excluded.add(quantity_col)
    label_col = next((col for col in sorted(cols) if col not in excluded), None)

    return dict(
        cols=cols,
        amount_cols=amount_cols,
        filter_cols=filter_cols,
        status_col=status_col,
        basis_col=basis_col,
        quantity_col=quantity_col,
        key_col=key_col,
        label_col=label_col,
    )


def _sheet_too_big(ws) -> bool:
    mr, mc = ws.max_row or 0, ws.max_column or 0
    return mr * mc > MAX_SHEET_CELLS


# ---------------------------------------------------------------------------
# golden-side extraction: every aggregation-labeled cell this check will try to verify
# ---------------------------------------------------------------------------


def extract_golden_targets(ws, sheet_name: str) -> tuple[list[dict], set[int]]:
    """Returns (targets, sheet_basis_hints). Never raises -- caller wraps per-sheet."""
    targets: list[dict] = []
    sheet_basis_hints: set[int] = set()

    for row in ws.iter_rows():
        for cell in row:
            v = cell.value
            if _is_plain_number(v) and float(v).is_integer():
                iv = abs(int(v))
                if BASIS_HINT_MIN <= iv <= BASIS_HINT_MAX:
                    sheet_basis_hints.add(int(v))

    header_rows = find_header_rows(ws, MAX_HEADER_SCAN_ROWS)
    for idx, header_row in enumerate(header_rows):
        info = build_header_info(ws, header_row)
        if not info["amount_cols"]:
            continue
        next_header = header_rows[idx + 1] if idx + 1 < len(header_rows) else None
        end_row = (
            (next_header - 1)
            if next_header
            else min(ws.max_row or header_row, header_row + MAX_GOLDEN_DATA_ROWS)
        )

        blank_streak = 0
        for r in range(header_row + 1, end_row + 1):
            row_vals = {c.column: c.value for c in ws[r]}
            non_empty = [v for v in row_vals.values() if v is not None]
            if not non_empty:
                blank_streak += 1
                if blank_streak >= 5:
                    break
                continue
            blank_streak = 0

            label = None
            if info["label_col"] is not None:
                lv = row_vals.get(info["label_col"])
                if isinstance(lv, str) and lv.strip():
                    label = lv.strip()

            status_text = None
            if info["status_col"] is not None:
                sv = row_vals.get(info["status_col"])
                if isinstance(sv, str) and sv.strip():
                    status_text = sv.strip()

            basis_text = None
            if info["basis_col"] is not None:
                bv = row_vals.get(info["basis_col"])
                if isinstance(bv, str) and bv.strip():
                    basis_text = bv.strip()

            row_other_ints = {
                int(v)
                for col, v in row_vals.items()
                if _is_plain_number(v)
                and float(v).is_integer()
                and BASIS_HINT_MIN <= abs(int(v)) <= BASIS_HINT_MAX
            }

            for amount_col, header_text in info["amount_cols"].items():
                val = row_vals.get(amount_col)
                if not _is_plain_number(val):
                    continue
                row_hints = {v for v in row_other_ints if v != abs(int(val))}
                targets.append(
                    dict(
                        sheet=sheet_name,
                        row=r,
                        cell=f"{get_column_letter(amount_col)}{r}",
                        header_text=header_text,
                        label=label,
                        status_text=status_text,
                        basis_text=basis_text,
                        value=float(val),
                        row_count_hints=sorted(row_hints),
                    )
                )
    return targets, sheet_basis_hints


def find_golden_spreadsheets(task_dir: Path) -> list[Path]:
    sol = task_dir / "solution"
    if not sol.is_dir():
        return []
    return sorted(
        p
        for p in sol.rglob("*")
        if p.is_file() and p.suffix.lower() in SPREADSHEET_SUFFIXES
    )


# ---------------------------------------------------------------------------
# source-side table model: every candidate spreadsheet under environment/
# ---------------------------------------------------------------------------


def find_environment_spreadsheets(task_dir: Path) -> list[Path]:
    env = task_dir / "environment"
    if not env.is_dir():
        return []
    out = sorted(
        p
        for p in env.rglob("*")
        if p.is_file() and p.suffix.lower() in SPREADSHEET_SUFFIXES
    )
    return out[:MAX_ENV_FILES_PER_TASK]


def build_source_tables(path: Path) -> tuple[list[dict], str | None]:
    """One task's one candidate file -> a list of table dicts (one per sheet that has a
    usable header + at least one amount-like column), or (empty list, error string)."""
    try:
        wb = openpyxl.load_workbook(str(path), data_only=True)
    except Exception as e:
        return [], f"could not open: {e}"

    tables = []
    try:
        for ws in wb.worksheets:
            if _sheet_too_big(ws):
                continue
            header_rows = find_header_rows(ws, MAX_SOURCE_HEADER_SCAN_ROWS)
            if not header_rows:
                continue
            header_row = header_rows[0]
            info = build_header_info(ws, header_row)
            if not info["amount_cols"]:
                continue

            rows = []
            for i, row in enumerate(ws.iter_rows(min_row=header_row + 1)):
                if i >= MAX_SOURCE_ROWS:
                    break
                row_vals = {c.column: c.value for c in row}
                if any(v is not None for v in row_vals.values()):
                    rows.append(row_vals)

            tables.append(
                dict(
                    path=path,
                    sheet=ws.title,
                    info=info,
                    rows=rows,
                    n_rows=len(rows),
                )
            )
    finally:
        try:
            wb.close()
        except Exception:
            pass
    return tables, None


# ---------------------------------------------------------------------------
# recomputation: for one golden target, try every candidate source table's amount column
# ---------------------------------------------------------------------------


def _dedup_sum(
    rows: list[dict], amount_col: int, key_col: int | None
) -> tuple[float, int]:
    """Sum, using the FIRST non-null amount-column value per unique key (file order) when a
    key column exists; otherwise a plain sum over every row. Returns (sum, n_keys_or_rows).
    """
    if key_col is None:
        total = sum(
            row.get(amount_col) or 0
            for row in rows
            if _is_plain_number(row.get(amount_col))
        )
        return total, len(rows)
    seen = {}
    for row in rows:
        k = row.get(key_col)
        if k is None or k in seen:
            continue
        v = row.get(amount_col)
        if _is_plain_number(v):
            seen[k] = v
    return sum(seen.values()), len(seen)


def _plain_sum(rows: list[dict], amount_col: int) -> float:
    return sum(v for row in rows if _is_plain_number(v := row.get(amount_col)))


def _product_sum(rows: list[dict], amount_col: int, qty_col: int) -> float:
    """SUM(amount_col * qty_col) -- extends a per-unit price by quantity. A row with a
    non-numeric or missing quantity is treated as qty=1 (the amount is itself the line total in
    that case), never dropped -- confirmed against the real corpus that a per-unit price column
    can coexist with a genuinely blank quantity on a header/summary row this check's own
    find_header_rows already excludes, so this fallback is defensive, not load-bearing on either
    validated example."""
    total = 0.0
    for row in rows:
        amt = row.get(amount_col)
        if not _is_plain_number(amt):
            continue
        qty = row.get(qty_col)
        total += amt * (qty if _is_plain_number(qty) else 1)
    return total


def _looks_like_filter_label(label: str | None) -> bool:
    if not label:
        return False
    if len(label) > PLAUSIBLE_FILTER_LABEL_MAX_LEN:
        return False
    if "." in label or len(label.split()) > 3:
        return False
    return True


def compute_candidates(target: dict, source_tables: list[dict]) -> list[dict]:
    candidates = []
    label = target.get("label")
    try_filter = _looks_like_filter_label(label)

    for table in source_tables:
        info = table["info"]
        rows = table["rows"]
        key_col = info["key_col"]

        qty_col = info.get("quantity_col")

        for amount_col, header_text in info["amount_cols"].items():
            raw_sum = _plain_sum(rows, amount_col)
            candidates.append(
                dict(
                    method="sum_all_rows",
                    file=str(table["path"]),
                    sheet=table["sheet"],
                    column=header_text,
                    value=raw_sum,
                    n_rows=len(rows),
                )
            )
            if qty_col is not None:
                candidates.append(
                    dict(
                        method="sum_product_all_rows",
                        file=str(table["path"]),
                        sheet=table["sheet"],
                        column=header_text,
                        quantity_column=info["cols"].get(qty_col),
                        value=_product_sum(rows, amount_col, qty_col),
                        n_rows=len(rows),
                    )
                )
            if key_col is not None:
                dedup_val, n_keys = _dedup_sum(rows, amount_col, key_col)
                candidates.append(
                    dict(
                        method="sum_dedup_by_key",
                        file=str(table["path"]),
                        sheet=table["sheet"],
                        column=header_text,
                        value=dedup_val,
                        n_rows=n_keys,
                    )
                )

            if try_filter and info["filter_cols"]:
                label_norm = label.strip().casefold()
                for filter_col, filter_header in info["filter_cols"].items():
                    filtered = [
                        row
                        for row in rows
                        if isinstance(row.get(filter_col), str)
                        and row[filter_col].strip().casefold() == label_norm
                    ]
                    if not filtered:
                        continue
                    f_raw = _plain_sum(filtered, amount_col)
                    candidates.append(
                        dict(
                            method="sum_all_rows_filtered",
                            file=str(table["path"]),
                            sheet=table["sheet"],
                            column=header_text,
                            filter_column=filter_header,
                            filter_value=label,
                            value=f_raw,
                            n_rows=len(filtered),
                        )
                    )
                    if qty_col is not None:
                        candidates.append(
                            dict(
                                method="sum_product_all_rows_filtered",
                                file=str(table["path"]),
                                sheet=table["sheet"],
                                column=header_text,
                                quantity_column=info["cols"].get(qty_col),
                                filter_column=filter_header,
                                filter_value=label,
                                value=_product_sum(filtered, amount_col, qty_col),
                                n_rows=len(filtered),
                            )
                        )
                    if key_col is not None:
                        f_dedup_val, f_n_keys = _dedup_sum(
                            filtered, amount_col, key_col
                        )
                        candidates.append(
                            dict(
                                method="sum_dedup_by_key_filtered",
                                file=str(table["path"]),
                                sheet=table["sheet"],
                                column=header_text,
                                filter_column=filter_header,
                                filter_value=label,
                                value=f_dedup_val,
                                n_rows=f_n_keys,
                            )
                        )
    return candidates


def values_match(
    golden_value: float, candidate_value: float
) -> tuple[bool, float, float]:
    diff = abs(golden_value - candidate_value)
    tol = max(MATCH_ABS_FLOOR, MATCH_REL_TOL * abs(golden_value))
    return diff <= tol, diff, tol


def classify_severity(status_text: str | None, row_count_corroborated: bool) -> str:
    st = _norm(status_text)
    if DERIVED_STATUS_RE.search(st):
        return "fail"
    if row_count_corroborated:
        return "fail"
    if RAW_FACT_STATUS_RE.search(st):
        return "info"
    return "warn"


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir: Path) -> dict:
    task_id = task_dir.name
    result = {
        "task_id": task_id,
        "status": None,
        "findings": [],
        "checked": [],
        "informational_mismatches": [],
        "not_recomputable": [],
        "errors": [],
    }

    golden_paths = find_golden_spreadsheets(task_dir)
    if not golden_paths:
        result["status"] = "skip"
        result["errors"].append("no spreadsheet under solution/ -- nothing to check")
        return result

    all_targets: list[dict] = []
    # Keyed by (golden_file, sheet_name) -- deliberately NOT one task-wide pool. A task-wide pool
    # was tried first and confirmed, empirically, to make row_count_corroborated fire on nearly
    # every mismatch: a real golden workbook contains dozens of small integers (dollar totals,
    # order counts, percentages) and a real candidate-recomputation sweep produces dozens of
    # distinct n_rows values, so a coincidental intersection is the norm, not the exception,
    # across a WHOLE workbook. Scoped to the same sheet the target cell itself lives on, this
    # still finds both the row-level corroboration (the CA row's own adjacent count) and the
    # sheet-level one (Orders and AOV Basis Trace's "12177 raw rows" stated a few rows above the
    # cell it corroborates), while no longer matching against a completely unrelated sheet's
    # unrelated numbers.
    basis_hints_by_sheet: dict[tuple[str, str], set[int]] = {}
    for gp in golden_paths:
        try:
            wb = openpyxl.load_workbook(str(gp), data_only=True)
        except Exception as e:
            result["errors"].append(f"{gp.name}: could not open golden workbook: {e}")
            continue
        try:
            for ws in wb.worksheets:
                if _sheet_too_big(ws):
                    result["errors"].append(
                        f"{gp.name}::{ws.title}: sheet too large, skipped ({ws.max_row}x{ws.max_column})"
                    )
                    continue
                try:
                    targets, hints = extract_golden_targets(ws, ws.title)
                except Exception as e:
                    result["errors"].append(f"{gp.name}::{ws.title}: {e}")
                    continue
                for t in targets:
                    t["golden_file"] = gp.name
                all_targets.extend(targets)
                basis_hints_by_sheet[(gp.name, ws.title)] = hints
        finally:
            try:
                wb.close()
            except Exception:
                pass

    if not all_targets:
        result["status"] = "skip"
        result["errors"].append(
            "no total/subtotal/amount/revenue/sales-labeled column found in any golden table -- "
            "nothing this check's pattern applies to"
        )
        return result

    env_paths = find_environment_spreadsheets(task_dir)
    if not env_paths:
        result["status"] = "skip"
        result["errors"].append(
            f"{len(all_targets)} candidate target cell(s) found in the golden, but no "
            "spreadsheet exists under environment/ to recompute them against"
        )
        return result

    source_tables: list[dict] = []
    for ep in env_paths:
        tables, err = build_source_tables(ep)
        if err:
            result["errors"].append(f"{ep.relative_to(task_dir)}: {err}")
            continue
        source_tables.extend(tables)

    if not source_tables:
        result["status"] = "skip"
        result["errors"].append(
            f"{len(env_paths)} spreadsheet(s) under environment/, but none had a "
            "recognizable header row with a total/subtotal/amount/revenue/sales-labeled column"
        )
        return result

    any_fail = False
    any_warn = False
    any_pass = False

    for target in all_targets:
        candidates = compute_candidates(target, source_tables)
        if not candidates:
            result["not_recomputable"].append(
                {
                    "golden_file": target["golden_file"],
                    "sheet": target["sheet"],
                    "cell": target["cell"],
                    "header_text": target["header_text"],
                    "label": target["label"],
                    "value": target["value"],
                    "note": (
                        "no candidate source column (total/subtotal/amount/revenue/sales) found "
                        "in any environment spreadsheet -- not checked, not asserted correct"
                    ),
                }
            )
            continue

        matched = None
        for c in candidates:
            ok, diff, tol = values_match(target["value"], c["value"])
            c["diff"] = diff
            c["tolerance"] = tol
            c["within_tolerance"] = ok
            if ok and matched is None:
                matched = c

        if matched is not None:
            any_pass = True
            result["checked"].append(
                {
                    "golden_file": target["golden_file"],
                    "sheet": target["sheet"],
                    "cell": target["cell"],
                    "header_text": target["header_text"],
                    "label": target["label"],
                    "golden_value": target["value"],
                    "outcome": "grounded",
                    "matched_candidate": matched,
                }
            )
            continue

        sheet_hints = basis_hints_by_sheet.get(
            (target["golden_file"], target["sheet"]), set()
        )
        hint_pool = set(target["row_count_hints"]) | sheet_hints
        # Deliberately restricted to candidates that used an actual FILTER match (this row's own
        # label found as a real value in the source's Province/State/etc. column), not a bare
        # row-count coincidence on an unfiltered candidate. A bare-count version of this check was
        # tried first and confirmed, empirically, to produce real false "fail" verdicts: on a
        # financial-close/reconciliation task (SVC-PC-14-3-0), 9 ordinary financial-statement line
        # items ("AP aging total", "Bank reconciliation in-transit item", ...) got
        # row_count_corroborated=True purely because SOME unrelated candidate's row count
        # happened to equal SOME other number on the same sheet -- no topical connection to the
        # row at all, just numeric coincidence on a busy sheet with many small integers. Requiring
        # the corroborating candidate to ALSO be the product of a genuine label match (the row's
        # own text found as a real cell value in a real filter column) combines two independent
        # pieces of evidence instead of one, and is what the real SVC-PC-37-3-0 example actually
        # has (every one of its 11 state rows' corroborating candidate is filtered on that exact
        # state). The Orders and AOV Basis Trace sheet's own C8 finding does not need this path at
        # all -- its fail-tier status comes from the golden's own "Derived" Status cell,
        # independent of row-count corroboration, and is unaffected by this restriction.
        filtered_candidates = [c for c in candidates if "filtered" in c["method"]]
        row_count_corroborated = any(
            c["n_rows"] in hint_pool for c in filtered_candidates
        )
        severity = classify_severity(target["status_text"], row_count_corroborated)

        # Rank a candidate that actually used THIS row's own label as its filter ahead of a
        # numerically-closer but unrelated one from a different file/column -- a coincidental
        # match from an irrelevant sheet is common (see this script's own commit message: FL/OH
        # /NY on SVC-PC-37-3-0's Jurisdiction Summary each have a real, correctly-filtered
        # Sales_Orders.xlsx candidate that is NOT the single closest-by-diff candidate, because an
        # unrelated Q2_Growth_Results.xlsx total happens to land nearer the golden value by pure
        # coincidence) and reporting only the closest-by-diff candidate would bury the actually
        # relevant recomputation a human reviewer needs to see.
        target_label_norm = (target.get("label") or "").strip().casefold()

        def _rank_key(c):
            used_target_label = (
                target_label_norm != ""
                and c.get("filter_value")
                and c["filter_value"].strip().casefold() == target_label_norm
            )
            return (0 if used_target_label else 1, c["diff"])

        top_candidates = sorted(candidates, key=_rank_key)[:5]
        entry = {
            "kind": "golden_arithmetic_mismatch",
            "severity": severity,
            "golden_file": target["golden_file"],
            "sheet": target["sheet"],
            "cell": target["cell"],
            "header_text": target["header_text"],
            "label": target["label"],
            "status_text": target["status_text"],
            "basis_text": target["basis_text"],
            "golden_value": target["value"],
            "row_count_corroborated": row_count_corroborated,
            "candidates_tried": len(candidates),
            "closest_candidates": top_candidates,
            "detail": (
                f"Golden states {target['value']!r} at {target['sheet']}!{target['cell']} "
                f"(column '{target['header_text']}'"
                + (f", row label {target['label']!r}" if target["label"] else "")
                + f"), but no recomputation from {len(source_tables)} environment table(s) "
                f"across {len(candidates)} candidate(s) matches within tolerance. Closest: "
                f"{top_candidates[0]['value']!r} via {top_candidates[0]['method']} on "
                f"{Path(top_candidates[0]['file']).name} (diff {top_candidates[0]['diff']:.2f})."
            ),
        }

        if severity == "info":
            result["informational_mismatches"].append(entry)
        else:
            result["findings"].append(entry)
            if severity == "fail":
                any_fail = True
            elif severity == "warn":
                any_warn = True

        result["checked"].append(
            {
                "golden_file": target["golden_file"],
                "sheet": target["sheet"],
                "cell": target["cell"],
                "header_text": target["header_text"],
                "label": target["label"],
                "golden_value": target["value"],
                "outcome": (
                    "mismatch" if severity != "info" else "mismatch_informational"
                ),
                "severity": severity,
            }
        )

    if any_fail:
        result["status"] = "fail"
    elif any_warn:
        result["status"] = "warn"
    elif any_pass:
        result["status"] = "pass"
    else:
        result["status"] = "skip"

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HOW_TO_READ_THIS_REPORT = {
    "purpose": (
        "Recomputes a golden workbook's own total/subtotal/amount/revenue/sales-labeled cells "
        "from the task's real source spreadsheets in environment/, and flags a divergence beyond "
        "tolerance (max($25, 1%)). A DIFFERENT defect class from criterion_groundedness_check.py "
        "(does a fact appear anywhere in environment/) and formula_health_check.py (does a live "
        "Excel formula recompute to its own cached value) -- this one catches a literal, "
        "hand-typed golden number that is a wrong SUM of real data that does exist."
    ),
    "task_status": {
        "fail": (
            "At least one mismatch where the golden itself discloses the cell as "
            "derived/computed (a same-row Status cell), or where a candidate source table's row "
            "count independently corroborates that the right source data was found."
        ),
        "warn": (
            "At least one mismatch found by column-header heuristics alone, with no Status-cell "
            "disclosure and no row-count corroboration -- a real but lower-confidence signal."
        ),
        "pass": "At least one aggregation-labeled cell was grounded against real source data.",
        "skip": (
            "Nothing to check: no golden spreadsheet, no total/subtotal/amount-labeled column in "
            "any golden table, no spreadsheet under environment/, or no environment table had a "
            "recognizable header with a matching column."
        ),
    },
    "informational_mismatches": (
        "Mismatches on a cell the golden's own Status column marks as a RAW fact (Confirmed / "
        "Actual / Reported / Stated), with no row-count corroboration. Not counted toward status "
        "-- a raw fact isn't asserted as independently re-derivable from a spreadsheet sum, so a "
        "failure to reproduce it here is far more likely this check's own limitation."
    ),
    "not_recomputable": (
        "A candidate cell existed but no environment spreadsheet had a plausible matching column "
        "to check it against. Not a finding -- absence of evidence, not evidence of correctness."
    ),
    "the_one_thing_this_check_cannot_see": (
        "A golden value stated as narrative PROSE (a sentence inside a text cell or an "
        "accompanying .docx), rather than a labeled table column. See this script's own module "
        "docstring for a real, hand-confirmed example (SVC-PC-5-3-0) this check does not catch."
    ),
}


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "") -> list[Path]:
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


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Golden arithmetic check: recomputes total/subtotal/amount/revenue/sales-labeled "
            "golden cells from environment/ source spreadsheets and flags divergence."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        help="root directory (REQUIRED)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this",
    )
    ap.add_argument(
        "--out", type=Path, default=None, help="write the aggregate JSON report here"
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error("--root is required")
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")
    if not args.root.is_dir():
        print(
            f"--root does not exist or is not a directory: {args.root}", file=sys.stderr
        )
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
        except Exception as e:
            r = {
                "task_id": task_dir.name,
                "status": "error",
                "errors": [f"unhandled exception: {e}"],
                "findings": [],
                "checked": [],
                "informational_mismatches": [],
                "not_recomputable": [],
            }
        results.append(r)
        print(
            f"    -> {r['status']}  ({len(r.get('checked', []))} cell(s) checked, "
            f"{len(r.get('findings', []))} finding(s))",
            file=sys.stderr,
        )

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    finding_counts: dict[str, int] = {}
    for r in results:
        for f in r.get("findings", []):
            k = f.get("severity", "unknown")
            finding_counts[k] = finding_counts.get(k, 0) + 1

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "id_prefix": args.id_prefix,
        "n_tasks": len(results),
        "status_counts": counts,
        "finding_severity_counts": finding_counts,
        "how_to_read_this_report": HOW_TO_READ_THIS_REPORT,
        "results": results,
    }

    print(f"\n{len(results)} task(s) checked.")
    print("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if finding_counts:
        print(
            "finding severity counts: "
            + ", ".join(f"{k}={v}" for k, v in sorted(finding_counts.items()))
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
