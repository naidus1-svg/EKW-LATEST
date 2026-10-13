#!/bin/bash
# Cron re-arm for the v7 scale-up daemon: makes the setup survive a daemon death or a sandbox reboot
# (the daemon itself is just a nohup process; without this a reboot would silently un-arm everything).
# Installed as: * * * * * /root/qc/svc_v7_rearm.sh   (kept as a script, not an inline crontab line, to
# avoid the nested-quote breakage that bit an inline attempt).
# Launches the daemon ONLY IF it is not already running, has not already fired a run (LAUNCHED marker),
# and has not been deliberately stopped (daemon.stop). All three guards so cron never double-fires.
W=/root/qc/_v7
pgrep -f '[s]vc_scaleup_daemon.sh' >/dev/null && exit 0
[ -f "$W/LAUNCHED" ]   && exit 0
[ -f "$W/daemon.stop" ] && exit 0
(setsid nohup bash /root/qc/svc_scaleup_daemon.sh >/dev/null 2>&1 </dev/null &)
