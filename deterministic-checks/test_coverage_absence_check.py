#!/usr/bin/env python3
r"""Test-coverage-absence check: does the golden contain a whole named content block
(a docx Heading-styled section, an xlsx tab) that ZERO rubric criteria actually reference or
test? Deleting such a block from the golden would leave every criterion's verdict unchanged --
the reward stays 1.0 -- because nothing in the rubric was ever looking at it.

**THIS IS A LOW-CONFIDENCE, CANDIDATE-FOR-REVIEW TOOL, NOT A PASS/FAIL GATE.** Matching "does
any criterion test this section" by keyword/text overlap has real false positives (a criterion
phrased generically enough to accidentally overlap a section it never actually grades) and real
false negatives (a criterion that tests a section's substance without ever repeating its words,
e.g. "reconciles every open item to zero" testing a section titled "Residual" with no lexical
overlap at all). Every finding in this script's output is a `candidate` for a human to look at,
the same status vocabulary `answer_key_content_leak_check.py` and `undisclosed_terminology_check.py`
already use in this folder -- never upgrade a finding here to "confirmed defect" without actually
opening the golden and the rubric side by side.

Why this check is a genuinely different shape than every other script in this folder: every
other check flags something PRESENT and WRONG (a duplicate ID, a compound criterion, an
unreachable fact). This one has to flag something ABSENT -- a golden section with no criterion
pointing at it -- which by construction no per-criterion check can do; it needs the golden's own
structure as the thing being tested against, not the rubric alone. Per `COVERAGE-MATRIX.md` Part
4 (the "Test-coverage absence" row, the source of this check's brief -- no
`svc-defect-taxonomy-2026-09-15.md` file with an "A44" id was found anywhere in this repo or in
`C:\ekwqc` as of this writing; that citation could not be verified and this docstring does not
repeat it as fact), this was UNASSIGNED and "not yet designed" before this script.

Evidence tags used throughout, same convention as `semantic-consistency-design-2026-09-14.md`:
RAN (executed this session, output quoted), READ (read from a file this session), PROPOSED (a
design decision, not evidence), OPEN (unresolved, named as such).

## What "section" means, concretely (READ, real goldens, this session)

docx: a paragraph whose `w:pStyle` is a Heading style (`Heading1`...`Heading9`, or `Title`)
starts a new section; every non-heading paragraph up to the next heading paragraph (ANY level --
this script does not nest Heading2 under Heading1, it flattens, see Known limits) is that
section's body. Confirmed against three real goldens this session:
  - SVC-PC-92-0-0 solution/files/Critical_Policy_Procedure_Lifecycle_Controls_Response.docx:
    107 paragraphs, 9 `Heading1` sections ("Executive decision", "Why this matters now",
    "Current control environment", "Critical guidance population", "Priority findings requiring
    resolution", "Minimum lifecycle-control model", "Implementation sequence", "Boundaries and
    limitations", "Source trace"), 6 `ListBullet`, everything else unstyled body/table text.
  - SVC-PC-88-0-0 solution/files/Audit_Committee_Remediation_Memo.docx: 8 `Heading1` sections
    ("What broke", "What was corrected / evidenced", "Residual", "Open items (including missing
    941)", "Ask to the Committee", "Cast / attachments", ...).
  - SVC-PC-88-0-0 solution/files/Payroll_Controls_Checklist.docx: 3 `Heading1` sections
    ("Period-end controls", "Threshold reminder", "Non-scope").
A golden with zero heading-styled paragraphs anywhere yields zero sections and is reported as
`no_sections_found` -- this script does not invent structure that isn't there (e.g. treating
every bold short line as a pseudo-heading was tried against these same three files and rejected:
bold is used throughout for table-cell emphasis, not section titles, and would have produced
40+ false "sections" per file that are really table rows). EXCEPTION: when zero heading-styled
paragraphs are found, `extract_docx_sections` falls back to detecting headings by direct
font-size formatting (a paragraph whose max run font size is strictly larger than the
document's body font size). This is a different signal than the rejected bold-only heuristic:
bold table cells sit at body font size and are excluded, while real headings (bold + larger
font, no Word style) are rescued. Confirmed against a real 91-paragraph EKW golden
(sports_api_documentation.docx) where all paragraphs are unstyled but headings are at 13pt /
10.5pt vs body at 10pt. The fallback fires ONLY when zero heading-styled sections are found,
so files that use Word heading styles (all confirmed SVC-PC goldens, most EKW goldens) are
unaffected.

xlsx: each worksheet tab is one section, its name the section label, and the text of every
non-empty cell (`data_only=True`, so a cached formula RESULT counts as content, capped at 300
rows x 40 cols per sheet -- a bound on runtime across a 600+274-task corpus, disclosed, not
silently applied) is its body. Confirmed against SVC-PC-88-0-0
solution/files/Payroll_Reconciliation_Workbook.xlsx: 13 sheets including a run of `Cite_L2_01`
through `Cite_L2_07` (each a small Ref/Headline/Value/Notes citation table), `Trace`,
`Books_Tie_Out`, `Cutover_Integrity`, `Federal_Books`, `Benefits`, `Controls`. The `Cite_L2_0N`
naming lines up with the task brief's own "SVC-PC-88-0-0 L2-1/7/8" citation -- PROPOSED reading,
not independently confirmed against the real rubric text before this script existed to check it.

## How "tested" is decided, per section (PROPOSED, the actual heuristic, stated plainly)

Every criterion's full description/Expected text (SVC-PC: `tests/deliverables*/judge.toml`,
identical file glob to `compound_criterion_check.py`'s `check_task()`; EKW:
`ekw_verifier_json.load_ekw_criteria()`) is concatenated into one lowercase corpus for the task.
A section counts as tested if ANY of three independent signals fires -- deliberately
OR-combined and generous, because the cost of a false "untested" finding (sends a human to
double-check a section that actually is graded) is treated as cheaper than the cost of silently
missing a real gap, but a section is never counted as untested off a single weak coincidence:

  1. **Label match**: the section's own label (docx heading text, or xlsx sheet name with
     underscores/dashes turned to spaces) appears, word-boundary-matched, anywhere in the
     criteria corpus. Cheap and highest-precision when it fires -- a criterion that names
     "Source trace" or "Cite_L2_04" directly is unambiguous.
  2. **Content-token overlap**: a token (an alphabetic word, 5+ chars, lowercased) counts as
     DISTINCTIVE to a section only if it appears in that section and in at most one OTHER
     section of the SAME golden (a document-relative rarity filter, not a fixed stopword list --
     a payroll memo's every section says "payroll", so "payroll" is never distinctive evidence
     for any one of them; "cutover" appearing only in one section is). >=2 distinct such tokens
     each independently appearing in the criteria corpus (word-boundary) counts as coverage.
  3. **Anchor match**: a section-specific numeric/currency/date/percent token (same shapes as
     `criterion_groundedness_check.py`'s VALUE_TOKEN_RE, reused not reimplemented) or a
     multi-word Capitalized phrase (a name-shaped anchor) that appears in the section body also
     appears verbatim in the criteria corpus. One hit is enough -- a specific figure or name
     repeated in a criterion is strong, low-coincidence evidence regardless of word count.

A section with NONE of the three signals is `untested_section`, always severity `candidate`,
never a hard gate -- see Known limits for exactly how noisy this is expected to be.

## Validation against the two positive controls (RAN this session, exact command in usage above)

SVC-PC-92-0-0: 1 of 9 sections flagged -- "Source trace", the task brief's own named example.
Confirmed by hand: its body is a bare citation list with no words/numbers any of the task's 10
criteria happen to restate. The brief's "3 untested blocks" is NOT reproduced (this script finds
1, not 3) -- stated as a real, disclosed discrepancy, not adjusted to match the brief. Two
readings, neither confirmed further this session (OPEN): the brief's "3" counts at a finer
granularity this script's flat per-Heading1 model doesn't see, or "L3-1" in the brief refers to a
different task/citation than what this script's structural read of this one golden shows.

SVC-PC-88-0-0: 5 of 25 sections flagged (`Cite_L2_02`, `Cite_L2_06`, `Cutover_Integrity`, docx
"What was corrected / evidenced", docx "Threshold reminder"). Each was checked BY HAND against
all 19 real criteria this session, not just accepted as this script's own verdict -- a mixed,
honestly-reported result:
  - `Cite_L2_02` (Location_BREAK=0, Location_INCONCLUSIVE=15, Filing_BREAK=1, Population_Gaps=2):
    CONFIRMED genuine. No obj-NN criterion cites any of these four values; only str-06 checks
    that the tab exists at all ("Cite_L2_01...Cite_L2_07 tabs present"), never its content.
  - `Cutover_Integrity`: CONFIRMED genuine, and a real finding beyond what the brief named -- its
    own header literally says "formulas carry L2-02 mismatch counts" and it duplicates
    `Cite_L2_02`'s same four values; equally uncited by any obj-NN criterion.
  - `Cite_L2_06` (Months_With_Break_Flag=5, Max_Abs_Gross_Break=7083.33): PARTIALLY confirmed.
    obj-04 cites Months_With_Break_Flag's value ("Expected: 5"), but this script's numeric-anchor
    signal requires 3+ digits (`\b\d{3,}\b`) specifically to avoid a bare "5" matching by
    coincidence (see Known limits), so it can't see that hit; Max_Abs_Gross_Break=7083.33 really
    is uncited by anything. Net: this section is a real partial gap, flagged for a different
    reason than its true one.
  - Two docx sections ("What was corrected / evidenced", "Threshold reminder"): LIKELY FALSE
    POSITIVES on manual read. jdg-04 ("AC memo states what broke, what was corrected,
    residual/open items...") structurally covers the FIRST section's topic via generic
    restatement, and the checklist's own threshold formula is restated in criteria elsewhere in
    the package -- but neither criterion repeats enough of the section's own specific vocabulary
    or values for any of this script's three signals to fire. This is the central, expected
    failure mode disclosed throughout this docstring: a criterion that tests a section's
    SUBSTANCE in its own words, not the section's words, is invisible to lexical overlap.
Net for 88-0-0: 2 of 5 flagged sections confirmed genuine, 1 partially genuine (right section,
wrong reason), 2 likely false positives -- roughly 60% real signal at the two-task scale, all
five still correctly surfaced as candidates rather than silently missed, none asserted as a
confirmed defect by this script itself.

## Known limits, disclosed rather than hidden

  - Flat section model: a Heading2 nested under a Heading1 becomes its OWN top-level section,
    not a child of the parent. This can OVER-split (a genuinely-covered parent section reads as
    several small untested-looking children) or UNDER-split relative to whatever granularity the
    task brief's "3 untested blocks" / "L2-1/7/8" figures were counted at. Not fixed this
    session -- true nesting needs heading-level tracking this v1 does not attempt.
  - Content-token overlap (signal 2) is the noisiest of the three by construction: two sections
    can share vocabulary by genre (two "Findings"-shaped sections in unrelated tasks both saying
    "reconcile", "evidence", "control") even when neither is really about the other. The
    document-relative rarity filter (a token must be rare WITHIN this one golden) mitigates but
    does not eliminate this -- a criterion corpus that happens to reuse a section's rare word for
    an unrelated reason still counts as a false "tested".
  - Label match (signal 1) has the opposite failure: a section titled generically ("Residual",
    "Summary", "Overview") will almost never be named verbatim in criterion text even when its
    CONTENT is fully graded, so this signal under-fires on exactly the section titles most likely
    to be generic-sounding but substantively covered.
  - Anchor match (signal 3) inherits `VALUE_TOKEN_RE`'s own known gaps (no OCR, no unit/scale
    normalization -- "$1.2M" vs "1200000" will not match) from `criterion_groundedness_check.py`.
  - xlsx cell reading is `data_only=True` only (cached results, not formulas); a sheet whose
    cache was wiped by a load+save round trip (the exact defect `formula_health_check.py` exists
    to catch) will read as having near-empty content here and may be wrongly reported as
    `no_sections_found` or as a spuriously "untested" section with too little text to match
    anything. This script does not cross-check against `formula_health_check.py`'s findings.
  - .pdf and other golden formats are not parsed -- not asserted clean, just not covered. Only
    `.docx`, `.xlsx`, `.xlsm` goldens under `solution/files/` (falling back to `solution/`
    directly if `files/` doesn't exist) are read.
  - This script does not attempt to tell WHICH criteria came close to testing a section, only
    whether any did -- a human reviewing a `candidate` finding still has to read the rubric
    themselves to confirm the gap is real.
  - Corpus-scale numbers (RAN this session, real corpora, not a sample): full SVC-PC
    `03_dataos_ready` (600 of 609 directories matched as tasks), 130s: 23,220 criteria, 5,363
    golden sections, 488 `untested_section` candidates (9.1% of sections), 28 tasks errored
    (`no_sections_found` -- a golden with no `.docx`/`.xlsx`/`.xlsm` under `solution/files/`, or
    one that has such a file but zero Heading-styled paragraphs/sheets found in it). Full EKW
    `_merged274` corpus, 157s (after fixing `find_golden_files` to also look under
    `solution/golden_outputs/` -- EKW's real layout, confirmed by listing `task_9` directly;
    before that fix every one of the 274 tasks read as `no_sections_found`, a real bug this
    script's own two-corpus validation caught, not a hypothetical): 5,624 criteria, 5,216
    sections, 454 candidates (8.7%), 13 tasks errored. Both corpora land in the same 9-12% flag
    rate as the 56-task reconciled sample (74/590, 12.5%) -- consistent, not spiky on one
    corpus. NONE of these ~950 combined candidates were manually verified the way the two
    positive-control tasks were (see Validation section above) -- extrapolating that ~50-60%
    real-signal rate to the full corpus is a guess, not a measurement, and is not made here.

Exit 0 clean (zero `untested_section` findings across every task scanned), 1 findings present
(candidates for review, NOT a failed gate -- read the printed banner), 2 bad usage. Stdlib plus
openpyxl (auto-installed via pip on first import if missing, same pattern as
`formula_health_check.py`/`deliverable_integrity_check.py`/`criterion_groundedness_check.py`).

    python test_coverage_absence_check.py <package_root> [--task TASK-ID ...] [--json out.json]
    python test_coverage_absence_check.py C:\b\_stage_0914_reconciled56 --task SVC-PC-92-0-0 SVC-PC-88-0-0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from ekw_verifier_json import has_ekw_config, load_ekw_criteria

try:
    import openpyxl
except ImportError:  # pragma: no cover
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

XLSX_MAX_ROWS = 300
XLSX_MAX_COLS = 40

HEADING_STYLE_RE = re.compile(r"^(heading\d?|title)$", re.I)

_PARA_RE = re.compile(r"<w:p\b.*?</w:p>", re.DOTALL)
_PSTYLE_RE = re.compile(r'<w:pStyle\s+w:val="([^"]+)"')
_WT_RE = re.compile(r"<w:t[^>]*>([^<]*)</w:t>")
_SZ_RE = re.compile(r'<w:sz\s+w:val="(\d+)"')

# Same value-token shapes as criterion_groundedness_check.py's VALUE_TOKEN_RE (reused, not
# reimplemented -- kept as a local copy since importing that module's private-ish constant
# would couple this script to its internals for no benefit).
VALUE_TOKEN_RE = re.compile(
    r"""
    (?P<currency>\$\d{1,3}(?:,\d{3})*(?:\.\d+)?)
  | (?P<percent>[-\u2212]?\d+(?:\.\d+)?%)
  | (?P<date_iso>\b\d{4}-\d{2}-\d{2}\b)
  | (?P<date_slash>\b\d{1,2}/\d{1,2}/\d{2,4}\b)
  | (?P<comma_number>\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b)
  | (?P<decimal_number>\b\d+\.\d+\b)
  | (?P<bare_number>\b\d{3,}\b)
""",
    re.VERBOSE,
)
NUMERIC_ANCHOR_KINDS = {"currency", "comma_number", "decimal_number", "bare_number"}
NUMERIC_TOLERANCE = 0.005


def to_float(token: str):
    """Same normalization as criterion_groundedness_check.py's to_float(): strip everything but
    digits/dot, negate on a leading "(" (the "$(1,050.00)" parenthetical-negative idiom this
    corpus also uses). A leading unicode minus (U+2212, "\u2212$1,050.00") is NOT detected as
    negative here, same known gap as the reference script -- this check compares ABSOLUTE VALUE
    for anchor matching regardless (see decide_coverage), since its job is "was this fact
    referenced at all", not "is the sign correct", so the gap does not defeat matching the way
    it would for a correctness check."""
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


def _corpus_numeric_values(corpus: str) -> set[float]:
    """Every numeric value stated anywhere in the criteria corpus, rounded to 2dp, ABSOLUTE
    VALUE (see to_float's docstring for why sign is dropped)."""
    out = set()
    for m in VALUE_TOKEN_RE.finditer(corpus):
        if m.lastgroup in NUMERIC_ANCHOR_KINDS:
            v = to_float(m.group(0))
            if v is not None:
                out.add(round(abs(v), 2))
    return out


# A name-shaped anchor: two-or-more-word Capitalized phrase ("Marcus Rivera", "Form 941" is
# handled by VALUE_TOKEN_RE's own numeric half, this catches the proper-noun half).
PROPER_PHRASE_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2}\b")

WORD_RE = re.compile(r"[a-z]{5,}")

# Minimal generic-English stopword list -- kept small on purpose. The document-relative rarity
# filter (a token must occur in at most one OTHER section of the SAME golden) is doing most of
# the real work; this list only removes words too generic to ever be distinctive even in a
# single-section golden.
STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "their",
    "there",
    "these",
    "those",
    "which",
    "while",
    "would",
    "should",
    "could",
    "every",
    "within",
    "where",
    "shall",
    "being",
    "other",
    "still",
    "under",
    "until",
    "based",
    "given",
    "table",
    "section",
    "review",
    "report",
    "overall",
    "summary",
}

# Tiny connector-word list for the bag-of-words label signal only (see decide_coverage) -- not
# the same list as STOPWORDS, which filters CONTENT tokens; this one filters a heading's own
# structural words ("and", "was") that carry no topic signal even in a short 2-4-word heading.
LABEL_CONNECTOR_WORDS = {
    "and",
    "was",
    "for",
    "the",
    "with",
    "from",
    "into",
    "are",
    "has",
    "have",
    "been",
    "including",
    "incl",
}


# ---------------------------------------------------------------------------
# golden section extraction
# ---------------------------------------------------------------------------


def _clean_label(label: str) -> str:
    return re.sub(r"[_\-]+", " ", label).strip()


def _extract_docx_sections_fallback(xml: str) -> list[dict]:
    r"""Fallback heading detection by direct font-size formatting, called only when
    the primary style-based method finds zero sections.

    Some real golden docx files use direct formatting (bold + larger font) instead
    of Word's built-in Heading styles, even when those styles exist in the template.
    Confirmed against a real 91-paragraph EKW golden (sports_api_documentation.docx)
    where every paragraph is unstyled or ListParagraph, yet headings are clearly bold
    at 13pt / 10.5pt while body text and bold table cells are both at 10pt.

    Detects headings as paragraphs whose maximum run font size (w:sz, half-points)
    is strictly larger than the document's body font size (the most common max-size
    across all text-bearing paragraphs, ties broken toward the smaller size). This
    cleanly separates real headings from bold table cells that sit at body size, the
    exact false-positive mode that made the earlier "every bold short line" approach
    (rejected, see module docstring) produce 40+ spurious sections in SVC-PC files.
    The font-size signal avoids that problem because table cells inherit the body
    font size even when bold.

    Only called when zero heading-styled sections are found, so files that DO use
    Word heading styles (all confirmed SVC-PC goldens, most EKW goldens) are entirely
    unaffected.
    """
    para_info: list[tuple[str, int]] = []
    sz_counts: dict[int, int] = {}
    for para in _PARA_RE.finditer(xml):
        text = "".join(_WT_RE.findall(para.group(0))).strip()
        if not text:
            continue
        sizes = [int(s) for s in _SZ_RE.findall(para.group(0))]
        max_sz = max(sizes) if sizes else 0
        para_info.append((text, max_sz))
        if max_sz > 0:
            sz_counts[max_sz] = sz_counts.get(max_sz, 0) + 1

    if not para_info or not sz_counts:
        return []

    max_count = max(sz_counts.values())
    body_sz = min(sz for sz, cnt in sz_counts.items() if cnt == max_count)

    # A paragraph is a heading if its max font size is strictly larger than body
    # AND it is reasonably short (a real heading label, not a lead paragraph or
    # abstract that merely sits at a slightly larger font). 100 chars is generous:
    # every confirmed real heading in the test corpus is under 35 chars, while the
    # one observed false positive (a 131-char lead paragraph at 11pt vs 10pt body)
    # is cleanly excluded.
    sections: list[dict] = []
    current: dict | None = None
    for text, max_sz in para_info:
        if max_sz > body_sz and len(text) <= 100:
            current = {"label": text, "body_parts": []}
            sections.append(current)
        elif current is not None:
            current["body_parts"].append(text)
    return sections


def extract_docx_sections(path: Path) -> tuple[list[dict], str | None]:
    """[{label, body_text}], or ([], error_string) on a read/parse failure. Flat model: every
    Heading-styled paragraph (any level) starts a new section; see module docstring. When zero
    heading-styled paragraphs are found, falls back to detecting headings by direct font-size
    formatting (see _extract_docx_sections_fallback) so files that use bold + larger font
    instead of Word styles still yield real sections instead of no_sections_found."""
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception as exc:
        return [], f"could not open/parse {path.name}: {exc}"

    sections: list[dict] = []
    current: dict | None = None
    for para in _PARA_RE.finditer(xml):
        p = para.group(0)
        style_m = _PSTYLE_RE.search(p)
        style = style_m.group(1) if style_m else None
        text = "".join(_WT_RE.findall(p)).strip()
        if style and HEADING_STYLE_RE.match(style) and text:
            current = {"label": text, "body_parts": []}
            sections.append(current)
        elif text and current is not None:
            current["body_parts"].append(text)
        # text before the first heading (title block, addressee lines, etc.) is deliberately
        # dropped -- it has no section label to attach findings to, and this check's job is
        # named blocks, not front-matter.
    if not sections:
        sections = _extract_docx_sections_fallback(xml)
    for s in sections:
        s["body_text"] = "\n".join(s.pop("body_parts"))
    return sections, None


def extract_xlsx_sections(path: Path) -> tuple[list[dict], str | None]:
    """[{label, body_text}] -- one entry per worksheet tab."""
    try:
        wb = openpyxl.load_workbook(str(path), data_only=True)
    except Exception as exc:
        return [], f"could not open/parse {path.name}: {exc}"

    sections = []
    for name in wb.sheetnames:
        ws = wb[name]
        parts = []
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row or 1, XLSX_MAX_ROWS)):
            for cell in row[:XLSX_MAX_COLS]:
                if cell.value is None:
                    continue
                v = str(cell.value).strip()
                if v:
                    parts.append(v)
        sections.append({"label": name, "body_text": "\n".join(parts)})
    return sections, None


def find_golden_files(task_dir: Path) -> list[Path]:
    """.docx / .xlsx / .xlsm under the golden's real directory. Tried in order: SVC-PC's
    `solution/files/`, EKW's `solution/golden_outputs/` (READ this session, real task_9 layout
    -- EKW does NOT use `files/`, confirmed by directly listing a real EKW task directory before
    assuming SVC-PC's layout transferred), then `solution/` itself as a last, defensive
    fallback. First candidate directory that actually exists wins; this does not merge files
    from more than one."""
    for sub in ("files", "golden_outputs", None):
        base = task_dir / "solution" / sub if sub else task_dir / "solution"
        if base.is_dir():
            return sorted(
                p
                for p in base.iterdir()
                if p.is_file() and p.suffix.lower() in (".docx", ".xlsx", ".xlsm")
            )
    return []


def extract_golden_sections(task_dir: Path) -> tuple[list[dict], list[str]]:
    """All sections across every golden file in solution/. Each section dict also carries
    `source_file`. Returns (sections, errors)."""
    sections: list[dict] = []
    errors: list[str] = []
    for gf in find_golden_files(task_dir):
        if gf.suffix.lower() == ".docx":
            secs, err = extract_docx_sections(gf)
        else:
            secs, err = extract_xlsx_sections(gf)
        if err:
            errors.append(err)
            continue
        for s in secs:
            s["source_file"] = gf.name
        sections.extend(secs)
    return sections, errors


# ---------------------------------------------------------------------------
# criteria corpus (dual format)
# ---------------------------------------------------------------------------


def _svc_pc_criteria_text(task_dir: Path) -> tuple[str, int]:
    """Concatenated lowercase text of every criterion description across
    tests/deliverables*/judge.toml (same glob as compound_criterion_check.py's check_task()).
    Returns (corpus_text, criteria_count)."""
    judge_files = sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )
    parts = []
    n = 0
    for jf in judge_files:
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        for c in data.get("criterion") or []:
            n += 1
            desc = (c.get("description") or "").strip()
            if desc:
                parts.append(desc)
    return "\n".join(parts).lower(), n


def _ekw_criteria_text(task_dir: Path) -> tuple[str, int]:
    criteria = load_ekw_criteria(task_dir)
    parts = []
    n = 0
    for c in criteria:
        if c.get("name") == "__parse_error__":
            continue
        n += 1
        desc = (c.get("description") or "").strip()
        if desc:
            parts.append(desc)
    return "\n".join(parts).lower(), n


def _has_svc_pc_config(task_dir: Path) -> bool:
    return bool(
        list(task_dir.glob("tests/deliverables/judge.toml"))
        or list(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def get_criteria_corpus(task_dir: Path) -> tuple[str, int, str]:
    """(corpus_text_lower, criteria_count, format_label)."""
    if _has_svc_pc_config(task_dir):
        text, n = _svc_pc_criteria_text(task_dir)
        return text, n, "svc-pc"
    if has_ekw_config(task_dir):
        text, n = _ekw_criteria_text(task_dir)
        return text, n, "ekw"
    return "", 0, "unknown"


# ---------------------------------------------------------------------------
# coverage decision
# ---------------------------------------------------------------------------


def _word_in_corpus(word: str, corpus: str) -> bool:
    return (
        re.search(r"(?<![a-z0-9])" + re.escape(word.lower()) + r"(?![a-z0-9])", corpus)
        is not None
    )


def _section_words(body_text: str) -> set[str]:
    return {w for w in WORD_RE.findall(body_text.lower()) if w not in STOPWORDS}


def _section_numeric_anchors(body_text: str) -> set[str]:
    """Numeric-shaped tokens (currency/comma/decimal/3+-digit bare) as their ORIGINAL text, for
    reporting -- matching itself is done via to_float()/absolute-value equivalence, not on
    these strings directly (see decide_coverage)."""
    return {
        m.group(0)
        for m in VALUE_TOKEN_RE.finditer(body_text)
        if m.lastgroup in NUMERIC_ANCHOR_KINDS
    }


def _section_proper_anchors(body_text: str) -> set[str]:
    return {m.group(0) for m in PROPER_PHRASE_RE.finditer(body_text)}


def decide_coverage(sections: list[dict], corpus: str) -> list[dict]:
    """Mutates nothing; returns one report dict per section with a `tested` bool and `signals`
    (list of which of the 3 signals fired, empty if untested)."""
    # document-relative word frequency: how many DISTINCT sections contain each word
    per_section_words = [_section_words(s["body_text"]) for s in sections]
    word_section_count: dict[str, int] = {}
    for words in per_section_words:
        for w in words:
            word_section_count[w] = word_section_count.get(w, 0) + 1

    corpus_numbers = _corpus_numeric_values(corpus)

    results = []
    for s, words in zip(sections, per_section_words):
        signals = []

        # signal 1: label match. Tried strongest-to-weakest so `signals` records which fired.
        label_clean = _clean_label(s["label"])
        if len(label_clean) >= 3 and _word_in_corpus(label_clean, corpus):
            signals.append("label_match")
        elif len(s["label"]) >= 3 and s["label"].lower() in corpus:
            # raw label (covers underscore-coded tab names like Cite_L2_01 that might appear
            # literally, underscores and all, in criterion text)
            signals.append("label_match_raw")
        else:
            # bag-of-words label match: a criterion restating a heading's own significant words
            # without the heading's exact phrasing/punctuation -- real case found this session,
            # SVC-PC-88-0-0's heading "What was corrected / evidenced" vs criterion jdg-04's
            # "...what was corrected, residual/open items..." (no "/ evidenced" in the criterion,
            # so the exact-phrase check above misses it even though this is obviously the same
            # topic). Requires ALL of the heading's significant words (>=3 alpha chars, minus a
            # tiny connector-word list) to appear somewhere in the corpus -- weaker signal than
            # an exact phrase, so only applied when the heading has 2+ such words (a 1-word
            # heading has nothing to disambiguate a bag-of-words match from a coincidence).
            heading_words = [
                w
                for w in re.findall(r"[A-Za-z]{3,}", label_clean.lower())
                if w not in LABEL_CONNECTOR_WORDS
            ]
            if len(heading_words) >= 2 and all(
                _word_in_corpus(w, corpus) for w in heading_words
            ):
                signals.append("label_words_match")

        # signal 2: content-token overlap, document-relative distinctive tokens only
        distinctive = {w for w in words if word_section_count.get(w, 0) <= 1}
        matched_tokens = [w for w in distinctive if _word_in_corpus(w, corpus)]
        if len(matched_tokens) >= 2:
            signals.append("content_overlap")

        # signal 3a: numeric anchor -- ABSOLUTE-VALUE numeric equivalence against every number
        # stated anywhere in the criteria corpus (not literal substring -- see to_float's
        # docstring for why: "$1,050.00" in a section cell must match "-$1,050.00" or
        # "−$1,050.00" in criterion text, which a substring test would miss on the comma
        # and the sign alone).
        numeric_anchors = _section_numeric_anchors(s["body_text"])
        matched_numeric = [
            a
            for a in numeric_anchors
            if (v := to_float(a)) is not None and round(abs(v), 2) in corpus_numbers
        ]
        if matched_numeric:
            signals.append("numeric_anchor_match")

        # signal 3b: proper-noun-phrase anchor -- literal substring (a multi-word capitalized
        # name is not subject to the numeric-formatting problem signal 3a exists for).
        proper_anchors = _section_proper_anchors(s["body_text"])
        matched_proper = [a for a in proper_anchors if a.lower() in corpus]
        if matched_proper:
            signals.append("proper_anchor_match")

        results.append(
            {
                "label": s["label"],
                "source_file": s.get("source_file"),
                "tested": bool(signals),
                "signals": signals,
                "matched_tokens_sample": matched_tokens[:5],
                "matched_numeric_sample": matched_numeric[:5],
                "matched_proper_sample": matched_proper[:5],
                "body_chars": len(s["body_text"]),
            }
        )
    return results


# ---------------------------------------------------------------------------
# per-task check
# ---------------------------------------------------------------------------


def check_task(task_dir: Path) -> dict:
    res = {
        "task": task_dir.name,
        "format": None,
        "golden_files": [],
        "sections_scanned": 0,
        "criteria_scanned": 0,
        "untested_section": [],
        "tested_sections": [],
        "errors": [],
        "ok": True,
    }
    corpus, n_criteria, fmt = get_criteria_corpus(task_dir)
    res["format"] = fmt
    res["criteria_scanned"] = n_criteria
    if not corpus:
        res["errors"].append(
            "no criteria text found (no judge.toml / verifier.json parsed)"
        )
        res["ok"] = False
        return res

    sections, errors = extract_golden_sections(task_dir)
    res["errors"].extend(errors)
    res["golden_files"] = sorted({s["source_file"] for s in sections})
    res["sections_scanned"] = len(sections)
    if not sections:
        res["errors"].append(
            "no_sections_found (no Heading-styled or font-size-differentiated "
            "docx paragraphs, and no xlsx tabs, in solution/)"
        )
        res["ok"] = not res["errors"]
        return res

    decisions = decide_coverage(sections, corpus)
    for d in decisions:
        if d["tested"]:
            res["tested_sections"].append(d)
        else:
            res["untested_section"].append(d)

    res["ok"] = not res["untested_section"] and not res["errors"]
    return res


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "root",
        help="a directory containing one subdirectory per task, or a single task directory",
    )
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        help="limit to these task ids (repeatable, or space-separated after one --task)",
        nargs="*",
    )
    ap.add_argument("--json", help="also write the full result set here")
    args = ap.parse_args()

    # --task collects either repeated flags or one flag with multiple ids; flatten either shape
    want_ids: list[str] = []
    for group in args.task:
        want_ids.extend(group) if isinstance(group, list) else want_ids.append(group)

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2
    if (root / "tests").is_dir() or (root / "solution").is_dir():
        task_dirs = [root]
    else:
        task_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if want_ids:
        want = set(want_ids)
        task_dirs = [d for d in task_dirs if d.name in want]
    if not task_dirs:
        sys.stderr.write(f"no task directories matched under {root}\n")
        return 2

    results = [check_task(d) for d in task_dirs]

    total_sections = 0
    total_untested = 0
    total_criteria = 0
    n_errored = 0
    for r in results:
        total_sections += r["sections_scanned"]
        total_untested += len(r["untested_section"])
        total_criteria += r["criteria_scanned"]
        if r["errors"]:
            n_errored += 1
        flag = "OK  " if r["ok"] else ("CAND" if r["untested_section"] else "ERR ")
        print(
            f"{flag} {r['task']:<20} [{r['format']}]  {r['criteria_scanned']:>4} criteria  "
            f"{r['sections_scanned']:>3} sections  untested: {len(r['untested_section'])}"
        )
        for e in r["errors"]:
            print(f"       error: {e}")
        for f in r["untested_section"]:
            print(
                f"       [CANDIDATE] untested_section  {f['source_file']}::{f['label']!r}  "
                f"({f['body_chars']} chars, no label/content/anchor match)"
            )

    print(
        f"\n{total_sections - total_untested}/{total_sections} golden sections have >=1 "
        f"matching signal  |  {total_criteria} criteria scanned across {len(results)} tasks  |  "
        f"{total_untested} untested_section candidate(s)  |  {n_errored} task(s) with errors"
    )
    print(
        "NOTE: untested_section is a CANDIDATE for human review, not a confirmed defect and not "
        "a pass/fail gate -- see this script's own module docstring for why the matching "
        "heuristic has real false positives and false negatives."
    )

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    return 1 if total_untested or n_errored else 0


if __name__ == "__main__":
    raise SystemExit(main())
