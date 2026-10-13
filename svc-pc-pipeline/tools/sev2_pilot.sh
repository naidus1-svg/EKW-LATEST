#!/usr/bin/env bash
# sev2_pilot.sh - copy of thorough_pilot.sh pointed at run_workspace_review_sev2.py
# (severity-addendum-v2.md by default) instead of run_workspace_review_thorough.py.
# Output per task+reviewer: sev2_pipe/<task>/CR.sev2.<reviewer>.json (+ .stats.json, .log).
# Idempotent: skips an output that already parses AND is canonical (see is_canonical below).
# Retries once on failure or a non-canonical verdict; if still bad, records MISSING.
#
# Usage: sev2_pilot.sh <task-list-file> <reviewer:glm|sonnet> [concurrency]
#   reviewer=sonnet -> Max-lane pool, default concurrency 4, honours lanes/<lane>.benched
#                      and lanes/<lane>.limited_until, pool restricted to
#                      /root/.claude(-b|-c|-d|-e|-f|-g|-i|-j|-k|-l) only (never -m -n -p -s -t -u -h -o -q -r)
#   reviewer=glm    -> goes through the GLM proxy (/root/.glm_keys), default concurrency 6,
#                      does not use a lane at all
#
# Log: /root/qc/_prompts/sev2/pilot.log
# Missing (failed twice) list: /root/qc/_prompts/sev2/missing.txt
#
# Lane-pick timing note: the FIRST-attempt lane for each task is chosen in the main
# loop (synchronous, single shell) before backgrounding the job - NOT inside run_one
# itself - because a backgrounded subshell only inherits a snapshot of the round-robin
# counter I at fork time and can never see a sibling subshell's increments; picking
# lanes inside run_one would make every concurrent job re-read the same stale I and
# pile onto the same lane instead of round-robining. A retry's lane pick happens
# inside run_one's own subshell, which is fine: it only needs to differ from that one
# job's own first attempt, not stay in step with sibling jobs.
cd /root/qc || exit 1
LIST="$1"; REVIEWER="$2"; CONC="${3:-}"
if [ -z "$LIST" ] || [ -z "$REVIEWER" ]; then
  echo "usage: sev2_pilot.sh <task-list-file> <reviewer:glm|sonnet> [concurrency]" >&2
  exit 1
fi
case "$REVIEWER" in
  sonnet) CONC="${CONC:-4}" ;;
  glm) CONC="${CONC:-6}" ;;
  *) echo "reviewer must be glm or sonnet, got: $REVIEWER" >&2; exit 1 ;;
esac

PIPE_ROOT=/root/qc/sev2_pipe
WS_ROOT=/root/qc/review_workspace_sev2/$REVIEWER
mkdir -p "$WS_ROOT" /root/qc/_prompts/sev2
CORPUS=/root/qc/sev2_corpus
# allowed pool only - explicitly excludes -q -r (reserve/fix-round lanes) and the
# never-list -m -n -p -s -t -u -h -o (other live sessions on this box)
POOL=(/root/.claude /root/.claude-b /root/.claude-c /root/.claude-d /root/.claude-e /root/.claude-f /root/.claude-g /root/.claude-i /root/.claude-j /root/.claude-k /root/.claude-l)
LOG=/root/qc/_prompts/sev2/pilot.log
MISSING=/root/qc/_prompts/sev2/missing.txt
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

is_canonical() {  # $1 = path to CR json; exit 0 if canonical, 1 otherwise
  python3 -c "
import json, sys
try:
    j = json.load(open('$1'))
except Exception:
    sys.exit(1)
if j.get('overall_verdict') not in ('accept', 'reject', 'invalid', 'needs_revision'):
    sys.exit(1)
checks = j.get('checks')
if not isinstance(checks, list) or not checks:
    sys.exit(1)
for c in checks:
    if not isinstance(c, dict) or c.get('severity') not in ('major', 'minor', 'good'):
        sys.exit(1)
if not isinstance(j.get('major_count'), int) or not isinstance(j.get('minor_count'), int):
    sys.exit(1)
sys.exit(0)
" 2>/dev/null
}

run_attempt() {  # task lane attempt_no -> runs once, returns run_workspace_review_sev2.py's exit code
  local t="$1" lane="$2" n="$3"
  local out="$PIPE_ROOT/$t/CR.sev2.$REVIEWER.json"
  local pipe_dir="$PIPE_ROOT/$t"
  mkdir -p "$pipe_dir"
  log "START $t $REVIEWER attempt=$n lane=$([ -n "$lane" ] && basename "$lane" || echo none)"
  if [ -n "$lane" ]; then
    CLAUDE_CONFIG_DIR="$lane" python3 tools/run_workspace_review_sev2.py --task "$t" \
      --corpus-root "$CORPUS" --workspace-root "$WS_ROOT" --runs-root /root/qc/runs \
      --pipe-dir "$pipe_dir" --reviewer "$REVIEWER" --timeout 3000 \
      --out "$out" --stats-out "$pipe_dir/CR.sev2.$REVIEWER.stats.json" \
      > "$pipe_dir/CR.sev2.$REVIEWER.attempt$n.log" 2>&1
  else
    python3 tools/run_workspace_review_sev2.py --task "$t" \
      --corpus-root "$CORPUS" --workspace-root "$WS_ROOT" --runs-root /root/qc/runs \
      --pipe-dir "$pipe_dir" --reviewer "$REVIEWER" --timeout 3000 \
      --out "$out" --stats-out "$pipe_dir/CR.sev2.$REVIEWER.stats.json" \
      > "$pipe_dir/CR.sev2.$REVIEWER.attempt$n.log" 2>&1
  fi
  return $?
}

pick_lane() {  # sonnet only. Sets global CHOSEN_LANE, honouring .benched and .limited_until.
  # Deliberately NOT "echo a value, call it via $(pick_lane)": command substitution
  # always forks a subshell in bash, so the I=$((I+1)) round-robin counter would be
  # silently discarded on every single call and every caller would see the exact same
  # I (and thus the exact same lane) forever - confirmed empirically before this was
  # written this way: a $(...) version returned /root/.claude on all 13 test calls.
  CHOSEN_LANE=""
  for _k in $(seq 1 ${#POOL[@]}); do
    c="${POOL[$(( I % ${#POOL[@]} ))]}"; I=$((I+1))
    base="$(basename "$c")"
    if [ -f "/root/qc/lanes/${base}.benched" ]; then continue; fi
    lu="/root/qc/lanes/${base}.limited_until"
    if [ -f "$lu" ] && [ "$(tr -dc 0-9 < "$lu" 2>/dev/null || echo 0)" -gt "$(date +%s)" ] 2>/dev/null; then continue; fi
    CHOSEN_LANE="$c"; break
  done
  if [ -z "$CHOSEN_LANE" ]; then
    CHOSEN_LANE="${POOL[$(( I % ${#POOL[@]} ))]}"; I=$((I+1))
  fi
}

run_one() {  # task lane1 - lane1 is the pre-picked lane for attempt 1 (empty string for glm)
  local t="$1" lane="$2"
  local out="$PIPE_ROOT/$t/CR.sev2.$REVIEWER.json"
  if [ -f "$out" ] && is_canonical "$out"; then
    log "SKIP $t $REVIEWER (already canonical)"
    return
  fi
  run_attempt "$t" "$lane" 1
  if [ -f "$out" ] && is_canonical "$out"; then
    local v; v=$(python3 -c "import json; j=json.load(open('$out')); print(j.get('overall_verdict'), 'maj', j.get('major_count'), 'min', j.get('minor_count'))" 2>/dev/null)
    log "FINISH $t $REVIEWER attempt=1 $v"
    return
  fi
  log "RETRY $t $REVIEWER (attempt 1 failed or non-canonical)"
  local lane2=""
  if [ "$REVIEWER" = "sonnet" ]; then pick_lane; lane2="$CHOSEN_LANE"; fi
  run_attempt "$t" "$lane2" 2
  if [ -f "$out" ] && is_canonical "$out"; then
    local v; v=$(python3 -c "import json; j=json.load(open('$out')); print(j.get('overall_verdict'), 'maj', j.get('major_count'), 'min', j.get('minor_count'))" 2>/dev/null)
    log "FINISH $t $REVIEWER attempt=2 $v"
    return
  fi
  log "MISSING $t $REVIEWER (failed or non-canonical after 2 attempts)"
  echo "$t,$REVIEWER" >> "$MISSING"
}

I=0
log "SEV2 PILOT START list=$LIST reviewer=$REVIEWER tasks=$(grep -c . "$LIST") conc=$CONC"
while read -r t; do
  [ -n "$t" ] || continue
  while [ "$(jobs -rp | wc -l)" -ge "$CONC" ]; do sleep 10; done
  lane1=""
  if [ "$REVIEWER" = "sonnet" ]; then pick_lane; lane1="$CHOSEN_LANE"; fi
  run_one "$t" "$lane1" &
  sleep 3
done < "$LIST"
wait
log "SEV2 PILOT DONE list=$LIST reviewer=$REVIEWER"
