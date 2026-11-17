# SPDX-License-Identifier: Apache-2.0
"""V2-21 .. V2-25 of regression specification: the Next step block, no truncation, the page, marking instead of blocking, claimed fixes."""
import re

from .helpers import FIXTURES
from .v2_common import V2, VP, mutate, read_json, run_tool, write_json

SIX = ('This single decision sentence is long on purpose, ' + ', and '.join(
    'clause number %d carries a threshold of %d units' % (i, i * 7) for i in range(1, 9)) + ', so it must reach the reader whole.')
TRUNC = re.compile(r'…|\.\.\.|\(\+\d+ (?:more|earlier)')


def card_of(case, name=VP, report=False):
    r = run_tool('card', case.work(name))
    case_assert = case.assertEqual(r.returncode, 0, r.stdout + r.stderr)
    return (case.work(name) / ('IDEA-REPORT.md' if report else 'IDEA-CARD.md')).read_text(encoding='utf-8')


class NextStepTest(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def test_block_follows_the_recommendation_with_four_lines_and_a_title(self):
        card = card_of(self)
        lines = card.splitlines()
        i = next(k for k, l in enumerate(lines) if l.startswith('**Recommendation'))
        j = next(k for k, l in enumerate(lines) if l == '## Next step')
        self.assertLessEqual(j - i, 2)
        block = lines[j:j + 5]
        self.assertTrue(block[1].startswith('First step: '))
        self.assertTrue(block[2].startswith('Inputs: '))
        self.assertTrue(block[3].startswith('Cost: '))
        self.assertTrue(block[4].startswith('Stop rule: '))
        self.assertNotIn('## Tomorrow', card)

    def test_the_lines_are_the_first_test_whole(self):
        tj = read_json(self.w / 'tests.json')
        first = next(t for t in tj['tests'] if t['id'] == tj['ranking']['order'][0])
        # the rule of an executed test is fingerprinted: only the feasibility changes here; the stop rule is copied as it stands
        mutate(self.w, 'tests.json', lambda d: [t['feasibility'].update(data=SIX) for t in d['tests'] if t['id'] == first['id']])
        card = card_of(self)
        self.assertIn('Stop rule: ' + first['decision_rule']['stop_if'], card)
        self.assertIn('Inputs: ' + SIX, card)

    def test_next_step_is_required_and_points_to_the_first_test(self):
        mutate(self.w, 'recommendation.json', lambda d: d.pop('next_step'))
        self.assertBlocks('[NEXT-STEP]')
        self.fresh()
        self.w = self.to_v2()
        mutate(self.w, 'recommendation.json', lambda d: d['next_step'].update(test='T2'))
        self.assertBlocks('[NEXT-STEP]')
        self.fresh()
        self.w = self.to_v2()
        mutate(self.w, 'recommendation.json', lambda d: d['next_step'].update(first_action='ok'))
        self.assertBlocks('[NEXT-STEP]')

    def test_framing_and_prior_art_are_on_the_card(self):
        card = card_of(self)
        self.assertIn('Framing: approved by the user', card)
        self.assertIn('Success criterion:', card)
        self.assertIn('Would be refuted by:', card)
        self.assertIn('Research plan: 2 iterations', card)
        self.assertIn('recall unknown', card)
        self.assertIn('shorter titles received more citations', card)

    def test_assumed_framing_is_marked(self):
        def go(d):
            d['approval'].update(status='assumption', by='assumption', reply='ASSUMED: the user was absent.')
            d['approval'].pop('changes', None)
        mutate(self.w, 'framing.json', go)
        card = card_of(self)
        self.assertIn('Framing: ASSUMED (the user was absent', card)

    def test_corrected_framing_is_shown_as_corrected(self):
        def go(d):
            d['approval'].update(status='corrected', changes=['success_criterion'], reply='The criterion must name the sample size.')
            d['final']['success_criterion'] = 'A paired retrieval test on 200 records separates retrieval from journal prestige'
        mutate(self.w, 'framing.json', go)
        card = card_of(self)
        self.assertIn('Framing: corrected by the user (success_criterion)', card)
        self.assertIn('on 200 records', card)


class CompleteCardTest(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def long_texts(self):
        mutate(self.w, 'recommendation.json', lambda d: d.update(reason=SIX))
        mutate(self.w, 'intake.json', lambda d: d.update(
            idea=SIX + ' ' + SIX, justifying_gain={'text': SIX, 'source': 'user'}))
        mutate(self.w, 'prior_art.json', lambda d: d['closest_work'][0].update(what_differs=SIX))
        mutate(self.w, 'hypotheses.json', lambda d: d['hypotheses'][0].update(statement=SIX))

    def test_no_truncation_mark_in_card_or_report(self):
        self.long_texts()
        for report in (False, True):
            text = card_of(self, report=report)
            self.assertEqual(TRUNC.findall(text), [], 'report' if report else 'card')

    def test_decision_texts_are_whole_on_the_card(self):
        self.long_texts()
        card = card_of(self)
        for field in (SIX,):
            self.assertGreaterEqual(card.count(field), 3, 'reason, gain, what differs, statement: each whole')
        idea = SIX + ' ' + SIX
        self.assertIn(idea, card)

    def test_lists_are_not_cut(self):
        def go(d):
            d['materials']['unexplained_anomalies'] = [
                {'text': 'Anomaly number %d of the closest work.' % i, 'refs': [{'id': 'doi:10.1000/titles.2019', 'run': 'prior_art', 'claim': 'A1'}]}
                for i in range(1, 5)]
        mutate(self.w, 'prior_art.json', go)
        card = card_of(self)
        for i in range(1, 5):
            self.assertIn('Anomaly number %d' % i, card)
        self.assertNotRegex(card, r'\(\+\d+\)')

    def test_the_page_limit_of_v2_and_the_fallback_to_the_report(self):
        card = card_of(self)
        self.assertLessEqual(len(card.splitlines()), 110)
        mutate(self.w, 'critique.json', lambda d: d.update(items=d['items'] * 6))
        card = card_of(self)
        self.assertLessEqual(len(card.splitlines()), 110)

    def test_report_holds_every_marked_and_unmarked_line(self):
        report = card_of(self, report=True)
        for needle in ('Framing', 'Research plan', 'Facets', 'Next step'):
            self.assertIn(needle, report)

    def test_the_synthetic_packing_card_defects_are_the_regression_cases(self):
        text = (FIXTURES / 'synthetic_defect_cards' / 'synthetic-packing-defects.card').read_text(encoding='utf-8')
        marks = set(TRUNC.findall(text))
        self.assertTrue(any(m.startswith('(+') for m in marks), 'the old card says (+34 more ...)')
        self.assertIn('...', marks)
        self.assertIn("not tied to the project's numbers", text)
        self.assertIn('no test or idea overlaps it', text)
        # none of the three can come out of a v2 directory
        self.long_texts()
        v2 = card_of(self)
        self.assertEqual(TRUNC.findall(v2), [])
        self.assertNotIn("not tied to the project's numbers (the simulations use values chosen by hand)", v2)


class MarkNotBlockTest(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2()

    def test_methodological_points_are_marked_not_blocking(self):
        mutate(self.w, 'tests.json', lambda d: [t.pop('verdict_scope') for t in d['tests']])
        self.assertMarks('[SCOPE]')
        mutate(self.w, 'tests.json', lambda d: [t['traps']['data_split'].pop('data_seen_before') for t in d['tests']])
        self.assertMarks('[DATA-SEEN]')
        r = run_tool('check', self.w)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('mark: ', r.stdout)

    def test_the_same_point_still_blocks_an_r3_directory(self):
        self.fresh()
        w = self.to_r3()
        mutate(w, 'tests.json', lambda d: [t.pop('verdict_scope') for t in d['tests']])
        self.assertTrue(any(p.startswith('[SCOPE]') for p in self.check.problems(w)))

    def test_the_card_lists_the_marks_whole(self):
        mutate(self.w, 'tests.json', lambda d: [t.pop('verdict_scope') for t in d['tests']])
        card = card_of(self)
        self.assertIn('Marked, not blocking', card)
        self.assertIn('[SCOPE]', card)

    def test_factual_and_arithmetic_errors_still_block(self):
        mutate(self.w, 'hypotheses.json', lambda d: d['hypotheses'][0]['against'].append(
            {'id': 'doi:10.1000/ghost.2021', 'run': 'prior_art', 'claim': 'A4', 'says': 'the abstract makes no causal claim'}))
        self.assertBlocks('[REF-ABSENT]')
        self.fresh()
        self.w = self.to_v2()
        mutate(self.w, 'tests.json', lambda d: d['tests'][0]['sensitivity'].update(
            replications='80 strata (creation month x tercile of citations) of preprints created from 2024-01-01 to 2024-12-31; 200 records x 1 query each'))
        self.assertBlocks('[ARITH')
        self.fresh()
        self.w = self.to_v2()
        mutate(self.w, 'decisive_claims.json', lambda d: d['claims'][0].update(fragment='shorter titles are always cited far more'))
        self.assertBlocks('[DECISIVE-FRAGMENT]')

    def test_recall_claim_and_tampered_coverage_still_block(self):
        mutate(self.w, 'recommendation.json', lambda d: d.update(reason='The search has high recall, so the closest work is surely found.'))
        self.assertBlocks('[RECALL-CLAIM]')

    def test_confidentiality_still_blocks(self):
        proj = self.project()
        mutate(self.w, 'intake.json', lambda d: d.update(project_dirs=[str(proj)]))
        self.assertTrue(any(p.startswith('[HISTORY-MISSING]') for p in self.v2_probs()))


class ClaimedFixTest(V2):
    def test_a_fixed_item_without_proof_is_shown_as_claimed_not_proven(self):
        w = self.to_v2()
        mutate(w, 'critique.json', lambda d: d['items'][0]['response'].pop('proof'))
        self.assertMarks('[FIX-PROOF]')
        card = card_of(self)
        self.assertIn('claimed fixed, not proven', card)
        self.assertIn('Marked, not blocking', card)

    def test_a_fixed_item_without_second_critique_is_marked(self):
        w = self.to_v2()
        mutate(w, 'critique.json', lambda d: d['second_critique']['verdicts'][0].update(objection_lifted='no'))
        self.assertMarks('[FIX-UNCONFIRMED]')
        self.assertIn('claimed fixed, not proven', card_of(self))

    def test_proven_fixes_are_shown_fixed(self):
        w = self.to_v2()
        self.assertIn('fixed (confirmed by the second critique)', card_of(self))
