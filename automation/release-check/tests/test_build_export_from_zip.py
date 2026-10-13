"""Tests for build_export_from_zip.py. Fixtures are tiny synthetic "with runs" zips (task ids and made-up names only, no task content).

Layout built here: <task name>/rev_<n>__<task id>/{task_files/, evaluations/eval_<eval id>__attempt_<k>__<agent>[__<model>]/eval_files/...,
verifications/comprehensive_review_<id>___<agent>__<model>.md}
"""
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

H = os.path.dirname(os.path.abspath(__file__))
P = os.path.dirname(H)
sys.path.insert(0, P)
import build_export_from_zip as bz  # noqa: E402

PROMPT = 'Fixture review prompt. Judge the task.'
PHASH = hashlib.sha256(PROMPT.encode()).hexdigest()
ANSWER = 'ok\n```json\n{"overall_verdict": "accept", "findings": []}\n```'


def details(vals, error=None):
    return {'g': {'kind': 'rubric', 'score': 0.0, 'criteria': [
        {'name': k, 'weight': w, 'value': v, 'raw': v, 'reasoning': 'x', 'error': error} for k, (v, w) in vals.items()]}}


def evaluation(agent_dir, eval_id, run_id, task_id, reward, det=None, exc=None):
    base = agent_dir
    res = {'id': 'u', 'task_name': 'task_%s' % task_id, 'trial_name': 'x', 'config': {'task': {'path': '/tmp/eval_%s_abc/task_%s' % (run_id, task_id)}},
           'verifier_result': {'rewards': {'reward': reward}} if reward is not None else None, 'exception_info': exc,
           'started_at': '2026-10-08T07:00:00Z', 'finished_at': '2026-10-08T07:10:00Z'}
    out = {'eval_files/result.json': json.dumps(res)}
    if det is not None:
        out['eval_files/verifier/reward-details.json'] = json.dumps(det)
        out['eval_files/verifier/reward.json'] = json.dumps({'reward': reward})
    return {os.path.join(base, k): v for k, v in out.items()}


def review_md(rid, task_id, run_ids, prompt=PROMPT, status='PASSED', agent='CLAUDE-CODE'):
    return ('## type\nCOMPREHENSIVE_REVIEW\n\n## status\n%s\n\n## model\nanthropic/m\n\n## agent\n%s\n\n## task_ids\n[%s]\n\n'
            '## evaluationrun_ids\n[%s]\n\n## transcript\nQ: %s\n\nA: %s\n' % (status, agent, task_id, ', '.join(run_ids), prompt, ANSWER))


def build_tree(root, name='Task-A', rev=1, task_id='900', with_review=True, with_nop=True, review_prompt=PROMPT, judge_error=None):
    rd = os.path.join(name, 'rev_%d__%s' % (rev, task_id))
    f = {}
    f[os.path.join(rd, 'task_files', 'instruction.md')] = 'do it'
    f[os.path.join(rd, 'task_files', 'task.toml')] = 'x=1'
    ev = os.path.join(rd, 'evaluations')
    f.update(evaluation(os.path.join(ev, 'eval_500__attempt_1__oracle'), 500, 9001, task_id, 1.0, details({'a': (1.0, .5), 'b': (1.0, .5)})))
    f.update(evaluation(os.path.join(ev, 'eval_501__attempt_1__codex__gpt-x'), 501, 9002, task_id, 0.5, details({'a': (1.0, .5), 'b': (0.0, .5)}, judge_error)))
    f.update(evaluation(os.path.join(ev, 'eval_501__attempt_2__codex__gpt-x'), 501, 9003, task_id, 0.5, details({'a': (1.0, .5), 'b': (0.0, .5)})))
    runs = ['9001', '9002', '9003']
    if with_nop:
        f.update(evaluation(os.path.join(ev, 'eval_502__attempt_1__nop'), 502, 9004, task_id, 0.0, details({'a': (0.0, .5), 'b': (0.0, .5)})))
        runs.append('9004')
    if with_review:
        f[os.path.join(rd, 'verifications', 'comprehensive_review_77___claude-code__m.md')] = review_md(77, task_id, runs, review_prompt)
    for rel, txt in f.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w').write(txt)


def zip_dir(src, dst):
    with zipfile.ZipFile(dst, 'w') as z:
        for dp, _dn, fn in os.walk(src):
            for x in fn:
                full = os.path.join(dp, x)
                z.write(full, os.path.relpath(full, src))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.known = os.path.join(self.d, 'known.json')
        json.dump({'prompts': {PHASH: {'saved_prompt_id': 557, 'name': 'fixture'}}}, open(self.known, 'w'))

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **kw):
        src = os.path.join(self.d, 'src')
        build_tree(src, **kw)
        z = os.path.join(self.d, 'in.zip')
        zip_dir(src, z)
        out = os.path.join(self.d, 'out')
        bz.main([z, out, '--known-prompts', self.known])
        return out

    def rows(self, out, name):
        return list(csv.DictReader(open(os.path.join(out, name))))


class FromZip(Fixture):
    def test_fields_found(self):
        out = self.build()
        rec = [json.loads(x) for x in open(os.path.join(out, 'results.jsonl'))]
        self.assertEqual(len(rec), 1)
        r = rec[0]
        self.assertEqual((r['key'], r['review_id'], r['status'], r['saved_prompt_id']), ('900-V1', 77, 'PASSED', 557))
        self.assertEqual(r['targets_runs'], [9001, 9002, 9003, 9004])
        self.assertEqual(r['targets_tasks'], [900])
        self.assertIn('overall_verdict', r['output']['response'])
        run = json.load(open(os.path.join(out, 'runs', '9002.json')))
        self.assertEqual((run['id'], run['_agent'], run['status'], run['aggregate_reward']), ('9002', 'CODEX', 'FAILED', 0.5))
        self.assertTrue(os.path.exists(os.path.join(out, 'runs', '9002.reward-details.json')))
        self.assertEqual(json.load(open(os.path.join(out, 'runs', '9001.json')))['status'], 'PASSED')
        self.assertTrue(os.path.exists(os.path.join(out, '_pkgs', '900', 'instruction.md')))

    def test_missing_verification(self):
        out = self.build(with_review=False)
        self.assertEqual(open(os.path.join(out, 'results.jsonl')).read(), '')
        self.assertEqual([r['task_id'] for r in self.rows(out, 'tasks.csv')], ['900'])
        self.assertIn('no verifications', open(os.path.join(out, 'build_report.txt')).read())

    def test_zip_with_no_nop_run(self):
        out = self.build(with_nop=False)
        self.assertEqual(self.rows(out, 'nop.csv'), [])
        agents = {r['agent'] for r in self.rows(out, 'newruns/index.csv')}
        self.assertEqual(agents, {'ORACLE', 'CODEX'})

    def test_nop_run_goes_to_nop_csv_not_index(self):
        out = self.build()
        self.assertEqual(self.rows(out, 'nop.csv'), [{'task_id': '900', 'nop_reward': '0.0'}])
        self.assertNotIn('9004', {r['run_id'] for r in self.rows(out, 'newruns/index.csv')})

    def test_two_revisions_use_the_latest_unless_asked(self):
        src = os.path.join(self.d, 'src')
        build_tree(src, rev=1, task_id='900')
        build_tree(src, rev=2, task_id='901')
        z = os.path.join(self.d, 'in.zip')
        zip_dir(src, z)
        out1 = os.path.join(self.d, 'o1')
        bz.main([z, out1, '--known-prompts', self.known])
        self.assertEqual([r['task_id'] for r in self.rows(out1, 'tasks.csv')], ['901'])
        self.assertIn('revision 1 (task id 900) skipped', open(os.path.join(out1, 'build_report.txt')).read())
        out2 = os.path.join(self.d, 'o2')
        bz.main([z, out2, '--all-revisions', '--known-prompts', self.known])
        self.assertEqual([r['task_id'] for r in self.rows(out2, 'tasks.csv')], ['900', '901'])

    def test_id_mapping_uses_run_id_from_path_not_the_folder_number(self):
        out = self.build()
        m = {r['eval_folder']: r for r in self.rows(out, 'run_mapping.csv')}
        self.assertEqual(m['eval_501__attempt_1__codex__gpt-x']['run_id'], '9002')
        self.assertEqual(m['eval_501__attempt_2__codex__gpt-x']['run_id'], '9003')
        self.assertEqual(m['eval_501__attempt_1__codex__gpt-x']['eval_id'], '501')
        self.assertIn('listed in a review', m['eval_500__attempt_1__oracle']['how'])

    def test_unmapped_run_gets_synthetic_id(self):
        src = os.path.join(self.d, 'src')
        build_tree(src)
        p = os.path.join(src, 'Task-A', 'rev_1__900', 'evaluations', 'eval_501__attempt_2__codex__gpt-x', 'eval_files', 'result.json')
        d = json.load(open(p))
        d['config']['task']['path'] = '/tmp/nothing'
        json.dump(d, open(p, 'w'))
        z = os.path.join(self.d, 'in.zip')
        zip_dir(src, z)
        out = os.path.join(self.d, 'out')
        bz.main([z, out, '--known-prompts', self.known])
        self.assertIn('e501a2', {r['run_id'] for r in self.rows(out, 'run_mapping.csv')})
        self.assertIn('review lists run 9003 but no evaluation folder', open(os.path.join(out, 'build_report.txt')).read())

    def test_review_on_another_prompt_is_not_used_by_default(self):
        out = self.build(review_prompt='some other prompt')
        self.assertEqual(open(os.path.join(out, 'results.jsonl')).read(), '')
        nu = self.rows(out, 'reviews_not_used.csv')
        self.assertEqual((len(nu), nu[0]['review_id']), (1, '77'))
        out2 = os.path.join(self.d, 'out_any')
        bz.main([os.path.join(self.d, 'in.zip'), out2, '--any-prompt', '--known-prompts', self.known])
        self.assertEqual(len(open(os.path.join(out2, 'results.jsonl')).read().splitlines()), 1)

    def test_extracted_folder_input_gives_same_result_as_zip(self):
        out = self.build()
        out2 = os.path.join(self.d, 'out_dir')
        bz.main([os.path.join(self.d, 'src'), out2, '--known-prompts', self.known])
        self.assertEqual(open(os.path.join(out, 'results.jsonl')).read(), open(os.path.join(out2, 'results.jsonl')).read())

    def test_zip_member_that_escapes_is_refused(self):
        z = os.path.join(self.d, 'bad.zip')
        with zipfile.ZipFile(z, 'w') as zf:
            zf.writestr('../evil.txt', 'x')
        with self.assertRaises(SystemExit):
            bz.safe_extract(z, os.path.join(self.d, 'dest'))

    def test_known_prompts_file_matches_the_two_prompts_seen_in_the_real_zips(self):
        k = json.load(open(os.path.join(P, 'known_prompts.json')))['prompts']
        ids = {v['saved_prompt_id'] for v in k.values()}
        self.assertTrue({557, 431, 145} <= ids)


class SameFormatAsV1(Fixture):
    """The export from a zip has the same files and columns as the export build_export.py makes from the downloader's folders."""

    def test_output_equals_v1_export_format(self):
        out = self.build()
        dl = os.path.join(self.d, 'dl', '900')
        os.makedirs(os.path.join(dl, 'runs'))
        os.makedirs(os.path.join(dl, 'verifications'))
        json.dump({'id': 900, 'updated_at': 't'}, open(os.path.join(dl, 'task.json'), 'w'))
        for rid, ag, rew, st in (('9001', 'ORACLE', 1.0, 'PASSED'), ('9002', 'CODEX', 0.5, 'FAILED'), ('9003', 'CODEX', 0.5, 'FAILED'), ('9004', 'NOP', 0.0, 'FAILED')):
            json.dump({'id': int(rid), '_agent': ag, 'status': st, 'aggregate_reward': rew, 'created_at': '2026-10-08T07:00:00Z', 'exception_info': ''},
                      open(os.path.join(dl, 'runs', rid + '.json'), 'w'))
        json.dump({'id': 77, 'status': 'PASSED', 'saved_prompt': {'id': 557}, 'token_usage': None, 'targets': {'evaluation_runs': [{'id': int(x)} for x in (9001, 9002, 9003, 9004)], 'tasks': [{'id': 900}]},
                   'turns': [{'output': {'response': ANSWER}}]}, open(os.path.join(dl, 'verifications', '77.json'), 'w'))
        v1 = os.path.join(self.d, 'v1out')
        subprocess.run([sys.executable, '-I', os.path.join(P, 'build_export.py'), os.path.join(self.d, 'dl'), v1],
                       check=True, capture_output=True)
        for name in ('runs.csv', 'nop.csv', 'map.csv', 'newruns/index.csv'):
            a, b = self.rows(v1, name), self.rows(out, name)
            if name == 'newruns/index.csv':
                for r in a + b:
                    r.pop('source')
                    r.pop('detail')
            self.assertEqual(sorted(map(str, a)), sorted(map(str, b)), name)
        r1 = json.loads(open(os.path.join(v1, 'results.jsonl')).readline())
        r2 = json.loads(open(os.path.join(out, 'results.jsonl')).readline())
        for k in ('key', 'review_id', 'status', 'targets_runs', 'targets_tasks', 'output'):
            self.assertEqual(r1[k], r2[k], k)


class WholePipeline(Fixture):
    def test_run_release_works_on_the_zip_export_and_ignores_judge_error_runs(self):
        out = self.build(judge_error='LLM judge infrastructure error: x')
        rel = os.path.join(self.d, 'rel')
        r = subprocess.run([sys.executable, '-I', os.path.join(P, 'run_release.py'), out, os.path.join(out, '_pkgs'), rel, '--dl', os.path.join(out, '_dl_stub'),
                            '--tasks', os.path.join(out, 'tasks.csv')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        row = list(csv.DictReader(open(os.path.join(rel, 'release_table.csv'))))[0]
        self.assertEqual(row['task_id'], '900')
        self.assertEqual(row['package_folder_found'], 'yes')
        self.assertIn('9002 (judge error', row['check1_attempts'])
        self.assertEqual(row['check1_c_fail'], 'NOT COMPUTABLE')
        self.assertEqual(row['call'], 'EVIDENCE MISSING')


if __name__ == '__main__':
    unittest.main()
