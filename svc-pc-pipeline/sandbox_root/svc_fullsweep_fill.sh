#!/bin/bash
# Full-coverage-sweep fixer for UNGRADED pipeline tasks (no DataOS findings yet).
# Fills idle lanes: one agent per task runs the complete coverage sweep from a shared brief template.
# Separate working dir (_fillfix) and a lane set that EXCLUDES the round-3 lanes (q,r) and capped t,
# so it never collides with a concurrent svc_dataos_overnight.sh run.
#
#   $1 = task-list file (one SVC-PC-<t> id per line; CRLF tolerated, blanks dropped)
#   $2 = brief template file with a literal {TASK} placeholder
#   $3 = fixer model (default sonnet; the plan's first-pass tier, Opus reserved for graded round-2/3)
#
# Launch DETACHED (SSH drops under load):
#   (setsid nohup bash /root/qc/svc_fullsweep_fill.sh /root/qc/_fill.txt /root/qc/_fullsweep_brief.md sonnet \
#      >/root/qc/_fillfix.log 2>&1 </dev/null &); exit 0
# Poll: tail -5 /root/qc/_fillfix/progress.txt
set -u
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
LIST="$1"; BRIEF="$2"; MODEL="${3:-sonnet}"
W=/root/qc/_fillfix
mkdir -p "$W/logs" "$W/snap" "$W/briefs"
export QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
# 13 lanes: exclude q,r (round-3 svc_dataos_fix.sh) and g (weekly-capped, resets Sep 23). t recovered.
LANES=(m v w c e f i j k l p t u)
MAXJ=13
tr -d '\r' < "$LIST" | grep . > "$W/_list_lf.txt"
N=$(wc -l < "$W/_list_lf.txt")
: > "$W/progress.txt"
echo "FILL_START $(date -u +%FT%TZ) tasks=$N model=$MODEL lanes=${#LANES[@]}" >> "$W/progress.txt"
idx=0
while read -r t; do
  [ -z "$t" ] && continue
  [ -d "$CORPUS/$t" ] || { echo "skip $t (not in corpus)" >> "$W/progress.txt"; continue; }
  lane="/root/.claude-${LANES[$((idx % ${#LANES[@]}))]}"
  idx=$((idx + 1))
  sed "s/{TASK}/$t/g" "$BRIEF" > "$W/briefs/$t.md"
  (
    # preserve the FIRST (pristine) pre-edit snapshot across relaunches; never overwrite it
    if [ ! -d "$W/snap/$t" ]; then
      mkdir -p "$W/snap/$t"
      cp -a "$CORPUS/$t/tests" "$W/snap/$t/tests" 2>/dev/null
      cp -a "$CORPUS/$t/solution" "$W/snap/$t/solution" 2>/dev/null
    fi
    cd "$CORPUS/$t" && CLAUDE_CONFIG_DIR="$lane" timeout 2700 claude -p "$(cat "$W/briefs/$t.md")" \
      --model "$MODEL" --permission-mode dontAsk --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
      --output-format text > "$W/logs/$t.fix.log" 2>&1
    echo "fixed $t rc=$? lane=$lane model=$MODEL $(date -u +%FT%TZ)" >> "$W/progress.txt"
  ) &
  while [ "$(jobs -r | wc -l)" -ge "$MAXJ" ]; do sleep 3; done
done < "$W/_list_lf.txt"
wait
echo "FILL_DONE $(date -u +%FT%TZ) fixed=$(grep -c '^fixed ' "$W/progress.txt")" >> "$W/progress.txt"
# Verify (oracle+static) is a SEPARATE step run after round-3's gate frees /root/qc/_preship.
