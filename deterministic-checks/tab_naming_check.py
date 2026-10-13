"""Tab-naming/position check: does a judge.toml criterion that names a specific tab at a
specific position in a golden workbook actually match the workbook's real sheet order?

Why this exists: a rubric criterion of the shape "Analysis tab is 2nd from left Expected:
Analysis 2nd." is a claim about the GOLDEN answer's own structure, not about the solver's
output -- if the golden workbook itself doesn't have a tab named "Analysis" in 2nd position,
the criterion is unpassable by construction, no matter what a solver produces. Nothing else in
this folder catches this: formula_health_check.py recomputes formula values and never looks at
sheet name/order, duplicate_criterion_check.py looks at criterion IDs on an xlsx rubric sheet
not at judge.toml text, and deliverable_filename_check.py checks whether instruction.md names
the right FILE, not whether a golden workbook's TABS are named/ordered the way a criterion
describing them claims. This script reads the criterion text, reads the actual golden
workbook's actual sheet order, and reports where they disagree -- a purely mechanical,
deterministic check with zero LLM cost.

Provenance: authored directly for this folder (not extracted from a pre-existing scratch
file). It reuses formula_health_check.py's task/file discovery and golden-file-resolution
logic verbatim via `import formula_health_check as health` -- the same pattern
formula_cache_autofix.py already uses -- so which file on disk counts as "the golden workbook"
for a given judge.toml files=[...] entry (including the documented xlsm<->xlsx conversion-shim
case) can never silently drift between this check and the health check. `load_judge_criteria()`
is reused unchanged for the same reason. Everything else (the tab-naming/position text parser,
the sheet-order reader, the match logic) is new.

Status: new. Verified against three confirmed real defects on SVC-PC-65-*, five confirmed real
defects on SVC-PC-44-*, and one clean negative-control task (SVC-PC-3-9-0, which has tab-order
criteria but none naming a specific tab at a specific ordinal position) -- see this script's own
accompanying verification run. Not yet run at full scale across every task in the pipeline; the
text-pattern parser is a heuristic (see Known limits) and should be spot-checked as it meets new
phrasings.

Usage:
    python tab_naming_check.py <TASK-ID> [<TASK-ID> ...] --root <path-to-task-dirs> --out report.json
    python tab_naming_check.py --all --root <path-to-task-dirs> --out report.json
    python tab_naming_check.py --all --root <path> --id-prefix SVC-PC- --out report.json

What it does, in order:

1. For a given task id (or --all tasks under --root), loads every [[criterion]] across every
   tests/deliverables_*/judge.toml (via health.load_judge_criteria -- tomllib, never regex).
2. Scans each criterion's description text for a tab-position/tab-naming claim: an ordinal
   word or digit form (1st/first .. 8th/eighth, or "last") appearing near the word "tab", OR
   the literal shape "tab position N of M". A description with no such signal is not a
   candidate at all and is skipped entirely -- e.g. "Cover tab present", "No hidden tabs or
   rows", and "Tabs in a coherent agreed order" all mention tabs but make no ordinal claim, so
   none of them are in scope for this check.
3. For each candidate, splits the description on its own "Expected: ..." marker (the same
   authoring convention every criterion in this pipeline uses) and extracts, preferring the
   cleaner Expected-side text and falling back to the claim-side text:
     - the claimed ordinal position (e.g. "2nd" -> 2, "last" -> the final sheet, or an explicit
       "tab position N of M" -> N, with M recorded as a sanity cross-check on sheet count)
     - a literal tab-name candidate: a short capitalized phrase sitting immediately next to
       "tab" or immediately next to the ordinal (e.g. "Analysis tab" / "Summary 2nd" both
       yield "Analysis" / "Summary"). Generic filler ("the", "this", "second", "next", "main",
       ...) is rejected as a non-name.
     - whether the description itself says the name is flexible ("whatever it is named", "does
       not need to be literally titled/named", "task-specific name", "satisfies this the same
       as") -- these are real criteria in the source pipeline, deliberately written so a
       deliverable-specific tab name is acceptable. This script still reports the position and
       the actual name found there, but never asserts a name MISMATCH against a flexible-name
       criterion -- there is no fixed name to be wrong about.
4. Resolves that criterion's judge.files=[...] entries against what's actually on disk via
   health.resolve_graded_files (same xlsm<->xlsx shim awareness formula_health_check.py has),
   keeps only the spreadsheet entries, and reads each one's REAL sheet name order straight from
   its xl/workbook.xml (via zipfile -- no full openpyxl load needed for this), falling back to
   openpyxl.load_workbook(read_only=True) if the fast path fails for any reason. Each sheet
   element's `state` attribute (visible/hidden/veryHidden) is carried through for transparency;
   position counting here is over ALL sheets in stored order (see Known limits).
5. Compares the claimed name (if any and not flexible) against the actual sheet name at the
   claimed position (exact match, substring either direction, or >=4-letter token overlap all
   count as a match -- this is deliberately lenient so e.g. "Analysis" matching an actual
   "Analysis_v2" is not a false mismatch). Every candidate criterion is recorded either way;
   only a real MISMATCH -- a resolvable position, a fixed (non-flexible) name, and no match
   found -- is written to result["findings"] and fails that task.
6. Writes one JSON result per task (status: pass|fail, every candidate criterion examined with
   its resolution, and the actual full sheet order of every golden file touched) plus an
   aggregate report across every task given on the command line (or discovered via --all).

Known limits, disclosed rather than silently dropped:
    - The description-text parser is a set of regexes over free-form rubric prose, not a formal
      grammar. A phrasing this script has not seen (e.g. "from right", multi-clause claims
      naming two different tabs in one criterion, an ordinal spelled out unusually) can produce
      an `unresolved` or `ambiguous` result rather than a silent wrong answer, but it can also
      simply fail to recognize the criterion as a candidate at all -- a `false negative` here
      means this check found nothing to say, not that the tab is confirmed correct.
    - Position counting is over every sheet stored in workbook.xml order, hidden ones included.
      A criterion that means "2nd VISIBLE tab" with a hidden sheet sitting in an earlier slot
      will not be distinguished from "2nd tab overall" -- the `state` field on every entry in
      `actual_sheets` is there so a human can spot this at a glance.
    - "from right" position claims are not specially handled (none were observed in the source
      pipeline's phrasing at authoring time) -- a criterion using that phrase is still scanned,
      but its position is resolved as if counted from the left, which is wrong for a true
      from-right claim. Flagged in the finding's own text via `from_right_claim: true` rather
      than silently mis-resolved with no trace.
    - The name-match heuristic (substring / token overlap) is lenient by design to avoid
      penalizing a reasonable variant spelling -- it is not proof of a correct name, only
      evidence against an obvious wrong one. A `match: true` result is not a claim that the tab
      name is exactly what a strict reading of the criterion would require.
    - This script analyzes the CURRENT on-disk state of solution/ under --root. It says nothing
      about whether a task was broken in the past and has since been fixed by other work, and
      nothing about environment/initial_workspace/ or any file outside solution/.

EKW port (2026-09-14): everything above this paragraph describes the original SVC-PC-only
script and is unchanged in behaviour. `_has_svc_pc_config()` and `load_criteria_for_task()`
(new, just above `analyze_task()`) are the only addition: format detection dispatches to
`health.load_judge_criteria()` for SVC-PC's `tests/deliverables_*/judge.toml`, or
`ekw_verifier_json.load_ekw_criteria()` for EKW's `tests/verifier.json` -- both already return
the identical {group, name, description, weight, type, files} shape, so the tab-position/
tab-naming text parser, the golden-file resolution (`health.resolve_graded_files`, unchanged --
it already walks all of `solution/` recursively by basename, which covers EKW's
`solution/golden_outputs/<file>` layout with no modification needed), and the sheet-order
comparison all run unchanged regardless of which config file produced the criteria.
`analyze_task()` calls `load_criteria_for_task()` instead of `health.load_judge_criteria()`
directly and records which format was used as `result["format"]` ("svc_pc" or "ekw", matching
the convention `judge_criterion_name_duplicate_check.py`'s own EKW port already established).
SVC-PC detection (`tests/deliverables_*/judge.toml`, the exact glob `load_judge_criteria`
itself uses) takes precedence over EKW detection, so an SVC-PC task's behaviour cannot change
even in the unobserved case where both shapes exist in one task dir.

Whether this check's detection pattern actually occurs in EKW: scanned all 5,596 rubric
prompts across all 274 real tasks at `C:\\ekwqc\\_merged274\\files` directly (not assumed) for
the same tab+ordinal signal `extract_tab_naming_claim()` gates on. 87 prompts (1.6%) mention
"tab" at all, and of those exactly 1 (task_37/v17, "a second distinct tab presenting a
tentative 30-day forward-looking forecast") matches the ordinal-near-"tab" regex -- and even
that one is not the pattern this check exists to catch: it is a claim that two distinct tabs
exist, not a claim that a SPECIFIC named tab sits at a SPECIFIC ordinal position (SVC-PC's
"Analysis tab is 2nd from left. Expected: Analysis 2nd." shape). EKW's rubric-authoring
convention describes values, control totals, and structural/scope conditions in prose
("PASS only if the workbook reports a total of $160.65...", "PASS if the workbook contains
clearly named analytical tabs covering at least Dashboard, Channel Disposition..."), not
SVC-PC's "tab at ordinal position, Expected: <name> <ordinal>" authoring shape. Structurally,
this check's detection signal does not occur in EKW's rubric style -- zero real findings are
expected from the EKW branch across the current 274-task corpus, and a `0 fail` result from an
`--all` run over EKW tasks is a confirmation of that absence, not evidence the port is a no-op:
the branch is still live and will fire correctly if a future EKW task's rubric prose ever
starts naming an ordinal tab position the way SVC-PC's does.
"""

import argparse
import html
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Windows console defaults to cp1252, which can't encode every character that shows up in a
# real task's judge.toml or golden workbook (curly quotes, arrows in a "Source Files ->" tab
# name, etc). Force UTF-8 with replacement so a printable-but-non-cp1252 character never
# crashes a batch run partway through.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

# Reuse the health check's own task/file discovery, judge.toml parsing, and golden-file
# resolution (including xlsm<->xlsx shim awareness) verbatim, so "which file on disk is the
# golden for this criterion" can never silently drift between the two checks. See module
# docstring.
import formula_health_check as health  # noqa: E402
from ekw_verifier_json import has_ekw_config, load_ekw_criteria  # noqa: E402

try:
    import openpyxl
except ImportError:  # pragma: no cover
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl


# ---------------------------------------------------------------------------
# description-text parsing
# ---------------------------------------------------------------------------

ORDINAL_WORDS = {
    "1st": 1,
    "first": 1,
    "2nd": 2,
    "second": 2,
    "3rd": 3,
    "third": 3,
    "4th": 4,
    "fourth": 4,
    "5th": 5,
    "fifth": 5,
    "6th": 6,
    "sixth": 6,
    "7th": 7,
    "seventh": 7,
    "8th": 8,
    "eighth": 8,
}
_ORDINAL_ALT = "|".join(sorted(ORDINAL_WORDS, key=len, reverse=True))

ORDINAL_RE = re.compile(rf"\b({_ORDINAL_ALT}|last)\b", re.IGNORECASE)

# The gate: is this criterion even a tab-position candidate at all? An ordinal near the word
# "tab" in either order, or the literal "tab position N of M" shape.
TAB_NEAR_ORDINAL_RE = re.compile(
    rf"\btab\b(?:(?!\btab\b).){{0,30}}\b({_ORDINAL_ALT}|last)\b"
    rf"|\b({_ORDINAL_ALT}|last)\b(?:(?!\btab\b).){{0,30}}\btab\b",
    re.IGNORECASE | re.DOTALL,
)
TAB_POSITION_OF_RE = re.compile(r"\btab position\s+(\d+)\s+of\s+(\d+)\b", re.IGNORECASE)
FROM_RIGHT_RE = re.compile(r"\bfrom\s+right\b", re.IGNORECASE)

FLEXIBLE_NAME_RE = re.compile(
    r"whatever it is named"
    r"|does not need to be literally"
    r"|need not be literally"
    r"|task-specific name"
    r"|satisfies this the same as",
    re.IGNORECASE,
)

EXPECTED_SPLIT_RE = re.compile(r"\bExpected:\s*", re.IGNORECASE)
MUST_PASS_RE = re.compile(r"\s*This is a must-pass criterion\.?\s*$", re.IGNORECASE)

# A short phrase sitting immediately before the word "tab", REQUIRED to start with a capital
# letter. Every real tab-name mention in the source pipeline's own authoring is Title Case
# ("Analysis tab", "Summary tab", "Executive Summary tab", "Source Files divider tab"); every
# generic/descriptive mention that is NOT a literal name ("the first tab", "a clearly-labeled
# summary tab", "the rate table ... first tab") starts lowercase. Requiring the leading capital
# is what keeps this regex from grabbing filler words like "as the first" as if they were a tab
# name -- without it, the greedy word-count backtracking happily walks past lowercase prose to
# find the nearest "tab" token. Subsequent words in the phrase may be any case (e.g. the second
# word of "Exec Summary").
NAME_BEFORE_TAB_RE = re.compile(
    r"\b([A-Z][\w&/\-]*(?:\s+[A-Za-z][\w&/\-]*){0,2})\s+(?i:tab)\b"
)
# A short phrase sitting at the very start of a segment, immediately before an ordinal (with an
# optional "tab"/"is" in between) -- covers the terse "Analysis 2nd." / "Summary tab 2nd." shape
# the Expected-side text almost always uses. Same leading-capital requirement and rationale as
# NAME_BEFORE_TAB_RE; the ordinal word itself stays case-insensitive via the scoped (?i:...).
NAME_BEFORE_ORDINAL_RE = re.compile(
    rf"^\s*([A-Z][\w&/\-]*(?:\s+[A-Za-z][\w&/\-]*){{0,2}}?)\s+(?:(?i:tab)\s+)?(?:(?i:is)\s+)?"
    rf"(?i:{_ORDINAL_ALT}|last)\b"
)

GENERIC_NAME_WORDS = {
    "the",
    "this",
    "that",
    "a",
    "an",
    "second",
    "first",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "next",
    "final",
    "last",
    "named",
    "main",
    "each",
    "every",
    "workbook",
    "workbook's",
    # common sentence-initial report-verbs a criterion uses to describe a tab's ROLE rather
    # than to name it ("Identifies the first tab ... as the rate table", "Presents the rate
    # table as the first tab ..."). These are real, observed false-positive sources: capitalized
    # only because they open the sentence, not because they are a proper tab name.
    "identifies",
    "presents",
    "states",
    "shows",
    "confirms",
    "includes",
    "provides",
    "documents",
    "reflects",
    "establishes",
    "demonstrates",
    "verifies",
    "describes",
    "reports",
    "occupies",
    "represents",
    "lists",
    "summarizes",
    "captures",
    "outlines",
    "details",
    "notes",
    "flags",
    "contains",
}


def split_description(description):
    """Split on the criterion's own "Expected: ..." marker. Returns (claim, expected); expected
    is "" if the description has no such marker (seen on a few older-style criteria)."""
    text = (description or "").strip()
    parts = EXPECTED_SPLIT_RE.split(text, maxsplit=1)
    claim = parts[0].strip()
    expected = MUST_PASS_RE.sub("", parts[1]).strip() if len(parts) > 1 else ""
    return claim, expected


def clean_name_candidate(raw):
    """Strip a trailing/embedded "tab" token, then trim (never reject piecemeal) leading and
    trailing generic filler words ("A Cover" -> "Cover", "the first" -> would already have been
    excluded by NAME_BEFORE_TAB_RE's leading-capital requirement before reaching here). Returns
    None only if nothing but filler remains."""
    name = re.sub(r"\btab\b", "", raw, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", name).strip(" -/")
    if not name:
        return None
    words = name.split(" ")

    def is_generic(w):
        return re.sub(r"[^a-z0-9']", "", w.lower()) in GENERIC_NAME_WORDS

    while words and is_generic(words[0]):
        words.pop(0)
    while words and is_generic(words[-1]):
        words.pop()
    if not words:
        return None
    return " ".join(words)


def find_all_name_candidates(text):
    """Every distinct literal tab name mentioned near the word "tab" anywhere in the combined
    claim+expected text, lowercased for comparison. Used to detect a compound criterion that
    names more than one tab (e.g. "A Cover tab and an Executive Summary tab are present
    (summary 2nd)") -- a single regex pass has no reliable way to attribute a position claim
    buried elsewhere in such a sentence to the RIGHT one of several named tabs, so this check
    treats that shape as ambiguous rather than silently picking whichever name the leftmost
    match happens to find."""
    names = set()
    for m in NAME_BEFORE_TAB_RE.finditer(text or ""):
        cand = clean_name_candidate(m.group(1))
        if cand:
            names.add(cand.lower())
    return names


def extract_literal_name(segment):
    if not segment:
        return None
    m = NAME_BEFORE_TAB_RE.search(segment)
    if m:
        cand = clean_name_candidate(m.group(1))
        if cand:
            return cand
    m = NAME_BEFORE_ORDINAL_RE.match(segment.strip())
    if m:
        cand = clean_name_candidate(m.group(1))
        if cand:
            return cand
    return None


def extract_tab_naming_claim(description):
    """Returns None if this description makes no tab-position/tab-naming claim at all (the vast
    majority of criteria -- most mentions of "tab" are about presence, formatting, or color, not
    position). Otherwise returns a dict describing the claim, best-effort:
        raw_claim, raw_expected   : the two description halves this was parsed from
        position                  : int (1-based) or "last" or None if unresolved
        position_source           : "tab_position_of" | "ordinal" | None
        total_hint                : int or None -- the M in an explicit "N of M" claim
        from_right_claim          : bool -- "from right" language seen (see Known limits)
        ambiguous_position        : bool -- more than one distinct ordinal value found in the
                                     combined text (claim-side and expected-side disagree)
        name                      : str or None -- the literal tab name claimed, if any
        ambiguous_name             : bool -- more than one distinct tab name is mentioned in this
                                     criterion's text (a compound criterion); `name` is forced to
                                     None in this case rather than guessing which one the
                                     position claim was about
        flexible_name             : bool -- description itself says any deliverable-specific
                                     name is acceptable at this position
    """
    claim, expected = split_description(description)
    full_text = f"{claim} {expected}".strip()
    if not full_text:
        return None

    has_signal = bool(
        TAB_NEAR_ORDINAL_RE.search(full_text) or TAB_POSITION_OF_RE.search(full_text)
    )
    if not has_signal:
        return None

    flexible_name = bool(FLEXIBLE_NAME_RE.search(full_text))
    from_right_claim = bool(FROM_RIGHT_RE.search(full_text))

    position = None
    position_source = None
    total_hint = None

    m = TAB_POSITION_OF_RE.search(full_text)
    if m:
        position = int(m.group(1))
        total_hint = int(m.group(2))
        position_source = "tab_position_of"
    else:
        for segment in (expected, claim):
            om = ORDINAL_RE.search(segment)
            if om:
                token = om.group(1).lower()
                position = "last" if token == "last" else ORDINAL_WORDS[token]
                position_source = "ordinal"
                break

    ordinal_values = set()
    for tok in ORDINAL_RE.findall(full_text):
        tok = tok.lower()
        ordinal_values.add("last" if tok == "last" else ORDINAL_WORDS[tok])
    ambiguous_position = position_source == "ordinal" and len(ordinal_values) > 1

    distinct_names = find_all_name_candidates(full_text)
    ambiguous_name = len(distinct_names) > 1
    name = (
        None
        if ambiguous_name
        else (extract_literal_name(expected) or extract_literal_name(claim))
    )

    return {
        "raw_claim": claim,
        "raw_expected": expected,
        "position": position,
        "position_source": position_source,
        "total_hint": total_hint,
        "from_right_claim": from_right_claim,
        "ambiguous_position": ambiguous_position,
        "name": name,
        "ambiguous_name": ambiguous_name,
        "flexible_name": flexible_name,
    }


# ---------------------------------------------------------------------------
# golden workbook sheet-order reading
# ---------------------------------------------------------------------------

SHEET_ELEM_RE = re.compile(r"<sheet\b[^>]*/?>", re.IGNORECASE)
ATTR_RE = re.compile(r'(\w[\w:]*)="([^"]*)"')


def _parse_workbook_xml(xml_text):
    sheets = []
    for elem in SHEET_ELEM_RE.findall(xml_text):
        attrs = dict(ATTR_RE.findall(elem))
        name = html.unescape(attrs.get("name", ""))
        if not name:
            continue
        sheets.append({"name": name, "state": attrs.get("state", "visible")})
    return sheets


def read_sheet_order(path):
    """Returns (sheets, source, error) where sheets is a list of {"name", "state"} dicts in
    real on-disk tab order, or None on failure. source is "workbook_xml" (the fast zipfile
    path) or "openpyxl" (fallback). Never raises."""
    try:
        with zipfile.ZipFile(path) as z:
            xml_text = z.read("xl/workbook.xml").decode("utf-8", errors="replace")
        sheets = _parse_workbook_xml(xml_text)
        if sheets:
            return sheets, "workbook_xml", None
    except (KeyError, zipfile.BadZipFile, OSError) as e:
        fast_err = str(e)
    else:
        fast_err = "xl/workbook.xml parsed to zero <sheet> elements"

    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        try:
            hidden_by_name = {}
            for ws in wb.worksheets:
                hidden_by_name[ws.title] = ws.sheet_state
            sheets = [
                {"name": n, "state": hidden_by_name.get(n, "visible")}
                for n in wb.sheetnames
            ]
        finally:
            wb.close()
        return sheets, "openpyxl", None
    except Exception as e:
        return (
            None,
            None,
            f"workbook.xml path failed ({fast_err}); openpyxl fallback also failed: {e}",
        )


# ---------------------------------------------------------------------------
# claim <-> actual matching
# ---------------------------------------------------------------------------


def resolve_position_index(position, n_sheets, from_right_claim):
    """1-based index into the sheet list, or None if unresolvable/out of range."""
    if position is None or n_sheets == 0:
        return None
    if position == "last":
        return n_sheets
    if not isinstance(position, int) or not (1 <= position <= n_sheets):
        return None
    if from_right_claim:
        idx = n_sheets - position + 1
        return idx if 1 <= idx <= n_sheets else None
    return position


def names_match(expected_name, actual_name):
    if not expected_name or not actual_name:
        return None
    e = expected_name.strip().lower()
    a = actual_name.strip().lower()
    if e == a or e in a or a in e:
        return True
    e_tokens = {w for w in re.findall(r"[a-z0-9]+", e) if len(w) >= 4}
    a_tokens = {w for w in re.findall(r"[a-z0-9]+", a) if len(w) >= 4}
    if e_tokens and (e_tokens & a_tokens):
        return True
    return False


# ---------------------------------------------------------------------------
# format detection: SVC-PC judge.toml vs EKW verifier.json
# ---------------------------------------------------------------------------


def _has_svc_pc_config(task_dir):
    """True if this task has at least one tests/deliverables/judge.toml or
    tests/deliverables_*/judge.toml -- the same two-glob union health.load_judge_criteria()
    itself uses, so detection can never disagree with what that loader would actually find.

    2026-09-16 fix (tracker row 20): this docstring's own invariant was violated until now --
    this function kept its OWN locally duplicated `deliverables_*`-only glob rather than
    actually matching load_judge_criteria()'s pattern, so the two silently drifted out of sync
    the moment load_judge_criteria() gained the plain-`deliverables` variant. Confirmed real:
    for any of the 89/600 real tasks using plain `tests/deliverables/judge.toml` naming, this
    function returned False, so load_criteria_for_task() below never even called
    health.load_judge_criteria() for them -- it fell through to the EKW branch, which also
    returned nothing, silently treating a real SVC-PC task as format "none". Fixing
    load_judge_criteria() alone does NOT fix this: the two are independent glob calls, not one
    shared function, despite this docstring's claim."""
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return False
    return any(tests_dir.glob("deliverables/judge.toml")) or any(
        tests_dir.glob("deliverables_*/judge.toml")
    )


def load_criteria_for_task(task_dir):
    """Format-dispatching wrapper around health.load_judge_criteria() (SVC-PC) and
    ekw_verifier_json.load_ekw_criteria() (EKW). Both loaders already return the identical
    {group, name, description, weight, type, files} shape, so this function is the entire EKW
    port for this check: everything downstream in analyze_task (the tab-position/tab-naming
    text parser, health.resolve_graded_files, the sheet-order comparison) consumes that shape
    without knowing or caring which config file it came from.

    Precedence: SVC-PC's tests/deliverables_*/judge.toml wins whenever it exists, so this port
    cannot change SVC-PC behaviour for any task that already has one, even in the unobserved
    case where a task dir somehow carries both shapes. A task with neither shape falls through
    to health.load_judge_criteria, which returns [] for a missing tests/ dir -- unchanged
    pre-port behaviour, not a new code path.

    Returns (criteria, format) where format is "svc_pc", "ekw", or "none".
    """
    if _has_svc_pc_config(task_dir):
        return health.load_judge_criteria(task_dir), "svc_pc"
    if has_ekw_config(task_dir):
        return load_ekw_criteria(task_dir), "ekw"
    return health.load_judge_criteria(task_dir), "none"


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir):
    task_id = task_dir.name
    criteria, config_format = load_criteria_for_task(task_dir)
    shim_scripts = health.detect_conversion_shim(task_dir)
    graded_file_resolution = health.resolve_graded_files(
        task_dir, criteria, shim_scripts
    )
    resolved_by_expected = {r["expected"]: r for r in graded_file_resolution}

    result = {
        "task_id": task_id,
        "format": config_format,
        "solution_dir_exists": (task_dir / "solution").is_dir(),
        "conversion_shim": {"detected": bool(shim_scripts), "scripts": shim_scripts},
        "checked_criteria": [],
        "findings": [],
        "errors": [],
    }

    sheet_cache = {}  # abs path (str) -> (sheets, source, error)

    def get_sheets(abs_path):
        key = str(abs_path)
        if key not in sheet_cache:
            sheet_cache[key] = read_sheet_order(abs_path)
        return sheet_cache[key]

    for c in criteria:
        claim = extract_tab_naming_claim(c.get("description") or "")
        if claim is None:
            continue

        expected_files = c.get("files") or []
        xlsx_expected = [
            f
            for f in expected_files
            if Path(f).suffix.lower() in health.SPREADSHEET_SUFFIXES
        ]

        entry = {
            "group": c.get("group"),
            "criterion_name": c.get("name"),
            "description": c.get("description"),
            "claim": {k: v for k, v in claim.items() if not k.startswith("raw_")},
            "files_checked": [],
        }

        if not xlsx_expected:
            entry["status"] = "not_applicable"
            source_label = (
                "verifier.json's source.file"
                if config_format == "ekw"
                else "judge.toml [judge].files"
            )
            entry["reason"] = (
                f"this criterion's {source_label}=[...] names no .xlsx/.xlsm -- "
                "nothing for this check to open"
            )
            result["checked_criteria"].append(entry)
            continue

        for expected_path in xlsx_expected:
            resolved = resolved_by_expected.get(expected_path)
            file_entry = {"expected_path": expected_path}
            if not resolved or not resolved.get("actual"):
                file_entry["status"] = "file_not_found"
                file_entry["note"] = (
                    resolved["note"]
                    if resolved
                    else "not present in graded_file_resolution"
                )
                entry["files_checked"].append(file_entry)
                continue

            actual_rel = resolved["actual"]
            file_entry["actual_path"] = actual_rel
            abs_path = task_dir / actual_rel
            sheets, source, err = get_sheets(abs_path)
            if sheets is None:
                file_entry["status"] = "unreadable"
                file_entry["error"] = err
                entry["files_checked"].append(file_entry)
                result["errors"].append(f"{actual_rel}: {err}")
                continue

            file_entry["sheet_read_source"] = source
            file_entry["actual_sheets"] = sheets
            n = len(sheets)
            if claim["total_hint"] is not None and claim["total_hint"] != n:
                file_entry["total_hint_mismatch"] = (
                    f"criterion implies {claim['total_hint']} tabs; workbook actually has {n}"
                )

            idx = resolve_position_index(
                claim["position"], n, claim["from_right_claim"]
            )
            if claim["ambiguous_position"]:
                file_entry["status"] = "ambiguous"
                file_entry["note"] = (
                    "more than one distinct ordinal value found in this criterion's own "
                    "description text -- not confident enough to assert a position"
                )
            elif idx is None:
                file_entry["status"] = "unresolved"
                file_entry["note"] = (
                    f"claimed position {claim['position']!r} could not be resolved against "
                    f"{n} actual sheet(s)"
                )
            else:
                actual_at_position = sheets[idx - 1]
                file_entry["resolved_position"] = idx
                file_entry["actual_name_at_position"] = actual_at_position["name"]
                file_entry["actual_state_at_position"] = actual_at_position["state"]
                if not claim["name"] or claim["flexible_name"]:
                    file_entry["status"] = "position_only"
                    if claim["flexible_name"]:
                        file_entry["note"] = (
                            "flexible-name criterion (description explicitly allows a "
                            "deliverable-specific tab name) -- position and actual name "
                            "reported for review, no name comparison asserted"
                        )
                    elif claim["ambiguous_name"]:
                        file_entry["note"] = (
                            "this criterion names more than one tab -- cannot confidently "
                            "attribute the claimed position to a single one of them -- "
                            "position and actual name reported for review only"
                        )
                    else:
                        file_entry["note"] = (
                            "no literal tab name could be extracted from this criterion's "
                            "text -- position and actual name reported for review only"
                        )
                else:
                    match = names_match(claim["name"], actual_at_position["name"])
                    file_entry["expected_name"] = claim["name"]
                    file_entry["name_match"] = match
                    if match:
                        file_entry["status"] = "match"
                    else:
                        file_entry["status"] = "mismatch"
                        finding = {
                            "file": actual_rel,
                            "group": c.get("group"),
                            "criterion_name": c.get("name"),
                            "description": c.get("description"),
                            "expected_name": claim["name"],
                            "expected_position": claim["position"],
                            "resolved_position": idx,
                            "actual_name_at_position": actual_at_position["name"],
                            "actual_sheet_order": [s["name"] for s in sheets],
                        }
                        result["findings"].append(finding)

            entry["files_checked"].append(file_entry)

        statuses = {f["status"] for f in entry["files_checked"]}
        entry["status"] = (
            "mismatch"
            if "mismatch" in statuses
            else (sorted(statuses)[0] if statuses else "not_applicable")
        )
        result["checked_criteria"].append(entry)

    result["status"] = "fail" if result["findings"] else "pass"
    result["summary"] = {
        "n_candidate_criteria": len(result["checked_criteria"]),
        "n_findings": len(result["findings"]),
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Check every judge.toml tab-position/tab-naming criterion against the "
        "actual sheet order of the task's golden workbook."
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
        help="when using --all, only treat subdirectories starting with this prefix as tasks "
        "(default: empty, i.e. every subdirectory is treated as a task)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
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
            r = analyze_task(task_dir)
        except Exception as e:  # never let one task's crash kill the whole batch
            r = {
                "task_id": task_dir.name,
                "status": "fail",
                "errors": [f"unhandled exception analyzing this task: {e}"],
                "checked_criteria": [],
                "findings": [],
                "summary": {"n_candidate_criteria": 0, "n_findings": 0},
            }
        results.append(r)
        print(
            f"    -> {r['status']}  "
            f"({r.get('summary', {}).get('n_candidate_criteria', 0)} candidate criteria, "
            f"{r.get('summary', {}).get('n_findings', 0)} findings)",
            file=sys.stderr,
        )

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
        print(
            f"  {r['task_id']}: {r['status']}  [{r.get('summary', {}).get('n_findings', 0)} findings]"
        )
        for finding in r.get("findings", []):
            print(
                f"      ! {finding['file']} [{finding['group']}/{finding['criterion_name']}]: "
                f"expected '{finding['expected_name']}' at position {finding['resolved_position']}, "
                f"actual is '{finding['actual_name_at_position']}'"
            )
        for e in r.get("errors", []):
            print(f"      x {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
