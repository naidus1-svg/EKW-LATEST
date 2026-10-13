"""Answer-key leakage check: mechanizes structural-audit pattern 4 ("Answer-key or
internal-pipeline leakage into the solver-facing prompt") as a pure text/regex scan, zero LLM
cost, over a task's `instruction.md` -- the actual solver-facing prompt -- plus a bonus filename
sweep of `environment/` (the solver's own workspace), since a leaked file is just as much a leak
sitting in the solver's directory listing as it is named in the prose.

Why this exists: `structural-audit/SKILL.md` pattern 4 names two concrete shapes -- a literal
`GOLDEN`/`Golden` reference-solution filename the solver is told to produce, and raw
internal-pipeline text (stage labels, bracketed build-system language) left inside
`instruction.md` that doesn't read like task content. Both are checkable without an LLM: filename
leakage is a substring check against every filename-shaped token in the prompt text, and pipeline
leakage is a keyword-plus-shape check against every bracketed span. This script does both.

## What it checks

1. Golden/reference-solution filename leakage (`find_filename_leaks`): every filename-shaped
   token in `instruction.md` (`word.ext`, ext in xlsx/xlsm/docx/doc/pptx/ppt/csv/pdf) is checked
   for:
     - `GOLDEN` or `Golden` as a case-SENSITIVE substring (deliberately not `golden` lowercase --
       a real business filename is very unlikely to carry the word capitalized like that, so
       case-sensitivity is most of this tell's precision).
     - `_SOLUTION`, `_ANSWER`, `_REFERENCE`, `_ANSWERKEY`, `_KEY` as case-INSENSITIVE substrings,
       each anchored so it cannot match as a mere prefix of a longer ordinary word (see "False
       positive found and fixed" below) -- `_Key_Metrics.xlsx` still matches `_KEY` (a real risk,
       disclosed in Known limits, not eliminated), but `_Answers.docx` (plural) no longer matches
       `_ANSWER`.
   The SAME filename-token scan also runs, as a bonus corroborating check, over every file's bare
   name under `environment/` (the solver's actual workspace -- NOT `solution/`, which is where a
   golden answer is supposed to live, invisible to the solver). A golden-named file sitting in the
   solver's own workspace is exactly this defect, just found by directory listing instead of
   prose.
2. Internal pipeline / build-system leakage (`find_bracket_leaks`): every `[...]` bracketed span
   in `instruction.md` (single-line only -- a span containing a newline is never treated as one
   directive) is checked for build-pipeline-jargon keywords (`node`, `pipeline`, `sequence`,
   `adjudicat*`, `apex`, `hold`, word-bounded so "shareholder"/"stakeholder"/"holding" never match
   "hold") and flagged only if it ALSO looks structurally like a directive rather than ordinary
   prose: either (a) two or more distinct keywords appear together in the same span, or (b) the
   span is short (10 words or fewer) with none of `,` `;` `:` inside it. Guard (a) alone would
   have caught the one historical example this script was asked to re-check (see below); guard
   (b) exists for a shorter directive that only carries one keyword.

## Verification against the real corpus

Corpus: `C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready`, 600 tasks with an
instruction.md (609 task directories total; 9 lack one). Nothing under that path was modified.

- Filename leakage, `--all` sweep: 12 real, currently-live hits, all under
  `## Graded deliverable filenames` -- i.e. the solver is told to submit a file by this literal
  name, not merely shown it in passing. Two distinct task families:
    - SVC-PC-88-2-0 through SVC-PC-88-7-0 (6 tasks): each names one graded filename following the
      template `L2-0N_..._Golden_..._Workpaper.xlsx` (e.g.
      `L2-03_Golden_Form_941_Tie_Out_Workpaper.xlsx`), alongside 0-2 other, non-Golden graded
      filenames for the same task. Sibling tasks in the same family with no golden-style name at
      all (SVC-PC-88-0-0, SVC-PC-88-1-0) confirm this is not just this family's normal naming
      convention -- it is six tasks out of eight.
    - SVC-PC-90-1-0 through SVC-PC-90-6-0 (6 tasks): the ONLY graded filename for each task is
      `L2-0N_<topic>_Golden.docx`.
  Every one of the 12 was read in full and by eye: all 12 are inside the
  `## Graded deliverable filenames` section (i.e. exact-match instructions to the solver, not
  incidental prose), none is explainable as a coincidental English phrase (unlike, say, "Golden
  State" as California's nickname -- checked for and not what this is: none of the 88-*/90-*
  topics are state-specific, and the template is uniform across six unrelated topics per family).
  Verdict: 12/12 genuine, 0 false positives in the flagged set.
  A prior report claimed a 13th case, SVC-PC-7-4-0
  (`Cirrus_Sleep_FY2022_Ops_Model_GOLDEN.xlsx` plus a bracketed pipeline directive). Checked
  fresh, not assumed: SVC-PC-7-4-0's current instruction.md (10 lines) contains neither "golden"
  in any case nor any bracket at all. That case has been remediated since the prior report; this
  script does not, and should not, re-assert it.
  False positive found and fixed during calibration: the naive (unanchored) substring form of
  this check also flagged SVC-PC-31-2-0's environment file
  `Product_Knowledge_Quiz_Answers.docx` on `_ANSWER` -- a real corpus business document (an
  employee product-knowledge quiz and its answer key, which is legitimate task content, not a
  leaked task answer key) whose plural "Answers" merely starts with the singular tell. Fixed by
  requiring the tell not be immediately followed by another letter, which blocks "_Answers",
  "_Referencing", "_Solutioning", "_Keynote", "_Answered" while still matching "_Answer.xlsx",
  "_Answer_Key.xlsx", "_ANSWERKEY.docx". Re-ran the full sweep after the fix: the one flagged
  filename hit is gone, 12/12 remaining filename hits are the genuine golden-family ones above,
  0 false positives in the final flagged set.
- Pipeline/bracket leakage, `--all` sweep: 0 flagged spans. Only 7 of 600 instruction.md files
  contain a `[` at all, and every bracketed span in those 7 was read by hand: 6 are placeholder
  addressee names in a memo header (`[the person pulling the plan together]`, one per
  SVC-PC-36-0-0 through SVC-PC-36-5-0 -- ordinary task content, a memo template blank, not
  pipeline text) and 1 is a numeric placeholder variable (`[X]` in SVC-PC-7-3-0, referring the
  solver to a named source file for the real value -- also ordinary task content). None contain
  any of the six directive keywords. Verdict: the corpus is currently clean of this specific
  defect shape; 0 false positives (nothing was flagged) and 0 false negatives found by the manual
  read (nothing that should have been flagged was missed).
  Because the corpus has zero real positives for this pattern right now, detection was proven
  against a synthetic fixture built for this purpose only, under a scratch temp path (never under
  the real corpus or this folder), reproducing the prior report's own claimed example almost
  verbatim: `[Sequence AFTER the node's apex gdpval_fit HOLD is adjudicated.]`. The detector fired
  (5 distinct keywords in one span; multi-keyword guard). The fixture was deleted immediately
  after the positive-control run; nothing from it is checked in.
- 10-clean-task negative control: SVC-PC-2-0-0, SVC-PC-5-0-0, SVC-PC-9-0-0, SVC-PC-15-0-0,
  SVC-PC-20-0-0, SVC-PC-25-0-0, SVC-PC-30-0-0, SVC-PC-40-0-0, SVC-PC-60-0-0, SVC-PC-70-0-0 --
  none mention "golden"/"Golden" in any form and none contain a `[` at all. All 10 report
  `status: pass`, 0 findings.

Status: v1, built and calibrated in one pass against the full 600-task corpus above (not a
sample), following `deliverable_count_check.py`'s precedent in this same repo for what "full
corpus calibration" means here.

Known limits, disclosed rather than silently dropped:
    - Pattern 1 is a literal-substring check on filename-SHAPED tokens only (must end in one of
      the eight listed extensions). A leaked reference-solution filename mentioned without an
      extension, split across a markdown line wrap, or using an extension outside that list
      (`.txt`, `.md`, `.zip`, ...) reads as a false "clean" -- this mirrors
      `deliverable_filename_check.py`'s own disclosed literal-substring limit in this folder.
    - `_KEY` is the highest false-positive-risk tell of the remaining case-insensitive ones: "key"
      is ordinary English business vocabulary ("key metrics", "key assumptions", "key findings").
      It produced zero hits in this 600-task corpus even after the word-boundary fix, but a
      corpus with a filename like `FY2022_Key_Assumptions.xlsx` would flag it, and that flag
      would be a false positive a reviewer needs to dismiss by eye, not a script bug. Treat a
      `_KEY` hit with more scrutiny than a `GOLDEN`/`Golden` hit.
    - `_REFERENCE` standalone is NOT a tell (see comment above `_REFERENCE_COMPOUND_RE`): a
      real-corpus false positive (task_133 outside the 600-task SVC-PC corpus this script was
      calibrated against -- `environment/data/denial_reason_code_reference.docx`, a legitimate
      denial-code-to-payer-category crosswalk the solver is required to use, confirmed NONSENSE
      on manual review) showed that "reference" alone describes a lookup table's FUNCTION, not
      that it's a copy of the answer key. `_REFERENCE` now only fires compounded with `ANSWER`,
      `SOLUTION`, `GOLDEN`, or `KEY` (e.g. `_ANSWER_REFERENCE.xlsx`, `_REFERENCE_SOLUTION.docx`).
      This is a recall narrowing, disclosed rather than silently absorbed: a leaked file named
      with "reference" alone and no co-occurring answer-implying word (e.g. a hypothetical
      `Golden_Output_Reference.xlsx` split so "Golden" and "Reference" are not adjacent
      underscore-delimited tokens) would no longer be caught by this tell -- though `GOLDEN`
      would still independently catch that specific example.
    - The five non-GOLDEN tells only match with their leading underscore present, per this
      script's spec (`_ANSWER`, not bare `ANSWER`). A CamelCase or space-separated leak
      (`AnswerKey.xlsx`, `Answer Key.xlsx`) is not caught by this check. `_ANSWERKEY` catches the
      underscored one-word form; nothing here catches the space-separated form since a space is
      not part of a single filename token to begin with.
    - Pattern 2's keyword list (`node`, `pipeline`, `sequence`, `adjudicat*`, `apex`, `hold`) came
      from the six-defect taxonomy's own worked example, the only real specimen of this defect
      shape on record, and this corpus currently has zero live specimens to calibrate further
      against. The list is a reasonable starting point, not a validated one -- a future genuine
      positive with different vocabulary (e.g. "stage", "gate", "batch", "checkpoint") would not
      be caught until someone adds that word here. This is a recall gap, disclosed rather than
      guessed away.
    - Pattern 2 only scans `instruction.md`, matching `structural-audit/SKILL.md`'s own
      methodology step 5, which names only instruction.md for the bracket check. Bracket-shaped
      text inside an `environment/` file's own CONTENT (as opposed to its filename, which IS
      checked) is out of scope here.
    - The `environment/` filename sweep only inspects bare filenames, never file content. A
      golden answer accidentally embedded inside an otherwise-ordinary-named file (e.g. a stray
      tab in a workbook) is invisible to this check; that is `deliverable_integrity_check.py` /
      Oracle territory, not this one.
    - This script checks the CURRENT on-disk state of the task directory under --root. It says
      nothing about whether a task was broken in the past (or, per the SVC-PC-7-4-0 case above,
      already fixed) and has since changed.

Usage:
    python answer_key_leakage_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python answer_key_leakage_check.py --all --root <path> --out report.json
    python answer_key_leakage_check.py --all --root <path> --id-prefix MYBENCH- --out report.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows console defaults to cp1252, which can't encode every character that shows up in a
# real task's instruction.md (curly quotes, em dashes in vendored text, non-Latin corpus paths).
# Force UTF-8 with replacement so a printable-but-non-cp1252 character never crashes a batch run
# partway through.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# pattern 1: golden / reference-solution filename leakage
# ---------------------------------------------------------------------------

FILENAME_EXTS = r"xlsx|xlsm|docx|doc|pptx|ppt|csv|pdf"
FILENAME_TOKEN_RE = re.compile(rf"\b[\w][\w\-]*\.(?:{FILENAME_EXTS})\b")

# Case-sensitive on purpose: a real business filename is very unlikely to carry "GOLDEN" or
# "Golden" capitalized like this, so case sensitivity alone does most of this tell's precision
# work. Checked as a plain substring, per this check's spec.
GOLDEN_TELLS = ("GOLDEN", "Golden")

# Case-insensitive, but each anchored with a negative lookahead so it cannot match as a bare
# prefix of a longer, ordinary word ("_Answers", "_Referencing", "_Solutioning", "_Keynote",
# "_Answered" must NOT match "_ANSWER"/"_REFERENCE"/"_SOLUTION"/"_KEY"). See the module docstring
# ("False positive found and fixed") for the real corpus case this exists to exclude.
OTHER_TELLS = ("_SOLUTION", "_ANSWER", "_REFERENCE", "_ANSWERKEY", "_KEY")

# `_REFERENCE` alone is not a leak tell: unlike "_SOLUTION"/"_ANSWER"/"_KEY", which only make
# sense in a filename if the file itself purports to BE the answer, "reference" is ordinary
# vocabulary for a lookup table / crosswalk / data dictionary the solver is meant to consult
# while working -- e.g. `denial_reason_code_reference.docx`, a legitimate internal-code-to-
# payer-category crosswalk shipped in `environment/data/` (task_133, real corpus false positive:
# flagged and confirmed NONSENSE by manual read -- the file has no golden answer, no verifier-
# derived figures, and tests/verifier.json requires the solver to actively USE this exact
# crosswalk, i.e. it is required input, not a leaked output). In the 600-task calibration sweep
# in this docstring, `_REFERENCE` contributed 0 of the 12 confirmed true positives (all 12 were
# `GOLDEN`/`Golden`) and 1 confirmed false positive since -- net negative signal on its own.
# The real defect this tell exists for is a *reference copy of the solution* (e.g.
# `Q3_GOLDEN_REFERENCE.xlsx`, `Answer_Reference_Sheet.docx`), which always co-occurs with
# another answer-implying word in practice. So `_REFERENCE` only counts as a tell when compounded
# with one of `ANSWER`/`SOLUTION`/`GOLDEN`/`KEY` (either order, one underscore-delimited word
# apart) -- a standalone "*_reference.ext" no longer matches at all.
_REFERENCE_COMPOUND_RE = re.compile(
    r"(?:_(?:ANSWER|SOLUTION|GOLDEN|KEY)_REFERENCE(?![A-Za-z]))"
    r"|(?:_REFERENCE_(?:ANSWER|SOLUTION|GOLDEN|KEY)(?![A-Za-z]))",
    re.IGNORECASE,
)


def _make_other_tell_pattern(tell):
    if tell == "_REFERENCE":
        return _REFERENCE_COMPOUND_RE
    return re.compile(re.escape(tell) + r"(?![A-Za-z])", re.IGNORECASE)


_OTHER_TELL_RES = [(tell, _make_other_tell_pattern(tell)) for tell in OTHER_TELLS]


def filename_tells(token):
    """Returns the list of tell strings (e.g. "Golden", "_ANSWER") that matched inside one
    filename-shaped token. Empty list if the token is clean."""
    matched = []
    for tell in GOLDEN_TELLS:
        if tell in token:
            matched.append(tell)
    for tell, pattern in _OTHER_TELL_RES:
        if pattern.search(token):
            matched.append(tell)
    return matched


def find_filename_leaks(text):
    """Scans instruction.md's raw text for filename-shaped tokens carrying a golden/
    reference-solution tell. Returns a list of {filename, line, tells} sorted by first
    appearance, one entry per unique (filename, tell-set) -- a filename repeated verbatim later
    in the same file is not reported twice."""
    seen = set()
    leaks = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in FILENAME_TOKEN_RE.finditer(line):
            token = m.group(0)
            tells = filename_tells(token)
            if not tells:
                continue
            key = (token, tuple(tells))
            if key in seen:
                continue
            seen.add(key)
            leaks.append({"filename": token, "line": lineno, "tells": tells})
    return leaks


def find_environment_filename_leaks(task_dir):
    """Bonus corroborating check: every bare filename under environment/ (the solver's actual
    workspace), NOT solution/ (where a golden answer is supposed to live, invisible to the
    solver). Returns a list of {path, tells} relative to task_dir. Never raises -- a permission
    error or an exotic filename on one file does not abort the scan of the rest."""
    leaks = []
    env_dir = task_dir / "environment"
    if not env_dir.is_dir():
        return leaks
    seen = set()
    try:
        walker = env_dir.rglob("*")
    except OSError:
        return leaks
    for f in walker:
        try:
            if not f.is_file():
                continue
            name = f.name
        except OSError:
            continue
        tells = filename_tells(name)
        if not tells:
            continue
        try:
            rel = str(f.relative_to(task_dir)).replace("\\", "/")
        except ValueError:
            rel = str(f)
        key = (rel, tuple(tells))
        if key in seen:
            continue
        seen.add(key)
        leaks.append({"path": rel, "tells": tells})
    return leaks


# ---------------------------------------------------------------------------
# pattern 2: internal pipeline / build-system leakage
# ---------------------------------------------------------------------------

# One bracketed span, single-line only: a span containing a newline is never treated as one
# directive (nothing in the real corpus does this, and allowing it would risk swallowing large,
# unrelated stretches of ordinary prose between two unrelated brackets).
BRACKET_RE = re.compile(r"\[([^\[\]\n]{1,400})\]")

# Word-bounded so "shareholder"/"stakeholder"/"holding"/"household"/"threshold" never match
# "hold", and "adjudicat*" catches "adjudicate"/"adjudicated"/"adjudication". This list is the
# six-defect taxonomy's own worked example vocabulary; see "Known limits" in the module docstring
# for why it is a starting point, not a validated set.
DIRECTIVE_KEYWORD_RE = re.compile(
    r"\b(node|pipeline|sequence|adjudicat\w*|apex|hold)\b", re.IGNORECASE
)

SENTENCE_PUNCT_RE = re.compile(r"[,;:]")
SHORT_CLAUSE_MAX_WORDS = 10


def classify_bracket_span(inner_text):
    """Returns (flagged: bool, keywords: list[str], reason: str) for one bracket span's inner
    text (without the brackets themselves).

    Flags when EITHER:
      (a) two or more distinct directive keywords appear together in the same span -- this alone
          would have caught the taxonomy's own worked example
          ("[Sequence AFTER the node's apex gdpval_fit HOLD is adjudicated.]", 5 keywords), or
      (b) the span is short (10 words or fewer) with no comma/semicolon/colon inside it AND
          carries at least one keyword -- for a shorter directive that only uses one keyword.
    A bracket with zero directive keywords is never flagged regardless of shape: "[the person
    pulling the plan together]" and "[X]" (both real, both ordinary task content in this corpus)
    have no keyword and so never reach either branch.
    """
    keywords = sorted(
        set(m.group(0).lower() for m in DIRECTIVE_KEYWORD_RE.finditer(inner_text))
    )
    if not keywords:
        return False, [], "no directive keyword present"

    if len(keywords) >= 2:
        return (
            True,
            keywords,
            f"{len(keywords)} distinct pipeline-directive keywords in one bracketed span",
        )

    word_count = len(inner_text.split())
    has_sentence_punct = bool(SENTENCE_PUNCT_RE.search(inner_text))
    if word_count <= SHORT_CLAUSE_MAX_WORDS and not has_sentence_punct:
        return (
            True,
            keywords,
            f"short ({word_count}-word) bracketed clause with no sentence punctuation, "
            f"carrying the directive keyword {keywords[0]!r}",
        )

    return (
        False,
        keywords,
        (
            f"keyword {keywords[0]!r} present but the span reads as ordinary prose "
            f"({word_count} words, sentence punctuation present)"
            if has_sentence_punct
            else f"keyword {keywords[0]!r} present but the span is too long "
            f"({word_count} words) to read as a short directive"
        ),
    )


def find_bracket_leaks(text):
    """Scans instruction.md's raw text for bracketed spans that look like an internal
    pipeline/build-system directive rather than task content. Returns only the FLAGGED spans,
    each with the exact quoted text (never a paraphrase)."""
    leaks = []
    for m in BRACKET_RE.finditer(text):
        inner = m.group(1)
        flagged, keywords, reason = classify_bracket_span(inner)
        if not flagged:
            continue
        line = text[: m.start()].count("\n") + 1
        leaks.append(
            {
                "text": m.group(0),
                "line": line,
                "keywords": keywords,
                "reason": reason,
            }
        )
    return leaks


# ---------------------------------------------------------------------------
# task discovery
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


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir):
    """Returns a result dict for one task. Never raises -- a missing instruction.md or an
    unreadable environment/ file is reported as a skip/empty finding, not a crash."""
    task_id = task_dir.name
    result = {
        "task_id": task_id,
        "instruction_md_exists": False,
        "environment_dir_exists": (task_dir / "environment").is_dir(),
        "instruction_filename_leaks": [],
        "environment_filename_leaks": [],
        "bracket_leaks": [],
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
        text = instr_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        result["status"] = "skip"
        result["errors"].append(f"could not read instruction.md: {e}")
        return result

    result["instruction_filename_leaks"] = find_filename_leaks(text)
    result["environment_filename_leaks"] = find_environment_filename_leaks(task_dir)
    result["bracket_leaks"] = find_bracket_leaks(text)

    any_finding = bool(
        result["instruction_filename_leaks"]
        or result["environment_filename_leaks"]
        or result["bracket_leaks"]
    )
    result["status"] = "fail" if any_finding else "pass"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Check instruction.md (plus a bonus environment/ filename sweep) for "
        "answer-key or internal-pipeline leakage into the solver-facing prompt "
        "(structural-audit pattern 4)."
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
        "this must not silently assume a project-specific path)",
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
                "status": "fail",
                "errors": [f"unhandled exception analyzing this task: {e}"],
                "instruction_filename_leaks": [],
                "environment_filename_leaks": [],
                "bracket_leaks": [],
            }
        results.append(r)
        n_findings = (
            len(r.get("instruction_filename_leaks", []))
            + len(r.get("environment_filename_leaks", []))
            + len(r.get("bracket_leaks", []))
        )
        print(
            f"    -> {r['status']}  ({n_findings} finding(s), {len(r.get('errors', []))} errors)",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_skip": n_skip,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_skip} skip out of {len(results)} task(s)"
    )
    for r in results:
        note_parts = []
        for leak in r.get("instruction_filename_leaks", []):
            note_parts.append(
                f"instruction.md filename {leak['filename']!r} ({leak['tells']})"
            )
        for leak in r.get("environment_filename_leaks", []):
            note_parts.append(
                f"environment/ filename {leak['path']!r} ({leak['tells']})"
            )
        for leak in r.get("bracket_leaks", []):
            note_parts.append(f"bracket {leak['text']!r}")
        note = "  [" + "; ".join(note_parts) + "]" if note_parts else ""
        print(f"  {r['task_id']}: {r['status']}{note}")
        for e in r.get("errors", []):
            print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
