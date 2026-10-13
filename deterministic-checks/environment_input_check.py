"""Environment/input check: does a task's instruction.md name required input files, an
unhydrated cloud-storage dependency, or a placeholder-environment contradiction -- structural-
audit patterns 1, 3, and 5, mechanized together because all three turn on the same underlying
question (does instruction.md's account of its inputs match what environment/initial_workspace/
actually holds), not three unrelated checks bolted together.

Why this exists: an Oracle run and a content-only prompt/golden/rubric read both operate on TEXT
-- neither one opens the actual shipped `environment/initial_workspace/` and checks it against
what the prompt says a solver needs. A task can have perfectly consistent prompt/golden/rubric
text and still be unrunnable because the file the prompt names was never staged, the prompt's
only usable input is a Google Drive folder URL an agent with a real filesystem cannot fetch, or
the environment ships an explicit "no input files required" marker while the prompt names real
required files anyway. See `structural-audit/SKILL.md` for the full six-pattern taxonomy this
script mechanizes patterns 1, 3, and 5 of; patterns 2 and 6 are already mechanized in this folder
as `deliverable_filename_check.py` and `deliverable_count_check.py`.

  Pattern 1 -- placeholder/missing named input: instruction.md names a specific input file (in
    backticks/quotes, or bare in running prose) that does not exist anywhere under
    environment/initial_workspace/.
  Pattern 3 -- unhydrated external dependency: instruction.md points at a cloud-storage URL
    (Drive, Dropbox, OneDrive, SharePoint) as an input, regardless of whether the environment
    separately holds real files -- an agent with a real filesystem cannot follow a URL it cannot
    fetch, so the URL itself is defect evidence.
  Pattern 5 -- internal contradiction: environment/initial_workspace/ is placeholder-only (a
    single "no input needed"-style marker file, or empty) while instruction.md's own text names
    specific required files or an "attached"/"attachment" reference. This is the same
    named-file signal as pattern 1, but the placeholder-vs-prompt disagreement is a stronger,
    more clearly wrong signal than a lone missing file could be on its own.

Provenance and calibration: built fresh for this folder, matching the CLI/docstring/style
convention of `deliverable_filename_check.py` and `deliverable_count_check.py` (argparse,
--root required with no default, --all, --id-prefix, --out, UTF-8 stdout/stderr reconfigure,
per-task JSON + aggregate report, never crash the whole batch on one task's exception).
Calibrated against the real 600-task SVC-PC pool
(C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready\\, used here purely as generic
Harbor-shaped fixtures, not to fix or re-audit SVC itself) in three widening passes:

  Pass 1 -- a naive first cut (quoted/backtick filenames + bare word.ext tokens in prose, checked
  against a recursive listing of initial_workspace/) flagged 172 of 600 tasks (29%) as having a
  "missing" named file. Reading the flagged output showed the overwhelming majority were never
  inputs at all: instruction.md routinely names its OWN output filenames in prose before the
  "## Graded deliverable filenames" section ever appears -- an "Inputs (use only these named
  files):" list sits next to a "Workstream deliverables (contributing analyses, built locally
  from the named inputs above):" list, a "Return one local package containing:" bulleted
  description of the graded files, a "Deliver a single formula-driven workbook (`X.xlsx`):"
  parenthetical, or a "Produce X.xlsx containing..." construction-verb sentence -- and a naive
  scan cannot tell "the prompt is naming what it wants back" from "the prompt is naming what it
  was given." This pass produced guards 1-4 below.
  Pass 2 -- rerunning after guards 1-4 cut the flagged count to 28. Reading those 28 by hand
  surfaced three more mechanical false-positive shapes, none semantic: a bare word.ext regex
  cannot see across a space, so a human-titled input named in backticks with spaces
  ("`FY2021 Partnerships Contribution Analysis.docx`") was ALSO caught a second time, truncated,
  by the bare-token pass as the bogus fragment "Analysis.docx"; an ampersand inside a real
  filename ("D&O_Insurance_2021.pdf") broke the bare-token word-boundary and mis-extracted
  "O_Insurance_2021.pdf", which then never matched the real file; and a wildcard-shorthand
  mention describing a family of files ("Q*_Vendor_Scorecard.xlsx", literally containing "*")
  can never match one real basename by construction, and the same mention's bare-token
  fragment ("_Vendor_Scorecard.xlsx", missing its "Q*" prefix since "*" is not a word
  character) is a second copy of the same non-defect. This pass produced guards 5-8 below and
  the ampersand fix to BARE_TOKEN_RE.
  Pass 3 -- final full run at this calibration: 17 of 600 tasks flagged for pattern 1, every one
  read by hand (see the verification report handed back with this script for the specific task
  IDs and findings) and confirmed as either a genuine missing file or a defensible literal-match
  finding under a disclosed known limit (see below), not a guard gap. Pattern 5 (the placeholder-
  contradiction) found zero real positives in this corpus: the six tasks whose
  initial_workspace/ is the `_no_input_files_required.txt` marker (SVC-PC-18-1-0, SVC-PC-52-4-0,
  SVC-PC-7-4-0, SVC-PC-96-0-0, SVC-PC-96-1-0, SVC-PC-96-5-0) were all read in full and none of
  them names a real input file or an attachment anywhere in instruction.md -- the placeholder is
  correct for all six. A synthetic fixture proving pattern 5's detection code actually fires is
  documented in the verification report handed back with this script (built under a scratch
  temp path, not committed anywhere). That fixture pass also caught a real bug in the first
  version of pattern 5's logic: it counted a candidate pattern 1 had EXCLUDED (as well as one it
  had checked) as contradiction evidence, so a placeholder-workspace task that names only its
  OWN output filenames ("Produce X.xlsx containing...", "Cirrus_FY2022_Operations_Model.xlsx"
  restating a graded deliverable name) wrongly fired pattern 5 -- naming an output is not a
  contradiction with "no input files required" at all. Fixed to use only
  candidates_considered (the set pattern 1 itself treats as genuine input mentions); the real
  SVC-PC-7-4-0 task that surfaced this went from a false "fail" back to "pass" once fixed.

Status: v1, calibrated against the full 600-task corpus at build time (every task the script's
own discovery could reach, not a hand-picked sample), with every pattern-1 fail and a pattern-5
synthetic fixture read by a person, not just re-run by the script.

Usage:
    python environment_input_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python environment_input_check.py --all --root <path> --out report.json
    python environment_input_check.py --all --root <path> --id-prefix MYBENCH- --out report.json

What it does, in order:

1. For a given task id (or --all tasks under --root), reads instruction.md and cuts it at the
   "## Graded deliverable filenames" heading (or an equivalent heading -- same detector
   `deliverable_count_check.py` uses): only the text BEFORE that heading is scanned for named
   inputs, since text after it is the solver's output contract, not an input list.
2. Pattern 1: extracts every candidate named file from that pre-heading text two ways --
   backtick/double-quote/single-quote-wrapped exact filenames (extension in
   xlsx/xlsm/docx/doc/pptx/ppt/csv/pdf/txt/json, spaces and other punctuation allowed inside the
   quotes), and bare filename-shaped tokens in running prose (`word.ext`, word characters plus
   "&" and "-"). Each candidate is reduced to its basename (a quoted path like
   "Operations/Q4_Ops_Summary.docx" is checked as "Q4_Ops_Summary.docx") and checked against a
   recursive listing of environment/initial_workspace/, exact basename match first, then a
   case-insensitive fallback tracked SEPARATELY from a true miss (a real but distinct defect
   shape: same file, wrong case, not "not shipped at all"). See "How this avoids false
   positives" for the nine guards that keep this from flooding on output-filename mentions.
3. Pattern 3: scans the WHOLE instruction.md (not just the pre-heading text -- a "Files /
   Connectors" field can appear anywhere) for a URL containing drive.google.com, docs.google.com,
   dropbox.com, onedrive.live.com, or sharepoint.com. This list is not exhaustive (Box, iCloud,
   internal file servers, etc. are not covered) -- every hit is reported with the full matched
   URL text as evidence, regardless of whether the environment separately holds real files,
   because an agent with a real filesystem cannot follow a URL it cannot fetch either way.
4. Pattern 5: classifies environment/initial_workspace/ as placeholder-only if it is completely
   empty, or holds exactly one file matching a "no input needed" name
   (no_input|not_?required|no_files, case-insensitive) or exactly one other file under 512 bytes
   (a size heuristic for "this is a marker, not real data"). If placeholder-only, re-uses
   pattern 1's own extraction AFTER its output-context guards run (candidates_considered, i.e.
   the same set pattern 1 itself would check for existence) to see whether instruction.md names
   ANY genuine input candidate -- a candidate the guards excluded was excluded precisely because
   it names the prompt's OWN output, which is not a contradiction with "no input required" at
   all -- or scans the same pre-heading text for "attach"/"attached"/"attachment". Either one,
   on a placeholder-only environment, fires pattern 5.
5. Writes one JSON result per task (status pass/fail/skip, patterns 1/3/5 findings each with
   verbatim matched text) plus an aggregate report across every task given on the command line
   (or discovered via --all). A task fails if pattern 1 has a genuine miss, pattern 3 has a URL
   hit, or pattern 5 fires; skip means no instruction.md was found to check at all; pass means
   this script ran all three patterns and found nothing.

How this avoids false positives (nine guards on pattern 1's extraction, all found by reading
real flagged output during calibration -- see Provenance above for which pass found which, and
guard 9's own entry below for the one added during the 2026-09-14 EKW fix):
    - Guard 1 (heading cut): text after "## Graded deliverable filenames" is never scanned for
      pattern-1 candidates at all -- it is the output contract, not an input list.
    - Guard 2 (output-context paragraph keywords): a candidate is dropped if the blank-line-
      delimited paragraph it appears in contains "deliverable(s)", "artifact", "containing:", a
      "deliver a/one/the" construction, "exactly this filename", or "submit the graded" --
      wording that reads as describing what the solver produces, not what it was given.
    - Guard 3 (parenthetical naming): a candidate immediately wrapped in "(...)" or "(`...`)" --
      "a formula-driven workbook (`Channel_PnL.xlsx`)" -- is dropped; this is how a prompt names
      the artifact it is asking for, not how it references an existing file.
    - Guard 4 (graded-filename cross-reference): a candidate whose basename matches (case-
      insensitive) one of the task's own "## Graded deliverable filenames" entries is dropped --
      it is a restatement of an output filename elsewhere in the prose, not a new claim about an
      input.
    - Guard 5 (construction-verb window): a candidate is dropped if a construction verb
      (produce/build/construct/generate/create/save/deliver/"name it"/"call it"/"titled")
      appears in the 60 characters immediately before it -- "Produce
      Engineering_Capacity_Allocation_Analysis.xlsx containing..." names an output being built,
      not an input being consumed. Deliberately a narrow trailing WINDOW, not a whole-paragraph
      keyword like guard 2, specifically to avoid guard 2's own risk of silently dropping a
      genuine input candidate that happens to share a paragraph with an unrelated use of one of
      these common verbs elsewhere in the same paragraph.
    - Guard 6 (wildcard-shaped candidate): a candidate whose extracted text contains a literal
      "*" ("customers_export_*.csv", "Q*_Vendor_Scorecard.xlsx") describes a FAMILY of files in
      prose, not one literal filename, and can never match a real basename by construction --
      dropped, not reported as missing.
    - Guard 7 (wildcard-truncation adjacency): the bare-token regex cannot include "*" in a
      filename token (it is not a word character), so "Q*_Vendor_Scorecard.xlsx" bare-extracts
      as the truncated fragment "_Vendor_Scorecard.xlsx" missing its "Q*" prefix. A bare-token
      match immediately preceded by a literal "*" in the source text is dropped as this same
      wildcard mention, not a second, different missing file.
    - Guard 8 (bare-token-nested-in-quote dedup): a quoted/backtick filename containing a space
      ("`FY2021 Partnerships Contribution Analysis.docx`") is one genuine QUOTED_RE match, but
      the bare-token regex (word characters only, blind to spaces) ALSO independently matches
      just its trailing "Analysis.docx" fragment inside the same quotes. Any bare-token match
      whose span falls entirely inside a quoted match's span is dropped -- the full name is
      checked once, not fragmented into a second, bogus candidate.
    - Guard 9 (2026-09-14, EKW-corpus finding: graded-name tail fragment, unquoted): the same
      bare-token truncation guard 8 fixes for a QUOTED multi-word name also happens for an
      UNQUOTED one -- confirmed on real EKW tasks whose deliverable names are human-readable
      titles never wrapped in quotes/backticks anywhere in instruction.md ("Produce exactly TWO
      final deliverables in /app/. DELIVERABLE 1 THE LAST VALLEY Sequence 87 Equine Execution &
      Recovery Plan.docx"). There is no quoted span for guard 8 to nest inside, and guard 4's
      exact match against graded_names never fires because the bare-token candidate is only the
      tail ("Plan.docx"), not the graded name in full. Guard 9 catches this directly: a candidate
      whose basename is a genuine word/space/underscore/hyphen-bounded trailing suffix of one of
      graded_names' own basenames (not a coincidental mid-word substring) is dropped as the same
      output-restated-in-prose case guard 4 already handles. Depends on graded_names actually
      containing EKW's verifier.json-sourced basenames (see compute_graded_names) -- with the
      pre-fix blanket EKW disable, graded_names was SVC-PC-only and always empty for an EKW task,
      so this guard would have had nothing to check against either.
    Net effect, same design choice `deliverable_count_check.py` makes and states explicitly: this
    is a conservative UNDER-count by design. Every guard above can only turn a flagged candidate
    into a dropped one, never the reverse, so the residual failure direction is a missed real
    input-mismatch, never a false "fail" on a task that is actually fine.

Known limits, disclosed rather than silently dropped:
    - Case-sensitivity is tracked SEPARATELY, per the task's own instruction: a candidate found
      under a different case (e.g. instruction.md says "chart_of_accounts.xlsx", the shipped
      file is "Chart_of_Accounts_.xlsx") is reported in `case_mismatch`, not `missing` -- a real
      but distinct defect shape from "not shipped at all."
    - Multi-file range/family shorthand is not expanded. A prompt that writes "Q2-Q3
      Pipeline_Tracker.xlsx" or "the Q1-Q4 set" as informal shorthand for two-or-more separately
      named real files (e.g. "Q2_Pipeline_Tracker.xlsx" and "Q3_Pipeline_Tracker.xlsx" both
      exist, but neither is literally spelled out) is checked LITERALLY against the shorthand
      string, which will never match any single real basename. Calibration's own real example:
      "Q1-Q4_Channel_Attribution.xlsx" recurs verbatim across ten related tasks
      (SVC-PC-13-3-0, SVC-PC-47-0-0/2-0/5-0, SVC-PC-75-0-0/3-0/8-0, SVC-PC-91-0-0/2-0/3-0,
      SVC-PC-94-0-0) and never exists as a single consolidated file in any of their
      environments -- only four separate per-quarter files (Q1_Channel_Attribution.xlsx ...
      Q4_Channel_Attribution.xlsx) are ever shipped. This script reports the literal miss (the
      named file genuinely does not exist under that name, and a solver told to open it will
      find nothing), which is the defensible, literal reading the task itself asked for; it is
      also plausible these ten tasks intend "the four quarterly files" and the miss is a wording
      issue rather than a missing-data issue. Either way this is a real, recurring, worth-fixing
      finding, not a script bug -- but the distinction between "wrong wording" and "missing data"
      needs a person, not this script.
    - The construction-verb window (guard 5) is a fixed 60-character trailing window, not a
      clause or sentence boundary. A genuine input filename that happens to fall within 60
      characters of an unrelated use of "produce"/"build"/etc. earlier in the same sentence
      could be wrongly dropped. Given the guard can only drop candidates (never invent a false
      "missing"), this is a false-negative risk, consistent with this script's stated
      conservative-undercount design, not a false-positive one.
    - The output-context paragraph keywords (guard 2) operate on the WHOLE paragraph a candidate
      falls in. A paragraph that names both a genuine input and an unrelated output in the same
      blank-line-delimited block (rare in the calibration corpus, but not provably impossible)
      would drop the genuine input candidate along with the output mention.
    - Pattern 1's extraction only recognizes four extensions groups' worth of quoting style
      (backtick, single quote, double quote) and requires an extension from a fixed list
      (xlsx/xlsm/docx/doc/pptx/ppt/csv/pdf/txt/json). A filename quoted with curly/smart quotes,
      or carrying an extension outside that list (e.g. .xls, .zip, .png), is invisible to this
      check.
    - Pattern 3's domain list (drive.google.com, docs.google.com, dropbox.com,
      onedrive.live.com, sharepoint.com) is explicitly not exhaustive -- Box, iCloud, an internal
      file server, or a plain non-cloud URL naming an external dependency are not covered.
    - Pattern 5's placeholder classification is a heuristic (empty, or exactly one file matching
      a name pattern or under 512 bytes) calibrated against exactly one real placeholder
      convention observed in the corpus (`_no_input_files_required.txt`). A different pipeline's
      placeholder convention may not match this shape at all.
    - This script checks the CURRENT on-disk state of the task directory under --root. It says
      nothing about whether a task was broken in the past and has since been fixed by other
      work.

EKW port (2026-09-14): everything above this paragraph describes the original SVC-PC-only
script and is unchanged in behaviour for any task detected as SVC-PC. `detect_task_format()`
and `resolve_workspace_dir()` (new, just below the module constants) are the path-constant
swap: EKW ships its inputs at `environment/data/`, not SVC-PC's `environment/initial_workspace/`
-- confirmed on real EKW task samples, not assumed. Detection mirrors
`deliverable_filename_check.py`'s own precedent exactly: SVC-PC (any `tests/*/judge.toml`) wins
whenever it exists, so this port cannot change SVC-PC behaviour even in the unobserved case
where a task dir somehow carries both shapes; EKW is detected via
`ekw_verifier_json.has_ekw_config()` (`tests/verifier.json` presence); a task with neither shape
defaults to `svc_pc`, an unchanged pre-port code path.

Pattern 1 (named input file vs. workspace), 2026-09-14 fix -- now ACTUALLY runs its
file-existence check for EKW tasks, replacing an earlier same-day version of this port that
disabled pattern 1 for EKW outright (`"status": "not_applicable_ekw"` unconditionally, on the
theory that EKW describes inputs by CONTENT rather than filename so a basename-match has
nothing to compare against). That theory was correct about EKW's input-describing prose, but
wrong about what pattern 1 would actually have flagged if simply turned back on: EKW's own
deliverable-listing sentence -- "Produce the following deliverables in `/workspace/output/`:"
(native-harbor) or "...in `/app/`:" (reward-kit-hybrid), confirmed against the real corpus in
several phrasings ("Produce exactly two deliverables in ...:", "Produce the following
deliverable in `/app/`:" singular, with and without backticks around the path) -- was never
recognized as a cut point the way SVC-PC's "## Graded deliverable filenames" heading is
(`GRADED_HEADING_RE`), and EKW has no equivalent heading to populate guard 4's graded_names
cross-reference either (confirmed by inspection across all 274 instruction.md files -- see
`deliverable_count_check.py`'s own EKW port notes for the same finding). So the deliverable
filenames sitting in the bulleted description right after that sentence would have been scanned
as INPUT candidates and reported as near-universally missing -- the opposite failure from the
"false clean pass" the blanket disable was built to avoid, and the reason a blanket disable was
chosen instead of debugging it same-day.

Two independent, additive fixes make it safe to run pattern 1 for real on EKW now:
  1. `EKW_DELIVERABLES_HEADING_RE` (new, next to `GRADED_HEADING_RE`): recognizes the "Produce
     ... deliverable(s) in `<path>`:" sentence shape and `prompt_scan_text()` cuts scan_text
     there for an EKW task (`task_format` is now threaded through), same role as guard 1's
     heading cut for SVC-PC. Scoped narrowly to this one observed phrasing on purpose -- a
     handful of other real "deliverables" mentions exist in the corpus this regex deliberately
     does not match ("Produce two deliverables:" with no path clause, "Produce both deliverables
     with the exact file...") -- because fix 2 below does not depend on recognizing any heading
     shape at all and is the real backstop.
  2. `compute_graded_names()` (new, replaces the direct `extract_graded_filenames()` call in
     `analyze_task()`): for an EKW task, unions in the basename of every file
     `tests/verifier.json` actually grades, read via `ekw_verifier_json.load_ekw_files()` --
     the AUTHORITATIVE list of what the grader itself will open, independent of instruction.md's
     wording entirely. Guard 4 (`analyze_pattern1`'s existing "matches a graded deliverable
     filename" check) then drops these candidates the same way it already drops SVC-PC's
     restated-output mentions, no new guard logic needed.

With both in place, `analyze_pattern1()` no longer branches on task_format at all beyond
recording it in the result and letting `resolve_workspace_dir()` pick the right workspace
directory upstream -- EKW and SVC-PC run the identical extraction/guard/existence-check logic.
`analyze_pattern5()` also simplified back to always reusing `pattern1_result["candidates_
considered"]` (it used to re-run `extract_named_file_candidates()` directly for EKW, working
around pattern 1's now-removed short-circuit). See `analyze_pattern1()`'s and
`analyze_pattern5()`'s own docstrings/comments for the fix narrative in place, and the verified
per-task numbers this produced against the real 274-task corpus at the end of this file's
docstring or the calibration report handed back alongside this change.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from ekw_verifier_json import has_ekw_config, load_ekw_files

# Windows console defaults to cp1252, which can't encode every character that shows up in a
# real task's instruction.md (curly quotes, em dashes in vendored text, etc). Force UTF-8 with
# replacement so a printable-but-non-cp1252 character never crashes a batch run partway through.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# shared constants
# ---------------------------------------------------------------------------

FILENAME_EXTS = r"xlsx|xlsm|docx|doc|pptx|ppt|csv|pdf|txt|json"

# Same heading detector `deliverable_count_check.py` uses for the same purpose: find the
# "Graded deliverable filenames" section so text after it (the output contract) is never
# scanned for pattern-1 input candidates.
GRADED_HEADING_RE = re.compile(
    r"(?im)^.{0,10}\bdeliverable\b.{0,20}\bfilenames?\b.{0,10}$"
)
ANY_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S")

# EKW guard 1 equivalent: EKW tasks never carry SVC-PC's "## Graded deliverable filenames"
# heading (confirmed by inspection across all 274 instruction.md files, see
# deliverable_count_check.py's own EKW port notes for the same finding). Instead the
# graded-deliverables intro is a sentence of the shape "Produce the following deliverable(s) in
# `/workspace/output/`:" (native-harbor tasks) or "...in `/app/`:" (reward-kit-hybrid tasks),
# confirmed against the real corpus: "Produce the following deliverables in `/app/`:", "Produce
# exactly two deliverables in `/workspace/output/`:", "Produce the deliverables in
# `/workspace/output/`:", "Produce three deliverables in /workspace/output/:" (no backticks --
# both quoted and bare path forms observed), "Produce the following deliverable in `/app/`:"
# (singular). This is the EKW equivalent cut point for guard 1: text at and after this sentence
# is the output contract (deliverable filenames + descriptions), never an input list, exactly
# like GRADED_HEADING_RE's role for SVC-PC. Scoped narrowly to this one observed phrasing
# ("produce ... deliverable(s) in <path-starting-with-/>:") rather than every way a prompt might
# mention "deliverables" -- a handful of other real phrasings exist in the corpus ("Produce two
# deliverables:" with no path clause, "Produce both deliverables with the exact file...") that
# this regex deliberately does NOT match; those are instead caught by the guard-4 cross-reference
# against tests/verifier.json's own graded-file list (see analyze_task/compute_graded_names
# below), which does not depend on recognizing any particular heading shape at all.
EKW_DELIVERABLES_HEADING_RE = re.compile(
    r"(?im)\bproduce\b[^\n:]{0,40}\bdeliverables?\b\s+in\s+`?/[^`\s:\n]*`?\s*:"
)

# Quoted/backtick-wrapped exact filenames. The content between the quote marks is permissive
# (spaces, "&", "+", "(", ")" all allowed) since real corpus filenames are sometimes
# human-readable titles ("FY2021 Warehousing & Fulfillment Performance Analysis (final).doc"),
# not just underscore-joined machine names -- only the extension is constrained.
QUOTED_RE = re.compile(
    r"`([^`\n]+\.(?:%s))`"
    r'|"([^"\n]+\.(?:%s))"'
    r"|'([^'\n]+\.(?:%s))'" % (FILENAME_EXTS, FILENAME_EXTS, FILENAME_EXTS),
    re.IGNORECASE,
)

# Bare filename-shaped token in running prose: word characters plus "&" (so "D&O_Insurance_
# 2021.pdf" is captured whole rather than truncated at the ampersand) and "-", ending in one of
# the recognized extensions.
BARE_TOKEN_RE = re.compile(rf"\b[\w][\w&\-]*\.(?:{FILENAME_EXTS})\b", re.IGNORECASE)

# Guard 2: a paragraph containing any of these reads as describing what the solver PRODUCES, not
# what it was given. See the module docstring's "How this avoids false positives" for examples
# of each real shape this was calibrated against.
OUTPUT_CONTEXT_RE = re.compile(
    r"\bdeliverables?\b"
    r"|\bartifact\b"
    r"|\bdeliver\s+(?:a|one|the)\b"
    r"|\bcontaining\s*:"
    r"|\bexactly\s+this\s+filename\b"
    r"|\bsubmit\s+the\s+graded\b",
    re.IGNORECASE,
)

# Guard 5: a construction verb in the short trailing window right before a candidate means the
# candidate is being NAMED as an output ("Produce X.xlsx containing...", "build a ... workbook
# (X.xlsx)"), not referenced as an existing input. See module docstring for why this is a
# window, not a whole-paragraph keyword like guard 2.
VERB_WINDOW_RE = re.compile(
    r"\b(?:produce|build|construct|generate|create|save|deliver|name it|call it|titled)\b",
    re.IGNORECASE,
)
VERB_WINDOW_CHARS = 60

# Pattern 3: cloud-storage domains. Not exhaustive -- see Known limits in the module docstring.
CLOUD_DOMAINS = (
    r"drive\.google\.com",
    r"docs\.google\.com",
    r"dropbox\.com",
    r"onedrive\.live\.com",
    r"sharepoint\.com",
)
CLOUD_URL_RE = re.compile(
    r"https?://[^\s\)\]\}<>\"']*(?:" + "|".join(CLOUD_DOMAINS) + r")[^\s\)\]\}<>\"']*",
    re.IGNORECASE,
)

# Pattern 5: a placeholder-shaped marker filename, e.g. "_no_input_files_required.txt".
PLACEHOLDER_NAME_RE = re.compile(r"no_input|not_?required|no_files", re.IGNORECASE)
PLACEHOLDER_TRIVIAL_SIZE_BYTES = 512

# Pattern 5: an "attached"/"attachment" reference, checked on the same pre-graded-heading text
# pattern 1 scans.
ATTACH_RE = re.compile(r"\battach(?:ed|ment|ments)?\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# format detection: SVC-PC (environment/initial_workspace/) vs EKW (environment/data/)
# ---------------------------------------------------------------------------

WORKSPACE_DIRNAME_BY_FORMAT = {"svc_pc": "initial_workspace", "ekw": "data"}


def _has_svc_pc_config(task_dir):
    """True if this task has at least one tests/*/judge.toml -- the same unrestricted glob
    deliverable_filename_check.py's own _has_svc_pc_config() uses, so the two scripts can never
    disagree about which format a given task dir is."""
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return False
    return any(tests_dir.glob("*/judge.toml"))


def detect_task_format(task_dir):
    """Returns "svc_pc" or "ekw". SVC-PC's tests/*/judge.toml wins whenever it exists (same
    precedence deliverable_filename_check.py's load_deliverable_files() uses), so this port
    cannot change SVC-PC behaviour for any task that already has one, even in the unobserved
    case where a task dir somehow carries both shapes. EKW is detected via
    ekw_verifier_json.has_ekw_config() (tests/verifier.json presence). A task with neither shape
    defaults to "svc_pc" -- unchanged pre-port behaviour: environment/initial_workspace/ simply
    won't exist, which analyze_task() already handles via environment_workspace_exists=False.
    """
    if _has_svc_pc_config(task_dir):
        return "svc_pc"
    if has_ekw_config(task_dir):
        return "ekw"
    return "svc_pc"


def resolve_workspace_dir(task_dir):
    """Returns (ws_dir: Path, task_format: str). ws_dir is environment/initial_workspace/ for
    SVC-PC, environment/data/ for EKW -- the only path constant this script hardcoded before the
    EKW port (see module docstring's EKW port section)."""
    task_format = detect_task_format(task_dir)
    return (
        task_dir / "environment" / WORKSPACE_DIRNAME_BY_FORMAT[task_format],
        task_format,
    )


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


def basename(p):
    """Reduce a quoted path-shaped mention to its bare filename, whatever separator it was
    authored with -- mirrors the sibling scripts' own basename() helper."""
    return str(p).replace("\\", "/").rsplit("/", 1)[-1]


def split_paragraphs(text):
    """Returns [(start, end, block_text), ...] for blank-line-delimited paragraphs. A blank
    line (a line that is empty or whitespace-only) ends one paragraph and starts the next.
    """
    blocks = []
    for m in re.finditer(r"[^\n]*(?:\n(?!\s*\n)[^\n]*)*", text):
        if m.group(0).strip():
            blocks.append((m.start(), m.end(), m.group(0)))
    return blocks


def extract_graded_filenames(text):
    """Returns (set of lowercased basenames, section_found: bool). Mirrors
    deliverable_count_check.py's extract_graded_filenames() but only needs the flat basename
    set, for guard 4's cross-reference."""
    m = GRADED_HEADING_RE.search(text)
    if not m:
        return set(), False
    rest = text[m.end() :]
    nh = ANY_HEADING_RE.search(rest)
    section = rest[: nh.start()] if nh else rest
    names = set()
    for line in section.splitlines():
        for bt in re.findall(r"`([^`]+)`", line):
            names.add(basename(bt).lower())
    return names, True


def compute_graded_names(task_dir, full_text, task_format):
    """Basenames (lowercased) of every filename guard 4 should treat as a restated OUTPUT, not
    a new input claim. Returns (names: set[str], ekw_parse_errors: list).

    SVC-PC: unchanged -- sourced entirely from instruction.md's own "## Graded deliverable
    filenames" heading via extract_graded_filenames().

    EKW: that heading essentially never appears (confirmed by inspection across all 274
    instruction.md files -- see deliverable_count_check.py's own EKW port notes), so relying on
    extract_graded_filenames() alone leaves graded_names empty and guard 4 with nothing to
    cross-reference. This is the 2026-09-14 fix's second, independent layer (the first being
    EKW_DELIVERABLES_HEADING_RE's guard-1-equivalent cut in prompt_scan_text): for an EKW task,
    additionally pull the AUTHORITATIVE graded-file list straight from tests/verifier.json --
    the file(s) the grader itself will actually open -- via ekw_verifier_json.load_ekw_files(),
    and union their basenames in. This does not depend on recognizing any particular heading or
    sentence shape in instruction.md at all, so it catches deliverable mentions
    EKW_DELIVERABLES_HEADING_RE's narrower phrasing match misses (e.g. "Produce two
    deliverables:" with no path clause, or a deliverable filename mentioned somewhere pattern
    1's scan_text cut didn't reach).
    """
    names, _section_found = extract_graded_filenames(full_text)
    ekw_parse_errors = []
    if task_format == "ekw":
        sources, ekw_parse_errors = load_ekw_files(task_dir)
        for src in sources:
            for f in src.get("files", []):
                names.add(basename(f).lower())
    return names, ekw_parse_errors


# ---------------------------------------------------------------------------
# pattern 1: named input files vs. environment/initial_workspace/
# ---------------------------------------------------------------------------


def prompt_scan_text(text, task_format="svc_pc"):
    """Text before the graded-deliverables cut point (or the whole text if no such cut point is
    found) -- the only span pattern 1 and pattern 5's attach-scan ever look at.

    SVC-PC (task_format == "svc_pc", the default): unchanged pre-port behaviour -- cuts at
    GRADED_HEADING_RE ("## Graded deliverable filenames") only.

    EKW: also checks EKW_DELIVERABLES_HEADING_RE ("Produce ... deliverable(s) in `<path>`:") and
    cuts at whichever of the two matches starts earliest, in the unobserved case a task carries
    both. Gated behind task_format specifically (rather than just always checking both regexes)
    so SVC-PC's own cut behaviour stays byte-for-byte unchanged even in the hypothetical case an
    SVC-PC prompt's prose happened to contain EKW_DELIVERABLES_HEADING_RE's shape.
    """
    candidates = []
    m = GRADED_HEADING_RE.search(text)
    if m:
        candidates.append(m.start())
    if task_format == "ekw":
        m2 = EKW_DELIVERABLES_HEADING_RE.search(text)
        if m2:
            candidates.append(m2.start())
    return text[: min(candidates)] if candidates else text


def extract_named_file_candidates(scan_text, graded_names):
    """Returns a dict: basename -> list of {"text": raw_matched_text, "excluded_reason":
    str-or-None}. One entry per DISTINCT raw match (so evidence is never lost to dedup), but a
    basename is only checked against the environment if at least one of its occurrences has
    excluded_reason None (see analyze_pattern1 below)."""
    paragraphs = split_paragraphs(scan_text)

    all_matches = []  # (start, end, raw_text, basename)
    quoted_spans = []
    for m in QUOTED_RE.finditer(scan_text):
        grp = next(g for g in m.groups() if g)
        all_matches.append((m.start(), m.end(), m.group(0), basename(grp.strip())))
        quoted_spans.append((m.start(), m.end()))
    for m in BARE_TOKEN_RE.finditer(scan_text):
        # Guard 8: drop a bare-token match nested entirely inside an already-captured quoted
        # span -- see module docstring.
        if any(qs <= m.start() and m.end() <= qe for qs, qe in quoted_spans):
            continue
        all_matches.append((m.start(), m.end(), m.group(0), basename(m.group(0))))

    found = {}
    for start, end, raw, bn in all_matches:
        reason = None
        if "*" in bn:
            # Guard 6
            reason = (
                "wildcard-shaped reference (contains '*'), not one literal filename"
            )
        elif start > 0 and scan_text[start - 1] == "*":
            # Guard 7
            reason = (
                "immediately preceded by '*' in the source text -- a truncated fragment "
                "of a wildcard-shorthand reference, not a distinct missing file"
            )
        elif bn.lower() in graded_names:
            # Guard 4
            reason = "matches a graded deliverable filename -- an output restated in prose, not an input"
        elif any(
            gn != bn.lower() and gn.endswith(bn.lower()) and gn[-(len(bn) + 1)] in " _-"
            for gn in graded_names
        ):
            # Guard 9 (2026-09-14, EKW): a trailing word.ext fragment of a graded deliverable's
            # own basename. Real, corpus-confirmed shape: EKW deliverable names are often
            # human-readable titles with spaces, never wrapped in quotes/backticks anywhere in
            # instruction.md ("Produce exactly TWO final deliverables in /app/. DELIVERABLE 1
            # THE LAST VALLEY Sequence 87 Equine Execution & Recovery Plan.docx"). BARE_TOKEN_RE
            # cannot cross the spaces in an unquoted name like that, so it captures only the last
            # word before the extension ("Plan.docx") -- guard 4's exact match against
            # graded_names never fires because the candidate isn't the full graded name, just its
            # tail. This guard catches that tail specifically (a real word/space/underscore/
            # hyphen boundary immediately before the fragment inside the graded name, not a
            # coincidental mid-word substring), so it is the same "output restated in prose, not
            # an input" case guard 4 already handles, not a new exception.
            reason = (
                "a trailing word.ext fragment of a graded deliverable's basename -- the "
                "bare-token regex cannot cross the spaces in an unquoted, human-readable "
                "graded filename, so it captured only the tail; the full name matches "
                "a tests/verifier.json-graded deliverable"
            )
        else:
            # Guard 3: parenthetical naming, optionally with a backtick just inside the parens
            before_ch = scan_text[start - 1] if start > 0 else ""
            after_ch = scan_text[end] if end < len(scan_text) else ""
            before_ch2 = scan_text[start - 2] if start > 1 else ""
            after_ch2 = scan_text[end + 1] if end + 1 < len(scan_text) else ""
            wrapped_open = before_ch == "(" or (before_ch == "`" and before_ch2 == "(")
            wrapped_close = after_ch == ")" or (after_ch == "`" and after_ch2 == ")")
            if wrapped_open and wrapped_close:
                reason = "parenthetical naming of an artifact being built (output, not input)"
        if reason is None:
            # Guard 5: construction-verb window
            window = scan_text[max(0, start - VERB_WINDOW_CHARS) : start]
            if VERB_WINDOW_RE.search(window):
                reason = (
                    "a construction verb (produce/build/create/...) immediately precedes "
                    "this mention -- names an output being built, not an input"
                )
        if reason is None:
            # Guard 2: whole-paragraph output-context keywords
            for pstart, pend, ptext in paragraphs:
                if pstart <= start < pend:
                    if OUTPUT_CONTEXT_RE.search(ptext):
                        reason = (
                            "mentioned in a paragraph with deliverable/output-framing "
                            "language"
                        )
                    break
        found.setdefault(bn, []).append({"text": raw, "excluded_reason": reason})
    return found


def collect_workspace_basenames(ws_dir):
    """Recursive basename listing of environment/initial_workspace/. Returns (exact_set,
    lower_set). A file appearing at any depth (including under a `_corpus_subtree/` staging
    layer some tasks use) counts -- pattern 1 only claims a basename is missing if it is absent
    everywhere under the workspace, not just at the top level."""
    exact = set()
    if ws_dir.is_dir():
        for _, _, filenames in __import__("os").walk(ws_dir):
            exact.update(filenames)
    return exact, {f.lower() for f in exact}


def analyze_pattern1(scan_text, graded_names, ws_dir, task_format="svc_pc"):
    """Pattern 1: named input files vs. the shipped workspace.

    2026-09-14 fix: previously this function short-circuited to a blanket "not_applicable_ekw"
    status for every EKW task, on the theory that EKW describes its inputs by CONTENT ("the
    bills of materials and routing standards...") rather than by filename, so a basename-match
    would have nothing to compare against. That premise was correct for the text BEFORE the
    graded-deliverables cut point, but the blanket disable also masked a real bug: EKW's
    deliverable-listing sentence ("Produce the following deliverables in `/app/`:", etc.) was
    never recognized as a cut point (GRADED_HEADING_RE only matches SVC-PC's "## Graded
    deliverable filenames" heading), so every deliverable's own filename sitting in the bulleted
    description below that sentence would have been scanned as an input candidate and, absent a
    matching "## Graded deliverable filenames" section to populate graded_names for guard 4
    either, reported as a near-universal false "missing input" -- not the false "clean pass" the
    original comment predicted, the opposite failure. Two independent fixes, both upstream of
    this function, now make it safe to actually run pattern 1's existence check for EKW instead
    of disabling it outright: (1) prompt_scan_text() now also cuts at
    EKW_DELIVERABLES_HEADING_RE for an EKW task, removing most deliverable-bullet text from
    scan_text entirely (EKW's guard-1 equivalent); (2) the caller (analyze_task, via
    compute_graded_names) now unions graded_names with every basename tests/verifier.json
    actually grades (ekw_verifier_json.load_ekw_files()), so guard 4 drops any candidate that
    literally is a graded deliverable regardless of where in the text it appears or whether cut
    (1) caught it. With both in place, this function's logic runs UNCHANGED and IDENTICALLY for
    both formats -- task_format is accepted only so the result records which format was checked,
    never to change behaviour. SVC-PC's own path (task_format == "svc_pc", the default) is
    byte-for-byte unchanged from the pre-EKW-port version of this function."""
    candidates = extract_named_file_candidates(scan_text, graded_names)
    exact, lower = collect_workspace_basenames(ws_dir)

    considered, excluded, found, missing, case_mismatch = [], [], [], [], []
    for bn, occs in sorted(candidates.items()):
        active = [o for o in occs if o["excluded_reason"] is None]
        if not active:
            excluded.append(
                {
                    "filename": bn,
                    "reason": occs[0]["excluded_reason"],
                    "text": occs[0]["text"],
                }
            )
            continue
        considered.append(bn)
        evidence = active[0]["text"]
        if bn in exact:
            found.append({"filename": bn, "text": evidence})
        elif bn.lower() in lower:
            actual = next(f for f in exact if f.lower() == bn.lower())
            case_mismatch.append({"filename": bn, "found_as": actual, "text": evidence})
        else:
            missing.append({"filename": bn, "text": evidence})
    return {
        "status": "checked",
        "task_format": task_format,
        "candidates_considered": considered,
        "excluded": excluded,
        "found": [f["filename"] for f in found],
        "missing": missing,
        "case_mismatch": case_mismatch,
    }


# ---------------------------------------------------------------------------
# pattern 3: unhydrated cloud-storage dependency
# ---------------------------------------------------------------------------


def analyze_pattern3(full_text):
    hits = []
    for m in CLOUD_URL_RE.finditer(full_text):
        context_start = max(0, m.start() - 60)
        hits.append(
            {
                "url": m.group(0),
                "context": full_text[context_start : m.start()].strip(),
            }
        )
    return {"hits": hits}


# ---------------------------------------------------------------------------
# pattern 5: placeholder environment vs. named-input/attachment contradiction
# ---------------------------------------------------------------------------


def classify_placeholder(ws_dir):
    """Returns (is_placeholder: bool, reason: str-or-None). Heuristic calibrated against the
    one real placeholder convention found in the SVC-PC corpus
    (`_no_input_files_required.txt`) -- see Known limits in the module docstring."""
    if not ws_dir.is_dir():
        return False, None
    entries = []
    for dirpath, _, filenames in __import__("os").walk(ws_dir):
        for fn in filenames:
            entries.append(Path(dirpath) / fn)
    if not entries:
        return True, "environment/initial_workspace/ is completely empty (0 files)"
    if len(entries) == 1:
        only = entries[0]
        if PLACEHOLDER_NAME_RE.search(only.name):
            return True, f"single placeholder-marker file: {only.name}"
        try:
            size = only.stat().st_size
        except OSError:
            size = None
        if size is not None and size <= PLACEHOLDER_TRIVIAL_SIZE_BYTES:
            return (
                True,
                f"single trivial file ({only.name}, {size} bytes) -- reads as a marker, "
                "not real input data",
            )
    return False, None


def analyze_pattern5(scan_text, pattern1_result, ws_dir):
    is_placeholder, placeholder_reason = classify_placeholder(ws_dir)
    result = {
        "environment_is_placeholder": is_placeholder,
        "placeholder_reason": placeholder_reason,
        "fired": False,
        "contradicting_named_files": [],
        "contradicting_attach_references": [],
    }
    if not is_placeholder:
        return result

    # Reuse pattern 1's own extraction, but ONLY the candidates that survived pattern 1's own
    # output-context guards (candidates_considered) -- an excluded candidate was excluded
    # precisely because it reads as the prompt naming ITS OWN output ("matches a graded
    # deliverable filename", a construction-verb window, a "Deliverables:" paragraph, ...), and
    # a task naming its own outputs is completely consistent with "no input files required." A
    # real placeholder/prompt contradiction requires the prompt to name a file it expects to be
    # GIVEN, which is exactly what candidates_considered (and nothing else) represents here.
    #
    # 2026-09-14: previously an EKW task re-ran extract_named_file_candidates() here directly,
    # bypassing pattern1_result, because analyze_pattern1() used to short-circuit to an empty
    # candidates_considered for EKW (pattern 1's existence CHECK was disabled, but pattern 5
    # still needed the underlying candidate-EXTRACTION). Now that analyze_pattern1() actually
    # runs its full extraction for EKW too (see that function's 2026-09-14 fix note), this
    # function can go back to simply reusing pattern1_result["candidates_considered"] for both
    # formats -- one code path, no format branching, same as before EKW existed.
    considered = pattern1_result["candidates_considered"]

    if considered:
        result["contradicting_named_files"] = list(considered)

    for m in ATTACH_RE.finditer(scan_text):
        ctx_start = max(0, m.start() - 40)
        ctx_end = min(len(scan_text), m.end() + 40)
        result["contradicting_attach_references"].append(
            scan_text[ctx_start:ctx_end].strip()
        )

    result["fired"] = bool(
        result["contradicting_named_files"] or result["contradicting_attach_references"]
    )
    return result


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir):
    task_id = task_dir.name
    result = {
        "task_id": task_id,
        "task_format": None,
        "instruction_md_exists": False,
        "environment_workspace_exists": False,
        "pattern1": None,
        "pattern3": None,
        "pattern5": None,
        "ekw_verifier_parse_errors": [],
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
        full_text = instr_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        result["status"] = "skip"
        result["errors"].append(f"could not read instruction.md: {e}")
        return result

    ws_dir, task_format = resolve_workspace_dir(task_dir)
    result["task_format"] = task_format
    result["environment_workspace_exists"] = ws_dir.is_dir()
    if not ws_dir.is_dir():
        ws_rel = f"environment/{WORKSPACE_DIRNAME_BY_FORMAT[task_format]}/"
        result["errors"].append(
            f"{ws_rel} does not exist -- pattern 1 will report every named candidate as "
            "missing, and pattern 5 is not evaluated (see Known limits)"
        )

    scan_text = prompt_scan_text(full_text, task_format=task_format)
    graded_names, ekw_parse_errors = compute_graded_names(
        task_dir, full_text, task_format
    )
    result["ekw_verifier_parse_errors"] = ekw_parse_errors
    if ekw_parse_errors:
        result["errors"].append(
            f"tests/verifier.json had {len(ekw_parse_errors)} parse error(s) -- guard 4's "
            "graded-file cross-reference is incomplete for this task, see "
            "ekw_verifier_parse_errors"
        )

    p1 = analyze_pattern1(scan_text, graded_names, ws_dir, task_format=task_format)
    p3 = analyze_pattern3(full_text)
    p5 = (
        analyze_pattern5(scan_text, p1, ws_dir)
        if ws_dir.is_dir()
        else {
            "environment_is_placeholder": False,
            "placeholder_reason": None,
            "fired": False,
            "contradicting_named_files": [],
            "contradicting_attach_references": [],
        }
    )

    result["pattern1"] = p1
    result["pattern3"] = p3
    result["pattern5"] = p5

    if p1["missing"] or p3["hits"] or p5["fired"]:
        result["status"] = "fail"
    else:
        result["status"] = "pass"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Check a task's instruction.md against its shipped environment for "
        "structural-audit patterns 1 (missing named input), 3 (unhydrated cloud-storage "
        "dependency), and 5 (placeholder environment contradicting a prompt that names "
        "required files)."
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
                "task_format": None,
                "status": "fail",
                "errors": [f"unhandled exception analyzing this task: {e}"],
                "pattern1": None,
                "pattern3": None,
                "pattern5": None,
            }
        results.append(r)
        p1 = r.get("pattern1") or {}
        p3 = r.get("pattern3") or {}
        p5 = r.get("pattern5") or {}
        print(
            f"    -> {r['status']}  "
            f"(fmt={r.get('task_format')}, "
            f"p1={p1.get('status', 'n/a')} missing={len(p1.get('missing', []))}, "
            f"p3 urls={len(p3.get('hits', []))}, "
            f"p5 fired={p5.get('fired', False)}, "
            f"{len(r.get('errors', []))} errors)",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    # EKW-port tallies -- new, additive. n_ekw_tasks / n_svc_pc_tasks let a caller confirm the
    # format-detection split without re-deriving it from raw results; n_pattern1_not_applicable_
    # ekw should equal n_ekw_tasks whenever every detected EKW task also has instruction.md (the
    # one path that reports task_format before pattern1 ever runs); the pattern 3/5 totals are
    # the real, previously-open-question counts this port was built to answer.
    n_ekw_tasks = sum(1 for r in results if r.get("task_format") == "ekw")
    n_svc_pc_tasks = sum(1 for r in results if r.get("task_format") == "svc_pc")
    # 2026-09-14: pattern 1 now actually runs (status "checked") for EKW tasks too, instead of
    # short-circuiting to "not_applicable_ekw" -- see analyze_pattern1()'s fix note. That old
    # status value should never appear again; n_pattern1_not_applicable_ekw is kept in the
    # aggregate (now always 0 in practice) specifically so a report reader can confirm the old
    # blanket disable is gone, rather than silently dropping the field. The real, newly-answered
    # question is n_pattern1_missing_ekw / n_pattern1_missing_svc_pc below: how many tasks of
    # each format have a genuine missing-input finding now that pattern 1 runs for both.
    n_pattern1_not_applicable_ekw = sum(
        1
        for r in results
        if (r.get("pattern1") or {}).get("status") == "not_applicable_ekw"
    )
    n_pattern1_missing_ekw = sum(
        1
        for r in results
        if r.get("task_format") == "ekw" and (r.get("pattern1") or {}).get("missing")
    )
    n_pattern1_missing_svc_pc = sum(
        1
        for r in results
        if r.get("task_format") == "svc_pc" and (r.get("pattern1") or {}).get("missing")
    )
    n_pattern3_hits_total = sum(
        len((r.get("pattern3") or {}).get("hits", [])) for r in results
    )
    n_pattern5_fired_total = sum(
        1 for r in results if (r.get("pattern5") or {}).get("fired")
    )
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_skip": n_skip,
        "n_ekw_tasks": n_ekw_tasks,
        "n_svc_pc_tasks": n_svc_pc_tasks,
        "n_pattern1_not_applicable_ekw": n_pattern1_not_applicable_ekw,
        "n_pattern1_missing_ekw": n_pattern1_missing_ekw,
        "n_pattern1_missing_svc_pc": n_pattern1_missing_svc_pc,
        "n_pattern3_hits_total": n_pattern3_hits_total,
        "n_pattern5_fired_total": n_pattern5_fired_total,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_skip} skip out of {len(results)} task(s)"
    )
    print(
        f"format split: {n_svc_pc_tasks} svc_pc / {n_ekw_tasks} ekw "
        f"(pattern 1 not_applicable_ekw on {n_pattern1_not_applicable_ekw} of them [should be "
        f"0 post-fix]; pattern 1 missing: {n_pattern1_missing_svc_pc} svc_pc / "
        f"{n_pattern1_missing_ekw} ekw tasks; "
        f"pattern 3 hits total: {n_pattern3_hits_total}; "
        f"pattern 5 fired total: {n_pattern5_fired_total})"
    )
    for r in results:
        if r["status"] != "fail":
            continue
        p1 = r.get("pattern1") or {}
        p3 = r.get("pattern3") or {}
        p5 = r.get("pattern5") or {}
        note_parts = []
        if p1.get("missing"):
            note_parts.append(
                "p1 missing: " + ", ".join(m["filename"] for m in p1["missing"])
            )
        if p3.get("hits"):
            note_parts.append("p3 urls: " + ", ".join(h["url"] for h in p3["hits"]))
        if p5.get("fired"):
            note_parts.append(
                f"p5 contradiction (placeholder: {p5.get('placeholder_reason')})"
            )
        print(f"  {r['task_id']}: fail  [{'; '.join(note_parts)}]")
        for e in r.get("errors", []):
            print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
