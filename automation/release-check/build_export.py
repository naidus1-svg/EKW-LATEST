#!/usr/bin/env python3
"""Build the release_check export folder from the downloader's per-task folders alone (no other DataOS file).

  python3 build_export.py DL_DIR OUT_EXPORT [--dl-copies DIR --map map.csv] [--tasks tasks.csv] [--spec 557]

  DL_DIR        downloader output: DL_DIR/<task_id>/{task.json, runs/<run>.json, runs/<run>.reward-details.json,
                verifications/<id>.json}
  --dl-copies   downloader output for QC copies (DIR/<copy_task_id>/...), with --map copy_task_id,orig_task_id
  --tasks       task_id,name,tab (copied to OUT_EXPORT/tasks.csv; without it names read "(name not in export)")

Writes OUT_EXPORT/: results.jsonl (one record per finished, not archived review on saved prompt SPEC), runs.csv,
nop.csv, map.csv, tasks.csv, runs/ (every run file), newruns/index.csv (every non-empty-answer run).
Review record keys use the ORIGINAL task id, as in the V11B1213 export.
"""
import argparse
import csv
import glob
import json
import os
import shutil


def tid(x):
    s = str(x).strip()
    return s[:-2] if s.endswith('.0') else s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('dl')
    ap.add_argument('out')
    ap.add_argument('--dl-copies', default=None)
    ap.add_argument('--map', default=None)
    ap.add_argument('--tasks', default=None)
    ap.add_argument('--spec', type=int, default=557)
    a = ap.parse_args(argv)
    cmap = {}
    if a.map:
        with open(a.map, newline='', encoding='utf-8-sig') as f:
            cmap = {tid(r['copy_task_id']): tid(r['orig_task_id']) for r in csv.DictReader(f)}
    orig_to_copy = {v: k for k, v in cmap.items()}
    os.makedirs(os.path.join(a.out, 'runs'), exist_ok=True)
    os.makedirs(os.path.join(a.out, 'newruns'), exist_ok=True)
    folders = []  # (dir, task id as in DataOS, original task id)
    for d in sorted(glob.glob(os.path.join(a.dl, '*', 'task.json'))):
        t = os.path.basename(os.path.dirname(d))
        folders.append((os.path.dirname(d), t, t))
    if a.dl_copies:
        for d in sorted(glob.glob(os.path.join(a.dl_copies, '*', 'task.json'))):
            c = os.path.basename(os.path.dirname(d))
            if c in cmap:
                folders.append((os.path.dirname(d), c, cmap[c]))
    reviews, idx, nop, runs_csv, seen_runs, agent_of = [], [], {}, {}, set(), {}
    for folder, t, o in folders:
        for p in sorted(glob.glob(os.path.join(folder, 'runs', '*[0-9].json'))):
            d = json.load(open(p, encoding='utf-8'))
            rid = tid(d['id'])
            agent_of[rid] = d.get('_agent', '')
            shutil.copy(p, os.path.join(a.out, 'runs', rid + '.json'))
            rd = p[:-5] + '.reward-details.json'
            if os.path.exists(rd):
                shutil.copy(rd, os.path.join(a.out, 'runs', rid + '.reward-details.json'))
            if d.get('_agent') == 'NOP':
                prev = nop.get(o)
                if prev is None or d.get('created_at', '') >= prev[0]:
                    nop[o] = (d.get('created_at', ''), d.get('aggregate_reward'))
                continue
            if rid in seen_runs:
                continue
            seen_runs.add(rid)
            idx.append(dict(run_id=rid, agent=d['_agent'], status=d.get('status', ''), reward=d.get('aggregate_reward'),
                            cost_usd='', task_id=t, orig_task_id=o, source='build_export',
                            detail='reward-details' if os.path.exists(rd) else 'none'))
        n = 0
        for p in sorted(glob.glob(os.path.join(folder, 'verifications', '*.json')), key=lambda x: int(os.path.basename(x)[:-5])):
            v = json.load(open(p, encoding='utf-8'))
            if (v.get('saved_prompt') or {}).get('id') != a.spec or v.get('status') != 'PASSED' or v.get('_archived'):
                continue
            n += 1
            turns = v.get('turns') or []
            tg = v.get('targets') or {}
            reviews.append(dict(
                key='%s-V%d' % (o, n), review_id=v['id'], status=v['status'], token_usage=v.get('token_usage'),
                targets_runs=[r['id'] for r in tg.get('evaluation_runs') or []],
                targets_tasks=[x['id'] for x in tg.get('tasks') or []],
                output=turns[-1].get('output') if turns else None))
    with open(os.path.join(a.out, 'results.jsonl'), 'w', encoding='utf-8') as f:
        for r in reviews:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    for r in reviews:
        for x in r['targets_runs']:
            runs_csv[tid(x)] = agent_of.get(tid(x), '')
    with open(os.path.join(a.out, 'runs.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['run_id', 'agent'])
        for k, v in runs_csv.items():
            if v:
                w.writerow([k, v])
    with open(os.path.join(a.out, 'nop.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['task_id', 'nop_reward'])
        for k, (_c, rew) in sorted(nop.items()):
            w.writerow([k, rew])
    with open(os.path.join(a.out, 'map.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['copy_task_id', 'orig_task_id'])
        for c, o in cmap.items():
            w.writerow([c, o])
    with open(os.path.join(a.out, 'newruns', 'index.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['run_id', 'agent', 'status', 'reward', 'cost_usd', 'task_id', 'orig_task_id', 'source', 'detail'])
        w.writeheader()
        w.writerows(idx)
    if a.tasks:
        shutil.copy(a.tasks, os.path.join(a.out, 'tasks.csv'))
    print('tasks %d, reviews %d, runs in index %d, nop rows %d, copies %d' % (len(folders), len(reviews), len(idx), len(nop), len(cmap)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
