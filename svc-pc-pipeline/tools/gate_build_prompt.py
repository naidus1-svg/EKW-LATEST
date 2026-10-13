#!/usr/bin/env python3
"""gate_build_prompt.py CANON ADDENDUM CALIB_NOTE DET_FINDINGS DIGEST OUT_PROMPT

Variant of /root/qc/tools/v3digest_build_prompt.py (read-only source, never edited) for
the gate-backtest severity-calibrated review (see /root/qc/_prompts/gate-backtest/).
Assembles: a digest-mode override note (same text as v3digest_build_prompt.py's, so the
review is graded against the identical bar) + the canon review spec verbatim + the
severity addendum verbatim + a NEW gate-calibration note (narrows exactly two decisive
tests that a run-blind review cannot evaluate the way the addendum assumes - see that
file's own text) + a NEW deterministic-findings block (this task's mechanically
precomputed signals, e.g. judge_schema_bytes.py's schema-size result, which the reviewer
must explicitly rule major-or-not on rather than leave advisory) + the task's digest
document + a closing instruction.

CANON and ADDENDUM are read-only, unmodified copies of the same two files
tools/v3digest_review.sh and tools/sev2 use. CALIB_NOTE and DET_FINDINGS are new
gate-backtest-only files. Never writes to any of its input paths.
"""

import sys
from pathlib import Path

DIGEST_MODE_NOTE = """# DIGEST MODE (read first - this note supersedes the "in your sandbox workspace" paragraph below; nothing else in the canon text is altered)

You are not running as an agent and you have no tools: no Read, no Glob, no Grep, no Bash,
no file access of any kind. Everything you can know about this task is the single DIGEST
document appended at the very end of this prompt, after the severity addendum, the gate
calibration note, and the deterministic findings block. It is a deterministic, mechanical
text extraction of the task package: `instruction.md`, `task.toml`, `tests/` (every
`judge.toml` and `reward.toml`), `environment/` (the `Dockerfile` and every environment
file), and `solution/` (the golden/reference deliverable). Spreadsheets were extracted via
openpyxl loaded twice (cached values and formulas separately, per non-empty cell); Word
documents via python-docx (paragraphs with style names, tables as pipe rows, plus whether
the file's XML shows tracked changes or comments); PDFs via pdftotext; other text files
verbatim. A file the digest's own file index marks "binary, listed only" was NOT
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
exactly as written. Read it, then the severity addendum, then the gate calibration note,
then the deterministic findings block, then the digest, in that order.

**Output discipline (stricter than section 5's own wording below, which allows prose before
the JSON): reply with ONLY the JSON object section 5 specifies. No prose before it, no prose
after it, no code fence around it. Your entire reply must be that one JSON object**, because
this reply is parsed programmatically with nothing to recover a stray preamble or coda.

---

"""

CLOSING_NOTE = """

---

# YOUR TASK

Apply the review spec, the severity addendum, and the gate calibration note above to the
digest document above, for task `{task_id}`. You must also explicitly rule on every item in
the DETERMINISTIC FINDINGS block above: state under the check id it names whether it is (or
contributes to) a MAJOR finding, or explain with evidence why it does not. Do not leave any
deterministic finding advisory-only or unaddressed. Remember the output discipline from the
DIGEST MODE note at the top: reply with ONLY the JSON object, nothing before it, nothing
after it, no code fence.
"""


def main():
    if len(sys.argv) != 7:
        print(
            "usage: gate_build_prompt.py CANON ADDENDUM CALIB_NOTE DET_FINDINGS DIGEST OUT_PROMPT",
            file=sys.stderr,
        )
        return 1
    canon_p, addendum_p, calib_p, det_p, digest_p, out_p = (
        Path(a) for a in sys.argv[1:7]
    )
    canon = canon_p.read_text(encoding="utf-8")
    addendum = addendum_p.read_text(encoding="utf-8")
    calib = calib_p.read_text(encoding="utf-8")
    det = det_p.read_text(encoding="utf-8")
    digest = digest_p.read_text(encoding="utf-8")
    task_id = digest_p.stem

    parts = [
        DIGEST_MODE_NOTE,
        canon,
        "\n",
        addendum,
        "\n",
        calib,
        "\n\n---\n\n# DETERMINISTIC FINDINGS FOR THIS TASK (rule on each explicitly; see YOUR TASK below)\n\n",
        det,
        "\n\n---\n\n# DIGEST DOCUMENT FOR THIS TASK\n\n",
        digest,
        CLOSING_NOTE.format(task_id=task_id),
    ]
    text = "".join(parts)
    MAX_PROMPT_BYTES = 1_400_000  # ~385k prompt tokens; above this the 1,000,000-token context is blown
    if len(text) > MAX_PROMPT_BYTES:
        sys.stderr.write(
            f"REFUSING: single-shot digest prompt for {task_id} is {len(text)} bytes, over "
            f"{MAX_PROMPT_BYTES} (a 2.19MB prompt measured ~1.17M tokens, rejected client-side). "
            f"This legacy digest path cannot review a task this large. Route to workspace-mode "
            f"review (run_workspace_review.py via task_driver_ws.sh), which reads files with tools.\n"
        )
        return 3
    out_p.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote prompt {out_p} ({out_p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
