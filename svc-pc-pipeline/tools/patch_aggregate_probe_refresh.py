#!/usr/bin/env python3
"""aggregate_fresh.py: when a task's judge-input probe is missing or older than its bytes, run judge_input_report.py (deterministic,
seconds, no model) instead of withholding the marker as "judge_input_report not run yet".
Why (2026-09-19 23:10Z): SVC-PC-11-4-0 had every DataOS row closed since 21:49Z and a clean round-3 pair, and sat unpackaged for 80
minutes because its probe (21:21:53Z) predated a 21:20:55Z edit by the fingerprint's reckoning and nothing re-ran the probe: the zip
loop only probes AFTER the marker gate, so the two waited on each other. Every task fixed tonight would hit the same hold.
Usage: python3 patch_aggregate_probe_refresh.py [SCRIPT=/root/qc/_prompts/verify/dataos-fresh/aggregate_fresh.py]
  -> writes SCRIPT.new, py_compile checked.
"""

import py_compile
import sys

SCRIPT = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/qc/_prompts/verify/dataos-fresh/aggregate_fresh.py"
)
OLD = (
    '        p = PIPE / task / "probes" / "judge_input.json"\n'
    "        if not p.is_file():\n"
    "            return None\n"
    "        try:\n"
    "            if tf.newest_mtime(task) > p.stat().st_mtime:\n"
    "                return None\n"
    "        except Exception:\n"
    "            return None\n"
)
NEW = (
    '        p = PIPE / task / "probes" / "judge_input.json"\n'
    "        # 23:10Z: a missing or stale probe is re-run here (deterministic, seconds). The zip loop probes only after the\n"
    "        # marker gate, so leaving this None made the marker and the probe wait on each other (11-4-0, 80 minutes).\n"
    "        try:\n"
    "            stale = (not p.is_file()) or tf.newest_mtime(task) > p.stat().st_mtime\n"
    "        except Exception:\n"
    "            stale = True\n"
    "        if stale:\n"
    "            import subprocess\n"
    "            p.parent.mkdir(parents=True, exist_ok=True)\n"
    '            tmp = p.with_suffix(".json.refresh")\n'
    "            try:\n"
    "                r = subprocess.run(\n"
    '                    ["python3", "/root/qc/tools/judge_input_report.py", "--task", task, "--out", str(tmp)],\n'
    "                    capture_output=True, text=True, timeout=300,\n"
    "                )\n"
    "                if r.returncode == 0 and tmp.is_file():\n"
    "                    tmp.replace(p)\n"
    "                else:\n"
    "                    return None\n"
    "            except Exception:\n"
    "                return None\n"
)

src = open(SCRIPT, encoding="utf-8").read()
if src.count(OLD) != 1:
    print(f"REFUSED: anchor count {src.count(OLD)} != 1")
    sys.exit(2)
out = src.replace(OLD, NEW)
open(SCRIPT + ".new", "w", encoding="utf-8", newline="\n").write(out)
py_compile.compile(SCRIPT + ".new", doraise=True)
print(
    f"wrote {SCRIPT}.new: stale or missing judge-input probe is re-run inside the ruling; py_compile ok"
)
