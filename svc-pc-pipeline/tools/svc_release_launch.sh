#!/bin/bash
# Release stuck tasks (claims -> claims_released, retries reset, back in queue) and launch them on free lanes.
# Usage: bash /root/qc/tools/svc_release_launch.sh "<lane lane ...>" TASK [TASK ...]   (tasks beyond the lane count are only released)
cd /root/qc/_v7 || exit 1
LANES=($1); shift
TS=$(date -u +%s); mkdir -p claims_released
i=0
for t in "$@"; do
  if ps -eo args | grep -q "[s]vc_v7_lane_runner.sh $t "; then echo "$t RUNNING, skip"; continue; fi
  if grep -qx "$t" do_not_touch.txt accepted.txt; then echo "$t frozen, skip"; continue; fi
  [ -d "claims/$t" ] && mv "claims/$t" "claims_released/$t.$TS"
  [ -f "retries/$t" ] && mv "retries/$t" "retries/$t.reset.$TS"
  grep -qx "$t" queue.txt || echo "$t" >> queue.txt
  echo "$(date -u +%FT%TZ) $t released for retry (regrade/verify/transient park; INFRA + formula-audit fixes deployed)" >> "logs/$t.log"
  if [ "$i" -lt "${#LANES[@]}" ] && mkdir "claims/$t" 2>/dev/null; then
    L=${LANES[$i]}; i=$((i+1))
    (setsid nohup bash /root/qc/svc_v7_lane_runner.sh "$t" "$L" > "logs/direct_$t.out" 2>&1 < /dev/null &)
    echo "$t launched on $L"
  else
    echo "$t released (queued)"
  fi
done
