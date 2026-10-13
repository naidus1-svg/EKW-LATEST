#!/usr/bin/env python3
"""Word-ban false-trigger check (round 55, row 34): does a task's judge criteria include a
word-ban criterion (one whose grading language PROHIBITS grading/evaluation vocabulary from
appearing in the solver's output) whose ban list is broad enough to catch the task's own
LEGITIMATE finance/domain terminology, so a solver correctly using standard domain vocabulary
would be false-rejected?

Why this exists, and why it is NOT rubric_overspecification_check.py's territory: that script
answers "does a criterion pin a specific value/name the instruction left open" (a PINNING
question). Its recognized categories are count_pinned, name_pinned, value_pinned, and cell-
address pinning. A word-ban criterion is a different shape entirely: it does not pin a value,
it PROHIBITS a class of vocabulary. The false-trigger risk is also distinct from
answer_key_content_leak (leak direction) or criterion_groundedness (absence direction): the
criterion's own ban list is the problem, because it catches a word the task's own source
material uses in a legitimate domain sense. Row 34 of the consolidated failure-mode tracker
names this as NOT GUARDED by any existing check.

Real, confirmed positive controls (all three failed real Comprehensive Review, two independent
reviewer passes per task):

  SVC-PC-52-3-0, criterion f5 (tests/deliverables_03/judge.toml, weight 0.02): description reads
  "No scoring, grading, benchmark or model-name language appears Expected: none found." The
  standard treasury term "benchmark" is on the ban list. Two of three model runs lost credit for
  legitimate finance usage: eval 459932 for "3-month U.S. Treasury bill secondary-market
  benchmark" (Assumptions!B6), eval 459934 for "Benchmark rate - annual | 0.000442". The golden
  itself avoids the word entirely (zero hits across all cells), so the criterion was written to
  the golden's vocabulary, not to the instruction's requirements. This was the task's ONLY source
  of score variance (0.98 / 1.00 / 0.98).

  SVC-PC-52-5-0, criterion g7 (tests/deliverables_04/judge.toml, weight 0.014283): same template
  text, "No scoring, grading, benchmark or model-name language appears Expected: none found."
  eval 459930 was failed solely for "reasonableness benchmark" (Source_Data!D27) and "POLICY
  BENCHMARK" (Source_Data!A45), reducing reward to 0.9857. NOTE: the round 55 assignment and the
  failure-mode tracker row 34 both refer to this criterion as "r07", but the REAL criterion name
  in the real judge.toml is "g7" (deliverables_04 uses the g-prefix series). The assignment's
  "r07" does not match any criterion name in any of this task's four judge.toml files. This
  mismatch is reported in the companion note, not silently corrected.

  SVC-PC-66-2-0, criterion e4 (tests/deliverables_03/judge.toml, weight 0.01): description reads
  "No scoring, rubric, benchmark or model-name language appears anywhere in the deliverable
  Expected: none found." The ban says "scoring" but the judge extended it to catch "scorecard"
  and "grade", which are the task's OWN vendor-scorecard reconciliation vocabulary. The
  instruction itself mandates the reconciliation ("Read your computed rate against what those
  report"; "three quarterly vendor scorecards"; "The vendor scorecards on file cover the last
  three quarters"). The GOLDEN itself failed this criterion in one Oracle run (eval 459790) for
  containing "scorecard" and "grade" (tab "04_Scorecard_Recon", columns "Scorecard measure",
  letter grades A-/C for vendor performance). A criterion that fails its own task's reference
  solution is a confirmed false trigger, not a hypothesis.

What it checks, per task, per criterion (SVC-PC: every criterion in every
tests/deliverables*/judge.toml; EKW: every verifier in tests/verifier.json):

  1. WORD-BAN SHAPE DETECTION. Scans the criterion's description for a negation cue ("no",
     "without", "contains no", "must not contain", "free of", "absent", ...) within
     MAX_NEGATION_TOKEN_DISTANCE word TOKENS of a CLUSTER of 2+ UNIQUE ban-list words (scoring,
     grading, benchmark, rubric, scorecard, score, grade, self-scoring, self-assessment,
     model-name, answer-key, ...). Token distance (not character distance) is what matters:
     "no scoring" (0 tokens) and "no internal grading" (1 adjective token) are real
     prohibitions; "never delivered a scorecard" (2 tokens, one a verb) is not. The
     cluster-of-2-UNIQUE requirement distinguishes a genuine word-ban criterion (which LISTS
     multiple banned words) from a content criterion that mentions one ban word in passing or
     repeats it (SVC-PC-66-2-0's d5 "not averaged toward the scorecard figures" has one ban
     word, no cluster, correctly NOT flagged; SVC-PC-70-6-0/tp03 "never delivered a scorecard
     ... no scorecard all year" has one unique ban word repeated, correctly NOT flagged). A
     criterion banning only pure-meta words (rubric, self-assessment, answer-key, ...) with no
     finance-ambiguous word is recorded as a word-ban criterion but carries no false-trigger
     risk and does not gate.
  2. FINANCE-AMBIGUOUS WORD EXTRACTION. From the detected ban list, keeps only the words that
     ALSO have a legitimate finance/domain sense: benchmark, scoring/score/scorecard,
     grading/grade. Each maps to a set of morphological search variants (scoring -> score,
     scores, scoring, scorecard, scorecards; grading -> grade, grades, grading) and a set of
     finance collocations (benchmark -> rate/interest/treasury/bill/bond/yield/policy/...;
     score -> vendor/supplier/credit/fico/risk/quality/...; grade ->
     credit/letter/rating/investment/vendor/...). The morphological expansion is the key
     insight from SVC-PC-66-2-0: the ban says "scoring" but the judge catches "scorecard" and
     "grade" (related by root), so the search must cover all morphological relatives.
  3. LEGITIMATE-USAGE SCAN. Searches the task's solver-visible material (instruction.md + every
     readable file under environment/initial_workspace/ for SVC-PC, environment/data/ for EKW,
     reusing criterion_groundedness_check.py's own environment_signals() to build the text blob
     so the same file-reading machinery every other check in this folder uses is reused rather
     than reinvented) for the morphological variants. For each hit, checks whether a finance
     collocation appears within COLLOCATION_WINDOW chars. Two findings, in order of confidence:
     a. word_ban_false_trigger_risk (HARD, gates the exit code): a banned word's morphological
        variant appears in the solver-visible material near a finance collocation. This is the
        SVC-PC-66-2-0 shape (instruction says "vendor scorecards", "scorecard" near "vendor"
        finance collocation) and the SVC-PC-52-3-0/52-5-0 shape (environment source files contain
        "benchmark rate", "benchmark" near "rate" finance collocation).
     b. possible_word_ban_false_trigger (SOFT, never gates): a banned word's morphological
        variant appears in the solver-visible material but no finance collocation is nearby.
        Kept low-confidence because the word might be used in its meta/evaluation sense
        legitimately ("your response will be scored"), not a finance sense.
  4. Reports, per hard finding, reward_at_risk_upper_bound: the weight of the flagged criterion
     (SVC-PC: judge.toml's own weight field, parsed directly via tomllib; EKW: metadata.weight).
     Named "upper bound" matching judge_file_scope_breadth_check.py's convention: this script
     confirms the criterion CAN false-trigger, not that it DID on a specific run.

Provenance: dual-format pattern matches judge_file_scope_breadth_check.py and
criterion_groundedness_check.py exactly (ekw_verifier_json.py's load_ekw_criteria()/
has_ekw_config() for EKW; tomllib + tests/deliverables*/judge.toml for SVC-PC).
environment_signals() is imported directly from criterion_groundedness_check, per that
script's own "reused rather than reinvented" convention. SVC-PC parsing is direct via tomllib
(not rubric_text_lint.load_judge_files) to preserve the weight field, the same decision
judge_file_scope_breadth_check.py made for the same reason.

Exit 0 clean (zero HARD findings across every task), 1 findings, 2 bad usage.

    python round55-word_ban_false_trigger_check.py <package_root> [--task TASK-ID] [--json out.json]

Known limits, disclosed rather than silently dropped (READ THIS BEFORE TRUSTING A "clean"
RESULT, matching this folder's own precedent):
    - This is a WORD-PATTERN check, not a semantic one. It detects the word-ban SHAPE (negation
      + ban-list cluster) and searches for finance collocations, but it cannot prove the judge
      WILL extend "scoring" to "scorecard" the way SVC-PC-66-2-0's judge did. It flags the RISK
      that a broad ban catches domain vocabulary, confirmed against three real false-rejection
      cases, not a guaranteed rejection on every task that fires.
    - The finance collocation lists are finite and curated from the three confirmed cases
      (benchmark+rate, scorecard+vendor, grade+letter/credit, ...). A finance sense this list
      does not name would land in possible_word_ban_false_trigger (SOFT) rather than the hard
      gate. This is an under-flagging risk, disclosed: a real false trigger using an unlisted
      collocation would be reported as "possible" not "hard", and would not gate the exit code.
    - The morphological expansion (scoring -> scorecard, grading -> grade) is a fixed root-
      sharing heuristic, not a lemmatizer. A ban on "scoring" catches "scorecard" because they
      share the "score" root; a ban on a word with no finance-sense morphological relative (e.g.
      "rubric" -> no finance variant) correctly produces no false-trigger risk. An unusual
      root relationship this heuristic misses would under-flag.
    - The collocation window (COLLOCATION_WINDOW chars) is a proximity heuristic. In the real
      blob (a lowercased concatenation of every environment file's extracted text, with xlsx
      XML tags stripped to spaces), a finance term and its collocation from DIFFERENT files
      could be separated by enough unrelated text to fall outside the window. This would
      under-flag. The confirmed cases all have the collocation adjacent ("vendor scorecards",
      "benchmark rate"), so the window is set generously (60 chars) to absorb the gap.
    - environment_signals() reuses the same file-reading machinery as every other check (openpyxl
      for xlsx, pypdf for pdf, python-docx for docx, plain read for txt/csv/json). Files in
      formats that machinery cannot read are invisible to this check. An environment that
      carries "benchmark rate" only in a .xlsm (openpyxl reads it) or a .pdf (pypdf reads it) is
      covered; a format no check in this folder reads would be invisible. This is the same
      disclosed limit every environment-scanning check here carries.
    - Like every text-pattern check in this folder, this reads instruction.md, the config
      files, and the environment files only; it does not open the deliverable itself or run the
      judge. It answers "can this criterion false-trigger on domain vocabulary the task
      itself uses," not "did it false-trigger on a specific solver run."
    - A word-ban criterion detected on a task whose environment does NOT carry the banned word
      in a finance sense is reported as word_ban_criterion_detected (INFO, non-blocking) for
      visibility. This is NOT a false-trigger risk, just a record that the check found the
      shape and scanned for collocations and found none. A task flagged this way could still
      false-trigger on a solver who imports the domain term from outside the environment (e.g.
      a solver who writes "benchmark rate" from general treasury knowledge, not from a source
      file), but that is not a task-level false trigger the environment proves.

Validation against real data (2026-09-16 session; this script only reads, never writes):

  Positive control (fully validated from this worktree): SVC-PC-66-2-0, criterion e4. The
  instruction.md itself carries "vendor scorecards" (lines 7, 8, 34, 49) and "scorecard quality
  metrics" (line 49). environment_signals() for SVC-PC includes instruction.md in the blob, so
  the scan finds "scorecard" near "vendor" (finance collocation) and fires
  word_ban_false_trigger_risk. The solution/golden xlsx also contains "Scorecard measure",
  "Letter grades", "Weighted vendor score" (confirmed by direct extraction). The criterion bans
  "scoring" (morphological root of "scorecard") and the judge failed the golden on it.

  Positive control (detection confirmed, environment-scan INCONCLUSIVE from this worktree):
  SVC-PC-52-3-0 criterion f5 and SVC-PC-52-5-0 criterion g7. The word-ban shape is detected (the
  ban lists "benchmark", a finance-ambiguous word). But the legitimate usage ("benchmark rate")
  lives in the task's environment source files (financial documents about treasury rates), which
  are NOT staged in this worktree (only the flattened text-and-listings mirror with
  instruction.md + judge.toml is available; the golden deliberately avoids "benchmark" per the
  Comprehensive Review). So the scan finds no finance collocation in the available material and
  reports word_ban_criterion_detected (INFO) rather than the hard gate. The Comprehensive Review
  confirms the false trigger: agents using "Treasury bill secondary-market benchmark" and
  "Benchmark rate - annual" were false-rejected. Run against the real task package with
  environment files staged, the scan would find "benchmark" + "rate" and fire the hard gate.
  This is a DATA-AVAILABILITY limit of this worktree, not a check-logic limit.

  Clean controls: tasks with no word-ban criteria (no negation + ban-list cluster) report zero
  findings. Tasks with a word-ban criterion whose environment carries no finance-ambiguous
  vocabulary (e.g. a payroll-reconciliation task banning "grading/rubric/self-scoring" with no
  "grade" or "score" in its environment) report word_ban_criterion_detected (INFO) and exit
  clean.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

# This script lives in design-proposals/, a sibling of deterministic-checks/. Add that
# directory to sys.path so the shared imports (environment_signals, load_ekw_criteria) resolve
# the same way they do for a script that lives inside deterministic-checks/ itself.
_HERE = Path(__file__).resolve().parent
_CHECKS_DIR = _HERE.parent / "deterministic-checks"
if str(_CHECKS_DIR) not in sys.path:
    sys.path.insert(0, str(_CHECKS_DIR))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from criterion_groundedness_check import environment_signals  # noqa: E402
from ekw_verifier_json import has_ekw_config, load_ekw_criteria  # noqa: E402

# ---------------------------------------------------------------------------
# word-ban shape detection
# ---------------------------------------------------------------------------

# The grading/evaluation vocabulary that word-ban criteria prohibit. Some of these are
# finance-ambiguous (have a legitimate domain sense); others are pure meta (rubric,
# self-assessment, answer-key, ...) and carry no false-trigger risk. The cluster-of-2
# requirement uses the full list; the false-trigger scan uses only the finance-ambiguous subset.
ALL_BAN_WORDS = [
    "scoring",
    "grading",
    "benchmark",
    "rubric",
    "scorecard",
    "score",
    "grade",
    "self-scoring",
    "self-assessment",
    "model-name",
    "answer-key",
    "self-graded",
]

# Negation cues that, near a ban-list cluster, mark a criterion as word-ban shaped. Matches the
# real phrasings: "No scoring, grading, ...", "No grading / rubric / ...", "contains no
# grading, rubric, ...", "without ... scoring".
NEGATION_CUE_RE = re.compile(
    r"\b(?:no|without|contains no|must not contain|free of|absent|"
    r"does not contain|not contain|none of|never|avoid)\b",
    re.IGNORECASE,
)

# A ban-list cluster is 2+ UNIQUE ban words within this many chars of each other. Set from the
# real texts: "scoring, grading, benchmark or model-name" spans ~40 chars; "grading, rubric,
# scoring, self-assessment, answer-key" spans ~55. 120 absorbs commas/slashes/conjunctions.
# The 2+ UNIQUE requirement (not just 2+ occurrences of the same word) stops a content
# criterion that mentions one ban word twice (e.g. "scorecard" in SVC-PC-70-6-0/tp03 and
# SVC-PC-15-3-0/e11) from looking like a ban list.
CLUSTER_WINDOW = 120

# Negation-to-ban-word proximity, measured in word TOKENS (not characters). The negation cue
# must be within MAX_NEGATION_TOKEN_DISTANCE word tokens of a ban word in the cluster. A gap
# of 0 tokens ("no scoring") always matches. A gap of 1-2 tokens matches only if every
# intervening token is an adjective or determiner (ALLOWED_INTERVENING_TOKENS). A gap with any
# non-adjective/determiner token (e.g. "never delivered a scorecard" where "delivered" is a
# verb) does NOT match, even if the token count is within the limit. This replaces the old
# NEGATION_WINDOW character-distance check (80 chars) which was too loose: it matched "never
# delivered a scorecard" (negation 3 tokens from the ban word) the same as "no scoring"
# (negation directly adjacent).
MAX_NEGATION_TOKEN_DISTANCE = 2

ALLOWED_INTERVENING_TOKENS = frozenset({
    "a", "an", "the", "this", "that", "these", "those", "some", "any",
    "all", "every", "each", "either", "both", "many", "much", "few",
    "several", "such", "own", "same", "another",
    "internal", "external", "specific", "particular", "certain",
    "general", "further", "additional", "other", "various",
    "individual", "explicit", "implicit", "formal", "informal",
    "direct", "indirect", "absolute", "relative", "overall",
    "official", "actual", "underlying", "relevant", "apparent",
    "possible", "potential", "single", "multiple",
})

_TOKEN_RE = re.compile(r"\w+")

# Finance-ambiguous ban words: each maps to (morphological search variants, finance
# collocations). The morphological expansion is the key design choice: a ban on "scoring" must
# search for "scorecard" too (SVC-PC-66-2-0: ban said "scoring", judge caught "scorecard"), and
# a ban on "grading" must search for "grade" (same case: judge caught "grade").
#
# Collocations are curated from the three confirmed cases plus standard finance terminology:
#   benchmark: "benchmark rate", "Treasury bill ... benchmark", "POLICY BENCHMARK",
#       "reasonableness benchmark"
#   score/scorecard: "vendor scorecard", "scorecard quality metrics", "Weighted vendor score",
#       "credit score", "FICO score"
#   grade/grading: "Letter grades", "credit grade", "investment grade", "vendor grade"
FINANCE_AMBIGUOUS_BANS: dict[str, tuple[list[str], list[str]]] = {
    "benchmark": (
        ["benchmark", "benchmarks"],
        [
            "rate",
            "interest",
            "treasury",
            "bill",
            "bond",
            "index",
            "return",
            "yield",
            "portfolio",
            "secondary",
            "market",
            "libor",
            "sofr",
            "fed",
            "policy",
            "reasonableness",
            "reference",
        ],
    ),
    "scoring": (
        ["score", "scores", "scoring", "scorecard", "scorecards"],
        [
            "vendor",
            "supplier",
            "credit",
            "fico",
            "risk",
            "quality",
            "performance",
            "measure",
            "metric",
            "report",
            "recon",
            "reconcil",
        ],
    ),
    "score": (
        ["score", "scores", "scoring", "scorecard", "scorecards"],
        [
            "vendor",
            "supplier",
            "credit",
            "fico",
            "risk",
            "quality",
            "performance",
            "measure",
            "metric",
            "report",
            "recon",
            "reconcil",
        ],
    ),
    "scorecard": (
        ["scorecard", "scorecards"],
        [
            "vendor",
            "supplier",
            "quality",
            "performance",
            "measure",
            "metric",
            "report",
            "recon",
            "reconcil",
        ],
    ),
    "grading": (
        ["grade", "grades", "grading"],
        [
            "credit",
            "letter",
            "rating",
            "investment",
            "vendor",
            "supplier",
            "performance",
            "scale",
            "risk",
        ],
    ),
    "grade": (
        ["grade", "grades", "grading"],
        [
            "credit",
            "letter",
            "rating",
            "investment",
            "vendor",
            "supplier",
            "performance",
            "scale",
            "risk",
        ],
    ),
}

# How close a finance collocation must be to a banned-word hit to count as a finance-sense
# usage. The real cases are all adjacent ("vendor scorecards", "benchmark rate"), but the
# extracted blob can insert spacing from XML tag stripping, so 60 chars absorbs the gap.
COLLOCATION_WINDOW = 60

# Pre-compile a regex per finance-ambiguous ban word for its morphological variants.
_VARIANT_RES: dict[str, list[re.Pattern]] = {}
for _bw, (_variants, _collocs) in FINANCE_AMBIGUOUS_BANS.items():
    _VARIANT_RES[_bw] = [
        re.compile(rf"\b{re.escape(v)}\b", re.IGNORECASE) for v in _variants
    ]


def _negation_near_banword(
    description: str, neg_matches: list[tuple[int, int]], cluster: list[tuple[int, int, str]]
) -> bool:
    """Check if any negation cue is within MAX_NEGATION_TOKEN_DISTANCE word tokens of any ban
    word in the cluster. Token distance (not character distance) is what matters: "no scoring"
    (0 tokens) and "no internal grading" (1 adjective token) are real prohibitions; "never
    delivered a scorecard" (2 tokens, one of which is a verb) is not, because "delivered" is
    not an adjective/determiner.

    A gap of 0 tokens always matches. A gap of 1-2 tokens matches only if every token is an
    adjective or determiner (in ALLOWED_INTERVENING_TOKENS). A gap with any non-adjective/
    determiner token (verb, noun, etc.) does not match, even if the token count is within the
    limit.
    """
    for neg_start, neg_end in neg_matches:
        for ban_start, ban_end, _bw in cluster:
            if ban_start >= neg_end:
                gap = description[neg_end:ban_start]
            elif ban_end <= neg_start:
                gap = description[ban_end:neg_start]
            else:
                continue
            tokens = _TOKEN_RE.findall(gap)
            n = len(tokens)
            if n == 0:
                return True
            if n <= MAX_NEGATION_TOKEN_DISTANCE and all(
                t.lower() in ALLOWED_INTERVENING_TOKENS for t in tokens
            ):
                return True
    return False


def _detect_word_ban(description: str):
    """Return (is_word_ban, finance_banned_words) for a criterion description.

    is_word_ban: True if the description has a word-ban shape (negation cue within
        MAX_NEGATION_TOKEN_DISTANCE tokens of a cluster of 2+ UNIQUE ban-list words).
    finance_banned_words: the subset of detected ban words that are finance-ambiguous (have a
        legitimate domain sense). Empty if the ban list is pure-meta only (rubric,
        self-assessment, ...) or if no ban word is finance-ambiguous.
    """
    # Find all ban-word occurrences with positions (start, end, word).
    occurrences = []
    for word in ALL_BAN_WORDS:
        for m in re.finditer(rf"\b{re.escape(word)}\b", description, re.IGNORECASE):
            occurrences.append((m.start(), m.end(), word))
    occurrences.sort()
    if len(occurrences) < 2:
        return False, []

    # Find all negation cue positions (start, end) for token-distance checking.
    neg_matches = [(m.start(), m.end()) for m in NEGATION_CUE_RE.finditer(description)]

    # Scan for a cluster of 2+ UNIQUE ban words within CLUSTER_WINDOW, with a negation cue
    # within MAX_NEGATION_TOKEN_DISTANCE tokens of a ban word in the cluster.
    for i in range(len(occurrences)):
        cluster = [occurrences[i]]
        for j in range(i + 1, len(occurrences)):
            if occurrences[j][0] - occurrences[i][0] <= CLUSTER_WINDOW:
                cluster.append(occurrences[j])
            else:
                break
        if len(cluster) < 2:
            continue
        unique_words = {w for _, _, w in cluster}
        if len(unique_words) < 2:
            continue
        if not _negation_near_banword(description, neg_matches, cluster):
            continue
        # Found a word-ban shape. Extract the finance-ambiguous subset.
        finance_banned = [w for w in unique_words if w in FINANCE_AMBIGUOUS_BANS]
        return True, finance_banned

    return False, []


def _scan_legitimate_usage(visible_text: str, finance_banned_words: list[str]):
    """Search solver-visible material for banned words in finance context.

    Returns (hard_results, soft_results), ONE entry per ban_word (not per text hit, so a
    criterion whose environment mentions "scorecard" 15 times produces one finding, not 15).
    hard_results: list of {ban_word, variants_found, collocations_found, context}.
        A morphological variant appears near a finance collocation (the false-trigger shape).
    soft_results: list of {ban_word, variants_found, context}.
        A variant appears but no collocation is nearby. Reported only when no hard result
        exists for that ban_word, so a ban_word with any finance-collocated hit suppresses
        its own soft hits.
    """
    hard_results = []
    soft_results = []
    for bw in finance_banned_words:
        _variants, collocations = FINANCE_AMBIGUOUS_BANS[bw]
        colloc_patterns = [
            (c, re.compile(rf"\b{re.escape(c)}\b", re.IGNORECASE)) for c in collocations
        ]
        variants_seen: set[str] = set()
        collocs_seen: set[str] = set()
        hard_ctx: str | None = None
        soft_ctx: str | None = None
        for v_re in _VARIANT_RES[bw]:
            for m in v_re.finditer(visible_text):
                variants_seen.add(m.group(0).lower())
                ctx_start = max(0, m.start() - COLLOCATION_WINDOW)
                ctx_end = min(len(visible_text), m.end() + COLLOCATION_WINDOW)
                ctx = visible_text[ctx_start:ctx_end]
                snippet = re.sub(r"\s+", " ", ctx).strip()[:140]
                matched_colloc = None
                for c_word, c_re in colloc_patterns:
                    if c_re.search(ctx):
                        matched_colloc = c_word
                        break
                if matched_colloc:
                    collocs_seen.add(matched_colloc)
                    if hard_ctx is None:
                        hard_ctx = snippet
                else:
                    if soft_ctx is None:
                        soft_ctx = snippet
        if collocs_seen:
            hard_results.append(
                {
                    "ban_word": bw,
                    "variants_found": sorted(variants_seen),
                    "collocations_found": sorted(collocs_seen),
                    "context": hard_ctx or "",
                }
            )
        elif variants_seen:
            soft_results.append(
                {
                    "ban_word": bw,
                    "variants_found": sorted(variants_seen),
                    "context": soft_ctx or "",
                }
            )
    return hard_results, soft_results


# ---------------------------------------------------------------------------
# SVC-PC: judge.toml, parsed directly (weight-preserving, matching the template's decision)
# ---------------------------------------------------------------------------


def _load_instruction(task_dir: Path) -> str:
    p = task_dir / "instruction.md"
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def _load_svc_pc_groups(task_dir: Path):
    """Every tests/deliverables*/judge.toml under a task dir, parsed directly via tomllib.
    Returns a list of {path, criteria: [{name, description, weight}], parse_error}. Same direct-
    parse decision as judge_file_scope_breadth_check.py (preserves the weight field that
    rubric_text_lint.load_judge_files drops)."""
    out = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return out
    for jt in sorted(tests_dir.glob("deliverables*/judge.toml")):
        rel = str(jt.relative_to(task_dir)).replace("\\", "/")
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            out.append({"path": rel, "criteria": [], "parse_error": str(e)})
            continue
        criteria = [
            {
                "name": c.get("name"),
                "description": c.get("description") or "",
                "weight": c.get("weight"),
            }
            for c in data.get("criterion") or []
        ]
        out.append({"path": rel, "criteria": criteria, "parse_error": None})
    return out


def _has_svc_pc_config(task_dir: Path) -> bool:
    tests_dir = task_dir / "tests"
    return tests_dir.is_dir() and any(tests_dir.glob("deliverables*/judge.toml"))


# ---------------------------------------------------------------------------
# shared per-task analysis
# ---------------------------------------------------------------------------


def _base_result(task_dir: Path, fmt: str) -> dict:
    return {
        "task": task_dir.name,
        "format": fmt,
        "groups_checked": 0,
        "n_criteria": 0,
        "word_ban_criteria": [],
        "findings": [],
        "possible_findings": [],
        "parse_errors": [],
        "ok": False,
    }


def _build_visible_text(task_dir: Path, ekw: bool) -> str:
    """Solver-visible text: environment blob (from environment_signals) + instruction.md.

    For SVC-PC, environment_signals already folds instruction.md into the blob; appending again
    is redundant but harmless (_scan_legitimate_usage deduplicates variants into a set, so a
    word appearing in both the blob and the appended instruction counts once per ban_word).
    For EKW, environment_signals reads environment/data/ only and does NOT include
    instruction.md, so this append is what makes the instruction scannable."""
    _nums, blob, _basenames, _instr = environment_signals(task_dir, ekw=ekw)
    instr = _load_instruction(task_dir)
    return blob + "\n" + instr.lower()


def _analyze_criteria(res, group_label, criteria, visible_text):
    for c in criteria:
        res["n_criteria"] += 1
        desc = c.get("description") or ""
        is_ban, finance_banned = _detect_word_ban(desc)
        if not is_ban:
            continue
        cname = c.get("name")
        weight = c.get("weight")
        ban_record = {
            "group": group_label,
            "criterion": cname,
            "weight": weight,
            "finance_banned_words": finance_banned,
        }
        res["word_ban_criteria"].append(ban_record)
        if not finance_banned:
            # Pure-meta ban (rubric, self-assessment, ...): no false-trigger risk.
            continue
        hard_results, soft_results = _scan_legitimate_usage(
            visible_text, finance_banned
        )
        for h in hard_results:
            variants_str = ", ".join(h["variants_found"])
            collocs_str = ", ".join(h["collocations_found"])
            res["findings"].append(
                {
                    "kind": "word_ban_false_trigger_risk",
                    "group": group_label,
                    "criterion": cname,
                    "weight": weight,
                    "ban_word": h["ban_word"],
                    "variants_found": h["variants_found"],
                    "collocations_found": h["collocations_found"],
                    "context": h["context"],
                    "reason": (
                        f"criterion '{cname}' bans '{h['ban_word']}' (finance-ambiguous). "
                        f"Morphological variants [{variants_str}] appear in the task's "
                        f"solver-visible material near finance collocations [{collocs_str}] "
                        f"(context: \"{h['context']}\"). A solver using this standard domain "
                        f"terminology would be false-rejected by this criterion."
                    ),
                }
            )
        for h in soft_results:
            variants_str = ", ".join(h["variants_found"])
            res["possible_findings"].append(
                {
                    "kind": "possible_word_ban_false_trigger",
                    "group": group_label,
                    "criterion": cname,
                    "ban_word": h["ban_word"],
                    "variants_found": h["variants_found"],
                    "context": h["context"],
                    "reason": (
                        f"criterion '{cname}' bans '{h['ban_word']}' (finance-ambiguous), and "
                        f"variants [{variants_str}] appear in solver-visible material, but no "
                        f"finance collocation is nearby. May be a meta/evaluation sense rather "
                        f"than a domain sense; kept non-blocking."
                    ),
                }
            )


def check_task_svc_pc(task_dir: Path) -> dict:
    res = _base_result(task_dir, "svc_pc")
    groups = _load_svc_pc_groups(task_dir)
    if not groups:
        res["parse_errors"].append(
            "no tests/deliverables*/judge.toml found for this task"
        )
        res["ok"] = not res["findings"] and not res["parse_errors"]
        return res

    visible_text = _build_visible_text(task_dir, ekw=False)

    for g in groups:
        if g["parse_error"]:
            res["parse_errors"].append(
                f"{g['path']}: judge.toml failed to parse: {g['parse_error']}"
            )
            continue
        res["groups_checked"] += 1
        _analyze_criteria(res, g["path"], g["criteria"], visible_text)

    res["ok"] = not res["findings"] and not res["parse_errors"]
    return res


def check_task_ekw(task_dir: Path) -> dict:
    """EKW: each verifier is its own group (no judge.toml-style shared scope, per
    ekw_verifier_json.py's own docstring), so the per-group check IS the per-criterion check.
    """
    res = _base_result(task_dir, "ekw")
    criteria = load_ekw_criteria(task_dir)
    parse_error_entries = [c for c in criteria if c["name"] == "__parse_error__"]
    if parse_error_entries:
        for c in parse_error_entries:
            res["parse_errors"].append(c["description"])
        return res
    if not criteria:
        res["parse_errors"].append("tests/verifier.json has zero verifiers")
        return res

    visible_text = _build_visible_text(task_dir, ekw=True)

    for c in criteria:
        res["groups_checked"] += 1
        _analyze_criteria(res, c["group"], [c], visible_text)

    res["ok"] = not res["findings"] and not res["parse_errors"]
    return res


def check_task_dispatch(task_dir: Path) -> dict:
    """SVC-PC takes precedence when both configs exist, matching every other dual-format check
    in this folder."""
    if _has_svc_pc_config(task_dir):
        return check_task_svc_pc(task_dir)
    if has_ekw_config(task_dir):
        return check_task_ekw(task_dir)
    res = _base_result(task_dir, "unknown")
    res["parse_errors"].append(
        "no tests/deliverables*/judge.toml or tests/verifier.json found"
    )
    return res


# ---------------------------------------------------------------------------
# CLI (same shape as judge_file_scope_breadth_check.py's main())
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
    n_possible_only = sum(1 for r in results if r["ok"] and r["possible_findings"])
    n_word_ban_detected = sum(1 for r in results if r["word_ban_criteria"])
    # reward_at_risk_upper_bound: sum the weight of each UNIQUE flagged criterion (one
    # criterion with 15 word hits counts once, not 15x), matching judge_file_scope_breadth
    # check.py's "upper bound" convention (the weight that COULD be gamed, not a count).
    flagged_criteria: set[tuple] = set()
    total_reward_at_risk = 0.0
    for r in results:
        for f in r["findings"]:
            key = (r["task"], f["group"], f["criterion"])
            if key in flagged_criteria:
                continue
            flagged_criteria.add(key)
            if isinstance(f.get("weight"), (int, float)):
                total_reward_at_risk += f["weight"]

    for r in results:
        flag = "OK  " if r["ok"] else "FAIL"
        print(
            f"{flag} {r['task']:<20} [{r['format']:<6}] "
            f"{r['groups_checked']:>3} group(s)  "
            f"{r['n_criteria']:>3} criteria  "
            f"{len(r['word_ban_criteria']):>2} word-ban  "
            f"{len(r['findings']):>2} findings  {len(r['possible_findings']):>2} possible"
        )
        for w in r["parse_errors"]:
            print(f"       parse: {w}")
        for wb in r["word_ban_criteria"]:
            tag = (
                "FALSE_TRIGGER"
                if any(
                    f["criterion"] == wb["criterion"] and f["group"] == wb["group"]
                    for f in r["findings"]
                )
                else "DETECTED"
            )
            fb = (
                ",".join(wb["finance_banned_words"])
                if wb["finance_banned_words"]
                else "(pure-meta)"
            )
            print(
                f"       WORD_BAN_{tag} [{wb['group']}/{wb['criterion']}] "
                f"w={wb['weight']} bans: {fb}"
            )
        for f in r["findings"]:
            variants_str = ", ".join(f["variants_found"])
            collocs_str = ", ".join(f["collocations_found"])
            print(
                f"       FALSE_TRIGGER [{f['group']}/{f['criterion']}]: ban '{f['ban_word']}' "
                f"-> variants [{variants_str}] near [{collocs_str}] (w={f['weight']})"
            )
            print(f"         context: {f['context'][:120]}")
        for f in r["possible_findings"]:
            variants_str = ", ".join(f["variants_found"])
            print(
                f"       possible [{f['group']}/{f['criterion']}]: variants "
                f"[{variants_str}] (ban '{f['ban_word']}'), no finance collocation nearby"
            )

    print(
        f"\n{len(results) - len(bad)}/{len(results)} clean "
        f"({n_possible_only} carry only possible findings, non-blocking), "
        f"{len(bad)} FAIL  |  {n_word_ban_detected}/{len(results)} tasks had >=1 word-ban "
        f"criterion  |  total reward_at_risk_upper_bound: {round(total_reward_at_risk, 6)}"
    )
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
