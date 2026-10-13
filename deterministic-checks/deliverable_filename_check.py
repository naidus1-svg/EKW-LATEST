"""Deliverable filename check, both directions between a task's judge.toml and its solver-facing
instruction.md:

  FORWARD  -- does every filename judge.toml expects get named, literally, somewhere in
              instruction.md? (unchanged from the original version of this script)
  REVERSE  -- does instruction.md COMMAND the solver, via directive language ("save as",
              "name the file", "produce a file called", a "## Graded deliverable filenames"
              section, etc.), to produce a specific filename that judge.toml's [judge].files
              list does NOT contain at all?

Why this exists: a Harbor task's judge.toml tells the grader which filenames it expects (its
top-level `[judge] files = [...]` list). If instruction.md never names one of those filenames
(FORWARD), the solver has no way to know what output file to produce. The REVERSE direction is
worse, not merely the mirror image: an agent that follows instruction.md exactly writes the file
it was explicitly told to write, and the grader never opens it -- a silent zero, with the agent
having done nothing wrong. Both are concrete defect shapes Jafar's manual reviews found on the
pool22/885 and GDM5 datasets (see `structural-audit/SKILL.md`'s deliverable-filename-mismatch
pattern, whose own real example is the REVERSE direction: "instruction.md demanded two specific
golden-style filenames; the verifier read two entirely different paths"). This script is a purely
mechanical, deterministic text-presence check for both defect shapes: zero LLM cost, and it
catches the mismatch before an expensive human or judge review.

The two directions are independent and a task can fail either without failing the other: a task
can name every judge.toml filename somewhere in its prose (FORWARD pass) while ALSO commanding
three unrelated filenames in a "Graded deliverable filenames" footer that judge.toml never reads
(REVERSE fail) -- see SVC-PC-6-0-0 in the corpus this was calibrated against, where judge.toml
reads `Cover_Memo.docx` (named in the prompt body, so FORWARD passes) while the footer commands
`README.md`, `Question_Source_Map_and_Remediation.xlsx`, and `Governance_and_Corporate_Summary.docx`
(none graded, so REVERSE fails on all three).

Provenance: this check's real logic started as a disposable scratch file
(`turing-context/ekw/_scratch_filename_mechanical_check.py`) -- a hardcoded task-ID root
(`C:\\ekwqc\\repo\\...`), no CLI at all, and a regex `re.search(r"files\\s*=\\s*\\[(.*?)\\]", ...)`
against the raw judge.toml text. That regex breaks on anything but the simplest single-line
array: a multi-line files=[...] list, an inline comment, a nested-quote filename, or a second
`files = [...]` key elsewhere in the same file (e.g. inside a differently-shaped table) all
produce a wrong extraction silently, with no parse error to signal it. This copy replaces the
regex with `tomllib` -- the same approach `formula_health_check.py`'s `load_judge_criteria()`
uses -- adds a full CLI (--root required with no default, --all, --id-prefix, --out), and
generalizes away the hardcoded root path and task-ID assumptions. The check itself is otherwise
unchanged: is each judge.toml filename a literal substring of instruction.md's text is exactly
the scratch file's original idea, and that idea was never in question -- only its parser was.

Status: recently promoted from a disposable scratch-file implementation -- less battle-tested
than the formula-health pair, but the core check (literal filename presence) is simple enough to
trust once verified against a few known cases.

Usage:
    python deliverable_filename_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python deliverable_filename_check.py --all --root <path> --out report.json
    python deliverable_filename_check.py --all --root <path> --id-prefix MYBENCH- --out report.json

What it does, in order:

1. For a given task id (or --all tasks under --root), finds every judge.toml one level under
   that task's tests/ directory (tests/*/judge.toml -- any subdirectory name, not restricted to
   a "deliverables_*" prefix, since the source pipeline's own layout varies and the scratch
   file's original scan was similarly unrestricted).
2. Parses each with `tomllib` (never regex) and reads the top-level `[judge].files` list -- the
   same field `formula_health_check.py`'s `load_judge_criteria()` reads for the same purpose.
   A judge.toml that fails to parse is recorded in that task's `parse_errors` and skipped; it
   does not fail the whole task if other judge.toml files under the same task parse fine.
3. Reduces every expected path to its basename: a judge.toml entry like "solution/output.xlsx"
   is named in instruction.md as "output.xlsx", not the full relative path, so the path prefix
   would only ever produce false negatives if checked literally.
4. Reads instruction.md once per task and checks, per basename, whether it appears anywhere in
   the raw text as a literal substring (case-sensitive, matching the scratch file's original
   behaviour).
5. Reports per task: which filenames were found, which were missing, which judge.toml file(s)
   contributed each expected filename, and any judge.toml parse errors. Writes one JSON result
   per task plus an aggregate pass/fail/skip summary across every task given on the command line
   (or discovered via --all).

That is the whole FORWARD-direction check, unchanged from the original version of this script.
The REVERSE direction runs alongside it, over the same instruction.md text, in two tiers:

6. Tier 1 (primary, ~98% of a 600-task corpus this was calibrated against): look for a
   `## Graded deliverable filenames` heading (case-insensitive, any `#` depth). In every corpus
   instruction.md that carries this heading it is the LAST section of the document, its intro
   line is always "Submit the graded deliverables using these exact filenames...", and every
   line under it is always exactly one markdown bullet holding exactly one backtick-quoted
   filename or path -- nothing else ever shares the section. Because that shape is so uniform,
   Tier 1 does not run a filename-shaped regex against the section at all: it takes each bullet's
   backtick content VERBATIM. That matters because real filenames in this corpus can contain
   spaces, commas, and ampersands ("Cirrus Sleep, Inc. FY21 Databook.xlsx", "Apex Crisis
   Post-Mortem & Dual-3PL Decision.docx") that a restrictive filename regex would truncate --
   an early version of this check's regex did exactly that and manufactured dozens of false
   "commanded" filenames that were really just the tail end of a longer real one split at the
   first "&" or ",". Taking the bullet verbatim sidesteps the whole problem.
7. Tier 2 (fallback, for the ~2% of instruction.md files with no such heading): scan the full
   text for a curated set of directive-language patterns calibrated against this corpus's actual
   phrasing -- an imperative "Deliver <file>.", a labeled "Artifact: <file>" line, "...using
   exactly this filename: <file>", "save/submit ... as <file>", "name the file <file>", "a file
   called/named <file>", "the deliverable is <file>". Unlike Tier 1, Tier 2 has no clean
   bullet-per-line structure to exploit, so it constrains the filename token itself to a strict,
   space-free, underscore/hyphen character class. That constraint is deliberate, not an
   oversight: an early version allowed spaces in the token and "Deliver only the completed
   Financial_Model_v1.xlsx" (prose describing a constraint, not naming a new file) matched the
   whole run of words as if it were one filename. Tightening the token to disallow spaces
   eliminated every one of those false matches in the calibration corpus without losing a single
   real one (every genuine Tier-2 match found -- SVC-PC-5-1-0, 13-3-0, 13-6-0, 13-7-0, 16-3-0 --
   already used bare underscore-style names with no spaces).
8. Every filename Tier 1 or Tier 2 extracts is reduced to its basename (same `basename()` used
   for the FORWARD direction, for the same reason: a path prefix in the commanded text or in
   judge.toml would otherwise produce a false contradiction). Any commanded basename absent from
   every judge.toml `[judge].files` list under the task is reported in `commanded_but_not_graded`,
   with the pattern name and raw matched text kept for provenance. The complementary set,
   `commanded_and_graded`, is kept too -- it is what lets a task pass FORWARD and REVERSE both,
   which is the common case.
9. The REVERSE direction is only evaluated when the task has at least one judge.toml
   `[judge].files` entry to check against (the same condition that gives FORWARD a "skip" instead
   of a pass/fail). Without an expected-files set, "not graded" is trivially true for anything
   ever named in the prompt and carries no information beyond what the FORWARD skip already says
   -- so REVERSE also reports "skip" in that case, not a manufactured "fail". If there IS an
   expected-files set but neither tier extracts any commanded filename at all (a real, common
   case in this corpus: many instruction.md files never name their own output file anywhere,
   which is itself a FORWARD-direction defect, not a REVERSE one), REVERSE reports "skip" too --
   there is nothing to contradict judge.toml in that case, not evidence that nothing is wrong.
10. Per-task and aggregate status now come in three flavours: `forward_status` (identical to the
    original, unrenamed `status` field -- kept for both directions' own sake and for any existing
    consumer of `status`), `reverse_status`, and `combined_status`, which is `fail` if either
    direction fails, `pass` only if both pass, and `skip` otherwise (mirrors the existing
    single-direction skip semantics: skip is never itself a claim that a task is fine).

Known limits, disclosed rather than silently dropped:
    - Literal substring match only, case-sensitive. A filename referenced with different casing,
      or split across a line wrap or a markdown table cell boundary, reads as a false "missing."
      This is a mechanical presence check, not a semantic one.
    - Only a judge.toml's top-level `[judge].files` list is checked. A criterion-level files=[...]
      override (if a package ever uses one) is out of scope here -- that shape of file resolution
      is `formula_health_check.py`'s territory via its own `load_judge_criteria()` /
      `resolve_graded_files()`.
    - A task is marked "skip" (not "fail") when it has no instruction.md, no tests/*/judge.toml,
      or a judge.toml with no files=[...] entries to check. "skip" is not itself a claim that the
      task is fine -- it means this check found nothing to verify.
    - This script checks the CURRENT on-disk state of the task directory under --root. It says
      nothing about whether a task was broken in the past and has since been fixed by other work.
    - REVERSE-direction limits, specific to that new check:
        - Tier 1's "take the bullet verbatim" approach is only as good as the heading match. A
          document that renames the heading to something Tier 1 doesn't recognise (this script
          matches "graded deliverable filenames" case-insensitively at any `#` depth) falls
          through to Tier 2, whose directive-language patterns are a curated list, not an
          exhaustive grammar of English imperatives -- a genuinely commanded filename phrased in
          a way none of the eight Tier 2 patterns anticipates is missed silently, the same
          silent-miss shape the FORWARD direction already discloses for casing/line-wrap.
        - Tier 2's filename token deliberately excludes spaces, commas, and ampersands to avoid
          swallowing surrounding prose (see point 7 above). If a non-Tier-1-heading document ever
          commands a human-readable filename containing those characters, Tier 2 will not extract
          it at all -- a false negative, not a false positive. Every real Tier-2 case found in the
          600-task calibration corpus was a plain underscore-style name, but that is a property of
          this corpus's phrasing conventions, not a guarantee about any other corpus.
        - The extension whitelist (xlsx, xlsm, docx, docm, pptx, pptm, csv, pdf, json, md, txt,
          zip) is calibrated from every extension actually seen in this corpus's judge.toml
          `files=` entries, padded with the other common Office/text variants. A task whose
          graded deliverable uses an extension outside this list is invisible to REVERSE
          extraction entirely (it would also fail to be flagged as a false "commanded" match, so
          this errs toward under-flagging, not over-flagging).
        - REVERSE inherits FORWARD's basename-only comparison (point 3). Two different files that
          happen to share a basename in different directories would look identical to this check;
          the calibration corpus never exhibited that shape, but it is worth naming.
        - REVERSE only ever reports "skip" when there is truly nothing to check in that direction
          (no judge.toml files= set, or no commanded filename extracted at all) -- it does not
          independently down-rank a task the FORWARD direction already marked "skip" for a
          different reason; the two directions' "skip" can and do fire for different underlying
          reasons on the same task, and both are reported rather than collapsed into one.

Provenance (REVERSE direction, added on top of the FORWARD provenance above): built by reading
10+ real instruction.md files with a judge.toml files=[...] list in the 600-task corpus at
`C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready` to see how commanded filenames are
actually phrased before writing any extraction regex (per structural-audit/SKILL.md's own
methodology: read the real files, don't infer phrasing from a description of the pattern). Two
regex-design mistakes were caught and fixed during that calibration by running the prototype
against the full corpus and reading the diffs, not by inspection alone -- both are described
under Known limits above, and both were the direct result of trying to use one generic
filename-shaped regex everywhere instead of exploiting Tier 1's much stronger structural
guarantee. A full --all sweep of the extended script across all 600 tasks found 4 tasks flagged
by FORWARD only, 24 by REVERSE only, and 2 by both (one of the "both" pairs is itself informative:
FORWARD and REVERSE flag the SAME missing file under two different extensions -- `.xlsx` expected
by judge.toml, `.xlsm` commanded by instruction.md -- which is a real extension-typo defect
neither direction alone states as plainly as the pair does together). Every REVERSE-only flag in
that sweep was read manually and traced to a real, current mismatch between instruction.md's own
"Graded deliverable filenames" section and judge.toml's files=[...] list -- not a single one was
an artifact of the extraction regex; SVC-PC-6-0-0, SVC-PC-10-0-0, SVC-PC-59-0-0, and the
SVC-PC-96-* family (a templated batch where roughly half the tasks drop the commanded Memo.docx
from judge.toml and half don't) are named here as real, reproducible examples, not illustrations.

EKW port (2026-09-14): everything above this paragraph describes the original SVC-PC-only script
and is unchanged in behaviour. `load_deliverable_files()` (new, just below `load_judge_files()`)
is the only addition: it detects which config shape a task uses and calls the matching loader --
`load_judge_files()` for SVC-PC's `tests/*/judge.toml`, or `ekw_verifier_json.load_ekw_files()` for
EKW's `tests/verifier.json` -- and returns the identical `(sources, parse_errors)` shape either
way. `analyze_task()` calls `load_deliverable_files()` instead of `load_judge_files()` directly;
nothing else in `analyze_task()`, the FORWARD/REVERSE extraction, or the CLI changed. SVC-PC
detection (any `tests/*/judge.toml`) takes precedence over EKW detection, so an SVC-PC task's
behaviour cannot change even in the unobserved case where both shapes exist in one task dir.

EKW port, REVERSE Tier 1 extension (2026-09-14): a first full run of the ported REVERSE direction
against 274 real EKW tasks fired on zero of them -- confirmed by direct grep that no EKW
instruction.md uses SVC-PC's exact "## Graded deliverable filenames" heading or a bare "Deliver "
imperative, so the SVC-PC-calibrated patterns simply had no signal on this corpus. Reading the
corpus directly (same methodology as the original SVC-PC calibration, not inferred from a
description) found EKW instead overwhelmingly phrases its deliverable list as "Produce the
following deliverables in `/workspace/output/`:" or "...in `/app/`:" (164 of 274 tasks), followed
by a bulleted, backtick-quoted filename per line with trailing descriptive prose after the closing
backtick. `PRODUCE_DELIVERABLES_HEADING_RE` and `_extract_produce_deliverables_bullets()` (just
above the Tier 2 patterns) recognize this as an EKW-specific tier-1-equivalent heading, purely
additive alongside the untouched SVC-PC Tier 1/Tier 2 patterns. It does not attempt the other
deliverable-listing shapes also seen in this corpus (a plain-prose "filename.ext — description"
line with no bullet or backticks, e.g. task_257 and task_202; a single inline sentence naming
multiple files with no bullets at all, e.g. task_201) -- those are silent misses for now, the same
disclosed-not-silently-dropped shape as every other known limit below.
"""

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from ekw_verifier_json import has_ekw_config, load_ekw_files

# Windows console defaults to cp1252, which can't encode every character that shows up in a
# real task's instruction.md or judge.toml (curly quotes, em dashes in vendored text, etc).
# Force UTF-8 with replacement so a printable-but-non-cp1252 character never crashes a batch
# run partway through.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# 2026-09-16 fix: a judge.toml [judge].files entry is not always a real-world filename the
# solver could ever be told about. A recurring shape in this corpus is a JUDGE-SIDE DERIVED
# ARTIFACT the grading pipeline generates from a real source file purely so the judge has a
# pre-processed copy to read -- named by suffixing or extending the real file's own basename,
# which is what appears elsewhere in the same files=[...] list and IS the name instruction.md
# actually discloses. Confirmed real and consistent, not assumed from the shape alone: hand
# checked against real environment/ files and instruction.md text for SVC-PC-1-2-0
# ("orders_export_1.csv" is named in instruction.md; the sibling
# "orders_export_1_judge_extract.csv" -- confirmed to exist alongside it under
# environment/initial_workspace/ -- is not, and was never meant to be), SVC-PC-54-2-0
# ("Sales_Orders.xlsx" named; "Sales_Orders_judge_extract.xlsx" is its judge-side sibling),
# SVC-PC-20-8-0 ("Vendor_Agreement_ADP.pdf" named; "Vendor_Agreement_ADP.extracted.md" is a
# markitdown-style text extraction of it), and SVC-PC-20-3-0 ("orders_export_1.csv" named;
# "orders_export_1_judge_prefix.csv" is its judge-side sibling) -- four independent real
# examples, each confirmed by direct directory listing and instruction.md text search, not
# inferred from naming alone. Before this fix, this shape accounted for 16 of 32 (50%) of this
# check's real fail-tier FORWARD population on a full 202-task run (2026-09-16), 16 flipping to
# a clean pass and 2 more losing a false finding after the fix, verified by a full before/after
# re-run -- see the failure-mode tracker's deliverable_filename fix entry for the complete
# record. A candidate matching this pattern is never simply dropped -- see
# excluded_judge_artifacts below -- so a report reader can still see it was checked and why it
# does not count toward "missing."
JUDGE_ARTIFACT_SUFFIX_RE = re.compile(
    r"(\.extracted\.md$)|(_judge_extract\.[^.]+$)|(_judge_prefix\.[^.]+$)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# task/file discovery
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


def basename(path):
    """Reduce a judge.toml files=[...] entry to its bare filename, whatever separator the
    entry was authored with (a judge.toml can be authored on either OS)."""
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


def load_judge_files(task_dir):
    """Every judge.toml one level under tests/, each carrying its own [judge].files list and
    its group name (the immediate parent directory) for provenance. Mirrors
    formula_health_check.py's load_judge_criteria() shape and parser (tomllib, not regex), but
    reads the [judge] table itself rather than [[criterion]] blocks.

    Returns (sources, parse_errors):
        sources      -- list of {"group": str, "path": str, "files": [str, ...]}
        parse_errors -- list of {"group": str, "path": str, "error": str}
    """
    sources = []
    parse_errors = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return sources, parse_errors

    for jt in sorted(tests_dir.glob("*/judge.toml")):
        rel = str(jt.relative_to(task_dir)).replace("\\", "/")
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
        except Exception as e:
            parse_errors.append({"group": jt.parent.name, "path": rel, "error": str(e)})
            continue
        judge = data.get("judge", {})
        files = judge.get("files", [])
        if not isinstance(files, list):
            parse_errors.append(
                {
                    "group": jt.parent.name,
                    "path": rel,
                    "error": f"[judge].files is not a list (got {type(files).__name__})",
                }
            )
            continue
        sources.append(
            {"group": jt.parent.name, "path": rel, "files": [str(f) for f in files]}
        )
    return sources, parse_errors


def _has_svc_pc_config(task_dir):
    """True if this task has at least one tests/*/judge.toml -- the same unrestricted glob
    load_judge_files() itself uses, so detection can never disagree with what that loader would
    actually find."""
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return False
    return any(tests_dir.glob("*/judge.toml"))


def load_deliverable_files(task_dir):
    """Format-dispatching wrapper around load_judge_files() (SVC-PC) and
    ekw_verifier_json.load_ekw_files() (EKW). Both loaders already return the identical
    (sources, parse_errors) shape -- list of {"group", "path", "files"} / {"group", "path",
    "error"} -- so this function is the entire EKW port for this check: everything downstream
    (the basename reduction, the FORWARD/REVERSE instruction.md comparison) consumes that shape
    without knowing or caring which config file it came from.

    Precedence: SVC-PC's tests/*/judge.toml wins whenever it exists, so this port cannot change
    SVC-PC behaviour for any task that already has one, even in the unobserved case where a task
    dir somehow carries both shapes. A task with neither shape falls through to load_judge_files(),
    which returns empty sources/parse_errors for a missing tests/ dir -- unchanged pre-port
    behaviour, not a new code path."""
    if _has_svc_pc_config(task_dir):
        return load_judge_files(task_dir)
    if has_ekw_config(task_dir):
        return load_ekw_files(task_dir)
    return load_judge_files(task_dir)


# 2026-09-16 fix (round 53, bug 1): a judge.toml [judge].files entry is not always a
# deliverable the solver produces. In corpus-exploration tasks (svc_pc), files= is the
# JUDGE'S read-scope: it legitimately includes pre-existing environment source files
# (under /app/_corpus_subtree/... or /app/-rooted environment inputs) the judge reads as
# reference evidence while grading, not files the solver is told to produce. Before this
# fix, the FORWARD direction flagged every such entry whose basename was absent from
# instruction.md, producing ~50 false positives across 13 tasks (see the round-53 bug
# report for the full evidence). Two detection routes, either suffices:
#   Route 2 (preferred, semantically exact): treat as a deliverable ONLY the files= entries
#     that also appear in the solver's solution/files/ listing. Everything else is judge
#     read-scope. Available whenever solution/files/ exists (9 of 10 sampled tasks).
#   Route 1 (fallback): skip entries under /app/_corpus_subtree/ or whose basename exists
#     under environment/initial_workspace/. Used when solution/files/ is unavailable.
def _load_solution_files(task_dir):
    """Set of basenames in solution/files/, or None if that directory does not exist or
    is empty. None (not an empty set) signals 'route 2 unavailable, use route 1 fallback' --
    an empty solution/files/ would wrongly classify every files= entry as read-scope."""
    sol_dir = task_dir / "solution" / "files"
    if not sol_dir.is_dir():
        return None
    files = {p.name for p in sol_dir.iterdir() if p.is_file()}
    return files or None


def _environment_filenames(task_dir):
    """Set of basenames of every file under environment/initial_workspace/ (recursive,
    so _corpus_subtree/ children are included). Used by route 1 to recognize an
    /app/-rooted environment input like Incident_Log_2021.xlsx that is NOT under
    _corpus_subtree/ but does exist in the environment."""
    ws = task_dir / "environment" / "initial_workspace"
    if not ws.is_dir():
        return set()
    return {p.name for p in ws.rglob("*") if p.is_file()}


def _is_readscope_source(fname, original_paths, solution_files, env_files):
    """True if a judge.toml files= entry is a read-scope source (judge reads it, solver
    does not produce it). Route 2: if solution/files/ is available, a file NOT in it is
    read-scope. Route 1 fallback: a file under /app/_corpus_subtree/ or whose basename
    exists under environment/initial_workspace/ is read-scope."""
    if solution_files is not None:
        return fname not in solution_files
    for p in original_paths:
        if p.replace("\\", "/").lstrip().startswith("/app/_corpus_subtree/"):
            return True
    return fname in env_files


# ---------------------------------------------------------------------------
# reverse-direction extraction: filenames instruction.md COMMANDS the solver to
# produce, whether or not judge.toml ever reads them
# ---------------------------------------------------------------------------

# Extensions actually seen across every judge.toml files=[...] entry in the 600-task calibration
# corpus (xlsx, docx, json, pptx, pdf, md, csv), padded with the other common Office/text variants
# that could plausibly show up in an instruction.md's own prose without ever appearing in this
# particular corpus's judge.toml sample.
DELIVERABLE_EXTENSIONS = (
    "xlsx",
    "xlsm",
    "docx",
    "docm",
    "pptx",
    "pptm",
    "csv",
    "pdf",
    "json",
    "md",
    "txt",
    "zip",
)
_EXT_ALTERNATION = "|".join(DELIVERABLE_EXTENSIONS)

# Tier 2's filename token. Deliberately NO spaces, commas, or ampersands: an earlier version of
# this regex allowed them and either truncated a real space/comma/ampersand-bearing filename at
# the first such character, or (worse, when used after an imperative verb like "Deliver") matched
# an entire run of ordinary prose words as if it were one filename. See the module docstring's
# "Known limits" for both failure modes and how the calibration corpus exposed them.
_TIER2_FILENAME = rf"[A-Za-z0-9][A-Za-z0-9_\-.]{{1,120}}\.(?:{_EXT_ALTERNATION})\b"

GRADED_FILENAMES_HEADING_RE = re.compile(
    r"^#{1,6}\s*graded deliverable filenames\s*$", re.IGNORECASE | re.MULTILINE
)
# Every corpus instruction.md carrying the heading above puts exactly one backtick-quoted
# filename (or path) on its own bulleted line, nothing else sharing the line. Matching that exact
# shape lets Tier 1 take the content verbatim instead of re-parsing it with a filename regex.
_GRADED_FILENAMES_BULLET_RE = re.compile(r"^-\s*`([^`]+)`\s*$", re.MULTILINE)

# EKW port, REVERSE Tier 1 extension (2026-09-14): EKW's instruction.md files carry their own
# tier-1-equivalent heading, "Produce the following deliverables in `<path>`:" -- inline prose,
# not a markdown "#" heading, and confirmed against this corpus's own text on 2026-09-14 to be
# the dominant deliverable-listing shape (164 of 274 real EKW instruction.md files use it).
# Unlike SVC-PC's "## Graded deliverable filenames" heading, which the module docstring notes is
# always the LAST section of the document, this heading commonly sits mid-document with more
# prose after the bulleted list (see task_379 in the calibration corpus: a "---" rule and a
# "Save your deliverables..." line follow it). So Tier 1's "section = everything after the
# heading to EOF" approach is not safe to reuse verbatim here -- it would risk sweeping in an
# unrelated bulleted list appearing later in the same document. This extraction instead bounds
# itself to the contiguous bulleted block immediately following the line (see
# _extract_produce_deliverables_bullets below): it stops at the first line that is neither
# blank, nor a bullet, nor an indented wrapped continuation of one. Each bullet's filename is
# still taken verbatim from inside the backticks, same rationale as Tier 1 (real filenames here
# can contain spaces and punctuation) -- but EKW's own bullets always carry trailing descriptive
# prose after the closing backtick ("- `mx_variance_memo.docx`, the memo covering..." /
# "- `name.docx` — a memo for..."), confirmed independently against this corpus on 2026-09-14, so
# this bullet regex, unlike Tier 1's `\s*$`-anchored one, allows anything after the backtick.
PRODUCE_DELIVERABLES_HEADING_RE = re.compile(
    r"^produce the following deliverables in [^\n:]*:", re.IGNORECASE | re.MULTILINE
)
_PRODUCE_DELIVERABLES_BULLET_RE = re.compile(r"^-\s*`([^`]+)`")


def _extract_produce_deliverables_bullets(section_text):
    """From the text immediately following a 'Produce the following deliverables in <path>:'
    line, pull every backtick-quoted filename out of the contiguous bulleted list that follows,
    stopping at the first line that is not part of that list.

    A line is part of the list if it is blank (a separator between bullets), a bullet itself
    (`- `filename.ext`, trailing prose...`), or an indented line wrapping the previous bullet's
    prose onto a second line (real corpus shape, see task_379's Marbeck Securities Lending Audit
    Workbook.xlsx bullet). The first line that is none of those -- non-blank, not indented, not a
    bullet -- ends the list; this is deliberately conservative so a document where the heading is
    not immediately followed by its list (or has no list at all, e.g. the plain-prose and
    inline-no-bullet shapes also seen in this corpus) yields no bullets rather than a guess.
    """
    filenames = []
    for line in section_text.splitlines():
        if line.strip() == "":
            continue
        m = _PRODUCE_DELIVERABLES_BULLET_RE.match(line)
        if m:
            fname = m.group(1).strip()
            # A handful of EKW instruction.md files wrap the bullet's filename in angle
            # brackets as a placeholder-style convention ("- `<APF_III_Investment_Memo.docx>`
            # -- A structured..."), confirmed on 2026-09-14 against every one of this
            # extraction's own real fails (task_122, 136, 145, 187, 206, 229): the graded
            # filename in every one of those tasks' verifier.json is the bare name with no
            # brackets, so leaving them in manufactured a false "commanded but not graded" on
            # all 6 -- the same false-positive shape Tier 1's own docstring (point 6 above)
            # already warns a too-literal bullet capture can produce. One layer only, matching
            # how basename() strips exactly one path-separator layer elsewhere in this file.
            if fname.startswith("<") and fname.endswith(">"):
                fname = fname[1:-1].strip()
            filenames.append(fname)
            continue
        if line[:1].isspace():
            continue
        break
    return filenames


# Tier 2: curated directive-language patterns, calibrated against the corpus's own non-heading
# instruction.md files (SVC-PC-5-1-0, 13-3-0, 13-6-0, 13-7-0, 16-3-0). Each pattern's single
# capture group is the filename-shaped token immediately implicated by that directive verb/label
# -- not every filename-shaped token in the sentence, so a filename mentioned only as an input or
# as background context (e.g. "the broker quote on file (Quote_2022.xlsx)") does not match any of
# these unless it also happens to sit right after one of these specific command constructions.
TIER2_DIRECTIVE_PATTERNS = [
    ("deliver_imperative", re.compile(rf"\bDeliver\s+({_TIER2_FILENAME})")),
    ("artifact_label", re.compile(rf"^Artifact:\s*({_TIER2_FILENAME})", re.MULTILINE)),
    ("filename_label", re.compile(rf"(?i)\bfilename:\s*({_TIER2_FILENAME})")),
    (
        "save_or_submit_as",
        re.compile(
            rf"(?i)\b(?:save|submit)\b[^.\n]{{0,40}}?\bas\s+(?:exactly\s+)?({_TIER2_FILENAME})"
        ),
    ),
    (
        "name_the_file",
        re.compile(rf"(?i)\bname(?:d)?\s+the\s+file\s+({_TIER2_FILENAME})"),
    ),
    (
        "file_called_or_named",
        re.compile(
            rf"(?i)\b(?:file|deliverable)\s+(?:called|named)\s+({_TIER2_FILENAME})"
        ),
    ),
    ("deliverable_is", re.compile(rf"(?i)\bdeliverable\s+is\s+({_TIER2_FILENAME})")),
]


def extract_commanded_filenames(instr_text):
    """Every filename instruction.md's own directive language commands the solver to produce,
    across both tiers. Returns a list of {"filename": raw text as matched (may be a path),
    "pattern": which tier/pattern matched, "snippet": a short window of surrounding text for
    provenance in the report}. Never raises; a text with no directive language at all yields [].
    """
    commanded = []

    heading_match = GRADED_FILENAMES_HEADING_RE.search(instr_text)
    if heading_match:
        section = instr_text[heading_match.end() :]
        for bullet_match in _GRADED_FILENAMES_BULLET_RE.finditer(section):
            fname = bullet_match.group(1).strip()
            commanded.append(
                {
                    "filename": fname,
                    "pattern": "graded_filenames_heading",
                    "snippet": f"- `{fname}`",
                }
            )

    for heading_match in PRODUCE_DELIVERABLES_HEADING_RE.finditer(instr_text):
        section = instr_text[heading_match.end() :]
        for fname in _extract_produce_deliverables_bullets(section):
            commanded.append(
                {
                    "filename": fname,
                    "pattern": "produce_deliverables_heading",
                    "snippet": f"- `{fname}`",
                }
            )

    for pattern_name, pat in TIER2_DIRECTIVE_PATTERNS:
        for m in pat.finditer(instr_text):
            fname = m.group(1).strip()
            start = max(0, m.start() - 20)
            end = min(len(instr_text), m.end() + 20)
            snippet = instr_text[start:end].replace("\n", " ").strip()
            commanded.append(
                {"filename": fname, "pattern": pattern_name, "snippet": snippet}
            )

    return commanded


def combine_statuses(forward_status, reverse_status):
    """fail beats everything (either direction finding a real contradiction makes the task
    unready); pass requires BOTH directions to have actually checked something and agreed;
    skip otherwise -- mirrors the single-direction rule that skip is never itself a claim that
    a task is fine."""
    if forward_status == "fail" or reverse_status == "fail":
        return "fail"
    if forward_status == "pass" and reverse_status == "pass":
        return "pass"
    return "skip"


def _set_direction_fields(
    result,
    reverse_status,
    commanded_filenames=None,
    commanded_but_not_graded=None,
    commanded_and_graded=None,
):
    """Fills in the REVERSE-direction and combined-status fields on a result dict that already
    has its (FORWARD) `status` set. Called at every return point in analyze_task so the JSON
    shape is identical whether a task exits early (skip) or runs the full comparison."""
    result["commanded_filenames"] = commanded_filenames or []
    result["commanded_but_not_graded"] = commanded_but_not_graded or []
    result["commanded_and_graded"] = commanded_and_graded or []
    result["reverse_status"] = reverse_status
    result["forward_status"] = result["status"]
    result["combined_status"] = combine_statuses(result["status"], reverse_status)


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir):
    """Returns a result dict for one task. Never raises -- a missing instruction.md or an
    unparseable judge.toml is reported as a skip/parse_error, not a crash.

    `status` (unchanged field, unchanged semantics) is the FORWARD-direction result and is also
    mirrored explicitly as `forward_status`. `reverse_status` is the new commanded-but-not-graded
    check, and `combined_status` rolls both up (see combine_statuses())."""
    task_id = task_dir.name
    result = {
        "task_id": task_id,
        "instruction_md_exists": False,
        "judge_toml_sources": [],
        "parse_errors": [],
        "expected_filenames": [],
        "found": [],
        "missing": [],
        "errors": [],
    }

    instr_path = task_dir / "instruction.md"
    if not instr_path.is_file():
        result["status"] = "skip"
        result["errors"].append(
            "no instruction.md found for this task -- nothing to check"
        )
        _set_direction_fields(result, "skip")
        return result
    result["instruction_md_exists"] = True

    try:
        instr_text = instr_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        result["status"] = "skip"
        result["errors"].append(f"could not read instruction.md: {e}")
        _set_direction_fields(result, "skip")
        return result

    sources, parse_errors = load_deliverable_files(task_dir)
    result["judge_toml_sources"] = sources
    result["parse_errors"] = parse_errors
    for pe in parse_errors:
        result["errors"].append(
            f"{pe['path']}: judge.toml failed to parse -- {pe['error']}"
        )

    if not sources:
        result["status"] = "skip"
        if not parse_errors:
            result["errors"].append(
                "no tests/*/judge.toml found (or none had a [judge].files list) -- nothing "
                "for this check to verify"
            )
        # REVERSE mirrors FORWARD's skip here: with no judge.toml files=[...] at all, every
        # commanded filename would trivially be "not graded," which adds no information beyond
        # what the FORWARD skip already says (see module docstring point 9).
        _set_direction_fields(result, "skip")
        return result

    # basename -> which judge.toml group(s) named it, for provenance in the report.
    # Also track the original paths per basename so the read-scope exemption (route 1)
    # can check for /app/_corpus_subtree/ prefixes.
    expected_by_group = {}
    expected_paths: dict[str, set[str]] = {}
    for src in sources:
        for f in src["files"]:
            bn = basename(f)
            expected_by_group.setdefault(bn, []).append(src["group"])
            expected_paths.setdefault(bn, set()).add(str(f))

    if not expected_by_group:
        result["status"] = "skip"
        result["errors"].append(
            "every judge.toml found had an empty [judge].files list -- nothing to verify"
        )
        _set_direction_fields(result, "skip")
        return result

    result["expected_filenames"] = sorted(expected_by_group)

    solution_files = _load_solution_files(task_dir)
    env_files = _environment_filenames(task_dir)

    found, missing, excluded_judge_artifacts = [], [], []
    for fname, groups in sorted(expected_by_group.items()):
        entry = {"filename": fname, "named_by": sorted(set(groups))}
        if fname in instr_text:
            found.append(entry)
        elif JUDGE_ARTIFACT_SUFFIX_RE.search(fname):
            entry["note"] = (
                "not found in instruction.md, but the basename matches a judge-side derived "
                "artifact suffix (.extracted.md / _judge_extract.* / _judge_prefix.*) -- see "
                "JUDGE_ARTIFACT_SUFFIX_RE's own comment for the real, hand-confirmed precedent. "
                "Not counted as missing: this is a grading-pipeline-generated copy of a real "
                "source file, not a name the solver is ever expected to see or produce."
            )
            excluded_judge_artifacts.append(entry)
        elif _is_readscope_source(
            fname, expected_paths.get(fname, set()), solution_files, env_files
        ):
            entry["note"] = (
                "not found in instruction.md, but classified as a read-scope source file "
                "(judge read-scope, not a solver deliverable). "
                + (
                    "Absent from solution/files/ -- the solver's own produce set does not "
                    "include this file (route 2)."
                    if solution_files is not None
                    else "Path is under /app/_corpus_subtree/ or the file exists under "
                    "environment/initial_workspace/ (route 1 fallback)."
                )
            )
            excluded_judge_artifacts.append(entry)
        else:
            missing.append(entry)
    result["found"] = found
    result["missing"] = missing
    result["excluded_judge_artifacts"] = excluded_judge_artifacts
    result["status"] = "fail" if missing else "pass"

    # REVERSE direction: filenames instruction.md commands that no judge.toml under this task
    # reads at all. Only evaluated here because expected_by_group is non-empty (see the skip
    # branches above) -- there is something real to check the commanded set against.
    commanded = extract_commanded_filenames(instr_text)
    commanded_by_basename = {}
    for c in commanded:
        commanded_by_basename.setdefault(basename(c["filename"]), []).append(c)

    if not commanded_by_basename:
        # Nothing in instruction.md matched either extraction tier -- e.g. the prompt never
        # names its own output file anywhere (a real, common shape in this corpus, and a
        # FORWARD-direction problem, not a REVERSE one: see docstring point 9).
        _set_direction_fields(result, "skip")
        return result

    commanded_and_graded, commanded_but_not_graded = [], []
    for bn, entries in sorted(commanded_by_basename.items()):
        record = {
            "filename": bn,
            "raw": sorted({e["filename"] for e in entries}),
            "matched_by": sorted({e["pattern"] for e in entries}),
            "snippets": [e["snippet"] for e in entries],
        }
        if bn in expected_by_group:
            commanded_and_graded.append(record)
        else:
            commanded_but_not_graded.append(record)

    reverse_status = "fail" if commanded_but_not_graded else "pass"
    _set_direction_fields(
        result,
        reverse_status,
        commanded_filenames=sorted(commanded_by_basename),
        commanded_but_not_graded=commanded_but_not_graded,
        commanded_and_graded=commanded_and_graded,
    )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Check both directions between a task's judge.toml and its instruction.md: "
        "FORWARD -- is every filename judge.toml's [judge].files list expects literally named "
        "somewhere in instruction.md; REVERSE -- does instruction.md command a filename (via "
        "directive language or a 'Graded deliverable filenames' section) that judge.toml never "
        "reads at all."
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
        "this is a generalized copy that must not silently assume a project-specific path)",
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
                "judge_toml_sources": [],
                "parse_errors": [],
                "expected_filenames": [],
                "found": [],
                "missing": [],
            }
            # analyze_task crashed before it could evaluate REVERSE at all -- "skip" here means
            # "unknown," not "nothing to check"; combine_statuses still reports "fail" overall
            # because FORWARD's "fail" always wins regardless of REVERSE.
            _set_direction_fields(r, "skip")
        results.append(r)
        print(
            f"    -> {r['status']}  "
            f"({len(r.get('missing', []))} missing / {len(r.get('expected_filenames', []))} "
            f"expected, {len(r.get('errors', []))} errors)  "
            f"| reverse: {r['reverse_status']} "
            f"({len(r.get('commanded_but_not_graded', []))} commanded-not-graded)",
            file=sys.stderr,
        )

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    n_rev_pass = sum(1 for r in results if r["reverse_status"] == "pass")
    n_rev_fail = sum(1 for r in results if r["reverse_status"] == "fail")
    n_rev_skip = sum(1 for r in results if r["reverse_status"] == "skip")
    n_comb_pass = sum(1 for r in results if r["combined_status"] == "pass")
    n_comb_fail = sum(1 for r in results if r["combined_status"] == "fail")
    n_comb_skip = sum(1 for r in results if r["combined_status"] == "skip")
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        # FORWARD direction -- unchanged field names/semantics from the original script.
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_skip": n_skip,
        # REVERSE direction -- new.
        "n_reverse_pass": n_rev_pass,
        "n_reverse_fail": n_rev_fail,
        "n_reverse_skip": n_rev_skip,
        # combined (fail if either direction fails; pass only if both pass) -- new.
        "n_combined_pass": n_comb_pass,
        "n_combined_fail": n_comb_fail,
        "n_combined_skip": n_comb_skip,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail / {n_skip} skip out of {len(results)} task(s)"
    )
    # New: REVERSE and COMBINED get their own summary lines, appended after the original
    # unchanged FORWARD line above rather than folded into it.
    print(
        f"reverse-direction (commanded filename not graded): "
        f"{n_rev_pass} pass / {n_rev_fail} fail / {n_rev_skip} skip"
    )
    print(
        f"combined (fail if either direction fails, pass only if both pass): "
        f"{n_comb_pass} pass / {n_comb_fail} fail / {n_comb_skip} skip"
    )
    for r in results:
        note = ""
        if r["status"] == "fail":
            missing_names = ", ".join(m["filename"] for m in r.get("missing", []))
            note = f"  [missing: {missing_names}]"
        if r["reverse_status"] == "fail":
            not_graded_names = ", ".join(
                c["filename"] for c in r.get("commanded_but_not_graded", [])
            )
            note += f"  [commanded but not graded: {not_graded_names}]"
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
