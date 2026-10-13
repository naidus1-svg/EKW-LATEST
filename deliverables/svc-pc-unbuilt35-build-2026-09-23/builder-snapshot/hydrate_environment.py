#!/usr/bin/env python3
"""hydrate_environment.py -- resolve and stage the real source/input files a
SVC-PC task's agent needs, so `environment/data/` (-> environment/
initial_workspace/ in the reward-kit build) isn't empty.

Confirmed by inspection: none of the 54 harbor tasks built so far have any
real input data -- `environment/initial_workspace/` is created but always
empty, which is why launching Oracle in DataOS crashed with
`DaytonaError: Path does not exist: .../initial_workspace/` (an empty
directory doesn't survive zip upload). The deeper defect: every task's
prompt expects the agent to read real named files, from one of two places:

  - Tasks with `L1-XX-NN/` subfolders (upstream leaf-task outputs, already
    downloaded locally) -- those ARE the input data.
  - Tasks that name specific files narratively or as an explicit list (e.g.
    "Required input files: Journal.csv; TrialBalance.csv; ...", or "Elena's
    Wholesale_Prospect_List.xlsx") -- those live in the shared "digital
    twin" corpus the user downloaded, not anywhere in the task's own Drive
    tree (confirmed by tracing the Drive parent chain up from a task with no
    local match -- there is no per-task or per-group source folder).

Both sources can apply to the same task (e.g. SVC-PC-3-6-0 and the
SVC-PC-4-* group have L1-* subfolders AND name specific corpus files).

A third source (Claire's Central Task Platform template): the Grading Rubric
workbook's own Read Me tab can declare an explicit INPUT MANIFEST table
(exact corpus-relative path, Included? Yes/No) -- see
rubric_xlsx_to_verifier.parse_read_me. Every row with Included=Yes and a
real (non-placeholder) path is resolved against the corpus the same way a
prompt-text-scanned filename is, and reported the same way -- this ADDS a
third source, it never replaces the L1-folder or prompt-text-scan paths
above.

Usage:
    python3 hydrate_environment.py <task_dir> [--corpus <corpus_root>] [--out <scratch_source_dir>]

Prints what it resolved, and exits non-zero listing any unresolved names
rather than silently proceeding with a partially-empty environment --
matches this project's established "don't guess, flag for review" posture
(see rubric_xlsx_to_verifier.py's rubric/deliverable file selection).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import openpyxl

import rubric_xlsx_to_verifier as rxv

DEFAULT_CORPUS = Path(
    "/Users/luiz.araujo/Downloads/Cirrus Sleep Full Y1 (FINAL VERSION)"
)

LEAF_SUBTASK_RE = re.compile(r"^L1-\d+-\d+", re.IGNORECASE)
FILENAME_RE = re.compile(
    r"[A-Za-z0-9][\w\-.,()&]*\.(?:csv|xlsx|docx|pdf|pptx|json|md|ofx|txt)",
    re.IGNORECASE,
)
# Two confirmed compressed-range patterns that read as ONE token to a human
# but stand for several distinct files -- they must be detected and expanded
# on the RAW prompt text before the general FILENAME_RE runs, because "/"
# and "–"/space aren't in FILENAME_RE's character class and would otherwise
# fragment them into garbage partial matches (observed: "12.pdf" as a
# spurious extra "file" from "Bank_Statement_2021-10/11/12.pdf").
#
# Suffix range: "Bank_Statement_2021-10/11/12.pdf" -> three monthly files.
DATE_SUFFIX_RANGE_RE = re.compile(
    r"\b(?P<prefix>[\w]+_\d{4}-\d{2})/(?P<mid>\d{2})/(?P<last>\d{2})(?P<ext>\.\w+)\b"
)
# Prefix range: "Q2–Q4 Pipeline_Tracker.xlsx" or "Q1-Q4_Channel_Attribution.xlsx"
# -> Q2_/Q3_/Q4_Pipeline_Tracker.xlsx (real corpus files always use "_" as the
# join, regardless of whether the prompt used a space or an underscore here).
QUARTER_PREFIX_RANGE_RE = re.compile(
    r"\bQ(?P<start>\d)[–—-]Q(?P<end>\d)[\s_]+(?P<name>[A-Za-z][\w]*\.\w+)\b"
)
# A "Source:" line whose named file is exactly this task's own graded
# deliverable, paired with an unfilled "[the ...]" mail-merge placeholder
# elsewhere in the prompt, is the SVC-PC-36 family's signature authoring
# defect: the template substitution that should have named a real upstream
# file never ran, so the Source: field collapsed onto the task's own output
# instead. is_self_reference() correctly discards that token as a
# self-reference (it IS this task's deliverable) -- but here that discard
# is silently wrong, because the intended real source was lost, not absent.
# Detected, not fixed: the real upstream file this should have named isn't
# recoverable from the text (see detect_template_source_collision's
# docstring), so this only earns the task a distinctly-labeled report entry
# instead of a misleading "reasoning-only"/generic "hydration gap" message.
SOURCE_LINE_RE = re.compile(r"(?im)^\s*Source:\s*(?P<name>[\w][\w\-.,()&]*\.\w+)\s*$")
UNFILLED_TEMPLATE_PLACEHOLDER_RE = re.compile(
    r"\[\s*the\s+[a-z][a-z /\-]*\]", re.IGNORECASE
)
# Matches the separator tolerantly rather than pinning the literal em-dash
# byte: a naive zip re-extraction of this corpus on Windows (Python's
# zipfile defaults to CP437 for filenames whose UTF-8 flag isn't set) turns
# every "My Drive — name" folder into "My Drive ΓÇ name" --
# confirmed live against a corpus copy fetched 2026-09-12, and it reproduces
# the exact "0 personas" symptom this regex used to produce against that
# copy. The two-letter mojibake sequence is itself made of Unicode word
# characters, so a plain `\W+`/`\s+` gap does not skip over it -- `.*?`
# (non-greedy, matches anything) does, and still anchors on the one thing
# that never changes regardless of separator corruption: the slug itself is
# ASCII and passes through any single-byte codec unchanged.
PERSONA_DIR_RE = re.compile(r"^My Drive\b.*?(?P<slug>[a-z]+\.[a-z]+)\s*$")
PROXIMITY_WINDOW = 80  # chars of text immediately before a filename mention to scan for a person's name


class HydrationError(Exception):
    pass


class CorpusIndexError(HydrationError):
    """The corpus root cannot possibly be right -- refuse to hydrate anything
    against it rather than let every task in the batch silently resolve to
    an all-not-found placeholder (see index_corpus's docstring)."""


def build_corpus_index(corpus_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for p in corpus_root.rglob("*"):
        if p.is_file():
            index.setdefault(p.name.lower(), []).append(p)
    return index


def index_corpus(
    corpus_root: Path,
) -> "tuple[dict[str, list[Path]], set[str], list[str]]":
    """Build the file index and persona-slug set together, with the
    completeness sanity checks that catch a broken or partially-extracted
    corpus before it silently produces a batch of empty hydrations.

    History: across 46 separate hydration-build runs spanning three days,
    5 batches (57 tasks) shipped "0 resolved, N not-found" against real
    filename candidates the SAME deterministic matcher code resolves on the
    first try when run today against this same corpus -- the signature of a
    corpus that was missing, partial, or wrong-rooted at build time, not a
    matcher defect. This function is the single place both
    hydrate_environment.main() and svc_pc_batch_convert.py build their
    index and persona set, so the two callers can no longer drift into
    validating the corpus two different (or zero) ways.

    Returns (file_index, persona_slugs, warnings). Raises CorpusIndexError
    for a corpus_root that cannot possibly be right: missing entirely, no
    files found anywhere under it, or 'My Drive ...'-shaped folders exist
    but zero of them resolve to a persona slug (the live-reproduced
    zip-encoding corruption signature -- see PERSONA_DIR_RE)."""
    if not corpus_root.is_dir():
        raise CorpusIndexError(
            f"corpus root does not exist or is not a directory: {corpus_root}"
        )

    top_level = list(corpus_root.iterdir())
    if not top_level:
        raise CorpusIndexError(f"corpus root is completely empty: {corpus_root}")

    index = build_corpus_index(corpus_root)
    total_files = sum(len(v) for v in index.values())
    if total_files == 0:
        top_dirs = [d for d in top_level if d.is_dir()]
        raise CorpusIndexError(
            f"corpus root {corpus_root} has {len(top_dirs)} subdirectory(ies) "
            "but the index found zero files anywhere under them -- this is "
            "the signature of an unpulled, partial, or mispointed corpus, "
            "not a genuinely empty one. Refusing to proceed rather than "
            "silently producing an all-not-found hydration run."
        )

    top_dirs = [d for d in top_level if d.is_dir()]
    persona_slugs = {
        m.group("slug") for d in top_dirs if (m := PERSONA_DIR_RE.match(d.name))
    }
    my_drive_like = [d.name for d in top_dirs if "my drive" in d.name.lower()]
    unmatched_my_drive = [n for n in my_drive_like if not PERSONA_DIR_RE.match(n)]

    warnings: list[str] = []
    if unmatched_my_drive:
        warnings.append(
            "corpus has 'My Drive ...'-shaped folder(s) PERSONA_DIR_RE still "
            f"could not parse a persona slug from: {unmatched_my_drive!r} -- "
            "check for an encoding problem in this corpus copy."
        )
    if my_drive_like and not persona_slugs:
        raise CorpusIndexError(
            f"found {len(my_drive_like)} 'My Drive ...'-shaped folder(s) "
            f"({my_drive_like!r}) but resolved zero persona slugs from any "
            "of them -- refusing to proceed with ambiguous-file "
            "disambiguation effectively disabled corpus-wide. This is the "
            "'0 personas' corruption signature (see PERSONA_DIR_RE)."
        )
    return index, persona_slugs, warnings


def _normalize_filename_for_comparison(name: str) -> str:
    """Collapse spelling variance that is not a semantic difference --
    separators and case -- while keeping the extension significant, so a
    prompt's own prose and its rubric/judge.toml deliverable footer compare
    equal despite drifting on underscores (see is_self_reference's
    docstring for the confirmed SVC-PC-50-6-0 case)."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    collapsed_stem = re.sub(r"[^a-z0-9]", "", stem.lower())
    return f"{collapsed_stem}.{ext.lower()}"


def detect_template_source_collision(
    prompt_text: str, deliverable_names: set[str]
) -> "list[dict]":
    """[{"source_filename":..., "placeholder": ...}, ...] when the prompt's
    own "Source: <file>" line names exactly this task's own graded
    deliverable AND the prompt also carries an unfilled "[the ...]"
    mail-merge placeholder -- the SVC-PC-36 family's signature (5/5 sampled:
    36-1 through 36-5). Both conditions together are the signal: a filled-in
    template can legitimately self-reference its own deliverable in a
    Source: line for unrelated reasons, and an unfilled placeholder alone
    says nothing about the Source: field. Together they mean the template
    substitution that should have named a real upstream file never ran, and
    that real file is not recoverable from this text -- there is no local
    L1-*/ staged copy either (the cross-task dependency was never fetched),
    so this function's job is honest detection and labeling, not
    resolution: it lets hydrate() report a distinct, correctly-diagnosed
    "template authoring defect" instead of silently falling through to a
    "reasoning-only" message that would send a human looking in the wrong
    place entirely."""
    placeholder_match = UNFILLED_TEMPLATE_PLACEHOLDER_RE.search(prompt_text)
    if not placeholder_match:
        return []
    hits = []
    for m in SOURCE_LINE_RE.finditer(prompt_text):
        name = m.group("name")
        if any(d.lower().endswith(name.lower()) for d in deliverable_names) or any(
            _normalize_filename_for_comparison(Path(d).name)
            == _normalize_filename_for_comparison(name)
            for d in deliverable_names
        ):
            hits.append(
                {"source_filename": name, "placeholder": placeholder_match.group(0)}
            )
    return hits


def _persona_near(text: str, pos: int, persona_slugs: set[str]) -> set[str]:
    """Persona slug(s) whose first/last name appear in the PROXIMITY_WINDOW
    chars immediately before `pos` -- used so "Brian's X.xlsx ... Elena's
    Y.xlsx" in the same prompt correctly ties each file to the right person,
    rather than "any person mentioned anywhere in this prompt" (which fails
    when a task assigns different files to different named people)."""
    window = text[max(0, pos - PROXIMITY_WINDOW) : pos]
    hits = set()
    for slug in persona_slugs:
        first, _, last = slug.partition(".")
        if re.search(rf"\b{re.escape(first)}\b", window, re.IGNORECASE) or (
            last and re.search(rf"\b{re.escape(last)}\b", window, re.IGNORECASE)
        ):
            hits.add(slug)
    return hits


def extract_candidate_filenames(
    prompt_text: str, deliverable_names: set[str], persona_slugs: set[str]
) -> list[tuple[str, set[str]]]:
    """Returns [(candidate_filename, personas_associated_with_this_specific_mention), ...].
    Handles two confirmed compressed-range notations (see the regexes above)
    by expanding them BEFORE the general filename regex runs, since both use
    separators ("/" and en-dash/space) that aren't valid inside a single
    FILENAME_RE token and would otherwise fragment into garbage matches."""
    candidates: dict[str, set[str]] = {}
    consumed_spans: list[tuple[int, int]] = []

    for m in DATE_SUFFIX_RANGE_RE.finditer(prompt_text):
        prefix, mid, last, ext = (
            m.group("prefix"),
            m.group("mid"),
            m.group("last"),
            m.group("ext"),
        )
        base, first_month = prefix.rsplit("-", 1)
        personas = _persona_near(prompt_text, m.start(), persona_slugs)
        for mm in (first_month, mid, last):
            candidates.setdefault(f"{base}-{mm}{ext}", set()).update(personas)
        consumed_spans.append(m.span())

    for m in QUARTER_PREFIX_RANGE_RE.finditer(prompt_text):
        start_q, end_q, name = (
            int(m.group("start")),
            int(m.group("end")),
            m.group("name"),
        )
        personas = _persona_near(prompt_text, m.start(), persona_slugs)
        for q in range(start_q, end_q + 1):
            candidates.setdefault(f"Q{q}_{name}", set()).update(personas)
        consumed_spans.append(m.span())

    residual = list(prompt_text)
    for start, end in consumed_spans:
        for i in range(start, end):
            residual[i] = " "
    residual_text = "".join(residual)

    def is_self_reference(name: str) -> bool:
        if any(d.lower().endswith(name.lower()) for d in deliverable_names):
            return True
        # Exact-suffix match alone misses deliverable-name spelling drift
        # between a prompt's own prose and its rubric/judge.toml footer --
        # confirmed for SVC-PC-50-6-0 (prompt body "Cross_Sell_Bundle_
        # Architecture.xlsx" vs the real deliverable
        # "CrossSell_Bundle_Architecture.xlsx", an extra underscore) and 11
        # siblings in the 45/50/51 families. That drift is an authoring
        # inconsistency, not a missing input -- the drifted spelling isn't a
        # real corpus file either, so without this it becomes a guaranteed
        # "not-found" input candidate that mis-labels the task a hydration
        # gap. Comparing with separators and case collapsed (extension kept
        # significant) catches this without weakening the match: a
        # genuinely different filename that merely happens to collapse to
        # the same letters would be a very unusual coincidence, and this
        # only ever discards a candidate that also fails real corpus
        # lookup on its literal spelling, so it can't mask a real input.
        normalized_name = _normalize_filename_for_comparison(name)
        return any(
            _normalize_filename_for_comparison(Path(d).name) == normalized_name
            for d in deliverable_names
        )

    for m in FILENAME_RE.finditer(residual_text):
        name = m.group(0)
        if is_self_reference(name):
            continue
        personas = _persona_near(residual_text, m.start(), persona_slugs)
        candidates.setdefault(name, set()).update(personas)

    return sorted(candidates.items())


def persons_anywhere_in(text: str, persona_slugs: set[str]) -> set[str]:
    """Weak fallback tier: any persona mentioned anywhere in the whole
    prompt (not proximity-scoped) -- only used by resolve_filename() if
    proximity matching didn't already narrow to one file."""
    hits = set()
    for slug in persona_slugs:
        first, _, last = slug.partition(".")
        if re.search(rf"\b{re.escape(first)}\b", text, re.IGNORECASE) or (
            last and re.search(rf"\b{re.escape(last)}\b", text, re.IGNORECASE)
        ):
            hits.add(slug)
    return hits


def _path_has_persona(path_parts: "tuple[str, ...]", slug: str) -> bool:
    """True if one of this path's components is THIS persona's 'My Drive
    ...' folder -- matched through PERSONA_DIR_RE rather than the literal
    'My Drive — {slug}' string, so disambiguation-by-persona still works
    even when the corpus copy on disk has a mangled separator (see
    PERSONA_DIR_RE's docstring): resolving persona_slugs tolerantly upstream
    and then re-hardcoding the literal separator here would silently
    reintroduce the same corruption sensitivity one call later."""
    return any(
        (m := PERSONA_DIR_RE.match(part)) and m.group("slug") == slug
        for part in path_parts
    )


def resolve_filename(
    name: str,
    index: dict[str, list[Path]],
    local_personas: set[str],
    prompt_wide_personas: set[str],
) -> tuple[str, list[Path]]:
    """Returns (status, paths). status in {"resolved", "not-found", "ambiguous"}.
    Prefers the persona(s) found close to THIS mention; falls back to any
    persona mentioned anywhere in the prompt only if that alone narrows to
    exactly one match."""
    matches = index.get(name.lower(), [])
    if not matches:
        return "not-found", []
    if len(matches) == 1:
        return "resolved", matches
    for personas in (local_personas, prompt_wide_personas):
        if not personas:
            continue
        narrowed = [
            p
            for p in matches
            if any(_path_has_persona(p.parts, slug) for slug in personas)
        ]
        if len(narrowed) == 1:
            return "resolved", narrowed
    return "ambiguous", matches


def l1_source_files(task_dir: Path) -> list[tuple[Path, str]]:
    """(absolute_path, relative_dest_under_source/) pairs for every real file
    under this task's L1-XX-NN subfolders, skipping model-output folders."""
    out = []
    for child in task_dir.iterdir():
        if not (child.is_dir() and LEAF_SUBTASK_RE.match(child.name)):
            continue
        for p in child.rglob("*"):
            if p.is_file() and not any(
                rxv.MODEL_SKIP_RE.search(part)
                for part in p.relative_to(task_dir).parts[:-1]
            ):
                out.append((p, str(p.relative_to(task_dir))))
    return out


def declared_manifest_paths(task_dir: Path) -> list[str]:
    """Real (non-placeholder, Included=Yes) file paths from the rubric
    workbook's own Read Me input manifest, if it has one -- see
    rubric_xlsx_to_verifier.parse_read_me. Returns [] (not an error) when the
    rubric has no Read Me tab, or the manifest has no filled-in rows: this
    only ADDS a third hydration source, on top of the L1-folder and
    prompt-text-scan sources below, so an absent or all-placeholder manifest
    must fall through to those unchanged rather than short-circuit them."""
    try:
        rubric_path = rxv.find_rubric_file(task_dir)
        wb = openpyxl.load_workbook(rubric_path, data_only=True)
    except (rxv.ConversionError, OSError, ValueError, KeyError):
        return []
    read_me = rxv.parse_read_me(wb)
    if read_me is None:
        return []
    return [
        entry["path"]
        for entry in read_me["input_manifest"]
        if entry["included"] and not entry["is_placeholder"] and entry.get("path")
    ]


# ---------------------------------------------------------------------------
# Role/description-based hydration fallback (Cause 1): a prompt that names
# its required inputs by ROLE or DESCRIPTION ("the ledger", "board
# resolutions", "the merchant agreement", "capitalization records") rather
# than a literal filename produces zero FILENAME_RE candidates, and used to
# fall straight through to the placeholder message -- a false negative, not
# a legitimate no-input-needed task (confirmed for the SVC-PC-38 and
# SVC-PC-52 families: every one of their descriptively-named documents
# exists in the corpus under a discoverable name).
#
# This is NOT solvable by better filename extraction -- several tasks in
# this same failure class explicitly instruct "I'm not telling you which
# records matter, work the drive" -- so the fix is not a smarter filename
# regex, it is a DIFFERENT kind of source: score every corpus
# department/persona folder ("bucket") by how much of its own filename
# vocabulary the prompt's language overlaps, weighted so a word shared by
# many buckets counts for less than one that is nearly unique to a single
# bucket, and stage the bucket(s) that clear a real-signal bar. This trades
# file-level precision for recall: it cannot always narrow to the exact one
# or two files a human curator would pick (that genuinely needs semantic
# document understanding this module has no path to), but it reliably
# replaces a completely empty environment with the real, correctly-scoped
# subset of the corpus the task is actually about, which is what "work the
# drive" tasks want handed to the agent in the first place. Only engaged
# when every other source (L1, manifest, literal-filename prompt scan) has
# already come up empty -- see hydrate()'s call site.
ROLE_MATCH_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "for",
    "to",
    "in",
    "on",
    "at",
    "by",
    "with",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "as",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "from",
    "into",
    "onto",
    "over",
    "under",
    "than",
    "then",
    "so",
    "not",
    "no",
    "do",
    "does",
    "did",
    "done",
    "have",
    "has",
    "had",
    "you",
    "your",
    "yours",
    "we",
    "our",
    "ours",
    "i",
    "me",
    "my",
    "they",
    "them",
    "their",
    "he",
    "she",
    "his",
    "her",
    "who",
    "what",
    "which",
    "when",
    "where",
    "how",
    "why",
    "all",
    "any",
    "each",
    "every",
    "some",
    "other",
    "own",
    "same",
    "can",
    "will",
    "would",
    "should",
    "could",
    "may",
    "might",
    "must",
    "one",
    "two",
    "three",
    "also",
    "just",
    "only",
    "more",
    "most",
    "much",
    "many",
    "very",
    "about",
    "because",
    "if",
    "but",
    "while",
    "after",
    "before",
    "up",
    "out",
    "off",
    "re",
    "copy",
    "file",
    "files",
    "report",
    "reports",
    "record",
    "records",
    "document",
    "documents",
    "data",
    "summary",
    "final",
    "draft",
    "version",
    "new",
    "old",
    "template",
    "please",
    "dont",
    "say",
    "says",
    "said",
    "tell",
    "show",
    "give",
    "need",
    "want",
    "us",
    "them",
    "policy",
    "policies",
    "plan",
    "planning",
    "review",
    "annual",
    "end",
    "close",
    "package",
    "chart",
    "detail",
    "manual",
    "memo",
    "model",
    "term",
    "terms",
    "source",
    "risk",
    "test",
    "rate",
    "cost",
    "actual",
    "approved",
    "forecast",
    "point",
    "list",
    "top",
    "chain",
    "payment",
    "work",
    "company",
    "working",
    "based",
    "using",
    "used",
    "across",
    "per",
    "each",
    "total",
    "overall",
    "current",
    "sample",
    "state",
    "level",
    "process",
    "processes",
    "reference",
    "year",
}
# "work the drive"-flavored phrasing: not a gate on whether the fallback
# runs (SVC-PC-52-1-0 needs it too and never says this), just a diagnostic
# flag on the report so a human reviewing a bucket-fallback task can see at
# a glance whether the prompt itself signaled this was an intentional
# whole-corpus search rather than an authoring gap.
EXPLICIT_CORPUS_SEARCH_RE = re.compile(
    r"work the drive|not telling you which|decide what'?s? authoritative|"
    r"figure out (?:which|what)",
    re.IGNORECASE,
)
BUCKET_TOP_SCORE_GATE = (
    2.0  # refuse to stage anything unless the single best bucket clears this
)
BUCKET_INCLUDE_FLOOR = 1.2  # any bucket clearing this joins the top one
BUCKET_MAX_COUNT = 8
BUCKET_MAX_TOTAL_FILES = 500


def _stem_words(stem: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)
    return [t.lower() for t in re.findall(r"[A-Za-z]+|\d+", spaced)]


def _significant_words(words: "list[str]") -> "set[str]":
    return {
        w
        for w in words
        if w not in ROLE_MATCH_STOPWORDS and len(w) > 2 and not w.isdigit()
    }


def _bucket_label_for(rel_parts: "tuple[str, ...]") -> str:
    """A persona 'My Drive ...' top-level folder is its own bucket (already
    a small, coherent unit). Any other top-level entry's own second-level
    subfolder becomes one bucket instead (e.g. 'Company Shared
    Drive/Accounting'), so a bucket is department-sized -- tens of files,
    never the whole shared drive at once."""
    top = rel_parts[0]
    if PERSONA_DIR_RE.match(top):
        return top
    if len(rel_parts) >= 3:
        return f"{top}/{rel_parts[1]}"
    return top


def build_folder_buckets(
    corpus_index: "dict[str, list[Path]]", corpus_root: Path
) -> "dict[str, list[Path]]":
    """bucket label -> file Paths, reusing the file list build_corpus_index
    already walked (no second filesystem pass)."""
    buckets: "dict[str, list[Path]]" = {}
    for paths in corpus_index.values():
        for p in paths:
            try:
                rel_parts = p.relative_to(corpus_root).parts
            except ValueError:
                continue
            if not rel_parts:
                continue
            buckets.setdefault(_bucket_label_for(rel_parts), []).append(p)
    return buckets


def _bucket_vocabulary(
    buckets: "dict[str, list[Path]]",
) -> "dict[str, set[str]]":
    vocab = {}
    for label, paths in buckets.items():
        words: "list[str]" = []
        for p in paths:
            words.extend(_stem_words(p.stem))
        vocab[label] = _significant_words(words)
    return vocab


def _word_bucket_document_frequency(
    vocab: "dict[str, set[str]]",
) -> "dict[str, int]":
    df: "dict[str, int]" = {}
    for words in vocab.values():
        for w in words:
            df[w] = df.get(w, 0) + 1
    return df


def score_folder_buckets(
    prompt_words: "set[str]", vocab: "dict[str, set[str]]", df: "dict[str, int]"
) -> "list[tuple[str, float, list[str]]]":
    """[(bucket_label, score, matched_words), ...] sorted highest score
    first. A word shared by many buckets contributes little (1/df); a word
    nearly unique to one bucket contributes close to its full weight -- so a
    bucket wins on a few distinctive shared words, not on volume of
    generic overlap."""
    scored = []
    for label, words in vocab.items():
        hits = prompt_words & words
        if not hits:
            continue
        score = sum(1.0 / df[w] for w in hits)
        scored.append((label, score, sorted(hits)))
    scored.sort(key=lambda t: -t[1])
    return scored


def select_relevant_buckets(
    scored: "list[tuple[str, float, list[str]]]",
    buckets: "dict[str, list[Path]]",
) -> "list[tuple[str, float, list[str]]]":
    """Applies the score gate and the size caps to a pre-sorted score list.
    The gate on the SINGLE BEST bucket's own score (not a per-bucket floor
    alone) is the regression guard: a genuinely reasoning-only prompt with
    no real document need still shares a stray generic word or two with
    some department's filenames by chance, but its best bucket's score sits
    far below a prompt that is actually about that department's documents
    (verified empirically: 2.0 clears both the SVC-PC-38 and SVC-PC-52
    top buckets while a prompt with only incidental overlap does not reach
    it). Only once that gate passes does the lower per-bucket floor decide
    which additional buckets join the top one."""
    if not scored or scored[0][1] < BUCKET_TOP_SCORE_GATE:
        return []
    selected = [
        (label, score, hits)
        for label, score, hits in scored
        if score >= BUCKET_INCLUDE_FLOOR
    ][:BUCKET_MAX_COUNT]
    total = 0
    capped: "list[tuple[str, float, list[str]]]" = []
    for label, score, hits in selected:
        n = len(buckets[label])
        if capped and total + n > BUCKET_MAX_TOTAL_FILES:
            break
        capped.append((label, score, hits))
        total += n
    return capped


def hydrate(
    task_dir: Path,
    corpus_index: dict[str, list[Path]],
    persona_slugs: set[str],
    out_dir: Path,
    corpus_root: "Path | None" = None,
) -> dict:
    """Stage every resolved file into out_dir (mirroring L1-*/ subfolder
    names; corpus files flat). Returns a report dict for this task."""
    report = {
        "task_id": task_dir.name,
        "resolved": [],
        "not_found": [],
        "ambiguous": [],
    }
    out_dir.mkdir(parents=True, exist_ok=True)

    l1_files = l1_source_files(task_dir)
    for src, rel in l1_files:
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        report["resolved"].append(f"L1:{rel}")

    manifest_paths = declared_manifest_paths(task_dir)
    report["manifest_declared_count"] = len(manifest_paths)
    for path in manifest_paths:
        name = Path(path).name
        status, paths = resolve_filename(name, corpus_index, set(), set())
        if status == "resolved":
            shutil.copy2(paths[0], out_dir / paths[0].name)
            report["resolved"].append(f"manifest:{paths[0]}")
        elif status == "not-found":
            report["not_found"].append(f"manifest:{name}")
        else:
            report["ambiguous"].append(f"manifest:{name} -> {[str(p) for p in paths]}")

    try:
        prompt_path = rxv.find_prompt_file(task_dir)
        prompt_text = rxv.extract_prompt_text(prompt_path)
    except rxv.ConversionError as e:
        prompt_text = ""
        report["not_found"].append(f"prompt file unreadable: {e}")

    try:
        deliverable_names = set(rxv.find_deliverable_files(task_dir))
    except rxv.ConversionError:
        deliverable_names = set()

    prompt_candidates = []
    if prompt_text:
        prompt_wide_personas = persons_anywhere_in(prompt_text, persona_slugs)
        prompt_candidates = extract_candidate_filenames(
            prompt_text, deliverable_names, persona_slugs
        )
        for name, local_personas in prompt_candidates:
            status, paths = resolve_filename(
                name, corpus_index, local_personas, prompt_wide_personas
            )
            if status == "resolved":
                shutil.copy2(paths[0], out_dir / paths[0].name)
                report["resolved"].append(f"corpus:{paths[0]}")
            elif status == "not-found":
                report["not_found"].append(name)
            else:
                report["ambiguous"].append(f"{name} -> {[str(p) for p in paths]}")

    # Cause 5: a Source:-line/unfilled-placeholder collision is diagnostic
    # metadata worth recording regardless of whether the environment ends up
    # empty (it explains WHY is_self_reference() discarded that candidate).
    template_defects = detect_template_source_collision(prompt_text, deliverable_names)
    if template_defects:
        report["template_authoring_defect"] = template_defects

    role_match_buckets: "list[dict]" = []
    if not any(out_dir.iterdir()) and prompt_text and corpus_root is not None:
        # Cause 1 fallback: every other source came up empty. Try scoring
        # corpus department/persona folders against the prompt's own
        # vocabulary and staging whichever ones show a real, distinctive
        # overlap -- see the block comment above ROLE_MATCH_STOPWORDS.
        buckets = build_folder_buckets(corpus_index, corpus_root)
        vocab = _bucket_vocabulary(buckets)
        df = _word_bucket_document_frequency(vocab)
        prompt_words = _significant_words(
            re.findall(r"[A-Za-z]+|\d+", prompt_text.lower())
        )
        scored = score_folder_buckets(prompt_words, vocab, df)
        selected = select_relevant_buckets(scored, buckets)
        for label, score, hits in selected:
            dest_dir = out_dir / "_corpus_subtree" / label.replace("/", "__")
            for p in buckets[label]:
                dest = dest_dir / p.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest)
                report["resolved"].append(f"role-bucket:{label}/{p.name}")
            role_match_buckets.append(
                {"bucket": label, "score": round(score, 3), "matched_words": hits}
            )
        if role_match_buckets:
            report["role_match_buckets"] = role_match_buckets
            report["explicit_corpus_search_instruction"] = bool(
                EXPLICIT_CORPUS_SEARCH_RE.search(prompt_text)
            )

    if not any(out_dir.iterdir()):
        has_l1_outputs = len(l1_files) > 0
        has_manifest_entries = len(manifest_paths) > 0
        has_prompt_candidates = len(prompt_candidates) > 0
        unresolved_prompt_names = [
            name
            for name, _ in prompt_candidates
            if name in report["not_found"]
            or any(name in entry for entry in report["ambiguous"])
        ]

        if template_defects:
            placeholder_msg = (
                "This task's prompt has a 'Source:' line naming exactly this "
                "task's own graded deliverable, alongside an unfilled "
                "'[the ...]' template placeholder elsewhere in the prompt. "
                "That is a broken template substitution, not a "
                "self-reference or a reasoning-only task: the real upstream "
                "source this Source: field should have named was lost, and "
                "is not recoverable from the prompt text. Needs a human to "
                "fix the template/prompt authoring, not another hydration "
                "attempt. Offending line(s):\n"
            )
            for d in template_defects:
                placeholder_msg += (
                    f"  - Source: {d['source_filename']!r} (placeholder: "
                    f"{d['placeholder']!r})\n"
                )
            placeholder_kind = "template_authoring_defect"
        elif unresolved_prompt_names or (has_manifest_entries and report["not_found"]):
            placeholder_msg = (
                "This task requested input files but resolution failed. "
                "Unresolved names:\n"
            )
            for name in unresolved_prompt_names:
                placeholder_msg += f"  - {name}\n"
            for entry in report["not_found"]:
                if entry.startswith("manifest:"):
                    placeholder_msg += f"  - {entry}\n"
            placeholder_msg += "This is a hydration gap requiring manual review.\n"
            placeholder_kind = "hydration_gap"
        elif has_l1_outputs or has_manifest_entries or has_prompt_candidates:
            placeholder_msg = (
                "Hydration found candidates (L1 folders, manifest entries, or prompt-named files) "
                "but nothing resolved successfully. Review resolution errors above. "
                "This is a hydration gap.\n"
            )
            placeholder_kind = "hydration_gap"
        else:
            placeholder_msg = (
                "This task's prompt names no specific input files, has no L1-* "
                "upstream outputs, and declares no Read Me input manifest entries "
                "-- appears to be reasoning-only.\n"
            )
            placeholder_kind = "reasoning_only"

        (out_dir / "_no_input_files_required.txt").write_text(placeholder_msg)
        report["placeholder"] = True
        report["placeholder_kind"] = placeholder_kind
        report["unresolved_prompt_names"] = unresolved_prompt_names
    else:
        report["placeholder"] = False
        report["placeholder_kind"] = None

    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("task_dir", type=Path)
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="defaults to <task_dir>/../_hydrated/<task_id>",
    )
    args = ap.parse_args()

    print(f"indexing corpus ({args.corpus}) ...")
    try:
        index, persona_slugs, warnings = index_corpus(args.corpus)
    except CorpusIndexError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    for w in warnings:
        print(f"  WARNING: {w}", file=sys.stderr)
    print(
        f"  indexed {sum(len(v) for v in index.values())} files, {len(persona_slugs)} personas"
    )

    out_dir = args.out or (args.task_dir.parent / "_hydrated" / args.task_dir.name)
    report = hydrate(
        args.task_dir, index, persona_slugs, out_dir, corpus_root=args.corpus
    )

    print(
        f"{report['task_id']}: {len(report['resolved'])} resolved, "
        f"{len(report['not_found'])} not-found, {len(report['ambiguous'])} ambiguous "
        f"(Read Me manifest declared {report.get('manifest_declared_count', 0)})"
    )
    for r in report["resolved"]:
        print(f"  ok: {r}")
    for r in report["not_found"]:
        print(f"  NOT FOUND: {r}")
    for r in report["ambiguous"]:
        print(f"  AMBIGUOUS: {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
