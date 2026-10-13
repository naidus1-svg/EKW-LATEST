#!/usr/bin/env python3
"""Fail if a relative link in the front-door docs points to a file that is not in the repo.

Stdlib only. Run from anywhere:

    python docs/check_links.py              # README.md, docs/README.md, docs/autofix-agent-quickstart.md
    python docs/check_links.py --all        # every tracked .md file (reports, does not change the exit code)
    python docs/check_links.py path/to/a.md # specific files

What it checks
  1. Every relative link [text](target) and <a href="target"> resolves to a file or folder that git tracks
     (so a file that only exists on your disk does not count).
  2. A "#anchor" on a link to a Markdown file matches a heading in that file (GitHub's slug rules).
  3. The "Last checked: YYYY-MM-DD against main at <sha>" stamp exists in README.md and docs/README.md.
     It only warns when main has moved since that sha; refresh the stamp when you re-read the docs.

Exit code 0 means clean, 1 means a broken link or a missing stamp in the front-door files.
http(s) and mailto links are not fetched.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
FRONT_DOOR = ["README.md", "docs/README.md", "docs/autofix-agent-quickstart.md"]
STAMP_FILES = ["README.md", "docs/README.md"]
STAMP_RE = re.compile(
    r"Last checked:\s*(\d{4}-\d{2}-\d{2})\s+against main at\s+`?([0-9a-f]{7,40})`?"
)
LINK_RE = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HREF_RE = re.compile(r"""href=["']([^"']+)["']""")
FENCE_RE = re.compile(r"^(```|~~~)")


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def tracked_files() -> set[str]:
    listed = git("ls-files").splitlines()
    if listed:
        return set(listed)
    return {
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }


def slug(heading: str) -> str:
    text = re.sub(r"[`*_~]", "", heading.strip().lower())
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors_in(path: Path) -> set[str]:
    found: set[str] = set()
    counts: dict[str, int] = {}
    in_fence = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            s = slug(m.group(1))
            n = counts.get(s, 0)
            counts[s] = n + 1
            found.add(s if n == 0 else f"{s}-{n}")
    return found


def links_in(path: Path):
    in_fence = False
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        if FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = re.sub(r"`[^`]*`", "", line)  # inline code is not a link
        for m in LINK_RE.finditer(line):
            yield lineno, m.group(1)
        for m in HREF_RE.finditer(line):
            yield lineno, m.group(1)


def check_file(rel: str, tracked: set[str]) -> list[str]:
    path = ROOT / rel
    problems = []
    for lineno, target in links_in(path):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("//"):
            continue  # http, https, mailto: not fetched
        file_part, _, anchor = target.partition("#")
        file_part = unquote(file_part)
        if not file_part:
            if (
                anchor
                and slug(unquote(anchor)) not in anchors_in(path)
                and unquote(anchor) not in anchors_in(path)
            ):
                problems.append(
                    f"{rel}:{lineno}: anchor #{anchor} not found in this file"
                )
            continue
        base = (path.parent / file_part).resolve()
        try:
            resolved = base.relative_to(ROOT).as_posix()
        except ValueError:
            problems.append(f"{rel}:{lineno}: {target} points outside the repo")
            continue
        is_dir = resolved in ("", ".") or any(
            t.startswith(resolved.rstrip("/") + "/") for t in tracked
        )
        if resolved not in tracked and not is_dir:
            problems.append(
                f"{rel}:{lineno}: {target} -> {resolved} is not a tracked file"
            )
            continue
        if anchor and resolved.endswith(".md") and resolved in tracked:
            wanted = unquote(anchor).lower()
            if wanted not in anchors_in(ROOT / resolved):
                problems.append(
                    f"{rel}:{lineno}: {target} -> no heading '#{anchor}' in {resolved}"
                )
    return problems


def check_stamps() -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    for rel in STAMP_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        m = STAMP_RE.search(text)
        if not m:
            errors.append(
                f"{rel}: missing the line 'Last checked: YYYY-MM-DD against main at <sha>'"
            )
            continue
        sha = m.group(2)
        if not git("cat-file", "-t", sha).strip():
            warnings.append(
                f"{rel}: stamp sha {sha} is not in this clone (fetch, then re-check)"
            )
            continue
        behind = git("rev-list", "--count", f"{sha}..origin/main").strip()
        if behind and behind != "0":
            warnings.append(
                f"{rel}: main is {behind} commit(s) past the stamp {sha}; re-read the docs, then refresh the stamp"
            )
    return errors, warnings


def main() -> int:
    args = sys.argv[1:]
    tracked = tracked_files()
    scan_all = "--all" in args
    files = [a for a in args if not a.startswith("--")]
    if scan_all:
        files = sorted(f for f in tracked if f.endswith(".md"))
    elif not files:
        files = FRONT_DOOR
    # a file that does not exist yet is itself a failure for the front-door set
    missing = [f for f in files if not (ROOT / f).is_file()]
    problems = [f"{f}: file not found" for f in missing]
    checked = 0
    for rel in files:
        if rel in missing:
            continue
        problems += check_file(rel, tracked)
        checked += 1
    errors, warnings = ([], [])
    if not scan_all and not args:
        errors, warnings = check_stamps()
    print(f"checked {checked} file(s)")
    for line in problems + errors:
        print("BROKEN  " + line)
    for line in warnings:
        print("WARN    " + line)
    if scan_all:
        print(
            f"{len(problems)} broken link(s) across all tracked .md files (informational)"
        )
        return 0
    if problems or errors:
        print(f"FAIL: {len(problems) + len(errors)} problem(s)")
        return 1
    print("OK: every relative link resolves to a tracked file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
