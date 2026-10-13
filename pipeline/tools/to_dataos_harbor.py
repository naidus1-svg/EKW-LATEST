#!/usr/bin/env python3
"""to_dataos_harbor.py — convert an internal-harbor task into dataos-harbor
shape, WITHOUT going through to_rewardkit.py's reward-kit conversion.

Naming (2026-09-08, settled): "internal-harbor" is the verifier.json +
verifier_lib runtime shipped verbatim from pipeline/templates/harbor/ (test.sh
+ verifier_runtime.py + verifier_lib/) — used as-is for the Harbor-beta
eval-request path (harbor_evals.py), which never touches Data-OS's own upload
validator. "dataos-harbor" is either (a) the full reward-kit conversion
to_rewardkit.py already produces, or (b) this lighter conversion: same
verifier.json + verifier_lib runtime, just patched so Data-OS's own
rewardkit.discover() (which it runs against every uploaded task's tests/ at
upload time, in its own bare Python environment, independent of the task's
container -- confirmed 2026-09-08 by installing harbor-rewardkit locally and
calling discover() directly) doesn't choke on it.

Root cause, revised after two rounds of real-platform testing (2026-09-08):
discover() ALWAYS imports any root-level tests/*.py file (regardless of what
sibling directories are named -- that part of the original diagnosis was
wrong; the __verifier_lib rename below doesn't by itself stop anything from
being imported). verifier_runtime.py IS that root-level file, and it imports
the whole verifier_lib package. Round 1 fix (lazy-import jsonpath_ng/tenacity)
made that import chain SUCCEED instead of raising ModuleNotFoundError -- but
succeeding is not nothing: Python writes a real __pycache__/*.pyc for every
module in the chain as a side effect of the import, which is exactly what a
real upload then flagged right back as "files that may not be relevant"
(discover() alone, called locally against a clean copy, reproduces the exact
same __pycache__ tree with zero other action taken). And discover() still
reports 0 native reward-kit criteria either way (we don't use rewardkit's own
@criterion API), which Data-OS's own upload validator treats as "Unable to
parse tests under tests/" regardless of whether the import underneath it
raised or succeeded.

Three fixes now, all applied to pipeline/templates/dataos_harbor/ (a
maintained sibling of pipeline/templates/harbor/ -- internal-harbor's own
template is deliberately left untouched, since the Harbor-beta eval-request
path never runs discover() against it):
  1. jsonpath_ng/tenacity imports moved from module level into the one
     function each that actually uses them (mirrors this codebase's existing
     convention of lazily importing python-docx/openpyxl/etc. inside
     verifier_lib/sources/*.py function bodies).
  2. tests/verifier_lib/ renamed to tests/__verifier_lib/ -- rewardkit's own
     _subdirs() helper skips directories starting with "." or "__" when
     deciding what counts as a criteria-dimension GROUP. Doesn't by itself
     stop verifier_runtime.py's own import of the package (see above), but
     kept anyway since it's harmless and documents intent.
  3. verifier_runtime.py renamed to verifier_runtime.pyrun (test.sh's
     invocation updated to match) -- THIS is what actually stops discover()
     from importing anything at all: with no *.py file left directly under
     tests/ and __verifier_lib/ excluded from _subdirs(), discover()'s
     nothing-to-scan path returns 0 groups without ever calling import,
     confirmed locally to leave zero __pycache__ behind. python3 runs a
     script fine regardless of its extension, so grading is unaffected.

Usage
-----
    python to_dataos_harbor.py <internal_harbor_task_dir> <out_task_dir>

Copies the whole internal-harbor task tree to <out_task_dir>, then replaces
tests/{test.sh,verifier_runtime.py,verifier_lib/} with the patched
tests/{test.sh,verifier_runtime.pyrun,__verifier_lib/} from
pipeline/templates/dataos_harbor/ -- everything else (instruction.md,
task.toml, environment/, solution/, tests/verifier.json) is untouched. Also
strips .DS_Store / __pycache__ / *.pyc on the way in, though those shouldn't
reappear post-fix-3 even if Data-OS's own validator imports things locally.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

DATAOS_HARBOR_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "dataos_harbor"

_JUNK_DIR_NAMES = {"__pycache__"}
_JUNK_FILE_NAMES = {".DS_Store"}
_JUNK_FILE_SUFFIXES = (".pyc",)


def _is_junk_dir(path: Path) -> bool:
    return path.name in _JUNK_DIR_NAMES


def _copytree_clean(src: Path, dst: Path) -> None:
    """Copies src -> dst, skipping .DS_Store / __pycache__ / *.pyc."""
    def _ignore(dir_: str, names: list[str]) -> set[str]:
        return {
            n for n in names
            if n in _JUNK_DIR_NAMES
            or n in _JUNK_FILE_NAMES
            or n.endswith(_JUNK_FILE_SUFFIXES)
        }
    shutil.copytree(src, dst, ignore=_ignore)


def convert(src_dir: Path, out_dir: Path) -> Path:
    """Writes one dataos-harbor task folder at out_dir from an internal-harbor src_dir."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    _copytree_clean(src_dir, out_dir)

    tests = out_dir / "tests"
    old_lib = tests / "verifier_lib"
    if old_lib.exists():
        shutil.rmtree(old_lib)
    old_runtime = tests / "verifier_runtime.py"
    if old_runtime.exists():
        old_runtime.unlink()

    shutil.copy2(DATAOS_HARBOR_TEMPLATE / "test.sh", tests / "test.sh")
    shutil.copy2(DATAOS_HARBOR_TEMPLATE / "verifier_runtime.pyrun", tests / "verifier_runtime.pyrun")
    shutil.copy2(DATAOS_HARBOR_TEMPLATE / "dataos_discovery_probe.py", tests / "dataos_discovery_probe.py")
    shutil.copytree(DATAOS_HARBOR_TEMPLATE / "__verifier_lib", tests / "__verifier_lib")
    (tests / "test.sh").chmod(0o755)
    (tests / "verifier_runtime.pyrun").chmod(0o755)

    print(f"Converted {src_dir} -> {out_dir} (internal-harbor -> dataos-harbor)")
    return out_dir


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <internal_harbor_task_dir> <out_task_dir>", file=sys.stderr)
        return 2
    src_dir = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    if not src_dir.is_dir():
        print(f"ERROR: not a directory: {src_dir}", file=sys.stderr)
        return 2
    if not (src_dir / "tests" / "verifier.json").is_file():
        print(f"ERROR: {src_dir} doesn't look like an internal-harbor task "
              f"(missing tests/verifier.json)", file=sys.stderr)
        return 2
    convert(src_dir, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
