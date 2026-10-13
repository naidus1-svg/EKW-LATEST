#!/usr/bin/env python3
"""Undisclosed terminology check: does a rubric criterion require the solver's output to use
an ID scheme, naming convention, code, abbreviation, or piece of terminology that is never
introduced anywhere in the task's own solver-facing `instruction.md`?

Why this exists: a criterion can be internally well-formed (real requirement sentence, real
expected value -- rubric_schema_check.py's territory) and still be unpassable, because it
grades the solver's own deliverable against a naming scheme only the grading config knows
about. `instruction.md` is the entire world the solver reads; if a criterion says the workbook
must carry `Cite_L2_01`...`Cite_L2_07` tabs and instruction.md never says so, a solver who does
everything else right has no way to guess that exact string. This is a different failure than
environment_input_check.py's pattern 1 (instruction.md names an input FILE that does not exist
in the environment): here the direction is reversed -- the GRADING CONFIG names a TERMINOLOGY
or NAMING CONVENTION that the solver-facing prompt never discloses.

Confirmed by hand against this corpus before any code was written (see the commit message and
the accompanying report for the full record): SVC-PC-88-0-0 requires "Cite_L2_01...Cite_L2_07"
workbook tabs, a "Trace tab", "Cite_*" formulas, an "Open_Items" header, and "OI-01...OI-08" open
item IDs -- none of which instruction.md ever states, it only describes the underlying concepts
in prose ("include a trace... flag every conflict"). The sibling task SVC-PC-88-1-0 repeats the
same "Cite_*" tab convention. SVC-PC-12-0-0 requires "SRC_Pricing/Pipeline/Assumptions" tabs with
no "SRC" anywhere in instruction.md. Two of the four originally-named candidate tasks
(SVC-PC-92-0-0, SVC-PC-92-1-0) turned out NOT to show this defect on hand review -- their
criteria are content-substance requirements (specific facts findable by reading the named
source files), not undisclosed naming conventions -- and are reported as such rather than forced
into a finding. The originally-cited calibration case, SVC-PC-6-1-0 criterion r13, also does not
show the "Cite_L2" pattern on direct inspection: r13 is about which files count as source
evidence, not tab naming. Both of these disagreements with the brief that produced this script
are called out explicitly in the accompanying report, per the standing rule that a claim needs
its own source, not another script's memory of one.

What counts as a candidate term, and why the bar is this narrow: a plain English capitalized
phrase ("Cover tab", "Executive Summary") is NOT enough by itself -- a corpus-wide scan found
hundreds of tasks using ordinary business vocabulary this way, and flagging all of it would drown
every real finding. A candidate must have CODE SHAPE (an underscore-joined multi-segment token,
a dash-joined alphanumeric code, or a token carrying a literal wildcard `*`) or sit within a
narrow window of an explicit scheme-cue word (convention, scheme, naming, labeled, named,
tagged, header, tab/tabs). A wildcarded token (`Cite_L2_*`) is treated as sufficient on its own:
a corpus scan found it in only 3 of 609 SVC-PC tasks, and nobody writes a literal asterisk into a
rubric except to describe a naming pattern. Filenames (anything immediately followed by a known
document extension) are explicitly out of scope -- that is environment_input_check.py's and
deliverable_filename_check.py's territory, not this script's.

What it checks, per criterion, per task:
  1. Extracts candidate scheme-shaped terms from the criterion's description text (SVC-PC:
     judge.toml `description`; EKW: verifier.json `assertion.rubric.prompt`, or for
     deterministic assertions, `metadata.how_justification` + `why_justification` + the
     `deterministic.path` field name).
  2. For each candidate, searches instruction.md for the exact term (case-insensitive), a
     close variant (underscores/dashes normalized to spaces, so "Open_Items" clears against
     prose reading "Open Items Register"), or (2026-09-15) a close paraphrase (the term's own
     significant words found near each other, in any order); then checks whether a real
     environment file's name or (2026-09-15) content already discloses it -- see is_disclosed()
     and the 2026-09-15 update below for the exact checks and their deliberate scope limits.
  3. Flags every candidate not found in any of the above.

Exit 0 clean, 1 findings, 2 bad usage. Needs Python 3.11+ for tomllib. Was stdlib-only through
v1; v2 (2026-09-15) added openpyxl, python-docx (optional), and pypdf for pattern-1 environment
file text extraction, all auto-installed or gracefully degraded the same way this folder's
answer_key_rubric_leak_check.py already handles its own golden-file readers -- see the
2026-09-15 update below.

    python undisclosed_terminology_check.py <package_root> [--task TASK-ID] [--json out.json]

Provenance: built fresh for this project. `check_task()` / `check_task_dispatch()` follow the
same dual-format shape and CLI as this folder's `rubric_schema_check.py`; `check_task_ekw()`
parses `tests/verifier.json` directly (no shared EKW parser module exists in this repo as of
this writing -- a `deterministic-checks/ekw_verifier_json.py` was referenced as prior art when
this script was commissioned but does not exist on this branch; verified by a repo-wide grep,
not assumed).

Known limits, disclosed rather than silently dropped:
  - Regex/shape based, not semantic. A scheme-shaped term paraphrased differently in
    instruction.md (spelled out in words with no underscore/dash at all) can read as
    "undisclosed" when a human would call it disclosed. The space-normalized variant check
    catches the common case (underscore vs. space) but not a full paraphrase.
  - Through v1, a term disclosed somewhere OTHER than instruction.md (an environment file the
    solver is told to read) was not credited at all -- this script only read instruction.md.
    v2 (2026-09-15) partially closes this: see pattern 1 in the update below for what is now
    credited (files directly inside environment/initial_workspace/) and its deliberate,
    disclosed non-recursive scope limit.
  - Deterministic-assertion JSON field names are checked as literal text; a field disclosed via
    a rendered table (as EKW "strict contract" schemas usually are) matches fine, but a field
    disclosed only via an ambiguous prose description of the same concept may not.
  - The denylist of well-known codes (W-2, GS1-128, GAAP, ...) is necessarily incomplete; a
    term this project has not seen before that is nonetheless common knowledge outside it will
    still be flagged. Every finding carries its snippet so a human clears these in seconds.
  - (2026-09-15) Environment-file disclosure credit (pattern 1 below) only reads files
    DIRECTLY inside environment/initial_workspace/, never a nested subdirectory such as
    _corpus_subtree/. A task whose real materials sit one or more folders deep gets none of
    this credit; see the update below for why that scope is deliberate, not left unfinished.
  - (2026-09-15) The grader-enumeration exclusion (pattern 3) only fires on 3+ same-prefix
    dash-codes packed into ONE description. A lone rubric-invented shorthand cited once (e.g.
    "PP12-31") is not caught and stays flagged.
  - (2026-09-15) The filename-without-extension credit (pattern 4) only matches a REAL file's
    own stem (exact, or exact-prefix plus "-<digits>"). A term that merely resembles a
    filename but names nothing that actually exists in the environment is unaffected.
  - (2026-09-15) The paraphrase credit (pattern 5) requires 2+ significant words (alphabetic,
    3+ characters, non-stopword) in the term itself, found in instruction.md adjacent, in the
    same order, with nothing but whitespace/hyphens and an optional stopword between each
    consecutive pair. A single-word paraphrase, a reordering, or one with a real (non-stopword)
    word inserted between two of the term's words, is not caught.

2026-09-15 update -- five false-positive patterns fixed, found in a hand triage of 40 real
flagged SVC-PC tasks against C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready (34 of 40
false; SVC-PC-26-4-0 and SVC-PC-10-5-0 excluded from this pass, under separate investigation
for an unrelated structural defect; the rest left flagged as real, including the two
re-verified below):

  1. SKU/product/policy/PO/incident/vendor codes disclosed INSIDE a binary source file
     (xlsx/pdf/docx) under environment/initial_workspace/, which this script never read at all
     before this update (it only ever read instruction.md). Confirmed real: SVC-PC-12-5-0's
     "CS-STD-01"/"CS-KNG-01" SKU codes sit in
     environment/initial_workspace/Product_Catalog_Q4.pdf ("1 CS-STD-01 Cirrus Pillow...",
     extracted and read directly, not assumed from the filename) and three sibling xlsx
     files, none of which instruction.md repeats but all of which the solver has direct,
     undisguised access to. The biggest of the five patterns by task count (around two dozen
     of the 34).
     Fix: read_environment_text() extracts every xlsx/xlsm/docx/pptx/pdf/csv/txt/md/json file
     that sits DIRECTLY inside environment/initial_workspace/ (openpyxl, python-docx, this
     folder's own zipfile-based pptx-XML reader matching answer_key_rubric_leak_check.py's,
     and pypdf for pdf -- none of which this script used before). is_disclosed() credits a
     term found there the same way it already credits instruction.md.
     Deliberately NOT recursive, and this is a disclosed scope limit, not an oversight: many
     of this corpus's tasks mirror an entire simulated company Drive into
     environment/initial_workspace/_corpus_subtree/ (many nested folders) instead of curating
     a flat, task-specific file set. Recursing into that subtree is unsafe on THIS corpus,
     proven rather than assumed: SVC-PC-63-4-0 and SVC-PC-12-2-0 (the two independently
     confirmed-real tasks re-verified for this update, see below) sit on the exact same shared
     _corpus_subtree/Company Shared Drive__Marketing/{Pricing_Matrix.xlsx,
     Product_Catalog_Q1..4.pdf} files as multiple confirmed-false-positive sibling tasks that
     reference the identical SKU catalog (e.g. SVC-PC-26-3-0's same "CS-STD-01"/"CS-KNG-01").
     A recursive credit would have cleared the real tasks too. Scoping to direct children
     only fixes every task whose environment is a flat, curated file set (most of the named
     false positives) and leaves the nested-_corpus_subtree-shaped false positives as an
     unresolved, disclosed gap -- see Known limits.

  2. An explicit "don't invent this" negative example -- the flagged term appears only inside
     a parenthetical the criterion itself marks as a rejected/forbidden answer: "no invented
     IDs ('84-SBA-CR-9847-21' rejected)" (SVC-PC-25-1-0 c30); "(e.g. policy
     84-SBA-CR-9847-21) = partial/fail" (SVC-PC-25-7-0 c20); "no internal tier-style codes
     (e.g. 'L2-0x') ... Fail if internal tier-style codes appear" (SVC-PC-77-0-0 c19 -- filed
     under a different pattern name in the triage, but the same negative-example shape on
     direct inspection of the live judge.toml).
     Fix: negative_example_spans() excludes any candidate sitting inside a parenthetical that
     is either preceded, in the same clause (no sentence-ending punctuation in between), by a
     bare "no", or followed shortly by "rejected/invented/fabricated/disallowed/not accepted"
     or "partial/fail"/"fail".

  3. Rubric-internal grader enumeration: 3 or more dash-codes sharing one letter prefix,
     packed into a SINGLE criterion's own description as a list. SVC-PC-94-0-0 c3: "PR-1 IMS
     ($383,819 feed variance); PR-2 3PL ship sync; PR-3 attribution join; PR-4 CloudHost
     warehouse; PR-5 vendor DPA + SOC 2" -- five self-contained plain-English facts the
     grader numbered PR-1..PR-5 purely to keep its own list organized; the solver's
     deliverable is never asked to reproduce the labels themselves.
     Fix: extract_candidates() groups same-prefix DASH_CODE_RE matches within one description
     and drops the whole group once it has 3+ members.
     Calibrated specifically against being too broad: SVC-PC-63-4-0's "PPC-001".."PPC-006"
     (below, confirmed real) has the same sequential-code surface shape, but each code
     appears ALONE in its own criterion's description (one PPC-code per criterion, never 3+
     together) -- the group-size-3 threshold leaves it untouched, verified by re-running the
     script, not assumed from the shape alone. SVC-PC-20-1-0 r6's "PP12-31" (also cited in the
     triage for this pattern) is the same grader-shorthand idea -- a rubric-invented
     "ACH-ADP-PP12-31" reference for a bank transaction that a direct text search confirms
     does NOT appear in either real environment file (svb_statement.csv,
     Q4_Processing_Statement.pdf) -- but it is a lone occurrence, not a 3+ list, so this
     narrow rule does not reach it and it stays flagged: a disclosed residual false positive
     rather than a broader rule this pass had no second real example to calibrate against.

  4. A filename cited without its extension, so the existing _followed_by_extension() check
     (which only looks at the character immediately after the match) never fires: "sources
     named: Payroll_Register_2021-01..12; Year_1_Balance_Sheet." (SVC-PC-11-3-0 r034) cites
     the real files Payroll_Register_2021-01.xlsx .. -12.xlsx and Year_1_Balance_Sheet.xlsx
     (both confirmed present under environment/initial_workspace/ by directory listing, not
     assumed from the name alone).
     Fix: environment_filename_stems() lists every real file's extension-stripped basename
     anywhere under environment/initial_workspace/ (recursive -- a filename match is a much
     lower-risk signal than a content search: it requires an exact match, or an exact prefix
     plus a "-<digits>" continuation, against a real file's own stem, not a substring inside
     free text). is_disclosed() credits a term that clears either form.
     SVC-PC-94-8-0 was named alongside 11-3-0 for this pattern in the triage, but its one
     finding ("dual-3PL" in r07) is not a missing-extension case on inspection -- nothing in
     its environment is a file named anything like "dual-3PL". It still clears, just via
     pattern 1 above rather than pattern 4: environment/initial_workspace/Q4_Ops_Summary.docx
     (a flat, top-level file, confirmed by directory listing) says "The dual-3PL model built
     after August..." in plain prose.

  5. Close paraphrase of already-disclosed terminology: the disclosure and the candidate
     share the same significant words, in the same order, joined by a different connector.
     SVC-PC-75-8-0's instruction.md says "growth-program spend with return" in prose; the
     rubric's own tab convention compresses this to "Spend_and_Return" ("with" and "and" are
     both mere connectors). Neither the exact match nor the existing underscore/dash-vs-space
     normalization catches this.
     Fix: is_disclosed() adds a fallback used ONLY when the term's significant words
     (alphabetic, 3+ characters, common-stopword-filtered) number two or more: it credits the
     term if those words occur, in order, adjacent in instruction.md -- nothing but
     whitespace/hyphens and an optional single stopword between each consecutive pair.
     Deliberately an ADJACENCY check, not a loose character-distance window: a window version
     was tried first and caught over-flagging in validation on SVC-PC-88-1-0 (confirmed real,
     see the module docstring's original calibration section above), whose required tab
     "Correcting_Entries" sits close enough to instruction.md's "prepare correcting journal
     entries" to clear under any generous window, purely because "journal" is short -- a real
     content word between the two matched words, not a connector, so it must NOT count as a
     paraphrase. The adjacency version correctly keeps "Correcting_Entries" flagged (re-run
     and confirmed) while still catching "Spend_and_Return" (gap = stopword "with").
     Also deliberately narrow so it cannot reach dash-codes or single-word terms at all:
     "OI-08" and "STD-01" normalize to a single significant word each ("oi" and "std" are
     under the 3-character floor and the digit segment is dropped entirely, so there are never
     2+ words to check adjacency between), so this fallback structurally cannot touch a
     SKU-code or sequential-ID finding; it only ever fires for a multi-word, underscore/
     dash-joined phrase.

Both re-verified as genuinely real for this update, not re-derived from the triage alone:
SVC-PC-12-2-0's 14 "CS-STD-01"/"CS-KNG-01" findings and SVC-PC-63-4-0's 6
"PPC-001".."PPC-006" findings both survive every fix above, confirmed by re-running the script
against each afterward. One disclosed tension left for a human rather than resolved silently:
SVC-PC-12-2-0's own Pricing_Matrix.xlsx
(environment/initial_workspace/_corpus_subtree/Company Shared
Drive__Marketing/Pricing_Matrix.xlsx -- exactly what instruction.md's "using the Pricing
Matrix costs" points the solver at) contains a "CS-STD-01" row with the exact MSRP ($109) and
unit COGS ($34) the flagged criteria expect, the same disclosure shape that makes
SVC-PC-12-5-0 a confirmed false positive. Pattern 1's fix does not reach that file (nested
under _corpus_subtree/, outside the deliberately non-recursive scope above), so the finding
is unchanged by this pass. Whether that is the right call for this specific task, or a false
positive sharing 12-5-0's root cause that pattern 1's scope limit happens to spare, is for
whoever confirmed it real to weigh in on, not something this pass re-litigates unilaterally.

A second disclosed tension, found generalizing pattern 3 to the full corpus rather than in the
original 40-task triage: SVC-PC-80-5-0 criterion b2 ("Every check row states the tolerance
applied and its pack reference (TO-1/TO-2/TO-3/TO-7 or the 5.3 exact-by-default rule)") loses
all four TO-N findings to the group-size-3 rule, the same as SVC-PC-94-0-0's PR-1..PR-5. But
unlike PR-1..PR-5 (where each code maps to an independently-checkable fact -- an IMS variance,
a 3PL sync -- and the solver never needs to write "PR-1" itself) and AJE-1..5 in SVC-PC-14-0-0
(each maps to a real JE-number the solver looks up), b2's own wording asks the solver's
deliverable to literally STATE the "TO-N" pack reference as part of its output, and no file
under SVC-PC-80-5-0's environment/initial_workspace/ (searched by name and, for this
investigation only, by content, recursively) discloses a "TO-1".."TO-7" tolerance-pack
definition anywhere, despite instruction.md telling the solver to use "the shared pack." This
may be a genuine undisclosed-terminology defect the group-size-3 rule wrongly suppresses, or
the shared pack may simply be missing from this environment mirror (environment_input_check.py
territory, not this script's). Left as a flagged, not silently resolved, judgment call rather
than narrowed into a rule with no second confirmed-real example to calibrate against; tightening
pattern 3 further on the strength of one ambiguous case risks reintroducing the AJE-1..5 /
PR-1..5 false positives without a clear replacement rule.

Status: v2 (2026-09-15). v1 was hand-validated against the 4 named candidate tasks in
SVC-PC-88-0-0/92-0-0/92-1-0/80-7-0 (1 of 4 confirmed defective on independent hand review --
see the commit message), then run at full corpus scale: SVC-PC 600 tasks, 564 clean / 36
flagged, 78 findings; EKW 274 tasks, 254 clean / 20 flagged, 32 findings. Precision was tuned
against real corpus false positives found during validation, not assumed -- see the
citation-parenthetical and temporal-code exclusions above, each added after a confirmed
over-flag. v2 added the five fixes above, hand-triaged against 40 real flagged SVC-PC tasks and
re-validated at full corpus scale against the SAME corpus root immediately before and after
(the two runs are minutes apart, not the v1 baseline recorded above, which is against a
corpus snapshot from an earlier date and no longer directly comparable): 600 SVC-PC tasks,
495 clean / 105 flagged / 396 findings before this update, 524 clean / 76 flagged / 277
findings after -- a real, non-total reduction (findings did not drop to zero anywhere near
corpus-wide), and re-confirmed after the fact that no task's finding count INCREASED and no
task gained a finding it did not already have (every clear is a strict subset of the
before-state). SVC-PC-12-2-0 and SVC-PC-63-4-0 (14 and 6 findings respectively) are unchanged
by any of the five fixes, verified by direct re-run, not by construction alone.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.stderr.write("needs Python 3.11+ for tomllib\n")
    raise SystemExit(2)

# Windows console defaults to cp1252, which cannot encode every character that shows up in
# real judge.toml/verifier.json/instruction.md text (arrows, curly quotes, em dashes). Force
# UTF-8 with replacement so a printable-but-non-cp1252 character never crashes a corpus sweep
# partway through -- same fix as this folder's answer_key_content_leak_check.py.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 2026-09-15: environment/initial_workspace/ text extraction for pattern-1 disclosure credit
# (see the module docstring's update section). openpyxl and pypdf auto-install the same way
# this folder's answer_key_rubric_leak_check.py already does for its own golden-file text
# extraction; python-docx degrades to "no text" rather than failing the whole script, matching
# that same script's HAVE_PYTHON_DOCX fallback, since a missing docx reader should shrink this
# check's recall, not crash a corpus sweep.
try:
    import openpyxl
except ModuleNotFoundError:  # pragma: no cover
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "openpyxl", "--quiet"], check=True
    )
    import openpyxl

try:
    import docx as _python_docx

    HAVE_PYTHON_DOCX = True
except ModuleNotFoundError:  # pragma: no cover
    HAVE_PYTHON_DOCX = False

try:
    import pypdf
except ModuleNotFoundError:  # pragma: no cover
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "pypdf", "--quiet"], check=True
    )
    import pypdf

# ---------------------------------------------------------------------------
# candidate extraction
# ---------------------------------------------------------------------------

# Document/media extensions -- a token immediately followed by one of these is a filename,
# environment_input_check.py's and deliverable_filename_check.py's territory, not ours.
_EXT_RE = re.compile(
    r"\.(xlsx|xlsm|xls|docx|doc|pptx|ppt|csv|pdf|txt|json|md|zip|png|jpe?g)\b", re.I
)

# Shape 1: a wildcarded token, e.g. Cite_L2_*, Cite_*, SRC_*. Requires at least one
# underscore/dash separator before the star so bare math notation (z*, d*, Q*) does not match
# -- seen in the wild in this corpus and confirmed harmless (statistical critical-value
# notation, not a naming scheme). The trailing group allows an empty alnum segment so both the
# one-segment form (Cite_*) and the multi-segment form (Cite_L2_*) match.
WILDCARD_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]*)+\*")

# Shape 2: underscore-joined token, 2+ segments (e.g. Cite_L2_01, SRC_Pricing, Open_Items).
UNDERSCORE_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+){1,}\b")

# Shape 3: dash-separated alphanumeric code with a digit segment (e.g. OI-01, STD-01, L2-05).
# Deliberately narrower than "any dash": requires letters then digits either side of the dash
# so "must-pass" / "cash-flow" style plain-English hyphenation never matches.
DASH_CODE_RE = re.compile(r"\b[A-Za-z]{1,6}[0-9]{0,3}-[0-9]{1,4}[A-Za-z]{0,3}\b")

# A DASH_CODE_RE match's own letter prefix, STARTING with 2+ uppercase letters ("OI-01",
# "STD-01", "PPC-003", "FY23-25" -- the last has trailing digits before the dash, still counts,
# `.match()` doesn't require consuming the whole prefix), reads as a genuine internal
# abbreviation regardless of nearby cue words -- see the carve-out in extract_candidates()
# below for the 2026-09-15 finding and calibration (this is exactly the pattern validated
# against a real 80-task sample; do not add a trailing `$` anchor without re-validating, it
# would silently exclude cases like FY23-25 that were part of the calibration).
ALLCAPS_PREFIX_RE = re.compile(r"^[A-Z]{2,}")

# A dash-code match whose letter part is a month name or a bare period word (year/quarter/
# week/...) is a date, not a naming scheme -- "Dec-22", "Year-2", "Q-4" all match DASH_CODE_RE's
# shape but are ordinary temporal references. Confirmed over-flagging in validation.
_TEMPORAL_PREFIX_RE = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
    r"|year|yr|qtr|q|fy|cy|month|mo|wk|week|day)$",
    re.I,
)

# Scheme-cue words: on their own, far too common to flag anything from (a corpus scan found
# "labeled"/"convention"/"tab" alone in 700+ of 609 SVC-PC tasks' criteria). They only matter
# as a proximity window around a shape-2/shape-3 candidate.
CUE_RE = re.compile(
    r"\bconventions?\b|\bschemes?\b|\bnaming\b|\bformats?\b|\blabell?ed\b"
    # "named" as a naming-scheme cue ("Trace tab named X") is wanted; "named" as an adjective
    # for a pre-disclosed category ("the named files/inputs/sources/corpus", seen 260+ times
    # in this corpus, almost always followed by a parenthetical list of already-disclosed
    # source filenames, not an output naming convention) is excluded via negative lookahead --
    # confirmed false-positive-prone in validation (SVC-PC-39-3-0's "named Inputs (...)").
    r"|\bnamed\b(?!\s+(?:files?|inputs?|sources?|corpus))"
    r"|\btagged\b|\bheaders?\b|\btabs?\b",
    re.I,
)
CUE_WINDOW = 60  # chars either side of a cue match to look for a shape-2/3 candidate

# 2026-09-16 fix (round 53, bug 2): named-source-origin exemption. An allcaps-prefix or
# wildcard cue on an identifier-shaped term (SKU code, policy number, cert serial, bank
# memo code) is not "undisclosed terminology" when instruction.md already names a specific
# source document as the origin of that class of code/value. The solver reads the value
# directly off the named source; pre-stating the exact token would be answer-key leakage,
# not a terminology fix. Confirmed real across 9 tasks / 29 false positives in the round-53
# bug report. The narrower single-step variant from the report: if instruction.md contains
# ANY source-naming directive AND the flagged token matches the identifier shape, suppress.
# Calibrated to NOT match SVC-PC-63-4-0's instruction.md (which mentions "price matrix" in
# passing but has no directive phrase), so its 6 confirmed-real PPC-001..PPC-006 findings
# stay flagged.
SOURCE_NAMING_DIRECTIVE_RE = re.compile(
    r"\bpricing matrix\b"
    r"|\bin-force policies\b"
    r"|\bdirectly from the policies\b"
    r"|\bread the schemas\b"
    r"|\bcite business-readable\b"
    r"|\bbusiness-insurance policy\b"
    r"|\bbuild it from your files\b"
    r"|\bfrom your files\b"
    r"|\bnamed source\b"
    r"|\bsource-room\b"
    r"|\bcite the exact file\b"
    r"|\bsource:\s",
    re.I,
)
IDENTIFIER_SHAPE_RE = re.compile(r"^[A-Z]{2,}[-_]?[0-9A-Z]*")

# Well-known codes/abbreviations that are code-shaped but common knowledge, not internal
# jargon -- never flag these even if a cue word sits nearby. Necessarily incomplete; see the
# module docstring's "known limits".
DENYLIST = {
    "w-2",
    "w-4",
    "w-9",
    "w2",
    "w4",
    "w9",
    "i-9",
    "i9",
    "1099",
    "401k",
    "941",
    "form-941",
    "gs1-128",
    "ispm-15",
    "asc-718",
    "asc718",
    "asc-606",
    "asc606",
    "gaap",
    "sox",
    "hipaa",
    "pci",
    "pci-dss",
    "kpi",
    "roi",
    "raci",
    "sop",
    "sops",
    "faq",
    "yoy",
    "mom",
    "qoq",
    "ttm",
    "ytd",
    "eod",
    "eom",
    "cogs",
    "gl",
    "tb",
    "aov",
    "gmv",
    "ap",
    "ar",
    "fte",
    "nda",
    "msa",
    "sla",
    "sku",
    "p&l",
    "pnl",
    "b2b",
    "b2c",
    "eoy",
    "cy",
    "fy",
    "nps",
    "csat",
    "okr",
    "ebitda",
    "n-a",
    "na",
}


def _followed_by_extension(text: str, end_pos: int) -> bool:
    return bool(_EXT_RE.match(text, end_pos))


# Two provenance-citation shapes confirmed in validation to sit on the SAME kind of
# underscore/dash-coded token this script otherwise looks for, but pointing the other way: they
# tell a human grader WHERE in the golden/reference answer a figure is grounded, not what the
# SOLVER's own deliverable must be named or labeled. Both were caught over-flagging in
# validation before being excluded:
#   "(Presented in WC_Baseline tab)" / "(Presented in WC_Baseline tie-out)" -- a location inside
#     the golden workbook, not a requirement that the solver's tab be named WC_Baseline.
#   "(SRC-1; WS-1; SRC-8)" -- a citation list of internal source-document reference codes, not
#     terminology the solver's deliverable needs to contain.
_PRESENTED_IN_RE = re.compile(r"\(presented in[^)]*\)", re.I)
_PAREN_RE = re.compile(r"\([^)]*\)")
# A citation-list parenthetical's inner text has no real English word (3+ lowercase letters in
# a row) and carries at least one dash-code shape -- "(SRC-1; WS-1-WS-6; SRC-2-SRC-9)" matches
# (only codes, semicolons, dashes/en-dashes as range separators), "(operating model)" does not
# (real words), so an ordinary descriptive parenthetical is never swept in by accident.
_CITATION_INNER_WORD_RE = re.compile(r"[a-z]{3,}")
_CITATION_INNER_CODE_RE = re.compile(r"[A-Za-z]{1,6}-\d{1,4}")


def _looks_like_citation_list(inner: str) -> bool:
    return not _CITATION_INNER_WORD_RE.search(inner) and bool(
        _CITATION_INNER_CODE_RE.search(inner)
    )


def _citation_spans(desc: str) -> list[tuple[int, int]]:
    spans = [m.span() for m in _PRESENTED_IN_RE.finditer(desc)]
    for m in _PAREN_RE.finditer(desc):
        if _looks_like_citation_list(m.group(0)):
            spans.append(m.span())
    return spans


def _in_span(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= pos < e for s, e in spans)


# Pattern 2 (2026-09-15): a criterion citing an example value the solver must NOT produce --
# "no invented IDs ('84-SBA-CR-9847-21' rejected)" (SVC-PC-25-1-0 c30), "(e.g. policy
# 84-SBA-CR-9847-21) = partial/fail" (SVC-PC-25-7-0 c20), or "no internal tier-style codes
# (e.g. 'L2-0x') ... Fail if internal tier-style codes appear" (SVC-PC-77-0-0 c19). All three
# read on the same code-shaped token this script otherwise looks for, but the surrounding
# words say the opposite of an undisclosed requirement: this is an explicit wrong-answer
# example. See the module docstring's 2026-09-15 update for the full evidence.
# Preceding form: a bare "no" earlier in the SAME clause as the parenthetical (nothing but
# spaces/letters/"/"/"&"/"-" in between -- a period, comma, or semicolon breaks the clause, so
# an unrelated "no" much earlier in the sentence never reaches across it).
_NEG_PRECEDING_RE = re.compile(r"\bno\b[ A-Za-z/&-]{0,40}$", re.I)
# Following form: the parenthetical is immediately followed (only whitespace/"=" in between)
# by "partial/fail" or bare "fail", or within 10 chars by "rejected"/"invented"/"fabricated"/
# "disallowed"/"not accepted".
_NEG_FOLLOWING_RE = re.compile(
    r"^\s*(?:=\s*)?(?:partial\s*/\s*fail|fail\b)"
    r"|^[^.;]{0,10}\b(?:rejected|invented|fabricated|disallowed|not\s+accepted)\b",
    re.I,
)


def _negative_example_spans(desc: str) -> list[tuple[int, int]]:
    spans = []
    for m in _PAREN_RE.finditer(desc):
        before = desc[max(0, m.start() - 45) : m.start()]
        after = desc[m.end() : m.end() + 60]
        if _NEG_PRECEDING_RE.search(before) or _NEG_FOLLOWING_RE.match(after):
            spans.append(m.span())
    return spans


def _clean(term: str) -> str:
    # A trailing "*" is the wildcard signal itself (Cite_L2_*) -- keep it. Everything else at
    # the boundary is regex-capture noise (a trailing comma, a stray underscore/dash) and gets
    # trimmed.
    had_star = term.rstrip().endswith("*")
    t = term.strip().strip("_-.,;:()[]{}\"'*")
    return t + "*" if had_star else t


def extract_candidates(desc: str, ekw: bool = False) -> list[dict]:
    """Candidate scheme-shaped terms in one criterion's description text, deduplicated by
    lowercase form. Each candidate carries the term and why it was picked up (for reporting).

    `ekw`: the all-caps-prefix carve-out below is SVC-PC-only, not applied here when True.
    Confirmed 2026-09-15 on the real 274-task EKW corpus (not assumed from the SVC-PC
    validation): 679 of 705 total findings across 82 tasks came from this carve-out, and a
    spot check (task_108's US-0992/EE-0992/US-0440) found these are real claim/record IDs
    that appear in environment/data/*.csv -- discoverable by the solver, not an undisclosed
    naming scheme the solver would have to invent. EKW's whole-rubric-prompt scan (no
    Expected: clause to isolate a stated requirement from narrative text citing real records)
    makes this a structurally different false-positive risk than anything the SVC-PC
    calibration covered. Scoped off pending real EKW-specific calibration, the same pattern
    criterion_groundedness_check.py already uses for its own EKW-specific quoted/date downgrade.
    """
    out: list[dict] = []
    seen: set[str] = set()
    citation_spans = _citation_spans(desc)
    negative_spans = _negative_example_spans(desc)
    # Pattern 3 (2026-09-15) staging: allcaps-prefix DASH_CODE_RE candidates with NO
    # independent cue word are deferred here instead of appended immediately, so they can be
    # grouped by letter prefix and dropped as a group once 3+ share one prefix within this
    # description -- see the group-size check right after the loop below.
    allcaps_dash_pending: list[dict] = []

    for m in WILDCARD_TOKEN_RE.finditer(desc):
        if _followed_by_extension(desc, m.end()) or _in_span(m.start(), citation_spans):
            continue
        term = _clean(m.group(0))
        key = term.lower()
        if not term or key in seen or key in DENYLIST:
            continue
        seen.add(key)
        out.append({"term": term, "cue": "wildcard"})

    # Cue proximity is computed on absolute character distance between spans in the FULL
    # description, never by slicing out a window substring first -- a substring slice would
    # truncate a token that straddles the window edge, and a truncated token silently defeats
    # the file-extension exclusion below (the truncated end no longer sits right before the
    # ".docx"/".xlsx" that would have excluded it). Caught in validation: a truncated
    # "Cirrus_FY2021_Operational_Ca..." slipped past the extension check this way before the
    # fix.
    cue_spans = [m.span() for m in CUE_RE.finditer(desc)]
    for rx in (UNDERSCORE_TOKEN_RE, DASH_CODE_RE):
        for m in rx.finditer(desc):
            if _followed_by_extension(desc, m.end()):
                continue
            # "TabName!CellRef" -- an Excel cross-reference into the golden workbook, not a
            # naming convention the solver's own tab needs to match.
            if desc[m.end() : m.end() + 1] == "!":
                continue
            if _in_span(m.start(), citation_spans) or _in_span(
                m.start(), negative_spans
            ):
                continue
            if rx is DASH_CODE_RE and _TEMPORAL_PREFIX_RE.match(
                m.group(0).split("-", 1)[0]
            ):
                continue
            token = m.group(0)
            cue_word = None
            if cue_spans:
                cue_word = next(
                    (
                        desc[cs:ce]
                        for cs, ce in cue_spans
                        if cs - CUE_WINDOW <= m.end() and m.start() <= ce + CUE_WINDOW
                    ),
                    None,
                )
            # A dash-code whose letter prefix is 2+ ALL-CAPS letters ("OI-01", "STD-01",
            # "PPC-003") reads as a genuine internal abbreviation/code on its own, the same way
            # a wildcard token does -- no cue word needed. Confirmed on real data, 2026-09-15:
            # SVC-PC-88-0-0/jdg-03 ("OI-01"/"OI-08") has zero cue words anywhere in its
            # description, so it was invisible under the cue-only gate no matter how wide the
            # window got -- this was a real recall gap, not a calibration nuance. Deliberately
            # NOT extended to UNDERSCORE_TOKEN_RE (title-case tokens like "Open_Items" stay
            # cue-gated) or to a lowercase/mixed-case dash prefix ("Net-30", "grade-9",
            # "Tier-1") -- tested on a real 80-task sample: the all-caps-only version surfaces
            # 28 new candidates, overwhelmingly real-looking internal codes (vendor/PO/policy/
            # marketing-initiative numbers); a same-shape version without the all-caps
            # restriction surfaces 162 and is dominated by ordinary vocabulary (see
            # criterion_groundedness_check.py-style investigation, same session).
            allcaps_prefix_ok = (
                not ekw
                and rx is DASH_CODE_RE
                and ALLCAPS_PREFIX_RE.match(token.split("-", 1)[0])
            )
            if cue_word is None and not allcaps_prefix_ok:
                continue
            term = _clean(token)
            key = term.lower()
            if not term or key in seen or key in DENYLIST:
                continue
            if cue_word is None:
                # allcaps-prefix is the SOLE reason this one was picked up -- defer for the
                # pattern-3 group-size check below rather than appending directly.
                seen.add(key)
                allcaps_dash_pending.append(
                    {"term": term, "key": key, "prefix": token.split("-", 1)[0].upper()}
                )
                continue
            seen.add(key)
            out.append({"term": term, "cue": f"cue:{cue_word.strip().lower()}"})

    # Pattern 3 (2026-09-15): 3 or more dash-codes sharing one letter prefix, picked up ONLY
    # via the allcaps-prefix mechanism (no independent cue word) and packed into this ONE
    # description, read as the grader's own list-numbering shorthand rather than a naming
    # convention the solver must reproduce -- e.g. SVC-PC-94-0-0's "PR-1".."PR-5", five
    # self-contained facts the grader numbered purely to keep its own "Expected:" list
    # organized. Calibrated specifically against being too broad: SVC-PC-63-4-0's
    # "PPC-001".."PPC-006" has the same sequential-code surface shape, but each code sits
    # ALONE in its own criterion's description (never 3+ together), so the group-size-3
    # threshold leaves it untouched -- verified by re-running this script against that task,
    # not assumed from the shape alone. See the module docstring's update for both examples
    # and for SVC-PC-20-1-0's "PP12-31", a lone occurrence this narrow rule deliberately does
    # NOT reach.
    by_prefix: dict[str, list[dict]] = {}
    for cand in allcaps_dash_pending:
        by_prefix.setdefault(cand["prefix"], []).append(cand)
    for group in by_prefix.values():
        if len(group) >= 3:
            continue
        for cand in group:
            out.append({"term": cand["term"], "cue": "allcaps-prefix"})

    return out


# Pattern 5 (2026-09-15): a close paraphrase of already-disclosed terminology -- the same
# significant words, in the same order, rejoined by a stopword-equivalent connector instead of
# the term's own underscore/dash (which the plain space-normalized check above already
# handles). SVC-PC-75-8-0's instruction.md says "growth-program spend with return" in prose;
# the rubric's own tab convention compresses this to "Spend_and_Return" -- "with" and "and"
# are both mere connectors. See is_disclosed() and the module docstring's update for the full
# evidence and the deliberate scope limit.
#
# Deliberately NOT a loose "these words somewhere near each other" window -- that version was
# built, then caught over-flagging in validation on a task this docstring already documents as
# a confirmed-real defect: SVC-PC-88-1-0's required tab "Correcting_Entries" is genuinely
# undisclosed, but instruction.md's "prepare correcting journal entries" put both of the
# term's words within any generous character window, because "journal" happens to be short. A
# window has no way to tell "only a connector in between" (a real paraphrase) from "a whole
# other content word in between" (two words that are merely nearby, not a paraphrase of this
# term). The fix requires the gap between each consecutive pair of the term's own words to be
# ONLY whitespace/hyphens and, optionally, a stopword -- never another real word. Confirmed
# against both real cases during validation: matches "spend with return" (gap = stopword
# "with"), does not match "correcting journal entries" (gap = real word "journal").
_PARAPHRASE_STOPWORDS = frozenset(
    "and or the a an of to in on at by for with from is are was were be been "
    "this that these those it its as per via vs".split()
)
_PARAPHRASE_STOPWORD_ALT = "|".join(
    re.escape(w) for w in sorted(_PARAPHRASE_STOPWORDS, key=len, reverse=True)
)
_ALPHA_WORD_RE = re.compile(r"[a-z]+")


def _significant_words(term_norm: str) -> list[str]:
    """Alphabetic words of 3+ characters, common-stopword-filtered, from a space-normalized
    term, in their original order. Deliberately drops anything touching a digit -- "std 01" /
    "oi 08" yield only "std"/"oi", each under the 3-character floor on their own, so this
    structurally cannot fire on a bare dash-code or sequential ID (see the module docstring's
    update)."""
    return [
        w
        for w in _ALPHA_WORD_RE.findall(term_norm)
        if len(w) >= 3 and w not in _PARAPHRASE_STOPWORDS
    ]


def _words_within_window(words: list[str], text: str) -> bool:
    """True if `words` (2+ significant words, in the term's own order) occur in `text` as a
    contiguous run where each consecutive pair is separated by ONLY whitespace/hyphens and,
    optionally, a single stopword -- never another real word. See the pattern-5 comment above
    for why this is an adjacency check, not a loose character-distance window."""
    if len(words) < 2:
        return False
    gap = rf"[\s-]+(?:(?:{_PARAPHRASE_STOPWORD_ALT})[\s-]+)*"
    pattern = rf"\b{re.escape(words[0])}\b" + "".join(
        rf"{gap}\b{re.escape(w)}\b" for w in words[1:]
    )
    return re.search(pattern, text) is not None


# 2026-09-16 fix (pattern 6): a criterion can cite a SOLVER-GENERATED sequential ID --
# instruction.md discloses the numbering CONVENTION ("assign sequential three-digit IDs in the
# form OI-001, OI-002, OI-003..." / "number each open item sequentially starting at OI-01"),
# not a fixed lookup table, because the specific number (is this the 3rd open item the solver
# found, or the 8th?) is generated by the solver's own discovery order and cannot be pre-stated
# for the same structural reason a filename's contents can't be pre-stated. A criterion that
# cites one specific instance of that convention (e.g. "OI-08", or an "Expected: OI-01...OI-08
# present" range naming a COUNT of items under the same convention) is not citing hidden
# terminology -- the convention that generates it is already disclosed, in full, by name.
# Confirmed real against this corpus, not assumed from the shape alone: SVC-PC-6-1-0's
# instruction.md says "Give each open item a sequential three-digit ID in the form OI-001,
# OI-002, OI-003, and so on in the order you surface them" -- disclosing the OI- convention --
# and this exact phrasing explains all 12 of this task's real findings (OI-006 through OI-016,
# plus RL-214, matching the SAME task's separate "each line item carrying a sequential
# three-digit ID in the form RL-001, RL-002, RL-003" disclosure for a different prefix).
# SVC-PC-88-0-0's instruction.md says "number each open item sequentially starting at OI-01",
# and its one real finding is a criterion whose own description reads "Expected: OI-01...OI-08
# present" -- a range describing a count of 8 items under that same already-disclosed
# convention, not 8 separately-hidden facts. Deliberately narrow: only fires within one
# sentence-ish window (80 chars) of the word "sequential"/"sequentially" itself, so it cannot
# credit an unrelated dash-code that merely happens to share a prefix with something
# coincidentally near that word elsewhere in a longer instruction.md.
_SEQUENTIAL_CONVENTION_RE = re.compile(
    r"sequential\w*[^.]{0,80}?\b([a-z]{1,8})-0*\d+\b"
)
_SEQUENTIAL_ID_SHAPE_RE = re.compile(r"^([a-z]{1,8})-0*\d+$")


def _sequential_convention_prefixes(instr_text_lower: str) -> set[str]:
    """Lowercased ID prefixes (e.g. {"oi", "rl"}) for which instruction.md discloses a
    sequential, solver-generated numbering convention -- see _SEQUENTIAL_CONVENTION_RE's own
    comment for the real, hand-confirmed precedent this pattern is calibrated against.
    """
    return {m.group(1) for m in _SEQUENTIAL_CONVENTION_RE.finditer(instr_text_lower)}


def is_disclosed(
    term: str,
    instr_text_lower: str,
    instr_norm: str,
    env: "_EnvCache | None" = None,
) -> bool:
    """True if `term` (or a close variant) is disclosed to the solver. Checks, cheapest
    first:
      1. instruction.md, exact or underscore/dash-vs-space-normalized (v1 behavior, unchanged).
      2. instruction.md, close paraphrase: 2+ significant words of the term found adjacent,
         in order, with only whitespace/hyphens and an optional stopword between each
         consecutive pair (2026-09-15, pattern 5).
      3. instruction.md discloses a SEQUENTIAL, solver-generated numbering convention for this
         term's own prefix (2026-09-16, pattern 6) -- see _sequential_convention_prefixes().
      4. a real environment filename's exact stem, or stem-plus-"-<digits>" continuation
         (2026-09-15, pattern 4) -- cheap (a directory listing), tried before the expensive
         content read below.
      5. the text content of every file directly inside environment/initial_workspace/
         (2026-09-15, pattern 1) -- laziest and most expensive, tried last, and skipped
         entirely when `env` is None (no task_dir wired up by the caller).
    The wildcard star itself never appears in prose, so matching is done on the term's fixed
    prefix -- "Cite_L2_*" clears if instruction.md says "Cite_L2" or "Cite L2" anywhere, even
    though the literal string "Cite_L2_*" obviously never will.
    """
    t = _clean(term).lower().rstrip("*").rstrip("_-")
    if not t:
        return True
    if t in instr_text_lower:
        return True
    norm = re.sub(r"[_\-]+", " ", t).strip()
    if norm and norm in instr_norm:
        return True

    words = _significant_words(norm) if norm else []
    if len(words) >= 2 and _words_within_window(words, instr_text_lower):
        return True

    id_shape = _SEQUENTIAL_ID_SHAPE_RE.match(t)
    if id_shape and id_shape.group(1) in _sequential_convention_prefixes(
        instr_text_lower
    ):
        return True

    if env is None:
        return False

    stems = env.filename_stems()
    if t in stems or (norm and norm.replace(" ", "_") in stems):
        return True
    for stem in stems:
        if stem.startswith(t) and len(stem) > len(t) and stem[len(t)] in "_-0123456789":
            return True

    # Word-boundary-anchored, NOT a plain substring "in" check like the instruction.md checks
    # above -- confirmed necessary, not just cautious: on the real corpus, a raw substring
    # check credited "PR-1" (space-normalized "pr 1") as disclosed because "Apr 12" (a date,
    # tokenized "apr 12") contains "pr 1" as a coincidental run of characters spanning "Apr"
    # and "12". instruction.md is short enough that this collision risk was never exercised
    # in v1; environment text after this update can be many concatenated files, long enough
    # that it is. Left as-is for instruction.md above (unchanged v1 behavior, out of this
    # update's scope) but required here.
    env_lower, env_norm = env.text()
    if t and re.search(rf"(?<!\w){re.escape(t)}(?!\w)", env_lower):
        return True
    return (
        bool(norm)
        and re.search(rf"(?<!\w){re.escape(norm)}(?!\w)", env_norm) is not None
    )


def _snippet(desc: str, term: str, radius: int = 50) -> str:
    needle = _clean(term).lower().rstrip("*").rstrip("_-")
    idx = desc.lower().find(needle) if needle else -1
    if idx == -1:
        return desc[: 2 * radius].strip()
    start = max(0, idx - radius)
    end = min(len(desc), idx + len(term) + radius)
    return desc[start:end].strip()


# ---------------------------------------------------------------------------
# per-task checks -- SVC-PC (judge.toml) and EKW (verifier.json)
# ---------------------------------------------------------------------------


def _load_instruction(task_dir: Path) -> tuple[str, str] | None:
    p = task_dir / "instruction.md"
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    return text.lower(), re.sub(r"[_\-]+", " ", text.lower())


# ---------------------------------------------------------------------------
# environment/initial_workspace/ text extraction -- pattern-1 and pattern-4 disclosure credit
# (2026-09-15, see the module docstring's update section)
# ---------------------------------------------------------------------------

_PPTX_SLIDE_TEXT_RE = re.compile(r"<a:t>(.*?)</a:t>")


def _read_xlsx_text(path: Path) -> str:
    """Every cell value from every sheet, stringified and space-joined. Same library
    (openpyxl) this folder's answer_key_rubric_leak_check.py already uses for its own
    golden-file text extraction. Never raises: an unreadable workbook contributes no text
    rather than aborting the task's whole check."""
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception:
        return ""
    parts: list[str] = []
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell is not None:
                        parts.append(str(cell))
    except Exception:
        pass
    return " ".join(parts)


def _read_docx_text(path: Path) -> str:
    """Paragraph and table-cell text. Returns "" (not an error) when python-docx isn't
    installed -- see HAVE_PYTHON_DOCX above."""
    if not HAVE_PYTHON_DOCX:
        return ""
    try:
        d = _python_docx.Document(str(path))
    except Exception:
        return ""
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return " ".join(parts)


def _read_pptx_text(path: Path) -> str:
    """Every <a:t> text run in every slide XML -- a zip of XML files, read directly with
    zipfile/re so this script does not need a python-pptx dependency, matching this folder's
    answer_key_rubric_leak_check.py's own read_pptx_text()."""
    try:
        parts: list[str] = []
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                    xml = z.read(name).decode("utf-8", errors="replace")
                    parts.extend(_PPTX_SLIDE_TEXT_RE.findall(xml))
        return " ".join(parts)
    except Exception:
        return ""


def _read_pdf_text(path: Path) -> str:
    """Per-page extract_text(), space-joined. pypdf handles the digitally-generated PDFs this
    corpus uses (Product_Catalog_Q4.pdf and similar); a scanned/image-only PDF would need OCR
    (out of scope) and contributes no text rather than erroring."""
    try:
        reader = pypdf.PdfReader(str(path))
        return " ".join((pg.extract_text() or "") for pg in reader.pages)
    except Exception:
        return ""


def _read_plain_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


_BINARY_TEXT_READERS = {
    ".xlsx": _read_xlsx_text,
    ".xlsm": _read_xlsx_text,
    ".docx": _read_docx_text,
    ".pptx": _read_pptx_text,
    ".pdf": _read_pdf_text,
}
_PLAIN_TEXT_EXTS = {".csv", ".txt", ".md", ".json"}


def read_environment_text(task_dir: Path) -> str:
    """Concatenated text of every file DIRECTLY inside environment/initial_workspace/ (its
    immediate children only -- deliberately NOT recursive into a subdirectory such as
    _corpus_subtree/). See the module docstring's 2026-09-15 update: a large share of this
    corpus mirrors an entire simulated company Drive into a nested _corpus_subtree/, shared
    across many task variants, and crediting disclosure through an unrestricted recursive
    walk is provably unsafe there (SVC-PC-63-4-0 and SVC-PC-12-2-0, both confirmed real, sit
    on the exact same shared files as confirmed-false-positive sibling tasks). This is a
    disclosed scope limit, not a placeholder for a future recursive version."""
    ws = task_dir / "environment" / "initial_workspace"
    if not ws.is_dir():
        return ""
    parts: list[str] = []
    for p in sorted(ws.iterdir()):
        if not p.is_file():
            continue
        reader = _BINARY_TEXT_READERS.get(p.suffix.lower())
        if reader is not None:
            parts.append(reader(p))
        elif p.suffix.lower() in _PLAIN_TEXT_EXTS:
            parts.append(_read_plain_text(p))
    return " ".join(parts)


def environment_filename_stems(task_dir: Path) -> set[str]:
    """Lowercase, extension-stripped basenames of every file anywhere under
    environment/initial_workspace/ (recursive -- unlike read_environment_text() above, a
    match here requires a real file's own exact stem, a far lower-risk signal than a content
    search, so the non-recursive caution above does not apply to this one)."""
    ws = task_dir / "environment" / "initial_workspace"
    if not ws.is_dir():
        return set()
    return {p.stem.lower() for p in ws.rglob("*") if p.is_file()}


class _EnvCache:
    """Lazily extracts and memoizes one task's environment text and filename stems, so N
    criteria checking the same task pay the binary-extraction cost at most once each -- and a
    task where every candidate already clears via instruction.md pays it zero times."""

    def __init__(self, task_dir: Path) -> None:
        self._task_dir = task_dir
        self._text: tuple[str, str] | None = None
        self._stems: set[str] | None = None

    def text(self) -> tuple[str, str]:
        if self._text is None:
            raw = read_environment_text(self._task_dir).lower()
            self._text = (raw, re.sub(r"[_\-]+", " ", raw))
        return self._text

    def filename_stems(self) -> set[str]:
        if self._stems is None:
            self._stems = environment_filename_stems(self._task_dir)
        return self._stems


def _scan(
    res: dict,
    criterion_label: str,
    desc: str,
    instr_lower: str,
    instr_norm: str,
    ekw: bool = False,
    env: "_EnvCache | None" = None,
) -> None:
    desc = (desc or "").strip()
    if not desc:
        return
    res["criteria_scanned"] += 1
    for cand in extract_candidates(desc, ekw=ekw):
        if not is_disclosed(cand["term"], instr_lower, instr_norm, env=env):
            if (
                cand["cue"] in ("allcaps-prefix", "wildcard")
                and IDENTIFIER_SHAPE_RE.match(cand["term"])
                and SOURCE_NAMING_DIRECTIVE_RE.search(instr_lower)
            ):
                continue
            res["findings"].append(
                {
                    "criterion": criterion_label,
                    "term": cand["term"],
                    "cue": cand["cue"],
                    "snippet": _snippet(desc, cand["term"]),
                }
            )


def has_svc_pc_config(task_dir: Path) -> bool:
    return bool(
        list(task_dir.glob("tests/deliverables/judge.toml"))
        or list(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def has_ekw_config(task_dir: Path) -> bool:
    return (task_dir / "tests" / "verifier.json").is_file()


def check_task(task_dir: Path) -> dict:
    """SVC-PC: tomllib + tests/deliverables[_*]/judge.toml. Never raises on a malformed
    package."""
    res = {
        "task": task_dir.name,
        "format": "svc_pc",
        "criteria_scanned": 0,
        "findings": [],
        "parse_errors": [],
        "ok": False,
    }

    instr = _load_instruction(task_dir)
    if instr is None:
        res["parse_errors"].append("no instruction.md")
        return res
    instr_lower, instr_norm = instr
    env = _EnvCache(task_dir)

    judge_files = sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )
    if not judge_files:
        res["parse_errors"].append(
            "no judge.toml under tests/deliverables/ or tests/deliverables_*/"
        )
        return res

    for jf in judge_files:
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception as exc:
            res["parse_errors"].append(f"{jf.name}: {exc}")
            continue
        for c in data.get("criterion") or []:
            name = c.get("name", "?")
            label = f"{jf.parent.name}/{name}"
            _scan(
                res, label, c.get("description", ""), instr_lower, instr_norm, env=env
            )

    res["ok"] = not res["findings"] and not res["parse_errors"]
    return res


def check_task_ekw(task_dir: Path) -> dict:
    """EKW: tests/verifier.json. Description text per verifier is the rubric prompt for
    rubric-type assertions, or the how/why justification plus the deterministic JSONPath field
    name for deterministic-type assertions. Never raises on a malformed package."""
    res = {
        "task": task_dir.name,
        "format": "ekw",
        "criteria_scanned": 0,
        "findings": [],
        "parse_errors": [],
        "ok": False,
    }

    instr = _load_instruction(task_dir)
    if instr is None:
        res["parse_errors"].append("no instruction.md")
        return res
    instr_lower, instr_norm = instr
    env = _EnvCache(task_dir)

    vp = task_dir / "tests" / "verifier.json"
    try:
        data = json.loads(vp.read_text(encoding="utf-8"))
    except Exception as exc:
        res["parse_errors"].append(f"verifier.json: {exc}")
        return res

    for v in data.get("verifiers") or []:
        name = v.get("name", "?")
        a = v.get("assertion") or {}
        parts: list[str] = []
        if a.get("type") == "rubric":
            parts.append((a.get("rubric") or {}).get("prompt", "") or "")
        else:
            md = v.get("metadata") or {}
            parts.append(md.get("how_justification", "") or "")
            parts.append(md.get("why_justification", "") or "")
            det = a.get("deterministic") or {}
            path = det.get("path", "") or ""
            if path:
                parts.append(path.lstrip("$.").replace(".", " "))
        desc = " ".join(p for p in parts if p).strip()
        _scan(res, name, desc, instr_lower, instr_norm, ekw=True, env=env)

    res["ok"] = not res["findings"] and not res["parse_errors"]
    return res


def check_task_dispatch(task_dir: Path) -> dict:
    """SVC-PC takes precedence when a task directory (in principle) carries both configs."""
    if has_svc_pc_config(task_dir):
        return check_task(task_dir)
    if has_ekw_config(task_dir):
        return check_task_ekw(task_dir)
    return {
        "task": task_dir.name,
        "format": "unknown",
        "criteria_scanned": 0,
        "findings": [],
        "parse_errors": ["no judge.toml or verifier.json found"],
        "ok": False,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "root",
        help="a directory containing one subdirectory per task (SVC-PC or EKW layout), "
        "or a single task directory",
    )
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        help="limit to these task ids (repeatable)",
    )
    ap.add_argument("--json", help="also write the full result set here")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2

    if (root / "tests").is_dir():
        task_dirs = [root]
    else:
        task_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.task:
        want = set(args.task)
        task_dirs = [d for d in task_dirs if d.name in want]
    if not task_dirs:
        sys.stderr.write(f"no task directories matched under {root}\n")
        return 2

    results = [check_task_dispatch(d) for d in task_dirs]

    bad = [r for r in results if not r["ok"]]
    for r in results:
        flag = "OK  " if r["ok"] else "FLAG"
        print(
            f"{flag} {r['task']:<20} [{r['format']:<6}] "
            f"{r['criteria_scanned']:>4} criteria  {len(r['findings']):>3} findings"
        )
        for w in r["parse_errors"]:
            print(f"       parse: {w}")
        for f in r["findings"]:
            print(
                f"       undisclosed term '{f['term']}' ({f['cue']}) in {f['criterion']}"
            )
            print(f"           ...{f['snippet']}...")

    print(f"\n{len(results) - len(bad)}/{len(results)} clean")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
