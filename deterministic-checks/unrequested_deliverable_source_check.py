#!/usr/bin/env python3
r"""Unrequested-deliverable-source check: for every file a task's grading config actually reads
(a real graded source -- not just a file that happens to sit in solution/), does that file's
name appear anywhere in `instruction.md`, the solver-facing prompt?

Why this exists (provenance): Pietro Carra's team (Perplexity's QC review of this same EKW
corpus, `ekw_structural_review.md`, shared 2026-09-15) named this "S-10": because EKW's
`solution/solve.sh` is literally `find "$GOLDEN_DIR" -maxdepth 1 -type f -exec cp -p {} "$OUTPUT_DIR/" \;`
-- it copies EVERY file in `golden_outputs/`, not just what the instruction asks for -- 177 of
223 EKW tasks ship a `Reasoning.docx` in the graded output directory that NO instruction ever
asks for (0 of 223 mention it), and 15 of those 177 contain literal grading/rubric commentary
or acceptance-band tables. SVC-PC's `solution/solve.sh` (`cp -a /solution/files/. /app/`) is the
exact same "copy everything" pattern under different path conventions, so this check runs
against both formats. Pietro's own general form of the test: "the instruction, not the directory
listing, decides which deliverables exist -- a golden output is only eligible as a verifier
source if the instruction names it."

## Relationship to this folder's other checks

Three checks already exist for answer-key leakage; reading all three docstrings first is what
makes clear this is a fourth, distinct mechanism, not a duplicate:
  - `answer_key_leakage_check.py` -- does instruction.md itself contain a GOLDEN-named filename
    or internal pipeline jargon? (leakage in the PROMPT'S OWN TEXT)
  - `answer_key_content_leak_check.py` -- does a rubric's literal EXPECTED VALUE (a number, a
    date, a dollar figure) appear verbatim inside a file the solver can actually read in
    environment/? (leakage of VALUES into solver-visible INPUT files)
  - `answer_key_rubric_leak_check.py` -- does a criterion's own grading PROSE near-verbatim-copy
    the golden answer's prose? (TEXT OVERLAP between rubric and golden CONTENT)
  None of the three asks this check's question: is a file the verifier actually GRADES ever
  named as a deliverable in the prompt at all? That is a naming/scope question about the
  GRADING CONFIG's own file list against the PROMPT, independent of what those files contain.

`deliverable_filename_check.py` is the closer relative and the overlap is real, disclosed here
rather than glossed over: its FORWARD direction already asks "does every judge.toml/verifier.json
filename get named in instruction.md," for SVC-PC's top-level `[judge].files` (via its own
`load_judge_files()`) and for EKW's per-verifier files (via `ekw_verifier_json.load_ekw_files()`,
the same shared module this script also imports). That script's own "Known limits" section
discloses the gap this script fills: "Only a judge.toml's top-level [judge].files list is
checked. A criterion-level files=[...] override... is out of scope here." Confirmed real and not
hypothetical: a corpus-wide scan (see Verification below) found `[[criterion]].files` overrides
naming files the task's own `[judge].files` list never mentions (SVC-PC-10-0-0 c01/c12,
SVC-PC-19-5-0 f01/f02) -- exactly the shape `deliverable_filename_check.py`'s FORWARD direction
is structurally blind to, because it never reads a `[[criterion]]` table's own `files=` key. This
script's real incremental value over the existing FORWARD direction is threefold: (1) it also
extracts and checks `[[criterion]].files` overrides, closing that disclosed gap; (2) it
optionally cross-references a flagged file against `solution/golden_outputs/`
(EKW) or `solution/files/` (SVC-PC) to surface the sharper "this isn't just unrequested, it's
the literal gold artifact" form of the finding (S-10's own example), which
`deliverable_filename_check.py` does not attempt; (3) it is framed and reported specifically
around the S-10 defect (a Reasoning.docx-shaped answer-key leak sitting in the graded directory),
with its own JSON/CLI shape matching `verifier_executability_check.py`'s convention
(`n_pass`/`n_fail`/`by_format`), not `deliverable_filename_check.py`'s FORWARD/REVERSE shape. It
does NOT re-implement the REVERSE direction (commanded-but-not-graded) at all -- that is a
different defect shape, already owned by that script.

## What it checks, per task

1. Every graded source filename is extracted from the task's real grading config:
     - EKW: `tests/verifier.json`, via `ekw_verifier_json.load_ekw_files()` -- the same shared,
       corpus-tested parser `deliverable_filename_check.py`, `rubric_schema_check.py`, and
       `judge_criterion_name_duplicate_check.py` already depend on. It already handles every
       known `source` shape on this corpus (a single file object, a list of file objects, a
       plural `files` key, a bare `{"path": ...}` with no `arguments` wrapper, a `paths` list,
       the `task_FIN-177` alt-schema, and a `type: "directory"` entry that correctly yields NO
       path). A `response.extract_final_message`-type source (no `file`/`files` key at all)
       naturally extracts zero paths through this module -- there is nothing to skip by hand,
       the shared parser already only extracts what has a real filename.
     - SVC-PC: every `tests/**/judge.toml` under the task (recursive glob -- confirmed necessary
       against the real corpus: task directories exist as `tests/deliverables/judge.toml`,
       `tests/deliverables_01/judge.toml`, etc, no single fixed pattern), read with
       `tomllib.load(open(path, "rb"))` (binary mode -- see Known traps below), walking BOTH
       `[judge].files` (the shared list for every criterion in that judge.toml, when a
       `[[criterion]]` carries no override of its own) AND each `[[criterion]].files` (a
       per-criterion override list, confirmed present and real on this corpus -- see
       Verification below; absent on most criteria, which is normal and simply means that
       criterion inherits `[judge].files`).
   Every extracted path is reduced to its basename (the same `path.replace("\\","/").rsplit("/",
   1)[-1]` idiom `deliverable_filename_check.py` uses, for the same reason: a judge.toml entry
   is a literal absolute `/app/...` path and a verifier.json entry is a relative `output/...`
   path -- neither is comparable to prose without stripping the directory).
2. For each distinct graded basename, checks whether it (or an obvious variant) appears anywhere
   in `instruction.md`'s raw text: exact basename (case-sensitive) first; then a case-insensitive
   basename match; then, only if the extension-stripped stem is at least 4 characters (to avoid
   a short generic stem like "v1" or "ch1" matching unrelated prose), a case-insensitive
   stem-only match. This is deliberately NOT fuzzy beyond that -- no synonym matching, no
   Levenshtein distance -- per this folder's own established practice of keeping a mechanical
   check mechanical and disclosing what it therefore misses (see Known limits).
3. Any graded basename matched by NONE of those three passes is flagged as a candidate: "this
   verifier/criterion grades a file the instruction never names as a deliverable." Every
   verifier name (EKW) or judge.toml path + `[judge]`/criterion name (SVC-PC) that references the
   flagged basename is recorded for provenance -- a basename graded by three different verifiers
   is reported once with all three attributions, not three times.
4. Status vocabulary matches this folder's established non-gating convention (see
   `answer_key_content_leak_check.py` and `answer_key_rubric_leak_check.py`, both of which use
   exactly `clean` / `candidate`, not a hard pass/fail): "candidate", never "confirmed" or
   "flagged" outright. Exact-filename-absence from the prompt is suggestive, not proof -- a task
   can legitimately request a deliverable by description ("submit your analysis as a Word
   document") without ever typing its exact filename, and this check cannot and does not try to
   recognize that shape. A human reviewing a "candidate" finding needs to open instruction.md and
   confirm the file genuinely has no requested counterpart before treating it as a real S-10
   instance.
5. Optional, cheap cross-check (included -- computing it costs nothing beyond a `Path.is_file()`
   call against data already being walked): for each flagged candidate, does a same-named file
   also exist under `solution/golden_outputs/` (EKW) or `solution/files/` (SVC-PC) -- the exact
   directory `solve.sh` copies wholesale from? If so, `origin_is_golden` is set true and the
   resolved path recorded. This is a **filename-existence** check, not a byte-hash comparison --
   disclosed explicitly under Known limits, since a same-named-but-different-content coincidence
   is theoretically possible (not observed on this corpus, but not ruled out by this check
   alone). It is included because it is exactly what makes an unrequested-deliverable finding
   the SHARPER S-10 shape Pietro's report describes (a literal answer-key artifact riding along
   in the graded directory) rather than merely an unrequested-but-harmless extra file.

## Known traps avoided (already hit and fixed elsewhere in this session -- not rediscovered here)

- `harbor-rewardkit`'s own `_load_toml` (`rewardkit/runner.py`) does `path.read_text()` with no
  explicit encoding, which defaults to cp1252 on Windows and throws `UnicodeDecodeError` on a
  judge.toml containing UTF-8 multi-byte characters (an em dash, a smart quote). This script
  never imports rewardkit -- no execution is needed for a pure text/JSON/TOML presence check --
  but the same class of trap applies to any naive `.read_text()` call on Windows, so every read
  in this script is explicit: `tomllib.load(open(path, "rb"))` for TOML (binary mode sidesteps
  codec guessing entirely -- tomllib decodes UTF-8 internally per the TOML spec), and
  `path.read_text(encoding="utf-8", errors="replace")` for `instruction.md`.
- This check needs NO execution at all: no `verifier_lib` import, no `rewardkit`, no subprocess.
  Pure text/JSON/TOML parsing, kept that way deliberately -- `--jobs` parallelism below is for
  wall-clock speed across many tasks, not because any single task's check does anything
  execution-shaped.

## Known limits, disclosed rather than silently dropped

- Literal-text presence only (plus the narrow case-insensitive/stem variants in step 2 above). A
  filename referenced only by description ("the reconciliation workbook"), split across a
  markdown table cell boundary, or wrapped in unusual punctuation this script doesn't strip, can
  read as a false "candidate" -- this is the same class of limitation
  `deliverable_filename_check.py`'s FORWARD direction already discloses for the identical reason.
- The stem-only fallback match is a real, disclosed source of false NEGATIVES in the other
  direction: a short/generic stem could coincidentally appear in unrelated prose and suppress a
  genuine candidate. Empirically confirmed live, not just theoretical: across the full EKW and
  SVC-PC corpora, exactly 2 matches (out of 1,384 total) were won by the loose stem-only tier
  rather than an exact basename match, and both turned out to be a real, adjacent defect this
  check doesn't otherwise look for -- an `.xlsx`/`.xlsm` extension mismatch between the graded
  source and the filename instruction.md names, silently absorbed into a "clean" verdict with
  no trace. Every task's result now carries a `matched` list (`{basename, how}` for every
  matched source, not just candidates) and an `n_loose_tier_matches` count, and the aggregate
  CLI summary prints a NOTE naming the total whenever it's nonzero -- so a human auditing a
  "clean" result can actually see when it was won by a loose tier, which an earlier version of
  this check's own docstring claimed but did not implement (caught by adversarial review before
  shipping; fixed here, not just re-described).
- `origin_is_golden` is a same-basename existence check against `solution/golden_outputs/` or
  `solution/files/`, not a content hash comparison -- see point 5 above.
- SVC-PC `[[criterion]].files` extraction trusts the TOML's own `files = [...]` array shape;
  a criterion that names a file some other way (inside `description` prose only, for instance)
  is invisible to this extraction step, same as `deliverable_filename_check.py`'s equivalent
  limitation for `[judge].files`.
- This script checks the CURRENT on-disk state of the task directory under `--root`. It makes no
  claim about a task's history.

## Verification against the real corpora (2026-09-15)

EKW corpus: `C:\\ekwqc\\_merged274\\files`, `--all --jobs 8`, all 274 real task directories, zero
crashes, zero parse errors, zero `unknown`-format or `skip` results (every task had a detectable
format and at least one graded source). Result: **272 clean, 2 candidate.** The 2 candidates are
`task_5` and `task_574`, both flagging `Reasoning.docx` -- referenced as a graded `source.file`
by 2-3 verifiers each, never named anywhere in either task's `instruction.md` (confirmed absent,
not just unmatched: a direct case-insensitive grep for "reasoning" against both instruction.md
files returns zero hits), and in both cases `origin_is_golden` confirms a same-named file exists
at `solution/golden_outputs/Reasoning.docx`. An independent grep (`grep -rl "Reasoning.docx"
--include=verifier.json`) across the full corpus, run separately from this script as a
cross-check, found exactly 3 verifier.json files mentioning that string at all --
`task_5`, `task_574`, AND `task_273` -- matching Pietro's own count ("only 3 verifier.json files
reference it") exactly. `task_273` is correctly NOT flagged: reading it directly shows
`Reasoning.docx` genuinely IS one of task_273's requested deliverables (instruction.md's own
deliverables list describes it by name and by required content, source.file.arguments.path is
`output/Reasoning.docx`, and the rubric grades its actual required content) -- a real, intended
deliverable that happens to reuse EKW's generic default filename, not a leak. This is the correct
result, not a false negative: the check's premise is graded-AND-unrequested, and task_273 is
graded-AND-requested.

`task_1` / `Reasoning.docx` specific check (Pietro's own worked example task): confirmed directly
by reading `tests/verifier.json` -- task_1's 20 verifiers (v1-v20) reference exactly two source
files, `output/tronox_credit_model.xlsx` and `output/tronox_investment_decision_memo.docx`.
`Reasoning.docx` is NOT a `source.file.arguments.path` in ANY of task_1's 20 verifiers, even
though it does exist under `solution/golden_outputs/` (and would therefore land in the graded
`output/` directory via `solve.sh`'s copy-everything behaviour). Because this check only flags a
FILE THE VERIFIER ACTUALLY READS, task_1 correctly produces ZERO findings for Reasoning.docx --
it is an unrequested extra file sitting in the output directory, but since no verifier's `source`
ever points at it, it is graded by nothing and therefore out of this check's scope by
construction. task_1 is one of the 271 EKW tasks (274 minus the 3 that reference Reasoning.docx
at all) where the file is simply never a graded source. This is the expected, honest result for
this specific task, not a bug: the check's whole premise is "flag a file that IS graded but NOT
requested," and task_1's Reasoning.docx fails the first half of that conjunction.

SVC-PC corpus: `C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready`, `--all --jobs 8`,
all 600 real task directories (the full corpus, not a sample -- the check is pure text/TOML
parsing and the entire sweep completed in about 2 seconds), zero crashes, zero parse errors,
zero skips. Result: **597 clean, 3 candidate**, all three in one templated family:
`SVC-PC-9-3-0`, `SVC-PC-9-4-0`, `SVC-PC-9-5-0`, 5-6 flagged files each (16 total), every one
confirmed `origin_is_golden` against `solution/files/`. Read directly: these three are a
different underlying shape from the EKW pair above, disclosed plainly rather than conflated with
S-10's narrower "one extra file rides along" pattern -- each of these three instruction.md files
is a short internal-email-style prompt that names NO deliverable filename anywhere (no "Graded
deliverable filenames" section, no filename in prose at all), while both of that task's
`judge.toml` groups (`deliverables_01`, `deliverables_02`) grade every one of 5-6 specifically
named files. This is a real, confirmed structural defect (a solver following the prompt exactly
has no way to learn what filenames to produce) that this check's mechanism correctly surfaces,
but it is the SAME defect shape `deliverable_filename_check.py`'s existing FORWARD direction
would also catch via its own top-level `[judge].files` extraction (these three tasks have no
criterion-level override at all -- the flagged files are all top-level `[judge].files` entries)
-- named here so the two scripts' results on this family are not mistaken for independent
confirmations of two different defects. The corpus-wide criterion-level-override gap this script
adds coverage for (see SVC-PC-10-0-0 and SVC-PC-19-5-0 below) produced zero NEW candidates beyond
what the top-level extraction already found across the full 600-task sweep -- every real
criterion-level override this script found across the corpus turned out to already be properly
named in its instruction.md.

Criterion-level `files=[...]` override extraction (the specific gap `deliverable_filename_check.py`
discloses as out of scope) confirmed present and exercised on real data, not just handled in
theory: a corpus-wide scan for `[[criterion]]` blocks carrying their own `files=` key found it in
`SVC-PC-10-0-0` (`tests/deliverables/judge.toml`, criteria c01 and c12, each overriding to a
3-file list that includes two files -- `..._Email.docx`, `..._Report.pdf` -- absent from that
task's own top-level `[judge].files`, which names only the `.xlsx`) and `SVC-PC-19-5-0`
(`tests/deliverables_01/judge.toml`, criteria f01 and f02, overriding to a 2-file list including
a `.docx` absent from `[judge].files`, which names only the `.xlsx`). Both were run individually
through this script and correctly returned `clean`: both extra files ARE named in each task's own
"## Graded deliverable filenames" section. This is the intended, disclosed-as-suggestive-not-
gating behaviour working exactly as designed on real data -- the extraction path this script adds
over `deliverable_filename_check.py`'s FORWARD direction is exercised and produces the right
answer on both real examples found, even though neither happens to be a genuine defect.

Usage:
    python unrequested_deliverable_source_check.py <TASK-ID> [<TASK-ID> ...] --root <path> [--out report.json]
    python unrequested_deliverable_source_check.py --all --root <path> [--out report.json] [--jobs N]
    python unrequested_deliverable_source_check.py --all --root <path> --id-prefix SVC-PC- [--out report.json]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ekw_verifier_json import has_ekw_config, load_ekw_files

# Windows console defaults to cp1252; force UTF-8 with replacement so a printable-but-non-cp1252
# character (an em dash, a smart quote) in some task's instruction.md never crashes a batch run
# partway through. Same pattern deliverable_filename_check.py uses.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# task discovery / format detection
# ---------------------------------------------------------------------------


def find_task_dirs(
    root: Path, task_ids: list[str] | None = None, id_prefix: str = ""
) -> list[Path]:
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


def _detect_format(task_dir: Path) -> str:
    """Identical convention to verifier_executability_check.py's own _detect_format: "ekw" if
    tests/verifier.json exists, "svc_pc" if any tests/**/judge.toml exists, "unknown" otherwise
    (reported, never raised)."""
    if (task_dir / "tests" / "verifier.json").is_file():
        return "ekw"
    if any(task_dir.glob("tests/**/judge.toml")):
        return "svc_pc"
    return "unknown"


def _basename(raw: str) -> str:
    """Same idiom deliverable_filename_check.py's own basename() uses: reduce a judge.toml or
    verifier.json path entry to its bare filename regardless of which separator it was authored
    with (an absolute /app/... path for SVC-PC, a relative output/... path for EKW)."""
    return str(raw).replace("\\", "/").rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# graded-source extraction, one shape per format, both returning the same
# {basename: {"raw_paths": set[str], "referenced_by": list[str]}} shape
# ---------------------------------------------------------------------------


def _extract_ekw_sources(
    task_dir: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    by_basename: dict[str, dict[str, Any]] = {}
    sources, parse_errors = load_ekw_files(task_dir)
    for s in sources:
        vname = s.get("group", "__unknown__")
        for raw in s.get("files", []):
            if not raw:
                continue
            bn = _basename(raw)
            if not bn:
                continue
            entry = by_basename.setdefault(
                bn, {"raw_paths": set(), "referenced_by": []}
            )
            entry["raw_paths"].add(raw)
            entry["referenced_by"].append(f"tests/verifier.json: verifier {vname}")
    errs = [
        {"path": pe.get("path", "tests/verifier.json"), "error": pe.get("error", "")}
        for pe in parse_errors
    ]
    return by_basename, errs


def _extract_svc_pc_sources(
    task_dir: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    by_basename: dict[str, dict[str, Any]] = {}
    parse_errors: list[dict[str, str]] = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return by_basename, parse_errors

    for jt in sorted(tests_dir.glob("**/judge.toml")):
        rel = str(jt.relative_to(task_dir)).replace("\\", "/")
        try:
            with open(jt, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            parse_errors.append({"path": rel, "error": f"{type(e).__name__}: {e}"})
            continue

        judge = data.get("judge", {})
        judge = judge if isinstance(judge, dict) else {}
        group = jt.parent.name
        judge_files = judge.get("files", [])
        if isinstance(judge_files, list):
            for raw in judge_files:
                if not isinstance(raw, str) or not raw:
                    continue
                bn = _basename(raw)
                if not bn:
                    continue
                entry = by_basename.setdefault(
                    bn, {"raw_paths": set(), "referenced_by": []}
                )
                entry["raw_paths"].add(raw)
                entry["referenced_by"].append(f"{rel}: [judge] (group {group})")

        criteria = data.get("criterion", [])
        if not isinstance(criteria, list):
            criteria = []
        for c in criteria:
            if not isinstance(c, dict):
                continue
            cname = c.get("name", "__unnamed__")
            cfiles = c.get("files")
            # Absent/non-list means this criterion inherits [judge].files, already captured
            # above -- only a criterion carrying its OWN files=[...] override is new information.
            if not isinstance(cfiles, list):
                continue
            for raw in cfiles:
                if not isinstance(raw, str) or not raw:
                    continue
                bn = _basename(raw)
                if not bn:
                    continue
                entry = by_basename.setdefault(
                    bn, {"raw_paths": set(), "referenced_by": []}
                )
                entry["raw_paths"].add(raw)
                entry["referenced_by"].append(f"{rel}: [[criterion]] {cname}")

    return by_basename, parse_errors


# ---------------------------------------------------------------------------
# instruction.md presence matching
# ---------------------------------------------------------------------------


def _match_in_instruction(
    basename: str, instruction_text: str
) -> tuple[bool, str | None]:
    """Three tiers, tried in order, most-precise first. Returns (found, how) where `how` names
    which tier matched (None if none did). See module docstring step 2 for the stem-length
    guard's rationale."""
    if basename in instruction_text:
        return True, "exact_basename"
    if basename.lower() in instruction_text.lower():
        return True, "case_insensitive_basename"
    stem = Path(basename).stem
    if len(stem) >= 4:
        if stem in instruction_text:
            return True, "stem_only_case_sensitive"
        if stem.lower() in instruction_text.lower():
            return True, "stem_only_case_insensitive"
    return False, None


# ---------------------------------------------------------------------------
# golden-origin cross-check (optional enhancement, item 5)
# ---------------------------------------------------------------------------


def _golden_origin_dir(task_dir: Path, fmt: str) -> Path | None:
    if fmt == "ekw":
        d = task_dir / "solution" / "golden_outputs"
    elif fmt == "svc_pc":
        d = task_dir / "solution" / "files"
    else:
        return None
    return d if d.is_dir() else None


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir: Path) -> dict[str, Any]:
    task_id = task_dir.name
    fmt = _detect_format(task_dir)

    if fmt == "ekw":
        by_basename, parse_errors = _extract_ekw_sources(task_dir)
    elif fmt == "svc_pc":
        by_basename, parse_errors = _extract_svc_pc_sources(task_dir)
    else:
        by_basename, parse_errors = {}, []

    instruction_path = task_dir / "instruction.md"
    instruction_text = ""
    instruction_missing = not instruction_path.is_file()
    if not instruction_missing:
        try:
            instruction_text = instruction_path.read_text(
                encoding="utf-8", errors="replace"
            )
        except Exception as e:
            parse_errors.append({"path": "instruction.md", "error": str(e)})
            instruction_missing = True

    golden_dir = _golden_origin_dir(task_dir, fmt)

    findings = []
    matched = []
    n_matched = 0
    if not instruction_missing:
        for bn in sorted(by_basename):
            info = by_basename[bn]
            found, how = _match_in_instruction(bn, instruction_text)
            if found:
                n_matched += 1
                matched.append({"basename": bn, "how": how})
                continue
            origin_is_golden = False
            golden_path = None
            if golden_dir is not None:
                candidate = golden_dir / bn
                if candidate.is_file():
                    origin_is_golden = True
                    golden_path = str(candidate.relative_to(task_dir)).replace(
                        "\\", "/"
                    )
            findings.append(
                {
                    "basename": bn,
                    "raw_paths": sorted(info["raw_paths"]),
                    "referenced_by": info["referenced_by"],
                    "status": "candidate",
                    "reason": "this basename is a graded source (named in the task's own "
                    "grading config) but does not appear, exactly or by an obvious variant, "
                    "anywhere in instruction.md",
                    "origin_is_golden": origin_is_golden,
                    "golden_path": golden_path,
                }
            )

    n_graded = len(by_basename)
    n_candidates = len(findings)

    if instruction_missing:
        status = "skip"
    elif fmt == "unknown" or n_graded == 0:
        status = "skip"
    elif n_candidates > 0:
        status = "candidate"
    else:
        status = "clean"

    errors: list[str] = []
    if instruction_missing:
        errors.append("instruction.md not found or unreadable")
    if fmt == "unknown":
        errors.append(
            "neither tests/verifier.json (EKW) nor tests/**/judge.toml (SVC-PC) found"
        )
    for pe in parse_errors:
        errors.append(f"parse error in {pe.get('path')}: {pe.get('error')}")

    n_loose_tier_matches = sum(1 for m in matched if m["how"] != "exact_basename")

    return {
        "task_id": task_id,
        "format": fmt,
        "status": status,
        "n_graded_sources": n_graded,
        "n_matched": n_matched,
        "n_candidates": n_candidates,
        "n_loose_tier_matches": n_loose_tier_matches,
        "findings": findings,
        "matched": matched,
        "parse_errors": parse_errors,
        "errors": errors,
    }


def _analyze_task_safe(task_dir: Path) -> dict[str, Any]:
    """Module-level wrapper so ProcessPoolExecutor can pickle it (Windows spawn requires a
    top-level, importable target). Never lets one task's crash kill the whole batch -- same
    convention as verifier_executability_check.py's _analyze_task_safe."""
    try:
        return analyze_task(task_dir)
    except Exception as e:
        return {
            "task_id": task_dir.name,
            "format": "unknown",
            "status": "error",
            "n_graded_sources": 0,
            "n_matched": 0,
            "n_candidates": 0,
            "n_loose_tier_matches": 0,
            "findings": [],
            "matched": [],
            "parse_errors": [],
            "errors": [
                f"unhandled exception analyzing this task: {type(e).__name__}: {e}"
            ],
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="For every file a task's grading config actually reads as a source, check "
        "whether that filename is ever named in instruction.md. Flags a candidate when a graded "
        "file is never requested -- the S-10 pattern (Pietro Carra, ekw_structural_review.md): "
        "solve.sh copies every golden file into the graded directory, so an unrequested file can "
        "ride along as a real, gradable source, and some of those carry literal answer-key text. "
        "Pure text/JSON/TOML parsing -- no execution, no verifier_lib, no rewardkit."
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
        help="root directory containing one subdirectory per task (REQUIRED -- no default)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix as tasks",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    ap.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=max(1, (os.cpu_count() or 4) - 1),
        help="parallel worker processes (default: cpu_count-1, %(default)s; pass 1 to force "
        "serial). Pure text/JSON/TOML parsing per task, no execution, so this is only about "
        "wall-clock speed across many tasks.",
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

    results: list[dict[str, Any]] = []
    if args.jobs <= 1 or len(task_dirs) <= 1:
        for i, task_dir in enumerate(task_dirs, 1):
            print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
            r = _analyze_task_safe(task_dir)
            results.append(r)
            print(f"    -> {r['status']}", file=sys.stderr)
    else:
        print(
            f"Checking {len(task_dirs)} tasks with {args.jobs} parallel workers "
            "(pure text/JSON/TOML parsing, each task independent)...",
            file=sys.stderr,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as ex:
            future_to_dir = {ex.submit(_analyze_task_safe, td): td for td in task_dirs}
            done = 0
            for fut in concurrent.futures.as_completed(future_to_dir):
                task_dir = future_to_dir[fut]
                done += 1
                r = fut.result()  # _analyze_task_safe never raises
                results.append(r)
                print(
                    f"[{done}/{len(task_dirs)}] {task_dir.name} -> {r['status']}",
                    file=sys.stderr,
                )
        results.sort(key=lambda r: r.get("task_id", ""))

    n_clean = sum(1 for r in results if r["status"] == "clean")
    n_candidate = sum(1 for r in results if r["status"] == "candidate")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    n_error = sum(1 for r in results if r["status"] == "error")
    # n_pass/n_fail mirror verifier_executability_check.py's aggregate shape: pass = clean,
    # fail = candidate or error. skip is reported separately and counted in neither, matching
    # this folder's established convention that "skip" is not itself a claim either way.
    n_pass = n_clean
    n_fail = n_candidate + n_error

    by_format: dict[str, dict[str, int]] = {}
    for r in results:
        fmt = r.get("format", "unknown")
        d = by_format.setdefault(
            fmt,
            {"n_tasks": 0, "n_clean": 0, "n_candidate": 0, "n_skip": 0, "n_error": 0},
        )
        d["n_tasks"] += 1
        d[f"n_{r['status']}"] += 1

    n_total_candidate_files = sum(r["n_candidates"] for r in results)
    n_total_candidate_files_golden = sum(
        1 for r in results for f in r["findings"] if f.get("origin_is_golden")
    )
    n_total_loose_tier_matches = sum(r.get("n_loose_tier_matches", 0) for r in results)

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_clean": n_clean,
        "n_candidate": n_candidate,
        "n_skip": n_skip,
        "n_error": n_error,
        "n_total_candidate_files": n_total_candidate_files,
        "n_total_candidate_files_golden_origin": n_total_candidate_files_golden,
        "n_total_loose_tier_matches": n_total_loose_tier_matches,
        "by_format": by_format,
        "results": results,
    }

    print(
        f"\n{n_clean} clean / {n_candidate} candidate / {n_skip} skip / {n_error} error "
        f"out of {len(results)} task(s)  "
        f"({n_total_candidate_files} candidate file(s) total, "
        f"{n_total_candidate_files_golden} confirmed sitting under the golden solution dir "
        "by filename)"
    )
    if n_total_loose_tier_matches:
        print(
            f"  NOTE: {n_total_loose_tier_matches} match(es) across the corpus were won by a "
            "loose tier (case-insensitive or stem-only), not an exact basename match -- see "
            "each task's 'matched' field for which basename/tier. A loose match can mask an "
            "adjacent naming defect (e.g. an .xlsx/.xlsm extension mismatch) behind a 'clean' "
            "verdict -- audit these, don't just trust the aggregate count."
        )
    for fmt, d in sorted(by_format.items()):
        print(
            f"  format={fmt}: {d['n_clean']} clean / {d['n_candidate']} candidate / "
            f"{d['n_skip']} skip / {d['n_error']} error ({d['n_tasks']} tasks)"
        )
    for r in results:
        if r["status"] == "candidate":
            print(f"  {r['task_id']}: CANDIDATE")
            for f in r["findings"]:
                golden_note = (
                    f" [ORIGIN: matches {f['golden_path']} by filename]"
                    if f.get("origin_is_golden")
                    else ""
                )
                refs = "; ".join(f["referenced_by"])
                print(f"      ? {f['basename']} <- {refs}{golden_note}")
        elif r["status"] == "error":
            print(f"  {r['task_id']}: ERROR")
            for e in r["errors"]:
                print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
