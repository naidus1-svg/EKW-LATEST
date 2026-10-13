#!/usr/bin/env python3
"""Patch /root/qc/tools/watchdog.sh: benches that survive any launcher version.

1. LANE KILL sweep: parse the account's own 'resets H:MMpm (UTC)' text from the task log and
   write that epoch (+5 min) to lanes/<lane>.reset_at instead of a one-off +180 min mtime.
2. Every loop: for each lanes/*.reset_at still in the future, re-touch lanes/<lane>.benched
   with the CURRENT time (age 0, so the running launcher's age >= BENCH_MIN test keeps it);
   past the reset time, remove both files and alert once.
Writes watchdog.sh.new, then the caller mv's it over and kills the old watchdog (cron restarts).
"""

import re, sys

p = "/root/qc/tools/watchdog.sh"
s = open(p).read()

old_kill = '''      [ -n "$lane" ] && touch -d "+180 min" "lanes/$(basename "$lane").benched"
      alert "LANE KILL: $t parked by a refused call on $lane; un-parked, queued for retry, lane benched 180m"'''
new_kill = """      if [ -n "$lane" ]; then
        rs=$(tail -60 "stream-pipe/$t/pipeline.log" | grep -oiE 'resets [0-9]{1,2}(:[0-9]{2})? ?[ap]m' | tail -1 | sed 's/resets //')
        ep=$(date -u -d "today $rs" +%s 2>/dev/null); [ -z "$ep" ] && ep=$(( $(date +%s) + 10800 ))
        [ "$ep" -le "$(date +%s)" ] && ep=$(( ep + 86400 ))
        ep=$(( ep + 300 )); echo "$ep" > "lanes/$(basename "$lane").reset_at"; touch "lanes/$(basename "$lane").benched"
        alert "LANE KILL: $t parked by a refused call on $lane; un-parked, queued for retry, lane benched until $(date -u -d @$ep +%H:%M) UTC (account says resets $rs)"
      else
        alert "LANE KILL: $t parked by a refused call, lane unknown; un-parked, queued for retry"
      fi"""
assert old_kill in s, "kill block not found"
s = s.replace(old_kill, new_kill)

old_bench = '''  b=$(ls lanes/*.benched 2>/dev/null | xargs -r -n1 basename | sed 's/.benched//' | tr '\\n' ' ')
  [ -n "$b" ] && throttle bench 900 && alert "LANE benched (rate-limited): $b"'''
new_bench = '''  # ---- BENCH re-assert: a bench lives until the account's own reset time, whatever deletes the marker ----
  for ra in lanes/*.reset_at; do
    [ -f "$ra" ] || continue; ln=$(basename "$ra" .reset_at); ep=$(tr -dc 0-9 < "$ra")
    if [ -n "$ep" ] && [ "$(date +%s)" -lt "$ep" ]; then
      [ -f "lanes/$ln.benched" ] || { throttle "gone$ln" 600 && alert "LANE bench marker for $ln was deleted by something; re-asserted (reset $(date -u -d @$ep +%H:%M) UTC)"; }
      touch "lanes/$ln.benched"
    else rm -f "$ra" "lanes/$ln.benched"; alert "LANE back: $ln bench expired (reset time passed), lane live again"; fi
  done
  b=$(ls lanes/*.benched 2>/dev/null | xargs -r -n1 basename | sed 's/.benched//' | tr '\\n' ' ')
  [ -n "$b" ] && throttle bench 900 && alert "LANE benched (rate-limited): $b until $(for f in lanes/*.reset_at; do [ -f "$f" ] && printf '%s=%s ' "$(basename "$f" .reset_at)" "$(date -u -d @$(tr -dc 0-9 < "$f") +%H:%M)"; done)UTC"'''
assert old_bench in s, "bench block not found"
s = s.replace(old_bench, new_bench)
s = s.replace(
    "#   LANE benched  a Max account is rate-limited -> alert (launcher benches it for 60 min)",
    "#   LANE benched  a Max account is rate-limited -> benched until the account's own reset time\n#                 (lanes/<lane>.reset_at, re-asserted every loop; the launcher's own bench file is only 60 min)",
)
open(p + ".new", "w").write(s)
print("wrote", p + ".new", len(s), "bytes")
