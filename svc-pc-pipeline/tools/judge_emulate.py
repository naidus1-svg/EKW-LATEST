#!/usr/bin/env python3
"""
judge_emulate.py - GATE-V2 3.1 judge emulator ("Z owns it; Sonnet writes it").

Grades a single SVC-PC task's deliverable the same way DataOS's rewardkit-based
verifier does, but with the actual judge call routed through the Claude Code CLI
(Max-plan compute, no API key) instead of a live litellm/API call. Built so an
oracle run (golden vs. its own rubric), a deliverable run, or an echo-probe run
can be scored locally before a task ever reaches DataOS - see GATE-V2.md 3.1.

WHY THIS FILE IS SAFE TO RUN AT WILL
-------------------------------------
- Read-only against the corpus: only ever opens files under <task>/tests/,
  <task>/instruction.md, and (oracle mode) <task>/solution/files/. Never writes
  under a task directory. `--dry-run` makes zero LLM calls of any kind.
- No API key, ever. The CLI backend is forced (`LLM_BACKEND_FORCE=cli`); if the
  Claude Code CLI is unavailable or not logged in, the call fails loudly rather
  than falling back to a paid HTTP backend.

WHAT IT REUSES FROM THE REAL STACK, VERBATIM (not reimplemented)
------------------------------------------------------------------
- Extraction: `rewardkit.judges._build_user_content` / `_read_file_blocks` /
  `_text_from_blocks` (harbor-rewardkit 0.2.0, installed in /root/venv). Same
  MarkItDown xlsx/docx conversion, same 1 MB file-size skip, same "--- <path>
  ---\\n<text>" framing DataOS's own judge sees.
- Prompt assembly: `rewardkit.judges.build_prompt` / `_build_criteria_block`,
  so the criteria block and the "respond with this JSON shape" instruction are
  byte-identical to what rewardkit's own LLMJudge sends.
- Response parsing + per-criterion normalization: `rewardkit.judges.
  parse_judge_response` (handles the flat single-criterion shape, `negate`,
  `optional`, and each `OutputFormat.normalize()` - binary/likert/numeric).
- Discovery + weighting + aggregation: `rewardkit.runner._discover_layout`,
  `_score_layout`, `_layout_details`, `_group_weights`, `_group_aggregation`
  (handles weighted_mean / all_pass / any_pass / threshold / required_pass,
  per-group reward.toml weights, and the root [[reward]] combination) and
  `rewardkit.reward.aggregate_scores`. This script never recomputes a mean or
  a weight by hand; it hands rewardkit's own Reward objects a `.scores` list
  and lets rewardkit's own `.score` property and runner functions do the math.
- CLI backend: `tools.llm_backend.call_llm` from
  /root/ekwqc/deterministic-checks (the exact function golden_groundedness_check.py
  and svc_run_checks.py's LLM checks call) - same `claude -p --output-format
  json` subprocess, same stdin-not-argv prompt handling, same CLAUDE_CODE_MODEL
  env var for model selection.

WHAT THIS SCRIPT ADDS (the only "new" logic)
-----------------------------------------------
- Path remapping: judge.toml `files = ["/app/X.xlsx"]` always names an absolute
  in-container path. This script has no /app; it remaps the "/app" prefix onto
  whatever directory is standing in for the deliverable (golden's solution/files/
  for oracle, or the given directory for `deliverable`) and hands the REMAPPED
  path to rewardkit's own `_build_user_content` unmodified. If the stand-in
  directory doesn't mirror judge.toml's path exactly, `_build_user_content`
  reports "[not found]" for that file - the same signal a real solver run gets
  for a missing deliverable, not a bug in this script.
- Bucketing: batches all criteria that share the same effective file scope
  (`criterion.files or judge.files`) into one CLI call, to hit "about one call
  per judge group" (GATE-V2 3.1). In this corpus every group's criteria share
  one file scope, so this is exactly one call per deliverables_NN group.
- Echo mode: replaces every group's file scope with the single echo file,
  regardless of what judge.toml names - the echo probe is graded as if it
  were every deliverable at once, per GATE-V2 3.1's definition ("assertions
  restated, no figures").
- Must-pass prose-vs-enforcement diagnostic: flags any criterion whose
  description says "must-pass" while its group's rewardkit aggregation is
  still weighted_mean (GATE-V2 class H - prose with no real gate).

MODES
-----
  oracle       <task>                 grade <task>/solution/files/* (golden)
  deliverable  <task> <dir>           grade an arbitrary deliverable directory
  echo         <task> <file>          grade a single echo-probe file against
                                       every judge group

FLAGS
-----
  --dry-run           build every prompt, print it, make NO CLI call
  --max-criteria N    stop issuing new CLI calls once N criteria have been
                       covered (a whole judge-group bucket is still issued as
                       one call, so the count can slightly exceed N); every
                       criterion beyond the budget gets a synthetic 0.0 score
                       with error="skipped: --max-criteria budget exhausted"
  --model MODEL        explicit `claude --model` override; when omitted, each
                       judge group uses ITS OWN rubric's judge model
                       (LLMJudge.model, i.e. judge.toml's `[judge] judge =`
                       field - the same value rewardkit's own verifier reads),
                       stripped of a leading "anthropic/" prefix, falling back
                       to "claude-sonnet-4-6" if that field is absent
  --timeout SECONDS     per-CLI-call timeout (default: 900)
  --corpus-root PATH    default /root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
  --out FILE             also write the JSON result to FILE

OUTPUT
------
JSON to stdout (and --out if given), shaped:
  {
    "task": "SVC-PC-29-2-0", "mode": "oracle", "total_reward": 0.97,
    "groups": [
      {"name": "deliverables_01", "weight": 0.2823, "score": 1.0,
       "aggregation": "weighted_mean",
       "must_pass_prose_but_unenforced": ["r001", "r003", "r012"],
       "criteria": [
         {"id": null, "name": "r001", "weight": 0.0245, "passed": true,
          "value": 1.0, "verdict_text": "...", "error": null}, ...
       ]}, ...
    ],
    "warnings": [...],
    "dry_run": false,
    "rewardkit_native": {"main": {...}, "details": {...}}
  }
`rewardkit_native` is rewardkit's own `_score_layout`/`_layout_details` output,
directly comparable to a real DataOS `reward-details.json` in shape (see
judge_emulate.README.md for exactly how the arithmetic composes).

Requires: run with /root/venv's python (harbor-rewardkit 0.2.0 installed there).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_CORPUS_ROOT  # noqa: E402
from judge_input_report import (
    build_app_root,
)  # noqa: E402 - verifier spec item 2, 2026-09-19

try:
    from rewardkit.judges import (
        build_prompt,
        _build_user_content,
        _text_from_blocks,
        parse_judge_response,
    )
    from rewardkit.models import AgentJudge, Criterion, LLMJudge, Score
    from rewardkit import runner as rk_runner
except ImportError as exc:  # pragma: no cover - environment problem, not a bug
    sys.stderr.write(
        "ERROR: harbor-rewardkit not importable. Run this script with "
        "/root/venv/bin/python3 (rewardkit 0.2.0 is installed there), e.g.:\n"
        "  /root/venv/bin/python3 /root/qc/tools/judge_emulate.py ...\n"
        f"(underlying error: {exc})\n"
    )
    raise SystemExit(2)

# Env override first, then the QC sandbox path, then this repo's own deterministic-checks/ (team repo layout:
# svc-pc-pipeline/tools/judge_emulate.py -> ../../deterministic-checks).
DETCHECKS_DIR = os.environ.get("DETCHECKS_DIR") or next(
    (
        d
        for d in (
            "/root/ekwqc/deterministic-checks",
            str(Path(__file__).resolve().parents[2] / "deterministic-checks"),
        )
        if os.path.isdir(d)
    ),
    "/root/ekwqc/deterministic-checks",
)
sys.path.insert(0, DETCHECKS_DIR)
try:
    from tools.llm_backend import call_llm, LLMBackendError  # noqa: E402
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        f"ERROR: could not import tools.llm_backend from {DETCHECKS_DIR} "
        f"(underlying error: {exc})\n"
    )
    raise SystemExit(2)

# GATE-V2 (laptop, 2026-09-19 02:11Z): SVC-PC-11-4-0's oracle probe returned
# total_reward=0.0 with every criterion's judge_output="" because lane d hit
# its Claude Max session limit mid-run - every LLMBackendError got silently
# turned into a synthetic value=0.0 score by run_bucket's except clause below,
# indistinguishable from a genuine golden failure. An infra refusal (session/
# usage/rate limit, overloaded) must never be scored as 0.0 - same pattern
# gate_task.sh's own LIMIT_RE/lane_refused() already use for exactly this
# failure class, kept in lockstep by hand.
import re  # noqa: E402

LANE_REFUSED_RE = re.compile(
    r"usage limit|session limit|weekly limit|hit your [a-z ]*limit|rate.?limit|"
    r"too many requests|resets [0-9]|resets [A-Z][a-z]{2} [0-9]|overloaded",
    re.IGNORECASE,
)


class InfraRefusalError(RuntimeError):
    """Raised (never caught into a synthetic score) when a judge call failed
    because the LANE was refused, not because the judge ran and produced a
    real verdict. Propagates all the way to main(), which writes
    total_reward=null + error, never a numeric 0.0."""


# 2026-09-29: 300 s was too short for large judge inputs through the CLI backend. SVC-PC-94-0-0 hit it 71
# times since 09-24 and SCO-205 parked on it, while DataOS's own grader scored both goldens 1.0 on every judge
# group with no timeout (batch10b/batch50, batch49/batch56). Two attempts at 900 s still fit the runners'
# 2400 s outer timeout.
DEFAULT_TIMEOUT = 900
# Fallback ONLY - used when a judge group's own LLMJudge.model field is
# somehow empty. Every real corpus judge.toml sets [judge] judge =
# "anthropic/claude-sonnet-4-6", and rewardkit's own LLMJudge.model default
# (models.py:242) is the same value, so this is never a silent divergence
# from the rubric in practice.
FALLBACK_MODEL = "claude-sonnet-4-6"


def resolve_model(explicit_override: str | None, judge_model_field: str | None) -> str:
    """--model, when passed on the CLI, is an explicit override and always
    wins. Otherwise, use the judge group's OWN rubric value: LLMJudge.model,
    populated straight from judge.toml's `[judge] judge = "..."` field. Strip
    a leading "anthropic/" prefix (the claude -p CLI backend takes a bare
    model id, e.g. CLAUDE_CODE_MODEL=claude-sonnet-4-6). Never hardcode a
    specific model as the default here - fall back to FALLBACK_MODEL only if
    the rubric's own field is missing or empty."""
    if explicit_override:
        return explicit_override
    model = judge_model_field or ""
    if model.startswith("anthropic/"):
        model = model[len("anthropic/") :]
    return model or FALLBACK_MODEL


# ---------------------------------------------------------------------------
# Task / path resolution
# ---------------------------------------------------------------------------


def resolve_task_dir(task_arg: str, corpus_root: Path) -> Path:
    """A bare task id resolves under corpus_root; an existing path is used as-is."""
    p = Path(task_arg)
    if p.is_dir():
        return p
    candidate = corpus_root / task_arg
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(
        f"task directory not found: neither {task_arg!r} nor {candidate} exists"
    )


def remap_app_path(file_path: str, content_root: Path) -> str:
    """Remap a judge.toml '/app/...' path onto content_root.

    judge.toml (and criterion-level `files=[...]`) always name absolute
    in-container paths rooted at /app - there is no real /app here, so this
    substitutes whatever directory is standing in for the deliverable
    (golden solution/files/ for oracle, the given directory for `deliverable`).
    A path that is NOT under /app is left untouched (defensive; not observed
    in this corpus, but a `judge.reference` or an absolute non-/app path
    should not be silently mangled).
    """
    pp = PurePosixPath(file_path)
    try:
        rel = pp.relative_to("/app")
    except ValueError:
        return file_path
    return str(content_root / rel)


# ---------------------------------------------------------------------------
# Bucketing: group criteria within one Reward by effective file scope
# ---------------------------------------------------------------------------


def effective_files(judge: "LLMJudge", criterion: "Criterion") -> tuple[str, ...]:
    """A criterion's own `files=[...]` overrides the judge-level `files=[...]`,
    exactly as rewardkit.judges.arun_llm's individual-mode path does (judges.py
    line ~338: `c.files or judge.files`)."""
    return criterion.files or judge.files


def bucket_criteria(
    judge: "LLMJudge",
    criteria: list["Criterion"],
    weights: list[float],
    echo_file: str | None,
) -> list[tuple[tuple[str, ...], list[int]]]:
    """Group criterion indices by effective file scope. In echo mode every
    criterion is forced into a single bucket keyed on the echo file, since the
    echo probe is graded as if it were every deliverable at once."""
    if echo_file is not None:
        return [((echo_file,), list(range(len(criteria))))]
    buckets: dict[tuple[str, ...], list[int]] = {}
    order: list[tuple[str, ...]] = []
    for i, c in enumerate(criteria):
        key = effective_files(judge, c)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(i)
    return [(key, buckets[key]) for key in order]


# ---------------------------------------------------------------------------
# One CLI call per bucket
# ---------------------------------------------------------------------------


class BudgetExhausted(Exception):
    pass


def _synthetic_error_scores(
    criteria: list["Criterion"], weights: list[float], message: str
) -> list["Score"]:
    return [
        Score(
            name=getattr(c, "name", None)
            or getattr(c, "__name__", None)
            or f"criterion_{i}",
            value=0.0,
            raw=None,
            weight=weights[i] if weights else 1.0,
            error=message,
            # Score.description is a str; a criterion without one used to pass None, so the error path itself
            # raised a pydantic ValidationError and the oracle CRASHED instead of scoring 0 (10-4-0, 35-0-0).
            description=getattr(c, "description", None) or "",
            id=getattr(c, "id", None),
            negate=bool(getattr(c, "negate", False)),
            optional=bool(getattr(c, "optional", False)),
        )
        for i, c in enumerate(criteria)
    ]


def run_bucket(
    bucket_files: tuple[str, ...],
    bucket_criteria_objs: list["Criterion"],
    bucket_weights: list[float],
    *,
    model: str,
    timeout: int,
    dry_run: bool,
    prompt_log: list[dict[str, Any]],
) -> list["Score"]:
    """Build the prompt for one bucket (rewardkit's own functions, unmodified),
    then either print it (dry-run) or call the CLI and parse the response."""
    system_prompt = build_prompt(bucket_criteria_objs)
    blocks = _build_user_content(bucket_files)
    user_text = _text_from_blocks(blocks)

    entry = {
        "files": list(bucket_files),
        "criteria": [c.name for c in bucket_criteria_objs],
        "system_prompt": system_prompt,
        "user_text_chars": len(user_text),
        "user_text_preview": user_text[:3000],
    }
    prompt_log.append(entry)

    if dry_run:
        return _synthetic_error_scores(
            bucket_criteria_objs, bucket_weights, "dry-run: no CLI call made"
        )

    prev_model = os.environ.get("CLAUDE_CODE_MODEL")
    prev_force = os.environ.get("LLM_BACKEND_FORCE")
    os.environ["CLAUDE_CODE_MODEL"] = model
    os.environ["LLM_BACKEND_FORCE"] = "cli"  # never fall through to a paid HTTP backend
    # A reply that does not parse as the judge JSON is a transport glitch, not a verdict: retry the call up to
    # PARSE_RETRIES times before scoring the bucket as an error. 2026-09-23: single malformed replies ("Expecting
    # ',' delimiter") zeroed whole criteria groups on 25-2-0, 15-5-0, 92-3-0, 19-6-0 and burned fix attempts on
    # goldens that scored 1.0 on the very next run.
    PARSE_RETRIES = 3

    # 2026-09-23: SVC-PC-21-0-0's judge group exceeds the CLI model's context ("Prompt is too long"). That is a
    # local-grader limit, not a lane cap and not a golden defect, yet it surfaced as an "infra refusal" and the
    # runner released the task 7 times as "lane capped". Retry that one group once on the 1M-context Sonnet alias
    # (included in the Max plan; the pinned "claude-sonnet-4-6[1m]" id asks for paid usage credits - never use it)
    # and record the substitution so nobody mistakes it for the rubric's own judge model.
    LONG_PROMPT_MODEL = "sonnet[1m]"

    def _judge_call():
        try:
            return call_llm(user_text, system=system_prompt, timeout=timeout)
        except LLMBackendError as exc:
            if (
                "prompt is too long" not in str(exc).lower()
                or os.environ.get("CLAUDE_CODE_MODEL") == LONG_PROMPT_MODEL
            ):
                raise
            entry["judge_model_substituted"] = "%s -> %s (prompt too long for %s)" % (
                model,
                LONG_PROMPT_MODEL,
                model,
            )
            os.environ["CLAUDE_CODE_MODEL"] = LONG_PROMPT_MODEL
            return call_llm(user_text, system=system_prompt, timeout=timeout)

    try:
        for _parse_try in range(PARSE_RETRIES):
            raw = _judge_call()
            try:
                parsed = parse_judge_response(raw, bucket_criteria_objs, bucket_weights)
                entry["raw_response"] = raw
                if _parse_try:
                    entry["parse_retries"] = _parse_try
                return parsed
            except ValueError as exc:
                entry.setdefault("parse_errors", []).append(str(exc)[:200])
                last_parse_exc = exc
        entry["raw_response"] = raw
        return _synthetic_error_scores(
            bucket_criteria_objs,
            bucket_weights,
            f"parse error after {PARSE_RETRIES} tries: {last_parse_exc}",
        )
    except LLMBackendError as exc:
        # Widened 2026-09-19 02:20Z: SVC-PC-20-8-0 re-ran clean of the lane-
        # refused text this fix originally targeted and STILL came back
        # total_reward=0.0 - its actual error was "timed out after 300s", a
        # different LLMBackendError shape the LANE_REFUSED_RE pattern never
        # matched. Every LLMBackendError means the judge call itself never
        # produced a real verdict (rate/session limit, timeout, not logged
        # in, no output) - none of that is a claim about the golden's
        # content, so all of it is now an infra refusal, never a synthetic
        # 0.0. LANE_REFUSED_RE is kept only to tag the specific mechanism in
        # the raised error, for the ALERTS.log/report trail.
        entry["error"] = str(exc)
        tag = "lane-refused" if LANE_REFUSED_RE.search(str(exc)) else "backend-error"
        raise InfraRefusalError(f"[{tag}] {exc}") from exc
    finally:
        if prev_model is None:
            os.environ.pop("CLAUDE_CODE_MODEL", None)
        else:
            os.environ["CLAUDE_CODE_MODEL"] = prev_model
        if prev_force is None:
            os.environ.pop("LLM_BACKEND_FORCE", None)
        else:
            os.environ["LLM_BACKEND_FORCE"] = prev_force


# ---------------------------------------------------------------------------
# Grading a whole layout
# ---------------------------------------------------------------------------


def grade_reward(
    reward,
    *,
    content_root: Path | None,
    echo_file: str | None,
    model_override: str | None,
    timeout: int,
    dry_run: bool,
    budget: list[int],
    prompt_log: list[dict[str, Any]],
    warnings: list[str],
    models_used: dict[str, str],
) -> None:
    """Populate reward.scores in place, one CLI call per file-scope bucket."""
    judge = reward.judge
    # Programmatic dimension (judge is None; criteria are Python callables, e.g. tests/**/checks.py or
    # tests/checks_deterministic/*.py). Score it exactly as rewardkit does, with its own run(). 2026-09-23: these
    # fell through to the unknown-judge error path, whose Score(name=c.name) crashed on a function; the runner
    # read the crash as a capped lane and released 1-5-0, 73-0-0, 41-4-0 as TRANSIENT on every attempt.
    if judge is None:
        try:
            reward.run()
        except Exception as e:  # a failing check scores 0, it never aborts the oracle
            warnings.append(
                f"{reward.name}: programmatic reward raised {e!r}; scored as error 0.0."
            )
            reward.scores = _synthetic_error_scores(
                reward.criteria,
                reward.weights or [1.0] * len(reward.criteria),
                f"programmatic reward raised {e!r}",
            )
        return
    if isinstance(judge, AgentJudge):
        warnings.append(
            f"{reward.name}: judge is an AgentJudge ({judge.agent}); this emulator "
            "only implements the LLMJudge (claude -p) path. Scored as all-error 0.0."
        )
        reward.scores = _synthetic_error_scores(
            reward.criteria,
            reward.weights or [1.0] * len(reward.criteria),
            "AgentJudge not supported by judge_emulate.py",
        )
        return
    if not isinstance(judge, LLMJudge):
        warnings.append(
            f"{reward.name}: unknown judge type {type(judge)}; scored as error."
        )
        reward.scores = _synthetic_error_scores(
            reward.criteria,
            reward.weights or [1.0] * len(reward.criteria),
            f"unsupported judge type {type(judge)}",
        )
        return

    model = resolve_model(model_override, judge.model)
    models_used[reward.name] = model

    weights = reward.weights if reward.weights else [1.0] * len(reward.criteria)
    buckets = bucket_criteria(judge, reward.criteria, weights, echo_file)

    ordered_scores: list[Score | None] = [None] * len(reward.criteria)
    for bucket_files, idxs in buckets:
        if echo_file is None:
            remapped = tuple(
                remap_app_path(f, content_root) if content_root is not None else f
                for f in bucket_files
            )
        else:
            remapped = bucket_files  # already the literal echo file path

        bucket_criteria_objs = [reward.criteria[i] for i in idxs]
        bucket_weights = [weights[i] for i in idxs]

        if budget[0] is not None and budget[0] <= 0:
            scores = _synthetic_error_scores(
                bucket_criteria_objs,
                bucket_weights,
                "skipped: --max-criteria budget exhausted",
            )
        else:
            scores = run_bucket(
                remapped,
                bucket_criteria_objs,
                bucket_weights,
                model=model,
                timeout=timeout,
                dry_run=dry_run,
                prompt_log=prompt_log,
            )
            if budget[0] is not None:
                budget[0] -= len(bucket_criteria_objs)

        for local_i, global_i in enumerate(idxs):
            ordered_scores[global_i] = scores[local_i]

    reward.scores = ordered_scores  # type: ignore[assignment]


def walk_rewards(group: "rk_runner._RewardGroup"):
    for item in group.rewards:
        yield item.reward
    for child in group.children:
        yield from walk_rewards(child)


_MUST_PASS_RE = None


def _must_pass_prose_names(reward) -> list[str]:
    import re

    global _MUST_PASS_RE
    if _MUST_PASS_RE is None:
        _MUST_PASS_RE = re.compile(r"must[- ]pass", re.IGNORECASE)
    return [
        getattr(c, "name", None) or getattr(c, "__name__", "?")
        for c in reward.criteria
        if getattr(c, "description", None) and _MUST_PASS_RE.search(c.description)
    ]


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------


def flatten_criteria(groups_out: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten build_group_output()'s nested groups/children tree into one flat list, each
    entry tagged with its full group_path (e.g. 'deliverables_01' or
    'deliverables_01/childname'), for cross-run comparison in a multi-run oracle probe
    (verifier spec, 2026-09-19 18:25Z step B)."""
    flat: list[dict[str, Any]] = []

    def walk(glist: list[dict[str, Any]], path: str) -> None:
        for g in glist:
            gp = f"{path}/{g['name']}" if path else g["name"]
            for c in g.get("criteria", []) or []:
                flat.append(
                    {
                        "group_path": gp,
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "value": c.get("value"),
                        "passed": c.get("passed"),
                        "verdict_text": c.get("verdict_text"),
                        "error": c.get("error"),
                    }
                )
            if g.get("children"):
                walk(g["children"], gp)

    walk(groups_out, "")
    return flat


def group_weight_in_total(layout: "rk_runner._RewardLayout", group_name: str) -> float:
    for spec in layout.specs:
        if group_name in spec.weights:
            return spec.weights[group_name]
    return 1.0


def build_group_output(group: "rk_runner._RewardGroup") -> dict[str, Any]:
    criteria_out: list[dict[str, Any]] = []
    must_pass_unenforced: list[str] = []
    aggregation = rk_runner._group_aggregation(group)

    for item in group.rewards:
        reward = item.reward
        if aggregation == "weighted_mean":
            must_pass_unenforced.extend(_must_pass_prose_names(reward))
        for s in reward.scores:
            criteria_out.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "weight": s.weight,
                    "passed": s.value > 0,
                    "value": round(s.value, 4),
                    "verdict_text": s.reasoning,
                    "error": s.error,
                }
            )

    children_out = [build_group_output(child) for child in group.children]

    out: dict[str, Any] = {
        "name": group.name,
        "score": group.score,
        "aggregation": aggregation,
        "criteria": criteria_out,
    }
    if must_pass_unenforced:
        out["must_pass_prose_but_unenforced"] = must_pass_unenforced
    if children_out:
        out["children"] = children_out
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _run_render_block(task_dir: Path, tests_dir: Path, content_root: Path) -> Path:
    """Execute the task's SVCPC-RENDER-V1 heredoc from tests/test.sh, as DataOS does before rewardkit runs.

    2026-09-29: this emulator ran the audit blocks but never RENDER-V1, which writes <docx>.format.md (and header
    and oversized-deliverable render sidecars) into /app AND adds them to the judge.toml files= lists in /tests.
    12-7-0's golden scored 0.9367-0.993 on 10 of 10 decide attempts on lane f (7 criteria grade the .format.md) and
    parked, while the same golden with the sidecar present scored 0 failing of 120. The block edits judge.toml, so it
    runs against a scratch COPY of tests/ (never the package) and the copy is returned for rewardkit to read.
    Returns tests_dir unchanged when the task has no RENDER block or the block fails.
    """
    ts = task_dir / "tests" / "test.sh"
    try:
        txt = ts.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return tests_dir
    h = re.search(r"^# --- (SVCPC-RENDER-V\d+)\b", txt, re.M)
    if not h:
        return tests_dir
    variant = h.group(1)
    end = re.search(r"^# --- END %s\b" % re.escape(variant), txt[h.end() :], re.M)
    body = txt[h.end() : h.end() + end.start()] if end else txt[h.end() :]
    m = re.search(r"python3 - <<'(\w+)'\n(.*?)\n\1\n", body, re.S)
    if not m:
        sys.stderr.write("WARN: %s header present but no heredoc block found inside it\n" % variant)
        return tests_dir
    tmp_tests = content_root.parent / (content_root.name + "__tests")
    if tmp_tests.exists():
        shutil.rmtree(tmp_tests)
    shutil.copytree(tests_dir, tmp_tests)
    # Repoint only the bare defaults (tests_root="/tests", app_root="/app"); every "/app/..." prefix is a judge.toml
    # path the block compares and writes back as written, exactly as FORMULA-AUDIT-V1 is handled.
    code = m.group(2).replace('"/tests"', repr(str(tmp_tests))).replace('"/app"', repr(str(content_root)))
    r = subprocess.run([sys.executable, "-"], input=code, capture_output=True, text=True, timeout=600)
    sides = sorted(p.name for p in content_root.glob("*.format.md"))
    sys.stderr.write("render block (%s): rc=%d, format sidecars: %s\n" % (variant, r.returncode, sides or "none"))
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-1500:] + "\n")
        shutil.rmtree(tmp_tests, ignore_errors=True)
        return tests_dir
    return tmp_tests


def _run_formula_audit_block(task_dir: Path, content_root: Path) -> None:
    """Execute the task's own SVCPC-FORMULA-AUDIT-V1 heredoc from tests/test.sh against content_root."""
    ts = task_dir / "tests" / "test.sh"
    try:
        txt = ts.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    # Anchor on the block's own header line: the marker name also appears in comments of earlier blocks.
    # 2026-09-23: DELIVERABLE-AUDIT-V1 (3-9-0) writes /app/FY26_Deliverable_Audit.md, which 28 of its
    # criteria grade; skipping it scored the golden 0.5032 on "[not found]" alone. Run every audit block.
    # 2026-09-25: this matched only V1 headers and only a 'PYEOF' heredoc, searching to the end of the file. The
    # FORMULA-AUTHENTICITY blocks in 20-4-0, 20-8-0 and 22-2-0 use 'FAEOF' (22-2-0 is V2), so it skipped them
    # and ran the NEXT section's PYEOF (SVCPC-RENDER-V1) instead; the report 4 criteria grade was never written and
    # the golden sat at 0.97 through 10 attempts. Now: any -V<n>, any heredoc delimiter, and only inside the
    # block's own "# --- END <variant>" fence.
    for h in re.finditer(
        r"^# --- (SVCPC-(?:FORMULA-AUDIT|FORMULA-AUTHENTICITY|DELIVERABLE-AUDIT)-V\d+)\b",
        txt,
        re.M,
    ):
        variant = h.group(1)
        end = re.search(r"^# --- END %s\b" % re.escape(variant), txt[h.end() :], re.M)
        body = txt[h.end() : h.end() + end.start()] if end else txt[h.end() :]
        m = re.search(r"python3 - <<'(\w+)'\n(.*?)\n\1\n", body, re.S)
        if not m:
            sys.stderr.write(
                "WARN: %s header present but no heredoc block found inside it\n"
                % variant
            )
            continue
        code = m.group(2)
        root = str(content_root)
        if variant.startswith("SVCPC-FORMULA-AUDIT-"):
            # main(tests_root="/tests", app_root="/app"): repoint only the bare defaults; its "/app/..." prefix
            # checks compare against judge.toml entries and must stay as written.
            code = code.replace('"/tests"', repr(str(task_dir / "tests"))).replace(
                '"/app"', repr(root)
            )
        else:
            # AUTHENTICITY-V1 and DELIVERABLE-AUDIT-V1 hardcode full "/app/<file>" paths for input and output.
            code = code.replace('"/app/', '"%s/' % root).replace(
                "'/app/", "'%s/" % root
            )
            # 20-8-0's AUTHENTICITY-V1 reads its QUANTITY definitions from TESTS_ROOT = "/tests"; locally that
            # is the task's own tests/ dir (DataOS mounts it at /tests).
            code = code.replace('"/tests"', repr(str(task_dir / "tests")))
        before_m = {p.name: p.stat().st_mtime for p in content_root.glob("*.md")}
        r = subprocess.run(
            [sys.executable, "-"],
            input=code,
            capture_output=True,
            text=True,
            timeout=300,
        )
        after = {p.name: p.stat().st_mtime for p in content_root.glob("*.md")}
        written = [n for n, t in after.items() if t != before_m.get(n)]
        sys.stderr.write(
            "audit block (%s): rc=%d, audit file(s) written: %s\n"
            % (variant, r.returncode, written or "none")
        )
        if r.returncode != 0:
            sys.stderr.write(r.stderr[-1500:] + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("mode", choices=["oracle", "deliverable", "echo"])
    ap.add_argument(
        "task", help="task id (resolved under --corpus-root) or a full path"
    )
    ap.add_argument(
        "target",
        nargs="?",
        default=None,
        help="deliverable directory (mode=deliverable) or echo file (mode=echo)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-criteria", type=int, default=None)
    ap.add_argument(
        "--model",
        default=None,
        help="explicit override; omit to use each judge group's own rubric model",
    )
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--runs",
        type=int,
        default=1,
        help="grade the layout up to N independent times (the judge is not deterministic "
        "on compound criteria - DataOS's own oracle scored 5-4-0 at 0.9714, not 1.0, on a "
        "second read). total_reward becomes the minimum total_reward across the completed "
        "runs; a new 'flips' field lists any criterion that passed in one run and failed in "
        "another, each with every run's own verdict. Stops early (whole probe stays "
        "infra-tainted, as with --runs 1) on the first InfraRefusalError - never salvages "
        "partial runs into a scored result. Ignored (forced to 1) under --dry-run.",
    )
    ap.add_argument(
        "--runs-out",
        type=Path,
        default=None,
        help="with --runs > 1, write full per-run per-criterion detail here (default: "
        "<--out stem>.runs.json next to --out; skipped if neither is given)",
    )
    args = ap.parse_args(argv)

    if args.mode in ("deliverable", "echo") and not args.target:
        ap.error(f"mode={args.mode} requires a second positional argument")

    task_dir = resolve_task_dir(args.task, args.corpus_root)
    task_id = task_dir.name
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        sys.stderr.write(f"ERROR: no tests/ directory under {task_dir}\n")
        return 2

    content_root: Path | None = None
    echo_file: str | None = None
    mode_label = args.mode
    if args.mode == "oracle":
        # Verifier spec item 2 (FOR-PIPE2.md, 2026-09-19): content_root used to
        # be JUST task_dir/solution/files - the golden alone, with no
        # environment overlay. Every environment SOURCE file named in a
        # group's files= (e.g. 67-1-0's Customer_Master.xlsx, Sales_Orders.xlsx)
        # then resolved to "[not found]" regardless of its real size, hiding
        # the real "[skipped: file too large]" marker a real grading run (whose
        # /app has the whole environment/initial_workspace/ copied in per the
        # Dockerfile, per solve.sh's own `cp -a /solution/files/. /app/` on top
        # of it) actually produces. build_app_root reproduces that real /app:
        # environment/initial_workspace/* copied in, solution/files/* overlaid
        # on top - so oracle total_reward now scores the real prompt, not one
        # up to 88x smaller with the environment silently absent.
        scratch_root = Path(
            os.environ.get(
                "QC_JUDGE_EMULATE_SCRATCH", "/root/qc/checks_scratch/judge_emulate_app"
            )
        )
        content_root = build_app_root(
            task_dir, scratch_root / task_id, mode="oracle", deliverable_dir=None
        )
    elif args.mode == "deliverable":
        # Same fix, same reasoning: a real solver's /app is not just its own
        # written deliverable, it is that deliverable landing on top of the
        # environment the Dockerfile already copied in - so a files= entry
        # naming an environment source resolves for a solver run exactly as
        # it does for oracle, not to "[not found]".
        deliverable_dir = Path(args.target)
        if not deliverable_dir.is_dir():
            sys.stderr.write(
                f"ERROR: deliverable directory not found: {deliverable_dir}\n"
            )
            return 2
        scratch_root = Path(
            os.environ.get(
                "QC_JUDGE_EMULATE_SCRATCH", "/root/qc/checks_scratch/judge_emulate_app"
            )
        )
        content_root = build_app_root(
            task_dir,
            scratch_root / task_id,
            mode="deliverable",
            deliverable_dir=deliverable_dir,
        )
        mode_label = f"deliverable:{deliverable_dir}"
    else:  # echo
        echo_path = Path(args.target)
        if not echo_path.is_file():
            sys.stderr.write(f"ERROR: echo file not found: {echo_path}\n")
            return 2
        echo_file = str(echo_path.resolve())
        mode_label = f"echo:{echo_file}"

    # 2026-09-23: tests/test.sh builds <deliverable>.formula_audit.md in /app BEFORE rewardkit runs
    # (SVCPC-FORMULA-AUDIT-V1; 1-1-0, 3-4-0, 12-3-0, 35-0-0, 94-0-0), and judge.toml grades that file. This
    # emulator never ran test.sh, so a re-graded DataOS answer had no audit file and its formula criteria
    # (35-0-0 r068/r141/r142) could never pass locally. Run THAT block only - it reads tests/*/judge.toml
    # and writes only under the app root - with its own /app and /tests defaults pointed at ours.
    if content_root is not None:
        tests_dir = _run_render_block(task_dir, tests_dir, content_root)
        _run_formula_audit_block(task_dir, content_root)

    # workspace is what programmatic (.py) criteria read: rewardkit hands it to every check as `workspace`, and
    # on DataOS it is /app. 2026-09-23: lane rebuilds now add tests/**/checks.py and checks_deterministic/*.py
    # (1-5-0, 73-0-0, 41-4-0, 35-1-0, 42-3-0, 77-8-0); passing tests/ here made every such check score 0 on the
    # golden. Oracle/deliverable modes pass the rebuilt /app (environment + golden or deliverable overlaid).
    ws = content_root if args.mode in ("oracle", "deliverable") else task_dir / "tests"
    layout = rk_runner._discover_layout(tests_dir, workspace=ws)

    # Verifier spec, step B (2026-09-19 18:25Z): the judge is not deterministic on
    # compound criteria (DataOS's own oracle scored 5-4-0 at 0.9714, q27 failed, while a
    # single local probe said 1.0). --runs > 1 grades the SAME layout up to N independent
    # times; --dry-run makes multiple runs meaningless (no real LLM variance), so it is
    # forced to 1 regardless of --runs.
    runs_requested = 1 if args.dry_run else max(1, args.runs)
    completed_runs: list[dict[str, Any]] = []
    infra_result: dict[str, Any] | None = None

    for run_idx in range(runs_requested):
        run_warnings: list[str] = []
        run_prompt_log: list[dict[str, Any]] = []
        run_models_used: dict[str, str] = {}
        run_budget: list[int] = [args.max_criteria]  # fresh budget per run

        try:
            for group in layout.groups:
                for reward in walk_rewards(group):
                    grade_reward(
                        reward,
                        content_root=content_root,
                        echo_file=echo_file,
                        model_override=args.model,
                        timeout=args.timeout,
                        dry_run=args.dry_run,
                        budget=run_budget,
                        prompt_log=run_prompt_log,
                        warnings=run_warnings,
                        models_used=run_models_used,
                    )
        except InfraRefusalError as exc:
            # Stop early. Never salvage the runs completed before an infra refusal into a
            # scored result - the whole probe stays infra-tainted, exactly as a single
            # --runs 1 call always has: a partial 2-of-3 is still "the judge never
            # produced N real verdicts", not a claim about the golden's content.
            infra_result = {
                "task": task_id,
                "mode": mode_label,
                "total_reward": None,
                "infra_failure": True,
                "error": str(exc),
                "groups": [],
                "warnings": run_warnings,
                "oracle_runs_requested": runs_requested,
                "oracle_runs_completed_before_refusal": len(completed_runs),
            }
            break

        # rewardkit's OWN aggregation code, untouched: per-group weighted_mean / all_pass /
        # etc., then the root reward.toml [[reward]] combination.
        main_scores = rk_runner._score_layout(layout)
        native_details = rk_runner._layout_details(layout)

        total_reward = main_scores.get("reward")
        if total_reward is None:
            # Flat layout with no named [[reward]] table: single group's score IS the
            # total (only path rewardkit itself falls back to; see runner.py
            # _score_layout - `result = dict(flat)` before any [[reward]] merge).
            if len(main_scores) == 1:
                total_reward = next(iter(main_scores.values()))
            else:
                run_warnings.append(
                    "no named [[reward]] table in tests/reward.toml and more than one "
                    "top-level group; total_reward is undefined, reporting None. "
                    f"Per-group scores: {main_scores}"
                )

        groups_out = [build_group_output(g) for g in layout.groups]
        for g_out, g in zip(groups_out, layout.groups):
            g_out["weight"] = group_weight_in_total(layout, g.name)

        completed_runs.append(
            {
                "total_reward": total_reward,
                "groups": groups_out,
                "rewardkit_native": {"main": main_scores, "details": native_details},
                "warnings": run_warnings,
                "models_used": run_models_used,
                "prompt_log": run_prompt_log,
            }
        )

    if infra_result is not None:
        # Never aggregate partial/absent scores into a numeric total_reward after an
        # infra refusal - that is exactly how SVC-PC-11-4-0 got a false 0.0. total_reward
        # is null; the caller (gate_task.sh's lane_refused()/refused_exit(),
        # zip_when_ready.sh, oracle_refresh.py) must treat this probe as not-yet-run and
        # retry it, never as a scored failure.
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(infra_result, indent=2))
        else:
            print(json.dumps(infra_result, indent=2))
        sys.stderr.write(
            f"ERROR: infra refusal, not a golden failure: {infra_result['error']}\n"
        )
        return 4  # matches gate_task.sh's own refused_exit() convention

    if runs_requested == 1:
        # Byte-identical shape to every caller before --runs existed: no new keys.
        run = completed_runs[0]
        result = {
            "task": task_id,
            "mode": mode_label,
            "total_reward": run["total_reward"],
            "groups": run["groups"],
            "warnings": run["warnings"],
            "dry_run": args.dry_run,
            "max_criteria_budget": args.max_criteria,
            "model_override": args.model,
            "models_used": run["models_used"],
            "rewardkit_native": run["rewardkit_native"],
        }
        if args.dry_run:
            result["prompt_log"] = run["prompt_log"]
            for entry in run["prompt_log"]:
                sys.stderr.write(
                    f"\n=== bucket: {entry['criteria']} (files={entry['files']}) ===\n"
                )
                sys.stderr.write("--- system prompt ---\n")
                sys.stderr.write(entry["system_prompt"] + "\n")
                sys.stderr.write(
                    f"--- user text ({entry['user_text_chars']} chars, preview) ---\n"
                )
                sys.stderr.write(entry["user_text_preview"] + "\n")
    else:
        # total_reward = the minimum over runs (a criterion that only sometimes passes
        # must not be hidden by an average or a best-of). The run realizing that minimum
        # is used as the canonical groups/rewardkit_native/warnings/models_used, so every
        # existing consumer of oracle.json's shape (zip_when_ready.sh's taint check,
        # build_review_union.py's failed_oracle_criteria) still sees one coherent,
        # real, worst-case run - `flips` and `oracle_runs` are the only new keys.
        totals = [r["total_reward"] for r in completed_runs]
        min_idx = min(
            range(len(totals)),
            key=lambda i: (totals[i] if totals[i] is not None else float("-inf")),
        )
        canonical = completed_runs[min_idx]

        flats = [flatten_criteria(r["groups"]) for r in completed_runs]
        by_key: dict[tuple[str, Any, Any], list[dict[str, Any]]] = {}
        for run_i, flat in enumerate(flats):
            for c in flat:
                key = (c["group_path"], c["id"], c["name"])
                by_key.setdefault(key, []).append(
                    {
                        "run": run_i + 1,
                        "passed": c["passed"],
                        "value": c["value"],
                        "verdict_text": c["verdict_text"],
                        "error": c["error"],
                    }
                )
        flips = []
        for (group_path, cid, name), run_records in by_key.items():
            passed_vals = {r["passed"] for r in run_records}
            if len(passed_vals) > 1:
                flips.append(
                    {
                        "group": group_path,
                        "id": cid,
                        "name": name,
                        "runs": run_records,
                    }
                )
        flips.sort(key=lambda f: (f["group"], f["name"] or ""))

        result = {
            "task": task_id,
            "mode": mode_label,
            "total_reward": canonical["total_reward"],
            "groups": canonical["groups"],
            "warnings": canonical["warnings"],
            "dry_run": args.dry_run,
            "max_criteria_budget": args.max_criteria,
            "model_override": args.model,
            "models_used": canonical["models_used"],
            "rewardkit_native": canonical["rewardkit_native"],
            "oracle_runs": len(completed_runs),
            "oracle_run_totals": totals,
            "flips": flips,
        }

        runs_out_path = args.runs_out
        if runs_out_path is None and args.out is not None:
            runs_out_path = args.out.with_name(args.out.stem + ".runs.json")
        if runs_out_path is not None:
            runs_out_path.parent.mkdir(parents=True, exist_ok=True)
            runs_out_path.write_text(
                json.dumps(
                    {
                        "task": task_id,
                        "mode": mode_label,
                        "runs": [
                            {
                                "run": i + 1,
                                "total_reward": completed_runs[i]["total_reward"],
                                "criteria": flats[i],
                            }
                            for i in range(len(completed_runs))
                        ],
                        "flips": flips,
                    },
                    indent=2,
                    default=str,
                )
            )

    text = json.dumps(result, indent=2, default=str)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
