"""Shared EKW `tests/verifier.json` reader, matching the two consumer shapes every SVC-PC
check script already expects from `judge.toml`, so a check only has to branch on which
config file exists and call the matching loader -- it never needs its own JSON parsing.

Why this is a separate module instead of one-off code in each script: `rubric_schema_check.py`,
`deliverable_filename_check.py`, and `judge_criterion_name_duplicate_check.py` all read the same
underlying verifier list for different purposes (weight-sum validation, filename cross-check,
name-collision detection). A single, tested parser here means all three see identical data,
rather than three independent re-implementations silently drifting apart.

Confirmed directly against two real EKW task packages this session (`task_142` and a `profound`
sample), not assumed from documentation:
  - `tests/verifier.json` (JSON), not `tests/deliverables_*/judge.toml` (TOML).
  - Top-level keys: `task_id`, `config` (`models`, `temperature`, `reasoning_effort`),
    `verifiers`.
  - `verifiers` is a JSON ARRAY of objects, not a dict keyed by name. `.items()`/`.keys()` will
    throw -- iterate the list directly.
  - Per verifier: `name`; `metadata.weight` (float; also carries `tag`, `importance`,
    `grading_role`, `how_justification`, `why_justification`, none of which this module surfaces
    since no current check consumes them); `source.type` (`"file"` in every verifier seen);
    `source.file.type` (`xlsx`/`docx`/`pptx` observed); `source.file.command`
    (`"extract_text"` in every verifier seen); `source.file.arguments.path` (the graded
    deliverable path, relative, always under `output/`); `assertion.type` (`"rubric"` in every
    verifier seen -- no deterministic/non-rubric verifier observed); `assertion.expected`
    (`true` in every verifier seen); `assertion.rubric.prompt` (the free-text pass/fail
    criteria -- the closest EKW equivalent to `judge.toml`'s `description` field).
  - No per-verifier "group" concept exists the way SVC-PC's `deliverables_NN` subdirectories
    group multiple criteria under one shared `judge.files` list -- each EKW verifier carries its
    own file path(s) directly. This module treats each verifier as its own group for
    provenance purposes (see `load_ekw_criteria`'s `group` field below).
  - **`source.file` is not always a single object.** Confirmed by running this module against
    all 274 real tasks, not just the 2 samples the shape was originally confirmed against:
    `task_270`, `task_326`, `task_536`, `task_569`, `task_600` all have verifiers whose
    `source.file` is a JSON ARRAY of file objects (a cross-file verifier grading two deliverables
    together, e.g. an xlsx and a docx in the same criterion), each with its own
    `type`/`command`/`arguments.path`. This module extracts every path in that case rather than
    assuming exactly one file per verifier.
  - Weight sums to 1.0 across all verifiers in both samples checked (unconfirmed across the
    other 272 EKW tasks -- `rubric_schema_check.py`'s own weight-sum validation is what actually
    checks this at scale once wired to this module).

Sample-size caveat, stated plainly: 2 of 274 packages were opened to confirm this shape. Both
were 100% rubric-type verifiers with a single source file each. This is not a claim about the
other 272 -- if a verifier.json ever has `assertion.type != "rubric"`, `source.type != "file"`,
or a `metadata.weight` that's missing/non-numeric, this module records it as `__parse_error__`
(matching `load_judge_criteria`'s existing SVC-PC parse-error convention) rather than crashing
or silently dropping it.
"""

import json
import re
from pathlib import Path

# Matches certification_gate_check.py's own MUST_PASS_RE exactly (kept as a separate literal
# here rather than imported, so this module -- the shared, dependency-free parser everything
# else in this folder imports FROM -- never imports from a downstream consumer). Used as the
# EKW text-marker fallback for must_pass below: metadata.must_pass is native and authoritative
# when present, but not every real verifier.json sets it (semantic-consistency-design-2026-09-14.md
# section 8.2), so a prompt stating "This is a must-pass criterion." in prose is still detected.
_MUST_PASS_RE = re.compile(r"must[\s-]*pass", re.IGNORECASE)


# Both spellings of the vendored verifier library are real in this corpus, and a check that knows
# only one silently mishandles the rest. Measured 2026-09-22 across the 79 shipped v7 packages:
# 47 ship `tests/__verifier_lib/`, 28 ship `tests/verifier_lib/` (the whole LGL batch plus
# task_78/79/81/86/97/98). Each spelling is imported under its OWN package name by that task's
# own runtime -- `from __verifier_lib.runner import ...` vs `from verifier_lib.runner import ...`
# -- so callers need the module name, not just the directory.
#
# This helper exists because the same one-line assumption was found three separate times in one
# session: container_build_check.py and verifier_requirements_pin_mismatch_check.py knew only the
# double-underscore spelling (so they reported `pass`/`skip` on 28 tasks, which is how
# task_LGL-168 shipped with drifted requirements and scored reward 0.0), and
# source_truncation_check.py knew only the single-underscore spelling (so it reported `error` on
# all 47 double-underscore tasks). Import from here rather than hardcoding either name.
VERIFIER_LIB_DIR_NAMES = ("__verifier_lib", "verifier_lib")


def verifier_lib_dir(task_dir):
    """The task's vendored verifier library directory, whichever spelling it uses, or None.

    `task_dir` is the package root (the directory holding `tests/`)."""
    tests = Path(task_dir) / "tests"
    for name in VERIFIER_LIB_DIR_NAMES:
        d = tests / name
        if d.is_dir():
            return d
    return None


def verifier_lib_module_name(task_dir):
    """The importable package name for this task's vendored verifier library, or None.

    Matches the directory name, because that is what the task's own `verifier_runtime` imports."""
    d = verifier_lib_dir(task_dir)
    return d.name if d is not None else None


def load_ekw_verifiers_raw(task_dir):
    """Read tests/verifier.json and return the raw list of verifier dicts, or an empty list if
    the file doesn't exist or fails to parse (parse failure is recorded in the second return
    value, mirroring load_judge_files' (sources, parse_errors) convention).

    Returns (verifiers, task_id, config, parse_error):
        verifiers   -- list of raw verifier dicts (empty list on missing file or parse error)
        task_id     -- the file's own "task_id" field, or None
        config      -- the file's own "config" dict ({}, if absent)
        parse_error -- str error message, or None if the file parsed cleanly (or didn't exist)
    """
    vj = task_dir / "tests" / "verifier.json"
    if not vj.is_file():
        return [], None, {}, None
    try:
        data = json.loads(vj.read_text(encoding="utf-8"))
    except Exception as e:
        return [], None, {}, f"tests/verifier.json failed to parse: {e}"
    verifiers = data.get("verifiers", [])
    if not isinstance(verifiers, list):
        return (
            [],
            data.get("task_id"),
            data.get("config", {}),
            (
                f"tests/verifier.json's 'verifiers' field is a {type(verifiers).__name__}, "
                "not a list -- EKW verifier.json always stores verifiers as a JSON array, "
                "never a dict keyed by name"
            ),
        )
    return verifiers, data.get("task_id"), data.get("config", {}), None


def _extract_file_paths(source):
    """`source` (the verifier's own "source" object, NOT just source.file) turns out to have at
    least 7 distinct shapes across the real 274-task population -- confirmed by a full scan
    (turing-context-49, cross-checked against this module's own narrower first-pass scan which
    only caught the list-of-files case). Handles all of them, returns every path found in order,
    and NEVER crashes on an entry that doesn't match a known shape -- it's skipped, not fatal.

    Shapes handled:
      1. source.file = {"arguments": {"path": "..."}}                (majority shape)
      2. source.file = {"arguments": {"paths": ["...", "..."]}}       (extract_many, 26 verifiers:
         task_108/130/133/272/462/578)
      3. source.file = [{"arguments": {"path": "..."}}, ...]          (cross-file verifier, 5+
         tasks: task_270/326/536/569/600)
      4. source.files = ["...", "..."]                                (plural "files" key
         directly on source, not "file" -- task_34 v23)
      5. source.file = {"path": "..."}  (no "arguments" wrapper at all -- task_536)
      6. source.file = {"type": "directory", "command": "list_files", "arguments": {"path":
         "output/"}}  (a directory reference, not a specific file -- task_605 v17; still
         extracted as a path, callers treat it as a directory-shaped path, not a bug)
      7. task_FIN-177's foreign schema: paths live at metadata.source.file.paths, not here at
         all -- this function is never called for that schema; see load_ekw_criteria's
         alt-schema branch instead.
    """
    if not isinstance(source, dict):
        return []
    paths = []

    # Shape 4: plural "files" key directly on source (not nested under "file")
    files_list = source.get("files")
    if isinstance(files_list, list):
        for f in files_list:
            if isinstance(f, str) and f:
                paths.append(f)
            elif isinstance(f, dict):
                paths.extend(_extract_one_file_entry(f))

    source_file = source.get("file")
    if isinstance(source_file, dict):
        candidates = [source_file]
    elif isinstance(source_file, list):
        candidates = source_file
    else:
        candidates = []
    for entry in candidates:
        paths.extend(_extract_one_file_entry(entry))
    return paths


def _extract_commands(source):
    """Every distinct `source.file.command` value for this verifier's file entries, e.g.
    "extract_text", "extract_formulas", "extract_xlsx", "list_files", "read_file". Added because
    a real, corpus-scale finding (rubric_text_lint.py's port, 2026-09-14) showed the command
    matters: 99.6% of EKW file-reads use "extract_text" (rendered/cached text only, no formulas
    -- `rl_world_verifiers/sources/xlsx.py` confirmed to load with `data_only=True`), but authors
    can opt into "extract_formulas"/"extract_xlsx" instead, which DO see live formulas. A check
    that assumes every EKW verifier is extraction-blind to formulas (as `load_ekw_criteria`'s
    `files` list alone would suggest) produces false positives on that minority. Mirrors
    `_extract_file_paths`'s shape-handling exactly, but returns commands, deduped, in first-seen
    order; empty list if the source has no recognizable file entry or is the alt-schema/
    directory-only case."""
    if not isinstance(source, dict):
        return []
    commands = []

    def _add(entry):
        if isinstance(entry, dict):
            c = entry.get("command")
            if isinstance(c, str) and c and c not in commands:
                commands.append(c)

    files_list = source.get("files")
    if isinstance(files_list, list):
        for f in files_list:
            _add(f)
    source_file = source.get("file")
    if isinstance(source_file, dict):
        _add(source_file)
    elif isinstance(source_file, list):
        for entry in source_file:
            _add(entry)
    return commands


def _extract_one_file_entry(entry):
    """One file-spec object -> list of paths (usually 1, sometimes many for "paths" plural,
    sometimes 0 if the shape isn't recognized).

    Shape 6, `type: "directory"` (task_605 v17, `command: "list_files"`, `arguments.path:
    "output/"`): a directory LISTING, not a graded file. Returning it as a path made
    deliverable_filename_check.py look for a deliverable literally named "output" in
    instruction.md, and would make the formula/tab checks try to resolve "output" as a file
    under solution/ -- both wrong (found via cross-verification against an independent
    normaliser, turing-context-49, 2026-09-14). Directory entries yield no file paths.
    """
    if not isinstance(entry, dict):
        return []
    if entry.get("type") == "directory":
        return []
    args = entry.get("arguments")
    if isinstance(args, dict):
        p = args.get("path")
        if p:
            return [p]
        ps = args.get("paths")
        if isinstance(ps, list):
            return [x for x in ps if isinstance(x, str) and x]
    # Shape 5: no "arguments" wrapper, path sits directly on the entry
    p = entry.get("path")
    if isinstance(p, str) and p:
        return [p]
    ps = entry.get("paths")
    if isinstance(ps, list):
        return [x for x in ps if isinstance(x, str) and x]
    return []


def load_ekw_criteria(task_dir):
    """EKW equivalent of formula_health_check.py's load_judge_criteria(task_dir): every
    verifier in tests/verifier.json, flattened to the same {group, name, description, weight,
    type, files} shape so downstream code (rubric_schema_check.py, duplicate_criterion_check.py,
    judge_criterion_name_duplicate_check.py, etc) can consume EKW and SVC-PC tasks identically
    once a caller branches on which file exists.

    Field mapping, each confirmed against a real verifier.json (see module docstring):
        group       -> the verifier's own "name" (v1, v2, ...) -- EKW has no judge.toml-style
                       subdirectory grouping, so each verifier is its own group for provenance
        name        -> the verifier's own "name" (v1, v2, ...) -- EKW has no separate
                       human-readable criterion name distinct from its group id
        description -> assertion.rubric.prompt (the free-text grading criteria)
        weight      -> metadata.weight
        type        -> assertion.type ("rubric" in every verifier seen; SVC-PC's judge.toml
                       "binary"/etc type has no direct EKW equivalent, so this is the closest
                       available signal, not a semantic match)
        files       -> every path in source.file (usually one, but source.file can itself be a
                       list for a cross-file verifier -- see _extract_file_paths)
        commands    -> every source.file.command seen (e.g. "extract_text", "extract_formulas");
                       see _extract_commands -- matters because most EKW file-reads are
                       extract_text (rendered/cached values only, no live formulas)
    """
    out = []
    verifiers, _task_id, _config, parse_error = load_ekw_verifiers_raw(task_dir)
    if parse_error:
        out.append(
            {
                "group": "verifier.json",
                "name": "__parse_error__",
                "description": parse_error,
                "weight": None,
                "type": None,
                "files": [],
                "commands": [],
            }
        )
        return out
    for v in verifiers:
        if not isinstance(v, dict):
            out.append(
                {
                    "group": "verifier.json",
                    "name": "__parse_error__",
                    "description": f"a 'verifiers' array entry is a {type(v).__name__}, not an object",
                    "weight": None,
                    "type": None,
                    "files": [],
                    "commands": [],
                    "must_pass": False,
                    "why_justification": None,
                    "how_justification": None,
                    "importance": None,
                }
            )
            continue
        vname = v.get("name", "__unnamed__")
        metadata = v.get("metadata") if isinstance(v.get("metadata"), dict) else {}

        if _is_alt_schema_verifier(v):
            out.append(
                {
                    "group": vname,
                    "name": vname,
                    "description": v.get("criterion", ""),
                    "weight": metadata.get("weight"),
                    "type": v.get("check_type"),
                    "files": _extract_alt_schema_files(v),
                    "commands": [],
                    "must_pass": bool(metadata.get("must_pass"))
                    or bool(_MUST_PASS_RE.search(str(v.get("criterion") or ""))),
                    "why_justification": metadata.get("why_justification"),
                    "how_justification": metadata.get("how_justification"),
                    "importance": metadata.get("importance"),
                }
            )
            continue

        source = v.get("source") if isinstance(v.get("source"), dict) else {}
        assertion = v.get("assertion") if isinstance(v.get("assertion"), dict) else {}
        rubric = (
            assertion.get("rubric") if isinstance(assertion.get("rubric"), dict) else {}
        )
        description = _describe_verifier(assertion, rubric, metadata)

        out.append(
            {
                "group": vname,
                "name": vname,
                "description": description,
                "weight": metadata.get("weight"),
                "type": assertion.get("type"),
                "files": _extract_file_paths(source),
                "commands": _extract_commands(source),
                # Added 2026-09-14 for semantic_consistency_check.py, additively, the same way
                # `commands` was added for extraction_groundedness_check.py: metadata.must_pass
                # is native and authoritative when present, but not confirmed set on every real
                # verifier.json, so the text marker in the rubric prompt is checked too, exactly
                # mirroring certification_gate_check.py's own EKW fallback
                # (`bool(md.get("must_pass")) or bool(MUST_PASS_RE.search(prompt))`).
                "must_pass": bool(metadata.get("must_pass"))
                or bool(_MUST_PASS_RE.search(description)),
                "why_justification": metadata.get("why_justification"),
                "how_justification": metadata.get("how_justification"),
                "importance": metadata.get("importance"),
            }
        )
    return out


def _describe_verifier(assertion, rubric, metadata):
    """The free-text description every downstream check expects. Most verifiers are
    assertion.type == "rubric" and carry it directly in rubric.prompt. A real subset (4 of 274
    confirmed, task_15) are assertion.type == "deterministic" instead -- a JSONPath equality/
    tolerance check against a literal expected value, with NO rubric.prompt text at all
    (confirmed: {"type": "deterministic", "expected": "EAST", "deterministic": {"path":
    "$.site_id", "comparison": "equals"}}, no "rubric" key present). For those, synthesize a
    description matching pipeline/tools/to_rewardkit.py's own `_deterministic_description()`
    exactly (why_justification, then "Check: <how_justification>", then "Verify (via
    <comparison> at <path>): <expected>", space-joined) -- turing-context-49 cross-verified this
    against an independent normaliser and flagged that this module's first version used a
    different, shorter composition; matching the converter's own text means rubric_text_lint
    sees identical wording whether a task was read natively or through the rewardkit conversion
    path. Not byte-identical to that function (skips its `_rewrite_instruction_paths` workspace-
    path rewrite, which only matters for the converted /app/ layout, not this read-only parser).
    """
    prompt = rubric.get("prompt")
    if prompt:
        return prompt
    if assertion.get("type") == "deterministic":
        det = (
            assertion.get("deterministic")
            if isinstance(assertion.get("deterministic"), dict)
            else {}
        )
        parts = []
        why = metadata.get("why_justification")
        if why:
            parts.append(str(why).strip())
        how = metadata.get("how_justification")
        if how:
            parts.append(f"Check: {str(how).strip()}")
        comparison = det.get("comparison")
        expected = assertion.get("expected")
        path = det.get("path")
        if comparison and expected is not None:
            where = f" at {path}" if path else ""
            parts.append(f"Verify (via {comparison}{where}): {expected}")
        return " ".join(parts).strip()
    # Unrecognized assertion type with no rubric text -- fall back to how_justification if any,
    # rather than silently returning an empty string that reads as "blank rubric."
    return metadata.get("how_justification", "") or ""


def load_ekw_files(task_dir):
    """EKW equivalent of deliverable_filename_check.py's load_judge_files(task_dir): every
    graded file path named anywhere in tests/verifier.json, grouped per-verifier since EKW has
    no judge.toml-style file group.

    Returns (sources, parse_errors), matching load_judge_files' exact return shape:
        sources      -- list of {"group": str, "path": str, "files": [str, ...]}
                         "path" here is always "tests/verifier.json" (relative to task_dir),
                         since unlike SVC-PC there is only ever one config file per task, not
                         one per deliverables_NN subdirectory
        parse_errors -- list of {"group": str, "path": str, "error": str}
    """
    sources = []
    parse_errors = []
    verifiers, _task_id, _config, parse_error = load_ekw_verifiers_raw(task_dir)
    rel_path = "tests/verifier.json"
    if parse_error:
        parse_errors.append(
            {"group": "verifier.json", "path": rel_path, "error": parse_error}
        )
        return sources, parse_errors
    if not verifiers and not (task_dir / "tests" / "verifier.json").is_file():
        # no verifier.json at all for this task -- not an error, just not an EKW-shaped task
        return sources, parse_errors
    for v in verifiers:
        if not isinstance(v, dict):
            parse_errors.append(
                {
                    "group": "verifier.json",
                    "path": rel_path,
                    "error": f"a 'verifiers' array entry is a {type(v).__name__}, not an object",
                }
            )
            continue
        vname = v.get("name", "__unnamed__")
        if _is_alt_schema_verifier(v):
            paths = _extract_alt_schema_files(v)
        else:
            source = v.get("source") if isinstance(v.get("source"), dict) else {}
            paths = _extract_file_paths(source)
        sources.append(
            {
                "group": vname,
                "path": rel_path,
                "files": paths,
            }
        )
    return sources, parse_errors


def _is_alt_schema_verifier(v):
    """One task (task_FIN-177, 1 of 274) uses a wholesale different verifier object schema:
    no top-level "source"/"assertion" keys at all -- instead "criterion" (the rubric text),
    "check_type", "applies_to", "grounding", "how_to_verify", "pass_condition", with the file
    path(s) nested under metadata.source.file.paths instead of a top-level source.file. "criterion"
    as a key is the reliable discriminator: it never appears on a majority-schema verifier (which
    has "assertion" instead), and every alt-schema verifier confirmed on task_FIN-177 has it.
    """
    return isinstance(v, dict) and isinstance(v.get("criterion"), str)


def _extract_alt_schema_files(v):
    """File paths for one alt-schema verifier (see _is_alt_schema_verifier): they live at
    metadata.source.file.paths (a list) or metadata.source.file.path (a single string),
    confirmed on task_FIN-177."""
    metadata = v.get("metadata") if isinstance(v.get("metadata"), dict) else {}
    alt_source = (
        metadata.get("source") if isinstance(metadata.get("source"), dict) else {}
    )
    alt_file = (
        alt_source.get("file") if isinstance(alt_source.get("file"), dict) else {}
    )
    paths = alt_file.get("paths")
    if isinstance(paths, list):
        return [p for p in paths if isinstance(p, str) and p]
    p = alt_file.get("path")
    return [p] if isinstance(p, str) and p else []


def has_ekw_config(task_dir):
    """True if this task uses EKW's verifier.json shape rather than SVC-PC's judge.toml shape.
    Callers should check this (or the inverse, whether tests/deliverables_*/judge.toml exists)
    to decide which loader to call -- this module never guesses silently."""
    return (Path(task_dir) / "tests" / "verifier.json").is_file()


if __name__ == "__main__":
    # Standalone self-test: point at a real task dir and print what this module extracts,
    # for a human to eyeball against the actual verifier.json before anything depends on it.
    import argparse
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(
        description="Self-test ekw_verifier_json.py against a real task dir"
    )
    p.add_argument("task_dir", type=Path)
    args = p.parse_args()

    print(f"has_ekw_config: {has_ekw_config(args.task_dir)}")
    criteria = load_ekw_criteria(args.task_dir)
    print(f"\nload_ekw_criteria: {len(criteria)} entries")
    for c in criteria[:3]:
        print(" ", json.dumps(c, indent=2)[:300])
    weights = [c["weight"] for c in criteria if isinstance(c["weight"], (int, float))]
    print(
        f"  weight sum: {sum(weights) if weights else 'n/a'} across {len(weights)} numeric weights"
    )

    sources, errs = load_ekw_files(args.task_dir)
    print(f"\nload_ekw_files: {len(sources)} sources, {len(errs)} parse errors")
    for s in sources[:3]:
        print(" ", s)
    for e in errs:
        print("  ERROR:", e)
