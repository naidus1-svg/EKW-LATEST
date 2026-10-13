#!/bin/bash
# Sandbox-resident GO daemon. Waits for the GO signal, then launches the v7 pool detached. Survives the
# laptop closing (launch it under setsid/nohup). This is the whole point: nothing needs the laptop after
# arming - when DataOS accepts SVC-PC-16-1-0, the ONLY human touch is:
#     ssh <sandbox> 'touch /root/qc/_v7/GO'        (from any terminal, phone included)
# The queue (the reject pool) and every task's complete brief are armed ahead of time, so GO -> full run.
set -uo pipefail
QC=/root/qc; WORK="$QC/_v7"; GO="$WORK/GO"; QUEUE="$WORK/queue.txt"
mkdir -p "$WORK"
dlog(){ echo "$(date -u +%FT%TZ) DAEMON $*" >> "$WORK/daemon.log"; }
# Singleton: only one daemon may exist, however it was started (manual + cron race made two once). Two
# daemons would each launch a pool on GO and double-subscribe every lane's account.
exec 9>"$WORK/daemon.lock"
flock -n 9 || { dlog "another daemon holds the lock; exiting"; exit 0; }
# Idempotent: if the pool was already launched once (marker), never launch again. This makes the cron
# re-arm safe - a re-spawned daemon after a death/reboot won't re-fire a run that already happened.
[ -f "$WORK/LAUNCHED" ] && { dlog "LAUNCHED marker present; a run already fired; exiting"; exit 0; }
dlog "armed; polling for $GO (staged = $(grep -cve '^[[:space:]]*$' "$WORK/queue.staged.txt" 2>/dev/null || echo 0) tasks)"
while [ ! -f "$GO" ]; do
  [ -f "$WORK/daemon.stop" ] && { dlog "stop requested; exit without launch"; exit 0; }
  sleep 60
done
dlog "GO detected"
# The live queue only exists AFTER GO: promote the pre-staged pool now, so nothing can drain it early.
if [ ! -s "$QUEUE" ] && [ -s "$WORK/queue.staged.txt" ]; then
  cp "$WORK/queue.staged.txt" "$QUEUE"
  dlog "promoted queue.staged.txt -> queue.txt ($(grep -cve '^[[:space:]]*$' "$QUEUE") tasks)"
fi
[ -s "$QUEUE" ] || { dlog "GO but no queue (neither queue.txt nor queue.staged.txt); NOT launching"; exit 1; }
touch "$WORK/LAUNCHED"   # mark before launch so a crash mid-launch still won't double-fire on re-arm
(setsid nohup bash "$QC/svc_v7_pool.sh" >> "$WORK/pool.log" 2>&1 </dev/null &)
dlog "v7 pool launched detached; the run is now fully sandbox-resident"
