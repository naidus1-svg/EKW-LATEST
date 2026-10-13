#!/usr/bin/env python3
"""container_build_check -- can DataOS actually BUILD this task's sandbox?

WHY THIS EXISTS. On 2026-09-21 a 26-task delivery errored at DataOS: no Dockerfile. All 37 converted
packages were missing `environment/Dockerfile` and `environment/verifier-requirements.txt`, because
the 310-drop conversion chain never wrote them. Every existing gate passed on those packages --
both reward gates, the review matrix, the zero-major bar, unreviewed bytes, build artefacts, solver
inputs. All seven grade the RUBRIC. None asked whether the container could be built, so a task could
be certified shippable and still be unusable.

Checks, per task:
  1. environment/Dockerfile exists (both genres)
  2. every path the Dockerfile COPYs from the build context exists -- a COPY of a missing path
     fails the build (both genres)

  native-harbor genre only (tests/__verifier_lib/ present -- the offline, pre-warmed-venv design):
  3. environment/verifier-requirements.txt exists
  4. verifier-requirements.txt matches tests/__verifier_lib/requirements.txt exactly
     (the image pre-warms a venv from it; drift means the grader runs different versions than
     the task ships)
  5. the Dockerfile still carries the two grading-relevant pieces: `libreoffice` (supplies the
     `soffice` binary xlsx.py looks for to recalculate uncached formula cells -- without it those
     cells extract BLANK and the judge grades an empty string) and `VERIFIER_VENV_DIR`

  Genre note (added 2026-09-21, task_462): rewardkit-hybrid tasks (tests/deliverables_*/judge.toml,
  no tests/__verifier_lib/) use a DIFFERENT, independently-verified-working build pattern -- test.sh
  `pip install`s `harbor-rewardkit` live at grade time (task.toml sets `allow_internet = true` for
  exactly this), and the rewardkit judge prompt is explicitly designed to tolerate uncached/blank
  formula cells via prompt language rather than a libreoffice recalculation step. Confirmed on
  task_462: 7 real DataOS evaluations completed successfully end-to-end (reward.json written, judge
  calls executed) against the current Dockerfile with NONE of native-harbor's three pieces -- so
  requiring them here would be a false positive for this genre, not a build risk. Checks 3-5 apply
  to native-harbor only; rewardkit-hybrid gets checks 1-2 plus a Dockerfile sanity check for a
  `pip install ... harbor-rewardkit` (or equivalent) line, since THAT is this genre's actual
  grading-relevant dependency.

    container_build_check.py --root <packages dir> [--task ID ...]

Exit 1 if any task fails.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

COPY_RE = re.compile(r"^\s*COPY\s+(?!--from=)(\S+)\s+\S+", re.IGNORECASE)


# Both real spellings of the vendored verifier library in this corpus. 28 of the 79 shipped v7
# tasks (every LGL task, plus task_78/79/81/86/97/98) ship the SINGLE-underscore
# `tests/verifier_lib/`; the rest ship `tests/__verifier_lib/`. Recognising only the
# double-underscore spelling made genre() return "unknown" for 35% of the corpus, which skipped
# every native-genre build check below and printed `pass` on packages that could not build at
# all -- confirmed 2026-09-22 on task_LGL-168, which shipped with drifted requirements, failed
# with "verifier dependency install failed", scored reward 0.0, and still passed this gate.
VERIFIER_LIB_DIRS = ("__verifier_lib", "verifier_lib")


def verifier_lib_dir(pkg: Path) -> Path | None:
    """The package's vendored verifier library, whichever spelling it uses, or None."""
    for name in VERIFIER_LIB_DIRS:
        d = pkg / "tests" / name
        if d.is_dir():
            return d
    return None


def genre(pkg: Path) -> str:
    if verifier_lib_dir(pkg) is not None:
        return "native"
    if list((pkg / "tests").glob("deliverables_*/judge.toml")):
        return "rewardkit"
    return "unknown"


def check(pkg: Path) -> list[str]:
    fails: list[str] = []
    env = pkg / "environment"
    dockerfile = env / "Dockerfile"
    reqs = env / "verifier-requirements.txt"
    g = genre(pkg)

    if not dockerfile.is_file():
        fails.append("environment/Dockerfile missing -- DataOS cannot build the sandbox")

    if g == "native":
        if not reqs.is_file():
            fails.append("environment/verifier-requirements.txt missing -- the Dockerfile COPYs it")
        lib = verifier_lib_dir(pkg)
        vendored = (lib / "requirements.txt") if lib is not None else None
        if reqs.is_file() and vendored is not None and vendored.is_file():
            if reqs.read_text().strip() != vendored.read_text().strip():
                rel = vendored.relative_to(pkg)
                fails.append(f"verifier-requirements.txt != {rel} "
                             "(pre-warmed venv would not match the vendored library; the "
                             "requirements-sha marker never matches, the venv is discarded, and "
                             "grading falls back to a PyPI install that fails offline -> reward 0.0)")

    if dockerfile.is_file():
        text = dockerfile.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            m = COPY_RE.match(line)
            if m and not (env / m.group(1).rstrip("/")).exists():
                fails.append(f"Dockerfile COPYs environment/{m.group(1)} which does not exist")
        if g == "native":
            if "libreoffice" not in text:
                fails.append("Dockerfile does not install libreoffice -- xlsx.py cannot recalculate "
                             "uncached formulas, so those cells extract blank to the judge")
            if "VERIFIER_VENV_DIR" not in text:
                fails.append("Dockerfile does not set VERIFIER_VENV_DIR -- grading runs offline against "
                             "the pre-warmed venv")
        elif g == "rewardkit":
            test_sh = pkg / "tests" / "test.sh"
            test_sh_text = test_sh.read_text(encoding="utf-8", errors="replace") if test_sh.is_file() else ""
            if "harbor-rewardkit" not in test_sh_text and "harbor-rewardkit" not in text:
                fails.append("rewardkit genre: neither the Dockerfile nor tests/test.sh installs "
                             "harbor-rewardkit -- grading has no verifier toolchain")

    # "I could not tell what this package is" must never render as success. Before 2026-09-22 an
    # unrecognised genre silently skipped every genre-specific assertion above and still printed
    # `pass` -- which is exactly how task_LGL-168 shipped with drifted requirements, failed its
    # dependency install and scored reward 0.0 on every run while this gate reported it clean.
    if g == "unknown":
        fails.append("cannot determine build genre -- no vendored verifier lib "
                     "(tests/__verifier_lib/ or tests/verifier_lib/) and no "
                     "tests/deliverables_*/judge.toml. Every genre-specific build assertion was "
                     "skipped, so this package is UNVERIFIED, not clean")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--task", action="append", dest="task_ids")
    args = ap.parse_args()

    pkgs = sorted(d for d in args.root.glob("task_*") if d.is_dir())
    if args.task_ids:
        pkgs = [d for d in pkgs if d.name in set(args.task_ids)]
    if not pkgs:
        print(f"no task_* packages under {args.root}", file=sys.stderr)
        return 1

    bad = 0
    for d in pkgs:
        fails = check(d)
        if fails:
            bad += 1
        print(f"{d.name:14} {'fail' if fails else 'pass':5} fail={fails}")
    print(f"\n{len(pkgs) - bad}/{len(pkgs)} buildable")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
