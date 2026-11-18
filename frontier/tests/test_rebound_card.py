# SPDX-License-Identifier: Apache-2.0
"""card.py shows the neighbouring ideas (regression specification RB12, RB25)."""
import copy
import re

from .helpers import FIXTURES, load_tool, mutate, read_json, run_tool
from .rb_common import NOVP, RB, VP

MAX_LINES = 80


class CardBase(RB):
    def card(self, name=VP, tools=None):
        r = run_tool('card', self.work(name), tools_dir=tools) if tools else run_tool('card', self.work(name))
        return r

    def text(self, name=VP, tools=None):
        r = self.card(name, tools)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return (self.work(name) / 'IDEA-CARD.md').read_text(encoding='utf-8')

    def lines_with(self, text, token):
        return [l for l in text.splitlines() if token in l]


class ContentTest(CardBase):
    def test_section_and_every_idea(self):
        t = self.text()
        self.assertIn('## Neighbouring ideas', t)
        for iid in ('N1', 'N2', 'N3', 'N4', 'N5'):
            self.assertTrue(re.search(r'(?m)^- %s ' % iid, t), iid)

    def test_debates_offer_is_one_final_visible_line(self):
        notice = 'Ranking of the neighbouring ideas by debates is available on request (tournament).'
        for name in (VP, NOVP):
            with self.subTest(name=name):
                text = self.text(name)
                self.assertEqual(text.splitlines().count(notice), 1)
                visible = [line for line in text.splitlines() if line.strip() and not line.startswith('<!--')]
                self.assertEqual(visible[-1], notice)
                self.assertLessEqual(len(text.splitlines()), MAX_LINES)
                self.assertNotIn(notice, (self.work(name) / 'IDEA-REPORT.md').read_text())

    def test_operator_and_label(self):
        t = self.text()
        n4 = self.lines_with(t, '- N4 ')[0]
        self.assertIn('anomaly', n4)
        self.assertIn('not measured', n4)
        n1 = self.lines_with(t, '- N1 ')[0]
        self.assertIn('facet_recombination', n1)
        self.assertNotIn('not measured', n1)

    def test_prior_art_per_idea(self):
        t = self.text()
        self.assertIn('Exists', self.lines_with(t, '- N3 ')[0])
        self.assertIn('already done: read, do not redo', self.lines_with(t, '- N3 ')[0])
        self.assertIn('Partially', self.lines_with(t, '- N1 ')[0])
        self.assertIn('Not found', self.lines_with(t, '- N2 ')[0])
        self.assertIn('Insufficient search', self.lines_with(t, '- N5 ')[0])
        self.assertNotIn('already done', self.lines_with(t, '- N1 ')[0])

    def test_not_found_is_not_new(self):
        t = self.text()
        self.assertRegex(t, r'(?i)not found.{0,80}(never|not).{0,40}(new|novel|absence)')

    def test_feasibility_and_test_shown(self):
        t = self.text()
        n3 = self.lines_with(t, '- N3 ')[0]
        self.assertIn('not established', n3)
        n1 = self.lines_with(t, '- N1 ')[0]
        self.assertIn('established', n1)
        self.assertRegex(n1, r'(?i)test:')

    def test_selection_shown(self):
        t = self.text()
        self.assertRegex(t, r'(?m)^Researcher choice.*retained: N1')
        self.assertIn('rejected: N2', t)

    def test_no_choice_said_when_absent(self):
        self.mut(VP, lambda d: d.pop('selection'))
        mutate(self.fx, 'IDEA-TREE.json', lambda d: [n.update(status='proposed') for n in d['nodes']])
        t = self.text()
        self.assertRegex(t, r'(?i)no idea retained yet|researcher has not chosen')

    def test_step_8_bis_shown(self):
        t = self.text()
        self.assertIn('Rebound after T1', t)
        self.assertIn('confirmed', t)
        self.assertRegex(t, r'(?m)^- B1 ')
        self.assertIn('scope_extension', self.lines_with(t, '- B1 ')[0])
        self.assertIn('transfer', self.lines_with(t, '- B2 ')[0])

    def test_unverified_reference_of_a_rebound_idea_follows_the_disclaimer(self):
        first = self.text().splitlines()[1]
        self.assertTrue(first.startswith('Unverified references:'))
        self.assertIn('doi:10.1000/clicks.2022', first)

    def test_without_vp_header_and_unverified_marks(self):
        t = self.text(NOVP)
        self.assertEqual(t.splitlines()[1], 'References not verified (VP not installed)')
        self.assertIn('## Neighbouring ideas', t)

    def test_duplicates_signalled(self):
        src = read_json(self.work(VP) / 'rebound.json')['ideas'][0]['mechanism']['summary']
        self.idea(VP, 'N2', lambda i: i['mechanism'].update(summary=src))
        self.mut(VP, lambda d: d.update(duplicate_groups=[{'ids': ['N1', 'N2'], 'fields': ['mechanism']}]))
        t = self.text()
        self.assertRegex(t, r'(?i)possible duplicates?: N1, N2 \(mechanism\)')

    def test_not_checked_idea(self):
        tools = self.skill_copy(prior_art_checks_max=4)

        def go(i):
            i['prior_art'] = {'status': 'Insufficient search', 'queries': [], 'scope': 'Not checked: budget used.',
                              'date': '2026-11-14T13:40:00Z', 'closest_work': [], 'uncontrolled': True}
        self.idea(VP, 'N5', go)
        self.drop_ranking()           # round 2 (RB42): an unchecked idea forbids any ranking or choice
        t = self.text(VP, tools)
        self.assertIn('not checked', self.lines_with(t, '- N5 ')[0])

    def test_no_numeric_novelty_on_the_card(self):
        t = self.text()
        sect = t[t.index('## Neighbouring ideas'):]
        self.assertNotRegex(sect, r'(?i)(novelty|originality|score)\W{0,10}\d')
        self.assertNotRegex(sect, r'\b\d+\s*/\s*10\b')

    def test_header_of_the_section_says_what_it_is(self):
        t = self.text()
        sect = t[t.index('## Neighbouring ideas'):]
        self.assertRegex(sect, r'(?i)no ranking by score|not ranked by a model|no novelty score')


class LimitsTest(CardBase):
    def test_one_page(self):
        t = self.text()
        self.assertLessEqual(len(t.splitlines()), MAX_LINES)

    def test_ten_ideas_fit(self):
        def many(d):
            base = d['ideas']
            ops = ['facet_recombination', 'analogy', 'literature_bridge', 'anomaly', 'hypothesis_inversion']
            for k in range(6, 11):
                it = copy.deepcopy(base[k - 6])
                it['id'] = 'N%d' % k
                it['title'] = 'Unique title number %d alpha%d beta%d' % (k, k, k)
                it['statement'] = 'Statement words gamma%d delta%d epsilon%d zeta%d' % (k, k, k, k)
                it['mechanism']['summary'] = 'Mechanism words eta%d theta%d iota%d kappa%d' % (k, k, k, k)
                it['hypothesis']['statement'] = 'Hypothesis words lambda%d omega%d sigma%d rho%d' % (k, k, k, k)
                it['test']['one_line'] = 'Test words tau%d upsilon%d phi%d chi%d' % (k, k, k, k)
                if k >= 6:      # round 2: one VP run per idea, so the added ideas are the ones left unchecked (cap 5)
                    it['prior_art'] = {'status': 'Insufficient search', 'queries': [], 'scope': 'Not checked: budget used.',
                                       'date': '2026-11-14T13:40:00Z', 'closest_work': [], 'uncontrolled': True}
                d['ideas'].append(it)
        self.mut(VP, many)
        self.drop_ranking()           # round 2 (RB42): ideas 9 and 10 are not checked, so nothing is ranked
        t = self.text(VP, self.skill_copy(prior_art_checks_max=5))
        self.assertLessEqual(len(t.splitlines()), MAX_LINES)
        self.assertIn('## Neighbouring ideas', t)
        self.assertIn('Ranking of the neighbouring ideas by debates is available on request (tournament).', t.splitlines())
        for k in range(1, 11):
            self.assertTrue(re.search(r'(?m)^- N%d ' % k, t), k)

    def test_a_full_page_drops_scenarios_then_ideas(self):
        card = load_tool('card')
        w = self.work(VP)
        refs = card.Refs(w, read_json(w / 'intake.json'))
        full = card.neighbour_lines(w, refs, 40)
        self.assertTrue(any(l.startswith('Scenario:') for l in full))
        for avail in (14, 10, 8, 5):
            lines = card.neighbour_lines(w, refs, avail)
            self.assertLessEqual(len(lines), avail)
        short = card.neighbour_lines(w, refs, 9)
        self.assertFalse(any(l.startswith('Scenario:') for l in short))
        self.assertTrue(any('more in rebound.json' in l for l in short), short)
        self.assertEqual(card.neighbour_lines(w, refs, 0), [])


class RefusalTest(CardBase):
    def test_refused_when_the_check_fails(self):
        self.idea(VP, 'N1', lambda i: i.update(operator='magic'))
        r = self.card()
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.work(VP) / 'IDEA-CARD.md').exists())

    def test_stale_when_a_rebound_file_changes(self):
        self.text()
        self.assertEqual(self.check.problems(self.work(VP)), [])
        self.idea(VP, 'N1', lambda i: i.update(teaches='A different thing the idea would teach the researcher.'))
        self.assertCode('[CARD-STALE]')
        self.fresh()
        self.text()
        self.mut(VP, lambda d: d.update(generated_utc='2026-11-14T13:31:00Z'), 'rebound_after.json')
        self.assertCode('[CARD-STALE]')


class UnchangedTest(CardBase):
    def test_card_without_rebound_matches_generated_fixture(self):
        for name in ('valid_vp', 'valid_novp'):
            with self.subTest(name=name):
                t = self.text(name)
                gold = (FIXTURES / 'golden_cards' / (name + '.md')).read_text(encoding='utf-8')
                marks = [line for line in t.splitlines() if line.startswith('Marks: ')]
                self.assertEqual(len(marks), 1)
                self.assertIn('[REVISION]', marks[0])
                self.assertIn('[OVERLAP-LEDGER]', marks[0])
                self.assertEqual(t, gold)
