#!/usr/bin/env python3
"""render_prompt.py - fill {{PLACEHOLDER}} tokens in a prompt template.

Used by gate_task.sh to build the three model prompts (blind CR, fix plan,
adjudication) from tools/prompts/*.md without shelling out to sed/awk on
arbitrarily large text (a CR.json or a 240k-char context file).

Usage:
    python3 render_prompt.py TEMPLATE.md --out OUT.txt \
        [--set KEY=path/to/file.txt ...] [--set-lit KEY=literal ...]

Every {{KEY}} in the template must have a --set or --set-lit; a template
placeholder with no value supplied is left as an error, not silently kept
verbatim (a leftover {{TASK_ID}} in an actual prompt sent to the model is a
bug, not something to ship).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("template", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=FILE")
    ap.add_argument("--set-lit", action="append", default=[], metavar="KEY=VALUE")
    args = ap.parse_args()

    values: dict[str, str] = {}
    for item in args.set:
        key, _, path = item.partition("=")
        p = Path(path)
        if not p.is_file():
            # Fail loudly with a one-line, unambiguous message instead of a
            # raw FileNotFoundError traceback - confirmed real failure mode
            # (2026-09-18, laptop session): an upstream step silently didn't
            # write this file, this raised uncaught, template.out was never
            # written, and the CALLER's exit code wasn't checked either, so
            # the next tool down the pipe (llm_call.py) failed on the missing
            # PROMPT file instead, hiding the real cause. Exit code here is
            # still nonzero either way - every gate_task.sh call site must
            # check it - but the message now names the actual missing input.
            sys.exit(f"ERROR: --set {key}={path!r} - file does not exist, template not rendered")
        values[key] = p.read_text(errors="replace")
    for item in args.set_lit:
        key, _, val = item.partition("=")
        values[key] = val

    text = args.template.read_text()
    used = set()

    def repl(m: re.Match) -> str:
        key = m.group(1)
        used.add(key)
        if key not in values:
            raise SystemExit(f"ERROR: template placeholder {{{{{key}}}}} has no --set/--set-lit value")
        return values[key]

    rendered = re.sub(r"\{\{([A-Z_]+)\}\}", repl, text)

    unused = set(values) - used
    if unused:
        sys.stderr.write(f"WARNING: --set keys unused in template: {sorted(unused)}\n")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
