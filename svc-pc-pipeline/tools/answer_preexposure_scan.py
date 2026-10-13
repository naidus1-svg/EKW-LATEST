#!/usr/bin/env python3
"""
answer_preexposure_scan.py - GATE-V2 class Q: the corpus already contains a
completed analysis of the task, and a solver that reads it gets credit for
copying it rather than deriving it.

Canonical example (25-4-0): three `FY2021_Legal_Status_and_Risk_Report*.docx`
variants and two legal closing messages, shipped inside
environment/initial_workspace/_corpus_subtree/, already state the cyber
limit, the carrier conflict, and the recommendations the task's golden is
supposed to derive. eval_471926 read them (trajectory line 1041) and was
credited on the carrier-conflict criterion. instruction.md's "Do not copy
or restate a completed answer ... re-derive every material calculation and
conclusion" does not stop this -- GATE-V2 1c is explicit that an
instruction sentence forbidding reliance is not a fix; removing the
pre-answered document from initial_workspace is the fix (3.3 Q).

Per task:
  1. GOLDEN prose: extract_document_text() over every file under
     solution/files/ (reused from _qc_common, same MarkItDown/openpyxl/
     python-docx extraction rewardkit itself uses), split into sentences.
     A sentence is kept if it has >=8 words OR matches a recommendation
     phrase ("we recommend", "the recommendation is", "our recommendation",
     "recommended action") regardless of length -- a short, punchy
     recommendation line is exactly the kind of conclusion a pre-answered
     source states verbatim.
  2. SOURCE/ENVIRONMENT text: every file under environment/initial_workspace/
     (recursive -- this is what puts the corpus_subtree in scope), broken
     into paragraph-sized units:
       - .docx: one unit per non-empty python-docx paragraph.
       - .xlsx: one unit per string cell with >=8 words (a source recap
         cell, not a header or a number).
       - everything else (pdf, doc, pptx, csv, ...): extract_document_text()
         then split on blank-line boundaries; a chunk over 600 words is
         further split into sentences (a markitdown PDF dump often yields
         one giant blob with no blank lines).
  3. Keyword-overlap each GOLDEN sentence against every SOURCE unit:
     overlap = |shared keywords| / |golden sentence keywords| -- deliberately
     NOT symmetric (Jaccard): a source paragraph is free to say more than
     the golden sentence and still fully pre-answer it, so the denominator
     is the golden side only. Overlap >=0.6 is reported at severity=fail
     (source states the golden's conclusion outright); 0.35-0.6 at
     severity=warn (partial/paraphrase overlap, CR judgment call). Below
     0.35 is noise and dropped.

Extraction is heuristic and documented, not exact: keyword-overlap is blind
to negation ("the carrier does NOT conflict") and to paraphrase beyond
shared vocabulary, so a fail-severity row is strong evidence, not proof --
the CR reads the actual paragraph before excluding a document (3.3 Q says
exclude the pre-answered document and keep the raw records it summarised;
a scan hit is the pointer to that document, not the ruling).

PERFORMANCE: this is the slow scan in the section-4 step-1 set. A single
task's initial_workspace can carry 300+ files across xlsx/docx/pdf/doc
(25-4-0: 335 files, 17 MB, mostly its _corpus_subtree). Corpus-wide is
O(202 tasks) of that -- explicitly NOT the default use; run --task on
demand per the CR's own suspicion of a specific task (a Q hit needs a
pre-answered-looking source in scope to begin with). Parallelized
(ProcessPoolExecutor) with a per-file soft timeout, same pattern as
source_reliability_scan.py and instruction_input_scan.py.

READ-ONLY. Never modifies the corpus.

Output: CSV [task, golden_sentence, source_file, source_loc, overlap,
golden_file, reason] at reports/answer_preexposure.csv. reason is
"long_sentence", "recommendation_phrase", or both joined with "+".
golden_sentence text is deduped per task before matching (see scan_task);
golden_file lists every distinct golden file the sentence occurred in,
joined by ";", when a sentence repeats (e.g. a boilerplate cell restated
on many rows) rather than emitting one row per repetition.

Usage:
    python3 answer_preexposure_scan.py --task SVC-PC-25-4-0
        [--corpus-root PATH] [--out PATH] [--workers N] [--verdict-out PATH]
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
    normalize_keywords,
    write_csv,
)

MIN_SENTENCE_WORDS = 8
FAIL_OVERLAP = 0.6
WARN_OVERLAP = 0.35
LONG_CHUNK_SPLIT_WORDS = 600

RECOMMENDATION_RE = re.compile(
    r"\bwe recommend\b|\bthe recommendation is\b|\bour recommendation\b|\brecommended action\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_BLANK_LINE_RE = re.compile(r"\n\s*\n")

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


# ---------------------------------------------------------------------------
# Golden sentence extraction
# ---------------------------------------------------------------------------


def golden_sentences_from_text(text: str) -> list[tuple[str, str]]:
    """(sentence, reason) pairs for sentences worth checking for
    pre-exposure: >=8 words, or a recommendation phrase at any length."""
    out = []
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        reasons = []
        if len(sentence.split()) >= MIN_SENTENCE_WORDS:
            reasons.append("long_sentence")
        if RECOMMENDATION_RE.search(sentence):
            reasons.append("recommendation_phrase")
        if reasons:
            out.append((sentence, "+".join(reasons)))
    return out


# ---------------------------------------------------------------------------
# Source paragraph-unit extraction
# ---------------------------------------------------------------------------


def _source_units_docx(path: Path) -> list[tuple[str, str]]:
    import docx

    d = docx.Document(str(path))
    units = []
    for i, p in enumerate(d.paragraphs):
        t = p.text.strip()
        if t:
            units.append((f"para{i}", t))
    for ti, table in enumerate(d.tables):
        for ri, row in enumerate(table.rows):
            cell_text = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
            if cell_text:
                units.append((f"table{ti}r{ri}", cell_text))
    return units


def _source_units_xlsx(path: Path) -> list[tuple[str, str]]:
    import openpyxl

    units = []
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    v = cell.value
                    if isinstance(v, str) and len(v.split()) >= MIN_SENTENCE_WORDS:
                        units.append((f"{ws.title}!{cell.coordinate}", v.strip()))
    finally:
        wb.close()
    return units


def _source_units_generic(text: str) -> list[tuple[str, str]]:
    units = []
    chunks = [c.strip() for c in _BLANK_LINE_RE.split(text) if c.strip()]
    for i, chunk in enumerate(chunks):
        if len(chunk.split()) > LONG_CHUNK_SPLIT_WORDS:
            for j, sentence in enumerate(_SENTENCE_SPLIT_RE.split(chunk)):
                sentence = sentence.strip()
                if sentence:
                    units.append((f"chunk{i}.sent{j}", sentence))
        else:
            units.append((f"chunk{i}", chunk))
    return units


def source_units(path: Path) -> list[tuple[str, str]]:
    """(loc, text) units for one source file, dispatched by extension."""
    ext = path.suffix.lower()
    if ext == ".docx":
        return _source_units_docx(path)
    if ext == ".xlsx":
        return _source_units_xlsx(path)
    text = extract_document_text(path)
    return _source_units_generic(text) if text else []


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _overlap(golden_kws: set[str], unit_kws: set[str]) -> float:
    if not golden_kws or not unit_kws:
        return 0.0
    return len(golden_kws & unit_kws) / len(golden_kws)


def match_golden_against_units(
    golden_sentences: list[tuple[str, str, str]],  # (golden_file, sentence, reason)
    units_by_file: dict[str, list[tuple[str, str]]],
) -> list[tuple[str, str, str, str, float, str]]:
    """Returns (golden_file, golden_sentence, source_file, source_loc,
    overlap, reason), one row per (golden sentence, source unit) pair above
    WARN_OVERLAP."""
    rows = []
    golden_kw_cache = [(gf, s, r, normalize_keywords(s)) for gf, s, r in golden_sentences]
    for gf, s, r, gkws in golden_kw_cache:
        if len(gkws) < 3:
            continue
        for source_file, units in units_by_file.items():
            for loc, unit_text in units:
                ukws = normalize_keywords(unit_text)
                ov = _overlap(gkws, ukws)
                if ov >= WARN_OVERLAP:
                    rows.append((gf, s, source_file, loc, ov, r))
    return rows


# ---------------------------------------------------------------------------
# Worker (per-file extraction, parallelized)
# ---------------------------------------------------------------------------


def _extract_units_worker(job: tuple[str, str]) -> tuple[str, list[tuple[str, str]]]:
    """job = (relpath, abspath). Returns (relpath, units)."""
    relpath, abspath_s = job
    abspath = Path(abspath_s)
    signal.signal(signal.SIGALRM, _alarm)
    signal.signal(signal.SIGVTALRM, _alarm)
    signal.alarm(PER_FILE_WALL_BACKSTOP_S)
    signal.setitimer(signal.ITIMER_VIRTUAL, PER_FILE_TIMEOUT_S)
    try:
        return relpath, source_units(abspath)
    except _TimeoutErr as exc:
        print(f"TIMEOUT>{PER_FILE_TIMEOUT_S}s ({exc}) skipped: {abspath}", file=sys.stderr)
        _record_skip(abspath, f"timeout {exc}")
        return relpath, []
    except Exception as exc:
        print(f"ERROR {abspath}: {exc}", file=sys.stderr)
        _record_skip(abspath, f"error {exc}")
        return relpath, []
    finally:
        signal.setitimer(signal.ITIMER_VIRTUAL, 0)
        signal.alarm(0)


def _extract_golden_worker(job: tuple[str, str]) -> tuple[str, list[tuple[str, str]]]:
    relpath, abspath_s = job
    abspath = Path(abspath_s)
    signal.signal(signal.SIGALRM, _alarm)
    signal.signal(signal.SIGVTALRM, _alarm)
    signal.alarm(PER_FILE_WALL_BACKSTOP_S)
    signal.setitimer(signal.ITIMER_VIRTUAL, PER_FILE_TIMEOUT_S)
    try:
        text = extract_document_text(abspath)
        return relpath, golden_sentences_from_text(text) if text else []
    except _TimeoutErr as exc:
        print(f"TIMEOUT>{PER_FILE_TIMEOUT_S}s ({exc}) skipped: {abspath}", file=sys.stderr)
        _record_skip(abspath, f"timeout {exc}")
        return relpath, []
    except Exception as exc:
        print(f"ERROR {abspath}: {exc}", file=sys.stderr)
        _record_skip(abspath, f"error {exc}")
        return relpath, []
    finally:
        signal.setitimer(signal.ITIMER_VIRTUAL, 0)
        signal.alarm(0)


def _list_files(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    out = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.name.lower() in SKIP_NAMES or p.suffix.lower() in SKIP_SUFFIXES:
            continue
        out.append(p)
    return out


def scan_task(task_dir: Path, workers: int) -> list[tuple[str, str, str, str, str, str, str]]:
    """Returns full CSV rows: (task, golden_sentence, source_file,
    source_loc, overlap, golden_file, reason)."""
    golden_files = _list_files(task_dir / "solution" / "files")
    source_files = _list_files(task_dir / "environment" / "initial_workspace")
    if not golden_files or not source_files:
        return []

    golden_jobs = [(str(p.relative_to(task_dir)), str(p)) for p in golden_files]
    source_jobs = [(str(p.relative_to(task_dir)), str(p)) for p in source_files]

    golden_sentences: list[tuple[str, str, str]] = []  # (golden_file, sentence, reason)
    units_by_file: dict[str, list[tuple[str, str]]] = {}

    n_jobs = len(golden_jobs) + len(source_jobs)
    if n_jobs <= 4:
        for relpath, abspath in golden_jobs:
            _, sr = _extract_golden_worker((relpath, abspath))
            for s, r in sr:
                golden_sentences.append((relpath, s, r))
        for relpath, abspath in source_jobs:
            _, units = _extract_units_worker((relpath, abspath))
            units_by_file[relpath] = units
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            gfuts = {ex.submit(_extract_golden_worker, job): job for job in golden_jobs}
            sfuts = {ex.submit(_extract_units_worker, job): job for job in source_jobs}
            for fut in as_completed(gfuts):
                relpath, sr = fut.result()
                for s, r in sr:
                    golden_sentences.append((relpath, s, r))
            for fut in as_completed(sfuts):
                relpath, units = fut.result()
                units_by_file[relpath] = units

    if not golden_sentences or not units_by_file:
        return []

    # Dedupe identical golden sentence text before matching: a repeated
    # boilerplate cell (25-4-0's Sources register: "Only underlying company
    # records are used as evidence." on 27 of 28 rows, GATE-V2 1c) would
    # otherwise multiply every one of its matches by its row count, drowning
    # real Q hits in duplicate noise with zero added signal. golden_file
    # keeps every distinct file the sentence occurred in, joined by ";".
    dedup: dict[str, tuple[list[str], str]] = {}
    for gf, s, r in golden_sentences:
        files, reason = dedup.setdefault(s, ([], r))
        if gf not in files:
            files.append(gf)
    deduped_sentences = [(";".join(files), s, reason) for s, (files, reason) in dedup.items()]

    matches = match_golden_against_units(deduped_sentences, units_by_file)
    return [
        (task_dir.name, s, source_file, loc, f"{ov:.2f}", gf, r)
        for gf, s, source_file, loc, ov, r in matches
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "answer_preexposure.csv")
    ap.add_argument("--task", type=str, default=None, help="restrict to one task; omit to run corpus-wide (slow, see docstring)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--verdict-out", type=Path, default=None, help="write per-task verdict CSV [task_id, answer_preexposure]")
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
    if not args.task and len(tasks) > 1:
        print(
            f"WARNING: no --task given, running corpus-wide across {len(tasks)} tasks. "
            "This is the slow path (see module docstring) -- consider --task <TASK>.",
            file=sys.stderr,
        )

    all_rows: list[tuple[str, str, str, str, str, str, str]] = []
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] scanning {task_dir.name} ...", file=sys.stderr)
        try:
            all_rows.extend(scan_task(task_dir, args.workers))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")

    n = write_csv(
        args.out,
        ["task", "golden_sentence", "source_file", "source_loc", "overlap", "golden_file", "reason"],
        all_rows,
    )
    tasks_flagged = {r[0] for r in all_rows}
    fail_rows = [r for r in all_rows if float(r[4]) >= FAIL_OVERLAP]
    tasks_fail = {r[0] for r in fail_rows}

    print(f"answer_preexposure_scan: {n} candidate pre-exposure matches across {len(tasks_flagged)} of {len(tasks)} tasks, written to {args.out}")
    print(f"  {len(fail_rows)} at overlap>={FAIL_OVERLAP} (fail severity) across {len(tasks_fail)} tasks")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = []
        for task_dir in tasks:
            if task_dir.name in tasks_fail:
                verdict = "fail"
            elif task_dir.name in tasks_flagged:
                verdict = "warn"
            else:
                verdict = "pass"
            verdict_rows.append((task_dir.name, verdict))
        write_csv(args.verdict_out, ["task_id", "answer_preexposure"], verdict_rows)
        n_fail = sum(1 for _, v in verdict_rows if v == "fail")
        n_warn = sum(1 for _, v in verdict_rows if v == "warn")
        n_pass = sum(1 for _, v in verdict_rows if v == "pass")
        print(f"answer_preexposure_scan: verdicts written to {args.verdict_out} ({n_fail} fail, {n_warn} warn, {n_pass} pass)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
