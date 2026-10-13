#!/usr/bin/env bash
# pipe_status.sh - one-screen view of the gate-v2 pipeline.
# Run:  watch -n 30 bash /root/qc/tools/pipe_status.sh
cd /root/qc
now=$(date -u +%s)
echo "GATE-V2 PIPELINE   $(date -u +%FT%TZ)"
echo
printf "LANES: "
for d in /root/.claude /root/.claude-*; do
  [ -f "$d/.credentials.json" ] || continue
  who=$(python3 -c "import json;print(json.load(open('$d/.claude.json')).get('oauthAccount',{}).get('emailAddress','?').split('@')[0])" 2>/dev/null)
  printf "%s(%s)  " "$(basename "$d")" "$who"
done
echo
echo "PROCS: pipe_batch=$(pgrep -fc pipe_batch.sh)  gate_task=$(pgrep -fc gate_task.sh)  opus/sonnet calls=$(pgrep -fc llm_call.py)  GLM solver=$(pgrep -fc 'timeout 3600 env IS_SANDBOX=1')"
echo "TOTALS: DONE=$(grep -c ' DONE ' stream-pipe/PIPE.log 2>/dev/null)  STOP/parked=$(grep -c ' STOP ' stream-pipe/PIPE.log 2>/dev/null)  queued=$(wc -l < stream-pipe/QUEUE.txt 2>/dev/null)  zips=$(ls out/pipe/*.zip 2>/dev/null | wc -l)  GLM ok=$(grep -c 'FINISH.*exit=0' runs/BATCH.log) fail=$(grep -c 'FINISH.*exit=[^0]' runs/BATCH.log) sched=$(pgrep -fc solver_batch.sh)"
echo
echo "IN FLIGHT   task           lane       step        last log line                                                       min"
for t in $(grep ' START ' stream-pipe/PIPE.log 2>/dev/null | awk '{print $3}' | sort -u); do
  d=stream-pipe/$t
  [ -f "$d/STATE" ] || continue
  pgrep -f "gate_task.sh $t" >/dev/null || continue
  lane=$(grep " START  $t " stream-pipe/PIPE.log | tail -1 | sed 's/.*lane=//; s#/root/##')
  step=$(tail -1 "$d/STATE" 2>/dev/null)
  last=$(grep "^\[" "$d/pipeline.log" 2>/dev/null | tail -1 | cut -c22-90)
  started=$(grep " START  $t " stream-pipe/PIPE.log | tail -1 | cut -c2-21)
  t0=$(date -u -d "$started" +%s 2>/dev/null || echo "$now")
  printf "            %-14s %-10s %-11s %-68s %3d\n" "$t" "$lane" "$step" "$last" $(( (now - t0) / 60 ))
done
echo
echo "LAST 6 OUTCOMES:"
grep -E ' (DONE|STOP) ' stream-pipe/PIPE.log 2>/dev/null | tail -6 | cut -c1-150
echo
parked=$(ls stream-pipe/*/PARKED.md 2>/dev/null | xargs -r -n1 dirname | xargs -r -n1 basename | tr '\n' ' ')
echo "ALERTS (last 4, tools/watchdog.sh):"; tail -4 ALERTS.log 2>/dev/null | cut -c1-150
echo
echo "PARKED (need a human): $(echo $parked | wc -w) -> $parked"
