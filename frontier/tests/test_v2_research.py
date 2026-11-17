# SPDX-License-Identifier: Apache-2.0
"""V2-6 .. V2-12 of regression specification: prior art by an iterative research plan (Nova), four outcomes backed by a passage, coverage."""
import copy
import json
from pathlib import Path

from .v2_common import CANNED_SEARCH, FIELDS_1, V2, VP, mutate, plan_json, read_json, run_tool, write_json


def edit_plan(case, fn, name=VP):
    mutate(case.work(name), 'research_plan.json', fn)


class PlanShapeTest(V2):
    def setUp(self):
        super().setUp()
        self.to_v2()

    def test_baseline_plan_is_clean(self):
        self.assertV2Clean()

    def test_plan_file_is_required(self):
        (self.work() / 'research_plan.json').unlink()
        self.assertBlocks('[PLAN-MISSING]')

    def test_one_iteration_only_with_insufficient_search(self):
        def one(d):
            d['iterations'] = d['iterations'][:1]
            d['iterations'][0].pop('revision')
            d['iterations'][0]['stop_reason'] = 'Only one round was possible in this session, so the search is insufficient.'
        edit_plan(self, one)
        self.assertBlocks('[PLAN-ITER]')
        edit_plan(self, lambda d: d['outcome'].clear() or d['outcome'].update(
            status='Insufficient search', summary='One round only: nothing can be concluded from a single plan.'))
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[PLAN-ITER]')], [])

    def test_more_than_three_iterations_is_refused(self):
        def four(d):
            it = copy.deepcopy(d['iterations'][1])
            it['n'] = 3
            it['revision'] = {'learned': 'Nothing new came back from the third round of the plan.', 'changes': ['dropped a keyword']}
            it.pop('stop_reason')
            it['fields'] = copy.deepcopy(d['iterations'][1]['fields'])
            it['fields'][2]['keywords'] = ['visibility', 'findability']
            d['iterations'].append(it)
            it4 = copy.deepcopy(it)
            it4['n'] = 4
            it4['fields'][2]['keywords'] = ['visibility', 'accessibility']
            it4['stop_reason'] = 'Stopped after the fourth round.'
            it4.pop('revision')
            d['iterations'].append(it4)
        edit_plan(self, four)
        self.assertBlocks('[PLAN-ITER]')

    def test_first_iteration_needs_two_fields_with_two_keywords_and_a_reason(self):
        for label, fn in (('one field', lambda d: d['iterations'][0].update(fields=d['iterations'][0]['fields'][:1])),
                          ('one keyword', lambda d: d['iterations'][0]['fields'][0].update(keywords=['title length'])),
                          ('no why', lambda d: d['iterations'][0]['fields'][0].update(why='n/a'))):
            with self.subTest(label):
                self.fresh()
                self.to_v2()
                edit_plan(self, fn)
                self.assertBlocks('[PLAN-ITER]')

    def test_identical_plan_is_not_an_iteration(self):
        def same(d):
            d['iterations'][1]['fields'] = copy.deepcopy(d['iterations'][0]['fields'])
        edit_plan(self, same)
        self.assertBlocks('[PLAN-REVISION]')

    def test_revision_must_say_what_was_learned_and_what_changed(self):
        edit_plan(self, lambda d: d['iterations'][0]['revision'].update(learned='ok'))
        self.assertBlocks('[PLAN-REVISION]')
        self.fresh()
        self.to_v2()
        edit_plan(self, lambda d: d['iterations'][0]['revision'].update(changes=[]))
        self.assertBlocks('[PLAN-REVISION]')

    def test_last_iteration_states_why_it_stops(self):
        edit_plan(self, lambda d: d['iterations'][1].pop('stop_reason'))
        self.assertBlocks('[PLAN-REVISION]')


class PlanCallsTest(V2):
    def test_search_goes_through_the_gateway_and_is_recorded(self):
        w = self.to_v2()
        plan = read_json(w / 'research_plan.json')
        calls = plan['iterations'][0]['calls']
        self.assertEqual(len(calls), 2)
        for c in calls:
            self.assertTrue((w / c['envelope']).is_file())
            self.assertEqual(c['ids'], ['doi:10.1000/titles.2019', 'arxiv:2101.00001'])
            self.assertRegex(c['envelope_sha256'], '^[0-9a-f]{64}$')
        journal = [json.loads(l) for l in (w / 'research' / 'state' / 'journal.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(journal), 3)
        self.assertEqual({e['T'] for e in journal}, {'2026-11-14'})

    def test_a_query_without_a_keyword_of_its_field_is_refused_before_sending(self):
        w = self.to_v2()
        vp = self.tmp / 'fakevp'
        n = len((vp / 'tools' / 'calls.jsonl').read_text(encoding='utf-8').splitlines())
        r = run_tool('research', 'search', w, '--iteration', 1, '--field', 'scientometrics', '--query', 'retrieval ranking engines', '--vp', vp)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len((vp / 'tools' / 'calls.jsonl').read_text(encoding='utf-8').splitlines()), n)

    def test_a_field_not_in_the_plan_is_refused(self):
        w = self.to_v2()
        r = run_tool('research', 'search', w, '--iteration', 1, '--field', 'philosophy of science', '--query', 'title length', '--vp', self.tmp / 'fakevp')
        self.assertEqual(r.returncode, 1)

    def test_archive_words_are_refused_before_sending_even_as_plan_keywords(self):
        w = self.to_v2()
        proj = self.project()
        (proj / 'LESSONS.md').write_text('# Lessons\nThe zeppelin ledger approach was REJECTED. DO NOT REOPEN.\n', encoding='utf-8')
        mutate(w, 'intake.json', lambda d: d.update(project_dirs=[str(proj)]))

        def add(d):
            d['iterations'][1]['fields'][2]['keywords'] = ['visibility', 'zeppelin']
        edit_plan(self, add)
        vp = self.tmp / 'fakevp'
        n = len((vp / 'tools' / 'calls.jsonl').read_text(encoding='utf-8').splitlines())
        r = run_tool('research', 'search', w, '--iteration', 2, '--field', 'science of science', '--query', 'zeppelin visibility', '--vp', vp)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len((vp / 'tools' / 'calls.jsonl').read_text(encoding='utf-8').splitlines()), n, 'nothing was sent')
        self.assertBlocks('[PLAN-LEAK]')

    def test_keywords_of_other_fields_are_allowed(self):
        w = self.to_v2()
        guards = self.guards
        self.assertEqual(guards.check_outgoing(w, 'visibility discoverability'), [])

    def test_a_call_missing_from_the_gateway_journal_blocks(self):
        w = self.to_v2()
        p = w / 'research' / 'state' / 'journal.jsonl'
        lines = p.read_text(encoding='utf-8').splitlines()
        p.write_text('\n'.join(lines[1:]) + '\n', encoding='utf-8')
        self.assertBlocks('[PLAN-JOURNAL]')

    def test_an_altered_envelope_blocks(self):
        w = self.to_v2()
        env = read_json(w / read_json(w / 'research_plan.json')['iterations'][0]['calls'][0]['envelope'])
        env['gateway']['results'].append({'id': 'doi:10.9999/invented', 'title': 'x', 'year': 2020})
        write_json(w / read_json(w / 'research_plan.json')['iterations'][0]['calls'][0]['envelope'], env)
        self.assertBlocks('[PLAN-ENVELOPE]')

    def test_an_envelope_changed_without_changing_the_ids_blocks_by_its_hash(self):
        w = self.to_v2()
        rel = read_json(w / 'research_plan.json')['iterations'][0]['calls'][0]['envelope']
        env = read_json(w / rel)
        env['gateway']['results'][0]['title'] = 'A title that the gateway never returned'
        write_json(w / rel, env)
        self.assertBlocks('[PLAN-ENVELOPE]')

    def test_a_work_nobody_found_blocks(self):
        w = self.to_v2()
        edit_plan(self, lambda d: d['iterations'][0]['found'].append({'id': 'doi:10.9999/invented', 'field': 'scientometrics'}))
        self.assertBlocks('[PLAN-FOUND]')

    def test_a_query_that_does_not_use_the_keywords_blocks(self):
        w = self.to_v2()
        edit_plan(self, lambda d: d['iterations'][0]['calls'][0].update(query='something else entirely'))
        self.assertTrue(any(p.startswith('[PLAN-JOURNAL]') or p.startswith('[PLAN-ITER]') for p in self.v2_probs()))

    def test_plan_keywords_are_in_the_guard_vocabulary(self):
        w = self.to_v2()
        self.assertIn('discoverability', self.guards.own_vocabulary(w))


class NoVpPlanTest(V2):
    """Without VP nothing is verified: the plan is accepted, the passage is MARKED as not verified, no coverage is demanded."""

    def run_plan(self, mutate_plan=None):
        w = self.tmp / 'novp'
        w.mkdir(exist_ok=True)
        plan = plan_json()
        if mutate_plan:
            mutate_plan(plan)
        write_json(w / 'research_plan.json', plan)
        write_json(w / 'intake.json', {'idea': 'Preprints with shorter titles collect more citations because search engines retrieve them',
                                       'domain': 'scientometrics', 'T': '2026-11-14', 'vp': {'mode': 'none', 'dir': None, 'runs': {}}})
        data = {'intake.json': read_json(w / 'intake.json'), 'prior_art.json': {'answer': 'Partially'}}
        P, W = [], []
        self.v2.check_plan(w, data, P, W, self.check)
        return P, W

    def test_a_plan_without_calls_is_accepted_and_the_passage_is_marked(self):
        P, W = self.run_plan()
        self.assertEqual(P, [])
        self.assertTrue(any('[PLAN-PASSAGE]' in x and 'not verified: no VP' in x for x in W), W)

    def test_the_other_rules_still_hold_without_vp(self):
        P, W = self.run_plan(lambda p: p['iterations'][1].update(fields=p['iterations'][0]['fields']))
        self.assertTrue(any(x.startswith('[PLAN-REVISION]') for x in P), P)
        P, W = self.run_plan(lambda p: p['outcome'].update(status='Novel'))
        self.assertTrue(any(x.startswith('[PLAN-OUTCOME]') for x in P), P)


class OutcomeTest(V2):
    def setUp(self):
        super().setUp()
        self.to_v2()

    def test_four_statuses_only(self):
        edit_plan(self, lambda d: d['outcome'].update(status='Novel'))
        self.assertBlocks('[PLAN-OUTCOME]')

    def test_partially_needs_a_passage_found_in_the_vp_verdict(self):
        edit_plan(self, lambda d: d['outcome']['passage'].update(fragment='shorter titles are always cited far more'))
        self.assertBlocks('[PLAN-PASSAGE]')

    def test_passage_reference_must_not_be_absent_or_invalid(self):
        def go(d):
            d['outcome']['passage'] = {'ref': {'id': 'doi:10.1000/ghost.2021', 'run': 'prior_art', 'claim': 'A4'},
                                       'fragment': 'the abstract makes no causal claim'}
        edit_plan(self, go)
        self.assertBlocks('[PLAN-PASSAGE]')

    def test_partially_needs_the_exact_difference(self):
        edit_plan(self, lambda d: d['outcome'].pop('difference'))
        self.assertBlocks('[PLAN-OUTCOME]')

    def test_exists_needs_a_passage_too(self):
        def go(d):
            d['outcome']['status'] = 'Exists'
            d['outcome'].pop('passage')
        edit_plan(self, go)
        mutate(self.work(), 'prior_art.json', lambda d: d.update(answer='Exists'))
        self.assertBlocks('[PLAN-PASSAGE]')

    def test_status_must_match_the_vp_answer_and_never_be_raised(self):
        edit_plan(self, lambda d: d['outcome'].update(status='Not found'))
        self.assertBlocks('[PLAN-OUTCOME]')
        self.fresh()
        self.to_v2()
        mutate(self.work(), 'prior_art.json', lambda d: d.update(answer='Not found'))
        edit_plan(self, lambda d: d['outcome'].update(status='Exists'))
        self.assertBlocks('[PLAN-OUTCOME]')

    def test_not_found_may_be_lowered_to_insufficient_search(self):
        mutate(self.work(), 'prior_art.json', lambda d: d.update(answer='Not found'))

        def go(d):
            d['outcome'] = {'status': 'Insufficient search', 'summary': 'Two sources failed, so nothing can be concluded.'}
        edit_plan(self, go)
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[PLAN-')], [])

    def test_partially_cannot_be_lowered_to_insufficient_search(self):
        edit_plan(self, lambda d: d['outcome'].clear() or d['outcome'].update(status='Insufficient search', summary='Not enough coverage to say.'))
        self.assertBlocks('[PLAN-OUTCOME]')

    def test_no_novelty_score_anywhere_in_the_plan(self):
        edit_plan(self, lambda d: d['outcome'].update(novelty_score=8))
        self.assertTrue(any('novelty' in p.lower() for p in self.v2_probs()))

    def test_outcome_text_never_claims_novelty_from_not_found(self):
        mutate(self.work(), 'prior_art.json', lambda d: d.update(answer='Not found'))
        edit_plan(self, lambda d: d['outcome'].clear() or d['outcome'].update(
            status='Not found', summary='Nothing found, so the idea is new and unprecedented.'))
        self.assertTrue(any(p.startswith('[PLAN-OUTCOME]') for p in self.v2_probs()))

    def test_scope_split_is_two_separate_answers(self):
        edit_plan(self, lambda d: d.update(scope_split={'whole_field': 'Partially', 'cited_by_idea': 'Not found'}))
        self.assertV2Clean()
        edit_plan(self, lambda d: d.update(scope_split={'whole_field': 'Maybe', 'cited_by_idea': 'Not found'}))
        self.assertTrue(any('[PLAN-' in p for p in self.v2_probs()) or any('[PLAN-' in w for w in self.warns()))


class CoverageTest(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def test_coverage_is_computed_from_the_journal_with_recall_unknown(self):
        cov = read_json(self.w / 'research_plan.json')['coverage']
        self.assertEqual(cov['calls'], 3)
        self.assertEqual(cov['recall'], 'unknown')
        self.assertEqual([i['calls'] for i in cov['iterations']], [2, 1])

    def test_typed_or_stale_coverage_blocks(self):
        edit_plan(self, lambda d: d['coverage'].update(calls=99))
        self.assertBlocks('[PLAN-COVER]')
        self.fresh()
        self.to_v2()
        edit_plan(self, lambda d: d.pop('coverage'))
        self.assertBlocks('[PLAN-COVER]')

    def test_recall_claim_blocks(self):
        edit_plan(self, lambda d: d['outcome'].update(summary='High recall: the search found everything that exists.'))
        self.assertTrue(any(p.startswith(('[RECALL-CLAIM]', '[PLAN-COVER]', '[PLAN-OUTCOME]')) for p in self.v2_probs()))

    def test_caps_and_unavailable_sources_make_not_found_weak(self):
        vp = self.vp_fake({'search-openalex|*': {'index_total': 20, 'results': [{'id': 'doi:10.1/a%d' % i, 'title': 't', 'year': 2020} for i in range(20)]}})
        # the fake gateway journals n = 20: twenty results reach the cap
        r = run_tool('research', 'search', self.w, '--iteration', 2, '--field', 'science of science', '--query', 'visibility discoverability',
                     '--vp', vp, '--n', 20)
        self.assertEqual(r.returncode, 0, r.stderr)
        run_tool('research', 'coverage', self.w)
        cov = read_json(self.w / 'research_plan.json')['coverage']
        self.assertGreaterEqual(cov['caps_reached'], 1)
        status = run_tool('research', 'status', self.w)
        self.assertIn('weak', status.stdout)
        self.assertIn('recall unknown', status.stdout)
