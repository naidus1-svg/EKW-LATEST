"""Shared logic for step 2 version 11: parse review outputs, apply the material rule, reinstate unjustified
drops, and decide the per-task verdict. Pure functions; no network, no model calls.

Built on build/step2/parse_reviews.py (version 10, frozen 2026-10-07 02:07 ET): same record shape, same
JSON extraction. Version 11 adds the v11 output schema (verdict + fix_list + considered_not_reported) and
keeps reading the older 431 / 472 / v10 outputs so stored runs can be replayed.

Record shape (DataOS export, one per line): {"key", "review_id", "status", "token_usage": {"cost_usd"},
"targets_runs": [...], "targets_tasks": [task id], "output": {"response": "<text with one JSON object>"}}.
"""
import ast, json, re

DEC = json.JSONDecoder()
DROP_REASONS_NEEDING_RUN = ('solver_miss', 'defensible')
EMPTY_REWARD_BLOCKS_ABOVE = 0.0      # version 10 rule kept: empty answer earned reward above 0
EKW_MATERIAL_WEIGHT = 0.05           # work/x6d/RULE_V3.txt (operator decision 2026-10-07 4:50 AM ET)
SVC_TOP_K = 3                        # same file: one of the task's 3 heaviest criteria, ties count


def extract_json(text, key):
    """First JSON object in text that has `key` at top level, else None (same as v10)."""
    if not isinstance(text, str):
        return None
    for m in re.finditer(r'\{\s*"' + re.escape(key) + '"', text):
        try:
            obj, _ = DEC.raw_decode(text[m.start():])
            if isinstance(obj, dict) and key in obj:
                return obj
        except ValueError:
            continue
    return None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def as_obj(x):
    if isinstance(x, (dict, list)):
        return x
    if isinstance(x, str):
        for f in (json.loads, ast.literal_eval):
            try:
                return f(x)
            except Exception:
                pass
    return x


def task_of(rec, cmap=None):
    tt = as_obj(rec.get('targets_tasks')) or []
    t = str(tt[0]) if tt else str(rec.get('key', '')).split('-')[0]
    return (cmap or {}).get(t, t)


def response_text(rec):
    out = rec.get('output') or {}
    return out.get('response') if isinstance(out, dict) else out


def crit_ids(c):
    """Criteria field -> list of id strings. v11 uses [{"id","weight"}]; older prompts use ["id", ...]."""
    out = []
    for x in (c or []):
        if isinstance(x, dict):
            if x.get('id') is not None:
                out.append(str(x['id']))
        elif x is not None:
            out.append(str(x))
    return out


def parse_record(rec):
    """Return a dict with schema, verdict, items (fix list), drops, runs info; None if no JSON found.

    Item keys: idx, type, severity_stated, weight, criteria (list), section, reinstated (bool).
    Formats: 'v11' (key "fix_list"), 'v10' (blocking/minor), '431' (major only). 472 output parses as '431'.
    """
    txt = response_text(rec)
    obj = extract_json(txt, 'schema') or extract_json(txt, 'verdict')
    if obj is not None and 'fix_list' in obj:
        return _parse_v11(obj)
    obj = extract_json(txt, 'overall_verdict')
    if obj is None:
        return None
    items = []
    for i, f in enumerate(obj.get('findings') or []):
        if not isinstance(f, dict):
            continue
        items.append(dict(idx=i, type=str(f.get('type', '')).upper(),
                          severity_stated=str(f.get('severity', 'major')).lower(),
                          weight=num(f.get('weight_at_risk')), criteria=crit_ids(f.get('criteria')),
                          section='CORE', reinstated=False))
    schema = 'v10' if ('blocking_count' in obj or any(i['severity_stated'] in ('blocking', 'minor') for i in items)) else '431'
    return dict(schema=schema, decision=str(obj.get('overall_verdict', '')).lower(), items=items, drops=[],
                all_runs_passed=obj.get('all_runs_passed'), runs_read=None, no_run_flag=None,
                empty_run_reward=None)


def _parse_v11(obj):
    items = []
    for i, f in enumerate(obj.get('fix_list') or []):
        if not isinstance(f, dict):
            continue
        cr = f.get('criteria') or []
        w = num(f.get('weight_cost'))
        if w is None:  # fall back to the sum of listed criterion weights
            ws = [num(x.get('weight')) for x in cr if isinstance(x, dict)]
            w = sum(x for x in ws if x is not None) if ws else None
        items.append(dict(idx=i, type=str(f.get('type', '')).upper(),
                          severity_stated=str(f.get('severity', '')).lower(), weight=w,
                          criteria=crit_ids(cr), section=str(f.get('section', 'CORE')).upper(),
                          reinstated=False))
    drops = [d for d in (obj.get('considered_not_reported') or []) if isinstance(d, dict)]
    n = len(items)
    for d in drops:
        if must_reinstate(d):
            cr = d.get('criteria') or []
            ws = [num(x.get('weight')) for x in cr if isinstance(x, dict)]
            w = num(d.get('weight_cost'))
            if w is None and ws:
                w = sum(x for x in ws if x is not None)
            items.append(dict(idx=n, type=str(d.get('type', '')).upper(), severity_stated='reinstated',
                              weight=w, criteria=crit_ids(cr), section=str(d.get('section', 'CORE')).upper(),
                              reinstated=True))
            n += 1
    v = obj.get('verdict') or {}
    return dict(schema='v11', decision=str(v.get('decision', '')).lower() if isinstance(v, dict) else str(v).lower(),
                items=items, drops=drops, all_runs_passed=obj.get('all_runs_passed'),
                runs_read=obj.get('runs_read'), no_run_flag=obj.get('no_run_flag'),
                empty_run_reward=num(obj.get('empty_run_reward')))


def must_reinstate(drop):
    """Rule (c): a finding dropped as a solver miss or as defensible stays on the fix list unless the drop
    quotes a run that took the alternative reading AND passed the criterion (accepted_by_criterion true)."""
    reason = str(drop.get('reason', '')).lower().replace(' ', '_')
    if reason not in DROP_REASONS_NEEDING_RUN:
        return False
    q = str(drop.get('quoted_run') or '').strip()
    acc = drop.get('accepted_by_criterion')
    return not (q and acc is True)


def top_k_set(weights, k=SVC_TOP_K):
    """Criterion ids among the k heaviest, ties with the k-th included (RULE_V3: minus 1e-6)."""
    if not weights:
        return set(), None
    ws = sorted(weights.values(), reverse=True)
    third = ws[min(k, len(ws)) - 1]
    return {c for c, w in weights.items() if w >= third - 1e-6}, third


def _norm(c):
    return str(c).split('/')[-1].split(':')[-1].strip().lower()


def is_material(weight, criteria, tab, weights=None):
    """RULE_V3 applied to one finding. EKW: weight >= 0.05. SVC: a named criterion is one of the 3
    heaviest (ties count) or the weight is at least the third-heaviest weight. weights: {crit_id: w}."""
    w = weight or 0.0
    if str(tab).upper() == 'SVC':
        top, third = top_k_set(weights or {})
        if third is None:
            return w >= EKW_MATERIAL_WEIGHT  # no weights known: fall back to the EKW rule, reported as such
        tn = {_norm(c) for c in top}
        toks = set()
        for c in criteria or []:
            toks.add(_norm(c))
            toks.update(_norm(x) for x in re.findall(r'[A-Za-z0-9_./:-]+', str(c)))
        if toks & tn:
            return True
        return w >= third - 1e-6
    return w >= EKW_MATERIAL_WEIGHT - 1e-9


def decide_task(items, tab, weights, empty_reward, verifier=None, runs=None, n_reviews=1):
    """Per-task verdict for version 11.

    items: list of dicts with keys review_id, idx, weight, criteria, type (all reviews of the task).
    verifier: None (no verifier: every item counts as stated) or {(review_id, idx): (verdict, weight_confirmed,
              criteria_confirmed)}; only CONFIRMED items count, at their confirmed weight and criteria.
    runs: None (unknown) or dict {'solver': n, 'nop': n}; zero solver runs or no empty-answer evidence
          makes the task INCOMPLETE unless it is already REJECTED on other grounds.
    Returns (verdict, reasons list, counted items list).
    """
    reasons, counted = [], []
    if n_reviews == 0:
        return 'INCOMPLETE', ['no parsed review'], []
    if empty_reward is not None and empty_reward > EMPTY_REWARD_BLOCKS_ABOVE:
        reasons.append(f'empty answer earned {empty_reward:g}')
    for it in items:
        if verifier is None:
            w, cr = it.get('weight'), it.get('criteria')
        else:
            v = verifier.get((str(it['review_id']), int(it['idx'])))
            if not v or v[0] != 'CONFIRMED':
                continue
            w = v[1] if v[1] is not None else it.get('weight')
            cr = v[2] or it.get('criteria')
        if is_material(w, cr, tab, weights):
            counted.append(it)
    if counted:
        reasons.append(f'{len(counted)} material item(s)' + (' confirmed by verifier' if verifier is not None else ' (verifier not run)'))
    if reasons:
        return 'REJECT', reasons, counted
    if runs is not None and (runs.get('solver', 0) == 0 or (runs.get('nop', 0) == 0 and empty_reward is None)):
        miss = []
        if runs.get('solver', 0) == 0:
            miss.append('no solver run among targets')
        if runs.get('nop', 0) == 0 and empty_reward is None:
            miss.append('no empty-answer run among targets')
        return 'INCOMPLETE', miss, []
    return 'PASS', ['no material item'], []
