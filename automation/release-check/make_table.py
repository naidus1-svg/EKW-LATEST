#!/usr/bin/env python3
"""Build the manager's table (release_table.csv) from two release_check.py runs plus review timing read from the
per-task download folders. Same logic as work/trial3a/scripts/build_table.py (job B12_TRIAL3A); the only change is that
every path is an argument.

  python3 make_table.py RUN_MIN2 RUN_MIN3 EXPORT_DIR PKGS_DIRS OUT_CSV --dl DIR [--dl-copies DIR] [--spec 557]

  RUN_MIN2 / RUN_MIN3  release_check.py output folders (check 1 at 2 valid attempts and at 3)
  EXPORT_DIR           the export folder (map.csv is read for QC copies)
  PKGS_DIRS            task package folders, ':'-joined (only used to say whether a package folder exists)
  --dl DIR             downloader output: DIR/<task_id>/task.json and DIR/<task_id>/verifications/*.json
  --dl-copies DIR      same, for QC copies named in map.csv (DIR/<copy_task_id>/...)
"""
import argparse
import csv
import glob
import json
import os


def rd(p):
    with open(p, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def call(*vals):
    if any(v in ('yes', 'HOLD') for v in vals):
        return 'HOLD'
    if any(v in ('NOT COMPUTABLE', 'CANT_JUDGE', 'NOT KNOWN') for v in vals):
        return 'EVIDENCE MISSING'
    return 'RELEASE'


def review_timing(tid, cmap, dl, dl_copies, spec):
    """answer-check-v11 review runs (DataOS saved prompt id `spec`; 557 is answer-check-v11) and last package edit, from the stored download."""
    cp = cmap.get(tid)
    if cp:
        folder, src = os.path.join(dl_copies or '', cp), 'QC copy ' + cp
    else:
        folder, src = os.path.join(dl or '', tid), 'task itself'
    try:
        edit = json.load(open(os.path.join(folder, 'task.json'), encoding='utf-8'))['updated_at']
    except Exception:
        return dict(n557='', fin='', edit='', newer='NOT KNOWN', src=src)
    fins = []
    for p in glob.glob(os.path.join(folder, 'verifications', '*.json')):
        d = json.load(open(p, encoding='utf-8'))
        sp = d.get('saved_prompt') or {}
        if sp.get('id') == spec and d.get('status') == 'PASSED' and not d.get('_archived'):
            fins.append(d['updated_at'])
    if not fins:
        return dict(n557=0, fin='', edit=edit, newer='NO REVIEW ON SPEC %s' % spec if spec != 557 else 'NO answer-check-v11 REVIEW', src=src)
    return dict(n557=len(fins), fin=max(fins), edit=edit, newer='yes' if min(fins) >= edit else 'no', src=src)


def build(run2, run3, export, pkgs, out_csv, dl, dl_copies, spec=557):
    r2 = {r['task_id']: r for r in rd(os.path.join(run2, 'release_check.csv'))}
    r3 = {r['task_id']: r for r in rd(os.path.join(run3, 'release_check.csv'))}
    mp = os.path.join(export, 'map.csv')
    cmap = {r['orig_task_id']: r['copy_task_id'] for r in rd(mp)} if os.path.exists(mp) else {}
    bases = pkgs.split(':')

    def has_pkg(tid):
        return any(os.path.isdir(os.path.join(p, tid)) for p in bases)

    rows = []
    for tid in r2:
        a, b = r2[tid], r3[tid]
        t = review_timing(tid, cmap, dl, dl_copies, spec)
        c1, c1b, c2, c3 = a['check1_c_fail'], b['check1_c_fail'], a['check2_v11'], a['check3_gate']
        miss, src = [], []
        if c1 == 'NOT COMPUTABLE':
            miss.append('check 1: ' + a['check1_reason'])
            src.append('check 1: more solver attempts (DataOS run) and/or oracle run per-criterion file (downloader)')
        elif c1b == 'NOT COMPUTABLE':
            miss.append('check 1 at 3 attempts: %s' % a['check1_attempts'])
            src.append('third valid attempt: new DataOS solver run, plus its reward-details download')
        if c2 == 'NOT COMPUTABLE':
            miss.append('check 2: ' + a['check2_reason'])
            src.append('check 2: task package folder (export from DataOS)')
        if c3 == 'CANT_JUDGE':
            miss.append('check 3: ' + a['check3_missing_inputs'])
            src.append('check 3: preflight.csv and step1.csv from final/step1 (scripts, no credit), review row from DataOS run history')
        rows.append(dict(
            task_id=tid, sheet_name=a['sheet_name'], tab=a['tab'],
            check1_c_fail=c1, check1_attempts=a['check1_attempts'], check1_rules=a['check1_rules'][:300],
            check1_at_3_attempts=c1b,
            check2_v11=c2, check2_reason=a['check2_reason'],
            check3_gate=c3, check3_reason=a['check3_reason'][:300],
            package_folder_found='yes' if has_pkg(tid) else 'no',
            answer_check_v11_review_count=t['n557'], review_last_finished=t['fin'], package_last_edit=t['edit'],
            review_newer_than_last_edit=t['newer'], review_source=t['src'],
            missing_inputs=' | '.join(miss), where_it_would_come_from=' | '.join(src),
            call=call(c1, c2, c3), call_with_check1_at_3_attempts=call(c1b, c2, c3)))
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('run_min2')
    ap.add_argument('run_min3')
    ap.add_argument('export')
    ap.add_argument('pkgs')
    ap.add_argument('out_csv')
    ap.add_argument('--dl', default=None)
    ap.add_argument('--dl-copies', default=None)
    ap.add_argument('--spec', type=int, default=557)
    a = ap.parse_args(argv)
    rows = build(a.run_min2, a.run_min3, a.export, a.pkgs, a.out_csv, a.dl, a.dl_copies, a.spec)
    n = len(rows)
    for k in ('call', 'call_with_check1_at_3_attempts'):
        print(k, {v: sum(1 for r in rows if r[k] == v) for v in ('HOLD', 'EVIDENCE MISSING', 'RELEASE')})
    print('tasks %d, written %s' % (n, a.out_csv))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
