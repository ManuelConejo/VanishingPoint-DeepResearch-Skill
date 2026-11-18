# SPDX-License-Identifier: Apache-2.0
"""V3 guarantees: offline journals, synthetic packing inputs, honest power and open leads."""
import copy
import json
import math
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import tempfile

from .helpers import FRONTIER, load_tool, read_json, write_json, mutate, run_tool
from .v2_common import V2
from .r3_common import REBOUND
from .test_v2_rebound import plan_of

# V5: the synthetic packing run supplies the component inputs.
ENTREES = FRONTIER / 'tests' / 'fixtures' / 'synthetic_packing_run'
CLASSES = ('rule_escape_hatch', 'target_signal_circularity', 'proxy_as_target')


def replay():
    return read_json(ENTREES / 'tests.json')


def checklist(t):
    return {c: {'answer': 'absent', 'where': 'tests.%s.decision_rule.continue_if' % t['id']} for c in CLASSES}


class V3Pure(TestCase):
    def setUp(self):
        self.v3 = load_tool('v3check')
        self.sim = load_tool('sim')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.w = Path(self.tmp.name)

    def checks(self, data):
        p, w = [], []
        self.v3.run(self.w, data, p, w)
        return p, w

    def journal(self, path, count):
        p = self.w / path / 'state' / 'journal.jsonl'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('\n'.join(json.dumps({'call': 'search-openalex' if i % 2 else 'read',
                                          'error': 'unavailable' if i == 0 else None, 'journal': path})
                               for i in range(count)) + '\n', encoding='utf-8')
        return p

    def usage_data(self):
        return {'intake.json': {'vp': {'runs': {'main': 'vp-main', 'reb': 'vp-neighbour'}}},
                'rebound.json': {'ideas': [{'id': 'N1', 'prior_art': {'vp_run': 'reb'}}]},
                'run.json': {'steps': [{'step': 'rebound_vp_run', 'vp_run': 'reb'}]}}

    def test_budget_uses_journal_calls_including_failures_and_reads(self):
        d = self.usage_data()
        self.journal('vp-main', 24)
        self.journal('vp-neighbour', 16)
        write_json(self.w / 'vp-neighbour' / 'run.json', {'gateway_calls': 1})
        u = self.v3.rebound_usage(self.w, d)
        self.assertEqual(u['total_calls'], 40)
        self.assertEqual(u['rebound_calls'], 16)
        self.assertEqual(u['rows'][0]['calls'], 16)
        self.assertAlmostEqual(u['rows'][0]['share'], .4)
        self.assertTrue(u['complete'])
        p, marks = self.checks(d)
        self.assertFalse(p)
        self.assertTrue(any('mark: [REBOUND-BUDGET]' in x for x in marks))

    def test_cap_boundary_and_configuration(self):
        d = self.usage_data()
        self.journal('vp-main', 1)
        self.journal('vp-neighbour', 15)
        self.assertFalse(any('[REBOUND-BUDGET]' in x for x in self.checks(d)[1]))
        cfg = self.v3.common.config()
        cfg['rebound_vp_max_calls_per_neighbour'] = 4
        with patch.object(self.v3.common, 'config', return_value=cfg):
            self.assertTrue(any('[REBOUND-BUDGET]' in x for x in self.checks(d)[1]))

    def test_only_explicit_host_selection_with_reason_allows_deepening(self):
        d = self.usage_data()
        self.journal('vp-main', 4)
        self.journal('vp-neighbour', 16)
        pa = d['rebound.json']['ideas'][0]['prior_art']
        for record in ({'reason': 'A decisive lead'}, {'selected': True, 'reason': ' '},
                       {'selected': False, 'reason': 'A decisive lead'}):
            pa['deepen'] = record
            self.assertTrue(any('[REBOUND-BUDGET]' in x for x in self.checks(d)[1]))
        pa['deepen'] = {'selected': True, 'reason': 'The host selected this neighbour to resolve the paper-cradle baseline.'}
        self.assertFalse(any('[REBOUND-BUDGET]' in x for x in self.checks(d)[1]))

    def test_all_journals_deduplicated_and_local_gateway_calls_in_denominator(self):
        d = self.usage_data()
        self.journal('vp-main', 10)
        self.journal('vp-neighbour', 10)
        self.journal('research', 3)
        self.journal('matter', 2)
        d['intake.json']['vp']['runs']['alias'] = str(self.w / 'vp-neighbour')
        u = self.v3.rebound_usage(self.w, d)
        self.assertEqual(u['total_calls'], 25)
        self.assertEqual(u['rebound_calls'], 10)
        self.assertAlmostEqual(u['share'], .4)

    def test_missing_or_corrupt_journal_is_unknown_never_zero(self):
        d = self.usage_data()
        self.journal('vp-main', 10)
        for content in (None, '{broken\n'):
            if content:
                p = self.journal('vp-neighbour', 1)
                p.write_text(content, encoding='utf-8')
            u = self.v3.rebound_usage(self.w, d)
            self.assertFalse(u['complete'])
            self.assertIsNone(u['rows'][0]['calls'])
            self.assertIsNone(u['rows'][0]['share'])
            self.assertTrue(any('[REBOUND-BUDGET]' in x for x in self.checks(d)[1]))

    def test_missing_main_journal_makes_share_unknown(self):
        d = self.usage_data()
        self.journal('vp-neighbour', 3)
        u = self.v3.rebound_usage(self.w, d)
        self.assertIsNone(u['rows'][0]['share'])
        self.assertEqual(u['rows'][0]['calls'], 3)

    def test_legacy_steps_still_count_without_rebound_json(self):
        # legacy-run.json is not supplied. Explicit synthetic legacy steps
        # test this adapter contract; they are not a recovered replay log.
        steps = [{'step': 'vp_run', 'vp_run': 'prior_art'}]
        steps += [{'step': 'rebound_vp_run', 'vp_run': 'reb-' + label}
                  for label in ('N1', 'N2', 'N3', 'N4', 'N5', 'B1', 'B2')]
        d = {'run.json': {'steps': steps}}
        d['intake.json'] = {'vp': {'runs': {}}}
        for step in d['run.json']['steps']:
            if step.get('vp_run'):
                name = step['vp_run']
                d['intake.json']['vp']['runs'][name] = name
                self.journal(name, 12 if name.startswith('reb-') else 25)
        u = self.v3.rebound_usage(self.w, d)
        self.assertEqual(len(u['rows']), 7)
        self.assertEqual(u['rebound_calls'], 84)
        self.assertEqual(u['total_calls'], 109)

    def test_replay_prior_art_needs_facet_even_though_it_mentions_code(self):
        d = {'prior_art.json': read_json(ENTREES / 'prior_art.json')}
        # This run supplies the facet; remove it to test the omission guarantee.
        d['prior_art.json'].pop('software_platform_search', None)
        self.assertTrue(any('[PRIOR-TOOLS]' in x for x in self.checks(d)[1]))
        d['prior_art.json']['closest_work'][0]['kind'] = 'software'
        self.assertTrue(any('[PRIOR-TOOLS]' in x for x in self.checks(d)[1]))

    def test_facet_attempt_or_explained_exception_is_enough(self):
        for record in ({'queries': ['synthetic cradle design platform'], 'result': 'credential_missing'},
                       {'not_applicable': 'This is a mathematical identity with no software or platform counterpart.'}):
            p, marks = self.checks({'prior_art.json': {'software_platform_search': record}})
            self.assertFalse(p)
            self.assertFalse(any('[PRIOR-TOOLS]' in x for x in marks))
        p, marks = self.checks({'prior_art.json': {'software_platform_search': {'queries': [' ']}}})
        self.assertTrue(any('[PRIOR-TOOLS]' in x for x in marks))

    def test_replay_power_is_at_exact_minimum_not_optimistic_scenario_or_stress_factor(self):
        for t in replay()['tests']:
            rb = t['sensitivity']['power']['robust']
            fresh = self.sim.robust(rb['design'], rb['n'], rb['sd_values'], rb['rho_values'], rb['overlap'],
                                    rb['useful_effect'], rb['rule']['continue_if_lower_above'],
                                    rb['rule']['stop_if_upper_below'], effect_factors=(1.,), reps=rb['reps'],
                                    seed=rb['seed'], alpha=rb['alpha'], decision_counts=True)
            expected = min(c['decision_counts']['continue'] / rb['reps'] for c in fresh['cells'] if c['effect'] == rb['useful_effect'])
            got = self.v3.power_at_minimum(t)
            self.assertAlmostEqual(got['power'], expected)
            self.assertEqual(got['effect'], rb['useful_effect'])
            self.assertLess(got['power'], .8)
            self.assertLess(got['power'], t['sensitivity']['simulation']['min_p_expected'])

    def test_power_does_not_trust_edited_cells(self):
        t = replay()['tests'][0]
        before = self.v3.power_at_minimum(t)
        for c in t['sensitivity']['power']['robust']['cells']:
            c['p_continue'] = 1.
        self.assertEqual(self.v3.power_at_minimum(t), before)

    def test_ordinary_simulation_fallback_uses_numeric_minimum(self):
        t = replay()['tests'][0]
        t['sensitivity'].pop('power')
        t['sensitivity']['minimum_useful_effect'] = .05
        b = t['sensitivity']['simulation']
        fresh = self.sim.simulate(b['design'], b['n'], b['sd'], [('minimum', .05, 'continue'), ('null', 0., 'stop')],
                                  b['rule']['continue_if_lower_above'], b['rule']['stop_if_upper_below'],
                                  reps=b['reps'], seed=b['seed'], alpha=b['alpha'])
        self.assertEqual(self.v3.power_at_minimum(t)['power'], fresh['scenarios'][0]['p_continue'])

    def test_proportions_and_paired_fallback(self):
        for design, sd, base, eff in [('paired', 1., None, .2), ('proportions', None, .2, .1)]:
            b = self.sim.simulate(design, 20, sd, [('H1', eff * 2, 'continue'), ('R1', 0., 'stop')],
                                  0., eff, reps=30, base=base)
            t = {'id': 'T1', 'sensitivity': {'minimum_useful_effect': eff, 'simulation': b}}
            got = self.v3.power_at_minimum(t)
            self.assertTrue(0 <= got['power'] <= 1)
            self.assertEqual(got['effect'], eff)

    def test_absent_inputs_are_marked_without_guessing_from_prose(self):
        t = replay()['tests'][0]
        t['sensitivity'].pop('power')
        t['sensitivity'].pop('minimum_useful_effect', None)
        p, marks = self.checks({'tests.json': {'tests': [t]}})
        self.assertFalse(p)
        self.assertIsNone(self.v3.power_at_minimum(t)['power'])
        self.assertTrue(any('[POWER-INPUTS]' in x for x in marks))

    def test_stated_power_mismatch_blocks_but_missing_inputs_only_mark(self):
        t = replay()['tests'][0]
        value = self.v3.power_at_minimum(t)['power']
        t['sensitivity']['power_at_minimum'] = value
        self.assertFalse(self.checks({'tests.json': {'tests': [t]}})[0])
        t['sensitivity']['power_at_minimum'] = 1.
        self.assertTrue(any(x.startswith('[POWER-MIN-MISMATCH]') for x in self.checks({'tests.json': {'tests': [t]}})[0]))

    def test_conflicting_minimum_effect_blocks(self):
        t = replay()['tests'][0]
        t['sensitivity']['minimum_useful_effect'] = .5
        self.assertTrue(any(x.startswith('[POWER-MIN-MISMATCH]') for x in self.checks({'tests.json': {'tests': [t]}})[0]))

    def test_nonfinite_stated_power_is_marked(self):
        for value in (float('nan'), float('inf'), True):
            t = replay()['tests'][0]
            t['sensitivity']['power_at_minimum'] = value
            problems, marks = self.checks({'tests.json': {'tests': [t]}})
            self.assertFalse(problems)
            self.assertTrue(any('[POWER-INPUTS]' in x and 'power_at_minimum' in x for x in marks))

    def test_replay_missing_checklists_are_soft(self):
        data = replay()
        for t in data['tests']:
            t.pop('pre_critique', None)
        p, marks = self.checks({'tests.json': data})
        self.assertFalse(p)
        for t in replay()['tests']:
            self.assertTrue(any('[PITFALL-CHECK]' in x and t['id'] in x for x in marks))

    def test_checklist_complete_present_absent_uncertain_are_not_blocks(self):
        t = replay()['tests'][0]
        t['pre_critique'] = checklist(t)
        for answer in ('present', 'absent', 'uncertain'):
            t['pre_critique']['target_signal_circularity']['answer'] = answer
            p, marks = self.checks({'tests.json': {'tests': [t]}})
            self.assertFalse(p)
            self.assertFalse(any('[PITFALL-CHECK]' in x for x in marks))

    def test_checklist_path_must_resolve_in_the_same_test_to_nonempty_content(self):
        for where in ('tests.T2.decision_rule', 'tests.T1.missing', 'tests.T1.pre_critique', '', 'tests.T1.empty'):
            t = replay()['tests'][0]
            t['empty'] = ''
            t['pre_critique'] = checklist(t)
            t['pre_critique']['rule_escape_hatch']['where'] = where
            self.assertTrue(any('[PITFALL-CHECK]' in x for x in self.checks({'tests.json': {'tests': [t]}})[1]))

    def test_replay_missing_prospective_is_soft_and_exception_is_accepted(self):
        d = {'tests.json': replay()}
        for t in d['tests.json']['tests']:
            for key in ('kind', 'start_action', 'readout_date'):
                t.pop(key, None)
        self.assertTrue(any('[PROSPECTIVE]' in x for x in self.checks(d)[1]))
        d['tests.json']['prospective_not_applicable'] = 'No independent outcome can mature over time for this finite tile inventory.'
        self.assertFalse(any('[PROSPECTIVE]' in x for x in self.checks(d)[1]))

    def test_prospective_requires_action_and_valid_readout_date_but_never_blocks(self):
        t = replay()['tests'][0]
        t.update(kind='prospective', start_action='Freeze and timestamp fifty predictions today.', readout_date='2027-11-15')
        self.assertFalse(any('[PROSPECTIVE]' in x for x in self.checks({'tests.json': {'tests': [t]}})[1]))
        for field, value in [('start_action', ''), ('readout_date', '2027-02-30'), ('readout_date', '')]:
            changed = copy.deepcopy(t)
            changed[field] = value
            p, marks = self.checks({'tests.json': {'tests': [changed]}})
            self.assertFalse(p)
            self.assertTrue(any('[PROSPECTIVE]' in x for x in marks))

    def test_critique_pack_contains_checklist_and_prospective_record_verbatim(self):
        pack = load_tool('pack_critique')
        tj = replay()
        t = tj['tests'][0]
        t['pre_critique'] = checklist(t)
        t.update(kind='prospective', start_action='Freeze fifty preregistered predictions.', readout_date='2027-11-15')
        text = pack.protocol_md({}, {}, tj)
        self.assertIn(json.dumps(t['pre_critique'], ensure_ascii=False), text)
        self.assertIn(t['start_action'], text)
        self.assertIn(t['readout_date'], text)
        self.assertIn('Pre-critique', text)


class V3Integration(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def test_new_omissions_are_marks_check_and_card_still_succeed(self):
        p, marks = self.check.run_all(self.w, with_card=False)
        self.assertFalse(p)
        for code in ('[PRIOR-TOOLS]', '[PITFALL-CHECK]', '[PROSPECTIVE]', '[POWER-INPUTS]'):
            self.assertTrue(any('mark: ' + code in x for x in marks), (code, marks))
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertLessEqual(len((self.w / 'IDEA-CARD.md').read_text().splitlines()), 80)

    def render_replay(self):
        # The actual tests need no network or replay of their unavailable VP sources for rendering.
        # Keep all other valid fixture inputs; direct rendering exercises the real JSON contents.
        write_json(self.w / 'tests.json', replay())
        mutate(self.w, 'recommendation.json', lambda d: d.update(next_step={'test': 'T1', 'first_action': 'Freeze the first snapshot.'},
                                                                 justification={'from': ['T1'], 'link': 'T1 decides the useful advance.'}))
        card = load_tool('card')
        return card.render(self.w), card.render(self.w, full=True)

    def test_synthetic_replay_headers_and_recommendation_surface_underpower(self):
        text, report = self.render_replay()
        for tid in ('T1', 'T2', 'T3'):
            line = next(x for x in text.splitlines() if x.startswith('### ' + tid + ':'))
            self.assertIn('power at minimum useful effect', line.lower())
            self.assertIn('UNDERPOWERED', line)
            self.assertNotIn('P=1', line)
        reco = next(x for x in text.splitlines() if x.startswith('**Recommendation'))
        self.assertIn('T1', reco)
        self.assertIn('UNDERPOWERED', reco)
        for t in replay()['tests']:
            self.assertIn('lowest P(expected decision) = %s' % t['sensitivity']['simulation']['min_p_expected'], report)
        self.assertLessEqual(len(text.splitlines()), 80)

    def test_prospective_can_run_alongside_three_primary_tests(self):
        tj = read_json(self.w / 'tests.json')
        template = copy.deepcopy(tj['tests'][0])
        primary = copy.deepcopy(template)
        primary['id'] = 'T3'
        prospective = copy.deepcopy(template)
        prospective.update(id='T4', kind='prospective', start_action='Timestamp a frozen prediction log today.', readout_date='2027-11-15')
        tj['tests'] += [primary, prospective]
        tj['ranking']['order'] += ['T3', 'T4']
        p, w = [], []
        self.check.check_tests(tj, {'H': {'H1', 'H2'}, 'R': {'R1', 'R2'}, 'V': {'V1'}}, None, p, w)
        self.assertFalse(p, p)
        write_json(self.w / 'tests.json', tj)
        text = load_tool('card').render(self.w)
        self.assertIn('Prospective T4:', text)
        self.assertIn('### T4:', text)
        self.assertLessEqual(len(text.splitlines()), 80)

    def test_threshold_config_changes_label_not_recomputed_power(self):
        write_json(self.w / 'tests.json', replay())
        card = load_tool('card')
        common = load_tool('common')
        cfg = common.config()
        cfg['power_min_threshold'] = 0.
        with patch.object(card.common, 'config', return_value=cfg):
            text = card.render(self.w)
        for line in text.splitlines():
            if line.startswith('### T'):
                self.assertNotIn('UNDERPOWERED', line)

    def test_arithmetic_mismatch_blocks_check_and_card(self):
        mutate(self.w, 'tests.json', lambda d: d['tests'][0]['sensitivity'].update(minimum_useful_effect=3., power_at_minimum=1.))
        p, marks = self.check.run_all(self.w, with_card=False)
        self.assertTrue(any(x.startswith('[POWER-MIN-MISMATCH]') for x in p), p)
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertFalse((self.w / 'IDEA-CARD.md').exists())

    def test_tools_beyond_three_entries_have_own_complete_lines(self):
        def edit(d):
            first = copy.deepcopy(d['closest_work'][0])
            d['closest_work'] = [copy.deepcopy(first) for _ in range(3)]
            for name, kind in [('CradleBench', 'platform'), ('SleevePlanner', 'software')]:
                item = copy.deepcopy(first)
                item.update(kind=kind, title=name, what_differs='Packing coverage is useful; prospective corner protection remains to be measured.')
                d['closest_work'].append(item)
            d['software_platform_search'] = {'queries': ['CradleBench and SleevePlanner tile packing controls']}
        mutate(self.w, 'prior_art.json', edit)
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout)
        text = (self.w / 'IDEA-CARD.md').read_text()
        for name in ('CradleBench', 'SleevePlanner'):
            line = next(x for x in text.splitlines() if x.startswith('- Closest tool/platform:') and name in x)
            self.assertIn('[FOUND]', line)
            self.assertIn('prospective corner protection remains to be measured.', line)
        self.assertLessEqual(len(text.splitlines()), 80)

    def test_present_pitfalls_and_prospective_action_each_visible(self):
        def edit(d):
            for t in d['tests']:
                t['pre_critique'] = checklist(t)
            t = d['tests'][0]
            t['pre_critique']['proxy_as_target']['answer'] = 'present'
            t.update(kind='prospective', start_action='Publish a frozen prediction log today.', readout_date='2027-11-15')
        mutate(self.w, 'tests.json', edit)
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout)
        text = (self.w / 'IDEA-CARD.md').read_text()
        self.assertTrue(any(x.startswith('Pitfalls present:') and 'T1 proxy_as_target' in x for x in text.splitlines()))
        self.assertTrue(any(x.startswith('Prospective T1:') and 'Publish a frozen prediction log today.' in x and '2027-11-15' in x for x in text.splitlines()))
        self.assertLessEqual(len(text.splitlines()), 80)


    def test_dense_replay_keeps_new_lines_and_all_leads_within_eighty(self):
        import hashlib
        self.w = self.to_v2(REBOUND)
        for fname in ('rebound.json', 'rebound_after.json'):
            mutate(self.w, fname, lambda d: [i.update(search_plan=plan_of(i['id'], i['prior_art']['queries'])) for i in d['ideas']])
        tj = replay()
        for t in tj['tests']:
            t['pre_critique'] = checklist(t)
        tj['tests'][0].update(kind='prospective', start_action='Freeze the prediction log today.', readout_date='2027-11-15')
        write_json(self.w / 'tests.json', tj)
        mutate(self.w, 'recommendation.json', lambda d: d.update(next_step={'test': 'T1', 'first_action': 'Freeze the first snapshot.'}))
        pa = read_json(ENTREES / 'prior_art.json')
        # Synthetic dense layout: three papers, two tools and eighteen leads,
        # as in the old contract. The source fixture itself remains complete.
        pa['closest_work'] = pa['closest_work'][:3]
        for name, kind in [('CradleBench', 'platform'), ('SleevePlanner', 'software')]:
            item = copy.deepcopy(pa['closest_work'][0])
            item.update(title=name, kind=kind)
            pa['closest_work'].append(item)
        write_json(self.w / 'prior_art.json', pa)
        quotes = [line.split('] ', 1)[1] for line in (ENTREES / 'IDEA-CARD.md').read_text().splitlines()
                  if line.startswith('- Draft ') and '] ' in line]
        self.assertGreaterEqual(len(quotes), 18)
        quotes = quotes[:18]
        draft = '\n'.join(quotes)
        (self.w / 'free_draft.md').write_text(draft)
        write_json(self.w / 'draft_claims.json', {'draft_sha256': hashlib.sha256(draft.encode()).hexdigest(),
                   'claims': [{'id': 'D%d' % i, 'quote': q, 'status': 'unverified_memory'} for i, q in enumerate(quotes, 1)]})
        evidence = read_json(self.w / 'decisive_claims.json')['claims'][0]
        write_json(self.w / 'decisive_claims.json', {'claims': [dict(evidence, id='C%d' % i) for i in range(6)]})
        card = load_tool('card')
        text, report = card.render(self.w), card.render(self.w, full=True)
        self.assertLessEqual(len(text.splitlines()), 80)
        notice = 'Ranking of the neighbouring ideas by debates is available on request (tournament).'
        self.assertEqual(text.splitlines().count(notice), 1)
        visible = [line for line in text.splitlines() if line.strip() and not line.startswith('<!--')]
        self.assertEqual(visible[-1], notice)
        self.assertNotIn(notice, report)
        for quote in quotes:
            self.assertIn(quote, text)
        for name in ('CradleBench', 'SleevePlanner'):
            self.assertTrue(any(x.startswith('- Closest tool/platform:') and name in x for x in text.splitlines()))
        self.assertIn('Prospective T1:', text)
        for tid in ('T1', 'T2', 'T3'):
            self.assertIn(tid + ':', text)
        for fname in ('rebound.json', 'rebound_after.json'):
            for idea in read_json(self.w / fname)['ideas']:
                self.assertIn(idea['statement'], text)
        self.assertIn('Decisive evidence C0', report)

    def test_rebound_budget_report_and_card_preserve_all_neighbours_and_scenarios(self):
        self.w = self.to_v2(REBOUND)
        for fname in ('rebound.json', 'rebound_after.json'):
            mutate(self.w, fname, lambda d: [i.update(search_plan=plan_of(i['id'], i['prior_art']['queries'])) for i in d['ideas']])
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        card = (self.w / 'IDEA-CARD.md').read_text()
        report = (self.w / 'IDEA-REPORT.md').read_text()
        self.assertIn('Rebound gateway budget', report)
        self.assertIn('share of all VP calls', report)
        for fname in ('rebound.json', 'rebound_after.json'):
            d = read_json(self.w / fname)
            for idea in d['ideas']:
                self.assertTrue(any(x.startswith('- ' + idea['id'] + ' ') for x in card.splitlines()))
                self.assertIn(idea['statement'], card)
                self.assertIn(idea['id'], report)
            for sc in (d.get('ranking') or {}).get('scenarios', []):
                self.assertIn(sc['then'].rstrip('.'), card)
        self.assertLessEqual(len(card.splitlines()), 80)
        self.assertNotRegex(card, r'\.\.\.|\u2026|\(\+\d+ more')
        self.assertFalse(self.check.run_all(self.w)[0])
