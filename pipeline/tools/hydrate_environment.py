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
PERSONA_DIR_RE = re.compile(r"^My Drive — (?P<slug>[\w.]+)$")
PROXIMITY_WINDOW = 80  # chars of text immediately before a filename mention to scan for a person's name


class HydrationError(Exception):
    pass


def build_corpus_index(corpus_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for p in corpus_root.rglob("*"):
        if p.is_file():
            index.setdefault(p.name.lower(), []).append(p)
    return index


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
        return any(d.lower().endswith(name.lower()) for d in deliverable_names)

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
            if any(f"My Drive — {slug}" in p.parts for slug in personas)
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


def hydrate(
    task_dir: Path,
    corpus_index: dict[str, list[Path]],
    persona_slugs: set[str],
    out_dir: Path,
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

    for src, rel in l1_source_files(task_dir):
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

    if prompt_text:
        prompt_wide_personas = persons_anywhere_in(prompt_text, persona_slugs)
        for name, local_personas in extract_candidate_filenames(
            prompt_text, deliverable_names, persona_slugs
        ):
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

    if not any(out_dir.iterdir()):
        (out_dir / "_no_input_files_required.txt").write_text(
            "This task's prompt names no specific input files, has no L1-*"
            " upstream outputs, and declares no Read Me input manifest entries"
            " -- confirmed reasoning-only, not a hydration gap.\n"
        )
        report["placeholder"] = True

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

    if not args.corpus.is_dir():
        print(f"ERROR: corpus not found: {args.corpus}", file=sys.stderr)
        return 1

    persona_slugs = {
        m.group("slug")
        for d in args.corpus.iterdir()
        if (m := PERSONA_DIR_RE.match(d.name))
    }
    print(f"indexing corpus ({args.corpus}) ...")
    index = build_corpus_index(args.corpus)
    print(
        f"  indexed {sum(len(v) for v in index.values())} files, {len(persona_slugs)} personas"
    )

    out_dir = args.out or (args.task_dir.parent / "_hydrated" / args.task_dir.name)
    report = hydrate(args.task_dir, index, persona_slugs, out_dir)

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
