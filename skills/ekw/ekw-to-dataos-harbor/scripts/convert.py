#!/usr/bin/env python3
"""convert.py -- one entry point for converting an EKW harbor task into a
DataOS-uploadable package. Detects the task's build genre (detect_genre.py) and
dispatches to the correct converter:
  - native-harbor    -> to_dataos_harbor.py (patches tests/ so DataOS's own
                        rewardkit.discover() upload validator doesn't choke on it)
  - rewardkit-hybrid -> to_rewardkit.py (produces a fully self-contained
                        reward-kit-native package: environment/initial_workspace/,
                        solution/files/, tests/deliverables_NN/judge.toml,
                        tests/reward.toml, tests/test.sh)

Never guesses: a task whose genre comes back "unknown" (signals tied or absent)
or "mixed" (conflicting signals) is skipped with a clear error instead of being
forced through either converter -- running the wrong converter on a task produces
a package that looks structurally fine locally but fails at DataOS sandbox-creation
time with an error like:
    DaytonaError: Failed to create sandbox: Path does not exist:
    .../environment/initial_workspace/
(exactly what happens if a rewardkit-hybrid task gets converted with
to_dataos_harbor.py instead of to_rewardkit.py -- its Dockerfile does
`COPY initial_workspace/ /app/`, but that directory is only ever produced by
to_rewardkit.py, never by to_dataos_harbor.py or present in the raw task dir.)

Usage:
    python convert.py <task_dir> <out_dir> [--prefix ekw] [--max-criteria-per-judge 12]
    python convert.py --all <root_dir> --out-dir <out_root> [--prefix ekw] [--max-criteria-per-judge 12]

--all mode converts every task_* directory under <root_dir>, writing each
converted task to <out_root>/<task_id>/, and prints a summary table at the end
(converted / skipped-unknown / skipped-mixed / failed counts) -- nothing is
silently dropped.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect_genre as _detect_genre_mod
import to_dataos_harbor as _native_converter
import to_rewardkit as _hybrid_converter


def convert_one(task_dir: Path, out_dir: Path, prefix: str, max_criteria_per_judge: int) -> dict:
    """Detects genre and converts task_dir -> out_dir. Returns a result dict;
    never raises for a genre it can't safely handle (unknown/mixed) -- those
    come back as status="skipped" with the reason, not an exception."""
    genre_info = _detect_genre_mod.detect_genre(task_dir)
    genre = genre_info["genre"]

    if genre == "unknown":
        return {"task": task_dir.name, "genre": genre, "status": "skipped",
                "reason": "genre signals absent or tied -- cannot safely pick a converter",
                "signals": genre_info["signals"]}
    if genre_info["mixed"]:
        return {"task": task_dir.name, "genre": genre, "status": "skipped",
                "reason": "conflicting genre signals across files -- inspect manually before converting",
                "signals": genre_info["signals"]}

    try:
        if genre == "native-harbor":
            _native_converter.convert(task_dir, out_dir)
        elif genre == "rewardkit-hybrid":
            _hybrid_converter.convert(str(task_dir), str(out_dir), prefix, max_criteria_per_judge)
        else:
            return {"task": task_dir.name, "genre": genre, "status": "skipped",
                     "reason": f"unhandled genre value: {genre!r}"}
    except Exception as e:  # noqa: BLE001 -- surface any converter failure per-task, don't abort a batch
        return {"task": task_dir.name, "genre": genre, "status": "failed", "reason": str(e)}

    return {"task": task_dir.name, "genre": genre, "status": "converted", "out_dir": str(out_dir)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task_dir_or_all", metavar="task_dir", nargs="?")
    ap.add_argument("out_dir_or_root_flag", metavar="out_dir", nargs="?")
    ap.add_argument("--all", dest="all_root", metavar="ROOT_DIR",
                     help="convert every task_* dir under ROOT_DIR instead of a single task")
    ap.add_argument("--out-dir", dest="out_root", metavar="OUT_ROOT",
                     help="required with --all: converted tasks land at OUT_ROOT/<task_id>/")
    ap.add_argument("--prefix", default="ekw", help="rewardkit task-name prefix (default: ekw)")
    ap.add_argument("--max-criteria-per-judge", type=int, default=12,
                     help="rewardkit-hybrid only: split a task's judge across this many criteria per judge.toml chunk (default: 12)")
    args = ap.parse_args()

    if args.all_root:
        if not args.out_root:
            print("ERROR: --all requires --out-dir", file=sys.stderr)
            return 2
        root = Path(args.all_root)
        out_root = Path(args.out_root)
        tasks = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("task_"))
        if not tasks:
            print(f"ERROR: no task_* directories found under {root}", file=sys.stderr)
            return 2
        results = [convert_one(t, out_root / t.name, args.prefix, args.max_criteria_per_judge) for t in tasks]
        for r in results:
            if r["status"] == "converted":
                print(f"{r['task']:20s} {r['genre']:18s} -> converted -> {r['out_dir']}")
            else:
                print(f"{r['task']:20s} {r['genre']:18s} -> {r['status']}: {r['reason']}")
        counts = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        print()
        print(f"{len(results)} tasks: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
        return 0 if counts.get("failed", 0) == 0 and counts.get("skipped", 0) == 0 else 1

    # single-task mode
    if not args.task_dir_or_all or not args.out_dir_or_root_flag:
        print("Usage: convert.py <task_dir> <out_dir> [--prefix ekw] [--max-criteria-per-judge 12]\n"
              "       convert.py --all <root_dir> --out-dir <out_root> [--prefix ekw]", file=sys.stderr)
        return 2
    task_dir = Path(args.task_dir_or_all)
    out_dir = Path(args.out_dir_or_root_flag)
    if not task_dir.is_dir():
        print(f"ERROR: not a directory: {task_dir}", file=sys.stderr)
        return 2
    r = convert_one(task_dir, out_dir, args.prefix, args.max_criteria_per_judge)
    if r["status"] == "converted":
        print(f"OK: {r['task']} ({r['genre']}) -> {r['out_dir']}")
        return 0
    print(f"NOT CONVERTED: {r['task']} ({r['genre']}) -- {r['status']}: {r['reason']}", file=sys.stderr)
    if "signals" in r:
        print(f"signals: {r['signals']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
