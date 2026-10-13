"""Parse a DataOS review export (version 11, or older 431 / 472 / v10 output) into per-review, per-item,
per-drop and per-task run-coverage files. Built on build/step2/parse_reviews.py (v10).

Usage:
  python3 parse_reviews_v11.py REVIEWS.jsonl OUTDIR [--map copy_to_orig.csv] [--runs runs.csv]
    --map   CSV copy_task_id,orig_task_id: the review targeted a QC copy; results are reported on the original
    --runs  CSV run_id,agent (agent ORACLE, CODEX, TERMINUS-2, CLAUDE-CODE or NOP) to count which runs each
            review was given; without it the review's own runs_read field is used (v11 only)
Outputs in OUTDIR:
  reviews.csv   one row per record: task_id, review_id, status, parsed, schema, decision, n_items, n_reinstated,
                cost_usd, runs_solver, runs_nop, empty_run_reward
  items.csv     one row per fix-list item (reinstated drops included, flagged reinstated=1)
  drops.csv     one row per considered_not_reported entry, with kept=0/1 (kept=1: rule (c) reinstated it)
  coverage.csv  one row per task: reviews, solver runs and empty-answer runs among targets, NO_RUN flags
  parse_report.txt
"""
import csv, json, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v11lib import parse_record, task_of, num, as_obj, must_reinstate, crit_ids, extract_json, response_text  # noqa: E402

SOLVER_AGENTS = ('CODEX', 'TERMINUS-2', 'CLAUDE-CODE')


def load_jsonl(p):
    with open(p, encoding='utf-8') as fh:
        return [json.loads(l) for l in fh if l.strip()]


def read_map(p, a, b):
    return {str(r[a]): str(r[b]) for r in csv.DictReader(open(p, encoding='utf-8-sig'))} if p else {}


def write(path, rows, cols):
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def raw_items(rec):
    """Raw item dicts in the same order parse_record numbers them (fix_list, then reinstated drops; or findings)."""
    txt = response_text(rec)
    obj = extract_json(txt, 'schema') or extract_json(txt, 'verdict')
    if obj is not None and 'fix_list' in obj:
        a = [f for f in obj.get('fix_list') or [] if isinstance(f, dict)]
        return a + [d for d in obj.get('considered_not_reported') or [] if isinstance(d, dict) and must_reinstate(d)]
    obj = extract_json(txt, 'overall_verdict')
    return [f for f in (obj or {}).get('findings') or [] if isinstance(f, dict)]


def parse_export(recs, cmap=None, agents=None):
    revs, items, drops, claims = [], [], [], []
    cov = defaultdict(lambda: dict(reviews=0, parsed=0, solver=0, nop=0, oracle=0))
    for rec in recs:
        t = task_of(rec, cmap)
        rid = str(rec.get('review_id', rec.get('key', '')))
        tu = as_obj(rec.get('token_usage')) or {}
        cost = num(tu.get('cost_usd')) if isinstance(tu, dict) else None
        st = rec.get('status', '')
        p = parse_record(rec) if st != 'EXCEPTION' else None
        runs = [str(x) for x in (as_obj(rec.get('targets_runs')) or [])]
        if agents:
            ag = [agents.get(x, '?') for x in runs]
            ns, nn, no = sum(a in SOLVER_AGENTS for a in ag), sum(a == 'NOP' for a in ag), sum(a == 'ORACLE' for a in ag)
        elif p and isinstance(p.get('runs_read'), dict):
            rr = p['runs_read']
            ns = int(num(rr.get('Codex')) or 0) + int(num(rr.get('Terminus')) or 0)
            nn, no = int(num(rr.get('no-op')) or 0), int(num(rr.get('oracle')) or 0)
        else:
            ns = nn = no = None
        c = cov[t]
        c['reviews'] += 1
        c['parsed'] += int(p is not None)
        for k, v in (('solver', ns), ('nop', nn), ('oracle', no)):
            if v is not None:
                c[k] = max(c[k], v)
        revs.append(dict(task_id=t, review_id=rid, status=st, parsed=int(p is not None),
                         schema=p['schema'] if p else '', decision=p['decision'] if p else '',
                         n_items=len(p['items']) if p else '', n_reinstated=sum(i['reinstated'] for i in p['items']) if p else '',
                         cost_usd='' if cost is None else round(cost, 4), runs_solver='' if ns is None else ns,
                         runs_nop='' if nn is None else nn,
                         empty_run_reward='' if not p or p.get('empty_run_reward') is None else p['empty_run_reward'],
                         all_runs_passed='' if not p else p.get('all_runs_passed')))
        if not p:
            continue
        raw = raw_items(rec)
        for it in p['items']:
            if it['idx'] < len(raw):
                claims.append(dict(review_id=rid, idx=it['idx'], claim=json.dumps(raw[it['idx']], ensure_ascii=False)[:6000]))
            items.append(dict(task_id=t, review_id=rid, idx=it['idx'], section=it['section'], type=it['type'],
                              severity_stated=it['severity_stated'], weight=it['weight'],
                              criteria='|'.join(it['criteria']), reinstated=int(it['reinstated'])))
        for j, d in enumerate(p['drops']):
            drops.append(dict(task_id=t, review_id=rid, j=j, type=d.get('type'), reason=d.get('reason'),
                              criteria='|'.join(crit_ids(d.get('criteria'))), quoted_run=d.get('quoted_run'),
                              accepted_by_criterion=d.get('accepted_by_criterion'), kept=int(must_reinstate(d))))
    covrows = []
    for t, c in sorted(cov.items()):
        flags = []
        if c['parsed'] == 0:
            flags.append('NO_REVIEW')
        if c['solver'] == 0:
            flags.append('NO_SOLVER_RUN')
        if c['nop'] == 0:
            flags.append('NO_EMPTY_RUN')
        covrows.append(dict(task_id=t, **c, flags='|'.join(flags)))
    return revs, items, drops, covrows, claims


def main(a):
    src, out = a[0], a[1]
    opt = {a[i]: a[i + 1] for i in range(2, len(a) - 1, 2)}
    os.makedirs(out, exist_ok=True)
    cmap = read_map(opt.get('--map'), 'copy_task_id', 'orig_task_id')
    agents = read_map(opt.get('--runs'), 'run_id', 'agent')
    recs = load_jsonl(src)
    revs, items, drops, cov, claims = parse_export(recs, cmap, agents)
    with open(f'{out}/claims.jsonl', 'w') as fh:
        for c in claims:
            fh.write(json.dumps(c, ensure_ascii=False) + '\n')
    write(f'{out}/reviews.csv', revs, ['task_id', 'review_id', 'status', 'parsed', 'schema', 'decision', 'n_items',
                                        'n_reinstated', 'cost_usd', 'runs_solver', 'runs_nop', 'empty_run_reward', 'all_runs_passed'])
    write(f'{out}/items.csv', items, ['task_id', 'review_id', 'idx', 'section', 'type', 'severity_stated', 'weight',
                                      'criteria', 'reinstated'])
    write(f'{out}/drops.csv', drops, ['task_id', 'review_id', 'j', 'type', 'reason', 'criteria', 'quoted_run',
                                      'accepted_by_criterion', 'kept'])
    write(f'{out}/coverage.csv', cov, ['task_id', 'reviews', 'parsed', 'solver', 'nop', 'oracle', 'flags'])
    costs = [r['cost_usd'] for r in revs if r['cost_usd'] != '']
    rep = (f"records {len(recs)}; parsed {sum(r['parsed'] for r in revs)}; tasks {len(cov)}; items {len(items)} "
           f"(reinstated {sum(i['reinstated'] for i in items)}); drops {len(drops)} (kept by rule c {sum(d['kept'] for d in drops)}); "
           f"tasks flagged NO_SOLVER_RUN {sum('NO_SOLVER_RUN' in c['flags'] for c in cov)}, NO_EMPTY_RUN {sum('NO_EMPTY_RUN' in c['flags'] for c in cov)}; "
           f"cost_usd total {sum(costs):.2f} over {len(costs)} records\n")
    open(f'{out}/parse_report.txt', 'w').write(rep)
    print(rep, end='')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1:])
