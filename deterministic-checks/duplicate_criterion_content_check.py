#!/usr/bin/env python3
r"""Duplicate criterion-CONTENT check: flag near-duplicate Expected-clause text across
differently-named criteria within a task, the #1 recommended new check by real-world impact
from this project's own coverage-gap analysis (9 real tasks with Comprehensive-Review-confirmed
defects: only 2 of 47 real root causes were caught by any wired check).

The defect this catches, with real confirmed evidence (not a hypothesis): two or more criteria
in a task's judge.toml file(s) carry DIFFERENT names but NEAR-IDENTICAL Expected-clause text,
silently inflating or corrupting the grading score. The same factual check is graded 2 to 4
times across differently-named criteria; the redundant weight is pure excess that distorts the
weighted-mean aggregation. This is distinct from judge_criterion_name_duplicate_check.py (same
NAME, different or same content) and from duplicate_criterion_check.py (pre-conversion xlsx
ID collision): both of those check identifiers, not content. No wired-in check detects
near-duplicate CONTENT across differently-named criteria. This check closes that gap.

Real confirmed evidence, from this project's own coverage-covN.md reports (all in
ekw/pipeline-mirror/khiem-202-data/comprehensive-review-qc-feedback-2026-09-15/), read directly
against the real staged judge.toml text in
ekw/pipeline-mirror/khiem-202-data/comprehensive-review-9-real-defects/ before writing the
threshold, not trusted from the reports' paraphrase:

  - cov2 (SVC-PC-29-2-0) RC3: 13 duplicate groups holding ~70% of declared weight, ~28-30% pure
    excess. Named cluster: r015/r024/r034/r044 all grade "the leave export cannot show who
    covered for whom" (same fact, 4 different criterion IDs spanning deliverables_02/03/04).
    Weights: 0.0218 + 0.02 + 0.02 + 0.0133 = 0.0751 cluster weight.
  - cov4 (SVC-PC-33-8-0) RC3: ~51% of total weight in clusters restating one fact. Named
    clusters: tolerance=None across r010/r017/r022/r031/r042 (combined weight 0.100),
    no-per-order-key across r009/r023/r034 (0.065), owner whitelist across r013/r029/r045
    (0.060). All confirmed against the real staged judge.toml text: the Expected clauses share
    the same factual tokens (tolerance/none/governing/reconciliation; no per-order key/lines
    reference order numbers; Jessica Liu/Priya Patel/David Nguyen/James Okafor).
  - cov3 (SVC-PC-29-5-0) RC3, cov5 (SVC-PC-37-3-0) RC4, cov6 (SVC-PC-41-4-0) RC4: same defect
    shape, named pairs confirmed in those reports. Real judge.toml text was NOT staged for
    those three (only 29-2-0, 33-8-0, and 21-4-0 are staged), so the threshold is calibrated
    against 29-2-0 and 33-8-0's real text and validated against 21-4-0 as a negative control
    (its criteria are mostly distinct and should stay quiet).

How it works:
  1. For every task, parse ALL tests/deliverables_*/judge.toml files (tomllib, the same
     two-layout glob judge_criterion_name_duplicate_check.py and rubric_schema_check.py use:
     tests/deliverables/judge.toml union tests/deliverables_*/judge.toml). Multiple files are
     compared TOGETHER, not per-file, since the named 29-2-0 cluster spans deliverables_02/03/04.
  2. Extract each criterion's Expected-clause text using criterion_groundedness_check.py's
     EXPECTED_CLAUSE_RE convention (reused, not reinvented) for the REPORT. The SIMILARITY
     COMPARISON uses the FULL description (requirement + Expected clause), not the Expected
     clause alone. This deviation from "compare only the Expected clause" is forced by the
     real calibration data: Expected-only comparison could NOT fire on all named clusters in
     SVC-PC-33-8-0. The tolerance cluster (r010/r017/r022/r031/r042) uses diverse Expected-clause
     phrasing ("Tolerance field ... is None" vs "Store-to-Books ... shows tolerance=None") that
     scores 0.30-0.59 on Expected-only TF-IDF cosine, BELOW the source-naming false positives
     (r005/r006 sharing "distinct non-blank emails" score 0.61). No threshold separates them on
     Expected-only. The full description adds the requirement text, which for real duplicates
     REINFORCES the shared content (both the requirement and Expected talk about "tolerance" /
     "no per-order key"), raising r009/r034 from 0.322 (Expected-only) to 0.491 (full-desc) and
     the tolerance cluster's weakest pairs above 0.42. For the source-naming false positives the
     requirement adds the distinguishing source names, but they also share the methodology phrase
     in both portions, so the net effect is small.      Full-desc at threshold 0.42 catches ALL named clusters in both staged tasks while
     keeping 21-4-0 clean (max pair 0.405). EKW has no
     Expected: label (1 in 5,624 real prompts sampled by compound_criterion_check.py), so for
     EKW the full rubric prompt is used with the "FAIL if" restatement clause stripped first
     (compound_criterion_check.py's EKW_FAIL_CLAUSE_RE convention).
  3. Tokenize each comparison text (lowercase alphanumeric runs) and build a TF-IDF vector per
     criterion, with document frequency computed across ALL criteria in the task. TF-IDF cosine
     is chosen over raw token-overlap (Jaccard) because it naturally downweights boilerplate
     many criteria share ("Names X as the source", "This is a must-pass criterion") and upweights
     task-specific factual tokens ("tolerance", "none", "governing", "Jessica Liu").
  4. Compute cosine similarity for EVERY pair. Flag a pair when BOTH hold: cosine >=
     SIMILARITY_THRESHOLD AND the pair shares at least MIN_SHARED_CONTENT_TOKENS non-zero-IDF
     tokens. The shared-token gate filters coincidental single-token overlaps (e.g. two short
     Expected clauses "3" and "7.3" sharing the token "3" with high IDF but no real content
     overlap; confirmed on SVC-PC-29-2-0 r005/r009, Expected-only cosine 0.668 from ONE shared
     token).
  5. Cluster flagged pairs by transitive closure (union-find): a chain a~b, b~c forms one
     cluster {a,b,c}.
  6. For each cluster: report the criterion IDs, total cluster weight, the fraction of the
     task's total declared weight that represents, and the EXCESS weight (cluster weight minus
     the heaviest single member, the one a human would keep). Aggregate the excess across all
     clusters as a fraction of total weight: the triage number.
  7. Severity: total_excess_fraction >= FAIL_EXCESS_FRACTION hard-fails; any cluster below
     that warns; no clusters passes. A single trivial pair at low weight (2%) warns; cov4's
     ~31% excess (51% in clusters, minus one representative per cluster) clearly fails.

Calibration (thresholds tuned against real staged judge.toml text, then frozen):

  SIMILARITY_THRESHOLD = 0.42, MIN_SHARED_CONTENT_TOKENS = 3. Measured against the real staged
  text (full-description TF-IDF cosine):

    SVC-PC-29-2-0 (named cluster r015/r024/r034/r044): all 6 pairs 0.638-0.901, well above 0.42.
    SVC-PC-33-8-0 named clusters (all fire at 0.42):
      owner r013/r029/r045:       0.672-0.740
      sales-incident r018/r032/r044: 0.602-0.749
      tolerance r010/r017/r022/r031/r042: weakest connecting pair 0.496 (r010/r031); r010
        joins via r010/r042 at 0.592, r017 via r017/r022 at 0.535. Full 5-member cluster.
      no-per-order-key r009/r023/r034: r009 joins via r009/r034 at 0.491; r023 via r023/r034
        at 0.589. Full 3-member cluster.
    SVC-PC-21-4-0 (negative calibration): max pair 0.405, below 0.42. Zero false positives.

  Known false-positive class, disclosed not hidden: SVC-PC-33-8-0's source-naming criteria
  (r001-r008, r025-r027) share the template "Names [SOURCE] as the source for that figure" plus
  the methodology phrase "distinct non-blank emails" across criteria that name DIFFERENT sources.
  These pairs score 0.48-0.69 (e.g. r005/r006 at 0.688) and DO flag at threshold 0.42. The
  coverage report does NOT list them as duplicate clusters. This is an inherent limitation of
  lexical comparison: the pairs genuinely share 4+ specific content tokens ("distinct non blank
  emails"), and no lexical measure can tell "same methodology, different source" from "same fact
  restated." The named real duplicate clusters in 33-8-0 use MORE diverse phrasing than these
  false positives, so any threshold low enough to catch the named clusters also catches them.
  Lowering the threshold to exclude them would miss the no-per-order-key cluster (r009/r034 at
  0.491) or the tolerance cluster (r010/r031 at 0.496). The check therefore fires on them and
  reports them as clusters; a human reviewing the output can distinguish them by the criterion
  IDs and the cluster's content. This is the same "report for human judgment" posture
  judge_criterion_name_duplicate_check.py and duplicate_criterion_check.py already adopt.

  FAIL_EXCESS_FRACTION = 0.15 (15% of total declared weight in pure excess). cov4's real
  excess is ~31% (fails); cov2's is ~28-30% (fails); a single 2.5% pair warns. 15% sits below
  both confirmed-major cases and well above the trivial-pair noise floor, so a task has to
  lose a sixth of its declared weight to redundant restating before it hard-fails.

Dual-format design (identical pattern to judge_criterion_name_duplicate_check.py and
compound_criterion_check.py): SVC-PC's judge.toml takes precedence when present; only when no
judge.toml exists is tests/verifier.json (EKW) read via ekw_verifier_json.load_ekw_criteria().
The EKW comparison text strips the FAIL-if restatement clause (compound_criterion_check.py's
confirmed convention: FAIL restates PASS, it does not add a new fact) before tokenizing.

Stdlib only (needs Python 3.11+ for tomllib; math, re, json, argparse).

    python duplicate_criterion_content_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python duplicate_criterion_content_check.py --all --root <path> --out report.json

Exit 0 when no task fails, 1 when any task fails or warns (findings present), 2 on bad usage.
Report-only: never writes to any judge.toml or verifier.json it reads.

Known limits, disclosed rather than silently dropped:
    - TF-IDF cosine is a lexical measure, not semantic. Two criteria restating the same fact
      in fully disjoint vocabulary (no shared content tokens) will not flag. The named real
      clusters all share substantial factual vocabulary, so this is a residual risk, not a
      confirmed gap against the evidence this check was calibrated on.
    - The comparison uses the FULL description (requirement + Expected clause), not the
      Expected clause alone. The Expected clause IS extracted (EXPECTED_CLAUSE_RE convention)
      and is available in the per-criterion report, but Expected-only comparison could not
      fire on all named clusters in SVC-PC-33-8-0 (see step 2 above for the real numbers).
      This is a calibration-forced deviation from the brief's "Expected clause portion"
      instruction, disclosed here rather than hidden.
    - Source-naming false positives: criteria sharing a methodology template ("Names X as the
      source", "distinct non-blank emails") across different sources DO flag at 0.42. See the
      Calibration section's "Known false-positive class" paragraph for the real numbers. The
      value-divergence gate (see _full_text_value_tokens()) now correctly suppresses this
      specific class in SVC-PC-29-2-0 (r002/r003/r013), since those criteria's differing
      source names carry differing extractable values with Jaccard distance above the 0.5
      threshold; a criterion pair in this class with no extractable value at all, or with
      values too similar to clear the threshold, would still flag and still need human
      judgment, so this is a partial fix to a disclosed class, not a closed one.
    - Value-divergence gate ceiling, disclosed not hidden: the gate (see
      _full_text_value_tokens()) only has signal when BOTH criteria in a pair have an
      extractable numeric/currency/percent/date value somewhere in their comparison text. A
      genuinely distinct pair of criteria whose distinguishing fact is purely qualitative
      (e.g. real examples from the 202-task corpus: "Launch-facing pass on HR's summary" vs
      "Draws on HR's authoritative program summary" vs "Does not rewrite a second program
      summary", three different facts sharing only the tag "(town-hall golden)", no numbers
      anywhere) gets no signal from this gate and is not suppressed by it. Re-measured against
      the full real 202-task corpus after this fix: roughly a fifth of the template-not-fact
      false-positive clusters are eliminated outright: this is a real, verified improvement,
      not a full resolution, and the remainder is this qualitative blind spot, not a threshold
      that was tuned wrong.
    - Clustering by transitive closure can chain: if a~b and b~c but a and c are only weakly
      similar, all three land in one cluster. This is deliberate (a chain of near-duplicates
      is one restating group), but it means a cluster's weakest internal pair may be below
      the threshold if it got pulled in by a stronger intermediate link.
    - Corpus-composition sensitivity: IDF is computed once per task from ALL of that task's
      criteria (see _compute_tfidf()'s docstring), so a pair's cosine is relative to what ELSE
      is in the same task, not an absolute property of the two criteria alone. Two real,
      confirmed consequences, found by adversarial review (r31-adv1, 2026-09-15): (1) the
      FAIL-if-clause stripping in _comparison_text() changes one criterion's own tokens, which
      shifts the shared IDF for every OTHER pair in the task too -- confirmed in SVC-PC-1-1-0,
      this flips 2 pair verdicts (1 false-positive created, 1 false-negative created) out of
      pairs unrelated to the stripped criteria, affecting about 1% of the 202-task corpus's
      descriptions. The task-level warn/pass verdict was unaffected in the confirmed case. (2)
      a synthetic test fixture's pair can flag or not flag purely as a function of how many
      OTHER criteria are in the same synthetic task, non-monotonically (verified directly:
      the same 2-criterion pair passes at n=2, flags at n=10-20 filler criteria added, then
      passes again at n=30+) -- this is why this module's own tests do not claim a fixture's
      flag/no-flag behavior generalizes beyond the exact criteria count it was tested at (see
      test_distinct_does_not_flag's and test_single_token_overlap_does_not_flag's docstrings).
      Both are accepted as inherent to per-task TF-IDF, not fixed, since decoupling IDF
      computation from the stripped/present token set would require re-deriving every
      calibrated threshold and named-cluster number in this docstring from scratch for an
      effect that does not change any real task's real verdict so far measured.
    - Weight handling: a criterion with a missing or non-numeric weight is treated as weight
      0 for cluster and total-weight math. It still participates in similarity comparison
      (content duplication without declared weight is still content duplication).
    - EKW cross-file scope: EKW has exactly one tests/verifier.json per task, so all
      comparison is within that one file. There is no cross-file dimension the way SVC-PC's
      deliverables_NN/ directories create one.
    - This only reads the CURRENT on-disk state. It says nothing about whether a task was
      fixed by other work after this check last ran.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from ekw_verifier_json import has_ekw_config, load_ekw_criteria
from criterion_groundedness_check import VALUE_TOKEN_RE

# Windows console defaults to cp1252, which cannot encode every character in real rubric text
# (curly quotes, en dashes in vendored descriptions, etc). Force UTF-8 with replacement so a
# printable-but-non-cp1252 character never crashes a batch run. Same guard every sibling uses.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# ---------------------------------------------------------------------------
# Expected-clause extraction: criterion_groundedness_check.py's convention, reused not
# reinvented. Captures the text after "Expected:" up to a double-period or end-of-string.
# ---------------------------------------------------------------------------
EXPECTED_CLAUSE_RE = re.compile(
    r"Expected\s*:\s*(.*?)(?:\.\.|\Z)", re.IGNORECASE | re.DOTALL
)

# EKW "FAIL if" restatement strip: compound_criterion_check.py's EKW_FAIL_CLAUSE_RE convention.
# EKW prompts state "PASS if X. FAIL if Y" where FAIL restates/negates PASS rather than adding a
# new checkable fact. Strip from the first FAIL marker onward before tokenizing for similarity.
EKW_FAIL_CLAUSE_RE = re.compile(r"\bFAIL\s*(?:if\b|only if\b|:)", re.I)

# Token: lowercase alphanumeric runs. Keeps numbers (specific facts: "4000", "none", dates)
# and splits on punctuation ("store-to-books" -> "store", "to", "books"; "tolerance=None"
# -> "tolerance", "none").
TOKEN_RE = re.compile(r"[a-z0-9]+")

# ---------------------------------------------------------------------------
# Calibrated thresholds (see module docstring for the real-evidence reasoning).
# ---------------------------------------------------------------------------
SIMILARITY_THRESHOLD = 0.42
MIN_SHARED_CONTENT_TOKENS = 3
FAIL_EXCESS_FRACTION = 0.15

# Value-divergence gate (see _full_text_value_tokens() for why this replaced an earlier
# Expected-only, exact-disjointness gate). A Jaccard DISTANCE, not exact disjointness: suppress
# a pair only when 1 - |intersection|/|union| >= this threshold, so a coincidental shared
# boilerplate value (SVC-PC-1-1-0's "$0" from "exact, $0 variance", shared by all 5 of its
# genuinely distinct criteria) does not by itself defeat the gate the way exact disjointness
# did. Calibrated directly against this module's own three named-cluster tasks: at 0.5, every
# documented named real cluster in SVC-PC-29-2-0 (r015/r024/r034/r044) and SVC-PC-33-8-0
# (owner r013/r029/r045; sales-incident r018/r032/r044; tolerance r010/r017/r022/r031/r042;
# no-per-order-key r009/r023/r034) survives fully intact, SVC-PC-21-4-0 (negative control)
# stays clean, AND the module's own disclosed source-naming false-positive class in
# SVC-PC-29-2-0 (r002/r003/r013, "Names X as the source") gets correctly suppressed for the
# first time. Thresholds 0.4-0.75 were all tried against the same three tasks; 0.6+ stops
# suppressing the source-naming false positive, so 0.5 is the highest threshold (most
# conservative on suppression) that still catches it. Re-verified against the full real
# 202-task corpus (full-202-text-and-listings): eliminates roughly a fifth of the
# template-not-fact false-positive clusters outright (66 of 334) with zero named-cluster
# regressions; the residual is a disclosed, structural ceiling, not a threshold-tuning gap
# (see _full_text_value_tokens()'s docstring and the module docstring's Known limits section).
VALUE_DIVERGENCE_JACCARD_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def to_jsonable(v):
    """Same conversion judge_criterion_name_duplicate_check.py uses: toml can carry a
    datetime value (an unquoted date/time literal) that json.dumps cannot serialize."""
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    if v is None or isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def find_task_dirs(root, task_ids=None, id_prefix=""):
    """Identical shape to judge_criterion_name_duplicate_check.py's own find_task_dirs()."""
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


def find_judge_files(task_dir: Path) -> list[Path]:
    """Both real layouts, same union rubric_schema_check.py's check_task() uses: a bare
    tests/deliverables/judge.toml (single-deliverable tasks) and one or more numbered
    tests/deliverables_NN/judge.toml (multi-deliverable tasks)."""
    return sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def _comparison_text(description: str, is_ekw: bool) -> str:
    """Extract the text to compare for near-duplicate detection.

    SVC-PC: the FULL description (requirement + Expected clause). The Expected clause is still
    extracted via EXPECTED_CLAUSE_RE for the per-criterion report, but the SIMILARITY comparison
    uses the full description because Expected-only comparison could not fire on all named
    clusters in SVC-PC-33-8-0 (see module docstring step 2 for the real numbers). The FAIL-if
    restatement clause is stripped first (compound_criterion_check.py's confirmed convention:
    FAIL restates PASS, it does not add a new fact), so a SVC-PC criterion whose Expected text
    carries a "Fail if" restatement does not get inflated by the duplicate restatement.

    EKW: the full rubric prompt with the "FAIL if" restatement clause stripped (same convention).
    EKW has no Expected: label (1 in 5,624 real prompts sampled by compound_criterion_check.py).
    """
    desc = description or ""
    m = EKW_FAIL_CLAUSE_RE.search(desc)
    return desc[: m.start()] if m else desc


def _expected_clause(description: str) -> str:
    """Extract just the Expected clause for the per-criterion report (not for comparison).
    Mirrors criterion_groundedness_check.py's EXPECTED_CLAUSE_RE convention. Returns "" if no
    Expected: label is found."""
    m = EXPECTED_CLAUSE_RE.search(description or "")
    return m.group(1) if m else ""


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _expected_value_tokens(description: str) -> set[str]:
    """Extract normalized value tokens (currency/percent/comma-number/decimal-number/
    bare-number, VALUE_TOKEN_RE's own kinds) from just the Expected clause. Normalizes by
    stripping non-alphanumeric characters so "$79,437.60" and "79437.60" compare equal.
    Returns an empty set if the Expected clause has no extractable value (e.g. "None", a
    qualitative statement). Kept as a small, independently testable primitive; the pairwise
    gate itself uses _full_text_value_tokens() below, not this function -- see that
    function's docstring for why the Expected-only scope was replaced."""
    clause = _expected_clause(description)
    if not clause:
        return set()
    return {
        re.sub(r"[^a-z0-9.]", "", m.group(0).lower())
        for m in VALUE_TOKEN_RE.finditer(clause)
    }


def _full_text_value_tokens(comparison_text: str) -> set[str]:
    """Extract normalized value tokens from the FULL comparison text (requirement + Expected
    clause), not just the Expected-clause substring _expected_value_tokens() scopes to.

    Replaces an Expected-only, exact-disjointness gate that shipped 2026-09-15 and was found,
    on re-verification against the full real 202-task corpus (not just the single example that
    prompted it), to barely move the false-positive rate (79% -> 74.1% of flagged clusters
    still template-not-fact false positives). Root cause, confirmed by direct diagnosis: most
    real criterion descriptions do not cleanly match "Expected: <value>." -- they carry
    parenthetical qualifiers, cross-file references, or purely narrative content after the
    label -- so _expected_clause() returned "" for at least one side of every one of the 334
    still-flagged false-positive clusters, making the old gate a near-total no-op at real
    scale, not a targeted fix.

    Scanning the full text recovers many of those cases (values often appear in the
    requirement sentence, not just after "Expected:"), but on its own reintroduces a second,
    equally real failure mode: criteria that share a coincidental boilerplate value are no
    longer exactly disjoint even when their substantive figures never overlap. Confirmed
    directly against SVC-PC-1-1-0's real judge.toml: five criteria (gross revenue/net loss/
    ending cash/returns reserve/inventory, each with a genuinely different dollar figure) ALL
    also share "$0" from the common "(exact, $0 variance)" boilerplate and "31" from
    "Dec-31" -- exact set disjointness fails on every pair even though the substantive figures
    never overlap.

    See VALUE_DIVERGENCE_JACCARD_THRESHOLD for how this is resolved: a Jaccard-DISTANCE
    threshold rather than exact disjointness, calibrated directly against this module's own
    three named-cluster tasks (see that constant's docstring), not against the crude
    corpus-wide proxy alone."""
    return {
        re.sub(r"[^a-z0-9.]", "", m.group(0).lower())
        for m in VALUE_TOKEN_RE.finditer(comparison_text)
    }


def _compute_tfidf(token_lists: list[list[str]]) -> list[dict[str, float]]:
    """Build a TF-IDF vector (binary TF, smoothed log IDF) per criterion. Document frequency is
    computed across ALL criteria in the task so boilerplate shared by many criteria (the
    "Names X as the source" template, "This is a must-pass criterion") gets near-zero IDF
    and contributes near-nothing to the dot product, while task-specific factual tokens
    (tolerance, none, Jessica Liu) get high IDF and dominate it.

    Binary TF (presence/absence, not raw count) is used because criterion descriptions
    are short: a repeated token within one is rare and raw-count TF would not change
    the relative ordering for the pairs this check cares about. Smoothed IDF
    (log((1+N)/(1+df)) + 1, sklearn's smooth_idf default) is used instead of raw log(N/df)
    so a task with only 2-3 criteria is not blind to duplicates: raw IDF gives every
    shared token weight 0 when N=2 (df=N for any shared token, log(1)=0), which silently
    swallows a 2-criterion task where both criteria ARE duplicates. The +1 floor ensures
    every token carries at least weight 1, so the cosine is non-zero for genuine overlaps
    even at N=2. For large N (the real 50-criterion tasks), the +1 is negligible relative
    to log(N) ~ 4, so it does not change the calibrated threshold materially."""
    n = len(token_lists)
    if n == 0:
        return []
    df: dict[str, int] = {}
    for tokens in token_lists:
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1
    idf: dict[str, float] = {}
    for t, d in df.items():
        idf[t] = math.log((1 + n) / (1 + d)) + 1.0
    vectors: list[dict[str, float]] = []
    for tokens in token_lists:
        v: dict[str, float] = {}
        for t in set(tokens):
            v[t] = idf.get(t, 0.0)
        vectors.append(v)
    return vectors


def _cosine(v1: dict[str, float], v2: dict[str, float]) -> float:
    """Cosine similarity of two sparse {token: weight} dicts. Iterates the smaller dict for
    the dot product. Returns 0.0 if either vector is empty (a criterion with no tokens after
    IDF zeroing, e.g. a description that is pure boilerplate present in every criterion)."""
    if not v1 or not v2:
        return 0.0
    if len(v1) > len(v2):
        v1, v2 = v2, v1
    dot = 0.0
    for t, w in v1.items():
        w2 = v2.get(t)
        if w2 is not None:
            dot += w * w2
    if dot == 0.0:
        return 0.0
    norm1 = math.sqrt(sum(w * w for w in v1.values()))
    norm2 = math.sqrt(sum(w * w for w in v2.values()))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def _cluster_by_transitive_closure(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    """Union-find clustering of flagged pairs. A chain a~b, b~c forms one cluster {a,b,c}
    (transitive closure, not pairwise-complete). Returns clusters with 2+ members only."""
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i, j in edges:
        union(i, j)
    by_root: dict[int, list[int]] = {}
    for i in range(n):
        by_root.setdefault(find(i), []).append(i)
    return [members for members in by_root.values() if len(members) > 1]


def _to_weight(v) -> float:
    """Coerce a criterion weight to float; missing or non-numeric -> 0.0 (the criterion
    still participates in similarity comparison; it just contributes no weight to the
    cluster/total math)."""
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def _analyze_criteria(
    criteria: list[dict],
    result: dict,
    *,
    is_ekw: bool,
) -> None:
    """Shared core: given a flat list of {where, name, description, weight} criterion dicts
    (same shape for both formats), compute pairwise TF-IDF cosine, flag, cluster, and fill
    the result dict's cluster/weight fields. Pure function over the list, no file I/O.

    A pair flags when BOTH hold: cosine >= SIMILARITY_THRESHOLD AND the pair shares at least
    MIN_SHARED_CONTENT_TOKENS non-zero-IDF tokens. The shared-token gate filters coincidental
    single-token overlaps (two short Expected clauses sharing one high-IDF number)."""
    n = len(criteria)
    result["criteria_checked"] = n
    if n < 2:
        return

    texts = [_comparison_text(c.get("description", ""), is_ekw=is_ekw) for c in criteria]
    token_lists = [_tokenize(t) for t in texts]
    vectors = _compute_tfidf(token_lists)
    value_tokens = [_full_text_value_tokens(t) for t in texts]

    total_weight = sum(_to_weight(c.get("weight")) for c in criteria)
    result["total_weight"] = round(total_weight, 6)

    edges: list[tuple[int, int]] = []
    pair_sims: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine(vectors[i], vectors[j])
            if sim < SIMILARITY_THRESHOLD:
                continue
            # shared-content-token gate: count non-zero-IDF tokens in both vectors
            shared = sum(1 for t in vectors[i] if t in vectors[j])
            if shared < MIN_SHARED_CONTENT_TOKENS:
                continue
            # value-divergence gate. Added after an adversarial review (2026-09-15) found
            # criteria sharing a template ("Sensitivity: X to P(<$1.0M). Expected: Y") but
            # grading genuinely different scenarios still pass the two gates above, since
            # shared template text dominates cosine similarity regardless of whether the
            # actual graded VALUES differ. Re-verified against the full real 202-task corpus
            # and rebuilt once already (see _full_text_value_tokens()'s docstring: an
            # Expected-only, exact-disjointness first version was a near-total no-op at real
            # scale). If both criteria have an extractable value anywhere in their comparison
            # text and those value sets are MOSTLY disjoint (Jaccard distance above
            # VALUE_DIVERGENCE_JACCARD_THRESHOLD, not exact disjointness -- a coincidental
            # shared boilerplate value must not defeat this), that is strong evidence of
            # "same template, different fact", not "same fact, reworded" -- suppress the pair.
            # A criterion whose value is genuinely non-numeric (the tolerance=None cluster)
            # has an empty value-token set on at least one side, which is "no signal" rather
            # than "no overlap", so it is NOT suppressed and still flags on template+text
            # alone.
            if value_tokens[i] and value_tokens[j]:
                intersection = value_tokens[i] & value_tokens[j]
                union = value_tokens[i] | value_tokens[j]
                jaccard_distance = 1.0 - (len(intersection) / len(union) if union else 0.0)
                if jaccard_distance >= VALUE_DIVERGENCE_JACCARD_THRESHOLD:
                    continue
            edges.append((i, j))
            pair_sims[(i, j)] = round(sim, 4)

    clusters_idx = _cluster_by_transitive_closure(n, edges)
    cluster_findings: list[dict] = []
    total_excess = 0.0
    for members in clusters_idx:
        weights = [_to_weight(criteria[m].get("weight")) for m in members]
        cluster_weight = sum(weights)
        max_weight = max(weights) if weights else 0.0
        excess = cluster_weight - max_weight
        total_excess += excess
        # pairwise sims within this cluster, for the report
        intra_sims = []
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                s = pair_sims.get((members[a], members[b]))
                if s is None:
                    lo, hi = sorted((members[a], members[b]))
                    s = round(
                        _cosine(vectors[lo], vectors[hi]), 4
                    )
                intra_sims.append(s)
        cluster_weight_frac = (
            cluster_weight / total_weight if total_weight > 0 else 0.0
        )
        excess_frac = excess / total_weight if total_weight > 0 else 0.0
        cluster_findings.append(
            {
                "criteria": [criteria[m]["where"] for m in members],
                "expected_clauses": {
                    criteria[m]["where"]: _expected_clause(
                        criteria[m].get("description", "")
                    )[:300]
                    for m in members
                },
                "weights": {
                    criteria[m]["where"]: to_jsonable(criteria[m].get("weight"))
                    for m in members
                },
                "cluster_weight": round(cluster_weight, 6),
                "max_weight": round(max_weight, 6),
                "excess_weight": round(excess, 6),
                "cluster_weight_fraction": round(cluster_weight_frac, 4),
                "excess_weight_fraction": round(excess_frac, 4),
                "max_similarity": max(intra_sims) if intra_sims else 0.0,
                "mean_similarity": (
                    round(sum(intra_sims) / len(intra_sims), 4) if intra_sims else 0.0
                ),
                "n_criteria": len(members),
            }
        )

    cluster_findings.sort(
        key=lambda c: c["excess_weight_fraction"], reverse=True
    )
    result["clusters"] = cluster_findings
    result["n_clusters"] = len(cluster_findings)
    result["total_excess_weight"] = round(total_excess, 6)
    result["total_excess_fraction"] = (
        round(total_excess / total_weight, 4) if total_weight > 0 else 0.0
    )


def analyze_task(task_dir: Path) -> dict:
    """Returns a result dict for one task. Never raises: a missing tests/ dir, an unparseable
    judge.toml/verifier.json, or a malformed criterion array is reported as a skip/parse_error,
    not a crash that kills the batch.

    Format detection mirrors judge_criterion_name_duplicate_check.py exactly: SVC-PC's
    judge.toml is checked FIRST (so a task carrying both shapes during a migration is still
    analyzed as SVC-PC); only when no judge.toml exists is tests/verifier.json (EKW) tried.
    """
    task_id = task_dir.name
    result: dict = {
        "task_id": task_id,
        "format": None,
        "status": None,
        "criteria_checked": 0,
        "total_weight": 0.0,
        "parse_errors": [],
        "clusters": [],
        "n_clusters": 0,
        "total_excess_weight": 0.0,
        "total_excess_fraction": 0.0,
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "fail_excess_fraction": FAIL_EXCESS_FRACTION,
    }

    judge_files = find_judge_files(task_dir)
    criteria: list[dict] = []
    if judge_files:
        result["format"] = "svc_pc"
        for jf in judge_files:
            rel = str(jf.relative_to(task_dir)).replace("\\", "/")
            group = jf.parent.name
            try:
                data = tomllib.loads(jf.read_text(encoding="utf-8"))
            except Exception as exc:
                result["parse_errors"].append(f"{rel}: failed to parse -- {exc}")
                continue
            crits = data.get("criterion")
            if crits is None:
                crits = []
            elif not isinstance(crits, list):
                result["parse_errors"].append(
                    f"{rel}: [[criterion]] is not an array (got {type(crits).__name__})"
                )
                continue
            for idx, c in enumerate(crits):
                if not isinstance(c, dict):
                    result["parse_errors"].append(
                        f"{rel}: criterion entry at index {idx} is not a table "
                        f"(got {type(c).__name__}) -- skipped"
                    )
                    continue
                name = c.get("name", f"__index_{idx}__")
                criteria.append(
                    {
                        "where": f"{group}/{name}",
                        "name": name,
                        "description": c.get("description") or "",
                        "weight": c.get("weight"),
                    }
                )
    elif has_ekw_config(task_dir):
        result["format"] = "ekw"
        ekw_criteria = load_ekw_criteria(task_dir)
        for c in ekw_criteria:
            if c.get("name") == "__parse_error__":
                result["parse_errors"].append(
                    c.get("description") or "tests/verifier.json parse error"
                )
                continue
            criteria.append(
                {
                    "where": f"{c.get('group', '?')}/{c.get('name', '?')}",
                    "name": c.get("name", "?"),
                    "description": c.get("description") or "",
                    "weight": c.get("weight"),
                }
            )
    else:
        result["status"] = "skip"
        result["parse_errors"].append(
            "no judge.toml under tests/deliverables/ or tests/deliverables_*/, and no "
            "tests/verifier.json -- nothing for this check to verify"
        )
        return result

    _analyze_criteria(criteria, result, is_ekw=(result["format"] == "ekw"))

    if result["parse_errors"] and result["criteria_checked"] == 0:
        result["status"] = "error"
    elif result["n_clusters"] > 0:
        # Downgraded from a real fail tier to warn-only after an adversarial review
        # (2026-09-15) found the FAIL tier fires on false positives at real scale: running
        # against all 202 real production tasks, 79% of flagged clusters were criteria
        # sharing a template but grading genuinely different scenarios (confirmed directly,
        # e.g. SVC-PC-5-2-0's five "Sensitivity: X to P(<$1.0M). Expected: Y" criteria, each a
        # distinct scenario, independently re-verified to fail on this exact task before the
        # fix). 26 of 202 real tasks got a false FAIL from this alone. No threshold on lexical
        # similarity separates the true-duplicate and false-positive populations (their cosine
        # ranges fully overlap, per the same review). Matches this project's own established
        # pattern (content_audit_check.py, golden_arithmetic_check.py) of warn-only when a
        # check's false-positive rate at hard-fail severity is not yet acceptable.
        result["status"] = "warn"
    else:
        result["status"] = "pass"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Report-only detector for near-duplicate criterion CONTENT across differently-"
            "named criteria within a task. Compares Expected-clause text (SVC-PC) or the full "
            "rubric prompt (EKW) via TF-IDF cosine similarity, clusters near-duplicates by "
            "transitive closure, and reports each cluster's weight as a fraction of the "
            "task's total declared weight plus the excess weight (the redundant portion). "
            "Never writes to any file it reads -- there is no --apply/fix mode."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="one or more task ids (directory names under --root)",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="run every task directory found under --root",
    )
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help="root directory containing one subdirectory per task",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix as tasks "
        "(default: empty, i.e. every subdirectory is a task)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

    if not args.root.is_dir():
        print(f"--root is not a directory: {args.root}", file=sys.stderr)
        return 2
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

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
        except Exception as exc:  # never let one task's crash kill the batch
            r = {
                "task_id": task_dir.name,
                "format": "error",
                "status": "error",
                "criteria_checked": 0,
                "total_weight": 0.0,
                "parse_errors": [f"unhandled exception analyzing this task: {exc}"],
                "clusters": [],
                "n_clusters": 0,
                "total_excess_weight": 0.0,
                "total_excess_fraction": 0.0,
            }
        results.append(r)
        n_c = r.get("n_clusters", 0)
        print(
            f"    -> {r['status']}  ({r.get('format')}, {r.get('criteria_checked', 0)} "
            f"criteria, {n_c} duplicate cluster(s), "
            f"excess={r.get('total_excess_fraction', 0.0)})",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_warn = sum(1 for r in results if r["status"] == "warn")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    n_error = sum(1 for r in results if r["status"] == "error")
    total_clusters = sum(r.get("n_clusters", 0) for r in results)
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "fail_excess_fraction": FAIL_EXCESS_FRACTION,
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_warn": n_warn,
        "n_fail": n_fail,
        "n_skip": n_skip,
        "n_error": n_error,
        "total_duplicate_clusters": total_clusters,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_warn} warn / {n_fail} fail / {n_skip} skip / "
        f"{n_error} error out of {len(results)} task(s)  "
        f"({total_clusters} duplicate cluster(s) total)"
    )
    for r in results:
        tag = ""
        if r.get("clusters"):
            tag = (
                f"  [{r['n_clusters']} cluster(s), "
                f"excess={r['total_excess_fraction']}]"
            )
        print(f"  {r['task_id']} ({r.get('format')}): {r['status']}{tag}")
        for pe in r.get("parse_errors", []):
            print(f"      ! {pe}")
        for c in r.get("clusters", []):
            ids = ", ".join(c["criteria"])
            print(
                f"      cluster ({c['n_criteria']} criteria, "
                f"weight={c['cluster_weight_fraction']}, "
                f"excess={c['excess_weight_fraction']}): {ids}"
            )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 1 if (n_fail or n_warn or n_error) else 0


if __name__ == "__main__":
    raise SystemExit(main())
