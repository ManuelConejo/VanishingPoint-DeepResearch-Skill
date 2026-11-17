# SPDX-License-Identifier: Apache-2.0
"""log.py: append-only decision journal, before then after (regression specification R23, R27)."""
import hashlib
import json
import shutil
import unittest

from .helpers import TempCase, load_tool, mutate, read_json, run_tool


class LogBase(TempCase):
    def setUp(self):
        super().setUp()
        self.w = self.tmp / 'run'
        self.w.mkdir()
        # modified round 2 (R37): a "before" of a test needs the test in tests.json, whose fingerprint it freezes
        shutil.copy2(str(self.work('valid_novp') / 'tests.json'), str(self.w / 'tests.json'))
        self.log = self.w / 'decision_log.jsonl'

    def lines(self):
        return [json.loads(x) for x in self.log.read_text(encoding='utf-8').splitlines() if x.strip()]


class LogTest(LogBase):
    def test_after_without_before_refused(self):
        r = run_tool('log', self.w, 'after', '--test', 'T1', '--text', 'did it')
        self.assertEqual(r.returncode, 1)
        self.assertIn('before', r.stdout + r.stderr)
        self.assertFalse(self.log.exists())

    def test_before_then_after(self):
        r = run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'would drop if no gain')
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_tool('log', self.w, 'after', '--test', 'T1', '--text', 'gain seen, running T2')
        self.assertEqual(r.returncode, 0, r.stderr)
        ls = self.lines()
        self.assertEqual([x['phase'] for x in ls], ['before', 'after'])
        self.assertEqual(ls[0]['by'], 'researcher')
        self.assertTrue(ls[0]['utc'].endswith('Z'))

    def test_after_needs_before_of_same_test(self):
        run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'x')
        r = run_tool('log', self.w, 'after', '--test', 'T2', '--text', 'y')
        self.assertEqual(r.returncode, 1)

    def test_before_after_an_after_refused(self):
        run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'x')
        run_tool('log', self.w, 'after', '--test', 'T1', '--text', 'y')
        r = run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'too late')
        self.assertEqual(r.returncode, 1)

    def test_assumption_flag(self):
        run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'assumed', '--assumption')
        self.assertEqual(self.lines()[0]['by'], 'assumption')

    def test_append_only(self):
        run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'first')
        first = self.log.read_bytes()
        run_tool('log', self.w, 'before', '--test', 'T2', '--text', 'second')
        self.assertTrue(self.log.read_bytes().startswith(first))
        self.assertEqual(len(self.lines()), 2)

    def test_corrupt_log_refused(self):
        self.log.write_text('not json\n', encoding='utf-8')
        r = run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'x')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.log.read_text(encoding='utf-8'), 'not json\n')

    def test_empty_text_refused(self):
        r = run_tool('log', self.w, 'before', '--test', 'T1', '--text', '  ')
        self.assertNotEqual(r.returncode, 0)

    def test_entries_match_schema(self):
        run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'x')
        schema = json.loads((load_tool('check').SCHEMAS / 'decision_log_entry.json').read_text(encoding='utf-8'))
        self.assertEqual(load_tool('schema_lite').validate(self.lines()[0], schema), [])


def expected_fingerprint(test):
    """Independent implementation of the R37 definition (regression specification)."""
    sens = test.get('sensitivity') or {}
    sim = sens.get('simulation')
    if isinstance(sim, dict):
        params = {k: sim.get(k) for k in ('design', 'n', 'sd', 'base', 'alpha', 'reps', 'seed', 'threshold', 'rule')}
        params['scenarios'] = [{'name': s.get('name'), 'effect': s.get('effect'), 'expected': s.get('expected')}
                               for s in sim.get('scenarios') or []]
    else:
        params = {'not_applicable': sens.get('simulation_not_applicable')}
    obj = {'predictions': test.get('predictions'), 'decision_rule': test.get('decision_rule'),
           'simulation_parameters': params}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


class FingerprintTest(LogBase):
    """R37: log.py before freezes the fingerprint of predictions + decision rule + simulation parameters."""

    def test_before_records_fingerprint(self):
        r = run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'x')
        self.assertEqual(r.returncode, 0, r.stderr)
        tests = read_json(self.w / 'tests.json')['tests']
        self.assertEqual(self.lines()[0]['fingerprint'], expected_fingerprint(tests[0]))
        run_tool('log', self.w, 'before', '--test', 'T2', '--text', 'y')
        self.assertEqual(self.lines()[1]['fingerprint'], expected_fingerprint(tests[1]))

    def test_fingerprint_follows_rule_predictions_and_sim_params(self):
        tests = read_json(self.w / 'tests.json')['tests']
        base = expected_fingerprint(tests[0])
        for change in (lambda t: t['decision_rule'].update(stop_if='CI below 2 positions.'),
                       lambda t: t['predictions'][0].update(interval=[2, 10]),
                       lambda t: t['sensitivity']['simulation'].update(n=150)):
            with self.subTest():
                self.fresh()
                mutate(self.w, 'tests.json', lambda d: change(d['tests'][0]))
                run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'x')
                fp = self.lines()[0]['fingerprint']
                self.assertNotEqual(fp, base)
                self.assertEqual(fp, expected_fingerprint(read_json(self.w / 'tests.json')['tests'][0]))

    def test_fingerprint_ignores_other_fields(self):
        tests = read_json(self.w / 'tests.json')['tests']
        mutate(self.w, 'tests.json', lambda d: d['tests'][0].update(title='Another title'))
        run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'x')
        self.assertEqual(self.lines()[0]['fingerprint'], expected_fingerprint(tests[0]))

    def test_before_needs_tests_json(self):
        (self.w / 'tests.json').unlink()
        r = run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'x')
        self.assertEqual(r.returncode, 1)
        self.assertIn('tests.json', r.stdout + r.stderr)
        self.assertFalse(self.log.exists())

    def test_before_needs_the_test(self):
        r = run_tool('log', self.w, 'before', '--test', 'T7', '--text', 'x')
        self.assertEqual(r.returncode, 1)
        self.assertFalse(self.log.exists())

    def test_idea_entry_has_no_fingerprint(self):
        (self.w / 'tests.json').unlink()
        r = run_tool('log', self.w, 'before', '--test', 'idea', '--text', 'would drop the idea if prior art exists')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('fingerprint', self.lines()[0])

    def test_after_has_no_fingerprint(self):
        run_tool('log', self.w, 'before', '--test', 'T1', '--text', 'x')
        run_tool('log', self.w, 'after', '--test', 'T1', '--text', 'y')
        self.assertNotIn('fingerprint', self.lines()[1])


if __name__ == '__main__':
    unittest.main()
