#!/usr/bin/env python3
"""
discretion_pin_scan.py - GATE-V2 class S / 3.2 map (f): the instruction
grants the solver discretion over a decision, and a criterion in judge.toml
pins that same decision to one specific answer anyway.

Canonical example (53-0-0): instruction.md:7 "Make your own calls and note
your assumptions as you go." -- a blanket, task-wide grant, tied to no
particular topic in its own sentence. Criterion r003c's Expected text ("The
2 swing seats held as reserve, not filled as the budget file's Growth-Mktg
Mgr + SWE.") pins one specific treatment of a decision the resourcing
workbook itself permits either way (eval_471915 made the other call,
documented the trade-off, and lost r003c at 0.974; eval_471914 made the
same call as the golden and was credited -- so the criterion is also
nondeterministic per GATE-V2 1c).

Phrase list is the UNION of two sources that don't quite agree: the task
brief that commissioned this script ("make your own call(s)", "your
judgment", "propose", "you decide", "at your discretion", "your
recommendation") and GATE-V2.md 3.2 map (f) itself ("make your own call",
"your judgment", "propose", "recommend", "you decide"). The union adds bare
"recommend" (48/202 tasks) and "we recommend" on top of the brief's list.
Every phrase is a literal candidate signal, not a defect by itself --
"recommend a renewal action" in an instruction's Required-work list is
exactly the kind of legitimate, bounded ask map (f) also has to see, and
the CR decides which occurrences are really open decisions.

TWO-TIER matching, because the canonical case does not fit a single
heuristic:

  Tier 1 (topic-overlap): for a discretion phrase tied to a specific ask in
  its own sentence (e.g. 25-4-0 "recommend a renewal action, owner, and
  timing"), keyword-overlap the sentence against every criterion's Expected
  text (reusing the corpus's own "Expected:" marker convention, same split
  used by rubric_consistency_scan.py). Overlap = |shared| / min(|sentence
  kws|, |expected kws|), kept at >=0.25 with >=2 shared keywords.

  Tier 2 (blanket fallback): the four BLANKET-labeled phrases ("make your
  own call(s)", "your judgment", "at your discretion", "you decide") carry
  no topical anchor of their own -- 53-0-0's grant sentence never says
  "reserve" or "seats". When a task has a blanket phrase and Tier 1 found
  NOTHING anywhere in the task, fall back to every criterion whose Expected
  text carries an explicit contrast marker ("not X", "rather than X",
  "instead of X", "as opposed to X") -- the textual shape of "one specific
  choice pinned against an alternative" that map (f) is looking for. This
  is what catches r003c's "not filled as the budget file's Growth-Mktg Mgr
  + SWE." "recommend" and "propose" are excluded from the blanket fallback
  on purpose: they fire on 24% and 11% of the corpus respectively and
  usually do carry their own topic (Tier 1 territory), so routing them
  through Tier 2 as well would flood the CSV with noise disproportionate to
  the signal.

Both tiers are candidates only -- verdict is pass/warn, never fail. Map (f)
itself says "the fix is decision-neutral grading ... never a pinned
outcome", and confirming a pin is really ungrounded requires reading the
source the decision rests on (3.3 S), which this static scan cannot do.

READ-ONLY. Run corpus-wide (instruction.md + judge.toml only -- no
document extraction, so it is fast).

Output: CSV [task, discretion_phrase, criterion_id, pinned_expected,
match_basis, overlap, discretion_sentence] at
reports/discretion_pin.csv. match_basis in {topic-overlap,
blanket-contrast-marker}; overlap is numeric for topic-overlap, "" for the
blanket fallback (no score, textual-shape match only).

Usage:
    python3 discretion_pin_scan.py [--corpus-root PATH] [--out PATH]
        [--task NAME] [--verdict-out PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import (
    DEFAULT_CORPUS_ROOT,
    DEFAULT_REPORTS_DIR,
    list_tasks,
    normalize_keywords,
    read_text_safe,
    write_csv,
)

# (label, is_blanket, regex). is_blanket marks phrases with no topical
# anchor of their own -- see module docstring, Tier 2.
DISCRETION_PATTERNS: list[tuple[str, bool, re.Pattern]] = [
    ("make your own call(s)", True, re.compile(r"\bmake\s+your\s+own\s+calls?\b", re.I)),
    ("your judgment", True, re.compile(r"\byour\s+judg(?:e)?ment\b", re.I)),
    ("at your discretion", True, re.compile(r"\bat\s+your\s+discretion\b", re.I)),
    ("you decide", True, re.compile(r"\byou\s+decide\b", re.I)),
    ("your recommendation(s)", False, re.compile(r"\byour\s+recommendations?\b", re.I)),
    ("we recommend", False, re.compile(r"\bwe\s+recommend\b", re.I)),
    ("recommend", False, re.compile(r"\brecommend(?:s|ed|ing)?\b", re.I)),
    ("propose", False, re.compile(r"\bpropos(?:e|es|ed|ing|al|als)\b", re.I)),
]

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_EXPECTED_SPLIT_RE = re.compile(r"\bExpected\s*:\s*", re.IGNORECASE)
_CONTRAST_RE = re.compile(r"\b(not|rather than|instead of|as opposed to)\b", re.IGNORECASE)

TIER1_MIN_OVERLAP = 0.25
TIER1_MIN_SHARED = 2
TIER1_MAX_PER_PHRASE = 5


def extract_discretion_phrases(text: str) -> list[tuple[str, bool, str]]:
    """(label, is_blanket, sentence) per match, sentence-split like
    _qc_common.extract_quantifier_phrases. Deduped by (label, sentence) by
    the caller (a sentence naming the same phrase twice is not a second
    occurrence)."""
    out: list[tuple[str, bool, str]] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for label, is_blanket, rx in DISCRETION_PATTERNS:
            if rx.search(sentence):
                out.append((label, is_blanket, sentence))
    return out


def load_criteria(task_dir: Path) -> list[tuple[str, str, str]]:
    """(criterion_name, full_description, expected_text) across every
    tests/deliverables_*/judge.toml in the task. expected_text is the
    description text after the literal "Expected:" marker, or the full
    description if there is no marker (same convention as
    rubric_consistency_scan.py's _primary_figure)."""
    out: list[tuple[str, str, str]] = []
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
            parts = _EXPECTED_SPLIT_RE.split(desc, maxsplit=1)
            expected = parts[1].strip() if len(parts) > 1 else desc.strip()
            out.append((name, desc.strip(), expected))
    return out


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def scan_task(task_dir: Path) -> list[tuple[str, str, str, str, str, str, str]]:
    """Returns rows: (task, discretion_phrase, criterion_id, pinned_expected,
    match_basis, overlap, discretion_sentence)."""
    instr = task_dir / "instruction.md"
    prompt = task_dir / "tests" / "task_prompt.txt"
    text = read_text_safe(instr) + "\n" + read_text_safe(prompt)
    if not text.strip():
        return []

    phrases = sorted(set(extract_discretion_phrases(text)))
    if not phrases:
        return []

    criteria = load_criteria(task_dir)
    if not criteria:
        return []

    rows: list[tuple[str, str, str, str, str, str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()  # (phrase_label, criterion_id) dedupe

    # Tier 1: topic overlap, every phrase occurrence against every criterion.
    for label, is_blanket, sentence in phrases:
        sent_kws = normalize_keywords(sentence)
        candidates = []
        for name, _desc, expected in criteria:
            exp_kws = normalize_keywords(expected)
            ov = _overlap(sent_kws, exp_kws)
            shared = len(sent_kws & exp_kws)
            if ov >= TIER1_MIN_OVERLAP and shared >= TIER1_MIN_SHARED:
                candidates.append((ov, name, expected))
        candidates.sort(key=lambda t: -t[0])
        for ov, name, expected in candidates[:TIER1_MAX_PER_PHRASE]:
            key = (label, name)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            rows.append((task_dir.name, label, name, expected, "topic-overlap", f"{ov:.2f}", sentence))

    # Tier 2: blanket fallback, only if Tier 1 found nothing at all in this
    # task and at least one blanket phrase occurred.
    if not rows:
        blanket_phrases = [(label, sentence) for label, is_blanket, sentence in phrases if is_blanket]
        if blanket_phrases:
            fallback_label, fallback_sentence = blanket_phrases[0]
            for name, _desc, expected in criteria:
                if _CONTRAST_RE.search(expected):
                    key = (fallback_label, name)
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    rows.append(
                        (task_dir.name, fallback_label, name, expected, "blanket-contrast-marker", "", fallback_sentence)
                    )

    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "discretion_pin.csv")
    ap.add_argument("--task", type=str, default=None)
    ap.add_argument("--verdict-out", type=Path, default=None, help="write per-task verdict CSV [task_id, discretion_pin]")
    args = ap.parse_args()

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple[str, str, str, str, str, str, str]] = []
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        try:
            all_rows.extend(scan_task(task_dir))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 50 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned", file=sys.stderr)

    n = write_csv(
        args.out,
        ["task", "discretion_phrase", "criterion_id", "pinned_expected", "match_basis", "overlap", "discretion_sentence"],
        all_rows,
    )
    tasks_flagged = {r[0] for r in all_rows}
    tier1 = sum(1 for r in all_rows if r[4] == "topic-overlap")
    tier2 = sum(1 for r in all_rows if r[4] == "blanket-contrast-marker")

    print(f"discretion_pin_scan: {n} candidate pins across {len(tasks_flagged)} of {len(tasks)} tasks, written to {args.out}")
    print(f"  {tier1} topic-overlap, {tier2} blanket-contrast-marker (fallback)")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = []
        for task_dir in tasks:
            verdict = "warn" if task_dir.name in tasks_flagged else "pass"
            verdict_rows.append((task_dir.name, verdict))
        write_csv(args.verdict_out, ["task_id", "discretion_pin"], verdict_rows)
        print(f"discretion_pin_scan: verdicts written to {args.verdict_out} "
              f"({len(tasks_flagged)} warn, {len(tasks) - len(tasks_flagged)} pass; no fail path -- see docstring)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
