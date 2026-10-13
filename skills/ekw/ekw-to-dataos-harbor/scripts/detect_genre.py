#!/usr/bin/env python3
"""detect_genre.py -- determine whether an EKW harbor task is "native-harbor" or
"rewardkit-hybrid" genre, so the right converter (to_dataos_harbor.py vs
to_rewardkit.py) can be chosen. Extracted verbatim from deterministic-checks/ekw/
ekw_check_b.py's detect_genre() (2026-09-14 mutation-tested version) -- logic
unchanged, lifted out so it has zero dependency on the rest of that check suite.

Two build genres share one directory layout in the EKW corpus:
  - native-harbor: task.toml has `artifacts =`, solve.sh copies golden_outputs/ to
    the workspace, Dockerfile installs verifier-requirements.txt / copies skills,
    tests/verifier_runtime.py is present. Convert with to_dataos_harbor.py.
  - rewardkit-hybrid: task.toml has `schema_version = "1.1"`, solve.sh copies
    /solution/files/ to /app/, Dockerfile does `COPY initial_workspace/ /app/`,
    no verifier_runtime.py. Convert with to_rewardkit.py.

Each of the four signal files (solve.sh, Dockerfile, task.toml, verifier_runtime.py
presence) votes once. A file carrying markers of BOTH genres votes "conflict"
(no vote) rather than an if/elif letting whichever test happened to run first win
silently -- this exact scenario (a task.toml with both `schema_version = "1.1"`
and `artifacts =`) hid a missing runtime file behind the wrong genre before this
fix. Genre is decided by majority vote across the (at most 4) votes cast; a tie
or zero votes returns "unknown" -- never guess.

Usage:
    python detect_genre.py <task_dir>                  # one task, prints JSON
    python detect_genre.py --all <root_dir>             # every task_* dir under root, prints a table
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def detect_genre(task_dir: Path) -> dict:
    solve = _read_text(task_dir / "solution" / "solve.sh")
    dock = _read_text(task_dir / "environment" / "Dockerfile")
    toml_txt = _read_text(task_dir / "task.toml")
    instr = _read_text(task_dir / "instruction.md")
    sig = {}

    def vote(hybrid: bool, native: bool, present: bool):
        if hybrid and native:
            return "conflict"
        if hybrid:
            return "rewardkit-hybrid"
        if native:
            return "native-harbor"
        return "unknown" if present else None

    sig["solve_sh"] = vote(
        "/solution/files" in solve and "/app" in solve,
        "golden_outputs" in solve or "OUTPUT_DIR" in solve,
        bool(solve),
    )
    sig["dockerfile"] = vote(
        bool(re.search(r"^COPY\s+initial_workspace/", dock, re.M)),
        "verifier-requirements.txt" in dock or "--from=skills" in dock,
        bool(dock),
    )
    sig["task_toml"] = vote(
        bool(re.search(r'^schema_version\s*=\s*"1\.1"', toml_txt, re.M)),
        bool(re.search(r"^artifacts\s*=", toml_txt, re.M)),
        bool(toml_txt),
    )
    # The runtime file's PRESENCE is native-harbor evidence; its absence is what this
    # check wants to judge, so absence casts no vote.
    sig["verifier_runtime"] = (
        "native-harbor"
        if (task_dir / "tests" / "verifier_runtime.py").is_file()
        else "absent"
    )
    sig = {k: v for k, v in sig.items() if v is not None}
    votes = [g for g in sig.values() if g in ("native-harbor", "rewardkit-hybrid")]
    n_native, n_hybrid = votes.count("native-harbor"), votes.count("rewardkit-hybrid")
    if n_native > n_hybrid:
        genre = "native-harbor"
    elif n_hybrid > n_native:
        genre = "rewardkit-hybrid"
    else:
        genre = "unknown"
    mixed = len(set(votes)) > 1 or "conflict" in sig.values()
    instr_conv = []
    if "/app/" in instr:
        instr_conv.append("/app/")
    if "/workspace/output" in instr:
        instr_conv.append("/workspace/output/")
    elif "output/" in instr:
        instr_conv.append("output/")
    return {
        "genre": genre,
        "signals": sig,
        "mixed": mixed,
        "instruction_conventions": instr_conv,
    }


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--all":
        root = Path(sys.argv[2])
        tasks = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("task_"))
        if not tasks:
            print(f"ERROR: no task_* directories found under {root}", file=sys.stderr)
            return 2
        counts = {"native-harbor": 0, "rewardkit-hybrid": 0, "unknown": 0}
        for t in tasks:
            r = detect_genre(t)
            counts[r["genre"]] = counts.get(r["genre"], 0) + 1
            flag = "  [MIXED SIGNALS -- inspect manually]" if r["mixed"] else ""
            print(f"{t.name:20s} {r['genre']:18s}{flag}")
        print()
        print(f"{len(tasks)} tasks: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
        if counts.get("unknown", 0):
            print("WARNING: 'unknown' tasks need manual inspection before converting -- "
                  "do not guess which converter to run.", file=sys.stderr)
        return 0
    if len(sys.argv) == 2:
        task_dir = Path(sys.argv[1])
        if not task_dir.is_dir():
            print(f"ERROR: not a directory: {task_dir}", file=sys.stderr)
            return 2
        print(json.dumps(detect_genre(task_dir), indent=2))
        return 0
    print(f"Usage: {sys.argv[0]} <task_dir>\n       {sys.argv[0]} --all <root_dir>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
