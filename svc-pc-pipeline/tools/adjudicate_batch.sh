#!/usr/bin/env bash
# adjudicate_batch.sh LIST_FILE [CONC=3] - run adjudicate_task.sh over a list of task ids (one per line, with or without the SVC-PC- prefix), rotating claude
# config dirs, at most CONC at a time, and holding off while the host load average is above 64 (judge calls start timing out there).
# Log: /root/qc/_prompts/adjudicate.log. Idempotent: adjudicate_task.sh keeps a fresh ADJUDICATE.json.
cd /root/qc || exit 1
LIST="${1:?list file}"
CONC="${2:-3}"
POOL=(/root/.claude-q /root/.claude-r /root/.claude-b /root/.claude-c /root/.claude-e /root/.claude-f /root/.claude-g /root/.claude-i)
LOG=/root/qc/_prompts/adjudicate.log
echo "$(date -u +%FT%TZ) ADJUDICATE BATCH START list=$LIST tasks=$(grep -c . "$LIST") conc=$CONC" | tee -a "$LOG"
i=0
while read -r t; do
  t="$(echo "$t" | tr -d '[:space:]')"
  [ -n "$t" ] || continue
  while [ "$(jobs -rp | wc -l)" -ge "$CONC" ] || [ "$(ps -eo args --no-headers | grep '[c]laude -p' | grep -vc 'glm-5')" -ge 75 ]; do sleep 20; done
  lane="${POOL[$((i % ${#POOL[@]}))]}"
  i=$((i + 1))
  ADJ_LANE="$lane" bash /root/qc/tools/adjudicate_task.sh "$t" > /dev/null 2>&1 &
  sleep 3
done < "$LIST"
wait
echo "$(date -u +%FT%TZ) ADJUDICATE BATCH DONE list=$LIST" | tee -a "$LOG"
