#!/usr/bin/env python3
r"""Source-truncation check: did the verifier's own source extraction silently cut off
document content before any assertion (deterministic or rubric) ever saw it?

**Provenance.** This is "S-6" from Pietro Carra's QC review of the Perplexity delivery of this
same EKW corpus (`ekw_structural_review.md`, shared 2026-09-15): EKW's `SourceRegistry` caps any
extracted file-content string at `max_content_chars` characters (default 90000) with NO marker,
NO warning, NO error -- the assertion that reads `source_output.text` has no way to tell "this is
the whole document" from "this is the first 90000 characters of a longer document". His method,
reused here: run each source's real extraction command against the GOLD content, and flag any
output whose length is EXACTLY `max_content_chars` -- an exact-boundary match is the tell that
content was cut, not that the source happened to end there naturally (a document that legitimately
ends at 90000 characters on the nose is astronomically unlikely; one that got cut there is not).
His numbers: 365 individual truncated source reads across 25 of 223 tasks in his corpus.

**Dual format, same convention as `verifier_executability_check.py`.** Format is auto-detected
per task (`_detect_format`, reused verbatim from that script) and every sub-check reports its own
`not_applicable` when the underlying mechanism genuinely does not exist for a format, rather than
crashing or silently skipping.

## EKW branch: the mechanism is confirmed, mechanically, three independent ways

1. **Read every `sources/*.py` in a real vendored `verifier_lib`** (`task_1`, this session):
   `docx.py`, `xlsx.py`, `pdf.py`, `pptx.py`, `text.py`, `csv.py`, `md.py` each thread
   `context.max_content_chars` into their extraction function and return the result sliced with
   `[:limit]` (or via an `append_limited`/early-return pattern that has the same effect) into a
   `text: str` field on a `StrictModel` output. `json.py` (`RootModel`, arbitrary parsed JSON) and
   `filesystem.py` (`exists`/`is_file`/`is_directory` booleans, confirmed by reading the file this
   session -- no text field at all) never reference `max_content_chars` -- their outputs are
   structured data, not a capped text blob, so they are excluded from this check entirely rather
   than attempted and silently ignored. `response.extract_final_message` DOES cap its `text` at
   `max_content_chars` (`message[:context.max_content_chars]` in `response.py`) but reads from
   `context.agent_logs_dir / "trajectory.json"`, which a gold replay does not populate (no real
   agent trajectory exists to replay) -- this is the same documented replay-harness limitation
   `verifier_executability_check.py`'s module docstring names for the same source type, so this
   script reports it as `skipped_no_gold_trajectory` per source rather than pretending to check it.
   Confirmed moot in practice: zero `response`-type sources exist anywhere in the 274-task corpus
   (checked this session by scanning every `verifier.json`).

2. **`max_content_chars` is NOT per-task configurable, checked three ways, not assumed.**
   `models.py`'s `Config` (the only verifier.json-authored config surface, `StrictModel` with
   `extra="forbid"`) has exactly three fields -- `models`, `temperature`, `reasoning_effort` -- no
   `max_content_chars` field exists to author. Every vendored `sources/registry.py` in the corpus
   (180/274 tasks have one; see point 3) defaults `SourceRegistry.__init__`'s `max_content_chars`
   parameter to `90000`, and grepping all 180 for that default found no other value. The real
   entrypoint, `verifier_runtime.py`, reads `MAX_CONTENT_CHARS = int(os.environ.get(
   "VERIFIER_MAX_CONTENT", "90000"))` -- an operator/environment override point exists in
   principle, but it lives outside every task's own shipped files (no task sets this env var
   itself), so every task in this corpus grades under the same 90000 unless a human running the
   harness overrides it out-of-band. Zero `verifier.json` files anywhere in the corpus contain the
   string `max_content_chars` (checked this session). Conclusion, stated plainly rather than
   over-engineered: this script hardcodes `EKW_MAX_CONTENT_CHARS = 90000` and does NOT read a
   per-task override from verifier.json, because there is nothing there to read.

3. **The corpus is NOT structurally uniform -- 94/274 tasks have no importable `verifier_lib` at
   all**, the same finding `verifier_executability_check.py`'s module docstring reports for a
   related reason (its missing-entrypoint check). Confirmed directly this session: `task_6`,
   `task_7`, `task_8` have no `tests/verifier_lib/` directory whatsoever; `task_9` has one, but
   flat (`compare.py`, `csv.py`, `docx.py` directly under `verifier_lib/`, no `sources/` package),
   so `from verifier_lib.sources.registry import SourceRegistry` raises `ModuleNotFoundError` for
   it. This script imports each task's OWN vendored `verifier_lib` in isolation (`sys.path.insert`
   + purge `sys.modules` entries starting with `verifier_lib`, a `finally` that removes the path --
   the exact pattern `verifier_executability_check.py`'s `_gold_replay` uses, reused not
   re-derived) and reports `no_verifier_lib` / `import_error` as a distinct, honest outcome when a
   task's own package cannot supply `SourceRegistry` at all -- never a crash, never silently
   skipped.

**Method, concretely.** For each EKW task: copy `solution/golden_outputs/*` into a scratch
`output/` dir (identical staging to `verifier_executability_check.py`'s `_gold_replay`), build a
`SourceRegistry(workspace_dir=scratch, agent_logs_dir=scratch/"agent_logs",
max_content_chars=90000)`, and for every verifier's `source` declaration in `tests/verifier.json`
whose namespace is in `EKW_TRUNCATABLE_NAMESPACES` call `registry.run(source)` directly (no LLM
judge involved anywhere -- this check only exercises the source-extraction step, never the
assertion or rubric layer). Identical `(source_name, arguments)` calls within one task are
computed once and reused (many verifiers in this corpus share one source file -- `task_1`'s 20
verifiers reduce to 2 unique source calls, confirmed this session) but every VERIFIER that binds
to a call at the cap is still reported as its own finding, matching Pietro's per-verifier-read
counting method rather than deduping the count away. A source whose extracted `text` length is
exactly `max_content_chars` is a `candidate` finding (status vocabulary from
`test_coverage_absence_check.py`'s docstring: strong evidence, not proof by construction -- a real
document could coincidentally be exactly 90000 characters, though this is vanishingly unlikely).
A `registry.run()` exception (unknown source, bad argument, or the resolved file genuinely missing
from golden_outputs) is reported as its own `source_error` finding, kept structurally separate
from truncation candidates so the two are never conflated in the summary counts.

## SVC-PC branch: investigated honestly, the analogous mechanism does NOT exist

Checked `harbor-rewardkit` 0.2.0's `rewardkit/judges.py` directly (installed at
`...\Python312\Lib\site-packages\rewardkit\judges.py`), specifically `_read_file_blocks`,
`_convert_with_markitdown`, and the `_MAX_FILE_SIZE = 1024 * 1024` constant near line 145, per the
brief's explicit pointer -- read the code, did not guess from the constant's name:

- `_convert_with_markitdown` (line 160) hands the WHOLE file to `MarkItDown().convert(...)
  .text_content` with no length cap anywhere in that call or its return.
- `_read_file_blocks` (line 171) checks `size > _MAX_FILE_SIZE` BEFORE any content is read
  (line 180) and, if the file exceeds 1MB, returns `[{"type": "text", "text": f"--- {label} ---
  \n[skipped: file too large]"}]` -- the file's content is not read at all, and the judge is
  handed an explicit `[skipped: file too large]` marker in its place. This is a hard, DISCLOSED
  reject keyed on file SIZE, not a silent cut of CONTENT after reading it -- the opposite defect
  shape from EKW's S-6, not a variant of it. Grepped the whole `rewardkit` package for
  `truncat|max_chars|char_limit`-shaped code: the only truncation function in the entire package
  is `trajectory.py`'s `_truncate(text, limit, model)`, used exclusively for formatting AGENT
  TRAJECTORY steps (tool calls, messages, reasoning) for a transcript judge -- never document/file
  content -- and even that truncation appends `"..."` and logs "Trajectory truncated to N tokens",
  so it is disclosed too, not silent. Confirmed by reading `trajectory.py` directly, not inferred
  from the brief's warning that it "does NOT apply here."

**Conclusion: this sub-check reports `not_applicable` for every SVC-PC task**, with this reasoning
as the stated `detail`, rather than being forced to fit a shape that does not exist here. The
`_MAX_FILE_SIZE` reject IS a real, distinct, worth-recording defect shape -- a judge criterion can
be silently ungradeable in practice if a referenced deliverable exceeds 1MB and the judge never
sees ANY of its content, marker or not, if nobody reads the marker -- so this script records it as
a SEPARATE finding type, `oversized_file_marked_skip`, cheap to compute alongside the main check
(no rewardkit invocation needed, just `os.stat` against files a task's own `judge.toml`s actually
reference) but explicitly not folded into `truncation candidate` counts anywhere in this report.

**2026-09-16 fix: this sub-check only ever resolved a referenced file against
`solution/files/`, the same blind spot found independently the same night in
`verifier_executability_check.py` and `formula_health_check.py`'s `resolve_graded_files`.** A
`judge.toml` `files=[...]` entry is frequently a source/input file the solver reads from
`environment/initial_workspace/`, not a deliverable under `solution/files/` -- confirmed real
against the live 600-task corpus, not assumed from the other two checks' findings alone: of
1369 referenced (task-deduped) file entries corpus-wide, 545 were not found under
`solution/files/`, and of those, 543 (99.6%) resolve to a real file under
`environment/initial_workspace/` (2 genuinely absent, both SVC-PC-10-0-0's own rewardkit
`judge.mode` config defect, a different check's territory). Of those 543 previously-unchecked
files, several genuinely exceed `SVC_PC_MAX_FILE_SIZE` and were invisible to
`oversized_file_marked_skip` before this fix -- files rewardkit's own `_MAX_FILE_SIZE` hard
reject would actually skip at grading time, exactly the defect shape this sub-check exists to
surface. Fixed the same way as the other two: a same-named file under
`environment/initial_workspace/` (recursive, see `_environment_basenames`) is now tried as a
fallback whenever `solution/files/` misses; each oversized finding now records which directory
it resolved from (`source: "solution/files"` or `"environment/initial_workspace"`), and the
result also reports `n_resolved_solution`/`n_resolved_environment`/`n_unresolved` so a reader
can see the resolution split without re-deriving it. Full 600-task corpus, both states actually
run, not projected: before this fix, 1 file/1 task (SVC-PC-4-0-0, the pre-fix state the
paragraph above used to cite). After: 24 files across 19 tasks (SVC-PC-4-0-0 still caught,
unchanged, plus 18 more tasks/23 more files newly surfaced from environment/) -- a real,
previously-silent gap, not a cosmetic change.

## Known traps already hit tonight, not rediscovered here

- **Not `bash -n`.** No test.sh parsing happens in this script, so this specific trap does not
  apply, but the general lesson does: every claim above about `max_content_chars` and about
  rewardkit's file-reading path was confirmed by reading the actual shipped code and, where
  practical, running it (see Validation) -- not assumed from a name or a docstring.
- **`rewardkit.runner._load_toml` reads TOML with implicit `.read_text()` encoding**, which
  defaults to cp1252 on Windows and throws `UnicodeDecodeError` on UTF-8 multi-byte characters
  common in these criteria (em dashes, smart quotes). This script never calls into
  `rewardkit.runner` at all (the `oversized_file_marked_skip` check only needs `os.stat` and a
  `judge.toml` file list, no rewardkit config loading), so the monkey-patch `_gold_replay_svc_pc`
  uses is not needed here -- but every `judge.toml` this script reads itself is opened in BINARY
  mode via stdlib `tomllib.load(open(path, "rb"))`, never `.read_text()`, for the same reason.
- **`ProcessPoolExecutor` on Windows uses spawn** (fresh interpreter per worker), which gives
  per-task `verifier_lib` import isolation for free, the same as `verifier_executability_check.py`
  relies on.

## Validation (RAN this session, real corpora, not projected)

`python source_truncation_check.py --all --root C:\ekwqc\_merged274\files --jobs 8`: see the
printed summary this script emits; numbers are also in this session's own handoff, not repeated
here to avoid the two copies drifting.

`python source_truncation_check.py --all --root
C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready --id-prefix SVC-PC-1- --jobs 8` (a 40+ task
slice, well above the 20-30 minimum) plus a full-corpus `--all` run for the (cheap, no rewardkit
needed) `oversized_file_marked_skip` count: see the same summary output.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import tempfile
import tomllib
import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ekw_verifier_json  # noqa: E402  (sibling module in this folder)

# ---------------------------------------------------------------------------
# Shared helpers, reused verbatim from verifier_executability_check.py
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
    """ "ekw" if tests/verifier.json exists, "svc_pc" if any tests/**/judge.toml exists,
    "unknown" otherwise (reported, not raised -- a format this script doesn't recognize is a
    finding, not a crash)."""
    if (task_dir / "tests" / "verifier.json").is_file():
        return "ekw"
    if any(task_dir.glob("tests/**/judge.toml")):
        return "svc_pc"
    return "unknown"


# ---------------------------------------------------------------------------
# EKW branch
# ---------------------------------------------------------------------------

# Not per-task configurable -- see module docstring point 2. Confirmed universal across the
# corpus: zero verifier.json files author it, every vendored registry.py defaults to it.
EKW_MAX_CONTENT_CHARS = 90000

# Namespaces whose extract command output is a max_content_chars-capped `text: str` field.
# Confirmed by reading every sources/*.py in a real vendored verifier_lib (see module docstring
# point 1). "response" is deliberately excluded here even though it also caps at
# max_content_chars -- it reads agent_logs, which gold replay cannot populate -- and is handled
# as its own skip reason below rather than silently omitted from this set.
EKW_TRUNCATABLE_NAMESPACES = {"docx", "xlsx", "pdf", "pptx", "text", "csv", "md"}


def _stage_gold_output(task_dir: Path, scratch: Path) -> str | None:
    """Copies solution/golden_outputs/* into scratch/output, same staging
    verifier_executability_check.py's _gold_replay uses. Returns an error string, or None on
    success."""
    golden_dir = task_dir / "solution" / "golden_outputs"
    if not golden_dir.is_dir():
        return f"no solution/golden_outputs directory: {golden_dir}"
    out_dir = scratch / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    for item in golden_dir.iterdir():
        dest = out_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    return None


def _source_namespace(source: Any) -> str:
    """Returns the dotted-namespace prefix ("xlsx", "docx", "response", ...) for a validated
    Source model, without needing to import verifier_lib.models.Source by name (source is a
    task's own vendored pydantic model instance, not this script's)."""
    if source.type == "file":
        return source.file.type
    return "response"


def _check_ekw_truncation(task_dir: Path) -> dict[str, Any]:
    tests_dir = task_dir / "tests"
    verifier_json = tests_dir / "verifier.json"
    # Both spellings are real (47 of 79 shipped v7 tasks use `__verifier_lib`, 28 use
    # `verifier_lib`). Hardcoding the single-underscore name here made this check report
    # `no_verifier_lib` -> `error` on every double-underscore task -- i.e. it has never actually
    # run on 59% of the corpus, on a defect class (extraction truncation) that hit 4 of 30 tasks
    # in the 2026-09-22 session. See ekw_verifier_json.VERIFIER_LIB_DIR_NAMES.
    lib_dir = ekw_verifier_json.verifier_lib_dir(task_dir)
    lib_module = ekw_verifier_json.verifier_lib_module_name(task_dir)

    if not verifier_json.is_file():
        return {
            "outcome": "no_verifier_json",
            "ok": False,
            "detail": str(verifier_json),
        }
    if lib_dir is None:
        return {
            "outcome": "no_verifier_lib",
            "ok": False,
            "detail": f"neither of {ekw_verifier_json.VERIFIER_LIB_DIR_NAMES} under {tests_dir}",
        }

    # Import THIS task's own vendored verifier_lib in isolation. Safe without extra sys.modules
    # bookkeeping under ProcessPoolExecutor spawn (Windows: fresh interpreter per task); the
    # explicit purge also makes repeated imports safe under --jobs 1. Exact pattern reused from
    # verifier_executability_check.py's _gold_replay, not re-derived.
    sys.path.insert(0, str(tests_dir))
    try:
        for mod_name in list(sys.modules):
            if mod_name == lib_module or mod_name.startswith(lib_module + "."):
                del sys.modules[mod_name]

        try:
            # Imported by the task's OWN package name -- `__verifier_lib` or `verifier_lib` --
            # exactly as that task's verifier_runtime imports it. importlib rather than a static
            # `from verifier_lib...` so both spellings work through one code path.
            _models = importlib.import_module(f"{lib_module}.models")
            _registry = importlib.import_module(f"{lib_module}.sources.registry")
            VerifierSpec = _models.VerifierSpec  # type: ignore
            source_output_to_data = _models.source_output_to_data  # type: ignore
            SourceRegistry = _registry.SourceRegistry  # type: ignore
        except Exception as exc:
            return {
                "outcome": "import_error",
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}",
            }

        try:
            spec = VerifierSpec.model_validate_json(
                verifier_json.read_text(encoding="utf-8")
            )
        except Exception as exc:
            return {
                "outcome": "verifier_json_invalid",
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}",
            }

        with tempfile.TemporaryDirectory(prefix="trunc_gold_") as scratch_str:
            scratch = Path(scratch_str)
            stage_err = _stage_gold_output(task_dir, scratch)
            if stage_err:
                return {
                    "outcome": "no_golden_outputs",
                    "ok": False,
                    "detail": stage_err,
                }

            agent_logs_dir = scratch / "agent_logs"
            agent_logs_dir.mkdir(parents=True, exist_ok=True)

            registry = SourceRegistry(
                workspace_dir=scratch,
                agent_logs_dir=agent_logs_dir,
                max_content_chars=EKW_MAX_CONTENT_CHARS,
            )

            candidates: list[dict[str, Any]] = []
            source_errors: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            n_checked_calls = 0
            # cache: (source_name, sorted-arguments-json) -> length, or a sentinel error string
            cache: dict[str, Any] = {}

            for definition in spec.verifiers:
                source = definition.source
                namespace = _source_namespace(source)

                if namespace == "response":
                    skipped.append(
                        {
                            "verifier": definition.name,
                            "source": source.source_name,
                            "reason": "skipped_no_gold_trajectory: response.* sources read "
                            "agent_logs_dir/trajectory.json, which a gold replay does not "
                            "populate (no real agent trajectory exists to replay) -- same "
                            "documented limitation as verifier_executability_check.py",
                        }
                    )
                    continue
                if namespace not in EKW_TRUNCATABLE_NAMESPACES:
                    # json.*/filesystem.* (structured, non-text output) or an unrecognized/
                    # malformed namespace (e.g. an authoring typo). Not this check's job to
                    # diagnose an unknown source -- verifier_executability_check.py's gold
                    # replay already catches those as a reward<1.0 / exception outcome.
                    skipped.append(
                        {
                            "verifier": definition.name,
                            "source": source.source_name,
                            "reason": f"not a max_content_chars-capped text source "
                            f"(namespace={namespace!r})",
                        }
                    )
                    continue

                cache_key = (
                    source.source_name
                    + "|"
                    + json.dumps(source.arguments, sort_keys=True, default=str)
                )
                n_checked_calls += 1
                if cache_key not in cache:
                    try:
                        output = registry.run(source)
                        data = source_output_to_data(output)
                        if isinstance(data, dict) and isinstance(data.get("text"), str):
                            cache[cache_key] = ("ok", len(data["text"]))
                        else:
                            cache[cache_key] = (
                                "unexpected_output_shape",
                                f"expected a dict with a string 'text' field, got "
                                f"{type(data).__name__}",
                            )
                    except Exception as exc:
                        cache[cache_key] = (
                            "error",
                            f"{type(exc).__name__}: {exc}",
                        )

                kind, payload = cache[cache_key]
                path = source.arguments.get("path")
                if kind == "ok":
                    length = payload
                    if length == EKW_MAX_CONTENT_CHARS:
                        candidates.append(
                            {
                                "verifier": definition.name,
                                "source": source.source_name,
                                "path": path,
                                "length": length,
                                "max_content_chars": EKW_MAX_CONTENT_CHARS,
                            }
                        )
                else:
                    source_errors.append(
                        {
                            "verifier": definition.name,
                            "source": source.source_name,
                            "path": path,
                            "error_kind": kind,
                            "detail": payload,
                        }
                    )

        return {
            "outcome": "checked",
            "ok": True,
            "n_source_calls_checked": n_checked_calls,
            "n_unique_source_calls": len(cache),
            "n_candidates": len(candidates),
            "candidates": candidates,
            "n_source_errors": len(source_errors),
            "source_errors": source_errors,
            "n_skipped": len(skipped),
            "skipped": skipped,
        }
    finally:
        try:
            sys.path.remove(str(tests_dir))
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# SVC-PC branch
# ---------------------------------------------------------------------------

# rewardkit.judges._MAX_FILE_SIZE, confirmed by reading judges.py directly this session (see
# module docstring). A hard, disclosed size-based reject, NOT a silent content-length truncation
# -- kept as a separate finding type, never folded into "truncation candidate" counts.
SVC_PC_MAX_FILE_SIZE = 1024 * 1024


def _svc_pc_referenced_files(tests_dir: Path) -> tuple[set[str], list[str]]:
    """Returns (basenames referenced by any judge.toml's [judge].files or
    [[criterion]].files, parse errors encountered). judge.toml is always opened in binary mode
    via stdlib tomllib -- never .read_text() -- per the cp1252-on-Windows trap documented in
    this script's module docstring and in verifier_executability_check.py."""
    referenced: set[str] = set()
    errors: list[str] = []
    for toml_path in sorted(tests_dir.glob("**/judge.toml")):
        try:
            with open(toml_path, "rb") as f:
                cfg = tomllib.load(f)
        except Exception as exc:
            errors.append(f"{toml_path.name}: {type(exc).__name__}: {exc}")
            continue
        file_refs = list(cfg.get("judge", {}).get("files", []))
        for crit in cfg.get("criterion", []):
            file_refs.extend(crit.get("files", []))
        for f in file_refs:
            referenced.add(Path(f).name)
    return referenced, errors


def _environment_basenames(task_dir: Path) -> dict[str, Path]:
    """Basename -> Path for every file under environment/initial_workspace/ (recursive, since
    some tasks nest files under a build-time subtree). 2026-09-16 fix, same shape as
    verifier_executability_check.py's _environment_basenames and formula_health_check.py's
    resolve_graded_files: a judge.toml files=[...] entry is not always a solver-produced
    deliverable under solution/files/ -- most are source/input files the solver reads from
    environment/initial_workspace/, included so the judge has them as grading context. Confirmed
    real against the live 600-task corpus before shipping this fix, not assumed from the other
    two checks' findings alone: of 545 referenced-but-not-in-solution/files/ entries, 543
    resolve to a real file under environment/initial_workspace/, and 23 of those 543 genuinely
    exceed SVC_PC_MAX_FILE_SIZE -- files rewardkit's own _MAX_FILE_SIZE hard-reject would skip
    at grading time, invisible to this check's oversized_file_marked_skip finding until now.
    """
    env_dir = task_dir / "environment" / "initial_workspace"
    if not env_dir.is_dir():
        return {}
    out: dict[str, Path] = {}
    for p in env_dir.rglob("*"):
        if p.is_file():
            out.setdefault(p.name, p)
    return out


def _check_svc_pc_truncation(task_dir: Path) -> dict[str, Any]:
    tests_dir = task_dir / "tests"
    solution_files_dir = task_dir / "solution" / "files"

    truncation = {
        "outcome": "not_applicable",
        "ok": True,
        "detail": "harbor-rewardkit 0.2.0's judges.py has no silent content-length truncation "
        "for file/document content: _convert_with_markitdown hands the whole file to markitdown "
        "with no cap, and the only size-based behavior (_MAX_FILE_SIZE=1MB in _read_file_blocks) "
        "is a hard reject BEFORE reading content, with an explicit '[skipped: file too large]' "
        "marker -- disclosed, not silent, and keyed on file size not content length. The only "
        "truncation function in the package (trajectory.py's _truncate) formats agent "
        "trajectories for a transcript judge, never document/file content, and itself appends "
        "'...' and logs a message -- also disclosed. See module docstring for the full read. "
        "Reported as its own distinct finding type, oversized_file_marked_skip, alongside this.",
    }

    if not tests_dir.is_dir():
        return {
            "truncation": truncation,
            "oversized_file_marked_skip": {
                "outcome": "no_tests_dir",
                "ok": False,
                "files": [],
            },
        }

    referenced, parse_errors = _svc_pc_referenced_files(tests_dir)
    env_basenames = _environment_basenames(task_dir)
    oversized: list[dict[str, Any]] = []
    n_resolved_solution = 0
    n_resolved_environment = 0
    n_unresolved = 0
    for name in sorted(referenced):
        f = solution_files_dir / name
        source = None
        if f.is_file():
            source = "solution/files"
            n_resolved_solution += 1
        else:
            env_f = env_basenames.get(name)
            if env_f is not None:
                f = env_f
                source = "environment/initial_workspace"
                n_resolved_environment += 1
            else:
                n_unresolved += 1
                continue
        size = f.stat().st_size
        if size > SVC_PC_MAX_FILE_SIZE:
            oversized.append({"file": name, "size_bytes": size, "source": source})

    return {
        "truncation": truncation,
        "oversized_file_marked_skip": {
            "outcome": "checked",
            "ok": not oversized,
            "n_referenced_files": len(referenced),
            "n_resolved_solution": n_resolved_solution,
            "n_resolved_environment": n_resolved_environment,
            "n_unresolved": n_unresolved,
            "n_oversized": len(oversized),
            "files": oversized,
            "parse_errors": parse_errors,
        },
    }


# ---------------------------------------------------------------------------
# Per-task dispatch
# ---------------------------------------------------------------------------


def analyze_task(task_dir: Path) -> dict[str, Any]:
    task_id = task_dir.name
    fmt = _detect_format(task_dir)

    if fmt == "ekw":
        ekw = _check_ekw_truncation(task_dir)
        n_candidates = ekw.get("n_candidates", 0)
        has_error = not ekw.get("ok", False)
        status = (
            "error" if has_error else ("candidates_found" if n_candidates else "ok")
        )
        return {
            "task_id": task_id,
            "format": fmt,
            "status": status,
            "ekw_truncation": ekw,
        }

    if fmt == "svc_pc":
        svc = _check_svc_pc_truncation(task_dir)
        oversized = svc["oversized_file_marked_skip"]
        has_error = not oversized.get("ok", True) and oversized.get("outcome") not in (
            "checked",
        )
        n_oversized = oversized.get("n_oversized", 0)
        status = (
            "error"
            if oversized.get("outcome") == "no_tests_dir"
            else ("candidates_found" if n_oversized else "not_applicable")
        )
        return {
            "task_id": task_id,
            "format": fmt,
            "status": status,
            "svc_pc_truncation": svc["truncation"],
            "svc_pc_oversized_file_marked_skip": svc["oversized_file_marked_skip"],
        }

    return {
        "task_id": task_id,
        "format": "unknown",
        "status": "error",
        "detail": "neither tests/verifier.json (EKW) nor tests/**/judge.toml (SVC-PC) found -- "
        "cannot determine which grading harness applies",
    }


def _analyze_task_safe(task_dir: Path) -> dict[str, Any]:
    """Module-level wrapper so ProcessPoolExecutor can pickle it (Windows spawn requires a
    top-level, importable target). Never lets one task's crash kill the whole batch -- an
    unhandled exception here is THIS SCRIPT's bug, reported as such, never mistaken for a task
    finding."""
    try:
        return analyze_task(task_dir)
    except Exception as e:
        return {
            "task_id": task_dir.name,
            "format": "unknown",
            "status": "error",
            "detail": f"unhandled exception in source_truncation_check.py analyzing this task "
            f"(this is a bug in the check, not a task defect): {type(e).__name__}: {e}",
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Flags EKW verifier sources whose gold-replay extracted text length lands "
        "exactly at max_content_chars (90000) -- the tell for SourceRegistry's silent, unmarked "
        "truncation (Pietro Carra's finding S-6). Also checks SVC-PC for an analogous mechanism "
        "(none found in harbor-rewardkit's judge file-reading path; a distinct, disclosed "
        "1MB hard-reject is reported separately as oversized_file_marked_skip). Every finding is "
        "a `candidate` for human review, not a confirmed defect -- see module docstring."
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
        "serial). Each task's gold replay is independent, and parallelism is also what gives "
        "per-task verifier_lib import isolation for free on Windows spawn (see module "
        "docstring).",
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
            "(gold-replay source extraction, each task independent)...",
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

    n_pass = sum(
        1
        for r in results
        if r["status"] in ("ok", "candidates_found", "not_applicable")
    )
    n_fail = sum(1 for r in results if r["status"] == "error")
    n_tasks_with_candidates = sum(
        1 for r in results if r["status"] == "candidates_found"
    )

    n_ekw_truncation_candidates = sum(
        r.get("ekw_truncation", {}).get("n_candidates", 0) for r in results
    )
    n_ekw_source_errors = sum(
        r.get("ekw_truncation", {}).get("n_source_errors", 0) for r in results
    )
    n_svc_pc_oversized = sum(
        r.get("svc_pc_oversized_file_marked_skip", {}).get("n_oversized", 0)
        for r in results
    )

    by_format: dict[str, dict[str, int]] = {}
    for r in results:
        fmt = r.get("format", "unknown")
        d = by_format.setdefault(
            fmt, {"n_tasks": 0, "n_pass": 0, "n_fail": 0, "n_tasks_with_candidates": 0}
        )
        d["n_tasks"] += 1
        d["n_pass" if r["status"] != "error" else "n_fail"] += 1
        if r["status"] == "candidates_found":
            d["n_tasks_with_candidates"] += 1

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_tasks_with_candidates": n_tasks_with_candidates,
        "n_ekw_truncation_candidates": n_ekw_truncation_candidates,
        "n_ekw_source_errors": n_ekw_source_errors,
        "n_svc_pc_oversized_file_marked_skip": n_svc_pc_oversized,
        "by_format": by_format,
        "results": results,
    }

    print(
        f"\n{len(results)} task(s) checked: {n_pass} completed cleanly / {n_fail} errored "
        f"(the check itself failed to run, e.g. no importable verifier_lib -- NOT a truncation "
        f"finding)"
    )
    n_ekw_tasks_with_candidates = by_format.get("ekw", {}).get(
        "n_tasks_with_candidates", 0
    )
    n_svc_pc_tasks_with_oversized = by_format.get("svc_pc", {}).get(
        "n_tasks_with_candidates", 0
    )
    print(
        f"EKW: {n_ekw_truncation_candidates} truncation candidate source-read(s) across "
        f"{n_ekw_tasks_with_candidates} task(s)  |  {n_ekw_source_errors} source_error(s) "
        f"(unrelated extraction failures, not truncation)"
    )
    print(
        f"SVC-PC: truncation mechanism not_applicable for all tasks (see module docstring)  |  "
        f"{n_svc_pc_oversized} file(s) referenced by a judge.toml and over "
        f"{SVC_PC_MAX_FILE_SIZE} bytes across {n_svc_pc_tasks_with_oversized} task(s) "
        f"(oversized_file_marked_skip -- a distinct, disclosed defect shape, not truncation)"
    )
    for fmt, d in sorted(by_format.items()):
        print(
            f"  format={fmt}: {d['n_pass']} clean / {d['n_fail']} errored "
            f"({d['n_tasks_with_candidates']} with candidates) out of {d['n_tasks']} tasks"
        )
    for r in results:
        if r["status"] == "error":
            print(f"  {r['task_id']}: ERROR")
            detail = r.get("detail") or r.get("ekw_truncation", {}).get("detail", "")
            if detail:
                print(f"      ! {detail}")
        elif r["status"] == "candidates_found":
            if r["format"] == "ekw":
                for c in r["ekw_truncation"]["candidates"]:
                    print(
                        f"  {r['task_id']}: CANDIDATE  {c['verifier']}  {c['source']}  "
                        f"{c['path']}  len={c['length']}"
                    )
            elif r["format"] == "svc_pc":
                for f in r["svc_pc_oversized_file_marked_skip"]["files"]:
                    print(
                        f"  {r['task_id']}: OVERSIZED  {f['file']}  {f['size_bytes']} bytes "
                        f"(> {SVC_PC_MAX_FILE_SIZE})"
                    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
