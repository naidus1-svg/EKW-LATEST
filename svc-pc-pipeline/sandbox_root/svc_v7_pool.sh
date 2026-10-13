#!/bin/bash
# v7 work-stealing pool: one worker per probed-OK lane, each running svc_v7_lane_runner.sh sequentially
# (one Opus per lane at a time - the per-account 5-hour window and one-task-one-lane rule). Work-stealing
# via atomic mkdir claim, so a capped lane never stalls the others. Sandbox-resident; launch under
# setsid/nohup. Self-heals across window resets: every candidate lane gets a worker that waits for its OWN
# window (wait_ok, re-probe every CAP_WAIT) and rejoins the moment it answers; a lane that caps mid-run
# RELEASES its task (runner exit 10) and waits the same way. A restarted pool adopts running runners (waits
# for them) instead of doubling a lane. Real defects (runner exit 20) park in parked.txt and are not retried.
# Usage: svc_v7_pool.sh ["lane letters"]
set -uo pipefail

QC="${POOL_QC:-/root/qc}"; WORK="$QC/_v7"; QUEUE="$WORK/queue.txt"   # POOL_QC: test override only
mkdir -p "$WORK/claims" "$WORK/retries" "$WORK/logs" "$WORK/ready"
POOLLOG="$WORK/pool.log"
# Lane candidates: an explicit arg, else EVERY real /root/.claude-? dir (no hardcoded roster to drift), minus
# known duplicate accounts. probe_ok() then live-filters capped/wedged lanes each pass, so this is only the
# candidate set. DUP_ACCOUNTS: s duplicates p (same Max account per lanes/LANES.md) - running both over-loads p.
DUP_ACCOUNTS=" s "
# Real lanes are lowercase. 2026-09-24: uppercase test lanes T and U kept coming back because probing a lane runs the
# real `claude` with CLAUDE_CONFIG_DIR=/root/.claude-T, which recreates the dir, so the pool re-adopted them forever.
if [ -n "${1:-}" ]; then RAW="$1"; else RAW="$(ls -d /root/.claude-[a-z] /root/.claude-[a-z][0-9] /root/.claude-[a-z][0-9][0-9] 2>/dev/null | sed 's#.*/.claude-##' | tr '\n' ' ')"; fi
LANES=""; for L in $RAW; do case "$DUP_ACCOUNTS" in *" $L "*) continue;; esac; LANES="$LANES $L"; done
MAX_RETRY=3          # informational only since 2026-09-24: lane limits release, never park
IDLE_POLL="${POOL_IDLE_POLL:-120}"   # an idle worker re-reads the queue this often (DataOS rejects are requeued at any time)
MAX_HOURS=168        # hard wall-clock stop; touch $WORK/POOL_STOP for a clean stop (workers finish their task)
STOPF="$WORK/POOL_STOP"
plog(){ echo "$(date -u +%FT%TZ) POOL $*" | tee -a "$POOLLOG"; }


probe_ok(){          # echo the lanes that answer OK right now
  local L o ok=""
  for L in $LANES; do
    o="$(CLAUDE_CONFIG_DIR=/root/.claude-$L timeout 70 claude -p --model sonnet --permission-mode dontAsk 'Reply with only the word OK' 2>&1 | tr -d '\r' | grep -o OK | head -1)"
    [ "$o" = "OK" ] && ok="$ok $L"
  done
  echo "$ok"
}

claimable_left(){    # count queue tasks with no claim dir (unclaimed or released) - what still needs a lane
  local t n=0
  while read -r t; do
    t="$(printf '%s' "$t" | tr -d '\r' | tr -d '[:space:]')"; [ -z "$t" ] && continue
    case "$t" in \#*) continue;; esac
    off_limits "$t" && continue
    [ -d "$WORK/claims/$t" ] || n=$((n+1))
  done < "$QUEUE"
  echo "$n"
}

# 2026-09-25 (owner): lanes work only what we are signed up for. tools/svc_build_freeze.py --push writes
# do_not_touch.txt every cycle (submitted anywhere, owned by someone else, or not assigned to us on the Combined
# tracker). The runner used to find out only after the pool claimed the task, so the claim sat held by a parked run.
off_limits(){ [ -f "$WORK/do_not_touch.txt" ] && tr -d '\r' < "$WORK/do_not_touch.txt" | grep -qx "$1"; }

claim_next(){        # atomic claim of the first still-unclaimed queue line that is still ours
  local t
  [ -f "$QUEUE" ] || return 1
  while read -r t; do
    t="$(printf '%s' "$t" | tr -d '\r' | tr -d '[:space:]')"; [ -z "$t" ] && continue
    case "$t" in \#*) continue;; esac
    off_limits "$t" && continue
    if mkdir "$WORK/claims/$t" 2>/dev/null; then echo "$t"; return 0; fi
  done < "$QUEUE"
  return 1
}

lane_ok(){          # $1 = lane; 0 if this one account answers right now
  local o
  o="$(CLAUDE_CONFIG_DIR=/root/.claude-$1 timeout 70 claude -p --model sonnet --permission-mode dontAsk 'Reply with only the word OK' 2>&1 | tr -d '\r' | grep -o OK | head -1)"
  [ "$o" = "OK" ]
}

CAP_WAIT=900         # a capped lane re-probes itself this often and rejoins when its window resets
CAP_WAIT_MAX_H=14    # ...for at most this long (a weekly cap can be days; then it leaves for the next pass)

wait_ok(){           # $1 = lane; block until it answers OK, re-probing every CAP_WAIT; 1 after CAP_WAIT_MAX_H
  local L="$1" waited=0
  until lane_ok "$L"; do
    if [ "$waited" -ge $(( CAP_WAIT_MAX_H * 3600 )) ]; then plog "lane $L still capped after ${CAP_WAIT_MAX_H}h; leaving for the next pass"; return 1; fi
    plog "lane $L capped; re-probing in ${CAP_WAIT}s"; sleep "$CAP_WAIT"; waited=$(( waited + CAP_WAIT ))
  done
}

lane_busy(){         # $1 = lane; 0 if a runner not started by this worker (old pool, svc_release_launch.sh) owns it
  pgrep -f "[s]vc_v7_lane_runner.sh SVC-PC-[0-9-]* $1\$" >/dev/null \
    || pgrep -f "[e]kw_v1_lane_runner.sh [A-Z]*-[0-9]* $1\$" >/dev/null
}

# 2026-09-25 (owner): lanes never idle while EKW work exists. SVC stays first; when claim_next finds no SVC task the
# worker claims from the EKW queue (/root/qc/_ekw, same claim/exit-code contract, runner releases its own claim on
# 10/30). POOL_EKW_CLAIM / POOL_EKW_RUNNER are test overrides.
EKW_WORK="${POOL_EKW_WORK:-$QC/_ekw}"
EKW_CLAIM="${POOL_EKW_CLAIM:-$QC/tools/ekw_v1_claim.sh}"
EKW_RUNNER="${POOL_EKW_RUNNER:-$QC/ekw_v1_lane_runner.sh}"
claim_ekw(){ [ -f "$EKW_CLAIM" ] || return 1; EKW_WORK="$EKW_WORK" bash "$EKW_CLAIM" 2>/dev/null; }

# 2026-09-25 (owner): a claim whose runner died before the pool saw its exit (pool restart, killed shell) was never
# released: 8 SVC tasks sat claimed with no runner for ~20h while 7 lanes idled, each last logged TRANSIENT (a lane
# limit, never a task defect). Reap a claim when no runner holds the task, it is older than REAP_AGE (a fresh claim
# is still being probed), and the task's newest log line is TRANSIENT. PARKED/READY claims are left alone.
REAP_AGE="${POOL_REAP_AGE:-600}"
reap_orphans(){      # $1 = work dir, $2 = runner basename
  local W="$1" R="$2" d t ll
  for d in "$W"/claims/*/; do
    [ -d "$d" ] || continue; t="$(basename "$d")"
    pgrep -f "[${R:0:1}]${R:1} $t " >/dev/null && continue
    [ $(( $(date +%s) - $(stat -c %Y "$d") )) -lt "$REAP_AGE" ] && continue
    ll="$(ls -t "$W/logs/$t"*.log 2>/dev/null | head -1)"; [ -n "$ll" ] || continue
    if tail -n 1 "$ll" | grep -q " TRANSIENT "; then
      rm -rf "$d" && plog "reaped orphan claim $t (no runner, last log TRANSIENT)"
    fi
  done
}

deadline_passed(){ [ $(( $(date +%s) - t0 )) -ge $(( MAX_HOURS * 3600 )) ]; }

worker(){            # $1 = lane; runs until POOL_STOP or MAX_HOURS, polling the queue when it is empty
  # 2026-09-23: this used to exit the first time claim_next found nothing, and a new pass only started once
  # EVERY worker had exited. DataOS rejects requeued later then sat unclaimed while lanes idled (9 of 23
  # workers left after 23h, 27 tasks queued). A worker now waits IDLE_POLL and re-reads the queue instead.
  local L="$1" t rc rf n
  while [ ! -f "$STOPF" ] && ! deadline_passed; do
    # Adopt: never put a second Opus agent on an account another runner already holds.
    if lane_busy "$L"; then sleep 15; continue; fi
    reap_orphans "$WORK" svc_v7_lane_runner.sh; reap_orphans "$EKW_WORK" ekw_v1_lane_runner.sh
    # Claim first, probe second: an idle lane costs a queue read, not a model call, every IDLE_POLL.
    t="$(claim_next)" || t=""
    KIND=svc; CLAIMS="$WORK/claims"; RUNNER="$QC/svc_v7_lane_runner.sh"
    if [ -z "$t" ]; then
      t="$(claim_ekw)" || t=""
      [ -n "$t" ] && { KIND=ekw; CLAIMS="$EKW_WORK/claims"; RUNNER="$EKW_RUNNER"; }
    fi
    if [ -z "$t" ]; then sleep "$IDLE_POLL"; continue; fi
    if ! lane_ok "$L"; then
      rm -rf "$CLAIMS/$t"                           # hand it to a lane that answers; wait out this one's window
      plog "lane $L capped at claim; released $t"
      wait_ok "$L" || true
      continue
    fi
    plog "lane $L claim $t ($KIND)"
    bash "$RUNNER" "$t" "$L" >/dev/null 2>&1; rc=$?
    if [ "$rc" -eq 10 ]; then                      # transient (lane capped / infra)
      rf="$WORK/retries/$t"; n=$(( $(cat "$rf" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$rf"
      # 2026-09-24 (owner): a lane usage limit is never a task defect, so it never parks a task. Before this, 6 tasks
      # sat parked as "transient x3" for a day with nothing wrong with them. Always release; wait_ok below throttles.
      rm -rf "$CLAIMS/$t"                           # release for another lane / next pass
      plog "lane $L TRANSIENT on $t (released, retry $n; lane limits never park a task)"
      wait_ok "$L" || true                          # wait out THIS lane's window, then rejoin
      continue
    fi
    if [ "$rc" -eq 30 ]; then                      # runner switched the task to decide mode (auto-decide)
      rm -rf "$CLAIMS/$t"
      plog "lane $L AUTO-DECIDE on $t (released for a decide-mode round)"
      continue
    fi
    plog "lane $L finished $t (rc=$rc)"             # 0 ready, 20 parked - claim kept either way
  done
  plog "lane $L worker exit"
}

[ "${POOL_SOURCE_ONLY:-}" = 1 ] && return 0 2>/dev/null   # tests source the functions only
t0=$(date +%s)
rm -f "$STOPF"
# One persistent worker per candidate lane; each waits for its own window (wait_ok) and for an adopted runner.
plog "POOL START claimable=$(claimable_left)  lanes=[$LANES]  idle_poll=${IDLE_POLL}s  max=${MAX_HOURS}h"
for L in $LANES; do worker "$L" & done
wait
plog "POOL_DONE ready=$(wc -l < "$WORK/ready.txt" 2>/dev/null || echo 0) parked=$(wc -l < "$WORK/parked.txt" 2>/dev/null || echo 0)"
