# SPDX-License-Identifier: Apache-2.0
"""check.py on the rebound files (regression specification RB5-RB22, RB24): operator, materials, structure, prior art on every idea
before any ranking, quotas, duplicates, references, no novelty score, feasibility, selection, step 8-bis, header, budget."""
import copy
import json

from .helpers import HEADER, load_tool, mutate, read_json, run_tool, write_json
from .rb_common import NOVP, RB, VP


class ValidTest(RB):
    def test_valid_with_vp(self):
        self.assertEqual(self.probs(VP), [])

    def test_valid_without_vp(self):
        self.assertEqual(self.probs(NOVP), [])

    def test_directories_without_rebound_unchanged(self):
        self.assertEqual(self.probs('valid_vp'), [])
        self.assertEqual(self.probs('valid_novp'), [])

    def test_cli(self):
        ok = run_tool('check', self.work(VP))
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.idea(VP, 'N1', lambda i: i.update(operator='magic'))
        bad = run_tool('check', self.work(VP))
        self.assertEqual(bad.returncode, 1)

    def test_invalid_json(self):
        (self.work(VP) / 'rebound.json').write_text('{oops', encoding='utf-8')
        self.assertCode('[JSON]')

    def test_references_of_rebound_are_read(self):
        st = self.check.reference_statuses(self.work(VP))
        self.assertEqual(st.get('doi:10.1000/rb.n1.2021'), 'FOUND')
        self.assertEqual(st.get('doi:10.1000/clicks.2022'), 'UNVERIFIED')


class OperatorTest(RB):
    def test_operator_missing(self):
        self.idea(VP, 'N1', lambda i: i.pop('operator'))
        self.assertAnyCode(['[SCHEMA]', '[REB-OPERATOR]'])

    def test_operator_unknown(self):
        self.idea(VP, 'N1', lambda i: i.update(operator='magic'))
        self.assertAnyCode(['[SCHEMA]', '[REB-OPERATOR]'])

    def test_recurring_ingredient_must_be_boolean(self):
        self.idea(VP, 'N1', lambda i: i.update(recurring_ingredient='yes'))
        self.assertAnyCode(['[SCHEMA]', '[REB-OPERATOR]'])
        self.fresh()
        self.idea(VP, 'N1', lambda i: i.pop('recurring_ingredient'))
        self.assertAnyCode(['[SCHEMA]', '[REB-OPERATOR]'])

    def test_unmeasured_operators_cannot_claim_measured(self):
        for op in ('anomaly', 'revived_old_idea', 'hypothesis_inversion', 'morphological_analysis'):
            with self.subTest(op=op):
                self.fresh()
                self.idea(VP, 'N5', lambda i: i.update(operator=op, recurring_ingredient=True))
                self.assertCode('[REB-OPERATOR]')

    def test_measured_operators_may_be_true_or_false(self):
        self.idea(VP, 'N1', lambda i: i.update(recurring_ingredient=False))
        self.assertEqual(self.probs(), [])

    def test_analogy_needs_correspondence_and_break(self):
        self.idea(VP, 'N2', lambda i: i.pop('analogy'))
        self.assertAnyCode(['[REB-OPERATOR]'])
        self.fresh()
        self.idea(VP, 'N2', lambda i: i['analogy'].update(breaks=' '))
        self.assertAnyCode(['[REB-OPERATOR]', '[SCHEMA]'])
        self.fresh()
        self.idea(VP, 'N2', lambda i: i['analogy'].pop('corresponds'))
        self.assertAnyCode(['[REB-OPERATOR]', '[SCHEMA]'])

    def test_bridge_needs_its_concept(self):
        self.idea(VP, 'N3', lambda i: i.pop('bridge'))
        self.assertCode('[REB-OPERATOR]')


class MaterialTest(RB):
    def test_materials_required(self):
        self.idea(VP, 'N1', lambda i: i.update(materials=[]))
        self.assertAnyCode(['[SCHEMA]', '[REB-MATERIAL]'])
        self.fresh()
        self.idea(VP, 'N1', lambda i: i.pop('materials'))
        self.assertAnyCode(['[SCHEMA]', '[REB-MATERIAL]'])

    def test_entry_must_resolve(self):
        for entry in ('hypotheses.json:H9', 'prior_art.json:materials.transferable_methods[7]', 'tests.json:T9',
                      'result.json:T9', 'notes.txt:1', 'prior_art.json:closest_work[9]'):
            with self.subTest(entry=entry):
                self.fresh()
                self.idea(VP, 'N5', lambda i: i['materials'].__setitem__(0, {'kind': 'entry', 'entry': entry, 'why': 'x'}))
                self.assertCode('[REB-MATERIAL]')

    def test_entries_that_resolve(self):
        for entry in ('hypotheses.json:R1', 'hypotheses.json:V1', 'prior_art.json:materials.transferable_methods[0]',
                      'prior_art.json:closest_work[1]', 'tests.json:T1', 'result.json:T1'):
            with self.subTest(entry=entry):
                self.fresh()
                self.idea(VP, 'N5', lambda i: i['materials'].__setitem__(0, {'kind': 'entry', 'entry': entry, 'why': 'x'}))
                self.assertEqual(self.probs(), [])

    def test_reference_material_needs_ref(self):
        self.idea(VP, 'N1', lambda i: i['materials'].__setitem__(0, {'kind': 'reference', 'why': 'x'}))
        self.assertAnyCode(['[SCHEMA]', '[REB-MATERIAL]'])

    def test_anomaly_needs_an_anomaly_material(self):
        self.idea(VP, 'N4', lambda i: i.update(materials=[{'kind': 'entry', 'entry': 'hypotheses.json:H1', 'why': 'x'}]))
        self.assertCode('[REB-MATERIAL]')
        self.fresh()
        self.idea(VP, 'N4', lambda i: i.update(materials=[{'kind': 'entry', 'entry': 'prior_art.json:materials.contradictory_results[0]', 'why': 'x'}]))
        self.assertEqual(self.probs(), [])

    def test_several_materials_allowed(self):
        self.idea(VP, 'N4', lambda i: i['materials'].append({'kind': 'entry', 'entry': 'hypotheses.json:H2', 'why': 'x'}))
        self.assertEqual(self.probs(), [])


class StructureTest(RB):
    def test_placeholders_refused(self):
        cases = [('mechanism', 'summary', 'tbd'), ('mechanism', 'goal', 'n/a'), ('hypothesis', 'statement', 'short'),
                 ('hypothesis', 'false_if', '-'), ('test', 'one_line', ''), ('test', 'variable', 'x'),
                 ('test', 'if_holds', 'none'), ('test', 'if_fails', 'tbd')]
        for block, field, val in cases:
            with self.subTest(block=block, field=field):
                self.fresh()
                self.idea(VP, 'N1', lambda i: i[block].update({field: val}))
                self.assertAnyCode(['[REB-STRUCT]', '[SCHEMA]'])

    def test_structured_blocks_required(self):
        for block in ('mechanism', 'hypothesis', 'test', 'teaches', 'tradeoffs', 'feasibility', 'prior_art'):
            with self.subTest(block=block):
                self.fresh()
                self.idea(VP, 'N1', lambda i: i.pop(block))
                self.assertCode('[SCHEMA]')

    def test_teaches_and_tradeoffs(self):
        self.idea(VP, 'N1', lambda i: i.update(teaches='n/a'))
        self.assertCode('[REB-STRUCT]')
        for key in ('gains', 'costs', 'assumptions', 'uncertainties'):
            with self.subTest(key=key):
                self.fresh()
                self.idea(VP, 'N1', lambda i: i['tradeoffs'].update({key: []}))
                self.assertAnyCode(['[SCHEMA]', '[REB-STRUCT]'])
                self.fresh()
                self.idea(VP, 'N1', lambda i: i['tradeoffs'].update({key: ['-']}))
                self.assertCode('[REB-STRUCT]')

    def test_duplicate_idea_ids(self):
        self.idea(VP, 'N2', lambda i: i.update(id='N1'))
        self.assertCode('[REB-STRUCT]')

    def test_idea_ids_follow_the_stage(self):
        self.idea(VP, 'B1', lambda i: i.update(id='N7'), 'rebound_after.json')
        self.assertAnyCode(['[REB-STRUCT]', '[SCHEMA]'])


class PriorArtTest(RB):
    def test_prior_art_on_every_idea(self):
        self.idea(VP, 'N3', lambda i: i.pop('prior_art'))
        probs = self.assertCode('[SCHEMA]')
        self.assertTrue(any(p.startswith('[REB-ORDER]') for p in probs), probs)

    def test_status_enum(self):
        self.idea(VP, 'N2', lambda i: i['prior_art'].update(status='Novel'))
        self.assertCode('[SCHEMA]')
        self.fresh()
        for st in ('Exists', 'Partially', 'Not found', 'Insufficient search'):
            self.assertIn(st, json.dumps(read_json(self.work(VP) / 'rebound.json')))

    def test_exists_and_partially_need_the_closest_work(self):
        self.idea(VP, 'N3', lambda i: i['prior_art'].update(closest_work=[]))
        self.assertCode('[REB-PRIOR-ART]')
        self.fresh()
        self.idea(VP, 'N1', lambda i: i['prior_art'].update(closest_work=[]))
        self.assertCode('[REB-PRIOR-ART]')

    def test_closest_work_needs_what_differs_and_ref(self):
        self.idea(VP, 'N3', lambda i: i['prior_art']['closest_work'][0].update(what_differs=' '))
        self.assertAnyCode(['[REB-PRIOR-ART]', '[SCHEMA]'])
        self.fresh()
        self.idea(VP, 'N3', lambda i: i['prior_art']['closest_work'][0].pop('ref'))
        self.assertAnyCode(['[REB-PRIOR-ART]', '[SCHEMA]'])

    def test_partially_shows_the_exact_difference(self):
        self.idea(VP, 'N1', lambda i: i['prior_art'].pop('difference'))
        self.assertCode('[REB-PRIOR-ART]')

    def test_queries_scope_and_date_written(self):
        self.idea(VP, 'N2', lambda i: i['prior_art'].update(queries=[]))
        self.assertCode('[REB-PRIOR-ART]')
        self.fresh()
        self.idea(VP, 'N2', lambda i: i['prior_art'].update(scope=' '))
        self.assertCode('[REB-PRIOR-ART]')
        self.fresh()
        self.idea(VP, 'N2', lambda i: i['prior_art'].update(date='14/11/2026'))
        self.assertCode('[SCHEMA]')
        self.fresh()
        self.idea(VP, 'N2', lambda i: i['prior_art'].pop('date'))
        self.assertCode('[SCHEMA]')

    def test_with_vp_the_run_is_required(self):
        self.idea(VP, 'N2', lambda i: i['prior_art'].pop('vp_run'))
        self.assertCode('[REB-PRIOR-ART]')

    def test_vp_run_must_be_listed(self):
        self.idea(VP, 'N2', lambda i: i['prior_art'].update(vp_run='ghost'))
        self.assertCode('[REB-PRIOR-ART]')

    def test_status_is_the_answer_of_the_vp_run(self):
        self.idea(VP, 'N2', lambda i: i['prior_art'].update(
            status='Exists', closest_work=[{'ref': {'id': 'doi:10.1000/rb.n2.2021', 'run': 'rb_n2', 'claim': 'A1'},
                                            'title': 'A headline study', 'year': '2021', 'what_differs': 'Differs in the engine.'}]))
        self.assertCode('[REB-PRIOR-ART]')
        self.fresh()
        self.idea(VP, 'N1', lambda i: i['prior_art'].update(status='Not found'))
        self.assertCode('[REB-PRIOR-ART]')   # never softened

    def test_insufficient_search_may_lower_the_answer(self):
        self.assertEqual(self.probs(), [])   # N5: VP says NOT FOUND, the idea says Insufficient search

    def test_without_vp_no_vp_run_needed(self):
        self.assertEqual(self.probs(NOVP), [])

    def test_model_recognition_without_source_is_flagged_unverified(self):
        self.idea(VP, 'N2', lambda i: i['prior_art'].update(recognised_by_model_only=True))
        probs = self.check.run_all(self.work(VP))
        self.assertTrue(any('[REB-PRIOR-ART]' in w for w in probs[1]), probs[1])


class OrderTest(RB):
    def test_ranking_before_prior_art(self):
        self.mut(VP, lambda d: d['ranking'].update(ranked_utc='2026-11-14T13:00:00Z'))
        self.assertCode('[REB-ORDER]')

    def test_ranking_needs_its_time(self):
        self.mut(VP, lambda d: d['ranking'].pop('ranked_utc'))
        self.assertAnyCode(['[SCHEMA]', '[REB-ORDER]'])

    def test_selection_needs_ranking(self):
        self.mut(VP, lambda d: d.pop('ranking'))
        self.assertCode('[REB-ORDER]')

    def test_selection_after_ranking(self):
        self.mut(VP, lambda d: d['selection'].update(decided_utc='2026-11-14T13:50:00Z'))
        self.assertCode('[REB-ORDER]')

    def test_unranked_is_allowed(self):
        self.mut(VP, lambda d: (d.pop('ranking'), d.pop('selection')))
        mutate(self.fx, 'IDEA-TREE.json', lambda d: [n.update(status='proposed') for n in d['nodes']
                                                     if n['status'] in ('retained', 'rejected')])
        self.assertEqual(self.probs(), [])

    def test_ranking_scenarios_explicit(self):
        self.mut(VP, lambda d: d['ranking']['scenarios'][0].update({'why': ''}))
        self.assertAnyCode(['[REB-ORDER]', '[SCHEMA]', '[REB-STRUCT]'])
        self.fresh()
        self.mut(VP, lambda d: d['ranking']['scenarios'][0].update({'prefer': ['N9']}))
        self.assertAnyCode(['[REB-ORDER]'])

    def test_no_imposed_order(self):
        self.mut(VP, lambda d: d['ranking'].update(order=['N1', 'N4']))
        self.assertAnyCode(['[SCHEMA]', '[REB-NOVELTY]'])


class UncontrolledTest(RB):
    def make_uncontrolled(self, name=VP):
        def go(i):
            i['prior_art'] = {'status': 'Insufficient search', 'queries': [], 'scope': 'Not checked: budget used.',
                              'date': '2026-11-14T13:40:00Z', 'closest_work': [], 'uncontrolled': True}
        self.idea(name, 'N5', go)

    def test_refused_while_budget_remains(self):
        self.make_uncontrolled()
        self.assertCode('[REB-PRIOR-ART]')

    def test_allowed_when_budget_is_used(self):
        # modified round 2 (RB42): allowed only while nothing is ranked or chosen
        tools = self.skill_copy(prior_art_checks_max=4)
        self.make_uncontrolled()
        self.drop_ranking()
        r = run_tool('check', self.work(VP), tools_dir=tools)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_forbids_any_ranking_or_choice(self):
        tools = self.skill_copy(prior_art_checks_max=4)
        self.make_uncontrolled()
        r = run_tool('check', self.work(VP), tools_dir=tools)
        self.assertEqual(r.returncode, 1)
        self.assertIn('[REB-ORDER]', r.stdout)

    def test_status_must_be_insufficient(self):
        tools = self.skill_copy(prior_art_checks_max=4)
        self.make_uncontrolled()
        self.idea(VP, 'N5', lambda i: i['prior_art'].update(status='Not found'))
        r = run_tool('check', self.work(VP), tools_dir=tools)
        self.assertEqual(r.returncode, 1)
        self.assertIn('[REB-PRIOR-ART]', r.stdout)

    def test_prior_art_budget_per_file(self):
        tools = self.skill_copy(prior_art_checks_max=4)
        r = run_tool('check', self.work(VP), tools_dir=tools)   # 5 controlled ideas, cap 4
        self.assertEqual(r.returncode, 1)
        self.assertIn('[BUDGET]', r.stdout)


class QuotaTest(RB):
    def test_too_few_in_step_8(self):
        self.mut(VP, lambda d: d['ideas'].pop())
        self.assertCode('[REB-QUOTA]')

    def test_too_many_in_step_8(self):
        tools = self.skill_copy(ideas_max=4)
        r = run_tool('check', self.work(VP), tools_dir=tools)
        self.assertEqual(r.returncode, 1)
        self.assertIn('[REB-QUOTA]', r.stdout)

    def test_step_8_bis_quota(self):
        self.mut(VP, lambda d: d['ideas'].pop(), 'rebound_after.json')
        self.assertCode('[REB-QUOTA]')
        self.fresh()
        tools = self.skill_copy(after_max=1)
        r = run_tool('check', self.work(VP), tools_dir=tools)
        self.assertIn('[REB-QUOTA]', r.stdout)

    def test_at_most_two_per_operator(self):
        self.idea(VP, 'N4', lambda i: i.update(operator='facet_recombination', recurring_ingredient=False,
                                               materials=[{'kind': 'entry', 'entry': 'hypotheses.json:H1', 'why': 'x'}]))
        self.assertEqual(self.probs(), [])   # two facet recombinations: allowed
        self.idea(VP, 'N5', lambda i: i.update(operator='facet_recombination', recurring_ingredient=False))
        self.assertCode('[REB-QUOTA]')

    def test_at_most_two_per_operator_in_step_8_bis(self):
        self.idea(VP, 'B2', lambda i: i.update(operator='facet_recombination'), 'rebound_after.json')
        self.assertEqual(self.probs(), [])
        self.mut(VP, lambda d: d['ideas'].append(_third_facet(d)), 'rebound_after.json')
        self.assertCode('[REB-QUOTA]')


def _third_facet(d):
    it = copy.deepcopy(d['ideas'][0])
    it['id'] = 'B3'
    return it


class DuplicateTest(RB):
    def test_same_mechanism_is_reported_not_removed(self):
        self.idea(VP, 'N2', lambda i: i['mechanism'].update(summary=_summary(self, 'N1')))
        self.assertCode('[REB-DUP]')
        d = read_json(self.work(VP) / 'rebound.json')
        self.assertEqual(len(d['ideas']), 5)   # nothing removed

    def test_recorded_group_matches(self):
        self.idea(VP, 'N2', lambda i: i['mechanism'].update(summary=_summary(self, 'N1')))
        self.mut(VP, lambda d: d.update(duplicate_groups=[{'ids': ['N1', 'N2'], 'fields': ['mechanism']}]))
        self.assertNoCode('[REB-DUP]')
        res = self.check.run_all(self.work(VP))
        self.assertTrue(any(w.startswith('[REB-DUP]') for w in res[1]), res[1])   # still shown as a warning

    def test_wrong_recorded_group(self):
        self.idea(VP, 'N2', lambda i: i['mechanism'].update(summary=_summary(self, 'N1')))
        self.mut(VP, lambda d: d.update(duplicate_groups=[{'ids': ['N1', 'N3'], 'fields': ['mechanism']}]))
        self.assertCode('[REB-DUP]')

    def test_recorded_group_that_does_not_exist(self):
        self.mut(VP, lambda d: d.update(duplicate_groups=[{'ids': ['N1', 'N2'], 'fields': ['test']}]))
        self.assertCode('[REB-DUP]')

    def test_hypothesis_test_and_text_fields(self):
        for field, setter, name in (
                ('hypothesis', lambda i, j: i['hypothesis'].update(statement=j['hypothesis']['statement']), 'hypothesis'),
                ('test', lambda i, j: i['test'].update(one_line=j['test']['one_line']), 'test'),
                ('text', lambda i, j: i.update(title=j['title'], statement=j['statement']), 'text')):
            with self.subTest(field=field):
                self.fresh()
                src = read_json(self.work(VP) / 'rebound.json')['ideas'][0]
                self.idea(VP, 'N3', lambda i: setter(i, src))
                self.mut(VP, lambda d: d.update(duplicate_groups=[{'ids': ['N1', 'N3'], 'fields': [name]}]))
                self.assertNoCode('[REB-DUP]')

    def test_distinct_ideas_make_no_group(self):
        d = read_json(self.work(VP) / 'rebound.json')
        self.assertEqual(d['duplicate_groups'], [])
        self.assertNoCode('[REB-DUP]')


def _summary(case, iid):
    d = read_json(case.work(VP) / 'rebound.json')
    return [i for i in d['ideas'] if i['id'] == iid][0]['mechanism']['summary']


class ReferenceTest(RB):
    def verdict(self, run, claim, status):
        def go(d):
            for c in d['claims']:
                if c['id'] == claim:
                    c['status'] = status
        mutate(self.work(run), 'verdicts.json', go)

    def test_absent_and_invalid_in_materials(self):
        self.verdict('vp_prior_art', 'A1', 'ABSENT')
        self.assertCode('[REF-ABSENT]')
        self.fresh()
        self.verdict('vp_prior_art', 'A1', 'INVALID')
        self.assertCode('[REF-INVALID]')

    def test_absent_and_invalid_in_closest_work(self):
        self.verdict('vp_rb_n1', 'A1', 'ABSENT')
        probs = self.assertCode('[REF-ABSENT]')
        self.assertTrue(any('rebound.json' in p for p in probs if p.startswith('[REF-ABSENT]')), probs)
        self.fresh()
        self.verdict('vp_rb_b1', 'A1', 'INVALID')
        probs = self.assertCode('[REF-INVALID]')
        self.assertTrue(any('rebound_after.json' in p for p in probs if p.startswith('[REF-INVALID]')), probs)

    def test_unverified_passes_and_is_listed(self):
        self.verdict('vp_rb_n1', 'A1', 'UNVERIFIED')
        self.assertEqual(self.probs(), [])
        self.assertIn(('doi:10.1000/rb.n1.2021', 'UNVERIFIED'), self.check.unverified_references(self.work(VP)))

    def test_no_verdict_and_no_run(self):
        self.idea(VP, 'N1', lambda i: i['prior_art']['closest_work'][0]['ref'].update(claim='A9'))
        self.assertAnyCode(['[REF-MISSING]', '[VP-RUN]'])
        self.fresh()
        self.idea(VP, 'N1', lambda i: i['prior_art']['closest_work'][0]['ref'].pop('run'))
        self.assertCode('[REF-MISSING]')

    def test_identifier_must_be_the_claim_source(self):
        self.idea(VP, 'N1', lambda i: i['prior_art']['closest_work'][0]['ref'].update(id='doi:10.1000/other'))
        self.assertCode('[REF-MISMATCH]')

    def test_date_after_T(self):
        self.idea(VP, 'N1', lambda i: i['prior_art']['closest_work'][0].update(year='2031'))
        self.assertCode('[DATE]')

    def test_feasibility_reference_checked(self):
        self.idea(VP, 'N1', lambda i: i['feasibility']['data'].update(
            ref={'id': 'doi:10.1000/titles.2019', 'run': 'prior_art', 'claim': 'A1'}))
        self.assertEqual(self.probs(), [])
        self.verdict('vp_prior_art', 'A1', 'ABSENT')
        self.assertCode('[REF-ABSENT]')

    def test_without_vp_no_status(self):
        self.assertEqual(self.check.reference_statuses(self.work(NOVP)), {})


class NoveltyScoreTest(RB):
    def test_numeric_fields_refused(self):
        for key, val in (('novelty_score', 8), ('score', 3), ('rating', 0.7), ('originality', 9)):
            with self.subTest(key=key):
                self.fresh()
                self.idea(VP, 'N1', lambda i: i.update({key: val}))
                self.assertCode('[REB-NOVELTY]')

    def test_number_anywhere_else_in_an_idea(self):
        self.idea(VP, 'N1', lambda i: i['tradeoffs'].update(extra=7))
        self.assertAnyCode(['[REB-NOVELTY]', '[SCHEMA]'])
        self.fresh()
        self.idea(VP, 'N1', lambda i: i['prior_art'].update(count=3))
        self.assertAnyCode(['[REB-NOVELTY]', '[SCHEMA]'])

    def test_score_in_text(self):
        for txt in ('Novelty 8/10 for this idea.', 'Originality: 7 out of 10.', 'A novelty score of 4.5 points.'):
            with self.subTest(txt=txt):
                self.fresh()
                self.idea(VP, 'N1', lambda i: i.update(teaches=txt + ' It would show where authors should act.'))
                self.assertCode('[REB-NOVELTY]')

    def test_certification_wording(self):
        for txt in ('This idea is novel and valuable for authors.', 'It is unprecedented in the field of retrieval.',
                    'Nothing like it has ever been done before, so this is groundbreaking.'):
            with self.subTest(txt=txt):
                self.fresh()
                self.idea(VP, 'N1', lambda i: i.update(statement=txt))
                self.assertCode('[REB-NOVELTY]')

    def test_not_found_is_never_new(self):
        self.idea(VP, 'N2', lambda i: i['prior_art'].update(scope='Nothing found, so the idea is new.'))
        self.assertCode('[REB-NOVELTY]')

    def test_number_in_ranking(self):
        self.mut(VP, lambda d: d['ranking']['scenarios'][0].update(rank=1))
        self.assertAnyCode(['[REB-NOVELTY]', '[SCHEMA]'])
        self.fresh()
        self.mut(VP, lambda d: d['ranking']['scenarios'][0].update(why='Scores 9 out of 10 on feasibility, so first.'))
        self.assertCode('[REB-NOVELTY]')

    def test_amounts_and_years_are_not_scores(self):
        d = read_json(self.work(VP) / 'rebound.json')
        amounts = [v['amount'] for i in d['ideas'] for v in i['feasibility'].values() if 'amount' in v]
        self.assertTrue(amounts)
        self.assertEqual(self.probs(), [])


class FeasibilityTest(RB):
    def test_established_needs_name_and_access(self):
        for el, drop in (('data', 'name'), ('data', 'access'), ('tool', 'name'), ('tool', 'access')):
            with self.subTest(el=el, drop=drop):
                self.fresh()
                self.idea(VP, 'N1', lambda i: i['feasibility'][el].pop(drop))
                self.assertCode('[REB-FEAS]')

    def test_established_cost_needs_amount_and_unit(self):
        for el, drop in (('time', 'amount'), ('time', 'unit'), ('compute', 'amount'), ('compute', 'unit')):
            with self.subTest(el=el, drop=drop):
                self.fresh()
                self.idea(VP, 'N1', lambda i: i['feasibility'][el].pop(drop))
                self.assertCode('[REB-FEAS]')

    def test_status_enum(self):
        self.idea(VP, 'N1', lambda i: i['feasibility']['data'].update(status='probably'))
        self.assertCode('[SCHEMA]')

    def test_not_established_is_fine(self):
        self.idea(VP, 'N1', lambda i: i.update(feasibility={k: {'status': 'not established'} for k in ('data', 'tool', 'time', 'compute')}))
        self.assertEqual(self.probs(), [])

    def test_placeholder_name_refused(self):
        self.idea(VP, 'N1', lambda i: i['feasibility']['data'].update(name='tbd'))
        self.assertCode('[REB-FEAS]')

    def test_all_four_elements_required(self):
        self.idea(VP, 'N1', lambda i: i['feasibility'].pop('compute'))
        self.assertCode('[SCHEMA]')


class SelectionTest(RB):
    def test_at_most_two_retained(self):
        self.mut(VP, lambda d: d['selection'].update(retained=['N1', 'N3', 'N4']))
        self.assertCode('[REB-SELECT]')

    def test_zero_retained_is_allowed(self):
        self.mut(VP, lambda d: d['selection'].update(retained=[]))
        self.mut(VP, lambda d: d['selection'].update(retained=[], rejected=[]))
        self.assertNoCode('[REB-SELECT]')

    def test_unknown_and_overlapping_ids(self):
        self.mut(VP, lambda d: d['selection'].update(retained=['N9']))
        self.assertCode('[REB-SELECT]')
        self.fresh()
        self.mut(VP, lambda d: d['selection'].update(rejected=[{'id': 'N1', 'reason': 'Both retained and rejected.'}]))
        self.assertCode('[REB-SELECT]')

    def test_no_user_no_choice(self):
        self.mut(VP, lambda d: d['selection'].update(decided_by='assumption'))
        self.assertCode('[REB-SELECT]')
        self.fresh()
        self.mut(VP, lambda d: d['selection'].update(decided_by='model'))
        self.assertCode('[SCHEMA]')

    def test_the_tree_follows_the_selection(self):
        def go(d):
            for n in d['nodes']:
                if n['source'] and n['source']['idea_id'] == 'N1' and n['source']['file'] == 'rebound.json':
                    n['status'] = 'proposed'
        mutate(self.fx, 'IDEA-TREE.json', go)
        self.assertCode('[REB-TREE]')

    def test_retained_duplicate_or_done_gives_a_warning(self):
        self.mut(VP, lambda d: d['selection'].update(retained=['N3']))
        mutate(self.fx, 'IDEA-TREE.json', lambda d: [n.update(status='retained') for n in d['nodes']
                                                     if n['source'] and n['source']['idea_id'] == 'N3'])
        mutate(self.fx, 'IDEA-TREE.json', lambda d: [n.update(status='proposed') for n in d['nodes']
                                                     if n['source'] and n['source']['idea_id'] == 'N1'
                                                     and n['source']['file'] == 'rebound.json'])
        probs, warns = self.check.run_all(self.work(VP))
        self.assertEqual(probs, [])
        self.assertTrue(any('[REB-SELECT]' in w and 'already done' in w for w in warns), warns)


class AfterTest(RB):
    def f(self, fn):
        self.mut(VP, fn, 'rebound_after.json')

    def test_unknown_test(self):
        self.f(lambda d: d.update(after_test='T9'))
        self.assertCode('[REB-AFTER]')

    def test_needs_an_after_entry(self):
        p = self.work(VP) / 'decision_log.jsonl'
        lines = p.read_text(encoding='utf-8').splitlines()
        p.write_text(lines[0] + '\n', encoding='utf-8')
        self.assertCode('[REB-AFTER]')

    def test_outcome_follows_the_executed_result(self):
        self.f(lambda d: d.update(outcome='refuted'))
        self.assertCode('[REB-AFTER]')
        self.fresh()
        self.f(lambda d: d.update(outcome='indeterminate'))
        self.assertCode('[REB-AFTER]')

    def test_outcome_enum_and_source(self):
        self.f(lambda d: d.update(outcome='won'))
        self.assertCode('[SCHEMA]')
        self.fresh()
        self.f(lambda d: d.pop('outcome_source'))
        self.assertAnyCode(['[SCHEMA]', '[REB-AFTER]'])

    def test_follow_up_kind_follows_the_outcome(self):
        def go(d):
            d['ideas'][0]['follow_up_kind'] = 'competing_explanation'
        self.f(go)
        self.assertCode('[REB-AFTER]')
        self.fresh()
        self.f(lambda d: d['ideas'][0].pop('follow_up_kind'))
        self.assertAnyCode(['[REB-AFTER]', '[SCHEMA]'])

    def test_refuted_outcome_with_a_stopped_result(self):
        def stop(d):
            d['decision'] = 'stop'
        mutate(self.work(VP), 'result.json', stop)
        self.assertCode('[REB-AFTER]')   # confirmed does not match stop
        self.f(lambda d: (d.update(outcome='refuted'), [i.update(follow_up_kind='repairable_variant') for i in d['ideas']]))
        self.assertNoCode('[REB-AFTER]')

    def test_revise_counts_as_refuted(self):
        mutate(self.work(VP), 'result.json', lambda d: d.update(decision='revise'))
        self.f(lambda d: (d.update(outcome='refuted'), [i.update(follow_up_kind='competing_explanation') for i in d['ideas']]))
        self.assertNoCode('[REB-AFTER]')

    def test_plan_only_takes_the_declared_outcome(self):
        mutate(self.work(VP), 'result.json', lambda d: (d.clear(), d.update(mode='plan only', reason='No container engine here.')))
        self.f(lambda d: d.update(outcome='refuted', outcome_source='researcher'))
        self.f(lambda d: [i.update(follow_up_kind='repairable_variant') for i in d['ideas']])
        self.assertNoCode('[REB-AFTER]')

    def test_step_8_has_no_after_fields(self):
        self.mut(VP, lambda d: d.update(after_test='T1'))
        self.assertAnyCode(['[REB-STAGE]', '[SCHEMA]'])


class HeaderAndStageTest(RB):
    def test_without_vp_header_required(self):
        self.mut(NOVP, lambda d: d.pop('header'))
        self.assertCode('[HEADER]', NOVP)
        self.fresh()
        self.mut(NOVP, lambda d: d.update(header='References checked'))
        self.assertCode('[HEADER]', NOVP)

    def test_with_vp_no_header(self):
        self.mut(VP, lambda d: d.update(header=HEADER))
        self.assertCode('[HEADER]')

    def test_stage_matches_file(self):
        self.mut(VP, lambda d: d.update(stage='8-bis'))
        self.assertCode('[REB-STAGE]')
        self.fresh()
        self.mut(VP, lambda d: d.update(stage='8'), 'rebound_after.json')
        self.assertCode('[REB-STAGE]')

    def test_stage_enum(self):
        self.mut(VP, lambda d: d.update(stage='9'))
        self.assertCode('[SCHEMA]')

    def test_parent_idea_is_the_intake_idea(self):
        self.mut(VP, lambda d: d.update(parent_idea='Another idea altogether about something else.'))
        self.assertCode('[REB-STAGE]')


class BudgetTest(RB):
    def test_every_vp_run_has_its_step(self):
        def go(d):
            d['steps'] = [s for s in d['steps'] if s.get('vp_run') != 'rb_n3']
        mutate(self.work(VP), 'run.json', go)
        self.assertCode('[BUDGET]')

    def test_step_count_cap(self):
        def go(d):
            d['steps'] += [{'step': 'rebound_vp_run', 'utc': '2026-11-14T16:00:00Z', 'duration_s': 1, 'cost_usd': 0,
                            'vp_run': 'rb_n1'} for _ in range(12)]
        mutate(self.work(VP), 'run.json', go)
        self.assertCode('[BUDGET]')

    def test_run_json_accepts_the_new_steps(self):
        errs = self.check.schema_lite.validate(read_json(self.work(VP) / 'run.json'),
                                               read_json(self.check.SCHEMAS / 'run.json'))
        self.assertEqual(errs, [])

    def test_existing_vp_budget_untouched(self):
        steps = read_json(self.work(VP) / 'run.json')['steps']
        self.assertEqual(sum(1 for s in steps if s['step'] == 'vp_run'), 1)
        self.assertEqual(self.probs(), [])


class TreeInCheckTest(RB):
    def test_tree_integrity(self):
        mutate(self.fx, 'IDEA-TREE.json', lambda d: d['nodes'][2].update(parent='I99'))
        self.assertCode('[REB-TREE]')

    def test_tree_cycle(self):
        mutate(self.fx, 'IDEA-TREE.json', lambda d: (d['nodes'][0].update(parent='I2')))
        self.assertCode('[REB-TREE]')

    def test_tree_schema(self):
        mutate(self.fx, 'IDEA-TREE.json', lambda d: d['nodes'][1].update(status='great'))
        self.assertAnyCode(['[REB-TREE]', '[SCHEMA]'])

    def test_absent_tree_is_a_warning(self):
        (self.fx / 'IDEA-TREE.json').unlink()
        probs, warns = self.check.run_all(self.work(VP))
        self.assertEqual(probs, [])
        self.assertTrue(any('[REB-TREE]' in w for w in warns), warns)

    def test_directory_not_in_the_tree_is_a_warning(self):
        probs, warns = self.check.run_all(self.work(NOVP))
        self.assertEqual(probs, [])
        self.assertTrue(any('[REB-TREE]' in w for w in warns), warns)

    def test_registered_directory_gives_no_warning(self):
        probs, warns = self.check.run_all(self.work(VP))
        self.assertFalse(any('[REB-TREE]' in w for w in warns), warns)
