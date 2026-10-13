#!/usr/bin/env python3
"""Check a Harbor batch against the operator guide before a byte reaches GCS.

`harbor-evals-quick-guide.md` (Luiz, 2026-09-01) ends its format section with
"if the task does not match this format, stop and ask an engineer". Everything
below is that checklist, made executable, because the guide's own upload step is
irreversible in practice: once tasks are copied and the ready markers written, the
enqueue cron can pick them up, and a format error found at that point means
re-uploading the whole batch.

The specific risk this exists for: SVC-PC packages built by our own pipeline write
deliverables to `/app/`, while Harbor requires `/workspace/output/`. A conversion
that carried the old path forward would produce a batch that uploads cleanly and
then fails every task.

Two checks go beyond the guide, both earned:

  judge consistency  Each task carries its own judge in tests/verifier.json. Ours
                     say openai/gpt-5.4 while Data-OS uses anthropic/claude-sonnet-4-6.
                     A batch with mixed judges yields a leaderboard whose rows were
                     graded by different models, which is worse than no leaderboard.
  id set, not count  Run #2152 was miscounted because a total matched while the
                     contents differed. Pass --expect-ids to compare the actual set.

    python tools/svc_harbor_preflight.py <ready-batch-root> [--expect-ids FILE]

Exit 0 only when every task passes. Anything else means do not upload.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

MAX_STORAGE_MB = 10240
REQUIRED_OUTPUT = "/workspace/output"
FORBIDDEN_DIRS = {"solution", "outputs", "node_modules", "__pycache__"}
FORBIDDEN_FILES = {".DS_Store", "Thumbs.db", ".harbor_package_ready"}
TEXT_SUFFIXES = {".md", ".toml", ".txt", ".json", ".sh", ".py", ".yaml", ".yml"}


def harbor_dir(task_root: Path) -> Path | None:
    """Locate <task>/v1/harbor_task, the layout the guide specifies."""
    candidate = task_root / "v1" / "harbor_task"
    if candidate.is_dir():
        return candidate
    hits = list(task_root.rglob("harbor_task"))
    return hits[0] if len(hits) == 1 and hits[0].is_dir() else None


def check_task(task_root: Path) -> tuple[list[str], str | None]:
    """Return this task's failures, and the judge it names."""
    fails: list[str] = []
    hd = harbor_dir(task_root)
    if hd is None:
        return ([f"no v1/harbor_task directory under {task_root.name}"], None)

    instruction = hd / "instruction.md"
    task_toml = hd / "task.toml"
    for required in (instruction, task_toml, hd / "environment", hd / "tests"):
        if not required.exists():
            fails.append(f"missing {required.relative_to(hd)}")

    # The output-path trap. Both the instruction and task.toml must agree.
    if instruction.is_file():
        text = instruction.read_text(encoding="utf-8", errors="replace")
        if REQUIRED_OUTPUT not in text:
            fails.append(f"instruction.md does not name {REQUIRED_OUTPUT}")
        if "/app/" in text:
            fails.append("instruction.md still references /app/, the Data-OS path")

    if task_toml.is_file():
        try:
            cfg = tomllib.loads(task_toml.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            cfg = {}
            fails.append(f"task.toml does not parse: {str(exc)[:60]}")
        artifacts = cfg.get("artifacts") or []
        if REQUIRED_OUTPUT not in [str(a).rstrip("/") for a in artifacts]:
            fails.append(f'task.toml artifacts does not contain "{REQUIRED_OUTPUT}"')
        storage = cfg.get("storage_mb")
        if isinstance(storage, (int, float)) and storage > MAX_STORAGE_MB:
            fails.append(f"storage_mb {storage} exceeds {MAX_STORAGE_MB}")

    data_dir = hd / "environment" / "data"
    if not data_dir.is_dir():
        fails.append("environment/data missing")
    else:
        real = [p for p in data_dir.rglob("*") if p.is_file() and p.stat().st_size > 0]
        if not real:
            fails.append("environment/data holds no real files")

    tests = hd / "tests"
    if tests.is_dir() and not (tests / "test.sh").is_file():
        fails.append("tests/test.sh missing")

    # Anything that must not ship.
    for p in hd.rglob("*"):
        if p.is_dir() and p.name in FORBIDDEN_DIRS:
            fails.append(f"forbidden directory present: {p.relative_to(hd)}")
        elif p.is_file() and p.name in FORBIDDEN_FILES:
            fails.append(f"forbidden file present: {p.relative_to(hd)}")

    # UTF-8 and no NUL bytes in text files.
    for p in hd.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        blob = p.read_bytes()
        if b"\x00" in blob:
            fails.append(f"NUL byte in {p.relative_to(hd)}")
        try:
            blob.decode("utf-8")
        except UnicodeDecodeError:
            fails.append(f"not valid UTF-8: {p.relative_to(hd)}")

    judge = None
    vj = tests / "verifier.json"
    if vj.is_file():
        try:
            data = json.loads(vj.read_text(encoding="utf-8"))
            models = (data.get("config") or {}).get("models")
            if isinstance(models, list) and models:
                judge = str(models[0])
            elif isinstance(models, str):
                judge = models
        except Exception as exc:  # noqa: BLE001
            fails.append(f"verifier.json does not parse: {str(exc)[:60]}")

    return fails, judge


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="the ready-batch directory, one folder per task")
    ap.add_argument("--expect-ids", help="file of expected task ids, one per line")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"BLOCKED: {root} is not a directory")
        return 2

    tasks = sorted(
        p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")
    )
    if not tasks:
        print(f"BLOCKED: no task directories under {root}")
        return 2

    print(f"{len(tasks)} task folder(s) under {root}\n")
    bad, judges = 0, {}
    for t in tasks:
        fails, judge = check_task(t)
        judges.setdefault(judge, []).append(t.name)
        if fails:
            bad += 1
            print(f"FAIL  {t.name}")
            for f in fails:
                print(f"        {f}")
        else:
            print(f"ok    {t.name}    judge={judge}")

    print("\n" + "=" * 72)
    print(f"{len(tasks) - bad} of {len(tasks)} tasks pass the format checklist")

    if len(judges) > 1:
        print("\nMIXED JUDGES. Scores across this batch would not be comparable:")
        for j, names in judges.items():
            print(f"  {j}: {len(names)} task(s), e.g. {', '.join(names[:3])}")
        bad += 1
    elif judges:
        print(f"judge, consistent across the batch: {next(iter(judges))}")

    if args.expect_ids:
        want = {
            ln.strip()
            for ln in Path(args.expect_ids).read_text(encoding="utf-8").splitlines()
            if ln.strip()
        }
        have = {t.name for t in tasks}
        missing, extra = sorted(want - have), sorted(have - want)
        print(f"\nid set: {len(have)} present, {len(want)} expected")
        if missing:
            print(f"  MISSING : {', '.join(missing[:8])}")
            bad += 1
        if extra:
            print(f"  UNEXPECTED: {', '.join(extra[:8])}")
            bad += 1
        if not missing and not extra:
            print("  exact match, by id not by count")

    print("=" * 72)
    print("CLEARED to upload" if not bad else "BLOCKED, do not upload")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
