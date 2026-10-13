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
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


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
) -> Path:
    """Write one harbor-shaped task folder at `out_dir / task_id`."""
    dest = out_dir / task_id
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    (dest / "instruction.md").write_text(prompt_text, encoding="utf-8")

    env = dest / "environment" / "data"
    n_source = _copy_dir_contents(source_dir, env) if source_dir else 0

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
        f"verifier: {len(verifier_text)} chars)"
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
    args = ap.parse_args()

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
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
