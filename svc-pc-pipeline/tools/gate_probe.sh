#!/usr/bin/env bash
# gate_probe.sh T [T ...] - run the zip actuator (stage_and_zip.sh) against a scratch output dir to learn whether a task passes
# the gates on its CURRENT bytes, without touching out/pipe. Prints the task, the exit code and the actuator's gate lines.
# Side effects, same as a zip-step attempt: rewrites /root/qc/stage/<T> and /root/qc/_recheck/<T>, and runs the 45 checks.
C=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
OUT=/root/qc/out/_gateprobe
mkdir -p "$OUT"
cd /root/qc || exit 1
for T in "$@"; do
  case "$T" in SVC-PC-*) ;; *) T="SVC-PC-$T" ;; esac
  log=$(bash stage_and_zip.sh "$C" "$T" "$OUT" --accept-skip golden_arithmetic,deliverable_count,source_truncation 2>&1)
  rc=$?
  echo "=== $T rc=$rc"
  echo "$log" | grep -E "^\[gate\]|^\[zip\]|BLOCKED|HOLD" | tail -6 | cut -c1-260
done
