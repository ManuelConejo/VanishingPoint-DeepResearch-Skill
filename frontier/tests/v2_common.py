# SPDX-License-Identifier: Apache-2.0
"""Shared helpers of the Frontier v2 tests (regression specification): a v2 baseline built from the R3 baseline (valid_vp), with the
framing approved by tools/framing.py, a research plan whose calls were made by tools/research.py through a fake gateway,
facets and operators, named elements, belief shifts and value-of-information levels.  No network, no model."""
import json
from pathlib import Path

from .r3_common import R3, VP, load_tool, mutate, read_json, run_tool, write_json  # noqa: F401

CANNED_SEARCH = {
    'search-openalex|*': {'index_total': 2, 'results': [
        {'id': 'doi:10.1000/titles.2019', 'title': 'Title length and citation counts across fields', 'year': 2019},
        {'id': 'arxiv:2101.00001', 'title': 'Search-engine retrieval of scholarly records by title terms', 'year': 2021}]}}

FIELDS_1 = [
    {'field': 'scientometrics', 'why': 'the citation side of the idea lives in this field',
     'keywords': ['title length', 'citation counts']},
    {'field': 'information retrieval', 'why': 'the retrieval side of the idea lives in this field',
     'keywords': ['retrieval ranking', 'title matching']}]
FIELDS_2 = FIELDS_1 + [
    {'field': 'science of science', 'why': 'visibility of papers is studied there under other names',
     'keywords': ['visibility', 'discoverability']}]

PASSAGE = {'ref': {'id': 'doi:10.1000/titles.2019', 'run': 'prior_art', 'claim': 'A1'},
           'fragment': 'shorter titles received more citations'}


def plan_json():
    return {
        'version': 1,
        'iterations': [
            {'n': 1, 'planned_utc': '2026-11-14T09:05:00Z', 'fields': FIELDS_1, 'calls': [],
             'found': [{'id': 'doi:10.1000/titles.2019', 'field': 'scientometrics'}],
             'revision': {'learned': 'The citation side is documented; the retrieval side is documented apart, never joined.',
                          'changes': ['added the field science of science with visibility keywords']}},
            {'n': 2, 'planned_utc': '2026-11-14T09:10:00Z', 'fields': FIELDS_2, 'calls': [],
             'found': [{'id': 'arxiv:2101.00001', 'field': 'information retrieval'}],
             'stop_reason': 'The third field returned nothing that joins the two sides; a third round would add no field.'}],
        'outcome': {'status': 'Partially', 'passage': PASSAGE,
                    'difference': 'Observational association only: no retrieval mechanism and no intervention on titles.',
                    'summary': 'The association is published; the retrieval mechanism as the cause is not.'}}


class V2(R3):
    """R3 with a v2 baseline: to_v2() returns a working directory that passes (apart from the card checks)."""

    def setUp(self):
        super().setUp()
        self.v2 = load_tool('v2check')

    def framing(self, w, how='approve'):
        r = run_tool('framing', 'propose', w, '--objective', 'Measure the retrieval effect of shortening a preprint title',
                     '--success', 'Use paired index queries to distinguish title matching from venue reputation with adequate power',
                     '--constraint', 'Use an offline index containing public citation metadata',
                     '--refuted-by', 'Paired title variants return identical ranks on the frozen index',
                     '--no-free-draft', 'fixture without a free draft')
        assert r.returncode == 0, r.stdout + r.stderr
        if how == 'approve':
            r = run_tool('framing', 'approve', w, '--reply', 'Yes, go ahead with that framing.')
        elif how == 'assume':
            r = run_tool('framing', 'assume', w)
        else:
            r = run_tool('framing', 'correct', w, '--reply', 'The success criterion should name the sample size.',
                         '--success', 'A paired retrieval test on 200 records separates retrieval from journal prestige')
        assert r.returncode == 0, r.stdout + r.stderr

    def research(self, w, vp=None, queries=None):
        write_json(w / 'research_plan.json', plan_json())
        vp = vp or self.vp_fake(CANNED_SEARCH)
        qs = queries or [(1, 'scientometrics', 'title length citation counts'),
                         (1, 'information retrieval', 'title retrieval ranking'),
                         (2, 'science of science', 'title visibility discoverability')]
        for it, field, q in qs:
            r = run_tool('research', 'search', w, '--iteration', it, '--field', field, '--query', q, '--vp', vp)
            assert r.returncode == 0, r.stdout + r.stderr
        r = run_tool('research', 'coverage', w)
        assert r.returncode == 0, r.stdout + r.stderr
        return vp

    def to_v2(self, name=VP):
        if read_json(self.work(name) / 'intake.json').get('frontier_version') == 4:
            return self.work(name)                      # idempotent: a test may call it again after fresh()
        w = self.to_r3(name)

        def intake(d):
            d['frontier_version'] = 4
        mutate(w, 'intake.json', intake)
        self.framing(w)

        def reco(d):
            d['next_step'] = d.pop('tomorrow')
        mutate(w, 'recommendation.json', reco)

        def hyp(d):
            d['facets'] = {'goal': 'Determine whether an author can improve preprint visibility by editing its title',
                           'mechanism': 'Search queries retrieve records with shortened titles at higher ranks'}
            d['rivals'][0]['operator'] = 'rival_theories'
            d['rivals'][0]['facet'] = 'mechanism'
            d['repairable_variants'][0]['operator'] = 'facet_recombination'
            d['repairable_variants'][0]['facet'] = 'mechanism'
        mutate(w, 'hypotheses.json', hyp)
        self.research(w)
        r = run_tool('named', 'add', w, '--name', 'OpenAlex works index', '--kind', 'dataset', '--used-in', 'T1',
                     '--host', 'Read the works-table schema in the public index documentation')
        assert r.returncode == 0, r.stdout + r.stderr

        def tests(d):
            order = d['ranking']['order']
            for t in d['tests']:
                a, b = t['competing_hypotheses']
                t['belief_shift'] = {
                    'exclusive': True,
                    'before': 'Both explanations are open; the closest work cannot separate them.',
                    'outcomes': [
                        {'outcome': 'The result lies in the interval predicted by %s' % a, 'matches': a,
                         'moves': {a: 'up', b: 'down'}, 'then': 'Increase confidence in %s and choose a follow-up experiment.' % a},
                        {'outcome': 'The result lies in the interval predicted by %s' % b, 'matches': b,
                         'moves': {a: 'down', b: 'up'}, 'then': 'Increase confidence in %s and close the %s investigation.' % (b, a)},
                        {'outcome': 'The result lies in the overlap of both intervals', 'matches': 'ambiguous',
                         'moves': {a: 'flat', b: 'flat'}, 'then': 'Collect one additional sample and apply the frozen decision rule.'},
                        {'outcome': 'The result lies outside every predicted interval', 'matches': 'unexpected',
                         'moves': {a: 'down', b: 'flat'}, 'then': 'Reassess the objective before beginning another experiment.'}]}
                t['voi'] = ({'information': 'high', 'cost': 'low', 'why': 'A few hours of offline query comparisons can distinguish the proposed explanations.'}
                            if t['id'] == order[0] else
                            {'information': 'medium', 'cost': 'medium', 'why': 'Citation metadata and additional ratings are needed; the distinction remains less clear.'})
                t['named_elements'] = ['N1'] if t['id'] == 'T1' else []
                if t['id'] != 'T1':
                    t['named_elements_none'] = 'This test names no dataset, model or metric beyond the public citation counts.'
        mutate(w, 'tests.json', tests)

        def run(d):
            d['steps'].insert(1, {'step': 'framing', 'utc': '2026-11-14T08:56:00Z', 'duration_s': 'unknown', 'cost_usd': 'unknown'})
            d['steps'].insert(3, {'step': 'research_plan', 'utc': '2026-11-14T09:30:00Z', 'duration_s': 'unknown', 'cost_usd': 'unknown'})
        mutate(w, 'run.json', run)
        return w

    def v2_probs(self, name=VP):
        return [p for p in self.probs(name) if not p.startswith('[CARD')]

    def assertV2Clean(self, name=VP):
        self.assertEqual(self.v2_probs(name), [])

    def warns(self, name=VP):
        return self.check.warnings(self.work(name))

    def assertBlocks(self, code, name=VP):
        p = self.v2_probs(name)
        self.assertTrue(any(x.startswith(code) for x in p), '%s not in %r' % (code, p))

    def assertMarks(self, code, name=VP):
        self.assertEqual([x for x in self.v2_probs(name) if x.startswith(code)], [])
        w = self.warns(name)
        self.assertTrue(any(code in x for x in w), '%s not in warnings %r' % (code, w))
