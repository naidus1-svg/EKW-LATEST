#!/usr/bin/env bash
# fixes_evidence.sh - is each of today's fixes actually doing something? Zero tokens.
# Run: bash /root/qc/tools/fixes_evidence.sh
cd /root/qc || exit 1
echo "FIX EVIDENCE   $(date -u +%FT%TZ)"
echo "VM: $(curl -s -m 3 -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/machine-type | sed 's#.*/##')  project=$(curl -s -m 3 -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/project/project-id)  zone=$(curl -s -m 3 -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/zone | sed 's#.*/##')  host=$(hostname)"
echo
r3=$(grep -l 'fix round 3\|CR (round 3' stream-pipe/SVC-PC-*/pipeline.log 2>/dev/null | wc -l)
echo "4 fix rounds     : tasks that reached round 3 or 4 = $r3; re-armed and waiting = $(ls stream-pipe/*/PARKED.after2.md 2>/dev/null | wc -l)"
echo "checkpoints      : reuse lines (calls saved) = $(grep -h 'checkpoint present' stream-pipe/SVC-PC-*/pipeline.log 2>/dev/null | wc -l); tasks on the new script = $(grep -l 'max 4' stream-pipe/SVC-PC-*/pipeline.log 2>/dev/null | wc -l)"
echo "lane benching    : refused calls caught = $(grep -c 'LANE KILL' ALERTS.log 2>/dev/null); tasks queued for retry = $(sort -u stream-pipe/RETRY.txt 2>/dev/null | wc -l); benched now: $(ls -A lanes/ | grep benched 2>/dev/null | xargs -r -n1 basename | sed 's/.benched//' | tr '\n' ' ')"
echo "xlsx/docx applier: binary edits applied = $(cat stream-pipe/SVC-PC-*/FIX-LOG.md 2>/dev/null | grep -c 'set_xlsx_cell.*APPLIED\|replace_docx_text.*APPLIED'); text edits applied = $(cat stream-pipe/SVC-PC-*/FIX-LOG.md 2>/dev/null | grep -c 'replace_literal.*APPLIED\|append_text.*APPLIED')"
echo "watchdog         : GLM kills = $(grep -c 'GLM  KILL' ALERTS.log), dup/orphan kills = $(grep -c 'orphan\|duplicate' ALERTS.log), stale kills = $(grep -c 'stale' ALERTS.log), running = $(pgrep -fc 'tools/watchdog.sh')"
echo "GLM              : clean runs this batch = $(awk '/RESTART 7/{f=1;next} f && / FINISH /' runs/BATCH.log | grep -c 'exit=0'), failed = $(awk '/RESTART 7/{f=1;next} f && / FINISH /' runs/BATCH.log | grep -c 'exit=[^0]'), in flight = $(pgrep -fc 'timeout 3600 env IS_SANDBOX=1')"
python3 - <<'PY'
import json,glob,os,statistics
drops=[]
for d in glob.glob('/root/qc/stream-pipe/SVC-PC-*'):
    a=os.path.join(d,'CR.round1.before-fix.json'); b=os.path.join(d,'CR.json')
    if os.path.exists(a) and os.path.exists(b):
        try:
            m=lambda f: sum(1 for x in json.load(open(f)).get('findings',[]) if x.get('severity')=='major')
            drops.append((m(a),m(b)))
        except Exception: pass
if drops:
    print(f"majors trend     : {len(drops)} tasks with 2+ reviews: first review median {statistics.median(x[0] for x in drops):.0f} majors, latest median {statistics.median(x[1] for x in drops):.0f}; at zero majors now: {sum(1 for x in drops if x[1]==0)}")
PY
echo "outcomes         : DONE=$(grep -c ' DONE ' stream-pipe/PIPE.log) zips=$(ls out/pipe/*.zip 2>/dev/null | wc -l) parked=$(ls stream-pipe/*/PARKED.md 2>/dev/null | wc -l) in flight=$(pgrep -fc gate_task.sh) load=$(cut -d' ' -f1 /proc/loadavg) live lanes=$(for d in /root/.claude /root/.claude-*; do [ -f $d/.credentials.json ] || continue; [ -f lanes/$(basename $d).benched ] && continue; echo x; done | wc -l)"
echo
echo "lane G (zip-gate fix) latest:"; tmux capture-pane -p -t pipe2 -S -40 2>/dev/null | grep -v "^$" | grep -vE "^[[:space:]]|^-|^>|Tip:|auto mode|^❯" | tail -3 | cut -c1-150
