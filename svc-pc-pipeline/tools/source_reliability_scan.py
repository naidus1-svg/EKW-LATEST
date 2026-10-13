#!/usr/bin/env python3
"""
source_reliability_scan.py - GATE-V2 class N: golden ignores reliability
flags on the sources it uses (1b class N, 3.2 map (d), section 4 step 1
`source_reliability_scan.py`). Extended 12:45 UTC for class R (authority
labels) and the unrendered-template-expression pass.

Per task, extracts source text over environment/initial_workspace/,
solution/files AND instruction.md (reusing _qc_common.py's extraction:
openpyxl for xlsx, python-docx for docx, MarkItDown fallback for
everything else) and flags occurrences of:

  - the original 10 reliability tokens: unreconciled, do not rely, draft,
    not approved, TBD, preliminary, superseded, placeholder, does not tie,
    unaudited (class N, map (d), unchanged from the original build).
  - (12:45 UTC, class R) two more STATUS tokens carried on a source
    document: "at management's direction", "not official" -- together
    with draft/not approved/TBD above, these are the five status words
    GATE-V2 3.2 map (d)/1c class R checks a figure's AUTHORITY LABEL
    against.
  - (12:45 UTC, class R) five AUTHORITY-LABEL claim words as they appear
    in instruction.md or the golden (solution/files): board-set / board
    set, approved, final, locked, official. A claim is a "board set /
    approved / final / locked / official" figure asserted by the
    instruction or golden; "not approved/final/locked/official" is
    excluded from the claim side (that is the SOURCE denying the label,
    handled by the status side, not the instruction/golden asserting it).
  - (12:45 UTC, class R) `unrendered_template`: source text carrying a
    literal, un-substituted template expression -- `+$(`, `{{`,
    `[INSERT`, or `<T` followed by a digit (e.g. `<T20`, avoids matching
    ordinary lowercase html tags like `<table>`/`<td>`). Real corpus hit:
    53-5-0's `FY2022 Ops Capacity & Headcount Plan ($4-5M, 20-22 FTE)
    (final).doc` carries literal `+$(T20.inYear)+`.

Per flag hit, records the file, the cell/paragraph/line location, the flag
text, and the nearest numeric figure (a dollar amount, percentage, or plain
number) found on the same row (xlsx) / paragraph (docx) / line (everything
else), expanding outward a few rows/paragraphs/lines if none is found in
place.

AUTHORITY-CONTRADICTION CANDIDATES (class R, new)
--------------------------------------------------
After the per-file pass, for every task that has BOTH >=1 authority-label
claim hit (in instruction.md or solution/files) AND >=1 status-token hit
on some file under environment/initial_workspace/, this script emits one
additional "authority_contradiction" row per (task, status file): the
claim location/label/nearby-figure, paired with that file's status
label(s) and nearby figure. This is a CANDIDATE list, not a proof --
unlike the arithmetic checks in formula_cache_scan.py, matching a claim to
a status hit does NOT require the two nearby figures to be numerically
equal (real-corpus text is too noisy for that: MHTML .doc sources in this
corpus carry raw quoted-printable/HTML-entity artifacts -- e.g. "$4&#8=\n
211;5M" for "$4-5M" -- that break naive figure extraction, and the real
53-5-0 defect is precisely that the LABEL is pinned to a DIFFERENT figure
than the one the source calls locked/board-recorded, so same-figure
matching would have missed it entirely). The CR reads both sides and
confirms; see GATE-V2.md 3.2 map (d) / 1c class R.

READ-ONLY: only reads corpus files, never modifies them. Run corpus-wide
(NOTE: per this build's instructions, NOT run corpus-wide in this
session -- see --task below for the fast single-task path used to build
and sanity-check this script; full-corpus text extraction is the slow
path). Parallelized (ProcessPoolExecutor) because the corpus has ~54k
environment files; a per-file 25s soft timeout (SIGALRM) guards against a
pathological single file stalling the whole run -- timed-out files are
logged to stderr and skipped, not silently dropped.

Output: CSV [task, file, loc, flag, nearest_figure]. `flag` is one of the
15 per-file token labels above, "unrendered_template", or
"authority_contradiction" (the cross-referenced class-R candidate rows,
appended after the per-file pass).

Usage:
    python3 source_reliability_scan.py [--corpus-root PATH] [--out PATH]
        [--task NAME] [--workers N] [--verdict-out PATH]

--task <TASK> restricts the whole run (per-file pass, authority
cross-reference, and --verdict-out) to one task -- this is the fast path;
full-corpus text extraction with no --task is the slow path and was not
run in this build (see GATE-V2.md session instructions).
"""
from __future__ import annotations

import argparse
import re
import signal
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import (
    DEFAULT_CORPUS_ROOT,
    DEFAULT_REPORTS_DIR,
    extract_document_text,
    list_tasks,
    read_text_safe,
    write_csv,
)

# (label, compiled regex) -- case-insensitive, word/phrase-bounded.
# Original 10 class-N reliability tokens, unchanged.
FLAGS: list[tuple[str, re.Pattern]] = [
    ("unreconciled", re.compile(r"\bunreconciled\b", re.I)),
    ("do not rely", re.compile(r"\bdo[\s-]not[\s-]rely\b", re.I)),
    ("draft", re.compile(r"\bdraft\b", re.I)),
    ("not approved", re.compile(r"\bnot approved\b", re.I)),
    ("TBD", re.compile(r"\bTBD\b", re.I)),
    ("preliminary", re.compile(r"\bpreliminary\b", re.I)),
    ("superseded", re.compile(r"\bsuperseded\b", re.I)),
    ("placeholder", re.compile(r"\bplaceholder\b", re.I)),
    ("does not tie", re.compile(r"\bdoes not tie\b", re.I)),
    ("unaudited", re.compile(r"\bunaudited\b", re.I)),
]

# (12:45 UTC, class R) two more status tokens a SOURCE document states
# about a figure's authority -- apostrophe made tolerant of the HTML
# entity ("&#39;"/"&apos;") this corpus's MHTML .doc sources carry.
STATUS_EXTRA: list[tuple[str, re.Pattern]] = [
    ("at management's direction", re.compile(r"\bat\s+management(?:'|&#39;|&apos;|’)?s\s+direction\b", re.I)),
    ("not official", re.compile(r"\bnot\s+official\b", re.I)),
]

# The five status words GATE-V2 checks an authority label against (three
# already exist in FLAGS: draft, not approved, TBD).
STATUS_LABEL_NAMES = {"draft", "not approved", "TBD", "at management's direction", "not official"}

# (12:45 UTC, class R) five authority-label CLAIM words, as they appear in
# instruction.md or the golden. Negative lookbehind excludes "not X" --
# that is the source's denial, not a claim, handled by STATUS_EXTRA/FLAGS.
AUTHORITY_LABELS: list[tuple[str, re.Pattern]] = [
    ("board-set/board set", re.compile(r"\bboard[\s-]set\b", re.I)),
    ("approved", re.compile(r"(?<!not )(?<!not-)\bapproved\b", re.I)),
    ("final", re.compile(r"(?<!not )(?<!not-)\bfinal\b", re.I)),
    ("locked", re.compile(r"(?<!not )(?<!not-)\blocked\b", re.I)),
    ("official", re.compile(r"(?<!not )(?<!not-)\bofficial\b", re.I)),
]
AUTHORITY_LABEL_NAMES = {label for label, _ in AUTHORITY_LABELS}

# (12:45 UTC, class R) unrendered template expressions in extracted source
# text. `<T\d` (capital T + digit) avoids matching ordinary lowercase html
# tags (<table>, <td>, ...) that MIME/MHTML fallback extraction leaves in
# the text verbatim.
TEMPLATE_FLAGS: list[tuple[str, re.Pattern]] = [
    ("unrendered_template", re.compile(r"\+\$\(|\{\{|\[INSERT|<T\d")),
]

ALL_PATTERNS: list[tuple[str, re.Pattern]] = FLAGS + STATUS_EXTRA + AUTHORITY_LABELS + TEMPLATE_FLAGS

FIGURE_RE = re.compile(r"\(?-?\$?\d[\d,]*(?:\.\d+)?%?\)?")
# Richer figure regex for the authority/status cross-reference only: also
# captures a "$4-5M"-style range and a K/M/B suffix. Kept separate from
# FIGURE_RE so the original reliability-flag nearest-figure behavior is
# unchanged.
RICH_FIGURE_RE = re.compile(
    r"\(?-?\$?\d[\d,]*(?:\.\d+)?\s*(?:-\s*\$?\d[\d,]*(?:\.\d+)?)?\s*[KMB]?%?\)?", re.I
)
_SUFFIX_MULT = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}


def _clean_figure(s: str) -> str:
    return s.strip().strip(",;: ")

SKIP_NAMES = {".ds_store", "thumbs.db"}
SKIP_SUFFIXES = {".dvc", ".zip"}

PER_FILE_TIMEOUT_S = 300  # CPU seconds per file (SIGVTALRM); 2026-09-19: Sales_Order_Receipts.pdf needs 146 to 151, Sales_Orders.xlsx 31; the old 25 skipped both on every task
PER_FILE_WALL_BACKSTOP_S = 1200  # hung-read backstop (SIGALRM); the limit above is CPU time, immune to starvation


def _record_skip(path, why):
    """Append a file that could not be scanned to the sidecar the parent named in QC_SCAN_SKIP_FILE (O_APPEND, one short line)."""
    import os as _os

    target = _os.environ.get("QC_SCAN_SKIP_FILE")
    if target:
        try:
            with open(target, "a") as fh:
                fh.write(f"{path}\t{why}\n")
        except OSError:
            pass




class _TimeoutErr(BaseException):  # not Exception: a broad `except Exception` in extractor code must not swallow it
    pass


def _alarm(signum, _frame):
    raise _TimeoutErr("cpu-budget" if signum == signal.SIGVTALRM else "wall-backstop")


def _nearest_figure_in_lines(lines: list[str], idx: int, window: int = 8) -> str:
    if idx < len(lines) and FIGURE_RE.search(lines[idx]):
        m = FIGURE_RE.search(lines[idx])
        return _clean_figure(m.group(0))
    for d in range(1, window + 1):
        for j in (idx - d, idx + d):
            if 0 <= j < len(lines):
                m = FIGURE_RE.search(lines[j])
                if m:
                    return f"{_clean_figure(m.group(0))} ({'above' if j < idx else 'below'} {d})"
    return "NONE"


_RICH_FIGURE_LABELS = AUTHORITY_LABEL_NAMES | STATUS_LABEL_NAMES


def _scan_generic_text(text: str, patterns: list[tuple[str, re.Pattern]] = ALL_PATTERNS) -> list[tuple[str, str, str]]:
    """Line-granularity scan for markitdown-extracted / plain text."""
    rows = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        for label, rx in patterns:
            if rx.search(line):
                if label in _RICH_FIGURE_LABELS:
                    fig = _nearest_rich_figure_in_lines(lines, i)
                else:
                    fig = _nearest_figure_in_lines(lines, i)
                rows.append((f"line{i + 1}", label, fig))
    return rows


def _scan_xlsx(path: Path, patterns: list[tuple[str, re.Pattern]] = ALL_PATTERNS) -> list[tuple[str, str, str]]:
    import openpyxl

    rows = []
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            grid: dict[int, dict[int, object]] = {}
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        grid.setdefault(cell.row, {})[cell.column] = cell.value
            for row in ws.iter_rows():
                for cell in row:
                    v = cell.value
                    if not isinstance(v, str) or not v.strip():
                        continue
                    for label, rx in patterns:
                        if rx.search(v):
                            if label in _RICH_FIGURE_LABELS:
                                fig = _nearest_rich_figure_same_row_xlsx(grid, cell.row, cell.column, ws)
                            else:
                                fig = _nearest_figure_same_row_xlsx(grid, cell.row, cell.column, ws)
                            rows.append((f"{ws.title}!{cell.coordinate}", label, fig))
    finally:
        wb.close()
    return rows


def _nearest_rich_figure_same_row_xlsx(grid, row_idx, col_idx, ws, window: int = 20) -> str:
    """Same shape as _nearest_figure_same_row_xlsx but RICH_FIGURE_RE
    (K/M/B suffix, "A-B" range) and a wider row window -- used only for
    AUTHORITY_LABEL/STATUS_LABEL hits, see find_authority_contradictions."""
    row_vals = grid.get(row_idx, {})
    for c, v in sorted(row_vals.items()):
        if c == col_idx:
            continue
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str):
            m = RICH_FIGURE_RE.search(v)
            if m and re.search(r"\d", m.group(0)):
                return m.group(0).strip()
    for d in range(1, window + 1):
        for r in (row_idx - d, row_idx + d):
            rvals = grid.get(r, {})
            for c, v in sorted(rvals.items()):
                if isinstance(v, (int, float)):
                    return f"{v} ({'above' if r < row_idx else 'below'} {d})"
                if isinstance(v, str):
                    m = RICH_FIGURE_RE.search(v)
                    if m and re.search(r"\d", m.group(0)):
                        return f"{m.group(0).strip()} ({'above' if r < row_idx else 'below'} {d})"
    return "NONE"


def _nearest_figure_same_row_xlsx(grid, row_idx, col_idx, ws, window: int = 6) -> str:
    row_vals = grid.get(row_idx, {})
    for c, v in sorted(row_vals.items()):
        if c == col_idx:
            continue
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str) and FIGURE_RE.search(v):
            m = FIGURE_RE.search(v)
            if m and re.search(r"\d", m.group(0)):
                return _clean_figure(m.group(0))
    for d in range(1, window + 1):
        for r in (row_idx - d, row_idx + d):
            rvals = grid.get(r, {})
            for c, v in sorted(rvals.items()):
                if isinstance(v, (int, float)):
                    return f"{v} ({'above' if r < row_idx else 'below'} {d})"
                if isinstance(v, str):
                    m = FIGURE_RE.search(v)
                    if m and re.search(r"\d", m.group(0)):
                        return f"{_clean_figure(m.group(0))} ({'above' if r < row_idx else 'below'} {d})"
    return "NONE"


def _scan_docx(path: Path, patterns: list[tuple[str, re.Pattern]] = ALL_PATTERNS) -> list[tuple[str, str, str]]:
    import docx

    rows = []
    d = docx.Document(str(path))
    paras = [p.text for p in d.paragraphs]
    for i, text in enumerate(paras):
        for label, rx in patterns:
            if rx.search(text):
                if label in _RICH_FIGURE_LABELS:
                    fig = _nearest_rich_figure_in_lines(paras, i)
                else:
                    fig = _nearest_figure_in_lines(paras, i)
                rows.append((f"para{i}", label, fig))
    for ti, table in enumerate(d.tables):
        table_rows = [[cell.text for cell in trow.cells] for trow in table.rows]
        for ri, trow in enumerate(table_rows):
            for ci, text in enumerate(trow):
                for label, rx in patterns:
                    if rx.search(text):
                        fig = "NONE"
                        fig_re = RICH_FIGURE_RE if label in _RICH_FIGURE_LABELS else FIGURE_RE
                        for c2, v in enumerate(trow):
                            if c2 != ci and fig_re.search(v) and re.search(r"\d", v):
                                fig = fig_re.search(v).group(0).strip()
                                break
                        rows.append((f"table{ti}r{ri}c{ci}", label, fig))
    return rows


def _process_file(job: tuple[str, str, str]) -> list[tuple[str, str, str, str, str]]:
    """job = (task_name, relpath, abspath). Returns full CSV rows."""
    task_name, relpath, abspath_s = job
    abspath = Path(abspath_s)
    signal.signal(signal.SIGALRM, _alarm)
    signal.signal(signal.SIGVTALRM, _alarm)
    signal.alarm(PER_FILE_WALL_BACKSTOP_S)
    signal.setitimer(signal.ITIMER_VIRTUAL, PER_FILE_TIMEOUT_S)
    try:
        ext = abspath.suffix.lower()
        if ext == ".xlsx":
            hits = _scan_xlsx(abspath)
        elif ext == ".docx":
            hits = _scan_docx(abspath)
        else:
            text = extract_document_text(abspath)
            hits = _scan_generic_text(text) if text else []
        return [(task_name, relpath, loc, flag, fig) for (loc, flag, fig) in hits]
    except _TimeoutErr as exc:
        print(f"TIMEOUT>{PER_FILE_TIMEOUT_S}s ({exc}) skipped: {abspath}", file=sys.stderr)
        _record_skip(abspath, f"timeout {exc}")
        return []
    except Exception as exc:
        print(f"ERROR {abspath}: {exc}", file=sys.stderr)
        _record_skip(abspath, f"error {exc}")
        return []
    finally:
        signal.setitimer(signal.ITIMER_VIRTUAL, 0)
        signal.alarm(0)


def build_jobs(task_dir: Path) -> list[tuple[str, str, str]]:
    jobs = []
    instruction_md = task_dir / "instruction.md"
    if instruction_md.is_file():
        jobs.append((task_dir.name, "instruction.md", str(instruction_md)))
    for base in (task_dir / "environment" / "initial_workspace", task_dir / "solution" / "files"):
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if p.name.lower() in SKIP_NAMES or p.suffix.lower() in SKIP_SUFFIXES:
                continue
            jobs.append((task_dir.name, str(p.relative_to(task_dir)), str(p)))
    return jobs


# ---------------------------------------------------------------------------
# (12:45 UTC, class R) authority-label vs. source-status cross-reference
# ---------------------------------------------------------------------------


def _figure_range(raw: str) -> tuple[float, float] | None:
    """Parse a nearest-figure string (RICH_FIGURE_RE match, or the plain
    FIGURE_RE strings the per-file pass already produces) into a
    (low, high) numeric range. Handles a plain amount, a K/M/B suffix, and
    an "A-B[suffix]" range ("$4-5M" -> (4_000_000, 5_000_000)). Returns
    None for "NONE" or anything unparseable -- callers then skip the
    figure-proximity annotation but still emit the candidate row."""
    if not raw or raw == "NONE":
        return None
    s = raw.split(" (")[0].strip().strip("()")
    s = s.replace(",", "").replace("$", "").replace("%", "").strip()
    m = re.match(r"(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*([KMB])?\s*$", s, re.I)
    if m:
        mult = _SUFFIX_MULT.get((m.group(3) or "").upper(), 1.0)
        return (float(m.group(1)) * mult, float(m.group(2)) * mult)
    m = re.match(r"(-?\d+(?:\.\d+)?)\s*([KMB])?\s*$", s, re.I)
    if not m:
        return None
    mult = _SUFFIX_MULT.get((m.group(2) or "").upper(), 1.0)
    val = float(m.group(1)) * mult
    return (val, val)


def _nearest_rich_figure_in_lines(lines: list[str], idx: int, window: int = 20) -> str:
    """Same shape as _nearest_figure_in_lines but with RICH_FIGURE_RE and a
    wider window -- authority claims and their figure are often a header
    line or a couple of rows apart (golden README prose, xlsx row groups),
    not adjacent like a reliability flag and its dollar amount."""
    if idx < len(lines) and RICH_FIGURE_RE.search(lines[idx]):
        return RICH_FIGURE_RE.search(lines[idx]).group(0).strip()
    for d in range(1, window + 1):
        for j in (idx - d, idx + d):
            if 0 <= j < len(lines):
                m = RICH_FIGURE_RE.search(lines[j])
                if m:
                    return f"{m.group(0).strip()} ({'above' if j < idx else 'below'} {d})"
    return "NONE"


def find_authority_contradictions(task_name: str, rows: list[tuple[str, str, str, str, str]]) -> list[tuple[str, str, str, str, str, str]]:
    """Post-process one task's per-file rows (already collected) into
    class-R candidate rows. A claim is any AUTHORITY_LABEL hit on
    instruction.md or a solution/files/* file; a status hit is any
    STATUS_LABEL_NAMES hit on an environment/initial_workspace/* file.
    One candidate row per (task, status file) with >=1 status hit, IF the
    task also has >=1 claim -- see module docstring for why this does not
    require the two nearby figures to match numerically."""
    claims = [r for r in rows if r[3] in AUTHORITY_LABEL_NAMES and (r[1] == "instruction.md" or r[1].startswith("solution/files/"))]
    statuses = [r for r in rows if r[3] in STATUS_LABEL_NAMES and r[1].startswith("environment/initial_workspace/")]
    if not claims or not statuses:
        return []
    claim = claims[0]  # first claim is enough context for the CR; see docstring
    by_file: dict[str, list[tuple[str, str, str, str, str]]] = {}
    for r in statuses:
        by_file.setdefault(r[1], []).append(r)
    out = []
    claim_range = _figure_range(claim[4])
    for file, file_rows in sorted(by_file.items()):
        labels = sorted({r[3] for r in file_rows})
        first = file_rows[0]
        status_range = _figure_range(first[4])
        if claim_range and status_range:
            tol = 0.12
            a_lo, a_hi = claim_range[0] * (1 - tol), claim_range[1] * (1 + tol)
            b_lo, b_hi = status_range[0] * (1 - tol), status_range[1] * (1 + tol)
            fig_note = "figures overlap" if (a_lo <= b_hi and b_lo <= a_hi) else "figures differ"
        else:
            fig_note = "figure not parsed on one or both sides"
        detail = (
            f"claim '{claim[3]}' near {claim[4]} at "
            f"{claim[1]}:{claim[2]}; source states {labels} ({len(file_rows)} hit(s) in this file); {fig_note}"
        )
        out.append((task_name, file, first[2], "authority_contradiction", first[4], detail))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "source_reliability.csv")
    ap.add_argument("--task", type=str, default=None, help="restrict the whole run to one task (fast path; full-corpus is the slow path, not run this session)")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--verdict-out", type=Path, default=None, help="write task_id,source_reliability,pass|warn|fail per scanned task")
    args = ap.parse_args()
    import atexit
    import os as _os

    _os.environ["QC_SCAN_SKIP_FILE"] = str(args.out) + ".skipped"
    try:
        _os.remove(_os.environ["QC_SCAN_SKIP_FILE"])
    except OSError:
        pass

    def _skip_summary(p=_os.environ["QC_SCAN_SKIP_FILE"]):
        try:
            n = sum(1 for _ in open(p))
        except OSError:
            return
        print(f"SCAN_INCOMPLETE: {n} file(s) could not be scanned (timeout or error), listed in {p}", file=sys.stderr)

    atexit.register(_skip_summary)
    try:  # admission control: at most K heavy scans at once, W workers each (scan_slots.py, fail-open)
        import scan_slots

        scan_slots.acquire(Path(__file__).stem, args.task or "")
        args.workers = scan_slots.workers(args.workers)
    except Exception as exc:
        print(f"scan_slots unavailable, running unbounded: {exc}", file=sys.stderr)

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_jobs: list[tuple[str, str, str]] = []
    for task_dir in tasks:
        all_jobs.extend(build_jobs(task_dir))
    print(f"source_reliability_scan: {len(all_jobs)} files to scan across {len(tasks)} tasks", file=sys.stderr)

    all_rows: list[tuple[str, str, str, str, str]] = []
    done = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_process_file, job): job for job in all_jobs}
        for fut in as_completed(futs):
            done += 1
            try:
                all_rows.extend(fut.result())
            except Exception as exc:
                job = futs[fut]
                print(f"WORKER ERROR {job}: {exc}", file=sys.stderr)
            if done % 2000 == 0:
                print(f"  ...{done}/{len(all_jobs)} files done", file=sys.stderr)

    # (12:45 UTC, class R) cross-reference authority-label claims against
    # source-status hits, per task, and append the candidate rows. Computed
    # from the raw 5-field per-file rows (task, file, loc, flag,
    # nearest_figure); the output schema then gains a 6th "detail" column
    # (empty for the per-file rows, the claim/status pairing for these).
    rows_by_task: dict[str, list[tuple[str, str, str, str, str]]] = {}
    for r in all_rows:
        rows_by_task.setdefault(r[0], []).append(r)
    authority_rows: list[tuple[str, str, str, str, str, str]] = []
    for task_dir in tasks:
        authority_rows.extend(find_authority_contradictions(task_dir.name, rows_by_task.get(task_dir.name, [])))

    all_rows_out: list[tuple[str, str, str, str, str, str]] = [r + ("",) for r in all_rows] + authority_rows
    # rows_by_task (used only for verdict flag-membership below) gets the
    # authority rows added back in on the padded (6-field) shape.
    rows_by_task = {}
    for r in all_rows_out:
        rows_by_task.setdefault(r[0], []).append(r)

    n = write_csv(args.out, ["task", "file", "loc", "flag", "nearest_figure", "detail"], all_rows_out)
    tasks_flagged = {r[0] for r in all_rows_out}
    by_flag: dict[str, int] = {}
    for r in all_rows_out:
        by_flag[r[3]] = by_flag.get(r[3], 0) + 1

    print(f"source_reliability_scan: {n} flag occurrences across {len(tasks_flagged)} of {len(tasks)} tasks, written to {args.out}")
    for k, v in sorted(by_flag.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    print(f"  (of which {len(authority_rows)} are authority_contradiction candidate rows, class R)")

    if args.verdict_out:
        reliability_names = {label for label, _ in FLAGS} | STATUS_LABEL_NAMES | AUTHORITY_LABEL_NAMES
        verdict_rows = []
        for task_dir in tasks:
            task_rows = rows_by_task.get(task_dir.name, [])
            flags_here = {r[3] for r in task_rows}
            if "unrendered_template" in flags_here:
                verdict = "fail"
            elif "authority_contradiction" in flags_here or (flags_here & reliability_names):
                verdict = "warn"
            else:
                verdict = "pass"
            verdict_rows.append((task_dir.name, verdict))
        write_csv(args.verdict_out, ["task_id", "source_reliability"], verdict_rows)
        by_verdict: dict[str, int] = {}
        for _t, v in verdict_rows:
            by_verdict[v] = by_verdict.get(v, 0) + 1
        print(f"source_reliability_scan: verdicts written to {args.verdict_out}: {by_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
