#!/usr/bin/env python3
"""EKW Check B: did the EKW build actually produce a valid task package, and lay a
contract-shaped copy of it down so every shared check in `deterministic-checks/` runs on
EKW tasks unchanged.

Why this file exists
--------------------
`BUILD-CONTRACT.md` says Check B is benchmark-specific and belongs next to the benchmark's
own build tools, never in a shared check. EKW's build output (`pipeline/cycle.py bundle`, and
the merged 274-task drop at `EKWBench_274_tasks_harbor_2026-09-10`) does not land in the
contract shape. It ships:

    <task>/
      instruction.md
      task.toml
      environment/Dockerfile
      environment/data/<inputs>                 (contract wants environment/initial_workspace/)
      solution/solve.sh
      solution/golden_outputs/<goldens>         (contract wants solution/<goldens>)
      tests/test.sh
      tests/verifier.json                       (contract wants tests/deliverables_NN/judge.toml)
      tests/verifier_lib/                       (vendored harbor runtime)
      tests/verifier_runtime.py                 (native-harbor genre only)

So this script does two things per task, both read-only against the source package:

  1. Check B proper: verify the build produced what a runnable, gradeable package needs.
     Every finding below was calibrated by scanning all 274 tasks of the 2026-09-10 drop at
     `C:\\ekwqc\\_merged274\\files` (see "Calibration" at the bottom of this docstring).

  2. Translation layer (`--stage DIR`): write a lossless contract-shaped copy so the shared
     checks (`formula_health_check.py`, `rubric_schema_check.py`, `deliverable_filename_check.py`
     and the rest) run on it with zero changes. Criterion names in the generated `judge.toml`
     are the verifier names from `verifier.json` (`v1`, `v2`, ...) so every downstream finding
     maps straight back to the entry the EKW author has to edit. The staged tree is a
     checking surface, NOT the artifact that gets uploaded: the upload artifact is whatever
     `pipeline/tools/rewardkit_convert.py` produces, and `--rewardkit-out DIR` runs that real
     converter per task and records whether it succeeded, which is the strongest "did it build"
     evidence available without a DataOS run.

The two build genres in one drop (Check B has to know this)
------------------------------------------------------------
Scanning the 274 tasks found two self-consistent build genres sharing one directory layout:

  native-harbor (180 tasks)   task.toml has `artifacts = ["/workspace/output"]`, solve.sh copies
                              `$GOLDEN_DIR/<file>` to `$OUTPUT_DIR/`, Dockerfile is the
                              `cycle.py` template (`COPY verifier-requirements.txt` or a
                              `--from=skills` stage), `tests/verifier_runtime.py` is vendored,
                              instruction.md talks about `output/`. Runnable under Harbor as-is.
  rewardkit-hybrid (94 tasks) task.toml `schema_version = "1.1"`, solve.sh does
                              `cp -a /solution/files/. /app/`, Dockerfile does
                              `COPY initial_workspace/ /app/`, no `verifier_runtime.py`,
                              instruction.md talks about `/app/`. Neither `initial_workspace/`
                              nor `solution/files/` exists in the package, so this genre only
                              runs AFTER `to_rewardkit.py` regenerates both. All 119 tasks of
                              DataOS dataset 608 (Oracle batch #2313, 112 pass / 7 fail) are
                              this genre, which is the evidence that the DataOS path converts
                              first rather than running the package verbatim.

The genre is detected per task from four signals (solve.sh, Dockerfile, task.toml, runtime
file) and reported. A rewardkit-hybrid task missing `verifier_runtime.py` is expected for its
genre (info); a native-harbor task missing it is a real build defect (fail), because its own
`tests/test.sh` execs that file.

What it asserts (finding kinds, severity in brackets)
-----------------------------------------------------
Package files
  missing_instruction [fail]        empty_instruction [fail]
  missing_task_toml [fail]          task_toml_parse_error [fail]      task_id_mismatch [warn]
  missing_environment_dir [fail]    environment_empty [fail]          zero_byte_input [fail]
  missing_golden_dir [fail]         golden_empty [fail]               zero_byte_golden [fail]
  missing_dockerfile [warn]         missing_solve_sh [warn]           missing_test_sh [warn]
  verifier_runtime_missing [fail on native-harbor, info on a clean rewardkit-hybrid, warn when
                            the genre signals conflict or tie]
  layout_requires_conversion [info] (rewardkit-hybrid genre: package is only runnable after
                                     to_rewardkit; not a defect on the DataOS path)
  genre_mixed_signals [warn]        extra_top_level_entry [info]

verifier.json
  missing_verifier_json [fail]      verifier_json_parse_error [fail]  verifiers_not_list [fail]
  no_verifiers [fail]               verifier_entry_not_object [fail]  verifier_schema_foreign [fail]
  verifier_name_missing [fail]      duplicate_verifier_name [fail]    empty_rubric_prompt [fail]
  weight_not_numeric [fail]         weights_all_missing [warn]        weight_sum_off [fail/warn]
  verifier_count_low [warn]         config_missing [warn]             config_no_models [warn]
  unrecognized_source_shape [warn]  (a source block none of the seven observed shapes matches)

Graded files vs goldens (the "did the golden get generated where the verifier reads it" check)
  graded_file_missing_golden [fail]         a verifier reads a file no golden supplies
  graded_golden_case_mismatch [warn]        same name, different case
  graded_golden_encoding_mismatch [warn]    same name once mojibake/Unicode form is undone
  golden_not_graded [warn]                  a golden no verifier ever reads (reasoning docs excluded)
  reasoning_doc_nonstandard_name [warn]     a reasoning doc not named Reasoning.docx, which the
                                            converter would ship as a deliverable
  reasoning_doc_invalid_format [warn]       a reasoning doc whose bytes are not its extension
                                            (six Reasoning.docx in the drop are Markdown)
  rubric_prompt_unencodable [warn]          a rubric prompt holding a lone surrogate escape;
                                            replaced with U+FFFD for staging
  path_convention_mismatch [info]           instruction.md and verifier.json name different
                                            output locations (/app/ vs output/); consistent
                                            after conversion, disclosed for the harbor path

Staging (only with --stage)
  stage_error [fail]                staged_roundtrip_mismatch [fail]  (generated judge.toml did
                                    not parse back to the exact source prompts and weights)

Conversion (only with --rewardkit-out)
  rewardkit_convert_failed [fail]   rewardkit_validate_failed [fail]

Status is `fail` if any fail-severity finding fired, otherwise `pass`. `skip` means the task
directory has none of the package files at all (not a task). Warn and info never change status;
they are disclosed so a reader can decide.

What it does NOT check
----------------------
- Whether prompt, golden and rubric agree in MEANING (Check A, `content-audit/SKILL.md`).
- Rubric text quality, blank criteria, duplicate names inside judge.toml, formula health,
  answer-key leakage: those are the shared checks' job and run on the staged copy.
- Judge temperature / panel: `judge_determinism_config_lint.py` reads `verifier.json`
  natively and already found the temperature=1.0 no-panel defect; not duplicated here.
- Whether DataOS accepts the package. Only a DataOS run proves that.

Usage
-----
    python ekw_check_b.py --all --root C:\\ekwqc\\_merged274\\files --out check_b.json
    python ekw_check_b.py task_142 task_15 --root ... --stage C:\\ekwqc\\_ekw274_stage --out check_b.json
    python ekw_check_b.py --all --root ... --stage ... --rewardkit-out C:\\ekwqc\\_ekw274_rk --out check_b.json

`--root` is required, no default, on purpose. `--stage` and `--rewardkit-out` must be outside
`--root`; an existing staged/converted task directory is deleted and rebuilt (they are derived
output). Exit 0 when every task passes, 1 when any task fails, 2 on bad usage. Stdlib only
(Python 3.11+ for tomllib).

Output shape (`--out`)
----------------------
    {generated, root, stage, rewardkit_out, n_tasks, n_pass, n_fail, n_skip,
     genre_counts, findings_by_kind, results: [ {task_id, status, genre, n_fail, n_warn, n_info,
     findings: [{kind, severity, message, ...}], package: {...}, verifiers: {...},
     graded_files: [...], goldens: [...], staged: {...} | null, rewardkit: {...} | null} ]}

Calibration (2026-09-14, all 274 tasks of `C:\\ekwqc\\_merged274\\files`)
--------------------------------------------------------------------
- 273 of 274 carry every package file; one lacks solve.sh.
- `verifiers` is a list in all 274; 5,596 rubric assertions, 4 deterministic (task_15).
- Seven source shapes observed and handled: `{type:file, file:{arguments:{path}}}` (the
  common one), `arguments:{paths:[...]}` (extract_many, 26 verifiers), `source.file` as a LIST
  of specs (task_270, 326, 536, 569, 600), `{type:files, files:[...]}` (task_34), a spec with
  `path` at its top level and no `arguments` (task_536), `type:directory command:list_files`
  (task_605), and task_FIN-177's foreign schema (`criterion`/`pass_condition`/`applies_to`,
  paths under `metadata.source.file.paths`, weights present, no `assertion` at all).
- Graded paths: 5,502 under `output/`, 51 bare filenames (task_350 and two others), 1 under
  `/workspace/output/`. All are normalised to a basename before matching against goldens.
- Weight sums: 273 tasks at 1.0 within 0.01; task_FIN-177 at 0 under the naive reader
  (its weights are real, at `metadata.weight`, and read once the foreign schema is handled).
- Goldens no verifier reads: 22 tasks, 16 of them a reasoning document under a non-standard
  name (`reasoning.md`, `Reasoning Doc.docx`, `Task 113 - Reasoning Document.pdf`, ...), two
  (task_48, task_56) an `output_variables.json`, task_653 two goldens whose on-disk names carry
  cp437-decoded UTF-8 (`ΓÇö` for an em dash) while verifier.json names them correctly.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.stderr.write("needs Python 3.11+ for tomllib\n")
    raise SystemExit(2)

# Task filenames carry em dashes and cp437 mojibake; a cp1252 Windows console would raise
# UnicodeEncodeError on the first finding (and on --help). Print what can be printed.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
REWARDKIT_CONVERT = REPO_ROOT / "pipeline" / "tools" / "rewardkit_convert.py"

ENV_DATA = ("environment", "data")
GOLDEN_DIR = ("solution", "golden_outputs")
VERIFIER_JSON = ("tests", "verifier.json")

# Names that mean "nothing was staged here", not "an input file".
PLACEHOLDER_NAMES = {
    ".gitkeep",
    ".keep",
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
    "placeholder",
    "placeholder.txt",
}
REASONING_RE = re.compile(r"reasoning", re.IGNORECASE)
STANDARD_REASONING_NAMES = {"reasoning.docx"}
OUTPUT_PREFIXES = ("/workspace/output/", "output/", "/app/", "./")
MIN_VERIFIERS = 6  # pipeline/cycle.py _verifier_sanity's own floor
WEIGHT_FAIL_TOL = 0.01
WEIGHT_WARN_TOL = 0.001


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _finding(kind, severity, message, **extra):
    d = {"kind": kind, "severity": severity, "message": message}
    d.update(extra)
    return d


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _rel(p: Path, base: Path) -> str:
    try:
        return str(p.relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _longpath(p: Path) -> str:
    """Windows refuses paths over ~260 chars unless prefixed with \\\\?\\; the 274-drop has
    input filenames long enough to trip this under any deep staging root (seen on task_1).
    """
    s = str(p.resolve())
    if sys.platform == "win32" and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + s
    return s


def _copy_file(src: Path, dst: Path, link: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if link:
        try:
            os.link(_longpath(src), _longpath(dst))
            return
        except OSError:
            pass
    shutil.copy2(_longpath(src), _longpath(dst))


def _copy_tree(src: Path, dst: Path, link: bool) -> int:
    n = 0
    for p in sorted(src.rglob("*")):
        if p.is_file():
            _copy_file(p, dst / p.relative_to(src), link)
            n += 1
    return n


def _rmtree(p: Path) -> None:
    if p.exists():
        shutil.rmtree(_longpath(p))


def _files_under(d: Path) -> list[Path]:
    if not d.is_dir():
        return []
    return sorted(p for p in d.rglob("*") if p.is_file())


def _toml_str(s: str) -> str:
    """A TOML basic string. json.dumps with ensure_ascii=False emits exactly TOML's escape set
    (\\b \\t \\n \\f \\r \\" \\\\ \\uXXXX) and raw non-ASCII; the one gap is U+007F, which TOML
    requires escaped and JSON does not. Round-tripped through tomllib in stage_task().
    """
    return json.dumps(str(s), ensure_ascii=False).replace("\x7f", "\\u007F")


def _toml_list(items) -> str:
    return "[" + ", ".join(_toml_str(x) for x in items) + "]"


def _strip_output_prefix(path: str) -> tuple[str, str]:
    """Returns (basename-or-relative, convention) for a verifier source path."""
    p = str(path).replace("\\", "/").strip()
    conv = "bare"
    for pre in OUTPUT_PREFIXES:
        if p.startswith(pre):
            conv = pre
            p = p[len(pre) :]
            break
    return p, conv


def _format_problem(p: Path) -> str:
    """'' when the file's bytes match its extension; otherwise a short reason. Office files are
    zip containers, PDFs start with %PDF. Six of the 274 drop's Reasoning.docx files are
    Markdown text (they start with '# ')."""
    ext = p.suffix.lower()
    try:
        head = p.open("rb").read(8)
    except OSError as e:
        return f"cannot be read ({e.__class__.__name__})"
    if ext in (".docx", ".xlsx", ".xlsm", ".pptx") and not head.startswith(b"PK"):
        return f"is not a zip container (starts with {head[:4]!r}), so not a real {ext[1:]}"
    if ext == ".pdf" and not head.startswith(b"%PDF"):
        return f"does not start with %PDF (starts with {head[:4]!r})"
    return ""


def _undo_mojibake(name: str) -> str:
    """'ΓÇö' is what an em dash's UTF-8 bytes look like decoded as cp437 (task_653)."""
    try:
        return name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def _norm_name(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


# ---------------------------------------------------------------------------
# verifier.json normalisation: every observed shape -> one criterion record
# ---------------------------------------------------------------------------


def _file_specs(source) -> tuple[list[dict], str]:
    """Flatten a verifier's `source` block into [{type, command, paths:[...]}].
    Returns (specs, shape_label). shape_label is for the report; 'unrecognized' means none of
    the calibrated shapes matched and the caller should warn."""
    if not isinstance(source, dict):
        return [], "missing"
    specs = source.get("file")
    label = "file"
    if specs is None:
        specs = source.get("files")
        label = "files"
    if specs is None:
        return [], "unrecognized"
    if isinstance(specs, dict):
        specs = [specs]
        label += ":single"
    elif isinstance(specs, list):
        label += ":list"
    else:
        return [], "unrecognized"
    out = []
    for s in specs:
        if not isinstance(s, dict):
            continue
        args = s.get("arguments") if isinstance(s.get("arguments"), dict) else {}
        paths: list[str] = []
        for key in ("path", "paths"):
            v = args.get(key, s.get(key))
            if isinstance(v, str):
                paths.append(v)
            elif isinstance(v, list):
                paths.extend(x for x in v if isinstance(x, str))
        out.append({"type": s.get("type"), "command": s.get("command"), "paths": paths})
    return out, label


def _deterministic_description(v: dict) -> str:
    """Mirror of pipeline/tools/to_rewardkit.py's _deterministic_description, minus its
    /app/ path rewrite: a judge-readable sentence for an assertion with no rubric prompt.
    """
    m = v.get("metadata") or {}
    a = v.get("assertion") or {}
    parts = []
    if m.get("why_justification"):
        parts.append(str(m["why_justification"]).strip())
    if m.get("how_justification"):
        parts.append("Check: " + str(m["how_justification"]).strip())
    det = a.get("deterministic") if isinstance(a.get("deterministic"), dict) else {}
    comparison, expected, path = (
        det.get("comparison"),
        a.get("expected"),
        det.get("path"),
    )
    if comparison and expected is not None:
        where = f" at {path}" if path else ""
        parts.append(f"Verify (via {comparison}{where}): {expected}")
    return " ".join(parts).strip()


def normalize_verifier(v, index: int) -> dict:
    """One verifier entry -> one criterion record. Never raises; records its own problems."""
    rec = {
        "index": index,
        "name": None,
        "tag": None,
        "weight": None,
        "weight_set": False,
        "kind": "unknown",
        "description": "",
        "files": [],  # basenames the verifier reads (after prefix stripping)
        "raw_paths": [],
        "dir_refs": [],  # directory listings (list_files on output/)
        "conventions": [],  # per raw path: 'output/', '/app/', '/workspace/output/', 'bare'
        "source_shape": None,
        "grading_role": None,
        "importance": None,
        "problems": [],  # (kind, message) for the caller to turn into findings
    }
    if not isinstance(v, dict):
        rec["problems"].append(
            (
                "verifier_entry_not_object",
                f"entry #{index} is {type(v).__name__}, not an object",
            )
        )
        return rec
    rec["name"] = v.get("name") if isinstance(v.get("name"), str) else None
    m = v.get("metadata") if isinstance(v.get("metadata"), dict) else {}
    rec["tag"] = m.get("tag") if isinstance(m.get("tag"), str) else None
    rec["grading_role"] = m.get("grading_role")
    rec["importance"] = m.get("importance") or m.get("classification")
    w = m.get("weight", v.get("weight"))
    if isinstance(w, bool):
        w = None
    if isinstance(w, (int, float)):
        rec["weight"] = float(w)
        rec["weight_set"] = True
    elif w is not None:
        rec["problems"].append(
            ("weight_not_numeric", f"{rec['name'] or '#'+str(index)}: weight is {w!r}")
        )

    a = v.get("assertion")
    if isinstance(a, dict):
        at = a.get("type")
        if at == "rubric":
            rec["kind"] = "rubric"
            rub = a.get("rubric")
            prompt = (
                rub.get("prompt")
                if isinstance(rub, dict)
                else (rub if isinstance(rub, str) else "")
            )
            rec["description"] = str(prompt or "").strip()
            # A JSON escape like "\ud83d" with no partner decodes to a lone surrogate, which
            # no UTF-8 file can hold. Replace it up front (and say so) rather than let the
            # judge.toml write crash mid-group and leave a 0-byte file (found by the staging
            # verifier, 2026-09-14).
            try:
                rec["description"].encode("utf-8")
            except UnicodeEncodeError:
                rec["description"] = (
                    rec["description"].encode("utf-8", "replace").decode("utf-8")
                )
                rec["problems"].append(
                    (
                        "rubric_prompt_unencodable",
                        f"{rec['name'] or '#'+str(index)}: rubric prompt holds a lone surrogate escape (invalid UTF-8); replaced with U+FFFD for staging",
                    )
                )
            if not rec["description"]:
                rec["problems"].append(
                    (
                        "empty_rubric_prompt",
                        f"{rec['name'] or '#'+str(index)}: rubric assertion with no prompt",
                    )
                )
        elif at == "deterministic":
            rec["kind"] = "deterministic"
            rec["description"] = _deterministic_description(v)
        else:
            rec["kind"] = "unknown"
            rec["description"] = str(
                (a.get("rubric") or {}).get("prompt", "")
                if isinstance(a.get("rubric"), dict)
                else ""
            ).strip()
            rec["problems"].append(
                (
                    "verifier_schema_foreign",
                    f"{rec['name'] or '#'+str(index)}: assertion.type={at!r} is not rubric/deterministic",
                )
            )
        specs, shape = _file_specs(v.get("source"))
    elif "criterion" in v or "pass_condition" in v:
        # task_FIN-177's schema: no assertion block, criterion text at top level, graded paths
        # under metadata.source.file.paths.
        rec["kind"] = "foreign"
        parts = [str(v.get("criterion") or "").strip()]
        if v.get("pass_condition"):
            parts.append("Pass condition: " + str(v["pass_condition"]).strip())
        rec["description"] = " ".join(p for p in parts if p)
        specs, shape = _file_specs(m.get("source"))
        shape = "foreign:" + shape
        rec["problems"].append(
            (
                "verifier_schema_foreign",
                f"{rec['name'] or '#'+str(index)}: no assertion block; criterion/pass_condition schema",
            )
        )
    else:
        specs, shape = _file_specs(v.get("source"))
        rec["problems"].append(
            (
                "verifier_schema_foreign",
                f"{rec['name'] or '#'+str(index)}: no assertion block",
            )
        )
    rec["source_shape"] = shape
    if shape == "unrecognized":
        rec["problems"].append(
            (
                "unrecognized_source_shape",
                f"{rec['name'] or '#'+str(index)}: source block has neither file nor files",
            )
        )
    for s in specs:
        is_dir_cmd = s.get("command") == "list_files" or s.get("type") == "directory"
        for raw in s["paths"]:
            rec["raw_paths"].append(raw)
            stripped, conv = _strip_output_prefix(raw)
            rec["conventions"].append(conv)
            if is_dir_cmd or stripped == "" or stripped.endswith("/"):
                rec["dir_refs"].append(raw)
                continue
            base = stripped.rsplit("/", 1)[-1]
            if base and base not in rec["files"]:
                rec["files"].append(base)
    return rec


def load_verifier(task_dir: Path):
    """Returns (data|None, error|None)."""
    p = task_dir.joinpath(*VERIFIER_JSON)
    if not p.is_file():
        return None, "missing"
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as e:
        return None, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# genre detection
# ---------------------------------------------------------------------------


def detect_genre(task_dir: Path) -> dict:
    solve = _read_text(task_dir / "solution" / "solve.sh")
    dock = _read_text(task_dir / "environment" / "Dockerfile")
    toml_txt = _read_text(task_dir / "task.toml")
    instr = _read_text(task_dir / "instruction.md")
    sig = {}

    # Each file votes once. A file carrying BOTH genres' markers votes "conflict" (no vote)
    # rather than letting whichever test ran first win: an if/elif here let a task.toml with
    # both `schema_version = "1.1"` and `artifacts =` read as rewardkit-hybrid and hid a
    # missing runtime file behind the wrong genre (found by mutation testing, 2026-09-14).
    def vote(hybrid: bool, native: bool, present: bool):
        if hybrid and native:
            return "conflict"
        if hybrid:
            return "rewardkit-hybrid"
        if native:
            return "native-harbor"
        return "unknown" if present else None

    sig["solve_sh"] = vote(
        "/solution/files" in solve and "/app" in solve,
        "golden_outputs" in solve or "OUTPUT_DIR" in solve,
        bool(solve),
    )
    sig["dockerfile"] = vote(
        bool(re.search(r"^COPY\s+initial_workspace/", dock, re.M)),
        "verifier-requirements.txt" in dock or "--from=skills" in dock,
        bool(dock),
    )
    sig["task_toml"] = vote(
        bool(re.search(r'^schema_version\s*=\s*"1\.1"', toml_txt, re.M)),
        bool(re.search(r"^artifacts\s*=", toml_txt, re.M)),
        bool(toml_txt),
    )
    # The runtime file's PRESENCE is native-harbor evidence; its absence is what this check
    # wants to judge, so absence casts no vote.
    sig["verifier_runtime"] = (
        "native-harbor"
        if (task_dir / "tests" / "verifier_runtime.py").is_file()
        else "absent"
    )
    sig = {k: v for k, v in sig.items() if v is not None}
    votes = [g for g in sig.values() if g in ("native-harbor", "rewardkit-hybrid")]
    n_native, n_hybrid = votes.count("native-harbor"), votes.count("rewardkit-hybrid")
    if n_native > n_hybrid:
        genre = "native-harbor"
    elif n_hybrid > n_native:
        genre = "rewardkit-hybrid"
    else:
        genre = "unknown"
    mixed = len(set(votes)) > 1 or "conflict" in sig.values()
    instr_conv = []
    if "/app/" in instr:
        instr_conv.append("/app/")
    if "/workspace/output" in instr:
        instr_conv.append("/workspace/output/")
    elif "output/" in instr:
        instr_conv.append("output/")
    return {
        "genre": genre,
        "signals": sig,
        "mixed": mixed,
        "instruction_conventions": instr_conv,
    }


# ---------------------------------------------------------------------------
# Check B proper
# ---------------------------------------------------------------------------


def check_task(task_dir: Path) -> dict:
    """Check B for one EKW task. Never raises on a malformed package."""
    t0 = time.time()
    tid = task_dir.name
    findings: list[dict] = []
    res = {
        "task_id": tid,
        "status": "pass",
        "genre": None,
        "n_fail": 0,
        "n_warn": 0,
        "n_info": 0,
        "findings": findings,
        "package": {},
        "verifiers": {},
        "criteria": [],  # normalised records (kept: the stager and runner reuse them)
        "graded_files": [],
        "goldens": [],
        "staged": None,
        "rewardkit": None,
        "seconds": 0.0,
    }
    has_any = any(
        (task_dir / x).exists()
        for x in ("instruction.md", "task.toml", "environment", "solution", "tests")
    )
    if not has_any:
        res["status"] = "skip"
        findings.append(
            _finding(
                "not_a_task_dir",
                "info",
                "none of instruction.md/task.toml/environment/solution/tests present",
            )
        )
        res["seconds"] = round(time.time() - t0, 3)
        return res

    # --- top-level files -------------------------------------------------------------
    extras = sorted(
        x.name
        for x in task_dir.iterdir()
        if x.name
        not in ("environment", "instruction.md", "solution", "task.toml", "tests")
    )
    for x in extras:
        findings.append(
            _finding(
                "extra_top_level_entry",
                "info",
                f"unexpected top-level entry: {x}",
                entry=x,
            )
        )

    instr_p = task_dir / "instruction.md"
    instr = _read_text(instr_p) if instr_p.is_file() else None
    if instr is None:
        findings.append(
            _finding("missing_instruction", "fail", "instruction.md missing")
        )
    elif not instr.strip():
        findings.append(
            _finding("empty_instruction", "fail", "instruction.md is empty")
        )

    toml_p = task_dir / "task.toml"
    task_toml = None
    if not toml_p.is_file():
        findings.append(_finding("missing_task_toml", "fail", "task.toml missing"))
    else:
        try:
            task_toml = tomllib.loads(_read_text(toml_p))
        except Exception as e:  # tomllib.TOMLDecodeError or odd bytes
            findings.append(
                _finding(
                    "task_toml_parse_error", "fail", f"task.toml does not parse: {e}"
                )
            )
    if task_toml:
        declared = str(
            ((task_toml.get("metadata") or {}).get("task_id"))
            or ((task_toml.get("task") or {}).get("name"))
            or ""
        )
        m_folder = re.search(r"task[_-]?(.+)$", tid)
        m_decl = re.search(r"task[_-]?([A-Za-z0-9-]+)$", declared)
        if (
            declared
            and m_folder
            and m_decl
            and m_folder.group(1).casefold() != m_decl.group(1).casefold()
        ):
            findings.append(
                _finding(
                    "task_id_mismatch",
                    "warn",
                    f"task.toml names {declared!r} but the folder is {tid}",
                    declared=declared,
                )
            )
        res["package"]["task_toml_id"] = declared or None

    # --- genre -----------------------------------------------------------------------
    g = detect_genre(task_dir)
    res["genre"] = g["genre"]
    res["package"]["genre_signals"] = g["signals"]
    res["package"]["instruction_conventions"] = g["instruction_conventions"]
    if g["mixed"]:
        findings.append(
            _finding(
                "genre_mixed_signals",
                "warn",
                f"build-genre signals disagree: {g['signals']}",
                signals=g["signals"],
            )
        )

    # --- environment -----------------------------------------------------------------
    env_dir = task_dir.joinpath(*ENV_DATA)
    env_files = _files_under(env_dir)
    real_inputs = [p for p in env_files if p.name.lower() not in PLACEHOLDER_NAMES]
    res["package"]["environment_files"] = len(env_files)
    res["package"]["environment_bytes"] = (
        sum(p.stat().st_size for p in env_files) if env_files else 0
    )
    if not env_dir.is_dir():
        findings.append(
            _finding(
                "missing_environment_dir",
                "fail",
                "environment/data/ missing (the solver's inputs)",
            )
        )
    elif not real_inputs:
        findings.append(
            _finding(
                "environment_empty",
                "fail",
                (
                    "environment/data/ holds no input files (placeholders only)"
                    if env_files
                    else "environment/data/ is empty"
                ),
            )
        )
    zero_in = [_rel(p, task_dir) for p in real_inputs if p.stat().st_size == 0]
    if zero_in:
        findings.append(
            _finding(
                "zero_byte_input",
                "fail",
                f"{len(zero_in)} zero-byte input file(s): {', '.join(zero_in[:5])}",
                files=zero_in,
            )
        )
    if not (task_dir / "environment" / "Dockerfile").is_file():
        findings.append(
            _finding("missing_dockerfile", "warn", "environment/Dockerfile missing")
        )

    # --- goldens ---------------------------------------------------------------------
    gold_dir = task_dir.joinpath(*GOLDEN_DIR)
    gold_files = _files_under(gold_dir)
    res["goldens"] = [_rel(p, gold_dir) for p in gold_files]
    if not gold_dir.is_dir():
        findings.append(
            _finding("missing_golden_dir", "fail", "solution/golden_outputs/ missing")
        )
    elif not gold_files:
        findings.append(
            _finding("golden_empty", "fail", "solution/golden_outputs/ is empty")
        )
    zero_g = [_rel(p, task_dir) for p in gold_files if p.stat().st_size == 0]
    if zero_g:
        findings.append(
            _finding(
                "zero_byte_golden",
                "fail",
                f"{len(zero_g)} zero-byte golden(s): {', '.join(zero_g[:5])}",
                files=zero_g,
            )
        )
    if not (task_dir / "solution" / "solve.sh").is_file():
        findings.append(
            _finding(
                "missing_solve_sh",
                "warn",
                "solution/solve.sh missing (Oracle cannot reproduce the golden)",
            )
        )
    if not (task_dir / "tests" / "test.sh").is_file():
        findings.append(_finding("missing_test_sh", "warn", "tests/test.sh missing"))
    runtime_present = (task_dir / "tests" / "verifier_runtime.py").is_file()
    if not runtime_present:
        if g["genre"] == "native-harbor":
            findings.append(
                _finding(
                    "verifier_runtime_missing",
                    "fail",
                    "tests/verifier_runtime.py missing but tests/test.sh execs it (native-harbor genre)",
                )
            )
        elif g["genre"] == "rewardkit-hybrid" and not g["mixed"]:
            findings.append(
                _finding(
                    "verifier_runtime_missing",
                    "info",
                    "tests/verifier_runtime.py absent; expected for the rewardkit-hybrid genre, which runs only after to_rewardkit conversion",
                )
            )
        else:
            findings.append(
                _finding(
                    "verifier_runtime_missing",
                    "warn",
                    f"tests/verifier_runtime.py absent and the build genre is ambiguous ({g['signals']}); harmless only if this package goes through to_rewardkit",
                    signals=g["signals"],
                )
            )
    if g["genre"] == "rewardkit-hybrid":
        findings.append(
            _finding(
                "layout_requires_conversion",
                "info",
                "solve.sh/Dockerfile expect solution/files/ and initial_workspace/ (reward-kit layout); package ships golden_outputs/ and data/, so it is runnable only after pipeline/tools/rewardkit_convert.py",
            )
        )

    # --- verifier.json ---------------------------------------------------------------
    data, err = load_verifier(task_dir)
    crits: list[dict] = []
    if err == "missing":
        findings.append(
            _finding("missing_verifier_json", "fail", "tests/verifier.json missing")
        )
    elif err:
        findings.append(
            _finding(
                "verifier_json_parse_error",
                "fail",
                f"tests/verifier.json does not parse: {err}",
            )
        )
    elif not isinstance(data, dict):
        findings.append(
            _finding(
                "verifier_json_parse_error",
                "fail",
                f"tests/verifier.json top level is {type(data).__name__}, not an object",
            )
        )
    else:
        cfg = data.get("config")
        if not isinstance(cfg, dict):
            findings.append(
                _finding(
                    "config_missing",
                    "warn",
                    "verifier.json has no config object (judge model/temperature unknown)",
                )
            )
            cfg = {}
        elif not cfg.get("models"):
            findings.append(
                _finding(
                    "config_no_models",
                    "warn",
                    f"verifier.json config names no judge model (keys: {sorted(cfg)})",
                    config_keys=sorted(cfg),
                )
            )
        vs = data.get("verifiers")
        if not isinstance(vs, list):
            findings.append(
                _finding(
                    "verifiers_not_list",
                    "fail",
                    f"verifiers is {type(vs).__name__}, not a list",
                )
            )
            vs = []
        elif not vs:
            findings.append(_finding("no_verifiers", "fail", "verifiers list is empty"))
        for i, v in enumerate(vs):
            crits.append(normalize_verifier(v, i))
        problem_kinds: dict[str, list[str]] = {}
        for c in crits:
            for kind, msg in c["problems"]:
                problem_kinds.setdefault(kind, []).append(msg)
        for kind, msgs in problem_kinds.items():
            sev = (
                "warn"
                if kind in ("unrecognized_source_shape", "rubric_prompt_unencodable")
                else "fail"
            )
            findings.append(
                _finding(
                    kind,
                    sev,
                    f"{len(msgs)} verifier(s): {msgs[0]}"
                    + (f" (+{len(msgs)-1} more)" if len(msgs) > 1 else ""),
                    verifiers=msgs,
                )
            )
        names = [c["name"] for c in crits]
        if any(n is None for n in names):
            findings.append(
                _finding(
                    "verifier_name_missing",
                    "fail",
                    f"{sum(n is None for n in names)} verifier(s) have no name",
                )
            )
        dupes = sorted({n for n in names if n is not None and names.count(n) > 1})
        if dupes:
            findings.append(
                _finding(
                    "duplicate_verifier_name",
                    "fail",
                    f"duplicate verifier names: {dupes}",
                    names=dupes,
                )
            )
        if vs and len(vs) < MIN_VERIFIERS:
            findings.append(
                _finding(
                    "verifier_count_low",
                    "warn",
                    f"only {len(vs)} verifiers; project minimum is {MIN_VERIFIERS}",
                )
            )
        set_w = [c["weight"] for c in crits if c["weight_set"]]
        wsum = round(sum(set_w), 6) if set_w else 0.0
        if crits and not set_w:
            findings.append(
                _finding(
                    "weights_all_missing",
                    "warn",
                    "no verifier carries a numeric weight; runtime and converter both default to an equal split",
                )
            )
        elif crits and abs(wsum - 1.0) > WEIGHT_FAIL_TOL:
            findings.append(
                _finding(
                    "weight_sum_off",
                    "fail",
                    f"verifier weights sum to {wsum}, expected 1.0",
                    weight_sum=wsum,
                )
            )
        elif crits and abs(wsum - 1.0) > WEIGHT_WARN_TOL:
            findings.append(
                _finding(
                    "weight_sum_off",
                    "warn",
                    f"verifier weights sum to {wsum}, off 1.0 by more than {WEIGHT_WARN_TOL}",
                    weight_sum=wsum,
                )
            )
        convs = sorted({c for cr in crits for c in cr["conventions"]})
        res["verifiers"] = {
            "n": len(crits),
            "n_rubric": sum(c["kind"] == "rubric" for c in crits),
            "n_deterministic": sum(c["kind"] == "deterministic" for c in crits),
            "n_foreign": sum(c["kind"] in ("foreign", "unknown") for c in crits),
            "weight_sum": wsum,
            "models": cfg.get("models"),
            "temperature": cfg.get("temperature"),
            "path_conventions": convs,
            "source_shapes": sorted(
                {c["source_shape"] for c in crits if c["source_shape"]}
            ),
        }
        # instruction vs verifier output-location convention
        instr_conv = set(g["instruction_conventions"])
        ver_conv = {c for c in convs if c != "bare"}
        if instr_conv and ver_conv and not (instr_conv & ver_conv):
            findings.append(
                _finding(
                    "path_convention_mismatch",
                    "info",
                    f"instruction.md names {sorted(instr_conv)} as the output location, verifier.json reads {sorted(ver_conv)}; consistent after to_rewardkit (both become /app/), disclosed for the harbor path",
                    instruction=sorted(instr_conv),
                    verifier=sorted(ver_conv),
                )
            )

    res["criteria"] = crits

    # --- graded files vs goldens ------------------------------------------------------
    graded = []
    for c in crits:
        for f in c["files"]:
            if f not in graded:
                graded.append(f)
    res["graded_files"] = graded
    by_exact = {p.name: p for p in gold_files}
    by_norm: dict[str, Path] = {}
    for p in gold_files:
        by_norm.setdefault(_norm_name(p.name), p)
        by_norm.setdefault(_norm_name(_undo_mojibake(p.name)), p)
    matched_goldens: set[str] = set()
    for f in graded:
        if f in by_exact:
            matched_goldens.add(by_exact[f].name)
            continue
        alt = by_norm.get(_norm_name(f))
        if alt is not None:
            matched_goldens.add(alt.name)
            if alt.name.casefold() == f.casefold():
                findings.append(
                    _finding(
                        "graded_golden_case_mismatch",
                        "warn",
                        f"verifier reads {f!r}; golden on disk is {alt.name!r} (case differs)",
                        graded=f,
                        golden=alt.name,
                    )
                )
            else:
                findings.append(
                    _finding(
                        "graded_golden_encoding_mismatch",
                        "warn",
                        f"verifier reads {f!r}; golden on disk is {alt.name!r} (same name after undoing mojibake/Unicode form)",
                        graded=f,
                        golden=alt.name,
                    )
                )
            continue
        if gold_files:
            close = difflib.get_close_matches(
                f, [p.name for p in gold_files], n=1, cutoff=0.6
            )
            hint = f"; nearest golden: {close[0]!r}" if close else ""
            findings.append(
                _finding(
                    "graded_file_missing_golden",
                    "fail",
                    f"verifier reads {f!r} but no golden of that name exists{hint}",
                    graded=f,
                    nearest=close[0] if close else None,
                )
            )
        elif gold_dir.is_dir():
            findings.append(
                _finding(
                    "graded_file_missing_golden",
                    "fail",
                    f"verifier reads {f!r} but solution/golden_outputs/ is empty",
                    graded=f,
                )
            )
    for p in gold_files:
        if p.name in matched_goldens:
            continue
        if REASONING_RE.search(p.name):
            if p.name.lower() not in STANDARD_REASONING_NAMES:
                findings.append(
                    _finding(
                        "reasoning_doc_nonstandard_name",
                        "warn",
                        f"reasoning document {p.name!r} is not named Reasoning.docx; to_rewardkit ships anything else under solution/files/ as if it were a deliverable",
                        golden=p.name,
                    )
                )
            bad_fmt = _format_problem(p)
            if bad_fmt:
                findings.append(
                    _finding(
                        "reasoning_doc_invalid_format",
                        "warn",
                        f"reasoning document {p.name!r} {bad_fmt}; not graded, but the file is not what its extension claims",
                        golden=p.name,
                    )
                )
            continue
        findings.append(
            _finding(
                "golden_not_graded",
                "warn",
                f"golden {p.name!r} is read by no verifier",
                golden=p.name,
            )
        )

    _finalize(res)
    res["seconds"] = round(time.time() - t0, 3)
    return res


def _finalize(res: dict) -> None:
    sev = [f["severity"] for f in res["findings"]]
    res["n_fail"], res["n_warn"], res["n_info"] = (
        sev.count("fail"),
        sev.count("warn"),
        sev.count("info"),
    )
    if res["status"] != "skip":
        res["status"] = "fail" if res["n_fail"] else "pass"


# ---------------------------------------------------------------------------
# translation layer: harbor package -> BUILD-CONTRACT shape
# ---------------------------------------------------------------------------


def _group_criteria(crits: list[dict]) -> list[dict]:
    """One deliverables_NN group per distinct graded-file set, in order of first appearance.
    A criterion that reads no file (directory listing, foreign entry with no path) lands in a
    trailing group with files=[]; the shared checks treat an empty files list as 'skip'.
    """
    groups: list[dict] = []
    index: dict[tuple, int] = {}
    for c in crits:
        key = tuple(c["files"])
        if key not in index:
            index[key] = len(groups)
            groups.append({"files": list(key), "criteria": [], "raw_paths": []})
        grp = groups[index[key]]
        grp["criteria"].append(c)
        for rp in c["raw_paths"]:
            if rp not in grp["raw_paths"]:
                grp["raw_paths"].append(rp)
    # keep the empty-files group last so deliverables_01 is always a real deliverable
    groups.sort(key=lambda g: (not g["files"], 0))
    return groups


def render_judge_toml(
    group: dict, judge_model: str, crit_weights: dict[int, float], source_rel: str
) -> str:
    total = round(sum(crit_weights[c["index"]] for c in group["criteria"]), 6)
    lines = [
        f"# Generated by deterministic-checks/ekw/ekw_check_b.py from {source_rel}.",
        "# Lossless view of verifier.json for the shared deterministic checks. NOT the graded",
        "# artifact and not for upload: the upload artifact comes from pipeline/tools/rewardkit_convert.py.",
        "# Criterion names are the verifier names in verifier.json; edit there, never here.",
        "",
        "[judge]",
        f"judge = {_toml_str(judge_model)}",
        f"files = {_toml_list('/app/' + f for f in group['files'])}",
        f"source_paths = {_toml_list(group['raw_paths'])}",
        f"weight = {total}",
        "",
    ]
    for c in group["criteria"]:
        ctype = "deterministic" if c["kind"] == "deterministic" else "binary"
        cname = c["name"] if c["name"] is not None else "v%d" % (c["index"] + 1)
        lines += [
            "[[criterion]]",
            f"name = {_toml_str(cname)}",
        ]
        if c["tag"]:
            lines.append(f"tag = {_toml_str(c['tag'])}")
        lines += [
            f"description = {_toml_str(c['description'])}",
            f"type = {_toml_str(ctype)}",
            f"weight = {crit_weights[c['index']]}",
            f"verifier_index = {c['index']}",
        ]
        if c["grading_role"]:
            lines.append(f"grading_role = {_toml_str(str(c['grading_role']))}")
        if c["importance"]:
            lines.append(f"importance = {_toml_str(str(c['importance']))}")
        lines.append("")
    return "\n".join(lines)


def stage_task(task_dir: Path, stage_root: Path, res: dict, link: bool = False) -> dict:
    """Write <stage_root>/<task_id>/ in BUILD-CONTRACT shape. Returns the staged summary and
    appends stage_error / staged_roundtrip_mismatch findings to res on failure."""
    out = stage_root / task_dir.name
    info = {
        "dir": str(out),
        "groups": [],
        "n_inputs": 0,
        "n_goldens": 0,
        "reasoning_docs": [],
        "roundtrip_ok": None,
    }
    try:
        _rmtree(out)
        out.mkdir(parents=True)
        for name in ("instruction.md", "task.toml"):
            if (task_dir / name).is_file():
                _copy_file(task_dir / name, out / name, link)
        if (task_dir / "environment" / "Dockerfile").is_file():
            _copy_file(
                task_dir / "environment" / "Dockerfile",
                out / "environment" / "Dockerfile",
                link,
            )
        env_src = task_dir.joinpath(*ENV_DATA)
        (out / "environment" / "initial_workspace").mkdir(parents=True, exist_ok=True)
        if env_src.is_dir():
            info["n_inputs"] = _copy_tree(
                env_src, out / "environment" / "initial_workspace", link
            )
        (out / "solution" / "files").mkdir(parents=True, exist_ok=True)
        gold_src = task_dir.joinpath(*GOLDEN_DIR)
        graded_names = set(res.get("graded_files") or [])
        for p in _files_under(gold_src):
            rel = p.relative_to(gold_src)
            if p.name not in graded_names and REASONING_RE.search(p.name):
                # Outside solution/: the contract says solution/ holds deliverables, and the
                # shared integrity check opens everything under it (six Reasoning.docx in the
                # drop are Markdown, which would read as broken deliverables).
                _copy_file(p, out / "reasoning" / rel, link)
                info["reasoning_docs"].append(str(rel).replace("\\", "/"))
            else:
                _copy_file(p, out / "solution" / "files" / rel, link)
                info["n_goldens"] += 1
        if (task_dir / "solution" / "solve.sh").is_file():
            _copy_file(
                task_dir / "solution" / "solve.sh", out / "solution" / "solve.sh", link
            )
        (out / "tests").mkdir(parents=True, exist_ok=True)
        for name in ("verifier.json", "test.sh"):
            if (task_dir / "tests" / name).is_file():
                _copy_file(task_dir / "tests" / name, out / "tests" / name, link)

        crits = res.get("criteria") or []
        set_w = [c["weight"] for c in crits if c["weight_set"]]
        if crits and not set_w:
            even = round(1.0 / len(crits), 6)
            crit_weights = {c["index"]: even for c in crits}
        else:
            crit_weights = {
                c["index"]: (c["weight"] if c["weight_set"] else 0.0) for c in crits
            }
        models = (res.get("verifiers") or {}).get("models") or []
        judge_model = str(models[0]) if models else "unknown"
        source_rel = "tests/verifier.json"
        groups = _group_criteria(crits)
        expected = {}
        for gi, grp in enumerate(groups, start=1):
            gname = f"deliverables_{gi:02d}"
            gdir = out / "tests" / gname
            gdir.mkdir(parents=True, exist_ok=True)
            text = render_judge_toml(grp, judge_model, crit_weights, source_rel)
            # Encode first, then write bytes: write_text() truncates the file before it finds
            # an unencodable character, which left a 0-byte judge.toml in testing.
            (gdir / "judge.toml").write_bytes(text.encode("utf-8"))
            info["groups"].append(
                {
                    "group": gname,
                    "files": grp["files"],
                    "n_criteria": len(grp["criteria"]),
                    "weight": round(
                        sum(crit_weights[c["index"]] for c in grp["criteria"]), 6
                    ),
                }
            )
            for c in grp["criteria"]:
                expected[(gname, c["index"])] = (
                    c["description"],
                    crit_weights[c["index"]],
                )
        # provenance
        (out / "tests" / "STAGED-FROM.json").write_text(
            json.dumps(
                {
                    "source": str(task_dir),
                    "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "generator": "deterministic-checks/ekw/ekw_check_b.py",
                    "genre": res.get("genre"),
                    "groups": info["groups"],
                    "reasoning_docs": info["reasoning_docs"],
                    "note": "checking surface only; not the upload artifact",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        # round-trip proof: every generated judge.toml parses back to the source text and weight
        mismatches = []
        for gi, grp in enumerate(groups, start=1):
            gname = f"deliverables_{gi:02d}"
            parsed = tomllib.loads(
                (out / "tests" / gname / "judge.toml").read_text(encoding="utf-8")
            )
            got = parsed.get("criterion") or []
            if len(got) != len(grp["criteria"]):
                mismatches.append(
                    f"{gname}: {len(got)} criteria parsed, {len(grp['criteria'])} written"
                )
                continue
            for c in got:
                exp = expected.get((gname, c.get("verifier_index")))
                if (
                    exp is None
                    or c.get("description") != exp[0]
                    or abs(float(c.get("weight", -1)) - exp[1]) > 1e-9
                ):
                    mismatches.append(
                        f"{gname}/{c.get('name')}: description or weight did not round-trip"
                    )
        info["roundtrip_ok"] = not mismatches
        if mismatches:
            res["findings"].append(
                _finding(
                    "staged_roundtrip_mismatch",
                    "fail",
                    f"{len(mismatches)} generated criteria did not round-trip: {mismatches[0]}",
                    details=mismatches,
                )
            )
    except Exception as e:  # any staging failure is a Check B failure for that task
        res["findings"].append(
            _finding("stage_error", "fail", f"staging failed: {type(e).__name__}: {e}")
        )
        info["roundtrip_ok"] = False
        info["error"] = f"{type(e).__name__}: {e}"
    res["staged"] = info
    return info


# ---------------------------------------------------------------------------
# optional: run the real converter as the strongest available build proof
# ---------------------------------------------------------------------------


def run_rewardkit(task_dir: Path, rk_root: Path, res: dict, timeout: int = 600) -> dict:
    out = rk_root / task_dir.name
    info = {
        "dir": str(out),
        "ok": False,
        "returncode": None,
        "problems": [],
        "stderr_tail": "",
    }
    if not REWARDKIT_CONVERT.is_file():
        info["problems"].append(f"converter not found at {REWARDKIT_CONVERT}")
        res["findings"].append(
            _finding("rewardkit_convert_failed", "fail", info["problems"][0])
        )
        res["rewardkit"] = info
        return info
    _rmtree(out)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(REWARDKIT_CONVERT),
                str(task_dir),
                str(out),
                "--prefix=ekw",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        info["returncode"] = proc.returncode
        combined = (proc.stdout or "") + (proc.stderr or "")
        info["stderr_tail"] = combined[-1500:]
        if proc.returncode == 0:
            info["ok"] = True
        else:
            probs = re.findall(r"^\s+-\s+(.*)$", combined, re.M)
            info["problems"] = probs or [
                (
                    combined.strip().splitlines()[-1]
                    if combined.strip()
                    else f"exit {proc.returncode}"
                )
            ]
            kind = (
                "rewardkit_validate_failed"
                if "VALIDATION FAILED" in combined
                else "rewardkit_convert_failed"
            )
            res["findings"].append(
                _finding(
                    kind,
                    "fail",
                    f"rewardkit_convert.py exit {proc.returncode}: {info['problems'][0]}",
                    problems=info["problems"],
                )
            )
    except subprocess.TimeoutExpired:
        info["problems"] = [f"timed out after {timeout}s"]
        res["findings"].append(
            _finding("rewardkit_convert_failed", "fail", info["problems"][0])
        )
    res["rewardkit"] = info
    return info


# ---------------------------------------------------------------------------
# driver
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


def run(
    root: Path,
    task_ids=None,
    id_prefix: str = "",
    stage: Path | None = None,
    rewardkit_out: Path | None = None,
    link: bool = False,
    quiet: bool = False,
    keep_criteria: bool = False,
    jobs: int | None = None,
) -> dict:
    """Programmatic entry point (ekw_run_checks.py uses this). Returns the report dict.
    Tasks are independent, so they run on a thread pool (`jobs`, default one per CPU): the
    work is file copying and one converter subprocess per task, both of which wait on I/O.
    """
    dirs = find_task_dirs(root, task_ids, id_prefix)

    def one(d: Path) -> dict:
        r = check_task(d)
        if stage is not None and r["status"] != "skip":
            stage_task(d, stage, r, link=link)
        if rewardkit_out is not None and r["status"] != "skip":
            run_rewardkit(d, rewardkit_out, r)
        _finalize(r)
        if not keep_criteria:
            r["criteria"] = [
                {
                    "name": c["name"],
                    "kind": c["kind"],
                    "weight": c["weight"],
                    "files": c["files"],
                }
                for c in r["criteria"]
            ]
        return r

    from concurrent.futures import ThreadPoolExecutor

    workers = max(1, jobs or (os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, dirs))
    for r in results:
        if not quiet:
            worst = next(
                (f["message"] for f in r["findings"] if f["severity"] == "fail"), ""
            )
            print(
                f"{r['status']:<4} {r['task_id']:<16} {r['genre'] or '-':<17} fail={r['n_fail']} warn={r['n_warn']} {worst}",
                file=sys.stderr,
            )
    by_kind: dict[str, int] = {}
    genres: dict[str, int] = {}
    for r in results:
        genres[r["genre"] or "unknown"] = genres.get(r["genre"] or "unknown", 0) + 1
        for f in r["findings"]:
            k = f"{f['kind']} [{f['severity']}]"
            by_kind[k] = by_kind.get(k, 0) + 1
    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": str(root),
        "stage": str(stage) if stage else None,
        "rewardkit_out": str(rewardkit_out) if rewardkit_out else None,
        "n_tasks": len(results),
        "n_pass": sum(r["status"] == "pass" for r in results),
        "n_fail": sum(r["status"] == "fail" for r in results),
        "n_skip": sum(r["status"] == "skip" for r in results),
        "genre_counts": genres,
        "findings_by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "results": results,
    }


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="task directory names under --root (omit with --all)",
    )
    ap.add_argument(
        "--all", action="store_true", help="every task directory under --root"
    )
    ap.add_argument(
        "--root",
        required=True,
        help="directory holding one EKW harbor task directory per task",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="with --all, only directories starting with this prefix",
    )
    ap.add_argument(
        "--stage",
        help="write a BUILD-CONTRACT-shaped copy of each task under this directory (outside --root)",
    )
    ap.add_argument(
        "--rewardkit-out",
        help="also run pipeline/tools/rewardkit_convert.py per task into this directory (outside --root)",
    )
    ap.add_argument(
        "--link",
        action="store_true",
        help="hard-link instead of copying files when staging (same filesystem only)",
    )
    ap.add_argument("--out", help="write the JSON report here")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="tasks checked, staged and converted concurrently (default: one per CPU)",
    )
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2
    if not args.all and not args.task_ids:
        sys.stderr.write("give task ids or --all\n")
        return 2
    stage = Path(args.stage) if args.stage else None
    rk = Path(args.rewardkit_out) if args.rewardkit_out else None
    for label, p in (("--stage", stage), ("--rewardkit-out", rk)):
        if p is not None and (_inside(p, root) or _inside(root, p)):
            sys.stderr.write(f"{label} must be outside --root\n")
            return 2

    report = run(
        root,
        args.task_ids or None,
        args.id_prefix,
        stage,
        rk,
        link=args.link,
        quiet=args.quiet,
        jobs=args.jobs,
    )
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {args.out}", file=sys.stderr)
    print(
        f"{report['n_pass']}/{report['n_tasks']} pass, {report['n_fail']} fail, {report['n_skip']} skip; genres {report['genre_counts']}",
        file=sys.stderr,
    )
    for k, n in list(report["findings_by_kind"].items())[:25]:
        print(f"  {n:>4}  {k}", file=sys.stderr)
    return 1 if report["n_fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
