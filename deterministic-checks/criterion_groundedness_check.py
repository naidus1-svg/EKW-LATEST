#!/usr/bin/env python3
"""Criterion groundedness check: does a criterion's `Expected:` value state a specific fact that
has no textual support anywhere in the task's own solver-visible corpus?

Why this exists: a criterion can name a dollar figure, a date, a person, or a specific filename
that reads as a raw SOURCE-DATA claim -- something the solver is supposed to find in the task's
own input files and carry forward, not compute. If that fact never actually appears anywhere in
environment/initial_workspace/ (SVC-PC) or environment/data/ (EKW), the solver cannot honestly
satisfy the criterion: they either guess, or the criterion was authored from information outside
what the task actually gives the solver. This is a different check from
`answer_key_content_leak_check.py` (already in this folder) -- that one asks whether an expected
VALUE leaks verbatim INTO the environment (the leak direction); this one asks the opposite
question, whether the value has any textual SUPPORT in the environment at all (the absence
direction). Read that script first if you haven't -- this one reuses its value-extraction
machinery (VALUE_TOKEN_RE, to_float, sig_len) rather than reinventing it.

What it checks, per criterion, per task:
    1. Extract every fact-shaped token from the criterion's `Expected:` clause (SVC-PC) or whole
       rubric prompt (EKW, which has no `Expected:` authoring convention -- confirmed against the
       real 274-task corpus by answer_key_content_leak_check.py's own EKW port, reused here
       unchanged): dollar figures, percentages, dates, comma/decimal numbers, quoted strings
       (identical token shapes to answer_key_content_leak_check.py's VALUE_TOKEN_RE), plus three
       new extractors this script adds: a filename token (`Cirrus_FY2021_..._final.docx`-shaped),
       a named entity following "named"/"called"/"labeled"/"titled", and a dash/underscore
       alphanumeric code (`Cite_L2_03`-shaped, EXCLUDING a task-ID-shaped token like
       `SVC-PC-6-1-0` -- that is structural provenance, not a criterion-authored fact).
    2. For each fact, search every file under the task's own environment directory (plain-text
       extraction: .txt/.md/.csv/.json read directly, .xlsx/.xlsm via openpyxl, .docx via
       python-docx or a zipfile+regex fallback, .pdf via pypdf -- reusing
       answer_key_content_leak_check.py's exact xlsx/docx approach, this script's own addition is
       only the .pdf branch, since no existing check in this folder reads PDF text) for a textual
        match: context-anchored proximity matching for numeric facts (currency, comma/decimal
        numbers, bare numbers, percentages -- the fact's value must appear near at least one
        of the same subject/unit words that surround it in the criterion text; see the
        context-anchored matching section below), literal case-insensitive substring for
        non-numeric kinds (filename, named_entity, quoted, date).
    3. No match anywhere -> `unreachable_criterion` (hard finding), UNLESS the fact reads as a
       computed/derived result rather than a raw source claim (see Classification below) or the
       fact's own kind is one this script keeps low-confidence-only by design (bare numbers,
       percentages, id/code tokens -- see Known limits). Ambiguous or low-confidence cases land in
       `possible_unreachable`, a separate, non-blocking bucket, never the hard exit-1 gate.

Classification -- computed result vs. raw source claim (the actual hard part of this check, and
the reason for the conservative design below): a criterion checking a solver's own correctly
DERIVED arithmetic (an AOV, a gross margin %, a bridge variance, a residual-to-zero) is not a
defect just because that exact number doesn't appear as a raw cell somewhere -- it is SUPPOSED to
be computed, not copied. `COMPUTE_INDICATOR_RE` matches a fixed list of computation-shaped words
("calculated", "derived", "AOV", "gross margin", "variance", "bridge", "ratio of", "delta
between", ...) in the criterion's full description; a numeric fact with a compute indicator
nearby is downgraded to `possible_unreachable` (or dropped) rather than hard-flagged, even if
literally absent from the environment. This is a disclosed heuristic, not a proof -- see Known
limits.

Hard-eligible fact kinds (can reach `unreachable_criterion`): filename, named_entity, quoted,
date, and the three "looks like a stated figure" numeric kinds (currency, comma_number,
decimal_number) when no compute indicator is present. Filenames and named entities are never
computed (a specific document name or a person's name is always either given or it isn't), so
they get no compute-indicator gate.

Possible-only fact kinds (can only ever reach `possible_unreachable`, never hard-gate, regardless
of compute indicators): bare_number (a standalone integer of 2+ digits like "30" or "9989" -- too
easily a coincidental match or a plain count with no reliable "stated as a source fact" signal;
single-digit numbers are excluded entirely, not even possible-only, since digits adjacent to
comparison operators like "≥1" or "≠ 0" swamped the signal at that length -- confirmed on a real
75-task sample, 2026-09-15: dropping to 1+ digits grew this bucket 13.7x over the 2+ baseline with
mostly operator-noise, not real counts). The "too easily a coincidental match" risk is not
theoretical: confirmed directly on SVC-PC-14-4-0/c17 (2026-09-15, after a `min_chars` fix made
2-3 digit extraction work at all -- see CHANGELOG entry) -- the criterion's "30-night window"
claim is unsupported (no such window exists in the corpus), but the bare token "30" coincidentally
word-matches an unrelated "swiftship ~30%" fulfillment figure elsewhere in the same environment,
so the original `classify_fact()`'s context-blind numeric-or-word-match check read it as "found"
and the real defect stayed invisible even in the possible bucket. Same for "14" and "100" in the
same criterion. This is now addressed by context-anchored proximity matching (implemented
2026-09-15 per design-proposals/criterion-groundedness-fix-2026-09-15.md, smoke-tested against
the 56-task mirror, full corpus-scale validation pending against real environment/solution
files): the fact's value must now appear near at least one anchor (the unit/subject word
adjacent to it in the criterion text, e.g. "night" for "30-night") in the environment, not just
anywhere in the blob.
percent (a percentage is disproportionately likely to be a computed rate/margin in this corpus's
own rubric language, per this script's own hand-validation below), and id_code (a dash/underscore
alphanumeric token -- deliberately ambiguous per the brief that created this script: it can be a
tab-naming convention the SOLVER must create, not a fact to find in the corpus, and this script
cannot reliably tell those apart).

Dual-format design (identical pattern to rubric_schema_check.py, which this script was built to
match exactly): `check_task()` (SVC-PC, tomllib + `tests/deliverables_*/judge.toml`),
`check_task_ekw()` (EKW, via `ekw_verifier_json.load_ekw_criteria()`), `check_task_dispatch()`
(SVC-PC detection takes precedence, mirroring every other dual-format check in this folder).

Validation: hand-reviewed against 4 real tasks (SVC-PC-88-0-0, SVC-PC-92-0-0, SVC-PC-92-1-0,
SVC-PC-80-7-0) a peer QC pass flagged as defective, BEFORE this script was run against them, per
this repo's own contribution convention (see this script's own commit message for the full
per-task write-up: which were independently confirmed by hand, which the extractor does and does
not catch, and the one task where a defect could not be confirmed). Corpus-wide false-positive
counts (SVC-PC 03_dataos_ready, all tasks; EKW C:\\ekwqc\\_merged274\\files, all 274 tasks, read
natively via has_ekw_config()) are likewise in that commit message rather than hardcoded here,
so they can't go stale silently in this file.

Exit 0 clean (zero unreachable_criterion findings across every task), 1 findings, 2 bad usage.

    python criterion_groundedness_check.py <package_root> [--task TASK-ID] [--json out.json]

Known limits, disclosed rather than silently dropped:
    - This is a low-confidence-tolerant tool by design, matching this folder's own precedent
      (answer_key_content_leak_check.py): `unreachable_criterion` is the gate, `possible_unreachable`
      is a non-blocking bucket for a human to skim, never counted toward the exit code.
    - The compute-indicator gate is a fixed keyword list, not semantic understanding, widened
      several times against real false-positive classes hand-confirmed during this script's own
      development: a "(TabName!C4)" cell reference or "results.a.b.c=" JSON-path pointing at the
      solver's OWN deliverable rather than a source (`DELIVERABLE_CELL_REF_RE`,
      `DOTTED_PATH_ASSIGNMENT_RE`, `RESULTS_JSON_ROOT_RE`); a bare "(cost model)"/"(stipend
      policy)"-shaped parenthetical pointing at a section of the solver's own deliverable rather
      than a cited source document (`SELF_SECTION_POINTER_RE`); Monte Carlo/percentile simulation
      language; and a criterion stating 4+ numeric facts at once, which reads as a computed
      table/series rather than individual source facts regardless of keywords
      (`SERIES_NUMERIC_THRESHOLD`). Even after all of this, a computed figure phrased without any
      recognized signal will still be hard-flagged as a false positive; a raw source fact phrased
      to sound computed ("the calculated headcount is exactly 47, per the roster") will be wrongly
      downgraded to possible-only. Disclosed, not assumed away -- this remains the single biggest
      source of residual false positives, concentrated in "the solver builds a full financial/
      cost model from scratch" task families (confirmed on SVC-PC-1-*, SVC-PC-10-*, SVC-PC-11-*
      during development; likely not an exhaustive list across ~600 tasks).
    - `SERIES_NUMERIC_THRESHOLD` can itself be defeated by `--min-chars`-style filtering
      (`sig_len(token) < min_chars`, hardcoded floor 4): a clause summing several SUB-$1000 line
      items ("$1,740/yr: Mailchimp $240, Sendgrid $240, Linear $288, Canva $360, Iconfinder $228,
      Hotjar $384..") has each 3-significant-digit line item dropped before extraction, so only
      the total survives as this criterion's ONE fact -- it never reaches the series threshold and
      gets hard-flagged as if it were a lone stated figure, even though it demonstrably is a sum
      (confirmed on SVC-PC-75-4-0/r6: every named vendor is a real row in that task's own
      Software_Licenses_Inventory.xlsx, so the total is a computed rollup of real, present line
      items, not an unsupported claim). Confirmed real, not fixed in this version -- the fix
      (count pre-filter tokens for series detection, not post-filter facts) is understood but
      deferred rather than triggering another full-corpus rerun this session.
    - Named-entity extraction only fires on the literal keywords named/called/labeled/titled. A
      criterion that states a person's name or a system name without one of those trigger words
      (most of them, in this corpus) extracts nothing -- this script does not attempt a generic
      capitalized-phrase heuristic, because on this corpus that heuristic catches ordinary
      boilerplate Expected values ("Board-ready narrative", "Cast correct") as false positives.
      This is a real, disclosed coverage gap, not a hidden one.
    - id_code extraction is deliberately narrow and never hard-gates (see Classification above).
    - .xls (legacy binary Excel) and .pptx are not scanned -- not asserted clean, just not covered.
    - PDF text extraction (pypdf) does not OCR scanned/image-only PDFs; a fact stated only in a
      scanned page reads as absent even when a human could read it.
    - Numeric matching tolerates formatting (currency sign, thousands separators, sign) but not
      unit/scale differences ("$1.2M" vs. "1200000") or rounding beyond the 0.005 tolerance.
    - Context-anchored matching (the 2026-09-15 fix for the "30-night window" false negative
      above) requires at least one content word near the fact in the criterion text to serve as
      an anchor. A numeric fact with no adjacent unit/subject word (e.g. "Expected: 30" with no
      surrounding context) falls to the no-anchors fallback: HARD_NUMERIC_KINDS fall back to
      context-blind matching (status quo, no regression on hard-gating facts), bare_number/
      percent/id_code return possible_unreachable (safe, these kinds never hard-gate). The
      proximity window (PROXIMITY_WINDOW=100 chars) and anchor extraction window
      (ANCHOR_TEXT_WINDOW=200 chars) are initial parameters from the design proposal, not
      empirically calibrated against the full corpus -- the implementing machine should tune
      these against real data.
    - Primary-anchor weighting (round 6, 2026-09-15): the context-anchored match now requires
      the PRIMARY anchor (the fact's immediate unit/label, e.g. "night" for "30-night")
      specifically, not `any` of the primary + ~20 secondary anchors. Secondary anchors are
      only used when no primary was extractable at all. This fixes a false-grounding class
      confirmed on SVC-PC-14-4-0/c17: a bare_number's value ("30") coincidentally appears near
      a generic secondary anchor ("return"/"policy"/"day") in the environment, grounding the
      fact as clean even though the specific context ("30-night") is absent. Known limitation
      of this approach: when the primary anchor itself is poorly extracted (it points to a
      word from a later clause, not the fact's real unit -- e.g. "omitted" for a "$(84,344)"
      whose real unit is "unallocated"), the fix may false-positive on a HARD_NUMERIC_KIND.
      This is a primary-anchor EXTRACTION quality issue (the extraction takes the first content
      word after the number, which can be from a different clause), not a weighting issue;
      improving the extraction (prefer the immediately-adjacent word, detect clause boundaries)
      is deferred to a future round. For bare_number/percent/id_code this lands in the
      non-blocking possible_unreachable bucket (acceptable); for HARD_NUMERIC_KINDS it can
      hard-gate. Confirmed 0 regressions on the 56-task mirror (no environment dirs, so the
      match functions return False regardless of anchor count); with real environments the
      risk is real and disclosed. Second known limitation (found by round 6's adversarial
      review, 2026-09-15): when no primary anchor is extractable AT ALL (40+ chars of
      stopwords on both sides of the fact) but secondary anchors exist, the fallback
      `anchors = secondary` matches on ANY single secondary anchor -- the exact pre-fix
      permissive behavior this change was meant to eliminate, just scoped to the rarer
      no-primary case instead of the common with-primary case. Also pre-existing (not
      introduced by this change): `_context_anchored_text_match`/`_context_anchored_numeric_
      match` use a raw substring check (`a in context`), not word-boundary matching, so a
      short primary anchor like "day" can match inside an unrelated word like "daybook";
      this is more impactful now that a single primary anchor is the only check instead of
      one of ~22. Both are disclosed, not fixed, in this round.
    - Text matching (`_word_match`) requires alnum boundaries on both sides of a fact, not just a
      raw Python substring test -- added after a real bug surfaced during EKW development: a
      possessive apostrophe ("East's higher volume") was misread as an opening quote mark by the
      quoted-token pattern inherited from answer_key_content_leak_check.py, which only had to
      handle SVC-PC's terser "Expected:" clauses, not EKW's free-running rubric prose. Fixed with
      a negative lookbehind on the quoted pattern's opening quote (`VALUE_TOKEN_RE`) plus
      boundary-aware matching everywhere a fact is checked against the environment text.
    - `_instruction_context_reads_as_computed` (c17, round 3, tracker row 14) only reads THIS
      task's own instruction.md text, never a file instruction.md merely names by reference (e.g.
      "your wholesale pricing proposal"). Confirmed asymmetric on real data: SVC-PC-35-6-0 states
      its tier-percentage formula inline in instruction.md and every one of its 41 tier/program/
      contribution-anchored findings resolves; sibling task SVC-PC-35-0-0 states the same
      contribution formula but defers the specific tier percentages to an external, unquoted
      "wholesale pricing proposal" file, and its resolved count (8 of 49) comes entirely from the
      contribution/fulfillment/mdf anchors that DO sit near the formula sentence, not tier. This
      is a disclosed scope boundary, not a bug -- reaching into a referenced-but-not-directly-
      scanned file would require a materially different (and separately risk-assessed) mechanism
      than the anchor-to-compute-indicator proximity check this function does, and was
      deliberately not attempted in the same round that shipped the narrower, verified fix.
    - `_instruction_context_reads_as_computed`'s remaining, DISCLOSED (not fixed) residual risk
      after the negation guard: a common or multi-sense English word used as a criterion's own
      anchor can coincidentally sit near an unrelated compute-indicator phrase elsewhere in the
      SAME instruction.md, for a completely different subject. Confirmed real on SVC-PC-48-1-0
      ("net" anchors a "net adds" [net of churn] criterion, but the nearest "% of" in
      instruction.md is about "net revenue" [net of returns] -- same word, two distinct business
      senses, purely coincidental adjacency) and on SVC-PC-48-2-0/50-0-0/50-5-0 (an anchor like
      "welcome"/"adds" sits near an unrelated metric purely because both are separate line items
      in the same numbered list of customer-lifecycle segments or scorecard metrics). Measured
      directly (_scratch_distance_analysis.py, round 3): anchor-to-keyword character distance
      does NOT separate these from the genuine matches -- SVC-PC-51-2-0's correct "net" match and
      SVC-PC-48-1-0's false "net" match are both distance 1 from their keyword, so no window-size
      tuning fixes this class, only a semantic understanding of which sense of the word applies
      would, which this heuristic-keyword approach does not have. None of the affected tasks are
      among the 21 hand-confirmed genuine defects, so this was not provable as a regression the
      way SVC-PC-17-2-0's negation case was -- disclosed as an open, accepted-risk residual, on
      the same "downgrade, don't exclude, on real evidence" basis as every other heuristic gap in
      this file, not silently assumed safe.
"""

from __future__ import annotations

import argparse
import email
import hashlib
import html as _html
import json
import quopri
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
    sys.stderr.write("needs openpyxl: pip install openpyxl\n")
    raise SystemExit(2)

try:
    import docx as _python_docx  # python-docx, optional -- falls back to zipfile+regex

    HAVE_PYTHON_DOCX = True
except ImportError:  # pragma: no cover
    HAVE_PYTHON_DOCX = False

try:
    import pypdf  # optional -- PDF facts/environment text are skipped (disclosed) if absent

    HAVE_PYPDF = True
except ImportError:  # pragma: no cover
    HAVE_PYPDF = False


# ---------------------------------------------------------------------------
# value-token extraction -- identical shapes to answer_key_content_leak_check.py, reused rather
# than reinvented (see this script's module docstring)
# ---------------------------------------------------------------------------

EXPECTED_CLAUSE_RE = re.compile(
    r"Expected\s*:\s*(.*?)(?:\.\.|\Z)", re.IGNORECASE | re.DOTALL
)
YEAR_RE = re.compile(r"^(19|20)\d{2}$")

VALUE_TOKEN_RE = re.compile(
    r"""
    (?P<currency>\$\(\d{1,3}(?:,\d{3})*(?:\.\d+)?\)|\$\d{1,3}(?:,\d{3})*(?:\.\d+)?)
  | (?P<percent>[-\u2212]?\d+(?:\.\d+)?%)
  | (?P<date_slash>(?<!\d/)\b\d{1,2}/\d{1,2}/\d{4}\b(?!\d|/\d))
  | (?P<date_iso>\b\d{4}-\d{2}-\d{2}\b)
  | (?P<date_dmon>\b\d{1,2}-[A-Za-z]{3,9}-\d{4}\b)
  | (?P<date_mdy>\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b)
  | (?P<quoted>(?<![A-Za-z0-9])'[^']{4,80}'|"[^"]{4,80}")
  | (?P<comma_number>\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b)
  | (?P<decimal_number>\b\d+\.\d+\b)
  | (?P<bare_number>\b\d{2,}\b)
""",
    re.VERBOSE | re.IGNORECASE,
)

# c8 / scale-suffix fix (2026-09-15 triage round): VALUE_TOKEN_RE's currency/comma_number/
# decimal_number groups stop at the last digit, so "$1.205M" or "$23.0mm" or "$1,205K"
# extracts as token "$1.205"/"$23.0"/"$1,205" -- silently dropping the scale, which changes
# the fact's numeric value by 1000x-1,000,000x and guarantees it can never match the real,
# correctly-scaled environment figure. Confirmed real on SVC-PC-72-1-0/r05 ("$1.205M"
# extracted with numeric 1.205 instead of 1,205,000.0) and SVC-PC-3-1-0/r044 (same bug on
# "$1.445M"). Applied as a post-match extension in extract_facts() (below), not a rewrite of
# VALUE_TOKEN_RE's own base patterns, to avoid touching those already-tuned groups.
# Deliberately excludes bare_number: a bare 2+ digit integer immediately followed by a
# lowercase "k"/"m"/"b" is also the shape of an alphanumeric code fragment ("50K-2"), and
# unlike currency/comma_number/decimal_number it carries no other signal (a "$", a thousands
# comma, a decimal point) that this is a monetary/quantity figure in the first place.
_SCALE_SUFFIX_RE = re.compile(r"(mm|bn|[mkb])(?![A-Za-z])")
_SCALE_MULTIPLIER = {
    "m": 1_000_000.0,
    "mm": 1_000_000.0,
    "k": 1_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
}

NUMERIC_KINDS = {"currency", "comma_number", "decimal_number", "bare_number"}
DATE_KINDS = {"date_slash", "date_iso", "date_dmon", "date_mdy"}
HARD_NUMERIC_KINDS = {"currency", "comma_number", "decimal_number"}
NUMERIC_TOLERANCE = 0.005
PROXIMITY_WINDOW = 100  # characters, for text-anchored and text-numeric context windows
ANCHOR_TEXT_WINDOW = 200  # characters, for anchor extraction from criterion text

# Harness-authored boilerplate sentences, not part of the criterion's own subject matter.
# Real bug found by turing-context-e5 verifying b9fb249: extract_anchors()'s primary-anchor
# scan unconditionally prefers the first content word AFTER the fact token, and "This is a
# must-pass criterion." sits immediately after a numeric fact in 1,576/corpus judge.toml
# files (confirmed: "...closing cash.. This is a must-pass criterion. Response..."). "pass"
# and "criterion" are real, non-stopword words, so they won the primary-anchor slot over
# the fact's actual anchor ("cash"), which sits BEFORE the number and was never reached
# because the before-text fallback only runs when the after-text scan finds NOTHING.
# Same fragment set `compound_criterion_check.py`'s BOILERPLATE_FRAGMENT_RE already
# established as the corpus's standard harness sentences -- reused here, not reinvented.
# Applied to the TEXT SLICES used for word-scanning (after/before/window), never to `desc`
# itself, so the fact's own recorded match_start/match_end offsets stay valid.
_ANCHOR_BOILERPLATE_RE = re.compile(
    r"this is a must-pass criterion\.?"
    r"|this criterion is (?:optional|not must-pass)\.?"
    r"|any values?\s*(?:!=|≠|other than|not equal to)[^.]*fails?\.?"
    r"|absent\s*(?:fails|=\s*0\s*pts)\.?\.?"
    # Found by ef diagnosing the 7-task regression from the first version of this scoring
    # redesign (2026-09-15): "Response criteria guidance:" boilerplate was winning "response"
    # as primary anchor on SVC-PC-19-6-0/c13,c14 because this fragment wasn't stripped at all.
    r"|response criteria guidance:?",
    re.I,
)

# Generic value-descriptor words: frequently the word closest to a numeric fact or to the
# "Expected:" boundary, but describing the VALUE's role/type rather than the sentence's real
# semantic subject. Found alongside the boilerplate bug by e5's corpus-scale verification,
# hand-confirmed on real text: "value"/"statement" (SVC-PC-80-7-0/a10,d8 -- real anchor is
# "cash", stated earlier in the sentence), "closed" grabbed from a trailing "(closed books)"
# qualifier instead of "revenue" (SVC-PC-53-3-0/r001), "invested" beating the real anchor
# "Drift" two words further back (SVC-PC-2-6-0/d3). Downweighted in extract_anchors()'s
# scoring, not excluded outright -- still usable if nothing better exists in the window.
_ANCHOR_GENERIC_DESCRIPTORS = {
    "value",
    "values",
    "figure",
    "figures",
    "amount",
    "amounts",
    "statement",
    "statements",
    "account",
    "accounts",
    "balance",
    "balances",
    "total",
    "totals",
    "sum",
    "sums",
    "estimate",
    "estimates",
    "result",
    "results",
    "closed",
    "invested",
    "reported",
    "recorded",
    "stated",
    "shown",
    "listed",
    "noted",
    # Degree/manner adverbs qualifying HOW a value is stated, not naming what it is: "is
    # correctly stated" / "matches exactly" / "computed accurately". Real, pre-existing gap
    # (seen on SVC-PC-14-4-0/c02 as "exactly" hours before tonight's anchor-scoring work even
    # started), surfaced again on SVC-PC-19-2-0/c13 ("correctly") once the -ed-ending neighbor
    # ("stated") stopped absorbing it as a false anchor.
    "correctly",
    "exactly",
    "accurately",
    "precisely",
    "approximately",
    "roughly",
    # 2026-09-15 triage round: "correct" (bare adjective form, e.g. "...the correct
    # $214,831 Total OpEx figure...") is the same value-property descriptor as
    # "correctly" just above, only missing the -ly. Confirmed on SVC-PC-3-1-0/r040,r041:
    # "correct" won primary anchor over the real subject nouns further away.
    "correct",
    # Bridge/range-value labels: "Expected: Start $56.72/order; ... end $X" formats the
    # expected VALUE as a labeled bridge, not a description of the fact's subject. Found by
    # ef diagnosing SVC-PC-58-9-0/c06: "start" sits immediately adjacent to the fact and beat
    # the real anchor "contribution" purely on proximity, capitalized or not.
    "start",
    "end",
    # --- round 14 additions (2026-09-15): value-property descriptors (EKW analytical prose) ---
    # EKW rubrics state computed properties of values ("midpoint", "minimum", "maximum",
    # "threshold", "average", "median") that describe the VALUE's role, not the sentence's
    # semantic subject. Found on the real 14-task EKW mirror: "midpoint" won 3 currency
    # facts as primary anchor in task_175/v5 (e.g. "$21.00-$24.00 with a $22.50 midpoint"
    # -- "midpoint" is about $22.50, not $21.00, but it won on proximity). Downweighted
    # rather than excluded: a genuine subject noun further away can still win on distance.
    "midpoint",
    "minimum",
    "maximum",
    "threshold",
    "average",
    "mean",
    "median",
    "ceiling",
    "floor",
    # --- round 21 additions (2026-09-15): sentence-initial adjectives, wrong-clause phrases ---
    # Found via real false-positive sweep on the 27-task SVC-PC sample. "Cumulative" and
    # "Operational" (SVC-PC-2-4-0/b3, e2) are common adjectives, not proper nouns, that won
    # the title-case bonus purely because they happen to start a sentence ("Cumulative
    # customers reached 6,000" / "Operational impact quantified: 4,000 units...") -- the
    # existing verb-shape exclusion on the title-case bonus doesn't catch adjectives. "books"
    # and "basis" (SVC-PC-31-0-0/r005, r027) come from an unrelated "against closed books"/
    # "books basis" accounting-method qualifier that sits closer to the fact than the real
    # anchor (revenue/gap/plan), the same trailing-qualifier shape "closed" already covers.
    "cumulative",
    "operational",
    "books",
    "basis",
    # c4 (2026-09-15): "live" in "against live $X" is an adjective meaning "actual"
    # (as opposed to example/gate values), describing the data source, not the
    # subject. Confirmed on SVC-PC-7-6-0/c13: "live" at distance 0 beat the real
    # anchor "cac" (from "LTV:CAC", distance 5) purely on proximity, preventing
    # $34.17 from grounding via "CAC" in the environment.
    "live",
    # c4 (2026-09-15): "payback" in "payback <= 6 mo" is a gate-value metric label
    # for a DIFFERENT fact (the 6 mo payback threshold), not the subject of $34.17
    # (which is CAC). Confirmed on SVC-PC-7-6-0/c13: "payback" at distance 3 beat
    # "cac" at distance 4 purely on proximity.
    "payback",
    # c4 (2026-09-15): "system" in "authoritative system named as QuickBooks
    # GL" is a generic type-descriptor, not the sentence's real subject (which is
    # "revenue"). Confirmed on SVC-PC-80-7-0/a2: "system" at distance 6 beat
    # "revenue" at distance 8 after the internally-capitalized penalty pushed
    # "quickbooks" out.
    "system",
    # c4 (2026-09-15): "authoritative" in "authoritative system named as" is an
    # adjective describing the system's authority level, not the sentence subject.
    # Confirmed on SVC-PC-80-7-0/a2: "authoritative" at distance 7 beat "revenue"
    # at distance 8 after "system" was penalized. No finding in the 27-full corpus
    # uses "authoritative" as its anchor, so this is zero-regression.
    "authoritative",
}

# Month names: a real, closed, zero-risk set. A month can sit right next to an unrelated fact
# (a different figure's own date, e.g. "$200,000 ... monthly peak $342,340 in September") and,
# being a genuine proper noun, would otherwise win the title-case bonus over the real subject
# despite naming nothing about THIS fact. Found by ef diagnosing SVC-PC-68-6-0/r008: "inventory"/
# "build" should win, not "september".
_ANCHOR_MONTH_NAMES = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    # Round 14 (2026-09-15): added 3-letter month abbreviations. EKW date format "31-Mar-2026"
    # produces "Mar" as a standalone [A-Za-z]{2,} token that is strict title-case (M upper, "ar"
    # lower) and wins the +20 bonus over the real anchor. Confirmed on the real 14-task EKW
    # mirror: "mar" won 22 facts as primary anchor, e.g. $238.2 million's real anchor "principal"
    # lost to "Mar" because "31-Mar-2026 principal of about $238.2 million" puts "Mar" closer.
    # Abbreviations are excluded from the title-case bonus, not from the candidate set, matching
    # the existing design intent (downweight, don't exclude, for the rare no-better-candidate case).
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
}

# Stopwords excluded from anchor extraction. A fact's anchors are the content words near
# its position in the criterion text; stopwords carry no subject/unit signal. "expected"
# is included because the "Expected:" label itself is not an anchor.
_ANCHOR_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "has",
    "have",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "shall",
    "should",
    "may",
    "might",
    "must",
    "can",
    "could",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "with",
    "by",
    "from",
    "as",
    "into",
    "about",
    "than",
    "then",
    "so",
    "if",
    "but",
    "or",
    "and",
    "not",
    "no",
    "all",
    "any",
    "each",
    "every",
    "same",
    "this",
    "that",
    "these",
    "those",
    "per",
    "via",
    "up",
    "down",
    "out",
    "over",
    "under",
    "here",
    "there",
    "when",
    "where",
    "why",
    "how",
    "what",
    "which",
    "who",
    "whom",
    "expected",
    "must",
    "should",
    # Round 14 (2026-09-15): expanded from the original SVC-PC-calibrated set with comprehensive
    # English function words (pronouns, prepositions, conjunctions, discourse adverbs, verdict
    # keywords, ordinal suffixes, magnitude suffixes). The original set was calibrated on SVC-PC's
    # terse "Expected: <fact>" clauses, which rarely use these words. EKW's long analytical rubric
    # prose uses them constantly, and they were winning primary-anchor slots over real subject
    # nouns on pure proximity. Confirmed on the real 14-task EKW mirror: "fail" won 58 facts,
    # "pass" won 55, "it" won 6 (all via proximity or title-case bonus), none of which are real
    # anchors in either format. Every word added here is a function word that is never a real
    # semantic anchor in either format's criterion prose, so the expansion is safe for SVC-PC
    # (zero regression risk) and necessary for EKW.
    # --- round 14 additions: pronouns (never real anchors) ---
    "it",
    "its",
    "they",
    "them",
    "their",
    "we",
    "us",
    "our",
    "you",
    "your",
    "he",
    "him",
    "his",
    "she",
    "her",
    "one",
    "both",
    "either",
    "neither",
    "another",
    "such",
    "other",
    "others",
    # --- round 14 additions: prepositions (never real anchors) ---
    "within",
    "between",
    "among",
    "across",
    "behind",
    "beyond",
    "above",
    "below",
    "through",
    "throughout",
    "during",
    "before",
    "after",
    "against",
    "without",
    "along",
    "upon",
    "off",
    "near",
    "since",
    "until",
    "onto",
    "despite",
    "except",
    "inside",
    "outside",
    "toward",
    "towards",
    "around",
    "alongside",
    "beside",
    "besides",
    "opposite",
    "underneath",
    "amid",
    "amidst",
    "amongst",
    # --- round 14 additions: conjunctions / discourse markers ---
    "also",
    "nor",
    "yet",
    "because",
    "while",
    "whereas",
    "although",
    "though",
    "unless",
    "whether",
    "however",
    "therefore",
    "thus",
    "hence",
    "moreover",
    "furthermore",
    "meanwhile",
    "instead",
    "otherwise",
    "rather",
    "indeed",
    "consequently",
    "accordingly",
    "subsequently",
    "previously",
    "currently",
    # --- round 14 additions: degree/focus adverbs (like existing "correctly"/"exactly") ---
    "only",
    "just",
    "simply",
    "merely",
    "virtually",
    "essentially",
    "basically",
    "ultimately",
    "particularly",
    "specifically",
    "especially",
    "generally",
    "typically",
    "usually",
    "normally",
    "clearly",
    "obviously",
    "actually",
    "respectively",
    # --- round 14 additions: verdict keywords (EKW "PASS if.../FAIL if..." structure) ---
    # "fail" won 58 facts and "pass" won 55 on the real 14-task EKW mirror as primary
    # anchors, because EKW rubrics state grading verdicts as "PASS if <condition>; FAIL
    # if <condition>" with the verdict keyword sitting immediately after the fact. These
    # are structural markers, not semantic anchors, in either format ("expected" is
    # already in stopwords for the same reason).
    "pass",
    "fail",
    "passes",
    "fails",
    "passing",
    "failing",
    "passed",
    "failed",
    # --- round 14 additions: ordinal suffixes (from "1st"/"2nd"/"3rd"/"5th" date refs) ---
    # EKW date format "31-Mar-2026" and ordinal references produce 2-letter fragments
    # ("st" from "1st") that the [A-Za-z]{2,} word scanner captures as standalone tokens.
    # "st" won 66 facts as primary anchor on the real 14-task EKW mirror, all from SKU
    # codes like "ST-205" where "ST" is a product prefix, not a semantic anchor.
    "st",
    "nd",
    "rd",
    "th",
    # --- round 14 additions: financial magnitude suffixes ---
    # "mm" (million, from "$23.0mm") and "bn" (billion, from "$1.2bn") are currency-
    # magnitude suffixes that sit immediately after a dollar fact and win primary anchor
    # on distance 0. The environment may spell out "million"/"billion" instead, so
    # the anchor "mm" never matches. Reported in the full 274-task EKW run's spot-check.
    "mm",
    "bn",
    # --- round 21 additions (2026-09-15): modal verbs and comparison words ---
    # Found via real false-positive sweep on the 27-task SVC-PC sample after tonight's
    # anchor-scoring fixes: "cannot" (a modal verb, SVC-PC-31-0-0/r101) and "vs" (a
    # comparison word, SVC-PC-42-1-0/c23) both won primary-anchor slots on proximity
    # despite naming nothing about the fact's subject. Neither is a real semantic
    # anchor in any criterion prose.
    "cannot",
    "vs",
    "versus",
    "can",
    "could",
    "would",
    "shall",
    # --- round 21 additions: generic transition/process verbs ---
    # "run" (SVC-PC-7-4-0/o14) won a primary-anchor slot from a phrase like "run rate"
    # or "run through Q4" -- describes a process, not the fact's subject. Same shape as
    # the existing generic-descriptor list (closed/invested/reported/...) but verb-only,
    # not caught by the -ed/-ing structural penalty since "run" has neither ending.
    "run",
    "runs",
    "running",
    # --- round 21 additions: 2-letter abbreviation fragment ---
    # "po" (SVC-PC-9-3-0/r08) won primary anchor from a "PO"/"purchase order" abbreviation
    # sitting closer to the fact than the real anchor ("NovaTex", the vendor name). Same
    # shape as the existing "st"/"nd"/"rd"/"th" ordinal-fragment exclusions -- a short
    # abbreviation fragment, not a semantic subject on its own.
    "po",
}


def sig_len(token: str) -> int:
    return len(re.sub(r"[^A-Za-z0-9]", "", token))


def to_float(token: str):
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


def _word_match(blob: str, token: str) -> bool:
    """Substring match with alnum boundaries on both sides, so a short fact (a 4-letter name, a
    bare id_code) can't silently "match" as a fragment inside an unrelated longer word or number
    -- e.g. a fact 'Cash' must not read as found because the blob happens to contain 'Cashflow'.
    Boundaries are alnum-adjacency, not `\\b`, since several fact kinds (currency, quoted) carry
    punctuation `\\b` does not treat the way this needs (`$3,614.79` has no word boundary at its
    own '$'). `blob` is already lowercased by environment_signals(); callers must lowercase
    `token` themselves before calling this."""
    if not token:
        return False
    pattern = r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])"
    return re.search(pattern, blob) is not None


def _date_match(blob: str, token: str) -> bool:
    """Date-aware word match for DATE_KINDS facts. c6(a) fix: normalizes
    punctuation (commas) and whitespace on both sides before comparing, so
    'Dec 31 2021' matches the corpus's 'Dec 31, 2021' and vice versa. The
    underlying _word_match does a literal alnum-bounded substring match that
    treats a comma in either side as a hard mismatch; this wrapper strips
    commas and collapses whitespace from the token, then builds a flexible
    pattern allowing optional commas and any whitespace between the date's
    parts. `blob` is already lowercased by environment_signals(); callers must
    lowercase `token` themselves before calling this."""
    if not token:
        return False
    if _word_match(blob, token):
        return True
    norm = re.sub(r"\s+", " ", token.replace(",", "")).strip()
    if not norm:
        return False
    if norm != token and _word_match(blob, norm):
        return True
    parts = [re.escape(p) for p in norm.split(" ") if p]
    if not parts:
        return False
    pattern = r"(?<![A-Za-z0-9])" + r"\s*,?\s*".join(parts) + r"(?![A-Za-z0-9])"
    return re.search(pattern, blob) is not None


# ---------------------------------------------------------------------------
# new extractors this script adds: filenames, named entities, id/code tokens
# ---------------------------------------------------------------------------

# No literal space in the character class, deliberately: every real on-disk filename this
# corpus's Expected: text cites by exact name uses underscores as its word separator (confirmed
# across every filename fact this script's own validation checked, e.g.
# "Payroll_Reconciliation_Workbook.xlsx", "Q4_Board_Minutes.docx"). Allowing a space here was a
# real bug found running the finished script at corpus scale: a description reading "...the
# 10,000 FY2021 orders cited in Year_2_Planning_Notes.docx..." greedily absorbed the entire
# clause before the real filename ("000 FY2021 orders cited in Year_2_Planning_Notes.docx") into
# one garbage token, because `[\w\-. ]` treats a run of ordinary prose words joined by spaces as
# part of the filename stem. A human-readable, space-separated citation with no extension
# ("Q4 Board Minutes") was never a FILENAME_RE match anyway (no ".ext" to anchor on), so this
# loses no real coverage -- it only removes a proven false-positive class.
FILENAME_RE = re.compile(
    r"\b[\w][\w.-]{1,80}\.(?:docx|xlsx|xlsm|pdf|csv|txt|md|pptx|doc)\b", re.IGNORECASE
)

# 2026-09-15 triage round: a generic quality-adjective (or the number-word "one") mashed
# directly against an extension with no separating space -- "a working.xlsx workbook",
# "Expected: One.xlsx present", "Expected: a valid .xlsx" written without the space --
# is judge.toml prose using ".xlsx" as informal shorthand for "a spreadsheet file", not a
# real filename citation. Confirmed on 3 real tasks (SVC-PC-1-2-0/str-01 "readable.xlsx",
# SVC-PC-1-5-0/c001 "working.xlsx" AND "One.xlsx" in the same criterion, SVC-PC-3-9-0/e1
# "Valid.xlsx"). Deliberately a small closed list of quality descriptors, not a structural
# rule like "no underscore" -- this corpus has real, confirmed single-word filenames with no
# underscore at all (e.g. "Journal.csv", SVC-PC-6-1-0/SVC-PC-6-2-0), so stem shape alone
# can't distinguish the two classes; the specific word can.
_FILENAME_GENERIC_ADJECTIVE_STEMS = {
    "working",
    "readable",
    "valid",
    "one",
    "complete",
    "correct",
    "clean",
    "blank",
    "empty",
    "functional",
    "editable",
    "viewable",
    "usable",
    "openable",
}

# Sentence-boundary fix (2026-09-15 triage round): the per-word character class used to
# include "." (`[\w.&']*`), so a word ending a sentence ("...named CEO. Expected: ...",
# "...named Inputs.. This is a must-pass criterion.") absorbed the period as part of ITSELF,
# and the pattern then happily extended into the NEXT sentence's leading capitalized word
# ("Expected", "This") via the `\s+[A-Z][\w.&']*` continuation, producing a garbled
# pseudo-entity ("CEO. Expected", "Inputs.. This") that can never have a real textual match.
# Confirmed on 3 real corpus tasks (SVC-PC-21-2-0/r014, SVC-PC-26-2-0/rb-03,
# SVC-PC-91-6-0/r1). Dropping "." from the char class (both occurrences) stops the match
# cleanly at the sentence-ending word instead: the following "." is not whitespace or "/",
# so the `{0,4}` continuation simply fails to extend there.
NAMED_ENTITY_RE = re.compile(
    r"\b(?:named|called|labell?ed|titled)\b(?:\s+as)?\s*(?:Expected\s*:\s*)?"
    r"([A-Z][\w&']*(?:\s*/\s*[A-Z][\w&']*|\s+[A-Z][\w&']*){0,4})"
)

_NAMED_ENTITY_STOPWORDS = {
    "present",
    "yes",
    "no",
    "n/a",
    "na",
    "none",
    "correct",
    "complete",
    "compliant",
    "pass",
    "fail",
    "clean",
    "true",
    "false",
    # c7: all-caps flag-label conventions the solver APPLIES, not proper-noun
    # facts to find in the source. "NOT SOURCED" (SVC-PC-2-7-0/f5: "explicitly
    # labeled NOT SOURCED") is a disclosure label; "hold" (SVC-PC-93-0-0/r25:
    # "labeled HOLD") and "tbd" are placeholder/status labels. Multi-word
    # all-caps labels are also caught generically by _is_all_caps_label below;
    # single all-caps words (which may be real acronym entities like "GL"/"SVB")
    # are handled by these explicit entries only, to avoid false-negaturing a
    # real single-word acronym entity.
    "not sourced",
    "hold",
    "tbd",
    # 2026-09-15 triage round: "the named Inputs" is this corpus's own structural
    # self-reference to the criterion's/task's own citation list ("Cites A, B, C; no file
    # outside the named Inputs"), not a proper-noun fact to find in the source -- confirmed
    # on SVC-PC-91-6-0/r1 and SVC-PC-26-2-0/rb-03 (both, after the sentence-boundary fix
    # above stops the extractor at "Inputs" instead of the garbled "Inputs.. This"/
    # "Inputs. No", still leave a bare "Inputs" that has no reason to hard-gate).
    "inputs",
    "input",
}

# Alphanumeric code with an internal dash/underscore and at least one digit somewhere in the
# token -- e.g. "Cite_L2_03", "OI-01". Excludes a task-ID-shaped token (SVC-PC-6-1-0, FIN-177)
# per this script's brief: those are structural provenance, never a criterion-authored fact.
ID_CODE_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+){1,5}\b")
TASK_ID_SHAPE_RE = re.compile(r"^[A-Za-z]+(?:-[A-Za-z0-9]+){2,5}$")

# c3: exclusion-context detection. A criterion stating a value as something to
# EXCLUDE ("not $X", "NOT $X", "Bans 'X'", "e.g., 'X' is scored 0", "'X' is scored
# 0") should not have that value extracted as a positive fact to find. The
# preceding-text window must END with the exclusion word (only whitespace between
# it and the token), so "not less than $X" (a real threshold) is NOT matched:
# "less than" sits between "not" and "$X", so the window ends with "than ", not
# "not ". Confirmed safe by the adversarial review's stress-test of this exact
# pattern. Following-text window catches "'X' is scored 0" / "'X' scored 0"
# where the exclusion signal is AFTER the token, not before it.
_EXCLUSION_PRECEDING_RE = re.compile(
    r"\b(?:not|bans)\s+$" r"|\be\.?g\.?,?\s+$",
    re.IGNORECASE,
)
_EXCLUSION_FOLLOWING_RE = re.compile(
    r"^\s*(?:is\s+)?scored\s+0\b",
    re.IGNORECASE,
)

# c7: prescriptive-context detection for quoted strings. A criterion quoting a
# phrase the solver should WRITE ("honest 'X' why-now", "segregated 'X'",
# "labeled 'X'", "called 'X'", "no criterion relies on 'X', 'Y', 'Z' alone") is
# output-direction, not a fact to find in the source. The prescriptive verb may
# sit in the requirement sentence while the same quoted string is re-extracted
# from the Expected: clause (confirmed on SVC-PC-11-4-0: "honest 'ran lean in
# Year 1' why-now ... Expected: 'ran lean in Year 1' why-now"), so this scans the
# FULL description and collects every quoted inner-text following a
# prescriptive verb, including comma-list continuations like "'clear',
# 'reasonable', 'adequate'" (SVC-PC-14-6-0/c20). "Bans 'X'" is already covered
# by c3's _EXCLUSION_PRECEDING_RE, so it is intentionally not duplicated here.
_PRESCRIPTIVE_VERB_RE = re.compile(
    r"\b(?:honest|segregated|labell?ed|called|(?:rely|relies|relying)\s+on)\b"
    r"\s*"
    r"(?P<quotes>(?:'[^']{4,80}'|\"[^\"]{4,80}\")"
    r"(?:\s*(?:,|and|or)\s*(?:'[^']{4,80}'|\"[^\"]{4,80}\"))*)",
    re.IGNORECASE,
)


# c13 (2026-09-15 triage round): broader exclusion-context signal for a class c3's own
# _EXCLUSION_PRECEDING_RE/_EXCLUSION_FOLLOWING_RE miss -- that pair requires the marker word
# to sit IMMEDIATELY adjacent to the token (whitespace-only gap), correct for "not $X" but
# too narrow for a comma-separated list of banned examples ("(e.g., Zendesk, GitHub,
# inventory_flows.csv, SOC reports...)", where 2 other list items sit between "e.g.," and
# the flagged token) or a marker several words earlier in the same clause ("(e.g., calling
# an estimate 'arbitrary')"). Also, unlike c3 (whose extract_facts() loop explicitly skips
# filename/named_entity kinds), applied to those two kinds too -- confirmed a real gap on
# SVC-PC-14-6-0/c10: 'inventory_flows.csv' is judge.toml's OWN listed example of a
# forbidden/invented filename, not a source citation, and had no exclusion-context handling
# of any kind before this round. Scans a wider preceding window, clipped at the nearest
# ". " sentence boundary so it can't reach into unrelated prior prose, plus a short
# following window for a marker that comes AFTER the token ("'36 SaaS tools' ... not
# used"). A short, closed marker list -- every entry confirmed against real judge.toml text
# during this triage round (SVC-PC-14-3-0/j2, SVC-PC-14-6-0/c10+c17, SVC-PC-42-9-0/c28,
# SVC-PC-77-0-0/c14, SVC-PC-77-7-0/c12+c19), not a guess at what might generalize.
#
# Additive only: called from classify_fact() at each hard-flag point AFTER the existing,
# narrower `_context_downgrade_reason` check has already returned None, so this can only
# soften a hard-flag into possible_unreachable -- it can never remove an existing "clean"
# verdict or override a more specific existing downgrade reason.
_BROAD_EXCLUSION_PRECEDING_WINDOW = 150
_BROAD_EXCLUSION_FOLLOWING_WINDOW = 60
_BROAD_EXCLUSION_MARKER_RE = re.compile(
    r"\be\.?g\.?,?\s|\binvented\b|\bfabricat\w*|\bunsourced\b|\bmust\s+not\b|"
    r"\bbann?ed\b|\bforbidden\b|\brejected?\b|\bfail\s+if\b|"
    r"\bdo\s+not\s+(?:use|cite|include)\b",
    re.IGNORECASE,
)
_BROAD_EXCLUSION_FOLLOWING_RE = re.compile(
    r"^[^.]{0,60}?\b(?:not\s+used|rejected|not\s+asserted|not\s+required|unused|"
    r"does\s+not\s+meet\s+this|does\s+not\s+satisfy\s+this)\b",
    re.IGNORECASE,
)

# Real bug found testing this round against SVC-PC-77-7-0/c12's actual text: a naive
# `rfind(". ")` sentence-boundary clip treats the period INSIDE "e.g." itself as a
# sentence end ("...content (e.g. no 'MODEL STATUS: PASS'..." -- "g." followed by a space
# looks exactly like a sentence boundary), clipping off the very "e.g." marker
# `_BROAD_EXCLUSION_MARKER_RE` is trying to find. A real sentence restart is signaled by
# the NEXT word starting with a capital letter, not just "period then space" -- "e.g. no"
# fails that test ("no" is lowercase) while "deliverable. Expected" passes it ("Expected"
# is capitalized). That alone isn't quite enough either: "(e.g., Zendesk" would wrongly
# pass since "Zendesk" is a capitalized proper noun (SVC-PC-14-6-0/c10's actual list), so
# a short closed list of known abbreviations immediately before the candidate period is
# also rejected as a boundary.
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?]\s+(?=[A-Z])")
_ABBREVIATION_TAIL_RE = re.compile(
    r"\b(?:e\.g|i\.e|etc|vs|approx|no)\.$", re.IGNORECASE
)


def _last_real_sentence_boundary(text: str) -> int:
    """Index just after the last genuine sentence-ending boundary in `text`, or 0 if none
    is found (keep the whole text)."""
    last = 0
    for m in _SENTENCE_BOUNDARY_RE.finditer(text):
        if _ABBREVIATION_TAIL_RE.search(text[: m.start() + 1]):
            continue
        last = m.end()
    return last


def _broad_exclusion_context(description: str, fact: dict) -> str | None:
    start = fact.get("match_start")
    end = fact.get("match_end")
    if start is None:
        return None
    seg_start = max(0, start - _BROAD_EXCLUSION_PRECEDING_WINDOW)
    pre = description[seg_start:start]
    pre = pre[_last_real_sentence_boundary(pre) :]
    if _BROAD_EXCLUSION_MARKER_RE.search(pre):
        return (
            f"{fact['token']!r} not found, but a fabrication/prohibition marker "
            "(e.g./invented/banned/forbidden/rejected/fail if) sits earlier in the same "
            "clause -- likely one of the criterion's own listed examples of what NOT to "
            "cite, not a positive source fact -- downgraded, not hard-flagged"
        )
    if end is not None:
        post = description[end : end + _BROAD_EXCLUSION_FOLLOWING_WINDOW]
        if _BROAD_EXCLUSION_FOLLOWING_RE.match(post):
            return (
                f"{fact['token']!r} not found, but is immediately followed by a "
                "not-used/rejected marker in the same clause -- downgraded, not "
                "hard-flagged"
            )
    return None


# c14 (2026-09-15 triage round): "Q1-Q4"/"Q1-Q3"-shaped quarter-range shorthand, either bare
# ("the single-named 'Q1-Q4' input maps to 4 quarterly files") or embedded in a filename
# stem ("Q1-Q4_Channel_Attribution.xlsx"). A real, closed authoring convention on this
# corpus meaning "the separate Q1/Q2/Q3/Q4 files taken together," not one literal file or a
# literal "Q1-Q4" string anywhere in source text. Confirmed on 3 real tasks
# (SVC-PC-91-3-0/r1 quoted 'Q1-Q4', SVC-PC-26-3-0/r1 and SVC-PC-75-8-0/r12 both
# "Q1-Q4_Channel_Attribution.xlsx"), each independently naming the same shorthand and each
# confirming the 4 individual quarter files really do exist under environment/ (e.g.
# Q1_Channel_Attribution.xlsx .. Q4_Channel_Attribution.xlsx). Grounded only when at least 2
# of the individual quarter-numbered files actually exist with a shared stem remainder --
# not just any q1_/q4_-prefixed file -- so a genuinely missing quarterly file set still
# hard-gates.
_QUARTER_RANGE_RE = re.compile(r"q([1-4])\s*(?:-|–|to)\s*q?([1-4])", re.IGNORECASE)


def _quarter_range_satisfied(token: str, basenames: set) -> bool:
    m = _QUARTER_RANGE_RE.search(token.lower())
    if not m:
        return False
    lo, hi = int(m.group(1)), int(m.group(2))
    if lo >= hi:
        return False
    remainder = _QUARTER_RANGE_RE.sub("", token.lower()).strip("_- .")
    hits = 0
    for q in range(lo, hi + 1):
        prefixes = (f"q{q}_", f"q{q}-", f"q{q} ")
        for b in basenames:
            if any(b.startswith(p) for p in prefixes) and (
                not remainder or remainder in b
            ):
                hits += 1
                break
    return hits >= 2


def _has_digit(token: str) -> bool:
    return any(ch.isdigit() for ch in token)


def _is_all_caps_label(phrase: str) -> bool:
    """c7: a multi-word ALL-CAPS named entity ("NOT SOURCED", "DO NOT MOVE") is a
    flag-label the solver applies, not a proper-noun fact to find in the source.
    Single all-caps words are excluded from this heuristic -- "GL", "SVB", "HOLD"
    may be real acronym entities or single-word labels, handled by the explicit
    _NAMED_ENTITY_STOPWORDS entries instead, to avoid false-negaturing a real
    single-word acronym entity. Returns True only when every whitespace-separated
    word has at least one letter and every letter is uppercase."""
    words = phrase.split()
    if len(words) < 2:
        return False
    for w in words:
        letters = [c for c in w if c.isalpha()]
        if not letters or not all(c.isupper() for c in letters):
            return False
    return True


def extract_facts(description: str, ekw: bool, min_chars: int = 4):
    """Every fact-shaped token in one criterion's description. Returns a list of
    {token, kind, numeric} dicts. Never raises."""
    facts = []
    desc = description or ""

    # numeric/date/quoted tokens: SVC-PC isolates the Expected: clause (the calibrated
    # authoring convention answer_key_content_leak_check.py's own EXPECTED_CLAUSE_RE already
    # locates); EKW has no such label (confirmed against the real 274-task corpus by that
    # script's own EKW port) so the whole rubric prompt is scanned instead.
    # Track clause offset within the full description so match_start/match_end are absolute
    # positions in `desc`, not relative to the clause. This lets extract_anchors() index into
    # the full description directly. EKW scans the whole prompt (clause = desc, offset = 0).
    if ekw:
        clauses = [(desc, 0)]
    else:
        clauses = [(m.group(1), m.start(1)) for m in EXPECTED_CLAUSE_RE.finditer(desc)]
    for clause, clause_offset in clauses:
        for vm in VALUE_TOKEN_RE.finditer(clause):
            token = vm.group(0)
            kind = vm.lastgroup
            if kind == "bare_number" and YEAR_RE.match(token):
                continue
            # c15 follow-up (2026-09-15, found testing c15 itself): lowering the min_chars
            # floor for decimal_number/currency surfaced a genuinely new false-positive
            # class the OLD floor had been accidentally filtering out as a side effect --
            # a document cross-reference like "Section 7.3" or "Article 4.2" is a
            # decimal_number-shaped token with sig_len 2-3, previously invisible below the
            # old floor of 4, now extracted. It is a structural pointer into the task's OWN
            # rubric/plan document, not a data value to find in the environment. Confirmed
            # real on SVC-PC-29-5-0/r014,r026,r034: "validation cadences from Section 7.3"
            # extracted '7.3' and hard-flagged it (anchor 'section') once the floor
            # dropped. Skipped at extraction time (like the wildcard-filename and generic-
            # adjective-filename skips elsewhere in this function), not merely downgraded,
            # since a section number is never a fact worth even a low-confidence flag.
            if kind in NUMERIC_KINDS and re.search(
                r"\b(?:section|article|clause|exhibit|appendix|schedule|item|part)\s*$"
                r"|§\s*$",
                clause[max(0, vm.start() - 20) : vm.start()],
                re.IGNORECASE,
            ):
                continue
            # c20 (2026-09-16, row 9 close-out): a number immediately inside "Full (N):" /
            # "Half (N):" / "Partial (N):" is the JUDGE'S OWN grading-scale point value for
            # this criterion, not a fact the criterion is asking about at all -- same "never a
            # fact worth even a low-confidence flag" standard as the section-reference skip
            # directly above (this is a sibling case, not a duplicate: that one is a cross-
            # reference INTO another document, this one is the rubric's own scoring scaffold).
            # Confirmed on SVC-PC-73-0-0/73-1-0/73-2-0/73-3-0/73-5-0/57-2-0 (six tasks, ~23
            # rows in the real full-600 diff): every description follows the same
            # "Full (7): <criterion for full credit>. Half (3.5): <criterion for half
            # credit>. Zero: <criterion for no credit>." scaffold, and the "3.5"/"2.5"-shaped
            # half-credit values were extracted as if they were business figures to find in
            # the environment (they never are, by construction -- half of the max score is a
            # scoring-rubric constant, not sourced from anywhere). Before c18's floor-lowering
            # these were invisible (sig_len("3.5")==2 < the old floor of 4 for decimal_number),
            # so this false-positive class was never exposed until now.
            if kind in NUMERIC_KINDS and re.search(
                r"\b(?:full|half|partial)\s*\(\s*$",
                clause[max(0, vm.start() - 15) : vm.start()],
                re.IGNORECASE,
            ):
                continue
            match_end = vm.end()
            scale = 1.0
            if kind in ("currency", "comma_number", "decimal_number"):
                sm = _SCALE_SUFFIX_RE.match(clause, match_end)
                if sm:
                    suffix = sm.group(1)
                    scale = _SCALE_MULTIPLIER[suffix.lower()]
                    token = token + suffix
                    match_end = sm.end()
            # bare_number's own floor tracks VALUE_TOKEN_RE's 2+ digit pattern directly, not the
            # shared min_chars=4 default -- that default was silently cancelling the 2026-09-15
            # widening (a 2-3 digit bare_number has sig_len 2-3, always < 4), confirmed by Session
            # D re-testing the landed fix against real ground truth (100/14/30/12/18 still
            # invisible). Other (non-numeric) kinds keep the shared floor unchanged.
            #
            # c18 (2026-09-16, row 9 close-out): re-applies the currency/comma_number/
            # decimal_number floor-lowering c15 tried and reverted, now paired with the fix c15's
            # OWN "Known limits" entry already named but deferred ("count pre-filter tokens for
            # series detection, not post-filter facts" -- see _count_series_candidate_tokens
            # below and its call site in _check_one_criterion). c15's revert was measured against
            # a version of this file where SERIES_NUMERIC_THRESHOLD counted only tokens that had
            # already survived this same floor -- so a dense short-figure clause (a fee schedule,
            # a run of margin-ratio decimals) never reached the series threshold even once the
            # floor let its members through, and each member got hard-flagged individually. That
            # is the exact defect this module's docstring (Known limits, "SERIES_NUMERIC_THRESHOLD
            # can itself be defeated by --min-chars-style filtering") already disclosed as
            # "confirmed real, not fixed in this version" before c15 was ever attempted. Fixing
            # the series count to run pre-filter closes that gap without touching anchor
            # selection/scoring (this file's own rounds 4-22 regression class) or the value-shape
            # heuristic (2263348) -- both stay exactly as they were. Full before/after numbers
            # against the real corpus are in tracker row 9 and this commit's message, not
            # repeated here; re-derive rather than trust this comment if it and a real run ever
            # disagree.
            #
            # c15 (2026-09-15, later triage round): tried and reverted, kept here rather than
            # silently dropped. A parallel adversarial review flagged that this same min_chars=4
            # floor also silently drops short currency/decimal_number tokens ("$450", "$60",
            # "4.5") from extraction entirely, before classify_fact ever runs -- confirmed real by
            # direct execution (SVC-PC-29-5-0/r038's "...the $450 per month..." extracted zero
            # facts). The direct fix (lower the floor to 2 for currency/comma_number/
            # decimal_number, matching bare_number) was implemented, and DID fix that exact case
            # plus the review's other two named tasks. But a full 202-task before/after regression
            # (the same verification this round's OTHER fixes were held to) showed it is a net
            # LOSS on this corpus: 19 tasks outside any triaged set newly hard-failed, EVERY new
            # finding a short currency/decimal_number token (SVC-PC-22-3-0 alone gained 15 -- a
            # dense run of margin-ratio-shaped decimals like '1.38'/'1.20'/'1.71'; SVC-PC-2-6-0
            # gained 10 small dollar figures reading like a fee schedule). None of these 19 tasks
            # were read by any triage agent, so there is no evidence either way on any individual
            # one -- but the volume and shape (short decimals/dollars clustered densely across
            # many criteria in "build a financial model"-family tasks) matches exactly the
            # computed-value-with-no-textual-signal class this file's own docstring already
            # names as "the single biggest source of residual false positives," just newly
            # exposed at a length the old floor had been accidentally screening out. Net effect
            # on Khiem's 202: fail 122->134, the wrong direction for a session about REDUCING
            # false positives. Reverted rather than shipped un-triaged. The real gap the review
            # found stands (see module docstring's Known limits) -- a safe fix needs something
            # sharper than a length floor (e.g. cross-checking task-family membership, or a
            # dedicated triage pass on short-figure findings specifically, the way tonight's
            # other 122 findings got one before any code changed), not attempted this round.
            effective_min_chars = 2 if kind in NUMERIC_KINDS else min_chars
            if sig_len(token) < effective_min_chars:
                continue
            numeric = to_float(token) if kind in NUMERIC_KINDS else None
            if numeric is not None and scale != 1.0:
                numeric *= scale
            facts.append(
                {
                    "token": token,
                    "kind": kind,
                    "numeric": numeric,
                    "match_start": clause_offset + vm.start(),
                    "match_end": clause_offset + match_end,
                }
            )

    # filenames -- anywhere in the full description (a required-deliverable-name citation can
    # sit outside the Expected: clause, e.g. in the requirement sentence itself). Skip a match
    # immediately preceded by "*": a real authoring convention on this corpus is a wildcarded
    # family reference ("Q*_Demand_Planning.xlsx" meaning any of Q1/Q2/Q3/.../xlsx) -- confirmed
    # by hand on SVC-PC-12-0-0/r065 -- and without this guard FILENAME_RE's \b boundary matches
    # only the tail after the "*", producing a nonsense literal like "_Demand_Planning.xlsx" that
    # can never exist by construction, not a real fact to check.
    for fm in FILENAME_RE.finditer(desc):
        if fm.start() > 0 and desc[fm.start() - 1] == "*":
            continue
        stem = fm.group(0).rsplit(".", 1)[0].lower()
        if stem in _FILENAME_GENERIC_ADJECTIVE_STEMS:
            continue
        facts.append(
            {
                "token": fm.group(0),
                "kind": "filename",
                "numeric": None,
                "match_start": fm.start(),
                "match_end": fm.end(),
            }
        )

    # named entities: "named X" / "called X" / "labeled X" / "titled X"
    for nm in NAMED_ENTITY_RE.finditer(desc):
        phrase = nm.group(1).strip().rstrip(".")
        # A single bare letter is never a real named entity -- confirmed on the real EKW corpus:
        # "references a labeled J-curve exhibit" captured just "J", because NAMED_ENTITY_RE's
        # per-word character class has no hyphen, so "J-curve" stops at the hyphen. Rare (1 of 14
        # named_entity findings in the full 274-task sweep) but a real, disclosed gap -- the
        # proper fix is adding "-" to the word class, left for a future revision rather than
        # triggering another full-corpus rerun for one low-volume kind.
        if (
            not phrase
            or len(phrase) < 2
            or phrase.lower() in _NAMED_ENTITY_STOPWORDS
            or _is_all_caps_label(phrase)
        ):
            continue
        facts.append(
            {
                "token": phrase,
                "kind": "named_entity",
                "numeric": None,
                "match_start": nm.start(),
                "match_end": nm.end(),
            }
        )

    # id/code tokens -- low-confidence only (see module docstring); skip a wildcard-suffixed
    # authoring convention ("Cite_L2_*") and any task-ID-shaped token
    for im in ID_CODE_RE.finditer(desc):
        token = im.group(0)
        if not _has_digit(token):
            continue
        if TASK_ID_SHAPE_RE.match(token):
            continue
        if "*" in desc[im.end() : im.end() + 2]:
            continue
        if sig_len(token) < min_chars:
            continue
        facts.append(
            {
                "token": token,
                "kind": "id_code",
                "numeric": None,
                "match_start": im.start(),
                "match_end": im.end(),
            }
        )

    # c3: mark facts in an exclusion context ("not $X", "Bans 'X'", "e.g., 'X' is
    # scored 0", "'X' is scored 0"). Downgraded to possible_unreachable in
    # classify_fact, not skipped, so a misdetected exclusion is still surfaced
    # (non-blocking) rather than silently dropped. Checked for numeric, quoted,
    # date, and id_code kinds; filename and named_entity have their own handling.
    for f in facts:
        if f["kind"] in ("filename", "named_entity"):
            continue
        start = f["match_start"]
        end = f["match_end"]
        pre = desc[max(0, start - 30) : start]
        post = desc[end : end + 30]
        if _EXCLUSION_PRECEDING_RE.search(pre) or _EXCLUSION_FOLLOWING_RE.match(post):
            f["exclusion_context"] = True

    # c7: mark quoted facts in a prescriptive context (a phrase the solver should
    # WRITE, not find). Scan the FULL description for a prescriptive verb
    # ("honest", "segregated", "labeled", "called", "rely/relies on") followed by
    # a quoted string or a comma-list of quoted strings, collect every inner-text
    # so matched, then mark any quoted fact whose inner-text is in that set. This
    # also covers the cross-occurrence case where the verb sits in the
    # requirement sentence and the same quoted string is re-extracted from the
    # Expected: clause (SVC-PC-11-4-0). Downgraded to possible_unreachable in
    # classify_fact via the shared _context_downgrade_reason helper, not skipped,
    # so a misdetected prescriptive context is still surfaced (non-blocking).
    prescriptive_inners: set[str] = set()
    for pm in _PRESCRIPTIVE_VERB_RE.finditer(desc):
        for qm in re.finditer(r"'[^']{4,80}'|\"[^\"]{4,80}\"", pm.group("quotes")):
            prescriptive_inners.add(qm.group(0)[1:-1].lower())
    if prescriptive_inners:
        for f in facts:
            if f["kind"] != "quoted":
                continue
            if f["token"][1:-1].lower() in prescriptive_inners:
                f["prescriptive_context"] = True

    for f in facts:
        f["ekw"] = ekw
    return facts


# c18 (2026-09-16, row 9 close-out): companion to extract_facts' NUMERIC_KINDS floor change
# above. Mirrors extract_facts' own clause loop and its two non-length exclusions (a
# year-shaped bare_number, a section/article/clause/exhibit/appendix/schedule/item/part
# cross-reference number) exactly, but does NOT apply sig_len/min_chars -- this is the
# "pre-filter" count the module docstring's own Known limits section already named as the
# fix for SERIES_NUMERIC_THRESHOLD being defeatable by min_chars filtering, deferred at the
# time rather than implemented. Deliberately a separate function rather than a parameter on
# extract_facts itself: extract_facts returns FACTS (used for matching/classification, where
# the floor is a real, intentional precision guard -- a 1-2 sig-char currency token is
# genuinely too weak a signal to hard-gate on by itself); this counts CANDIDATES (used only to
# decide whether a criterion reads as a computed table/series, where a token below the floor
# is still real evidence of "this clause lists several figures at once" even though it is not
# itself trustworthy enough to individually hard-flag). Conflating the two by reusing
# extract_facts' own output would silently reintroduce the exact bug this exists to fix.
def _count_series_candidate_tokens(description: str, ekw: bool) -> int:
    desc = description or ""
    if ekw:
        clauses = [desc]
    else:
        clauses = [m.group(1) for m in EXPECTED_CLAUSE_RE.finditer(desc)]
    count = 0
    for clause in clauses:
        for vm in VALUE_TOKEN_RE.finditer(clause):
            kind = vm.lastgroup
            if kind not in NUMERIC_KINDS:
                continue
            token = vm.group(0)
            if kind == "bare_number" and YEAR_RE.match(token):
                continue
            if re.search(
                r"\b(?:section|article|clause|exhibit|appendix|schedule|item|part)\s*$"
                r"|§\s*$",
                clause[max(0, vm.start() - 20) : vm.start()],
                re.IGNORECASE,
            ):
                continue
            # c20: mirrors extract_facts' grading-scale skip above -- keep the two in sync
            # per this function's own docstring (a candidate extract_facts would never
            # extract as a fact must not inflate the series-candidate count either).
            if re.search(
                r"\b(?:full|half|partial)\s*\(\s*$",
                clause[max(0, vm.start() - 15) : vm.start()],
                re.IGNORECASE,
            ):
                continue
            count += 1
    return count


COMPUTE_INDICATOR_RE = re.compile(
    r"\b(aov|average order value|gross margin|growth rate|variance|bridge|"
    r"calculat\w*|comput\w*|deriv\w*|resulting|result of|net of|adjusted for|"
    r"ratio of|%\s*of|percent of|delta between|difference(?:\s+between)?|weighted[- ]average|"
    r"reconcil\w*\s+to\s+(?:zero|residual)|"
    # c10 (2026-09-15 triage round): bare "average" (no "order value"/"weighted-" prefix
    # required). Confirmed on SVC-PC-10-2-0/c01,c02,c06: "8 weeks of average Nov/Dec demand"
    # states the computation method directly, but no existing keyword covers a bare
    # "average" -- only the compound "average order value" and "weighted[- ]average" did.
    # A raw stated fact being phrased with "average" in this corpus's rubric prose is not a
    # confirmed real risk anywhere in the 4-task hand-validation set or this triage round's
    # 101-finding sweep, so this is judged safe on the same "downgrade, don't exclude, on
    # real evidence" basis as every other entry in this list.
    r"\baverage\b|"
    # c11 (2026-09-15 triage round): "presented as a range"/"as a range, not a point
    # figure" -- a criterion whose OWN Expected text explicitly asks for a RANGE output
    # under genuine data uncertainty can never be satisfied by a single verbatim source
    # figure; the range bounds are the solver's own honest-estimate endpoints, not two
    # separate lookup facts. Confirmed verbatim on SVC-PC-15-1-0/b2 and SVC-PC-15-2-0/d8:
    # "Customer compensation is presented as a range, not a point figure Expected:
    # $2,000-$4,000."
    r"presented\s+as\s+a\s+range|as\s+a\s+range,?\s+not\s+a?\s*point|"
    # a "build a financial model" task family (SVC-PC-10-*, confirmed by hand) states its own
    # simulation-methodology terms right next to the Expected: figures it produces -- a Monte
    # Carlo trough at a specified seed is fully reproducible by the solver, not an unreachable
    # fact, even though it obviously appears nowhere in the raw input environment
    r"monte carlo|stochastic|pcg64|\bseed\s*\d|\btrials\b|percentile|\bp0[1-9]\b|\bp[1-9]\d\b|"
    # "design/build/stand up a new program and cost it out" tasks (SVC-PC-11-*, confirmed by
    # hand: a benefits-program build where "$2,400/FTE (stipend policy)" and "$276,599 (cost
    # model)" are the solver's own cost-modeling output, not a fact from an existing document --
    # the task literally says "you are responsible for ... the integrated cost model")
    r"subtotal|cost model|financial model|program design|"
    # c2b/c2c (round 22, 2026-09-15): "itemised by vendor" / "itemized by vendor" /
    # "projected by vendor" (SVC-PC-7-4-0/o4) are compute signals: a criterion that
    # says a value is "itemised by" or "projected by" something is describing the
    # solver's own aggregation or projection methodology, not a raw source fact.
    # itemi[sz]ed catches both British "itemised" and American "itemized".
    r"itemi[sz]ed\s+by|projected\s+by|"
    # "Total FY2022 payroll Expected: $2,259,750.", "Total wholesale units Expected: ~6,500" --
    # confirmed by hand: on this corpus "Total X Expected: Y" reads as a rollup the solver
    # builds up from several source lines, not a single stated figure; the genuine raw-fact
    # convention here is "Cited X Expected: Y" (see obj-06/YE TB 6100 in this script's own
    # 4-task validation set), which does not contain the word "total" at all.
    # c2d (round 22, 2026-09-15): \btotal\b missed inflected forms "totalling"/"totalled"
    # (British) and "totaled"/"totals" (American). The narrower \btotal(?:ling|led|s)?\b from
    # the triage still misses American "totaled" (single-l + "ed"). \btotal[a-z]*\b catches
    # every inflection (total, totals, totalling, totalled, totaled, totalled, totalings)
    # without enumerating spellings. Confirmed on SVC-PC-14-4-0/c02 ("correctly totaled and
    # counted") and SVC-PC-9-3-0/r04 ("totalling").
    r"\btotal[a-z]*\b|employer burden|\bburden\b|"
    # c19 (2026-09-16, row 9 close-out): two named-metric keywords found auditing the real
    # full-600 before/after diff for the c18 floor-lowering above, both unambiguous -- neither
    # word names anything a source document states directly, each names a formula.
    # "elasticity" (arc/price elasticity): confirmed on SVC-PC-22-3-0's r012-r017, each
    # description literally "<Event>: arc elasticity ~-N.NN Expected: ~-N.NN" -- an arc
    # elasticity is computed from a price-and-quantity-change formula by construction, never a
    # value a source document states outright. Scoped to the bare word (not "arc elasticity"
    # specifically) since every real occurrence checked is a compute context and the word has
    # no other sense in this corpus's business-finance register.
    # "compa" (compa-ratio, a standard HR/compensation metric = salary / market midpoint):
    # confirmed on SVC-PC-18-5-0/r3, "Expected: 0.88; 1.00" anchored on "compa" from a
    # "comp-ratio" / "compa-ratio" label. Scoped to the stem "compa" (not the full word) so
    # "compa-ratio", "compa ratio", and "comp-ratio"-adjacent phrasing all match without
    # enumerating spellings, same pattern as \btotal[a-z]*\b above.
    r"\belasticity\b|\bcompa\b|compa[- ]?ratio|"
    # c19 continued: "weighted ... score" (a weighted evaluation/comparison score) is a
    # distinct compute-indicator from the existing \bweighted[- ]average\b -- confirmed on
    # SVC-PC-15-4-0/b1 ("States SwiftShip's weighted evaluation score Expected: 4.22") and /b4
    # ("States the runner-up's weighted score Expected: 3.92"), a vendor-scoring task family
    # where the solver computes each vendor's score from its own stated criteria weights, so
    # the resulting number is never independently stated in a source document. Bounded to a
    # short word gap (not a bare \bscore\b, which risks the same generic-word regression class
    # rounds 4-22 already hit) so it requires BOTH "weighted" and "score" together.
    r"weighted\b[a-z ]{0,20}\bscore\b)\b",
    re.IGNORECASE,
)

# A short, non-filename parenthetical directly after an Expected: value
# ("(cost model)", "(stipend policy)", "(Pipeline_Forecast tab)", "(broker quote)",
# "(broker quote × census)") reads as "which section of YOUR OWN deliverable this belongs
# under" or "what methodology produced this figure" rather than a citation to an existing
# source document -- a real source citation on this corpus is either a Title-Case filename
# (caught by FILENAME_RE) or capitalized proper-noun prose, not a bare common-noun phrase
# in parens. Deliberately narrow (no filename-shaped content, short, keyword-anchored) to
# avoid swallowing a genuine parenthetical source citation like "(per the November invoice)".
# c2b (round 22, 2026-09-15): added quote|census|rollup|projection|estimate to the keyword
# list, added re.IGNORECASE so the docstring's own "(Pipeline_Forecast tab)" example
# actually matches (the regex required lowercase [a-z] with no IGNORECASE flag, so it
# never matched its own documented example), and added _ and the multiplication sign
# (U+00D7, the "x" in "(broker quote x census)") to the char class so both
# "(Pipeline_Forecast tab)" and "(broker quote x census)" match. Confirmed on
# SVC-PC-11-2-0/r016 ("$160,934 (broker quote x census)") and r018 ("$10,336 (broker quote)").
SELF_SECTION_POINTER_RE = re.compile(
    r"\((?:the\s+)?[a-z][a-z '/_\u00d7-]{1,30}\s+"
    r"(?:model|policy|plan|design|proposal|budget|forecast|tab|sheet|schedule|"
    r"quote|census|rollup|projection|estimate)\)",
    re.IGNORECASE,
)

# A parenthetical "(TabName!C4)"-shaped citation. Confirmed as a real, high-volume authoring
# convention on a 60-task sample (4 tasks, 161 occurrences, all in one "build a forecast model"
# task family): the Expected: value is pointing at a CELL IN THE SOLVER'S OWN DELIVERABLE
# workbook (e.g. "Revenue Expected: 140,000 (Pipeline_Forecast!D4)"), not a source document --
# it is telling a grader/reviewer where to find the number in the graded output, exactly the
# inverse of a source citation. Any fact from a description carrying this pattern is treated as
# computed/derived, same as a COMPUTE_INDICATOR_RE match -- confirmed by hand this catches a real
# false-positive class this script's own compute-indicator keyword list otherwise misses
# entirely (no "calculated"/"derived"/etc. keyword appears in that phrasing).
DELIVERABLE_CELL_REF_RE = re.compile(
    r"\([A-Za-z_][\w ]*![A-Z]{1,3}\d+(?::[A-Z]{1,3}\d+)?\)"
)

# A "results.board_conclusion.conclusion=..."-shaped dotted-path assignment. Confirmed by hand
# on SVC-PC-10-5-0: an entire task family has the solver build a full financial model from a
# small set of input assumptions, and every "Expected:" value is a JSON-path assertion against
# the solver's OWN computed results structure (Monte Carlo percentiles, a 12-month cash-flow
# table, a sensitivity ranking) -- structurally the same "citing an output location, not a
# source" shape as DELIVERABLE_CELL_REF_RE above, just JSON-path syntax instead of
# sheet-and-cell. Requires 3+ dotted segments before the "=" so it doesn't fire on an ordinary
# "X.Y=" fragment.
DOTTED_PATH_ASSIGNMENT_RE = re.compile(
    r"\b[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*){2,}\s*="
)

# The same task family also states a short 2-segment path ("Jan.cash_in=114,301.05") once its
# JSON root ("results.") has already been established earlier in the SAME description ("results.
# children.three_case_decision.cases.Base.monthly has all 12 months ..."). Rather than lowering
# DOTTED_PATH_ASSIGNMENT_RE's segment count (which would start matching ordinary short dotted
# prose elsewhere in the corpus), a second, narrower signal: "results." itself, anywhere in the
# description, with no "=" required -- confirmed specific to this JSON-model convention on the
# real corpus, not seen in any other task's rubric language during this script's development.
RESULTS_JSON_ROOT_RE = re.compile(r"\bresults\s*[.=]", re.IGNORECASE)

# c2a (round 22, 2026-09-15): arithmetic identity printed in the criterion text itself.
# The round-21 triage found criteria stating an explicit formula
# ("$34.17 = $205,000 / 6,000 new customers",
#  "$1,218,900 less the $14,000 ... equals ... $1,204,900",
#  "140 x $100") that no COMPUTE_INDICATOR_RE keyword matches, so a genuinely
# computed value gets hard-flagged as unreachable. This matches an explicit
# arithmetic identity: a number, an operator/word, and another number within a
# bounded gap, plus the standalone words "arithmetic"/"formula".
#
# Guarded against over-match (the triage flagged this as the highest-volume
# fix, so each guard was checked against real corpus text):
# - "=" requires a NUMBER on the LEFT, so "FULL=6" tier-scoring boilerplate,
#   "a = 1" variable assignments, and ">="/" <=" comparisons don't trigger it
#   (the > or < char before = breaks the number-left-= anchor).
# - "/" requires the LEFT number to be $-prefixed, 3+ digits, or comma-containing
#   so date components (1-2 digits like "4/8/12") don't trigger it. A negative
#   lookahead after the right number rejects a date_slash continuation
#   (X/Y/Z), so "2021/03/22" doesn't match either. "$1,740/yr" and "$2,400/FTE"
#   don't match because the right side is a word, not a digit.
# - "x" as multiplication requires a digit on both sides (digit-x-digit or
#   digit-space-x-space-digit), so the letter x in ordinary words ("box", "tax",
#   "expected") or as a multiplier suffix ("3.0x," followed by a comma) doesn't
#   trigger it.
# - "less" excludes "less than" (comparison, not subtraction) via negative
#   lookahead. Word operators (less/equals/divided/times) require a number on
#   the LEFT and a number within 40 chars on the right, not crossing a sentence
#   boundary ([^.] gap).
# - "arithmetic"/"formula" are matched as standalone words anywhere in the
#   description (rare in rubric prose, always computational when present), same
#   risk profile as the existing COMPUTE_INDICATOR_RE keywords "calculated" /
#   "derived".
ARITHMETIC_IDENTITY_RE = re.compile(
    r"(?:"
    # number = number (e.g. "$34.17 = $205,000")
    r"[\$]?\d[\d,]*\.?\d*\s*=\s*[\$]?\d" r"|"
    # number + number (addition)
    r"[\$]?\d[\d,]*\.?\d*\s*\+\s*[\$]?\d" r"|"
    # number / number (division) -- left must be $-prefixed, 3+ digits, or
    # comma-containing so date components don't match; negative lookbehind
    # rejects a left number preceded by a slash or digit (date/list
    # continuation); negative lookahead rejects any following digit, period,
    # comma, slash, percent, or "x" (with optional whitespace), preventing
    # date_slash continuation (X/Y/Z), cap-table "shares / percent", and
    # value lists like "$34.17 / 5.9x" from false-matching as division. The
    # period and comma in the rejected set close all backtracking paths (the
    # regex can't shorten the right number to escape the guard).
    r"(?<![/\d,])(?:\$\d|\d{3,}|\d,\d{3})[\d,]*\.?\d*\s*/\s*[\$]?\d[\d,]*\.?\d*(?<!,)(?!\s*[\d.,%x/])"
    r"|"
    # number (word-op) ... number within 40 chars, not crossing a sentence
    r"[\$]?\d[\d,]*\.?\d*\s+(?:equals?|divided|times|less(?!\s+than))\b[^.]{0,40}?\d"
    r"|"
    # digit x [space] digit/$digit (multiplication, e.g. "140 x $100", "6x6")
    r"\d\s*x\s*\$?\d" r"|"
    # standalone computational language
    r"\b(?:arithmetic|formula)\b" r")",
    re.IGNORECASE,
)

# c12 (2026-09-15 triage round): arrow/derivation notation, "input -> output" or
# "input=>output" -- a raw-input value converted to a derived one inline in the criterion's
# own text, not a fact the environment states directly. Confirmed on SVC-PC-3-4-0/c23
# ("350/mo/head -> 80,850 FY") and SVC-PC-39-3-0/c10 ("new customers 6,000->~22,408").
# Kept OUT of ARITHMETIC_IDENTITY_RE (a separate regex + guard function, not just another
# alternative in that one) after a real regression found testing this exact round against
# SVC-PC-75-6-0/d2, a GENUINE defect: "correct the $350/mo charge → ~$100/mo" also matches
# an arrow between two numbers, but the arrow here means "this WRONG value should become
# this one," a correction narrative -- $350 is the disputed fact in question, not a value
# derived FROM something else. Syntactically indistinguishable from the real derivation
# cases without a semantic check, so `_arrow_reads_as_computed` rejects any match whose
# neighborhood contains correction/proposal language ("correct", "propose", "should be",
# "dispute", "instead of", "rather than") before trusting the arrow as a compute signal.
ARROW_DERIVATION_RE = re.compile(
    r"\d[^.\n]{0,40}(?:->|=>|→)[^.\n]{0,40}\d", re.IGNORECASE
)
_CORRECTION_NARRATIVE_RE = re.compile(
    r"\b(?:correct\w*|propos\w*|should\s+be|dispute\w*|instead\s+of|rather\s+than)\b",
    re.IGNORECASE,
)


def _arrow_reads_as_computed(description: str) -> bool:
    for m in ARROW_DERIVATION_RE.finditer(description):
        window = description[max(0, m.start() - 40) : m.end() + 10]
        if not _CORRECTION_NARRATIVE_RE.search(window):
            return True
    return False


# c2c (round 22, 2026-09-15): row/population counts stated as a figure
# ("2,184 lines", "9,989 orders", "11 JEs") with no count-noun compute signal.
# The round-21 triage found criteria stating a row/population count as a
# computed figure: the solver counts, filters, or aggregates the source data,
# and the count is not a raw fact copied from any single source cell.
# A numeric fact immediately followed by a count noun (lines, JEs, entries,
# orders, rows, records, SKUs) is treated as a computed population count, same
# risk profile as COMPUTE_INDICATOR_RE's existing "calculated" / "derived"
# keywords. Confirmed on SVC-PC-14-6-0/c02 ("2,184 lines") and
# SVC-PC-80-7-0/a5 ("9,989 orders").
COUNT_NOUN_RE = re.compile(
    r"\b\d[\d,]*\s+(?:lines|JEs|entries|orders|rows|records|SKUs)\b",
    re.IGNORECASE,
)


def _reads_as_computed(description: str) -> bool:
    return bool(
        COMPUTE_INDICATOR_RE.search(description)
        or ARITHMETIC_IDENTITY_RE.search(description)
        or _arrow_reads_as_computed(description)
        or DELIVERABLE_CELL_REF_RE.search(description)
        or DOTTED_PATH_ASSIGNMENT_RE.search(description)
        or RESULTS_JSON_ROOT_RE.search(description)
        or SELF_SECTION_POINTER_RE.search(description)
        or COUNT_NOUN_RE.search(description)
    )


# c16 (2026-09-15, anchor-proximity-miss round): a VALUE-SHAPE signal, not a description-
# text keyword -- the one new mechanism this round adds that never touches anchor selection
# or scoring at all. A currency/comma_number/decimal_number token with 3+ digits after the
# decimal point is essentially never a raw fact a human typed into a real business document:
# this corpus's actual source files (invoices, GL exports, bank statements, rate cards) use
# at most 2 decimal places for currency, and a 3+-digit decimal tail is the signature of an
# unrounded division/ratio result. Confirmed by enumerating every current anchor-proximity-
# miss finding across the full ~600-task corpus (1718 total) and cross-checking the 138
# tokens with 3+ decimal digits against this session's own triage evidence: EVERY one
# checked traces to a confirmed computed value or external constant, never once to a
# contradicted case -- e.g. SVC-PC-12-2-0's 0.376/0.364/0.436/... (per-SKU gross-margin
# outputs, "(wholesale price - unit cost) / wholesale price"), SVC-PC-5-2-0's
# 0.907/0.749/0.557/0.398 (Monte Carlo P(<$1.0M) outputs), SVC-PC-70-5-0's 2.326 (a
# standard-normal service-level constant), SVC-PC-40-1-0/40-3-0's dense run of 4-decimal
# cohort-repeat-rate figures. Tolerates a trailing ")" (accounting-negative currency).
# Deliberately narrow -- 1-2 decimal places (the normal currency/percentage shape) are left
# alone, since that range is exactly where a genuine raw source fact and a computed one are
# indistinguishable by shape and this signal would stop being safe.
#
# Real bug found testing this against its own edge cases before the full-corpus run: a
# scale-suffixed token ("$1.205M", from this file's own c8 fix) also has a 3-digit decimal
# tail ("205") but is NOT suspicious -- "$1.205M" = $1,205,000 exactly, a perfectly normal,
# human-writable abbreviation at that scale (real financial writing routinely carries 2-3
# decimals into an M/K/B abbreviation). The unrounded-division signature this check targets
# only applies to a token with NO scale suffix, so a trailing letter exempts the token
# entirely rather than being "tolerated" through to the digit-count check.
_VALUE_SHAPE_DECIMAL_TAIL_RE = re.compile(r"\.(\d+)\)?$")
_VALUE_SHAPE_SCALE_SUFFIX_RE = re.compile(r"[A-Za-z]$")


def _value_shape_reads_as_computed(fact: dict) -> bool:
    if fact["kind"] not in ("currency", "comma_number", "decimal_number"):
        return False
    token = fact["token"]
    if _VALUE_SHAPE_SCALE_SUFFIX_RE.search(token):
        return False
    m = _VALUE_SHAPE_DECIMAL_TAIL_RE.search(token)
    return bool(m) and len(m.group(1)) >= 3


# c17 (2026-09-15, tier-anchor task-scope round, tracker row 14): instruction.md is shared,
# task-wide context every criterion in a task implicitly inherits, unlike a criterion's own
# judge.toml description (which is all _reads_as_computed above ever looks at). Confirmed by
# hand on SVC-PC-35-0-0 and SVC-PC-35-6-0: both build a tiered wholesale partner program and
# both instruction.md files state "Contribution = gross margin $ - fulfillment - MDF"
# (SVC-PC-35-6-0 additionally states the T1/T2/T3 percentage formula inline and a "Program
# roll-up ... revenue and contribution by tier, plus program totals" rollup sentence;
# SVC-PC-35-0-0 defers the percentages to an external "wholesale pricing proposal" it only
# references by name, never quoting the numbers). Neither file repeats the specific per-partner
# dollar figures anywhere (those come from an external pipeline spreadsheet), so a "same numeric
# token in instruction.md" scope cannot work for this mechanism by construction -- the value
# that would need to match is never there.
#
# Deliberately NOT a blanket "does instruction.md contain any COMPUTE_INDICATOR_RE word
# anywhere -> downgrade every hard-fail in this task" gate -- ties the downgrade to requiring
# BOTH (a) the criterion's OWN scored anchor word appears in instruction.md as a whole word, AND
# (b) a compute-indicator match sits within the same PROXIMITY_WINDOW already used for every
# other anchor-proximity check in this file, anchored to THAT occurrence. This is the
# task-scope analogue of the exact criterion-scope failure mode that caused rounds 4-22's
# regressions, so it does not reuse COMPUTE_INDICATOR_RE unchanged -- see
# _INSTRUCTION_COMPUTE_INDICATOR_RE below for why a second, narrower keyword list was necessary
# even with the anchor-proximity requirement in place.
#
# REAL REGRESSION FOUND AND FIXED before shipping, not merely a theoretical risk: the FIRST
# full-corpus verification run (khiem_202, round 3) using the FULL COMPUTE_INDICATOR_RE for this
# check silently cleared 2 of the 21 hand-confirmed genuine defects, SVC-PC-17-2-0's r040 ("FY2021
# units shipped (order book) -- Product Expected: 12,166") and r042 ("Implied blended landed cost
# per unit ($) -- Product Expected: 34.80"). Root cause traced exactly: both criteria's own
# judge.toml phrasing ends "... -- Product Expected: <value>", so extract_anchors() scores the
# templated placeholder word "Product" as primary anchor for both -- not a real semantic subject.
# SVC-PC-17-2-0's instruction.md is a landed-cost-breakdown memo that uses "product" repeatedly
# for an unrelated, legitimate reason (a cost-COMPONENT name and a column label: "the cost
# components (product/ex-works, inbound freight, duties/handling), the landed total"), and that
# occurrence sits within PROXIMITY_WINDOW of "total" (from "the landed total") -- a real anchor
# match, a real compute-indicator match, and a completely false connection between them: units
# shipped and a landed-cost-per-unit figure have nothing to do with "the landed total" three
# words away. "total" is exactly the kind of bare, common word this file's OWN existing anchor
# infrastructure already distrusts -- it is a member of _ANCHOR_GENERIC_DESCRIPTORS above,
# specifically because a generic word like this coincidentally sits near almost anything. Using
# the FULL COMPUTE_INDICATOR_RE (tuned for the criterion-scoped, much narrower text window
# _reads_as_computed searches) against an entire task-wide instruction.md is a materially larger
# search space for exactly this kind of coincidence, so the same keyword list is not safe to
# reuse unchanged at this wider scope.
#
# Fixed by searching a second, deliberately narrower regex
# (_INSTRUCTION_COMPUTE_INDICATOR_RE) for this function only -- _reads_as_computed's own
# criterion-scoped use of the full COMPUTE_INDICATOR_RE is untouched, since that use has its own
# separate history of real-corpus verification at the narrower scope it was tuned for. Dropped:
# every bare or near-bare common-English word/phrase already flagged risky by this file's own
# _ANCHOR_GENERIC_DESCRIPTORS list (total/totals, resulting/result of -- "result"/"results" is in
# that list, bare average -- already flagged in this file's own c10 comment as accepted only on
# a "downgrade, don't exclude" basis for the NARROWER criterion-text use) or of the same
# generic-business-prose character (net of, adjusted for, growth rate, burden/employer burden).
# Kept: every technical or multi-word-distinctive phrase (gross margin, % of/percent of,
# calculat*/comput*/deriv*, ratio of, delta/difference between, weighted-average, reconcile to
# zero/residual, Monte Carlo/stochastic/percentile family, subtotal/cost model/financial
# model/program design, itemised/projected by, presented as a range, aov/average order value).
#
# Re-verified after the fix (see _scratch_round3_full_verify.py, tracker row 14): SVC-PC-17-2-0's
# r040/r042 confirmed still correctly hard-flagged; SVC-PC-35-6-0 still resolves via the SAME
# "tier"/"program"/"contribution" anchors, now matching "% of" (from the T1/T2/T3 percentage
# sentence) and "gross margin" (from "Contribution = gross margin $...") instead of the dropped
# "totals" -- confirming the real signal for that task was never dependent on the risky keyword.
# SVC-PC-35-0-0 remains at 8 of 49 resolved (up from 1 pre-fix, since fixing the anchor regex's
# accidental case-sensitivity below let it find capitalized occurrences too) -- see the module's
# own asymmetry note in Known limits above. Full before/after corpus numbers are in the round-3
# commit message and tracker row 14, not repeated here.
#
# SECOND round of real problems found auditing the first full-corpus run's OTHER newly-resolved
# tasks (not just SVC-PC-17-2-0), before trusting any of them: a negation-blind match
# (SVC-PC-48-1-0's "Consume existing inputs -- don't re-derive the attribution read" matched
# "derive" as if it meant this IS derived, when the sentence says the opposite: use the existing,
# sourced figure, don't recompute it) and a same-word-different-sense collision (that same task's
# "net" anchor, from a criterion about "net adds" i.e. net of churn, matched a "% of" a few
# characters away that is actually about "net revenue" i.e. net of returns -- textually adjacent,
# semantically unrelated). Measured the actual anchor-to-keyword character distance for every
# hand-reviewed good and bad match (_scratch_distance_analysis.py): they do NOT separate by
# distance at all -- SVC-PC-51-2-0's genuine "net" match and SVC-PC-48-1-0's false "net" match are
# BOTH distance 1, so no window size fixes this class; only the negation guard below (fixable)
# addresses it, and the same-word-different-sense class remains a disclosed residual risk (see
# Known limits) rather than something this round invents a heuristic to chase.
_INSTRUCTION_COMPUTE_INDICATOR_RE = re.compile(
    r"\b(aov|average order value|gross margin|variance|bridge|"
    r"calculat\w*|comput\w*|deriv\w*|"
    r"ratio of|%\s*of|percent of|delta between|difference(?:\s+between)?|weighted[- ]average|"
    r"reconcil\w*\s+to\s+(?:zero|residual)|"
    r"presented\s+as\s+a\s+range|as\s+a\s+range,?\s+not\s+a?\s*point|"
    r"monte carlo|stochastic|pcg64|\bseed\s*\d|\btrials\b|percentile|\bp0[1-9]\b|\bp[1-9]\d\b|"
    r"subtotal|cost model|financial model|program design|"
    r"itemi[sz]ed\s+by|projected\s+by)\b",
    re.IGNORECASE,
)

# Same precedent as ARROW_DERIVATION_RE's own _CORRECTION_NARRATIVE_RE guard above (a small
# window checked immediately around a match, rejecting it rather than trusting the keyword
# alone): "don't re-derive" / "not re-derived" / "never calculated" instructs the solver to USE
# an existing, sourced figure rather than recompute it -- the opposite of what a bare keyword
# match assumes. Confirmed real on SVC-PC-48-1-0's two "don't re-derive" occurrences (see above).
_INSTRUCTION_NEGATION_GUARD_RE = re.compile(
    r"\b(?:don'?t|do\s+not|does\s*n'?t|does\s+not|won'?t|will\s+not|"
    r"never|not|no\s+need\s+to)\s+(?:\w+[-\s])?$",
    re.IGNORECASE,
)
_NEGATION_GUARD_WINDOW = (
    20  # chars immediately before the keyword match, not PROXIMITY_WINDOW
)


def _instruction_context_reads_as_computed(
    instruction_text: str, anchors: list[str]
) -> bool:
    if not instruction_text or not anchors:
        return False
    for anchor in anchors:
        for m in re.finditer(
            r"(?<![A-Za-z0-9])" + re.escape(anchor) + r"(?![A-Za-z0-9])",
            instruction_text,
            re.IGNORECASE,
        ):
            ctx_start = max(0, m.start() - PROXIMITY_WINDOW)
            ctx_end = min(len(instruction_text), m.end() + PROXIMITY_WINDOW)
            window = instruction_text[ctx_start:ctx_end]
            for cm in _INSTRUCTION_COMPUTE_INDICATOR_RE.finditer(window):
                guard_start = max(0, cm.start() - _NEGATION_GUARD_WINDOW)
                if not _INSTRUCTION_NEGATION_GUARD_RE.search(
                    window[guard_start : cm.start()]
                ):
                    return True
    return False


# ---------------------------------------------------------------------------
# context-anchored matching: replaces the two context-blind suppression paths
# (_word_match for numeric facts, the flat floats set) with proximity-based
# anchor matching. See design-proposals/criterion-groundedness-fix-2026-09-15.md.
# A fact is "grounded" only if its value appears in the environment near at least
# one of the same subject/unit words that surround it in the criterion text.
# ---------------------------------------------------------------------------


# c4b (2026-09-15): high-frequency abbreviations that can win primary-anchor on
# pure proximity over a full word also present in the same criterion text. A short
# abbreviation (op, gl, gm, mo) is structurally closer to the numeric token than
# the full word (orders, ledger, margin, month) because the abbreviation sits in
# the unit-position right after the number, while the full word is a word or two
# further away. The -30 penalty overcomes a ~6-word distance gap. Confirmed on:
# SVC-PC-80-7-0/a2 ("gl" beat "revenue"), SVC-PC-2-4-0/c6 ("op" beat "orders"),
# SVC-PC-7-6-0/c13 ("mo" beat "cac"). "cac" is deliberately NOT included: it IS
# the correct anchor on SVC-PC-7-6-0/c13 (the value grounds via "CAC" in the
# environment). "fy" is NOT included: testing showed it caused a regression on
# SVC-PC-13-3-0/m04 (penalizing "fy" let "quarter" win, but "fy" was the correct
# anchor that grounded the value).
_ANCHOR_ABBREVIATIONS = {
    "op",
    "gl",
    "gm",
    "mo",
    "je",
    "tb",
    "pl",
    "aov",
    "roas",
    "ltv",
    "svb",
    "src",
    "ye",
}


def extract_anchors(description: str, fact: dict) -> tuple[str | None, list[str]]:
    """Extract the fact's primary anchor (immediate unit/label) and secondary anchors
    (nearby content words) from the criterion description, using the fact's recorded
    match position. Returns (primary, secondary), both lowercased. primary may be None
    if no adjacent content word exists. The anchor list used by the grounding check is
    ([primary] if primary else []) + secondary."""
    desc = description or ""
    start = fact.get("match_start")
    end = fact.get("match_end")
    if start is None or end is None:
        # Fallback: re-search for the token (less reliable if token repeats in the
        # criterion text, which is exactly why extract_facts now records positions).
        pattern = r"(?<![A-Za-z0-9])" + re.escape(fact["token"]) + r"(?![A-Za-z0-9])"
        m = re.search(pattern, desc, re.IGNORECASE)
        if not m:
            return None, []
        start, end = m.start(), m.end()

    # Primary anchor: scored multi-candidate selection, not "nearest non-stopword word,
    # stop." Real regression found by turing-context-e5 verifying the original nearest-word
    # version at corpus scale (1,404 new false unreachable findings across 327 tasks, before
    # this session's own boilerplate fix): the word immediately adjacent to a fact is
    # frequently a GENERIC DESCRIPTOR of the value's role ("value", "statement", "closed"
    # from a trailing "(closed books)" qualifier) or a verb ("invested"), not the sentence's
    # real semantic subject -- which this corpus's own authoring convention usually states as
    # a specific noun or named entity 1-3 words further away (e.g. "Drift cash invested
    # Expected: 2117647.0" -- the real anchor is "Drift", not "invested"; confirmed by e5
    # pulling the real environment text). Collect every non-stopword candidate within a wider
    # window on BOTH sides, score each by distance (closer wins ties, in word-count not
    # characters) with a penalty for generic descriptors and a bonus for capitalization (a
    # real, if imperfect, proper-noun/named-entity signal in this corpus -- confirmed on
    # "Drift", and coincides with sentence-initial real subjects like "Cash tie-out check..."
    # too), then take the single best-scoring candidate.
    ANCHOR_CANDIDATE_WINDOW = 80  # chars, each side -- wider than the old 40 so a real
    # anchor sitting a few words further back than a generic descriptor is even a candidate.
    # c4a (2026-09-15): per-fact after-window clipping in multi-fact criteria. When the
    # description contains 2+ numeric tokens, the 80-char after-window can extend into a
    # NEIGHBORING fact's clause, letting a word from that clause win on proximity. Clip
    # at the next numeric token's start so only THIS fact's own adjacent words are
    # candidates. Confirmed on: SVC-PC-13-3-0/m01 ("new" from "6,000 new customers" in the
    # next fact's clause beat "cac"), SVC-PC-93-0-0/r22 ("pioneer" from "Pioneer Counsel
    # LLP" after the next fact $783,695 beat "inventory"), SVC-PC-7-6-0/c13 ("mo" from
    # "0.6 mo" after the next numeric token 5.9 beat "cac"). The before-window is NOT
    # clipped: the sentence subject often sits at the start, before any numeric token
    # (e.g. SVC-PC-80-7-0/a2 "revenue" is before "4000"), and clipping it regressed that
    # case in a prior attempt.
    _value_matches = list(VALUE_TOKEN_RE.finditer(desc))
    after_end = end + ANCHOR_CANDIDATE_WINDOW
    if len(_value_matches) >= 2:
        for vm in _value_matches:
            if vm.start() >= end:
                after_end = min(after_end, vm.start())
                break
    after_text = _ANCHOR_BOILERPLATE_RE.sub(" ", desc[end:after_end])
    before_text = _ANCHOR_BOILERPLATE_RE.sub(
        " ", desc[max(0, start - ANCHOR_CANDIDATE_WINDOW) : start]
    )
    candidates: list[tuple[float, str]] = []  # (score, lowercased word); highest wins
    for side_text, reverse in ((after_text, False), (before_text, True)):
        words = re.findall(r"[A-Za-z]{2,}", side_text)
        if reverse:
            words = list(
                reversed(words)
            )  # nearest-to-fact first, same order as after_text
        for word_distance, w in enumerate(words):
            wl = w.lower()
            if wl in _ANCHOR_STOPWORDS:
                continue
            score = -float(
                word_distance
            )  # closer wins ties, generic/capital can outweigh it
            if wl in _ANCHOR_GENERIC_DESCRIPTORS:
                score -= 100.0
            # Past-participle-shaped penalty (structural, not a word list): corpus-scale
            # cluster testing found this corpus's authoring convention repeatedly puts a
            # sourcing/citation VERB directly before "Expected:" ("...revenue referenced
            # Expected: $614,400", "...formula errors Expected:" with "reconciled" nearby,
            # etc) -- the explicit _ANCHOR_GENERIC_DESCRIPTORS list already caught several
            # specific instances (closed, invested, reported...) but a targeted 29-task
            # cluster test (the exact recurring-figure family e5 flagged as the corpus-scale
            # regression's driver) surfaced "referenced" as the single most common still-
            # missed case, confirming this is a general PATTERN (past-participle verb as
            # false anchor), not a fixed vocabulary a list can keep up with. Any candidate
            # ending "-ed" (4+ letters, so real short words aren't caught by accident) gets
            # the same penalty as the explicit list, on the same "downweight, don't exclude"
            # principle -- a genuine noun that happens to end in "-ed" can still win if
            # nothing better exists in the window.
            if (
                len(wl) >= 4
                and (wl.endswith("ed") or wl.endswith("ing"))
                and wl not in _ANCHOR_GENERIC_DESCRIPTORS
            ):
                score -= 100.0
            # STRICT title-case bonus (first letter upper, EVERY other letter lower) -- a
            # real proper-noun signal ("Drift", "Cash", "Shopify"). Deliberately excludes
            # both ALL-CAPS acronyms (GL, SVB, GMV, FY) and internally-capitalized
            # acronym/product-name shapes ("SoR", "QuickBooks") -- neither is reliably the
            # sentence's real subject, confirmed by direct real-environment cross-check: the
            # SAME $2,186,512 fact grounds correctly via "cash" on one criterion (d8) but
            # failed via "sor" on a near-duplicate criterion (a10) before this narrowing,
            # because "Cash"/"SoR" scored a near-tie and the acronym edged it out on distance
            # alone. An unconditional `not w.isupper()` check let "SoR"/"QuickBooks" through
            # (internal capitals don't make a word ALL-caps) and both out-scored the real
            # anchor in hand-testing.
            #
            # Bonus tuning history, real regression found by turing-context-09 (ef) diagnosing
            # this exact scoring redesign at corpus scale (7 tasks, 11 false positives, one
            # root cause every time): a flat +50 bonus dwarfed the whole realistic 5-15-word
            # clause-length range, so a sentence-initial capitalized VERB ("States", "Carries",
            # "Uses", "Totalling" -- capitalized only because a sentence starts there, not
            # because it's a real proper noun) beat the true semantic anchor every time ef
            # checked real text. Dropping the bonus to a small flat value (tried: 4.0) broke
            # the opposite, equally real case: "Cash" (a genuine, correct, sentence-initial
            # NOUN anchor, e5's own confirmed case) sits just as far from its fact as "States"
            # does from its own, so any single flat magnitude either lets both classes of
            # far-sentence-initial word win, or lets neither - "Cash" and "States" are
            # positionally identical, the real difference is part of speech, not position or
            # distance. Fixed by excluding VERB-SHAPED candidates from the bonus specifically
            # (3rd-person-singular-present "-s" and gerund "-ing" endings, the shapes every one
            # of ef's 7 false positives had) rather than tuning a single number that can't
            # distinguish the two cases on its own.
            is_verb_shaped = wl.endswith("ing") or (len(wl) >= 4 and wl.endswith("s"))
            is_excluded_proper = is_verb_shaped or wl in _ANCHOR_MONTH_NAMES
            if w[:1].isupper() and w[1:].islower() and not is_excluded_proper:
                score += 20.0
            # c4 (2026-09-15): internally-capitalized word penalty. Words like
            # "QuickBooks", "SoR", "PowerPoint" have 2+ uppercase letters but are
            # not all-caps acronyms. The title-case bonus already excludes them;
            # this -10 penalty further downweights them as primary anchors because
            # they are product/system names, not the sentence's real semantic
            # subject. Confirmed on SVC-PC-80-7-0/a2: "quickbooks" at distance 3
            # beat "revenue" at distance 8 without this penalty.
            if sum(1 for c in w if c.isupper()) >= 2 and not w.isupper():
                score -= 10.0
            # c4 (2026-09-15): before-text 3rd-person-singular verb penalty. The
            # existing -100 penalty covers -ed/-ing endings (past participles and
            # gerunds). A 3rd-person-singular verb ending in "-s" (e.g. "flags",
            # "reads") at distance 0 in the before-text can still beat the real
            # subject noun at distance 1+ in the after-text. A -2 penalty
            # (applied ONLY to before-text, not after-text, because after-text
            # -s words are usually plural-noun units like "orders") lets the
            # after-text noun win by a 1-point margin while preserving a before-
            # text plural noun at distance 0 over a non-verb at distance 3+
            # (confirmed: SVC-PC-2-4-0/b2 "orders" at -2 still beats "correct" at
            # -3). A larger penalty (-5) regressed b2 by pushing "orders" below
            # "correct". Confirmed on: SVC-PC-93-0-0/r22 ("flags" beat "inventory"),
            # SVC-PC-2-4-0/c6 ("reads" beat "orders").
            if reverse and len(wl) >= 4 and wl.endswith("s") and not wl.endswith("ing"):
                score -= 2.0
            # c4b (2026-09-15): abbreviation penalty. A short abbreviation (op, gl,
            # gm, mo) can win over a full word (orders, ledger, margin, month/CAC-
            # adjacent) on pure proximity because the abbreviation sits in the
            # unit-position right after the number. The -30 penalty overcomes a
            # ~6-word distance gap, letting the full word win. See
            # _ANCHOR_ABBREVIATIONS docstring for confirmed cases and exclusions
            # (cac excluded: it IS the correct anchor on SVC-PC-7-6-0/c13; fy
            # excluded: caused regression on SVC-PC-13-3-0/m04).
            if wl in _ANCHOR_ABBREVIATIONS:
                score -= 30.0
            candidates.append((score, wl))
    primary = max(candidates, key=lambda c: c[0])[1] if candidates else None

    # Secondary anchors: content words within a wider window of the fact token.
    # These provide a fallback when the primary anchor is not extractable, and
    # additional signal when it is. Excludes stopwords, the fact's own token, and
    # duplicates of the primary anchor.
    window_start = max(0, start - ANCHOR_TEXT_WINDOW)
    window_end = min(len(desc), end + ANCHOR_TEXT_WINDOW)
    segment = _ANCHOR_BOILERPLATE_RE.sub(" ", desc[window_start:window_end])
    secondary: list[str] = []
    seen: set[str] = set()
    token_lower = fact["token"].lower()
    for w in re.findall(r"[A-Za-z]{3,}", segment):
        wl = w.lower()
        if wl in _ANCHOR_STOPWORDS or wl == token_lower or wl in seen:
            continue
        seen.add(wl)
        secondary.append(wl)
    if primary and primary in secondary:
        secondary.remove(primary)

    return primary, secondary


def _anchor_word_match(context: str, anchors: list[str]) -> bool:
    """Word-boundary anchor check (round 6 follow-up, 2026-09-15): a raw `a in context`
    substring test let a short anchor like "night" match inside an unrelated word like
    "knight" -- confirmed as a real, live false-positive on SVC-PC-14-4-0/c17's own
    environment (a customer named "Victoria Knight" grounded the "30-night" fact's "night"
    anchor against an unrelated order row's "30"). Same alnum-boundary discipline
    `_word_match` already uses elsewhere in this file, applied here too."""
    for a in anchors:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", context):
            return True
    return False


def _context_anchored_text_match(
    blob: str, token: str, anchors: list[str], window: int = PROXIMITY_WINDOW
) -> bool:
    """Find every occurrence of the fact's exact text token in the blob. Require at
    least one anchor to appear within `window` characters of at least one occurrence.
    Replaces the context-blind _word_match for numeric facts: a bare "30" in an
    unrelated "swiftship ~30%" context no longer grounds a "30-night window" fact
    because "night" does not appear in that occurrence's context window."""
    if not token or not anchors:
        return False
    pattern = r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])"
    for m in re.finditer(pattern, blob):
        ctx_start = max(0, m.start() - window)
        ctx_end = min(len(blob), m.end() + window)
        context = blob[ctx_start:ctx_end]
        if _anchor_word_match(context, anchors):
            return True
    return False


def _context_anchored_numeric_match(
    numeric: float | None,
    numeric_occurrences: list[tuple[float, str]],
    anchors: list[str],
    tolerance: float = NUMERIC_TOLERANCE,
) -> bool:
    """Find the fact's numeric value among the environment's numeric occurrences
    (spreadsheet cells with per-cell context, text-extracted numbers with
    surrounding-text context). Require at least one anchor in the matching
    occurrence's context. Replaces the context-blind
    `any(abs(n - f) < tol for f in floats)` check: a 30.0 from a "fulfillment_rates"
    sheet no longer grounds a "30-night window" fact because "night" does not appear
    in that cell's context string."""
    if numeric is None or not anchors:
        return False
    for value, context in numeric_occurrences:
        if abs(numeric - value) < tolerance:
            if _anchor_word_match(context, anchors):
                return True
    return False


# ---------------------------------------------------------------------------
# environment scanning -- reuses answer_key_content_leak_check.py's exact xlsx/docx approach;
# this script's own addition is the .pdf branch (no existing check in this folder reads PDF
# text -- see deliverable_integrity_check.py's own docstring, which deliberately did not add a
# PDF parser). Cached by content sha256 across the whole process run: this corpus's real shape
# (a shared "Company Shared Drive" subtree resampled per task) means the same file recurs across
# many task directories, and a full corpus sweep would otherwise reopen it once per task.
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xlsx",
    ".xlsm",
    ".docx",
    ".pdf",
    # mechanism 1: only the MIME/MHTML shape is actually read (see read_doc_mime_text) -- a
    # real legacy binary .doc still contributes nothing, same as before this round.
    ".doc",
}

_file_cache: dict[str, tuple] = {}


def read_docx_text(path: Path) -> str:
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
    try:
        with zipfile.ZipFile(path) as zf:
            if "word/document.xml" not in zf.namelist():
                return ""
            xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
            return " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
    except Exception:
        return ""


def read_pdf_text(path: Path) -> str:
    if not HAVE_PYPDF:
        return ""
    try:
        reader = pypdf.PdfReader(str(path))
        return "\n".join((pg.extract_text() or "") for pg in reader.pages)
    except Exception:
        return ""


# --- mechanism 1 (2026-09-15 triage round): '.doc' MIME/MHTML decoding ---------------------
# A '.doc' file on this corpus is one of two unrelated formats sharing an extension: a real
# legacy binary Word document (OLE compound file, magic bytes D0CF11E0A1B11AE1) this script
# does not read (disclosed not-covered, same as .xls/.pptx -- no parser added for either), or
# -- confirmed by hand on SVC-PC-24-4-0's/SVC-PC-26-4-0's real corpus files -- a MIME/MHTML
# export ("Save as Web Page, Filtered" saved with a .doc extension): a "MIME-Version:"/
# "Content-Type: multipart/related" header wrapping a quoted-printable-encoded HTML part.
# Before this round, ".doc" was entirely absent from SUPPORTED_EXTENSIONS, so every fact in
# one of these files was invisible to this check regardless of anchors or compute-indicators --
# not a false negative in the matching logic, a file the scanner never opened at all. Triage
# found ~20 of one 31-task shard's tasks sharing 15 such files carrying real dollar/plan
# figures (e.g. SVC-PC-24-4-0's "$4.5M base case 36,000 orders @ $125 AOV").
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _looks_like_mime_doc(head: bytes) -> bool:
    """head is the file's first ~512 bytes. A real OLE-compound-file .doc starts with the
    fixed magic bytes above -- reject those outright (disclosed not-covered) rather than
    attempt to parse them as MIME and silently return nothing anyway."""
    if head.startswith(_OLE_MAGIC):
        return False
    return b"MIME-Version:" in head or b"Content-Type: multipart" in head


def _looks_like_bare_html_doc(head: bytes) -> bool:
    """A second, unrelated '.doc' shape found scanning a real 400-file sample of this
    corpus's .doc files after the MIME fix above (~7% of the sample, 27/401, zero real OLE
    binaries in the same sample): Word's OTHER "save as web page" export, WITHOUT the MIME/
    MHTML envelope -- the file starts directly with '<html' (plain UTF-8, no quoted-
    printable escaping, confirmed by hand: no '=3D' or '=\\r\\n' soft-break artifacts
    anywhere in a sampled file). `_looks_like_mime_doc` correctly returns False for these
    (no MIME-Version/multipart header), which would otherwise leave them silently unread
    exactly like before mechanism 1 existed at all."""
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    return stripped[:15].lower().startswith((b"<html", b"<!doctype"))


def read_doc_mime_text(path: Path) -> str:
    """Read a MIME/MHTML-encoded '.doc' file's text. Returns "" for a real legacy binary
    .doc, a file that fails the MIME signature check, or on any parse failure -- never
    raises, matching every other reader in this file.

    Uses only the standard library (email + quopri + html, all always available, no
    optional-import guard needed): `email.message_from_bytes` walks the MIME multipart
    structure and decodes each part's own Content-Transfer-Encoding, so this script does not
    hand-roll multipart boundary or quoted-printable soft-line-break parsing. That parsing is
    not an optional cleanup step: quoted-printable's 76-column soft line break ("=\\r\\n") can
    split a token's digits across a line boundary, so a raw byte-level search for a figure
    known to be in one of these files (confirmed by hand on SVC-PC-24-4-0's "36,000 orders")
    finds nothing at all pre-decode.

    The HTML part (Word's own simplified HTML export) is reduced to plain text with a bare
    tag-strip + entity-unescape, the same fidelity bar read_docx_text's own zipfile fallback
    uses -- this only needs to expose numbers/text to VALUE_TOKEN_RE, not render the document.

    Handles a second, unrelated '.doc' shape too (see `_looks_like_bare_html_doc`): a bare
    HTML export with no MIME envelope at all, read directly as UTF-8 text with no
    quoted-printable step.
    """
    try:
        raw = path.read_bytes()
    except Exception:
        return ""
    head = raw[:512]
    if _looks_like_bare_html_doc(head):
        try:
            combined = raw.decode("utf-8", errors="replace")
            combined = re.sub(
                r"<(script|style)[^>]*>.*?</\1>", " ", combined, flags=re.I | re.S
            )
            return _html.unescape(re.sub(r"<[^>]+>", " ", combined))
        except Exception:
            return ""
    if not _looks_like_mime_doc(head):
        return ""
    combined = ""
    try:
        msg = email.message_from_bytes(raw)
        parts = msg.walk() if msg.is_multipart() else [msg]
        html_chunks = []
        for part in parts:
            if part.get_content_maintype() == "multipart":
                continue
            ctype = (part.get_content_type() or "").lower()
            if ctype not in ("text/html", "text/plain"):
                continue
            payload = part.get_payload(decode=True)  # honors Content-Transfer-Encoding
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                html_chunks.append(payload.decode(charset, errors="replace"))
            except Exception:
                html_chunks.append(payload.decode("utf-8", errors="replace"))
        combined = "\n".join(html_chunks)
    except Exception:
        combined = ""
    if not combined:
        # Not real multipart/email-parseable (e.g. a bare quoted-printable body with no
        # proper MIME boundary), but the same soft-line-break issue still applies -- decode
        # the whole body as quoted-printable text directly rather than giving up.
        try:
            combined = quopri.decodestring(raw).decode("utf-8", errors="replace")
        except Exception:
            return ""
    try:
        combined = re.sub(
            r"<(script|style)[^>]*>.*?</\1>", " ", combined, flags=re.I | re.S
        )
        text = re.sub(r"<[^>]+>", " ", combined)
        return _html.unescape(text)
    except Exception:
        return ""


def _scan_one_file(path: Path):
    """Returns (cell_numeric_occurrences: list[(float, str)], text_lower: str). Never raises
    -- an unreadable file contributes nothing rather than crashing the task.

    cell_numeric_occurrences is populated only for .xlsx/.xlsm numeric cells, each carrying
    a per-cell context string (sheet name + column header + row labels). Text-extracted numbers
    are NOT included here -- they are extracted from the concatenated blob in environment_signals()
    where the full surrounding-text context is available."""
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return [], ""
    cached = _file_cache.get(digest)
    if cached is not None:
        return cached

    suffix = path.suffix.lower()
    cell_occs: list[tuple[float, str]] = []
    text = ""
    try:
        if suffix in (".txt", ".md", ".csv", ".json"):
            text = path.read_text(encoding="utf-8", errors="replace")
        elif suffix in (".xlsx", ".xlsm"):
            workbook = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
            text_parts: list[str] = []
            for worksheet in workbook.worksheets:
                sheet_name = (worksheet.title or "").lower()
                rows = list(worksheet.iter_rows(values_only=True))
                headers: list[str] = []
                if rows:
                    headers = [str(c).lower() if c is not None else "" for c in rows[0]]
                for row in rows:
                    row_labels = [str(c) for c in row if isinstance(c, str)]
                    row_label_text = " ".join(row_labels).lower()
                    for col_idx, value in enumerate(row):
                        if value is None or isinstance(value, bool):
                            continue
                        if isinstance(value, (int, float)):
                            f = round(float(value), 2)
                            header = headers[col_idx] if col_idx < len(headers) else ""
                            context = f"{sheet_name} {header} {row_label_text}"
                            cell_occs.append((f, context))
                        elif isinstance(value, str):
                            text_parts.append(value)
            workbook.close()
            text = "\n".join(text_parts)
        elif suffix == ".docx":
            text = read_docx_text(path)
        elif suffix == ".pdf":
            text = read_pdf_text(path)
        elif suffix == ".doc":
            text = read_doc_mime_text(path)
    except Exception:
        pass

    result = (cell_occs, text.lower() if text else "")
    _file_cache[digest] = result
    return result


def environment_signals(task_dir: Path, ekw: bool):
    """One pass over this task's whole environment. Returns (numeric_occurrences, blob,
    basenames, instruction_text).

    numeric_occurrences: list of (rounded_float, context_str) from two sources:
      1. Spreadsheet numeric cells: per-cell context (sheet name + column header + row labels).
      2. Text-extracted numbers: surrounding-text window from the concatenated blob. Handles
         formatting-different matches (e.g., "$1,204,900" in a criterion vs "1204900" in a .csv).
    blob: lowercased text concatenation of every readable file's text (for text-anchored match
    and for the non-numeric filename/named_entity/quoted/date branches, which still use _word_match).
    basenames: lowercased filename set (so a filename fact can be checked for existence even if
    this script can't read that file's own content, e.g. a .xlsm golden reference or an image).
    instruction_text: raw (NOT lowercased, NOT mixed into blob) text of this task's own
    instruction.md, or "" if absent or ekw=True. Kept separate from blob so a same-task-scoped
    anchor-to-compute-indicator proximity check (see _instruction_context_reads_as_computed)
    can search within instruction.md's own bounds only, not across a scrambled concatenation of
    every environment file. c1's existing blob-inclusion (below) already lets a fact's VALUE
    match textually against instruction.md; this is a second, independent use of the same text
    for a different question (does instruction.md explain that this task's numeric facts are
    computed, not does the specific value appear in instruction.md).
    """
    env_dir = task_dir / "environment" / ("data" if ekw else "initial_workspace")
    cell_occs_all: list[tuple[float, str]] = []
    text_occs: list[tuple[float, str]] = []
    blob_parts: list[str] = []
    basenames: set[str] = set()
    if env_dir.is_dir():
        for p in env_dir.rglob("*"):
            if not p.is_file():
                continue
            basenames.add(p.name.lower())
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            cell_occs, text = _scan_one_file(p)
            cell_occs_all.extend(cell_occs)
            if text:
                blob_parts.append(text)
                # c5: text-numeric occurrences are extracted per-file (not from the global
                # blob) so the context window stays within this file's own bounds and
                # cannot cross file boundaries. The file's stem tokens (lowercased,
                # underscores/hyphens -> spaces) are prepended to every occurrence's
                # context so the filename is always an available anchor source, bridging
                # a document title far from a table/figure in the same file.
                stem_ctx = p.stem.replace("_", " ").replace("-", " ").lower()
                for m in VALUE_TOKEN_RE.finditer(text):
                    if m.lastgroup in NUMERIC_KINDS:
                        parsed = to_float(m.group(0))
                        if parsed is not None:
                            # c9 (this round): accounting-negative notation in plain prose/
                            # table text, e.g. "(423,359)" with no leading "$". Only the
                            # currency group's own VALUE_TOKEN_RE pattern includes the
                            # parens in its match (to_float's paren-prefix check then
                            # negates it); bare_number/comma_number/decimal_number match
                            # just the digits, so a text-embedded "(4,282)" silently loses
                            # its sign here even though the identical "$(4,282)" would not.
                            # Real gap in the same family as the scale-suffix fix below,
                            # not a hypothetical: this corpus's own accounting exports use
                            # bare parenthesized negatives outside literal dollar figures
                            # (a unit/FTE/count column shown negative for a decrease).
                            if (
                                m.lastgroup != "currency"
                                and m.start() > 0
                                and text[m.start() - 1] == "("
                                and m.end() < len(text)
                                and text[m.end()] == ")"
                            ):
                                parsed = -abs(parsed)
                            ctx_start = max(0, m.start() - PROXIMITY_WINDOW)
                            ctx_end = min(len(text), m.end() + PROXIMITY_WINDOW)
                            text_occs.append(
                                (
                                    round(parsed, 2),
                                    f"{stem_ctx} {text[ctx_start:ctx_end]}",
                                )
                            )

    # c1: also scan instruction.md and task.toml for SVC-PC. A fact the prompt
    # states verbatim (the solver reads the prompt) is grounded even if absent
    # from environment/initial_workspace/. Per the adversarial review, this alone
    # does NOT clear every case: the anchor still has to land within
    # PROXIMITY_WINDOW of the value in instruction.md's text (that logic lives in
    # extract_anchors(), not here). EKW already scans environment/data/ which
    # contains its prompt-adjacent files. Only the text blob is extended (not
    # basenames), so a filename fact is still checked against environment files
    # only, not against instruction.md/task.toml as pseudo-environment files.
    # Runs even when env_dir is absent (some task packages ship judge.toml +
    # instruction.md but no environment/, e.g. the 56/71 corpora).
    instruction_text = ""
    if not ekw:
        for fname in ("instruction.md", "task.toml"):
            p = task_dir / fname
            if p.is_file():
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                    if text:
                        blob_parts.append(text.lower())
                        if fname == "instruction.md":
                            instruction_text = text
                except Exception:
                    pass
    blob = "\n".join(blob_parts)

    numeric_occurrences = cell_occs_all + text_occs
    return numeric_occurrences, blob, basenames, instruction_text


# ---------------------------------------------------------------------------
# classification: unreachable_criterion (hard) vs. possible_unreachable (low-confidence) vs. clean
# ---------------------------------------------------------------------------


def _context_downgrade_reason(fact: dict) -> str | None:
    """c3/c7: return a possible_unreachable reason if this fact sits in a context
    that makes hard-flagging a false failure, else None.

    c3 exclusion_context: the fact was pulled from an exclusion assertion ("not
    $X", "NOT $X", "Bans 'X'", "e.g., 'X' is scored 0", "'X' is scored 0") -- a
    value to exclude, not a positive fact to find. Set in extract_facts() for
    numeric/quoted/date/id_code kinds (filename and named_entity have their own
    handling and are never marked).

    c7 prescriptive_context: the fact is a quoted string the solver should WRITE
    (output-direction), preceded by a prescriptive verb ("honest", "segregated",
    "labeled", "called", "relies on") or a comma-list continuation of one. Set in
    extract_facts() for quoted kind only.

    Both downgrade to possible_unreachable (non-blocking), never skip, so a
    misdetected context is still surfaced rather than silently dropped -- the
    file's conservative severity model (see module docstring's Known limits).
    Applied only at the not-found hard-return points in classify_fact, so a fact
    that IS found in the environment still returns clean (no false failure to
    fix)."""
    excl = fact.get("exclusion_context")
    presc = fact.get("prescriptive_context")
    if not (excl or presc):
        return None
    tags = []
    if excl:
        tags.append("exclusion")
    if presc:
        tags.append("prescriptive")
    return (
        f"{fact['token']!r} not found, but sits in a {'/'.join(tags)} context "
        "(a value to exclude or a phrase the solver should WRITE, not a "
        "positive source fact to find) -- downgraded, not hard-flagged"
    )


def classify_fact(
    fact: dict,
    description: str,
    numeric_occurrences: list[tuple[float, str]],
    blob: str,
    basenames: set,
    deliverable_basenames: set,
    instruction_text: str = "",
):
    """Returns (bucket, reason) where bucket is 'clean', 'unreachable_criterion', or
    'possible_unreachable'. See module docstring's Classification section for the design.

    Non-numeric branches (filename, named_entity, quoted, date) use _word_match against the
    blob unchanged -- the context-anchored matching applies only to numeric kinds, where the
    two context-blind suppression paths (word_match and the flat floats set) were diagnosed.
    """
    kind = fact["kind"]
    token = fact["token"]

    if kind == "filename":
        base = token.strip().lower()
        # c1-self-reference extension (2026-09-15 triage round): "instruction.md"/
        # "task.toml" are always present at the task's own ROOT (c1's existing
        # environment_signals() scan already treats their CONTENT as grounding text for
        # OTHER facts), but the root itself is never part of `basenames` (which only walks
        # environment/initial_workspace/) -- so a criterion whose flagged token IS literally
        # "instruction.md" (self-referencing the task's own prompt file, e.g.
        # "instruction.md poses this only as an open question") was hard-flagged as a
        # missing filename every time, since neither existing check (`base in basenames`,
        # or the file's own content mentioning its own filename by name, which essentially
        # never happens) could ever pass. Confirmed on SVC-PC-12-7-0/r023,
        # SVC-PC-12-8-0/r019+r020, SVC-PC-26-2-0/rb-02.
        if base in ("instruction.md", "task.toml"):
            return "clean", None
        # A filename naming the criterion's OWN graded deliverable (judge.toml's [judge].files=
        # for SVC-PC, a verifier's own "files" for EKW) is an OUTPUT the solver must produce, not
        # a source fact to find in the environment -- checking it against the corpus is the wrong
        # question entirely (deliverable_filename_check.py already covers whether the deliverable
        # name is consistent with instruction.md). Confirmed as a real false-positive class by
        # hand: SVC-PC-88-0-0's str-01/02/03 name exactly the three files that judge.toml's own
        # files= list declares as this task's graded output.
        if base in deliverable_basenames:
            return "clean", None
        if (
            base in basenames
            or _word_match(blob, base)
            or _quarter_range_satisfied(base, basenames)
        ):
            return "clean", None
        down = _broad_exclusion_context(description, fact)
        if down:
            return "possible_unreachable", down
        return "unreachable_criterion", (
            f"filename '{token}' does not exist anywhere under this task's environment and is "
            "not mentioned as text in any environment file"
        )

    if kind == "named_entity":
        parts = [p.strip() for p in re.split(r"\s*/\s*", token) if p.strip()]
        if any(_word_match(blob, p.lower()) for p in parts):
            return "clean", None
        down = _broad_exclusion_context(description, fact)
        if down:
            return "possible_unreachable", down
        return "unreachable_criterion", (
            f"named entity '{token}' has no textual match anywhere in this task's environment"
        )

    if kind == "quoted":
        inner = token[1:-1].lower()
        # c14: 'Q1-Q4'-shaped quarter-range shorthand quoted directly, e.g. "notes the
        # single-named 'Q1-Q4' input maps to 4 quarterly files" -- see
        # _quarter_range_satisfied's own docstring. Confirmed on SVC-PC-91-3-0/r1.
        if _word_match(blob, inner) or _quarter_range_satisfied(inner, basenames):
            return "clean", None
        # c3/c7: an exclusion-context ("not 'X'", "Bans 'X'", "e.g., 'X' is
        # scored 0") or prescriptive-context ("honest 'X' why-now", "segregated
        # 'X'", "relies on 'X'") quoted string is a false failure if hard-
        # flagged. Checked before the EKW/computed downgrade so the c3/c7
        # reason is reported when applicable. c13: the narrower c3/c7 check is
        # tried first (more specific reason text); the broader marker scan below only
        # runs if c3/c7 found nothing, and can only add a downgrade, never remove one.
        down = _context_downgrade_reason(fact) or _broad_exclusion_context(
            description, fact
        )
        if down:
            return "possible_unreachable", down
        # EKW-only: quoted-kind is possible-only, never hard. Confirmed at corpus scale (274-task
        # sweep): SVC-PC's "Expected:" clause isolates a stated fact, so a quoted phrase there
        # ("Expected: 'Alice Chen, CEO'") genuinely is one; EKW has no such clause and this
        # script scans the WHOLE rubric prompt instead (see extract_facts), where a quoted phrase
        # routinely reads as the rubric's own argumentative/conceptual language, not a source
        # fact -- e.g. "'increased opportunity for fraud/collusion'" (a legal-analysis concept
        # the response should discuss) and "'(Mem. at X)'" (a citation-format PLACEHOLDER, X
        # literally a variable, not a page number). Hard-gating this on the real EKW corpus
        # produced a 232/274 FAIL rate driven mostly by this one kind (653 of 1521 unreachable
        # rows) -- not a credible defect rate, a detector miscalibration.
        if fact.get("ekw") or _reads_as_computed(description):
            return "possible_unreachable", (
                f"quoted text {token} not found"
                + (
                    ", but description reads as computed/derived"
                    if not fact.get("ekw")
                    else " -- EKW quoted-kind is possible-only by design (whole-prompt scan, "
                    "no Expected: clause to isolate a stated fact from argumentative prose)"
                )
                + " -- not hard-flagged"
            )
        return "unreachable_criterion", (
            f"quoted text {token} does not appear anywhere in this task's environment"
        )

    if kind in DATE_KINDS:
        if _date_match(blob, token.lower()):
            return "clean", None
        # c3: an exclusion-context date ("not <date>", "Bans <date>") is a false
        # failure if hard-flagged; downgrade before the EKW/computed path. c13: broader
        # marker scan added as a second, additive attempt (see quoted branch above).
        down = _context_downgrade_reason(fact) or _broad_exclusion_context(
            description, fact
        )
        if down:
            return "possible_unreachable", down
        # Same EKW-only downgrade as quoted, same reason, same corpus-scale evidence: EKW's
        # whole-prompt scan surfaces narrative/contextual dates ("as of the filing date...")
        # that are not source-corpus facts to verify, at a volume (227 of 1521 unreachable rows
        # in the same sweep) that makes hard-gating them a miscalibration, not a real signal.
        if fact.get("ekw") or _reads_as_computed(description):
            return "possible_unreachable", (
                f"date '{token}' not found"
                + (
                    ", but description reads as computed/derived"
                    if not fact.get("ekw")
                    else " -- EKW date-kind is possible-only by design (same rationale as quoted)"
                )
                + " -- not hard-flagged"
            )
        return "unreachable_criterion", (
            f"date '{token}' does not appear anywhere in this task's environment"
        )

    # --- numeric branches: context-anchored proximity matching ---
    # Both suppression paths (word_match's context-blind substring match and the flat
    # floats set's context-blind numeric-equivalence) are replaced here. A numeric fact is
    # "grounded" only if its value appears near at least one anchor extracted from the
    # criterion text. See design-proposals/criterion-groundedness-fix-2026-09-15.md.

    primary, secondary = extract_anchors(description, fact)

    if not primary and not secondary:
        # No context available in the criterion text. Fallback policy (design section 2.3):
        # HARD_NUMERIC_KINDS fall back to context-blind matching (status quo, no regression
        # on hard-gating facts). bare_number/percent/id_code return possible_unreachable
        # (safe, these kinds never hard-gate, and the detector cannot confirm grounding
        # without context -- strictly better than marking clean on any numeric coincidence).
        if kind in HARD_NUMERIC_KINDS and fact["numeric"] is not None:
            matched = any(
                abs(fact["numeric"] - v) < NUMERIC_TOLERANCE
                for v, _ in numeric_occurrences
            ) or _word_match(blob, token.lower())
            if matched:
                return "clean", None
            # c3: exclusion-context numeric fact (no anchors, not found) -> downgrade.
            # c13: broader marker scan added as a second, additive attempt.
            down = _context_downgrade_reason(fact) or _broad_exclusion_context(
                description, fact
            )
            if down:
                return "possible_unreachable", down
            if _reads_as_computed(description) or _value_shape_reads_as_computed(fact):
                return "possible_unreachable", (
                    f"'{token}' not found in environment, but the description reads as a "
                    "computed/derived figure (compute-indicator, own-deliverable cell-"
                    "reference, or a 3+-decimal-place value shape matched) -- not "
                    "hard-flagged"
                )
            # EKW numeric downgrade (round 14, 2026-09-15): same rationale as the quoted/
            # date EKW downgrade below -- EKW has no "Expected:" clause and this script
            # scans the WHOLE rubric prompt, where a numeric value routinely reads as a
            # check bound, tolerance band, or golden example, not a source fact. Hard-
            # gating these on the real EKW corpus produced a 143/274 hard-fail rate (the
            # task doc's full-corpus result), a miscalibration not a defect rate. See the
            # quoted-kind comment above for the full corpus-scale evidence.
            if fact.get("ekw"):
                return "possible_unreachable", (
                    f"'{token}' not found in environment (no context anchors available, "
                    "context-blind fallback used) -- EKW numeric-kind is possible-only by "
                    "design (whole-prompt scan, no Expected: clause to isolate a stated "
                    "fact from check bounds/tolerances/golden examples) -- not hard-flagged"
                )
            return "unreachable_criterion", (
                f"'{token}' does not appear anywhere in this task's environment "
                "(no context anchors available, context-blind fallback used), and the "
                "description does not read as a computed/derived value"
            )
        # bare_number, percent, id_code: possible-only.
        return "possible_unreachable", (
            f"'{token}' ({kind}) has no extractable context anchors in the criterion "
            "text, cannot verify grounding -- kept low-confidence"
        )

    # Option 1 (round 6, 2026-09-15): when a primary anchor was extracted, require IT
    # specifically to ground the fact; secondary anchors are only used as a fallback when
    # no primary was extractable at all. The primary anchor (the fact's immediate
    # unit/label, e.g. "night" for "30-night") is the single most discriminating anchor
    # because a different "30" (like "30%" or "30 days") has a different unit. The previous
    # code built `anchors = ([primary] if primary else []) + secondary` and matched via
    # `any(a in context for a in anchors)`, weighting all ~22 anchors equally. On a real
    # corpus this was too permissive: a generic secondary anchor ("return", "policy",
    # "day", "revenue") near an UNRELATED corpus occurrence of the value grounded the
    # fact even when the specific context ("30-night") was absent. Confirmed on
    # SVC-PC-14-4-0/c17's three bare_number facts (100, 14, 30): each has a specific
    # primary anchor ("night"/"day") but ~21 generic secondary anchors, and the value
    # coincidentally appears near generic business words elsewhere in the environment.
    # Requiring the primary anchor eliminates this class of false grounding without
    # losing the no-primary fallback (which preserves behavior for facts whose
    # description gives no adjacent content word). See
    # NEW-TASK-2026-09-15-round6.md for the full option comparison.
    anchors = [primary] if primary else secondary

    # Context-anchored matching: both paths require anchor co-occurrence. Neither can
    # short-circuit the other into a context-blind "clean" verdict (the half-fixed failure
    # mode the task doc warns about). If numeric_grounded is False, text_grounded is still
    # checked independently.
    text_grounded = _context_anchored_text_match(blob, token.lower(), anchors)
    numeric_grounded = _context_anchored_numeric_match(
        fact.get("numeric"), numeric_occurrences, anchors
    )
    matched = text_grounded or numeric_grounded

    if matched:
        return "clean", None

    # Not grounded by either path. Route to the appropriate bucket.
    if kind in HARD_NUMERIC_KINDS:
        # c3: exclusion-context numeric fact (not found, has anchors) -> downgrade.
        # c13: broader marker scan added as a second, additive attempt.
        down = _context_downgrade_reason(fact) or _broad_exclusion_context(
            description, fact
        )
        if down:
            return "possible_unreachable", down
        if (
            _reads_as_computed(description)
            or _value_shape_reads_as_computed(fact)
            or _instruction_context_reads_as_computed(instruction_text, anchors)
        ):
            return "possible_unreachable", (
                f"'{token}' not found near its unit/subject anchors {set(anchors)} in the "
                "environment, but the description reads as a computed/derived figure "
                "(compute-indicator, own-deliverable cell-reference, a 3+-decimal-place "
                "value shape, or a task-wide compute indicator near this same anchor in "
                "instruction.md matched) -- not hard-flagged"
            )
        # EKW numeric downgrade (round 14, 2026-09-15): same rationale as the quoted/date
        # EKW downgrade above and the no-anchors fallback above. EKW's whole-prompt scan
        # (no "Expected:" clause) surfaces check bounds ("between $2.00 and $3.00"),
        # tolerance bands ("differ by no more than $0.10"), and golden examples ("the
        # golden range is $21.00-$24.00") that are not source-corpus facts to verify.
        # Hard-gating these produced 143/274 hard-fail on the full EKW corpus (the task
        # doc's number), driven by a mix of anchor-quality bugs (verdict keywords like
        # "pass"/"fail" winning primary anchor, dense multi-fact prose where the nearest
        # word describes a different fact) and legitimate golden/output values that simply
        # do not appear in the environment by design. The anchor-quality bugs are
        # addressed separately (round 14 stopword expansion, verdict-keyword stopwords,
        # month-abbreviation exclusion, value-descriptor downweighting); this downgrade
        # handles the residual class where the check's "does this value appear in the
        # environment?" premise does not apply to EKW's rubric format at all. Confirmed
        # on the real 14-task EKW mirror: task_175/v5's "$21.00" is a golden filing-
        # range low (solver output, not a source fact), task_591/v7's "$46,800" IS a
        # real source fact but was false-positived by the "it" pronoun anchor (now fixed
        # by the stopword expansion). The downgrade is non-blocking (possible_unreachable)
        # so genuine defects are still surfaced for human review without inflating the
        # hard-fail rate to a miscalibrated level.
        if fact.get("ekw"):
            return "possible_unreachable", (
                f"'{token}' not found near its unit/subject anchors {set(anchors)} "
                "anywhere in this task's environment -- EKW numeric-kind is possible-only "
                "by design (whole-prompt scan, no Expected: clause to isolate a stated "
                "fact from check bounds/tolerances/golden examples) -- not hard-flagged"
            )
        return "unreachable_criterion", (
            f"'{token}' does not appear near its unit/subject anchors {set(anchors)} "
            "anywhere in this task's environment (context-anchored match), and the "
            "description does not read as a computed/derived value"
        )

    # bare_number, percent, id_code: possible-only.
    return "possible_unreachable", (
        f"'{token}' ({kind}) not found near its unit/subject anchors {set(anchors)} "
        "anywhere in this task's environment -- kept low-confidence by design"
    )


# ---------------------------------------------------------------------------
# per-task checks -- same shape as rubric_schema_check.py's check_task()/check_task_ekw()/
# check_task_dispatch()
# ---------------------------------------------------------------------------


def _base_result(task_dir: Path) -> dict:
    return {
        "task": task_dir.name,
        "criteria": 0,
        "facts_extracted": 0,
        "unreachable_criterion": [],
        "possible_unreachable": [],
        "parse_errors": [],
        "ok": False,
    }


# A single criterion stating 4+ numeric facts at once ("Jan $0; Feb $5,900; Mar $53,100; ...;
# FY $1,204,900") reads as a computed monthly/spot-value TABLE, not individual source facts --
# confirmed by hand across three unrelated task families (a monthly-revenue-from-raw-orders
# build, a 12-month cash-flow model, a "Pipeline_Forecast" tab) where every genuinely
# hand-confirmed unreachable fact (this script's own 4-task validation set) instead sits ALONE
# or with at most one or two siblings in its own criterion. A generic count-based signal, not
# another keyword to chase -- cheaper and more robust than enumerating every phrasing this
# corpus uses for "here is a computed series."
SERIES_NUMERIC_THRESHOLD = 4


def _check_one_criterion(
    res: dict,
    where: str,
    description: str,
    ekw: bool,
    numeric_occurrences,
    blob,
    basenames,
    deliverable_basenames,
    instruction_text: str = "",
):
    res["criteria"] += 1
    facts = extract_facts(description, ekw=ekw)
    res["facts_extracted"] += len(facts)
    # c18: pre-filter count (see _count_series_candidate_tokens), not len(post-filter facts) --
    # a dense short-figure clause must read as a series even when some/all of its members sit
    # below extract_facts' own min_chars floor.
    n_numeric = _count_series_candidate_tokens(description, ekw)
    is_series = n_numeric >= SERIES_NUMERIC_THRESHOLD
    for fact in facts:
        bucket, reason = classify_fact(
            fact,
            description,
            numeric_occurrences,
            blob,
            basenames,
            deliverable_basenames,
            instruction_text,
        )
        if (
            bucket == "unreachable_criterion"
            and is_series
            and fact["kind"] in NUMERIC_KINDS
        ):
            bucket = "possible_unreachable"
            reason = (
                f"{reason} -- downgraded: this criterion states {n_numeric} numeric facts at "
                "once, reading as a computed table/series rather than a single source fact"
            )
        if bucket == "clean":
            continue
        row = {
            "criterion": where,
            "token": fact["token"],
            "kind": fact["kind"],
            "reason": reason,
        }
        res[bucket].append(row)


def check_task(task_dir: Path) -> dict:
    """SVC-PC: tests/deliverables[_*]/judge.toml."""
    res = _base_result(task_dir)
    judge_files = sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )
    if not judge_files:
        res["parse_errors"].append(
            "no judge.toml under tests/deliverables/ or tests/deliverables_*/"
        )
        return res

    numeric_occurrences, blob, basenames, instruction_text = environment_signals(
        task_dir, ekw=False
    )
    deliverable_basenames = set()
    parsed = []
    for jf in judge_files:
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception as exc:
            res["parse_errors"].append(f"{jf.name}: {exc}")
            continue
        parsed.append((jf, data))
        for f in (data.get("judge") or {}).get("files") or []:
            deliverable_basenames.add(Path(str(f)).name.lower())

    for jf, data in parsed:
        for c in data.get("criterion") or []:
            name = c.get("name", "?")
            desc = (c.get("description") or "").strip()
            _check_one_criterion(
                res,
                f"{jf.parent.name}/{name}",
                desc,
                False,
                numeric_occurrences,
                blob,
                basenames,
                deliverable_basenames,
                instruction_text,
            )

    res["ok"] = not res["unreachable_criterion"] and not res["parse_errors"]
    return res


def check_task_ekw(task_dir: Path) -> dict:
    """EKW: tests/verifier.json, via ekw_verifier_json.load_ekw_criteria()."""
    res = _base_result(task_dir)
    criteria = load_ekw_criteria(task_dir)
    if not criteria:
        res["parse_errors"].append("tests/verifier.json has no verifiers")
        return res

    parse_error_entries = [c for c in criteria if c["name"] == "__parse_error__"]
    if parse_error_entries:
        for c in parse_error_entries:
            res["parse_errors"].append(c["description"])
        return res

    numeric_occurrences, blob, basenames, _instruction_text = environment_signals(
        task_dir, ekw=True
    )
    deliverable_basenames = set()
    for c in criteria:
        for f in c.get("files") or []:
            deliverable_basenames.add(Path(str(f)).name.lower())

    for c in criteria:
        where = f"{c['group']}/{c['name']}"
        desc = (c.get("description") or "").strip()
        _check_one_criterion(
            res,
            where,
            desc,
            True,
            numeric_occurrences,
            blob,
            basenames,
            deliverable_basenames,
        )

    res["ok"] = not res["unreachable_criterion"] and not res["parse_errors"]
    return res


def _has_svc_pc_config(task_dir: Path) -> bool:
    return bool(
        list(task_dir.glob("tests/deliverables/judge.toml"))
        or list(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def check_task_dispatch(task_dir: Path) -> dict:
    """Format-dispatching wrapper. SVC-PC's tests/deliverables*/judge.toml takes precedence
    whenever it exists, matching every other dual-format check in this folder."""
    if _has_svc_pc_config(task_dir):
        return check_task(task_dir)
    if has_ekw_config(task_dir):
        return check_task_ekw(task_dir)
    return check_task(task_dir)


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

    results = []
    for i, d in enumerate(task_dirs, 1):
        if len(task_dirs) > 20:
            print(f"[{i}/{len(task_dirs)}] {d.name} ...", file=sys.stderr)
        results.append(check_task_dispatch(d))

    bad = [r for r in results if not r["ok"]]
    n_possible = sum(1 for r in results if r["ok"] and r["possible_unreachable"])
    for r in results:
        flag = "OK  " if r["ok"] else "FAIL"
        print(
            f"{flag} {r['task']:<20} {r['criteria']:>4} criteria  "
            f"{r['facts_extracted']:>4} facts  "
            f"{len(r['unreachable_criterion']):>2} unreachable  "
            f"{len(r['possible_unreachable']):>2} possible"
        )
        for w in r["parse_errors"]:
            print(f"       parse: {w}")
        for f in r["unreachable_criterion"]:
            print(
                f"       UNREACHABLE: {f['criterion']}: {f['token']!r} ({f['kind']}) -- {f['reason']}"
            )
        for f in r["possible_unreachable"]:
            print(f"       possible: {f['criterion']}: {f['token']!r} ({f['kind']})")

    print(
        f"\n{len(results) - len(bad)}/{len(results)} clean "
        f"({n_possible} of those carry only possible_unreachable, non-blocking), "
        f"{len(bad)} FAIL"
    )
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
