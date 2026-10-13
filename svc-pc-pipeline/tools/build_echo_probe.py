#!/usr/bin/env python3
"""build_echo_probe.py - GATE-V2 3.1 echo probe, script-only (no model call;
HANDOFF.md section 3 restricts model calls to steps 3, 4 and the step-5
adjudication - the echo probe is generated mechanically).

"A deliverable containing only the instruction's requirements restated as
assertions, no figures, no analysis" (GATE-V2 3.1). This script:
  1. Reads instruction.md, drops the email-header lines (From/To/Subject)
     and the "## Graded deliverable filenames" section and after (that part
     names files, not requirements).
  2. Splits the remainder into sentences.
  3. Redacts every dollar amount, percentage, and standalone number to
     "[figure]" so no genuine figure appears (no computation happened, so no
     computed figure should be present either).
  4. Writes each redacted sentence as a flat assertion line ("Confirmed: ...")
     to a plain .txt file - restating what was asked, doing none of it.

This is a heuristic, not a natural-language paraphraser: it cannot rewrite
imperative instruction prose into fluent declarative assertions without a
model call, which step 5 is not allowed to spend. The result is still a
faithful echo for the probe's purpose (a rubric that scores this above 0.5
is rewarding prompt-restatement, not derived work), even where a sentence
reads awkwardly as an "assertion."

Usage:
    python3 build_echo_probe.py <TASK> --out ECHO.txt [--corpus-root PATH]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

DEFAULT_CORPUS_ROOT = Path("/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready")

_FIGURE_RE = re.compile(
    r"\$[\d,]+(?:\.\d+)?[MKk]?\b"        # $4,500,000 / $45K / $1.2M
    r"|\b\d[\d,]*(?:\.\d+)?%"             # 12% / 62.5%
    r"|\b\d[\d,]*(?:\.\d+)?\b"            # bare numbers
)

_HEADER_LINE_RE = re.compile(r"^(From|To|Subject|Cc|Date):", re.IGNORECASE)


def load_requirements_text(instruction_path: Path) -> str:
    text = instruction_path.read_text(errors="replace")
    # Cut off anything from "## Graded deliverable filenames" onward - that
    # names files, not requirements to restate.
    cut = re.split(r"\n##\s*Graded deliverable filenames", text, maxsplit=1)[0]
    lines = [l for l in cut.splitlines() if not _HEADER_LINE_RE.match(l.strip())]
    return "\n".join(lines)


def split_sentences(text: str) -> list[str]:
    # Collapse whitespace, then split on sentence-ending punctuation followed
    # by whitespace+capital or end of text. Simple and good enough for memo
    # prose; not meant to be a general sentence tokenizer.
    flat = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"'])", flat)
    return [p.strip() for p in parts if p.strip()]


def redact_figures(sentence: str) -> str:
    return _FIGURE_RE.sub("[figure]", sentence)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    args = ap.parse_args()

    task_dir = args.corpus_root / args.task
    instr = task_dir / "instruction.md"
    if not instr.is_file():
        raise SystemExit(f"ERROR: missing {instr}")

    req_text = load_requirements_text(instr)
    sentences = split_sentences(req_text)

    lines = [f"# Echo probe - {args.task} (GATE-V2 3.1, script-generated, no analysis performed)", ""]
    for s in sentences:
        redacted = redact_figures(s)
        lines.append(f"Confirmed: {redacted}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out} ({len(sentences)} assertions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
