#!/bin/bash
# PRECISION test: do Fable/Opus raise 1.4/1.5 on DataOS-PASS tasks (which severity-recalibration
# would then falsely reject)? 6 batch27 passes (staged from with_runs rev_*/task_files/) + 2 batch15
# passes (already at _step0/corpus). Reviewed by fable AND opus, workspace mode, on the graded bytes.
set -u
W=/root/qc/_prectest
CORPUS=$W/corpus
rm -rf "$CORPUS" "$W/out" "$W/ws" "$W/runs" "$W/pipe"; mkdir -p "$CORPUS" "$W/out" "$W/ws" "$W/runs" "$W/pipe"
/root/venv/bin/python3 - <<'PY'
import zipfile, os
Z="/root/qc/_prectest/bacth_of_27_with_runs.zip"; OUT="/root/qc/_prectest/corpus"
PASSES=["SVC-PC-11-4-0","SVC-PC-2-6-0","SVC-PC-20-8-0","SVC-PC-21-4-0","SVC-PC-38-1-0","SVC-PC-73-2-0"]
z=zipfile.ZipFile(Z); names=z.namelist()
for t in PASSES:
    rev=sorted({n.split('/')[1] for n in names if n.startswith(t+'/') and len(n.split('/'))>1})[0]
    pre=f"{t}/{rev}/task_files/"
    n=0
    for name in names:
        if name.startswith(pre) and not name.endswith('/'):
            rel=name[len(pre):]; d=os.path.join(OUT,t,rel)
            os.makedirs(os.path.dirname(d),exist_ok=True); open(d,'wb').write(z.read(name)); n+=1
    print("staged",t,n,"files")
PY
for t in SVC-PC-12-1-0 SVC-PC-5-2-0; do cp -a /root/qc/_step0/corpus/$t "$CORPUS/$t" 2>/dev/null && echo "copied $t"; done
RWR=/root/qc/tools/run_workspace_review.py
TASKS="SVC-PC-11-4-0 SVC-PC-2-6-0 SVC-PC-20-8-0 SVC-PC-21-4-0 SVC-PC-38-1-0 SVC-PC-73-2-0 SVC-PC-12-1-0 SVC-PC-5-2-0"
LANES=(q r m v w c e f g i j k l p t u)
idx=0
for t in $TASKS; do
  for rev in fable opus; do
    lane="/root/.claude-${LANES[$((idx % ${#LANES[@]}))]}"; idx=$((idx+1))
    ( CLAUDE_CONFIG_DIR="$lane" timeout 3000 python3 "$RWR" --task "$t" --corpus-root "$CORPUS" \
        --workspace-root "$W/ws/$t.$rev" --runs-root "$W/runs" --pipe-dir "$W/pipe/$t.$rev" \
        --out "$W/out/$t.$rev.json" --stats-out "$W/out/$t.$rev.stats.json" --reviewer "$rev" --timeout 2700 \
        > "$W/out/$t.$rev.log" 2>&1
      echo "done $t $rev rc=$? lane=$(basename $lane)" >> "$W/progress.txt" ) &
  done
done
wait
echo "ALL_DONE $(date -u +%FT%TZ)" >> "$W/progress.txt"
