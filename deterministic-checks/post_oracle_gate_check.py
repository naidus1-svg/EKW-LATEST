#!/usr/bin/env python3
"""Post-Oracle gate check: run certification_gate_check.py and weight_aggregation_check.py
against completed run output, after a task has at least one real Oracle run recorded.

Both underlying checks need --run pointing at completed DataOS/Oracle output
(<task>/verifier/reward-details.json). The natural trigger point: once a task has at
least one real Oracle run recorded, run both checks against that run's output before
the task moves to the next pipeline stage. This wrapper automates that trigger.

Why a wrapper, not a registry entry. Both checks are deliberately excluded from
svc_run_checks.py's per-package CHECKS registry (see that script's own docstring and
the code comment at its CHECKS dict):

  - certification_gate_check.py: "operates post-hoc against a COMPLETED judge run
    (verifier/reward-details.json) plus DataOS gate-adjudication records, answering
    'did the must-pass criteria actually gate the shipped score' -- a release-time
    question, not a pre-grading package question."
  - weight_aggregation_check.py: "deliberately NOT registered here, same reason as
    certification_gate_check.py above: it requires --run pointing at completed judge-run
    output (reward-details.json), not just a task package -- a post-hoc release-time
    replay, not a per-package deterministic check this runner's sweep model can drive."

svc_run_checks.py sweeps task PACKAGES (pre-Oracle, pre-grading). This wrapper sweeps
completed RUNS (post-Oracle, post-grading). Different input shape, different cadence,
different output location. The wrapper does not modify either check's logic; it calls
them as subprocesses with the right arguments and combines their JSON output.

What it does:

  1. Discovers tasks with completed runs. Walks each --run root for
     verifier/reward-details.json (the same rglob both checks use internally) and
     collects the set of task ids that have at least one completed run. This is the
     trigger condition: a task with no reward-details.json under any --run root has
     not yet reached the post-Oracle stage and is not checked.
  2. Runs certification_gate_check.py as a subprocess with --root, --all (or specific
     task_ids), --run (as-is, with oracle:/model: prefix), --gate-records, --checks-
     summary, --threshold, --converter, --require-model-run, --out, --quiet.
  3. Runs weight_aggregation_check.py as a subprocess with --root, --all (or specific
     task_ids), --run (prefix STRIPPED: weight_aggregation_check does not support the
     oracle:/model: prefix, confirmed by reading its discover_runs source and its
     --help output), --json, --quiet.
  4. Reads both JSON outputs and writes a combined summary to
     --out-dir/post_oracle_gate_report.json, with per-task verdicts from both checks
     and a combined_status roll-up.

Combined status per task:

  ERROR     certification_gate returned ERROR (package unparseable or engine drift)
  NO RUN    certification_gate returned NO RUN (no reward-details.json found)
  NOT CLEAN certification_gate returned BLOCKED or PASS WITH OPEN ITEMS, OR
            weight_aggregation returned any FAIL/WARN verdict on any run
  CLEAN     certification_gate returned PASS AND weight_aggregation returned only
            OK/INFO verdicts on every run

Output location: --out-dir/post_oracle_gate_report.json, plus the two underlying
checks' own JSON at --out-dir/certification_gate.json and --out-dir/weight_aggregation
.json. This is distinct from svc_run_checks.py's summary.json/csv (which lives in its
own --out-dir at package-build time), because this wrapper runs on a different cadence
(after Oracle, not at package-build time).

The --checks-summary pass-through: certification_gate_check.py's --checks-summary
input (new in round 11, commit ba5c025 on the glm-worker branch) lets it consult
svc_run_checks.py's per-package registry output at certification time. This wrapper
accepts --checks-summary and passes it through to certification_gate_check.py only.
If the current worktree's certification_gate_check.py does not yet support
--checks-summary (the glm-worker commit has not been merged), the subprocess will
exit 2 and the wrapper reports the error. Once merged, the pass-through works with no
wrapper change.

CLI contract (verified against the real --help of both underlying checks, not assumed):

    python post_oracle_gate_check.py --root <package_root> --all \\
        --run oracle:<oracle_pull_root> --run model:<model_run_root> \\
        --gate-records <local qc_validation export> \\
        --checks-summary <svc_run_checks out-dir or summary.json> \\
        --out-dir <output_dir>

    python post_oracle_gate_check.py --root <package_root> SVC-PC-80-7-0 \\
        --run model:C:/b/_terminus_extract --out-dir <output_dir>

Limitations (honest):

  - No real Oracle run output exists on this machine (all paths the underlying checks'
    docstrings reference -- C:/b/_inspect_2866, C:/b/_terminus_extract,
    C:/ekwqc/_harbor_ekw8/_jobs, C:/ekwqc/_merged274/files -- are absent from this
    worktree). The wrapper's discovery, subprocess-invocation, and JSON-merge logic
    are tested against synthetic data (a minimal reward-details.json fixture). The
    underlying checks themselves are individually validated against real data per
    their own docstrings; this wrapper calls them correctly by construction (verified
    by reading their actual argparse, not guessing).
  - EKW scope: the wrapper works for EKW the same way (both checks support EKW's
    verifier.json format natively), but no real EKW run output in the Harbor trial
    layout exists on this machine. The round10-trackB-artifacts under
    ekw/pipeline-mirror/results/ are verifier-execution reports with a DIFFERENT
    schema (assertion_results with result.success, not the Harbor trial layout with
    reward-details.json/reward.json), so they do not qualify as "completed run output"
    in the sense these two checks need.
  - --checks-summary pass-through requires the glm-worker version of
    certification_gate_check.py (commit ba5c025), not yet in this worktree.

Exit 0 when every discovered task is CLEAN, 1 when any task is NOT CLEAN / NO RUN /
ERROR, 2 on bad usage. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CHECK_DIR = Path(__file__).parent
CERT_GATE_SCRIPT = CHECK_DIR / "certification_gate_check.py"
WEIGHT_AGG_SCRIPT = CHECK_DIR / "weight_aggregation_check.py"
RUN_WALK_MAX_DEPTH = 8

# Same run-spec prefix parsing as certification_gate_check.py's _parse_run_spec.
# Re-implemented here (not imported) per this folder's no-downstream-import convention.
SVC_ID_RE = re.compile(r"svc[-_ ]?pc[-_ ](\d+)[-_](\d+)[-_](\d+)", re.IGNORECASE)
EKW_ID_RE = re.compile(r"^task[-_](\d+)$", re.IGNORECASE)
PATH_TASK_ID_RE = re.compile(r"task[-_](\d+)\b", re.IGNORECASE)


def _parse_run_spec(spec: str) -> tuple[str, Path]:
    """'oracle:C:/x' -> ('oracle', Path); 'model:C:/x' -> ('model', Path); 'C:/x' -> ('auto', Path).
    A bare Windows drive letter ('C:') is not a kind prefix."""
    for kind in ("oracle", "model"):
        if spec.lower().startswith(kind + ":"):
            return kind, Path(spec[len(kind) + 1 :])
    return "auto", Path(spec)


def _strip_run_prefix(spec: str) -> str:
    """Strip oracle:/model: prefix for weight_aggregation_check (it does not support it,
    confirmed by reading its discover_runs source: it does Path(spec) directly with no
    prefix parsing, so 'oracle:C:/x' would be misread as drive letter 'oracle:')."""
    for kind in ("oracle", "model"):
        if spec.lower().startswith(kind + ":"):
            return spec[len(kind) + 1 :]
    return spec


def normalize_task_id(raw: str) -> str:
    """Same normalization as certification_gate_check.py's normalize_task_id, so task
    ids match across the two checks' reports (which may use different casing)."""
    s = str(raw).strip()
    m = SVC_ID_RE.search(s)
    if m:
        return f"SVC-PC-{int(m.group(1))}-{int(m.group(2))}-{int(m.group(3))}"
    m = EKW_ID_RE.match(s)
    if m:
        return f"task_{int(m.group(1))}"
    return s


def discover_tasks_with_runs(run_specs: list[str]) -> tuple[list[str], list[str]]:
    """Walk each --run root for verifier/reward-details.json and collect the set of
    task ids that have at least one completed run. Returns (sorted_task_ids, notes).
    Same rglob pattern both underlying checks use internally."""
    tasks: set[str] = set()
    notes: list[str] = []
    for spec in run_specs:
        kind, root = _parse_run_spec(spec)
        if not root.is_dir():
            notes.append(f"run root not a directory, skipped: {root}")
            continue
        root_depth = len(root.parts)
        found = 0
        for rd in root.rglob("reward-details.json"):
            if rd.parent.name != "verifier":
                continue
            if len(rd.parts) - root_depth > RUN_WALK_MAX_DEPTH:
                continue
            run_dir = rd.parent.parent
            task_id = run_dir.name
            if task_id == "harbor_task" or not re.search(r"\d", task_id):
                result_path = run_dir / "result.json"
                result = _read_json(result_path)
                for path_field in (
                    (((result or {}).get("config") or {}).get("task") or {}).get("path"),
                    ((result or {}).get("task_id") or {}).get("path"),
                ):
                    if not path_field:
                        continue
                    m = PATH_TASK_ID_RE.search(str(path_field))
                    if m:
                        task_id = f"task_{int(m.group(1))}"
                        break
            tasks.add(task_id)
            found += 1
        notes.append(f"{found} run(s) under {root} (kind hint: {kind})")
    return sorted(tasks), notes


def _read_json(p: Path):
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def run_subprocess(
    script: Path, args: list[str], label: str, timeout: int | None
) -> tuple[int, str, str]:
    """Run a check script as a subprocess. Returns (exit_code, stdout, stderr)."""
    cmd = [sys.executable, str(script)] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"{label} timed out after {timeout}s"
    except FileNotFoundError:
        return 127, "", f"{label}: script not found at {script}"
    except Exception as exc:
        return 1, "", f"{label}: {type(exc).__name__}: {exc}"


# Severity ordering for weight_aggregation verdicts (from VERDICT_SEVERITY in that file).
WEIGHT_SEVERITY = {
    "unweighted_mean_signature": "FAIL",
    "closer_to_unweighted": "WARN",
    "weighted_mean_signature": "OK",
    "closer_to_weighted": "OK",
    "tied": "OK",
    "not_discriminating": "INFO",
    "insufficient_groups": "INFO",
    "weight_unresolved": "INFO",
    "no_reported_reward": "INFO",
}
SEVERITY_RANK = {"FAIL": 3, "WARN": 2, "OK": 1, "INFO": 0}


def _weight_worst_severity(runs: list[dict]) -> str:
    """Worst severity across all runs for a task in weight_aggregation's report."""
    worst = "INFO"
    for r in runs:
        v = r.get("verdict", "")
        sev = WEIGHT_SEVERITY.get(v, "INFO")
        if SEVERITY_RANK.get(sev, 0) > SEVERITY_RANK.get(worst, 0):
            worst = sev
    return worst


def combine_reports(
    cert_report: dict | None,
    weight_report: dict | None,
) -> list[dict]:
    """Combine per-task verdicts from both checks into a unified list."""
    cert_tasks = {}
    if cert_report and isinstance(cert_report.get("tasks"), list):
        for t in cert_report["tasks"]:
            tid = normalize_task_id(t.get("task", ""))
            cert_tasks[tid] = t

    weight_tasks = {}
    if weight_report and isinstance(weight_report.get("tasks"), list):
        for t in weight_report["tasks"]:
            tid = normalize_task_id(t.get("task", ""))
            weight_tasks[tid] = t

    all_ids = sorted(set(cert_tasks) | set(weight_tasks))
    combined = []
    for tid in all_ids:
        ct = cert_tasks.get(tid, {})
        wt = weight_tasks.get(tid, {})
        cert_verdict = ct.get("verdict", "ERROR" if cert_report is None else "NO RUN")
        weight_runs = wt.get("runs", [])
        weight_verdicts = [r.get("verdict", "") for r in weight_runs]
        weight_worst = _weight_worst_severity(weight_runs)

        if cert_verdict == "ERROR":
            status = "ERROR"
        elif cert_report is None or weight_report is None:
            # A crashed subprocess writes no JSON: treat as ERROR, not NO RUN/CLEAN,
            # even for tasks the surviving subprocess reported cleanly.
            status = "ERROR"
        elif cert_verdict == "NO RUN" and not weight_runs:
            status = "NO RUN"
        elif cert_verdict == "PASS" and weight_worst in ("OK", "INFO"):
            status = "CLEAN"
        else:
            status = "NOT CLEAN"

        combined.append(
            {
                "task": tid,
                "certification_gate_verdict": cert_verdict,
                "certification_gate_open_items": ct.get("open_items", []),
                "certification_gate_reasons": ct.get("reasons", []),
                "n_cert_runs": ct.get("n_runs", 0),
                "n_oracle_runs": ct.get("n_oracle_runs", 0),
                "n_model_runs": ct.get("n_model_runs", 0),
                "weight_aggregation_verdicts": weight_verdicts,
                "weight_aggregation_worst_severity": weight_worst,
                "weight_aggregation_n_runs": len(weight_runs),
                "combined_status": status,
            }
        )
    return combined


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("task_ids", nargs="*", help="task ids to check (default: --all)")
    ap.add_argument(
        "--all", action="store_true", help="check every task directory under --root"
    )
    ap.add_argument(
        "--root",
        required=True,
        help="package root: one task directory per task (passed to both checks)",
    )
    ap.add_argument(
        "--run",
        action="append",
        default=[],
        required=True,
        help="a run root holding <task>/verifier/reward-details.json at any depth; "
        "repeatable; prefix 'oracle:' or 'model:' to force the run kind "
        "(prefix is passed to certification_gate_check as-is, stripped for "
        "weight_aggregation_check which does not support it)",
    )
    ap.add_argument(
        "--gate-records",
        action="append",
        default=[],
        help="gate-adjudication records, passed to certification_gate_check only; "
        "repeatable",
    )
    ap.add_argument(
        "--checks-summary",
        action="append",
        default=[],
        help="svc_run_checks.py output (summary.json or summary.csv), passed to "
        "certification_gate_check only; repeatable. Requires the glm-worker "
        "version of certification_gate_check.py (commit ba5c025); the current "
        "worktree may not have it yet",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="release threshold percent, passed to certification_gate_check only",
    )
    ap.add_argument(
        "--converter",
        default=None,
        help="path to rubric_xlsx_to_verifier.py, passed to certification_gate_check only",
    )
    ap.add_argument(
        "--require-model-run",
        action="store_true",
        help="promote gate_unexercised to an open item in certification_gate_check",
    )
    ap.add_argument(
        "--out-dir",
        required=True,
        help="output directory for the combined report and both checks' own JSON",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="seconds per check subprocess (default: 600)",
    )
    ap.add_argument(
        "--quiet", action="store_true", help="pass --quiet to both underlying checks"
    )
    args = ap.parse_args()

    if not args.all and not args.task_ids:
        sys.stderr.write("give task ids or --all\n")
        return 2
    if not CERT_GATE_SCRIPT.is_file():
        sys.stderr.write(f"certification_gate_check.py not found at {CERT_GATE_SCRIPT}\n")
        return 2
    if not WEIGHT_AGG_SCRIPT.is_file():
        sys.stderr.write(f"weight_aggregation_check.py not found at {WEIGHT_AGG_SCRIPT}\n")
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- discovery: which tasks have completed runs?
    discovered, disc_notes = discover_tasks_with_runs(args.run)
    print("=== discovery ===")
    for n in disc_notes:
        print(f"  {n}")
    if discovered:
        print(f"  {len(discovered)} task(s) with completed runs: {', '.join(discovered)}")
    else:
        print("  0 tasks with completed runs (no reward-details.json found under any --run root)")
        print("  the wrapper will still invoke both checks; they will report NO RUN per task")

    # ---- build common args
    use_all = args.all or not args.task_ids
    task_args = ["--all"] if use_all else list(args.task_ids)

    # ---- run certification_gate_check.py
    cert_out = out_dir / "certification_gate.json"
    cert_args = [
        "--root", args.root,
        *task_args,
        "--out", str(cert_out),
    ]
    for r in args.run:
        cert_args.extend(["--run", r])
    for gr in args.gate_records:
        cert_args.extend(["--gate-records", gr])
    for cs in args.checks_summary:
        cert_args.extend(["--checks-summary", cs])
    if args.threshold is not None:
        cert_args.extend(["--threshold", str(args.threshold)])
    if args.converter:
        cert_args.extend(["--converter", args.converter])
    if args.require_model_run:
        cert_args.append("--require-model-run")
    if args.quiet:
        cert_args.append("--quiet")

    print("\n=== certification_gate_check.py ===")
    cert_rc, cert_stdout, cert_stderr = run_subprocess(
        CERT_GATE_SCRIPT, cert_args, "certification_gate_check", args.timeout
    )
    print(cert_stdout.rstrip())
    if cert_stderr.strip():
        print(f"  stderr: {cert_stderr.strip()[:500]}")
    print(f"  exit code: {cert_rc}")

    # ---- run weight_aggregation_check.py
    weight_out = out_dir / "weight_aggregation.json"
    weight_args = [
        "--root", args.root,
        *task_args,
        "--json", str(weight_out),
    ]
    for r in args.run:
        # Strip oracle:/model: prefix: weight_aggregation_check does not support it
        weight_args.extend(["--run", _strip_run_prefix(r)])
    if args.quiet:
        weight_args.append("--quiet")

    print("\n=== weight_aggregation_check.py ===")
    weight_rc, weight_stdout, weight_stderr = run_subprocess(
        WEIGHT_AGG_SCRIPT, weight_args, "weight_aggregation_check", args.timeout
    )
    print(weight_stdout.rstrip())
    if weight_stderr.strip():
        print(f"  stderr: {weight_stderr.strip()[:500]}")
    print(f"  exit code: {weight_rc}")

    # ---- read both JSON outputs
    cert_report = _read_json(cert_out)
    weight_report = _read_json(weight_out)

    # ---- combine
    combined = combine_reports(cert_report, weight_report)
    counts: dict[str, int] = {}
    for c in combined:
        counts[c["combined_status"]] = counts.get(c["combined_status"], 0) + 1

    # ---- write combined report
    report = {
        "trigger": "post-Oracle gate: run after a task has at least one completed Oracle run recorded",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "root": args.root,
        "run_specs": args.run,
        "gate_records": args.gate_records,
        "checks_summary": args.checks_summary,
        "discovery": {
            "tasks_with_runs": discovered,
            "n_tasks_with_runs": len(discovered),
            "notes": disc_notes,
        },
        "certification_gate": {
            "exit_code": cert_rc,
            "report_path": str(cert_out),
            "summary": (cert_report or {}).get("summary", {}),
        },
        "weight_aggregation": {
            "exit_code": weight_rc,
            "report_path": str(weight_out),
            "summary": (weight_report or {}).get("summary", {}),
        },
        "combined_summary": counts,
        "tasks": combined,
    }
    report_path = out_dir / "post_oracle_gate_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"\n=== combined ===")
    for c in combined:
        print(
            f"  {c['combined_status']:<10} {c['task']:<20}  "
            f"cert={c['certification_gate_verdict']:<21}  "
            f"weight_worst={c['weight_aggregation_worst_severity']}"
        )
    print(f"\nsummary: {', '.join(f'{k}={v}' for k, v in sorted(counts.items()))} (of {len(combined)})")
    print(f"wrote {report_path}")

    if cert_report is None or weight_report is None:
        # Vacuous-pass guard: a crashed subprocess writes no JSON, so a task list
        # built only from valid JSON can be empty even though real data was lost.
        # Never let an empty combined list read as "everything is CLEAN".
        return 1
    if any(c["combined_status"] != "CLEAN" for c in combined):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
