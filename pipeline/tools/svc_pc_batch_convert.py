#!/usr/bin/env python3
"""svc_pc_batch_convert.py -- batch-convert every SVC-PC task under
pipeline/data/svc_pc_qc/00_fetched/ into DataOS reward-kit format.

Pipeline per task: rubric_xlsx_to_verifier -> assemble_task.py -> to_rewardkit.py.
Single-file delivery only (project constraint) -- any task that fails at any
stage (multiple deliverables, ambiguous rubric/prompt file, etc.) is routed
to a "messy" output folder with the specific reason recorded in
incidents.md, instead of guessing.

Every task now gets the shared corpus's DVC pointer unconditionally --
`assemble_task.py` always includes it, regardless of this script's own
branching below. That branching still exists, but only decides whether
`hydrate_environment.py` also runs to selectively resolve and stage named
input files for a task: most tasks name specific input files (or have
L1-XX-NN upstream outputs) it can resolve. A task whose prompt expects the
agent to explore the WHOLE shared corpus instead (e.g. "Company records -
Cirrus Sleep Full Y1 ... + related workstream outputs where noted", no named
files) skips that step -- selective hydration on a task like that finds no
filenames to resolve and would ship an empty/placeholder workspace on top of
the (always-present) DVC pointer, which is just noise. There's no reliable
automatic signal to tell the two cases apart (a prompt that names zero files
could legitimately need zero inputs, or could need the whole corpus), so
this remains opt-in per task: drop an empty marker file named `_FULLCORPUS`
directly in a task's 00_fetched/<task_id>/ directory to skip selective
hydration. Forgetting the marker no longer risks an unreachable environment
either way -- it only means selective hydration ran (harmlessly) and named
files may additionally be staged flat, on top of the corpus DVC always
provides.

Usage:
    python svc_pc_batch_convert.py [--input-root PATH] [--output-root PATH]
                                   [--corpus-root PATH] [--scratch-root PATH]
                                   [--python PATH] [--only TASK[,TASK...]]
                                   [--preflight] [--reset]

Each path can also be supplied through its matching environment variable:
SVC_PC_INPUT_ROOT, SVC_PC_OUTPUT_ROOT, SVC_PC_CORPUS_ROOT,
SVC_PC_SCRATCH_ROOT, and SVC_PC_PYTHON. Command-line values take precedence.

`--preflight` checks the local paths and staged task count without creating,
changing, or deleting any package output. Normal builds preserve existing
ready and messy task outputs. Pass `--reset` only when you intentionally want
to replace the selected outputs.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import rubric_xlsx_to_verifier as rxv
import hydrate_environment as he

REPO = Path(__file__).resolve().parents[2]
TOOLS = Path(__file__).resolve().parent
DEFAULT_INPUT_ROOT = REPO / "pipeline/data/svc_pc_qc/00_fetched"
DEFAULT_OUTPUT_ROOT = REPO / "pipeline/data/svc_pc_qc"
DEFAULT_SCRATCH_ROOT = (
    REPO / "pipeline/data/svc_pc_qc/_scratch"
    if os.name == "nt"
    else Path("/tmp/svc_pc_batch_scratch")
)
DEFAULT_VENV_PYTHON = (
    REPO
    / "pipeline/.venv"
    / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
)
DEFAULT_PYTHON = (
    DEFAULT_VENV_PYTHON if DEFAULT_VENV_PYTHON.is_file() else Path(sys.executable)
)


class TaskFailure(Exception):
    pass


def process_task(
    task_dir: Path,
    scratch: Path,
    corpus_index: dict,
    persona_slugs: set,
    python: Path,
) -> tuple[Path, dict]:
    """Run one task through the full chain. Returns (reward-kit output dir,
    hydration report) on success; raises TaskFailure with a specific reason
    otherwise."""
    task_id = task_dir.name

    try:
        prompt_path = rxv.find_prompt_file(task_dir)
    except rxv.ConversionError as e:
        raise TaskFailure(f"prompt file: {e}") from e
    prompt_text = rxv.extract_prompt_text(prompt_path)
    prompt_out = scratch / "prompt.md"
    prompt_out.write_text(prompt_text, encoding="utf-8")

    try:
        verifier = rxv.convert(task_dir)
    except rxv.ConversionError as e:
        raise TaskFailure(f"rubric conversion: {e}") from e
    verifier_out = scratch / "verifier.json"
    verifier_out.write_text(json.dumps(verifier, indent=2), encoding="utf-8")

    try:
        deliverable_names = rxv.find_deliverable_files(task_dir)
    except rxv.ConversionError as e:
        raise TaskFailure(f"golden deliverable: {e}") from e
    solution_dir = scratch / "golden"
    solution_dir.mkdir(parents=True, exist_ok=True)
    for deliverable_name in deliverable_names:
        deliverable_path = rxv.resolve_deliverable_path(task_dir, deliverable_name)
        shutil.copy2(deliverable_path, solution_dir / deliverable_name)

    harbor_out = scratch / "harbor"
    dvc_fullcorpus = (task_dir / "_FULLCORPUS").is_file()
    if dvc_fullcorpus:
        hydration_report = {"task_id": task_id, "resolved": [], "not_found": [], "ambiguous": [],
                             "dvc_fullcorpus": True}
        assemble_args = [
            str(python), str(TOOLS / "assemble_task.py"),
            "--task-id", task_id,
            "--prompt", str(prompt_out),
            "--dvc-fullcorpus",
            "--solution-dir", str(solution_dir),
            "--verifier", str(verifier_out),
            "--out", str(harbor_out),
            "--category", "SVC-PC",
        ]
    else:
        source_dir = scratch / "source"
        hydration_report = he.hydrate(task_dir, corpus_index, persona_slugs, source_dir)
        assemble_args = [
            str(python), str(TOOLS / "assemble_task.py"),
            "--task-id", task_id,
            "--prompt", str(prompt_out),
            "--source-dir", str(source_dir),
            "--solution-dir", str(solution_dir),
            "--verifier", str(verifier_out),
            "--out", str(harbor_out),
            "--category", "SVC-PC",
        ]

    result = subprocess.run(assemble_args, capture_output=True, text=True)
    if result.returncode != 0:
        raise TaskFailure(
            f"assemble_task.py: {result.stderr.strip() or result.stdout.strip()}"
        )

    rewardkit_out = scratch / "rewardkit"
    result = subprocess.run(
        [
            str(python),
            str(TOOLS / "to_rewardkit.py"),
            str(harbor_out / task_id),
            str(rewardkit_out),
            "svc",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise TaskFailure(
            f"to_rewardkit.py: {result.stderr.strip() or result.stdout.strip()}"
        )

    return rewardkit_out, hydration_report


def _path_from_env(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--input-root",
        type=Path,
        default=_path_from_env("SVC_PC_INPUT_ROOT", DEFAULT_INPUT_ROOT),
        help="directory containing one staged folder per task",
    )
    ap.add_argument(
        "--output-root",
        type=Path,
        default=_path_from_env("SVC_PC_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT),
        help="parent directory for 03_dataos_ready and 03_dataos_messy",
    )
    ap.add_argument(
        "--corpus-root",
        type=Path,
        default=_path_from_env("SVC_PC_CORPUS_ROOT", he.DEFAULT_CORPUS),
        help="local Cirrus Sleep Full Y1 corpus root used by hydration",
    )
    ap.add_argument(
        "--scratch-root",
        type=Path,
        default=_path_from_env("SVC_PC_SCRATCH_ROOT", DEFAULT_SCRATCH_ROOT),
        help="local temporary directory for per-task build intermediates",
    )
    ap.add_argument(
        "--python",
        type=Path,
        default=_path_from_env("SVC_PC_PYTHON", DEFAULT_PYTHON),
        help="Python interpreter used for assemble_task.py and to_rewardkit.py",
    )
    ap.add_argument(
        "--only",
        default="",
        help="comma-separated task IDs to build; default builds every staged task",
    )
    ap.add_argument(
        "--preflight",
        action="store_true",
        help="validate paths and count staged task folders without writing output",
    )
    ap.add_argument(
        "--reset",
        action="store_true",
        help="replace existing ready and messy outputs for the selected task(s)",
    )
    return ap.parse_args(argv)


def _requested_task_ids(value: str) -> set[str]:
    return {task_id.strip() for task_id in value.split(",") if task_id.strip()}


def _report_path(path: Path) -> Path:
    """Choose a new report name instead of overwriting an earlier report."""
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not choose a non-conflicting report path near {path}")


def preflight(args: argparse.Namespace) -> tuple[bool, list[Path]]:
    checks = {
        "input root": args.input_root,
        "corpus root": args.corpus_root,
        "python interpreter": args.python,
    }
    failed = False
    for label, path in checks.items():
        expected = path.is_file() if label == "python interpreter" else path.is_dir()
        state = "ok" if expected else "MISSING"
        print(f"{label}: {state}  {path}")
        failed = failed or not expected

    task_dirs = (
        sorted(p for p in args.input_root.iterdir() if p.is_dir())
        if args.input_root.is_dir()
        else []
    )
    requested = _requested_task_ids(args.only)
    if requested:
        found = {task_dir.name for task_dir in task_dirs}
        missing = sorted(requested - found)
        if missing:
            print(f"requested task folders: MISSING  {', '.join(missing)}")
            failed = True
        task_dirs = [task_dir for task_dir in task_dirs if task_dir.name in requested]
    if not task_dirs:
        print("staged task folders: MISSING  0")
        failed = True
    else:
        print(f"staged task folders: ok  {len(task_dirs)}")
    print(f"output root (not created by preflight): {args.output_root}")
    print(f"scratch root (not created by preflight): {args.scratch_root}")
    return not failed, task_dirs


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.input_root = args.input_root.expanduser().resolve()
    args.output_root = args.output_root.expanduser().resolve()
    args.corpus_root = args.corpus_root.expanduser().resolve()
    args.scratch_root = args.scratch_root.expanduser().resolve()
    args.python = args.python.expanduser().resolve()
    paths_ok, task_dirs = preflight(args)
    if not paths_ok:
        return 2
    if args.preflight:
        return 0

    ready = args.output_root / "03_dataos_ready"
    messy = args.output_root / "03_dataos_messy"
    requested = _requested_task_ids(args.only)
    if args.reset:
        if requested:
            for output_dir in (ready, messy):
                for task_id in requested:
                    task_output = output_dir / task_id
                    if task_output.exists():
                        shutil.rmtree(task_output)
        else:
            if ready.exists():
                shutil.rmtree(ready)
            if messy.exists():
                shutil.rmtree(messy)
    ready.mkdir(parents=True, exist_ok=True)
    messy.mkdir(parents=True, exist_ok=True)
    args.scratch_root.mkdir(parents=True, exist_ok=True)

    print(f"indexing corpus ({args.corpus_root}) ...")
    corpus_index = he.build_corpus_index(args.corpus_root)
    persona_slugs = {
        m.group("slug")
        for d in args.corpus_root.iterdir()
        if (m := he.PERSONA_DIR_RE.match(d.name))
    }
    print(
        f"  indexed {sum(len(v) for v in corpus_index.values())} files, {len(persona_slugs)} personas"
    )

    incidents = []
    hydration_reports = []
    ready_count = 0

    for task_dir in task_dirs:
        task_id = task_dir.name
        print(f"=== {task_id} ===")
        ready_dest = ready / task_id
        messy_dest = messy / task_id
        if ready_dest.exists() or messy_dest.exists():
            reason = "output already exists; choose a new --output-root or rerun with --reset"
            print(f"  SKIPPED: {reason}")
            incidents.append((task_id, reason))
            continue

        scratch = args.scratch_root / task_id
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True)

        try:
            rewardkit_out, hydration_report = process_task(
                task_dir, scratch, corpus_index, persona_slugs, args.python
            )
        except TaskFailure as e:
            print(f"  MESSY: {e}")
            incidents.append((task_id, str(e)))
            shutil.copytree(task_dir, messy_dest)
            continue

        hydration_reports.append(hydration_report)
        shutil.copytree(rewardkit_out, ready_dest)
        ready_count += 1
        print(
            f"  READY -> {ready_dest} "
            f"(hydrated: {len(hydration_report['resolved'])} resolved, "
            f"{len(hydration_report['not_found'])} not-found, "
            f"{len(hydration_report['ambiguous'])} ambiguous, "
            f"manifest declared: {hydration_report.get('manifest_declared_count', 0)})"
        )

    incidents_path = _report_path(messy / "incidents.md")
    lines = [
        f"# SVC-PC batch conversion incidents ({len(incidents)} of {len(task_dirs)} tasks)",
        "",
    ]
    for task_id, reason in incidents:
        lines.append(f"- **{task_id}**: {reason}")
    incidents_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    hydration_path = _report_path(args.output_root / "_HYDRATION_REPORT.md")
    totals = {
        "resolved": 0,
        "not_found": 0,
        "ambiguous": 0,
        "placeholder": 0,
        "manifest_declared": 0,
    }
    hlines = [f"# Hydration report ({len(hydration_reports)} tasks)", ""]
    for r in hydration_reports:
        totals["resolved"] += len(r["resolved"])
        totals["not_found"] += len(r["not_found"])
        totals["ambiguous"] += len(r["ambiguous"])
        totals["placeholder"] += 1 if r.get("placeholder") else 0
        # Claire's Central Task Platform Read Me input manifest -- a third
        # hydration source alongside L1-* subfolders and prompt-text-scanned
        # filenames (see hydrate_environment.declared_manifest_paths()).
        totals["manifest_declared"] += r.get("manifest_declared_count", 0)
        flag = " (placeholder)" if r.get("placeholder") else ""
        hlines.append(
            f"## {r['task_id']}: {len(r['resolved'])} resolved, "
            f"{len(r['not_found'])} not-found, {len(r['ambiguous'])} ambiguous, "
            f"{r.get('manifest_declared_count', 0)} manifest declared{flag}"
        )
        for x in r["not_found"]:
            hlines.append(f"- NOT FOUND: {x}")
        for x in r["ambiguous"]:
            hlines.append(f"- AMBIGUOUS: {x}")
    hlines.insert(
        1,
        f"Totals: {totals['resolved']} resolved, {totals['not_found']} not-found, "
        f"{totals['ambiguous']} ambiguous, {totals['placeholder']} placeholder-only tasks, "
        f"{totals['manifest_declared']} Read Me manifest path(s) declared\n",
    )
    hydration_path.write_text("\n".join(hlines) + "\n", encoding="utf-8")

    print()
    print(f"done: {ready_count} ready, {len(incidents)} messy (see {incidents_path})")
    print(f"hydration totals: {totals} (see {hydration_path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
