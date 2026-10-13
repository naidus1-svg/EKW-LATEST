#!/usr/bin/env bash
# after_boot.sh - bring the gate-v2 pipeline back after a VM stop/start (resize). Idempotent.
# Run: bash /root/qc/tools/after_boot.sh   (the laptop session runs it as soon as ssh answers)
cd /root/qc || exit 1
echo "== $(date -u +%FT%TZ) after_boot on $(nproc) cores, $(free -g | awk '/Mem/{print $2}')G, machine $(curl -s -m 3 -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/machine-type | sed 's#.*/##')"
# 1. checkpoints for tasks that ran on the pre-checkpoint script: never re-spend a finished model call
python3 tools/seed_checkpoints.py | tail -1
# 2. lanes: nothing to do, credentials are on disk; clear stale bench files whose reset time has passed
shopt -s dotglob; now=$(date +%s)
for ra in lanes/*.reset_at; do [ -f "$ra" ] || continue; [ "$(tr -dc 0-9 < "$ra")" -lt "$now" ] && rm -f "$ra" "lanes/$(basename "$ra" .reset_at).benched"; done
# 3. every in-flight task at stop time is re-queued: the launcher skips DONE/PARKED at once, resumes the rest from STATE
for d in stream-pipe/SVC-PC-*; do t=$(basename "$d"); [ -f "$d/PARKED.md" ] && continue; grep -q '^DONE$' "$d/STATE" 2>/dev/null && continue; grep -qx "$t" stream-pipe/RETRY.txt 2>/dev/null || echo "$t" >> stream-pipe/RETRY.txt; done
echo "RETRY.txt now $(sort -u stream-pipe/RETRY.txt | wc -l) tasks; QUEUE.txt $(sort -u stream-pipe/QUEUE.txt | wc -l)"
# 3b. tasks parked by a failed model call with no account-limit text (network loss, CLI reinstall, missing file) are not verdicts: re-queue them
np=0; for pk in stream-pipe/SVC-PC-*/PARKED.md; do [ -f "$pk" ] || continue; tail -1 "$pk" | grep -q 'call failed' || continue; d=$(dirname "$pk"); t=$(basename "$d")
  grep -B25 'PARKED:' "$d/pipeline.log" 2>/dev/null | tail -26 | grep -qiE 'usage limit|session limit|weekly limit|hit your [a-z ]*limit' && continue
  rm -f "$pk"; grep -qx "$t" stream-pipe/RETRY.txt || echo "$t" >> stream-pipe/RETRY.txt; np=$((np+1)); done; echo "re-queued $np call-failed parks (no limit text)"
# 3c. make this script run on every boot
crontab -l 2>/dev/null | grep -q 'after_boot.sh' || (crontab -l 2>/dev/null; echo "@reboot sleep 60 && bash /root/qc/tools/after_boot.sh >> /root/qc/after_boot.out 2>&1") | crontab -
# 4. relaunch: watchdog (cron also does this), launcher, solver batch
pgrep -f 'tools/watchdog.sh' >/dev/null || { rm -f watchdog.pid; nohup bash tools/watchdog.sh >> watchdog.out 2>&1 & }
pgrep -f 'tools/pipe_batch.sh' >/dev/null || nohup bash tools/pipe_batch.sh > stream-pipe/PIPE.nohup.log 2>&1 &
pgrep -f 'tools/solver_batch.sh' >/dev/null || nohup bash tools/solver_batch.sh --go > runs/BATCH.nohup.log 2>&1 &
sleep 5
echo "watchdog=$(pgrep -fc 'tools/watchdog.sh') launcher=$(pgrep -fc 'tools/pipe_batch.sh') solver=$(pgrep -fc 'tools/solver_batch.sh')"
# 5. metadata classifier: finish the generic ones (idempotent, only touches tasks still generic)
pgrep -f metadata_classify_glm.py >/dev/null || nohup python3 tools/metadata_classify_glm.py --only-generic --workers 3 >> _prompts/metadata_classify_glm.log 2>&1 &
# 6. lane G engineering session: resume in tmux pipe2 (session id recorded at stop time)
if [ -s lanes/PIPE2_SESSION ] && ! tmux has-session -t pipe2 2>/dev/null; then
  tmux new-session -d -s pipe2 -c /root/qc
  tmux send-keys -t pipe2 "CLAUDE_CONFIG_DIR=/root/.claude-g claude --resume $(cat lanes/PIPE2_SESSION)" Enter
  echo "pipe2 resume sent for session $(cat lanes/PIPE2_SESSION); check the pane for a trust prompt"
fi
echo "$(date -u +%FT%TZ) AFTER_BOOT done" | tee -a ALERTS.log
