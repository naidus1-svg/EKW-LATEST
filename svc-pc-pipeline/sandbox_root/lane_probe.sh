#!/usr/bin/env bash
# lane_probe.sh - test every Max lane with one tiny call and report which are alive vs session-dead.
set -u
LANES="q r m v w b c d e f g i j k l p t u"
tmp=/tmp/laneprobe; rm -rf "$tmp"; mkdir -p "$tmp"
for L in $LANES; do
  (
    o=$(CLAUDE_CONFIG_DIR=/root/.claude-$L timeout 75 claude -p --model sonnet --permission-mode dontAsk 'Reply with only the word OK' 2>&1 | tr '\n' ' ' | head -c 200)
    if echo "$o" | grep -qiE 'session limit|hit your|reached your|usage limit|429'; then st="DEAD_limit"
    elif echo "$o" | grep -qi 'ok'; then st="ALIVE"
    else st="DEAD_other"; fi
    echo "$L $st | ${o:0:90}" > "$tmp/$L"
  ) &
done
wait
echo "=== LANE STATUS $(date -u +%FT%TZ) ==="
alive=$(cat "$tmp"/* 2>/dev/null | grep -c ALIVE)
dlimit=$(cat "$tmp"/* 2>/dev/null | grep -c DEAD_limit)
dother=$(cat "$tmp"/* 2>/dev/null | grep -c DEAD_other)
echo "ALIVE=$alive  DEAD_limit=$dlimit  DEAD_other=$dother  (of 18)"
cat "$tmp"/* 2>/dev/null | sort
echo "=== THROUGHPUT ==="
echo "PASS total: $(ls /root/qc/fleet/verdicts/*.PASS 2>/dev/null | wc -l)"
echo "verdicts written last 30m: $(find /root/qc/fleet/verdicts -maxdepth 1 -type f -mmin -30 2>/dev/null | wc -l)"
echo "canonical review files last 30m: $(find /root/qc/fleet/wsreviews -maxdepth 1 -name '*.run*.json' -mmin -30 2>/dev/null | wc -l)"
