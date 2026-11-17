# SPDX-License-Identifier: Apache-2.0
"""Round 2 of the rebound step: registered prior art tied to the VP gateway journal, budget per card, no note disguised as
an order, unverified references (regression specification RB39 to RB44)."""
import json

from .helpers import load_tool, mutate, read_json, run_tool
from .rb_common import NOVP, RB, VP


def journal(case, run):
    return case.fx / ('vp_' + run) / 'state' / 'journal.jsonl'


def rewrite_journal(case, run, fn):
    p = journal(case, run)
    rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
    fn(rows)
    p.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')


class ResolveEntryTest(RB):
    """RB39."""

    def test_result_entry_needs_the_test_of_the_result(self):
        rb = load_tool('rebound')
        files = {'tests.json': {'tests': [{'id': 'T1'}, {'id': 'T2'}]}, 'result.json': {'mode': 'executed', 'test': 'T1'}}
        self.assertTrue(rb.resolve_entry('result.json:T1', files))
        self.assertFalse(rb.resolve_entry('result.json:T2', files))      # T2 exists but the result is about T1
        self.assertTrue(rb.resolve_entry('tests.json:T2', files))

    def test_plan_only_result_resolves_nothing(self):
        rb = load_tool('rebound')
        files = {'tests.json': {'tests': [{'id': 'T1'}]}, 'result.json': {'mode': 'plan only', 'reason': 'x'}}
        self.assertFalse(rb.resolve_entry('result.json:T1', files))


class RegisteredPriorArtTest(RB):
    """RB40: the search is recorded and tied to the gateway journal of the idea's own VP run."""

    def test_the_valid_fixture_passes(self):
        self.assertEqual(self.probs(), [])

    def test_a_query_never_sent_to_the_gateway(self):
        self.idea(VP, 'N1', lambda i: i['prior_art']['queries'].append('a query that was never sent anywhere'))
        probs = self.assertCode('[REB-PRIOR-ART]')
        self.assertTrue(any('never sent anywhere' in p or 'gateway journal' in p for p in probs), probs)

    def test_case_and_spaces_do_not_matter(self):
        self.idea(VP, 'N1', lambda i: i['prior_art'].update(queries=['  ABSTRACT term   coverage RETRIEVAL rank preprint ']))
        self.assertEqual(self.probs(), [])

    def test_one_vp_run_per_idea(self):
        self.idea(VP, 'N2', lambda i: i['prior_art'].update(vp_run='rb_n1'))
        probs = self.assertCode('[REB-PRIOR-ART]')
        self.assertTrue(any('one VP run per idea' in p for p in probs), probs)

    def test_journal_entry_after_the_declared_date(self):
        def late(rows):
            rows[0]['utc'] = '2026-11-14T13:50:00.000000+00:00'      # the idea says its check was done at 13:40
        rewrite_journal(self, 'rb_n1', late)
        self.assertCode('[REB-PRIOR-ART]')

    def test_journal_entry_after_the_ranking(self):
        def later(rows):
            rows[0]['utc'] = '2026-11-14T14:10:00.000000+00:00'
        rewrite_journal(self, 'rb_n1', later)
        self.idea(VP, 'N1', lambda i: i['prior_art'].update(date='2026-11-14T14:20:00Z'))
        probs = self.assertCode('[REB-ORDER]')
        self.assertTrue(any('after the ranking' in p for p in probs), probs)

    def test_journal_without_any_search_call(self):
        def none(rows):
            for r in rows:
                r['call'] = 'fetch'
        rewrite_journal(self, 'rb_n2', none)
        self.assertCode('[REB-PRIOR-ART]')

    def test_closest_work_comes_from_the_idea_own_run(self):
        def go(i):
            i['prior_art']['closest_work'][0]['ref'].update(run='prior_art', claim='A1')
        self.idea(VP, 'N1', go)
        probs = self.probs()
        self.assertTrue(any(p.startswith('[REB-PRIOR-ART]') and 'own VP run' in p for p in probs), probs)

    def test_no_ranking_without_queries(self):
        self.idea(VP, 'N3', lambda i: i['prior_art'].update(queries=[]))
        self.assertCode('[REB-ORDER]')

    def test_no_ranking_without_scope(self):
        self.idea(VP, 'N3', lambda i: i['prior_art'].update(scope=''))
        self.assertCode('[REB-ORDER]')

    def test_no_choice_without_a_registered_search_even_without_ranking_in_file(self):
        self.idea(VP, 'N3', lambda i: i['prior_art'].update(queries=[]))
        self.mut(VP, lambda d: d.pop('ranking'))
        probs = self.assertCode('[REB-ORDER]')
        self.assertTrue(any('N3' in p for p in probs), probs)

    def test_without_ranking_or_choice_the_gap_is_only_a_prior_art_problem(self):
        self.drop_ranking()
        self.idea(VP, 'N3', lambda i: i['prior_art'].update(queries=[]))
        self.assertNoCode('[REB-ORDER]')
        self.assertCode('[REB-PRIOR-ART]')

    def test_step_8_bis_has_the_same_rules(self):
        self.idea(VP, 'B1', lambda i: i['prior_art']['queries'].append('never sent in step 8-bis'), 'rebound_after.json')
        self.assertCode('[REB-PRIOR-ART]')

    def test_without_vp_queries_are_still_required(self):
        self.idea(NOVP, 'N2', lambda i: i['prior_art'].update(queries=[]))
        self.assertCode('[REB-ORDER]', NOVP)


class NoVpTest(RB):
    """RB41."""

    def test_warning_per_idea_without_vp(self):
        probs, warns = self.check.run_all(self.work(NOVP))
        self.assertEqual(probs, [])
        marked = [w for w in warns if w.startswith('[REB-PRIOR-ART]') and 'not verified: no VP' in w]
        self.assertEqual(len(marked), 5, warns)

    def test_no_such_warning_with_vp(self):
        probs, warns = self.check.run_all(self.work(VP))
        self.assertFalse(any('not verified: no VP' in w for w in warns), warns)


class BudgetCardTest(RB):
    """RB42."""

    def test_defaults(self):
        cfg = load_tool('common').config()['rebound']
        self.assertEqual((cfg['prior_art_checks_max'], cfg['prior_art_checks_card_max']), (10, 14))

    def test_checked_ideas_of_the_two_files_are_bounded_per_card(self):
        tools = self.skill_copy(prior_art_checks_card_max=6)       # 5 + 2 checked ideas in the valid directory
        r = run_tool('check', self.work(VP), tools_dir=tools)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any(l.startswith('[BUDGET]') and 'per card' in l for l in r.stdout.splitlines()), r.stdout)

    def test_rebound_vp_run_steps_are_bounded_per_card(self):
        tools = self.skill_copy(prior_art_checks_card_max=6)
        r = run_tool('check', self.work(VP), tools_dir=tools)      # 7 steps recorded
        self.assertIn('rebound_vp_run', r.stdout)

    def test_the_valid_directory_is_inside_the_budget(self):
        self.assertEqual(self.probs(), [])


class NoOrderInDisguiseTest(RB):
    """RB43."""

    def test_prefer_in_canonical_order_is_fine(self):
        self.mut(VP, lambda d: d['ranking']['scenarios'][0].update(prefer=['N1', 'N4']))
        self.assertNoCode('[REB-ORDER]')

    def test_prefer_in_another_order_is_refused(self):
        self.mut(VP, lambda d: d['ranking']['scenarios'][0].update(prefer=['N4', 'N1']))
        self.assertCode('[REB-ORDER]')

    def test_prefer_twice_the_same_idea(self):
        self.mut(VP, lambda d: d['ranking']['scenarios'][0].update(prefer=['N1', 'N1']))
        self.assertCode('[REB-ORDER]')

    def test_ordinal_wording_in_the_ranking(self):
        for phrase in ('N1 is the best idea of the set', 'the top-ranked idea first', 'ranked first in this case',
                       'the most promising idea', 'this is number one', 'first priority for the researcher'):
            with self.subTest(phrase=phrase):
                self.fresh()
                self.mut(VP, lambda d: d['ranking']['scenarios'][0].update(why=phrase + ' under this belief'))
                self.assertCode('[REB-ORDER]')

    def test_ordinal_wording_in_an_idea(self):
        for field in ('teaches', 'statement'):
            with self.subTest(field=field):
                self.fresh()
                self.idea(VP, 'N2', lambda i: i.update({field: i[field] + ' It is the most promising idea of all.'}))
                self.assertCode('[REB-ORDER]')

    def test_ordinary_words_are_not_refused(self):
        self.idea(VP, 'N2', lambda i: i.update(teaches=i['teaches'] + ' The first step is a paired comparison.'))
        self.assertNoCode('[REB-ORDER]')


class UnverifiedReferenceTest(RB):
    """RB44."""

    def set_status(self, run, status):
        def go(d):
            for c in d['claims']:
                if c['id'] == 'A1':
                    c['status'] = status
        mutate(self.fx / ('vp_' + run), 'verdicts.json', go)

    def test_distorted_is_a_warning_not_a_problem(self):
        self.set_status('rb_n1', 'DISTORTED')
        probs, warns = self.check.run_all(self.work(VP))
        self.assertEqual(probs, [])
        self.assertTrue(any(w.startswith('[REB-REF]') and 'DISTORTED' in w for w in warns), warns)

    def test_unverified_and_source_unavailable(self):
        for st in ('UNVERIFIED', 'SOURCE-UNAVAILABLE'):
            with self.subTest(status=st):
                self.fresh()
                self.set_status('rb_n1', st)
                probs, warns = self.check.run_all(self.work(VP))
                self.assertEqual(probs, [])
                self.assertTrue(any(w.startswith('[REB-REF]') and st in w for w in warns), warns)

    def test_found_gives_no_warning(self):
        probs, warns = self.check.run_all(self.work(VP))
        # the valid directory has one UNVERIFIED reference of its own (clicks.2022); the FOUND ones give no warning
        refs = [w for w in warns if w.startswith('[REB-REF]')]
        self.assertEqual(len(refs), 1, refs)
        self.assertIn('clicks.2022', refs[0])

    def test_absent_still_fails(self):
        self.set_status('rb_n1', 'ABSENT')
        self.assertCode('[REF-ABSENT]')

    def test_card_lists_a_distorted_reference_of_the_rebound(self):
        self.set_status('rb_n1', 'DISTORTED')
        r = run_tool('card', self.work(VP))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        first = (self.work(VP) / 'IDEA-CARD.md').read_text(encoding='utf-8').splitlines()[1]
        self.assertIn('Unverified references', first)
        self.assertIn('doi:10.1000/rb.n1.2021', first)
        self.assertIn('DISTORTED', first)


class CardRound2Test(RB):
    """RB38 (scope on the card) and RB41 (no VP)."""

    def text(self, name):
        r = run_tool('card', self.work(name))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return (self.work(name) / 'IDEA-CARD.md').read_text(encoding='utf-8')

    def test_scope_of_the_evidence_is_on_the_section_header(self):
        t = self.text(VP)
        head = [l for l in t.splitlines() if l.startswith('## Neighbouring ideas')][0]
        self.assertIn('recurring ingredients', head)
        self.assertIn('no efficacy figure', head)

    def test_not_verified_without_vp(self):
        t = self.text(NOVP)
        lines = [l for l in t.splitlines() if l.startswith('- N')]
        self.assertEqual(len(lines), 5)
        for l in lines:
            self.assertIn('not verified: no VP', l)

    def test_not_said_with_vp(self):
        self.assertNotIn('not verified: no VP', self.text(VP))
