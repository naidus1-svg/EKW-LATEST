#!/usr/bin/env python3
"""Give a rewardkit package three judge samples per chunk (mean of 3).

rewardkit's ``[judge]`` table has no sampling key, so one judge call decides every criterion and a
verdict can flip on identical bytes. rewardkit does, however, load EVERY ``*.toml`` in a chunk
directory that has ``[judge]`` + ``[[criterion]]`` as its own reward, named by the file stem, and
averages the rewards of a directory by weight. So for each ``tests/deliverables_NN/judge.toml``:

  * ``judge_s2.toml`` and ``judge_s3.toml`` are written as byte copies of ``judge.toml``
    (always regenerated -- ``judge.toml`` stays the only file anyone edits);
  * if the chunk's ``reward.toml`` names ``judge`` in its weights, that weight is split three ways
    (``judge``, ``judge_s2``, ``judge_s3`` = w/3 each) so ``$checks`` keeps its share. Without such
    an override the three files carry the same ``[judge].weight`` and average equally.

Owner ruling 2026-09-18 (mean of 3, 3x judge cost). Idempotent. ``--check`` exits 1 if a package
is not in this form; ``--undo`` removes the sample files and restores the weight.

Usage: rewardkit_mean_of_3.py <package_dir> [--check | --undo]
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

SAMPLES = ("judge_s2", "judge_s3")
MARK = "# mean-of-3: judge weight split across judge / judge_s2 / judge_s3 (was {w})"
MARK_RE = re.compile(r"^# mean-of-3: .*\(was ([0-9.]+)\)\n", re.M)
# `judge = 0.64` inside an inline `weights = {...}` table or under a `[...weights]` header
JUDGE_W_RE = re.compile(r"(?<![\w\"$])judge\s*=\s*([0-9]*\.?[0-9]+)")


def chunk_dirs(package: Path) -> list[Path]:
    return sorted(p.parent for p in (package / "tests").glob("deliverables_*/judge.toml"))


def _weights_of(reward_toml: Path) -> dict:
    data = tomllib.loads(reward_toml.read_text(encoding="utf-8"))
    specs = data.get("reward", [])
    spec = specs[0] if isinstance(specs, list) and specs else (specs if isinstance(specs, dict) else {})
    return dict(spec.get("weights", {}))


def _split_weight(reward_toml: Path) -> bool:
    text = reward_toml.read_text(encoding="utf-8")
    weights = _weights_of(reward_toml)
    if "judge" not in weights or all(s in weights for s in SAMPLES):
        return False
    w = float(weights["judge"])
    third = round(w / 3, 6)
    m = next((x for x in JUDGE_W_RE.finditer(text) if not text[text.rfind("\n", 0, x.start()) + 1 : x.start()].lstrip().startswith("#")), None)
    if not m:
        raise SystemExit(f"{reward_toml}: weights name 'judge' but the entry could not be located to split")
    inline = "{" in text[text.rfind("\n", 0, m.start()) + 1 : m.start()]
    sep = ", " if inline else "\n"
    entry = sep.join(f"{name} = {third}" for name in ("judge", *SAMPLES))
    text = text[: m.start()] + entry + text[m.end() :]
    reward_toml.write_text(MARK.format(w=w) + "\n" + text, encoding="utf-8")
    return True


def apply(package: Path) -> list[str]:
    done = []
    for d in chunk_dirs(package):
        src = (d / "judge.toml").read_bytes()
        for s in SAMPLES:
            (d / f"{s}.toml").write_bytes(src)
        split = (d / "reward.toml").is_file() and _split_weight(d / "reward.toml")
        done.append(f"{d.name}: 3 samples" + (" + weight split" if split else ""))
    return done


def undo(package: Path) -> list[str]:
    done = []
    for d in chunk_dirs(package):
        for s in SAMPLES:
            (d / f"{s}.toml").unlink(missing_ok=True)
        rt = d / "reward.toml"
        if rt.is_file() and (m := MARK_RE.search(text := rt.read_text(encoding="utf-8"))):
            text = MARK_RE.sub("", text, count=1)
            text = re.sub(r"(?<![\w\"$])judge\s*=\s*[0-9.]+(,\s*|\n)judge_s2\s*=\s*[0-9.]+(,\s*|\n)judge_s3\s*=\s*[0-9.]+", f"judge = {m.group(1)}", text, count=1)
            rt.write_text(text, encoding="utf-8")
        done.append(f"{d.name}: restored")
    return done


def check(package: Path) -> list[str]:
    problems = []
    for d in chunk_dirs(package):
        src = (d / "judge.toml").read_bytes()
        for s in SAMPLES:
            f = d / f"{s}.toml"
            if not f.is_file():
                problems.append(f"{d.name}: {f.name} missing")
            elif f.read_bytes() != src:
                problems.append(f"{d.name}: {f.name} differs from judge.toml (re-run this tool after editing judge.toml)")
        rt = d / "reward.toml"
        if rt.is_file():
            w = _weights_of(rt)
            if "judge" in w and not (all(s in w for s in SAMPLES) and len({round(float(w[k]), 6) for k in ("judge", *SAMPLES)}) == 1):
                problems.append(f"{d.name}: reward.toml weights do not give judge / judge_s2 / judge_s3 equal shares")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--undo", action="store_true")
    args = ap.parse_args(argv)
    if not chunk_dirs(args.package):
        print("not a rewardkit package (no tests/deliverables_*/judge.toml)")
        return 1
    if args.check:
        problems = check(args.package)
        print("\n".join(problems) or "mean-of-3: ok")
        return 1 if problems else 0
    print("\n".join(undo(args.package) if args.undo else apply(args.package)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
