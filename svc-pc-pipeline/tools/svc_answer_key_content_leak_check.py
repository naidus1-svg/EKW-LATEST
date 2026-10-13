"""Answer-key content leak check: does a task's own literal grading answer appear, verbatim,
inside a file the solver can actually read before or during solving?

Why this exists: this org's hard rule (this repo's README and the global CLAUDE.md both state
it) is "never put the answer key in front of the graded party" -- expected values, test
contents, tolerances, and grading criteria may not appear in anything a solver, candidate, or
vendor reads. Two independent adversarial QC reviews of unrelated benchmarks (Perplexity's
CompanyBench and an EKW delivery) each found a real instance of exactly this leak class: a
reference-reasoning file left in a path that gets copied into the solver-visible workspace, and
a rubric's own literal expected values appearing verbatim in something the solver could read.
Nothing else in this repo checks for it. This is a different check from the (separately built)
answer_key_leakage_check.py, which scans instruction.md for GOLDEN-named filenames and internal
pipeline-jargon leakage -- that one is about naming and jargon in the PROMPT; this one is about
literal EXPECTED VALUES (numbers, dollar amounts, dates, short quoted facts) from the grading
rubric appearing verbatim inside environment/initial_workspace/, the files the solver is
actually handed.

Status: v1, LOW-CONFIDENCE CANDIDATE-FOR-REVIEW TOOL, not a clean pass/fail gate. Read this
before trusting a "clean" result -- see "What the calibration against real data found" below.
This is a deliberate, disclosed design choice, not an oversight: false positives could not be
driven to zero on the calibration corpus's own terms (a genuine expected figure very often
legitimately appears in a real, intended-to-be-read source document -- see below), so this
script narrows to the one signal that measurably discriminated on that corpus (does the
matching file's own path/name look suspicious?) and surfaces everything else as a labeled,
non-gating diagnostic instead of pretending precision it doesn't have.

What the calibration against real data found (required before this script was finalized;
corpus: C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready, 600 real task packages):

  1. A criterion's expected value legitimately appearing in a real, intended-to-be-read source
     file is COMMON, not rare, exactly as anticipated. Hand-reading 10 real tasks' judge.toml
     "Expected:" values against their own environment/initial_workspace/ contents confirmed it
     directly: e.g. SVC-PC-1-0-0's criteria expect FY control totals ($1,204,900 net revenue,
     $(665,333) net loss, $2,186,512 ending cash, ...) that are exactly the numbers a real
     "Year_1_Management_Commentary.docx" or "Tax_Prep_Package.xlsx" in that same task's own
     environment is supposed to state -- these are approved-facts source documents the task
     narrative says the solver should read and reconcile against, not leaks.
  2. A naive "the same value literally appears somewhere in environment/" check is therefore
     nowhere near sufficient on its own -- across the same 10 tasks it fired between 12 and 873
     times per task (3,431 raw hits total), the overwhelming majority against ordinary,
     realistically-named business documents (P&L tabs, trial balances, aging reports) that are
     exactly the files the task intends the solver to read the answer's inputs from.
  3. A same-judge-file "multiple distinct expected values co-occurring in one environment file"
     signal (the other mitigation this script's spec offered as an alternative) does NOT
     discriminate on this corpus either, for the same reason: real "approved facts" source
     documents are BUILT to carry many of a task's control totals together on purpose (that's
     what makes them the approved-facts source), so this signal fires on the same legitimate
     files as #2, just as often. It is reported below (see --full-scan) as a labeled diagnostic
     only, never as the gate, because of this finding.
  4. A suspicious-file-NAME signal ("golden", "solution", "answer", "answers", "key", "reference",
     "oracle", "rubric", "grading", "judge", "cheat", ... as a whole path token, split on any
     non-alphanumeric character so "key" flags "answer_key.txt" but never "keyword.txt") was
     cheap to compute up front for the ENTIRE corpus (65,179 environment files across all 600
     tasks, under 20 seconds, zero files opened) and found only 35 file instances, resolving to
     just 3 distinct real files: "Engineering_Interview_Rubric.docx" (23 tasks, token "rubric"),
     "Product_Knowledge_Cheatsheet.docx" (11 tasks, token "cheatsheet"), and
     "Product_Knowledge_Quiz_Answers.docx" (1 task, token "answers"). All three are genuine,
     unrelated in-universe business documents (an HR interview rubric for an engineering hire; a
     customer-support pricing cheat-sheet; an employee product-knowledge quiz with its own
     answer key) that happen to contain a generic English word from the suspicious-token list.
     Every one of the 35 instances (not a sample) was then content-scanned against its own
     task's actual expected values: zero genuine hits. One incidental match surfaced during that
     check before the year exclusion below was added -- a criterion expecting the literal year
     "2021" matched "...MR, feb 2021..." in the interview rubric's own byline -- which is exactly
     the shape of noise a bare year produces everywhere.
  5. Conclusion: this script's PRIMARY, gating signal is suspicious file naming AND a
     corroborating literal/numeric value match in that same file's content -- an AND, not
     either alone. This is also why the naming-token list can stay broad (finding #4 shows even
     "rubric"/"cheatsheet"/"answers" hitting real, unrelated business documents is harmless once
     content-matching is required) rather than needing per-word anchoring tricks. On the full
     600-task corpus this combination produces zero findings (see Verification below), which is
     the expected result for a corpus with no known leaks of this kind, not evidence the check
     does nothing: with zero real positive instances available, detection was proven with a
     hand-built synthetic fixture instead (also below).

Usage:
    python answer_key_content_leak_check.py <TASK-ID> [<TASK-ID> ...] --root <path> [--out report.json]
    python answer_key_content_leak_check.py --all --root <path> [--out report.json]
    python answer_key_content_leak_check.py --all --root <path> --id-prefix MYBENCH- [--out report.json]

    --min-chars N          significant-character floor for an extracted value token to be worth
                            checking (default 4; a bare "0" or "1" is noise, disclosed and
                            tunable). "Significant characters" = alphanumeric characters only,
                            so "$1,204,900" counts as 7, "$500" counts as 3 (dropped by default).
    --include-years        by default, a bare 4-digit token that reads as a plausible calendar
                            year (1900-2099) is EXCLUDED from the extracted value set -- finding
                            4 above is exactly this noise source. Pass this flag to re-include
                            years if your task population genuinely uses a year as a protected
                            expected value (rare, but disclosed as a real trade-off: a task whose
                            actual secret answer happens to BE a 4-digit year in that range is
                            invisible to this check by default).
    --full-scan             ALSO scan every environment file (not just suspicious-named ones)
                            and report the co-occurrence diagnostic from finding #3 above, for
                            human review. Expensive (opens every spreadsheet in every task;
                            ~15s/task observed on the calibration corpus) and, per finding #3,
                            does not itself gate pass/fail -- every result it adds is reported
                            as a "candidate", never "flagged" on its own.
    --cooccurrence-threshold N
                            only meaningful with --full-scan: how many distinct expected values
                            from the SAME judge.toml file must land in the SAME environment file
                            before that (judge file, environment file) pair is even worth listing
                            as a diagnostic candidate row (default 3 -- a single coincidental
                            match is not worth a row; several is still not proof of a leak per
                            finding #3, just a row worth a human glance).

What it does, in order, per task:

1. Parses every tests/deliverables/judge.toml and tests/deliverables_*/judge.toml (both layouts
   are real, see rubric_schema_check.py's own comment on this) via tomllib. Never raises on a
   malformed file -- a parse error is recorded and that file's criteria are simply skipped.
2. For each [[criterion]].description, finds every "Expected:" label (case-insensitive, anywhere
   in the text -- not just at the start) and looks at the text from that label up to the next
   literal ".." (this rubric-authoring convention's own sentence-boundary marker, confirmed
   against 23,203 real "Expected:" occurrences in the calibration corpus) or the end of the
   description if no ".." follows. Reuses rubric_schema_check.py's BARE_TIER_RE shape (a tier
   word immediately followed by "Expected:") only as the precedent for how this repo already
   locates the "Expected:" label; this script's own EXPECTED_CLAUSE_RE looks for the label
   anywhere in the text (most real criteria put it mid-description, after the requirement
   sentence, not at the very start) and, unlike the bare-tier detector, captures the value
   tokens that follow rather than just flagging the label's presence.
3. Within that clause, extracts every value-shaped token: a dollar amount ($1,204,900 or the
   accounting-negative $(665,333)), a percentage (64.9% or -7.3%), a date (3/25/2021, 2021-03-25,
   30-Nov-2021, or "March 15, 2024"), a short quoted string ('Alice Chen, CEO'), a comma-grouped
   or decimal bare number (9,989 / 64.9), or a bare 4+-digit integer (excluding plausible
   calendar years by default, see --include-years). Anything under --min-chars significant
   characters is dropped as noise.
4. Cheaply (no files opened) flags every file under environment/initial_workspace/ whose
   relative path contains a suspicious whole-path-segment token (see SUSPICIOUS_TOKENS).
5. For every suspicious-named file found, opens and extracts its text/values: .txt/.md/.csv/.json
   read directly as UTF-8 text; .xlsx/.xlsm read cell-by-cell via openpyxl (data_only=True,
   read_only=True for speed, matching this repo's existing spreadsheet-reading convention in
   deliverable_integrity_check.py); .docx via python-docx if installed, else a zipfile +
   regex pull of every <w:t> text run out of word/document.xml (the same "a .docx IS a zip
   archive" fact deliverable_integrity_check.py's own check_docx() already relies on, used here
   for text extraction instead of integrity checking). Numeric-kind values (currency/comma
   number/decimal/bare integer) are compared by PARSED NUMERIC VALUE, not exact string, so
   "$1,204,900" in a rubric matches a spreadsheet cell holding the raw number 1204900 or the
   text "1,204,900" -- not just an identically-formatted string (this is a deliberate widening
   from pure string equality, to actually catch the "hardcoded, unformatted answer" leak shape;
   see Known limits for what it still cannot normalize). Percent/date/quoted values are matched
   as a literal case-insensitive substring only.
6. Any corroborated hit (suspicious-named file AND a genuine value match inside it) is a HIGH
   finding: the task is "flagged". With --full-scan, every OTHER environment file is scanned
   too and grouped by (judge.toml file, environment file) pair; a pair with at least
   --cooccurrence-threshold distinct matching values is reported as a MEDIUM "candidate" row
   (never flagging the task on its own, per finding #3); everything below that bar is reported
   only in the aggregate counts, not per-row, to keep the report readable.
7. Writes one JSON result per task (status: clean | candidate | flagged) plus an aggregate
   report. Never lets one task's exception kill the batch.

Verification against the real corpus (C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready,
600 real task packages; nothing under that path was modified):

- Default-mode --all sweep, full corpus: 600/600 clean, 0 candidate, 0 flagged, 0 errored,
  26 seconds. 10,784 expected-value tokens extracted across the corpus; 128 tasks had zero
  (spot-checked SVC-PC-12-6-0: its "Expected:" clauses are qualitative -- "Memo deliverable
  present", "Opens valid / complete" -- genuinely no number/date/currency to extract, not a
  missed case). 65,179 environment files path-scanned for the suspicious-naming gate,
  35 suspicious-path instances found (see calibration finding #4 above for all 3 resolving to
  legitimate, unrelated business documents), every one content-scanned, zero genuine hits.
- --full-scan spot check, 2 tasks (SVC-PC-1-0-0, SVC-PC-1-1-0): 11 seconds, 0 high, 43 and 60
  candidate rows respectively -- confirms calibration finding #3 at scale: dozens of ordinary,
  realistically-named source spreadsheets and memos per task legitimately carry 3+ of that
  task's own control totals together, exactly the "approved facts" shape the task narrative
  intends. This is why --full-scan's output is candidates for a human glance, never a gate.
- Detection proof: since the real corpus has zero genuine leaks of this kind, a minimal
  synthetic fixture was hand-built under a scratch temp path (never under the real corpus or
  this repo) -- one judge.toml criterion expecting "$1,204,900", and one environment file named
  reference_answer_key.txt containing that exact figure alongside an unrelated, plausibly-named
  Company_Ledger.txt with no matching content. The check correctly flagged the task (1 high
  finding, the $1,204,900 hit in reference_answer_key.txt, numeric_equivalent match) and did
  NOT flag Company_Ledger.txt. The fixture was deleted immediately after this positive-control
  run; nothing from it is checked in.

Provenance: built fresh for this repo, calibrated against the real corpus at
C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready per this org's hard rule ("never put the
answer key in front of the graded party", stated in this repo's README and the org's global
CLAUDE.md) and the two adversarial QC review findings (Perplexity CompanyBench, an EKW delivery)
that motivated building this as its own check rather than folding it into
answer_key_leakage_check.py's naming/jargon scope. Expects the same generic Harbor task package
shape as every other check in this repo (BUILD-CONTRACT.md): for each task,
environment/initial_workspace/ and tests/deliverables[_*]/judge.toml.

Known limits, disclosed rather than silently dropped:
    - This is a low-confidence candidate-for-review tool, not a pass/fail gate. A "flagged" task
      needs a human to look at the specific file and value named in the finding before acting --
      see the docstring's calibration section above for exactly how much real-corpus overlap
      between legitimate source documents and expected values this had to be designed around.
    - Numeric matching normalizes formatting (currency sign, thousands separators, integer vs.
      float) but not units, scale, or rounding -- an expected value of "$1.2M" written as
      "1200000" would not match (no unit-word parsing), and a value that matches after rounding
      to a different number of decimal places than this script's tolerance (0.005) will not
      match either.
    - Percent, date, and quoted-string values are matched as a literal, case-insensitive
      substring only -- no normalization. A percentage stored as a raw fraction (0.649 instead
      of the text "64.9%"), or a date in a different format than the one the rubric happened to
      use, will not be caught. This is disclosed, not silently assumed away.
    - The suspicious-filename token list is short and English-specific (see SUSPICIOUS_TOKENS).
      It will not catch a leak sitting in an innocuously-named file -- by design, per the
      calibration finding that naming was the only signal available that didn't drown in false
      positives on real "approved facts" source documents. A genuine leak in a plausibly-named
      file is invisible to the default (non---full-scan) run; --full-scan's co-occurrence
      diagnostic is the only thing in this script that could ever surface that shape, and even
      it is explicitly non-gating (see calibration finding #3).
    - Calendar-year bare numbers (1900-2099) are excluded from extraction by default (see
      --include-years) because of a real false-positive instance found during calibration (a
      criterion expecting the literal year "2021" matched an unrelated document's own byline
      date). This also means a task whose genuinely protected answer IS a bare year in that
      range is invisible to this check by default.
    - .xls (legacy binary Excel), .pptx, and .pdf are not scanned -- not asserted clean, just
      not covered. Extending EXT scanning is the one place to adapt if your task packages use
      these formats for solver-visible content.
    - This script reads only tests/deliverables[_*]/judge.toml and
      environment/initial_workspace/. It says nothing about solution/ or instruction.md itself
      (a rubric criterion leaking its own answer into its OWN description text, as opposed to
      into an environment file, is content-audit's item 5, a different check).
"""

# Copied into turing-context on 2026-09-14 from harbor-qc-checks/answer_key_content_leak_check.py.
# See tools/svc_qc_tracker_build.py CHECK_META["D"]["subchecks"]["D8"]. No logic changed.
# LOW-CONFIDENCE BY DESIGN (see this file's own docstring above): review-only, never a gate.

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Windows console defaults to cp1252, which cannot encode every character that can show up in
# real judge.toml/environment text (curly quotes, em dashes, currency symbols). Force UTF-8 with
# replacement so a printable-but-non-cp1252 character never crashes the whole sweep partway
# through a batch.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import openpyxl
except ImportError:  # pragma: no cover
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl

try:
    import docx as _python_docx  # python-docx, optional

    HAVE_PYTHON_DOCX = True
except ImportError:  # pragma: no cover
    HAVE_PYTHON_DOCX = False


# ---------------------------------------------------------------------------
# value extraction
# ---------------------------------------------------------------------------

# Anywhere in a criterion description, "Expected:" opens the value clause. Precedent for
# locating this exact label in this repo is rubric_schema_check.py's BARE_TIER_RE (a tier word
# immediately followed by "Expected:", anchored at the start of the description, used there only
# to detect the label's presence). This regex differs in scope on purpose: it looks for the
# label ANYWHERE in the text (most real criteria state the requirement first, then "Expected:"
# the value, per the calibration corpus), and it captures everything up to the next ".." --
# confirmed as this rubric-authoring convention's own sentence-boundary marker against 23,203
# real occurrences in the calibration corpus -- or the end of the description if no ".." follows.
EXPECTED_CLAUSE_RE = re.compile(
    r"Expected\s*:\s*(.*?)(?:\.\.|\Z)", re.IGNORECASE | re.DOTALL
)

# A 4-digit token that reads as a plausible calendar year. Excluded from bare_number extraction
# by default -- see Known limits and --include-years.
YEAR_RE = re.compile(r"^(19|20)\d{2}$")

# Value-token shapes, tried in this order at each position (first alternative that matches at a
# given starting character wins; alternatives are ordered so a currency/date/percent shape is
# never partially reinterpreted as a smaller bare-number match). Currency and comma-number use a
# proper thousands-group pattern (\d{1,3}(?:,\d{3})*) rather than a loose \d[\d,]* -- an earlier
# draft of this regex used the loose form and it captured a trailing stray comma or an unpaired
# closing parenthesis from surrounding prose (e.g. "$37,942, each" -> "$37,942," ; "(e.g.,
# $3,035,845)" -> "$3,035,845)" with no matching open paren). Confirmed and fixed during
# calibration against the real corpus.
VALUE_TOKEN_RE = re.compile(
    r"""
    (?P<currency>\$\(\d{1,3}(?:,\d{3})*(?:\.\d+)?\)|\$\d{1,3}(?:,\d{3})*(?:\.\d+)?)
  | (?P<percent>[-\u2212]?\d+(?:\.\d+)?%)
  | (?P<date_slash>\b\d{1,2}/\d{1,2}/\d{2,4}\b)
  | (?P<date_iso>\b\d{4}-\d{2}-\d{2}\b)
  | (?P<date_dmon>\b\d{1,2}-[A-Za-z]{3,9}-\d{4}\b)
  | (?P<date_mdy>\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b)
  | (?P<quoted>'[^']{4,80}'|"[^"]{4,80}")
  | (?P<comma_number>\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b)
  | (?P<decimal_number>\b\d+\.\d+\b)
  | (?P<bare_number>\b\d{4,}\b)
""",
    re.VERBOSE | re.IGNORECASE,
)

NUMERIC_KINDS = {"currency", "comma_number", "decimal_number", "bare_number"}


def sig_len(token: str) -> int:
    """Significant-character length: alphanumeric characters only, so punctuation/currency
    symbols/commas/quotes never count toward --min-chars."""
    return len(re.sub(r"[^A-Za-z0-9]", "", token))


def to_float(token: str):
    """Parse a currency/comma/decimal/bare-number token to a float. Accounting-negative
    ($(665,333)) is treated as negative. Returns None if nothing numeric survives stripping.
    """
    stripped = token.strip()
    is_negative = stripped.startswith("(") or stripped.startswith("$(")
    core = re.sub(r"[^\d.]", "", token)
    if not core or core == ".":
        return None
    try:
        value = float(core)
    except ValueError:
        return None
    return -value if is_negative else value


def extract_expected_values(
    description: str, min_chars: int = 4, exclude_years: bool = True
):
    """Every value-shaped token found in every "Expected: ..." clause of one criterion
    description. Returns a list of {"token", "kind", "numeric"} dicts (numeric is a float for
    the four NUMERIC_KINDS, else None). Never raises."""
    found = []
    for clause_match in EXPECTED_CLAUSE_RE.finditer(description or ""):
        clause = clause_match.group(1)
        for value_match in VALUE_TOKEN_RE.finditer(clause):
            token = value_match.group(0)
            kind = value_match.lastgroup
            if kind == "bare_number" and exclude_years and YEAR_RE.match(token):
                continue
            if sig_len(token) < min_chars:
                continue
            numeric = to_float(token) if kind in NUMERIC_KINDS else None
            found.append({"token": token, "kind": kind, "numeric": numeric})
    return found


# ---------------------------------------------------------------------------
# task/judge.toml discovery -- same pattern as this repo's other checks
# ---------------------------------------------------------------------------


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = ""):
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


def load_judge_values(task_dir: Path, min_chars: int = 4, exclude_years: bool = True):
    """Every extracted expected-value token across every tests/deliverables[_*]/judge.toml for
    this task, each carrying its own criterion name and judge.toml group for provenance. Also
    returns the list of parse errors encountered (never raises)."""
    values = []
    parse_errors = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return values, parse_errors

    judge_files = sorted(
        set(tests_dir.glob("deliverables/judge.toml"))
        | set(tests_dir.glob("deliverables_*/judge.toml"))
    )
    for jt in judge_files:
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
        except Exception as exc:
            parse_errors.append(f"{jt.relative_to(task_dir)}: {exc}")
            continue
        group = jt.parent.name
        for criterion in data.get("criterion", []):
            description = criterion.get("description") or ""
            name = criterion.get("name", "?")
            for value in extract_expected_values(
                description, min_chars=min_chars, exclude_years=exclude_years
            ):
                values.append({**value, "criterion": name, "judge_group": group})
    return values, parse_errors


# ---------------------------------------------------------------------------
# suspicious-filename gate (cheap, no files opened)
# ---------------------------------------------------------------------------

# Whole-path-segment tokens (split on any non-alphanumeric character, so this matches "key" in
# "answer_key.txt" but never in "keyword.txt" -- \b would fail on the former since underscore is
# a \w character and would falsely fire on the latter otherwise). Deliberately broad: this list
# alone never fails a task -- see the module docstring's calibration finding #4 for why the two
# real-corpus hits it produces ("Engineering_Interview_Rubric.docx", "cheatsheet" ->
# "Product_Knowledge_Cheatsheet.docx") are legitimate, unrelated business documents that a
# content-match gate correctly clears.
SUSPICIOUS_TOKENS = {
    "golden",
    "gold",
    "solution",
    "solutions",
    "answer",
    "answers",
    "answerkey",
    "key",
    "reference",
    "ref",
    "rubric",
    "judge",
    "grading",
    "grader",
    "oracle",
    "expected",
    "cheat",
    "cheatsheet",
}

SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".xlsx", ".xlsm", ".docx"}


def path_suspicious_tokens(rel_path: str):
    tokens = set(re.split(r"[^A-Za-z0-9]+", rel_path.lower()))
    return sorted(SUSPICIOUS_TOKENS & tokens)


def find_environment_files(task_dir: Path):
    env_dir = task_dir / "environment" / "initial_workspace"
    if not env_dir.is_dir():
        return []
    return sorted(
        p
        for p in env_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


# ---------------------------------------------------------------------------
# per-file content extraction
# ---------------------------------------------------------------------------


def read_docx_text(path: Path) -> str:
    """python-docx if available; else a zipfile + regex pull of every <w:t> text run out of
    word/document.xml -- the same "a .docx IS a zip archive" fact
    deliverable_integrity_check.py's check_docx() already relies on for integrity checking,
    reused here for text extraction instead."""
    if HAVE_PYTHON_DOCX:
        try:
            document = _python_docx.Document(str(path))
            parts = [p.text for p in document.paragraphs]
            for table in document.tables:
                for row in table.rows:
                    for cell in row.cells:
                        parts.append(cell.text)
            return "\n".join(parts)
        except Exception:
            pass  # fall through to the zipfile fallback
    with zipfile.ZipFile(path) as zf:
        if "word/document.xml" not in zf.namelist():
            return ""
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
        return " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))


def scan_environment_file(path: Path):
    """Returns (found_floats: set[float rounded to 2dp], text_blob: str, error: str|None).
    Never raises -- a file this can't open/parse reports an error string and empty content
    rather than crashing the task."""
    suffix = path.suffix.lower()
    floats = set()
    blob_parts = []
    try:
        if suffix in (".txt", ".md", ".csv", ".json"):
            text = path.read_text(encoding="utf-8", errors="replace")
            blob_parts.append(text)
            _collect_numeric_tokens(text, floats)
        elif suffix in (".xlsx", ".xlsm"):
            workbook = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
            for worksheet in workbook.worksheets:
                for row in worksheet.iter_rows():
                    for cell in row:
                        value = cell.value
                        if isinstance(value, bool):
                            continue
                        if isinstance(value, (int, float)):
                            floats.add(round(float(value), 2))
                        elif isinstance(value, str):
                            # Cheap pre-filter: skip the (usually large majority of) label-only
                            # string cells with no digit at all before paying for a regex scan.
                            if any(ch.isdigit() for ch in value):
                                blob_parts.append(value)
                                _collect_numeric_tokens(value, floats)
                            elif len(value) >= 4:
                                blob_parts.append(value)
            workbook.close()
        elif suffix == ".docx":
            text = read_docx_text(path)
            blob_parts.append(text)
            _collect_numeric_tokens(text, floats)
    except Exception as exc:  # never let one file's crash kill the whole task
        return floats, "\n".join(blob_parts), str(exc)
    return floats, "\n".join(blob_parts), None


def _collect_numeric_tokens(text: str, floats: set):
    for value_match in VALUE_TOKEN_RE.finditer(text):
        if value_match.lastgroup in NUMERIC_KINDS:
            parsed = to_float(value_match.group(0))
            if parsed is not None:
                floats.add(round(parsed, 2))


NUMERIC_TOLERANCE = 0.005


def match_value_in_file(value: dict, floats: set, text: str, text_lower: str):
    """Returns a match_type string ("numeric_equivalent" | "literal_substring") or None."""
    kind = value["kind"]
    if kind in NUMERIC_KINDS and value["numeric"] is not None:
        target = value["numeric"]
        if any(abs(target - f) < NUMERIC_TOLERANCE for f in floats):
            return "numeric_equivalent"
        if value["token"] in text:
            return "literal_substring"
        return None
    if kind == "quoted":
        inner = value["token"][1:-1].lower()
        return "literal_substring" if inner in text_lower else None
    # percent, date_*
    return "literal_substring" if value["token"].lower() in text_lower else None


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(
    task_dir: Path,
    min_chars: int = 4,
    exclude_years: bool = True,
    full_scan: bool = False,
    cooccurrence_threshold: int = 3,
):
    task_id = task_dir.name
    values, parse_errors = load_judge_values(
        task_dir, min_chars=min_chars, exclude_years=exclude_years
    )
    env_files = find_environment_files(task_dir)

    result = {
        "task_id": task_id,
        "n_expected_values": len(values),
        "n_environment_files": len(env_files),
        "parse_errors": parse_errors,
        "high_findings": [],
        "candidate_findings": [],
        "errors": [],
    }

    if not values:
        result["status"] = "clean"
        result["summary"] = {"n_high": 0, "n_candidate": 0}
        if not parse_errors and not (task_dir / "tests").is_dir():
            result["errors"].append(
                "no tests/ directory -- nothing for this check to verify"
            )
        return result

    suspicious_files = [
        (p, path_suspicious_tokens(str(p.relative_to(task_dir)).replace("\\", "/")))
        for p in env_files
    ]
    suspicious_files = [(p, toks) for p, toks in suspicious_files if toks]

    scan_targets = env_files if full_scan else [p for p, _ in suspicious_files]
    suspicious_set = {p for p, _ in suspicious_files}
    file_scans = {}
    for p in scan_targets:
        floats, blob, err = scan_environment_file(p)
        if err:
            result["errors"].append(
                f"{p.relative_to(task_dir)}: could not fully scan ({err})"
            )
        file_scans[p] = (floats, blob, blob.lower())

    for p, (floats, blob, blob_lower) in file_scans.items():
        rel = str(p.relative_to(task_dir)).replace("\\", "/")
        is_suspicious = p in suspicious_set
        matched_values = []
        for value in values:
            match_type = match_value_in_file(value, floats, blob, blob_lower)
            if match_type:
                matched_values.append({**value, "match_type": match_type})
        if not matched_values:
            continue
        if is_suspicious:
            for m in matched_values:
                result["high_findings"].append(
                    {
                        "confidence": "high",
                        "reason": "suspicious file path + literal/numeric value match",
                        "environment_file": rel,
                        "suspicious_path_tokens": path_suspicious_tokens(rel),
                        "value": m["token"],
                        "value_kind": m["kind"],
                        "match_type": m["match_type"],
                        "criterion": m["criterion"],
                        "judge_group": m["judge_group"],
                    }
                )
        elif full_scan and len(matched_values) >= cooccurrence_threshold:
            result["candidate_findings"].append(
                {
                    "confidence": "medium",
                    "reason": (
                        f"{len(matched_values)} distinct expected values from "
                        f"{matched_values[0]['judge_group']} co-occur in one ordinary "
                        "environment file -- per this script's own calibration finding, this "
                        "is common in legitimate approved-facts source documents and is NOT "
                        "itself evidence of a leak; listed for human review only"
                    ),
                    "environment_file": rel,
                    "n_cooccurring_values": len(matched_values),
                    "values": sorted({m["token"] for m in matched_values}),
                }
            )

    result["status"] = (
        "flagged"
        if result["high_findings"]
        else "candidate" if result["candidate_findings"] else "clean"
    )
    result["summary"] = {
        "n_high": len(result["high_findings"]),
        "n_candidate": len(result["candidate_findings"]),
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
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
        "this must not silently assume a project-specific path)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix as tasks",
    )
    ap.add_argument(
        "--min-chars",
        type=int,
        default=4,
        help="significant-character floor for an extracted value to be worth checking "
        "(default 4; alphanumeric characters only, so '$500' counts as 3 and is dropped)",
    )
    ap.add_argument(
        "--include-years",
        action="store_true",
        help="do NOT exclude plausible calendar-year (1900-2099) bare numbers from extraction "
        "(default: excluded -- see Known limits in this script's docstring)",
    )
    ap.add_argument(
        "--full-scan",
        action="store_true",
        help="also scan every environment file (not just suspicious-named ones) and report the "
        "co-occurrence diagnostic (slow: opens every spreadsheet in every task; never gates "
        "pass/fail on its own -- see this script's docstring)",
    )
    ap.add_argument(
        "--cooccurrence-threshold",
        type=int,
        default=3,
        help="only with --full-scan: minimum distinct co-occurring values before a (judge file, "
        "environment file) pair is listed as a candidate row (default 3)",
    )
    ap.add_argument(
        "--out", type=Path, default=None, help="write the aggregate JSON report here"
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error(
            "--root is required (point it at the directory containing your task folders)"
        )
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")
    if not args.root.is_dir():
        sys.stderr.write(f"not a directory: {args.root}\n")
        return 2

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 2

    print(
        "answer_key_content_leak_check.py: LOW-CONFIDENCE CANDIDATE-FOR-REVIEW tool, not a "
        "pass/fail gate -- see the module docstring's calibration section before trusting a "
        "'clean' result or acting on a 'flagged' one without reading the finding.",
        file=sys.stderr,
    )

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(
                task_dir,
                min_chars=args.min_chars,
                exclude_years=not args.include_years,
                full_scan=args.full_scan,
                cooccurrence_threshold=args.cooccurrence_threshold,
            )
        except Exception as exc:  # never let one task's crash kill the whole batch
            r = {
                "task_id": task_dir.name,
                "status": "error",
                "errors": [f"unhandled exception analyzing this task: {exc}"],
                "high_findings": [],
                "candidate_findings": [],
                "summary": {"n_high": 0, "n_candidate": 0},
            }
        results.append(r)
        print(
            f"    -> {r['status']}  ({r['summary']['n_high']} high, "
            f"{r['summary']['n_candidate']} candidate, {len(r.get('errors', []))} errors)",
            file=sys.stderr,
        )

    n_flagged = sum(1 for r in results if r["status"] == "flagged")
    n_candidate = sum(1 for r in results if r["status"] == "candidate")
    n_clean = sum(1 for r in results if r["status"] == "clean")
    n_error = sum(1 for r in results if r["status"] == "error")

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "options": {
            "min_chars": args.min_chars,
            "exclude_years": not args.include_years,
            "full_scan": args.full_scan,
            "cooccurrence_threshold": args.cooccurrence_threshold,
        },
        "n_tasks": len(results),
        "n_flagged": n_flagged,
        "n_candidate": n_candidate,
        "n_clean": n_clean,
        "n_error": n_error,
        "results": results,
    }

    print(
        f"\n{n_clean}/{len(results)} clean, {n_candidate} candidate (human review, not gated), "
        f"{n_flagged} FLAGGED (suspicious file + verbatim value match), {n_error} errored"
    )
    for r in results:
        if r["status"] == "clean":
            continue
        print(f"  {r['task_id']}: {r['status']}")
        for f in r.get("high_findings", []):
            print(
                f"      HIGH: '{f['value']}' ({f['value_kind']}, {f['criterion']}) found in "
                f"{f['environment_file']} [{f['match_type']}, path tokens: "
                f"{f['suspicious_path_tokens']}]"
            )
        for c in r.get("candidate_findings", []):
            print(
                f"      candidate: {c['n_cooccurring_values']} values co-occur in "
                f"{c['environment_file']} -- {c['values'][:5]}"
            )
        for e in r.get("errors", []):
            print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")

    return 1 if (n_flagged or n_candidate) else 0


if __name__ == "__main__":
    raise SystemExit(main())
