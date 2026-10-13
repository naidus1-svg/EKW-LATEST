#!/usr/bin/env python3
r"""Verifier executability check: can this task's verifier grade ANYTHING at all?

Two mechanical, execution-based sub-checks, both catching defects in the harness itself
rather than in any rubric's wording or any task author's judgement:

1. **Entrypoint parse.** Does `tests/test.sh` -- the real grading entrypoint -- contain CRLF
   line endings? A CRLF shebang (`#!/bin/bash\r`) names an interpreter that does not exist, and
   CRLF anywhere breaks token boundaries under a real (non-Cygwin) bash. This is checked by
   reading raw bytes, NOT by shelling out to `bash -n` on the machine running this check --
   see the "why not bash -n" note below, which is the actual reason this check exists in this
   form rather than the obvious one.

2. **Gold replay (EKW only -- see "Dual format" below for what SVC-PC actually gets).** Copy
   `solution/golden_outputs/*` into a scratch `output/` directory, import THIS TASK'S OWN
   vendored `tests/verifier_lib/`, and call its `run_verifier()` with the LLM judge stubbed to
   approve every rubric call unconditionally. A healthy EKW task's own gold answer must score
   `reward == 1.0` under an approving judge -- anything else (an exception, or a reward below
   1.0) is a mechanical failure in the verifier itself, independent of what any judge would
   actually decide.

   **Measured caveat (2026-09-22) -- what a `reward_below_1_0` here does and does not mean.**
   Run against a plain package directory, the dominant failure reason is
   `required file missing`, NOT a defective golden: only `solution/golden_outputs/*` is staged
   into the scratch `output/`, so every criterion whose source reads anything else cannot
   resolve and is scored as failed. Across the 79 shipped v7 packages this produced
   `reward_below_1_0` on 69 of them, with rewards as low as 0.48 -- none of which corresponds
   to a real rubric defect. Spot-checked against tasks whose genuine golden-fails-own-rubric
   criteria were established by hand in the same session: task_120's real defect is `v6c` but
   gold_replay flags only `v15 (required file missing)`; task_101's are `v1d`/`v7`/`v7b` but it
   flags `v6b`/`v11`/`v14`, all `required file missing`. **The overlap is coincidental -- do not
   read this check's failing-assertion list as the set of criteria the golden fails.** Use
   `pipeline/tools/oracle_golden_check.py` (full workspace, real sources) for that question, and
   `oracle_reproducibility_check.py` for per-criterion instability. What gold_replay reliably
   catches is the mechanical layer: a verifier that crashes, cannot import, or cannot resolve
   its own configured sources. For EKW this is a hard pass/fail gate, not a heuristic: unlike most checks
   in this folder, a failure here means the task cannot be graded correctly no matter how good
   the submission is, so there is no "candidate for human review" status -- a gold replay that
   does not reach reward 1.0 is a confirmed defect by construction. **This "hard gate" guarantee
   does NOT extend to the SVC-PC branch**, which never computes a reward at all -- read the
   "Dual format" section before trusting an SVC-PC "pass" to mean the same thing an EKW "pass"
   means.

**Provenance.** Both sub-checks and the recommendation to combine them into one pre-delivery
gate come from a QC review Pietro Carra's team ran on the Perplexity delivery of this same EKW
corpus (`ekw_structural_review.md`, shared 2026-09-15): "S-1" (37/223 tasks in their corpus
score 0.0 against their own gold, mostly a `"task_id": 300` int where the schema wants a str)
and "S-2" (75/223 tasks ship a CRLF `test.sh`). Verified present in OUR corpus before building
this: 34/274 tasks have `task_id` as an int in `verifier.json`, and 128/274 have CRLF in
`tests/test.sh` -- same defect classes, similar order of magnitude, confirmed by direct
inspection of this repo's own files, not assumed from their numbers.

**Why not `bash -n`.** The obvious way to check "does this entrypoint parse" is to shell out to
`bash -n tests/test.sh` and check the exit code. Tried that first here and it was WRONG: this
dev box's `bash` is Cygwin (`GNU bash ... x86_64-pc-cygwin`), confirmed via `bash --version`,
and Cygwin bash silently tolerates a CRLF shebang and CRLF line endings that a real (non-Cygwin,
i.e. the actual Harbor Linux container) bash rejects. `bash -n` on a known-CRLF file (verified
byte-for-byte: `#!/bin/bash\r\n`) returned exit 0 here -- a false "clean" result that would not
hold in production. Reading the raw bytes for `\r\n` sidesteps this environment mismatch
entirely and gives the same answer regardless of what bash implementation happens to be
installed on whatever machine runs this check.

**Why gold replay is a hard gate here, not a candidate-status check.** Every other script in
this folder that produces a "candidate, not a confirmed defect" finding does so because it is
inferring intent from text (does this criterion test that section, does this rubric leak the
answer) -- a judgement call a human should confirm. This check does not infer anything: it
actually runs the shipped grading code against the shipped gold and reads back the reward the
shipped code itself computed. There is no interpretation step where a false positive could
enter, only environment mismatches (see below), which are reported as their own distinct
outcome rather than folded into "fail."

**Known limitation, reported honestly rather than hidden.** A few source types
(`response.extract_final_message`) read from `agent_logs_dir`, which a gold replay does not
populate with anything (there is no real agent trajectory to replay). If a task's gold replay
fails specifically because of a missing agent-log source, that is a replay-harness limitation,
not necessarily a task defect -- this check reports the failing source/assertion name so a
human can tell the two apart before treating a "reward < 1.0" result as fully confirmed.

**Dual format: EKW and SVC-PC, by design, not by accident.** Format is auto-detected per task
(`tests/verifier.json` present -> EKW; a `tests/**/judge.toml` present -> SVC-PC) and every
sub-check reports its own `not_applicable` when the underlying mechanism genuinely does not
exist for a format, rather than crashing or silently skipping. The two formats are NOT graded
by the same machinery, so "gold replay" means something different in each:

- **EKW**: vendored per-task `verifier_lib`, a Python package this script imports and executes
  directly -- see above.
- **SVC-PC**: `harbor-rewardkit`, a third-party PyPI package (`pip show harbor-rewardkit`, not
  vendored per task) invoked via `rewardkit /tests --output reward.json` in `tests/test.sh`.
  Its `[judge].files` and `[[criterion]].files` entries are LITERAL ABSOLUTE PATHS
  (`"/app/x.xlsx"`, not `"output/x.xlsx"` the way EKW's sources are). `/app/` at grade time is
  NOT populated by `solution/solve.sh` alone -- that script only overlays the golden deliverable
  (`cp -a /solution/files/. /app/`) on top of what `/app/` already starts with, which
  `BUILD-CONTRACT.md` states plainly is `environment/initial_workspace/`'s full contents ("every
  file the solver starts with, actually staged on disk"). This was a real, confirmed bug here
  until 2026-09-16, not just an omission: the file-existence check originally validated
  ONLY against `solution/files/`, and against the real 202-task corpus that produced a
  100% false-positive `referenced_file_missing` outcome on 71/202 (35%) of tasks -- every one
  of their combined 908 "missing" file references (source documents like MSAs, rate cards,
  vendor master lists that a judge cross-checks the deliverable against) was actually present
  under `environment/initial_workspace/`, just not `solution/files/`. Fixed by checking both
  directories (see `_environment_basenames`); a single global `/app` still cannot be safely
  staged per task under this script's own parallel `ProcessPoolExecutor` workers (concurrent
  tasks would collide writing to the same path), but checking file EXISTENCE across two local,
  read-only directories needs no shared mutable state and stays fully parallel-safe. So the
  SVC-PC branch validates two things that need no file I/O beyond local existence checks:
  (1) `rewardkit.discover(tests_dir)` succeeds (verified empirically to need zero real files --
  it only parses TOML and builds `Criterion`/`Reward` objects, which is exactly where a
  malformed `judge.toml` -- SVC-PC's analog of EKW's `"task_id": 300` schema crash -- would
  throw), and (2) every file named in `[judge].files`/`[[criterion]].files` has a same-named
  file under `solution/files/` OR `environment/initial_workspace/`. It does NOT attempt the
  full stubbed-judge `reward == 1.0` replay EKW gets -- that would need either staging gold at
  the literal `/app` path (unsafe under parallelism, see above) or patching `rewardkit`'s
  internal file-reading path resolution, both scoped out here for time. This is a real,
  disclosed scope gap, not a silent one -- see `_gold_replay_svc_pc`'s returned `note`.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import importlib
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ekw_verifier_json  # noqa: E402  (sibling module in this folder)


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


_ENTRYPOINT_SCRIPT_RE = re.compile(
    r'"\$PYTHON_BIN"\s+"\$TESTS_DIR/([A-Za-z0-9_./-]+\.py)"'
)


def _check_entrypoint(task_dir: Path) -> dict[str, Any]:
    """Two checks on tests/test.sh: (1) byte-level CRLF (see module docstring for why this
    is not `bash -n`), and (2) does the .py script test.sh actually execs (e.g.
    verifier_runtime.py) exist on disk. Found empirically necessary on this corpus, not
    hypothetical: of 274 tasks, all 274 reference tests/verifier_runtime.py as their real
    entrypoint, but only 180 actually ship that file -- 94/274 (34%) point test.sh at a
    script that does not exist. Every one of those 94 also fails the gold-replay sub-check
    below for a related reason (an inconsistent verifier_lib package layout), so this does
    not currently change any task's pass/fail verdict -- but it is the cheaper, more direct
    diagnosis (a missing file vs. an ImportError three frames deep) and a future task could
    ship a missing entrypoint with an otherwise-importable verifier_lib, which the gold
    replay alone would not catch."""
    test_sh = task_dir / "tests" / "test.sh"
    if not test_sh.is_file():
        return {"checked": False, "ok": False, "detail": "tests/test.sh not found"}

    raw = test_sh.read_bytes()
    has_crlf = b"\r\n" in raw
    first_nl = raw.find(b"\n")
    shebang_corrupted = (
        has_crlf and first_nl > 0 and raw[first_nl - 1 : first_nl] == b"\r"
    )
    n_crlf = raw.count(b"\r\n") if has_crlf else 0

    text = raw.decode("utf-8", errors="replace")
    m = _ENTRYPOINT_SCRIPT_RE.search(text)
    entrypoint_script = m.group(1) if m else None
    entrypoint_missing = False
    if entrypoint_script:
        entrypoint_missing = not (task_dir / "tests" / entrypoint_script).is_file()

    problems = []
    if has_crlf:
        problems.append(
            "tests/test.sh has CRLF line endings"
            + (
                " -- the shebang itself is corrupted (#!/bin/bash\\r names a nonexistent "
                "interpreter)"
                if shebang_corrupted
                else " -- shebang line is LF but CRLF appears later in the file"
            )
            + f"; {n_crlf} CRLF occurrence(s); will not parse under a standard (non-Cygwin) "
            "bash regardless of what bash -n reports on this machine"
        )
    if entrypoint_missing:
        problems.append(
            f"tests/test.sh execs tests/{entrypoint_script} but that file does not exist "
            "on disk -- this task cannot start grading at all, regardless of verifier.json "
            "or the golden answer"
        )

    return {
        "checked": True,
        "ok": not problems,
        "has_crlf": has_crlf,
        "n_crlf_occurrences": n_crlf,
        "shebang_corrupted": shebang_corrupted,
        "entrypoint_script": entrypoint_script,
        "entrypoint_missing": entrypoint_missing,
        "detail": "; ".join(problems),
    }


def _detect_format(task_dir: Path) -> str:
    """ "ekw" if tests/verifier.json exists, "svc_pc" if any tests/**/judge.toml exists,
    "unknown" otherwise (reported, not raised -- a format this script doesn't recognize is a
    finding, not a crash)."""
    if (task_dir / "tests" / "verifier.json").is_file():
        return "ekw"
    if any(task_dir.glob("tests/**/judge.toml")):
        return "svc_pc"
    return "unknown"


def _environment_basenames(task_dir: Path) -> set[str]:
    """Every file basename anywhere under environment/initial_workspace/ (recursive -- real
    tasks nest files under a build-time subtree like _corpus_subtree/, not always flat).

    Added 2026-09-16 after a real, 100%-confirmed false-positive pattern in
    _gold_replay_svc_pc's missing-files check: BUILD-CONTRACT.md's own package-shape contract
    states plainly that "environment/initial_workspace/ [is] every file the solver starts with,
    actually staged on disk" -- meaning /app/ at grading time is NOT populated by solution/
    solve.sh's `cp -a /solution/files/. /app/` alone, as this module's docstring originally
    assumed; it starts pre-seeded with environment/initial_workspace/'s contents, and solve.sh
    (confirmed by reading it directly: `mkdir -p /app && cp -a /solution/files/. /app/`, nothing
    else) only overlays the golden deliverable on TOP of that. A judge.toml [judge].files or
    [[criterion]].files entry naming a source/reference document (an MSA, a rate card, a vendor
    master list) is legitimately satisfied by the environment, not the solution -- it was never
    meant to be a solver-produced file. Checked against the real corpus before fixing, not
    assumed: every one of the 71/202 (35%) real tasks this check flagged fail in Step 2's full
    run, and all 908 of their combined "missing" file entries, were found to exist somewhere
    under environment/initial_workspace/ -- 0 were genuinely missing from both directories.
    """
    env_dir = task_dir / "environment" / "initial_workspace"
    if not env_dir.is_dir():
        return set()
    return {p.name for p in env_dir.rglob("*") if p.is_file()}


def _gold_replay_svc_pc(task_dir: Path) -> dict[str, Any]:
    """SVC-PC gold-replay analog. See the module docstring's "Dual format" section for why
    this validates config-loading + referenced-file-existence rather than a full stubbed-judge
    reward==1.0 replay."""
    import tomllib

    tests_dir = task_dir / "tests"
    solution_files_dir = task_dir / "solution" / "files"
    env_basenames = _environment_basenames(task_dir)

    try:
        import rewardkit
        import rewardkit.runner as _rk_runner
    except Exception as exc:
        return {
            "outcome": "rewardkit_not_installed",
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc} -- `pip install harbor-rewardkit` required "
            "to run this sub-check",
        }

    # rewardkit's own runner._load_toml does `path.read_text()` with NO explicit encoding,
    # which defaults to the OS locale codec -- cp1252 on Windows. Confirmed empirically:
    # reproduced against a real judge.toml, root-caused to this exact line via traceback, not
    # assumed. This is a tooling artifact of running rewardkit on Windows, not a real defect
    # in the task -- the real Linux grading environment defaults to a UTF-8 locale and would
    # not hit this.
    #
    # NOTE, corrected after an adversarial review caught the original comment overclaiming:
    # most non-ASCII bytes (an em dash, most smart quotes) do NOT raise UnicodeDecodeError
    # under cp1252 -- cp1252 maps almost the full byte range, so they decode "successfully"
    # into the WRONG characters (silent mojibake), which is a bigger, unacknowledged risk than
    # a crash: wrong text would reach rewardkit's TOML parser with no error at all. Only the
    # five cp1252-undefined byte values (0x81, 0x8D, 0x8F, 0x90, 0x9D) actually throw. Scanned
    # against the real SVC-PC corpus (2252 judge.toml files): 562 contain non-ASCII bytes, but
    # only 16 across 13 tasks contain one of the five undefined bytes that would have crashed
    # the unpatched loader -- the other ~546 would have silently fed mis-decoded text into
    # TOML parsing with no error at all. The fix below (always read as UTF-8) correctly
    # resolves all 562 cases, not just the 16 that would have crashed -- it was never narrower
    # than needed, just under-described. Patch the one function for the duration of this call
    # and restore it, rather than mis-report (or silently corrupt) every task with a non-ASCII
    # character in its judge.toml.
    def _load_toml_utf8(path: Path) -> dict[str, Any]:
        with open(path, "rb") as f:
            return tomllib.load(f)

    _original_load_toml = _rk_runner._load_toml
    _rk_runner._load_toml = _load_toml_utf8
    try:
        with tempfile.TemporaryDirectory(prefix="svc_discover_") as scratch_str:
            rewards = rewardkit.discover(str(tests_dir), workspace=scratch_str)
    except Exception as exc:
        return {
            "outcome": "discover_error",
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }
    finally:
        _rk_runner._load_toml = _original_load_toml

    if not rewards:
        return {
            "outcome": "no_rewards_discovered",
            "ok": False,
            "detail": "rewardkit.discover() found zero reward groups under tests/ -- no "
            "judge.toml/reward.toml recognized",
        }

    missing_files: list[dict[str, str]] = []
    referenced: set[str] = set()
    for toml_path in sorted(tests_dir.glob("**/judge.toml")):
        try:
            with open(toml_path, "rb") as f:
                cfg = tomllib.load(f)
        except Exception as exc:
            return {
                "outcome": "judge_toml_unparseable",
                "ok": False,
                "detail": f"{toml_path.relative_to(task_dir)}: {type(exc).__name__}: {exc}",
            }
        file_refs = list(cfg.get("judge", {}).get("files", []))
        for crit in cfg.get("criterion", []):
            file_refs.extend(crit.get("files", []))
        for f in file_refs:
            name = Path(f).name
            referenced.add(name)
            # A referenced file is satisfied by EITHER solution/files/ (the golden deliverable,
            # copied on top by solve.sh) OR environment/initial_workspace/ (what /app/ starts
            # pre-seeded with, per BUILD-CONTRACT.md -- see _environment_basenames's own
            # docstring for the real, 100%-confirmed false-positive pattern this fixes). Only
            # a file in NEITHER is a genuine gap.
            if not (solution_files_dir / name).is_file() and name not in env_basenames:
                missing_files.append(
                    {"judge_toml": str(toml_path.relative_to(task_dir)), "file": f}
                )

    if missing_files:
        return {
            "outcome": "referenced_file_missing",
            "ok": False,
            "detail": f"{len(missing_files)} file(s) named in judge.toml [judge].files or "
            "[[criterion]].files have no same-named file under solution/files/ (the golden "
            "deliverable, copied to /app/ by solve.sh) OR environment/initial_workspace/ (what "
            "/app/ starts pre-seeded with, per BUILD-CONTRACT.md) -- neither source can "
            "populate what the judge is configured to read, so this task cannot be gracefully "
            "graded",
            "missing_files": missing_files,
        }

    return {
        "outcome": "discover_and_files_ok",
        "ok": True,
        "n_reward_groups": len(rewards),
        "n_referenced_files": len(referenced),
        "note": "validates rewardkit.discover() (config/schema loads -- the SVC-PC analog of "
        "EKW's schema-crash S-1) and that every judge-referenced file exists in "
        "solution/files/ or environment/initial_workspace/ (see BUILD-CONTRACT.md -- both are "
        "real sources for what /app/ contains at grading time). Does NOT replay to reward==1.0 "
        "under a stubbed judge -- see module docstring's Dual format section for why.",
    }


def _stub_completion(**_kwargs: Any) -> dict[str, Any]:
    """A LiteLLM-compatible completion function that approves every rubric call
    unconditionally, so a gold replay measures whether the verifier CAN produce reward 1.0,
    not whether a real judge would agree with the gold."""
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "verdict": True,
                            "justification": "gold-replay stub: judge always approves",
                        }
                    )
                }
            }
        ]
    }


def _gold_replay(task_dir: Path) -> dict[str, Any]:
    tests_dir = task_dir / "tests"
    verifier_json = tests_dir / "verifier.json"
    # Both spellings are real -- 47 of the 79 shipped v7 tasks vendor `tests/__verifier_lib/`,
    # 28 vendor `tests/verifier_lib/`. Hardcoding the single-underscore name made gold_replay
    # report `no_verifier_lib` on double-underscore tasks, i.e. it silently never replayed the
    # golden for most of the corpus -- on the one check that can detect "the golden fails its
    # own rubric" WITHOUT a live judge (8 of 30 tasks had exactly that defect on 2026-09-22).
    # See ekw_verifier_json.VERIFIER_LIB_DIR_NAMES.
    lib_dir = ekw_verifier_json.verifier_lib_dir(task_dir)
    lib_module = ekw_verifier_json.verifier_lib_module_name(task_dir)
    golden_dir = task_dir / "solution" / "golden_outputs"

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
    if not golden_dir.is_dir():
        return {"outcome": "no_golden_outputs", "ok": False, "detail": str(golden_dir)}

    # Import THIS task's own vendored verifier_lib in isolation. Safe without extra
    # sys.modules bookkeeping because every ProcessPoolExecutor worker on Windows is a fresh
    # spawned interpreter -- there is no cross-task module-cache collision even though every
    # task's library uses the same top-level package name ("verifier_lib"). If this script is
    # ever run with --jobs 1 (serial, same process for every task), the explicit purge below
    # still makes repeated imports safe.
    sys.path.insert(0, str(tests_dir))
    try:
        for mod_name in list(sys.modules):
            if mod_name == lib_module or mod_name.startswith(lib_module + "."):
                del sys.modules[mod_name]

        try:
            # By the task's OWN package name (`__verifier_lib` or `verifier_lib`), matching what
            # that task's verifier_runtime imports. importlib so both spellings share one path.
            run_verifier = importlib.import_module(f"{lib_module}.runner").run_verifier  # type: ignore
        except Exception as exc:
            return {
                "outcome": "import_error",
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}",
            }

        with tempfile.TemporaryDirectory(prefix="gold_replay_") as scratch_str:
            scratch = Path(scratch_str)
            out_dir = scratch / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            for item in golden_dir.iterdir():
                dest = out_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            verifier_dir = scratch / "verifier_out"
            verifier_dir.mkdir(parents=True, exist_ok=True)
            agent_logs_dir = scratch / "agent_logs"
            agent_logs_dir.mkdir(parents=True, exist_ok=True)

            try:
                payload = run_verifier(
                    verifier_json,
                    workspace_dir=scratch,
                    verifier_dir=verifier_dir,
                    agent_logs_dir=agent_logs_dir,
                    llm_completion=_stub_completion,
                )
            except Exception as exc:
                return {
                    "outcome": "exception",
                    "ok": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                }

        reward = payload.get("reward")
        if reward == 1.0:
            return {"outcome": "reward_1_0", "ok": True, "reward": reward}

        assertion_results = payload.get("assertion_results", [])
        failing = [
            {
                "name": r.get("name"),
                "error": (r.get("result") or {}).get("error"),
                "reason": (r.get("result") or {}).get("reason"),
            }
            for r in assertion_results
            if not (r.get("result") or {}).get("success")
        ]
        return {
            "outcome": "reward_below_1_0",
            "ok": False,
            "reward": reward,
            "detail": f"{len(failing)} of {len(assertion_results)} assertion(s) failed against "
            "the task's own gold under an approving judge",
            "failing_assertions": failing,
        }
    finally:
        try:
            sys.path.remove(str(tests_dir))
        except ValueError:
            pass


def analyze_task(task_dir: Path) -> dict[str, Any]:
    task_id = task_dir.name
    fmt = _detect_format(task_dir)
    entrypoint = _check_entrypoint(task_dir)

    if fmt == "ekw":
        replay = _gold_replay(task_dir)
    elif fmt == "svc_pc":
        replay = _gold_replay_svc_pc(task_dir)
    else:
        replay = {
            "outcome": "unrecognized_format",
            "ok": False,
            "detail": "neither tests/verifier.json (EKW) nor tests/**/judge.toml (SVC-PC) "
            "found -- cannot determine which grading harness applies",
        }

    errors: list[str] = []
    if not entrypoint.get("ok", False):
        errors.append(f"entrypoint: {entrypoint.get('detail', 'not ok')}")
    if not replay.get("ok", False):
        errors.append(
            f"gold_replay ({replay.get('outcome')}): {replay.get('detail', '')}"
        )

    status = "pass" if not errors else "fail"
    return {
        "task_id": task_id,
        "format": fmt,
        "status": status,
        "errors": errors,
        "entrypoint": entrypoint,
        "gold_replay": replay,
    }


def _analyze_task_safe(task_dir: Path) -> dict[str, Any]:
    """Module-level wrapper so ProcessPoolExecutor can pickle it (Windows spawn requires a
    top-level, importable target). Never lets one task's crash kill the whole batch."""
    try:
        return analyze_task(task_dir)
    except Exception as e:
        return {
            "task_id": task_dir.name,
            "format": "unknown",
            "status": "fail",
            "errors": [f"unhandled exception analyzing this task: {e}"],
            "entrypoint": {"checked": False, "ok": False},
            "gold_replay": {
                "outcome": "unhandled_exception",
                "ok": False,
                "detail": str(e),
            },
        }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Check whether each task's verifier can grade ANYTHING: does tests/test.sh "
        "parse under a real (non-Cygwin) bash, and (EKW only) does the task's own gold reach "
        "reward 1.0 against its own verifier under an approving judge. For EKW both are hard "
        "pass/fail gates, not heuristics -- a failure means the task is ungradable regardless "
        "of submission quality. SVC-PC's gold-replay analog does NOT compute a reward -- it "
        "only checks that rewardkit's own config parses and every referenced file exists; see "
        "the module docstring's Dual format section before treating an SVC-PC pass the same "
        "way as an EKW pass."
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
        "serial). Each task's gold replay is independent -- embarrassingly parallel, and "
        "parallelism is also what gives per-task verifier_lib import isolation for free on "
        "Windows spawn (see module docstring).",
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
            "(entrypoint parse + gold replay, each task independent)...",
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

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_entrypoint_fail = sum(
        1 for r in results if not r.get("entrypoint", {}).get("ok", False)
    )
    n_replay_fail = sum(
        1 for r in results if not r.get("gold_replay", {}).get("ok", False)
    )
    by_format: dict[str, dict[str, int]] = {}
    for r in results:
        fmt = r.get("format", "unknown")
        d = by_format.setdefault(fmt, {"n_tasks": 0, "n_pass": 0, "n_fail": 0})
        d["n_tasks"] += 1
        d["n_pass" if r["status"] == "pass" else "n_fail"] += 1

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "n_entrypoint_fail": n_entrypoint_fail,
        "n_gold_replay_fail": n_replay_fail,
        "by_format": by_format,
        "results": results,
    }

    print(
        f"\n{n_pass} pass / {n_fail} fail out of {len(results)} task(s)  "
        f"(entrypoint failures: {n_entrypoint_fail}, gold-replay failures: {n_replay_fail})"
    )
    for fmt, d in sorted(by_format.items()):
        print(
            f"  format={fmt}: {d['n_pass']} pass / {d['n_fail']} fail ({d['n_tasks']} tasks)"
        )
    for r in results:
        if r["status"] != "pass":
            print(f"  {r['task_id']}: FAIL")
            for e in r["errors"]:
                print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
