#!/usr/bin/env python3
"""
rubric_consistency_scan.py - GATE-V2 class P: judge.toml self-inconsistency
and hidden schemas (GATE-V2.md 1b P, map (a)/1b tightened 12:30 UTC).

Parses every tests/deliverables_*/judge.toml in a task and flags, per task:

  (a) same base figure pinned at different values or tolerances across
      criteria -- e.g. GATE-V2.md 1b: 11-3-0 r005 accepts $722,958 and
      $722,959; 22-5-0 r049/r050 pin $184,091/$1,534,091.
  (b) an instruction.md figure marked ~/about/approximately that some
      criterion's Expected text pins exactly (no tolerance qualifier) --
      e.g. 22-5-0's instruction says "~12%" while a criterion pins an
      exact dollar figure derived from it.
  (c) an Expected token matching `Acct \\d+`, a cell-reference shape
      (`[A-Z]{1,3}\\d{1,4}`, e.g. "B7", "Price_List!B7"), or a quoted
      label, that appears in NEITHER instruction.md NOR the extracted
      source text -- the map-(a) rule from GATE-V2.md 3.2 ("A token that
      appears in neither makes that criterion NONE"): "Acct 6710", "owner
      / evidence needed / resolution condition", "Price_List!B7", a
      shortened product name.

HEURISTIC NOTES (read before trusting a row)
----------------------------------------------
(a) figure clustering: one PRIMARY figure per criterion -- the first
    $-amount or N% found after the literal "Expected:" marker in its
    description (an arithmetic breakdown after that marker, e.g.
    "$754,105 = $722,959 + $31,146", is a criterion stating components of
    ONE figure, not several criteria pinning the same figure differently,
    so only the first value is used). Its label is the criterion's TITLE
    (the text before "Expected:", normalized to a keyword set with
    boilerplate words dropped). Primary figures are clustered greedily
    within a task, in judge.toml/criterion order, into the first existing
    cluster whose label keyword set overlaps >=60% (Jaccard over the
    smaller set) with the new figure's label, else a new cluster. This is
    order-dependent and can both over-merge (two genuinely different
    figures whose criteria happen to share generic title words) and
    under-merge (the same figure titled very differently in two
    criteria) -- it is a candidate generator, not a proof. A cluster is
    flagged only when it collects >=2 distinct numeric values (dollar and
    percent figures are clustered separately, never cross-compared) or
    >=2 distinct nearby tolerance annotations (~$X, |diff|<=$X, "exact",
    "$0 var", "within $X") on the SAME numeric value.
(b) approx-in-instruction: a number preceded within ~15 characters by
    "~", "about", "approximately" or "roughly" in instruction.md. Flagged
    when the identical numeric value appears in some criterion's
    description with no such qualifier (and no tolerance annotation, see
    above) within 30 characters before it -- i.e. the criterion's own
    text gives no sign it inherited the instruction's approximation.
(c) token-vs-source containment: the "extracted source" is, for
    performance, instruction.md + tests/task_prompt.txt + every
    solution/files/* document (full text, via _qc_common's
    extract_document_text) + every environment/initial_workspace/*
    xlsx/docx/csv/json/txt/md file under 2 MB (full text). pdf/pptx/doc
    are excluded from the environment side (markitdown conversion is far
    slower and, empirically in this corpus, these formats rarely carry
    GL account codes or spreadsheet cell references) and any file over
    2 MB is skipped -- both are named explicitly in the CSV's
    `source_scope_note` companion text so a MISSING verdict here is read
    as "not found in the scope this script searched," not "does not
    exist anywhere in the corpus." Cell-reference matching excludes
    Q1-Q4, H1/H2, and FYyyyy/CYyyyy-shaped tokens (quarter/half/fiscal-
    year labels that otherwise fit the `[A-Z]{1,3}\\d{1,4}` shape but are
    not cell references).

READ-ONLY on the corpus: only ever reads files, never writes into a task
directory.

Also (12:45 UTC, class P, section 4/1c) flags, per criterion:

  (d) band_text_binary: a criterion typed binary (or yes-no) whose
      description carries partial-credit band/tiered language --
      "FULL (16)"/"PARTIAL (8)"/"NONE (0)" tier labels, "N (or M) = full",
      "<=N = 0", "N = ~M pts", "pro-rata", "full/half", "tiered".
  (e) self_contradicting_threshold: a criterion whose own bands score one
      value two different ways -- a discrete "N = full" alternate that
      also satisfies a "<=N = 0" (or similar) threshold clause, or two
      discrete clauses pinning the same value to different verdicts.

Output: CSV reports/rubric_consistency.csv
  [task, kind, criterion_ids, detail]
kind is one of: duplicate_base_figure (a), approx_pinned_exact (b),
unsourced_expected_token (c), band_text_binary (d),
self_contradicting_threshold (e).

Usage:
    python3 rubric_consistency_scan.py [--corpus-root PATH] [--out PATH] [--task NAME]
        [--verdict-out PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
    DEFAULT_REPORTS_DIR,
    extract_document_text,
    list_tasks,
    normalize_keywords,
    read_text_safe,
    write_csv,
)

# ---------------------------------------------------------------------------
# Criterion loading
# ---------------------------------------------------------------------------


def load_criteria(task_dir: Path) -> list[tuple[str, str, float, str, str]]:
    """Return (criterion_name, description, weight, judge_group, crit_type)
    across every tests/deliverables_*/judge.toml in the task. crit_type is
    the raw `type = "..."` toml value (corpus-wide, only "binary" is used
    today), lowercased, or "" if absent."""
    out: list[tuple[str, str, float, str, str]] = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return out
    for group_dir in sorted(tests_dir.iterdir()):
        toml_path = group_dir / "judge.toml"
        if not toml_path.is_file():
            continue
        try:
            with toml_path.open("rb") as f:
                data = tomllib.load(f)
        except Exception:
            continue
        for crit in data.get("criterion", []):
            name = crit.get("name") or "UNNAMED"
            desc = crit.get("description") or ""
            weight = crit.get("weight")
            try:
                weight = float(weight)
            except (TypeError, ValueError):
                weight = 0.0
            crit_type = str(crit.get("type") or "").strip().lower()
            out.append((name, desc, weight, group_dir.name, crit_type))
    return out


# ---------------------------------------------------------------------------
# (a) duplicate/inconsistent base figure clustering
# ---------------------------------------------------------------------------

_DOLLAR_RE = re.compile(r"\$\(?-?[\d][\d,]*(?:\.\d+)?\)?\s?[KMB]?\b")
_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?%")
_TOLERANCE_RE = re.compile(
    r"(±\s?\$?[\d,.]+|\|diff\|\s*[≤<]\s*\$?[\d,.]+|\bexact\b|\$0 var|\bwithin\s+\$?[\d,.]+)",
    re.IGNORECASE,
)
_LABEL_WINDOW = 40
_TOL_WINDOW = 30
# Boilerplate that sits next to nearly every Expected figure in this
# corpus's judge.toml style ("Expected: $X ...", "... (FY21-actuals
# golden)") -- left in, these words dominate the keyword-overlap label and
# merge unrelated figures purely because they share a citation phrase.
_LABEL_STOPWORDS = {"expected", "golden", "actuals"}
_ANY_NUMBER_RE = re.compile(r"\$?\(?-?\d[\d,]*(?:\.\d+)?\)?%?")


_SUFFIX_MULT = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def _numeric_value(raw: str) -> float:
    negative = "(" in raw
    suffix_m = re.search(r"([KMB])\s*$", raw)
    mult = _SUFFIX_MULT.get(suffix_m.group(1), 1) if suffix_m else 1
    digits = re.sub(r"[^\d.]", "", raw)
    if not digits:
        return 0.0
    val = float(digits) * mult
    return -val if negative else val


def _figures_in(text: str) -> list[tuple[str, tuple[str, ...], str, float, str | None]]:
    """Return (kind, label_keywords, raw_value, numeric, tolerance_or_None)
    for every $ or % figure in text. label_keywords is built from the text
    immediately before the figure with every OTHER number masked out first
    (otherwise "= $722,959 + $31,146" leaks fragments like "722"/"959" into
    the label of the $31,146 figure and merges it with every other
    criterion that also cites $722,959) and boilerplate words dropped
    (_LABEL_STOPWORDS). A figure whose masked label yields fewer than 2
    keywords is still returned but with an empty label tuple so the
    clustering step treats it as unclusterable (isolated) rather than a
    high-overlap false match on one generic word."""
    out = []
    for kind, rx in (("dollar", _DOLLAR_RE), ("percent", _PERCENT_RE)):
        for m in rx.finditer(text):
            raw_window = text[max(0, m.start() - _LABEL_WINDOW):m.start()]
            masked = _ANY_NUMBER_RE.sub(" ", raw_window)
            label_kws = tuple(kw for kw in normalize_keywords(masked) if kw not in _LABEL_STOPWORDS)
            if len(label_kws) < 2:
                label_kws = ()  # unclusterable -- see docstring
            tail = text[m.end():m.end() + _TOL_WINDOW]
            head = text[max(0, m.start() - _TOL_WINDOW):m.start()]
            tol_m = _TOLERANCE_RE.search(head + " " + tail)
            tolerance = tol_m.group(0) if tol_m else None
            out.append((kind, label_kws, m.group(0), _numeric_value(m.group(0)), tolerance))
    return out


def _label_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


_CLUSTER_OVERLAP_MIN = 0.6
_EXPECTED_SPLIT_RE = re.compile(r"\bExpected\s*:\s*", re.IGNORECASE)


def _primary_figure(desc: str) -> tuple[str, tuple[str, ...], str, float, str | None] | None:
    """One figure per criterion, not every figure in its description: the
    FIRST $ or % value found after the literal "Expected:" marker (or
    anywhere in the description if there is no such marker). A criterion
    whose Expected text spells out an arithmetic breakdown ("$754,105 =
    $722,959 + $31,146") legitimately contains several DIFFERENT figures
    that are components of one another, not restatements of the same
    figure -- clustering every one of them (as an earlier version of this
    scan did) manufactured false "different values" findings out of that
    breakdown. Only the first (the criterion's own headline pinned value)
    is used for the (a) cross-criterion consistency check; label is the
    criterion's TITLE (the text before "Expected:", which is almost
    always the descriptive noun phrase identifying what the figure IS --
    "Gross FY2021 payroll", "P&L Payroll line reconciled to register
    gross" -- a much more stable signal than the words immediately
    preceding the number, which are often just "Expected:" itself)."""
    parts = _EXPECTED_SPLIT_RE.split(desc, maxsplit=1)
    title = parts[0]
    scope = parts[1] if len(parts) > 1 else desc
    dollar_m = _DOLLAR_RE.search(scope)
    percent_m = _PERCENT_RE.search(scope)
    candidates = [(m, k) for m, k in ((dollar_m, "dollar"), (percent_m, "percent")) if m]
    if not candidates:
        return None
    m, kind = min(candidates, key=lambda pair: pair[0].start())
    masked_title = _ANY_NUMBER_RE.sub(" ", title)
    label_kws = tuple(kw for kw in normalize_keywords(masked_title) if kw not in _LABEL_STOPWORDS)
    tail = scope[m.end():m.end() + _TOL_WINDOW]
    head = scope[max(0, m.start() - _TOL_WINDOW):m.start()]
    tol_m = _TOLERANCE_RE.search(head + " " + tail)
    tolerance = tol_m.group(0) if tol_m else None
    return (kind, label_kws, m.group(0), _numeric_value(m.group(0)), tolerance)


def cluster_task_figures(criteria: list[tuple[str, str, float, str]]) -> list[dict]:
    """Greedy single-pass clustering (see module docstring) of each
    criterion's PRIMARY figure (`_primary_figure`) across a task, by title
    keyword overlap >= _CLUSTER_OVERLAP_MIN. A figure with an empty label
    (title has fewer than 2 non-boilerplate keywords) is never merged
    with anything: it gets its own single-item cluster, which
    find_duplicate_figures then ignores (a cluster needs >=2 items to be a
    finding), so an unclusterable figure is silently dropped rather than
    flagged on weak evidence."""
    clusters: list[dict] = []
    for name, desc, _weight, _group, _crit_type in criteria:
        primary = _primary_figure(desc)
        if primary is None:
            continue
        kind, label_kws, raw, numeric, tolerance = primary
        label_set = set(label_kws)
        target = None
        if label_set:
            for cl in clusters:
                if cl["kind"] != kind or not cl["label_kws"]:
                    continue
                if _label_overlap(label_set, cl["label_kws"]) >= _CLUSTER_OVERLAP_MIN:
                    target = cl
                    break
        if target is None:
            target = {"kind": kind, "label_kws": set(label_set), "items": []}
            clusters.append(target)
        else:
            target["label_kws"] |= label_set
        target["items"].append((name, raw, numeric, tolerance))
    return clusters


def find_duplicate_figures(task_name: str, criteria: list[tuple[str, str, float, str]]) -> list[tuple]:
    rows = []
    for cl in cluster_task_figures(criteria):
        items = cl["items"]
        distinct_values = {round(n, 2) for _n, _r, n, _t in items}
        if len(distinct_values) > 1:
            crit_ids = ",".join(sorted({n for n, *_ in items}))
            detail = "; ".join(f"{n}={r}" for n, r, _v, _t in items)
            rows.append((task_name, "duplicate_base_figure", crit_ids, f"same figure, different values: {detail}"))
            continue
        # same value everywhere -- check for differing tolerance annotations
        tol_values = {t for *_r, t in items if t is not None}
        if len(tol_values) > 1:
            crit_ids = ",".join(sorted({n for n, *_ in items}))
            detail = "; ".join(f"{n}={r} tol={t}" for n, r, _v, t in items)
            rows.append((task_name, "duplicate_base_figure", crit_ids, f"same value, different tolerances: {detail}"))
    return rows


# ---------------------------------------------------------------------------
# (b) instruction approx figure pinned exactly in a criterion
# ---------------------------------------------------------------------------

_APPROX_RE = re.compile(
    r"(?:~|\babout\b|\bapproximately\b|\broughly\b)\s*\$?\s?(\d[\d,]*(?:\.\d+)?)\s?(%)?",
    re.IGNORECASE,
)
# A bare decimal like "0.12" in a criterion's Expected text is often the
# fraction form of a percentage the instruction states as "~12%" (e.g.
# GATE-V2.md 1b 22-5-0 r049 "Avg effective discount depth Expected: 0.12"
# against instruction "about 12%") -- $/% figures alone would miss this.
_BARE_DECIMAL_RE = re.compile(r"(?<![\d.$])0?\.(\d{1,4})(?!\d)%?")


def find_approx_pinned_exact(task_name: str, instr_text: str, criteria: list[tuple[str, str, float, str]]) -> list[tuple]:
    approx_values: set[float] = set()  # any unit (dollar or bare number)
    approx_percents: set[float] = set()  # specifically "~N%"-shaped
    for m in _APPROX_RE.finditer(instr_text):
        val = round(_numeric_value(m.group(1)), 2)
        approx_values.add(val)
        if m.group(2):
            approx_percents.add(val)
    if not approx_values:
        return []
    rows = []
    for name, desc, _weight, _group, _crit_type in criteria:
        for kind, _label_kws, raw, numeric, tolerance in _figures_in(desc):
            if round(numeric, 2) not in approx_values:
                continue
            start = desc.find(raw)
            head = desc[max(0, start - _TOL_WINDOW):start] if start >= 0 else ""
            has_qualifier = bool(_APPROX_RE.search(head)) or tolerance is not None
            if not has_qualifier:
                rows.append(
                    (
                        task_name,
                        "approx_pinned_exact",
                        name,
                        f"instruction marks {raw} approximate; criterion {name} pins it exactly: ...{desc[max(0,start-30):start+30]}...",
                    )
                )
        if not approx_percents:
            continue
        for m in _BARE_DECIMAL_RE.finditer(desc):
            frac_value = round(float("0." + m.group(1)) * 100, 2)
            if frac_value not in approx_percents:
                continue
            head = desc[max(0, m.start() - _TOL_WINDOW):m.start()]
            if _APPROX_RE.search(head):
                continue
            rows.append(
                (
                    task_name,
                    "approx_pinned_exact",
                    name,
                    f"instruction marks ~{frac_value:g}% approximate; criterion {name} pins {m.group(0)} (={frac_value:g}%) exactly: ...{desc[max(0,m.start()-30):m.start()+30]}...",
                )
            )
    return rows


# ---------------------------------------------------------------------------
# (12:45 UTC, class P) (d) band text in a binary criterion, (e)
# self-contradicting threshold
# ---------------------------------------------------------------------------

# (d) band/tiered-credit language in a criterion typed binary. Three
# shapes, corpus-verified against 25-4-0 c15/c06: "FULL (16)"/"PARTIAL
# (8)"/"NONE (0)" tier labels (r006); "<comparator> N <(parenthetical)>
# = <target>" where target is full/half/partial/none/zero/a bare number/a
# "~N pts" fraction (c15's ">=6 = full", "4 = ~4 pts", "<3 = 0"; c06's
# "15 (or 13 W-2) = full", "<=14 (e.g., 20-22) = 0"); and the standalone
# words "pro-rata" / "full/half" / "tiered".
_BAND_TIER_LABEL_RE = re.compile(r"\b(?:full|partial|none)\s*\(\s*\d+(?:\.\d+)?\s*\)", re.I)
# Capture group on the target so find_band_text_binary can classify it
# (full/zero/partial) -- a plain two-outcome "$4,390 = full; anything
# else = 0" is normal, precise binary grading, NOT a defect; only a
# THIRD, partial-credit rung (a "~N pts"/"half" target, or an explicit
# FULL(..)/PARTIAL(..)/NONE(..) tier label, or pro-rata/tiered wording)
# makes this class P. Verified against 25-4-0: c15 (">=6=full; 4=~4pts
# (pro-rata); <3=0") and c04 ("6,000=full; ...=<=2 pts; ...=0") correctly
# flag; c08/c17 ("$4,390=full; anything else=0", ">=2=full; 0 caught=0" --
# two outcomes only) correctly do NOT.
_BAND_ITEM_RE = re.compile(
    r"\b(?:>=|<=|>|<)?\s*\d+(?:\.\d+)?\s*(?:\([^)]{0,40}\))?\s*=\s*"
    r"(full|half|partial|none|zero|~?\d+(?:\.\d+)?\s*pts?|\d+)\b",
    re.I,
)
# Coordinator, 2026-09-19 22:30Z: bare "tiered" false-fired on 12-6-0 r010 ("order minimums
# differentiated by partner tier") and 17-2-0 r047 - ordinary business content the DELIVERABLE
# describes (a tiered pricing/wholesale/approval structure), not the CRITERION's own scoring band.
# "pro-rata" and "full/half" stay bare (both are specific-enough scoring vocabulary that they are
# not credibly business prose); "tiered" alone is common outside grading contexts, so it only counts
# when it sits near an actual scoring/credit word - the same proximity rule tiered_criterion_scan.py
# uses for the identical ambiguity (C1, 2026-09-19 18:40Z).
_BAND_MISC_RE = re.compile(
    r"\bpro-?rata\b|\bfull\s*/\s*half\b"
    r"|\btier(?:s|ed)?\b.{0,80}\b(?:credit|points?|marks?|scored?)\b"
    r"|\b(?:credit|points?|marks?|scored?)\b.{0,80}\btier(?:s|ed)?\b",
    re.I | re.S,
)
# "pass"/"passes"/"passed" and "grade"/"graded" were tried and dropped: both are generic criterion
# boilerplate in this corpus ("PASS if X...", any employee/product "grade") that sits near "tier"
# purely by coincidence, not because the criterion defines a scoring band. Verified false-fire on
# SVC-PC-12-6-0 r010b: "...Strategic/Hospitality accounts (Tier 3). PASS if the quantities..." -
# "PASS" is the criterion's ordinary pass-condition marker, not a tier of partial credit.
_BINARY_TYPES = {"binary", "yes-no", "yes/no"}


def find_band_text_binary(task_name: str, criteria: list[tuple[str, str, float, str, str]]) -> list[tuple]:
    """(d) A criterion typed binary whose description carries partial-
    credit band/tiered language -- GATE-V2 3.3 'Binary criteria with band
    text'. Flags the whole criterion once per criterion (not once per
    matched snippet) with the matched snippets joined in the detail."""
    rows = []
    for name, desc, _weight, _group, crit_type in criteria:
        if crit_type not in _BINARY_TYPES:
            continue
        tier_hits = [m.group(0) for m in _BAND_TIER_LABEL_RE.finditer(desc)]
        misc_hits = [m.group(0) for m in _BAND_MISC_RE.finditer(desc)]
        item_matches = list(_BAND_ITEM_RE.finditer(desc))
        verdicts = {_normalize_band_verdict(m.group(1)) for m in item_matches}
        if not (tier_hits or misc_hits or "partial" in verdicts):
            continue  # full/zero only -- ordinary precise binary grading, not a defect
        hits = tier_hits + [m.group(0) for m in item_matches] + misc_hits
        uniq = sorted(set(h.strip() for h in hits))
        rows.append((task_name, "band_text_binary", name, f"type={crit_type!r} carries band text: {uniq}"))
    return rows


# (e) self-contradicting threshold: a value that the criterion's own bands
# score two different ways -- GATE-V2 1c: 25-4-0 c06 "15 (or 13 W-2) =
# full; any count >=16 or <=14 = 0" makes 13 both full (the "or 13"
# alternate) and 0 (13 <= 14).
_CLAUSE_VERDICT_RE = re.compile(r"=\s*(full|half|partial|none|zero|~?\d+(?:\.\d+)?\s*pts?|\d[\d,]*)", re.I)
_CLAUSE_COMPARATOR_RE = re.compile(r"([<>]=?)\s*(\d[\d,]*)")
_CLAUSE_BARE_NUM_RE = re.compile(r"(?:(?<=\s)|(?<=\()|^)(\d[\d,]*)\b")
_CLAUSE_OR_ALT_RE = re.compile(r"\(or\s*(\d[\d,]*)", re.I)
_NEGATED_BEFORE_RE = re.compile(r"(?:non|not)[\s-]*$", re.I)


def _int(raw: str) -> int:
    return int(raw.replace(",", ""))


def _normalize_band_verdict(raw: str) -> str:
    raw = raw.strip().lower()
    if raw == "half":
        return "partial"
    if raw in ("full", "partial", "none", "zero"):
        return "zero" if raw == "none" else raw
    if "pts" in raw:
        return "partial"
    try:
        return "zero" if float(raw.replace(",", "")) == 0 else "partial"
    except ValueError:
        return raw


def _parse_band_clauses(desc: str) -> tuple[list[tuple[int, str]], list[tuple[str, int, str]]]:
    """Return (discrete[(value, verdict)], thresholds[(op, num, verdict)])
    parsed clause-by-clause (clauses split on ';', matching this corpus's
    judge.toml band-list style). See module docstring / GATE-V2.md 1c for
    the worked example.

    Threshold (comparator+number) pairs are collected from EVERY clause --
    precise and safe, since a comparator symbol directly on a number is
    unambiguous. Bare (non-comparator) discrete values are collected ONLY
    from the FIRST clause (the criterion's headline "correct value = full"
    statement, per this corpus's style), and only the first non-negated
    one there, plus any "(or N ...)" alternate marker in that same clause
    -- collecting bare numbers from every clause over-fires on a LATER
    clause that merely restates the headline value while describing HOW
    you got it wrong (25-4-0 c04's "leading with a non-6,000 figure
    without deriving 6,000 = <=2 pts" repeats "6,000" twice without
    proposing it as an alternately-scored value; a naive bare-number scan
    there manufactured a false collision against clause 1's "6,000 =
    full"). Heuristic -- a candidate generator, not a proof (see
    find_self_contradicting_threshold)."""
    discrete: list[tuple[int, str]] = []
    thresholds: list[tuple[str, int, str]] = []
    for clause_idx, clause in enumerate(desc.split(";")):
        vms = list(_CLAUSE_VERDICT_RE.finditer(clause))
        if not vms:
            continue
        vm = vms[-1]
        verdict = _normalize_band_verdict(vm.group(1))
        pre = clause[: vm.start()]
        comparator_spans = [m.span() for m in _CLAUSE_COMPARATOR_RE.finditer(pre)]
        for op, num in _CLAUSE_COMPARATOR_RE.findall(pre):
            thresholds.append((op, _int(num), verdict))
        if clause_idx == 0:
            for m in _CLAUSE_BARE_NUM_RE.finditer(pre):
                if any(s <= m.start() < e for s, e in comparator_spans):
                    continue
                if _NEGATED_BEFORE_RE.search(pre[max(0, m.start() - 6): m.start()]):
                    continue
                discrete.append((_int(m.group(1)), verdict))
                break  # only the headline value, not every later mention
            for m in _CLAUSE_OR_ALT_RE.finditer(pre):
                discrete.append((_int(m.group(1)), verdict))
    return discrete, thresholds


def _op_holds(op: str, val: int, num: int) -> bool:
    if op == ">=":
        return val >= num
    if op == "<=":
        return val <= num
    if op == ">":
        return val > num
    if op == "<":
        return val < num
    return False


def find_self_contradicting_threshold(task_name: str, criteria: list[tuple[str, str, float, str, str]]) -> list[tuple]:
    """(e) A criterion whose own bands score some value two different
    ways: a discrete value with verdict A that also satisfies a threshold
    clause with a different verdict B, or two discrete clauses pinning the
    same value to different verdicts. Deliberately does NOT check
    threshold-vs-threshold overlap (e.g. c15's ">=6 = full" vs "<3 = 0"
    never overlap and are not flagged here -- the 4-5 gap is the
    intentional pro-rata band, already caught by find_band_text_binary,
    not a contradiction)."""
    rows = []
    for name, desc, _weight, _group, _crit_type in criteria:
        discrete, thresholds = _parse_band_clauses(desc)
        if not discrete:
            continue
        seen: set[tuple] = set()
        hits: list[str] = []
        for val, verdict in discrete:
            for op, num, t_verdict in thresholds:
                if verdict == t_verdict or not _op_holds(op, val, num):
                    continue
                key = (val, verdict, op, num, t_verdict)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(f"{val}={verdict} but also satisfies {op}{num}={t_verdict}")
        by_value: dict[int, set[str]] = {}
        for val, verdict in discrete:
            by_value.setdefault(val, set()).add(verdict)
        for val, verdicts in by_value.items():
            if len(verdicts) > 1:
                hits.append(f"{val} scored both {sorted(verdicts)} by two discrete clauses")
        if hits:
            rows.append((task_name, "self_contradicting_threshold", name, "; ".join(hits)))
    return rows


# ---------------------------------------------------------------------------
# (c) unsourced Expected tokens
# ---------------------------------------------------------------------------

_ACCT_RE = re.compile(r"\bAcct\.?\s?\d{3,6}\b", re.IGNORECASE)
_CELLREF_RE = re.compile(r"\b(?:[A-Za-z_][A-Za-z0-9_ ]{0,30}!)?[A-Z]{1,3}\d{1,4}\b")
_CELLREF_EXCLUDE = re.compile(r"^(FY\d{2,4}|CY\d{2,4}|Q[1-4]|H[12])$", re.IGNORECASE)
_QUOTED_RE = re.compile(r"[\"‘’“”]([^\"‘’“”]{2,40})[\"‘’“”]")

_ENV_TEXT_EXTS = {"xlsx", "docx", "csv", "json", "txt", "md"}
_ENV_MAX_BYTES = 2_000_000


def extract_expected_tokens(desc: str) -> set[str]:
    tokens: set[str] = set()
    tokens |= {m.group(0) for m in _ACCT_RE.finditer(desc)}
    for m in _CELLREF_RE.finditer(desc):
        candidate = m.group(0)
        bare = candidate.split("!")[-1]
        if _CELLREF_EXCLUDE.match(bare):
            continue
        # require at least one digit AND the letter part to be short-caps,
        # already guaranteed by the regex; drop pure sheet-name-only hits
        # (no '!' and the token itself looks like a common word abbrev is
        # already filtered by the exclude list above).
        tokens.add(candidate)
    for m in _QUOTED_RE.finditer(desc):
        label = m.group(1).strip()
        if label and len(label) >= 2:
            tokens.add(label)
    return tokens


def build_task_source_blob(task_dir: Path) -> str:
    """instruction.md + task_prompt.txt + golden solution/files + a capped
    slice of environment/initial_workspace (see module docstring for the
    exact scope). One blob per task, built once and reused for every
    token containment check in that task."""
    parts = [
        read_text_safe(task_dir / "instruction.md"),
        read_text_safe(task_dir / "tests" / "task_prompt.txt"),
    ]
    solution_files = task_dir / "solution" / "files"
    if solution_files.is_dir():
        for f in sorted(solution_files.rglob("*")):
            if f.is_file():
                parts.append(extract_document_text(f))
    workspace = task_dir / "environment" / "initial_workspace"
    if workspace.is_dir():
        for f in sorted(workspace.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix.lower().lstrip(".") not in _ENV_TEXT_EXTS:
                continue
            try:
                if f.stat().st_size > _ENV_MAX_BYTES:
                    continue
            except OSError:
                continue
            parts.append(extract_document_text(f))
    return "\n".join(p for p in parts if p)


# Coordinator, 2026-09-19 22:30Z: unsourced_expected_token false-fired on SVC-PC-17-2-0 r003/r010/
# r017/r024. Verified on bytes: the source workbooks render each product as separate cells joined
# by the extractor into one linear blob ("Cirrus Pillow — Standard\n..."), and a token like "Pillow
# King" or "Complete Sleep Set — Standard (kit)" fails a raw substring check only because of a dash
# variant (em dash in the token vs a plain hyphen "-" in one workbook, or a dash the token drops
# entirely) or the surrounding whitespace the cell-by-cell linearization inserts - the underlying
# fact IS present. Normalize both the token and the source blob the same way before the containment
# check: any of em dash/en dash/hyphen becomes a single space (so "Pillow — King" and "Pillow King"
# compare equal, and an em-dash token matches a hyphen-variant source or vice versa), curly quotes
# fold to straight, and whitespace runs collapse to one space.
_DASH_CHARS = "—–‒‐‑-"  # em dash, en dash, figure dash, hyphens (incl. plain -)
_DASH_RE = re.compile("[" + _DASH_CHARS + "]")
_CURLY_QUOTE_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_WS_RE = re.compile(r"\s+")
_LEADING_ARTICLE_RE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


def _normalize_for_match(text: str, strip_leading_article: bool = False) -> str:
    text = text.translate(_CURLY_QUOTE_MAP)
    text = _DASH_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    if strip_leading_article:
        # A leading article is the exact "minor wording difference" these product-name criteria
        # themselves say a judge must accept (e.g. r003: "a leading article ... passes"); stripping
        # it from the TOKEN only (never from the source blob) is grounded in that stated tolerance,
        # not an unrequested loosening - "Cirrus Pillow Standard" is what's sourced, "the"/"a" in
        # front of it is not a separate fact that needs its own citation.
        text = _LEADING_ARTICLE_RE.sub("", text)
    return text


def find_unsourced_tokens(task_name: str, criteria: list[tuple[str, str, float, str]], source_blob: str) -> list[tuple]:
    rows = []
    normalized_blob = _normalize_for_match(source_blob)
    for name, desc, _weight, _group, _crit_type in criteria:
        for token in sorted(extract_expected_tokens(desc)):
            if token in source_blob:
                continue
            normalized_token = _normalize_for_match(token, strip_leading_article=True)
            if normalized_token and normalized_token in normalized_blob:
                continue
            rows.append((task_name, "unsourced_expected_token", name, f"{token!r} not found in instruction.md or extracted source"))
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def scan_task(task_dir: Path) -> list[tuple]:
    criteria = load_criteria(task_dir)
    if not criteria:
        return []
    instr_text = read_text_safe(task_dir / "instruction.md")
    rows: list[tuple] = []
    rows.extend(find_duplicate_figures(task_dir.name, criteria))
    rows.extend(find_approx_pinned_exact(task_dir.name, instr_text, criteria))
    rows.extend(find_band_text_binary(task_dir.name, criteria))
    rows.extend(find_self_contradicting_threshold(task_dir.name, criteria))
    source_blob = build_task_source_blob(task_dir)
    rows.extend(find_unsourced_tokens(task_dir.name, criteria, source_blob))
    return rows


# Verdict classification (see --verdict-out): duplicate_base_figure,
# band_text_binary and self_contradicting_threshold are the three kinds
# GATE-V2 names as concrete worked hard-major examples (11-3-0 r005;
# 25-4-0 c15; 25-4-0 c06) -- an objective contradiction/pattern in the
# rubric text itself, fail. approx_pinned_exact and unsourced_expected_token
# stay candidates the CR must confirm (the module docstring's own scope
# caveats: clustering is "a candidate generator, not a proof", and a
# missing token is "not found in the scope this script searched," not
# "does not exist") -- warn.
_FAIL_KINDS = {"duplicate_base_figure", "band_text_binary", "self_contradicting_threshold"}
_WARN_KINDS = {"approx_pinned_exact", "unsourced_expected_token"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT, help="corpus root directory")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "rubric_consistency.csv", help="output CSV path")
    ap.add_argument("--task", type=str, default=None, help="restrict to a single task name (debugging)")
    ap.add_argument("--verdict-out", type=Path, default=None, help="write task_id,rubric_consistency,pass|warn|fail per scanned task")
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple] = []
    rows_by_task: dict[str, list[tuple]] = {}
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        try:
            task_rows = scan_task(task_dir)
            all_rows.extend(task_rows)
            rows_by_task[task_dir.name] = task_rows
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 10 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned", file=sys.stderr)

    n = write_csv(args.out, ["task", "kind", "criterion_ids", "detail"], all_rows)
    by_kind: dict[str, int] = {}
    tasks_by_kind: dict[str, set[str]] = {}
    for r in all_rows:
        by_kind[r[1]] = by_kind.get(r[1], 0) + 1
        tasks_by_kind.setdefault(r[1], set()).add(r[0])

    print(f"rubric_consistency_scan: {n} findings across {len(tasks)} tasks, written to {args.out}")
    for kind in (
        "duplicate_base_figure",
        "approx_pinned_exact",
        "unsourced_expected_token",
        "band_text_binary",
        "self_contradicting_threshold",
    ):
        print(f"  {kind}: {by_kind.get(kind, 0)} rows, {len(tasks_by_kind.get(kind, set()))} tasks")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = []
        for task_dir in tasks:
            kinds_here = {r[1] for r in rows_by_task.get(task_dir.name, [])}
            if kinds_here & _FAIL_KINDS:
                verdict = "fail"
            elif kinds_here & _WARN_KINDS:
                verdict = "warn"
            else:
                verdict = "pass"
            verdict_rows.append((task_dir.name, verdict))
        write_csv(args.verdict_out, ["task_id", "rubric_consistency"], verdict_rows)
        by_verdict: dict[str, int] = {}
        for _t, v in verdict_rows:
            by_verdict[v] = by_verdict.get(v, 0) + 1
        print(f"rubric_consistency_scan: verdicts written to {args.verdict_out}: {by_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
