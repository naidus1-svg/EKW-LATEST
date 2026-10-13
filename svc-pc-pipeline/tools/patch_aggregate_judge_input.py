#!/usr/bin/env python3
"""Let aggregate_fresh.py's marker rule read the fresh judge-input report.
Why (2026-09-19 20:40Z): rule 3 of the DATAOS_MAJORS_RESOLVED marker ("judge_input_report has actually run and is
non-blocking") read only dataos-old/judge_input/<task>.json, which exists for the old set's 44 tasks and for none of the
22 batch 6-8 tasks, while every one of the 22 has stream-pipe/<task>/probes/judge_input.json (written by the actuator, the
zip loop or pipe2's probes) and all are non-blocking. Result: no task in the 22 could ever get its marker, so the zip loop
could never touch it, whatever the verify loop ruled. Fix: fall back to the fresh report when the old one is absent, and
count it as run only when no shipped file is newer than it (task_fingerprint.newest_mtime, the same test rule 5 uses).
Usage: python3 patch_aggregate_judge_input.py [SCRIPT=/root/qc/_prompts/verify/dataos-fresh/aggregate_fresh.py]
-> writes SCRIPT.new, compile-checked, SCRIPT untouched. Refuses unless the anchor occurs exactly once and `tf` is imported.
"""

import py_compile
import re
import sys

SCRIPT = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/qc/_prompts/verify/dataos-fresh/aggregate_fresh.py"
)

ANCHOR = """def judge_input_blocking(task: str) -> bool | None:
    p = OLD / "judge_input" / f"{task}.json"
    if not p.is_file():
        return None
    try:
        return bool(json.loads(p.read_text()).get("blocking_major"))
    except Exception:
        return None
"""

NEW = """def judge_input_blocking(task: str) -> bool | None:
    p = OLD / "judge_input" / f"{task}.json"
    if not p.is_file():
        # 20:40Z: the fresh set has no dataos-old/judge_input/<task>.json (that dir holds the old set's 44); every one of
        # the 22 has stream-pipe/<task>/probes/judge_input.json (actuator, zip loop, pipe2 probes). Use it when no shipped
        # file is newer than it: a report older than the bytes has not "actually run" on them.
        p = PIPE / task / "probes" / "judge_input.json"
        if not p.is_file():
            return None
        try:
            if tf.newest_mtime(task) > p.stat().st_mtime:
                return None
        except Exception:
            return None
    try:
        return bool(json.loads(p.read_text()).get("blocking_major"))
    except Exception:
        return None
"""

src = open(SCRIPT, encoding="utf-8").read()
n = src.count(ANCHOR)
if n != 1:
    print(f"REFUSED: anchor occurs {n} times (need exactly 1)")
    sys.exit(2)
if (
    not re.search(
        r"^import task_fingerprint as tf|^\s*import task_fingerprint as tf|as tf$",
        src,
        re.M,
    )
    and "tf.newest_mtime" not in src
):
    print("REFUSED: task_fingerprint is not imported as tf")
    sys.exit(2)
out = src.replace(ANCHOR, NEW)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(SCRIPT + ".new", doraise=True)
print(f"wrote {SCRIPT}.new ({len(out) - len(src):+d} bytes), compiled")
