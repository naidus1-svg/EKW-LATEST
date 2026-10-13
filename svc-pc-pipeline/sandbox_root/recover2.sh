#!/usr/bin/env bash
# recover2.sh - one-shot: install the oversize-aware driver + POOL=40 pool, restart all drivers on the
# new code, undo the false "reviews-uncomputable" UNFIXABLE drops, and report the oversize scope.
# Report -> fleet/recover2.out. Launched detached so a dropped SSH session cannot interrupt it.
set -u
cd /root/qc || exit 1
CORP=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
DIG=/root/qc/_prompts/gate-revalidate/digests
{
  echo "=== RECOVER2 $(date -u +%FT%TZ) ==="
  for f in task_driver.sh driver_pool.sh; do
    tr -d '\r' < "$f" > "$f.tmp" && mv "$f.tmp" "$f"; chmod +x "$f"
    if bash -n "$f"; then echo "$f SYNOK"; else echo "$f SYNFAIL - ABORT"; exit 1; fi
  done
  # restart drivers on the new code (kill old-code drivers + their review calls; fixers keep draining)
  pkill -f task_driver.sh 2>/dev/null; pkill -f gate_review_cold.sh 2>/dev/null; sleep 2
  echo "post-kill: drivers=$(pgrep -fc task_driver.sh 2>/dev/null || echo 0) reviews=$(pgrep -fc gate_review_cold.sh 2>/dev/null || echo 0)"
  # undo the false UNFIXABLE (all were reviews-uncomputable) and clear the review-fail counters
  undo=0
  for v in /root/qc/fleet/verdicts/*.UNFIXABLE; do
    [ -e "$v" ] || continue
    if grep -q "reviews-uncomputable\|reviews failed" "$v" 2>/dev/null; then rm -f "$v"; undo=$((undo+1)); fi
  done
  rm -f /root/qc/fleet/reviewfail/* 2>/dev/null
  echo "undone false UNFIXABLE: $undo"
  # oversize scope for the morning: how many task digests exceed 9.5MB
  over=0; total=0
  for d in "$DIG"/SVC-PC-*.md; do
    [ -e "$d" ] || continue; total=$((total+1))
    sz=$(stat -c%s "$d" 2>/dev/null || echo 0); [ "$sz" -gt 9500000 ] && over=$((over+1))
  done
  echo "digests: total=$total oversize_gt_9.5MB=$over (these need a workspace review, flagged .OVERSIZE by the driver)"
  echo "verdicts now: PASS=$(ls /root/qc/fleet/verdicts/*.PASS 2>/dev/null|wc -l) FAIL=$(ls /root/qc/fleet/verdicts/*.FAIL 2>/dev/null|wc -l) UNFIX=$(ls /root/qc/fleet/verdicts/*.UNFIXABLE 2>/dev/null|wc -l) OVERSIZE=$(ls /root/qc/fleet/verdicts/*.OVERSIZE 2>/dev/null|wc -l)"
  echo "load: $(uptime | sed 's/.*load/load/')"
  echo "=== DONE $(date -u +%FT%TZ) ==="
} > /root/qc/fleet/recover2.out 2>&1
