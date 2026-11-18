# SPDX-License-Identifier: Apache-2.0
"""Debates-only arithmetic oracles adapted from the reference tournament tests.
Expected Elo values and presentation orders are hand computed, not tool output.
Written and run before the tournament implementation.
"""
import copy
import math
import unittest
from .helpers import FRONTIER, load_tool, read_json


def settings(**changes):
    cfg = dict(max_debates=1, top_count=1, initial_rating=1000, k_factor=32,
               rating_scale=400, rating_base=10, debate_max_words=180,
               criteria=['coherence', 'testability', 'distinctiveness', 'limits'])
    cfg.update(changes)
    return cfg


def scope():
    return dict(candidate_kind='ideas', question='Which lead should be explored next?',
                hypothesis_ids=['H1'], test_ids=['T1'],
                settings_rationale='Small budget; uncalibrated design assumptions.')


def debate(a='A', b='B', result='a'):
    return dict(a=a, b=b, result=result, route='author', judge_family='unknown',
                input_sha256='a' * 64,
                comparison=dict(a_case='Case for A.', b_case='Case for B.',
                                objection='Shared limit.', reason='Provisional choice.',
                                hypothesis_ids=['H1'], test_ids=['T1'],
                                proposed_change='Add a blinded positive control.'))


class TournamentOracle(unittest.TestCase):

    def test_balanced_positions_and_fixed_budget(self):
        s = self.state(max_debates=4)
        for a, b in [('A', 'B'), ('B', 'A'), ('A', 'B'), ('B', 'A')]:
            self.assertEqual(self.t.next_pair(s), [a, b])
            s = self.t.record(s, debate(a, b, 'tie'))
        self.assertIsNone(self.t.next_pair(s))
        self.assertTrue(self.t.stats(s)['complete'])
        self.assertEqual(self.t.stats(s)['positions'],
                         {'A': {'first': 2, 'second': 2}, 'B': {'first': 2, 'second': 2}})
        with self.assertRaises(ValueError):
            self.t.record(s, debate())

    def test_unscheduled_pair_or_order_refused_without_mutation(self):
        s = self.state(('A', 'B', 'C'))
        before = copy.deepcopy(s)
        for d in (debate('A', 'C'), debate('B', 'A')):
            with self.assertRaisesRegex(ValueError, 'scheduled'):
                self.t.record(s, d)
            self.assertEqual(s, before)

    def test_no_observations_draws_or_unseen_candidates_do_not_claim_top(self):
        states = [self.state(max_debates=0),
                  self.t.record(self.state(), debate(result='tie')),
                  self.t.record(self.state(k_factor=0), debate()),
                  self.t.record(self.state(('A', 'B', 'C')), debate())]
        for state in states:
            self.assertEqual(self.t.stats(state)['top_ids'], [])

    def test_cutoff_ties_remain_visible(self):
        s = self.state(('A', 'B', 'C', 'D'), max_debates=2)
        for a, b, result in [('A', 'B', 'a'), ('D', 'C', 'b')]:
            s = self.t.record(s, debate(a, b, result))
        self.assertEqual(self.t.stats(s)['top_ids'], ['A', 'C'])

    def test_scope_and_only_rebound_source_required(self):
        for source, sc in [('rebound.json', None), ('hypotheses.json', scope()),
                           ('rebound_after.json', scope()),
                           ('rebound.json', dict(scope(), candidate_kind='hypotheses'))]:
            with self.assertRaises(ValueError):
                self.t.create(source, ['A', 'B'], settings(), sc)

    def test_bad_config_values(self):
        for change in ({'k_factor': -1}, {'rating_scale': 0}, {'rating_base': 1},
                       {'initial_rating': math.nan}, {'top_count': True},
                       {'max_debates': -1}, {'max_debates': 1.5}, {'criteria': []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.state(**change)

    def test_schema_and_code_agree_on_open_numeric_boundaries(self):
        validator = load_tool('schema_lite').validate
        schema = read_json(FRONTIER / 'schemas' / 'tournament.json')
        for key, bad, good in [('rating_scale', 0, 1e-300),
                               ('rating_base', 1, math.nextafter(1, 2))]:
            state = self.state()
            state['config'][key] = bad
            self.assertTrue(validator(state, schema))
            with self.assertRaises(ValueError):
                self.t.validate_state(state)
            state['config'][key] = good
            self.assertEqual(validator(state, schema), [])
            self.t.validate_state(state)

    def test_schema_rejects_nonfinite_numbers(self):
        validator = load_tool('schema_lite').validate
        for value in (math.nan, math.inf, -math.inf):
            self.assertTrue(validator(value, {'type': 'number'}))

    def test_numeric_claims_are_estimates_with_assumptions(self):
        d = debate()
        d['comparison']['numerical_claims'] = [dict(value=0.7, status='measured', assumptions='Hypothetical.')]
        with self.assertRaises(ValueError):
            self.t.record(self.state(), d)
        d['comparison']['numerical_claims'][0]['status'] = 'estimate'
        self.t.validate_state(self.t.record(self.state(), d))
        d['comparison']['numerical_claims'][0]['assumptions'] = ''
        with self.assertRaises(ValueError):
            self.t.record(self.state(), d)

    def test_replay_detects_tampering(self):
        state = self.t.record(self.state(), debate())
        for mutate in (lambda s: s['matches'][0].update(a='B', b='A'),
                       lambda s: s['matches'][0].update(a='Z'),
                       lambda s: s['matches'][0].update(result='unknown'),
                       lambda s: s['config'].update(rating_scale=0),
                       lambda s: s['candidates'].append({'id': 'A'})):
            changed = copy.deepcopy(state)
            mutate(changed)
            with self.assertRaises(ValueError):
                self.t.validate_state(changed)

    @classmethod
    def setUpClass(cls):
        cls.t = load_tool('tournament')

    def state(self, ids=('A', 'B'), **cfg):
        state = self.t.create('rebound.json', list(ids), settings(**cfg), scope())
        # Arithmetic fixtures have no source directory, but accepted journals
        # still need complete provenance snapshots.
        state['original_statements'] = {i: 'Original statement for ' + i for i in ids}
        state['source_digests'] = [{'id': i, 'sha256': 'a' * 64} for i in ids]
        return state

    def test_schema_and_validation_require_both_snapshots(self):
        validator = load_tool('schema_lite').validate
        schema = read_json(FRONTIER / 'schemas' / 'tournament.json')
        for key in ('source_digests', 'original_statements'):
            state = self.t.record(self.state(), debate())
            del state[key]
            with self.subTest(key=key, surface='schema'):
                self.assertTrue(validator(state, schema))
            with self.subTest(key=key, surface='validate_state'):
                with self.assertRaisesRegex(ValueError, key):
                    self.t.validate_state(state)

    def test_required_debate_attribution_and_comparison_text(self):
        validator = load_tool('schema_lite').validate
        schema = self.t.definition('match')
        bad = []
        for key in ('route', 'judge_family', 'comparison'):
            d = debate()
            del d[key]
            bad.append((key, d))
        for value in ('', '   '):
            bad.append(('judge_family', dict(debate(), judge_family=value)))
        bad.append(('comparison', dict(debate(), comparison={})))
        for key in self.t.COMPARISON_FIELDS:
            for value in (None, '', '   '):
                d = debate()
                if value is None:
                    del d['comparison'][key]
                else:
                    d['comparison'][key] = value
                bad.append((key, d))
        for key, d in bad:
            with self.subTest(key=key, debate=d, surface='schema'):
                self.assertTrue(validator(d, schema))
            with self.subTest(key=key, debate=d, surface='record'):
                state = self.state()
                before = copy.deepcopy(state)
                with self.assertRaisesRegex(ValueError, key):
                    self.t.record(state, d)
                self.assertEqual(state, before)

    def test_equal_ratings_win(self):
        s = self.t.record(self.state(), debate())
        self.assertEqual(self.t.ratings(s), {'A': 1016, 'B': 984})

    def test_equal_ratings_loss(self):
        s = self.t.record(self.state(), debate(result='b'))
        self.assertEqual(self.t.ratings(s), {'A': 984, 'B': 1016})

    def test_equal_ratings_tie(self):
        s = self.t.record(self.state(), debate(result='tie'))
        self.assertEqual(self.t.ratings(s), {'A': 1000, 'B': 1000})
        self.assertEqual(self.t.stats(s)['top_ids'], [])

    def test_unequal_tie_hand_computed(self):
        a, b = self.t.elo(1400, 1000, 'tie', settings())
        self.assertAlmostEqual(a, 1400 - 144 / 11)
        self.assertAlmostEqual(b, 1000 + 144 / 11)

    def test_upset_and_conservation(self):
        a, b = self.t.elo(1400, 1000, 'b', settings())
        self.assertAlmostEqual(a, 1400 - 320 / 11)
        self.assertAlmostEqual(a + b, 2400)

    def test_sequential_not_batch_updates(self):
        s = self.state(max_debates=2)
        s = self.t.record(s, debate())
        s = self.t.record(s, debate('B', 'A'))
        delta = 32 * (1 - 1 / (1 + 10 ** (32 / 400)))
        self.assertAlmostEqual(self.t.ratings(s)['B'], 984 + delta)
        self.assertAlmostEqual(sum(self.t.ratings(s).values()), 2000)

    def test_no_intermediate_rounding(self):
        a, b = self.t.elo(1016, 984, 'tie', settings())
        self.assertNotEqual(a, round(a))
        self.assertAlmostEqual(a + b, 2000)

    def test_extreme_rating_gap_stays_finite(self):
        a, b = self.t.elo(1e9, -1e9, 'b', settings())
        self.assertEqual((a, b), (1e9 - 32, -1e9 + 32))

    def test_custom_named_parameters(self):
        a, b = self.t.elo(600, 600, 'a', settings(k_factor=20, rating_scale=200))
        self.assertEqual((a, b), (610, 590))  # 20*(1-1/2)=10
        self.assertEqual(self.t.ratings(self.state(initial_rating=600)), {'A': 600, 'B': 600})

    def test_unplayed_before_closest_rematch(self):
        s = self.state(('A', 'B', 'C'), max_debates=5)
        self.assertEqual(self.t.next_pair(s), ['A', 'B'])
        s = self.t.record(s, debate())
        # A-C and B-C each have a gap of 16; identifiers break the tie.
        self.assertEqual(self.t.next_pair(s), ['C', 'A'])
        s = self.t.record(s, debate('C', 'A', 'tie'))
        self.assertEqual(self.t.next_pair(s), ['B', 'C'])

    def test_closest_ratings_when_all_pairs_played(self):
        s = self.state(max_debates=2)
        s = self.t.record(s, debate())
        self.assertEqual(self.t.next_pair(s), ['B', 'A'])

    def test_unplayed_beats_a_zero_gap_rematch(self):
        s = self.state(('A', 'B', 'C', 'D'), max_debates=5)
        s = self.t.record(s, debate(result='tie'))
        s = self.t.record(s, debate('C', 'A', 'tie'))
        # AB and AC were played; the zero-gap unplayed AD precedes rematches.
        self.assertEqual(self.t.next_pair(s), ['A', 'D'])

    def test_deterministic_input_order(self):
        self.assertEqual(self.t.next_pair(self.state(('C', 'B', 'A'))), ['A', 'B'])

    def test_empty_and_singleton(self):
        for ids in ((), ('A',)):
            with self.subTest(ids=ids):
                s = self.state(ids)
                self.assertIsNone(self.t.next_pair(s))
                self.assertEqual(self.t.stats(s)['match_count'], 0)
                self.assertEqual(self.t.stats(s)['rating_spread'], 0)

    def test_duplicate_ids_invalid(self):
        with self.assertRaises(ValueError):
            self.state(('A', 'A'))

    def test_bad_debates_leave_original_untouched(self):
        s = self.state()
        before = copy.deepcopy(s)
        for d in (debate('A', 'A'), debate('A', 'Z'), debate(result='maybe'),
                  dict(debate(), result=0.7)):
            with self.subTest(d=d), self.assertRaises(ValueError):
                self.t.record(s, d)
            self.assertEqual(s, before)

    def test_incomplete_methodology_is_marked(self):
        d = debate()
        d['comparison'] = {k: d['comparison'][k] for k in self.t.COMPARISON_FIELDS}
        s = self.t.record(self.state(), d)
        self.assertEqual(self.t.stats(s)['match_count'], 1)
        self.assertTrue(any('objection/change links' in m for m in self.t.issues(s)))

    def test_long_debate_is_marked(self):
        d = debate()
        d['comparison']['reason'] = 'mot ' * 181
        s = self.t.record(self.state(), d)
        self.assertTrue(any('debate_max_words' in m for m in self.t.issues(s)))

    def test_counts_and_spread(self):
        s = self.t.record(self.state(), debate())
        out = self.t.stats(s)
        self.assertEqual(out['match_count'], 1)
        self.assertEqual(out['rating_spread'], 32)  # 1016-984
        self.assertEqual(out['matches_by_candidate'], {'A': 1, 'B': 1})

    def test_schema_accepts_and_catches_invalid_result(self):
        validator = load_tool('schema_lite')
        schema = read_json(FRONTIER / 'schemas' / 'tournament.json')
        s = self.t.record(self.state(), debate())
        self.assertEqual(validator.validate(s, schema), [])
        s['matches'][0]['result'] = 'guess'
        self.assertTrue(validator.validate(s, schema))
