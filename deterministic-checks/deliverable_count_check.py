"""Deliverable count check: does a task's solver-facing "Deliverables:" prose name more
distinct artifacts than its "Graded deliverable filenames" section will ever actually check
for existence?

Why this exists: a Harbor task's instruction.md typically carries two things -- a prose
description of what the solver should produce (often under a "Deliverables:" label) and a
"Graded deliverable filenames" section naming the literal file(s) the pipeline will look for at
grading time. When the prose promises more separate artifacts than the filenames section
enumerates -- "a workbook, a driver-choices note, AND a Slack draft to the VP" but only one
filename is ever graded -- the solver has no way to know two of those three deliverables are
never checked for existence at all. This is a purely mechanical, deterministic text-shape check
for that one defect: zero LLM cost, no judge.toml required (a judge.toml files= cross-check is
included when one is present, as a bonus corroboration, not a requirement).

Provenance: built fresh for this folder (harbor-qc-checks), matching the CLI conventions and
docstring style of formula_health_check.py and deliverable_filename_check.py in this same
directory. Calibrated in two widening passes against the SVC-PC-* pool
(C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready\\, 600 tasks total), not just the 3
tasks named in this script's own required verification run:
  Pass 1 -- every one of the 22 tasks that carries a "Deliverables:" label in instruction.md,
  read by hand. This surfaced the SVC-PC-6-*-0 Series-B data-room family: a numbered
  "Deliverables: 1. ... 2. ... 3. ..." list where items 2/3/4 are terse noun-phrase headers for
  tabs, registers, or "open-item intake rows" that fold into the SAME single graded workbook,
  not separate ungraded artifacts. A naive count of numbered-list items would have flagged every
  one of those tasks. Guards 1 and 2 below come from this pass.
  Pass 2 -- a full `--all` run over all 600 tasks (most have no "Deliverables:" label at all and
  correctly skip). The 22-task hand sample was too small to expose three more real bugs, each
  found by reading the actual flagged output rather than assuming the 22-task calibration
  generalized: a bare comma-before-filename appositive ("a workbook, `File.xlsx`.", ~3 dozen
  tasks), a dash-introduced elaboration clause re-using "the X, the Y" for one file's contents
  (SVC-PC-45-2-0), and a "this deliverable:" boilerplate phrase that isn't a deliverables list at
  all (all eight SVC-PC-47-*-0 tasks plus SVC-PC-80-2-0). Guards 3 and 4 below, and the
  indefinite-article narrowing in guard 1, come from this pass. Final state on the full 600-task
  corpus: 89 pass / 6 fail / 505 skip, 0 unhandled exceptions -- see "How this avoids false
  positives" for why each of the 6 remaining flags looks like a genuine candidate, not a bug.

Status: v1, calibrated against the full 600-task corpus at build time (not a sample). "Full
corpus" here means every task this script's own eligibility logic could reach, not that a human
re-read all 600 instruction.md files by hand -- the 484 that skip were read by the script, not
independently re-verified one by one.

Usage:
    python deliverable_count_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python deliverable_count_check.py --all --root <path> --out report.json
    python deliverable_count_check.py --all --root <path> --id-prefix MYBENCH- --out report.json

What it does, in order:

1. For a given task id (or --all tasks under --root), reads instruction.md and locates a
   "Deliverables:" (or "Produce N deliverables:", "Required deliverables:", etc -- anything
   matching the word "deliverable(s)" immediately followed by a colon) marker. A task with no
   such marker is marked "skip" -- this check has nothing to verify, which is NOT itself a claim
   the task is fine.
2. Extracts the text after that marker up to the "## Graded deliverable filenames" heading (or
   the next markdown heading, or a trailing unrelated sentence in the same paragraph -- see
   `extract_deliverables_block`). Detects whether that text is a numbered list ("1. ... 2. ..."),
   a bulleted list ("- ..." / "* ..."), or inline prose ("X, Y, and Z").
3. Splits the block into candidate items (numbered/bulleted: one item per marker; inline: split
   on semicolons, on ", and a/an/the ..." boundaries, and on the start of any literal filename
   mention -- see `split_inline_block`) and classifies each candidate against the two guards
   below (`classify_item`) to decide whether it counts as a distinct, separately-claimed
   deliverable.
4. Separately parses the "## Graded deliverable filenames" section (a heading containing
   "deliverable" and "filenames", case-insensitive) for its bulleted, backtick-quoted filename
   list, and counts them. When a tests/*/judge.toml is present, its [judge].files entries are
   ALSO collected purely as a corroborating filename-count cross-check (never as the primary
   count, and only the files= path list is read -- criterion text, which can carry the answer
   key, is never touched).
5. Flags a mismatch when the counted prose-item total exceeds the graded-filename total. Writes
   one JSON result per task (status: pass|fail|skip, both item lists, both counts, the judge.toml
   cross-check) plus an aggregate report across every task given on the command line (or
   discovered via --all).

How this avoids false positives (four guards, spread across three functions -- see the
Provenance note above for which calibration pass found each one):
    - Guard 1, eligibility (`classify_item`, via ARTICLE_START_RE): a candidate item counts only
      if it opens with an INDEFINITE article ("a"/"an" -- deliberately not "the", see below) or
      contains a literal filename-like token (`name.xlsx`, `name.docx`, etc). A terse noun-phrase
      header with neither -- "Articulation and source tie-out schedule.", "Open-item intake rows
      for unresolved planning assumptions." -- does NOT count. This is deliberately the same
      shape every genuine top-level deliverable in the calibration set was phrased in ("a short
      note on your driver choices", "a Slack draft to VP Finance", "a People and Organizational
      Readiness Report"), while every sub-component filler line in the SVC-PC-6-*-0 family lacked
      it. "The" is excluded on purpose: "the X" reads as a definite, already-scoped reference,
      almost always to an internal content of the ONE artifact an earlier "a/an" item just
      introduced -- "a note with the certification scope table, the wording review by surface,
      and the open counsel questions" (SVC-PC-56-4-0) is one note with three named contents, not
      four deliverables. A "the X" item that legitimately IS its own file still counts regardless,
      via its filename mention.
    - Guard 2, sub-component exclusion (`classify_item`, via EXCLUSION_RE): even an eligible item
      is dropped if its text contains tab(s), section(s), worksheet(s), sheet(s), register(s),
      log(s), row(s), intake, or column(s) -- words that read as "this is part of another file"
      rather than "this is its own file". "Master Open Items List tab labeled Open Items
      Register" is excluded on both "tab" and "register" even though it happens to open with a
      capitalized noun.
    - Guard 3, bare-filename appositive merge (`split_inline_block`): a comma-introduced item
      that, once markdown `**`/`` ` `` decoration and trailing punctuation are stripped, is
      NOTHING but a filename token gets MERGED into the item right before it rather than counted
      on its own -- "Deliverable: a single formula-driven workbook,
      **`Email_Performance_Baseline.xlsx`**." is one deliverable named twice (once as a noun,
      once as a filename), not two. Roughly three dozen tasks in the calibration pool phrase
      their single deliverable exactly this way. The merge is keyed off the SEPARATOR, not just
      the item's shape, so it never fires across a semicolon boundary: "`A.docx`; `B.xlsx`;
      `C.docx`" (SVC-PC-55-0-0) is a genuine three-item list and each bare filename there still
      counts on its own. A trailing dash-elaboration clause ("`File.docx` -- the X, the Y, and
      the Z.") gets the same treatment for the same reason: carved off before splitting and
      reattached whole, so its own internal "the X, the Y" enumeration is never mistaken for
      three more top-level deliverables (SVC-PC-45-2-0). A named file that DOES carry other
      descriptive words directly alongside it in the same comma-delimited clause
      ("Engineering_Delivery_Analysis.xlsx containing the supporting sprint-level analysis...")
      is unaffected either way -- it was never bare to begin with. Two regex bugs were found and
      fixed while building this guard, both from letting a separator be fully optional in front
      of the filename-token alternative (see the comment on INLINE_SPLIT_RE for the detail): one
      let the lookahead fire mid-word inside an ordinary filename, the other let it fire on a
      bare parenthetical filename mention with no comma or "and" in front of it at all
      (SVC-PC-49-7-0). Both are why the separator is now mandatory, not optional, in that
      alternative.
    - Guard 4, non-list marker exclusion (`extract_deliverables_block`, via
      _DEMONSTRATIVE_BEFORE_MARKER): a "deliverable(s):" marker preceded by "this", "that",
      "its", "their", "such", or "same" is skipped when picking which marker starts the list,
      because it is pointing BACK at an artifact already named earlier rather than introducing
      one -- "Cross-branch tie-outs specific to THIS deliverable: every bridge figure must trace
      to ..." introduces a tie-out/tracing list, not a deliverables list. This exact "this
      deliverable:" phrase drove a false positive on all eight SVC-PC-47-*-0 tasks plus
      SVC-PC-80-2-0 before this guard existed.
    - Net effect is a conservative UNDER-count, by design: an item is only counted when it is
      unambiguously phrased as its own artifact. Undercounting can only produce a false "clean"
      (a missed real mismatch), never a false flag -- the failure direction the calling skill
      asked this script to avoid. A "+"-joined phrase ("Space & capacity + August operational
      post-mortem memo saved as a Word doc.") is never split at the "+" at all (only at ";", at
      ", [and] a/an/the ...", and at filename-token boundaries), so a task that explicitly says
      its two-part description is "saved as a Word doc" (singular) is never miscounted as two.

EKW port (added after v1's SVC-PC-only calibration, see `ekw_verifier_json.py` for the
underlying `tests/verifier.json` shape): the "Deliverables:" prose side above (marker,
extraction, splitting, guards 1-4) is completely unchanged and reads instruction.md exactly as
before, for either task type -- it has nothing SVC-PC-specific in it. Only the OTHER side of
the comparison -- what counts as "graded" -- is format-detected in `analyze_task`:
    - `tests/deliverables_*/judge.toml` present -> SVC-PC path, byte-for-byte unchanged: the
      graded count still comes from instruction.md's own "## Graded deliverable filenames"
      heading (`extract_graded_filenames`), with the judge.toml files= list as a bonus
      cross-check only, exactly as before.
    - else `has_ekw_config(task_dir)` (tests/verifier.json exists) -> EKW path: EKW tasks were
      confirmed by inspection (grep across all 274 instruction.md files) to never carry a
      "## Graded deliverable filenames" heading at all -- the equivalent "will this actually be
      checked for existence" answer lives structurally in tests/verifier.json instead. So for
      this path, `load_ekw_files(task_dir)` (not `load_ekw_criteria` -- this check only ever
      needed file paths, the same shape `load_judge_files_only` already returns for SVC-PC, not
      weights or rubric text) supplies the deduplicated graded-file list, fed into the exact
      same `prose_count > graded_filename_count` comparison used for SVC-PC. No rewrite of the
      comparison itself, just a redirected input.
    - EKW-specific marker gap, found while porting and now closed: EKW's own "Deliverables:"-style
      intro is almost always phrased "Produce the following deliverables in `/workspace/output/`:"
      (or the `/app/` variant, or "Produce two/three deliverables in ..."), where the colon sits
      after the output-path clause, not immediately after the word "deliverable(s)".
      `DELIVERABLES_MARKER_RE` requires the colon immediately (only whitespace) after
      "deliverable(s)", by design, to avoid matching "## Graded deliverable filenames" or "Submit
      the graded deliverables using ...", and that requirement is UNCHANGED. Confirmed by grep
      across all 274 real EKW instruction.md files that this "deliverables in `<path>`:" shape
      covers 219 occurrences and is structurally disjoint from DELIVERABLES_MARKER_RE on the same
      "deliverable(s)" mention (one requires the colon immediately after the word, the other
      requires " in `/path/`" between the word and the colon -- they cannot both match the same
      span), so `EKW_DELIVERABLES_IN_PATH_MARKER_RE` was added purely additively: same extraction,
      splitting, and guard pipeline runs once either marker locates the block, and SVC-PC's own
      600-task corpus was re-run and reproduced its documented 89/6/505 split exactly, plus a grep
      of that corpus for the new marker's shape returned zero matches, confirming it never fires
      there. Effect on the 274-task EKW corpus: skip dropped from 271 (marker never found) to 67
      (204 pass, 3 fail); the 67 remaining skips are genuinely different phrasing or no explicit
      deliverables heading at all -- see the known-limit note below on what the marker fix then
      exposed. A handful of EKW tasks phrase it as a bare "Deliverables" / "Deliverables:" /
      "deliverables:" line and were already picked up by the pre-existing marker and guards.

Known limits, disclosed rather than silently dropped:
    - This is a text-shape heuristic, not a semantic one. A genuinely separate deliverable
      phrased as a terse, article-less noun phrase (matching the SVC-PC-6-*-0 family's own
      style) will be silently undercounted and this check will not catch it. It trades recall
      for precision on purpose; it is one layer, not a replacement for a human or LLM read of
      the prose.
    - The inline-prose sentence boundary (`extract_deliverables_block`) is a period+capital-letter
      heuristic with light guards against decimals and a short abbreviation list -- an unusual
      sentence structure right after the marker could pull in (or cut off) more or less of the
      list than intended. The raw extracted block is always included in the JSON output so this
      is checkable by eye.
    - The judge.toml cross-check only reads the top-level [judge].files list, mirroring
      deliverable_filename_check.py's load_judge_files(); a criterion-level files=[...] override
      is out of scope here, same disclosed limit that script carries.
    - "filename.ext, a description..." ordering can double-count one deliverable. Guard 3 in
      `split_inline_block` only merges the "description, `filename`" appositive order (noun
      phrase first, bare filename second). EKW instruction.md files commonly invert that order --
      "restraint_determination_memo.docx, a formal clinical and regulatory determination memo
      for..." (task_212) -- and this reversed order has no merge guard: the bare filename counts
      once as its own item, then its own comma-introduced, article-led description counts a
      SECOND time as a distinct item, since nothing currently recognizes "the text right before
      this comma was itself just a bare filename token" as a reason to merge forward instead of
      backward. Found spot-checking the EKW port's newly-passing/failing tasks (2026-09-14):
      task_212 (3 prose vs 2 graded), task_234 (3 vs 2), and task_396 (3 vs 2) are this exact
      pattern, and in task_234 and task_396 the SAME double-count also interacts with Guard 2 (an
      embedded "worksheet"/"row" word wrongly excludes the real second deliverable's own
      description, and a later fragment re-counts it via an embedded filename token) -- worth a
      human read before trusting any of these three as a real defect, not a parsing artifact.
      Separately, `split_numbered_or_bulleted` only recognizes a bullet marker at the START of a
      line (`^[ \t]*[-*]`): an EKW task whose entire bulleted list is written on one physical line
      with " - " separators instead of newlines (task_162, `<Wayfarer_*>` deliverables) collapses
      to a single item, undercounting 3 real deliverables as 1 -- consistent with this script's
      documented conservative-undercount design (never a false flag), but worth knowing this
      specific shape triggers it. And task_201's single candidate item was wrongly excluded by
      Guard 2 because "Corvid Row" (a company name in the prose) contains the substring "Row",
      which `EXCLUSION_RE`'s `\brows?\b` matches as sub-component wording -- an incidental word
      collision, not a real "this is part of another file" signal. None of this is caused by, or
      fixed by, the new EKW marker pattern above -- the marker only made these tasks reachable for
      the first time; the double-count and exclusion logic is unchanged, SVC-PC-calibrated, and
      out of scope for this port (see module-level instruction: extend the marker, do not touch
      the guards).
    - This script checks the CURRENT on-disk state of the task directory under --root. It says
      nothing about whether a task was broken in the past and has since been fixed by other work.
"""

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from ekw_verifier_json import has_ekw_config, load_ekw_files

# Windows console defaults to cp1252, which can't encode every character that shows up in a
# real task's instruction.md (curly quotes, em dashes in vendored text, etc). Force UTF-8 with
# replacement so a printable-but-non-cp1252 character never crashes a batch run partway through.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


FILENAME_EXTS = r"xlsx|xlsm|docx|doc|pptx|ppt|csv|pdf|txt|md"
FILENAME_TOKEN_RE = re.compile(rf"\b[\w][\w\-]*\.(?:{FILENAME_EXTS})\b", re.IGNORECASE)
BARE_FILENAME_RE = re.compile(rf"^[\w][\w\-]*\.(?:{FILENAME_EXTS})$", re.IGNORECASE)

# Marker: the word "deliverable(s)" immediately followed by a colon, anywhere in the text.
# Deliberately does NOT match "## Graded deliverable filenames" (no colon follows "deliverable"
# there) or "Submit the graded deliverables using ..." (no colon follows "deliverables" there).
DELIVERABLES_MARKER_RE = re.compile(r"(?im)\bdeliverables?\s*:")

# Second, ADDITIVE marker shape, EKW-calibrated: confirmed by grep across all 274 real EKW
# instruction.md files that EKW's dominant phrasing is "Produce the following deliverables in
# `/workspace/output/`:" (native-harbor tasks) or "Produce ... deliverables in `/app/`:"
# (reward-kit-hybrid tasks) -- 219 occurrences across the corpus, the great majority of them
# ("Produce" is the leading verb in all but 6). Here the colon sits after the output-path clause,
# not immediately after the word "deliverable(s)", so DELIVERABLES_MARKER_RE above (colon must be
# the very next non-whitespace character) never matches it and never will -- the two patterns are
# structurally disjoint on the same "deliverable(s)" occurrence, so adding this one cannot change
# what the first one matches. Path is usually backtick-wrapped (`` `/workspace/output/` ``) but
# not always (`/workspace/output/:` with no backticks is also common) -- both are matched. A
# handful of samples trail the path with more words before the colon ("... in /app/ and no
# additional files:"), hence the bounded `[^\n:]{0,40}` tail. Deliberately anchored to a leading
# "/" so this stays scoped to the actual observed shape (an absolute in-container path) rather
# than matching any arbitrary "deliverables in X:" sentence elsewhere in a task's prose.
EKW_DELIVERABLES_IN_PATH_MARKER_RE = re.compile(
    r"(?im)\bdeliverables?\s+in\s+`?/[^\n:`]{0,80}`?[^\n:]{0,40}:"
)

# A demonstrative/possessive determiner immediately before the marker word means it is pointing
# BACK at an artifact already named earlier ("Cross-branch tie-outs specific to THIS
# deliverable: every bridge figure must trace to ...", "...reconciliation yourself, inside THIS
# deliverable: tie payroll-register cost to ..."), introducing some other kind of list (a
# tie-out/tracing list here) rather than enumerating deliverables. Calibration found this exact
# "this deliverable:" shape driving every false positive in the SVC-PC-47-*-0 family (all eight
# tasks) plus SVC-PC-80-2-0 -- a real, recurring template pattern, not a one-off. A genuine
# marker in this corpus is never preceded by one of these words ("Produce all three
# deliverables:", "Deliverable: a Master PBC Tracker workbook..." are both clear of it).
_DEMONSTRATIVE_BEFORE_MARKER = {"this", "that", "its", "their", "such", "same"}

# A markdown heading, or plain text, that names the graded-filenames section.
GRADED_HEADING_RE = re.compile(
    r"(?im)^.{0,10}\bdeliverable\b.{0,20}\bfilenames?\b.{0,10}$"
)

# Any markdown heading (used as a fallback right edge for the deliverables block).
ANY_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S")

NUMBERED_ITEM_RE = re.compile(r"(?m)^[ \t]*(\d+)[.\)][ \t]+")
BULLETED_ITEM_RE = re.compile(r"(?m)^[ \t]*[-*\u2022][ \t]+")

# Deliberately indefinite articles ONLY ("a"/"an"), not "the". Every genuine multi-deliverable
# list in the calibration set introduces each new artifact with an indefinite article ("a short
# note", "a Slack draft", "a data-governance spec") because each is being named for the first
# time. "the X" instead reads as a definite, already-scoped reference -- almost always to an
# internal section/content of the ONE artifact an earlier "a/an" item just introduced, e.g.
# "Deliverable: a note with the certification scope table, the wording review by surface, and
# the open counsel questions." (SVC-PC-56-4-0) is one note with three named contents, not four
# deliverables. Excluding bare "the X" items here cut the false-positive rate sharply during
# calibration; an item that legitimately needs "the" AND is a real separate file still counts
# via its filename mention (has_filename below), which this exclusion does not touch.
ARTICLE_START_RE = re.compile(r"^\s*(?:a|an)\b", re.IGNORECASE)
EXCLUSION_RE = re.compile(
    r"\b(?:tabs?|sections?|worksheets?|sheets?|registers?|logs?|rows?|intake|columns?)\b",
    re.IGNORECASE,
)

# Sentence-boundary guard for inline-prose extraction: a period followed by whitespace and a
# capital letter, EXCLUDING a digit immediately before the period (decimals, "$1.2M", "97.5%")
# and excluding a short list of abbreviations that commonly precede a real list item. Python's
# re module requires fixed-width lookbehind, so the abbreviation/digit check is done in Python
# on each candidate match (see find_sentence_end) rather than folded into the regex itself.
_ABBREVIATIONS = (
    "mr",
    "mrs",
    "ms",
    "dr",
    "inc",
    "corp",
    "ltd",
    "vs",
    "etc",
    "e.g",
    "i.e",
    "approx",
)
SENTENCE_CANDIDATE_RE = re.compile(r"\.\s+(?=[A-Z])")


def find_sentence_end(raw_block):
    """Returns the char offset of the first genuine sentence-ending period in raw_block (the
    period itself), or None if no valid boundary is found. Skips a candidate ". " when the
    character right before the period is a digit (decimals, "$1.2M") or when the word right
    before the period is a common abbreviation."""
    for m in SENTENCE_CANDIDATE_RE.finditer(raw_block):
        period_pos = m.start()
        if period_pos == 0:
            continue
        if raw_block[period_pos - 1].isdigit():
            continue
        preceding = raw_block[:period_pos]
        word_match = re.search(r"([A-Za-z]+)$", preceding)
        if word_match and word_match.group(1).lower() in _ABBREVIATIONS:
            continue
        return period_pos
    return None


# Inline splitter: semicolon, OR comma [+ "and"] before an article, OR comma-or-"and" right
# before a literal filename token. All zero-width after the literal separator so nothing gets
# eaten from the following item.
#
# Two bugs found during calibration shaped this regex, both from the same root cause: letting
# the separator in front of the filename-token alternative be fully optional turns that
# alternative into a bare, position-only lookahead that Python's re will try to satisfy starting
# at EVERY character index in the string, not just at real item boundaries.
#   1. Without a \b anchored immediately before the token's first character, it also matched
#      mid-word -- the "w" in "...Review.docx" alone satisfies `[\w][\w\-]*\.docx\b` -- and
#      mis-split ordinary filenames into fragments (in one case down to single letters).
#      Fixed by anchoring the lookahead's own start on \b.
#   2. Even with that \b in place, making BOTH the comma and "and" fully optional (`,?` +
#      `(?:and\s+)?`) still lets the alternative match with zero characters consumed wherever a
#      filename-shaped token merely follows a non-word character -- e.g. "a standalone memo
#      (Positioning_Recommendations.docx)" (SVC-PC-49-7-0) was wrongly split right after the "("
#      even though nothing there introduces a new list item. A comma or "and" must actually be
#      present and consumed; a bare parenthetical or mid-sentence filename mention is never on
#      its own a split point.
INLINE_SPLIT_RE = re.compile(
    r";\s*"
    r"|,\s*(?:and\s+)?(?=(?:a|an|the)\b)"
    rf"|(?:,\s*(?:and\s+)?|and\s+)(?=\b[\w][\w\-]*\.(?:{FILENAME_EXTS})\b)",
    re.IGNORECASE,
)

# An em dash, en dash, or a hyphen with spaces on both sides (so "per-channel" is never
# mistaken for one) introducing a trailing elaboration clause: "a brand architecture document,
# `File.docx` -- the positioning hierarchy, the voice system, and the per-channel adaptation."
# Everything from the dash onward describes/enumerates the ONE deliverable just named, using its
# own internal "the X, the Y, and the Z" list -- which would otherwise defeat the article-based
# eligibility rule and get miscounted as three more top-level deliverables. See
# split_inline_block, which carves this clause off before splitting and reattaches it whole.
DASH_ELABORATION_RE = re.compile(r"\s[–—-]\s")

# Characters stripped when checking whether an item is NOTHING but a filename mention (markdown
# emphasis/backtick decoration plus the punctuation that can trail or lead it in prose).
_DECORATION_CHARS = "*_`.,;: \t"


# ---------------------------------------------------------------------------
# task discovery
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


# ---------------------------------------------------------------------------
# "Deliverables:" prose parsing
# ---------------------------------------------------------------------------


def find_graded_heading_span(text):
    """Returns (start, end) char offsets of the "Graded deliverable filenames" heading line,
    or None if no such heading is found."""
    m = GRADED_HEADING_RE.search(text)
    if m:
        return m.span()
    return None


def extract_deliverables_block(text):
    """Finds the last "deliverable(s):" marker before the graded-filenames heading (or before
    end of text, if no such heading exists) and returns (marker_text, block_text, list_mode).

    list_mode is "numbered" if the block opens as a numbered list, "bulleted" if it opens as a
    bulleted list, else "inline". Returns (None, None, None) if no marker is found.
    """
    graded_span = find_graded_heading_span(text)
    search_end = graded_span[0] if graded_span else len(text)
    search_text = text[:search_end]

    # Union of both marker shapes, sorted by position: DELIVERABLES_MARKER_RE (SVC-PC-calibrated,
    # colon immediately after "deliverable(s)") plus EKW_DELIVERABLES_IN_PATH_MARKER_RE (EKW's
    # "deliverables in `/path/`:" shape, added on top -- see that regex's own comment for why the
    # two never match the same text span). Reusing the existing "last valid mention before the
    # heading wins" + demonstrative-exclusion loop below for both is deliberate: it is the same
    # decision either pattern needs (skip a marker pointing back at an already-named artifact,
    # prefer the marker closest to the actual list), so no separate code path is needed per shape.
    matches = sorted(
        list(DELIVERABLES_MARKER_RE.finditer(search_text))
        + list(EKW_DELIVERABLES_IN_PATH_MARKER_RE.finditer(search_text)),
        key=lambda m: m.start(),
    )
    marker = None
    for candidate in reversed(matches):  # last valid mention before the heading wins
        preceding_word_match = re.search(
            r"([A-Za-z]+)\s*$", search_text[: candidate.start()]
        )
        preceding_word = (
            preceding_word_match.group(1).lower() if preceding_word_match else ""
        )
        if preceding_word in _DEMONSTRATIVE_BEFORE_MARKER:
            continue
        marker = candidate
        break
    if marker is None:
        return None, None, None
    marker_text = search_text[max(0, marker.start() - 5) : marker.end()].strip()

    raw_block = text[marker.end() : search_end]

    stripped = raw_block.lstrip()
    if NUMBERED_ITEM_RE.match(stripped):
        return marker_text, raw_block.strip(), "numbered"
    if BULLETED_ITEM_RE.match(stripped):
        return marker_text, raw_block.strip(), "bulleted"

    # Inline prose: cut at the first real sentence boundary so a trailing unrelated sentence in
    # the same paragraph ("Derive all figures and conclusions from the listed files...") never
    # gets pulled into the deliverables list.
    period_pos = find_sentence_end(raw_block)
    if period_pos is not None:
        block = raw_block[: period_pos + 1]  # include the terminating period
    else:
        block = raw_block
    return marker_text, block.strip(), "inline"


def split_numbered_or_bulleted(block, item_re):
    starts = [m.end() for m in item_re.finditer(block)]
    if not starts:
        return [block.strip()] if block.strip() else []
    # first marker may not be at position 0 if there was leading whitespace/newlines
    bounds = starts + [len(block)]
    items = []
    for i in range(len(starts)):
        chunk = block[bounds[i] : bounds[i + 1]]
        # trim off the next marker's own leading text is not needed since item_re.finditer
        # gives us marker END positions already, so chunk starts right after "N. "
        # but the marker regex itself only matches up to the NEXT marker's start via bounds[i+1]
        items.append(chunk.strip())
    return [it for it in items if it]


def _is_bare_filename(text):
    """True if, once markdown emphasis/backtick decoration and trailing punctuation are
    stripped, text is NOTHING but a filename token."""
    return bool(BARE_FILENAME_RE.match(text.strip(_DECORATION_CHARS)))


def split_inline_block(block):
    """Splits an inline-prose deliverables block into candidate item strings.

    Two passes beyond a plain INLINE_SPLIT_RE.split() are needed to avoid a false-positive shape
    calibration surfaced (see module docstring, Guard 3):

    1. A trailing dash-elaboration clause ("... `File.docx` -- the X, the Y, and the Z.") is
       carved off BEFORE splitting and reattached whole to the last item afterward, so its own
       internal "the X, the Y, and the Z" enumeration is never split into extra top-level items.
    2. A comma-introduced item that is nothing but a bare filename mention -- "a single
       formula-driven workbook, `File.xlsx`." -- is merged into the item right before it rather
       than counted on its own, since it is naming that same deliverable, not adding a new one.
       This merge only fires when the boundary before the bare filename was a comma (an
       appositive), never when it was a semicolon -- "`A.docx`; `B.xlsx`; `C.docx`" is a genuine
       three-item list (see SVC-PC-55-0-0 in this script's own calibration set) and each bare
       filename there must keep counting on its own.
    """
    dash_match = DASH_ELABORATION_RE.search(block)
    if dash_match:
        head, tail = block[: dash_match.start()], block[dash_match.start() :]
    else:
        head, tail = block, ""

    items_with_seps = []  # (item_text, preceding_separator_text_or_None)
    cursor = 0
    prev_sep = None
    for m in INLINE_SPLIT_RE.finditer(head):
        items_with_seps.append((head[cursor : m.start()], prev_sep))
        prev_sep = m.group(0)
        cursor = m.end()
    items_with_seps.append((head[cursor:], prev_sep))

    merged = []
    for raw_text, sep in items_with_seps:
        text = raw_text.strip(" ,;")
        if not text:
            continue
        sep_is_semicolon = bool(sep) and sep.strip().startswith(";")
        if merged and _is_bare_filename(text) and not sep_is_semicolon:
            merged[-1] = f"{merged[-1]}, {text}"
        else:
            merged.append(text)

    if tail:
        if merged:
            merged[-1] = f"{merged[-1]} {tail.strip()}".strip()
        else:
            merged = [tail.strip()]

    return [m for m in merged if m]


def classify_item(item_text):
    """Returns (counted: bool, reason: str) for one candidate deliverable item."""
    text = item_text.strip().strip(",;. ")
    if not text:
        return False, "empty after trimming"

    has_article = bool(ARTICLE_START_RE.match(text))
    has_filename = bool(FILENAME_TOKEN_RE.search(text))
    if not has_article and not has_filename:
        return (
            False,
            "no leading indefinite article (a/an) and no filename mention -- reads as a "
            "terse header or a definite ('the ...') reference to another item's content, "
            "not a standalone deliverable claim",
        )

    excl = EXCLUSION_RE.search(text)
    if excl:
        return (
            False,
            f"contains sub-component wording ({excl.group(0)!r}) -- reads as part of "
            "another file, not counted as its own deliverable",
        )

    return (
        True,
        "counted: opens with an article or names a file, no sub-component wording",
    )


def parse_deliverables_items(block, list_mode):
    if list_mode == "numbered":
        raw_items = split_numbered_or_bulleted(block, NUMBERED_ITEM_RE)
    elif list_mode == "bulleted":
        raw_items = split_numbered_or_bulleted(block, BULLETED_ITEM_RE)
    else:
        raw_items = split_inline_block(block)

    results = []
    for raw in raw_items:
        counted, reason = classify_item(raw)
        results.append({"text": raw, "counted": counted, "reason": reason})
    return results


# ---------------------------------------------------------------------------
# "Graded deliverable filenames" parsing
# ---------------------------------------------------------------------------


def extract_graded_filenames(text):
    """Returns (filenames: list[str], section_found: bool)."""
    m = GRADED_HEADING_RE.search(text)
    if not m:
        return [], False

    rest = text[m.end() :]
    next_heading = ANY_HEADING_RE.search(rest)
    section_text = rest[: next_heading.start()] if next_heading else rest

    filenames = []
    for line in section_text.splitlines():
        line = line.strip()
        if not line.startswith(("-", "*", "\u2022")):
            continue
        bt = re.search(r"`([^`]+)`", line)
        if bt:
            filenames.append(bt.group(1).strip())
        else:
            candidate = line.lstrip("-*\u2022 \t").strip()
            if candidate:
                filenames.append(candidate)
    return filenames, True


# ---------------------------------------------------------------------------
# judge.toml cross-check (bonus, not required -- files= list only, never criterion text)
# ---------------------------------------------------------------------------


def load_judge_files_only(task_dir):
    """Mirrors deliverable_filename_check.py's load_judge_files() but returns only the flat,
    deduplicated set of basenames across every tests/*/judge.toml [judge].files list -- never
    criterion text, which can carry a task's answer key."""
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return None, []
    basenames = set()
    parse_errors = []
    found_any = False
    for jt in sorted(tests_dir.glob("*/judge.toml")):
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
        except Exception as e:
            parse_errors.append(f"{jt.name}: {e}")
            continue
        found_any = True
        files = data.get("judge", {}).get("files", [])
        if isinstance(files, list):
            for f in files:
                basenames.add(str(f).replace("\\", "/").rsplit("/", 1)[-1])
    if not found_any:
        return None, parse_errors
    return sorted(basenames), parse_errors


def has_svc_pc_config(task_dir):
    """True if this task uses SVC-PC's tests/deliverables_*/judge.toml layout. Checked first in
    analyze_task so a task carrying both a legacy judge.toml AND a verifier.json (not observed,
    but not assumed impossible) still takes the unchanged SVC-PC path rather than the new EKW
    one."""
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return False
    return any(tests_dir.glob("*/judge.toml"))


def load_ekw_graded_filenames(task_dir):
    """EKW equivalent of extract_graded_filenames(): the deduplicated, order-preserving list of
    every graded file path named anywhere in tests/verifier.json, via load_ekw_files (the same
    loader deliverable_filename_check.py's EKW branch uses for file paths -- this check only
    ever needed paths, not the weight/rubric-text load_ekw_criteria also carries).

    Returns (filenames, section_found, parse_errors), mirroring extract_graded_filenames' two
    return values plus a third slot for verifier.json parse errors (SVC-PC has no equivalent
    failure mode here since judge.toml parsing is handled entirely inside
    load_judge_files_only).
    """
    sources, parse_errors = load_ekw_files(task_dir)
    seen = set()
    filenames = []
    for src in sources:
        for f in src["files"]:
            if f not in seen:
                seen.add(f)
                filenames.append(f)
    section_found = has_ekw_config(task_dir) and not parse_errors
    return filenames, section_found, parse_errors


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir):
    task_id = task_dir.name
    result = {
        "task_id": task_id,
        "config_format": None,
        "instruction_md_exists": False,
        "deliverables_marker": None,
        "deliverables_list_mode": None,
        "deliverables_raw_block": None,
        "deliverables_items": [],
        "prose_deliverable_count": 0,
        "graded_filenames_section_found": False,
        "graded_filenames": [],
        "graded_filename_count": 0,
        "judge_toml_files": None,
        "judge_toml_parse_errors": [],
        "ekw_parse_errors": [],
        "errors": [],
    }

    instr_path = task_dir / "instruction.md"
    if not instr_path.is_file():
        result["status"] = "skip"
        result["errors"].append(
            "no instruction.md found for this task -- nothing to check"
        )
        return result
    result["instruction_md_exists"] = True

    try:
        text = instr_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        result["status"] = "skip"
        result["errors"].append(f"could not read instruction.md: {e}")
        return result

    marker, block, list_mode = extract_deliverables_block(text)
    if marker is None:
        result["status"] = "skip"
        result["errors"].append(
            'no "Deliverables:" (or similarly-labeled) prose section found -- nothing '
            "for this check to verify"
        )
        return result

    result["deliverables_marker"] = marker
    result["deliverables_list_mode"] = list_mode
    result["deliverables_raw_block"] = block

    items = parse_deliverables_items(block, list_mode)
    result["deliverables_items"] = items
    prose_count = sum(1 for it in items if it["counted"])
    result["prose_deliverable_count"] = prose_count

    # Format detection: SVC-PC's tests/deliverables_*/judge.toml takes the unchanged path
    # (graded count from instruction.md's "## Graded deliverable filenames" heading). A task
    # with no judge.toml but a tests/verifier.json takes the EKW path (graded count from the
    # verifier list itself, since EKW tasks never carry that heading -- see module docstring's
    # "EKW port" section). A task with neither falls back to the original text-only behavior,
    # same as before this port existed.
    if has_svc_pc_config(task_dir):
        result["config_format"] = "svc-pc"
        filenames, section_found = extract_graded_filenames(text)
        no_section_msg = (
            '"Deliverables:" prose found but no "Graded deliverable filenames" section '
            "found -- nothing to compare against"
        )
    elif has_ekw_config(task_dir):
        result["config_format"] = "ekw"
        filenames, section_found, ekw_parse_errors = load_ekw_graded_filenames(task_dir)
        result["ekw_parse_errors"] = ekw_parse_errors
        no_section_msg = (
            '"Deliverables:" prose found but tests/verifier.json named no graded file '
            "(missing, empty, or failed to parse -- see ekw_parse_errors) -- nothing to "
            "compare against"
        )
    else:
        filenames, section_found = extract_graded_filenames(text)
        no_section_msg = (
            '"Deliverables:" prose found but no "Graded deliverable filenames" section '
            "found, and no tests/verifier.json either -- nothing to compare against"
        )

    result["graded_filenames_section_found"] = section_found
    result["graded_filenames"] = filenames
    result["graded_filename_count"] = len(filenames)

    judge_files, judge_errors = load_judge_files_only(task_dir)
    result["judge_toml_files"] = judge_files
    result["judge_toml_parse_errors"] = judge_errors

    if not section_found:
        result["status"] = "skip"
        result["errors"].append(no_section_msg)
        return result

    if prose_count == 0:
        result["status"] = "skip"
        result["errors"].append(
            '"Deliverables:" prose found but no item in it was countable as a distinct '
            "standalone deliverable (see deliverables_items[].reason) -- nothing flagged, "
            "not itself a clean bill of health for this section"
        )
        return result

    if prose_count > result["graded_filename_count"]:
        result["status"] = "fail"
        result["errors"].append(
            f"prose names {prose_count} distinct deliverable(s) but only "
            f"{result['graded_filename_count']} graded filename(s) are listed -- some "
            "described deliverables may never actually be graded"
        )
    else:
        result["status"] = "pass"

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description='Check whether a task\'s "Deliverables:" prose names more distinct '
        'artifacts than its "Graded deliverable filenames" section will ever check for '
        "existence."
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
                "deliverables_items": [],
                "prose_deliverable_count": 0,
                "graded_filenames": [],
                "graded_filename_count": 0,
            }
        results.append(r)
        print(
            f"    -> {r['status']}  "
            f"(prose={r.get('prose_deliverable_count', 0)} vs "
            f"graded={r.get('graded_filename_count', 0)}, "
            f"{len(r.get('errors', []))} errors)",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_skip": n_skip,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_skip} skip out of {len(results)} task(s)"
    )
    for r in results:
        note = ""
        if r["status"] == "fail":
            note = (
                f"  [prose names {r['prose_deliverable_count']} deliverable(s), only "
                f"{r['graded_filename_count']} graded filename(s)]"
            )
        print(f"  {r['task_id']}: {r['status']}{note}")
        for e in r.get("errors", []):
            print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
