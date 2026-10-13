#!/usr/bin/env python3
"""assemble_task.py — turn an expert's loose task pieces into one harbor-shaped
task folder that `gdpval-assess` (`gdpval_qc.v18_loader.TaskCorpusLoader`) can
load directly.

A non-technical expert running the streamlined-qc skill hands over four
pieces individually — a prompt, a folder of source/input files, a folder of
expert-solution files, and a verifier JSON — the same shape
`skills/ekw/gdpval-task-qc` already asks for. This tool is the one place that
understands "loose expert pieces -> harbor task", modeled on the corpus
writer in `build_corpus.py` (task.toml / instruction.md / environment/ /
solution/golden_outputs/ / tests/verifier.json). It never talks to a cycle
folder or the tracker CSV — the caller supplies everything explicitly.

Usage
-----
    python assemble_task.py \\
        --task-id my_task \\
        --prompt prompt.md \\
        --source-dir "Source Documents/" \\
        --solution-dir "Expert Solution/" \\
        --verifier verifier.json \\
        --out /tmp/streamlined_qc/my_task

`--prompt` accepts a file path or `-` to read from stdin.
`--solution-dir` is optional — Solution QC dims are simply skipped by the
engine when `solution/golden_outputs/` doesn't exist.

Every SVC-PC task (`--category` starting with "SVC", case-insensitive)
automatically ships the canonical `data.dvc` + `.dvc/config` pointer from
`pipeline/templates/svc_fullcorpus_dvc/` (pushed once to gs://colab-bench per
https://data-os.turing.com/docs/dvc-large-files; verified end-to-end
2026-08-27 — dvc push then a clean dvc pull round-tripped all 1180 files),
alongside any `--source-dir` files. This is a deliberate safety net, not a
redundant default: selective hydration (`hydrate_environment.py`) has shipped
tasks whose named source files exist in the standing shared corpus by exact
filename but were never resolved or mounted into that specific task's
environment (confirmed on cirrus-y1-task-svc-pc-47-3-0 and svc-pc-53-2-0 —
both shipped a "_SOURCES_NEEDED.md, nothing mounted" placeholder for files
that were genuinely present in the corpus all along). Making the DVC pointer
automatic for every SVC-PC task means a selective-hydration miss is no longer
a dead end — the full corpus is always reachable via `dvc pull` at
container-build time regardless. `to_rewardkit.py` detects the pointer
downstream and injects the matching Dockerfile block; real named files (if
any) land flat under `/app/` as before, while `dvc pull` separately
materializes the full corpus at `/app/data/` — the two don't collide.

This pointer is SVC-PC-specific (the "Cirrus Sleep Full Y1" fictional-company
corpus) — `assemble_task.py` is also the shared assembler for EKW tasks (see
`skills/ekw/harbor-task-intake`), which have nothing to do with that corpus,
so inclusion is gated on `--category` rather than unconditional.
`--dvc-fullcorpus` is kept as an explicit override for the rare non-SVC-PC
task that genuinely needs this specific corpus anyway; it no longer needs to
be mutually exclusive with `--source-dir`.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

DVC_FULLCORPUS_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "svc_fullcorpus_dvc"


def _read_prompt(spec: str) -> str:
    if spec == "-":
        return sys.stdin.read()
    path = Path(spec).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"--prompt file not found: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def _copy_dir_contents(src: Path, dest: Path) -> int:
    """Copy every file under `src` (recursively) into `dest`, preserving
    relative structure. Returns the number of files copied."""
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
        count += 1
    return count


def assemble(
    task_id: str,
    prompt_text: str,
    source_dir: Path | None,
    solution_dir: Path | None,
    verifier_path: Path,
    out_dir: Path,
    category: str = "",
    dvc_fullcorpus: bool = False,
) -> Path:
    """Write one harbor-shaped task folder at `out_dir / task_id`."""
    dest = out_dir / task_id
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    (dest / "instruction.md").write_text(prompt_text, encoding="utf-8")

    # The shared corpus's DVC pointer is SVC-PC-specific (it's the "Cirrus
    # Sleep Full Y1" fictional-company corpus) -- shipping it on every task
    # regardless of category would staple an irrelevant, off-topic corpus
    # onto e.g. EKW tasks assembled via this same tool. Every SVC-PC task
    # gets it unconditionally (category detection, not --dvc-fullcorpus,
    # which is kept only as an explicit override for the rare non-SVC-PC
    # task that genuinely needs this specific corpus). This is a safety net
    # against selective hydration silently missing a named file that's
    # actually in the standing corpus.
    env_dir = dest / "environment"
    env_dir.mkdir(parents=True, exist_ok=True)
    include_dvc = dvc_fullcorpus or category.strip().upper().startswith("SVC")
    dvc_note = ""
    if include_dvc:
        shutil.copy2(DVC_FULLCORPUS_TEMPLATE / "data.dvc", env_dir / "data.dvc")
        shutil.copytree(DVC_FULLCORPUS_TEMPLATE / ".dvc", env_dir / ".dvc")
        dvc_note = ", dvc full-corpus pointer (data.dvc + .dvc/config)"

    n_source = 0
    if source_dir:
        env = env_dir / "data"
        n_source = _copy_dir_contents(source_dir, env)

    n_solution = 0
    if solution_dir is not None:
        sol = dest / "solution" / "golden_outputs"
        n_solution = _copy_dir_contents(solution_dir, sol)

    tests = dest / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    verifier_text = verifier_path.read_text(encoding="utf-8", errors="replace")
    (tests / "verifier.json").write_text(verifier_text, encoding="utf-8")

    toml = (
        'version = "1.0"\n'
        'artifacts = ["/workspace/output"]\n\n'
        "[metadata]\n"
        f'task_id = "{task_id}"\n'
        f'category = "{category}"\n'
        'difficulty = ""\n'
        "tags = []\n"
    )
    (dest / "task.toml").write_text(toml, encoding="utf-8")

    print(
        f"Assembled {dest} "
        f"(instruction: {len(prompt_text)} chars, "
        f"{n_source} source file(s), {n_solution} solution file(s), "
        f"verifier: {len(verifier_text)} chars{dvc_note})"
    )
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--prompt", required=True, help="prompt file path, or - for stdin")
    ap.add_argument("--source-dir", type=Path, default=None,
                     help="folder of source/input files (optional)")
    ap.add_argument("--solution-dir", type=Path, default=None,
                     help="folder of expert-solution files (optional)")
    ap.add_argument("--verifier", type=Path, required=True, help="verifier JSON file")
    ap.add_argument("--out", type=Path, required=True,
                     help="corpus directory to write <task-id>/ under")
    ap.add_argument("--category", default="", help="task.toml [metadata].category")
    ap.add_argument("--dvc-fullcorpus", action="store_true",
                     help="force-include the shared SVC-PC corpus's DVC pointer "
                          "(pipeline/templates/svc_fullcorpus_dvc/) even when --category "
                          "doesn't start with 'SVC'. Every --category starting with 'SVC' "
                          "(case-insensitive) already includes it automatically -- this "
                          "flag is only for the rare non-SVC-PC task that genuinely needs "
                          "this specific corpus anyway")
    args = ap.parse_args()

    needs_dvc = args.dvc_fullcorpus or args.category.strip().upper().startswith("SVC")
    if needs_dvc and not (DVC_FULLCORPUS_TEMPLATE / "data.dvc").is_file():
        print(f"ERROR: DVC full-corpus template missing at {DVC_FULLCORPUS_TEMPLATE}", file=sys.stderr)
        return 2
    if args.source_dir is not None and not args.source_dir.is_dir():
        print(f"ERROR: --source-dir not a directory: {args.source_dir}", file=sys.stderr)
        return 2
    if args.solution_dir is not None and not args.solution_dir.is_dir():
        print(f"ERROR: --solution-dir not a directory: {args.solution_dir}", file=sys.stderr)
        return 2
    if not args.verifier.is_file():
        print(f"ERROR: --verifier not a file: {args.verifier}", file=sys.stderr)
        return 2

    prompt_text = _read_prompt(args.prompt)
    args.out.mkdir(parents=True, exist_ok=True)
    assemble(
        task_id=args.task_id,
        prompt_text=prompt_text,
        source_dir=args.source_dir,
        solution_dir=args.solution_dir,
        verifier_path=args.verifier,
        out_dir=args.out,
        category=args.category,
        dvc_fullcorpus=args.dvc_fullcorpus,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
