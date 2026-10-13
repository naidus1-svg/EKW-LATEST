#!/usr/bin/env python3
"""Instruction requirement coverage check (Andrew Ma pattern 5, the reverse direction
of criterion_groundedness_check.py): does an instruction's stated imperative requirement
have ANY criterion that plausibly covers it, or is it stated and never graded?

Why this exists: Andrew Ma's manual QC (ekw/andrew-11-pattern-qc-artifact-2026-09-15.md)
found that 12 of 19 tasks show "explicit prompt requirements go ungraded" (his pattern 5):
the instruction states an imperative requirement (a formatting rule, a labelling
convention, "must include X", "ensure Y", a named deliverable component, a modelling
rule) that no criterion in judge.toml/verifier.json ever grades. A solver can ignore the
requirement entirely and still pass every criterion. deliverable_filename_check.py's
REVERSE direction already covers one narrow slice of this (a commanded filename no
judge.toml reads). This check covers the general case: any imperative requirement whose
object no criterion text mentions.

Direction, stated plainly so it is not confused with criterion_groundedness_check.py:
  criterion_groundedness_check.py  ->  criterion's stated fact  ->  does it exist in the
                                      ENVIRONMENT? (criterion -> environment)
  THIS check                      ->  instruction's stated requirement -> does ANY
                                      CRITERION cover it? (instruction -> criteria)
The two are structural mirror images. This check reuses criterion_groundedness's
general posture (extract a textual signal from one side, look for it on the other,
disclose the heuristic honestly) but does NOT reuse its extractors: the signal there is
a FACT (a number/filename/named entity), the signal here is an imperative clause's
OBJECT nouns, which need their own extraction. Round 9/14's own non-transfer findings
already showed reusing a calibrated signal across directions is unsafe in this codebase,
so the extraction here was rebuilt and independently calibrated against the real 27-task
SVC-PC and 14-dir EKW samples (see Validation below), not assumed to transfer.

What it checks, per task:
  1. Read instruction.md, split into sentences.
  2. Keep imperative requirement sentences: those carrying a deliverable-directed
     action verb (rank, segment, recommend, name, label, produce-as-component, own,
     author, define, identify, map, reconcile, quantify, establish, derive, assign,
     embed, document, flag, state, show, include, exclude, separate, distinguish,
     cite, ...  or a modal "must / ensure / need to / required to + action"). Drop
     scene-setting / role framing ("I need you to own the backbone", "You are the
     backstop", "The CEO needs a business case", email Subject/From/To lines, title
     headers), the standard "Working requirements" boilerplate block ("do not copy or
     restate a prebuilt answer", "If a record contains a placeholder, repair
     marker...", "do not invent", "rely only on"), format/existence-only instructions
     ("Produce the deliverable in Excel.", "Produce the following deliverables in
     /workspace/output/:"  those are deliverable_filename_check.py's territory and
     are structurally covered by "workbook present / opens valid" criteria), and
     bare input-file listing lines.
  3. For each kept sentence, score coverage = fraction of its content-word stems that
     appear in the concatenated criteria description text (with a small
     corpus-grounded abbreviation map so "customer-acquisition cost" matches a
     criterion that says "CAC", "minimum advertised price" matches "MAP", etc.).
   4. Coverage below COVERAGE_THRESHOLD (calibrated 0.34, see Calibration) -> an
      `uncovered_requirement` finding (a candidate for human review). The finding carries
      the sentence, its coverage score, and the missing content words.
  5. Negative scope-constraint sub-case (the OPPOSITE direction of steps 1-4): the
     instruction may impose an EXCLUSION ("without extending the analysis into X",
     "excluding Y", "do not cover Z", "keep W out of scope") bounding what the
     solution should NOT do. "Coverage" here means "some criterion would PENALIZE a
     solution that did extend into the excluded topic", NOT "the topic's words appear
     in a criterion" (a criterion mentioning "demand intake" approvingly would reward,
     not penalize). That penalize-vs-approve polarity is semantic and a heuristic
     cannot make it reliably, so this sub-case is scoped to a NECESSARY-but-NOT-
     SUFFICIENT precondition: if NO criterion mentions the excluded topic's content
     words AT ALL, no criterion can be penalizing extension into it, so it is an
     `uncovered_negative_constraint` WARN candidate. If a criterion DOES reference the
     topic the sub-case stays quiet (a disclosed false-negative risk, see the
     "Known limits of the negative-constraint sub-case" section below, not a claimed
     coverage).

Dual-format design (identical pattern to deliverable_filename_check.py):
  load_criteria_text() dispatches on which config exists: SVC-PC's tests/*/judge.toml
  (tomllib) takes precedence; else EKW's tests/verifier.json via
  ekw_verifier_json.load_ekw_criteria(). SVC-PC detection takes precedence so an SVC-PC
  task's behaviour cannot change even if both shapes exist.

THIS IS A NON-BLOCKING CANDIDATE TOOL, NOT A HARD GATE. Its verdict is "warn", never
"fail". See the "Honest limitation" section below for the measured false-positive rate
and the LLM-judgment alternative this crisis's own standing rule (round 12, pattern 2)
requires when a deterministic heuristic does not cleanly separate.

Calibration (real, measured, not assumed):
  Threshold 0.34 was chosen by running the prototype against the real 27-task SVC-PC
  sample and the 14-dir EKW sample and reading every flag by hand. At this threshold:
    - SVC-PC: both real pattern-5 positives I confirmed by hand (SVC-PC-12-1-0: the
      "Recommend the go-to-market motion / Tier-1 beachhead / guardrails", "Flag the
      ... beachhead", and "resolve TBD/pending" requirements; SVC-PC-12-2-0: the
      "volume tiers and opening minimums", "guardrails / margin floor", and "MAP policy
      language" requirements  none of which any criterion in those tasks mentions)
      ARE flagged. One hand-confirmed positive (12-1-0 "rank them by brand fit, margin,
      and effort") is MISSED (false negative): it sits inside a long sentence whose
      other nouns do appear in criteria, so the sentence-level coverage clears the
      threshold even though the ranking requirement itself is ungraded.
    - Across the 22 hand-confirmed SVC-PC NEGATIVE tasks (well-covered: 7-2-0, 14-1-0,
      14-3-0, 14-6-0, 31-0-0, 42-1-0, 58-3-0, 80-7-0, 88-0-0, 9-3-0, 9-5-0, 9-6-0,
      92-0-0, 1-2-0, 11-2-0, 11-4-0, 13-3-0, 17-3-0, 24-6-0, 7-6-0, 93-0-0, 14-4-0),
      this check flags 7 of them with 17 candidate sentences that are, on hand
      review, false positives (corrected after an adversarial review: this
      docstring previously said ~12 tasks / ~21 sentences, stale numbers from
      an earlier prototype iteration that were never updated when the
      threshold was finalized at 0.34; the report body's own numbers were
      already correct). The false-positive class is dominated by
      "covered-by-consequence with different nouns" (e.g. 13-3-0 "Quantify
      customer-acquisition cost"  criteria grade it as "CAC"; 17-3-0 "Anchor it in
      the MSA and the PO history"  criteria grade "Ties to NovaTex PO history";
      80-7-0 "Author the data-governance spec"  criteria grade its SoR / RACI /
      reconciliation components) and by process/discipline "working requirements"
      (9-3-0 "Keep direct evidence separate from inferences", "Retain source, period,
      population, unit, and basis") which are a different pattern class from Andrew's
      "whole deliverables / modelling rules / formatting asks go ungraded".
    - EKW (14-dir sample): the check flags mostly deliverable-listing headers
      ("Produce the following deliverables in /workspace/output/:") and
      working-requirements prose, with at most one borderline true positive
      (task_12 "name the disagreement and say which you're relying on"). No clean
      EKW pattern-5 positive was confirmed in this sample (the sample is small and
      EKW criteria are dense rubric prompts that tend to cover their instructions).

  Net, on the 27-task SVC-PC sample: task-level precision as a GATE would be 22%
  (2 true-positive tasks / 9 flagged tasks; corrected after an adversarial review,
  same stale-docstring issue as above). That is why this check is WARN-tier,
  not fail. As a CANDIDATE triage tool its value is high-recall surfacing: a human
  reviews the 9 flagged tasks instead of all 600, and the two real pattern-5
  positives (12-1-0, 12-2-0) are in that set. Full-corpus validation (the complete
  600-task SVC-PC and 274-task EKW corpora) needs corpora this machine does not have
  staged; the 27/14-task samples are what was available here, disclosed plainly.

Honest limitation and the LLM-judgment alternative (the real deliverable per this
crisis's standing rule, matching round 12 pattern 2's own honest conclusion):
  A deterministic noun-overlap heuristic FUNDAMENTALLY cannot distinguish "the
  instruction states a requirement no criterion grades" (a real gap) from "the
  instruction states a requirement a criterion grades BY CONSEQUENCE using different
  nouns" (not a gap). "Covered does not require verbatim quoting" is explicit in the
  task brief, and consequence-coverage is exactly the case noun-overlap misreads. The
  measured false-positive rate above is the evidence. Forcing this heuristic into a
  hard gate would flag 12 of 22 well-covered tasks. The correct gating decision
  (is this requirement genuinely ungraded?) needs semantic judgment. An
  LLM-judgment version would, per flagged candidate sentence, prompt a model with the
  sentence plus the full criteria text and ask "does any criterion plausibly grade
  compliance with this requirement, directly or by testing a consequence of following
  it?"  the same "covered" definition the task brief gives. That is the version that
  should gate; this deterministic script is the cheap, zero-cost triage layer that
  produces the candidate set the LLM judge (or a human reviewer) then adjudicates.
  Wiring the LLM judge is out of scope for this deterministic-checks folder (no other
  check here calls a model); it belongs in the judgment layer above, called on this
  check's warn-tier output.

Negative scope-constraint sub-case (calibration, real, measured on the full 202-task
  SVC-PC corpus at C:/wt/_shared/ekw/pipeline-mirror/khiem-202-data/full-202-text-
  and-listings, reconstructed to the native tests/<deliv>/judge.toml layout the check
  reads, the same way the positive-imperative side was calibrated against the 27/14-
  task samples):
    - Fire rate: 14 of 202 tasks fire, 15 findings (one task, 79-2-0, carries two
      exclusions).
    - Hand-confirmed TRUE positives: 11 tasks / 11 findings, all topical scope
      exclusions genuinely uncovered (no criterion in the task mentions the excluded
      area, so a solver who overreaches into it violates an explicit instruction
      constraint and can still score 1.0): SVC-PC-46-1-0 demand intake /
      prioritization / governance (the coverage report cov2 RC1 named case),
      75-1-0 "final cuts / executive plan", 75-4-0 / 75-5-0 / 91-5-0 / 91-6-0
      "the consolidated model", 79-1-0 "profitability / contribution margin / demand
      ranking / pricing effectiveness / marketing performance", 79-2-0 "S&OP / demand
      planning / reorder points / supplier or 3PL network strategy", 82-1-0
      "commercial assortment / pricing or promotion / marketing performance", 82-4-0
      "technical data integrity / demand planning / capacity expansion / supplier or
      3PL strategy / product quality / returns / customer support", 92-1-0
      "corrective-action closure / onboarding readiness / automation prioritization".
    - Hand-confirmed FALSE positives: 4 tasks / 4 findings (corrected 2026-09-16 by
      an adversarial review that independently re-derived every finding rather than
      trusting this section's first-draft count; see the tokenization bullet in
      Known limits below for the mechanism the 4th case exposed). SVC-PC-10-4-0 ("Do
      not build a model one year of data cannot carry") is a methodological caveat
      (do not overfit), not a topical scope boundary, and its captured "topic" is a
      clause, not an analytical area. SVC-PC-15-2-0 ("Don't just give me raw data;
      give me an assessment") is a positive requirement in disguise whose violation
      (giving only raw data) IS penalized by the analysis criteria by consequence.
      SVC-PC-76-0-0 ("Do not give uncited current-law advice or import external
      thresholds, standards, or benchmarks") is source-discipline (use only the
      corpus) that leaked through the finite WORKING_BOILERPLATE list because its
      exact phrasing is not listed; it is adjacent to "do not use outside", not a
      topical scope boundary. SVC-PC-79-2-0's second exclusion ("Do not perform an
      audit of whether employees followed the procedures") IS covered: criterion
      l2-02-r01's Expected text ("Six approved sources only; no employee-execution
      conclusion") penalizes exactly this overreach, but the sub-case fired anyway
      because of a tokenization failure, not an absence of coverage -- see Known
      limits.
    - Net: task-level precision 11/14 = 79%, finding-level 11/15 = 73%, materially
      above the positive-imperative side's 22% because the "NO criterion mentions the
      topic AT ALL" precondition is stricter than a coverage threshold, so the
      sub-case fires on a cleaner signal. The headline case (46-1-0 demand-intake
      exclusion) fires; its sibling story-point exclusion ("do not translate them
      into hours or use them to compare individual engineer productivity") correctly
      stays quiet because criterion 13 grades it (the asymmetry the coverage report
      describes).

Known limits of the negative-constraint sub-case (disclosed, not hidden, matching
  duplicate_criterion_content_check.py's own disclosed-false-positive convention for
  this family):
    1. NECESSARY but NOT SUFFICIENT. The sub-case fires only when NO criterion
       mentions the excluded topic's content words. It STAYS QUIET when a criterion
       DOES mention the topic, even if that mention approves the topic, describes it
       for an unrelated reason, or grades the IN-scope area whose noun overlaps the
       excluded topic. So it produces disclosed FALSE NEGATIVES on real gaps where the
       excluded topic's noun incidentally grounds. Confirmed real examples from the
       202-task corpus: SVC-PC-46-3-0 ("Do not independently assess overall
       sprint-delivery reliability, make capacity allocation the primary analysis,
       redesign the technology roadmap, or evaluate individual engineer productivity"
       is a genuine uncovered exclusion, but "sprint" grounds via the demand/intake
       criteria that share the noun); SVC-PC-46-0-0 (same family, "productivity"
       grounds via the story-point criterion l3-r03); SVC-PC-26-3-0 / 26-4-0 / 26-7-0
       / 26-8-0 ("Do not score other departments' requests" stays quiet because the
       rubric grades the team's OWN requests, grounding "requests"); and the same
       shape in 29-5-0, 56-1-0, 72-1-0, 31-4-0, 80-6-0, and SVC-PC-76-0-0 line 27
       ("Do not perform a general customer-experience review ..."). A criterion
       mentioning a topic approvingly rather than punitively is exactly the polarity
       judgment a deterministic heuristic cannot make; the LLM-judgment version
       described for the positive side applies here too.
    1b. Tokenization can defeat the precondition in the OTHER direction: a criterion
       CAN semantically cover the excluded topic and the sub-case can still fire,
       because "mentions the topic's content words" is computed via the shared
       `_content_words`/`_stem` helpers, not real matching. Confirmed real example
       (found by an adversarial review, 2026-09-16, and left unfixed deliberately --
       see below): SVC-PC-79-2-0's exclusion "an audit of whether employees followed
       the procedures" was counted as a true positive in this file's first-draft
       Calibration write-up, but criterion l2-02-r01 ("Six approved sources only; no
       employee-execution conclusion") DOES penalize exactly this overreach. Two
       compounding tokenization failures hide the match: `_content_words`' regex
       captures the hyphenated compound "employee-execution" as ONE token, which
       never matches the stem of "employees"; and the light stemmer's suffix order
       (`ing, ed, ies, es, s`) reduces "employees" to "employe" and "procedures" to
       "procedur", neither of which equals the "employee"/"procedure" stems the
       criterion text and the SOP abbreviation expansion actually produce. This is
       NOT fixed here: the tokenizer is shared with the positive-imperative side,
       whose 0.34 threshold is calibrated against its current behavior, so a
       tokenizer change is a real regression risk to a mature, already-shipped
       mechanism for the sake of one warn-tier finding on the negative side. Flagged
       for a future round, not patched under this one's time pressure.
    2. Single-list capture. An exclusion that lists several excluded areas ("Do not
       assess X, redesign Y, or evaluate Z") is captured as ONE topic; if ANY listed
       area shares a noun with a criterion, the whole exclusion stays quiet (the
       46-3-0 case above). Splitting the list into per-area checks is left to the LLM
       judge.
    3. Anaphoric / sub-min-word exclusions skipped. "Treat it as out of scope", "Do
       not redo it", "Do not decompose margin" (1 content word) are skipped
       (MIN_TOPIC_CONTENT_WORDS = 2); a content-word proxy is meaningless on a
       pronoun or single token.
    4. Discipline leakage. A few source-discipline "do not [scope verb]" clauses
       whose exact phrasing is not in WORKING_BOILERPLATE (the 76-0-0 "import
       external standards" case) fire as false positives; the finite boilerplate list
       cannot enumerate every discipline phrasing. This is the same finite-list
       precision lever the positive side relies on, with the same disclosed leakage.

Validation: hand-reviewed against the real 27-task SVC-PC and 14-dir EKW samples on
  2026-09-15, BEFORE registration. The negative scope-constraint sub-case was
  calibrated against the full 202-task SVC-PC corpus on 2026-09-16 (14 fires hand-read
  for TP/FP, numbers above). Full-corpus validation of the positive side is pending
  the complete corpora this machine does not have.

Exit 0 clean (zero uncovered_requirement findings), 1 findings (warn), 2 bad usage.

    python instruction_requirement_coverage_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python instruction_requirement_coverage_check.py --all --root <path> --out report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from ekw_verifier_json import has_ekw_config, load_ekw_criteria

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# task / config discovery (mirrors deliverable_filename_check.py)
# ---------------------------------------------------------------------------


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "") -> list[Path]:
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


def _has_svc_pc_config(task_dir: Path) -> bool:
    tests = task_dir / "tests"
    if not tests.is_dir():
        return False
    return any(tests.glob("*/judge.toml"))


def load_criteria_text(task_dir: Path) -> tuple[str, list[str]]:
    """Concatenate every criterion's name + description into one blob, for stem
    matching. Returns (text, errors). Dispatches SVC-PC (tomllib) vs EKW
    (ekw_verifier_json) on which config exists; SVC-PC takes precedence."""
    errors: list[str] = []
    parts: list[str] = []
    if _has_svc_pc_config(task_dir):
        tests = task_dir / "tests"
        for jt in sorted(tests.glob("*/judge.toml")):
            try:
                data = tomllib.loads(jt.read_text(encoding="utf-8"))
            except Exception as e:
                errors.append(f"{jt.name}: parse error: {e}")
                continue
            for c in data.get("criterion", []):
                parts.append(str(c.get("name", "")) + " " + str(c.get("description", "")))
        return "\n".join(parts), errors
    if has_ekw_config(task_dir):
        try:
            for c in load_ekw_criteria(task_dir):
                parts.append(str(c.get("name", "")) + " " + str(c.get("description", "")))
        except Exception as e:
            errors.append(f"verifier.json: {e}")
        return "\n".join(parts), errors
    return "", ["no tests/*/judge.toml and no tests/verifier.json found"]


# ---------------------------------------------------------------------------
# requirement extraction
# ---------------------------------------------------------------------------

STOP = set(
    (
        "the a an is are was were be been being has have had do does did will would "
        "shall should may might must can could of in on at to for with by from as into "
        "about than then so if but or and not no all any each every same this that these "
        "those per via up down out over under here there when where why how what which "
        "who whom you your our we us i me my it its their they them he she his her one "
        "two three first second third new own s"
    ).split()
)

# Deliverable-directed action verbs (command form). Calibrated from the real
# instruction corpus: these are the verbs that, when they head a clause, signal
# "do this work and put it in the deliverable" rather than "here is context".
IMPERATIVE_VERBS = set(
    """
rank segment recommend name label produce deliver state show flag document build
quantify size define identify map reconcile cite separate distinguish exclude include
list present provide establish derive compute calculate assess evaluate test verify log
record own author design determine confirm prove substantiate audit review sequence
assign embed treat adopt resolve restate derive tie surface quantify decompose
attribute decline proposes keep retain remove carry compose consolidate reperform
enumerate bound score rate catalog catalogue register draft lay anchor lock limit
narrow frame position draft walk return give annotate note explain ground own
""".split()
)

# Scene-setting / role-framing line starters: not deliverable requirements. These
# survived hand-review as the dominant false-positive class on the calibration set,
# so they are filtered here. Each is a finite, corpus-grounded pattern, not an open
# English grammar.
SCENE_STARTERS = re.compile(
    r"^(?:i need|i will|you are|you're|your role|you own|you have|sarah|alice|priya|"
    r"brian|elena|jessica|from:|to:|subject:|hi|hey|team|prompt|task design|"
    r"internal email|cirrus sleep|accountable owner|executive assignment|"
    r"required analysis|evidence and scope rules|ground rules|inputs|named corpus|"
    r"working requirements|definitions and constraints|constraints|deliverables|"
    r"required deliverable|files / connectors|note on|quick context|the ceo|"
    r"the part|the recommendation should|the source documents|a central task|"
    r"the deck may|the patient|the only per|the deal|the sponsor|the company|"
    r"the merchant|the category|the store|a successful submission|fy\d|"
    r"cirrus-y|cirrus sleep|produce the following deliverables|produce two deliverables|"
    r"produce the deliverable|produce the results|produce the fy|produce in "
    r")",
    re.IGNORECASE,
)

# Standard "Working requirements" / process-discipline boilerplate block. This is a
# DIFFERENT pattern class from Andrew's pattern-5 (whole deliverables / modelling
# rules / formatting asks go ungraded): these are authoring-discipline rules, often
# partially graded by a "no fabrication" / "independently built" criterion. Filtering
# them is a stated precision choice, not a silent drop.
WORKING_BOILERPLATE = re.compile(
    r"(?:do not copy or restate|do not restate|do not rely on completed work|"
    r"placeholder,? repair marker|malformed formula|apparent truncation|"
    r"do not invent|rely only on|ignore any|do not create, move, rename|"
    r"perform the analysis independently|do not include any internal grading|"
    r"do not draw conclusions|do not produce an amended|treat those as evidence|"
    r"do not let it substitute|do not manufacture precision|"
    r"keep direct evidence separate|retain source, period|"
    r"do not infer actual|separate observed evidence|"
    r"every figure and classification in your deliverables must be grounded|"
    r"cleanly separate the instrument|test the stated incident narrative|"
    r"preserve provenance for material|"
    r"do not use outside|do not use any information outside|do not make assumptions"
    r")",
    re.IGNORECASE,
)

FORMAT_TOKENS = {"excel", "word", "workbook", "docx", "xlsx", "pptx", "pdf", "csv",
                 "json", "doc", "xlsm"}
FILENAME_TOKEN_RE = re.compile(
    r"[\w.\-]+\.(?:xlsx|docx|pptx|pdf|csv|json|md|txt|xlsm)\b", re.IGNORECASE
)

# Corpus-grounded abbreviation map: instruction prose often spells a term out where a
# criterion uses the acronym (or vice versa). Without this, "Quantify
# customer-acquisition cost" reads as uncovered against a criterion that says "CAC".
# Each entry maps a phrase (word(s)) to the acronym/variant criteria use, so a stem
# match on either direction grounds the other. Finite, hand-confirmed against the
# real corpus, not a general NLP resource.
ABBREV_MAP = {
    "cac": "customer acquisition cost",
    "aov": "average order value",
    "msrp": "manufacturer suggested retail price",
    "map": "minimum advertised price",
    "roas": "return on ad spend",
    "ltv": "lifetime value",
    "ap": "accounts payable",
    "ar": "accounts receivable",
    "gl": "general ledger",
    "tb": "trial balance",
    "je": "journal entry",
    "nps": "net promoter score",
    "sla": "service level agreement",
    "dtc": "direct to consumer",
    "wc": "working capital",
    "npv": "net present value",
    "fte": "full time equivalent",
    "pbc": "prepared by client",
    "raci": "responsible accountable consulted informed",
    "sop": "standard operating procedure",
    "dioh": "days inventory on hand",
    "sor": "system of record",
    "batna": "best alternative to negotiated agreement",
    "msa": "master services agreement",
    "po": "purchase order",
    "cfo": "chief financial officer",
    "coo": "chief operating officer",
    "cto": "chief technology officer",
    "ceo": "chief executive officer",
    "kpi": "key performance indicator",
    "roi": "return on investment",
    "gom": "gross order margin",
    "gmv": "gross merchandise value",
}


def _stem(word: str) -> str:
    """Light stemmer: lowercase, strip a trailing plural/verb-s. Deliberately not a
    full Porter/Snowball: this is a presence-check proxy, and a heavier stemmer
    increases false-grounding (two unrelated words collapsing to the same stem)."""
    w = word.lower()
    for suf in ("ing", "ed", "ies", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _content_words(s: str) -> list[str]:
    out = []
    for w in re.findall(r"[A-Za-z][A-Za-z-]{2,}", s):
        wl = w.lower()
        if wl in STOP:
            continue
        out.append(wl)
    return out


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.;:\n])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _is_imperative(s: str) -> bool:
    ws = re.findall(r"[A-Za-z][A-Za-z-]{2,}", s)
    if not ws:
        return False
    if ws[0].lower() in IMPERATIVE_VERBS:
        return True
    if re.search(r"\b(ensure|must|need to|shall|required to|please)\b", s, re.I):
        return True
    return any(w.lower() in IMPERATIVE_VERBS for w in ws)


def _is_scene_or_boilerplate(s: str) -> bool:
    if SCENE_STARTERS.match(s):
        return True
    if WORKING_BOILERPLATE.search(s):
        return True
    if FILENAME_TOKEN_RE.search(s) and len(s) < 90:
        return True
    cws = [w for w in _content_words(s) if w not in FORMAT_TOKENS and len(w) >= 3]
    fmt_present = any(w.lower() in FORMAT_TOKENS for w in re.findall(r"[A-Za-z]+", s))
    if fmt_present and len(cws) <= 3 and re.search(
        r"\b(produce|deliver|save|submit)\b", s, re.I
    ):
        return True
    if len(cws) < 3:
        return True
    return False


COVERAGE_THRESHOLD = 0.34


def _criteria_stems(crit_text: str) -> set[str]:
    """Stem set of the criteria text, expanded with the abbreviation map so an
    instruction noun matches a criterion acronym (and vice versa)."""
    stems = set()
    for w in _content_words(crit_text):
        stems.add(_stem(w))
        for acr, expansion in ABBREV_MAP.items():
            if w == acr or _stem(w) == _stem(acr):
                for ew in expansion.split():
                    stems.add(_stem(ew))
            if w in expansion.split() or _stem(w) == _stem(w):
                stems.add(_stem(acr))
    # also seed the acronyms themselves from any expansion word present
    for acr, expansion in ABBREV_MAP.items():
        for ew in expansion.split():
            if _stem(ew) in stems or any(_stem(x) == _stem(ew) for x in _content_words(crit_text)):
                stems.add(_stem(acr))
    return stems


def _coverage(sentence: str, crit_text_lower: str, crit_stems: set[str]):
    """Returns (coverage_fraction, missing_words). Coverage = fraction of the
    sentence's content-word stems that appear in the criteria stem set OR whose
    raw word appears in the criteria text (catches exact acronyms the stemmer would
    mangle)."""
    cws = [w for w in _content_words(sentence) if len(w) >= 3]
    if not cws:
        return 1.0, []
    hits = 0
    missing = []
    for w in cws:
        sw = _stem(w)
        grounded = sw in crit_stems or w in crit_text_lower
        if grounded:
            hits += 1
        else:
            missing.append(w)
    return (hits / len(cws)), missing


def extract_uncovered_requirements(instr_text: str, crit_text: str):
    """Every imperative requirement sentence whose object nouns no criterion
    mentions above the coverage threshold. Returns a list of finding dicts, never
    raises."""
    crit_lower = crit_text.lower()
    crit_stems = _criteria_stems(crit_text)
    findings = []
    for s in _sentences(instr_text):
        if not _is_imperative(s):
            continue
        if _is_scene_or_boilerplate(s):
            continue
        cov, missing = _coverage(s, crit_lower, crit_stems)
        if cov < COVERAGE_THRESHOLD:
            findings.append(
                {
                    "kind": "uncovered_requirement",
                    "coverage": round(cov, 3),
                    "missing_words": missing[:8],
                    "sentence": s[:300],
                    "message": f"cov={round(cov, 2)} missing={missing[:4]} :: {s[:120]}",
                }
            )
    return findings


# ---------------------------------------------------------------------------
# negative scope-constraint extraction (sub-case; the OPPOSITE direction of
# the positive-imperative coverage above)
# ---------------------------------------------------------------------------
#
# The core loop above answers "does this POSITIVE imperative's OBJECT get
# graded." This sub-case answers the structurally opposite direction: "does
# violating this NEGATIVE exclusion get PENALIZED." A negative scope constraint
# is an instruction clause that bounds what the solution should NOT do
# ("without extending the analysis into X", "excluding Y", "do not cover Z",
# "keep W out of scope"). It is satisfied by ABSENCE: the solution correctly
# did NOT do the excluded thing, so a solver who overreaches into the excluded
# area violates an explicit instruction constraint.
#
# Coverage here does NOT mean "the excluded topic's words appear in a
# criterion"  that is the WRONG signal: a criterion mentioning "demand intake"
# approvingly would not catch a solver who wrongly extended into it. It means
# "at least one criterion would PENALIZE a solution that DID extend into the
# excluded topic." That polarity judgment (penalize vs. approve) is semantic
# and a deterministic lexical heuristic cannot make it reliably. So this
# sub-case is scoped down to the only signal a heuristic CAN honestly assert:
# a NECESSARY but NOT SUFFICIENT precondition. If NO criterion mentions the
# excluded topic's content words AT ALL, then no criterion can be penalizing
# extension into it (you cannot penalize overreach into a topic you never
# reference), so the negative constraint is a WARN candidate for human review.
# If a criterion DOES reference the topic, this sub-case stays quiet  a human
# still must check whether that reference actually penalizes overreach or
# merely describes the topic approvingly / for an unrelated reason (e.g. a
# "productivity" mention that grades the instruction's OTHER negative
# constraint, not this one). Staying quiet there is a disclosed FALSE-NEGATIVE
# risk, not a claimed coverage. See the "Known limits" addition to the
# Calibration section in the module docstring.
#
# Trigger phrasings were calibrated against the real 202-task instruction
# corpus (C:\wt\_shared\ekw\pipeline-mirror\khiem-202-data\full-202-text-and-
# listings\*\instruction.md), the same way the positive-imperative verb list
# above was calibrated against the 27/14-task samples. "rather than [gerund]"
# was deliberately NOT added as a trigger: in the real corpus it is
# overwhelmingly authoring DISCIPLINE ("rather than inventing", "rather than
# inferring", "rather than fabricating", "rather than assuming"), not
# analytical scope, so treating it as scope-exclusion would invert the signal
# and fire on process rules, not boundaries. The named-example phrasings from
# the coverage report ("without extending", "excluding", "do not cover",
# "outside the scope of", "not covering", "do not extend into") are all
# covered by the patterns below, plus the corpus-grounded "do not
# [analytical verb] [topic]" shape (assess / redesign / build / rank /
# score ... the technology roadmap / the consolidated model / other
# departments' requests) and "exclude [topic]" / "keep [topic] out of scope".
#
# The "do not [verb]" shape is the precision-critical one: "do not" fronts
# BOTH scope-exclusion ("do not redesign the technology roadmap") and
# authoring-discipline ("do not invent", "do not copy or restate", "do not
# rely on completed work"). They are separated here by (a) a finite
# SCOPE_EXCLUSION_VERBS list of analytical/topic verbs and (b) skipping any
# match whose span overlaps a WORKING_BOILERPLATE phrase, so a sentence that
# carries both a discipline clause and a scope clause (the real Cirrus
# 46-3-0 sentence does) still yields its scope clause.

# Analytical / topic-boundary verbs that, after "do not", signal "stay out of
# this analytical area" rather than "do not fabricate / cheat". Discipline
# verbs (invent, copy, restate, rely, fabricate, create, move, rename, edit,
# assume, derive, manufacture) are deliberately ABSENT: those are left to the
# WORKING_BOILERPLATE filter / the positive-imperative side. Calibrated from
# the real corpus (assess/redesign/rank/build/score/set/calculate/perform/
# evaluate/recommend/conduct/translate/draw/go/rewrite/decide/list/write/
# infer/...).
SCOPE_EXCLUSION_VERBS = (
    "assess rank conduct make redesign evaluate recommend cover extend address "
    "discuss analyze analyse model attempt build score set calculate perform give "
    "decide rewrite go decompose propose undertake pursue re-open reopen re-close "
    "reclose redo translate draw pre-decide predecide blend list write infer".split()
)

# "without extending the analysis into [topic]" and close variants. The
# .{0,30}? lazily swallows the optional object ("the analysis", "your review")
# between the gerund and "into", then captures the excluded topic to the
# sentence boundary.
_WITHOUT_INTO = re.compile(
    r"\bwithout\s+(?:extending|going|delving|venturing|drilling|diving|including|"
    r"addressing|straying|wandering|reaching|drifting|expanding)\b"
    r".{0,30}?\binto\b\s+(.*?)(?=[.;\n]|$)",
    re.IGNORECASE,
)

# "do not [scope verb] [topic]"  the dominant real-corpus shape. Captures the
# excluded topic (everything after the verb) to the sentence boundary. The
# optional adverb slot (independently / just / quietly / simply / ...) absorbs
# real modifiers like 46-3-0's "Do not independently assess ...".
_DO_NOT_SCOPE = re.compile(
    r"\b(?:do\s+not|don['\u2019]t)\s+"
    r"(?:independently\s+|just\s+|quietly\s+|simply\s+|also\s+|merely\s+)?"
    r"(?:" + "|".join(SCOPE_EXCLUSION_VERBS) + r")\b"
    r"\s*(.*?)(?=[.;\n]|$)",
    re.IGNORECASE,
)

# "excluding [topic]" / "exclude [topic]" / "excludes [topic]".
_EXCLUDE = re.compile(
    r"\bexclud(?:ing|e[s]?)\s+(.*?)(?=[.;\n]|$)",
    re.IGNORECASE,
)

# "outside / beyond the scope of [topic]".
_SCOPE_OF = re.compile(
    r"\b(?:outside|beyond)\s+(?:the\s+)?scope\s+of\s+(.*?)(?=[.;\n]|$)",
    re.IGNORECASE,
)

# "keep / leave / put / treat / hold [topic] out of scope". Captures the topic
# between the verb and "out of scope".
_KEEP_OUT_OF_SCOPE = re.compile(
    r"\b(?:keep|leave|put|treat|hold)\s+(.*?)\s+(?:as\s+)?out of scope\b",
    re.IGNORECASE,
)

# Minimum content words a captured topic must hold to be assessed. Below this,
# the topic is anaphoric / underspecified ("Treat it as out of scope", "Do not
# redo it") and a content-word check is meaningless; it is skipped (disclosed
# in Known limits).
MIN_TOPIC_CONTENT_WORDS = 2

_NEG_PATTERNS = (
    _WITHOUT_INTO,
    _DO_NOT_SCOPE,
    _EXCLUDE,
    _SCOPE_OF,
    _KEEP_OUT_OF_SCOPE,
)


def _overlaps_boilerplate(sentence: str, span: tuple[int, int]) -> bool:
    """True if the match span overlaps any WORKING_BOILERPLATE phrase in the
    sentence. Used to drop a scope match that is actually authoring-discipline
    ("do not make assumptions", "do not draw conclusions") so a sentence can
    carry both a discipline clause and a genuine scope clause without the
    discipline one leaking through."""
    for m in WORKING_BOILERPLATE.finditer(sentence):
        if m.start() < span[1] and span[0] < m.end():
            return True
    return False


def extract_uncovered_negative_constraints(
    instr_text: str, crit_text: str
) -> list[dict]:
    """Negative scope constraints in the instruction whose excluded topic no
    criterion mentions at all. Returns a list of `uncovered_negative_constraint`
    finding dicts, never raises. See the sub-case block above for the
    necessary-but-not-sufficient scoping."""
    crit_lower = crit_text.lower()
    crit_stems = _criteria_stems(crit_text)
    findings: list[dict] = []
    seen_topics: set[tuple[str, ...]] = set()
    for s in _sentences(instr_text):
        if SCENE_STARTERS.match(s):
            continue
        for pat in _NEG_PATTERNS:
            for m in pat.finditer(s):
                topic = m.group(1).strip()
                if _overlaps_boilerplate(s, m.span()):
                    continue
                cws = [w for w in _content_words(topic) if len(w) >= 3]
                if len(cws) < MIN_TOPIC_CONTENT_WORDS:
                    continue
                cov, missing = _coverage(topic, crit_lower, crit_stems)
                if cov != 0.0:
                    continue
                key = tuple(sorted(w for w in cws[:6]))
                if key in seen_topics:
                    continue
                seen_topics.add(key)
                findings.append(
                    {
                        "kind": "uncovered_negative_constraint",
                        "coverage": 0.0,
                        "excluded_topic": topic[:200],
                        "missing_words": missing[:8],
                        "sentence": s[:300],
                        "message": (
                            "neg-constraint cov=0.0 (no criterion mentions the "
                            f"excluded topic) topic={topic[:80]!r} :: {s[:120]}"
                        ),
                    }
                )
    return findings


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir: Path) -> dict:
    task_id = task_dir.name
    result = {
        "task_id": task_id,
        "instruction_md_exists": False,
        "criteria_found": False,
        "errors": [],
        "findings": [],
    }
    instr_path = task_dir / "instruction.md"
    if not instr_path.is_file():
        result["status"] = "skip"
        result["errors"].append("no instruction.md found -- nothing to check")
        return result
    result["instruction_md_exists"] = True
    try:
        instr_text = instr_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        result["status"] = "skip"
        result["errors"].append(f"could not read instruction.md: {e}")
        return result

    crit_text, load_errors = load_criteria_text(task_dir)
    result["errors"].extend(load_errors)
    if not crit_text:
        result["status"] = "skip"
        if not load_errors:
            result["errors"].append("no criteria found -- nothing to check coverage against")
        return result
    result["criteria_found"] = True

    findings = list(extract_uncovered_requirements(instr_text, crit_text))
    findings.extend(extract_uncovered_negative_constraints(instr_text, crit_text))
    result["findings"] = findings
    # WARN tier, never fail: this is a candidate triage tool, see module docstring.
    result["status"] = "warn" if findings else "pass"
    result["n_findings"] = len(findings)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Instruction requirement coverage check (Andrew Ma pattern 5): "
        "flag imperative requirements in instruction.md that no criterion in "
        "judge.toml/verifier.json plausibly covers. NON-BLOCKING warn-tier candidate "
        "tool -- see the module docstring for the measured false-positive rate and "
        "the LLM-judgment alternative."
    )
    ap.add_argument("task_ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help="root directory containing one subdirectory per task",
    )
    ap.add_argument("--id-prefix", default="")
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

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
        except Exception as e:
            r = {
                "task_id": task_dir.name,
                "status": "skip",
                "errors": [f"unhandled exception: {e}"],
                "findings": [],
            }
        results.append(r)
        _fs = r.get("findings", [])
        _n_pos = sum(1 for f in _fs if f.get("kind") == "uncovered_requirement")
        _n_neg = sum(
            1 for f in _fs if f.get("kind") == "uncovered_negative_constraint"
        )
        print(
            f"    -> {r['status']}  ({_n_pos} uncovered, {_n_neg} neg-constraint, "
            f"{len(r.get('errors', []))} errors)",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_warn = sum(1 for r in results if r["status"] == "warn")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_warn": n_warn,
        "n_skip": n_skip,
        "results": results,
    }
    print(f"\n{n_pass} pass / {n_warn} warn / {n_skip} skip out of {len(results)} task(s)")
    for r in results:
        if r["status"] == "warn":
            _fs = r["findings"] or [{}]
            _p = sum(1 for f in _fs if f.get("kind") == "uncovered_requirement")
            _n = sum(1 for f in _fs if f.get("kind") == "uncovered_negative_constraint")
            first = _fs[0]
            print(
                f"  {r['task_id']}: {_p} uncovered + {_n} neg-constraint  e.g. "
                f"[{first.get('coverage', '?')}] {first.get('sentence', '')[:100]}"
            )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {args.out}")
    # warn-tier: never fail-exit on findings (exit 1 is used only to signal "has
    # findings" for scripting; the orchestrator reads the JSON status, not the exit
    # code, matching every other warn-tier check in this folder).
    return 1 if n_warn else 0


if __name__ == "__main__":
    raise SystemExit(main())
