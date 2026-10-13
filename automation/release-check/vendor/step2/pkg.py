"""Task package helpers: locate a package, read its criteria weights and its tab (EKW or SVC).
Criteria arithmetic copied from build/step2/skeptic/make_ws.py (v10, frozen 2026-10-07 02:12 ET), which copied
work/strict strict_build.py, so weights match every earlier audit."""
import json, os, tomllib


def pkg_root(tid, bases):
    for b in bases:
        for p in (f'{b}/{tid}/{tid}', f'{b}/{tid}'):
            if os.path.isfile(f'{p}/instruction.md'):
                return p
    return None


def criteria(root):
    t = f'{root}/tests'
    out = []
    if os.path.exists(f'{t}/reward.toml'):
        rw = tomllib.load(open(f'{t}/reward.toml', 'rb'))['reward'][0].get('weights') or \
            {d: 1.0 for d in sorted(os.listdir(t)) if d.startswith('deliverables')}
        tot = sum(rw.values())
        for d, dw in rw.items():
            jt = f'{t}/{d}/judge.toml'
            if os.path.exists(jt):
                cs = tomllib.load(open(jt, 'rb')).get('criterion', [])
                s = sum(c['weight'] for c in cs)
                for c in cs:
                    out.append(dict(id=f'{d}/{c["name"]}', w=dw / tot * c['weight'] / s, text=c['description']))
            else:
                out.append(dict(id=d, w=dw / tot, text='(deterministic check, no rubric text)'))
    elif os.path.exists(f'{t}/verifier.json'):
        v = json.load(open(f'{t}/verifier.json'))['verifiers']
        s = sum(x['metadata']['weight'] for x in v)
        for x in v:
            a = x.get('assertion', {})
            txt = (a.get('rubric') or {}).get('prompt') or json.dumps(a)[:1500]
            out.append(dict(id=x['name'], w=x['metadata']['weight'] / s, text=txt))
    return out


def tab(root):
    """EKW or SVC from task.toml (any key or value naming SVC counts as SVC); EKW otherwise.
    Note: out/TABRECON.md found task.toml marks some EKW tasks SVC; pass --tabs to override from the sheet."""
    p = f'{root}/task.toml'
    if not os.path.exists(p):
        return 'EKW'
    txt = open(p, encoding='utf-8', errors='replace').read()
    return 'SVC' if 'svc' in txt.lower() else 'EKW'
