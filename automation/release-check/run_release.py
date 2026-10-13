#!/usr/bin/env python3
"""The one command a manager runs: the three release checks, then the table.

  python3 run_release.py EXPORT_DIR PKGS_DIRS OUT_DIR --dl DL_DIR [--dl-copies DIR] [--tasks FILE]
                         [--verifier-out DIR | --run-verifier] [--spec 557]

Runs release_check.py twice (check 1 with at least 2 valid attempts, then with at least 3), then make_table.py.
Writes OUT_DIR/release_table.csv (one row per task; columns `call` and `call_with_check1_at_3_attempts`).
Needs only Python 3.11+ and this folder. Check 2 needs either --verifier-out (verdicts already produced) or
--run-verifier (runs your own `claude` command, about 1.6 calls per task); with neither, check 2 reads
NOT COMPUTABLE on purpose.
"""
import argparse
import os
import subprocess
import sys

H = os.path.dirname(os.path.abspath(__file__))


def sh(cmd):
    print('+', ' '.join(cmd), flush=True)
    r = subprocess.run(cmd)
    if r.returncode:
        sys.exit(r.returncode)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('export')
    ap.add_argument('pkgs')
    ap.add_argument('out')
    ap.add_argument('--dl', required=True)
    ap.add_argument('--dl-copies', default=None)
    ap.add_argument('--tasks', default=None)
    ap.add_argument('--verifier-out', default=None)
    ap.add_argument('--run-verifier', action='store_true')
    ap.add_argument('--spec', type=int, default=557)
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    rc = os.path.join(H, 'release_check.py')
    base = [sys.executable, '-I', rc, os.path.abspath(a.export), a.pkgs]
    common = ['--spec', str(a.spec)]
    if a.tasks:
        common += ['--tasks', os.path.abspath(a.tasks)]
    run2, run3 = os.path.join(out, 'run_min2'), os.path.join(out, 'run_min3')
    first = common + ['--min-attempts', '2']
    if a.verifier_out:
        first += ['--verifier-out', os.path.abspath(a.verifier_out)]
    elif a.run_verifier:
        first += ['--run-verifier']
    sh(base[:3] + [base[3], base[4], run2] + first)
    second = common + ['--min-attempts', '3']
    if a.verifier_out:
        second += ['--verifier-out', os.path.abspath(a.verifier_out)]
    elif a.run_verifier:
        second += ['--verifier-out', os.path.join(run2, 'step2', 'verifier_out')]
    sh(base[:3] + [base[3], base[4], run3] + second)
    mt = [sys.executable, '-I', os.path.join(H, 'make_table.py'), run2, run3, os.path.abspath(a.export), a.pkgs,
          os.path.join(out, 'release_table.csv'), '--dl', os.path.abspath(a.dl), '--spec', str(a.spec)]
    if a.dl_copies:
        mt += ['--dl-copies', os.path.abspath(a.dl_copies)]
    sh(mt)
    return 0


if __name__ == '__main__':
    sys.exit(main())
