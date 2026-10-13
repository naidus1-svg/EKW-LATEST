"""Step 2 version 11 pass rule: per-task VERDICT plus the FIX LIST, from parsed reviews, verifier verdicts,
the empty-answer run and the package weights.

Usage: python3 pass_rule_v11.py PARSE_DIR --out OUT_DIR [--verifier VERIFIER_OUT_DIR] [--nop nop.csv]
           [--pkgs PKGS_DIR[:PKGS_DIR...]] [--weights weights.csv] [--tabs tabs.csv] [--t1t3 report|blocking]
  PARSE_DIR   output of parse_reviews_v11.py (reviews.csv, items.csv, coverage.csv)
  --verifier  output of verifier/run_verifier.sh (<task>__c<k>/verdicts.json and items_index.csv)
  --nop       CSV task_id,nop_reward (reward of the empty-answer run; the copy's run if the original has none)
  --pkgs      package folders: criteria weights come from the package (tests/), tab from task.toml
  --weights   CSV task_id,crit,w instead of --pkgs (offline use); --tabs CSV task_id,tab overrides task.toml
  --t1t3      'report' (default while runs R5 and R6 are pending): items with section T1 or T3 go on the fix list
              but never count toward the verdict; 'blocking': they count like CORE items once confirmed

VERDICT (REJECT / PASS / INCOMPLETE):
  REJECT when the empty-answer run earned reward above 0, or at least one item is CONFIRMED by the verifier and
  MATERIAL under work/x6d/RULE_V3.txt at its confirmed weight and criteria (EKW: 0.05 or more; SVC: one of the
  3 heaviest criteria, ties count). One review is enough (any of N, as prompt 431's any-reject).
  INCOMPLETE when not rejected and the task has no parsed review, no solver run among the targets, or no
  empty-answer evidence (no NOP run among targets and no --nop value). INCOMPLETE is not a pass: the operator
  adds the missing run (the QC copy's run if the original has none) and reruns.
  PASS otherwise.
  Without --verifier the rule is reported as 'v11_noverifier' (every item counts at its stated weight).
FIX LIST: every item of every review, with the verifier verdict. Destination: CONFIRMED -> author (fix list);
  UNCLEAR or no verdict -> manager; REFUTED -> log only. No weight floor anywhere.
Writes OUT_DIR/verdicts.csv, fixlist.csv, flags.csv. Prints one line per task.
"""
import csv, json, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v11lib import decide_task, is_material, num  # noqa: E402
from pkg import pkg_root, criteria, tab as pkg_tab  # noqa: E402


def read(p):
    return list(csv.DictReader(open(p, encoding='utf-8-sig'))) if p and os.path.exists(p) else []


def verifier_map(d):
    m = {}
    if not d or not os.path.isdir(d):
        return m
    for w in os.listdir(d):
        vj, ix = f'{d}/{w}/verdicts.json', f'{d}/{w}/items_index.csv'
        if not (os.path.exists(vj) and os.path.exists(ix)):
            continue
        idx = {r['id']: (r['review_id'], int(r['idx'])) for r in read(ix)}
        for v in json.load(open(vj)).get('verdicts', []):
            if v.get('id') in idx:
                m[idx[v['id']]] = (str(v.get('verdict', 'UNCLEAR')).upper(), num(v.get('weight_confirmed')),
                                   [str(c) for c in v.get('criteria') or []])
    return m


def run(pdir, out, ver_dir=None, nop_csv=None, pkgs=None, weights_csv=None, tabs_csv=None, t1t3='report'):
    reviews, items, cov = read(f'{pdir}/reviews.csv'), read(f'{pdir}/items.csv'), {r['task_id']: r for r in read(f'{pdir}/coverage.csv')}
    nop = {}
    for r in read(nop_csv):
        v = num(r.get('nop_reward'))
        if v is not None:
            nop[r['task_id']] = v
    W = defaultdict(dict)
    for r in read(weights_csv):
        W[r['task_id']][r['crit']] = float(r['w'])
    tabs = {r['task_id']: r['tab'].upper() for r in read(tabs_csv)}
    bases = pkgs.split(':') if pkgs else []
    have_ver = ver_dir is not None
    vm = verifier_map(ver_dir) if have_ver else None
    by = defaultdict(list)
    for it in items:
        it['idx'] = int(it['idx'])
        it['weight'] = num(it['weight'])
        it['criteria'] = [c for c in it['criteria'].split('|') if c]
        by[it['task_id']].append(it)
    nrev = defaultdict(int)
    for r in reviews:
        nrev[r['task_id']] += int(r['parsed'] == '1')
    tasks = sorted(set(nrev) | set(cov))
    vrows, frows, flags = [], [], []
    for t in tasks:
        root = pkg_root(t, bases) if bases else None
        w = W.get(t) or ({c['id']: c['w'] for c in criteria(root)} if root else {})
        tb = tabs.get(t) or (pkg_tab(root) if root else 'EKW')
        its = by.get(t, [])
        gate_items = [i for i in its if t1t3 == 'blocking' or i['section'] not in ('T1', 'T3')]
        c = cov.get(t, {})
        runs = None
        if c and c.get('solver', '') != '':
            runs = {'solver': int(c['solver'] or 0), 'nop': int(c['nop'] or 0)}
        er = nop.get(t)
        if er is None:  # the review's own reading of the empty run (v11 field), when the operator gave no nop.csv
            vals = [num(r.get('empty_run_reward')) for r in reviews if r['task_id'] == t]
            vals = [v for v in vals if v is not None]
            er = max(vals) if vals else None
        v_nov, why_nov, cnt_nov = decide_task(gate_items, tb, w, er, None, runs, nrev[t])
        if have_ver:
            v, why, cnt = decide_task(gate_items, tb, w, er, vm, runs, nrev[t])
        else:
            v, why, cnt = v_nov, why_nov, cnt_nov
        counted = {(i['review_id'], i['idx']) for i in cnt}
        nconf = nref = nunc = nnone = 0
        for i in its:
            vv = vm.get((str(i['review_id']), i['idx'])) if have_ver else None
            verdict = vv[0] if vv else ('NOT_RUN' if not have_ver else 'NONE')
            nconf += verdict == 'CONFIRMED'
            nref += verdict == 'REFUTED'
            nunc += verdict == 'UNCLEAR'
            nnone += verdict in ('NONE', 'NOT_RUN')
            wc = vv[1] if vv and vv[1] is not None else i['weight']
            cr = (vv[2] if vv and vv[2] else i['criteria'])
            dest = {'CONFIRMED': 'author', 'REFUTED': 'log'}.get(verdict, 'manager')
            frows.append(dict(task_id=t, review_id=i['review_id'], idx=i['idx'], section=i['section'], type=i['type'],
                              severity_stated=i['severity_stated'], weight_stated=i['weight'],
                              criteria='|'.join(i['criteria'])[:300], reinstated=i.get('reinstated', '0'),
                              verifier=verdict, weight_confirmed='' if not vv else vv[1],
                              material=int(is_material(wc, cr, tb, w)), counted_in_verdict=int((i['review_id'], i['idx']) in counted),
                              destination=dest))
        vrows.append(dict(task_id=t, tab=tb, verdict=v, reason=' + '.join(why), n_reviews=nrev[t], n_items=len(its),
                          n_counted=len(cnt), n_confirmed=nconf if have_ver else '', n_refuted=nref if have_ver else '',
                          n_unclear=nunc if have_ver else '', n_unverified=nnone, empty_reward='' if er is None else er,
                          coverage_flags=c.get('flags', ''), verdict_noverifier=v_nov,
                          weights_known=int(bool(w))))
        fl = {'v11_noverifier': v_nov == 'REJECT', 'v11_fixlist_nonempty': bool(its)}
        if have_ver:
            fl['v11'] = v == 'REJECT'
        for k, x in fl.items():
            flags.append(dict(task_id=t, rule=k, flagged=int(x)))
    os.makedirs(out, exist_ok=True)
    for name, data in (('verdicts.csv', vrows), ('fixlist.csv', frows), ('flags.csv', flags)):
        with open(f'{out}/{name}', 'w', newline='') as fh:
            if data:
                wr = csv.DictWriter(fh, fieldnames=list(data[0].keys()))
                wr.writeheader()
                wr.writerows(data)
    return vrows, frows, flags


def main(a):
    pdir = a[0]
    opt = {a[i]: a[i + 1] for i in range(1, len(a) - 1, 2)}
    vrows, frows, _ = run(pdir, opt.get('--out', pdir), opt.get('--verifier'), opt.get('--nop'), opt.get('--pkgs'),
                          opt.get('--weights'), opt.get('--tabs'), opt.get('--t1t3', 'report'))
    for r in vrows:
        top = [f for f in frows if f['task_id'] == r['task_id'] and f['counted_in_verdict']][:4]
        print(f"{r['task_id']}\t{r['verdict']}\t{r['reason']}\t" +
              '; '.join(f"{f['type']} {f['criteria'][:60]} w={f['weight_stated']}" for f in top))
    n = defaultdict(int)
    for r in vrows:
        n[r['verdict']] += 1
    dest = defaultdict(int)
    for f in frows:
        dest[f['destination']] += 1
    print(f"tasks {len(vrows)}; " + '; '.join(f'{k} {v}' for k, v in sorted(n.items())) +
          f"; fix-list items {len(frows)} (author {dest['author']}, manager {dest['manager']}, log {dest['log']})")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
