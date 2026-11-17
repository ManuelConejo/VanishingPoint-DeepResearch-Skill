# SPDX-License-Identifier: Apache-2.0
"""V2-13 .. V2-15 of regression specification: facets, named operators, named datasets / models / metrics verified to exist."""
from .v2_common import V2, VP, mutate, read_json, run_tool, write_json

RECURRING = ('facet_recombination', 'analogy', 'literature_bridge')
NOT_MEASURED = ('anomaly', 'revived_old_idea', 'hypothesis_inversion', 'morphological_analysis', 'new_problem', 'new_hypothesis',
                'limits_exploration', 'critical_experiment', 'rival_theories')


class FacetsOperatorsTest(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def edit(self, fn):
        mutate(self.w, 'hypotheses.json', fn)

    def test_baseline_clean(self):
        self.assertV2Clean()

    def test_facets_are_required_with_goal_and_mechanism(self):
        self.edit(lambda d: d.pop('facets'))
        self.assertBlocks('[FACETS]')
        self.fresh()
        self.w = self.to_v2()
        self.edit(lambda d: d['facets'].update(mechanism='short'))
        self.assertBlocks('[FACETS]')

    def test_optional_facets_are_accepted(self):
        self.edit(lambda d: d['facets'].update(population='Preprints in four fields', evaluation='Rank of the record in an offline index'))
        self.assertV2Clean()

    def test_rival_without_an_operator_blocks(self):
        self.edit(lambda d: d['rivals'][0].pop('operator'))
        self.assertBlocks('[OPERATOR]')

    def test_variant_without_an_operator_blocks(self):
        self.edit(lambda d: d['repairable_variants'][0].pop('operator'))
        self.assertBlocks('[OPERATOR]')

    def test_unknown_operator_blocks(self):
        self.edit(lambda d: d['rivals'][0].update(operator='intuition'))
        self.assertBlocks('[OPERATOR]')

    def test_every_named_operator_is_accepted(self):
        for op in RECURRING + NOT_MEASURED:
            with self.subTest(op=op):
                self.edit(lambda d, op=op: d['rivals'][0].update(operator=op))
                self.assertEqual([p for p in self.v2_probs() if p.startswith('[OPERATOR]')], [])

    def test_facet_must_be_a_known_facet(self):
        self.edit(lambda d: d['rivals'][0].update(facet='vibes'))
        self.assertBlocks('[OPERATOR]')

    def test_library_flags_recurring_ingredients_and_the_rest_as_not_measured(self):
        lib = self.v2.OPERATORS
        for op in RECURRING:
            self.assertTrue(lib[op]['recurring_ingredient'], op)
        for op in NOT_MEASURED:
            self.assertFalse(lib[op]['recurring_ingredient'], op)
        self.assertEqual(set(lib), set(RECURRING + NOT_MEASURED))

    def test_card_says_operator_not_measured_and_recurring_ingredient(self):
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertIn('rival_theories (operator not measured)', card)
        self.assertIn('facet_recombination (recurring ingredient)', card)
        self.assertIn('Facets: goal', card)


class NamedElementsTest(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def named(self):
        return read_json(self.w / 'named_elements.json')

    def edit(self, fn):
        mutate(self.w, 'named_elements.json', fn)

    def add(self, *args):
        return run_tool('named', 'add', self.w, *args)

    def test_baseline_has_a_host_checked_element_marked_as_such(self):
        e = self.named()['elements'][0]
        self.assertEqual((e['id'], e['existence'], e['kind']), ('N1', 'host_checked', 'dataset'))
        self.assertV2Clean()

    def test_unverified_and_not_found_are_accepted_and_marked(self):
        r = self.add('--name', 'Moral Scenarios dataset', '--kind', 'dataset', '--used-in', 'T2', '--not-found', '--query', 'moral scenarios dataset')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.add('--name', 'ClarityNet', '--kind', 'model', '--used-in', 'T2', '--unverified', 'Recalled from memory, not searched')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        els = {e['name']: e for e in self.named()['elements']}
        self.assertEqual(els['Moral Scenarios dataset']['existence'], 'not_found')
        self.assertEqual(els['ClarityNet']['existence'], 'unverified')
        mutate(self.w, 'tests.json', lambda d: [t.update(named_elements=['N1', 'N2', 'N3']) for t in d['tests'] if t['id'] == 'T2'] and [t.pop('named_elements_none') for t in d['tests'] if t['id'] == 'T2'])
        self.assertV2Clean()
        run_tool('card', self.w)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertIn('NOT FOUND', card)
        self.assertIn('do not rely on it', card)
        self.assertIn('unverified (memory)', card)

    def test_not_found_needs_the_queries_searched(self):
        self.assertEqual(self.add('--name', 'Ghost set', '--kind', 'dataset', '--used-in', 'T1', '--not-found').returncode, 1)

    def test_a_verified_element_needs_evidence_that_resolves(self):
        self.edit(lambda d: d['elements'][0].update(existence='verified', evidence={'kind': 'material', 'item': 'OpenAlex works index'}))
        self.assertBlocks('[NAMED-VERIFY]')

    def test_verified_by_a_material_item_found_by_the_gateway(self):
        vp = self.vp_fake({'search-hf-datasets|*': {'index_total': 1, 'results': [
            {'id': 'hfdataset:synthetic/tiles', 'title': 'Synthetic tile inspection panel', 'date': '2025-02-01', 'licence': 'cc-by-4.0'}]}})
        r = run_tool('matter', 'search', self.w, '--for', 'main', '--kind', 'dataset', '--query', 'title citation', '--vp', vp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        env = read_json(self.w / 'matter' / 'gw-001.json') if (self.w / 'matter' / 'gw-001.json').exists() else None
        envs = sorted((self.w / 'matter').glob('gw-*.json'))
        rel = 'matter/' + envs[-1].name
        r = run_tool('matter', 'add', self.w, '--for', 'main', '--kind', 'dataset', '--envelope', rel, '--candidate', 0, '--vp', vp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        item_name = read_json(self.w / 'material.json')['items'][-1]['name']
        r = self.add('--name', item_name, '--kind', 'dataset', '--used-in', 'T2', '--material', item_name)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        e = [x for x in self.named()['elements'] if x['name'] == item_name][0]
        self.assertEqual(e['existence'], 'verified')
        mutate(self.w, 'tests.json', lambda d: [t.update(named_elements=[e['id']]) for t in d['tests'] if t['id'] == 'T2'] and [t.pop('named_elements_none') for t in d['tests'] if t['id'] == 'T2'])
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[NAMED')], [])
        self.edit(lambda d: d['elements'][-1]['evidence'].update(item='Some other dataset'))
        self.assertBlocks('[NAMED-VERIFY]')

    def test_the_tool_refuses_a_material_that_is_not_in_material_json(self):
        r = self.add('--name', 'Synthetic tile inspection panel', '--kind', 'dataset', '--used-in', 'T1', '--material', 'Synthetic tile inspection panel')
        self.assertEqual(r.returncode, 1)

    def test_verified_by_a_found_vp_reference_whose_fragment_holds_the_name(self):
        r = self.add('--name', 'Title length and citation counts', '--kind', 'dataset', '--used-in', 'T2',
                     '--ref-id', 'doi:10.1000/titles.2019', '--run', 'prior_art', '--claim', 'A1',
                     '--fragment', 'shorter titles received more citations')
        self.assertEqual(r.returncode, 1, 'the fragment does not contain the name')
        r = self.add('--name', 'citations', '--kind', 'metric', '--used-in', 'T2',
                     '--ref-id', 'doi:10.1000/titles.2019', '--run', 'prior_art', '--claim', 'A1',
                     '--fragment', 'shorter titles received more citations')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.named()['elements'][-1]['existence'], 'verified')

    def test_a_reference_that_is_absent_cannot_verify(self):
        self.edit(lambda d: d['elements'].append({'id': 'N2', 'name': 'causal', 'kind': 'metric', 'used_in': ['T2'], 'existence': 'verified',
                                                  'evidence': {'kind': 'reference', 'ref': {'id': 'doi:10.1000/ghost.2021', 'run': 'prior_art', 'claim': 'A4'},
                                                               'fragment': 'the abstract makes no causal claim'}}))
        self.assertBlocks('[NAMED-VERIFY]')

    def test_host_checked_needs_a_description_of_the_check(self):
        self.edit(lambda d: d['elements'][0]['evidence'].update(how='ok'))
        self.assertBlocks('[NAMED-VERIFY]')

    def test_every_test_lists_its_elements_or_says_none(self):
        mutate(self.w, 'tests.json', lambda d: [t.pop('named_elements') for t in d['tests'] if t['id'] == 'T1'])
        self.assertMarks('[NAMED-LINK]')

    def test_a_name_in_a_test_text_that_the_test_does_not_list_is_marked(self):
        def go(d):
            for t in d['tests']:
                if t['id'] == 'T2':
                    t['decisive_intervention']['description'] += ' The ranks come from the OpenAlex works index.'
        mutate(self.w, 'tests.json', go)
        self.assertMarks('[NAMED-LINK]')

    def test_unknown_id_in_a_test_blocks(self):
        mutate(self.w, 'tests.json', lambda d: [t.update(named_elements=['N9']) for t in d['tests'] if t['id'] == 'T1'])
        self.assertBlocks('[NAMED-VERIFY]')

    def test_elements_are_never_dropped_from_the_report(self):
        run_tool('named', 'add', self.w, '--name', 'ClarityNet', '--kind', 'model', '--used-in', 'T1', '--unverified', 'Recalled from memory only')
        mutate(self.w, 'tests.json', lambda d: [t.update(named_elements=['N1', 'N2']) for t in d['tests'] if t['id'] == 'T1'])
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rep = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertIn('ClarityNet', rep)
        self.assertIn('OpenAlex works index', rep)
