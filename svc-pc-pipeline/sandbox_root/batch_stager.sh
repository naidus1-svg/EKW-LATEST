#!/usr/bin/env bash
# batch_stager.sh - bundle gate-PASS tasks into <=480MB submission zips (task dirs at the archive
# root), from CURRENT bytes. Idempotent: never re-stages a task already recorded in fleet/staged.txt.
# Pure bash, zero LLM tokens. Run from cron, singleton via its own fd lock:
#   */5 * * * * bash /root/qc/batch_stager.sh >> /root/qc/fleet/stager.out 2>&1
set -u
cd /root/qc || exit 1
exec 8>/run/stager_int.lock
flock -n 8 || exit 0
FLEET=/root/qc/fleet
VERD=$FLEET/verdicts
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
OUT=$FLEET/batches
STAGED=$FLEET/staged.txt
MAXBYTES=$((480*1000*1000))
mkdir -p "$OUT"; touch "$STAGED"
passers=$(for f in "$VERD"/*.PASS; do [ -e "$f" ] && basename "$f" .PASS; done | sort)
[ -z "$passers" ] && { echo "$(date -u +%FT%TZ) no passers yet"; exit 0; }
new=$(comm -23 <(echo "$passers") <(sort "$STAGED"))
[ -z "$new" ] && { echo "$(date -u +%FT%TZ) no new passers (staged=$(wc -l < "$STAGED"))"; exit 0; }
n=$(( $(ls "$OUT"/batch-*.zip 2>/dev/null | wc -l) + 1 ))
zipf="$OUT/batch-$n.zip"; rm -f "$zipf"
cur=0; added=0
cd "$CORPUS" || exit 1
for t in $new; do
  [ -d "$t" ] || continue
  sz=$(du -sb "$t" 2>/dev/null | cut -f1); sz=${sz:-0}
  if [ "$added" -gt 0 ] && [ $((cur + sz)) -gt "$MAXBYTES" ]; then break; fi
  zip -rq "$zipf" "$t" -x "*/__pycache__/*" "*.pyc" "*.tmp" "*/_scratch*"
  echo "$t" >> "/root/qc/fleet/staged.txt"
  cur=$((cur + sz)); added=$((added+1))
done
cd /root/qc
if [ "$added" -gt 0 ]; then
  python3 -c "import zipfile,os
z=zipfile.ZipFile('$zipf')
assert z.testzip() is None, 'bad zip'
print('$(date -u +%FT%TZ) STAGED $zipf', len(z.namelist()),'entries', round(os.path.getsize('$zipf')/1e6,1),'MB', $added,'tasks')"
else
  rm -f "$zipf"; echo "$(date -u +%FT%TZ) nothing staged"
fi
