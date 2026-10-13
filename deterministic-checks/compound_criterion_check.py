#!/usr/bin/env python3
r"""Compound-criterion check: flag rubric criteria whose expected-value text bundles several
independent factual clauses into one verdict.

The defect, with real confirmed evidence, not a hypothesis: an LLM judge resolving ONE
pass/fail verdict for a criterion whose text states SEVERAL separate checkable facts at once
(semicolons, "and", multiple sentences) has to silently weigh those facts against each other,
and reaches a DIFFERENT verdict run to run on byte-identical content. Confirmed on three real
SVC-PC tasks, 2026-09-10, on packages proven byte-identical across datasets: SVC-PC-6-1-0
failed r13 on one Oracle run and r48 on another (4 reward points apart across 6 runs on the
same content); SVC-PC-16-4-0 failed r005 twice then passed twice before its golden was fixed;
SVC-PC-13-6-0 scored 0.8400 then 1.0000 on l02/l03.

All five were re-read directly from pipeline/data/svc_pc_qc/03_dataos_ready/ to design this
check (not assumed), and two premises stated when this check was commissioned did NOT hold up:

  - "All five are weight 0.02." False for 3 of 5 -- r005 is 0.05 (its file ranges 0.01-0.06),
    l02/l03 are both 0.08. 0.02 is just the modal weight in r13/r48's own file (~15 criteria,
    all 0.02), not a distinguishing signal. LOW_WEIGHT_MAX below is 0.10, not 0.03.
  - "All five are must-pass." False for l02/l03 by the only signal that exists (no `must_pass`
    TOML key anywhere in this schema -- confirmed against the raw files -- so it's a free-text
    claim or nothing). l02/l03 gate with "any one of the four missing or contradicted fails
    this criterion" instead of the literal phrase. MUST_PASS_RE below matches that idiom too
    (adds 7 matches on top of 5,552 literal hits across 23,220 criteria -- checked before
    adopting it, not assumed safe).

Positive control this check MUST flag: SVC-PC-6-1-0 r13 (tests/deliverables_02/judge.toml):
"Uses only direct company records as source evidence. Expected: External evidence governs
cash; approved books/close govern GAAP balances; subledgers corroborate; operational records
are diagnostic. non-source reference material/reconciled, derived packages and supporting
schedule workbooks are excluded from source citations.. This is a must-pass criterion." --
four semicolon/period-joined clauses in the Expected value alone.

Two finding kinds, per criterion:
  1. compound_criterion -- clause count (see below). 1: clean. 2: `warn` only if must-pass
     (a 2-clause non-gating criterion doesn't match the evidence shape closely enough to
     report). 3+: `fail` if must-pass and weight <= LOW_WEIGHT_MAX (highest-confidence match
     to the real evidence, which spans 0.02-0.08); `warn` otherwise (not must-pass, or
     must-pass at a weight higher than anything confirmed flipping).
  2. tiered_scoring_on_binary_type -- SECONDARY, added at a peer session's request, always
     `warn`: single unverified peer report, not the six-run proof behind compound_criterion.
     Independently checked before building a detector (not taken on the report alone):
     grepping all 23,220 SVC-PC criteria for graduated-credit language (TIER_RE) finds 149
     hits in 25 tasks, clustered by template family (SVC-PC-57-1-0 and SVC-PC-73-1-0 both
     11/15, same shape as the peer's "13 of 15"). Real, but one part of the peer's framing
     is NOT confirmed: reading SVC-PC-57-1-0 in full shows the partial tier usually IS
     qualitatively defined ("Half (3.5): the difference in totals is noticed but not
     resolved"), just not representable by a `type = "binary"` field -- and `type` is
     "binary" on 100% of criteria sampled, so "co-occurring with type=binary" adds zero
     discriminating power. Reported narrower than the peer's framing: the schema can't
     represent the three-way verdict the text defines, not that the partial tier is
     undefined.

Round 23 (2026-09-15): bf5a375 (round 22) still left 107 fails on Khiem Doan's 202-task
subset. Four Sonnet agents independently triaged all 107 against the real judge.toml text:
91 all_false_positive, 16 has_genuine_defect (already fixed at the task level by splitting
the compound criterion into atomic sub-criteria, e.g. SVC-PC-93-0-0's r09 -> r09a..r09f). Of
the 91, five mechanically-groundable shapes got real fixes here (b8-b13, see each regex's own
comment for corpus counts and the genuine-defect tasks checked against): b8 broadens the
"FAIL if" strip to the "Fails if" verb conjugation; b9 fixes a leading-paren gap in the b4
reference-fragment filter (also widens the pure-numeric check to comma/decimal/currency
figures); b10 extends the boilerplate-trailer strip to "Reference cross-tab:"/"Reference
table:"; b11 strips an explicit "this list is illustrative, not exhaustive" example span;
b12 masks explicit self-gating "Pass = .../Threshold: .../N of N/all N ... present" spans so
their own internal punctuation isn't mistaken for a clause boundary; b13 collapses a run of
3+ bare "period-label number" fragments (a monthly/quarterly data series) into one clause.

Honest yield, measured (not asserted) by running svc_run_checks.py before and after on both
Khiem's 202-task subset and the full ~600-task 03_dataos_ready corpus: task-level rollup on
the 202 subset is UNCHANGED (fail=106 both runs) because every one of the 91 tasks turned out
to carry MULTIPLE distinct compound-shaped criteria, and these five mechanisms only clear
some of the shapes present per task -- clearing 2 of 3 fail findings in a task leaves the
task's own rollup at "fail." The real effect shows at criterion-finding granularity: on the
202 subset, compound_fail findings 351->338 (-13) and compound_warn 1066->1003 (-63); corpus-
wide, compound_fail 997->967 (-30) and compound_warn 2929->2841 (-88), plus 3 full task-level
flips outside the 91 (SVC-PC-78-1-0, SVC-PC-78-2-0, SVC-PC-9-0-0, all fail->warn). Two named
examples go fully clean: SVC-PC-1-2-0's obj-01/obj-02 (clause_count 13->1 each, the exact
"Jan 0; Feb 50; ...; FY 10,000" shape this round was commissioned over); SVC-PC-14-1-0's r-03
goes fail(7)->warn(2). Confirmed safe against all 16 genuine-defect tasks' current (already-
split) sub-criteria, checked individually both before and after: zero severity changes except
SVC-PC-93-0-0's r09a-f/r23a-h, which drop a stray "(SRC-1"/"(WS-N)" citation-tag artifact
(warn(2)->clean(1), a real bug fix, not a swept defect -- 93-0-0 is not one of the tasks named
as still-should-fail). The three explicitly-flagged still-fail tasks (SVC-PC-6-2-0's r50a,
SVC-PC-91-2-0's r5a/r5b, SVC-PC-93-1-0's c18a) are confirmed unchanged.

NOT fixed, by design, and still the majority of the 91: (a) "total + component breakdown"
tie-outs (SVC-PC-14-3-0's o1/o2/o5/o11 and siblings) -- declined because this shape overlaps
the check's own positive control (SVC-PC-6-1-0 r13 is itself a multi-clause reconciliation),
so a general exemption here risks the exact false-negative this check exists to catch; (b)
same-fact restated as a negative then a positive clause ("Does not fabricate X; states that
Y", SVC-PC-15-1-0's b3; "No fabrication; figures tie to source", SVC-PC-2-6-0's a8) -- tried
one narrow regex for this shape, corpus-wide hits: 1 (not the "real volume" bar the other
five mechanisms cleared), so not shipped; (c) "N attributes jointly define one item" without
an explicit "all N ... present" marker in the text (SVC-PC-53-0-0 through 53-6-0's r001-r004
family) -- the same shape b12 fixes when the rubric author wrote the count out explicitly,
left alone when they didn't, because distinguishing "N genuinely separable facts" from "N
facets of one fact" without that textual anchor is a judgment call, the same one the four
Sonnet agents made reading full context, not a regex-safe mechanical signal.

Clause counting, SVC-PC: `_split_requirement_and_expected()` locates the first `Expected:`
label with the same `\bexpected\s*:\s*` convention rubric_schema_check.py's
PLACEHOLDER_EXPECTED_RE uses (reused, not reimplemented), splitting the description into a
requirement region and an expected region. BOTH are clause-split and the counts ADDED --
deliberately more than "count only what's after Expected:". r005's compound content lives
entirely in the requirement sentence ("names NovaTex's relationship holder ... and names at
least one of the Apex relationship ... or the SwiftShip relationship ...") with a single-fact
Expected: value ("Vendor_Master_List.xlsx tab"); counting only the expected region would
silently miss a confirmed real flip case.

Clause counting, EKW: read real verifier.json prompts (task_142 plus 8 more) before assuming
SVC-PC's convention transfers -- it does not. `Expected:` appears in 1 of 5,624 real prompts
sampled. What EKW has instead (5,437 of 5,624, 96.7%) is "PASS if X. FAIL if Y", where FAIL
restates/negates PASS rather than adding a new fact (confirmed by hand against ~15 prompts
across distinct tasks). So for EKW: strip from the first "FAIL if"/"Fail if" onward, then run
the SAME `_split_clauses()` used for SVC-PC's two regions -- one splitter, two callers, so the
formats can't silently drift on what counts as a clause. A second, genuinely EKW-specific
idiom: an enumerated "includes ALL of: (a) ... (b) ... (c) ..." requirement (task_197 v1,
task_290 v1) -- real multi-fact bundling written as a lettered list. `_split_clauses()`
detects 2+ "(a)"/"(1)"-style markers and splits on those in preference to punctuation.

EKW must-pass equivalent: no `must_pass` text convention exists in verifier.json prompts. The
closest real signal, confirmed against the same samples: `metadata.importance` is "core" or
"secondary" on every verifier seen; "core" is treated as must-pass (MUST_PASS_RE's text
patterns are also checked as a fallback). `load_ekw_criteria()`'s flattened dict drops
`importance`, so this module re-reads tests/verifier.json via the already-shared
`load_ekw_verifiers_raw()` rather than editing that module for one field.

Exit 0 clean, 1 findings, 2 bad usage. Stdlib only (needs Python 3.11+ for tomllib).

    python compound_criterion_check.py <package_root> [--task TASK-ID] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.stderr.write("needs Python 3.11+ for tomllib\n")
    raise SystemExit(2)

from ekw_verifier_json import has_ekw_config, load_ekw_criteria, load_ekw_verifiers_raw

# Same `\bexpected\s*:` convention as rubric_schema_check.py's PLACEHOLDER_EXPECTED_RE, reused
# to locate the label's position rather than to test for emptiness.
EXPECTED_LABEL_RE = re.compile(r"\bexpected\s*:\s*", re.I)

# EKW's dominant "PASS if X. FAIL if Y" idiom (96.7% of 5,624 real prompts sampled): split
# point for stripping the restatement/negation half before clause-counting what remains.
# Broadened 2026-09-15: the "if"/"only if" form alone missed colon-form "PASS:/FAIL:" and
# similar labeled phrasing (e.g. "FAIL: missing X") -- confirmed by turing-context-e5 as
# 116/2511 (4.6%) of corpus-wide fail-severity findings hitting this gap. `.search()` still
# strips from the FIRST match onward, so a prompt with multiple FAIL markers has everything
# after the first one excluded either way -- unchanged behavior for that case, just a wider
# net for what counts as the first marker.
#
# b8 (2026-09-15, round 23): the third-person-singular conjugation "Fails if"/"Fails:" was
# NOT matched -- the old pattern required "FAIL" immediately followed by optional whitespace
# then "if"/":", and the "s" in "Fails" is neither. Confirmed on the real corpus: 12 criteria
# corpus-wide use "Fails if" (SVC-PC-58-6-0 alone accounts for 8), and it is the exact gap
# that let SVC-PC-67-1-0's r003 "Fails if one record is adopted..." sentence plus everything
# textually after it (a "Reference cross-tab:" trailer with 6 more semicolon-joined figures)
# survive clause-counting untouched. `s?` added; this is a strict broadening of the existing
# idiom (same restatement/negation semantics), not a new mechanism.
EKW_FAIL_CLAUSE_RE = re.compile(r"\bFAILs?\s*(?:if\b|only if\b|:)", re.I)

# Boilerplate trailer that restates the same expected fact a second and third time after
# the main Expected: text (b2, 2026-09-15). Confirmed corpus-wide on 63 findings spanning
# 5 task families (SVC-PC-19-3/4/6-0, 37-3-0, 59-6-0): a "Response criteria guidance:"
# and/or "Blocked if:" trailer repeats the expected fact, inflating the clause count.
# Stripped from the first marker onward (whichever appears first) before clause-splitting.
#
# "Reference cross-tab:"/"Reference table:" added (b10, 2026-09-15, round 23): a supporting
# data table the rubric author included so a grader can double-check a figure, not a second
# requirement -- confirmed on SVC-PC-67-1-0/r003, where "Reference cross-tab: master Yes
# 4,801 / No 1,199; latest-order yes 4,789 / no 1,211; ..." adds 6 more semicolon-joined
# fragments after the real requirement is already fully stated. Only 1 corpus-wide hit for
# this exact marker (not assumed to generalize further); included because it is the
# clean-boundary companion to the illustrative-list fix below on the same criterion, and
# carries the same "restates/supports, does not add a new fact" semantics as the trailers
# already handled here, so it belongs in the same mechanism rather than a new one.
BOILERPLATE_TRAILER_RE = re.compile(
    r"\b(?:Response\s+criteria\s+guidance|Blocked\s+if|Reference\s+cross-tab|Reference\s+table)\s*:",
    re.I,
)

# Illustrative/non-exhaustive example list (b11, 2026-09-15, round 23): the rubric author
# explicitly marks a list of sample values as non-normative ("THIS LIST IS ILLUSTRATIVE, NOT
# EXHAUSTIVE", "not an exhaustive list", "non-exhaustive", "illustrative only") -- text saying
# in-band "do not grade against this list item-by-item" is the strongest possible signal that
# what follows carries no independent checkable facts. Confirmed on SVC-PC-67-1-0/r003: "THIS
# LIST IS ILLUSTRATIVE, NOT EXHAUSTIVE: any other figure the records demonstrably produce,
# defended and with alternatives disclosed, also passes." Only 1 corpus-wide hit for the exact
# marker (checked before adopting, not assumed to generalize) but zero regression risk: a
# rubric author who wrote this phrase has, by construction, already told the judge these
# items are not independently gradable. Strips the marker's own sentence only (to the next
# real sentence boundary), leaving the actual named-example list before it (a separate,
# ordinary clause) untouched -- narrower than BOILERPLATE_TRAILER_RE's "strip to end" because
# the marker here sits mid-criterion, not at the tail.
ILLUSTRATIVE_LIST_RE = re.compile(
    r"\bTHIS\s+LIST\s+IS\s+ILLUSTRATIVE,?\s*NOT\s+EXHAUSTIVE\b[^.]*\.{1,2}(?=\s|$)"
    r"|\bnot\s+an?\s+exhaustive\s+list\b[^.]*\.{1,2}(?=\s|$)"
    r"|\bnon-exhaustive\b[^.]*\.{1,2}(?=\s|$)"
    r"|\billustrative\s+only\b[^.]*\.{1,2}(?=\s|$)",
    re.I,
)

# Explicit self-gating combination rule (b12, 2026-09-15, round 23): "Pass = ...", "Threshold:
# ... = full; ... = 0", or an "N of N"/"all N <items> present/addressed/..." completeness
# count, all stated in the criterion's OWN text. The check's whole rationale (module
# docstring) is that an LLM judge resolving a multi-fact criterion has to SILENTLY weigh
# those facts against each other; when the rubric author has already spelled out the exact
# combination arithmetic in-band, there is nothing left to weigh silently, so the semicolons
# or ", and/or" INSIDE that stated rule are the rule's own wording, not separate bundled
# facts. Confirmed corpus-wide: "pass\s*=" 55 hits, "\d+\s+of\s+\d+" 77 hits, "all N ...
# present/addressed/scheduled/..." 130 hits (e.g. SVC-PC-25-2-0's c01/c04/c05/c27/c31,
# SVC-PC-14-1-0's r-03/r-09's "Threshold:3/3 = full; 2/3 = 3 pts; <=1/3 = 0"). Checked against
# all 16 real genuine-defect criteria this round confirmed still-compound (SVC-PC-93-0-0
# r09a-f/r23a-h, SVC-PC-9-5-0 v01a-d, SVC-PC-94-7-0 r7a-f, SVC-PC-91-6-0 r10a-d, SVC-PC-6-2-0
# r36a-b/r50a-b, SVC-PC-88-0-0 obj-07a-b, SVC-PC-91-2-0 r5a-b, SVC-PC-91-3-0 r6a-c,
# SVC-PC-93-1-0 c18a-b, SVC-PC-3-1-0 r059a-g, SVC-PC-39-3-0 c18a-b, SVC-PC-59-6-0 f04a-c,
# SVC-PC-94-5-0 r11a-b, SVC-PC-94-6-0 r09a-c, SVC-PC-26-8-0 r1a-c/r12a-c): none of their real
# text contains this idiom, so masking this span does not touch any of them. Masks (not
# drops) the matched span so its own internal punctuation cannot be split further -- see
# `_split_clauses`; the rest of the criterion is unaffected and still splits normally, so a
# criterion that bundles an unrelated compound fact ALONGSIDE a self-gating rule is not
# swept clean by this alone.
NUM_WORD_RE_FRAG = (
    r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
)
EXPLICIT_THRESHOLD_RE = re.compile(
    r"\b(?:pass\s*=|threshold\s*[:=])[^.]*\.{1,2}(?=\s|$)"
    r"|\b\d+\s+of\s+\d+\b[^.;]{0,80}?\.{1,2}(?=\s|$)"
    # Round-43 EKW-primary triage (2026-09-16): the digit-only alternative above misses the
    # SAME completeness-threshold idiom spelled out in words -- "at least four of these five",
    # "at least SIX of these eight", "eight of the ten". The TEXTUAL idiom is large and real:
    # 243 criteria across 129 of 274 tasks (47% of the corpus) contain the phrase, e.g.
    # task_207/v3 "at least four of the five elements are clearly present", task_346/v1
    # "naming at least eight of the ten pairs". Mirrors the "all N ..." alternative below,
    # which already accepts word-form numbers for the same reason -- NOT a separate mechanism,
    # an extension of the existing one, same masking semantics (own combination arithmetic
    # already stated in-band, nothing left to weigh silently).
    #
    # MEASURED real yield is far smaller than the 243-count above suggests, and that gap is
    # itself worth recording: real full-274 before/after, isolated from the FRAME_LEADIN fix
    # below (see that mechanism's own comment), is fail 1252->1251 (-1), warn 2523->2524 (+1,
    # the same criterion moving fail->warn, not a new defect) -- ONE real severity change, not
    # hundreds. Root cause, confirmed by direct construction: the trailing mask span
    # `[^.;]{0,80}?\.{1,2}(?=\s|$)` -- unchanged from the digit alternative, not something this
    # extension introduced -- can only anchor its closing period at the FIRST period-or-
    # semicolon-free run after the phrase, and EKW's dense multi-clause prose routinely puts an
    # abbreviation period ("e.g.", "vs.", "i.e.", a "$3.70x"-style decimal) before the real
    # sentence boundary, which blocks the match entirely rather than skipping past it (checked
    # directly on 11 real hits sampled from the 243: 11 of 11 failed to mask for exactly this
    # reason). Kept anyway rather than reverted: real full-274 before/after confirms zero
    # regressions (no clean/warn criterion anywhere became more severe), so this is a strict,
    # if small, improvement -- same bar b11/round-42's SCOPE_NARROWING_RE shipped on (1 and 3
    # corpus-wide hits respectively), just reached from a bigger textual population than actual
    # yield. A structurally different fix (detecting the qualifier and collapsing its
    # associated enumerated list, not span-masking to the next sentence boundary) would likely
    # reach more of the 243 -- not attempted here; the same "not forced without a safe
    # mechanical shape" bar this file's docstring already applies to (b) and (c) in the "NOT
    # fixed" list applies equally to redesigning this into something riskier.
    r"|\b"
    + NUM_WORD_RE_FRAG
    + r"\s+of\s+(?:these\s+|the\s+)?"
    + NUM_WORD_RE_FRAG
    + r"\b"
    r"[^.;]{0,80}?\.{1,2}(?=\s|$)"
    r"|\ball\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b"
    r"[^.;]{0,70}?\b(?:present|addressed|statements?|conditions?|scheduled|schedules?|"
    r"elements?|classes?|sections?|met|satisfied|listed)\b[^.]*\.{1,2}(?=\s|$)",
    re.I,
)

# A fragment that IS the whole boilerplate trailer and nothing else (fullmatch against one
# already-split, already-stripped fragment). "This is a must-pass criterion." alone is
# 856/2252 sampled judge.toml files' most common short sentence by a wide margin.
BOILERPLATE_FRAGMENT_RE = re.compile(
    r"this is a must-pass criterion\.?"
    r"|this criterion is (?:optional|not must-pass)\.?"
    r"|any values?\s*(?:!=|≠|other than|not equal to)[^.]*fails?\.?"
    r"|absent\s*(?:fails|=\s*0\s*pts)\.?\.?",
    re.I,
)

# Round-42 port (2026-09-16, GLM secondary compound_criterion triage, new benign pattern 4
# of 6): trapped boilerplate. "This is a must-pass criterion." glued to the PRECEDING real
# clause by a joiner CLAUSE_SPLIT_RE does not split on is never dropped, because
# BOILERPLATE_FRAGMENT_RE only runs via `.fullmatch()` in `_clean_fragment` against an
# ALREADY-split fragment -- if the split never happens, the boilerplate is never isolated
# to fullmatch against. Root cause: CLAUSE_SPLIT_RE's sentence-boundary branch requires
# `(?<=[a-zA-Z0-9%\)\]])` immediately before the period -- a quote character (a rubric
# author closing a quoted term right before the doubled period, e.g. "no 'improve
# fulfillment'..") is not in that set, so the split never fires and "'improve
# fulfillment'.. This is a must-pass criterion." survives clause-splitting as ONE fragment.
# Confirmed real corpus-wide (not GLM's 1-instance 202-task-mirror characterization): 10
# criteria across 10 tasks, always the LAST sentence of the description, always a single
# quoted word/phrase immediately followed by ".."/"." then " This is a must-pass
# criterion." -- SVC-PC-14-0-0/c12 ('show that they tie'), SVC-PC-26-3-0/r11 ('web'),
# SVC-PC-33-1-0/r033 ('customer'), SVC-PC-42-3-0/c06 ('contribution basis'),
# SVC-PC-53-3-0/r004 ('everyone'), SVC-PC-53-5-0/r003 ('improve fulfillment', GLM's
# original find), SVC-PC-53-6-0/r003 ('improve support'), SVC-PC-58-9-0/c03 ('TBD'),
# SVC-PC-77-7-0/c14 ('Approved'). Narrowly scoped to the confirmed shape only (a quote
# character immediately before the doubled/single period, anchored to the end of the
# description) rather than widening CLAUSE_SPLIT_RE's lookbehind generally, which would
# newly split many unrelated sentences that happen to end mid-prose on a quoted term --
# not evidenced safe and not needed for this confirmed shape. Surgical removal (not
# truncation from the match point) in case a future instance isn't the last sentence.
TRAPPED_BOILERPLATE_RE = re.compile(
    r"(?<=['\"])(\.{1,2})\s+(?:this is a must-pass criterion\.?"
    r"|this criterion is (?:optional|not must-pass)\.?)\s*$",
    re.I,
)

# Reference-code and source-label fragments that carry no checkable fact (b4, 2026-09-15).
# _clean_fragment already drops pure-numeric fragments (\d+) but not alphanumeric
# reference codes like "OI-011", "SRC-1", "WS-1" or source labels like
# "Source: audited FY2021 P&L" or "(Sources: task prompt, organization chart, ...)".
# 228 findings corpus-wide have such fragments; per the adversarial review only 4 of 82
# go fully clean from this fix alone (most affected findings are real compounds that
# carry a source fragment as noise), but the clause count is more accurate either way.
# Matched against `core` (fragment after leading/trailing punctuation strip). The
# Source/Sources alternatives use prefix match (not fullmatch) since the full fragment
# is "Source: <description>" -- the prefix is the signal, the rest is the description.
#
# round-39 port (2026-09-16): GLM's mirror independently found and fixed the same
# leading-paren gap this file's own b9 (2026-09-15, round 23, see _dedupe_ref... below)
# already closed via a different mechanism -- b9 strips "()" out of `core` before this
# regex ever runs (`core = f.strip(" .()")`), so a fragment that reaches this line has
# already lost its leading "(". GLM's fix instead widens the regex to tolerate a leading
# "(" directly (`\(?` below), never relying on the caller to have stripped it. Porting
# GLM's literal regex text here anyway, even though it is provably redundant with b9 for
# every caller in this file today: it makes the pattern correct in its own right (safe
# for any future caller that skips the paren-stripping `core` convention), matches
# GLM's real corroborated fix verbatim, and is a no-op change in this file's current
# behavior -- confirmed by a real full-600-task before/after run, not assumed from
# reading the two patterns side by side. See the round-39 port note in this file's own
# CHANGELOG-equivalent commit message for the real numbers.
REF_FRAGMENT_RE = re.compile(
    r"^\(?(?:OI-\d+|SRC-\d+|WS-\d+)\)?$" r"|^(?:Source|Sources?):" r"|^\(Sources?:",
    re.I,
)

# Literal phrase (5,552/23,220 criteria, 23.9%) plus the gating idiom l02/l03 use instead
# ("any one of the four ... fails this criterion") -- broadening adds 7 matches corpus-wide,
# checked before adopting it.
MUST_PASS_RE = re.compile(
    r"must[- ]pass"
    r"|\bany\s+(?:one|value)[^.]{0,80}?fails?\b"
    r"|fails?\s+this\s+criterion",
    re.I,
)

# Lettered/numbered enumeration marker, e.g. "(a)", "(3)" -- EKW's "includes ALL of: (a) ...
# (b) ... (c) ..." idiom. Requires a preceding boundary so it can't fire on "(exact)".
# re.I added 2026-09-15: the bare pattern (no flags = flags=32, no IGNORECASE) matched
# "(a)...and (b)..." but missed "(a)...AND (b)..." -- confirmed on real EKW prompts by
# turing-context-e5's systematic sample, letting real lettered structures fall through to
# the noisier CLAUSE_SPLIT_RE fallback instead of the more precise enumeration path.
ENUM_MARKER_RE = re.compile(
    r"(?:^|[,;:]\s*|\band\s+|\bor\s+)\(([a-hA-H]|[1-9]\d?)\)\s*", re.I
)

# One combined clause-boundary pass: semicolon (strongest signal); ", and "/", or " joining two
# distinct items (the comma keeps this off short phrases like "first and last name", which has
# no comma); a sentence boundary of 1-2 periods + capital/"(" (1-2 to match
# PLACEHOLDER_EXPECTED_RE's own doubled-period handling -- "...source citations.." is real,
# verbatim in r13).
# Two fixes 2026-09-15, both from turing-context-e5's systematic EKW sampling (13/13 fail-tier
# + 16/16+16/16 warn-tier hand-checks, real execution not inference):
# 1. The ", and"/", or" branch used a bare `and|or`, case-sensitive -- EKW writes emphatic
#    "AND"/"OR" far more often than SVC-PC did, so real compounds went undetected (a
#    false-negative in the opposite direction from mechanism 2 below). Scoped to just this
#    alternation via `(?i:...)` rather than a global re.I, so it doesn't also weaken the
#    `[A-Z(]` capital-start-of-sentence lookahead in the third branch below.
# 2. The sentence-boundary branch had no abbreviation exception, so "Dr. Brandt" and
#    "D. Featherstonhaugh" (a middle initial) both got bisected as if the period ended a
#    sentence. Added: a negative lookbehind for a single preceding capital letter (initials)
#    plus explicit common titles/abbreviations. Not exhaustive -- covers what was actually
#    observed in the sample, not every possible abbreviation.
# Round 53 (2026-09-16, bug 3): slash-list enumeration is handled as a post-pass in
# _split_clauses (see _split_slash_list below), NOT as a CLAUSE_SPLIT_RE alternative. A
# bare " / " between letters is too ambiguous (citation references like
# "Cash_BalanceSheet / BS_Monthly", ratios, path-like expressions) to split every
# occurrence. The post-pass requires 2+ " / " patterns in the same clause (3+ items),
# the same threshold the comma-list enum uses, which correctly splits a11's
# "Shopify customer / HubSpot Record ID / Zendesk requester_id" (3 items) while
# leaving single-slash citation references intact.
CLAUSE_SPLIT_RE = re.compile(
    r";"
    r"|,\s+(?i:and|or)\s+(?=[A-Za-z0-9(])"
    r"|(?<![A-Z])(?<!\bDr)(?<!\bMr)(?<!\bMs)(?<!\bJr)(?<!\bSr)(?<!\bvs)(?<!Mrs)(?<!etc)"
    r"(?<=[a-zA-Z0-9%\)\]])\.{1,2}\s+(?=[A-Z(])"
)

# Tiered-scoring language, calibrated against the real corpus (149/23,220 criteria, 25 tasks)
# before being adopted -- see module docstring.
TIER_RE = re.compile(
    r"full\s*\(\d"
    r"|half\s*\(\d"
    r"|zero\s*\(\d"
    r"|minus\s+\d+\s*(?:pts?|points?)?\s*per"
    r"|-\s*\d+\s*point"
    r"|partial\s+credit",
    re.I,
)

# Structural tier markers used to gate compound-criterion SUPPRESSION specifically --
# deliberately narrower/wider than TIER_RE / _has_tiered_language() in two different
# directions. _has_tiered_language() (all 6 TIER_RE alternatives, unchanged) still gates
# the separate, additive tiered_scoring_on_binary_type finding below; only the compound
# suppression gate uses this pair. Real corpus verification (round-40 port, 2026-09-16)
# found two precision problems with using plain _has_tiered_language() as the suppression
# gate, as GLM's mirror ports it verbatim:
#
# 1. The bare "partial credit" TIER_RE alternative, firing with no co-occurring
#    Full(/Half(/Zero(/minus-per/dash-point marker, produced 2 confirmed false
#    suppressions on the real 600-task corpus: SVC-PC-20-7-0/deliverables/r8, a
#    MUST-PASS 9-named-file compound criterion whose only tiered-sounding text is an
#    aside ("disclosing X ... earns partial credit, but does not satisfy this
#    criterion") -- suppressing this hid a genuine fail-tier compound defect, which is
#    why the real corpus's fail count (949->948 on the straight port) does not match
#    GLM's claimed "0 fail-tier impact" (measured on GLM's own 202-task mirror, which
#    does not include this task); and SVC-PC-58-5-0/deliverables_01/c08, 8 independent
#    balance-sheet dollar figures with "partial credit prorated by count correct" -- a
#    compound criterion's own proration note, not one graduated quality dimension.
#    TIER_STRUCTURAL_RE drops that one alternative for suppression purposes.
# 2. GLM separately disclosed a residual: 2 of 8 hand-verified-benign examples use a
#    colon-form tier label ("0:"/"Half:"/"Full:"/"Partial:", no parenthesized points)
#    that TIER_RE does not match at all. Confirmed real and NOT negligible at real-
#    corpus scale: 73 further real instances found (SVC-PC-36-0-0 through 36-5-0's
#    "0: .../Half: .../Full: ..." three-way scale, 56 instances; SVC-PC-67-0-0 through
#    67-4-0's "Full: .../Partial: ..." two-way scale, 17 instances) -- all warn-tier,
#    none must-pass, hand-confirmed genuine by sample from each cluster.
#    _has_colon_tier_language() requires 2+ DISTINCT tier labels (from 0/zero/half/
#    partial/full) each immediately followed by a colon, deliberately conservative so a
#    single incidental "Full:" elsewhere in a criterion's prose can't suppress it alone.
TIER_STRUCTURAL_RE = re.compile(
    r"full\s*\(\d"
    r"|half\s*\(\d"
    r"|zero\s*\(\d"
    r"|minus\s+\d+\s*(?:pts?|points?)?\s*per"
    r"|-\s*\d+\s*point",
    re.I,
)
COLON_TIER_LABEL_RE = re.compile(r"\b(0|zero|half|partial|full)\s*:", re.I)


def _has_colon_tier_language(desc: str) -> bool:
    labels = {m.group(1).lower() for m in COLON_TIER_LABEL_RE.finditer(desc or "")}
    return len(labels) >= 2


def _has_structural_tier_language(desc: str) -> bool:
    return bool(TIER_STRUCTURAL_RE.search(desc or "")) or _has_colon_tier_language(desc)


LOW_WEIGHT_MAX = 0.10  # NOT 0.03 -- see module docstring, real evidence spans 0.02-0.08

# Mechanism 1 (round 9, 2026-09-15): a ", and"/", or" that is the FINAL ITEM of a genuine
# single enumeration ("distinguish A, B, and C") must not be counted as a clause boundary.
# Disambiguator: treat ", and/or X" as a list-final item, not a new clause, when (a) a comma-
# separated run of >=2 items precedes it AND (b) the joined segment carries no finite verb (a
# noun phrase continuing the list, not an independent clause). Calibrated against the real
# mirrored corpus: 352 of 692 ", and/or" split points are this clean-noun-phrase case (51%),
# 305 carry a verb (genuine clause boundary -- kept as a split), 35 are gapped/no-comma-run
# (kept as a split, not suppressed -- the comma-run requirement protects elided-verb
# coordination like "exact for share counts, and within $0.2M for dollar figures"). The verb
# list is deliberately BROAD: a missed verb would wrongly merge an independent clause, while a
# noun-word matching the verb list only leaves the existing split in place (no regression, just
# no fix for that case). So breadth errs toward the safe direction. Does NOT fix the nested
# case "stores that are A, B, C, or D receive Y" (the main verb "receive" sits after the list
# inside the joined segment, so it reads as a verb and the split stays) -- that case is
# unchanged, not broken; fixing it needs real clause parsing, not regex.
ANDOR_SEG_VERB_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has|have|had|does|do|did|"
    r"must|should|shall|will|can|may|might|would|could|"
    r"uses|names|states?|includes?|contains?|reports?|shows?|"
    r"lists?|reflects?|matches?|equals?|exceeds?|covers?|"
    r"presents?|appears?|exists?|given|stated|"
    r"built|computed|calculated?|treated|labeled|labelled|identified|"
    r"recommend(?:s|ed)?|keep(?:s)?|delist|deduct|divides?|gives|"
    r"reach(?:es|ed)?|adds?|reduces?|removes?|apply|applied|applies|"
    r"conveys?|distinguish(?:es)?|flag(?:s|ged)?|"
    r"expose(?:s|d)?|itemiz(?:e|es|ed)|reconcil(?:e|es|ed)|"
    r"separat(?:e|es|ed)|document(?:s|ed)?|explain(?:s|ed)?|"
    r"quantif(?:y|ies)|compare(?:s|d)?|refer(?:s|red)?|mention(?:s|ed)?|"
    r"remains?|falls?|sits?|stands?|"
    r"sums?|total(?:s|ed)?|clears?|satisf(?:y|ies|ied)|"
    r"receive(?:s|d)?|remain(?:s|ed)?|allow(?:s|ed)?|"
    r"ship(?:s|ped)?|place(?:s|d)?|allocat(?:e|es|ed)|earn(?:s|ed)?|"
    r"justify|justifies|justified|"
    r"fail(?:s|ed)?|pass(?:es|ed)?|govern(?:s|ed)?|"
    r"prove(?:s|n)?|demonstrat(?:e|es|ed)|establish(?:es|ed)?|"
    r"confirm(?:s|ed)?|deny|denies|denied|"
    r"omit(?:s|ted)?|absent|forbid(?:s|den|dden)|govern|governs)\b",
    re.I,
)

# Mechanism 1 refinement (round 11, 2026-09-15): un-suppress the enum guard for
# compound cases the original guard wrongly collapsed. The guard suppresses
# ", and/or" when a comma-run precedes and the joined segment has no verb. But
# some suppressed splits are genuinely compound (N independent bundled facts),
# not one enumeration. This refinement un-suppresses when the text before the
# list carries compound-distribution signals, and keeps suppressed when it
# carries enumeration signals.
#
# Keep-suppressed signals (the list is one enumeration, not N facts):
#   - Classification verb before the list (distinguish, classify, categorize)
#   - Attribute preposition (with, across, including, comprising, into)
#   - "from" or "of" (distinguishes X from A, B, C; consists of A, B, C)
#   - Absence/negation (no X, zero, without, does not, excludes)
#   - Example marker (e.g., such as, for example) in the list items
#
# Un-suppress signals (N independent facts, not one enumeration):
#   - Compound verb pair joined by "and" (identifies and treats, preserves and
#     avoids): two verbs in the text before the list signal distribution
#   - Distributive action verb + long items (avg word count of items 2+ >= 3):
#     items with internal modifiers are distinct objects, not interchangeable
#     category labels
#
# Calibrated against the real mirrored corpus (188 SVC-PC + 124 EKW suppressed
# split points, 81 of which change classification if un-suppressed). Un-suppresses
# 6 SVC-PC + 1 EKW changed-classification cases, all genuinely compound. See
# results/round11-compound-criterion-fix-2026-09-15.md for full evidence.
#
# "avoids" is excluded from ABSENCE_RE: "avoids A, B, C claims" (SVC-PC-92-0-0
# r10) is N independent avoidances, not one absence check. "and" (not "or") in
# the compound-verb check: "states or applies" is one alternative act, while
# "identifies and treats" is two independent actions distributed over each item.
CLASSIFICATION_VERB_RE = re.compile(
    r"\b(?:distinguish(?:es)?|classif(?:y|ies|ied)|categor(?:y|ize|izes|ized)|"
    r"label(?:s|ed)?|labelled|differentiate(?:s|d)?|sort(?:s|ed)?|"
    r"separat(?:e|es|ed)|group(?:s|ed)?|rank(?:s|ed)?|prioriti(?:ze|zes|zed)|"
    r"bucket(?:s|ed)?|stratify|stratifies|stratified)\b",
    re.I,
)

ATTRIB_PREP_RE = re.compile(
    r"\b(?:with|across|including|comprising|consisting|comprise|comprises|into)\b", re.I
)

FROM_OF_RE = re.compile(r"\b(?:from|of)\b", re.I)

ABSENCE_RE = re.compile(
    r"\b(?:no\s+\w|zero|0\s+|absent|without|exclud(?:e|es|ed|ing)|"
    r"must\s+not|should\s+not|does\s+not|do\s+not|not\s+include|not\s+state|"
    r"not\s+contain|not\s+present|not\s+rely|not\s+cite|"
    r"none\s+of|neither|lacks?)\b",
    re.I,
)

EXAMPLE_RE = re.compile(r"\be\.g|such\s+as|for\s+example", re.I)

# Verb set for compound-verb detection: both sides of "and" must match. Broad
# enough to catch "identifies and treats", "preserves and avoids"; narrow
# enough to avoid most common-noun matches. Noun/verb ambiguities (report,
# state, name, list, show, cover, place) are a known residual risk; the "and"
# requirement plus the keep-suppressed signals gate most false positives on the
# real mirrored corpus (0 false positives observed).
COMPOUND_VERB_SET = re.compile(
    r"\b(?:identif(?:y|ies|ied)|treats?|retains?|preserves?|avoids?|addresses?|"
    r"states?|names?|reports?|shows?|flags?|carries?|keeps?|makes?|"
    r"decomposes?|places?|requires?|includes?|contains?|covers?|lists?|"
    r"reflects?|matches?|presents?|appears?|exposes?|itemizes?|reconciles?|"
    r"documents?|explains?|quantif(?:y|ies)|compares?|mentions?|"
    r"remains?|receives?|allows?|ships?|allocates?|earns?|reaches?|"
    r"reduces?|removes?|adds?|gives?|divides?|justif(?:y|ies|ied)|"
    r"fails?|passes?|governs?|proves?|establishes?|confirms?|"
    r"omits?|distinguishes?|separates?|demonstrates?|applies?|"
    r"relies?|cites?|holds?|provides?|defines?|delivers?)\b",
    re.I,
)

DISTRIBUTIVE_VERB_RE = re.compile(
    r"\b(?:identif(?:y|ies|ied)|treats?|retains?|preserves?|avoids?|addresses?|"
    r"states?|names?|reports?|shows?|flags?|carries?|keeps?|"
    r"makes?|decomposes?|places?|requires?)\b",
    re.I,
)

# Mechanism 4 (round 9): formulaic scene-setting lead-ins that frame/announce the check without
# stating a checkable fact of their own. Dropped from the clause list so a "The extracted
# content is an IPO valuation workbook. This rubric checks ONE thing: X. PASS if ..." prompt
# counts the PASS clause(s), not the two framing sentences. Calibrated on the real mirror:
# 92 EKW clauses match (0 SVC-PC -- SVC-PC's framing is the BOILERPLATE "This is a must-pass
# criterion." already handled). Anchored to the clause START (these are sentence-initial
# formulas), and NOT gated on a requirement signal: "This rubric checks ... and what must
# give" is framing where "must" is the idiom, not a requirement verb -- the lead-in structure
# is the signal, not the presence of "must".
FRAME_LEADIN_RE = re.compile(
    r"^\s*(?:assess\s+only\s+the\s+extracted\s+\w+\s+text\.?"
    r"|the\s+extracted\s+(?:content|workbook|memo|briefing|deck|document|text)\s+"
    r"(?:is|appears?|seems?|represents?)\s+(?:a|an|the)\b"
    r"|this\s+rubric\s+(?:checks?|evaluates?|grades?|verifies?|tests?|measures?|guards?)\b"
    r"|this\s+(?:criterion|verifier|check|rubric)\s+"
    r"(?:checks?|evaluates?|grades?|verifies?|tests?|measures?|guards?|is)\b"
    r"|for\s+this\s+(?:criterion|verifier|rubric|check)\b"
    r"|you\s+are\s+(?:inspecting|reviewing)\b)",
    re.I,
)

# Round-43 EKW-primary triage (2026-09-16, own hand-read of 30/252 fail-tier tasks, not GLM's):
# a SECOND-PERSON scene-setting opener -- "You are inspecting extracted text from
# rbc_capital_model.xlsx." / "You are reviewing a merger-arb trade memo." -- that the
# existing mechanism-4 alternatives above (all third-person: "The extracted content is a...",
# "This rubric checks...") do not match. Same rationale as mechanism 4: this sentence only
# names WHAT is being read, never a checkable fact; the real requirement is always fully
# restated in the criterion's own PASS/FAIL clause. Confirmed real corpus-wide (not assumed
# from the sample): 66 criteria across exactly 4 tasks -- task_461, task_518, task_566,
# task_631 -- so this is a template a small, identifiable cluster of task authors uses, not a
# one-off. Deliberately narrow: matches only the sentence-initial "you are
# inspecting/reviewing" opener itself, NOT the "Determine whether X." / "Identify Y." sentence
# that typically follows it in the same template (task_518/task_631) -- that second sentence
# restates the criterion's topic using verbs ("determine", "identify") that could carry real
# requirement content in a differently-worded criterion elsewhere in the corpus, and was not
# separately corpus-verified safe to drop; left alone rather than forced.
#
# MEASURED real yield, isolated from the EXPLICIT_THRESHOLD_RE word-form fix above (that
# mechanism's own comment has the isolation method): real full-274 before/after, this
# alternative ALONE -- fail 1252->1223 (-29), warn 2523->2497 (-26), task-level fail 252->250
# (2 tasks fully clear: task_566, task_631). This single alternative accounts for 29 of the 30
# real fail-tier downgrades the combined round-43 changes produce -- the dominant mechanism of
# the two, despite touching only 4 tasks total, because task_518 and task_631 carry many
# findings each built almost entirely from this 2-sentence template plus 2-3 short numeric
# clauses (see module docstring's round-43 evidence).


# Mechanism 5 (round 9): scope-narrowing grading guidance -- "Brevity is acceptable.",
# "Showing a net figure is optional and not required.", "... is not by itself a failure."
# These tell the judge what NOT to require; they carry no checkable fact of their own. The
# task's named examples ("This is critical.", "Do not skip this step.") do NOT occur in the
# mirrored EKW corpus (grep, 0 hits); what occurs is this guidance form (~26 clauses). Gated
# on NO requirement signal (must/should/shall/names/states/...) AND no digit AND not a PASS/FAIL
# lead, so a real requirement clause that happens to contain "is NOT required" as a sub-phrase
# (task_511/v15: "The extracted workbook must make its burden figures traceable ... a separate
# citation string on every single item row is NOT required: ...") is NOT suppressed -- the
# "must make" requirement signal keeps it. Residual restatement the regex cannot cleanly catch
# (alternative-expression ", or equivalently Y", emphasis, definitions) is left for LLM
# judgment -- see the round-9 writeup.
GUIDANCE_RE = re.compile(
    r"\b(?:is\s+(?:not\s+)?(?:required|optional|acceptable|disqualifying|"
    r"a\s+failure|by\s+itself|strictly\s+required|supportive\s+but\s+not\s+required)"
    r"|not\s+strictly\s+required"
    r"|not\s+disqualifying"
    r"|brevity\s+is\s+acceptable"
    r"|elaborate\s+detail\s+is\s+not\s+required"
    r"|absence\s+of\s+[^.]{0,60}?is\s+not\s+by\s+itself\s+a\s+failure"
    r"|is\s+supportive\s+but\s+not\s+required)\b",
    re.I,
)
REQ_SIGNAL_RE = re.compile(
    r"\b(?:must|should|shall|names?|states?|reports?|shows?|includes?|"
    r"identifies?|recommend(?:s|ed)?|requires?|obtain(?:s|ed)?|checked)\b",
    re.I,
)

# "must NOT be required" guidance idiom (b6): REQ_SIGNAL_RE treats "must" as a
# requirement verb, so _is_noncheckable returns False before GUIDANCE_RE fires,
# keeping the clause as checkable and inflating the count. This parallel check
# fires ahead of the REQ_SIGNAL_RE gate so the guidance path catches it.
MUST_NOT_REQUIRED_RE = re.compile(r"\bmust\s+not\s+be\s+required\b", re.I)
DIGIT_RE = re.compile(r"\d")
PASS_LEAD_RE = re.compile(r"^\s*(?:pass|fail)\b", re.I)

# Round-42 port (2026-09-16, GLM secondary compound_criterion triage, new benign pattern 2
# of 6): cross-reference scope-narrowing -- a clause telling the judge that a RELATED
# requirement is graded in a DIFFERENT, named criterion ("... is graded separately in A14",
# "coverage of X is graded in F02 / F06 / F08, not here"). This carries no independently-
# verifiable fact for the CURRENT criterion; it is a redirect, the same "tells the judge
# what NOT to require here" family as mechanism 5 (GUIDANCE_RE), but a distinct surface
# form GUIDANCE_RE does not match. Confirmed real corpus-wide (not GLM's 202-task mirror,
# which found only 1 instance): 3 criteria across 2 tasks -- SVC-PC-5-1-0/a01 (GLM's
# original find) plus a SECOND task GLM's mirror didn't sample, SVC-PC-5-6-0 (f12, f14,
# sharing near-identical boilerplate: "coverage of the top risk / first move / decision
# point is graded in F02 / F06 / F08, not here"). Checked before adopting: the real
# criterion IDs referenced (A14, F02/F06/F08) contain digits, so this check is placed
# BEFORE the DIGIT_RE gate below (same placement as FRAME_LEADIN_RE) -- placing it after,
# like GUIDANCE_RE, would silently never fire on any of the 3 real instances.
SCOPE_NARROWING_RE = re.compile(r"\bis\s+graded\s+(?:separately\s+)?in\b", re.I)


def _clean_fragment(frag: str) -> str | None:
    """Raw split fragment -> cleaned clause, or None (empty, pure boilerplate, a stray
    list-numbering artifact like a bare "2." left from a tab reference, a reference-
    code/source-label fragment like "OI-011" or "Source: audited FY2021 P&L", or a bare
    figure left dangling by its own enclosing parenthesis (b9, 2026-09-15)."""
    f = frag.strip().strip(",;: ")
    if not f or BOILERPLATE_FRAGMENT_RE.fullmatch(f):
        return None
    # b9 (2026-09-15, round 23): strip a leading/trailing "(" or ")" too before computing
    # `core`. A semicolon inside "(SRC-1; WS-1)" splits into "(SRC-1" and "WS-1)"; the old
    # strip(",;: ") never touched parens, so only the already-bare "WS-1)" half ever matched
    # REF_FRAGMENT_RE's `WS-\d+\)?$` anchor -- "(SRC-1" kept its leading "(" and the parallel
    # `SRC-\d+` anchor, which has no leading-paren form, never fired. Confirmed on
    # SVC-PC-93-0-0's split r09a-f/r23a-h: each carries a "(SRC-1; WS-N)" citation tag whose
    # first half survived clause-counting as a fake second clause (clause_count 2, should be
    # 1). Widening the numeric check in the same line to accept comma/decimal/currency/percent
    # figures ("4,801", "$1,204,900", "45.5%") closes the parallel gap the plain \d+ check
    # always had for any number with punctuation -- a fragment that is JUST a number carries
    # no checkable fact whether or not it has a thousands separator.
    core = f.strip(" .()")
    if len(core) < 2 or re.fullmatch(r"\$?\d[\d,]*(?:\.\d+)?%?", core):
        return None
    if REF_FRAGMENT_RE.match(core):
        return None
    return f


def _has_compound_verb(text: str) -> bool:
    """Two COMPOUND_VERB_SET verbs joined by 'and' (not 'or') within a word
    window. Finds each 'and', checks the 5 words before and 3 after for verb
    matches. 'and' (not 'or') because 'states or applies' is one alternative
    act, while 'identifies and treats' is two independent actions distributed
    over each list item."""
    for m in re.finditer(r"\band\b", text, re.I):
        before = text[: m.start()].split()
        after = text[m.end() :].split()
        before_words = before[-5:] if len(before) >= 5 else before
        after_words = after[:3] if len(after) >= 3 else after
        for bw in before_words:
            if COMPOUND_VERB_SET.match(bw):
                for aw in after_words:
                    if COMPOUND_VERB_SET.match(aw):
                        return True
    return False


def _avg_items2plus(run_text: str) -> float:
    """Average word count of comma-separated items 2+ (skip the first, which
    includes the governing phrase and inflates the count). Short parallel
    items (confirmed, derived, owner) average < 3; long noun phrases with
    internal modifiers (the stale dual-3PL SOP, missing supersession trail)
    average >= 3."""
    items = [it.strip() for it in run_text.split(",") if it.strip()]
    if len(items) < 2:
        return 0.0
    rest = items[1:]
    wc = [len(it.split()) for it in rest]
    return sum(wc) / len(wc) if wc else 0.0


def _enum_guard_should_suppress(
    text: str, last: int, m_start: int, next_start: int
) -> bool:
    """Return True if the enum guard should suppress this ", and/or" split
    (keep the enumeration merged as one clause), False if it should un-suppress
    (split despite the guard, because the list is N independent facts not one
    enumeration). See the mechanism-1 refinement comment block for the signals
    and the round-11 writeup for calibration evidence."""
    run_text = text[last:m_start]
    items_text = text[last:next_start]
    # Keep-suppressed signals: the list is one enumeration
    if CLASSIFICATION_VERB_RE.search(run_text):
        return True
    if ATTRIB_PREP_RE.search(run_text):
        return True
    if FROM_OF_RE.search(run_text):
        return True
    if ABSENCE_RE.search(run_text):
        return True
    if EXAMPLE_RE.search(items_text):
        return True
    # Un-suppress signals: N independent bundled facts
    if _has_compound_verb(run_text):
        return False
    if DISTRIBUTIVE_VERB_RE.search(run_text) and _avg_items2plus(run_text) >= 3:
        return False
    # Default: suppress (original mechanism-1 behavior)
    return True


def _clause_split_with_enum_guard(text: str) -> list[str]:
    """CLAUSE_SPLIT_RE.split, but suppress the ", and"/", or" branch when it is the final item
    of a genuine single enumeration (mechanism 1). Suppression fires when (a) a comma-separated
    run of >=2 items precedes the ", and/or" (text since the previous split point has a comma,
    i.e. this isn't a bare "X, and Y" two-fact join) AND (b) the joined segment -- up to the next
    CLAUSE_SPLIT_RE match, which is abbreviation-aware for sentence boundaries -- carries no
    finite verb. Suppression means: don't cut here, keep the enumeration merged as one clause.
    Everything else (";", sentence boundary, ", and/or" with a verb in the joined segment, or
    ", and/or" with no comma-run before it) splits exactly as before. See ANDOR_SEG_VERB_RE's
    comment for why the verb list is broad and which real case stays unfixed-but-unbroken.

    Round 11 refinement: the suppression is now gated by _enum_guard_should_suppress(), which
    un-suppresses when the text before the list carries compound-distribution signals (compound
    verb pair, or distributive verb + long items) and no enumeration signal (classification verb,
    attribute preposition, from/of, absence, example marker). This fixes the SVC-PC-92-0-0
    regression where r04/r09/r10 were wrongly suppressed despite being N independent bundled
    facts. See the mechanism-1 refinement comment block above for signal definitions."""
    raw: list[str] = []
    matches = list(CLAUSE_SPLIT_RE.finditer(text))
    last = 0
    for i, m in enumerate(matches):
        if m.group(0).startswith(","):
            run_items = text[last : m.start()].count(",") + 1
            next_start = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            seg = text[m.end() : next_start]
            if run_items >= 2 and not ANDOR_SEG_VERB_RE.search(seg):
                if _enum_guard_should_suppress(text, last, m.start(), next_start):
                    continue  # list-final noun phrase: keep merged, do not split here
        raw.append(text[last : m.start()])
        last = m.end()
    raw.append(text[last:])
    return raw


def _is_noncheckable(clause: str) -> bool:
    """Mechanisms 4/5: a clause that frames the check or narrows its scope without stating a
    checkable fact of its own. Two disjoint paths, both require the clause to NOT be a PASS/FAIL
    lead (the actual test is never dropped):
      - frame lead-in (mechanism 4): clause starts with a formulaic framing lead-in. Ungated
        on requirement signal -- "This rubric checks ... what must give" is framing.
      - guidance (mechanism 5): scope-narrowing phrase, gated on NO requirement signal AND no
        digit, so a real requirement clause containing "is NOT required" as a sub-phrase is kept.

    Round-42 port: cross-reference scope-narrowing ("is graded separately in A14") is a
    third path, checked alongside the frame lead-in (mechanism 4) and BEFORE the digit
    gate -- see SCOPE_NARROWING_RE's own comment for why (the real named cross-references
    contain digits, e.g. "A14", "F02 / F06 / F08").
    """
    c = clause.strip().strip(".")
    if not c or len(c) < 3:
        return False
    if PASS_LEAD_RE.search(c):
        return False
    if FRAME_LEADIN_RE.search(c) or SCOPE_NARROWING_RE.search(c):
        return True
    if DIGIT_RE.search(c):
        return False
    if MUST_NOT_REQUIRED_RE.search(c):
        return True
    if REQ_SIGNAL_RE.search(c):
        return False
    return bool(GUIDANCE_RE.search(c))


# b13 (2026-09-15, round 23): a run of bare "period-label number" fragments -- "Jan 0",
# "Feb 50", ..., "FY 10,000" -- is one monthly/quarterly data series checked against one
# approved source, not N independent facts; the positive-control case for this file
# (SVC-PC-6-1-0 r13) is a reconciliation with 4 DIFFERENT full-sentence source-precedence
# rules for 4 different balance types, a different shape entirely from a bare label+number
# pair. Confirmed on SVC-PC-1-2-0 obj-01/obj-02/obj-04 (the module docstring's own compound
# fix history references obj-02's "Jan $0; Feb $5,900; ...; FY $1,204,900" as the canonical
# example of this shape): each semicolon-joined item is JUST a period label and a number,
# nothing else. Anchored with `$` so a fragment that happens to start with a month name but
# continues into prose ("May require further review") never matches -- only a fragment that
# is ENTIRELY "label [/label] [and label] number" matches. `mar` and `may` are deliberately
# both month abbreviations and, for "may", an English modal verb; the trailing `$` anchor is
# what keeps this from over-matching, not the word list.
PERIOD_LABEL_RE = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|q[1-4]|fy|h[12]|w(?:eek)?\s?\d{1,2})"
    r"(?:\s*/\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|q[1-4]|fy|h[12]))?"
    r"(?:\s+and\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|q[1-4]|fy|h[12]))?"
    r"\.?\s+\$?[\d,]+(?:\.\d+)?%?$",
    re.I,
)


def _collapse_periodic_series(clauses: list[str]) -> list[str]:
    """Collapse a run of 3+ CONSECUTIVE PERIOD_LABEL_RE clauses into one ("one data-series
    check against one approved source"). A run of 1-2 is left alone -- two related figures
    is not yet "a series" and the existing per-clause logic already handles that case fine.
    Runs shorter than 3 or interrupted by a non-matching clause are not merged across the
    gap (deliberately conservative: only a clean, unbroken run collapses)."""
    out: list[str] = []
    i, n = 0, len(clauses)
    while i < n:
        if PERIOD_LABEL_RE.match(clauses[i]):
            j = i
            while j < n and PERIOD_LABEL_RE.match(clauses[j]):
                j += 1
            if j - i >= 3:
                out.append(
                    f"{clauses[i]}; ...; {clauses[j - 1]} (one period-series check)"
                )
                i = j
                continue
        out.append(clauses[i])
        i += 1
    return out


def _drop_noncheckable(clauses: list[str]) -> list[str]:
    """Drop frame-setting/guidance clauses (mechanisms 4/5). Never reduces a non-empty list to
    zero -- if every clause looks non-checkable, keep the first (a criterion that is pure
    framing with no checkable clause is rare and shouldn't silently read as 'clean')."""
    if not clauses:
        return clauses
    kept = [cl for cl in clauses if not _is_noncheckable(cl)]
    return kept if kept else [clauses[0]]


def _split_clauses(text: str) -> list[str]:
    """One region of text -> independent factual clauses. Enumeration markers take priority
    when 2+ are present (EKW's "(a)...(b)...(c)" idiom); otherwise one combined pass over
    CLAUSE_SPLIT_RE with the mechanism-1 enumeration guard, then a periodic-series collapse
    (b13), then mechanisms 4/5 drop frame-setting/guidance clauses. Heuristic by design --
    see module docstring.

    b12 (round 23): before any of that, EXPLICIT_THRESHOLD_RE spans ("Pass = ...",
    "Threshold: ...", "N of N", "all N ... present") are masked out to a single placeholder
    token so their own internal ";"/", and/or" cannot be mistaken for a clause boundary, then
    restored onto whichever cleaned clause ends up containing the token. The token starts
    with a capital letter and ends with a period so the sentence-boundary branch of
    CLAUSE_SPLIT_RE still sees a normal-looking sentence on both sides of it.
    """
    text = text.strip()
    if not text:
        return []
    protected: list[str] = []

    def _mask(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"Xthresholdmarkerx{len(protected) - 1}x."

    text = EXPLICIT_THRESHOLD_RE.sub(_mask, text)
    markers = list(ENUM_MARKER_RE.finditer(text))
    if len(markers) >= 2:
        raw = []
        for i, m in enumerate(markers):
            start = m.end()
            end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
            raw.append(text[start:end])
    else:
        raw = _clause_split_with_enum_guard(text)
    clauses = [c for c in (_clean_fragment(f) for f in raw) if c]
    if protected:
        clauses = [
            re.sub(
                r"Xthresholdmarkerx(\d+)x\.?",
                lambda m: protected[int(m.group(1))],
                c,
            )
            for c in clauses
        ]
    clauses = _collapse_periodic_series(clauses)
    clauses = _drop_noncheckable(clauses)
    clauses = _split_slash_list(clauses)
    return clauses


def _split_slash_list(clauses: list[str]) -> list[str]:
    """Round 53 (2026-09-16, bug 3): split a clause that is a slash-separated enumeration
    of 3+ items. Requires 2+ " / " patterns (whitespace-slash-whitespace between letters)
    in the same clause to confirm it's an enumeration, not a single path/ratio/citation
    reference. Guards against dates (digits, no whitespace), file paths (no whitespace),
    and fractions (digits, no whitespace) inherently via the \\s+ requirement.

    Confirmed on SVC-PC-80-6-0/a11 where "Shopify customer / HubSpot Record ID / Zendesk
    requester_id" (2 slashes = 3 items) was counted as 1 clause instead of 3. Single-slash
    cases like "Cash_BalanceSheet / BS_Monthly" (a citation reference, not an enum) are
    left intact by the 2+ threshold."""
    slash_re = re.compile(r"(?<=[A-Za-z])\s+/\s+(?=[A-Za-z])")
    out: list[str] = []
    for clause in clauses:
        matches = list(slash_re.finditer(clause))
        if len(matches) < 2:
            out.append(clause)
            continue
        # Split on all 2+ slash positions
        parts: list[str] = []
        last = 0
        for m in matches:
            parts.append(clause[last : m.start()].strip())
            last = m.end()
        parts.append(clause[last:].strip())
        out.extend(p for p in parts if p)
    return out


def _split_comma_list_enum(clauses: list[str]) -> list[str]:
    """Round 53 (2026-09-16, bug 3): guard-aware comma-list splitter for the Expected: region.
    When the post-Expected: text is a comma-list of 3+ short noun phrases (each <= 4 words,
    no main verb), split it into separate clauses. The first item may carry a lead-in prefix
    (e.g. "Shopify = SOR for orders, line items, retail price"), so only items 2+ are checked
    for noun-phrase shape. Oxford "and" before the last item is stripped before counting.

    Discriminates an enum from a single expected value: an enum has 3+ comma-separated items
    where items 2+ are noun phrases with no main verb. A single value like "Pass = the
    schedule ties to the ledger" has no 3+ comma-list and is not split. Confirmed on
    SVC-PC-80-6-0/c2 ("orders, line items, retail price" -> 3) and SVC-PC-77-8-0/c20
    ("cash preserved, time-to-realize, operational/growth cost, and a ... rank" -> 4).
    Applied to the exp region only (inside the Expected: guard), not the req region."""
    out: list[str] = []
    for clause in clauses:
        # Split on commas NOT between digits (avoids breaking thousands separators like
        # $300,000 and $55,000). A comma between "summary, design" (letter, space) splits;
        # a comma in "$300,000" (digit, digit) does not.
        parts = [p.strip() for p in re.split(r"(?<!\d),(?!\d)", clause) if p.strip()]
        if len(parts) < 3:
            out.append(clause)
            continue
        # Strip Oxford "and" before the last item
        last = parts[-1]
        last_clean = re.sub(r"^and\s+", "", last, flags=re.I)
        if last_clean != last:
            parts[-1] = last_clean
        # Check items 2+ (index 1 onward): each <= 4 words, no main verb
        all_noun = True
        for item in parts[1:]:
            if len(item.split()) > 4:
                all_noun = False
                break
            if ANDOR_SEG_VERB_RE.search(item):
                all_noun = False
                break
        if all_noun:
            out.extend(parts)
        else:
            out.append(clause)
    return out


def _split_requirement_and_expected(desc: str) -> tuple[str, str]:
    """SVC-PC shape: requirement sentence, `Expected:` label, expected value. Returns
    (requirement_text, expected_text); expected_text is "" with no label (also EKW's
    fallback path -- 1 of 5,624 real prompts sampled has one)."""
    m = EXPECTED_LABEL_RE.search(desc)
    if not m:
        return desc, ""
    return desc[: m.start()], desc[m.end() :]


def _strip_ekw_fail_clause(prompt: str) -> str:
    """Drop everything from the first "FAIL if"/"Fail if" onward. Confirmed by hand against
    ~15 real EKW prompts across distinct tasks: FAIL restates/negates PASS rather than adding
    a new checkable fact. A FAIL clause that DOES add new content (not observed) would be
    under-counted -- same direction of error as SVC-PC's boilerplate-suffix exclusion.

    2026-09-15 (b1): the same "Fail if" restatement idiom appears in at least 17 SVC-PC
    criteria in the expected region, inflating the clause count the same way. The strip
    now runs for SVC-PC too (count_clauses no longer gates on is_ekw). Verified safe: 0
    SVC-PC findings have "FAIL:" without "FAIL if", so the colon branch of the regex does
    not fire on SVC-PC text.
    """
    m = EKW_FAIL_CLAUSE_RE.search(prompt)
    return prompt[: m.start()] if m else prompt


def _strip_boilerplate_trailer(text: str) -> str:
    """Drop everything from the first "Response criteria guidance:", "Blocked if:",
    "Reference cross-tab:" or "Reference table:" onward (whichever appears first). These
    trailers restate the same expected fact a second and third time after the main Expected:
    text (b2, 2026-09-15; b10 added the two Reference variants). Confirmed on 63 corpus-wide
    findings across 5 SVC-PC task families (b2) plus 1 for the Reference variants (b10).
    """
    m = BOILERPLATE_TRAILER_RE.search(text)
    return text[: m.start()] if m else text


def _strip_illustrative_list(text: str) -> str:
    """Drop the sentence containing an explicit "this list is illustrative/non-exhaustive"
    marker (b11, 2026-09-15). Unlike `_strip_boilerplate_trailer`, this does not strip to the
    end of the string -- only the marker's own sentence, since the named-example list before
    it is ordinary content (its own clause) and real requirement text often follows after.
    """
    return ILLUSTRATIVE_LIST_RE.sub("", text)


def _strip_trapped_boilerplate(text: str) -> str:
    """Drop a "This is a must-pass criterion."-style boilerplate sentence that survives
    clause-splitting glued to the preceding quoted clause (round-42 port; see
    TRAPPED_BOILERPLATE_RE's own comment). Removes just the matched boilerplate span,
    keeping the quote and its closing period(s) intact, so the real preceding clause is
    unaffected."""
    return TRAPPED_BOILERPLATE_RE.sub(r"\1", text)


# Round-42 port (2026-09-16, GLM secondary compound_criterion triage, new benign pattern 1
# of 6): "Pass = <restated value>[; fail (if|on) <restated condition>]" restates a value
# already stated earlier in the SAME region (requirement or expected), framed as the
# pass/fail condition. b12's EXPLICIT_THRESHOLD_RE already masks a "Pass = ..." span so its
# OWN internal punctuation can't be mistaken for a clause boundary, but the masked token is
# still restored and counted as one clause -- correct when "Pass=" states a genuinely NEW
# self-gating rule (SVC-PC-14-1-0's r-03/r-09 "Threshold:3/3 = full; ..."), wrong when it
# merely repeats a fact the region already stated. Confirmed corpus-wide (not GLM's 202-task
# mirror -- the real 600-task corpus, which surfaced a SECOND task GLM's mirror didn't
# sample): 55 criteria across exactly 2 tasks, SVC-PC-25-2-0 (32) and SVC-PC-7-5-0 (23).
# The two tasks place the marker in DIFFERENT regions -- 25-2-0's "Pass=" trails the
# Expected: value ("Expected: $250,000 (exact). Pass = $250,000 stated..."); 7-5-0's
# "Pass=" sits in the REQUIREMENT sentence BEFORE the Expected: label ("Retention is built
# on the booked installed base... Pass = total orders == 10,000 AND... Expected: 10,000
# orders..."). A naive "strip from the first Pass= onward" over the WHOLE pre-split text
# (the way `_strip_boilerplate_trailer` works) would, on 7-5-0's shape, delete the real
# `Expected:` label and its value along with the restatement -- confirmed by direct
# construction, not assumed. Fixed by stripping PER REGION, after
# `_split_requirement_and_expected` has already separated requirement from expected, so a
# marker in one region can never consume the other region's real content. Guarded so a
# region is never stripped to nothing: verified real corpus-wide (all 55 hits, both tasks)
# that real content always precedes the marker in its own region before shipping this
# guard, not assumed. `fail (if|on) <condition>` is swept up for free since it always
# trails the same "Pass=" marker in these 55 criteria; a bare "fail on" with no accompanying
# "Pass=" (3 further corpus-wide hits: SVC-PC-7-0-0/c84 and SVC-PC-7-1-0/st5, both a
# "PASS/FAIL" dashboard-column LABEL matching "FAIL on <metric>", not this restatement
# idiom at all; SVC-PC-77-0-0/c16, a standalone "Fail on any headline contradiction"
# elaboration with no "Pass=" partner) is NOT touched -- out of GLM's characterized pattern
# and not verified safe.
PASS_RESTATEMENT_RE = re.compile(r"\bpass\s*=", re.I)


def _strip_pass_restatement(text: str) -> str:
    """Drop a trailing "Pass = ..." restatement (and anything after it, e.g. a paired
    "fail on/if ...") from ONE already-split region, only when real content precedes the
    marker in that SAME region -- never reduces a region to nothing."""
    m = PASS_RESTATEMENT_RE.search(text)
    if not m or not text[: m.start()].strip():
        return text
    return text[: m.start()]


def count_clauses(desc: str, *, is_ekw: bool) -> tuple[list[str], list[str]]:
    """(requirement_clauses, expected_clauses) for one description/prompt. Both EKW and
    SVC-PC strip the FAIL clause first, then strip the "Response criteria guidance:" /
    "Blocked if:" / "Reference cross-tab:" / "Reference table:" boilerplate trailer, then
    strip any "illustrative, not exhaustive" example-list sentence, then run the identical
    requirement/expected split -- which will almost always find no `Expected:` label on EKW
    and return everything as the requirement region, so a stray real `Expected:` in an EKW
    prompt is still handled for free. SVC-PC's "Fail if" restatement inflates the clause
    count the same way EKW's does (b1, 2026-09-15). The boilerplate trailer strip handles the
    "Response criteria guidance:" / "Blocked if:" duplication pattern (b2, 2026-09-15) and
    the "Reference cross-tab:" / "Reference table:" supporting-data pattern (b10). The
    illustrative-list strip (b11) handles named-example lists the rubric author marked
    non-normative in-band. The trapped-boilerplate strip (round-42 port, see
    `_strip_trapped_boilerplate`'s own comment) removes a "This is a must-pass criterion."
    sentence glued to the preceding quoted clause by a joiner CLAUSE_SPLIT_RE doesn't split
    on. Each already-split region then has its own trailing "Pass=" restatement stripped
    (round-42 port, see `_strip_pass_restatement`'s own comment). `_split_clauses` (called
    below, per region) separately masks explicit self-gating "Pass="/"Threshold:"/"N of
    N"/"all N ... present" spans (b12, for whatever "Pass=" text the per-region strip above
    did NOT remove -- i.e. a "Pass=" with no real content before it in its own region,
    which the b12 masking still protects), drops cross-reference scope-narrowing clauses
    (round-42 port, see `_is_noncheckable`), and collapses period-label numeric series
    (b13)."""
    text = _strip_ekw_fail_clause(desc)
    text = _strip_boilerplate_trailer(text)
    text = _strip_illustrative_list(text)
    text = _strip_trapped_boilerplate(text)
    req, exp = _split_requirement_and_expected(text)
    req = _strip_pass_restatement(req)
    exp = _strip_pass_restatement(exp)
    return _split_clauses(req), _split_comma_list_enum(_split_clauses(exp))


def _is_must_pass(desc: str, *, importance: str | None = None) -> bool:
    if importance == "core":
        return True
    return bool(MUST_PASS_RE.search(desc or ""))


def _has_tiered_language(desc: str) -> bool:
    return bool(TIER_RE.search(desc or ""))


# b14 (2026-09-16, tracker row 18/round 4 audit): a requirement region that splits into
# EXACTLY 2 clauses, where the SECOND is a negative caveat of the SAME instruction ("do X;
# do not do the naive-wrong-thing" -- "Extract the finished-goods/inventory sub-limit from the
# certificate itself; do not assume it.", SVC-PC-25-2-0's c01) is not a second independent
# fact, the same rationale the module docstring already gives for the single-clause topic-
# sentence exemption just above `req_n`'s own definition, extended to the very common case
# where the rubric author wrote the caveat as its own semicolon-joined clause instead of
# folding it into the first sentence.
#
# Confirmed by a real, random 18-task/73-finding hand sample against real judge.toml text
# (not assumed): found this exact shape recurring across unrelated task families (25-2-0,
# 36-3-0, 36-5-0, 75-8-0's r2, plus corpus-wide grep turned up dozens more: sprint-evidence-
# window caveats across the 46-x-0 family, "uses only X; does not invent Y" caveats across
# 14-3-0/58-5-0/70-8-0/80-1-0/88-3-0, scope-boundary caveats across 24-5-0/24-6-0/75-8-0/
# 91-7-0). Measured directly against classify_compound() itself (_scratch_r4_reqneg.py, not a
# hand estimate): corpus-wide, 1245 criteria have exactly 2 requirement-region clauses, 62 of
# those have a negation-led second clause, and discounting req_n for those 62 changes the
# REAL fail/warn/clean verdict on 42 of them.
#
# Real safety gap found reviewing those 42 before shipping, not assumed away: a "does not X"
# clause sometimes states a genuinely SEPARATE, independent rule about a DIFFERENT named
# document, not a caveat on the first clause's own topic -- SVC-PC-96-2-0/c04's "does not
# treat the Apex lead-time tracker's ... as full-year coverage" is unrelated to that same
# criterion's first clause (a dollar-figure-distinctness rule about entirely different
# figures). Guarded with `_negation_caveat_same_topic`: a negated clause that names a
# filename-shaped token NOT already present in the first clause is treated as a genuinely
# separate fact, not discounted. This drops 2 of the 42 (both SVC-PC-96-x-0 cases) and leaves
# 40 real severity changes spanning 30+ distinct, unrelated task families -- real volume, not
# concentrated in one template.
NEG_CAVEAT_RE = re.compile(r"^\s*(?:do\s+not|does\s+not|without|not\s)\b", re.I)
FILENAME_TOKEN_RE = re.compile(
    r"\b[\w][\w .-]{2,60}\.(?:xlsx|xlsm|docx|csv|pdf|pptx)\b", re.I
)


def _negation_caveat_same_topic(first: str, negated: str) -> bool:
    neg_files = {m.group(0).lower() for m in FILENAME_TOKEN_RE.finditer(negated)}
    if not neg_files:
        return True
    first_files = {m.group(0).lower() for m in FILENAME_TOKEN_RE.finditer(first)}
    return neg_files.issubset(first_files)


def _req_clause_count_for_scoring(req_clauses: list[str]) -> int:
    """len(req_clauses) if it should count toward the total (2+ genuinely distinct clauses),
    else 0 -- same "generic topic sentence, not a real extra clause" exemption the module
    docstring already applies to a single-clause requirement region, extended (b14) to the
    exactly-2-clause case where clause 2 is a same-topic negative caveat of clause 1."""
    if len(req_clauses) < 2:
        return 0
    if (
        len(req_clauses) == 2
        and NEG_CAVEAT_RE.search(req_clauses[1].strip())
        and _negation_caveat_same_topic(req_clauses[0], req_clauses[1])
    ):
        return 0
    return len(req_clauses)


def classify_compound(
    req_clauses: list[str],
    exp_clauses: list[str],
    *,
    must_pass: bool,
    weight,
    is_ekw: bool = False,
) -> dict | None:
    """None if clean; otherwise a dict with severity in {"warn", "fail"}. See module
    docstring for full reasoning: 1 clause clean; 2 clauses warn only if must-pass; 3+
    clauses fail if must-pass and weight <= LOW_WEIGHT_MAX, else warn.

    The requirement region only contributes when it is ITSELF internally multi-clause
    (len >= 2, as in r005's "names NovaTex's holder ... and names Apex-or-SwiftShip's
    holder ..."). A single-clause requirement region is SVC-PC's generic topic sentence
    ("Reconciles the complete chart-of-accounts population.") that precedes almost every
    Expected: label -- counting it as a full extra clause would inflate every two-fact
    Expected: value (e.g. r01: "Exactly 25 account rows; corrected net control is $0.") past
    the 3-clause fail threshold on the strength of its topic sentence alone, not on any
    second compound fact. This has no effect on EKW/no-label text, where the requirement
    region is the ENTIRE criterion: a real single-clause criterion still totals <=1 (clean)
    whether or not it's zeroed here, since 0 and 1 both fail the total<=1 check below.

    b14 (round 4, 2026-09-16): the same exemption extends to an exactly-2-clause requirement
    region where clause 2 is a same-topic negative caveat of clause 1 ("do X; do not assume
    it") -- see `_req_clause_count_for_scoring`'s own comment for the full rationale and
    corpus-wide evidence. A 3+-clause requirement region is untouched by this extension.

    EKW fail threshold (round 9, 2026-09-15): on EKW the fail bar is 4+ clauses, not 3+.
    `importance=="core"` is EKW's must-pass proxy and is 72.7% of the mirrored corpus (66.1%
    of the full 5,624-criteria corpus per the module docstring), vs SVC-PC's literal
    "must-pass" phrase at 23.9% -- roughly 3x less selective. No verifier.json field is more
    selective (grading_role=="outcome" is 76.8%, BROADER than core; core-and-outcome is
    67.1%, barely narrower; metadata.must_pass is present on 0 of 289 mirrored verifiers).
    So EKW's must-pass signal is inherently noisier: a 3-clause must-pass EKW criterion is a
    weaker match to the real (SVC-PC) flip evidence than a 3-clause literal-must-pass SVC-PC
    criterion. Requiring 4+ clauses for fail on EKW compensates by demanding more compound
    evidence before the highest-confidence tier fires; 2- and 3-clause must-pass EKW criteria
    still warn (not silently clean). SVC-PC is unchanged (fail at 3+).
    """
    req_n = _req_clause_count_for_scoring(req_clauses)
    total = req_n + len(exp_clauses)
    if total <= 1:
        return None
    low_weight = weight is None or (
        isinstance(weight, (int, float)) and weight <= LOW_WEIGHT_MAX
    )
    fail_min = 4 if is_ekw else 3
    if total >= fail_min:
        severity = "fail" if (must_pass and low_weight) else "warn"
    else:  # total == 2, or total == 3 on EKW (below EKW's 4+ fail bar)
        if not must_pass:
            return None
        severity = "warn"
    return {
        "clause_count": total,
        "requirement_clauses": req_clauses,
        "expected_clauses": exp_clauses,
        "must_pass": must_pass,
        "weight": weight,
        "severity": severity,
    }


def _new_result(task_dir: Path) -> dict:
    return {
        "task": task_dir.name,
        "format": None,
        "criteria": 0,
        "compound_fail": [],
        "compound_warn": [],
        "tiered_warn": [],
        "parse_errors": [],
        "ok": False,
    }


def _finalize(res: dict) -> dict:
    res["ok"] = not (
        res["compound_fail"]
        or res["compound_warn"]
        or res["tiered_warn"]
        or res["parse_errors"]
    )
    return res


def _record(
    res: dict,
    *,
    where: str,
    desc: str,
    weight,
    must_pass: bool,
    is_ekw: bool,
    extra: dict | None = None,
) -> None:
    req_clauses, exp_clauses = count_clauses(desc, is_ekw=is_ekw)
    finding = classify_compound(
        req_clauses, exp_clauses, must_pass=must_pass, weight=weight, is_ekw=is_ekw
    )
    # Round-40 tier suppressor, ported from GLM's mirror (2026-09-16) then hardened
    # against 2 real false suppressions and widened for a real colon-form gap, both
    # found by re-verifying against the real 600-task corpus -- see
    # _has_structural_tier_language()'s own comment above for the full evidence. The
    # multi-clause structure this check reacts to is, for text matching that gate, the
    # Full/Half/Zero (or Full/Partial/None) description of ONE graduated quality
    # dimension, not N independently-creditable facts bundled under one binary verdict --
    # suppressed here. The tiered_scoring_on_binary_type finding below is NOT suppressed
    # (fires regardless of this gate) and deliberately keeps using the wider, unhardened
    # _has_tiered_language() (all 6 TIER_RE alternatives) -- a false positive there only
    # adds a non-blocking warn, so the extra recall is worth more than the precision cost
    # that made the same predicate unsafe to use for suppression. GLM's own mirror-corpus
    # numbers (warn 1066->971, -95, 0 fail-tier impact) do not transfer as-is -- see this
    # file's own real full-600-task before/after in the round-40 port commit message.
    if finding and not _has_structural_tier_language(desc):
        finding.update(where=where, excerpt=desc[:400], **(extra or {}))
        res[f"compound_{finding['severity']}"].append(finding)
    if _has_tiered_language(desc):
        res["tiered_warn"].append(
            {
                "where": where,
                "weight": weight,
                "excerpt": desc[:400],
                "severity": "warn",
            }
        )


def check_task(task_dir: Path) -> dict:
    """SVC-PC: every [[criterion]] under tests/deliverables/judge.toml or
    tests/deliverables_*/judge.toml, same glob rubric_schema_check.py uses."""
    res = _new_result(task_dir)
    res["format"] = "svc-pc"
    judge_files = sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )
    if not judge_files:
        res["parse_errors"].append(
            "no judge.toml under tests/deliverables/ or tests/deliverables_*/"
        )
        return _finalize(res)

    for jf in judge_files:
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception as exc:
            res["parse_errors"].append(f"{jf.name}: {exc}")
            continue
        for c in data.get("criterion") or []:
            res["criteria"] += 1
            desc = (c.get("description") or "").strip()
            _record(
                res,
                where=f"{jf.parent.name}/{c.get('name', '?')}",
                desc=desc,
                weight=c.get("weight"),
                must_pass=_is_must_pass(desc),
                is_ekw=False,
            )
    return _finalize(res)


def _ekw_importance_map(task_dir: Path) -> dict[str, str | None]:
    """load_ekw_criteria()'s flattened dict doesn't carry metadata.importance through (no
    prior check consumed it). Re-read tests/verifier.json via the already-shared
    load_ekw_verifiers_raw() rather than editing that module for one field."""
    verifiers, _task_id, _config, parse_error = load_ekw_verifiers_raw(task_dir)
    if parse_error:
        return {}
    out: dict[str, str | None] = {}
    for v in verifiers:
        if isinstance(v, dict) and isinstance(v.get("name"), str):
            metadata = v.get("metadata") if isinstance(v.get("metadata"), dict) else {}
            out[v["name"]] = metadata.get("importance")
    return out


def check_task_ekw(task_dir: Path) -> dict:
    """EKW counterpart to check_task(): tests/verifier.json via
    ekw_verifier_json.load_ekw_criteria(), same finding shape, same classify_compound().
    """
    res = _new_result(task_dir)
    res["format"] = "ekw"
    criteria = load_ekw_criteria(task_dir)
    if not criteria:
        res["parse_errors"].append("tests/verifier.json has no verifiers")
        return _finalize(res)
    parse_error_entries = [c for c in criteria if c["name"] == "__parse_error__"]
    if parse_error_entries:
        res["parse_errors"].extend(c["description"] for c in parse_error_entries)
        return _finalize(res)

    importance_map = _ekw_importance_map(task_dir)
    for c in criteria:
        res["criteria"] += 1
        desc = (c.get("description") or "").strip()
        importance = importance_map.get(c["name"])
        _record(
            res,
            where=f"{c['group']}/{c['name']}",
            desc=desc,
            weight=c.get("weight"),
            must_pass=_is_must_pass(desc, importance=importance),
            is_ekw=True,
            extra={"importance": importance},
        )
    return _finalize(res)


def _has_svc_pc_config(task_dir: Path) -> bool:
    return bool(
        list(task_dir.glob("tests/deliverables/judge.toml"))
        or list(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def check_task_dispatch(task_dir: Path) -> dict:
    """SVC-PC's judge.toml takes precedence whenever present, matching
    deliverable_filename_check.py's and rubric_schema_check.py's own EKW-port rule."""
    if _has_svc_pc_config(task_dir):
        return check_task(task_dir)
    if has_ekw_config(task_dir):
        return check_task_ekw(task_dir)
    return check_task(task_dir)


def _print_finding(kind: str, f: dict) -> None:
    sev = f["severity"].upper()
    if kind == "compound_criterion":
        print(
            f"       [{sev}] compound_criterion {f['where']}  "
            f"({f['clause_count']} clauses, must_pass={f['must_pass']}, weight={f['weight']})"
        )
    else:
        print(
            f"       [{sev}] tiered_scoring_on_binary_type {f['where']}  (weight={f['weight']})"
        )


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

    results = [check_task_dispatch(d) for d in task_dirs]
    bad = [r for r in results if not r["ok"]]
    total_criteria = 0
    agg = {"compound_fail": 0, "compound_warn": 0, "tiered_warn": 0}
    for r in results:
        total_criteria += r["criteria"]
        flag = "OK  " if r["ok"] else ("FAIL" if r["compound_fail"] else "WARN")
        print(
            f"{flag} {r['task']:<20} [{r['format']}]  {r['criteria']:>4} criteria  "
            f"compound: {len(r['compound_fail'])} fail / {len(r['compound_warn'])} warn   "
            f"tiered: {len(r['tiered_warn'])} warn"
        )
        for w in r["parse_errors"]:
            print(f"       parse: {w}")
        for f in r["compound_fail"] + r["compound_warn"]:
            _print_finding("compound_criterion", f)
        for f in r["tiered_warn"]:
            _print_finding("tiered_scoring_on_binary_type", f)
        for k in agg:
            agg[k] += len(r[k])

    clean_tasks = len(results) - len(bad)
    print(
        f"\n{clean_tasks}/{len(results)} tasks clean  |  {total_criteria} criteria scanned  |  "
        f"compound_criterion: {agg['compound_fail']} fail, {agg['compound_warn']} warn  |  "
        f"tiered_scoring_on_binary_type: {agg['tiered_warn']} warn"
    )
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
