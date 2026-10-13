#!/usr/bin/env python3
"""Keep every copy of the verifier library identical to the canonical template.

``pipeline/templates/dataos_harbor/`` is the single source of truth. Two other trees ship
copies of it and have drifted before (2026-09-18: the copy bundled in the conversion skill was a
116-line ``xlsx.py`` with ``extract_text`` only, so converted tasks shipped without formula
commands or uncached-formula recalculation):

  * ``pipeline/templates/harbor/verifier_lib/``  -- the single-underscore genre's library. Must
    equal ``dataos_harbor/__verifier_lib/`` except ``requirements.txt`` (it additionally pins the
    optional ``formulas`` recompute engine).
  * ``skills/ekw/ekw-to-dataos-harbor/templates/dataos_harbor/`` -- the skill's self-contained
    bundle. Must equal the canonical tree file for file (library, ``test.sh``,
    ``verifier_runtime.pyrun``, ``dataos_discovery_probe.py``).

Usage:
    sync_templates.py            # --check: exit 1 and list every differing/missing/extra file
    sync_templates.py --write    # refresh the copies from the canonical tree
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CANONICAL = REPO / "pipeline" / "templates" / "dataos_harbor"

# (copy root, canonical sub-root it mirrors, files allowed to differ)
MIRRORS: list[tuple[Path, Path, frozenset[str]]] = [
    (REPO / "pipeline" / "templates" / "harbor" / "verifier_lib", CANONICAL / "__verifier_lib", frozenset({"requirements.txt"})),
    (REPO / "skills" / "ekw" / "ekw-to-dataos-harbor" / "templates" / "dataos_harbor", CANONICAL, frozenset()),
]


def _files(root: Path) -> dict[str, Path]:
    return {
        str(p.relative_to(root)): p
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc" and p.name != ".DS_Store"
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(copy_root: Path, canon_root: Path, allow: frozenset[str]) -> list[str]:
    canon, copy = _files(canon_root), _files(copy_root)
    problems: list[str] = []
    for rel, src in canon.items():
        if rel in allow:
            continue
        if rel not in copy:
            problems.append(f"missing  {copy_root.relative_to(REPO)}/{rel}")
        elif _sha(src) != _sha(copy[rel]):
            problems.append(f"differs  {copy_root.relative_to(REPO)}/{rel}")
    for rel in copy:
        if rel not in canon and rel not in allow:
            problems.append(f"extra    {copy_root.relative_to(REPO)}/{rel}")
    return problems


def write(copy_root: Path, canon_root: Path, allow: frozenset[str]) -> list[str]:
    canon, copy = _files(canon_root), _files(copy_root)
    changed: list[str] = []
    for rel, src in canon.items():
        if rel in allow:
            continue
        dst = copy_root / rel
        if not dst.is_file() or _sha(src) != _sha(dst):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            changed.append(f"updated  {dst.relative_to(REPO)}")
    for rel, path in copy.items():
        if rel not in canon and rel not in allow:
            path.unlink()
            changed.append(f"removed  {path.relative_to(REPO)}")
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="refresh the copies from the canonical tree")
    args = ap.parse_args(argv)
    out: list[str] = []
    for copy_root, canon_root, allow in MIRRORS:
        out += write(copy_root, canon_root, allow) if args.write else compare(copy_root, canon_root, allow)
    for line in out:
        print(line)
    if args.write:
        print(f"{len(out)} file(s) synced from {CANONICAL.relative_to(REPO)}")
        return 0
    print("templates in sync" if not out else f"{len(out)} template file(s) out of sync -- run: sync_templates.py --write")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
