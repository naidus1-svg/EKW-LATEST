#!/bin/bash
# Stop the v7 daemon + pool + in-flight rebuilds cleanly. Bracketed patterns so pkill never matches this
# shell itself (the self-match incident). Kill and relaunch are NEVER combined in one ssh (the kill spikes
# load and drops the ssh before relaunch); this only stops.
touch /root/qc/_v7/daemon.stop
pkill -f '[s]vc_scaleup_daemon.sh' 2>/dev/null
pkill -f '[s]vc_v7_pool.sh'        2>/dev/null
pkill -f '[s]vc_v7_lane_runner.sh' 2>/dev/null
pkill -9 -f '[t]imeout [0-9]* claude -p' 2>/dev/null  # every lane agent: rebuild (3000), fix + verify (1800).
                                                       # Was '3600' only, which matched none of the runner's
                                                       # agents and would orphan them mid-edit (fixed 2026-09-22).
pkill -9 -f '[j]udge_emulate.py oracle' 2>/dev/null  # in-flight oracles
echo "v7 stop signalled: daemon.stop set; pool/runner/rebuild/oracle killed"
echo "to resume: rm /root/qc/_v7/daemon.stop, then relaunch the daemon in a SEPARATE ssh call"
