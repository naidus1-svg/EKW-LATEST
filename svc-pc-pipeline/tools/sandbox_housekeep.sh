#!/bin/bash
# Sandbox housekeeping, run from cron every 30 min (see crontab line at the bottom). Deletes nothing of value.
# 2026-09-26: the root disk hit 100% (lane session transcripts, ~350 GB of *.jsonl under /root/.claude-*/projects)
# and /tmp ran out of inodes (96,796 matplotlib "mat-debug-*" temp dirs). judge_emulate crashed with Errno 28,
# 17 tasks parked, and the pool died at 10:12Z; lanes sat idle ~10 h before anyone looked.
#  1. /tmp: remove matplotlib temp dirs older than 60 min (nothing reads them after the render that made them).
#  2. Root disk: when free space drops under LOW_GB, gzip transcripts older than 2 days in place
#     (/root/qc/compress_transcripts.sh, reversible with gunzip) until TARGET_GB is free.
#  3. Log one line with free space and /tmp inode use to /root/qc/housekeep.log.
#  5. /tmp inodes (2026-09-28): lane scratch (regrade_*, tmp*, _scratch*, per-task dirs, ...) filled /tmp to 93% of its
#     inodes and the VM stopped answering SSH. When inode use reaches TMP_PCT, remove top-level /tmp entries older
#     than TMP_AGE_MIN (no lane attempt runs that long), never system entries (sockets, systemd, ssh, tmux, snap).
#  6. Orphan reaper (2026-09-29): a `python3 -` left behind by lane i's `claude -p` session on SCO-232 (parent PID 1,
#     cwd .../_raw/SCO-232/source_documents) held 88.6 GB RSS at ~97% CPU for 8.7 h. Load reached 168 with 5 GB of
#     125 GB free before it was killed by hand; nothing reaped orphaned lane helpers.
#     Candidate: parent is PID 1 AND environ has CLAUDE_CONFIG_DIR=/root/.claude-<lane>, and it is not a lane runner,
#     a pool script, a `claude` process, or a judge_emulate.py whose lane still has a live runner on the same task.
#     Kill only when RSS > REAP_RSS_GB, or elapsed > REAP_ELAPSED_S with CPU time > REAP_CPU_S: TERM, then KILL after
#     REAP_GRACE_S. Every kill and every spared candidate goes to REAP_LOG with its reason. A false kill wastes a
#     lane's work, so anything the rule does not name is spared. The start time is re-read before each signal so a
#     recycled pid is never hit. `--reap-dry-run` prints the decisions, kills nothing, and runs no other step.
REAP_LOG="${HK_REAP_LOG:-/root/qc/_v7/reaper.log}"
REAP_RSS_GB="${REAP_RSS_GB:-20}"; REAP_ELAPSED_S="${REAP_ELAPSED_S:-10800}"; REAP_CPU_S="${REAP_CPU_S:-3600}"
REAP_GRACE_S="${REAP_GRACE_S:-10}"; REAP_LANE_RE="${REAP_LANE_RE:-[A-Za-z0-9]+}"
REAP_DRY=0; [ "${1:-}" = "--reap-dry-run" ] && REAP_DRY=1
REAP_KILLS=0
reap_log(){ if [ "$REAP_DRY" = 1 ]; then echo "DRY-RUN $*"; else echo "$(date -u +%FT%TZ) $*" >> "$REAP_LOG"; fi; }
pstart(){ { sed 's/.*) //' "/proc/$1/stat" | cut -d' ' -f20; } 2>/dev/null; }
reap_orphans(){
  local pid ppid lane rss et cpu comm args cwd exe spare kill t i s n_orph=0 n_cand=0 vic=() st=()
  local re_runner='_lane_runner\.sh' re_pool='[A-Za-z0-9_]*pool[A-Za-z0-9_]*\.sh' re_judge='judge_emulate\.py +[a-z]+ +([^ ]+)'
  while read -r pid ppid; do
    [ "$ppid" = 1 ] && [ "$pid" != "$$" ] || continue
    n_orph=$((n_orph+1))
    lane=$({ tr '\0' '\n' < "/proc/$pid/environ"; } 2>/dev/null | sed -nE "s#^CLAUDE_CONFIG_DIR=/root/\.claude-($REAP_LANE_RE)\$#\1#p" | head -1)
    [ -n "$lane" ] || continue
    read -r rss et cpu comm < <(ps -o rss=,etimes=,times=,comm= -p "$pid" 2>/dev/null) || continue
    n_cand=$((n_cand+1))
    args=$({ tr '\0' ' ' < "/proc/$pid/cmdline"; } 2>/dev/null | tr -d '\n' | cut -c1-120)
    cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null); exe=$(basename "$(readlink "/proc/$pid/exe" 2>/dev/null)" 2>/dev/null)
    spare=""; kill=""
    if [[ "$args" =~ $re_runner ]]; then spare="lane runner"
    elif [[ "$args" =~ $re_pool ]]; then spare="pool"
    elif [ "$comm" = claude ] || [ "$exe" = claude ] || [ "$(basename "${args%% *}" 2>/dev/null)" = claude ]; then spare="claude process"
    elif [[ "$args" =~ $re_judge ]] && t="${BASH_REMATCH[1]}" && pgrep -f "_lane_[r]unner\.sh $t $lane\$" >/dev/null; then
      spare="judge_emulate.py with a live runner ($t on lane $lane)"
    elif [ "${rss:-0}" -gt $((REAP_RSS_GB*1024*1024)) ]; then kill="rss ${rss}kB > ${REAP_RSS_GB}GB"
    elif [ "${et:-0}" -gt "$REAP_ELAPSED_S" ] && [ "${cpu:-0}" -gt "$REAP_CPU_S" ]; then kill="elapsed ${et}s > ${REAP_ELAPSED_S}s and cpu ${cpu}s > ${REAP_CPU_S}s"
    else spare="below thresholds (rss ${rss}kB, elapsed ${et}s, cpu ${cpu}s)"
    fi
    if [ -n "$spare" ]; then
      reap_log "SPARE pid=$pid lane=$lane why=\"$spare\" cwd=$cwd args=\"$args\""
    else
      reap_log "$([ "$REAP_DRY" = 1 ] && echo WOULD-KILL || echo KILL) pid=$pid lane=$lane cwd=$cwd rss_kb=$rss elapsed_s=$et cpu_s=$cpu why=\"$kill\" args=\"$args\""
      vic+=("$pid"); st+=("$(pstart "$pid")")
    fi
  done < <(ps -eo pid=,ppid=)
  [ "$REAP_DRY" = 1 ] && { echo "DRY-RUN summary: ppid1_procs=$n_orph lane_tagged_orphans=$n_cand would_kill=${#vic[@]}"; return; }
  [ "${#vic[@]}" -gt 0 ] || return
  for i in "${!vic[@]}"; do [ "$(pstart "${vic[$i]}")" = "${st[$i]}" ] && kill -TERM "${vic[$i]}" 2>/dev/null; done
  for ((s=0; s<REAP_GRACE_S; s++)); do
    t=0; for i in "${!vic[@]}"; do [ "$(pstart "${vic[$i]}")" = "${st[$i]}" ] && t=1; done
    [ "$t" = 0 ] && break; sleep 1
  done
  for i in "${!vic[@]}"; do
    if [ "$(pstart "${vic[$i]}")" = "${st[$i]}" ]; then
      kill -KILL "${vic[$i]}" 2>/dev/null; reap_log "SIGKILL pid=${vic[$i]} (still alive ${REAP_GRACE_S}s after TERM)"
    fi
  done
  REAP_KILLS=${#vic[@]}
}
reap_orphans
[ "$REAP_DRY" = 1 ] && exit 0
reap_note=""; [ "$REAP_KILLS" -gt 0 ] && reap_note=" REAPED=$REAP_KILLS"
LOW_GB="${LOW_GB:-60}"
TMP_DIR="${HK_TMP:-/tmp}"; TMP_PCT="${TMP_PCT:-70}"; TMP_AGE_MIN="${TMP_AGE_MIN:-720}"
find "$TMP_DIR" -maxdepth 1 -name 'mat-debug-*' -mmin +60 -exec rm -rf {} + 2>/dev/null
tmp_pct=$(df --output=ipcent "$TMP_DIR" | tail -1 | tr -dc 0-9)
tmp_note=""
if [ "${tmp_pct:-0}" -ge "$TMP_PCT" ]; then
  find "$TMP_DIR" -mindepth 1 -maxdepth 1 -mmin +"$TMP_AGE_MIN" \
    ! -name '.*' ! -name 'systemd-private-*' ! -name 'ssh-*' ! -name 'tmux-*' ! -name 'snap-private-tmp' \
    -exec rm -rf {} + 2>/dev/null
  tmp_note=" TMP_CLEANED(${tmp_pct}%->$(df --output=ipcent "$TMP_DIR" | tail -1 | tr -d ' '))"
fi
free=$(df --output=avail -BG / | tail -1 | tr -dc 0-9)
if [ "${free:-0}" -lt "$LOW_GB" ] && ! pgrep -f '^bash /root/qc/[c]ompress_transcripts.sh' >/dev/null; then
  TARGET_GB=150 bash /root/qc/compress_transcripts.sh
fi
# 4. Pool watchdog (2026-09-26): the pool died at 10:12Z and nothing noticed for ~10 h. If no dispatcher is
#    running and no POOL_STOP was requested, relaunch it (same detached form as the runbook) and log it.
POOL="${HK_POOL:-/root/qc/svc_v7_pool.sh}"; POOLWORK="${HK_POOLWORK:-/root/qc/_v7}"; HKLOG="${HK_LOG:-/root/qc/housekeep.log}"
pool_note=""
if [ ! -f "$POOLWORK/POOL_STOP" ] && ! pgrep -f "^bash $POOL\$" >/dev/null; then
  (setsid nohup bash "$POOL" > "$POOLWORK/pool.out" 2>&1 < /dev/null &)
  pool_note=" POOL_RELAUNCHED"
fi
echo "$(date -u +%FT%TZ)${pool_note}${tmp_note}${reap_note} free=$(df --output=avail -BG / | tail -1 | tr -d ' ') tmp_inodes=$(df --output=ipcent /tmp | tail -1 | tr -d ' ')" \
  >> "$HKLOG"
# crontab: */30 * * * * /bin/bash /root/qc/sandbox_housekeep.sh >/dev/null 2>&1
