#!/usr/bin/env python3
"""Release check: one row per task, three yes/no checks, one overall value, for the manager to read before a batch
goes to TFRL (the outside QC team). Runs on the sandbox AFTER the DataOS evaluation nodes and the four reviews have finished.

  python3 release_check.py EXPORT_DIR PKGS_DIRS OUT_DIR [options]

  EXPORT_DIR   DataOS export of the batch, in the work/V11B1213 layout:
                 results.jsonl   the review export (4 reviews per task, written with the answer-check-v11 review prompt)
                 runs.csv        run_id,agent of the runs the reviews targeted
                 nop.csv         task_id,nop_reward (reward of the empty-answer run)
                 map.csv         copy_task_id,orig_task_id (when reviews ran on QC copies)
                 newruns/        index.csv (run_id,agent,status,reward,cost_usd,task_id,orig_task_id,...) and, per run,
                                 <run_id>.json and <run_id>.reward-details.json (per-criterion results)
               optional: runs/ (same per-run files for older runs), tasks.csv (task_id,name,tab),
               preflight.csv, step1.csv, history.csv, fixcheck.csv, tracker.csv, review.csv (step 3 inputs)
  PKGS_DIRS    task package folders, ':'-joined
  OUT_DIR      release_check.csv, release_check_tab.csv, check1_detail.csv, step2/ (step2_v11 outputs), gate/

Options:
  --runs-dir D        extra folder searched (recursively) for <run_id>.reward-details.json (repeatable)
  --gate-inputs D     folder with step 3 input CSVs (preflight, step1, history, fixcheck, tracker, review);
                      files in EXPORT_DIR are used when this is not given
  --verifier-out D    reuse verifier verdicts already produced (step 2 --verifier-out)
  --run-verifier      run the frozen verifier now (Max-plan claude calls, about 1.6 per task, no DataOS credit)
  --min-attempts N    fewest valid solver attempts for check 1 (default 2; the EXECTRUTH backtest used 3)
  --spec N --version N  review run spec and version the gate requires; they are copied into the generated
                      review.csv as the operator's statement (without them the gate cannot confirm the run)
  --tasks FILE        task_id,name,tab (overrides EXPORT_DIR/tasks.csv)

Check 1 (step 1, "c_fail"): yes when some grading rule scores 0 in EVERY valid solver attempt while the reference
  (oracle) run earns full credit on it. Rule, same as work/EXECTRUTH/exectruth.py: rule value 1.0 in the oracle run,
  value 0.0 in all attempts. NOT COMPUTABLE when there are fewer than --min-attempts valid attempts or no passing
  reference run with per-criterion results.
Check 2 (step 2, version 11): yes when final/step2 pass_rule_v11 says REJECT. NOT COMPUTABLE when no version 11
  review parsed, the verifier did not run or left items without a verdict, or the package is missing.
Check 3 (step 3): final/step3/gate.py verdict. yes = HOLD. CANT_JUDGE = NOT COMPUTABLE (the missing input is named).
Overall: HOLD if any check is yes; NEEDS INPUT if any check is not computable and none is yes; RELEASE otherwise.
No cutoff is applied anywhere: the script reports counts and reasons, the manager decides.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile

H = os.path.dirname(os.path.abspath(__file__))
FINAL = os.path.join(H, 'vendor')  # portable copy: step2 and step3 modules are vendored under vendor/
sys.path.insert(0, os.path.join(FINAL, 'step3'))
sys.path.insert(0, os.path.join(FINAL, 'step2'))

SOLVER_AGENTS = ('CODEX', 'TERMINUS-2', 'TERMINUS')
COLS = ['task_id', 'sheet_name', 'tab', 'check1_c_fail', 'check1_reason', 'check1_attempts', 'check1_rules',
        'check2_v11', 'check2_reason', 'check2_rules', 'check3_gate', 'check3_reason', 'check3_missing_inputs',
        'check3_rules', 'overall', 'message']


# ---------------------------------------------------------------- small readers
def read_csv(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def tid(x):
    s = str(x if x is not None else '').strip()
    return s[:-2] if s.endswith('.0') else s


def load_jsonl(path):
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def judge_error(path):
    """v2: True if any criterion in this reward-details.json carries a non-empty `error` (for example the LLM judge could not
    be called). Such a run says nothing about the answer, so check 1 does not count it as an attempt or as a reference."""
    try:
        d = json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        return False
    found = []

    def walk(n):
        if isinstance(n, dict):
            if 'name' in n and 'weight' in n and n.get('error'):
                found.append(1)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(d)
    return bool(found)


def crit_map(path):
    """criterion key -> (value, weight) from a reward-details.json (same walk as work/EXECTRUTH/exectruth.py)."""
    d = json.load(open(path, encoding='utf-8'))
    out = {}

    def walk(n, key):
        if isinstance(n, dict):
            if 'name' in n and 'value' in n and 'weight' in n and not isinstance(n['value'], (dict, list)):
                try:
                    out['%s/%s' % (key, n['name'])] = (float(n['value']), float(n['weight']))
                except (TypeError, ValueError):
                    pass
            for v in n.values():
                walk(v, key)
        elif isinstance(n, list):
            for v in n:
                walk(v, key)
    if isinstance(d, dict):
        for dk, v in d.items():
            walk(v, dk)
    return out


# ---------------------------------------------------------------- export
def orig_of(key):
    return str(key).rsplit('-', 1)[0]


def load_export(exp):
    res_path = os.path.join(exp, 'results.jsonl')
    if not os.path.exists(res_path):
        raise SystemExit('results.jsonl missing in %s' % exp)
    reviews = load_jsonl(res_path)
    cmap = {tid(r['copy_task_id']): tid(r['orig_task_id']) for r in (read_csv(os.path.join(exp, 'map.csv')) or [])}
    nop = {tid(r['task_id']): r['nop_reward'] for r in (read_csv(os.path.join(exp, 'nop.csv')) or [])}
    # run id -> original task id, from what each review targeted
    run_task = {}
    for r in reviews:
        o = orig_of(r.get('key', ''))
        for run in r.get('targets_runs') or []:
            run_task[tid(run)] = o
    runs = {}  # run_id -> dict(agent, status, reward, task, detail)
    for r in read_csv(os.path.join(exp, 'runs.csv')) or []:
        runs[tid(r['run_id'])] = dict(agent=r['agent'].upper(), status='', reward='', task=run_task.get(tid(r['run_id'])), detail='')
    for r in read_csv(os.path.join(exp, 'newruns', 'index.csv')) or []:
        k = tid(r['run_id'])
        o = tid(r.get('orig_task_id')) or cmap.get(tid(r.get('task_id'))) or tid(r.get('task_id'))
        runs[k] = dict(agent=r['agent'].upper(), status=r.get('status', ''), reward=r.get('reward', ''), task=o,
                       detail='')
    return reviews, cmap, nop, runs


def find_details(exp, extra_dirs):
    """run id -> path of its reward-details.json, searched in newruns/, runs/ and --runs-dir folders."""
    found = {}
    roots = [os.path.join(exp, 'newruns'), os.path.join(exp, 'runs')] + list(extra_dirs)
    for root in roots:
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if f.endswith('.reward-details.json'):
                    found.setdefault(f.split('.')[0], os.path.join(dp, f))
    return found


def run_json(path_dir_candidates, run_id):
    for d in path_dir_candidates:
        p = os.path.join(d, '%s.json' % run_id)
        if os.path.exists(p):
            try:
                return json.load(open(p, encoding='utf-8'))
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------- check 1
def check1(task, runs, details, exp, extra_dirs, min_attempts):
    """Returns dict(result, reason, attempts, rules, rows)."""
    jdirs = [os.path.join(exp, 'newruns'), os.path.join(exp, 'runs')] + list(extra_dirs)
    mine = {k: v for k, v in runs.items() if v['task'] == task}
    valid_att, invalid, oracles = [], [], []
    for k, v in sorted(mine.items()):
        if v['agent'] == 'NOP':
            continue
        det = details.get(k)
        if det and judge_error(det):
            invalid.append('%s (judge error in per-criterion file)' % k)
            continue
        rj = run_json(jdirs + ([os.path.dirname(det)] if det else []), k)
        status = (rj or {}).get('status') or v['status'] or ''
        exc = ((rj or {}).get('exception_info') or '').strip()
        if v['agent'] == 'ORACLE':
            ok = det and status in ('PASSED', '') and not exc
            reward = (rj or {}).get('aggregate_reward', v['reward'])
            try:
                reward = float(reward)
            except (TypeError, ValueError):
                reward = None
            if ok and (reward is None or reward > 0):
                oracles.append(k)
            continue
        if v['agent'] not in SOLVER_AGENTS:
            continue
        if det and status in ('PASSED', 'FAILED', '') and not exc:
            valid_att.append(k)
        else:
            invalid.append('%s (%s)' % (k, 'no per-criterion file' if not det else 'status %s%s' % (status, ' exception' if exc else '')))
    info = dict(attempts='%d valid%s' % (len(valid_att), ('; %d dropped: %s' % (len(invalid), ', '.join(invalid))) if invalid else ''),
                rules='', rows=[])
    if len(valid_att) < min_attempts:
        info.update(result='NOT COMPUTABLE', reason='fewer than %d valid attempts with per-criterion results (%d found)' % (min_attempts, len(valid_att)))
        return info
    if not oracles:
        info.update(result='NOT COMPUTABLE', reason='no passing reference (oracle) run with per-criterion results')
        return info
    ref_id = sorted(oracles, key=lambda x: int(x) if x.isdigit() else 0)[-1]
    ref = crit_map(details[ref_id])
    atts = [crit_map(details[k]) for k in valid_att]
    fails = []
    for key, (ov, ow) in ref.items():
        vals = [a[key][0] for a in atts if key in a]
        if len(vals) < len(atts):
            continue
        if ov == 1.0 and all(v == 0.0 for v in vals):
            fails.append((key, ow))
    info['rows'] = [dict(task_id=task, reference_run=ref_id, attempts=','.join(valid_att), rule=k, weight=w) for k, w in fails]
    weak = ' (only %d attempts: a rule can lose in all of them by chance; EXECTRUTH used 3 or more)' % len(valid_att) if len(valid_att) < 3 else ''
    if fails:
        info.update(result='yes', reason='%d rule(s) lost by all %d valid attempts and earned by reference run %s%s' % (len(fails), len(valid_att), ref_id, weak),
                    rules='; '.join('%s w=%.4g' % (k, w) for k, w in fails))
    else:
        info.update(result='no', reason='no rule lost by all %d valid attempts while earned by reference run %s%s' % (len(valid_att), ref_id, weak))
    return info


# ---------------------------------------------------------------- check 2
def run_step2(exp, pkgs, out, verifier_out, run_verifier, tasks_with_pkg, tabs_csv):
    """Runs final/step2/step2_v11.py on the export, restricted to tasks that have a package. Returns dict task -> row, notes."""
    s2 = os.path.join(out, 'step2')
    os.makedirs(s2, exist_ok=True)
    keep = os.path.join(s2, 'reviews_with_package.jsonl')
    with open(keep, 'w', encoding='utf-8') as f:
        for r in load_jsonl(os.path.join(exp, 'results.jsonl')):
            if orig_of(r.get('key', '')) in tasks_with_pkg:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    cmd = [sys.executable, os.path.join(FINAL, 'step2', 'step2_v11.py'), keep, pkgs, s2]
    for flag, name in (('--nop', 'nop.csv'), ('--map', 'map.csv'), ('--runs', 'runs.csv')):
        if os.path.exists(os.path.join(exp, name)):
            cmd += [flag, os.path.join(exp, name)]
    if tabs_csv:
        cmd += ['--tabs', tabs_csv]
    if verifier_out:
        cmd += ['--verifier-out', verifier_out]
    if run_verifier:
        cmd += ['--run-verifier', 'local']
    # the child writes UTF-8 and we read it as UTF-8, whatever the Windows code page is (the system default would garble or crash on non-ASCII)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    with open(os.path.join(s2, 'step2.log'), 'w', encoding='utf-8') as f:
        f.write(p.stdout + '\n--- stderr ---\n' + p.stderr)
    rows = {r['task_id']: r for r in (read_csv(os.path.join(s2, 'verdicts.csv')) or [])}
    fix = read_csv(os.path.join(s2, 'fixlist.csv')) or []
    return rows, fix, p.returncode, s2


def check2_row(task, vrows, fix, rc, have_verifier, pkg_ok, unreadable=None):
    if not pkg_ok and unreadable and task in unreadable:
        return 'NOT COMPUTABLE', 'task package found but check 2 cannot read its grader file (%s)' % unreadable[task], ''
    if not pkg_ok:
        return 'NOT COMPUTABLE', 'task package folder not found', ''
    r = vrows.get(task)
    if r is None:
        return 'NOT COMPUTABLE', 'no version 11 review (review prompt answer-check-v11, DataOS saved prompt id 557) parsed for this task (step2_v11 exit %s)' % rc, ''
    if not have_verifier:
        return 'NOT COMPUTABLE', ('verifier not run (would be %s without it; never ship that); run with --run-verifier or --verifier-out'
                                  % r.get('verdict_noverifier', '?')), ''
    v = r['verdict']
    counted = [f for f in fix if f['task_id'] == task and f.get('counted_in_verdict') == '1']
    rules = '; '.join('%s %s w=%s' % (f['type'], f['criteria'][:50], f['weight_confirmed'] or f['weight_stated']) for f in counted[:6])
    unver = int(r.get('n_unverified') or 0)
    if v == 'REJECT':
        return 'yes', 'REJECT: %s' % r['reason'], rules
    if v == 'INCOMPLETE':
        return 'NOT COMPUTABLE', 'INCOMPLETE: %s' % r['reason'], ''
    if unver:
        return 'NOT COMPUTABLE', 'PASS but %d fix-list item(s) have no verifier verdict; rerun the verifier' % unver, ''
    note = 'PASS: %s' % r['reason'] if r['reason'] else 'PASS'
    if int(r.get('n_unclear') or 0):
        note += '; %s item(s) UNCLEAR go to the manager' % r['n_unclear']
    return 'no', note, ''


# ---------------------------------------------------------------- check 3
MISSING = {'P0': 'preflight.csv (package export, grader files, runs current)', 'S1': 'step1.csv (step 1 verdict)',
           'R1': 'current review run row (review.csv with spec, version, finish time, last-edit time)',
           'F1': 'fixcheck.csv (fix verification of an earlier rejection)'}


def build_gate_dir(exp, gate_inputs, reviews, nop, names, spec, version, gdir):
    os.makedirs(gdir, exist_ok=True)
    with open(os.path.join(gdir, 'tasks.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['task_id', 'name', 'tab'])
        for t, (n, tb) in names.items():
            w.writerow([t, n, tb])
    srcs = [d for d in (gate_inputs, exp) if d]
    for nm in ('preflight', 'step1', 'history', 'fixcheck', 'tracker', 'review'):
        for d in srcs:
            p = os.path.join(d, nm + '.csv')
            if os.path.exists(p):
                open(os.path.join(gdir, nm + '.csv'), 'wb').write(open(p, 'rb').read())
                break
    if not os.path.exists(os.path.join(gdir, 'review.csv')):
        by = {}
        for r in reviews:
            by.setdefault(orig_of(r.get('key', '')), []).append(r)
        with open(os.path.join(gdir, 'review.csv'), 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['task_id', 'run_id', 'spec_id', 'version', 'status', 'n_reviews', 'finished_at', 'last_edit_at',
                        'major_counts', 'fix_items', 'fix_list', 'nop_rewards'])
            for t, rs in by.items():
                st = 'COMPLETED' if all(str(x.get('status')).upper() == 'PASSED' for x in rs) else 'FAILED'
                w.writerow([t, '', spec or '', version or '', st, len(rs), '', '', '', '', '', nop.get(t, '')])
    return gdir


def check3(gdir, spec, version, reviews_needed):
    import gate
    cfg = gate.Cfg(spec if spec else gate.DEFAULT_SPEC, version if version else gate.DEFAULT_VERSION, reviews_needed)
    return {r['task_id']: r for r in gate.run_gate(gdir, cfg)}


# ---------------------------------------------------------------- assemble
def overall(c1, c2, c3):
    results = [c1, c2, 'yes' if c3 == 'HOLD' else ('NOT COMPUTABLE' if c3 == 'CANT_JUDGE' else 'no')]
    if 'yes' in results:
        return 'HOLD'
    if 'NOT COMPUTABLE' in results:
        return 'NEEDS INPUT'
    return 'RELEASE'


def message(row):
    parts = []
    if row['check1_c_fail'] == 'yes':
        parts.append('Check 1: rule(s) %s lost by every attempt but earned by the reference answer; fix the rule or the reference, say which.' % row['check1_rules'])
    if row['check2_v11'] == 'yes':
        parts.append('Check 2: version 11 review (answer-check-v11, DataOS saved prompt id 557) says REJECT; answer each confirmed item (%s).' % row['check2_rules'])
    if row['check3_gate'] == 'HOLD':
        parts.append('Check 3: manager gate HOLD (%s).' % row['check3_rules'])
    if parts:
        return ' '.join(parts)
    need = []
    if row['check1_c_fail'] == 'NOT COMPUTABLE':
        need.append('check 1: ' + row['check1_reason'])
    if row['check2_v11'] == 'NOT COMPUTABLE':
        need.append('check 2: ' + row['check2_reason'])
    if row['check3_gate'] == 'CANT_JUDGE':
        need.append('check 3: missing ' + row['check3_missing_inputs'])
    if need:
        return 'Needs input before a decision: ' + ' | '.join(need)
    return 'No check fired; all three computed.'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('export')
    ap.add_argument('pkgs')
    ap.add_argument('out')
    ap.add_argument('--runs-dir', action='append', default=[])
    ap.add_argument('--gate-inputs', default=None)
    ap.add_argument('--verifier-out', default=None)
    ap.add_argument('--run-verifier', action='store_true')
    ap.add_argument('--min-attempts', type=int, default=2)
    ap.add_argument('--spec', type=int, default=None)
    ap.add_argument('--version', type=int, default=None)
    ap.add_argument('--tasks', default=None)
    a = ap.parse_args(argv)
    exp, out = a.export, a.out
    os.makedirs(out, exist_ok=True)
    reviews, cmap, nop, runs = load_export(exp)
    details = find_details(exp, a.runs_dir)
    for k, v in runs.items():
        v['detail'] = details.get(k, '')
    listed = {tid(r['task_id']) for r in (read_csv(os.path.join(exp, 'tasks.csv')) or []) if os.path.isdir(os.path.join(exp, '_pkgs'))}  # v2: tasks of a zip export with no review yet
    tasks = sorted({orig_of(r['key']) for r in reviews} | set(nop) | listed, key=lambda x: int(x) if x.isdigit() else 0)
    # names and tabs
    nm = {}
    for r in read_csv(a.tasks or os.path.join(exp, 'tasks.csv')) or []:
        nm[tid(r['task_id'])] = (r.get('name', ''), r.get('tab', ''))
    from pkg import pkg_root, tab as pkg_tab, criteria as pkg_criteria
    bases = a.pkgs.split(':')
    names, pkg_ok, unreadable = {}, {}, {}
    for t in tasks:
        root = pkg_root(t, bases)
        pkg_ok[t] = root is not None
        if root is not None:  # v2: a package whose grader file check 2 cannot read must not stop check 2 for the other tasks
            try:
                pkg_criteria(root)
            except Exception as e:  # noqa: BLE001
                pkg_ok[t] = False
                unreadable[t] = '%s: %s' % (type(e).__name__, e)
        n, tb = nm.get(t, ('', ''))
        names[t] = (n or '(name not in export; add tasks.csv)', tb or (pkg_tab(root) if root else ''))
    tabs_csv = os.path.join(out, 'tabs_used.csv')
    with open(tabs_csv, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['task_id', 'tab'])
        for t, (_n, tb) in names.items():
            if tb:
                w.writerow([t, tb])
    # check 1
    c1, c1rows = {}, []
    for t in tasks:
        c1[t] = check1(t, runs, details, exp, a.runs_dir, a.min_attempts)
        c1rows += c1[t]['rows']
    with open(os.path.join(out, 'check1_detail.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['task_id', 'reference_run', 'attempts', 'rule', 'weight'])
        w.writeheader()
        w.writerows(c1rows)
    # check 2
    have_verifier = bool(a.run_verifier or a.verifier_out)
    vrows, fix, rc, s2 = run_step2(exp, a.pkgs, out, a.verifier_out, a.run_verifier, {t for t in tasks if pkg_ok[t]}, tabs_csv)
    if have_verifier and not a.verifier_out:
        have_verifier = os.path.isdir(os.path.join(s2, 'verifier_out'))
    # check 3
    gdir = build_gate_dir(exp, a.gate_inputs, reviews, nop, names, a.spec, a.version, os.path.join(out, 'gate'))
    n_rev = max([sum(1 for r in reviews if orig_of(r['key']) == t) for t in tasks] + [4])
    g = check3(gdir, a.spec, a.version, n_rev)
    rows = []
    for t in tasks:
        r1, (r2, why2, rules2) = c1[t], check2_row(t, vrows, fix, rc, have_verifier, pkg_ok[t], unreadable)
        gr = g.get(t, {})
        verdict = gr.get('verdict', 'CANT_JUDGE')
        hold, cant = gr.get('hold', ''), gr.get('cant_judge', '')
        codes = sorted(set(re.findall(r'(?:^|\| )([A-Z]\d)\b', hold if verdict == 'HOLD' else cant)))
        missing = '; '.join(MISSING[c] for c in codes if c in MISSING) if verdict == 'CANT_JUDGE' else ''
        row = dict(task_id=t, sheet_name=names[t][0], tab=names[t][1],
                   check1_c_fail=r1['result'], check1_reason=r1['reason'], check1_attempts=r1['attempts'], check1_rules=r1['rules'],
                   check2_v11=r2, check2_reason=why2, check2_rules=rules2,
                   check3_gate=verdict, check3_reason=(hold if verdict == 'HOLD' else cant)[:600], check3_missing_inputs=missing,
                   check3_rules=','.join(codes))
        row['overall'] = overall(r1['result'], r2, verdict)
        row['message'] = message(row)
        rows.append(row)
    with open(os.path.join(out, 'release_check.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    tabcols = ['task_id', 'sheet_name', 'tab', 'check1_c_fail', 'check2_v11', 'check3_gate', 'overall', 'message']
    with open(os.path.join(out, 'release_check_tab.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=tabcols, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    n = len(rows)
    cnt = lambda k, vals: {v: sum(1 for r in rows if r[k] == v) for v in vals}
    print('TASKS %d' % n)
    print('overall', cnt('overall', ['HOLD', 'NEEDS INPUT', 'RELEASE']))
    print('check1', cnt('check1_c_fail', ['yes', 'no', 'NOT COMPUTABLE']))
    print('check2', cnt('check2_v11', ['yes', 'no', 'NOT COMPUTABLE']))
    print('check3', cnt('check3_gate', ['SEND', 'HOLD', 'CANT_JUDGE']))
    print('written', os.path.join(out, 'release_check.csv'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
