#!/usr/bin/env python3
"""Spelling check for instruction.md and judge.toml description text across the SVC-PC task
mirror. Closes defect class U12 (spelling/grammar errors in rubric/instruction prose), named in
Andrew's own review (AR-01) as a real, never-prioritized quick win.

Why this exists: a misspelled word in instruction.md or a rubric criterion's description is a
real authoring defect. A solver may misread a garbled instruction; a judge model may penalize a
correct answer that spells a term the way the instruction does rather than the way the (misspelled)
rubric expects; or the typo is simply unprofessional in a deliverable the solver is told to
emulate. None of the existing checks in this folder scan prose for spelling; they lint structure
(rubric_schema_check), formulas (formula_health_check), terminology codes
(undisclosed_terminology_check), or criterion text shape (rubric_text_lint) -- never plain
spelling. This script fills that gap.

What it checks, per task, per file:
  1. Reads instruction.md (plain markdown text) and every tests/deliverables*/judge.toml's
     [[criterion]] description strings (the human-authored prose, not the structural TOML).
  2. Tokenizes to alpha words (length >= 2), then asks pyspellchecker whether each is in its
     English dictionary. pyspellchecker is a pure-Python, dependency-free spellchecker that
     bundles its own word-frequency dictionary (no external service, no Java backend). It is a
     common, lightweight dependency -- the only non-stdlib import this script needs. Chosen
     after confirming the environment has no stdlib spellchecker and no system wordlist
     (/usr/share/dict absent), and that language-tool-python (the grammar alternative) requires a
     running Java/LanguageTool server, which is too heavy for this task per the brief's
     "do not over-engineer grammar" instruction. Grammar detection is therefore OUT OF SCOPE
     here; spelling alone is the real win the brief sanctioned.
  3. Excludes tokens that are almost certainly not misspellings, to keep the signal honest:
     - ALL-CAPS tokens of length >= 2 (acronyms: SKU, NPS, AOV, GMV, GL, SVB, KPI, CEO, COO).
     - Tokens containing any digit (codes, identifiers, FY2021, Q1, OI-01).
     - Underscore-joined or dash-joined code identifiers (Cite_L2_01, Open_Items).
     - Filenames (anything with a known document extension).
     - A denylist of proper nouns / domain terms observed in this corpus (company names, person
       names, product names). This is necessarily incomplete; every finding carries its line +
       context so a human clears the residual false positives in seconds.
  4. Reports each unknown token with file, line number, the matching line's text, and
     pyspellchecker's top correction candidate.

Exit 0 clean (zero misspelled tokens after exclusions), 1 findings, 2 bad usage. NOT a gate
by default: a misspelling is a quality defect, not a structural impossibility, so this script
surfaces findings for human review rather than blocking a build.

    python spelling_grammar_check.py <package_root> [--task TASK-ID] [--json out.json]

Dual-format: SVC-PC (tomllib + tests/deliverables*/judge.toml) takes precedence; EKW
(tests/verifier.json via ekw_verifier_json.load_ekw_criteria()) is also scanned, matching this
folder's check_task_dispatch() convention (rubric_schema_check.py et al).

Provenance: built fresh for round 8 (2026-09-15). Naming follows this folder's
<descriptive_name>_check.py convention. Dependency: pyspellchecker (pip install pyspellchecker,
pure-Python wheel, ~7MB bundled dictionary, no compiled extensions).

Known limits, disclosed rather than silently dropped:
  - Proper-noun false positives: pyspellchecker's dictionary does not contain person names,
    company names, or product names. The denylist catches the ones this corpus actually uses,
    but a new proper noun this script has not seen will still be flagged. Each finding carries
    context so these are trivial to clear.
  - Grammar is out of scope (see "Why this exists"). A real grammar check needs
    language-tool-python + a Java backend; spelling is the sanctioned quick win.
  - British/American spelling: pyspellchecker's default dictionary is American English
    (en_US). A legitimate British spelling ("organisation") will be flagged as unknown; the
    correction candidate usually makes the dialect obvious. Switching the dictionary to en_GB
    is a one-line change (SpellChecker(language="en_GB")) if this corpus turns out to prefer
    British spelling.
  - Hyphenated compounds and apostrophe-bearing words are split on non-alpha characters, so
    "decision-making" is checked as "decision" and "making" (both known) rather than as one
    token; this is the safe default (avoids false-flagging valid hyphenations) but means a
    misspelling inside a hyphenated compound is reported on the misspelled half only.
  - A misspelling INSIDE a proper noun that is on the denylist is hidden (the whole token is
    skipped). This is an acceptable trade-off: proper-noun typos are rare and the denylist is
    small.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from spellchecker import SpellChecker
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "needs pyspellchecker (pip install pyspellchecker; pure-Python, no compiled deps)\n"
    )
    raise SystemExit(2)

try:
    from ekw_verifier_json import has_ekw_config, load_ekw_criteria
except ImportError:  # pragma: no cover
    has_ekw_config = None
    load_ekw_criteria = None

SPELL = SpellChecker(language="en")

# Documents the judge/extractor never spellcheck (filenames, extensions, code).
EXT_RE = re.compile(
    r"\b[\w.-]+\.(?:docx|xlsx|pptx|pdf|csv|txt|xlsm|doc|json|toml|md)\b", re.I
)
CODE_TOKEN_RE = re.compile(
    r"[A-Za-z]*[_-][A-Za-z0-9_-]+"
)  # underscore/dash-joined identifiers
WORD_RE = re.compile(r"[A-Za-z]+")

# Proper nouns / domain terms observed in the SVC-PC corpus. Lowercased for compare. Kept
# small on purpose: every added term hides a future typo inside it, so only high-frequency
# corpus terms go here.
PROPER_NOUN_DENYLIST = {
    # company / product names
    "quickbooks",
    "shopify",
    "hubspot",
    "zendesk",
    "workday",
    "cirrus",
    "sendgrid",
    "mailchimp",
    "iconfinder",
    "hotjar",
    "swiftship",
    "swiftshipexpress",
    "linear",
    "canva",
    "markitdown",
    "openpyxl",
    "python-docx",
    "pypdf",
    "perplexity",
    "novatex",
    "drift",
    "oakmont",
    "apex",
    "hiscox",
    "tiktok",
    "okta",
    "cloudhost",
    "stripe",
    "twilio",
    "intercom",
    "segment",
    "amplitude",
    "mixpanel",
    "datadog",
    "trialbalance",
    # person names (first + last, observed across the 56-task mirror)
    "sarah",
    "jessica",
    "priya",
    "alice",
    "chen",
    "liu",
    "patel",
    "laura",
    "martinez",
    "elena",
    "torres",
    "brian",
    "chang",
    "kevin",
    "michelle",
    "khiem",
    "andrew",
    "sonu",
    "pranaya",
    "mithil",
    "riju",
    "krys",
    "zheng",
    "jonathan",
    "dodson",
    "luiz",
    "araujo",
    "zoe",
    "zhou",
    "shyam",
    "jafar",
    "okafor",
    "saito",
    "whitfield",
    "hoffman",
    "baker",
    "nguyen",
    "wright",
    "rivera",
    "marcus",
    "kim",
    "tom",
    # place names
    "asheville",
    "nashville",
    "ontario",
    # domain terms that are genuinely one word but not in pyspellchecker's en_US dict
    "kpi",
    "aoi",
    "reorder",
    "tieout",
    "workstream",
    "backlog",
    "scorecard",
    "subledger",
    "restatement",
    "tieouts",
    "stockout",
    "stockouts",
    "counterparty",
    "counterparties",
    "metadata",
    "lifecycle",
    "workpaper",
    "dataset",
    "datasets",
    "onboarding",
    "onboarded",
    "offboarding",
    "chargeback",
    "chargebacks",
    "backorder",
    "backorders",
    "budgetable",
    "unreviewable",
    "unstaffed",
    "unexecuted",
    "unsourced",
    "nonmatching",
    "unmeetable",
    "followable",
    "rebalancing",
    "influencer",
    "databook",
    "actuals",
    "financials",
    "deliverables",
    "filenames",
    "intra",
    "cyber",
    "recalibration",
    "putaway",
    "restocking",
    "multistate",
    "enablement",
    "rollout",
    "failover",
    "sublimits",
    "gameability",
    "greenwashing",
    "roadmap",
    "callout",
    "lineitem",
    "lineitems",
    "tercile",
    "populatable",
    "presales",
    "unpriceable",
    "rollforward",
    "annualizes",
    "annualize",
    "tokenization",
    "barcode",
    "signable",
    "hardcoded",
    "establishable",
    "sublimit",
    "lineate",
    "candela",
    "rebateable",
    "monetised",
    "monetize",
    "authorised",
    "authorized",
    "filename",
    "filenames",
    "cutover",
    "workflow",
    "drawdown",
    "auditable",
    "timestamp",
    "survivorship",
    "webhook",
    "webhooks",
    "unbilled",
    "uncited",
    "unevidenced",
    "unretrieved",
    "reportability",
    "restockable",
    "admins",
    "admin",
    "majeure",
    "snowflake",
    "elementary",
    "pagerduty",
    "opsgenie",
    "bigquery",
    "fivetran",
    "airbyte",
    # British spellings (pyspellchecker's default is en_US; these are legitimate, not typos)
    "programme",
    "behaviour",
    "centre",
    "characterised",
    "authorisation",
    "labour",
    "organisation",
    "organise",
    "realise",
    "recognise",
    "analyse",
    "optimise",
    "prioritise",
    "minimise",
    "maximise",
    "summarise",
    "standardise",
    "emphasise",
    "honoured",
    "itemising",
    "itemised",
    "characterises",
    "neighbouring",
    "memorialises",
    "penalised",
    "unrecognised",
    "defence",
    "doesn",
    "memorialize",
    # standards / certification names
    "certipur",
}

# File extensions that appear as standalone tokens after splitting filenames on non-alpha.
# Catches docx/xlsx/pdf/pptx/csv etc. split out of backtick-quoted filenames in instruction.md.
FILE_EXT_DENYLIST = {
    "docx",
    "xlsx",
    "pptx",
    "pdf",
    "csv",
    "txt",
    "xlsm",
    "doc",
    "json",
    "toml",
    "md",
    "zip",
    "py",
    "sql",
    "xml",
    "html",
    "htm",
    "tsv",
    "wps",
}

# Contraction fragments left after splitting on apostrophes (we've -> we + ve). These are
# never misspellings; they are artifacts of the alpha-only tokenizer.
CONTRACTION_FRAGMENT_DENYLIST = {
    "ve",
    "re",
    "ll",
    "aren",
    "isn",
    "wasn",
    "weren",
    "hasn",
    "haven",
    "hadn",
    "doesn",
    "don",
    "didn",
    "won",
    "wouldn",
    "shouldn",
    "couldn",
    "mightn",
    "mustn",
    "needn",
    "ain",
    "daren",
    "oughtn",
    "shant",
}

# Common short abbreviations / domain shorthand used in rubric prose (acct for account, mfr
# for manufacturer, etc.). Flagged because they are not dictionary words. Kept as a named set
# (not a length cutoff) so a real 2-4 letter typo is not hidden.
ABBREV_DENYLIST = {
    "pre",
    "op",
    "acct",
    "comp",
    "avg",
    "incl",
    "rec",
    "occ",
    "agg",
    "mfr",
    "yr",
    "yrs",
    "sep",
    "mktg",
    "ack",
    "coq",
    "ror",
    "lb",
    "kg",
    "kwh",
    "voc",
    "pnl",
    "adj",
    "deps",
    "cert",
    "env",
    "pp",
    "civ",
    "qb",
    "inv",
    "forma",
    "multi",
    "etc",
    "approx",
    "corp",
    "calc",
    "stmt",
    "recon",
    "var",
    "cap",
    "ret",
    "pct",
    "qty",
    "amt",
    "init",
    "config",
    "auth",
    "dev",
    "prod",
    "stg",
    "qa",
    "ops",
    "fin",
    "hr",
    "legal",
    "eng",
    "saas",
    "sor",
    "ipaas",
    "dbt",
    "xref",
    "eoq",
    "monte",
    "carlo",
}

ALL_DENYLIST = (
    PROPER_NOUN_DENYLIST
    | FILE_EXT_DENYLIST
    | CONTRACTION_FRAGMENT_DENYLIST
    | ABBREV_DENYLIST
)


def _is_acronym_plural(token: str) -> bool:
    """True for KPIs, SKUs, ToS, PLs, APIs: an initialism with a trailing lowercase suffix.

    Heuristic: strip the trailing run of lowercase letters; if the remainder is ALL-CAPS of
    length >= 2, treat the whole token as an acronym/initialism (not a misspelling). Catches
    KPIs, SKUs, APIs, PLs, ToS, FYs. Does NOT catch single-letter+plural ("As") which is too
    noise-prone.
    """
    m = re.match(r"^([A-Z]{2,})([a-z]+)$", token)
    return m is not None


def is_excluded(token: str) -> bool:
    """True if this token should be skipped (not a spelling candidate)."""
    # ALL-CAPS of length >= 2 (acronym / initialism): SKU, NPS, AOV, GL, SVB, CEO.
    if len(token) >= 2 and token.isupper():
        return True
    # Acronym + lowercase suffix (KPIs, SKUs, ToS, PLs).
    if _is_acronym_plural(token):
        return True
    return False


def _british_american_known(token: str) -> bool:
    """True if `token` is a British spelling whose American equivalent is a known dict word.

    Catches the regular -ise/-ised/-isation/-our/-ence/-ogue/-ise->-ize family that
    pyspellchecker's en_US dictionary rejects. Conservative: only applies fixed suffix
    substitutions, never free-form phonetic guessing.
    """
    low = token.lower()
    pairs = [
        ("isation", "ization"),
        ("ised", "ized"),
        ("ise", "ize"),
        ("our", "or"),
        ("ence", "ense"),
        ("ogue", "og"),
        ("re", "er"),
    ]
    for brit, amer in pairs:
        if low.endswith(brit):
            cand = low[: -len(brit)] + amer
            if cand in SPELL:
                return True
    return False


def _stem_known(token: str) -> bool:
    """True if a morphological stem of `token` is a known dictionary word.

    Catches regular plurals (deliverables->deliverable, financials->financial, actuals->actual,
    backorders->backorder) and simple verb forms (onboarded->onboard) that pyspellchecker's
    `unknown()` misses because it does not do morphological analysis. Conservative: only strips
    common English inflectional suffixes, never compounds.
    """
    low = token.lower()
    for suf in ("ies", "es", "s", "ed", "ing", "d"):
        if low.endswith(suf) and len(low) - len(suf) >= 2:
            stem = low[: -len(suf)]
            # "ies" -> "y" (deliveries -> delivery, categories -> category)
            if suf == "ies":
                stem = low[:-3] + "y"
            if stem in SPELL or stem in PROPER_NOUN_DENYLIST:
                return True
    return False


def _candidate_tokens(text: str) -> set[str]:
    """All non-excluded, non-denylisted, lowercased alpha tokens (len >= 2) in text.

    Also drops tokens whose morphological stem is a known dictionary word (catches plurals /
    inflections pyspellchecker's unknown() misses: deliverables, financials, actuals) and
    British spellings whose American equivalent is known.
    """
    out = set()
    for raw in WORD_RE.findall(text):
        if is_excluded(raw):
            continue
        low = raw.lower()
        if len(low) < 2 or low in ALL_DENYLIST:
            continue
        if _stem_known(low):
            continue
        if _british_american_known(low):
            continue
        out.add(low)
    return out


def scan_text(text: str, unknown: set[str]) -> list[tuple[int, str, str]]:
    """Return [(line_number_1indexed, token, line_text)] for tokens in the unknown set.

    `unknown` is the precomputed set of misspelled lowercased tokens for this text (from
    SPELL.unknown()), so the per-line check is a plain set membership test, not a dictionary
    lookup. This is the fast path: the expensive pyspellchecker work is batched once per text.
    """
    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        seen_on_line = set()
        for raw in WORD_RE.findall(line):
            if raw in seen_on_line:
                continue
            seen_on_line.add(raw)
            low = raw.lower()
            if len(low) < 2 or low in ALL_DENYLIST or is_excluded(raw):
                continue
            if _stem_known(low):
                continue
            if _british_american_known(low):
                continue
            if low in unknown:
                findings.append((lineno, raw, line.rstrip()))
    return findings


def scan_instruction(task_dir: Path) -> list[dict]:
    instr = task_dir / "instruction.md"
    if not instr.exists():
        return []
    text = instr.read_text(encoding="utf-8", errors="replace")
    unknown = SPELL.unknown(_candidate_tokens(text))
    return [
        {"file": "instruction.md", "line": ln, "token": tok, "context": ctx}
        for ln, tok, ctx in scan_text(text, unknown)
    ]


def scan_judge_toml(jf: Path) -> list[dict]:
    findings = []
    raw = jf.read_text(encoding="utf-8")
    data = tomllib.loads(raw)
    for crit in data.get("criterion", []):
        desc = crit.get("description", "")
        name = crit.get("name", "?")
        unknown = SPELL.unknown(_candidate_tokens(desc))
        for ln, tok, ctx in scan_text(desc, unknown):
            findings.append(
                {
                    "file": str(jf.parent.name) + "/judge.toml",
                    "criterion": name,
                    "line": ln,
                    "token": tok,
                    "context": ctx,
                }
            )
    return findings


# 2026-09-16 fix (tracker row 20): both this glob and check_task_dispatch()'s below only ever
# matched tests/deliverables_*/judge.toml (a literal underscore required), never the plain
# tests/deliverables/judge.toml naming with no suffix. Confirmed real: 89/600 real tasks
# (14.8%) use the plain naming, e.g. SVC-PC-10-0-0 through SVC-PC-10-5-0. The dispatch bug
# below is the more severe of the two -- it misrouted these real SVC-PC tasks to
# check_task_ekw(), which returns [] immediately (has_ekw_config() is also False for them), so
# NEITHER the judge.toml scan below NOR the instruction.md scan check_task() itself starts
# with (scan_instruction()) ever ran for these 89 tasks. Same set(...) | set(...) two-glob
# convention already used elsewhere in this folder for the identical naming split (see
# criterion_groundedness_check.py, compound_criterion_check.py, answer_key_content_leak_
# check.py, answer_key_rubric_leak_check.py, harness_fragility_check.py).
_JUDGE_TOML_GLOBS = ("deliverables/judge.toml", "deliverables_*/judge.toml")


def _judge_toml_files(tests_dir: Path):
    return sorted(set().union(*(tests_dir.glob(pat) for pat in _JUDGE_TOML_GLOBS)))


def check_task(task_dir: Path) -> list[dict]:
    findings = scan_instruction(task_dir)
    for jf in _judge_toml_files(task_dir / "tests"):
        findings.extend(scan_judge_toml(jf))
    return findings


def check_task_ekw(task_dir: Path) -> list[dict]:
    if load_ekw_criteria is None or not has_ekw_config(task_dir):
        return []
    findings = scan_instruction(task_dir)
    for crit in load_ekw_criteria(task_dir):
        desc = crit.get("description", "")
        name = crit.get("name", "?")
        unknown = SPELL.unknown(_candidate_tokens(desc))
        for ln, tok, ctx in scan_text(desc, unknown):
            findings.append(
                {
                    "file": "verifier.json",
                    "criterion": name,
                    "line": ln,
                    "token": tok,
                    "context": ctx,
                }
            )
    return findings


def check_task_dispatch(task_dir: Path) -> list[dict]:
    # (also fixed in passing: the old form's first clause -- a bare `.glob(...)` generator
    # object -- is always truthy regardless of whether it yields anything, so it was a no-op
    # ahead of the real `any(...)` check, not a second real condition.)
    if _judge_toml_files(task_dir / "tests"):
        return check_task(task_dir)
    return check_task_ekw(task_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "package_root", help="root containing per-task dirs (e.g. svc-task-samples-56/)"
    )
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        help="limit to these task ids (repeatable)",
    )
    ap.add_argument(
        "--json", dest="json_out", help="write findings as JSON to this path"
    )
    args = ap.parse_args()

    root = Path(args.package_root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2

    task_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.task:
        wanted = set(args.task)
        task_dirs = [d for d in task_dirs if d.name in wanted]
        if not task_dirs:
            sys.stderr.write(f"task(s) not found: {args.task}\n")
            return 2

    all_findings = {}
    total = 0
    for td in task_dirs:
        f = check_task_dispatch(td)
        if f:
            all_findings[td.name] = f
            total += len(f)

    if args.json_out:
        # BARE list of {"task": ..., "findings": [...]}, one entry per task SCANNED (not just
        # tasks with hits) -- the exact shape every other check in this folder's orchestrator
        # registry uses (style="rubric_schema"; merge_shards() auto-extends a bare list across
        # shards, but would NOT correctly combine a dict-wrapped shape). Previously wrote a
        # dict keyed by task name with hits only, which merge_shards() cannot shard-merge
        # correctly -- found and fixed while wiring this check into the orchestrator for the
        # first time (it was never registered before tonight).
        per_task = [
            {"task": td.name, "findings": all_findings.get(td.name, [])}
            for td in task_dirs
        ]
        Path(args.json_out).write_text(
            json.dumps(per_task, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Precompute corrections once for the unique unknown tokens (correction() is expensive:
    # edit-distance over the whole dictionary per call; doing it per-finding makes a corpus-scale
    # print take minutes).
    uniq_tokens = {f["token"].lower() for finds in all_findings.values() for f in finds}
    corr_map = {t: (SPELL.correction(t) or "") for t in uniq_tokens}

    print(f"Scanned {len(task_dirs)} task(s) under {root}")
    print(f"Misspelled-token findings (after exclusions): {total}")
    print()
    for task, finds in all_findings.items():
        print(f"=== {task} ({len(finds)} finding(s)) ===")
        for fnd in finds:
            loc = f"{fnd['file']}"
            if fnd.get("criterion"):
                loc += f" criterion={fnd['criterion']}"
            loc += f" line={fnd['line']}"
            corr = corr_map.get(fnd["token"].lower(), "")
            corr_s = f" -> {corr!r}" if corr else ""
            print(f"  {loc}: {fnd['token']!r}{corr_s}")
            print(f"      context: {fnd['context'].strip()[:140]}")
        print()

    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
