# SPDX-License-Identifier: Apache-2.0
"""Reviewer guarantees for V3R2; independent decision fixtures, entirely offline."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .helpers import FIXTURES, load_tool, read_json, write_json
from .v2_common import V2


class ReviewerPure(unittest.TestCase):
    def setUp(self):
        self.v3 = load_tool('v3check')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)

    def checks(self, data):
        problems, warnings = [], []
        self.v3.run(self.work, data, problems, warnings)
        return problems, warnings

    def test_actual_continue_frequency_independent_of_simulator_probabilities(self):
        # c=0, s=1, zero SE: 2 -> continue; .5 -> revise; -1 -> stop.
        # Cell sd=1: 4 continue, 5 revise, 1 stop. Cell sd=2: 2, 7, 1.
        # Null draws are consumed first in each cell, but not used for power.
        estimates = [0.] * 10 + [2.] * 4 + [.5] * 5 + [-1.]
        estimates += [0.] * 10 + [2.] * 2 + [.5] * 7 + [-1.]
        test = {'sensitivity': {'power': {'robust': {
            'design': 'paired', 'n': 10, 'sd_values': [1., 2.], 'rho_values': [0.],
            'overlap': 1, 'useful_effect': .5, 'reps': 10, 'seed': 7, 'alpha': .05,
            'rule': {'continue_if_lower_above': 0., 'stop_if_upper_below': 1.}}}}}
        sim = self.v3.sim
        sim._robust_cached.cache_clear()
        self.addCleanup(sim._robust_cached.cache_clear)
        with patch.object(sim, '_series', return_value=[0.] * 10), \
                patch.object(sim, '_hac_se', side_effect=[(0., m) for m in estimates]):
            got = self.v3.power_at_minimum(test)
        self.assertEqual(got['power'], 2 / 10)  # Hand-counted; revise must be excluded.
        self.assertEqual((got['continue_count'], got['reps']), (2, 10))
        self.assertEqual(got['worst_cell'], {'sd': 2., 'rho': 0.})
        self.assertEqual([c['decision_counts'] for c in got['cells']], [
            {'continue': 4, 'revise': 5, 'stop': 1, 'indeterminate': 0},
            {'continue': 2, 'revise': 7, 'stop': 1, 'indeterminate': 0}])

    def test_default_robust_output_keeps_historical_semantics(self):
        sim = self.v3.sim
        sim._robust_cached.cache_clear()
        self.addCleanup(sim._robust_cached.cache_clear)
        args = ('paired', 10, [1.], [0.], 1, .5, 0., 1.)
        with patch.object(sim, '_series', return_value=[0.] * 10), \
                patch.object(sim, '_hac_se', return_value=(0., .5)):
            legacy = sim.robust(*args, effect_factors=(1.,), reps=10, seed=99)
            counted = sim.robust(*args, effect_factors=(1.,), reps=10, seed=99, decision_counts=True)
        self.assertEqual([c['p_continue'] for c in legacy['cells']], [1., 1.])
        self.assertEqual(legacy['power_min'], 1.)
        self.assertNotIn('decision_counts', legacy)
        self.assertTrue(all('decision_counts' not in c for c in legacy['cells']))
        for old, new in zip(legacy['cells'], counted['cells']):
            self.assertEqual({k: new[k] for k in old}, old)
            self.assertEqual(new['decision_counts'], {'continue': 0, 'revise': 10, 'stop': 0, 'indeterminate': 0})

    def test_stated_precision_accepts_rounding_and_rejects_contradiction(self):
        exact = {'power': 2 / 120, 'effect': .05, 'basis': 'fixture', 'reason': ''}
        with patch.object(self.v3, 'power_at_minimum', return_value=exact):
            for stated, mismatch in [(0.017, False), (0.016667, False), (0.02, False),
                                     (0.018, True), (1., True), (-.1, True)]:
                with self.subTest(stated=stated):
                    p, _ = self.checks({'tests.json': {'tests': [
                        {'id': 'T1', 'sensitivity': {'power_at_minimum': stated}}]}})
                    self.assertEqual(any('[POWER-MIN-MISMATCH]' in x for x in p), mismatch)

    def test_half_up_rounding_is_accepted(self):
        # Terra r3: round() rounds half to even; 0.13 is a valid two-decimal rounding of 1/8 = 0.125.
        exact = {'power': 1 / 8, 'effect': .05, 'basis': 'fixture', 'reason': ''}
        with patch.object(self.v3, 'power_at_minimum', return_value=exact):
            for stated, mismatch in [(0.13, False), (0.12, False), (0.125, False), (0.14, True)]:
                with self.subTest(stated=stated):
                    p, _ = self.checks({'tests.json': {'tests': [
                        {'id': 'T1', 'sensitivity': {'power_at_minimum': stated}}]}})
                    self.assertEqual(any('[POWER-MIN-MISMATCH]' in x for x in p), mismatch)

    def test_optional_nonnumeric_power_is_only_a_mark(self):
        for recompute in (None, 2 / 120):
            for stated in ('unknown', None, True, float('nan'), float('inf'), {}, []):
                with self.subTest(recompute=recompute, stated=stated):
                    with patch.object(self.v3, 'power_at_minimum', return_value={
                            'power': recompute, 'reason': 'missing simulation', 'effect': None}):
                        p, w = self.checks({'tests.json': {'tests': [
                            {'id': 'T1', 'sensitivity': {'power_at_minimum': stated}}]}})
                    self.assertEqual(p, [])
                    self.assertTrue(any('[POWER-INPUTS]' in x and 'power_at_minimum' in x for x in w))

    def test_label_reports_monte_carlo_count(self):
        with patch.object(self.v3, 'power_at_minimum', return_value={
                'power': 2 / 120, 'effect': .05, 'continue_count': 2, 'reps': 120}):
            self.assertIn('2/120', self.v3.power_label({}))

    def journal(self, name, count, label):
        path = self.work / name / 'state' / 'journal.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((' {"call":"read", "source":"%s"}\n' % label) * count)
        return path

    def data(self):
        return {'intake.json': {'vp': {'runs': {'a': 'a', 'b': 'b', 'main': 'main'}}},
                'rebound.json': {'ideas': [{'id': 'N1', 'prior_art': {'vp_run': 'a'}}]},
                'rebound_after.json': {'ideas': [{'id': 'N1', 'prior_art': {'vp_run': 'b'}}]}}

    def test_all_runs_for_same_neighbour_are_aggregated_before_cap(self):
        data = self.data()
        self.journal('a', 10, 'a')
        self.journal('b', 10, 'b')
        self.journal('main', 5, 'main')
        usage = self.v3.rebound_usage(self.work, data)
        self.assertEqual(len(usage['rows']), 1)
        self.assertEqual(usage['rows'][0]['calls'], 20)
        self.assertEqual(usage['rows'][0]['share'], 20 / 25)
        self.assertEqual(set(usage['rows'][0]['runs']), {'a', 'b'})
        self.assertTrue(any('[REBOUND-BUDGET]' in x and '20 calls' in x for x in self.checks(data)[1]))
        data['rebound_after.json']['ideas'][0]['prior_art']['deepen'] = {'selected': True, 'reason': 'Resolve the baseline.'}
        self.assertFalse(any('[REBOUND-BUDGET]' in x for x in self.checks(data)[1]))

    def test_hardlinks_deduplicated_but_identical_copies_both_counted(self):
        # Terra r3: same file (device, inode) counts once; two distinct journals with identical bytes count twice.
        for alias in ('hardlink', 'copy'):
            with self.subTest(alias=alias):
                data = self.data()
                source = self.journal('a', 10, 'a')
                self.journal('main', 5, 'main')
                target = self.work / 'b' / 'state' / 'journal.jsonl'
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target.unlink()
                if alias == 'hardlink':
                    os.link(source, target)
                else:
                    target.write_bytes(source.read_bytes())
                usage = self.v3.rebound_usage(self.work, data)
                n = 10 if alias == 'hardlink' else 20
                self.assertEqual(usage['total_calls'], n + 5)
                self.assertEqual(usage['rebound_calls'], n)
                self.assertEqual(usage['share'], n / float(n + 5))
                # same neighbour: 10 calls stay under the cap of 15; two real journals (20 calls) exceed it
                self.assertEqual(any('[REBOUND-BUDGET]' in x for x in self.checks(data)[1]), alias == 'copy')

    def test_partial_neighbour_is_unknown_but_known_overcap_is_marked(self):
        data = self.data()
        self.journal('a', 16, 'a')
        self.journal('main', 5, 'main')
        usage = self.v3.rebound_usage(self.work, data)
        self.assertEqual(len(usage['rows']), 1)
        self.assertIsNone(usage['rows'][0]['calls'])
        self.assertIsNone(usage['rows'][0]['share'])
        self.assertIsNone(usage['rebound_calls'])
        self.assertTrue(any('[REBOUND-BUDGET]' in x and '16 calls' in x for x in self.checks(data)[1]))


class ReviewerIntegration(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def grid(self, primary, companions):
        data = read_json(self.w / 'tests.json')
        template = data['tests'][0]
        data['tests'] = []
        for i in range(primary + companions):
            test = copy.deepcopy(template)
            test['id'] = 'T%d' % (i + 1)
            if i >= primary:
                test.update(kind='prospective', start_action='Freeze the prediction log today.', readout_date='2027-11-15')
            data['tests'].append(test)
        data['ranking']['order'] = [t['id'] for t in data['tests']]
        return data

    def check_grid(self, data):
        p, w = [], []
        self.check.check_tests(data, {'H': {'H1', 'H2'}, 'R': {'R1', 'R2'}, 'V': {'V1'}}, None, p, w)
        return p, w

    def test_prospective_only_is_marked_not_blocked(self):
        # Terra r3: mark rather than block: zero primary with prospective tests is a mark; no test at all blocks.
        for count in (1, 4):
            p, w = self.check_grid(self.grid(0, count))
            self.assertFalse(any('[GRID]' in x for x in p), p)
            self.assertTrue(any('[GRID-PRIMARY]' in x for x in w), w)
        p, _ = self.check_grid(self.grid(0, 0))
        self.assertTrue(any('[GRID]' in x and '0 primary' in x for x in p), p)

    def test_one_companion_allowed_and_extras_marked_without_hiding(self):
        self.assertEqual(self.check_grid(self.grid(3, 1))[0], [])
        data = self.grid(1, 2)
        p, w = self.check_grid(data)
        self.assertEqual(p, [])
        self.assertTrue(any('mark: [PROSPECTIVE]' in x for x in w), w)
        write_json(self.w / 'tests.json', data)
        text = load_tool('card').render(self.w)
        self.assertIn('Prospective T2:', text)
        self.assertIn('Prospective T3:', text)

    def test_old_v2_without_v3_fields_matches_fixed_golden_bytes(self):
        card = load_tool('card')
        data = read_json(self.w / 'tests.json')
        self.assertTrue(card.guards.is_v2(self.w))
        for test in data['tests']:
            self.assertFalse({'pre_critique', 'kind', 'start_action', 'readout_date'} & set(test))
            self.assertFalse({'minimum_useful_effect', 'power_at_minimum'} & set(test['sensitivity']))
        expected = (FIXTURES / 'synthetic-legacy-v2-card.md').read_bytes()
        # Framing/research helpers write current timestamps and temporary paths.
        # Pin only their opaque input fingerprint; compare every rendered byte.
        with patch.object(card.check, 'inputs_fingerprint', return_value=
                          'f5d036c9858333d63f22454467ba865124a3f8d8930297ef38917b81e62f5763'):
            rendered = card.render(self.w)
            added = [line for line in rendered.splitlines() if line.startswith('Marks: ')]
            self.assertEqual(len(added), 1)
            self.assertIn('[REVISION]', added[0])
            self.assertIn('[OVERLAP-LEDGER]', added[0])
            self.assertEqual(rendered.encode('utf-8'), expected)

    def test_empty_v3_checklist_still_shows_pitfalls_line(self):
        data = read_json(self.w / 'tests.json')
        data['tests'][0]['pre_critique'] = {}
        write_json(self.w / 'tests.json', data)
        self.assertIn('Pitfalls present:', load_tool('card').render(self.w))
