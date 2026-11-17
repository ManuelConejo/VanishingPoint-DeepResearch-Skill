# SPDX-License-Identifier: Apache-2.0
"""sim.py: simple sensitivity simulation, standard library, fixed seed (regression specification R24)."""
import json
import unittest

from .helpers import TempCase, load_tool, read_json, run_tool


def args(design='means', n=100, sd=1.0, extra=()):
    a = ['--design', design, '--n', str(n), '--sd', str(sd), '--seed', '7', '--reps', '400',
         '--continue-if-lower-above', '0', '--stop-if-upper-below', '0.2']
    return a + list(extra)


class SimTest(TempCase):
    def run_json(self, a):
        r = run_tool('sim', *a)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_deterministic(self):
        a = args(extra=['--scenario', 'H1=0.6', '--scenario', 'R1=0', '--expect', 'H1=continue', '--expect', 'R1=stop'])
        self.assertEqual(self.run_json(a), self.run_json(a))

    def test_output_shape(self):
        out = self.run_json(args(extra=['--scenario', 'H1=0.6', '--scenario', 'R1=0',
                                        '--expect', 'H1=continue', '--expect', 'R1=stop']))
        self.assertEqual(out['tool'], 'frontier/sim.py')
        self.assertEqual(out['seed'], 7)
        self.assertEqual(len(out['scenarios']), 2)
        for s in out['scenarios']:
            total = s['p_continue'] + s['p_revise'] + s['p_stop'] + s['p_indeterminate']
            self.assertAlmostEqual(total, 1.0, places=6)
            self.assertIn('p_expected', s)
        self.assertIn('distinguishes', out)

    def test_large_effect_distinguishes(self):
        out = self.run_json(args(n=800, extra=['--scenario', 'H1=0.8', '--scenario', 'R1=0',
                                               '--expect', 'H1=continue', '--expect', 'R1=stop']))
        self.assertTrue(out['distinguishes'])
        h1 = [s for s in out['scenarios'] if s['name'] == 'H1'][0]
        self.assertGreater(h1['p_continue'], 0.95)

    def test_tiny_effect_does_not(self):
        out = self.run_json(args(n=20, extra=['--scenario', 'H1=0.05', '--scenario', 'R1=0',
                                              '--expect', 'H1=continue', '--expect', 'R1=stop']))
        self.assertFalse(out['distinguishes'])

    def test_proportions(self):
        out = self.run_json(['--design', 'proportions', '--n', '500', '--base', '0.2', '--seed', '3', '--reps', '300',
                             '--continue-if-lower-above', '0', '--stop-if-upper-below', '0.03',
                             '--scenario', 'H1=0.1', '--scenario', 'R1=0', '--expect', 'H1=continue', '--expect', 'R1=stop'])
        self.assertEqual(out['design'], 'proportions')
        h1 = [s for s in out['scenarios'] if s['name'] == 'H1'][0]
        self.assertGreater(h1['p_continue'], 0.9)

    def test_paired(self):
        out = self.run_json(args(design='paired', n=200, sd=5, extra=[
            '--scenario', 'H1=3', '--scenario', 'R1=0', '--expect', 'H1=continue', '--expect', 'R1=indeterminate']))
        self.assertEqual(out['design'], 'paired')
        self.assertGreater(out['scenarios'][0]['p_continue'], 0.95)

    def test_revise_branch(self):
        # real but small effect: CI above 0 and below the useful threshold -> revise
        out = self.run_json(['--design', 'paired', '--n', '5000', '--sd', '1', '--seed', '1', '--reps', '200',
                             '--continue-if-lower-above', '0', '--stop-if-upper-below', '0.2',
                             '--scenario', 'small=0.1', '--expect', 'small=revise', '--scenario', 'none=0', '--expect', 'none=stop'])
        small = out['scenarios'][0]
        self.assertGreater(small['p_revise'], 0.9)

    def test_bad_input_refused(self):
        r = run_tool('sim', '--design', 'means', '--n', '1', '--sd', '1', '--scenario', 'H1=1', '--scenario', 'R1=0')
        self.assertNotEqual(r.returncode, 0)
        r = run_tool('sim', '--design', 'proportions', '--n', '10', '--base', '0.9', '--scenario', 'H1=0.5', '--scenario', 'R1=0')
        self.assertNotEqual(r.returncode, 0)
        r = run_tool('sim', '--design', 'means', '--n', '10', '--sd', '1', '--scenario', 'H1=1')
        self.assertNotEqual(r.returncode, 0, 'at least two scenarios')

    # modified round 2 (R41): the thresholds simulated are those of decision_rule.thresholds (0 and 1 for T1)
    def test_write_into_tests_json(self):
        work = self.work('valid_novp')
        a = args(design='paired', n=200, sd=5, extra=[
            '--scenario', 'H1=3', '--scenario', 'R1=0', '--expect', 'H1=continue', '--expect', 'R1=stop',
            '--write-into', work / 'tests.json', '--test', 'T1'])
        a[a.index('--stop-if-upper-below') + 1] = '1'
        r = run_tool('sim', *a)
        self.assertEqual(r.returncode, 0, r.stderr)
        t1 = read_json(work / 'tests.json')['tests'][0]
        self.assertEqual(t1['sensitivity']['simulation']['seed'], 7)
        self.assertEqual(load_tool('check').problems(work), [])

    def test_write_into_uses_rule_thresholds(self):
        """R41: other thresholds than the rule's are refused; without thresholds, the rule's are simulated."""
        work = self.work('valid_novp')
        bad = run_tool('sim', *args(design='paired', n=200, sd=5, extra=[
            '--scenario', 'H1=3', '--scenario', 'R1=0', '--write-into', work / 'tests.json', '--test', 'T1']))
        self.assertNotEqual(bad.returncode, 0)
        r = run_tool('sim', '--design', 'paired', '--n', '200', '--sd', '5', '--scenario', 'H1=3', '--scenario', 'R1=0',
                     '--expect', 'H1=continue', '--expect', 'R1=stop', '--write-into', work / 'tests.json',
                     '--test', 'T1')
        self.assertEqual(r.returncode, 0, r.stderr)
        t1 = read_json(work / 'tests.json')['tests'][0]
        self.assertEqual(t1['sensitivity']['simulation']['rule'],
                         {'continue_if_lower_above': 0.0, 'stop_if_upper_below': 1.0})
        self.assertEqual(t1['decision_rule']['thresholds'], t1['sensitivity']['simulation']['rule'])

    def test_rerun_and_compare(self):
        """R40: rerun() gives back the stored block; compare() names a difference."""
        sim = load_tool('sim')
        out = sim.simulate('paired', 50, 5.0, [('H1', 3.0, 'continue'), ('R1', 0.0, 'stop')], 0.0, 1.0, reps=300)
        self.assertEqual(sim.compare(out, sim.rerun(out)), [])
        forged = json.loads(json.dumps(out))
        forged['scenarios'][1]['p_stop'] = 0.99
        self.assertTrue(sim.compare(forged, sim.rerun(forged)))

    def test_write_into_unknown_test(self):
        work = self.work('valid_novp')
        r = run_tool('sim', *args(extra=['--scenario', 'H1=1', '--scenario', 'R1=0',
                                         '--write-into', work / 'tests.json', '--test', 'T9']))
        self.assertNotEqual(r.returncode, 0)

    def test_function_api(self):
        sim = load_tool('sim')
        out = sim.simulate('means', n=50, sd=1.0, scenarios=[('H1', 1.0, 'continue'), ('R1', 0.0, 'stop')],
                           continue_if_lower_above=0.0, stop_if_upper_below=0.3, reps=200, seed=5)
        self.assertEqual(out['reps'], 200)


if __name__ == '__main__':
    unittest.main()
