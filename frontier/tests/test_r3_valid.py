# SPDX-License-Identifier: Apache-2.0
"""R3-7 .. R3-12 (regression specification): arithmetic checks, fixes need proof, data seen before, verdict scope, realistic power."""
import copy
import json

from .am1_common import AM, NOVP, REBOUND, VP, load_tool, mutate, read_json, run_tool, write_json
from .r3_common import R3, fr, second_raw


def set_text(w, path, text):
    def go(d):
        t = next(x for x in d['tests'] if x['id'] == path[0])
        cur = t
        for k in path[1:-1]:
            cur = cur[k]
        cur[path[-1]] = text
    mutate(w, 'tests.json', go)


class ArithmeticTest(R3):
    """R3-7: valid in EVERY directory (legacy included)."""

    def put(self, text, name=VP):
        set_text(self.work(name), ['T1', 'decisive_intervention', 'description'], text)

    def test_strata_impossible_in_a_year_is_refused(self):
        # Synthetic batches: twelve months times three size groups cannot make eighty strata.
        self.put(fr("Sur 80 strates (mois de conditionnement {x} tercile de taille des carreaux) du 2023-01-01 au 2023-12-31, comparer les housses de feutre."))
        self.assertCode('[ARITH-STRATA]')

    def test_strata_possible_passes_and_the_limit_is_exact(self):
        for n, ok in ((36, True), (37, False), (12, True)):
            self.fresh()
            self.put("Over %d strata (month of packing x tercile of tile size) of wooden tiles packed from 2023-01-01 to 2023-12-31." % n)
            p = self.probs()
            self.assertEqual(any(x.startswith('[ARITH-STRATA]') for x in p), not ok, (n, p))

    def test_strata_by_month_alone_and_by_quartile(self):
        self.put("20 strata, one per month of packing wooden tiles, between 2023-01-01 and 2023-12-31.")
        self.assertCode('[ARITH-STRATA]')
        self.fresh()
        self.put("48 strata (month of packing x quartile of tile size) packed between 2023-01-01 and 2023-12-31.")
        self.assertNoCode('[ARITH-STRATA]')

    def test_period_longer_than_the_range_is_refused(self):
        for text, bad in (("Confirmation on 270 mois (2009-2026).", True), ("Confirmation on 216 mois (2009-2026).", False),
                          ("Confirmation on 19 years from 2009 to 2026.", True), ("Confirmation on 18 years from 2009 to 2026.", False),
                          ("Confirmation on 73 quarters (2009-2026).", True), ("Confirmation on 72 quarters (2009-2026).", False)):
            self.fresh()
            set_text(self.work(), ['T1', 'feasibility', 'data'], text)
            p = self.probs()
            self.assertEqual(any(x.startswith('[ARITH-PERIOD]') for x in p), bad, (text, p))

    def test_n_of_the_simulation_must_be_in_the_replications(self):
        # an R3 directory refuses; an older one only warns (the fixture valid_novp simulates n = 20 beside "200 records")
        text = fr('60 strates appari{e\'}es, un classement par strate')
        set_text(self.work(), ['T1', 'sensitivity', 'replications'], text)
        self.assertNoCode('[ARITH-N]')
        self.assertTrue(any(x.startswith('[ARITH-N]') for x in self.check.warnings(self.work())))
        self.fresh()
        w = self.to_r3()
        set_text(w, ['T1', 'sensitivity', 'replications'], text)
        self.assertCode('[ARITH-N]')
        self.fresh()
        w = self.to_r3()
        set_text(w, ['T1', 'sensitivity', 'replications'], '200 records x 1 query each')
        self.assertNoCode('[ARITH-N]')

    def test_existing_fixtures_have_no_arithmetic_problem(self):
        for name in (VP, NOVP, REBOUND):
            p = self.probs(name)
            self.assertFalse([x for x in p if x.startswith('[ARITH')], (name, p))


class FixProofTest(R3):
    def setUp(self):
        super().setUp()
        self.w = self.to_r3()

    def crit(self, fn):
        mutate(self.w, 'critique.json', fn)

    def test_baseline_is_clean(self):
        self.assertR3Clean()

    def test_fixed_without_proof_is_refused(self):
        self.crit(lambda d: d['items'][0]['response'].pop('proof'))
        self.assertCode('[FIX-PROOF]')

    def test_fixed_with_an_opinion_only_is_refused(self):
        self.crit(lambda d: d['items'][0]['response'].update(proof={'kind': 'opinion', 'where': 'x', 'evidence': 'I think it is fixed now',
                                                                    'addresses': 'index sensitive titles'}))
        self.assertCode('[FIX-PROOF]')

    def test_tests_diff_quote_must_be_where_it_says(self):
        self.crit(lambda d: d['items'][0]['response']['proof'].update(evidence='A sentence that is nowhere in the protocol of T1'))
        self.assertCode('[FIX-PROOF]')
        self.fresh()
        self.w = self.to_r3()
        self.crit(lambda d: d['items'][0]['response']['proof'].update(where='tests.T9.traps.positive_control.description'))
        self.assertCode('[FIX-PROOF]')

    def test_proof_must_answer_the_objection(self):
        self.crit(lambda d: d['items'][0]['response']['proof'].update(addresses='something about budget and licences of repositories'))
        self.assertCode('[FIX-PROOF]')

    def test_file_proof_needs_the_file_and_its_hash(self):
        (self.w / 'calc.txt').write_text('mean gain 4.1 over 200 records\n', encoding='utf-8')
        import hashlib
        h = hashlib.sha256((self.w / 'calc.txt').read_bytes()).hexdigest()
        self.crit(lambda d: d['items'][0]['response'].update(proof={'kind': 'file', 'where': 'calc.txt', 'evidence': h,
                                                                    'addresses': 'the index sensitive to titles shown by a positive control'}))
        self.assertNoCode('[FIX-PROOF]')
        self.crit(lambda d: d['items'][0]['response']['proof'].update(evidence='0' * 64))
        self.assertCode('[FIX-PROOF]')

    def test_calculation_proof_needs_a_sim_block_and_a_number_from_it(self):
        self.crit(lambda d: d['items'][0]['response'].update(proof={
            'kind': 'calculation', 'where': 'tests.T1.sensitivity.simulation', 'evidence': 'min_p_expected 0.803',
            'addresses': 'the index sensitive to titles shown by simulation of the control'}))
        self.assertNoCode('[FIX-PROOF]')
        self.crit(lambda d: d['items'][0]['response']['proof'].update(evidence='min_p_expected 0.999'))
        self.assertCode('[FIX-PROOF]')

    def test_second_critique_must_confirm(self):
        self.crit(lambda d: d['second_critique']['verdicts'][0].update(objection_lifted='no'))
        self.assertCode('[FIX-UNCONFIRMED]')
        self.fresh()
        self.w = self.to_r3()
        self.crit(lambda d: d['second_critique']['verdicts'][0].update(objection_lifted='unclear'))
        self.assertCode('[FIX-UNCONFIRMED]')

    def test_fixed_without_any_second_critique_is_refused(self):
        self.crit(lambda d: d.pop('second_critique'))
        p = self.assertCode('[FIX-UNCONFIRMED]')
        self.assertEqual(len([x for x in p if x.startswith('[FIX-UNCONFIRMED]')]) >= 2, True)

    def test_open_is_the_honest_state_and_marks_dig_when_blocking(self):
        def go(d):
            for i in (0, 1):
                d['items'][i]['response'] = {'action': 'open', 'note': 'the second critic does not confirm the fix'}
            d.pop('second_critique')
        self.crit(go)
        p = self.probs()
        self.assertFalse(self.code_in('[FIX-', p), p)
        self.assertFalse(self.code_in('[RECO-OPEN]', p), p)
        self.assertTrue(any('mark: [RECO-OPEN]' in w for w in self.check.warnings(self.w)))
        mutate(self.w, 'recommendation.json', lambda d: d.update(verdict='test first',
               reason='The blocking leakage objection is still open, so the cheap T1 comes before any larger effort.'))
        self.assertNoCode('[RECO-OPEN]')
        self.assertNoCode('[CRITIQUE]')

    def test_the_second_critic_is_not_the_author_when_an_independent_critic_exists(self):
        self.crit(lambda d: d['second_critique'].update(critic_family='claude'))        # the author family of the fixture
        p = self.assertCode('[FIX-UNCONFIRMED]')
        self.assertTrue(any('own family' in x for x in p), p)

    def test_low_power_under_perturbation_is_a_warning_and_is_said_on_the_card(self):
        # control: a large useful effect, independent observations: no warning, no label
        r = run_tool('sim', 'robust', '--design', 'paired', '--tests', self.w / 'tests.json', '--test', 'T1',
                     '--useful-effect', '4', '--rho', '0', '--overlap', '1', '--reps', '300')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(any(x.startswith('[POWER-LOW]') for x in self.check.warnings(self.w)))
        # useful effect 0.5 with sd up to 7, n = 200, dependence and overlap: the worst-case power is far below 0.8
        r = run_tool('sim', 'robust', '--design', 'paired', '--tests', self.w / 'tests.json', '--test', 'T1',
                     '--useful-effect', '0.5', '--rho', '0,0.6', '--overlap', '3', '--reps', '40')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse([x for x in self.probs() if x.startswith('[POWER')])
        self.assertTrue(any(x.startswith('[POWER-LOW]') for x in self.check.warnings(self.w)))
        self.assertEqual(self.card().returncode, 0)
        self.assertIn('UNDERPOWERED', (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8'))

    def test_second_critique_raw_is_kept_and_hashed(self):
        self.crit(lambda d: d['second_critique'].update(raw_sha256='0' * 64))
        self.assertCode('[FIX-UNCONFIRMED]')
        self.fresh()
        self.w = self.to_r3()
        self.crit(lambda d: d['second_critique']['verdicts'][0].update(why='a sentence that the critic never wrote anywhere'))
        self.assertCode('[FIX-UNCONFIRMED]')

    def test_budget_one_second_critique(self):
        r = run_tool('step', self.w, '--step', 'critique2')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('budget', r.stderr)

    def test_legacy_directories_keep_the_old_rule(self):
        self.assertNoCode('[FIX-', NOVP)


class DataSeenAndScopeTest(R3):
    def setUp(self):
        super().setUp()
        self.w = self.to_r3()

    def test_data_seen_before_is_mandatory(self):
        mutate(self.w, 'tests.json', lambda d: d['tests'][0]['traps']['data_split'].pop('data_seen_before'))
        self.assertCode('[DATA-SEEN]')

    def test_overlap_of_years_is_refused_and_disjoint_passes(self):
        # Synthetic leakage: the development window includes confirmation years.
        cases = (('2005-2024', '2010-2024', True), ('1990-2004', '2005-2024', False), ('2005', '2005-2024', True),
                 ('2025', '2005-2024', False), ('2000-2005 and 2024', '2005-2024', True))
        for seen, conf, bad in cases:
            self.fresh()
            self.w = self.to_r3()
            def go(d):
                ds = d['tests'][0]['traps']['data_split']
                ds['data_seen_before'] = 'Already consulted before the protocol: %s (the production model saw it).' % seen
                ds['confirmation_data'] = 'Confirmation on %s, read once after the freeze.' % conf
            mutate(self.w, 'tests.json', go)
            p = self.probs()
            self.assertEqual(self.code_in('[DATA-SEEN]', p), bad, (seen, conf, p))

    def test_scope_is_mandatory_for_every_test(self):
        mutate(self.w, 'tests.json', lambda d: d['tests'][1].pop('verdict_scope'))
        self.assertCode('[SCOPE]')
        self.fresh()
        self.w = self.to_r3()
        mutate(self.w, 'tests.json', lambda d: d['tests'][0]['verdict_scope'].update(does_not_conclude_about=[]))
        self.assertCode('[SCOPE]')

    def test_a_failed_test_cannot_conclude_beyond_what_it_tested(self):
        for txt in ('The idea is false if the CI is below 1.', 'Stop: the idea is refuted.', 'the whole idea is dead'):
            self.fresh()
            self.w = self.to_r3()
            set_text(self.w, ['T1', 'decision_rule', 'stop_if'], txt)
            self.assertCode('[SCOPE]')
        self.fresh()
        self.w = self.to_r3()
        set_text(self.w, ['T1', 'decision_rule', 'stop_if'], 'CI entirely below 1 position: this retrieval mechanism is not supported in this sample.')
        self.assertNoCode('[SCOPE]')


class PowerParametersTest(R3):
    def setUp(self):
        super().setUp()
        self.w = self.to_r3()

    def power(self, fn, test=0):
        mutate(self.w, 'tests.json', lambda d: fn(d['tests'][test]['sensitivity']['power']))

    def test_power_block_is_mandatory_in_r3(self):
        mutate(self.w, 'tests.json', lambda d: d['tests'][0]['sensitivity'].pop('power'))
        self.assertCode('[POWER-MISSING]')

    def test_without_user_data_a_single_figure_is_refused(self):
        self.power(lambda p: p['parameters'][1].pop('low') and None)
        self.assertCode('[POWER-RANGE]')
        self.fresh()
        self.w = self.to_r3()
        self.power(lambda p: p['parameters'][0].update(low=300, central=200, high=250))
        self.assertCode('[POWER-RANGE]')

    def test_measured_needs_a_source_240_months_case(self):
        # A measured packing count must cite a source.
        def go(p):
            p['parameters'][0] = {'name': 'n', 'status': 'measured', 'value': 200}
        self.power(go)
        self.assertCode('[POWER-SOURCE]')
        def ok(p):
            p['parameters'][0] = {'name': 'n', 'status': 'measured', 'value': 200,
                                  'source': {'kind': 'reference', 'ref': {'id': 'doi:10.1000/titles.2019', 'run': 'prior_art', 'claim': 'A1'}}}
        self.power(ok)
        self.assertNoCode('[POWER-SOURCE]')

    def test_measured_from_context_must_be_a_confirmed_key_number(self):
        def go(p):
            p['parameters'][0] = {'name': 'n', 'status': 'measured', 'value': 200, 'source': {'kind': 'context', 'name': 'n_periods'}}
        self.power(go)
        self.assertCode('[POWER-SOURCE]')
        def ctx(d):
            d['context'] = {'key_numbers': [{'name': 'n_periods', 'value': 200, 'source': 'user'}]}
        mutate(self.w, 'intake.json', ctx)
        self.assertNoCode('[POWER-SOURCE]')

    def test_measured_value_must_equal_the_source_value(self):
        mutate(self.w, 'intake.json', lambda d: d.update(context={'key_numbers': [{'name': 'n_periods', 'value': 180, 'source': 'user'}]}))
        self.power(lambda p: p['parameters'].__setitem__(0, {'name': 'n', 'status': 'measured', 'value': 200,
                                                             'source': {'kind': 'context', 'name': 'n_periods'}}))
        self.assertCode('[POWER-SOURCE]')

    def test_n_of_the_simulation_is_the_central_n(self):
        self.power(lambda p: p['parameters'][0].update(central=210, low=150, high=250))
        self.assertCode('[POWER-LINK]')

    def test_the_target_metric_is_declared_and_a_proxy_has_its_gap_written(self):
        self.power(lambda p: p.pop('target_metric'))
        self.assertCode('[POWER-TARGET]')
        self.fresh()
        self.w = self.to_r3()
        self.power(lambda p: p.update(metric_is_target=False))
        self.assertCode('[POWER-TARGET]')
        self.power(lambda p: p.update(proxy_gap='the surface-scuff gap does not measure corner strength; corner strength needs a separate loading experiment'))
        self.assertNoCode('[POWER-TARGET]')

    def test_costs_data_prior_trials_and_the_model_are_written(self):
        for key in ('costs', 'data_available', 'prior_trials'):
            self.fresh()
            self.w = self.to_r3()
            self.power(lambda p: p.update({key: 'n/a'}))
            self.assertCode('[POWER-FIELD]')
        self.fresh()
        self.w = self.to_r3()
        self.power(lambda p: p['model'].update(justification='iid'))
        self.assertCode('[POWER-FIELD]')

    def test_role_is_protocol_support(self):
        self.power(lambda p: p.update(role='experiment'))
        self.assertCode('[POWER-FIELD]')

    def test_robust_block_is_rerun_by_check(self):
        def go(p):
            p['robust']['cells'][0]['p_continue'] = 0.99
        self.power(go)
        self.assertCode('[POWER-RERUN]')
        self.fresh()
        self.w = self.to_r3()
        self.power(lambda p: p.pop('robust'))
        self.assertCode('[POWER-RERUN]')

    def test_robust_reports_false_positives_and_power(self):
        rb = read_json(self.w / 'tests.json')['tests'][0]['sensitivity']['power']['robust']
        for k in ('false_positive_max', 'power_min', 'effective_n_min', 'cells', 'analysis'):
            self.assertIn(k, rb)
        labels = {c['scenario'] for c in rb['cells']}
        self.assertIn('null', labels)
        self.assertTrue(any(l.startswith('useful') for l in labels))
        self.assertEqual(rb['analysis'], 'hac')

    def test_the_card_labels_the_simulation_and_the_inputs(self):
        self.assertEqual(self.card().returncode, 0, self.card().stdout)
        rep = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertIn('protocol-support simulation (not an experiment)', rep)
        self.assertIn('assumed', rep)
        self.assertIn('false positives', rep)


class RobustSimTest(R3):
    ARGS = dict(design='paired', n=200, sd_values=[5.0], rho_values=[0.0], overlap=1, useful_effect=3.0,
                continue_if_lower_above=0.0, stop_if_upper_below=1.0, reps=300, seed=20261114)

    def run_(self, **kw):
        a = dict(self.ARGS)
        a.update(kw)
        return self.sim.robust(**a)

    def test_no_dependence_false_positive_is_near_alpha(self):
        out = self.run_(useful_effect=3.0)
        fp = next(c for c in out['cells'] if c['scenario'] == 'null')['p_continue']
        self.assertLessEqual(fp, 0.10)

    def test_effective_n_decreases_with_rho_and_overlap(self):
        a = self.run_(rho_values=[0.0])['effective_n_min']
        b = self.run_(rho_values=[0.6])['effective_n_min']
        c = self.run_(rho_values=[0.0], overlap=5)['effective_n_min']
        self.assertLess(b, a)
        self.assertLess(c, a)
        self.assertAlmostEqual(a, 200, places=6)

    def test_power_does_not_improve_with_dependence(self):
        p0 = self.run_(rho_values=[0.0], useful_effect=0.6, sd_values=[5.0])['power_min']
        p1 = self.run_(rho_values=[0.7], useful_effect=0.6, sd_values=[5.0])['power_min']
        self.assertLessEqual(p1, p0 + 0.05)

    def test_perturbed_noise_lowers_the_worst_case_power(self):
        base = self.run_(sd_values=[5.0], useful_effect=0.6)['power_min']
        wide = self.run_(sd_values=[5.0, 9.0], useful_effect=0.6)['power_min']
        self.assertLessEqual(wide, base)

    def test_null_and_useful_are_both_simulated(self):
        out = self.run_(sd_values=[4.0, 6.0], rho_values=[0.0, 0.5])
        self.assertEqual(len([c for c in out['cells'] if c['scenario'] == 'null']), 4)
        self.assertEqual(len([c for c in out['cells'] if c['scenario'].startswith('useful')]), 8)
        self.assertEqual(out['false_positive_max'], max(c['p_continue'] for c in out['cells'] if c['scenario'] == 'null'))
        self.assertEqual(out['power_min'], min(c['p_continue'] for c in out['cells'] if c['scenario'].startswith('useful')))

    def test_deterministic_and_rerunnable(self):
        a = self.run_(reps=100)
        b = self.run_(reps=100)
        self.assertEqual(a, b)
        self.assertEqual(self.sim.compare_robust(a, self.sim.rerun_robust(a)), [])
        c = copy.deepcopy(a)
        c['cells'][0]['p_continue'] += 0.1
        self.assertTrue(self.sim.compare_robust(c, self.sim.rerun_robust(c)))

    def test_bad_inputs_are_refused(self):
        for bad in (dict(n=1), dict(rho_values=[1.0]), dict(rho_values=[-1.0]), dict(overlap=0), dict(sd_values=[0.0]),
                    dict(design='proportions')):
            with self.assertRaises(ValueError):
                self.run_(**bad)
