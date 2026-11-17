# SPDX-License-Identifier: Apache-2.0
"""check.py: mechanical validation of a Frontier working directory (regression specification R5, R7-R23)."""
import copy
import hashlib
import json
import os
import shutil
import unittest
from pathlib import Path

from .helpers import (FRONTIER, HEADER, TempCase, copy_skill, load_tool, mutate, read_json, run_tool, set_config,
                      write_json)


def codes(problems):
    return ' '.join(problems)


class CheckBase(TempCase):
    def setUp(self):
        super().setUp()
        self.check = load_tool('check')

    def problems(self, name='valid_vp'):
        return self.check.problems(self.work(name))

    def assertCode(self, code, name='valid_vp'):
        probs = self.problems(name)
        self.assertTrue(any(p.startswith(code) for p in probs), '%s not in %r' % (code, probs))
        return probs


class SchemasTest(CheckBase):
    def test_schema_files_exist_and_are_json(self):
        for n in ('intake', 'prior_art', 'hypotheses', 'tests', 'critique', 'result', 'recommendation', 'decision_log_entry'):
            p = FRONTIER / 'schemas' / (n + '.json')
            self.assertTrue(p.exists(), p)
            json.loads(p.read_text(encoding='utf-8'))

    def test_schema_violation_reported(self):
        mutate(self.work(), 'intake.json', lambda d: d.update(T=20261114))
        self.assertCode('[SCHEMA]')

    def test_missing_file(self):
        (self.work() / 'hypotheses.json').unlink()
        self.assertCode('[MISSING]')

    def test_invalid_json(self):
        (self.work() / 'tests.json').write_text('{not json', encoding='utf-8')
        self.assertCode('[JSON]')


class ValidTest(CheckBase):
    def test_valid_vp(self):
        self.assertEqual(self.problems('valid_vp'), [])

    def test_valid_novp(self):
        self.assertEqual(self.problems('valid_novp'), [])

    def test_cli_exit_codes(self):
        ok = run_tool('check', self.work('valid_vp'))
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        mutate(self.work('valid_novp'), 'hypotheses.json', lambda d: d.update(rivals=[]))
        bad = run_tool('check', self.work('valid_novp'))
        self.assertEqual(bad.returncode, 1)
        self.assertIn('[RIVAL]', bad.stdout)

    def test_cli_json(self):
        r = run_tool('check', self.work('valid_vp'), '--json')
        out = json.loads(r.stdout)
        self.assertTrue(out['ok'])
        self.assertEqual(out['problems'], [])
        self.assertIn('warnings', out)

    def test_valid_vp_real(self):
        """R51: a working directory whose references point into a REAL VP run (Q01) passes. MODIFIED (orchestrator fix,
        review round 2): with VP, vp_prior_art_md is now required; Q01 is a standard run, not a prior-art run, so that is
        the only problem left without it; the fixture now points to the prior-art fixture (same answer, Partially)."""
        self.assertEqual(self.problems('valid_vp_real'), [])

    def test_structural_note(self):
        """R47: the report starts with the statement of what the checks are."""
        note = 'checks are structural; they do not prove scientific soundness'
        ok = run_tool('check', self.work('valid_vp'))
        self.assertIn(note, ok.stdout.splitlines()[0])
        mutate(self.work('valid_novp'), 'hypotheses.json', lambda d: d.update(rivals=[]))
        bad = run_tool('check', self.work('valid_novp'))
        self.assertIn(note, bad.stdout.splitlines()[0])
        out = json.loads(run_tool('check', self.work('valid_vp'), '--json').stdout)
        self.assertIn(note, out['note'])


class IntakeTest(CheckBase):
    def test_idea_too_long(self):
        mutate(self.work(), 'intake.json', lambda d: d.update(idea='One. Two. Three. Four.'))
        self.assertCode('[INTAKE]')

    def test_bad_date(self):
        mutate(self.work(), 'intake.json', lambda d: d.update(T='14/11/2026'))
        self.assertCode('[SCHEMA]')

    def test_gain_source_must_be_user_or_assumption(self):
        mutate(self.work(), 'intake.json', lambda d: d['justifying_gain'].update(source='guess'))
        self.assertCode('[SCHEMA]')

    def test_gain_empty(self):
        mutate(self.work(), 'intake.json', lambda d: d['justifying_gain'].update(text=' '))
        self.assertCode('[INTAKE]')

    def test_language_required(self):
        """R63: the language of the user (prose of the card) is recorded."""
        mutate(self.work(), 'intake.json', lambda d: d.pop('language'))
        self.assertCode('[SCHEMA]')
        self.fresh()
        mutate(self.work(), 'intake.json', lambda d: d.update(language='French'))
        self.assertCode('[SCHEMA]')


class PriorArtTest(CheckBase):
    def test_answer_enum(self):
        mutate(self.work(), 'prior_art.json', lambda d: d.update(answer='Novel'))
        self.assertCode('[SCHEMA]')

    def test_not_found_requires_search_description(self):
        def f(d):
            d['answer'] = 'Not found'
            d['closest_work'] = []
            d['searched'] = ''
        mutate(self.work(), 'prior_art.json', f)
        self.assertCode('[PRIOR-ART]')

    # modified round 2 (R56): with VP the answer is VP's (PRIOR-ART.md says Partially), so this is shown without VP
    def test_not_found_with_search_is_ok(self):
        def f(d):
            d['answer'] = 'Not found'
            d['closest_work'] = []
        mutate(self.work('valid_novp'), 'prior_art.json', f)
        self.assertEqual(self.problems('valid_novp'), [])

    def test_partially_requires_closest_work(self):
        mutate(self.work(), 'prior_art.json', lambda d: d.update(closest_work=[]))
        self.assertCode('[PRIOR-ART]')

    def test_what_differs_missing_is_marked(self):
        mutate(self.work(), 'prior_art.json', lambda d: d['closest_work'][0].update(what_differs=''))
        problems, warnings = self.check.run_all(self.work(), with_card=False)
        self.assertEqual(problems, [])
        self.assertTrue(any('[OVERLAP-LEDGER]' in w and 'difference' in w for w in warnings))

    def test_materials_keys(self):
        mutate(self.work(), 'prior_art.json', lambda d: d['materials'].pop('transferable_methods'))
        self.assertCode('[SCHEMA]')


class HypothesesTest(CheckBase):
    def test_no_rival(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d.update(rivals=[]))
        self.assertCode('[RIVAL]')

    def test_too_few_hypotheses(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d.update(hypotheses=d['hypotheses'][:1]))
        self.assertCode('[HYPOTHESES]')

    def test_too_many_hypotheses(self):
        def f(d):
            h = d['hypotheses'][0]
            d['hypotheses'] = [dict(h, id='H%d' % i) for i in range(1, 6)]
        mutate(self.work(), 'hypotheses.json', f)
        self.assertCode('[HYPOTHESES]')

    def test_hypothesis_without_references(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d['hypotheses'][0].update({'for': [], 'against': []}))
        self.assertCode('[HYPOTHESES]')

    def test_no_variant(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d.update(repairable_variants=[]))
        self.assertCode('[HYPOTHESES]')

    def test_duplicate_ids(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d['rivals'][0].update(id='H1'))
        self.assertCode('[HYPOTHESES]')


GRID_FIELDS = ['competing_hypotheses', 'predictions', 'compatible_with_both', 'unexpected_under_both',
               'decisive_intervention', 'sensitivity', 'decision_rule', 'feasibility']


class GridTest(CheckBase):
    def test_each_grid_field_required(self):
        for field in GRID_FIELDS:
            with self.subTest(field=field):
                self.fresh()
                mutate(self.work(), 'tests.json', lambda d: d['tests'][0].pop(field))
                self.assertCode('[GRID]')

    def test_empty_string_field(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0].update(unexpected_under_both='  '))
        self.assertCode('[GRID]')

    def test_feasibility_subfields(self):
        for sub in ('data', 'human_time', 'compute', 'technical_risk'):
            with self.subTest(sub=sub):
                self.fresh()
                mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['feasibility'].pop(sub))
                self.assertCode('[GRID]')

    def test_sensitivity_subfields(self):
        for sub in ('smallest_useful_effect', 'expected_noise', 'replications'):
            with self.subTest(sub=sub):
                self.fresh()
                mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['sensitivity'].pop(sub))
                self.assertCode('[GRID]')

    def test_intervention_kind_must_be_known(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['decisive_intervention'].update(kind=['vibes']))
        self.assertCode('[GRID]')

    def test_one_to_three_tests(self):
        mutate(self.work(), 'tests.json', lambda d: d.update(tests=[]))
        self.assertCode('[GRID]')
        self.fresh()

        def four(d):
            t = d['tests'][0]
            d['tests'] = [dict(copy.deepcopy(t), id='T%d' % i) for i in range(1, 5)]
            d['ranking']['order'] = ['T1', 'T2', 'T3', 'T4']
        mutate(self.work(), 'tests.json', four)
        self.assertCode('[GRID]')

    def test_competing_needs_two_known_ids_including_a_rival(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0].update(competing_hypotheses=['H1']))
        self.assertCode('[COMPETING]')
        self.fresh()
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0].update(competing_hypotheses=['H1', 'H9']))
        self.assertCode('[COMPETING]')

    def test_every_test_pits_against_a_rival_or_variant(self):
        def f(d):
            d['tests'][0]['competing_hypotheses'] = ['H1', 'H2']
            d['tests'][0]['predictions'][1]['hypothesis'] = 'H2'
        mutate(self.work(), 'tests.json', f)
        self.assertCode('[COMPETING]')

    def test_variant_alone_is_not_a_rival(self):
        """R43: a test must pit the idea against at least one rival R; a repairable variant V alone is not enough."""
        def f(d):
            t = d['tests'][1]
            t['competing_hypotheses'] = ['H2', 'V1']
            t['predictions'][1]['hypothesis'] = 'V1'
        mutate(self.work(), 'tests.json', f)
        self.assertCode('[COMPETING]')

    def test_prediction_for_each_competing_hypothesis(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0].update(predictions=d['tests'][0]['predictions'][:1]))
        self.assertCode('[PRED]')


class TrapsTest(CheckBase):
    def test_empty_trap(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['traps']['positive_control'].update(description=''))
        self.assertCode('[TRAP]')

    def test_missing_trap(self):
        for trap in ('proxy_vs_target', 'variants', 'positive_control', 'data_split'):
            with self.subTest(trap=trap):
                self.fresh()
                mutate(self.work(), 'tests.json', lambda d: d['tests'][1]['traps'].pop(trap))
                self.assertCode('[TRAP]')

    def test_variants_number_must_be_positive_integer(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['traps']['variants'].update(number_tested=0))
        self.assertCode('[TRAP]')

    def test_data_split_same_data(self):
        def f(d):
            s = d['tests'][0]['traps']['data_split']
            s['confirmation_data'] = s['design_data']
        mutate(self.work(), 'tests.json', f)
        self.assertCode('[TRAP]')

    def test_proxy_equals_target(self):
        def f(d):
            p = d['tests'][0]['traps']['proxy_vs_target']
            p['target'] = p['proxy']
        mutate(self.work(), 'tests.json', f)
        self.assertCode('[TRAP]')

    PLACEHOLDERS = ['n/a', 'N/A', 'na', 'none', 'None.', 'not applicable', 'Not applicable', 'tbd', 'TBD', 'todo', '-',
                    '--', '...', '…', 'null', 'nothing', 'unknown', 'same', 'idem', 'see above', '?']

    def test_placeholders_refused(self):
        """R44: placeholder fillings are refused in every text field of the four traps."""
        fields = [('proxy_vs_target', 'how_kept_apart'), ('variants', 'selection_rule_fixed_before'),
                  ('positive_control', 'distinguishes_bug_from_refutation'), ('data_split', 'separation'),
                  ('proxy_vs_target', 'proxy'), ('data_split', 'confirmation_data')]
        for trap, field in fields:
            for ph in self.PLACEHOLDERS:
                with self.subTest(trap=trap, field=field, value=ph):
                    self.fresh()
                    mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['traps'][trap].update({field: ph}))
                    self.assertCode('[TRAP]')

    def test_short_strings_refused(self):
        """R44: a trap field under 20 characters is refused."""
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['traps']['positive_control'].update(description='Checked by hand.'))
        self.assertCode('[TRAP]')

    def test_twenty_characters_accepted(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['traps']['positive_control'].update(description='x' * 20))
        self.assertNotIn('[TRAP]', codes(self.problems()))

    def test_multiple_variants_need_correction(self):
        """R45: several variants tested => a correction for multiple comparisons is required."""
        mutate(self.work(), 'tests.json', lambda d: d['tests'][1]['traps']['variants'].pop('multiple_comparisons'))
        self.assertCode('[TRAP]')
        self.fresh()
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][1]['traps']['variants'].update(multiple_comparisons='none'))
        self.assertCode('[TRAP]')
        self.fresh()
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['traps']['variants'].update(number_tested=3))
        self.assertCode('[TRAP]')


class PredictionsTest(CheckBase):
    def test_identical_predictions(self):
        def f(d):
            p = d['tests'][0]['predictions']
            p[1] = dict(p[0], hypothesis=p[1]['hypothesis'])
        mutate(self.work(), 'tests.json', f)
        self.assertCode('[PRED-IDENTICAL]')

    def test_identical_up_to_case_and_spaces(self):
        def f(d):
            p = d['tests'][0]['predictions']
            p[1] = {'hypothesis': p[1]['hypothesis'], 'direction': p[0]['direction'].upper(),
                    'magnitude': '  ' + p[0]['magnitude'].upper() + ' ', 'interval': list(p[0]['interval'])}
        mutate(self.work(), 'tests.json', f)
        self.assertCode('[PRED-IDENTICAL]')

    def test_direction_required(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['predictions'][0].update(direction=''))
        self.assertCode('[PRED]')

    def test_magnitude_or_interval_required(self):
        def f(d):
            p = d['tests'][0]['predictions'][0]
            p.pop('interval')
            p['magnitude'] = ''
        mutate(self.work(), 'tests.json', f)
        self.assertCode('[PRED]')

    def test_bad_interval(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['predictions'][0].update(interval=[10, 3]))
        self.assertCode('[PRED]')

    # modified round 2 (R42): an overlap is refused unless compatible_with_both names it (was a warning in round 1)
    def test_overlapping_intervals_refused_unless_named(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['predictions'][1].update(interval=[-1, 4]))
        self.assertCode('[PRED-OVERLAP]')

    def test_overlap_named_in_compatible_with_both_is_accepted(self):
        def f(d):
            t = d['tests'][0]
            t['predictions'][1]['interval'] = [-1, 4]
            t['compatible_with_both'] = 'A rank gain between 3 and 4 positions is predicted by both hypotheses.'
            t['sensitivity']['simulation']['scenarios'][1]['effect'] = 0.0
        mutate(self.work(), 'tests.json', f)
        self.assertNotIn('[PRED-OVERLAP]', codes(self.problems()))

    def test_interval_required(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][1]['predictions'][0].pop('interval'))
        self.assertCode('[PRED]')

    def test_unit_required(self):
        for unit in (None, '', '   '):
            with self.subTest(unit=unit):
                self.fresh()

                def f(d):
                    p = d['tests'][1]['predictions'][0]
                    if unit is None:
                        p.pop('unit')
                    else:
                        p['unit'] = unit
                mutate(self.work(), 'tests.json', f)
                self.assertCode('[PRED]')

    def test_words_differ_but_same_interval(self):
        def f(d):
            p = d['tests'][1]['predictions']
            p[1].update(direction='increases', magnitude='a rise', interval=list(p[0]['interval']))
        mutate(self.work(), 'tests.json', f)
        self.assertCode('[PRED-IDENTICAL]')


class RuleTest(CheckBase):
    def test_each_branch_required(self):
        for b in ('continue_if', 'revise_if', 'stop_if', 'indeterminate_if'):
            with self.subTest(branch=b):
                self.fresh()
                mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['decision_rule'].update({b: ''}))
                self.assertCode('[RULE]')

    def test_fixed_before_observation(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['decision_rule'].update(fixed_before_observation=False))
        self.assertCode('[RULE]')

    def test_equivalence_declared(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['decision_rule'].pop('equivalence'))
        self.assertCode('[RULE]')

    def test_equivalence_relevant_needs_margin(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['decision_rule'].update(equivalence={'relevant': True, 'margin': ''}))
        self.assertCode('[RULE]')

    def test_equivalence_not_relevant_needs_reason(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['decision_rule'].update(equivalence={'relevant': False}))
        self.assertCode('[RULE]')

    def test_rule_fixed_after_execution(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['decision_rule'].update(fixed_utc='2026-11-14T12:30:00Z'))
        self.assertCode('[RULE]')


class LeakageTest(CheckBase):
    def test_llm_judge_needs_l0(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][1].update(l0_leakage_control={'applicable': True, 'description': ''}))
        self.assertCode('[L0]')

    def test_llm_judge_cannot_declare_not_applicable(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][1].update(l0_leakage_control={'applicable': False, 'why_not': 'none'}))
        self.assertCode('[L0]')

    def test_flag_required(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0].pop('llm_judges_history'))
        self.assertCode('[L0]')

    def test_not_applicable_needs_reason(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0].update(l0_leakage_control={'applicable': False, 'why_not': ''}))
        self.assertCode('[L0]')


class RankingTest(CheckBase):
    def test_numeric_score_refused(self):
        mutate(self.work(), 'tests.json', lambda d: d['ranking'].update(scores={'T1': 0.73, 'T2': 0.41}))
        self.assertCode('[RANK]')

    def test_numeric_inside_scenario_refused(self):
        mutate(self.work(), 'tests.json', lambda d: d['ranking']['scenarios'][0].update(voi=12.5))
        self.assertCode('[RANK]')

    def test_scenarios_required(self):
        mutate(self.work(), 'tests.json', lambda d: d['ranking'].update(scenarios=[]))
        self.assertCode('[RANK]')

    def test_order_matches_tests(self):
        mutate(self.work(), 'tests.json', lambda d: d['ranking'].update(order=['T1']))
        self.assertCode('[RANK]')

    def test_scenario_names_a_known_test_or_stop(self):
        mutate(self.work(), 'tests.json', lambda d: d['ranking']['scenarios'][0].update({'then': ''}))
        self.assertCode('[RANK]')


class SimEmbedTest(CheckBase):
    def test_simulation_or_reason_required(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][1]['sensitivity'].pop('simulation_not_applicable'))
        self.assertCode('[SIM]')

    def test_simulation_must_come_from_sim_py(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['sensitivity']['simulation'].update(tool='excel'))
        self.assertCode('[SIM]')

    def test_simulation_needs_two_scenarios(self):
        def f(d):
            s = d['tests'][0]['sensitivity']['simulation']
            s['scenarios'] = s['scenarios'][:1]
        mutate(self.work(), 'tests.json', f)
        self.assertCode('[SIM]')

    # modified round 2 (R40): a hand-edited "distinguishes" is now refused by the rerun; the non-distinguishing
    # simulation is produced by sim.py itself (n = 20), on the plan-only directory
    def test_not_distinguishing_is_a_warning(self):
        w = self.work('valid_novp')
        r = run_tool('sim', '--design', 'paired', '--n', '20', '--sd', '5', '--scenario', 'H1=3', '--scenario', 'R1=0',
                     '--expect', 'H1=continue', '--expect', 'R1=stop', '--write-into', w / 'tests.json', '--test', 'T1')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.problems('valid_novp'), [])
        self.assertTrue(any('[SIM]' in x for x in self.check.warnings(w)))


class ReferencesVPTest(CheckBase):
    def test_absent_reference(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d['hypotheses'][0]['for'].append(
            {'id': 'doi:10.1000/ghost.2021', 'run': 'prior_art', 'claim': 'A4'}))
        self.assertCode('[REF-ABSENT]')

    def test_invalid_reference(self):
        mutate(self.work(), 'prior_art.json', lambda d: d['materials']['contradictory_results'][0]['refs'].append(
            {'id': 'doi:10.1000/bad.2018', 'run': 'prior_art', 'claim': 'A5'}))
        self.assertCode('[REF-INVALID]')

    def test_claim_without_verdict(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d['hypotheses'][0]['for'].append(
            {'id': 'doi:10.1000/titles.2019', 'run': 'prior_art', 'claim': 'A99'}))
        self.assertCode('[REF-MISSING]')

    def test_reference_without_claim(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d['hypotheses'][0]['for'].append({'id': 'doi:10.9/x'}))
        self.assertCode('[REF-MISSING]')

    def test_unknown_run(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d['hypotheses'][0]['for'][0].update(run='other'))
        self.assertCode('[REF-MISSING]')

    def test_verdicts_file_missing(self):
        (self.fx / 'vp_prior_art' / 'verdicts.json').unlink()
        self.assertCode('[REF-MISSING]')

    def test_identifier_mismatch(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d['hypotheses'][0]['for'][0].update(id='doi:10.1000/other'))
        self.assertCode('[REF-MISMATCH]')

    def test_statuses_reported(self):
        st = self.check.reference_statuses(self.work())
        self.assertEqual(st['doi:10.1000/titles.2019'], 'FOUND')
        self.assertEqual(st['doi:10.1000/prestige.2020'], 'DISTORTED')

    def test_card_json_missing(self):
        """R53 (modifies R18): a VP run without card.json fails (was a warning in round 1)."""
        (self.fx / 'vp_prior_art' / 'card.json').unlink()
        self.assertCode('[REF-CARD]')

    def test_unverified_is_accepted(self):
        """R52: UNVERIFIED passes the check (it is listed on the card)."""
        mutate(self.work(), 'hypotheses.json', lambda d: d['hypotheses'][0]['for'].append(
            {'id': 'doi:10.1000/clicks.2022', 'run': 'prior_art', 'claim': 'A6'}))
        self.assertEqual(self.problems(), [])
        self.assertEqual(self.check.reference_statuses(self.work())['doi:10.1000/clicks.2022'], 'UNVERIFIED')


class HeaderNoVPTest(CheckBase):
    def test_header_required_in_prior_art(self):
        mutate(self.work('valid_novp'), 'prior_art.json', lambda d: d.pop('header'))
        self.assertCode('[HEADER]', 'valid_novp')

    def test_header_exact_text(self):
        mutate(self.work('valid_novp'), 'prior_art.json', lambda d: d.update(header='refs maybe fine'))
        self.assertCode('[HEADER]', 'valid_novp')

    # modified round 2 (R63): the card is IDEA-CARD.md
    def test_header_required_in_card(self):
        (self.work('valid_novp') / 'IDEA-CARD.md').write_text('# Idea card\n\nno header\n', encoding='utf-8')
        self.assertCode('[HEADER]', 'valid_novp')

    # modified round 2 (R60): a hand-written card has no inputs fingerprint; the card comes from tools/card.py
    def test_card_with_header_ok(self):
        r = run_tool('card', self.work('valid_novp'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.work('valid_novp') / 'IDEA-CARD.md').read_text(encoding='utf-8').splitlines()[1], HEADER)
        self.assertEqual(self.problems('valid_novp'), [])

    def test_vp_mode_with_header_is_wrong(self):
        mutate(self.work('valid_vp'), 'prior_art.json', lambda d: d.update(header=HEADER))
        self.assertCode('[HEADER]')


class CritiqueTest(CheckBase):
    def test_target_must_be_protocol(self):
        mutate(self.work(), 'critique.json', lambda d: d.update(target='report'))
        self.assertCode('[SCHEMA]')

    def test_same_family_inconsistent(self):
        mutate(self.work(), 'critique.json', lambda d: d.update(critic_family='Claude'))
        self.assertCode('[CRITIQUE]')

    def test_claims_other_family_but_same(self):
        mutate(self.work('valid_novp'), 'critique.json', lambda d: d.update(same_family=False))
        self.assertCode('[CRITIQUE]', 'valid_novp')

    def test_vp_route_requires_vp(self):
        mutate(self.work('valid_novp'), 'critique.json',
               lambda d: d.update(route='vp-contradictor', critic_family='openai', same_family=False))
        self.assertCode('[CRITIQUE]', 'valid_novp')

    def test_item_test_must_exist(self):
        mutate(self.work(), 'critique.json', lambda d: d['items'][0].update(test='T7'))
        self.assertCode('[CRITIQUE]')

    def test_blocking_methodological_item_left_open_is_marked(self):
        mutate(self.work(), 'critique.json', lambda d: d['items'][1]['response'].update(action='open'))
        self.assertNotIn('[CRITIQUE]', codes(self.problems()))
        self.assertTrue(any('mark: [CRITIQUE]' in w for w in self.check.warnings(self.work())))


class ResultTest(CheckBase):
    def test_executed_needs_decision(self):
        mutate(self.work(), 'result.json', lambda d: d.update(decision=None))
        self.assertCode('[RESULT]')

    def test_executed_needs_observation(self):
        mutate(self.work(), 'result.json', lambda d: d.update(observed=''))
        self.assertCode('[RESULT]')

    def test_decision_enum(self):
        mutate(self.work(), 'result.json', lambda d: d.update(decision='yay'))
        self.assertCode('[RESULT]')

    def test_plan_only_needs_reason(self):
        mutate(self.work('valid_novp'), 'result.json', lambda d: d.update(reason=''))
        self.assertCode('[RESULT]', 'valid_novp')

    def test_executed_test_must_exist(self):
        mutate(self.work(), 'result.json', lambda d: d.update(test='T9'))
        self.assertCode('[RESULT]')

    def test_result_optional_file(self):
        (self.work('valid_novp') / 'result.json').unlink()
        self.assertEqual(self.problems('valid_novp'), [])


class RecommendationTest(CheckBase):
    def test_verdict_enum(self):
        mutate(self.work(), 'recommendation.json', lambda d: d.update(verdict='maybe'))
        self.assertCode('[SCHEMA]')

    def test_one_sentence(self):
        mutate(self.work(), 'recommendation.json', lambda d: d.update(reason='First reason. Second reason.'))
        self.assertCode('[RECO]')

    def test_no_certification(self):
        for bad in ('The idea is novel and worth testing.', 'This is certainly valuable.',
                    'The test proves the idea is new.', 'Novelty is guaranteed by the search.'):
            with self.subTest(reason=bad):
                self.fresh()
                mutate(self.work(), 'recommendation.json', lambda d: d.update(reason=bad))
                self.assertCode('[RECO]')

    def test_no_certification_round2(self):
        """R67."""
        for bad in ('An unprecedented lever for visibility deserves a day of work.',
                    'This groundbreaking approach is worth a day.', 'The first ever test of the mechanism is cheap.',
                    'It has never been done, so a day is worth it.', 'This has never been tried and costs a day.'):
            with self.subTest(reason=bad):
                self.fresh()
                mutate(self.work(), 'recommendation.json', lambda d: d.update(reason=bad))
                self.assertCode('[RECO]')


class LogCheckTest(CheckBase):
    def test_after_without_before(self):
        p = self.work() / 'decision_log.jsonl'
        p.write_text(json.dumps({'utc': '2026-11-14T12:10:00Z', 'phase': 'after', 'test': 'T1',
                                 'text': 'did it', 'by': 'researcher'}) + '\n', encoding='utf-8')
        self.assertCode('[LOG]')

    def test_log_required_with_a_before(self):
        (self.work() / 'decision_log.jsonl').unlink()
        self.assertCode('[LOG]')

    def test_before_must_precede_execution(self):
        p = self.work() / 'decision_log.jsonl'
        lines = p.read_text(encoding='utf-8').splitlines()
        first = json.loads(lines[0])
        first['utc'] = '2026-11-14T12:01:00Z'
        lines[0] = json.dumps(first)
        p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        self.assertCode('[LOG]')

    def test_bad_line(self):
        p = self.work() / 'decision_log.jsonl'
        p.write_text(p.read_text(encoding='utf-8') + 'garbage\n', encoding='utf-8')
        self.assertCode('[LOG]')


def rewrite_log(work, fn):
    p = Path(work) / 'decision_log.jsonl'
    lines = [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
    lines = fn(lines) or lines
    p.write_text(''.join(json.dumps(e) + '\n' for e in lines), encoding='utf-8')


class ProofTest(CheckBase):
    """R39: an executed result.json is tied to a "before" written earlier, by the fingerprint of the protocol."""

    def test_valid_has_proof(self):
        self.assertNotIn('[PROOF]', codes(self.problems()))

    def test_missing_fingerprint(self):
        mutate(self.work(), 'result.json', lambda d: d.pop('before_fingerprint'))
        self.assertCode('[PROOF]')

    def test_forged_fingerprint(self):
        mutate(self.work(), 'result.json', lambda d: d.update(before_fingerprint='0' * 64))
        self.assertCode('[PROOF]')

    def test_protocol_changed_after_execution(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['decision_rule'].update(
            continue_if='Point estimate above 2 positions.'))
        self.assertCode('[PROOF]')

    def test_before_written_after_start(self):
        def f(lines):
            lines[0]['utc'] = '2026-11-14T12:01:00Z'
        rewrite_log(self.work(), f)
        self.assertCode('[PROOF]')

    def test_before_without_fingerprint(self):
        def f(lines):
            lines[0].pop('fingerprint')
        rewrite_log(self.work(), f)
        self.assertCode('[PROOF]')

    def test_handwritten_executed_result_without_before(self):
        def f(lines):
            return [e for e in lines if e['test'] != 'T1'] + [
                {'utc': '2026-11-14T11:00:00Z', 'phase': 'before', 'test': 'idea', 'text': 'x', 'by': 'researcher'}]
        rewrite_log(self.work(), f)
        self.assertCode('[PROOF]')


class SimRerunTest(CheckBase):
    """R40: check.py reruns sim.py with the stored parameters and refuses any difference."""

    def test_valid_rerun_matches(self):
        self.assertNotIn('[SIM-RERUN]', codes(self.problems()))

    def test_invented_probabilities(self):
        def f(d):
            s = d['tests'][0]['sensitivity']['simulation']
            s['scenarios'][1].update(p_stop=0.95, p_indeterminate=0.021, p_expected=0.95)
            s['min_p_expected'] = 0.95
        mutate(self.work(), 'tests.json', f)
        self.assertCode('[SIM-RERUN]')

    def test_parameters_changed_without_rerun(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['sensitivity']['simulation'].update(n=40))
        self.assertCode('[SIM-RERUN]')

    def test_distinguishes_flipped(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['sensitivity']['simulation'].update(distinguishes=False))
        self.assertCode('[SIM-RERUN]')


class SimLinkTest(CheckBase):
    """R41: the simulation is tied to the test: names, effects inside the predicted intervals, thresholds of the rule."""

    def test_scenario_name_not_a_competing_hypothesis(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['sensitivity']['simulation']['scenarios'][1].update(name='NULL'))
        self.assertCode('[SIM-LINK]')

    def test_effect_outside_predicted_interval(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['sensitivity']['simulation']['scenarios'][0].update(effect=12.0))
        self.assertCode('[SIM-LINK]')

    def test_thresholds_required_with_simulation(self):
        mutate(self.work(), 'tests.json', lambda d: d['tests'][0]['decision_rule'].pop('thresholds'))
        self.assertCode('[SIM-LINK]')

    def test_thresholds_must_equal_simulated_rule(self):
        mutate(self.work(), 'tests.json',
               lambda d: d['tests'][0]['decision_rule']['thresholds'].update(stop_if_upper_below=2.0))
        self.assertCode('[SIM-LINK]')


class CritiqueRound2Test(CheckBase):
    """R46, R48, R49: trap verdicts, raw output kept with its SHA-256, independence of the critic."""

    def test_valid(self):
        for name in ('valid_vp', 'valid_novp', 'valid_vp_real'):
            self.assertNotIn('[CRITIQUE]', codes(self.problems(name)), name)

    def test_items_not_empty(self):
        mutate(self.work(), 'critique.json', lambda d: d.update(items=[]))
        probs = codes(self.problems())
        self.assertTrue('[SCHEMA]' in probs or '[CRITIQUE]' in probs, probs)

    def test_raw_output_required(self):
        mutate(self.work(), 'critique.json', lambda d: d.pop('raw_output'))
        probs = codes(self.problems())
        self.assertTrue('[SCHEMA]' in probs or '[CRITIQUE]' in probs, probs)

    def test_raw_output_missing_file(self):
        (self.work() / 'critique-raw.json').unlink()
        self.assertCode('[CRITIQUE]')

    def test_raw_output_tampered(self):
        p = self.work() / 'critique-raw.json'
        p.write_text(p.read_text(encoding='utf-8') + ' ', encoding='utf-8')
        self.assertCode('[CRITIQUE]')

    def test_raw_output_outside_directory(self):
        mutate(self.work(), 'critique.json', lambda d: d.update(raw_output='../vp_prior_art/card.json'))
        self.assertCode('[CRITIQUE]')

    def test_item_text_not_in_raw_output(self):
        mutate(self.work(), 'critique.json', lambda d: d['items'][0].update(text='An item the critic never wrote.'))
        self.assertCode('[CRITIQUE]')

    def test_trap_verdicts_required(self):
        mutate(self.work('valid_novp'), 'critique.json', lambda d: d.pop('trap_verdicts'))
        probs = codes(self.problems('valid_novp'))
        self.assertTrue('[SCHEMA]' in probs or '[CRITIQUE]' in probs, probs)

    def test_trap_verdict_per_test_and_trap(self):
        mutate(self.work('valid_novp'), 'critique.json', lambda d: d['trap_verdicts']['T2'].pop('data_split'))
        self.assertCode('[CRITIQUE]', 'valid_novp')
        self.fresh()
        mutate(self.work('valid_novp'), 'critique.json', lambda d: d['trap_verdicts'].pop('T1'))
        self.assertCode('[CRITIQUE]', 'valid_novp')

    def test_trap_verdict_enum(self):
        mutate(self.work('valid_novp'), 'critique.json',
               lambda d: d['trap_verdicts']['T1']['variants'].update(verdict='fine'))
        self.assertCode('[CRITIQUE]', 'valid_novp')

    def test_not_returned_only_on_vp_route(self):
        mutate(self.work('valid_novp'), 'critique.json',
               lambda d: d['trap_verdicts']['T1']['variants'].update(verdict='not_returned'))
        self.assertCode('[CRITIQUE]', 'valid_novp')

    def test_trap_verdict_why_in_raw_output(self):
        mutate(self.work('valid_novp'), 'critique.json',
               lambda d: d['trap_verdicts']['T1']['variants'].update(why='Invented by the orchestrator.'))
        self.assertCode('[CRITIQUE]', 'valid_novp')

    def test_not_addressed_needs_trap_item(self):
        w = self.work('valid_novp')
        raw = w / 'critique-raw.txt'
        raw.write_text(raw.read_text(encoding='utf-8').replace('"verdict": "unclear"', '"verdict": "not_addressed"'),
                       encoding='utf-8')

        def f(d):
            d['trap_verdicts']['T2']['proxy_vs_target']['verdict'] = 'not_addressed'
            d['raw_sha256'] = hashlib.sha256(raw.read_bytes()).hexdigest()
        mutate(w, 'critique.json', f)
        self.assertCode('[CRITIQUE]', 'valid_novp')

    def test_same_family_needs_declaration(self):
        mutate(self.work('valid_novp'), 'critique.json', lambda d: d.pop('no_independent_critic'))
        self.assertCode('[CRITIQUE]', 'valid_novp')

    def test_same_family_only_by_subagent(self):
        # valid_vp uses the vp-contradictor route
        mutate(self.work('valid_vp'), 'critique.json',
               lambda d: d.update(critic_family='claude', same_family=True, no_independent_critic=True))
        self.assertCode('[CRITIQUE]')

    def test_same_family_refused_when_other_family_configured(self):
        env = dict(os.environ, FRONTIER_CRITIC_FAMILIES='openai,gemini')
        r = run_tool('check', self.work('valid_novp'), env=env)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn('[CRITIQUE]', r.stdout)

    def test_same_family_accepted_when_only_host_family_configured(self):
        env = dict(os.environ, FRONTIER_CRITIC_FAMILIES='claude', FRONTIER_HOST_FAMILY='claude')
        r = run_tool('check', self.work('valid_novp'), env=env)
        self.assertNotIn('[CRITIQUE]', r.stdout)

    def test_author_must_be_the_host_family(self):
        env = dict(os.environ, FRONTIER_HOST_FAMILY='openai')
        r = run_tool('check', self.work('valid_vp'), env=env)
        self.assertIn('[CRITIQUE]', r.stdout)

    def test_aliases_from_config(self):
        skill = copy_skill(self.tmp / 'skill-alias')
        set_config(skill, lambda c: c['critic'].update(aliases={'codex': 'openai'}))
        mutate(self.work(), 'critique.json', lambda d: d.update(critic_family='codex'))
        r = run_tool('check', self.work(), tools_dir=skill / 'tools')
        self.assertNotIn('[CRITIQUE]', r.stdout)


class VPRunTest(CheckBase):
    """R54, R56: the VP run named by a reference holds the gateway journal; claims are in card.json and verdicts.json."""

    def test_journal_missing(self):
        (self.fx / 'vp_prior_art' / 'state' / 'journal.jsonl').unlink()
        self.assertCode('[VP-RUN]')

    def test_journal_empty(self):
        (self.fx / 'vp_prior_art' / 'state' / 'journal.jsonl').write_text('', encoding='utf-8')
        self.assertCode('[VP-RUN]')

    def test_journal_not_json(self):
        (self.fx / 'vp_prior_art' / 'state' / 'journal.jsonl').write_text('garbage\n', encoding='utf-8')
        self.assertCode('[VP-RUN]')

    def test_claim_missing_from_card(self):
        mutate(self.fx / 'vp_prior_art', 'card.json', lambda d: d.update(claims=[c for c in d['claims']
                                                                                 if c['id'] != 'A2']))
        self.assertCode('[VP-RUN]')

    def test_fabricated_verdicts_without_journal(self):
        fake = self.fx / 'fake_vp'
        fake.mkdir()
        shutil.copy2(str(self.fx / 'vp_prior_art' / 'card.json'), str(fake / 'card.json'))
        shutil.copy2(str(self.fx / 'vp_prior_art' / 'verdicts.json'), str(fake / 'verdicts.json'))
        mutate(self.work(), 'intake.json', lambda d: d['vp']['runs'].update(prior_art='../fake_vp'))
        self.assertCode('[VP-RUN]')

    def test_prior_art_answer_matches_vp(self):
        mutate(self.work(), 'prior_art.json', lambda d: d.update(answer='Exists'))
        self.assertCode('[PRIOR-ART]')
        self.fresh()
        (self.fx / 'vp_prior_art' / 'PRIOR-ART.md').unlink()
        self.assertCode('[PRIOR-ART]')


class VPModeTest(CheckBase):
    """R55: vp.mode "none" is refused when VP is detected, unless a reason is written."""

    def novp_without_reason(self):
        mutate(self.work('valid_novp'), 'intake.json', lambda d: d['vp'].pop('none_reason'))

    def test_refused_when_vp_detected(self):
        self.novp_without_reason()
        vp = self.tmp / 'vp'
        vp.mkdir()
        (vp / 'SKILL.md').write_text('---\nname: vanishingpoint\ndescription: test double\n---\n', encoding='utf-8')
        skill = copy_skill(vp)
        r = run_tool('check', self.work('valid_novp'), tools_dir=skill / 'tools')
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn('[VP-MODE]', r.stdout)

    def test_accepted_when_vp_absent(self):
        self.novp_without_reason()
        skill = copy_skill(self.tmp / 'lonely')
        r = run_tool('check', self.work('valid_novp'), tools_dir=skill / 'tools',
                     env=dict(os.environ, FRONTIER_VP_DIR=''))
        self.assertNotIn('[VP-MODE]', r.stdout)

    def test_reason_must_be_written(self):
        vp = self.tmp / 'vp'
        vp.mkdir()
        (vp / 'SKILL.md').write_text('---\nname: vanishingpoint\ndescription: test double\n---\n', encoding='utf-8')
        skill = copy_skill(vp)
        r = run_tool('check', self.work('valid_novp'), tools_dir=skill / 'tools')
        self.assertNotIn('[VP-MODE]', r.stdout)
        mutate(self.work('valid_novp'), 'intake.json', lambda d: d['vp'].update(none_reason='n/a'))
        r = run_tool('check', self.work('valid_novp'), tools_dir=skill / 'tools')
        self.assertIn('[VP-MODE]', r.stdout)


class DateTest(CheckBase):
    """R57, R58: date barrier T."""

    def test_vp_journal_after_T(self):
        p = self.fx / 'vp_prior_art' / 'state' / 'journal.jsonl'
        p.write_text(p.read_text(encoding='utf-8').replace('"T": "2026-11-14"', '"T": "2026-12-31"'), encoding='utf-8')
        self.assertCode('[DATE]')

    def test_vp_journal_before_T_ok(self):
        p = self.fx / 'vp_prior_art' / 'state' / 'journal.jsonl'
        p.write_text(p.read_text(encoding='utf-8').replace('"T": "2026-11-14"', '"T": "2026-01-01"'), encoding='utf-8')
        self.assertNotIn('[DATE]', codes(self.problems()))

    def test_year_in_vp_card_after_T(self):
        mutate(self.fx / 'vp_prior_art', 'card.json', lambda d: d['sources']['S1'].update(year='2027'))
        self.assertCode('[DATE]')

    def test_year_in_reference_after_T(self):
        mutate(self.work(), 'prior_art.json', lambda d: d['closest_work'][1].update(year='2028'))
        self.assertCode('[DATE]')

    def test_year_without_vp(self):
        mutate(self.work('valid_novp'), 'hypotheses.json',
               lambda d: d['hypotheses'][0]['for'][0].update(year='2030'))
        self.assertCode('[DATE]', 'valid_novp')

    def test_year_from_real_vp_studies(self):
        """Real VP runs carry no year in card.json: it is read in STUDIES.json / result.json of the run."""
        mutate(self.work('valid_vp_real'), 'intake.json', lambda d: d.update(T='2022-06-30'))
        probs = self.problems('valid_vp_real')
        self.assertTrue(any(p.startswith('[DATE]') and '10.1016/j.transci.2023.103839' in p for p in probs), probs)


class BudgetTest(CheckBase):
    """R62: budget per idea, from run.json: at most 3 VP runs, 1 critique, 1 execution."""

    def add_steps(self, name, step, k, **extra):
        def f(d):
            for i in range(k):
                d['steps'].append(dict({'step': step, 'utc': '2026-11-14T09:0%d:00Z' % i, 'duration_s': 'unknown',
                                        'cost_usd': 'unknown'}, **extra))
        mutate(self.work(name), 'run.json', f)

    def test_run_json_required(self):
        (self.work() / 'run.json').unlink()
        self.assertCode('[RUNLOG]')

    def test_too_many_vp_runs(self):
        self.add_steps('valid_vp', 'vp_run', 3, vp_run='hypotheses')
        self.assertCode('[BUDGET]')

    def test_three_vp_runs_ok(self):
        self.add_steps('valid_vp', 'vp_run', 2, vp_run='hypotheses')
        self.assertNotIn('[BUDGET]', codes(self.problems()))

    def test_two_critiques(self):
        self.add_steps('valid_novp', 'critique', 1)
        self.assertCode('[BUDGET]', 'valid_novp')

    def test_two_executions(self):
        self.add_steps('valid_vp', 'execution', 1)
        self.assertCode('[BUDGET]')

    def test_vp_run_without_step(self):
        mutate(self.work(), 'run.json', lambda d: d.update(steps=[s for s in d['steps'] if s['step'] != 'vp_run']))
        self.assertCode('[BUDGET]')

    def test_critique_without_step(self):
        mutate(self.work(), 'run.json', lambda d: d.update(steps=[s for s in d['steps'] if s['step'] != 'critique']))
        self.assertCode('[BUDGET]')

    def test_execution_without_step(self):
        mutate(self.work(), 'run.json', lambda d: d.update(steps=[s for s in d['steps'] if s['step'] != 'execution']))
        self.assertCode('[BUDGET]')

    def test_bad_cost_value(self):
        mutate(self.work(), 'run.json', lambda d: d['steps'][0].update(cost_usd='cheap'))
        self.assertCode('[RUNLOG]')


if __name__ == '__main__':
    unittest.main()
