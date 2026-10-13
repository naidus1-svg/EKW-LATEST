"""One command for step 2 version 11: parse a DataOS review export, build verifier workspaces for every
fix-list item, optionally run the verifier, apply the pass rule, print a per-task verdict plus the items
that decided it, and write the fix list.

  python3 step2_v11.py REVIEWS.jsonl PKGS_DIR OUT_DIR [--nop nop.csv] [--map copy_to_orig.csv] [--runs runs.csv]
                       [--tabs tabs.csv] [--weights weights.csv] [--verifier-out DIR] [--run-verifier LANE|local]
                       [--t1t3 report|blocking]

  REVIEWS.jsonl   DataOS export of the review node outputs (records as in hist/ext1x/*_results.jsonl)
  PKGS_DIR        task package folder(s), ':'-joined (for example /root/pq/b12/pkgs:/root/pq/b12/pkgs_dev)
  OUT_DIR         parse/, verifier_ws/, verifier_out/, verdicts.csv, fixlist.csv, flags.csv
  --runs          CSV run_id,agent so the parser can count solver and empty-answer runs among each review's targets
  --run-verifier  run the frozen verifier now (a sandbox lane name, or 'local' for plain claude -p on the Max plan)
No network is used unless --run-verifier is given.
"""
import os, subprocess, sys

H = os.path.dirname(os.path.abspath(__file__))


def run(cmd):
    print('+', ' '.join(cmd), flush=True)
    r = subprocess.run(cmd)
    if r.returncode:
        sys.exit(r.returncode)


def main(a):
    src, pk, out = a[0], a[1], a[2]
    opt = {a[i]: a[i + 1] for i in range(3, len(a) - 1, 2)}
    os.makedirs(out, exist_ok=True)
    pa = [sys.executable, f'{H}/parse_reviews_v11.py', src, f'{out}/parse']
    for k in ('--map', '--runs'):
        if k in opt:
            pa += [k, opt[k]]
    run(pa)
    mw = [sys.executable, f'{H}/verifier/make_ws_v11.py', f'{out}/parse', pk, f'{out}/verifier_ws']
    if '--nop' in opt:
        mw += ['--nop', opt['--nop']]
    run(mw)
    vo = opt.get('--verifier-out', f'{out}/verifier_out')
    if '--run-verifier' in opt:
        lane = opt['--run-verifier']
        run(['bash', f'{H}/verifier/run_verifier.sh', f'{out}/verifier_ws', vo] + ([] if lane == 'local' else [lane]))
    pr = [sys.executable, f'{H}/pass_rule_v11.py', f'{out}/parse', '--out', out, '--pkgs', pk]
    for k in ('--nop', '--tabs', '--weights', '--t1t3'):
        if k in opt:
            pr += [k, opt[k]]
    if os.path.isdir(vo) and any(os.path.exists(f'{vo}/{w}/verdicts.json') for w in os.listdir(vo)):
        pr += ['--verifier', vo]
    else:
        print('NOTE: no verifier verdicts found; the verdict column below counts every item at its stated weight '
              '(rule v11_noverifier). Do not ship these verdicts: run the verifier first.')
    run(pr)


if __name__ == '__main__':
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(sys.argv[1:])
