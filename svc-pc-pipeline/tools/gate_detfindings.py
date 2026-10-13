#!/usr/bin/env python3
"""gate_detfindings.py TASK TASKDIR OUT_MD

Builds the per-task DETERMINISTIC FINDINGS block that gate_build_prompt.py inserts into
the gate review prompt. Runs /root/qc/tools/judge_schema_bytes.py (read-only, unmodified)
against TASKDIR and formats its result as a block the reviewer must explicitly rule
major-or-not on. This is the only deterministic scan wired into the gate for this backtest
(see RESULT.md's "what was not integrated, and why" section for the broader
bundling/coverage/golden-grounding scan library this project chose not to re-run fresh).

Usage: gate_detfindings.py SVC-PC-11-4-0 /root/qc/sev2_corpus/SVC-PC-11-4-0 \
           /root/qc/_prompts/gate-backtest/detfindings/SVC-PC-11-4-0.md
"""

import subprocess
import sys
from pathlib import Path

BLOCK = 4000
WARN = 3500


def main():
    if len(sys.argv) != 4:
        print("usage: gate_detfindings.py TASK TASKDIR OUT_MD", file=sys.stderr)
        return 1
    task, taskdir, out_md = sys.argv[1:4]
    proc = subprocess.run(
        [
            sys.executable,
            "/root/qc/tools/judge_schema_bytes.py",
            taskdir,
            "--block",
            str(BLOCK),
            "--warn",
            str(WARN),
        ],
        capture_output=True,
        text=True,
    )
    table = proc.stdout.strip()
    worst = proc.returncode

    lines = [
        "## DF1 (check 1.8, environment packaging and errored runs)",
        "",
        "`judge_schema_bytes.py` compiled every judge group's strict response schema with "
        "rewardkit's own builder (`rewardkit.judges._build_response_schema`) and measured "
        "its serialized byte size, run directly against this task's own tests/*/judge.toml "
        f"(source: `{taskdir}`, read-only). Block threshold: {BLOCK} bytes - at or over "
        "this, Anthropic's structured-output compiler rejects the compiled grammar with "
        '"The compiled grammar is too large", which aborts rewardkit\'s TaskGroup and '
        "zeroes every evaluation in that group, including the oracle. Warn threshold: "
        f"{WARN} bytes (a margin call, not itself a crash).",
        "",
        "```",
        table,
        "```",
        "",
    ]
    if worst >= 2:
        lines += [
            "**At least one group is AT OR OVER the block threshold.** Rewardkit cannot "
            "compile this group's judge schema; the oracle and every solver run in that "
            "group score 0 regardless of content quality. This is a MAJOR 1.8 finding by "
            "the addendum's own decisive test (a), and the task verdict must be `invalid` "
            "unless you find a countervailing fact this note does not know about (state it "
            "explicitly if so). Do not let any other check's content quality argue this "
            "one away: a run that cannot receive a genuine reward is invalid regardless of "
            "how good the underlying work is.",
        ]
    elif worst == 1:
        lines += [
            "**No group is over the block threshold; at least one is in the warn band "
            f"({WARN}-{BLOCK - 1} bytes).** This is not, on its own, a demonstrated crash - "
            "rewardkit has not been shown to fail at this size. Rule explicitly: minor (a "
            "packaging margin worth tightening) or good (no real risk), with your reasoning "
            "against the specific byte count and criteria count shown above. Do not default "
            "this to major without a decisive-test basis for doing so.",
        ]
    else:
        lines += [
            "**Every group is comfortably under both thresholds.** State explicitly that "
            "this deterministic signal contributes nothing to a major finding, rather than "
            "leaving it unaddressed.",
        ]

    Path(out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(out_md).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"{task}: schema worst-exit={worst} -> wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
