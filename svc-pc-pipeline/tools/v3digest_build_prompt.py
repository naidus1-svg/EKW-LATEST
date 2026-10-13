#!/usr/bin/env python3
"""v3digest_build_prompt.py CANON ADDENDUM DIGEST OUT_PROMPT

Assembles the single-shot digest-review prompt: a digest-mode override note
(this script's own DIGEST_MODE_NOTE, not an edit to the canon file), then the
canon review spec verbatim, then the severity addendum verbatim (same two
files run_workspace_review_sev2.py reads - read-only, never copied-then-
edited), then the task's digest document, then a closing instruction.

The override note exists because the canon spec's opening describes a
workspace with task_files/, evaluations/ and prior_verifications/ directories
and Read/Glob/Grep/Bash tool access - none of which exist in digest mode. The
note tells the model to substitute "the digest below" for those paths and
tools, and to treat every evaluations/prior_verifications bullet exactly the
way the spec's own text already handles an EMPTY evaluations/ directory
(mark that bullet's evidence inconclusive, never a default pass) - because
the digest, per v3digest_build.py's own spec, contains the task package only
(instruction.md/task.toml/tests/environment/solution), never solver-run
trajectories or this corpus's prior deterministic-checks output. The rest of
the canon text (checks, process, severity/verdict rules, JSON output format)
is included byte-for-byte unchanged, so the digest-mode review is graded
against the identical bar the sev2 agentic review was.
"""

import sys
from pathlib import Path

DIGEST_MODE_NOTE = """# DIGEST MODE (read first - this note supersedes the "in your sandbox workspace" paragraph below; nothing else in the canon text is altered)

You are not running as an agent and you have no tools: no Read, no Glob, no Grep, no Bash,
no file access of any kind. Everything you can know about this task is the single DIGEST
document appended at the very end of this prompt, after the severity addendum. It is a
deterministic, mechanical text extraction of the task package: `instruction.md`, `task.toml`,
`tests/` (every `judge.toml` and `reward.toml`), `environment/` (the `Dockerfile` and every
environment file), and `solution/` (the golden/reference deliverable). Spreadsheets were
extracted via openpyxl loaded twice (cached values and formulas separately, per non-empty
cell); Word documents via python-docx (paragraphs with style names, tables as pipe rows, plus
whether the file's XML shows tracked changes or comments); PDFs via pdftotext; other text
files verbatim. A file the digest's own file index marks "binary, listed only" was NOT
extracted - you only have its name and size, nothing about its content.

**The digest does NOT include `evaluations/` (solver run trajectories, rewards, any
Oracle/golden run output) or `prior_verifications/` (this corpus's own deterministic-checks
output, `judge_input.json`).** Wherever a check below asks you to look at "the evaluations"
or "prior verifications" - treat it exactly as the spec's own text already instructs for an
EMPTY `evaluations/` directory: mark that bullet's evidence `inconclusive`, never a pass by
default, and say so in the check's justification. Do not invent a run, a trajectory, or a
reward you were not shown.

Wherever the checks or process below say "open X", "run Y", "extract text from Z", "use
Read/Glob/Grep/Bash", "your workspace", "task_files/" - read that as "find the relevant
content already present in the digest below". You cannot verify anything beyond what the
digest text already shows. If the digest shows a file as binary/listed-only, you cannot
inspect it and must say so (`inconclusive`) rather than guessing at its content.

Everything else below - the checks (section 1), the process (section 2), the verification
and severity rules (sections 3-4), and the required JSON output shape (section 5) - applies
exactly as written. Read it, then read the severity addendum that follows it (it narrows
section 4 the same way it would for a workspace-mode review), then read the digest.

**Output discipline (stricter than section 5's own wording below, which allows prose before
the JSON): reply with ONLY the JSON object section 5 specifies. No prose before it, no prose
after it, no code fence around it. Your entire reply must be that one JSON object**, because
this reply is parsed programmatically with nothing to recover a stray preamble or coda.

---

"""

CLOSING_NOTE = """

---

# YOUR TASK

Apply the review spec and severity addendum above to the digest document above, for task
`{task_id}`. Remember the output discipline from the DIGEST MODE note at the top: reply with
ONLY the JSON object, nothing before it, nothing after it, no code fence.
"""


def main():
    if len(sys.argv) != 5:
        print(
            "usage: v3digest_build_prompt.py CANON ADDENDUM DIGEST OUT_PROMPT",
            file=sys.stderr,
        )
        return 1
    canon_p, addendum_p, digest_p, out_p = (Path(a) for a in sys.argv[1:5])
    canon = canon_p.read_text(encoding="utf-8")
    addendum = addendum_p.read_text(encoding="utf-8")
    digest = digest_p.read_text(encoding="utf-8")
    task_id = digest_p.stem

    parts = [
        DIGEST_MODE_NOTE,
        canon,
        "\n",
        addendum,
        "\n\n---\n\n# DIGEST DOCUMENT FOR THIS TASK\n\n",
        digest,
        CLOSING_NOTE.format(task_id=task_id),
    ]
    out_p.write_text("".join(parts), encoding="utf-8", newline="\n")
    print(f"wrote prompt {out_p} ({out_p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
