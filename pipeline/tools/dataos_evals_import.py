#!/usr/bin/env python3
"""Import a Data-OS QC-run drop (the `dataos-qc-run` skill's output) into the
03_evals/ shape Internal QC's engine already reads.

The skill (skills/ekw/dataos-qc-run/SKILL.md) downloads, per task:
  dataos_qc_runs/<dataset_name>/task_<id>/
    task_<id>_evals.zip                  # per-agent trial artifacts
    task_<id>_verifications_results.json # Data-OS's own trajectory-verification flags

Unzipped, task_<id>_evals.zip contains one top-level folder per agent run
(claude-code_<runid>/, codex_<runid>/, sometimes oracle_<runid>/), each with
artifacts/, verifier/{reward.json,reward-details.json,runtime.log}, agent/.

This writes, per task:
  <evals_out>/task_<id>/                       # authoritative def, copied from bundle_dir
    evals/anthropic__claude-opus-4-8/trial_1/  # <- claude-code_* run, verbatim contents
    evals/openai__gpt-5-6-sol/trial_1/         # <- codex_* run, verbatim contents
    oracle/                                    # <- oracle_* run if present (not under evals/ --
                                                #    excluded from reward-stats/judge dims, same as
                                                #    the browser-driven flow already excludes it)
    verifications_results.json                 # Data-OS's own flags -- new artifact, not read by
                                                #    the QC engine itself, consumed by joint-feedback

build_verifier_assertion_summary() (gdpval_qc/v18_verifier_summary.py) walks any
evals/<name>/trial_*/ with a verifier/reward.json (or verifier-report.json) inside
-- no special naming convention required beyond that, so this reshape alone is
enough to ground the QC engine's eval-dependent verifier-quality dims; no engine
change needed.

Usage: python3 dataos_evals_import.py <dataos_qc_runs_dir> <bundle_dir> <evals_out_dir> [--only ids]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

AGENT_TO_MODEL = {
    "claude-code": "anthropic__claude-opus-4-8",
    "codex": "openai__gpt-5-6-sol",
}


def _task_id_from_dirname(name: str) -> str:
    return name[len("task_"):] if name.startswith("task_") else name


def _import_one(task_dropdir: Path, bundle_dir: Path, evals_out: Path) -> tuple[str, str]:
    """Returns (task_id, status) where status is "ok" or a skip/error reason."""
    tid = _task_id_from_dirname(task_dropdir.name)
    bundle_task = bundle_dir / f"task_{tid}"
    if not bundle_task.is_dir():
        return tid, f"skip: no matching {bundle_dir.name}/task_{tid}/"

    zips = list(task_dropdir.glob("task_*_evals.zip")) or list(task_dropdir.glob("*_evals.zip"))
    verifs = (list(task_dropdir.glob("task_*_verifications_results.json"))
              or list(task_dropdir.glob("*_verifications_results.json")))
    if not zips:
        return tid, "skip: no *_evals.zip found"

    dst = evals_out / f"task_{tid}"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(bundle_task, dst)  # authoritative task definition, same as cmd_evals

    n_agents, n_oracle = 0, 0
    with zipfile.ZipFile(zips[0]) as zf:
        names = zf.namelist()
        top_dirs = sorted({n.split("/", 1)[0] for n in names if "/" in n})
        tmp = dst / ".dataos_unzip_tmp"
        zf.extractall(tmp)
        for d in top_dirs:
            src_dir = tmp / d
            if not src_dir.is_dir():
                continue
            agent = d.split("_", 1)[0].lower()
            if agent == "oracle":
                oracle_dst = dst / "oracle" / d
                oracle_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src_dir), str(oracle_dst))
                n_oracle += 1
                continue
            model = AGENT_TO_MODEL.get(agent)
            if model is None:
                continue  # unrecognized top-level entry; not a known agent-run folder
            trial_dst = dst / "evals" / model / "trial_1"
            trial_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_dir), str(trial_dst))
            n_agents += 1
        shutil.rmtree(tmp, ignore_errors=True)

    if verifs:
        shutil.copy2(verifs[0], dst / "verifications_results.json")

    if n_agents == 0:
        return tid, "warn: evals.zip had no recognized claude-code_*/codex_* trial folder"
    return tid, f"ok: {n_agents} agent trial(s)" + (f", {n_oracle} oracle" if n_oracle else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataos_qc_runs_dir")
    ap.add_argument("bundle_dir")
    ap.add_argument("evals_out_dir")
    ap.add_argument("--only", default="", help="comma-separated task ids to restrict to")
    args = ap.parse_args(argv)

    runs_dir = Path(args.dataos_qc_runs_dir)
    bundle_dir = Path(args.bundle_dir)
    evals_out = Path(args.evals_out_dir)
    if not runs_dir.is_dir():
        sys.exit(f"dataos_qc_runs_dir not found: {runs_dir}")
    if not bundle_dir.is_dir():
        sys.exit(f"bundle_dir not found: {bundle_dir}")
    evals_out.mkdir(parents=True, exist_ok=True)
    only = {t.strip() for t in args.only.split(",") if t.strip()}

    task_dirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    if not task_dirs:
        sys.exit(f"no task_<id>/ drop dirs found in {runs_dir}")

    ok, skipped = [], []
    for d in task_dirs:
        tid = _task_id_from_dirname(d.name)
        if only and tid not in only:
            continue
        tid, status = _import_one(d, bundle_dir, evals_out)
        print(f"  task_{tid}: {status}")
        (ok if status.startswith("ok") else skipped).append(tid)

    print(f"imported {len(ok)} task(s) -> {evals_out}")
    if skipped:
        print(f"  {len(skipped)} skipped/warned: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
