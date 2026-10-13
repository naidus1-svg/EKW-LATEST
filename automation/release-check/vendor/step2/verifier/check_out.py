"""check_out.py <run_dir> <log> <out_dir>: accept verdicts.json only if it parses and covers exactly the
item ids with CONFIRMED / REFUTED / UNCLEAR; copy it plus cost to out_dir. Exit 1 otherwise."""
import json, os, sys

r, log, o = sys.argv[1:4]
want = {f['id'] for f in json.load(open(f'{r}/items.json'))}
try:
    v = json.load(open(f'{r}/verdicts.json'))['verdicts']
    ok = {x['id'] for x in v} == want and all(x.get('verdict') in ('CONFIRMED', 'REFUTED', 'UNCLEAR') for x in v)
except Exception as e:
    print('bad', e)
    ok = False
if not ok:
    sys.exit(1)
cost = None
for line in open(log):
    try:
        j = json.loads(line)
        if j.get('type') == 'result':
            cost = j.get('total_cost_usd')
    except Exception:
        pass
os.makedirs(o, exist_ok=True)
json.dump({'verdicts': v, 'cost_usd': cost, 'log': log}, open(f'{o}/verdicts.json', 'w'), indent=1)
