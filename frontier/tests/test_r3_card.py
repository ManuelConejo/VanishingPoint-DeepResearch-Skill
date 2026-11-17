# SPDX-License-Identifier: Apache-2.0
"""R3-4 .. R3-6, R3-13 .. R3-16, R3-18 (regression specification): complete card, Tomorrow, scenarios not results, decisive evidence,
coverage, hybrid draft, and the regressions taken from three invented packing-card detector cases."""
import json
import re

from .am1_common import AM, NOVP, REBOUND, VP, load_tool, mutate, read_json, run_tool, write_json
from .r3_common import LONG600, R3, regression_text, fr

TRUNC = re.compile(r'…|\.\.\.|\(\+\d+ more')


def card_text(case, name=VP):
    r = case.card(name)
    case.assertEqual(r.returncode, 0, r.stdout + r.stderr)
    return (case.work(name) / 'IDEA-CARD.md').read_text(encoding='utf-8')


class CompleteCardTest(R3):
    def setUp(self):
        super().setUp()
        self.w = self.to_r3()

    def test_r3_card_has_no_truncation_mark(self):
        t = card_text(self)
        self.assertEqual(TRUNC.findall(t), [])
        self.assertLessEqual(len(t.splitlines()), 80)

    def test_every_decision_field_is_whole_on_the_card(self):
        # property over every field that decides, with a 600-character value in each
        fields = [('tests.json', lambda d, v: d['tests'][0]['decision_rule'].update(continue_if=v)),
                  ('tests.json', lambda d, v: d['tests'][0]['decision_rule'].update(revise_if=v)),
                  ('tests.json', lambda d, v: d['tests'][0]['decision_rule'].update(stop_if=v)),
                  ('tests.json', lambda d, v: d['tests'][0]['decision_rule'].update(indeterminate_if=v)),
                  ('tests.json', lambda d, v: d['ranking']['scenarios'][0].update(**{'if': v})),
                  ('tests.json', lambda d, v: d['ranking']['scenarios'][0].update(then=v)),
                  ('tests.json', lambda d, v: d['tests'][0]['verdict_scope'].update(concludes_about=v)),
                  ('tests.json', lambda d, v: d['tests'][0]['feasibility'].update(data=v)),
                  ('tests.json', lambda d, v: d['tests'][0]['feasibility'].update(human_time=v)),
                  ('recommendation.json', lambda d, v: d.update(reason=v + '.')),
                  ('recommendation.json', lambda d, v: d['tomorrow'].update(first_action=v))]
        for i, (fname, fn) in enumerate(fields):
            self.fresh()
            self.w = self.to_r3()
            # six sentences of about 90 characters: a clipping card would keep the first one and point to the report; only
            # the reason is a single (long) sentence, as check.py demands
            if fname == 'recommendation.json' and i == 9:
                v = LONG600.replace('word', 'fld%d_' % i)
            else:
                v = ' '.join('Sentence %d of field %d %s.' % (k, i, ' '.join('w%d_%d' % (k, j) for j in range(12))) for k in range(6))
            mutate(self.w, fname, lambda d: fn(d, v))
            if fname == 'tests.json':                       # the rule is part of the frozen protocol of the executed test:
                (self.w / 'result.json').unlink()            # drop the execution and its "after" so that the card can be made
                lines = (self.w / 'decision_log.jsonl').read_text(encoding='utf-8').splitlines()
                (self.w / 'decision_log.jsonl').write_text(lines[0] + '\n', encoding='utf-8')
            r = self.card()
            self.assertEqual(r.returncode, 0, (i, r.stdout, r.stderr))
            t = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
            # (a field joined by ';' inside one line loses only its final period, as before)
            self.assertTrue(v.rstrip('.') in t, 'field %d not whole on the card' % i)
            self.assertEqual(TRUNC.findall(t), [], i)
            self.assertLessEqual(len(t.splitlines()), 80, i)

    def test_a_long_non_decision_field_is_replaced_by_whole_sentences(self):
        long = 'First complete sentence of the hypothesis. Then ' + LONG600 + ' trailing words without an end'
        mutate(self.w, 'hypotheses.json', lambda d: d['hypotheses'][0].update(statement=long))
        t = card_text(self)
        self.assertIn('First complete sentence of the hypothesis.', t)
        self.assertEqual(TRUNC.findall(t), [])
        self.assertNotIn('word010', t)
        rep = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertIn(long, rep)

    def test_report_is_complete_and_checked(self):
        card_text(self)
        rep = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertEqual(TRUNC.findall(rep.replace('(unverified)', '')), [])
        self.assertNoCode('[REPORT-STALE]')

    def test_the_card_never_cuts_the_critique_list(self):
        t = card_text(self)
        self.assertNotRegex(t, r'\(\+\d+ (more|earlier)')
        cr = read_json(self.w / 'critique.json')
        for it in cr['items']:
            self.assertIn(it['text'], t)

    def test_card_truncation_detector_and_the_three_synthetic_cards(self):
        for n in (1, 2, 3):
            text = regression_text(n)
            self.assertTrue(self.r3.card_truncation(text), 'synthetic card %d has truncation marks' % n)
        self.assertEqual(self.r3.card_truncation(card_text(self)), [])

    def test_no_list_is_cut_scenarios_closest_works_critique_items(self):
        def tests(d):
            for k in range(3, 8):
                d['ranking']['scenarios'].append({'name': 's%d' % k, 'if': 'condition number %d holds in the sample' % k,
                                                  'then': 'take action number %d next' % k, 'why': 'reason number %d is written' % k})
        mutate(self.w, 'tests.json', tests)
        def pa(d):
            for k in range(5):
                d['closest_work'].append(dict(d['closest_work'][1], title='Extra close work number %d' % k))
        mutate(self.w, 'prior_art.json', pa)
        def cr(d):
            for k in range(4):
                d['items'].append({'test': 'T1', 'category': 'other', 'severity': 'minor', 'text': d['items'][0]['text'],
                                   'response': {'action': 'rejected', 'note': 'extra item %d kept as is' % k}})
        mutate(self.w, 'critique.json', cr)
        t = card_text(self)
        self.assertEqual(TRUNC.findall(t), [])
        for k in range(3, 8):
            self.assertIn('take action number %d next' % k, t)
        for k in range(5):
            self.assertIn('Extra close work number %d' % k, t)
        self.assertEqual(len([l for l in t.splitlines() if re.match(r'- \[(major|blocking|minor)\] ', l)]), 6)
        self.assertNotRegex(t, r'\(\+\d+')

    def test_check_refuses_a_card_with_truncation_marks_in_r3(self):
        card_text(self)
        p = self.w / 'IDEA-CARD.md'
        p.write_text(p.read_text(encoding='utf-8').replace('## Idea', '## Idea (+4 more in x.json)'), encoding='utf-8')
        self.assertCode('[CARD-TRUNC]')

    def test_legacy_card_keeps_its_own_rendering(self):
        # legacy directories keep the rendering of the golden cards (tests/test_rebound_card.py): no Tomorrow block there
        t = card_text(self, NOVP)
        self.assertNotIn('## Tomorrow', t)


class TomorrowTest(R3):
    def setUp(self):
        super().setUp()
        self.w = self.to_r3()

    def block(self):
        t = card_text(self)
        lines = t.splitlines()
        i = lines.index('## Tomorrow')
        return lines, i

    def test_five_lines_right_after_the_recommendation(self):
        lines, i = self.block()
        self.assertTrue(lines[i - 2].startswith('**Recommendation:'), lines[i - 3:i + 1])
        blk = []
        for l in lines[i:]:
            if not l.strip():
                break
            blk.append(l)
        self.assertEqual(len(blk), 5, blk)
        for pref, l in zip(('## Tomorrow', 'First step:', 'Inputs:', 'Cost:', 'Stop rule:'), blk):
            self.assertTrue(l.startswith(pref), (pref, l))

    def test_the_block_is_derived_from_the_first_test_not_typed(self):
        lines, i = self.block()
        tj = read_json(self.w / 'tests.json')
        t = tj['tests'][0]
        self.assertIn(t['feasibility']['data'], lines[i + 2])
        self.assertIn(t['feasibility']['human_time'], lines[i + 3])
        self.assertIn(t['feasibility']['compute'], lines[i + 3])
        self.assertIn(t['decision_rule']['stop_if'], lines[i + 4])
        self.assertIn(read_json(self.w / 'recommendation.json')['tomorrow']['first_action'], lines[i + 1])

    def test_tomorrow_test_is_the_first_of_the_ranking(self):
        mutate(self.w, 'recommendation.json', lambda d: d['tomorrow'].update(test='T2'))
        self.assertCode('[TOMORROW]')

    def test_tomorrow_is_mandatory_in_r3(self):
        mutate(self.w, 'recommendation.json', lambda d: d.pop('tomorrow'))
        self.assertCode('[TOMORROW]')
        mutate(self.w, 'recommendation.json', lambda d: d.update(tomorrow={'test': 'T1', 'first_action': 'todo'}))
        self.assertCode('[TOMORROW]')

    def test_legacy_directories_do_not_need_it(self):
        self.assertNoCode('[TOMORROW]', NOVP)


class ScenarioNotResultTest(R3):
    def test_after_by_assumption_is_refused_in_r3(self):
        w = self.to_r3(REBOUND)
        r = run_tool('log', w, 'after', '--test', 'T2', '--text', 'After reading the card I would run T2 first.', '--assumption')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('scenario', r.stderr)

    def test_an_assumed_after_is_refused_even_with_an_observation_or_an_executed_result(self):
        w = self.to_r3()
        r = run_tool('log', w, 'after', '--test', 'T1', '--text', 'I would schedule T2.', '--assumption')       # T1 is executed
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        run_tool('log', w, 'before', '--test', 'T2', '--text', 'If ratio >= 1.1 I write the paper.')
        r = run_tool('log', w, 'after', '--test', 'T2', '--text', 'I would run T2.', '--assumption',
                     '--observed', 'The user ran T2 on their own data: ratio 1.02, CI [0.97, 1.07].')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(len([l for l in (w / 'decision_log.jsonl').read_text().splitlines() if '"after"' in l]), 1)

    def test_after_without_result_needs_the_observation(self):
        w = self.to_r3()
        run_tool('log', w, 'before', '--test', 'T2', '--text', 'If T2 shows a ratio of at least 1.1 I write the paper.')
        r = run_tool('log', w, 'after', '--test', 'T2', '--text', 'I would run T2 first, I think.')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        r = run_tool('log', w, 'after', '--test', 'T2', '--text', 'Ratio 1.02 seen by the user.',
                     '--observed', 'The user ran T2 on their own data: ratio 1.02, CI [0.97, 1.07].')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_after_with_executed_result_is_allowed(self):
        w = self.to_r3()
        r = run_tool('log', w, 'after', '--test', 'T1', '--text', 'Gain seen; I schedule T2 next week.')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_flags_an_assumed_after(self):
        w = self.to_r3()
        with open(w / 'decision_log.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps({'utc': '2026-11-14T13:00:00Z', 'phase': 'before', 'test': 'T2', 'text': 'If ratio >= 1.1 go on.', 'by': 'researcher'}) + '\n')
            f.write(json.dumps({'utc': '2026-11-14T13:01:00Z', 'phase': 'after', 'test': 'T2', 'text': 'Assumed: I would run T2.', 'by': 'assumption'}) + '\n')
        self.assertCode('[LOG-AFTER]')

    def test_legacy_log_rule_is_unchanged(self):
        w = self.work(NOVP)
        r = run_tool('log', w, 'after', '--test', 'T1', '--text', 'Assumed.', '--assumption')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_rebound_after_from_an_assumption_is_refused_and_a_scenario_is_labelled(self):
        w = self.to_r3(REBOUND)
        d = read_json(w / 'rebound_after.json')
        mutate(w, 'rebound_after.json', lambda x: x.update(outcome_source='assumption'))
        p = self.probs(REBOUND)
        self.assertTrue(self.code_in('[REB-AFTER-ASSUMED]', p), p)
        mutate(w, 'rebound_after.json', lambda x: x.update(outcome_source='scenario'))
        p = self.probs(REBOUND)
        self.assertFalse(self.code_in('[REB-AFTER', p), p)
        t = card_text(self, REBOUND)
        self.assertIn('Scenarios, no result yet', t)
        self.assertNotIn('## Rebound after', t)
        self.assertNotIn('no result yet): next ideas conditioned on the outcome', t)

    def test_synthetic_card_3_after_entries_would_be_refused(self):
        # Synthetic card 3 declares three assumed outcomes despite having no observations.
        text = regression_text(3)
        afters = re.findall(r'- After \((T\d), assumption,', text)
        self.assertGreaterEqual(len(afters), 3)
        w = self.to_r3()
        run_tool('log', w, 'before', '--test', 'T2', '--text', 'Before: run T2 only if T1 continues.')
        for tid in afters:
            r = run_tool('log', w, 'after', '--test', 'T2', '--text', 'After reviewing the packing plan, no inspection has occurred.', '--assumption')
            self.assertEqual(r.returncode, 1)


class DecisiveClaimsTest(R3):
    def setUp(self):
        super().setUp()
        self.w = self.to_r3()

    def claims(self, fn):
        mutate(self.w, 'decisive_claims.json', lambda d: fn(d['claims'][0]))

    def test_baseline(self):
        self.assertNoCode('[DECISIVE')

    def test_file_is_mandatory_with_vp(self):
        (self.w / 'decisive_claims.json').unlink()
        self.assertCode('[DECISIVE]')

    def test_fragment_must_be_the_one_vp_verified(self):
        self.claims(lambda c: c.update(fragment='shorter titles cause citations'))
        self.assertCode('[DECISIVE-FRAGMENT]')

    def test_full_support_needs_every_number_of_the_claim_in_the_fragment(self):
        self.claims(lambda c: c.update(claim='Shorter titles raise citations by 12.5% in 3 fields'))
        self.assertCode('[DECISIVE-OVERCLAIM]')
        self.claims(lambda c: c.update(supports='partial'))
        self.assertNoCode('[DECISIVE-OVERCLAIM]')

    def test_found_is_not_enough_partial_is_shown_as_partial(self):
        self.claims(lambda c: c.update(claim='Shorter titles raise citations by 12.5%', supports='partial'))
        t = card_text(self)
        self.assertIn('partial', t.split('Decisive evidence')[1].split('\n')[0])

    def test_scope_limits_link_are_required_and_real(self):
        for key in ('scope', 'limits', 'why_linked'):
            self.fresh()
            self.w = self.to_r3()
            self.claims(lambda c: c.update({key: 'n/a'}))
            self.assertCode('[DECISIVE]')

    def test_a_context_only_claim_cannot_carry_the_verdict(self):
        self.claims(lambda c: c.update(decides='verdict', supports='context_only'))
        self.assertCode('[DECISIVE]')

    def test_a_status_other_than_found_marks_the_claim_not_verified(self):
        self.claims(lambda c: c.update(ref={'id': 'doi:10.1000/prestige.2020', 'run': 'prior_art', 'claim': 'A3'},
                                       fragment='prestige explains a large part'))
        t = card_text(self)
        self.assertIn('DISTORTED', t.split('Decisive evidence')[1].split('\n')[0])

    def test_recommendation_justification_links_results_to_the_conclusion(self):
        mutate(self.w, 'recommendation.json', lambda d: d.pop('justification'))
        self.assertCode('[DECISIVE]')
        mutate(self.w, 'recommendation.json', lambda d: d.update(justification={'from': ['K9'], 'link': 'K9 shows everything we need to know here.'}))
        self.assertCode('[DECISIVE]')


class CoverageTest(R3):
    def setUp(self):
        super().setUp()
        self.w = self.to_r3()

    def test_coverage_is_computed_from_the_vp_journal(self):
        cov = read_json(self.w / 'prior_art.json')['coverage']
        self.assertEqual(cov['calls'], 2)
        self.assertEqual(cov['recall'], 'unknown')
        for k in ('searches', 'caps_reached', 'sources_unavailable'):
            self.assertIn(k, cov)

    def test_typed_coverage_is_refused(self):
        mutate(self.w, 'prior_art.json', lambda d: d['coverage'].update(calls=40))
        self.assertCode('[COVER-STALE]')

    def test_unavailable_sources_and_caps_come_from_the_journal(self):
        jp = self.tmp / 'fx' / 'vp_prior_art' / 'state' / 'journal.jsonl'
        rows = [json.loads(l) for l in jp.read_text().splitlines()]
        rows.append({'utc': '2026-11-14T09:01:00.000000+00:00', 'run': rows[0]['run'], 'T': '2026-11-14', 'call': 'search-openalex',
                     'engine': 'openalex', 'query': 'title length', 'n': 20, 'count': 20, 'excluded': 0, 'error': None, 'ids': []})
        rows.append({'utc': '2026-11-14T09:02:00.000000+00:00', 'run': rows[0]['run'], 'T': '2026-11-14', 'call': 'search-pubmed',
                     'engine': 'pubmed', 'query': 'title length', 'n': 20, 'count': 0, 'excluded': 0, 'error': 'timeout', 'ids': []})
        jp.write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        cov = self.guards.coverage(self.tmp / 'fx' / 'vp_prior_art')
        self.assertEqual(cov['caps_reached'], 1)
        self.assertEqual(cov['sources_unavailable'], ['pubmed'])
        self.assertEqual(cov['calls'], 4)
        self.assertCode('[COVER-STALE]')                      # prior_art.json still holds the old computation

    def test_card_prints_coverage_never_a_recall(self):
        t = card_text(self)
        line = next(l for l in t.splitlines() if l.startswith('- Coverage'))
        self.assertIn('recall unknown', line)
        self.assertIn('2 call', line)

    def test_recall_claims_are_refused(self):
        for fname, fn in (('recommendation.json', lambda d: d.update(reason='The search found only separate bricks, with a degraded recall, so T1 comes first.')),
                          ('recommendation.json', lambda d: d.update(reason=fr("La recherche sur les housses de feutre a un rappel d{e'}grad{e'} ; examiner le berceau t{e'}moin en premier."))),
                          ('prior_art.json', lambda d: d['closest_work'][0].update(what_differs='Observational only; recall of the search is about 80 percent.'))):
            self.fresh()
            self.w = self.to_r3()
            mutate(self.w, fname, fn)
            self.assertCode('[RECALL-CLAIM]')

    def test_not_found_is_weak_when_a_cap_was_hit(self):
        mutate(self.w, 'prior_art.json', lambda d: d['coverage'].update(caps_reached=2))
        # (card refuses on the stale coverage; the weak-line rule is tested on the pure function)
        self.assertIn('weak', self.guards.not_found_note({'calls': 3, 'caps_reached': 2, 'sources_unavailable': []}))
        self.assertIn('weak', self.guards.not_found_note({'calls': 3, 'caps_reached': 0, 'sources_unavailable': ['pubmed']}))
        self.assertNotIn('weak', self.guards.not_found_note({'calls': 3, 'caps_reached': 0, 'sources_unavailable': []}))


class HybridR3Test(R3):
    SENT = "Smith et al. (2019) reported a citation gain of 12.5% for titles under ten words, measured on 240 records."

    def setUp(self):
        super().setUp()
        self.w = self.to_r3()
        self.draft = ("Working notes before any search. " + self.SENT + " The rank gain might be about sixty percent of the "
                      "prestige effect in my memory. Neighbouring idea: rank-based targets for retrieval. Another idea: "
                      "query-log replay on a frozen index.\n")
        (self.w / 'free_draft.md').write_text(self.draft, encoding='utf-8')

    def seal(self, claims):
        import hashlib
        h = hashlib.sha256(self.draft.encode('utf-8')).hexdigest()
        write_json(self.w / 'draft_claims.json', {'draft_sha256': h, 'claims': claims})
        def go(d):
            d['steps'].insert(0, {'step': 'free_draft', 'utc': '2026-11-14T08:50:00Z', 'duration_s': 'unknown', 'cost_usd': 'unknown', 'sha256': h})
        mutate(self.w, 'run.json', go)

    def test_overlap_only_quote_does_not_cover_in_r3(self):
        hy = self.load_hybrid()
        rows = hy.analyse(self.draft, [{'id': 'D1', 'quote': 'Smith et al. (2019)', 'status': 'unverified_memory'}], {}, strict=True)
        ref = [r for r in rows if r['kind'] == 'reference'][0]
        self.assertEqual(ref['covered_by'], [])
        rows = hy.analyse(self.draft, [{'id': 'D1', 'quote': self.SENT, 'status': 'unverified_memory'}], {}, strict=True)
        self.assertEqual([r for r in rows if r['kind'] == 'reference'][0]['covered_by'], ['D1'])
        rows = hy.analyse(self.draft, [{'id': 'D1', 'quote': 'Smith et al. (2019)', 'status': 'unverified_memory'}], {}, strict=False)
        self.assertEqual([r for r in rows if r['kind'] == 'reference'][0]['covered_by'], ['D1'])      # legacy net unchanged

    def load_hybrid(self):
        return load_tool('hybrid')

    def test_integers_and_spelled_numbers_are_detected(self):
        hy = self.load_hybrid()
        kinds = {(r['kind'], r['text']) for r in hy.candidates(self.draft, strict=True)}
        self.assertIn(('integer', '240'), kinds)
        self.assertTrue(any(k == 'integer' and 'sixty' in t.lower() for k, t in kinds), kinds)
        legacy = {(r['kind'], r['text']) for r in hy.candidates(self.draft)}
        self.assertNotIn(('integer', '240'), legacy)
        fr = {(r['kind'], r['text'].lower()) for r in hy.candidates('Il y a quatre-vingts strates et soixante mois.', strict=True)}
        self.assertEqual(len([1 for k, _ in fr if k == 'integer']), 2, fr)

    def test_a_verified_claim_needs_an_explicit_support(self):
        ref = {'id': 'doi:10.1000/titles.2019', 'run': 'prior_art', 'claim': 'A1'}
        good = {'proposition': 'Shorter titles are associated with more citations', 'fragment': 'shorter titles received more citations',
                'link': 'the fragment states the association, not a 12.5% figure', 'scope': 'association only'}
        self.seal([{'id': 'D1', 'quote': self.SENT, 'status': 'verified', 'ref': ref}])
        self.assertCode('[DRAFT-SUPPORT]')
        self.seal_again = None
        for bad in ({}, dict(good, fragment='titles cause citations'), dict(good, link='ok')):
            self.fresh()
            self.w = self.to_r3()
            (self.w / 'free_draft.md').write_text(self.draft, encoding='utf-8')
            self.seal([{'id': 'D1', 'quote': self.SENT, 'status': 'verified', 'ref': ref, 'support': bad}])
            self.assertCode('[DRAFT-SUPPORT]')

    def test_richness_and_priority(self):
        hy = self.load_hybrid()
        ref = {'id': 'doi:10.1000/titles.2019', 'run': 'prior_art', 'claim': 'A1'}
        self.seal([{'id': 'D1', 'quote': self.SENT, 'status': 'unverified_memory', 'kind': 'magnitude'},
                   {'id': 'D2', 'quote': 'Neighbouring idea: rank-based targets for retrieval.', 'status': 'unverified_memory', 'kind': 'lead'},
                   {'id': 'D3', 'quote': 'Another idea: query-log replay on a frozen index.', 'status': 'unverified_memory', 'kind': 'lead'}])
        rich = hy.richness(self.w)
        self.assertEqual((rich['leads'], rich['magnitudes'], rich['claims'], rich['verified']), (2, 1, 3, 0))
        self.assertEqual(rich['verified_share'], 0.0)
        self.assertIn('leads', hy.richness_line(rich))
        order = hy.priority(self.w)
        self.assertEqual(sorted(c['id'] for c in order), ['D1', 'D2', 'D3'])

    def test_a_decisive_unverified_claim_must_be_marked_in_the_reason(self):
        self.seal([{'id': 'D1', 'quote': self.SENT, 'status': 'unverified_memory', 'kind': 'magnitude'}])
        # Exact quote reuse retains the decisive check. Partial paraphrases
        # are now advisory [DRAFT-REUSE?], independently tested in test_v5r2.
        mutate(self.w, 'recommendation.json', lambda d: d.update(reason=self.SENT))
        p = self.probs()
        self.assertTrue(self.code_in('[DRAFT-DECISIVE]', p), p)
        mutate(self.w, 'recommendation.json', lambda d: d.update(
            reason=self.SENT + ' unverified (memory)'))
        self.assertNoCode('[DRAFT-DECISIVE]')


class SyntheticCardRegressionTest(R3):
    """R3-18: three synthetic detector cases retain the defect contracts."""

    def test_the_three_synthetic_cards_carry_the_defects_the_tests_name(self):
        c1 = regression_text(1)
        c2 = regression_text(2)
        c3 = regression_text(3)
        self.assertIn('(+2 more in critique.json)', c1)
        self.assertIn('degraded recall', c1)
        self.assertIn('216 months', c1)
        self.assertIn('Across 80 strata', c3)
        self.assertIn('-> fixed:', c2)
        self.assertIn('After (T1, assumption', c3)
        self.assertIn('Rebound after T1 (indeterminate, outcome from assumption)', c2)

    def test_r3_cards_never_carry_them(self):
        w = self.to_r3()
        t = card_text(self)
        for bad in ('rappel', 'outcome from assumption', ', assumption,', '(+'):
            self.assertNotIn(bad, t)

    def test_synthetic_card_1_reason_is_refused(self):
        w = self.to_r3()
        mutate(w, 'recommendation.json', lambda d: d.update(
            reason=fr("La recherche sur les berceaux de papier a un rappel d{e'}grad{e'} ; inspecter le plateau t{e'}moin avant de choisir.")))
        self.assertCode('[RECALL-CLAIM]')
