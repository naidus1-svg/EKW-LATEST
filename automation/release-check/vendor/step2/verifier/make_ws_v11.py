"""Build verifier workspaces for EVERY fix-list item (no cap, no severity filter), 12 items per workspace.

Usage: python3 make_ws_v11.py PARSE_DIR PKGS_DIR WS_DIR [--nop nop.csv]
  PARSE_DIR  output of parse_reviews_v11.py (items.csv)
  PKGS_DIR   package folder(s), ':'-joined; layout <id>/<id>/ or <id>/
Writes WS_DIR/<task>__c<k>/ with instruction.md, inputs/, golden/, rubric/criteria.json, rubric/raw/,
evidence.json, items.json (ids F<n>) and items_index.csv (F id -> review_id, idx). Prints the count of tasks
with items but no package (their items stay UNVERIFIED and never count toward the verdict).
"""
import csv, glob, json, os, shutil, sys

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(H))
from pkg import pkg_root, criteria  # noqa: E402

CHUNK = 12


def build_one(ws, root, chunk, ev):
    if os.path.exists(ws):
        shutil.rmtree(ws)
    os.makedirs(f'{ws}/rubric/raw')
    shutil.copy(f'{root}/instruction.md', f'{ws}/instruction.md')
    iw = next((x for x in (f'{root}/environment/initial_workspace', f'{root}/environment/data') if os.path.isdir(x)), None)
    shutil.copytree(iw, f'{ws}/inputs') if iw else os.makedirs(f'{ws}/inputs')
    if os.path.isdir(f'{root}/solution'):
        shutil.copytree(f'{root}/solution', f'{ws}/golden')
    t = f'{root}/tests'
    for p in glob.glob(f'{t}/**/*', recursive=True):
        rel = os.path.relpath(p, t)
        if os.path.isfile(p) and ('lib' not in rel and 'pristine' not in rel and '_data' not in rel) \
                and p.endswith(('.toml', '.json', '.txt')):
            os.makedirs(os.path.dirname(f'{ws}/rubric/raw/{rel}'), exist_ok=True)
            shutil.copy(p, f'{ws}/rubric/raw/{rel}')
    crit = sorted(criteria(root), key=lambda c: -c['w'])
    json.dump([dict(id=c['id'], w=round(c['w'], 4), text=c['text']) for c in crit],
              open(f'{ws}/rubric/criteria.json', 'w'), indent=1)
    json.dump(ev, open(f'{ws}/evidence.json', 'w'), indent=1)
    json.dump([dict(id=f'F{k + 1}', text=x['text']) for k, x in enumerate(chunk)], open(f'{ws}/items.json', 'w'), indent=1)
    with open(f'{ws}/items_index.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['id', 'review_id', 'idx'])
        for k, x in enumerate(chunk):
            w.writerow([f'F{k + 1}', x['review_id'], x['idx']])


def item_text(r):
    return json.dumps({'type': r['type'], 'section': r['section'], 'criteria': r['criteria'].split('|'),
                       'weight_cost': r['weight'], 'reinstated': r['reinstated'] == '1',
                       'claim': r.get('claim', '')}, ensure_ascii=False)


def main(a):
    pdir, bases, wsd = a[0], a[1].split(':'), a[2]
    opt = {a[i]: a[i + 1] for i in range(3, len(a) - 1, 2)}
    nop = {}
    if '--nop' in opt:
        for r in csv.DictReader(open(opt['--nop'], encoding='utf-8-sig')):
            try:
                nop[r['task_id']] = float(r['nop_reward'])
            except ValueError:
                pass
    claims = {}
    if os.path.exists(f'{pdir}/claims.jsonl'):
        for l in open(f'{pdir}/claims.jsonl'):
            j = json.loads(l)
            claims[(j['review_id'], str(j['idx']))] = j['claim']
    by = {}
    for r in csv.DictReader(open(f'{pdir}/items.csv')):
        r['claim'] = claims.get((r['review_id'], r['idx']), '')
        by.setdefault(r['task_id'], []).append(dict(review_id=r['review_id'], idx=r['idx'], text=item_text(r)))
    os.makedirs(wsd, exist_ok=True)
    made = nopkg = 0
    for t, its in sorted(by.items()):
        root = pkg_root(t, bases)
        if not root:
            nopkg += 1
            print('NO PACKAGE', t)
            continue
        ev = {'empty_answer_run': {'reward': nop[t]}} if t in nop else {}
        for k in range(0, len(its), CHUNK):
            build_one(f'{wsd}/{t}__c{k // CHUNK + 1}', root, its[k:k + CHUNK], ev)
            made += 1
    print(f'workspaces {made}; items {sum(len(v) for v in by.values())}; tasks with items but no package {nopkg}')


if __name__ == '__main__':
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(sys.argv[1:])
