#!/usr/bin/env python3
"""run_workspace_review.py - GATE-V2 (laptop, 2026-09-18 23:20Z): workspace-
mode Comprehensive Review, replacing the single-shot llm_call.py CR.

The single-shot review (build_cr_context.py -> one CONTEXT.txt -> one
completion) truncates the environment to a ~60K-token budget and has no real
run evidence - it missed everything DataOS's batch-4 rejections found on
SVC-PC-67-1-0/8-2-0 (rewardkit's silent 1 MiB file skip, a leaked near-final
answer document among 119 environment files, a source-name mismatch, an
unsourced rubric value, source files paying reward with no deliverable) - all
things a single truncated text blob cannot show, but a real agent with
Read/Glob/Grep/Bash over the actual files can find directly.

This script instead runs `claude -p` as a real agent: stages the task into a
workspace laid out as `task_files/` / `evaluations/` / `prior_verifications/`
(the layout fix-task-from-review.SKILL.md's own "What you need before
starting" section already documents), sets that workspace as the process cwd,
gives it Read/Glob/Grep/Bash (no Write/Edit - a read-only review, and since
this box runs as root, `--permission-mode bypassPermissions` is refused
outright ("cannot be used with root/sudo privileges"), confirmed empirically
2026-09-18 - `--permission-mode dontAsk` is the unattended-safe substitute
that does not hit that restriction), and reads the exact canon
ekw-svc-comprehensive-review.md with only its "workspace-layout skill"
paragraph replaced by a paragraph naming these actual three directories (see
tools/prompts/ekwqc/ekw-svc-comprehensive-review.workspace-mode.md - built by
a verified byte-identical substitution, nothing else in the canon text
touched).

Output: writes --out (the CR.json-shape file, section 5's JSON, same as the
old run_blind_cr) and --out.raw.txt (the full final-message text), plus
--stats-out (tool_calls, token usage, cost - for GATE.md to report per
round). Exit 0 on success (CR.json-shape written and parses), non-zero
otherwise, matching llm_call.py's own contract so gate_task.sh's existing
`if ! run_blind_cr ...; then park; fi` callers need no changes.

Usage:
    python3 run_workspace_review.py --task SVC-PC-X --corpus-root PATH \
        --workspace-root PATH --runs-root PATH --pipe-dir PATH \
        --out CR.json --stats-out CR_STATS.json [--timeout 2400] [--model opus]
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm_call import extract_json_object  # noqa: E402 - reuse the already-fixed extractor

CANON_WORKSPACE_MODE = (
    Path(__file__).resolve().parent
    / "prompts"
    / "ekwqc"
    / "ekw-svc-comprehensive-review.workspace-mode.md"
)

# Verbatim from stage_and_zip.sh / gate_task.sh's checkfix_stage_and_run - keep
# this exclude list in lockstep by hand if either of those changes; it exists
# in three places now for the same reason checkfix_classify's GATE/ADVISORY
# sets do (never diverge on what a "clean" staged copy looks like).
RSYNC_EXCLUDES = [
    "_prior", "_runs", "FIX-LOG*.md", "REFUTER*.md", "CR-REFUTER.md", "_scratch",
    "COMPREHENSIVE-REVIEW.md", "GATE.md", "*.round1", "*.round2", "*.bak", "*.bak-*",
    "__pycache__", "_golden_*", "_conv_test*", "__img_embed_test__*",
    "capacity_tmp_conv.*", ".DS_Store",
]


def stage_task_files(corpus_root: Path, task: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-a", "--delete"]
    for pat in RSYNC_EXCLUDES:
        cmd += [f"--exclude={pat}"]
    cmd += [f"{corpus_root / task}/", f"{dest}/"]
    subprocess.run(cmd, check=True)


def compute_task_files_manifest(task_files_dir: Path) -> str:
    """GATE-V2 (laptop, 2026-09-19 01:50Z): sha256 over the sorted lines
    'relpath sha256(file)' of every file under task_files/ - the actuator
    recomputes this same manifest over its own staging and refuses to zip
    (exit 11) unless it matches, so a zip can only ever contain the exact
    bytes the last review saw. Exact algorithm, mirrored byte-for-byte:
    os.walk(task_files), lines = relpath + ' ' + sha256(bytes), digest =
    sha256('\\n'.join(sorted(lines)).encode())."""
    lines = []
    for root, _dirs, files in os.walk(task_files_dir):
        for name in files:
            p = Path(root) / name
            relpath = str(p.relative_to(task_files_dir))
            file_hash = hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append(f"{relpath} {file_hash}")
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


def write_reviewed_manifest(pipe_dir: Path, digest: str) -> None:
    utc_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pipe_dir.mkdir(parents=True, exist_ok=True)
    (pipe_dir / "REVIEWED_MANIFEST.sha256").write_text(f"{digest} {utc_time}\n")


def _classify_run_status(glm_dir: Path) -> str:
    """FOR-PIPE2.md item 4: separate judge-TRANSPORT failure (the judge call
    itself was refused/too-long - a criterion-level zero that says nothing
    about the deliverable's content) from a genuine SOLVER crash (no
    deliverable was ever produced) or a real rubric-driven grade. One line
    per glm-N run, for RUN_STATUS.md."""
    exit_code_f = glm_dir / "claude_exit_code.txt"
    exit_code = exit_code_f.read_text().strip() if exit_code_f.is_file() else "?"
    run_log = (glm_dir / "run.log").read_text(errors="replace") if (glm_dir / "run.log").is_file() else ""
    reward_f = glm_dir / "reward-details.json"

    if "multimodal processing is not enabled" in run_log:
        return f"SOLVER CRASH (exit={exit_code}): provider rejected the run ('multimodal processing is not enabled') - no deliverable was produced. Any reward computed from this run's app/ is not evidence of rubric quality."
    if exit_code not in ("0", "?") and exit_code != "0":
        app_dir = glm_dir / "app"
        n_files = sum(1 for _ in app_dir.rglob("*") if _.is_file()) if app_dir.is_dir() else 0
        if n_files <= 1:  # just instruction.md, no real deliverable
            return f"SOLVER CRASH (exit={exit_code}): app/ has {n_files} file(s), no real deliverable produced."

    if reward_f.is_file():
        try:
            d = json.loads(reward_f.read_text())
        except json.JSONDecodeError:
            d = {}
        errors = []
        for g in d.get("groups", []):
            for c in g.get("criteria", []):
                err = c.get("error") or ""
                if "Prompt is too long" in err or "too long" in err.lower():
                    errors.append(c.get("name"))
        if errors:
            return (f"JUDGE TRANSPORT FAILURE: {len(errors)} criteria ({', '.join(errors[:5])}"
                    f"{'...' if len(errors) > 5 else ''}) zeroed by the judge call itself refusing "
                    f"('Prompt is too long'), not by the deliverable's content - total_reward="
                    f"{d.get('total_reward')} on this run is not a rubric-quality signal for those criteria.")
        return f"graded normally: total_reward={d.get('total_reward')}"
    return f"no reward-details.json (exit={exit_code})"


def stage_evaluations(runs_root: Path, pipe_dir: Path, task: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    status_lines = ["# RUN_STATUS.md - judge-transport failure vs solver crash vs real grade",
                     "# (FOR-PIPE2.md item 4: gather_both_failed.py hands a judge-transport zero",
                     "# to the Opus adjudicator as \"both runs failed this criterion\" - a false",
                     "# premise. Read this before treating any run's low reward as rubric evidence.",
                     ""]
    for glm_dir in sorted(glob.glob(str(runs_root / task / "glm-*"))):
        name = Path(glm_dir).name
        target = dest / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(glm_dir, target)
        status_lines.append(f"## {name}\n{_classify_run_status(Path(glm_dir))}\n")
    (dest / "RUN_STATUS.md").write_text("\n".join(status_lines))

    for name, rel in (
        ("oracle.json", Path("probes") / "oracle.json"),
        ("echo.json", Path("probes") / "echo.json"),
        ("echo_deliverable.txt", Path("probes") / "echo_deliverable.txt"),
        ("nocache.json", Path("probes") / "nocache.json"),
    ):
        src = pipe_dir / rel
        if src.is_file():
            shutil.copy2(src, dest / name)


def stage_prior_verifications(pipe_dir: Path, task: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    # verifier spec item 3 (FOR-PIPE2.md, 2026-09-19): scan_summary.csv is the
    # 13-scan file; checks/recheck/summary.csv is the 45-check file, and it is
    # the one carrying judge_scope_over_inclusion / judge_file_size_cliff /
    # source_truncation - the reviewer had never seen any of them. Stage both
    # (scan_summary.csv kept for backward compatibility, nothing reads it
    # exclusively), plus this task's own row from the corpus-wide leak scan.
    for name, src in (
        ("summary.csv", pipe_dir / "checks" / "scan_summary.csv"),
        ("recheck_summary.csv", pipe_dir / "checks" / "recheck" / "summary.csv"),
    ):
        if src.is_file():
            shutil.copy2(src, dest / name)

    leak_csv = Path("/root/qc/_prompts/golden_leak_scan.csv")
    if leak_csv.is_file():
        with open(leak_csv, newline="") as f:
            reader = csv.DictReader(f)
            rows = [r for r in reader if r.get("task") == task]
        if rows:
            with open(dest / "golden_leak_scan_row.csv", "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)


GLM_BASE_URL = "http://34.41.10.8:4000"
GLM_MODEL = "glm-5.2"
GLM_KEYS_FILE = Path("/root/.glm_keys")

REVIEWER_MODELS = {
    "glm": GLM_MODEL,
    "sonnet": "claude-sonnet-4-6",
    "opus": "opus",
}


def _glm_auth_token() -> str:
    if not GLM_KEYS_FILE.is_file():
        raise RuntimeError(f"{GLM_KEYS_FILE} not found - cannot run --reviewer glm")
    for line in GLM_KEYS_FILE.read_text().splitlines():
        k = line.strip()
        if k and not k.startswith("#"):
            return k
    raise RuntimeError(f"{GLM_KEYS_FILE} has no usable key")


def run_claude_agentic(workspace: Path, prompt: str, reviewer: str, timeout: int) -> dict:
    """Runs `claude -p` in workspace-mode (stream-json) as one of three
    reviewer identities and returns {"final_text": str, "tool_calls": int,
    "usage": dict|None, "total_cost_usd": float|None, "is_error": bool,
    "raw_lines": list[dict]}. Raises RuntimeError on a hard failure (nonzero
    exit with no result line, a timeout, or an unknown reviewer).

    Reviewer-agnostic (Khiem's direction, laptop 2026-09-18 23:55Z):
      - "glm": through the GLM proxy, exactly as tools/solver_batch.sh
        launches a GLM solver run - same env vars (IS_SANDBOX=1,
        CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000, ANTHROPIC_BASE_URL, the first
        key in /root/.glm_keys as ANTHROPIC_AUTH_TOKEN), same model
        (glm-5.2), same --dangerously-skip-permissions.
      - "sonnet" / "opus": a normal Max-lane session (this process's own
        CLAUDE_CONFIG_DIR/OAuth login), model claude-sonnet-4-6 / opus.

    `--dangerously-skip-permissions` (not `--permission-mode dontAsk`, the
    earlier choice): confirmed empirically (2026-09-18) that the "cannot be
    used with root/sudo privileges" refusal is specifically lifted by
    IS_SANDBOX=1 - this is what solver_batch.sh's own GLM invocation already
    relies on, so using it here too for all three reviewers, not just glm,
    keeps one permission story instead of two.
    """
    if reviewer not in REVIEWER_MODELS:
        raise RuntimeError(f"unknown reviewer {reviewer!r} - must be one of {sorted(REVIEWER_MODELS)}")
    model = REVIEWER_MODELS[reviewer]

    env = dict(os.environ)
    env["IS_SANDBOX"] = "1"
    if reviewer == "glm":
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "64000"
        env["ANTHROPIC_BASE_URL"] = GLM_BASE_URL
        env["ANTHROPIC_AUTH_TOKEN"] = _glm_auth_token()

    args = [
        "claude", "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--tools", "Read,Glob,Grep,Bash",
        "--dangerously-skip-permissions",
        "--model", model,
    ]
    try:
        proc = subprocess.run(
            args, input=prompt, cwd=str(workspace), env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"workspace-mode review ({reviewer}) timed out after {timeout}s") from exc

    tool_calls = 0
    final_result_line: dict | None = None
    raw_lines: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw_lines.append(obj)
        if obj.get("type") == "assistant":
            for block in obj.get("message", {}).get("content", []) or []:
                if block.get("type") == "tool_use":
                    tool_calls += 1
        elif obj.get("type") == "result":
            final_result_line = obj

    if final_result_line is None:
        stderr_tail = proc.stderr.strip()[-2000:]
        raise RuntimeError(
            f"no final result line in stream-json output (exit {proc.returncode}); "
            f"stderr tail: {stderr_tail}"
        )

    return {
        "final_text": final_result_line.get("result", "") or "",
        "tool_calls": tool_calls,
        "usage": final_result_line.get("usage"),
        "total_cost_usd": final_result_line.get("total_cost_usd"),
        "num_turns": final_result_line.get("num_turns"),
        "is_error": bool(final_result_line.get("is_error")),
        "raw_lines": raw_lines,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--corpus-root", type=Path, required=True)
    ap.add_argument("--workspace-root", type=Path, required=True,
                     help="parent dir; the workspace itself is <workspace-root>/<task>/")
    ap.add_argument("--runs-root", type=Path, required=True)
    ap.add_argument("--pipe-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stats-out", type=Path, required=True)
    ap.add_argument("--reviewer", choices=sorted(REVIEWER_MODELS), default="opus",
                     help="glm (proxy, glm-5.2) | sonnet (Max lane, claude-sonnet-4-6) | opus (Max lane) - "
                          "default ship rule uses glm+sonnet; opus is fix-plan-only, kept here for calibration/acceptance runs")
    ap.add_argument("--timeout", type=int, default=2400)
    args = ap.parse_args()

    workspace = args.workspace_root / args.task
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "artifacts").mkdir(exist_ok=True)

    stage_task_files(args.corpus_root, args.task, workspace / "task_files")
    task_files_manifest = compute_task_files_manifest(workspace / "task_files")
    write_reviewed_manifest(args.pipe_dir, task_files_manifest)
    stage_evaluations(args.runs_root, args.pipe_dir, args.task, workspace / "evaluations")
    stage_prior_verifications(args.pipe_dir, args.task, workspace / "prior_verifications")

    # Verifier spec item 1 (FOR-PIPE2.md, 2026-09-19): the ONE deterministic
    # check that finds what no amount of reading can (the 1 MiB rewardkit
    # skip) - run it fresh for every review and stage its output into
    # prior_verifications/ so the reviewer confirms it under 1.2/1.5 instead
    # of hunting for it. Must run under /root/venv's interpreter (rewardkit
    # lives there) - shells out with sys.executable so this works whether or
    # not the CALLING process itself has the venv activated.
    judge_input_path = args.pipe_dir / "probes" / "judge_input.json"
    judge_input_path.parent.mkdir(parents=True, exist_ok=True)
    jir_proc = subprocess.run(
        [sys.executable if "venv" in sys.executable else "/root/venv/bin/python3",
         str(Path(__file__).resolve().parent / "judge_input_report.py"),
         "--task", args.task, "--corpus-root", str(args.corpus_root),
         "--out", str(judge_input_path)],
        capture_output=True, text=True,
    )
    if jir_proc.returncode != 0:
        print(f"WARNING: judge_input_report.py failed (exit {jir_proc.returncode}): "
              f"{jir_proc.stderr.strip()[:2000]}", file=sys.stderr)
    elif judge_input_path.is_file():
        shutil.copy2(judge_input_path, workspace / "prior_verifications" / "judge_input.json")

    if not CANON_WORKSPACE_MODE.is_file():
        print(f"ERROR: {CANON_WORKSPACE_MODE} not found", file=sys.stderr)
        return 2
    prompt = CANON_WORKSPACE_MODE.read_text().replace("{{TASK_ID}}", args.task)
    _add = Path("/root/qc/tools/prompts/ekwqc/thorough-addendum.md")
    if _add.is_file():
        prompt += "\n" + _add.read_text()
    # The canon doc itself has no {{TASK_ID}} placeholder (it derives task_id
    # from task.toml / the directory name per its own §5 instruction) - the
    # .replace above is a harmless no-op unless a future edit adds one.

    raw_path = args.out.with_suffix(args.out.suffix + ".raw.txt")
    # Bug fixed here (2026-09-19): naming by task+reviewer alone collides
    # whenever the same task+reviewer runs more than once - concurrently
    # (confirmed: 3 acceptance rounds of the same task overwrote each
    # other's transcript, only the last writer survived) or sequentially
    # (round0 then a later round1 re-review, which bulk_review.sh does).
    # --out's own stem is already unique per invocation by convention (every
    # caller names it per-round: CR.<reviewer>.roundN.json, <task>.rN.json),
    # so derive the transcript name from --out instead of task+reviewer, with
    # the PID appended as a last-resort disambiguator if two callers still
    # somehow share one --out stem.
    transcript_path = args.pipe_dir / "checks" / f"WORKSPACE_TRANSCRIPT_{args.out.stem}_{os.getpid()}.jsonl"
    try:
        result = run_claude_agentic(workspace, prompt, args.reviewer, args.timeout)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(result["final_text"])
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with open(transcript_path, "w") as f:
        for obj in result["raw_lines"]:
            f.write(json.dumps(obj) + "\n")

    stats = {
        "tool_calls": result["tool_calls"],
        "num_turns": result["num_turns"],
        "usage": result["usage"],
        "total_cost_usd": result["total_cost_usd"],
        "is_error": result["is_error"],
        "transcript": str(transcript_path),
        "task_files_manifest": task_files_manifest,
    }
    args.stats_out.parent.mkdir(parents=True, exist_ok=True)
    args.stats_out.write_text(json.dumps(stats, indent=2))

    if result["is_error"]:
        print(f"ERROR: claude -p reported is_error=true, see {raw_path}", file=sys.stderr)
        return 4

    obj = extract_json_object(result["final_text"])
    if obj is None:
        print(f"ERROR: no valid JSON object found in the final message, see {raw_path}", file=sys.stderr)
        return 5

    args.out.write_text(json.dumps(obj, indent=2))
    print(f"wrote {args.out} (tool_calls={result['tool_calls']}, "
          f"tokens={result['usage']}, cost=${result['total_cost_usd']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
