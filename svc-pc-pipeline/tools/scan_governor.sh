#!/usr/bin/env bash
# scan_governor.sh - keep the deterministic scans from starving latency-sensitive work (judge probes, review agents).
# 2026-09-19: a fix round launches scans that run 8+ worker processes at about 200 percent CPU each; two dispatchers together
# put 112 scan processes on 32 cores (load 185 to 341). Judge probes then time out at 300 s ("timed out after 300s", scored as
# 0.0), the zip step defers oracle launches while load1 > 64, and the 02:38 mass SIGKILL happened at that load.
# Every 2 s this moves each scan process into the cgroup /sys/fs/cgroup/qc-scans (cpu.weight 20 against 100 for everything
# else, cpu.max 20 cores). With spare CPU the scans still burst; under contention they yield. Children inherit the cgroup.
# Not governed: the actuator's svc_run_checks.py (critical path to a zip), judge_emulate.py, claude, run_workspace_review*.py.
# Off switch: touch /root/qc/lanes/GOVERNOR_OFF. Undo: kill this script; the cgroup empties as the scans exit.
# Cron: * * * * * flock -n /run/scan_governor.lock bash /root/qc/tools/scan_governor.sh >/dev/null 2>&1
CG=/sys/fs/cgroup/qc-scans
[ -d "$CG" ] || mkdir "$CG" || exit 1
echo 20 > "$CG/cpu.weight"
echo "2000000 100000" > "$CG/cpu.max"
PAT='tools/[a-z_]*_scan\.py|duplicate_criterion_check\.py|build_cr_context\.py|gather_files_text\.py'
while true; do
  if [ -f /root/qc/lanes/GOVERNOR_OFF ]; then sleep 10; continue; fi
  for p in $(pgrep -f "$PAT"); do
    grep -q qc-scans "/proc/$p/cgroup" 2>/dev/null || echo "$p" > "$CG/cgroup.procs" 2>/dev/null
  done
  sleep 2
done
