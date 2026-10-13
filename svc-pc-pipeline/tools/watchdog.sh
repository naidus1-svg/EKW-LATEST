#!/usr/bin/env bash
# watchdog.sh v2 - zero-token health checks for the gate-v2 pipeline (Claude Max
# lanes) and the GLM solver batch. Runs every 60s. Alerts go to /root/qc/ALERTS.log.
# Kept alive by cron (see install line at bottom). What it catches and does:
#   GLM  streak   8 of the last 10 solver finishes in THIS batch exit!=0 -> stop batch,
#                 quarantine failed runs, alert (proxy 402/5xx/down all look like this)
#   GLM  dead     no scheduler while runs remain -> alert (relaunch is a human call)
#   PIPE dup      same task running twice -> kill younger, alert
#   PIPE dead     no launcher while queue not drained -> alert
#   PIPE stale    running task with no log line for 45 min -> alert; 75 min -> kill (resumes on re-run)
#   PIPE stops    5+ non-parked STOP lines in 15 min -> alert with the last reason
#   LANE benched  a Max account is rate-limited -> benched until the account's own reset time
#                 (lanes/<lane>.reset_at, re-asserted every loop; the launcher's own bench file is only 60 min)
#   HOST load     auto-throttle: load > 6x cores -> PER_LANE 8; load < 2x cores -> PER_LANE 12
#   HOST disk     >90% -> alert
# Launch:  nohup bash /root/qc/tools/watchdog.sh > /root/qc/watchdog.out 2>&1 &
# Cron:    * * * * * pgrep -f 'tools/watchdog.sh' >/dev/null || nohup bash /root/qc/tools/watchdog.sh >> /root/qc/watchdog.out 2>&1 &
cd /root/qc || exit 1
shopt -s dotglob   # lane dirs start with a dot: lanes/*.benched must match .claude-x.benched
ALERTS=/root/qc/ALERTS.log; PIDFILE=/root/qc/watchdog.pid
SOLVER_RE='timeout 3600 env IS_SANDBOX=1'
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null && [ "$(cat "$PIDFILE")" != "$$" ]; then exit 0; fi
echo $$ > "$PIDFILE"
alert() { echo "$(date -u +%FT%TZ) $1" | tee -a "$ALERTS"; }
touch "$ALERTS"; alert "WATCHDOG v2 started pid $$"
declare -A last; cores=$(nproc)
throttle() { local key="$1" gap="$2"; local now; now=$(date +%s); [ $((now - ${last[$key]:-0})) -gt "$gap" ] && { last[$key]=$now; return 0; }; return 1; }

while true; do
  # ---- GLM ----
  if pgrep -f 'solver_batch.sh' >/dev/null; then
    recent=$(awk '/BATCH START|RESTART/{buf=""; next} {buf=buf $0 "\n"} END{printf "%s", buf}' runs/BATCH.log | grep ' FINISH ' | tail -10)
    nfin=$(echo "$recent" | grep -c FINISH); bad=$(echo "$recent" | grep -c 'exit=[^0]')
    if [ "$nfin" -ge 10 ] && [ "$bad" -ge 8 ]; then
      alert "GLM  KILL: $bad of last 10 solver runs in this batch exit!=0; stopping solver_batch.sh"
      pkill -f 'solver_batch.sh'; sleep 1; pkill -f "$SOLVER_RE"
      q=runs/_watchdog_fail_$(date -u +%Y%m%dT%H%M); mkdir -p "$q"; n=0
      for d in runs/SVC-PC-*/glm-*; do
        [ -f "$d/claude_exit_code.txt" ] && [ "$(cat "$d/claude_exit_code.txt")" != "0" ] || continue
        mkdir -p "$q/$(basename "$(dirname "$d")")"; mv "$d" "$q/$(basename "$(dirname "$d")")/"; n=$((n+1))
      done
      alert "GLM  quarantined $n failed runs to $q; sample: $(grep -h -m1 -E 'API Error|Error' "$q"/*/*/run.log 2>/dev/null | head -1 | cut -c1-150)"
      echo "$(date -u +%FT%TZ) WATCHDOG STOP: failure streak; relaunch: nohup bash tools/solver_batch.sh --go" >> runs/BATCH.log
    fi
  else
    left=$(( 404 - $(for d in runs/SVC-PC-*/glm-*; do [ -f "$d/claude_exit_code.txt" ] && [ "$(cat "$d/claude_exit_code.txt")" = 0 ] && echo x; done | wc -l) ))
    [ "$left" -gt 0 ] && throttle glmdead 900 && alert "GLM  DEAD: no scheduler running, $left runs still needed; relaunch: nohup bash tools/solver_batch.sh --go > runs/BATCH.nohup.log 2>&1 &"
  fi
  # orphan solver runs (no live scheduler ancestor)
  sched=$(for p in $(pgrep -f 'solver_batch.sh'); do pp=$(ps -o ppid= -p "$p" | tr -d ' '); ps -o args= -p "$pp" 2>/dev/null | grep -q solver_batch || echo "$p"; done | head -1)
  if [ -n "$sched" ]; then
    o=0; for c in $(pgrep -f "$SOLVER_RE"); do a=$c; hit=0; for i in 1 2 3 4 5 6 7 8; do a=$(ps -o ppid= -p "$a" 2>/dev/null | tr -d ' '); [ -z "$a" ] || [ "$a" = 1 ] && break; [ "$a" = "$sched" ] && { hit=1; break; }; done; [ $hit = 0 ] && { pkill -P "$c"; kill "$c" 2>/dev/null; o=$((o+1)); }; done
    [ "$o" -gt 0 ] && alert "GLM  KILL: $o orphan solver runs (no live scheduler parent)"
  fi

  # ---- PIPE ----
  dups=$(pgrep -fa 'bash /root/qc/tools/gate_task.sh' | awk '{print $NF}' | sort | uniq -d)
  for t in $dups; do
    pids=$(pgrep -f "bash /root/qc/tools/gate_task.sh $t$" | sort -n); keep=$(echo "$pids" | head -1)
    for p in $pids; do [ "$p" != "$keep" ] && { pkill -P "$p"; kill "$p"; }; done
    alert "PIPE KILL: duplicate run of $t, kept pid $keep"
  done
  nl=0; for p in $(pgrep -f 'pipe_batch.sh'); do pp=$(ps -o ppid= -p "$p" | tr -d ' '); ps -o args= -p "$pp" 2>/dev/null | grep -q pipe_batch.sh || nl=$((nl+1)); done
  [ "$nl" -gt 1 ] && alert "PIPE WARN: $nl launcher processes (should be 1)"
  if [ "$nl" -eq 0 ] && [ -s stream-pipe/QUEUE.txt ] && ! grep -q 'queue drained' <(tail -3 stream-pipe/PIPE.log 2>/dev/null); then
    throttle pipedead 900 && alert "PIPE DEAD: no launcher running and queue not drained; relaunch: nohup bash tools/pipe_batch.sh > stream-pipe/PIPE.nohup.log 2>&1 &"
  fi
  now=$(date +%s)
  for t in $(pgrep -fa 'bash /root/qc/tools/gate_task.sh' | awk '{print $NF}' | sort -u); do
    lg=stream-pipe/$t/pipeline.log; [ -f "$lg" ] || continue
    age=$(( (now - $(stat -c %Y "$lg")) / 60 ))
    if [ "$age" -ge 75 ]; then
      pids=$(pgrep -f "bash /root/qc/tools/gate_task.sh $t$"); for p in $pids; do pkill -P "$p"; kill "$p"; done
      alert "PIPE KILL: $t stale ${age}m (no log line); killed, will resume from STATE on next launcher pass"
    elif [ "$age" -ge 45 ]; then throttle "stale$t" 1800 && alert "PIPE STALE: $t no log line for ${age}m (last: $(grep '^\[' "$lg" | tail -1 | cut -c22-100))"; fi
  done
  cutoff=$(date -u -d '15 min ago' +%FT%TM)
  stops=$(awk -v c="$cutoff" 'substr($1,2,16)>=c && / STOP /' stream-pipe/PIPE.log 2>/dev/null | grep -vc parked)
  [ "$stops" -ge 5 ] && throttle stops 900 && alert "PIPE WARN: $stops non-parked STOP lines in 15 min: $(awk -v c="$cutoff" 'substr($1,2,16)>=c && / STOP /' stream-pipe/PIPE.log | grep -v parked | tail -1 | cut -c1-140)"
  # ---- BENCH re-assert: a bench lives until the account's own reset time, whatever deletes the marker ----
  for ra in lanes/*.reset_at; do
    [ -f "$ra" ] || continue; ln=$(basename "$ra" .reset_at); ep=$(tr -dc 0-9 < "$ra")
    if [ -n "$ep" ] && [ "$(date +%s)" -lt "$ep" ]; then
      [ -f "lanes/$ln.benched" ] || { throttle "gone$ln" 600 && alert "LANE bench marker for $ln was deleted by something; re-asserted (reset $(date -u -d @$ep +%H:%M) UTC)"; }
      touch "lanes/$ln.benched"
    else rm -f "$ra" "lanes/$ln.benched"; alert "LANE back: $ln bench expired (reset time passed), lane live again"; fi
  done
  b=$(ls lanes/*.benched 2>/dev/null | xargs -r -n1 basename | sed 's/.benched//' | tr '\n' ' ')
  [ -n "$b" ] && throttle bench 900 && alert "LANE benched (rate-limited): $b until $(for f in lanes/*.reset_at; do [ -f "$f" ] && printf '%s=%s ' "$(basename "$f" .reset_at)" "$(date -u -d @$(tr -dc 0-9 < "$f") +%H:%M)"; done)UTC"

  # ---- PARKED-BY-LIMIT sweep: a refused model call is a lane problem, not a task verdict ----
  for pk in stream-pipe/SVC-PC-*/PARKED.md; do
    [ -f "$pk" ] || continue; grep -q 'call failed' "$pk" || continue
    t=$(basename "$(dirname "$pk")")
    if grep -B25 'PARKED:' "stream-pipe/$t/pipeline.log" 2>/dev/null | tail -26 | grep -qiE 'usage limit|session limit|weekly limit|hit your [a-z ]*limit|rate.?limit|too many requests|resets [0-9]|resets [A-Z][a-z]{2} [0-9]'; then
      lane=$(grep " START  $t " stream-pipe/PIPE.log | tail -1 | sed 's/.*lane=//')
      rm -f "$pk"; echo "$t" >> stream-pipe/RETRY.txt
      if [ -n "$lane" ]; then
        rs=$(tail -60 "stream-pipe/$t/pipeline.log" | grep -oiE 'resets [0-9]{1,2}(:[0-9]{2})? ?[ap]m' | tail -1 | sed 's/resets //')
        ep=$(date -u -d "today $rs" +%s 2>/dev/null); [ -z "$ep" ] && ep=$(( $(date +%s) + 10800 ))
        [ "$ep" -le "$(date +%s)" ] && ep=$(( ep + 86400 ))
        ep=$(( ep + 300 )); echo "$ep" > "lanes/$(basename "$lane").reset_at"; touch "lanes/$(basename "$lane").benched"
        alert "LANE KILL: $t parked by a refused call on $lane; un-parked, queued for retry, lane benched until $(date -u -d @$ep +%H:%M) UTC (account says resets $rs)"
      else
        alert "LANE KILL: $t parked by a refused call, lane unknown; un-parked, queued for retry"
      fi
    fi
  done
  # ---- extra rounds: parked-after-N tasks get MAX_ROUNDS via seeded checkpoints ----
  r=$(python3 tools/unpark_more_rounds.py 2>/dev/null); case "$r" in nothing*|"") ;; *) alert "PIPE $r";; esac
  # ---- HOST ----
  load=$(cut -d' ' -f1 /proc/loadavg | cut -d. -f1)
  cur=$(cat lanes/PER_LANE 2>/dev/null || echo 12)
  if [ "$load" -gt $((cores * 6)) ] && [ "$cur" -gt 8 ]; then echo 8 > lanes/PER_LANE; alert "HOST throttle: load $load on $cores cores, PER_LANE 12 -> 8 for new launches"; fi
  if [ "$load" -lt $((cores * 2)) ] && [ "$cur" -lt 12 ]; then echo 12 > lanes/PER_LANE; alert "HOST throttle: load $load on $cores cores, PER_LANE -> 12"; fi
  rm_=$(stat -c %a /); if [ "$rm_" != "755" ]; then chmod 755 / && alert "HOST FIX: root directory mode was $rm_, reset to 755 (a 0700 root took the VM off the network on 2026-09-18)"; fi
  for dd in /etc /usr /var /run; do m=$(stat -c %a "$dd"); [ "$m" = "755" ] || { throttle "mode$dd" 3600 && alert "HOST WARN: $dd mode is $m (expected 755)"; }; done
  m=$(stat -c %a /tmp); [ "$m" = "1777" ] || { throttle modetmp 3600 && alert "HOST WARN: /tmp mode is $m (expected 1777)"; }
  df -P /root | awk 'NR==2 && $5+0 > 90 {print "HOST WARN: disk " $5 " used"}' | while read -r l; do alert "$l"; done
  sleep 60
done
