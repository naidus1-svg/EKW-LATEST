#!/usr/bin/env python3
"""Step 3 batch gate, version 4: decide per task SEND, HOLD or CANT_JUDGE before a batch goes to TFRL.

Deterministic. No model call, no network. Usage:
    python3 gate.py <batch_dir> [--spec 401 --version 8 --reviews 4] [--out <csv>]

<batch_dir> holds CSV files (UTF-8, header row). Only tasks.csv is required; every other missing file turns the
rule that needs it into CANT_JUDGE for every task, with the file name as the missing item.

  tasks.csv      the batch task list: task_id, name, tab (EKW or SVC). Optional posted_id (the DataOS id that
                 will be posted; default task_id).
  preflight.csv  task_id, package_exported, grader_files, runs_current (yes or no each).
  step1.csv      task_id, verdict (PASS or HOLD; BLOCK is read as HOLD), unresolved_material (count of
                 unresolved verified material items), items (text, optional).
  review.csv     latest DataOS review run per task, either in this layout:
                   task_id, run_id, spec_id, version, status, n_reviews, finished_at, last_edit_at,
                   major_counts (comma list, one per review), fix_items (count of material fix items),
                   fix_list (text), nop_rewards (comma list of stored empty-answer rewards)
                 or as the raw DataOS run-history export (more2/dataos_pipeline_history.csv column names:
                 orig_task_id, latest_run_spec_id, ...); the export layout is mapped automatically.
  history.csv    earlier rejections and pipeline holds: task_id or name, rejected_id (the DataOS id that was
                 graded or held), source (TFRL or PIPELINE), batch, rejected_at.
  fixcheck.csv   fix verification, one row per cited item: task_id (the fixed task), item_id, severity
                 (Major or Minor), status (ADDRESSED, PARTLY, NOT ADDRESSED, CANNOT TELL), new_material
                 (count of new material defects found on the fixed package; repeat it on every row or put it
                 on one row with item_id NEW).
  tracker.csv    task_id or name, state, status (the tracker's State column and its column C status).

Rules (RULES_V4.md). Every rule is hard; advisories never block.
  B0 batch list   a task id or posted id listed twice -> HOLD both rows (the batch list is wrong).
  P0 pre-flight   package not exported or runs not current -> CANT_JUDGE; grader files missing -> HOLD.
  S1 step 1       HOLD, or unresolved verified material items above 0 -> HOLD. No row -> CANT_JUDGE.
  R1 run current  latest review run is the required spec and version, COMPLETED, with the required number of
                  reviews, and finished at or after the task's last edit. Otherwise CANT_JUDGE.
  R2 review       any review major, or any material fix item -> HOLD (read even on a non-current run).
  R3 empty answer any stored empty-answer reward above 0 -> HOLD.
  F1 fix check    task (by id or name) was rejected by TFRL or held by the pipeline before: every Major item
                  ADDRESSED and new_material 0 -> pass; any Major item not ADDRESSED or new_material above 0 ->
                  HOLD; no fix-check row -> CANT_JUDGE.
  F2 same id      the id to be posted equals a DataOS id TFRL already graded or the pipeline held -> HOLD,
                  unless the task was edited after the rejection AND F1 passes (then advisory D1 only).
  T1 tracker      tracker State says rejected and not fixed, or unresolvable -> HOLD. When its status column
                  also says "submit for manual QC", the reason names the contradiction. No tracker row ->
                  advisory only (the tracker is joined by name and misses rows).
Verdict: any HOLD reason -> HOLD; else any CANT_JUDGE reason -> CANT_JUDGE; else SEND.
Exit code 0 when every task is SEND, 2 otherwise.
"""
import argparse
import csv
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')

DEFAULT_SPEC, DEFAULT_VERSION, DEFAULT_REVIEWS = 401, 8, 4

EXPORT_MAP = {  # DataOS run-history export column -> review.csv column
    'orig_task_id': 'task_id', 'latest_run_id': 'run_id', 'latest_run_spec_id': 'spec_id',
    'latest_run_version': 'version', 'latest_run_status': 'status', 'n_reviews_in_latest_run': 'n_reviews',
    'latest_run_finished_utc': 'finished_at', 'orig_last_updated_utc': 'last_edit_at',
    'review_major_counts': 'major_counts',
}


def num(x):
    s = str(x if x is not None else '').strip()
    if s == '' or s.lower() in ('nan', 'none'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def nums(x):
    s = str(x if x is not None else '').strip()
    if s == '' or s.lower() == 'nan':
        return []
    return [v for v in (num(p) for p in re.split(r'[,;]', s)) if v is not None]


def when(x):
    s = str(x or '').strip()
    if not s or s.lower() == 'nan':
        return None
    try:
        t = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=ET)  # a time with no zone is read as US Eastern


def tid(x):
    s = str(x if x is not None else '').strip()
    m = re.search(r'/tasks/(\d+)', s)
    if m:
        return m.group(1)
    return s[:-2] if s.endswith('.0') else s


def norm_name(x):
    return re.sub(r'[^a-z0-9]', '', str(x or '').lower())


def yes(x):
    return str(x or '').strip().lower() in ('yes', 'y', 'true', '1', 'ok', 'pass')


def no(x):
    return str(x or '').strip().lower() in ('no', 'n', 'false', '0', 'fail', 'missing')


def read(path):
    if not os.path.exists(path):
        return None
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def index(rows, many=False):
    """Index rows by task id and by normalised name. many=True keeps lists."""
    by_id, by_name = {}, {}
    for r in rows or []:
        k = tid(r.get('task_id'))
        n = norm_name(r.get('name'))
        for d, key in ((by_id, k), (by_name, n)):
            if not key:
                continue
            if many:
                d.setdefault(key, []).append(r)
            else:
                d.setdefault(key, r)
    return by_id, by_name


def lookup(ix, task_id, name, posted_id=None):
    by_id, by_name = ix
    for k in (task_id, posted_id):
        if k and k in by_id:
            return by_id[k]
    n = norm_name(name)
    return by_name.get(n) if n else None


def normalise_review(rows):
    out = []
    for r in rows or []:
        if 'orig_task_id' in r and 'task_id' not in r:
            m = {EXPORT_MAP[k]: v for k, v in r.items() if k in EXPORT_MAP}
            m['nop_rewards'] = ','.join(x for x in (r.get('copy_nop_rewards'), r.get('orig_nop_rewards'))
                                        if str(x or '').strip() and str(x).lower() != 'nan')
            m['copy_task_id'] = r.get('copy_task_id', '')
            m['answer_check_review_ids'] = r.get('answer_check_review_ids', '')
            out.append(m)
        else:
            out.append(dict(r))
    return out


def rejected_unfixed(state):
    s = str(state or '').lower()
    if 'unresolv' in s:
        return 'unresolvable'
    if 'reject' in s and not re.search(r'\b(fixed|resubmit|reworked|re-?uploaded)', s.replace('not fixed', '')):
        return 'rejected'
    return None


def says_submit(status):
    return bool(re.search(r'submit\w*\s+(for\s+)?manual\s*qc', str(status or '').lower()))


def judge(task, pre, s1, rv, hist, fix, trk, have, cfg):
    """One task. have: dict file -> bool (file present). Returns (verdict, hold, cant, advisory)."""
    hold, cant, adv = [], [], []
    t_id, posted = task['task_id'], task['posted_id']
    # P0 pre-flight
    if not have['preflight']:
        cant.append('P0: no preflight.csv (package export, grader files, runs current)')
    elif pre is None:
        cant.append('P0: no pre-flight row for this task')
    else:
        if not yes(pre.get('package_exported')):
            cant.append('P0: package not exported; export it and run step 1')
        if no(pre.get('grader_files')):
            hold.append('P0: grader files missing from the package')
        elif not yes(pre.get('grader_files')):
            cant.append('P0: grader files not checked')
        if not yes(pre.get('runs_current')):
            cant.append('P0: solver runs are older than the last edit; rerun them')
    # S1 step 1
    if not have['step1']:
        cant.append('S1: no step1.csv')
    elif s1 is None:
        cant.append('S1: no step 1 result for this task; run step 1')
    else:
        v = str(s1.get('verdict', '')).strip().upper()
        um = num(s1.get('unresolved_material'))
        if v in ('HOLD', 'BLOCK'):
            hold.append('S1: step 1 HOLD (%s)' % (str(s1.get('items') or '').strip() or 'see the step 1 fix list'))
        elif um is not None and um > 0:
            hold.append('S1: %d unresolved verified material item(s) from step 1' % um)
        elif v != 'PASS':
            cant.append('S1: step 1 verdict unreadable (%r)' % v)
    # R1 to R3 review run
    if not have['review']:
        cant.append('R1: no review.csv (DataOS review run export)')
    elif rv is None:
        cant.append('R1: no DataOS review run for this task; run spec %d version %d' % (cfg.spec, cfg.version))
    else:
        g = []
        sp, ve = num(rv.get('spec_id')), num(rv.get('version'))
        if sp != cfg.spec or ve != cfg.version:
            g.append('run is spec %s version %s, need spec %d version %d' % (
                tid(rv.get('spec_id')) or '?', tid(rv.get('version')) or '?', cfg.spec, cfg.version))
        st = str(rv.get('status', '')).strip().upper()
        if st != 'COMPLETED':
            g.append('run status %s' % (st or 'missing'))
        nr = num(rv.get('n_reviews'))
        if nr != cfg.reviews:
            g.append('%s reviews, need %d' % (tid(rv.get('n_reviews')) or '0', cfg.reviews))
        fin, ed = when(rv.get('finished_at')), when(rv.get('last_edit_at'))
        if fin is None or ed is None:
            g.append('run finish time or last-edit time missing')
        elif ed > fin:
            g.append('task edited %.1f h after the run finished' % ((ed - fin).total_seconds() / 3600))
        if g:
            cant.append('R1: no current review run (' + '; '.join(g) + ')')
        tag = 'R2' if not g else 'R2 (on a non-current run)'
        majors = nums(rv.get('major_counts'))
        hit = [(i + 1, int(m)) for i, m in enumerate(majors) if m > 0]
        if hit:
            hold.append('%s: major in review %s' % (tag, ', '.join('%d (%d)' % h for h in hit)))
        fi = num(rv.get('fix_items'))
        if fi is not None and fi > 0:
            hold.append('%s: %d material fix item(s): %s' % (tag, fi, str(rv.get('fix_list') or '').strip()[:300]))
        nops = nums(rv.get('nop_rewards'))
        if nops:
            if max(nops) > 0:
                hold.append('R3: empty answer earned reward %.4f' % max(nops))
        else:
            adv.append('A2: no stored empty-answer reward; step 1 must compute it')
    # F1, F2 earlier rejection
    prior = hist or []
    if prior:
        srcs = sorted({str(h.get('source', '')).strip().upper() or '?' for h in prior})
        rej_ids = {tid(h.get('rejected_id')) for h in prior if tid(h.get('rejected_id'))}
        f1_ok = False
        if not have['fixcheck']:
            cant.append('F1: earlier %s rejection and no fixcheck.csv' % '/'.join(srcs))
        elif not fix:
            cant.append('F1: earlier %s rejection and no fix verification for this task' % '/'.join(srcs))
        else:
            maj = [f for f in fix if str(f.get('severity', '')).strip().lower() == 'major']
            bad = [f for f in maj if str(f.get('status', '')).strip().upper().replace('_', ' ') != 'ADDRESSED']
            newm = max([num(f.get('new_material')) or 0 for f in fix] + [0])
            if not maj:
                cant.append('F1: fix verification lists no Major item; it must cover every Major item TFRL or the pipeline cited')
            if bad:
                hold.append('F1: %d of %d Major item(s) not ADDRESSED (%s)' % (
                    len(bad), len(maj), ', '.join('%s %s' % (f.get('item_id', '?'), str(f.get('status', '')).strip()) for f in bad)))
            if newm > 0:
                hold.append('F1: fix verification found %d new material defect(s)' % newm)
            f1_ok = bool(maj) and not bad and newm == 0
            mino = [f for f in fix if str(f.get('severity', '')).strip().lower() == 'minor'
                    and str(f.get('status', '')).strip().upper().replace('_', ' ') != 'ADDRESSED']
            if mino:
                adv.append('A4: %d Minor item(s) not fully addressed (%s); send to the author with the fix list'
                           % (len(mino), ', '.join(str(f.get('item_id', '?')) for f in mino)))
        if posted in rej_ids or t_id in rej_ids:
            rej_at = max([x for x in (when(h.get('rejected_at')) for h in prior
                                      if tid(h.get('rejected_id')) in (posted, t_id)) if x], default=None)
            ed = when(rv.get('last_edit_at')) if rv else None
            edited_after = rej_at is not None and ed is not None and ed > rej_at
            if edited_after and f1_ok:
                adv.append('D1: posted id %s is the id that was rejected; edited in place after the rejection and fix verified' % posted)
            else:
                hold.append('F2: the id to post (%s) is the same DataOS id that was %s%s' % (
                    posted, 'graded and rejected' if 'TFRL' in srcs else 'held',
                    '' if edited_after else '; no edit after the rejection is recorded'))
    # T1 tracker
    if not have['tracker']:
        adv.append('A3: no tracker.csv; tracker State not checked')
    elif trk is None:
        adv.append('A3: no tracker row found by id or name')
    else:
        ru = rejected_unfixed(trk.get('state'))
        if ru:
            msg = 'T1: tracker State says %s (%r)' % ('rejected and not fixed' if ru == 'rejected' else 'unresolvable',
                                                      str(trk.get('state', '')).strip())
            if says_submit(trk.get('status')):
                msg += ' while its status says submit for manual QC: the two columns contradict'
            hold.append(msg)
    verdict = 'HOLD' if hold else ('CANT_JUDGE' if cant else 'SEND')
    return verdict, hold, cant, adv


class Cfg:
    def __init__(self, spec=DEFAULT_SPEC, version=DEFAULT_VERSION, reviews=DEFAULT_REVIEWS):
        self.spec, self.version, self.reviews = spec, version, reviews


def run_gate(batch_dir, cfg=None):
    cfg = cfg or Cfg()
    tasks = read(os.path.join(batch_dir, 'tasks.csv'))
    if tasks is None:
        raise SystemExit('tasks.csv missing in %s' % batch_dir)
    files = {k: read(os.path.join(batch_dir, k + '.csv')) for k in
             ('preflight', 'step1', 'review', 'history', 'fixcheck', 'tracker')}
    have = {k: v is not None for k, v in files.items()}
    files['review'] = normalise_review(files['review'])
    ix = {k: index(files[k], many=(k in ('history', 'fixcheck'))) for k in files}
    # review rows may be keyed by copy id as well
    for r in files['review']:
        c = tid(r.get('copy_task_id'))
        if c:
            ix['review'][0].setdefault(c, r)
    # B0 duplicates in the batch list
    seen_id, seen_post = {}, {}
    for t in tasks:
        t['task_id'] = tid(t.get('task_id'))
        t['posted_id'] = tid(t.get('posted_id')) or t['task_id']
        seen_id[t['task_id']] = seen_id.get(t['task_id'], 0) + 1
        seen_post[t['posted_id']] = seen_post.get(t['posted_id'], 0) + 1
    out = []
    for t in tasks:
        a, n, p = t['task_id'], t.get('name', ''), t['posted_id']
        v, h, c, ad = judge(t, lookup(ix['preflight'], a, n, p), lookup(ix['step1'], a, n, p),
                            lookup(ix['review'], a, n, p), lookup(ix['history'], a, n, p),
                            lookup(ix['fixcheck'], a, n, p), lookup(ix['tracker'], a, n, p), have, cfg)
        if seen_id[a] > 1 or seen_post[p] > 1:
            h = ['B0: task id or posted id appears more than once in the batch list'] + h
            v = 'HOLD'
        out.append(dict(task_id=a, posted_id=p, name=n, tab=t.get('tab', ''), verdict=v,
                        hold=' | '.join(h), cant_judge=' | '.join(c), advisory=' | '.join(ad)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('batch_dir')
    ap.add_argument('--spec', type=int, default=DEFAULT_SPEC)
    ap.add_argument('--version', type=int, default=DEFAULT_VERSION)
    ap.add_argument('--reviews', type=int, default=DEFAULT_REVIEWS)
    ap.add_argument('--out', default=None)
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    rows = run_gate(a.batch_dir, Cfg(a.spec, a.version, a.reviews))
    path = a.out or os.path.join(a.batch_dir, 'gate_out.csv')
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['task_id', 'posted_id', 'name', 'tab', 'verdict', 'hold', 'cant_judge', 'advisory'])
        w.writeheader()
        w.writerows(rows)
    if not a.quiet:
        for r in rows:
            print('%s\t%s\t%s' % (r['task_id'], r['verdict'], ' | '.join(x for x in (r['hold'], r['cant_judge']) if x)))
    n = {k: sum(1 for r in rows if r['verdict'] == k) for k in ('SEND', 'HOLD', 'CANT_JUDGE')}
    print('TOTAL %d tasks: SEND %d, HOLD %d, CANT_JUDGE %d. Written %s' % (len(rows), n['SEND'], n['HOLD'], n['CANT_JUDGE'], path))
    return 0 if n['HOLD'] == 0 and n['CANT_JUDGE'] == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
