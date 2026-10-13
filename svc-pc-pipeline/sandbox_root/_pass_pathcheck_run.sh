#!/bin/bash
set -u
F=/root/qc/fleet
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
cd /root/ekwqc/deterministic-checks || exit 3
ids=$(ls "$F"/verdicts/*.PASS 2>/dev/null | xargs -n1 basename 2>/dev/null | sed 's/\.PASS$//' | tr '\n' ' ')
echo "PASS_COUNT=$(echo $ids | wc -w)"
export QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
export QC_SCRATCH_ROOT=/root/qc/checks_scratch/gate_pass
/root/venv/bin/python3 judge_input_gate.py $ids --root "$CORPUS" --out /root/qc/_pass_pathcheck.json 2>&1 | tail -3
/root/venv/bin/python3 -c "import json
d=json.load(open('/root/qc/_pass_pathcheck.json'))
bad=[r for r in d if r['status']=='fail']
sk=[r for r in d if r['status']=='skip']
er=[r for r in d if r['status']=='error']
print('CHECKED',len(d),'| PASS_WITH_PATH_DEFECT',len(bad),'| skip',len(sk),'| error',len(er))
for r in bad:
    print('  DEFECT',r['task_id'],r['blocking_entries'][:2])
for r in er:
    print('  ERROR',r['task_id'],r['blocking_entries'][:1])"
echo "DONE_PASS_PATHCHECK"
