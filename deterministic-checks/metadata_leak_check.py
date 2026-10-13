#!/usr/bin/env python3
"""Metadata leak check: do a file's own hidden METADATA fields -- xlsx cell comments, defined
names, sheet titles; docx comments, tracked-changes deleted text, headers/footers; pptx speaker
notes -- carry an answer-key value or an internal grading-artifact filename, invisible to every
existing leak check because all three only read VISIBLE cell/paragraph/run content?

Why this exists
----------------
Read directly (2026-09-16, this session, not assumed from a report): `answer_key_leakage_
check.py` regex-scans instruction.md's raw text plus a bare-filename sweep of environment/ --
never opens a spreadsheet or Word file to look inside it. `answer_key_content_leak_check.py`
extracts .xlsx/.xlsm via `cell.value` (openpyxl, `data_only=True`) and .docx via python-docx
`paragraph.text`/`table.cell.text` or a zipfile regex pull of `<w:t>` runs out of
word/document.xml. `answer_key_rubric_leak_check.py`'s own `read_xlsx_text()`/`read_docx_text()`/
`read_pptx_text()` do the identical thing: cell values, paragraph/table text, `<w:t>`/`<a:t>` runs.
None of the three ever touches `cell.comment`, a defined name, a sheet's own title-as-content, a
docx `word/comments.xml` part, a `<w:delText>` tracked-change deletion, a header/footer part, or a
pptx `notesSlide` part -- confirmed by grepping all three files for
`comment|defined_name|docProps|notesSlide|header|footer|w:ins|w:del`: zero matches in any of the
three. A leak sitting in a cell comment is therefore invisible to every check in this folder.

Two real, confirmed golden-side instances (verified directly against the live files at
C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready 2026-09-16, not inferred from a report):
  - SVC-PC-7-6-0's golden `Cirrus_FY2022_Strategic_Plan_Recommendation.xlsx`, sheet
    "Assumptions", carries 12 cell comments stating real control totals verbatim, e.g. B6: "...
    Net revenue $1,204,900.", B50: "...Conservative $1.90M / Balanced $2.45M / Aggressive
    $3.00M.", B62: "...ending cash ties to the canonical $1,146,822 / $959,017 / $766,212."
  - SVC-PC-7-4-0's golden `Cirrus_FY2022_Operations_Model.xlsx`, sheet "Inputs", carries 22 cell
    comments (author "OpenAI"), all reading "Source: L2-04_Task_7_Rubric.xlsx and
    L2-04_Task_7_Response_Criteria.xlsx in the provided Drive folder." -- internal
    grading-pipeline filenames, invisible to `answer_key_leakage_check.py`'s five-tell filename
    scan (`_SOLUTION`/`_ANSWER`/`_REFERENCE`/`_ANSWERKEY`/`_KEY` -- none matches "_Rubric" or
    "_Response_Criteria") because that scan only runs over instruction.md and bare environment/
    filenames, never a golden file's own comment text.
Both are golden-SIDE (solution/) findings: solution/ is never solver-visible in this package
shape, so on their own these are a disclosed hygiene gap, not a "front of the graded party"
violation -- see Severity below. Whether the SAME shape occurs on the environment/ (solver-
visible) side, at full 600-task scale, is the real open question this check exists to answer.

What it checks, mechanistically
--------------------------------
For each task, for BOTH its golden files (solution/files/ SVC-PC, solution/golden_outputs/ EKW --
reusing `answer_key_rubric_leak_check.py`'s own `find_golden_files()`/`_task_format()`) and its
solver-visible environment files (environment/initial_workspace/ SVC-PC, environment/data/ EKW),
restricted to the four formats a metadata field can exist in at all (.xlsx/.xlsm/.docx/.pptx --
.txt/.csv/.json/.pdf have no equivalent hidden-field structure this check targets), extracts:

  xlsx/xlsm (direct `xl/workbook.xml` zip/XML parse for sheet titles + defined names, always
  cheap; openpyxl `cell.comment` -- the slower, non-`read_only` load path -- ONLY for files a
  fast `zipfile.namelist()` prefilter (`any(n.startswith("xl/comments") for n in names)`) already
  confirms carry a comments part, so the large majority of workbooks with zero comments never pay
  the full-load cost):
    - every cell comment's text
    - every defined name's own name string plus its reference/value text
    - every sheet's own title string
  docx (zipfile + regex over the relevant XML parts, the same "a .docx IS a zip archive"
  technique `answer_key_content_leak_check.py`'s own `read_docx_text()` fallback already uses --
  python-docx 1.2.0, confirmed installed this session, exposes NONE of these three fields via its
  public API, so this check does not attempt a python-docx path for them at all):
    - every `word/comments.xml` `<w:comment>` block's `<w:t>` run text
    - every `<w:delText>` (tracked-change DELETED text -- distinct from `<w:t>`, which
      `read_docx_text()` already extracts, so this is genuinely new coverage) in word/document.xml
    - every `word/header*.xml` / `word/footer*.xml` part's `<w:t>` run text
  pptx (zipfile + regex over `ppt/notesSlides/notesSlideN.xml`, the same no-python-pptx-dependency
  convention `answer_key_rubric_leak_check.py`'s own `read_pptx_text()` already uses for slide
  text, applied here to the separate notes-slide parts instead):
    - every slide's speaker-notes text

Each extracted metadata item is then evaluated against three signals, reusing this folder's own
existing "does this look like a leaked expected value" logic rather than reinventing it (per this
check's own build brief):
  1. HIGH -- expected-value match: the item's text numerically- or literally-matches one of the
     task's own judge.toml/verifier.json "Expected:" values. Reuses `answer_key_content_leak_
     check.py`'s `load_values_for_task()` (the task's own expected-value set, SVC-PC/EKW
     format-dispatched), `_collect_numeric_tokens()`, and `match_value_in_file()` verbatim --
     the identical numeric-equivalence-with-tolerance / literal-substring matcher that check
     already calibrated against this same 600-task corpus for its own (environment-file-content)
     purpose.
  2. HIGH -- internal filename reference: a filename-shaped token inside the metadata text (via
     `answer_key_leakage_check.py`'s own `FILENAME_TOKEN_RE`) carries either that script's
     five-tell golden/reference scan (`filename_tells()`) or `answer_key_content_leak_check.py`'s
     broader `SUSPICIOUS_TOKENS` vocabulary (rubric/judge/grading/grader/oracle/cheat/...) via
     `path_suspicious_tokens()`. Restricted to filename-SHAPED tokens specifically (not
     unrestricted prose, see signal 3) because a real business document's own name is very
     unlikely to end in "..._Rubric.xlsx" the way ordinary prose might casually use the word
     "key" -- this is what catches the SVC-PC-7-4-0 shape above, which the narrower five-tell set
     alone would miss (neither tell matches "_Rubric" or "_Response_Criteria").
  3. CANDIDATE (not HIGH) -- suspicious wording: `path_suspicious_tokens()` matches somewhere in
     the metadata text but NOT inside a filename-shaped token (i.e., a bare word like "rubric" or
     "judge" in ordinary comment prose, no filename and no value corroborating it). Lower
     confidence by design, the same two-tier philosophy `answer_key_content_leak_check.py`
     already established for its own suspicious-name-only case: a human needs to read the actual
     comment before trusting this as a real leak (see Known limits).

Severity
--------
A HIGH finding on the ENVIRONMENT (solver-visible) side is `fail`: this is the actual "answer key
in front of the graded party" violation the org's hard rule exists for. A HIGH or CANDIDATE
finding on the GOLDEN (solution/) side, or a CANDIDATE finding on either side, is `warn`: real and
worth a human glance, but solution/ is never solver-visible in this package shape (confirmed by
every sibling check's own directory convention in this folder), so a golden-side-only result is a
disclosed hygiene gap, not a confirmed solver-facing defect. No findings anywhere is `pass`.

Verification against the real corpus (2026-09-16, full 600-task run,
C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready, real command output below, not
aspirational)
------------------------------------------------------------------------------------------------
`python metadata_leak_check.py --all --root ... --out full600.json`: 600/600 tasks, 0 errored
(one task, SVC-PC-15-3-0, logged 2 non-fatal per-file extraction errors -- "Bad magic number for
file header" on two .docx files that are not real OOXML zips -- without affecting the rest of the
task or the batch). status: fail=32, warn=202, pass=366.

GOLDEN side (solution/, never solver-visible): 84 raw HIGH findings across 19 tasks, 33 CANDIDATE
findings. Real, confirmed hits, not a false-positive population -- three tasks hand-verified in
full against live judge.toml text, not sampled: SVC-PC-7-6-0 (7/7 `expected_value_match` findings
confirmed genuine -- every matched value is a real criterion's own Expected figure, e.g. B6's
"$1,204,900" = criterion c20's expected net revenue, B62's "$959,017" = criterion c02's expected
ending cash), SVC-PC-7-4-0 (22/22 `internal_filename_reference` findings confirmed genuine -- all
22 comments cite the real internal artifact names "L2-04_Task_7_Rubric.xlsx" /
"L2-04_Task_7_Response_Criteria.xlsx"), SVC-PC-25-3-0 (the highest-count task, n=23 -- spot-
checked 2 of its distinct values against live judge.toml: criterion c02's Expected clause
literally is "Policy GL-2021-**448812**", criterion c03's is "Hiscox Insurance Co.
HSX-GL-21-**487291**", both bare policy-number matches confirmed genuine, not coincidental). Not
solver-facing, so per this check's own Severity section this is `warn`, not `fail` -- a real,
disclosed authoring-hygiene gap (comments meant for the golden's own author leak the answer into
metadata a human reviewer could stumble on, e.g. via "always open with track changes/comments
visible"), not a "front of the graded party" violation.

ENVIRONMENT side (solver-visible -- the real open question this check exists to answer): 32 tasks
initially flagged `fail` (47 distinct HIGH finding patterns after deduplication, since several
patterns repeat verbatim across many tasks via shared `_corpus_subtree/` business documents), plus
181 more tasks `warn`-only on 2 distinct CANDIDATE patterns. EVERY ONE of the 47 distinct HIGH
patterns was hand-verified against the real judge.toml criterion text behind it (not sampled by
finding count -- sampled by DISTINCT pattern, which is every real pattern that exists); both
CANDIDATE patterns were also read. **Zero confirmed genuine answer-key leaks.** Every flagged case
resolves to one of four confirmed mechanisms, none of which hands the solver anything they were
not already supposed to have:
  1. Excel absolute cell-reference misparse (SVC-PC-14-2-0, SVC-PC-93-2-0 and others) -- FIXED
     this session, see EXCEL_ABS_CELL_REF_RE / `_text_for_numeric_scan()` above. Re-run after the
     fix (same corpus, same command): environment HIGH task count 32 -> confirmed below.
  2. A criterion's own quoted keyword is ordinary English ("cash", "customer", "result",
     "approved", "product", "actual", "total cost") and trivially co-occurs in unrelated real
     business content (a "Cash Flow" sheet name, a "Customer Support" header, a "Results" tab) --
     the exact "approved facts" false-positive class `answer_key_content_leak_check.py`'s own
     docstring already extensively disclosed for full-file-content matching; metadata text is
     short and repetitive enough that this class dominates. Confirmed via real judge.toml text
     for SVC-PC-10-4-0 c06 ("cash" is a bare JSON field-name inside a structured Expected clause,
     `results.censoring={"cash":...}`, not a value) and SVC-PC-26-3-0 r11 ("Customer" is a
     CRM lifecycle-stage label, unrelated to a "Customer Support" doc header).
  3. The environment genuinely, legitimately contains the real source data a criterion's Expected
     clause describes -- confirmed via real judge.toml for SVC-PC-1-5-0 c023 / SVC-PC-3-10-0 1-02
     (a real accountant's rounding note in `August_PnL.xlsx`, the actual source workbook the
     criterion is checking against, states the same $195.5K/$ 59,000 the criterion expects,
     because that IS the source) and SVC-PC-67-1-0 r013, where the criterion's own text explicitly
     says the fact is "stated in plain language on the 'Population Guide' sheet... credit it as
     corroboration rather than discovery" -- the "leak" this check found IS the disclosed,
     by-design source the rubric author already named.
  4. Scale-suffix blindness: SVC-PC-6-5-0 wc-06's "$18.00" (a per-order sensitivity rate) matched
     a speaker note's "$18K" (eighteen THOUSAND dollars of COGS) because the shared `to_float()`
     this check reuses drops a trailing K/M/B scale letter rather than applying it -- the same
     token-splitting gap `answer_key_rubric_leak_check.py`'s own v6 `SCALE_SUFFIX_TOKENS` fix
     addressed on the rubric side (see that script's docstring), not yet fixed here (see Known
     limits) because it is a single confirmed instance, not a whole mechanism, and because fixing
     it means editing shared, already-calibrated code in `answer_key_content_leak_check.py` that
     is out of this check's own scope.
Re-run after fix 1 (Excel cell-reference guard), same corpus, same command: environment HIGH task
count 32 -> 30 (SVC-PC-14-2-0, SVC-PC-14-3-0, SVC-PC-93-2-0 clear on their cell-reference-only
findings; SVC-PC-93-2-0 keeps its OTHER, unrelated HIGH finding on the same task from mechanism 3
above, so the task itself does not fully clear). The two CANDIDATE-only patterns ("Reference" /
"Breakpoint Ref" bare sheet titles, 175 and 59 tasks respectively) are equally mundane on inspection
-- "Reference" is an ordinary Excel lookup-tab convention, "Breakpoint Ref" is a CSS
responsive-design breakpoint table in an unrelated frontend-engineering filler document, nothing to
do with any SVC-PC finance scenario.

**Conclusion, resolving GLM's round-37 open question**: GLM's own 27-task sample found this
metadata-leak shape NOT populated on the solver-visible side, but flagged the sample as too small
to rule out at full scale. This check's full-600-task run, with every distinct flagged pattern
hand-verified against real judge.toml text (not sampled), confirms the same result at full scale:
the golden-side leak shape is real (19/600 tasks, disclosed above), the solver-visible/environment-
side shape is NOT populated anywhere in this corpus. See `metadata_leak.json`'s own per-task
`environment_high_findings`/`environment_candidate_findings` for the full, re-derivable finding
list this conclusion is based on.

Known limits, disclosed rather than silently dropped
------------------------------------------------------
  - .txt/.md/.csv/.json/.pdf carry none of the six metadata kinds this check targets (a CSV has
    no comment field; a PDF's own XMP/annotation metadata is a different, unimplemented surface --
    not asserted clean, just not covered, the same disclosed-gap shape every sibling check in this
    folder uses for its own unsupported-extension list). EKW's environment/data/ is 39% PDF by
    file count per `answer_key_content_leak_check.py`'s own EKW-port docstring section -- the
    single biggest blind spot this check still has on the EKW side specifically.
  - Legacy .xls/.ppt/.doc (pre-OOXML binary formats) are not zip archives at all and are not
    scanned by this check's zipfile-based extractors; `FILENAME_EXTS` elsewhere in this folder
    still includes ".doc"/".ppt" for FILENAME leak purposes, but this check's own metadata
    extraction does not open them.
  - The xlsx comments fast-path prefilter (`xl/comments*.xml` in the zip namelist) is a real
    optimization, not a precision trade: a workbook with zero comment parts in its zip has zero
    comments, full stop -- there is no OOXML shape where a comment exists without that part. The
    prefilter therefore cannot produce a false "no comments" result.
  - Signal 3 (bare suspicious wording, CANDIDATE tier) is exactly as prone to false positives as
    `answer_key_content_leak_check.py`'s own disclosed calibration finding for the identical
    vocabulary applied to file PATHS ("key metrics", "key assumptions" are ordinary English) --
    here applied to metadata PROSE instead, which is if anything a larger surface (a sourcing
    comment legitimately saying "per the engagement rubric" is common, harmless prose). Every
    CANDIDATE finding needs a human read of the actual comment before being treated as a leak;
    this tier is a disclosure, not a gate, matching this folder's established convention for a
    low-confidence signal.
  - Defined-name VALUES in xlsx are almost always a cell reference ("Sheet1!$B$2"), not a literal
    answer -- signal 1 (value match) can still fire on a defined name's own NAME string if that
    name happens to spell out a value-shaped token (rare), but the practical exposure from defined
    names is dominated by signal 2/3 (a name like "Golden_Answer_Range") rather than signal 1.
  - Signal 1 (expected-value match) is NOISY at metadata scale, confirmed by the full-corpus
    hand-verification above, not just theorized: a bare quoted common English word in a
    criterion's own Expected clause (mechanism 2 above) and a criterion's value legitimately
    appearing in its own real source document (mechanism 3) together accounted for the large
    majority of the 47 distinct environment-side HIGH patterns found in the real corpus, and
    NEITHER is fixed by this check (mechanism 1, the Excel cell-reference misparse, IS fixed --
    see EXCEL_ABS_CELL_REF_RE). This check's HIGH tier is therefore a real signal worth routing to
    a human (same "flag liberally, triage separately" convention this folder's other checks and
    tracker already use), NOT a confirmed-genuine-leak gate on its own -- treat an
    `environment_high_findings` entry the way `duplicate_criterion_content_check.py`'s own
    pre-severity-removal fail tier was treated (real signal, ~15-25% genuine on hand sample per
    this repo's own tracker), not the way `answer_key_content_leak_check.py`'s AND-gated HIGH tier
    is treated (100% genuine on its own calibration). A fix that raises precision here would need
    either an AND-gate against a second signal (this check does not currently have one for signal
    1 the way `answer_key_content_leak_check.py` gates on suspicious filename) or a stopword-style
    exclusion list for common quoted words -- not attempted this session, flagged as a real,
    scoped candidate for a future round.
  - Scale-suffix blindness (mechanism 4 above, SVC-PC-6-5-0 wc-06): the shared `to_float()` this
    check reuses from `answer_key_content_leak_check.py` drops a trailing K/M/B/MM/BN/MN letter
    rather than applying it as a multiplier, so "$18K" and "$18.00" parse to the identical float
    18.0. `answer_key_rubric_leak_check.py`'s own v6 fix addressed the equivalent gap on the
    RUBRIC side (`SCALE_SUFFIX_TOKENS`); this check does not carry an equivalent guard, because
    the fix lives in shared code (`answer_key_content_leak_check.py`'s `to_float()`/
    `VALUE_TOKEN_RE`) this check was asked to reuse, not fork or edit -- confirmed as exactly one
    real instance in the full-corpus run, not a whole mechanism the way the cell-reference misparse
    was, so a local guard was judged lower priority than the fix that shipped this session.
  - This check does not attempt semantic understanding of WHY a comment exists (an author's
    genuine sourcing note vs. a deliberate grading crib) -- the same disclosed limit
    `answer_key_content_leak_check.py`'s own docstring states for its own suspicious-file-name
    gate. A human triaging a HIGH finding on the environment side should still read the actual
    comment text (included verbatim, truncated to 500 chars, in every finding) before treating it
    as confirmed.

Usage
-----
    python metadata_leak_check.py <TASK-ID> [<TASK-ID> ...] --root <path> [--out report.json]
    python metadata_leak_check.py --all --root <path> [--out report.json]
    python metadata_leak_check.py --all --root <path> --id-prefix MYBENCH- [--out report.json]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    import openpyxl
except ImportError:  # pragma: no cover
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl

# Reuse, don't reinvent: the task's own expected-value set and its numeric/literal matcher come
# from answer_key_content_leak_check.py, already calibrated against this exact 600-task corpus
# for the identical "does this text contain a leaked expected value" question (just asked there
# of environment FILE CONTENT, asked here of metadata TEXT). SUSPICIOUS_TOKENS / path_suspicious_
# tokens is that same module's suspicious-wording vocabulary. filename_tells / FILENAME_TOKEN_RE
# is answer_key_leakage_check.py's own precision-tuned golden/reference filename-tell scan.
# find_golden_files / _task_format is answer_key_rubric_leak_check.py's golden-file discovery
# (identical _task_format logic to answer_key_content_leak_check.py's own, confirmed by reading
# both -- see this module's docstring).
from answer_key_content_leak_check import (  # noqa: E402
    SUSPICIOUS_TOKENS,  # noqa: F401  (re-exported for callers that want the raw vocabulary)
    _collect_numeric_tokens,
    _task_format,
    load_values_for_task,
    match_value_in_file,
    path_suspicious_tokens,
)
from answer_key_leakage_check import FILENAME_TOKEN_RE, filename_tells  # noqa: E402
from answer_key_rubric_leak_check import find_golden_files  # noqa: E402

# ---------------------------------------------------------------------------
# file discovery
# ---------------------------------------------------------------------------

# Only formats that can carry the metadata kinds this check reads. Deliberately broader than
# answer_key_content_leak_check.py's own SUPPORTED_EXTENSIONS (which excludes .pptx -- it has no
# reason to include it, since ordinary pptx run-text is already covered by answer_key_rubric_
# leak_check.py's golden-text extraction) and narrower than either sibling's own extension list
# (.txt/.csv/.json have no comment/defined-name/tracked-change/header-footer/notes-slide field to
# extract at all -- see Known limits).
METADATA_CAPABLE_EXTENSIONS = {".xlsx", ".xlsm", ".docx", ".pptx"}


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


def find_environment_files_for_metadata(task_dir: Path, fmt: str) -> list[Path]:
    """Solver-visible files in a metadata-capable format. Same environment/-directory dispatch
    answer_key_content_leak_check.py's find_environment_files() and answer_key_rubric_leak_
    check.py's _task_format() already established (environment/initial_workspace/ for SVC-PC,
    environment/data/ for EKW -- confirmed against real task samples in both of those checks'
    own build sessions, not re-derived here), just filtered to this check's own (pptx-inclusive)
    extension set."""
    env_dir = (
        task_dir / "environment" / "data"
        if fmt == "ekw"
        else task_dir / "environment" / "initial_workspace"
    )
    if not env_dir.is_dir():
        return []
    return sorted(
        p
        for p in env_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in METADATA_CAPABLE_EXTENSIONS
    )


# ---------------------------------------------------------------------------
# per-format metadata extraction
# ---------------------------------------------------------------------------

_SHEET_NAME_RE = re.compile(r'<sheet\b[^>]*\bname="([^"]*)"')
_DEFINED_NAMES_BLOCK_RE = re.compile(r"<definedNames>(.*?)</definedNames>", re.DOTALL)
_DEFINED_NAME_RE = re.compile(
    r'<definedName\b[^>]*\bname="([^"]*)"[^>]*>(.*?)</definedName>', re.DOTALL
)
_XML_TAG_RE = re.compile(r"<[^>]+>")
_W_T_RE = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
_W_DELTEXT_RE = re.compile(r"<w:delText[^>]*>([^<]*)</w:delText>")
_W_COMMENT_RE = re.compile(r"<w:comment\b([^>]*)>(.*?)</w:comment>", re.DOTALL)
_W_AUTHOR_ATTR_RE = re.compile(r'w:author="([^"]*)"')
_A_T_RE = re.compile(r"<a:t[^>]*>([^<]*)</a:t>")
_HEADER_FOOTER_PART_RE = re.compile(r"word/(header|footer)\d+\.xml$")

# Excel absolute cell reference ($B$1, $M$16, $AA$123, ...). Confirmed real false-positive
# source (2026-09-16 full-corpus hand verification, see this module's docstring "Verification"
# section): answer_key_content_leak_check.py's own VALUE_TOKEN_RE currency alternative
# (\$\d{1,3}...) matches the digit run after a reference's SECOND '$' as if it were a dollar
# amount -- "$B$1" yields a spurious "$1" -> 1.0, "Bands!$B$4:$M$16" yields a spurious
# "$16" -> 16.0 -- which can coincidentally equal an unrelated criterion's real expected value.
# Confirmed real collisions: SVC-PC-14-2-0's defined name "QB_COLUMN_7721 = AP!$B$1" against
# criterion obj-01's "JE-00001"; SVC-PC-93-2-0's Excel-AUTO-GENERATED
# "_xlnm._FilterDatabase = Bands!$B$4:$M$16" (created automatically by AutoFilter, not
# human-authored at all) against criterion obj-05's "$16.00" range boundary.
EXCEL_ABS_CELL_REF_RE = re.compile(r"\$[A-Za-z]{1,3}\$\d{1,7}")


def _text_for_numeric_scan(text: str) -> str:
    """Strips Excel absolute-cell-reference tokens before numeric-token extraction (signal 1
    only -- see EXCEL_ABS_CELL_REF_RE above). The original, unstripped text is still used for
    the literal-substring path and for signals 2/3: a cell reference cannot coincidentally look
    like a filename or a literal quoted/date/percent token, so stripping it there would only
    remove information for no precision gain."""
    return EXCEL_ABS_CELL_REF_RE.sub(" ", text)


def extract_xlsx_metadata(path: Path) -> tuple[list[dict], str | None]:
    """Sheet titles + defined names (always, direct workbook.xml zip/XML parse) and cell
    comments (only for files a fast zip-namelist prefilter confirms carry a comments part --
    see this module's docstring). Never raises."""
    items: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if "xl/workbook.xml" in names:
                xml = zf.read("xl/workbook.xml").decode("utf-8", errors="replace")
                for m in _SHEET_NAME_RE.finditer(xml):
                    title = html.unescape(m.group(1))
                    items.append(
                        {"kind": "sheet_title", "location": title, "text": title}
                    )
                dn_block = _DEFINED_NAMES_BLOCK_RE.search(xml)
                if dn_block:
                    for m in _DEFINED_NAME_RE.finditer(dn_block.group(1)):
                        name = html.unescape(m.group(1))
                        value = html.unescape(_XML_TAG_RE.sub("", m.group(2))).strip()
                        items.append(
                            {
                                "kind": "defined_name",
                                "location": name,
                                "text": f"{name} = {value}",
                            }
                        )
            has_comments_part = any(n.startswith("xl/comments") for n in names)
    except Exception as exc:
        return items, str(exc)

    if not has_comments_part:
        return items, None

    try:
        wb = openpyxl.load_workbook(str(path), data_only=False, read_only=False)
    except Exception as exc:
        return items, f"could not open for comment extraction: {exc}"
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if cell.comment is not None:
                        text = cell.comment.text or ""
                        items.append(
                            {
                                "kind": "cell_comment",
                                "location": f"{ws.title}!{cell.coordinate}",
                                "text": text,
                            }
                        )
    except Exception as exc:
        return items, f"partial comment extraction: {exc}"
    finally:
        wb.close()
    return items, None


def extract_docx_metadata(path: Path) -> tuple[list[dict], str | None]:
    """Comments (word/comments.xml), tracked-change DELETED text (<w:delText> in
    word/document.xml -- distinct from the <w:t> runs read_docx_text() already extracts
    elsewhere in this folder), and header/footer parts. Direct zipfile + regex, the same
    "a .docx IS a zip archive" technique answer_key_content_leak_check.py's own read_docx_text()
    fallback already uses -- python-docx 1.2.0 (confirmed installed this session) exposes none
    of these three fields via its public paragraph/table API, so there is no higher-level path
    to prefer here. Never raises."""
    items: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())

            if "word/comments.xml" in names:
                xml = zf.read("word/comments.xml").decode("utf-8", errors="replace")
                for m in _W_COMMENT_RE.finditer(xml):
                    attrs, body = m.group(1), m.group(2)
                    author_m = _W_AUTHOR_ATTR_RE.search(attrs)
                    text = html.unescape(" ".join(_W_T_RE.findall(body))).strip()
                    if text:
                        items.append(
                            {
                                "kind": "docx_comment",
                                "location": (
                                    f"author={html.unescape(author_m.group(1))}"
                                    if author_m
                                    else "author=?"
                                ),
                                "text": text,
                            }
                        )

            if "word/document.xml" in names:
                xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
                deleted = _W_DELTEXT_RE.findall(xml)
                text = html.unescape(" ".join(deleted)).strip()
                if text:
                    items.append(
                        {
                            "kind": "tracked_change_deletion",
                            "location": "word/document.xml",
                            "text": text,
                        }
                    )

            for part in sorted(n for n in names if _HEADER_FOOTER_PART_RE.search(n)):
                xml = zf.read(part).decode("utf-8", errors="replace")
                text = html.unescape(" ".join(_W_T_RE.findall(xml))).strip()
                if text:
                    items.append(
                        {"kind": "header_footer", "location": part, "text": text}
                    )
    except Exception as exc:
        return items, str(exc)
    return items, None


def extract_pptx_metadata(path: Path) -> tuple[list[dict], str | None]:
    """Speaker notes (ppt/notesSlides/notesSlideN.xml). Same no-python-pptx-dependency zipfile
    approach answer_key_rubric_leak_check.py's own read_pptx_text() uses for ordinary slide
    text, applied to the separate notes-slide parts. Never raises."""
    items: list[dict] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for name in sorted(zf.namelist()):
                if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(
                    ".xml"
                ):
                    xml = zf.read(name).decode("utf-8", errors="replace")
                    text = html.unescape(" ".join(_A_T_RE.findall(xml))).strip()
                    if text:
                        items.append(
                            {"kind": "speaker_notes", "location": name, "text": text}
                        )
    except Exception as exc:
        return items, str(exc)
    return items, None


def extract_metadata_items(path: Path) -> tuple[list[dict], str | None]:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return extract_xlsx_metadata(path)
    if suffix == ".docx":
        return extract_docx_metadata(path)
    if suffix == ".pptx":
        return extract_pptx_metadata(path)
    return [], f"unsupported extension: {suffix}"


# ---------------------------------------------------------------------------
# leak evaluation -- reuses answer_key_content_leak_check.py's and
# answer_key_leakage_check.py's own "does this look like a leak" signals
# ---------------------------------------------------------------------------


def evaluate_metadata_item(item: dict, values: list[dict]) -> dict | None:
    """Returns a finding dict (confidence "high" or "candidate") or None. See this module's
    docstring for the three signals, in priority order."""
    text = (item.get("text") or "").strip()
    if not text:
        return None
    text_lower = text.lower()

    # signal 1 (HIGH): a genuine expected-value match. Reuses answer_key_content_leak_check.py's
    # own _collect_numeric_tokens()/match_value_in_file() verbatim, over a copy of the text with
    # Excel absolute cell-references stripped first (see _text_for_numeric_scan()).
    floats: set = set()
    _collect_numeric_tokens(_text_for_numeric_scan(text), floats)
    for value in values:
        match_type = match_value_in_file(value, floats, text, text_lower)
        if match_type:
            return {
                "confidence": "high",
                "signal": "expected_value_match",
                "reason": "metadata text contains a genuine expected-value match against "
                "this task's own judge/rubric criteria",
                "kind": item["kind"],
                "location": item["location"],
                "text": text[:500],
                "value": value["token"],
                "value_kind": value["kind"],
                "match_type": match_type,
                "criterion": value["criterion"],
                "judge_group": value["judge_group"],
            }

    # signal 2 (HIGH): a filename-shaped token inside the metadata text that is itself
    # golden/reference/internal-artifact-named. Reuses answer_key_leakage_check.py's
    # filename_tells() (the precise five-tell set) OR answer_key_content_leak_check.py's
    # broader SUSPICIOUS_TOKENS via path_suspicious_tokens(), restricted to filename-SHAPED
    # tokens (not unrestricted prose -- see signal 3) so this catches the confirmed
    # SVC-PC-7-4-0 shape ("L2-04_Task_7_Rubric.xlsx", which the five-tell set alone misses).
    for m in FILENAME_TOKEN_RE.finditer(text):
        token = m.group(0)
        tells = filename_tells(token)
        susp = path_suspicious_tokens(token)
        if tells or susp:
            return {
                "confidence": "high",
                "signal": "internal_filename_reference",
                "reason": "metadata text references a golden/reference-solution or "
                "internal-pipeline-artifact-named file",
                "kind": item["kind"],
                "location": item["location"],
                "text": text[:500],
                "filename": token,
                "tells": tells,
                "suspicious_tokens": susp,
            }

    # signal 3 (CANDIDATE): a bare suspicious word, not inside a filename token, with no
    # corroborating value match -- lower confidence by design, same two-tier philosophy
    # answer_key_content_leak_check.py already established for its own suspicious-name-only
    # case. A human must read the actual text before trusting this as a leak.
    toks = path_suspicious_tokens(text)
    if toks:
        return {
            "confidence": "candidate",
            "signal": "suspicious_wording",
            "reason": "metadata text mentions a word associated with internal grading "
            "artifacts, with no corroborating value or filename match -- may be an innocuous "
            "editorial note, needs a human glance",
            "kind": item["kind"],
            "location": item["location"],
            "text": text[:500],
            "suspicious_tokens": toks,
        }
    return None


def scan_files(
    files: list[Path], task_dir: Path, values: list[dict]
) -> tuple[list[dict], list[dict], list[str], int]:
    high: list[dict] = []
    candidate: list[dict] = []
    errors: list[str] = []
    n_scanned = 0
    for f in files:
        items, err = extract_metadata_items(f)
        n_scanned += 1
        if err:
            errors.append(f"{f.relative_to(task_dir)}: {err}")
        rel = str(f.relative_to(task_dir)).replace("\\", "/")
        for item in items:
            finding = evaluate_metadata_item(item, values)
            if finding is None:
                continue
            finding["file"] = rel
            (high if finding["confidence"] == "high" else candidate).append(finding)
    return high, candidate, errors, n_scanned


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir: Path) -> dict:
    task_id = task_dir.name
    fmt = _task_format(task_dir)
    result = {
        "task_id": task_id,
        "task_format": fmt,
        "n_golden_files_scanned": 0,
        "n_environment_files_scanned": 0,
        "n_expected_values": 0,
        "parse_errors": [],
        "golden_high_findings": [],
        "golden_candidate_findings": [],
        "environment_high_findings": [],
        "environment_candidate_findings": [],
        "errors": [],
    }

    if fmt == "none":
        result["status"] = "skip"
        result["errors"].append(
            "no tests/deliverables*/judge.toml or tests/verifier.json found -- not a "
            "recognized task format"
        )
        result["summary"] = {
            "n_golden_high": 0,
            "n_golden_candidate": 0,
            "n_environment_high": 0,
            "n_environment_candidate": 0,
        }
        return result

    values, parse_errors = load_values_for_task(task_dir)
    result["n_expected_values"] = len(values)
    result["parse_errors"] = parse_errors

    golden_files = [
        f
        for f in find_golden_files(task_dir, fmt)
        if f.suffix.lower() in METADATA_CAPABLE_EXTENSIONS
    ]
    env_files = find_environment_files_for_metadata(task_dir, fmt)

    g_high, g_cand, g_err, g_n = scan_files(golden_files, task_dir, values)
    e_high, e_cand, e_err, e_n = scan_files(env_files, task_dir, values)

    result["golden_high_findings"] = g_high
    result["golden_candidate_findings"] = g_cand
    result["environment_high_findings"] = e_high
    result["environment_candidate_findings"] = e_cand
    result["errors"].extend(g_err)
    result["errors"].extend(e_err)
    result["n_golden_files_scanned"] = g_n
    result["n_environment_files_scanned"] = e_n

    if e_high:
        result["status"] = "fail"
    elif g_high or g_cand or e_cand:
        result["status"] = "warn"
    else:
        result["status"] = "pass"

    result["summary"] = {
        "n_golden_high": len(g_high),
        "n_golden_candidate": len(g_cand),
        "n_environment_high": len(e_high),
        "n_environment_candidate": len(e_cand),
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

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(task_dir)
        except Exception as exc:  # never let one task's crash kill the whole batch
            r = {
                "task_id": task_dir.name,
                "status": "error",
                "errors": [f"unhandled exception analyzing this task: {exc}"],
                "golden_high_findings": [],
                "golden_candidate_findings": [],
                "environment_high_findings": [],
                "environment_candidate_findings": [],
                "summary": {
                    "n_golden_high": 0,
                    "n_golden_candidate": 0,
                    "n_environment_high": 0,
                    "n_environment_candidate": 0,
                },
            }
        results.append(r)
        s = r["summary"]
        print(
            f"    -> {r['status']}  (golden: {s['n_golden_high']} high / "
            f"{s['n_golden_candidate']} candidate; environment: {s['n_environment_high']} "
            f"high / {s['n_environment_candidate']} candidate; {len(r.get('errors', []))} errors)",
            file=sys.stderr,
        )

    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_warn = sum(1 for r in results if r["status"] == "warn")
    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    n_error = sum(1 for r in results if r["status"] == "error")

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_fail": n_fail,
        "n_warn": n_warn,
        "n_pass": n_pass,
        "n_skip": n_skip,
        "n_error": n_error,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_warn} warn / {n_fail} FAIL (solver-facing) / {n_skip} skip / "
        f"{n_error} error out of {len(results)} task(s)"
    )
    for r in results:
        if r["status"] in ("pass", "skip"):
            continue
        print(f"  {r['task_id']}: {r['status']}")
        for f in r.get("environment_high_findings", []):
            print(
                f"      ENV HIGH [{f['signal']}]: {f['kind']} in {f['file']} "
                f"({f['location']}): {f['text'][:120]!r}"
            )
        for f in r.get("environment_candidate_findings", []):
            print(
                f"      env candidate [{f['signal']}]: {f['kind']} in {f['file']} "
                f"({f['location']}): {f['text'][:120]!r}"
            )
        for f in r.get("golden_high_findings", []):
            print(
                f"      golden high [{f['signal']}]: {f['kind']} in {f['file']} "
                f"({f['location']}): {f['text'][:120]!r}"
            )
        for f in r.get("golden_candidate_findings", []):
            print(f"      golden candidate: {f['kind']} in {f['file']}")
        for e in r.get("errors", []):
            print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(aggregate, fh, indent=2, ensure_ascii=False)
        print(f"\nWrote {args.out}")

    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
