# SPDX-License-Identifier: Apache-2.0
"""step.py: cost and duration per step in run.json, "unknown" when the host gives nothing (regression specification R66)."""
import unittest

from .helpers import TempCase, read_json, run_tool


class StepTest(TempCase):
    def setUp(self):
        super().setUp()
        self.w = self.tmp / 'run'
        self.w.mkdir()

    def steps(self):
        return read_json(self.w / 'run.json')['steps']

    def test_unknown_by_default(self):
        r = run_tool('step', self.w, '--step', 'critique')
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.steps()[0]
        self.assertEqual(s['step'], 'critique')
        self.assertEqual(s['cost_usd'], 'unknown')
        self.assertEqual(s['duration_s'], 'unknown')
        self.assertRegex(s['utc'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')

    def test_measured_values(self):
        r = run_tool('step', self.w, '--step', 'vp_run', '--vp-run', 'prior_art', '--cost-usd', '0.42',
                     '--started-utc', '2026-11-14T09:00:00Z', '--ended-utc', '2026-11-14T09:25:00Z',
                     '--note', 'VP prior-art mode')
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.steps()[0]
        self.assertEqual(s['cost_usd'], 0.42)
        self.assertEqual(s['duration_s'], 1500)
        self.assertEqual(s['vp_run'], 'prior_art')

    def test_append_only(self):
        run_tool('step', self.w, '--step', 'intake')
        first = (self.w / 'run.json').read_text(encoding='utf-8')
        run_tool('step', self.w, '--step', 'tests')
        self.assertEqual([s['step'] for s in self.steps()], ['intake', 'tests'])
        self.assertIn('"intake"', first)

    def test_refusals(self):
        for args in (['--step', 'lunch'], ['--step', 'vp_run'], ['--step', 'critique', '--cost-usd', '-1'],
                     ['--step', 'critique', '--started-utc', '2026-11-14T10:00:00Z', '--ended-utc',
                      '2026-11-14T09:00:00Z']):
            with self.subTest(args=args):
                r = run_tool('step', self.w, *args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse((self.w / 'run.json').exists())

    def test_budget_refused_by_step(self):
        for _ in range(3):
            self.assertEqual(run_tool('step', self.w, '--step', 'vp_run', '--vp-run', 'x').returncode, 0)
        r = run_tool('step', self.w, '--step', 'vp_run', '--vp-run', 'y')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('budget', r.stdout + r.stderr)
        self.assertEqual(len(self.steps()), 3)


if __name__ == '__main__':
    unittest.main()
