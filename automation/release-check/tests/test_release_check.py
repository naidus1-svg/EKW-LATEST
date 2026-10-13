"""Unit tests for release_check.py. Fixtures are synthetic files in the V11B1213 export layout (same keys as the real
reward-details.json and index.csv, task ids only, no task content). One integration test runs the whole script on the
synthetic export through the portable one-command runner (no verifier, no package: check 2 must read NOT COMPUTABLE).

Run: python3 tests/run_tests.py   (from any folder; path of the portable folder is found from this file)
"""
import csv
import json
import os
import sys
import hashlib
import subprocess
import tempfile
import unittest
from unittest import mock

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(H))
import release_check as rc  # noqa: E402



def details(values):
    """values: dict criterion name -> (value, weight); the shape of a real reward-details.json."""
    return {'deliverables_01': {'score': 0.0, 'criteria': [
        {'name': k, 'value': v, 'raw': 'x', 'weight': w, 'description': '', 'reasoning': ''} for k, (v, w) in values.items()]}}


def make_export(d, runs):
    """runs: list of (run_id, agent, status, task, {crit: (value, weight)} or None, exception)."""
    os.makedirs(os.path.join(d, 'newruns'))
    idx = [['run_id', 'agent', 'status', 'reward', 'cost_usd', 'task_id', 'orig_task_id', 'source', 'detail']]
    for rid, ag, st, task, det, exc in runs:
        idx.append([rid, ag, st, 0.5, 1.0, task, task, 'part3', 'reward-details' if det else ''])
        json.dump({'id': rid, 'status': st, 'exception_info': exc, 'aggregate_reward': 1.0 if st == 'PASSED' else 0.5},
                  open(os.path.join(d, 'newruns', '%s.json' % rid), 'w'))
        if det:
            json.dump(details(det), open(os.path.join(d, 'newruns', '%s.reward-details.json' % rid), 'w'))
    csv.writer(open(os.path.join(d, 'newruns', 'index.csv'), 'w', newline='')).writerows(idx)
    open(os.path.join(d, 'results.jsonl'), 'w').write(json.dumps({'key': '900-V1', 'targets_runs': [], 'targets_tasks': [900], 'status': 'PASSED'}) + '\n')


ORACLE = {'a': (1.0, .5), 'b': (1.0, .3), 'c': (1.0, .2)}


class Check1(unittest.TestCase):
    def run_c1(self, runs, min_attempts=2):
        with tempfile.TemporaryDirectory() as d:
            make_export(d, runs)
            reviews, cmap, nop, rr = rc.load_export(d)
            det = rc.find_details(d, [])
            return rc.check1('900', rr, det, d, [], min_attempts)

    def test_yes_when_all_attempts_lose_a_rule_the_oracle_earns(self):
        r = self.run_c1([(1, 'ORACLE', 'PASSED', '900', ORACLE, ''),
                         (2, 'CODEX', 'FAILED', '900', {'a': (1.0, .5), 'b': (0.0, .3), 'c': (1.0, .2)}, ''),
                         (3, 'TERMINUS-2', 'FAILED', '900', {'a': (1.0, .5), 'b': (0.0, .3), 'c': (0.0, .2)}, '')])
        self.assertEqual(r['result'], 'yes')
        self.assertEqual([x['rule'] for x in r['rows']], ['deliverables_01/b'])
        self.assertIn('only 2 attempts', r['reason'])

    def test_no_when_one_attempt_earns_the_rule(self):
        r = self.run_c1([(1, 'ORACLE', 'PASSED', '900', ORACLE, ''),
                         (2, 'CODEX', 'FAILED', '900', {'a': (1.0, .5), 'b': (0.0, .3), 'c': (1.0, .2)}, ''),
                         (3, 'TERMINUS-2', 'FAILED', '900', {'a': (1.0, .5), 'b': (1.0, .3), 'c': (0.0, .2)}, '')])
        self.assertEqual(r['result'], 'no')

    def test_partial_credit_is_not_a_loss(self):
        r = self.run_c1([(1, 'ORACLE', 'PASSED', '900', ORACLE, ''),
                         (2, 'CODEX', 'FAILED', '900', {'a': (0.5, .5), 'b': (1.0, .3), 'c': (1.0, .2)}, ''),
                         (3, 'TERMINUS-2', 'FAILED', '900', {'a': (0.0, .5), 'b': (1.0, .3), 'c': (1.0, .2)}, '')])
        self.assertEqual(r['result'], 'no')

    def test_not_computable_with_one_valid_attempt(self):
        r = self.run_c1([(1, 'ORACLE', 'PASSED', '900', ORACLE, ''),
                         (2, 'CODEX', 'FAILED', '900', {'a': (0.0, .5), 'b': (0.0, .3), 'c': (0.0, .2)}, '')])
        self.assertEqual(r['result'], 'NOT COMPUTABLE')
        self.assertIn('fewer than 2', r['reason'])

    def test_attempt_without_criterion_file_or_with_exception_is_dropped(self):
        r = self.run_c1([(1, 'ORACLE', 'PASSED', '900', ORACLE, ''),
                         (2, 'CODEX', 'FAILED', '900', None, ''),
                         (3, 'TERMINUS-2', 'FAILED', '900', {'a': (0.0, .5), 'b': (0.0, .3), 'c': (0.0, .2)}, 'infra down'),
                         (4, 'TERMINUS-2', 'FAILED', '900', {'a': (0.0, .5), 'b': (1.0, .3), 'c': (1.0, .2)}, '')])
        self.assertEqual(r['result'], 'NOT COMPUTABLE')
        self.assertIn('1 found', r['reason'])
        self.assertIn('2 (no per-criterion file)', r['attempts'])

    def test_not_computable_without_reference_run(self):
        r = self.run_c1([(2, 'CODEX', 'FAILED', '900', {'a': (0.0, .5)}, ''), (3, 'TERMINUS-2', 'FAILED', '900', {'a': (0.0, .5)}, '')])
        self.assertEqual(r['result'], 'NOT COMPUTABLE')
        self.assertIn('reference', r['reason'])

    def test_failed_oracle_is_not_a_reference(self):
        r = self.run_c1([(1, 'ORACLE', 'FAILED', '900', ORACLE, ''), (2, 'CODEX', 'FAILED', '900', {'a': (0.0, .5)}, ''),
                         (3, 'TERMINUS-2', 'FAILED', '900', {'a': (0.0, .5)}, '')])
        self.assertEqual(r['result'], 'NOT COMPUTABLE')

    def test_min_attempts_three_makes_two_attempts_not_computable(self):
        runs = [(1, 'ORACLE', 'PASSED', '900', ORACLE, ''), (2, 'CODEX', 'FAILED', '900', {'a': (0.0, .5)}, ''),
                (3, 'TERMINUS-2', 'FAILED', '900', {'a': (0.0, .5)}, '')]
        self.assertEqual(self.run_c1(runs, 3)['result'], 'NOT COMPUTABLE')
        self.assertEqual(self.run_c1(runs, 2)['result'], 'yes')

    def test_empty_answer_run_is_not_an_attempt(self):
        r = self.run_c1([(1, 'ORACLE', 'PASSED', '900', ORACLE, ''), (2, 'NOP', 'FAILED', '900', {'a': (0.0, .5)}, ''),
                         (3, 'CODEX', 'FAILED', '900', {'a': (0.0, .5)}, '')])
        self.assertEqual(r['result'], 'NOT COMPUTABLE')


class Overall(unittest.TestCase):
    def test_truth_table(self):
        o = rc.overall
        self.assertEqual(o('yes', 'NOT COMPUTABLE', 'CANT_JUDGE'), 'HOLD')
        self.assertEqual(o('no', 'no', 'HOLD'), 'HOLD')
        self.assertEqual(o('no', 'yes', 'SEND'), 'HOLD')
        self.assertEqual(o('no', 'NOT COMPUTABLE', 'SEND'), 'NEEDS INPUT')
        self.assertEqual(o('no', 'no', 'CANT_JUDGE'), 'NEEDS INPUT')
        self.assertEqual(o('NOT COMPUTABLE', 'no', 'SEND'), 'NEEDS INPUT')
        self.assertEqual(o('no', 'no', 'SEND'), 'RELEASE')


class Gate(unittest.TestCase):
    def build(self, extra):
        d = tempfile.mkdtemp()
        reviews = [{'key': '900-V%d' % i, 'status': 'PASSED'} for i in range(1, 5)]
        g = rc.build_gate_dir(d, None, reviews, {'900': '0.0'}, {'900': ('x', 'EKW')}, 557, 1, os.path.join(d, 'gate'))
        for name, rows in extra.items():
            csv.writer(open(os.path.join(g, name + '.csv'), 'w', newline='')).writerows(rows)
        return g

    def test_cant_judge_names_missing_inputs(self):
        g = self.build({})
        r = rc.check3(g, 557, 1, 4)['900']
        self.assertEqual(r['verdict'], 'CANT_JUDGE')
        self.assertIn('P0', r['cant_judge'])
        self.assertIn('S1', r['cant_judge'])

    def test_send_when_all_inputs_present_and_clean(self):
        g = self.build({'preflight': [['task_id', 'package_exported', 'grader_files', 'runs_current'], ['900', 'yes', 'yes', 'yes']],
                        'step1': [['task_id', 'verdict', 'unresolved_material', 'items'], ['900', 'PASS', '0', '']],
                        'review': [['task_id', 'run_id', 'spec_id', 'version', 'status', 'n_reviews', 'finished_at', 'last_edit_at', 'major_counts', 'fix_items', 'fix_list', 'nop_rewards'],
                                   ['900', '1', '557', '1', 'COMPLETED', '4', '2026-10-08T03:00:00-04:00', '2026-10-08T01:00:00-04:00', '0,0,0,0', '0', '', '0.0']]})
        self.assertEqual(rc.check3(g, 557, 1, 4)['900']['verdict'], 'SEND')

    def test_hold_when_empty_answer_earned_reward(self):
        g = self.build({'preflight': [['task_id', 'package_exported', 'grader_files', 'runs_current'], ['900', 'yes', 'yes', 'yes']],
                        'step1': [['task_id', 'verdict', 'unresolved_material', 'items'], ['900', 'PASS', '0', '']]})
        d = os.path.dirname(g)
        csv.writer(open(os.path.join(d, 'nop.csv'), 'w', newline='')).writerows([['task_id', 'nop_reward'], ['900', '0.15']])
        reviews = [{'key': '900-V%d' % i, 'status': 'PASSED'} for i in range(1, 5)]
        os.remove(os.path.join(g, 'review.csv'))
        rc.build_gate_dir(d, None, reviews, {'900': '0.15'}, {'900': ('x', 'EKW')}, 557, 1, g)
        r = rc.check3(g, 557, 1, 4)['900']
        self.assertEqual(r['verdict'], 'HOLD')
        self.assertIn('R3', r['hold'])


FOLDER = os.path.dirname(H)


# a stand-in for vendor/step2/step2_v11.py that prints text no Windows code page can hold, plus a byte that is not UTF-8
FAKE_STEP2 = '''import os, sys
print('stdout: r\\u00e9sum\\u00e9 \\u2192 \\u672c\\u8a9e \\u2713')
sys.stdout.flush()
sys.stdout.buffer.write(b'raw: bad \\xff byte\\n')
sys.stderr.write('stderr: \\u20ac \\u00fcn\\u00efcode\\n')
out = sys.argv[3]
os.makedirs(out, exist_ok=True)
open(os.path.join(out, 'verdicts.csv'), 'w').write('task_id,verdict\\n')
open(os.path.join(out, 'fixlist.csv'), 'w').write('task_id,type\\n')
'''


class Step2Log(unittest.TestCase):
    def test_child_output_is_read_and_logged_as_utf8_whatever_the_code_page(self):
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, 'vendor', 'step2')
            os.makedirs(fake)
            with open(os.path.join(fake, 'step2_v11.py'), 'w', encoding='utf-8') as f:
                f.write(FAKE_STEP2)
            exp = os.path.join(d, 'exp')
            os.makedirs(exp)
            open(os.path.join(exp, 'results.jsonl'), 'w').close()
            # a parent whose environment asks the child for a narrow code page: the child must still write UTF-8
            with mock.patch.dict(os.environ, {'PYTHONIOENCODING': 'cp1252'}), mock.patch.object(rc, 'FINAL', os.path.join(d, 'vendor')):
                rows, fix, code, s2 = rc.run_step2(exp, d, os.path.join(d, 'out'), None, False, set(), None)
            self.assertEqual((code, rows, fix), (0, {}, []))
            with open(os.path.join(s2, 'step2.log'), 'rb') as f:
                log = f.read().decode('utf-8')  # strict: the log file itself is valid UTF-8
            self.assertIn('stdout: résumé → 本語 ✓', log)
            self.assertIn('stderr: € ünïcode', log)
            self.assertIn('raw: bad � byte', log)  # a byte that is not UTF-8 becomes U+FFFD, it does not stop the run


class Portable(unittest.TestCase):
    def test_no_absolute_sandbox_path_in_code_we_wrote(self):
        for f in ('release_check.py', 'run_release.py', 'make_table.py'):
            self.assertNotIn('/root/', open(os.path.join(FOLDER, f)).read(), f)

    def test_vendored_files_match_recorded_sha256(self):
        n = 0
        for line in open(os.path.join(FOLDER, 'VENDORED.sha256')):
            h, rel = line.split(None, 1)
            rel = rel.strip()
            self.assertEqual(hashlib.sha256(open(os.path.join(FOLDER, rel), 'rb').read()).hexdigest(), h, rel)
            n += 1
        self.assertGreaterEqual(n, 10)

    def test_one_command_end_to_end_on_synthetic_export(self):
        with tempfile.TemporaryDirectory() as d:
            exp, out, pk, dl = [os.path.join(d, x) for x in ('exp', 'out', 'pk', 'dl')]
            os.makedirs(exp)
            os.makedirs(pk)
            os.makedirs(os.path.join(dl, '900', 'verifications'))
            make_export(exp, [(1, 'ORACLE', 'PASSED', '900', ORACLE, ''),
                              (2, 'CODEX', 'FAILED', '900', {'a': (1.0, .5), 'b': (0.0, .3), 'c': (1.0, .2)}, ''),
                              (3, 'TERMINUS-2', 'FAILED', '900', {'a': (1.0, .5), 'b': (0.0, .3), 'c': (0.0, .2)}, '')])
            json.dump({'updated_at': '2026-01-01T00:00:00Z'}, open(os.path.join(dl, '900', 'task.json'), 'w'))
            for i in range(2):
                json.dump({'saved_prompt': {'id': 557}, 'status': 'PASSED', 'updated_at': '2026-01-02T00:00:00Z', '_archived': False},
                          open(os.path.join(dl, '900', 'verifications', '%d.json' % i), 'w'))
            p = subprocess.run([sys.executable, '-I', os.path.join(FOLDER, 'run_release.py'), exp, pk, out, '--dl', dl],
                               capture_output=True, text=True, cwd=d)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            rows = list(csv.DictReader(open(os.path.join(out, 'release_table.csv'))))
            self.assertEqual(len(rows), 1)
            r = rows[0]
            self.assertEqual((r['check1_c_fail'], r['check1_at_3_attempts']), ('yes', 'NOT COMPUTABLE'))
            self.assertEqual(r['check2_v11'], 'NOT COMPUTABLE')
            self.assertEqual(r['check3_gate'], 'CANT_JUDGE')
            self.assertEqual((r['call'], r['call_with_check1_at_3_attempts']), ('HOLD', 'EVIDENCE MISSING'))
            self.assertEqual((r['answer_check_v11_review_count'], r['review_newer_than_last_edit'], r['package_folder_found']), ('2', 'yes', 'no'))

    def test_build_export_from_download_folder(self):
        with tempfile.TemporaryDirectory() as d:
            dl, out = os.path.join(d, 'dl'), os.path.join(d, 'exp')
            f = os.path.join(dl, '900')
            os.makedirs(os.path.join(f, 'runs'))
            os.makedirs(os.path.join(f, 'verifications'))
            json.dump({'updated_at': '2026-01-01T00:00:00Z'}, open(os.path.join(f, 'task.json'), 'w'))
            for rid, ag, rew in ((1, 'ORACLE', 1.0), (2, 'CODEX', 0.4), (3, 'NOP', 0.0)):
                json.dump({'id': str(rid), '_agent': ag, 'status': 'PASSED', 'aggregate_reward': rew, 'created_at': '2026-01-01'},
                          open(os.path.join(f, 'runs', '%d.json' % rid), 'w'))
                json.dump(details({'a': (1.0, 1.0)}), open(os.path.join(f, 'runs', '%d.reward-details.json' % rid), 'w'))
            for vid, spec in ((10, 557), (11, 557), (12, 400)):
                json.dump({'id': str(vid), 'saved_prompt': {'id': spec}, 'status': 'PASSED', '_archived': False, 'updated_at': 'x',
                           'targets': {'tasks': [{'id': 900}], 'evaluation_runs': [{'id': 1}, {'id': 2}]},
                           'turns': [{'output': {'response': 'r'}}]}, open(os.path.join(f, 'verifications', '%d.json' % vid), 'w'))
            import build_export as be
            be.main([dl, out])
            recs = [json.loads(x) for x in open(os.path.join(out, 'results.jsonl'))]
            self.assertEqual([r['key'] for r in recs], ['900-V1', '900-V2'])
            self.assertEqual(recs[0]['targets_runs'], [1, 2])
            self.assertEqual(list(csv.DictReader(open(os.path.join(out, 'nop.csv')))), [{'task_id': '900', 'nop_reward': '0.0'}])
            self.assertEqual([r['agent'] for r in csv.DictReader(open(os.path.join(out, 'newruns', 'index.csv')))], ['ORACLE', 'CODEX'])


if __name__ == '__main__':
    unittest.main()
