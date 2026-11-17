# SPDX-License-Identifier: Apache-2.0
"""V2-16 .. V2-20 of regression specification: belief shift between exclusive explanations, value of information over cost, project numbers in the power."""
import copy

from .v2_common import V2, VP, load_tool, mutate, read_json, run_tool, write_json


class BeliefShiftTest(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def edit(self, fn):
        mutate(self.w, 'tests.json', fn)

    def t1(self, d):
        return next(t for t in d['tests'] if t['id'] == 'T1')

    def test_baseline_clean(self):
        self.assertV2Clean()

    def test_belief_shift_is_required_on_every_test(self):
        self.edit(lambda d: self.t1(d).pop('belief_shift'))
        self.assertBlocks('[BELIEF-MISSING]')

    def test_moves_cover_exactly_the_competing_hypotheses(self):
        self.edit(lambda d: self.t1(d)['belief_shift']['outcomes'][0]['moves'].pop('R1'))
        self.assertBlocks('[BELIEF-LOGIC]')
        self.fresh()
        self.w = self.to_v2()
        self.edit(lambda d: self.t1(d)['belief_shift']['outcomes'][0]['moves'].update(H9='up'))
        self.assertBlocks('[BELIEF-LOGIC]')

    def test_only_up_down_flat(self):
        self.edit(lambda d: self.t1(d)['belief_shift']['outcomes'][0]['moves'].update(H1='0.8'))
        self.assertBlocks('[BELIEF-LOGIC]')

    def test_every_competing_hypothesis_has_an_outcome_where_it_goes_up(self):
        def go(d):
            t = self.t1(d)
            t['belief_shift']['outcomes'] = [o for o in t['belief_shift']['outcomes'] if o['matches'] != 'R1']
        self.edit(go)
        self.assertBlocks('[BELIEF-LOGIC]')

    def test_the_matched_hypothesis_must_go_up(self):
        self.edit(lambda d: self.t1(d)['belief_shift']['outcomes'][0]['moves'].update(H1='flat'))
        self.assertBlocks('[BELIEF-LOGIC]')

    def test_exclusive_explanations_cannot_both_go_up(self):
        self.edit(lambda d: self.t1(d)['belief_shift']['outcomes'][0]['moves'].update(R1='up'))
        self.assertBlocks('[BELIEF-LOGIC]')

    def test_exclusive_matched_outcome_must_lower_another_one(self):
        self.edit(lambda d: self.t1(d)['belief_shift']['outcomes'][0]['moves'].update(R1='flat'))
        self.assertBlocks('[BELIEF-LOGIC]')

    def test_non_exclusive_explanations_may_rise_together(self):
        def go(d):
            t = self.t1(d)
            t['belief_shift']['exclusive'] = False
            t['belief_shift']['outcomes'][0]['moves']['R1'] = 'up'
        self.edit(go)
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[BELIEF')], [])

    def test_an_ambiguous_outcome_must_not_discriminate(self):
        self.edit(lambda d: self.t1(d)['belief_shift']['outcomes'][2]['moves'].update(H1='up'))
        self.assertBlocks('[BELIEF-LOGIC]')

    def test_an_ambiguous_outcome_is_required(self):
        def go(d):
            t = self.t1(d)
            t['belief_shift']['outcomes'] = [o for o in t['belief_shift']['outcomes'] if o['matches'] != 'ambiguous']
        self.edit(go)
        self.assertBlocks('[BELIEF-LOGIC]')

    def test_unexpected_outcome_is_marked_when_absent(self):
        def go(d):
            t = self.t1(d)
            t['belief_shift']['outcomes'] = [o for o in t['belief_shift']['outcomes'] if o['matches'] != 'unexpected']
        self.edit(go)
        self.assertMarks('[BELIEF-MISSING]')

    def test_a_false_precision_is_marked_not_blocked(self):
        self.edit(lambda d: self.t1(d)['belief_shift'].update(before='H1 is about 70% likely before the test and R1 30%.'))
        self.assertMarks('[BELIEF-PRECISE]')
        self.fresh()
        self.w = self.to_v2()
        self.edit(lambda d: self.t1(d)['belief_shift']['outcomes'][0].update(then='Probability of H1 rises to p = 0.85 afterwards.'))
        self.assertMarks('[BELIEF-PRECISE]')

    def test_the_card_shows_the_scenarios_of_the_first_test(self):
        self.assertEqual(run_tool('card', self.w).returncode, 0)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertIn('Belief after T1', card)
        self.assertIn('H1 up, R1 down', card)
        self.assertIn('ambiguous', card)


class VoiOrderTest(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def edit(self, fn):
        mutate(self.w, 'tests.json', fn)

    def test_voi_levels_are_required(self):
        self.edit(lambda d: d['tests'][0].pop('voi'))
        self.assertBlocks('[VOI-MISSING]')
        self.fresh()
        self.w = self.to_v2()
        self.edit(lambda d: d['tests'][0]['voi'].update(cost='cheap'))
        self.assertBlocks('[VOI-MISSING]')
        self.fresh()
        self.w = self.to_v2()
        self.edit(lambda d: d['tests'][0]['voi'].update(why='short'))
        self.assertBlocks('[VOI-MISSING]')

    def test_order_follows_information_over_cost(self):
        order = read_json(self.w / 'tests.json')['ranking']['order']
        self.assertEqual(order[0], 'T1')

        def flip(d):
            d['ranking']['order'] = list(reversed(d['ranking']['order']))
        self.edit(flip)
        self.assertBlocks('[VOI-ORDER]')

    def test_an_inversion_is_allowed_with_a_written_exception(self):
        def flip(d):
            d['ranking']['order'] = list(reversed(d['ranking']['order']))
            d['ranking']['order_exception'] = 'T2 goes first because its data arrive next week and T1 needs a licence still pending.'
        self.edit(flip)
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[VOI-ORDER]')], [])

    def test_ties_leave_the_order_free(self):
        def tie(d):
            for t in d['tests']:
                t['voi'].update(information='medium', cost='medium')
            d['ranking']['order'] = list(reversed(d['ranking']['order']))
        self.edit(tie)
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[VOI-ORDER]')], [])

    def test_ratio_is_ordinal_high_over_high_equals_medium_over_medium(self):
        voi = self.v2.voi_ratio
        self.assertEqual(voi({'information': 'high', 'cost': 'high'}), voi({'information': 'medium', 'cost': 'medium'}))
        self.assertGreater(voi({'information': 'high', 'cost': 'low'}), voi({'information': 'medium', 'cost': 'low'}))
        self.assertGreater(voi({'information': 'medium', 'cost': 'low'}), voi({'information': 'medium', 'cost': 'high'}))

    def test_no_number_in_the_ranking(self):
        self.edit(lambda d: d['ranking'].update(score=7.5))
        self.assertTrue(any('[RANK]' in p for p in self.v2_probs()))

    def test_card_header_of_the_tests_says_information_over_cost(self):
        run_tool('card', self.w)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertIn('information high / cost low', card)


class ProjectNumbersTest(V2):
    """Synthetic context regression: 4 key numbers were extracted and the card said the power was not tied to them."""

    KEYS = [
        {'name': 'n_quarters', 'value': 44, 'unit': 'quarters', 'source': 'user'},
        {'name': 'padding_score', 'value': 2.41, 'role': 'effect', 'source': 'user'},
        {'name': 'preparation_cost', 'value': 30, 'unit': 'minutes per batch', 'role': 'cost', 'source': 'user'},
        {'name': 'inspection_agreement', 'value': 0.046, 'role': 'ic', 'source': 'user'}]

    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def with_context(self, keys=None):
        mutate(self.w, 'intake.json', lambda d: d.update(context={'key_numbers': copy.deepcopy(keys or self.KEYS)}))

    def power_use(self, uses):
        def go(d):
            for t in d['tests']:
                t['sensitivity']['power']['context_use'] = copy.deepcopy(uses)
        mutate(self.w, 'tests.json', go)

    GOOD_USES = [
        {'name': 'padding_score', 'use': 'not_a_simulation_input', 'why': 'It is the level of the baseline, not the noise of a paired difference.'},
        {'name': 'preparation_cost', 'use': 'not_a_simulation_input', 'why': 'The simulated outcome is a rank or ratio and uses no preparation-time input.'},
        {'name': 'inspection_agreement', 'use': 'not_a_simulation_input', 'why': 'It is a reference for the size of a useful effect, not a noise parameter.'}]

    def test_an_unused_project_number_blocks(self):
        self.with_context()
        self.assertBlocks('[CTX-USE]')

    def test_n_quarters_is_recognised_as_n(self):
        common = load_tool('common')
        ci = common.context_inputs({'context': {'key_numbers': [{'name': 'n_quarters', 'value': 44, 'source': 'user'}]}})
        self.assertEqual(ci['n']['value'], 44)
        for name in ('n_months', 'n_years', 'n_rebalances', 'n_observations', 'n_samples'):
            ci = common.context_inputs({'context': {'key_numbers': [{'name': name, 'value': 12, 'source': 'user'}]}})
            self.assertIn('n', ci, name)

    def test_the_simulation_must_use_the_n_of_the_project(self):
        self.with_context()
        self.power_use(self.GOOD_USES)
        self.assertBlocks('[CTX-USE]')            # n_quarters = 44 is not used by the simulation (n = 200) and not dispositioned

    def test_a_reasoned_disposition_for_n_unblocks_it(self):
        self.with_context()
        self.power_use(self.GOOD_USES + [{'name': 'n_quarters', 'use': 'not_a_simulation_input',
                                          'why': 'The test is run on 200 records of an offline index, not on the quarters of the project.'}])
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[CTX-USE]')], [])

    def test_a_vague_reason_does_not_count(self):
        self.with_context()
        self.power_use(self.GOOD_USES + [{'name': 'n_quarters', 'use': 'not_a_simulation_input', 'why': 'not needed'}])
        self.assertBlocks('[CTX-USE]')

    def test_using_the_project_n_in_the_simulation_satisfies_the_rule(self):
        self.with_context([{'name': 'n_records', 'value': 200, 'role': 'n', 'source': 'user'}])
        r = run_tool('sim', '--design', 'paired', '--sd', 5, '--context', self.w, '--scenario', 'H1=3', '--scenario', 'R1=0',
                     '--expect', 'H1=continue', '--expect', 'R1=stop', '--continue-if-lower-above', 0, '--stop-if-upper-below', 1,
                     '--write-into', self.w / 'tests.json', '--test', 'T1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sim = next(t for t in read_json(self.w / 'tests.json')['tests'] if t['id'] == 'T1')['sensitivity']['simulation']
        self.assertTrue(sim['context']['used'])
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[CTX-USE]') and 'T1' in p], [])

    def test_numbers_extracted_from_the_archives_and_confirmed_are_held_to_the_same_rule(self):
        """Synthetic context regression: four key numbers were EXTRACTED from the project and the power was not tied to them."""
        proj = self.project()
        mutate(self.w, 'intake.json', lambda d: d.update(project_dirs=[str(proj)]))
        r = run_tool('context', 'extract', self.w, '--json')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cands = read_json(self.w / 'context_candidates.json')['candidates']
        picked = {}
        for c in cands:
            if c['class'] not in picked:
                picked[c['class']] = c
        self.assertGreaterEqual(len(picked), 4, [c['class'] for c in cands])
        for cls, c in list(picked.items())[:4]:
            r = run_tool('context', 'confirm', self.w, '--id', c['id'], '--name', cls)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        extracted = [k for k in read_json(self.w / 'intake.json')['context']['key_numbers'] if k['source'] == 'extracted']
        self.assertEqual(len(extracted), 4)
        ctx = [p for p in self.v2_probs() if p.startswith('[CTX-USE]') and 'T1' in p]
        self.assertGreaterEqual(len(ctx), 4, 'each of the four extracted numbers is used or placed: %r' % ctx)
        self.power_use([{'name': k['name'], 'use': 'not_a_simulation_input',
                         'why': 'This number describes the project, not the noise of the paired rank difference of this test.'} for k in extracted])
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[CTX-USE]') and 'T1' in p and 'assumed' not in p], [])

    def test_a_dispositioned_number_that_is_not_in_the_context_blocks(self):
        self.with_context()
        self.power_use(self.GOOD_USES + [{'name': 'invented_number', 'use': 'not_a_simulation_input', 'why': 'x' * 40}])
        self.assertBlocks('[CTX-USE]')

    def test_an_assumed_parameter_while_the_project_gives_the_number_blocks(self):
        self.with_context([{'name': 'n_records', 'value': 200, 'role': 'n', 'source': 'user'}])
        # the baseline power block says n is 'assumed' (150 / 200 / 250) and the simulation ignores the project n
        self.assertBlocks('[CTX-USE]')

    def test_without_context_nothing_is_demanded_and_the_card_says_what_is_assumed(self):
        self.assertV2Clean()
        run_tool('card', self.w)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertIn('no project numbers were given', card)

    def test_the_card_lists_used_reference_and_missing_numbers(self):
        self.with_context()
        self.power_use(self.GOOD_USES + [{'name': 'n_quarters', 'use': 'not_a_simulation_input',
                                          'why': 'The test is run on 200 records of an offline index, not on the quarters of the project.'}])
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rep = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertIn('Project numbers and the power:', rep)
        for name in ('n_quarters', 'padding_score', 'preparation_cost', 'inspection_agreement'):
            self.assertIn(name, rep)
        self.assertIn('not a simulation input', rep)
        self.assertIn('missing from the project numbers', rep)
        self.assertNotIn("not tied to the project's numbers (the simulations use values chosen by hand)", rep)
