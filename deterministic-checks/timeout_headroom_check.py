#!/usr/bin/env python3
"""timeout_headroom_check -- will this task's grading run FINISH inside its own
`[verifier] timeout_sec`, or will it die mid-judging and return no reward at all?

WHY THIS EXISTS (measured, 2026-09-22, 30-task fix session).

Every one of the 79 shipped v7 packages carries the same `[verifier] timeout_sec = 3600.0`,
copied from the template, while the shipped verifier library judges rubric criteria STRICTLY
SERIALLY -- one criterion at a time, one judge call at a time. Grading cost therefore scales
with `rubric_criteria x judge_samples`, and nothing in the package scales the budget with it.

Two tasks in that batch produced rewardless runs from exactly this:

  * task_157      oracle attempt 1 (`eval_501545__attempt_1__oracle`) died with
                  "Verifier execution timed out after 3600.0 seconds" (its own trial.log).
                  36 rubric criteria x 3 samples = 108 serial judge calls; its completed
                  sibling runs took up to 3322 s of the 3600 s budget.
  * task_LGL-160  `eval_503989__attempt_1__oracle` died the same way. Only 22 criteria
                  (66 calls) -- but its completed runs reached 3583 s, 17 s under the cap.

A timed-out run yields NO reward.json. It does not appear as a low score in an aggregate
report -- it appears as nothing, which reads like "the run never happened". The fix agent who
found it called it "batch-wide, not an LGL-160 one" and named LGL-126 (25 rubric criteria),
LGL-131 (22) and LGL-168 (33) as sharing the same worst case.

WHAT IT COMPUTES.

    est_serial_sec = rubric_criteria x judge_samples x seconds_per_call
    headroom       = timeout_sec / est_serial_sec

`fail` when `headroom < --min-headroom` (default 1.5x).

WHERE `--seconds-per-call` COMES FROM (real measurement, not a guess).

Derived from the bundled DataOS eval artifacts under
`dataos_qc_runs/74-ekw-sprint/{qcr_20092026_rework,qcr_21092026}/incoming/`. For every
`eval_files/result.json` that records a `verifier.started_at` / `verifier.finished_at` pair,
wall-clock verifier seconds were divided by the number of judge attempts actually recorded in
that run's `eval_files/verifier/verifier-report.json`
(`assertion_results[].result.evaluation.attempts`). Across **87 real runs of 18 tasks**:

    min 8.6   median 23.7   p90 45.9   max 61.2   seconds per judge call

The default is **46.0 s/call, the measured p90**, NOT the median. A verifier timeout is a TAIL
event: you have to budget for the slow run, not the typical one. The measured per-task medians
range from 8.9 s/call (task_145) to 55.9 s/call (task_LGL-155) on the same judge model and the
same 3600 s budget, so a median-latency model provably cannot see a real timeout. Concretely:
task_LGL-160 has only 22 rubric criteria (66 calls), which looks comfortable at the median -- and
its `eval_503989` still died at the 3600 s cap, because its slowest observed call was 54.3 s.
Pass `--seconds-per-call 25` (the measured median, rounded up) for the typical-latency view,
which is the more useful RANKING of which tasks are worst; the p90 default is the safety view.

Note the measured per-call figure already includes the run's fixed overhead (image pull,
dependency install, extraction), because it is wall-clock verifier time divided by calls. That
makes it conservative for high-criterion tasks and slightly pessimistic for tiny ones.

HONEST READING OF THE DEFAULT RESULT: at 46 s/call and a 1.5x margin, **74 of the 75 native v7
packages fail** (only task_LGL-177, 17 criteria, clears it). That is not a broken threshold --
it is the finding. The fix agent who first hit this called it "batch-wide, not an LGL-160 one",
and the batch-wide cause is that all 79 packages copy the same template `timeout_sec = 3600.0`
regardless of rubric size. The actionable output of this check at the default is therefore a
BATCH decision (raise `timeout_sec`, or cut criteria), not a per-task accept/reject. Use
`--seconds-per-call 25` when you want the per-task ranking (23 fail / 52 pass / 4 skip).

WHAT IT COUNTS.

Only **LLM-judged rubric criteria** -- `assertion.type == "rubric"` in `tests/verifier.json`.
Deterministic assertions (`assertion.type == "deterministic"`, a JSONPath/tolerance comparison)
make no LLM call, cost milliseconds, and are counted separately and excluded from the estimate.

`judge_samples` is read from the task's OWN config, never assumed: `config.models` in
`tests/verifier.json` lists the judge model once per sample (this corpus's convention, enforced
by `reward_signal_gate.py` G9 -- all 75 native v7 packages list it exactly 3 times). A config
with no `models` list falls back to 1 sample and says so in `notes`.

WHAT IT DOES **NOT** CATCH (read this before gating on it).

  * It cannot see the real judge latency of the run you are about to start -- provider load,
    prompt size and model choice all move it, and the measured spread above is 7x. It answers
    "is the configured budget plausibly enough", not "will this specific run finish".
  * It does not model retries. `tests/test.sh` in the rewardkit genre retries the whole
    invocation up to twice; the native genre's own per-call retry on a schema-parse failure is
    likewise invisible here. Both make the true worst case LARGER than this estimate.
  * It does not model extraction cost (LibreOffice recalculation of a large workbook, a big
    PDF) which is real fixed overhead partially folded into the measured per-call number above.
  * It says nothing about whether the criteria are any good -- only about how many there are.
  * **rewardkit-hybrid genre is reported `skip`, not graded.** That genre chunks criteria into
    `tests/deliverables_*/judge.toml` files, sends ONE prompt per chunk (not per criterion), and
    dispatches the chunks through an `asyncio.TaskGroup` -- i.e. concurrently, not serially. The
    serial model above does not apply and this corpus has no measured concurrency factor to
    calibrate one against. The check still parses the chunk configs and reports each chunk's
    criterion count and its own `[judge] timeout` in `rewardkit`, plus a clearly-labelled
    `serial_upper_bound_sec`, as disclosure -- it is never used for pass/fail.

CALIBRATION STATUS. Validated against all 79 shipped v7 packages at
`dataos_qc_runs/74-ekw-sprint/ready_to_upload_v7/submitted/`. The two tasks with CONFIRMED real
3600 s verifier timeouts (task_157, task_LGL-160) and the third sampled worst case
(task_LGL-168) are all in the flagged set at the defaults. Regression-pinned in
`timeout_headroom_check_test.py`.

USAGE
    python timeout_headroom_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python timeout_headroom_check.py --all --root <path> --id-prefix task_ --out report.json
    python timeout_headroom_check.py --all --root <path> --seconds-per-call 25   # median view

Exit code: 0 always (disclosure report; the gating decision is `--min-headroom` plus whoever
reads the status counts). Pass `--exit-nonzero-on-fail` to use it as a hard gate.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ekw_verifier_json import load_ekw_verifiers_raw  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Measured p90 of 87 real DataOS verifier runs -- see module docstring for the derivation and
# for why the p90 (tail), not the 23.7 s median, is the default.
DEFAULT_SECONDS_PER_CALL = 46.0
DEFAULT_MIN_HEADROOM = 1.5

# rewardkit's own default per-chunk judge timeout when [judge] timeout is absent, as documented
# in this corpus's own judge.toml comments ("Default is 300 s").
REWARDKIT_DEFAULT_JUDGE_TIMEOUT = 300.0

VERIFIER_LIB_DIRS = ("__verifier_lib", "verifier_lib")


# ---------------------------------------------------------------------------
# genre detection -- same two spellings container_build_check.py recognises
# ---------------------------------------------------------------------------


def genre(pkg: Path) -> str:
    for name in VERIFIER_LIB_DIRS:
        if (pkg / "tests" / name).is_dir():
            return "native"
    if (pkg / "tests" / "verifier.json").is_file():
        return "native"
    if list((pkg / "tests").glob("deliverables_*/judge.toml")):
        return "rewardkit"
    return "unknown"


# ---------------------------------------------------------------------------
# config readers
# ---------------------------------------------------------------------------


def read_timeout_sec(pkg: Path) -> tuple[float | None, str | None]:
    """`[verifier] timeout_sec` from task.toml, or (None, why-not)."""
    tt = pkg / "task.toml"
    if not tt.is_file():
        return None, "task.toml missing -- no verifier budget to check against"
    try:
        data = tomllib.loads(tt.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        return None, f"task.toml failed to parse: {exc}"
    verifier = data.get("verifier")
    if not isinstance(verifier, dict) or not isinstance(
        verifier.get("timeout_sec"), (int, float)
    ):
        return None, "task.toml has no [verifier] timeout_sec"
    return float(verifier["timeout_sec"]), None


def native_grading_shape(pkg: Path) -> dict:
    """rubric/deterministic criterion counts + judge sample count from tests/verifier.json."""
    verifiers, _task_id, config, parse_error = load_ekw_verifiers_raw(pkg)
    out: dict = {
        "rubric_criteria": 0,
        "deterministic_criteria": 0,
        "other_criteria": 0,
        "judge_samples": None,
        "notes": [],
        "parse_error": parse_error,
    }
    if parse_error:
        return out
    for v in verifiers:
        if not isinstance(v, dict):
            out["other_criteria"] += 1
            continue
        assertion = v.get("assertion") if isinstance(v.get("assertion"), dict) else {}
        atype = assertion.get("type")
        if atype == "rubric":
            out["rubric_criteria"] += 1
        elif atype == "deterministic":
            out["deterministic_criteria"] += 1
        else:
            # The alternate schema (task_FIN-177 shape) has no assertion block; it is still
            # LLM-judged, so count it as rubric rather than silently dropping its cost.
            if v.get("criterion") is not None:
                out["rubric_criteria"] += 1
            else:
                out["other_criteria"] += 1

    models = (config or {}).get("models")
    if isinstance(models, list) and models:
        out["judge_samples"] = len(models)
    else:
        out["judge_samples"] = 1
        out["notes"].append(
            "tests/verifier.json config has no non-empty `models` list -- assuming 1 judge "
            "sample. This corpus's convention (reward_signal_gate.py G9) is to list the judge "
            "model three times; a task missing it is under-sampled, not cheap."
        )
    return out


def rewardkit_grading_shape(pkg: Path) -> dict:
    """Per-chunk criterion counts and per-chunk judge timeouts (disclosure only -- see docstring)."""
    chunks = []
    for jt in sorted((pkg / "tests").glob("deliverables_*/judge.toml")):
        entry = {
            "chunk": jt.parent.name,
            "criteria": 0,
            "judge_timeout_sec": REWARDKIT_DEFAULT_JUDGE_TIMEOUT,
            "judge_timeout_source": "rewardkit default (no [judge] timeout in this chunk)",
        }
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            entry["parse_error"] = str(exc)
            chunks.append(entry)
            continue
        crits = data.get("criterion")
        entry["criteria"] = len(crits) if isinstance(crits, list) else 0
        judge = data.get("judge") if isinstance(data.get("judge"), dict) else {}
        if isinstance(judge.get("timeout"), (int, float)):
            entry["judge_timeout_sec"] = float(judge["timeout"])
            entry["judge_timeout_source"] = "[judge] timeout in this chunk's judge.toml"
        chunks.append(entry)

    reward_toml = pkg / "tests" / "reward.toml"
    return {
        "chunks": chunks,
        "n_chunks": len(chunks),
        "criteria": sum(c["criteria"] for c in chunks),
        "reward_toml_present": reward_toml.is_file(),
    }


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(
    task_dir: Path,
    seconds_per_call: float = DEFAULT_SECONDS_PER_CALL,
    min_headroom: float = DEFAULT_MIN_HEADROOM,
) -> dict:
    """One result dict for one package. Never raises."""
    result: dict = {
        "task_id": task_dir.name,
        "genre": genre(task_dir),
        "status": None,
        "timeout_sec": None,
        "rubric_criteria": None,
        "deterministic_criteria": None,
        "judge_samples": None,
        "judge_calls": None,
        "seconds_per_call": seconds_per_call,
        "est_serial_sec": None,
        "headroom": None,
        "min_headroom": min_headroom,
        "findings": [],
        "notes": [],
    }

    timeout_sec, why = read_timeout_sec(task_dir)
    result["timeout_sec"] = timeout_sec

    if result["genre"] == "rewardkit":
        rk = rewardkit_grading_shape(task_dir)
        result["rewardkit"] = rk
        upper = sum(c["judge_timeout_sec"] for c in rk["chunks"]) * 3
        rk["serial_upper_bound_sec"] = upper
        rk["serial_upper_bound_note"] = (
            "sum of every chunk's own judge timeout x 3 samples. NOT used for pass/fail: "
            "rewardkit dispatches chunks through an asyncio.TaskGroup (concurrently), so this "
            "is a loose upper bound, and this corpus has no measured concurrency factor to "
            "calibrate a real estimate against."
        )
        result["status"] = "skip"
        result["notes"].append(
            "rewardkit-hybrid genre: criteria are chunked one prompt per "
            "tests/deliverables_*/judge.toml and judged concurrently, not one serial call per "
            "criterion. This check's serial model does not apply -- chunk shape reported as "
            "disclosure only."
        )
        return result

    if result["genre"] != "native":
        result["status"] = "skip"
        result["notes"].append(
            "no tests/verifier.json and no tests/deliverables_*/judge.toml -- no grading "
            "config to size a budget against"
        )
        return result

    shape = native_grading_shape(task_dir)
    result["rubric_criteria"] = shape["rubric_criteria"]
    result["deterministic_criteria"] = shape["deterministic_criteria"]
    result["judge_samples"] = shape["judge_samples"]
    result["notes"].extend(shape["notes"])

    if shape["parse_error"]:
        result["status"] = "skip"
        result["notes"].append(shape["parse_error"])
        return result
    if timeout_sec is None:
        result["status"] = "skip"
        result["notes"].append(why or "no verifier timeout found")
        return result
    if shape["rubric_criteria"] == 0:
        result["status"] = "skip"
        result["notes"].append(
            "zero LLM-judged rubric criteria (deterministic assertions only) -- no judge "
            "latency to budget for"
        )
        return result

    calls = shape["rubric_criteria"] * shape["judge_samples"]
    est = calls * seconds_per_call
    headroom = timeout_sec / est if est else None

    result["judge_calls"] = calls
    result["est_serial_sec"] = est
    result["headroom"] = round(headroom, 3) if headroom is not None else None

    if headroom is not None and headroom < min_headroom:
        result["status"] = "fail"
        result["findings"].append(
            {
                "kind": "verifier_timeout_headroom_below_margin",
                "severity": "fail",
                "detail": (
                    f"{shape['rubric_criteria']} LLM-judged rubric criteria x "
                    f"{shape['judge_samples']} judge samples = {calls} SERIAL judge calls. At "
                    f"the measured {seconds_per_call:g} s/call that is ~{est:.0f} s of judging "
                    f"against a [verifier] timeout_sec of {timeout_sec:.0f} s -- headroom "
                    f"{headroom:.2f}x, below the {min_headroom:g}x margin. A verifier timeout "
                    f"writes NO reward.json: the run yields no reward at all and is invisible "
                    f"in an aggregate score report rather than showing up as a low score."
                ),
                "rubric_criteria": shape["rubric_criteria"],
                "judge_samples": shape["judge_samples"],
                "judge_calls": calls,
                "est_serial_sec": est,
                "timeout_sec": timeout_sec,
                "headroom": round(headroom, 3),
            }
        )
    else:
        result["status"] = "pass"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HOW_TO_READ_THIS_REPORT = {
    "purpose": (
        "Estimates whether a task's serial LLM judging (rubric_criteria x judge_samples) fits "
        "inside its own [verifier] timeout_sec, with margin. A verifier timeout returns NO "
        "reward, so it hides rather than shows."
    ),
    "task_status": {
        "fail": "headroom below --min-headroom -- the budget is plausibly too small.",
        "pass": "headroom at or above --min-headroom at the configured seconds-per-call.",
        "skip": (
            "rewardkit-hybrid genre (concurrent chunked judging, serial model does not apply), "
            "no grading config, no [verifier] timeout_sec, or zero rubric criteria."
        ),
    },
    "seconds_per_call_provenance": (
        "87 real DataOS verifier runs of 18 tasks (wall-clock verifier seconds / recorded "
        "judge attempts) from the 2026-09-20 and 2026-09-21 QCR bundles: min 8.6, median 23.7, "
        "p90 45.9, max 61.2. Default 46.0 is the p90 -- a timeout is a tail event, and the "
        "per-task medians span 8.9 to 55.9 s/call on the same model and the same budget. Pass "
        "--seconds-per-call 25 for the median (per-task ranking) view."
    ),
    "the_one_thing_this_check_cannot_see": (
        "Real judge latency for the run you are about to start. The measured spread is 7x, and "
        "retries (test.sh's bounded re-invocation, the judge's own schema-parse retry) are not "
        "modelled -- so the true worst case is always LARGER than est_serial_sec."
    ),
}


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
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Verifier timeout headroom check: rubric_criteria x judge_samples x "
            "seconds-per-call against [verifier] timeout_sec."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("task_ids", nargs="*", help="one or more task ids")
    ap.add_argument("--all", action="store_true", help="run every task under --root")
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--id-prefix", default="")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--seconds-per-call",
        type=float,
        default=DEFAULT_SECONDS_PER_CALL,
        help=f"seconds per serial judge call (default {DEFAULT_SECONDS_PER_CALL:g}, the "
        "measured p90 across 87 real runs; pass 25 for the measured median -- see the "
        "module docstring)",
    )
    ap.add_argument(
        "--min-headroom",
        type=float,
        default=DEFAULT_MIN_HEADROOM,
        help=f"fail below this timeout_sec/est_serial_sec ratio (default {DEFAULT_MIN_HEADROOM:g})",
    )
    ap.add_argument(
        "--exit-nonzero-on-fail",
        action="store_true",
        help="exit 1 if any task fails (for use as a hard gate)",
    )
    args = ap.parse_args(argv)

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")
    if not args.root.is_dir():
        print(f"--root does not exist or is not a directory: {args.root}", file=sys.stderr)
        return 2

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 2

    results = []
    for task_dir in task_dirs:
        try:
            r = analyze_task(task_dir, args.seconds_per_call, args.min_headroom)
        except Exception as exc:  # noqa: BLE001
            r = {
                "task_id": task_dir.name,
                "status": "skip",
                "findings": [],
                "notes": [f"unhandled exception: {exc}"],
            }
        results.append(r)

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    graded = [r for r in results if r.get("headroom") is not None]
    graded.sort(key=lambda r: r["headroom"])

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "id_prefix": args.id_prefix,
        "seconds_per_call": args.seconds_per_call,
        "min_headroom": args.min_headroom,
        "n_tasks": len(results),
        "status_counts": counts,
        "how_to_read_this_report": HOW_TO_READ_THIS_REPORT,
        "results": results,
    }

    print(f"\n{len(results)} task(s) checked "
          f"(seconds-per-call={args.seconds_per_call:g}, min-headroom={args.min_headroom:g}).")
    print("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if graded:
        print(f"\n{'task':18} {'crit':>5} {'x samp':>7} {'calls':>6} {'est s':>8} "
              f"{'budget':>8} {'headroom':>9}")
        for r in graded:
            print(f"{r['task_id']:18} {r['rubric_criteria']:>5} {r['judge_samples']:>7} "
                  f"{r['judge_calls']:>6} {r['est_serial_sec']:>8.0f} "
                  f"{r['timeout_sec']:>8.0f} {r['headroom']:>8.2f}x"
                  + ("  FAIL" if r["status"] == "fail" else ""))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(aggregate, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote {args.out}")

    if args.exit_nonzero_on_fail and counts.get("fail"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
