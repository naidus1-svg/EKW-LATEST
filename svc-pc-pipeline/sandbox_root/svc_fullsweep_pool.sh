#!/bin/bash
# Work-stealing full-coverage-sweep pool for UNGRADED pipeline tasks.
# One persistent worker per lane; each worker atomically claims the next unclaimed task, fixes it under a
# per-task timeout, marks it done, and pulls the next. A hung session blocks only its own lane (until the
# timeout), never the whole queue - which is the failure the earlier jobs-cap runner hit (stalled at 14).
#
#   $1 = task-list file      $2 = brief template ({TASK} placeholder)      $3 = model (default sonnet)
#   $4 = per-task timeout seconds (default 1500 = 25 min)
# Launch detached: (setsid nohup bash /root/qc/svc_fullsweep_pool.sh /root/qc/_fill.txt \
#   /root/qc/_fullsweep_brief.md sonnet 1500 >/root/qc/_fillpool.log 2>&1 </dev/null &); exit 0
# Poll: sort -u /root/qc/_fillfix/progress.txt | tail; ls /root/qc/_fillfix/done | wc -l
set -u
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
LIST="$1"; BRIEF="$2"; MODEL="${3:-sonnet}"; TMO="${4:-1500}"
W=/root/qc/_fillfix
mkdir -p "$W/logs" "$W/snap" "$W/briefs" "$W/done"
rm -rf "$W/claim"; mkdir -p "$W/claim"          # fresh claims each run; done/ persists (skip re-fixed)
export QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
LANES=(q r m v w c e f i j k l p t u)            # 15 working lanes; g excluded (weekly-capped)
tr -d '\r' < "$LIST" | grep . > "$W/_queue.txt"

worker() {
  local L="$1" lane="/root/.claude-$1" t
  while read -r t; do
    [ -z "$t" ] && continue
    [ -e "$W/done/$t" ] && continue                       # already fixed in a prior pass
    mkdir "$W/claim/$t" 2>/dev/null || continue           # atomic claim; another worker has it
    [ -d "$CORPUS/$t" ] || { echo "skip $t absent" >>"$W/progress.txt"; continue; }
    if [ ! -d "$W/snap/$t" ]; then                        # preserve the FIRST pristine snapshot
      mkdir -p "$W/snap/$t"
      cp -a "$CORPUS/$t/tests" "$W/snap/$t/tests" 2>/dev/null
      cp -a "$CORPUS/$t/solution" "$W/snap/$t/solution" 2>/dev/null
    fi
    # graded task with accumulated DataOS findings -> directed brief; else the generic full sweep
    if [ -f "/root/qc/_targeted/$t.md" ]; then
      cp "/root/qc/_targeted/$t.md" "$W/briefs/$t.md"
    else
      sed "s/{TASK}/$t/g" "$BRIEF" > "$W/briefs/$t.md"
    fi
    ( cd "$CORPUS/$t" && CLAUDE_CONFIG_DIR="$lane" timeout "$TMO" claude -p "$(cat "$W/briefs/$t.md")" \
        --model "$MODEL" --permission-mode dontAsk --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
        --output-format text > "$W/logs/$t.fix.log" 2>&1 )
    local rc=$?
    # VERIFY inline on the same lane: mark done ONLY if the real oracle scores the golden 1.0.
    # This replaces the separate serial gate - done now means shippable.
    local orc=""
    if [ "$rc" -eq 0 ] && [ -s "$W/logs/$t.fix.log" ]; then
      mkdir -p "$W/verify"
      # 2x: judge_emulate takes the MIN across runs, so total_reward==1.0 means BOTH runs scored 1.0
      # (matches DataOS's own 2-independent-runs bar; catches flaky-borderline goldens locally)
      CLAUDE_CONFIG_DIR="$lane" timeout 1500 /root/venv/bin/python3 /root/qc/tools/judge_emulate.py oracle "$t" \
        --runs 2 --corpus-root "$CORPUS" --out "$W/verify/$t.json" > "$W/verify/$t.log" 2>&1
      orc=$(/root/venv/bin/python3 -c "import json;print(json.load(open('$W/verify/$t.json')).get('total_reward'))" 2>/dev/null)
    fi
    if [ "$orc" = "1.0" ]; then
      touch "$W/done/$t"
      echo "DONE $t oracle=1.0 lane=$L $(date -u +%FT%TZ)" >> "$W/progress.txt"
    elif [ -z "$orc" ] || [ "$orc" = "None" ]; then
      mkdir -p "$W/unverified"; touch "$W/unverified/$t"   # locally unverifiable (/app path); decide later
      echo "UNVERIFIED $t rc=$rc oracle=$orc lane=$L $(date -u +%FT%TZ)" >> "$W/progress.txt"
    else
      echo "HELD $t rc=$rc oracle=$orc lane=$L $(date -u +%FT%TZ)" >> "$W/progress.txt"  # golden<1.0, retry next pass
    fi
  done < "$W/_queue.txt"
  echo "WORKER_DONE $L $(date -u +%FT%TZ)" >> "$W/progress.txt"
}

: > "$W/progress.txt"
echo "POOL_START $(date -u +%FT%TZ) tasks=$(wc -l <"$W/_queue.txt") lanes=${#LANES[@]} model=$MODEL tmo=$TMO already_done=$(ls "$W/done" 2>/dev/null | wc -l)" >> "$W/progress.txt"
for L in "${LANES[@]}"; do worker "$L" & done
wait
echo "POOL_DONE $(date -u +%FT%TZ) done=$(ls "$W/done" 2>/dev/null | wc -l)" >> "$W/progress.txt"
