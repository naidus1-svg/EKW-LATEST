#!/usr/bin/env python3
"""svc_pc_batch_convert.py -- batch-convert every SVC-PC task under
pipeline/data/svc_pc_qc/00_fetched/ into DataOS reward-kit format.

Pipeline per task: rubric_xlsx_to_verifier -> assemble_task.py -> to_rewardkit.py.
Single-file delivery only (project constraint) -- any task that fails at any
stage (multiple deliverables, ambiguous rubric/prompt file, etc.) is routed
to a "messy" output folder with the specific reason recorded in
incidents.md, instead of guessing.

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


def strip_metadata_lines(prompt_text: str, task_id: str) -> str:
    """Remove internal task-node metadata lines from prompt text.

    Strips lines containing L2-NN / L3 node tokens, 'Node:', 'Level:', or
    'Prompt verified:' fields that are metadata headers, never dropping
    lines that are part of the scenario narrative.

    Returns the cleaned prompt text and prints count of stripped lines.
    """
    import re

    lines = prompt_text.split("\n")
    stripped_count = 0
    kept_lines = []

    for line in lines:
        should_strip = False

        # Check for explicit field indicators
        if "Node:" in line or "Level:" in line or "Prompt verified:" in line:
            should_strip = True
        # Check for L2-NN or L3-NN patterns at line start (title/header lines
        # like "# L2-04 -- Prompt" or "L2-01 | Quarterly ..."). Anchored so a
        # narrative sentence that merely mentions a node id in passing (e.g.
        # "...carried forward from the L2-01 baseline...") is never stripped.
        elif re.match(r"^#*\s*L[23]-\d{2}\b", line):
            should_strip = True
        # Check for bare L2 or L3 at line start (e.g., "L2 node · Accounting")
        elif re.match(r"^L[23]\s+", line):
            should_strip = True

        if should_strip:
            stripped_count += 1
        else:
            kept_lines.append(line)

    if stripped_count > 0:
        print(f"  stripped {stripped_count} metadata line(s)")

    return "\n".join(kept_lines)


def process_task(
    task_dir: Path,
    scratch: Path,
    corpus_index: dict,
    persona_slugs: set,
    python: Path,
    corpus_root: Path,
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

    # Strip internal task-node metadata from the prompt
    prompt_text = strip_metadata_lines(prompt_text, task_id)

    # Find deliverable names to add to prompt before writing
    try:
        deliverable_names = rxv.find_deliverable_files(task_dir)
    except rxv.ConversionError as e:
        raise TaskFailure(f"golden deliverable: {e}") from e

    # Add "Graded deliverable filenames" section if not already present and if there are deliverables
    if deliverable_names:
        if "Graded deliverable filenames" not in prompt_text:
            section_lines = [
                "",
                "## Graded deliverable filenames",
                "",
                "Submit the graded deliverables using these exact filenames (and paths where shown):",
                "",
            ]
            for deliverable_name in deliverable_names:
                section_lines.append(f"- `{deliverable_name}`")
            section_lines.append("")

            prompt_text = prompt_text + "\n" + "\n".join(section_lines)
        # else: section already present, don't add duplicate
    else:
        print(f"  warning: no graded deliverables found for {task_id}")

    prompt_out = scratch / "prompt.md"
    prompt_out.write_text(prompt_text, encoding="utf-8")

    try:
        verifier = rxv.convert(task_dir)
    except rxv.ConversionError as e:
        raise TaskFailure(f"rubric conversion: {e}") from e
    verifier_out = scratch / "verifier.json"
    verifier_out.write_text(json.dumps(verifier, indent=2), encoding="utf-8")
    solution_dir = scratch / "golden"
    solution_dir.mkdir(parents=True, exist_ok=True)
    for deliverable_name in deliverable_names:
        deliverable_path = rxv.resolve_deliverable_path(task_dir, deliverable_name)
        shutil.copy2(deliverable_path, solution_dir / deliverable_name)

    source_dir = scratch / "source"
    hydration_report = he.hydrate(
        task_dir, corpus_index, persona_slugs, source_dir, corpus_root=corpus_root
    )
    # Cause 3: hydrate() itself never raises -- a placeholder that is NOT the
    # legitimate "reasoning-only, no input needed" case is a real hydration
    # gap and must not silently ship to 03_dataos_ready with just a
    # placeholder file in it. Route it to messy instead, same as any other
    # stage failure, so it gets picked up on the next --only/--reset pass
    # instead of being invisible until someone happens to notice the
    # placeholder file by hand.
    placeholder_kind = hydration_report.get("placeholder_kind")
    if hydration_report.get("placeholder") and placeholder_kind != "reasoning_only":
        detail = ""
        if placeholder_kind == "template_authoring_defect":
            detail = f" ({hydration_report['template_authoring_defect']})"
        elif hydration_report.get("unresolved_prompt_names"):
            detail = f" (unresolved: {hydration_report['unresolved_prompt_names']})"
        raise TaskFailure(f"hydration: {placeholder_kind}{detail}")
    # A Source:/placeholder template-authoring defect (Cause 5) needs a
    # human to fix the prompt regardless of whether the environment ended
    # up empty -- the role-match bucket fallback can still populate
    # plausible department files, but it never recovers the SPECIFIC
    # upstream file the broken template lost, so this always routes to
    # messy for review rather than only when nothing else compensated.
    if hydration_report.get("template_authoring_defect"):
        raise TaskFailure(
            "hydration: template_authoring_defect "
            f"({hydration_report['template_authoring_defect']})"
        )

    harbor_out = scratch / "harbor"
    result = subprocess.run(
        [
            str(python),
            str(TOOLS / "assemble_task.py"),
            "--task-id",
            task_id,
            "--prompt",
            str(prompt_out),
            "--source-dir",
            str(source_dir),
            "--solution-dir",
            str(solution_dir),
            "--verifier",
            str(verifier_out),
            "--out",
            str(harbor_out),
            "--category",
            "SVC-PC",
        ],
        capture_output=True,
        text=True,
    )
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
    try:
        corpus_index, persona_slugs, corpus_warnings = he.index_corpus(args.corpus_root)
    except he.CorpusIndexError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    for w in corpus_warnings:
        print(f"  WARNING: {w}", file=sys.stderr)
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
                task_dir,
                scratch,
                corpus_index,
                persona_slugs,
                args.python,
                args.corpus_root,
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
