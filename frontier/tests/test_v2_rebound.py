# SPDX-License-Identifier: Apache-2.0
"""V2-26 .. V2-28 of regression specification: classed trials of the project are said at the head; the neighbouring ideas come from an iterative search."""
import copy
import re
from pathlib import Path

from .v2_common import V2, VP, mutate, read_json, run_tool, write_json
from .r3_common import REBOUND

BANNER = 'REOPENS A TRIAL CLASSED BY YOUR PROJECT'
NET = 'POSSIBLE OVERLAP WITH A TRIAL CLASSED BY YOUR PROJECT'
# the words of the archives are chosen outside the keywords of the plans: the outgoing guard would refuse a keyword that the
# archives hold and the idea does not
LINE2 = 'Paired shortened title lookup experiment on an offline index: REJECTED after the first ablation run.'
LINE3 = 'DO NOT REOPEN unless the index grows beyond 2000 records.'


def plan_of(idea_id, queries):
    w = queries[0].split()
    w = (w + w * 4)[:4]                               # two keywords of two words, taken from the query of the idea
    k1, k2, k3 = ' '.join(w[:2]), ' '.join(w[2:4]), 'preprint'
    f1 = {'field': 'scientometrics', 'why': 'where the citation side of the idea is studied', 'keywords': [k1, k2]}
    f2 = {'field': 'information retrieval', 'why': 'where the retrieval side of the idea is studied', 'keywords': [k2, k1]}
    f2b = dict(f2, keywords=[k2, k1, k3])
    return {
        'iterations': [
            {'fields': [f1, f2],
             'revision': {'learned': 'The first round finds abstract wording but never coverage of query terms.',
                          'changes': ['added the keyword preprint to the retrieval field']}},
            {'fields': [f1, f2b], 'queries': queries,
             'stop_reason': 'The second round returned the same closest work as the first one.'}],
        'differs_from_previous': 'The first version tested title length; the revised idea moves the lever to the abstract coverage of query terms.'}


class RebV2(V2):
    def setUp(self):
        super().setUp()
        self.w = self.to_v2(REBOUND)

    def add_plans(self):
        def go(d):
            for i in d['ideas']:
                i['search_plan'] = plan_of(i['id'], list(i['prior_art']['queries']))
        for fname in ('rebound.json', 'rebound_after.json'):
            mutate(self.w, fname, go)

    def edit_idea(self, fn, idea='N1', fname='rebound.json'):
        mutate(self.w, fname, lambda d: fn(next(i for i in d['ideas'] if i['id'] == idea)))


class IterativeSearchTest(RebV2):
    def setUp(self):
        super().setUp()
        self.add_plans()

    def codes(self):
        return [p for p in self.v2_probs() if p.startswith('[REB-PLAN]')]

    def test_baseline_clean(self):
        self.assertV2Clean(REBOUND)

    def test_search_plan_is_required_on_every_idea_of_a_v2_directory(self):
        self.edit_idea(lambda i: i.pop('search_plan'))
        self.assertTrue(self.codes() or any(p.startswith('[REB-PLAN]') for p in self.probs(REBOUND)))

    def test_two_iterations_at_least(self):
        self.edit_idea(lambda i: i['search_plan'].update(iterations=i['search_plan']['iterations'][:1]))
        self.assertTrue(any(p.startswith('[REB-PLAN]') for p in self.probs(REBOUND)))

    def test_first_iteration_has_two_fields(self):
        self.edit_idea(lambda i: i['search_plan']['iterations'][0].update(fields=i['search_plan']['iterations'][0]['fields'][:1]))
        self.assertTrue(any(p.startswith('[REB-PLAN]') for p in self.probs(REBOUND)))

    def test_a_revision_that_changes_nothing_is_not_an_iteration(self):
        self.edit_idea(lambda i: i['search_plan']['iterations'][1].update(fields=copy.deepcopy(i['search_plan']['iterations'][0]['fields'])))
        self.assertTrue(any(p.startswith('[REB-PLAN]') for p in self.probs(REBOUND)))

    def test_the_revised_idea_must_say_how_it_differs_from_the_previous_one(self):
        self.edit_idea(lambda i: i['search_plan'].pop('differs_from_previous'))
        self.assertTrue(any(p.startswith('[REB-PLAN]') for p in self.probs(REBOUND)))

    def test_the_final_queries_are_the_queries_of_the_prior_art_check(self):
        self.edit_idea(lambda i: i['search_plan']['iterations'][1].update(queries=['abstract wording preprint citation']))
        self.assertTrue(any(p.startswith('[REB-PLAN]') for p in self.probs(REBOUND)))

    def test_a_query_must_use_a_keyword_of_its_plan(self):
        def go(i):
            i['search_plan']['iterations'][1]['fields'][0]['keywords'] = ['something', 'else']
            i['search_plan']['iterations'][1]['fields'][1]['keywords'] = ['unrelated', 'words']
        self.edit_idea(go)
        self.assertTrue(any(p.startswith('[REB-PLAN]') for p in self.probs(REBOUND)))

    def test_quota_and_prior_art_rules_are_inherited(self):
        def go(d):
            for i in d['ideas'][:3]:
                i['operator'] = 'analogy'
                i['recurring_ingredient'] = True
        mutate(self.w, 'rebound.json', go)
        self.assertTrue(any(p.startswith('[REB-QUOTA]') for p in self.probs(REBOUND)))

    def test_keywords_of_a_plan_cannot_carry_archive_words(self):
        proj = self.project()
        (proj / 'LESSONS.md').write_text('# Lessons\nThe zeppelin ledger approach was REJECTED. DO NOT REOPEN.\n', encoding='utf-8')
        mutate(self.w, 'intake.json', lambda d: d.update(project_dirs=[str(proj)]))
        self.edit_idea(lambda i: i['search_plan']['iterations'][0]['fields'][0]['keywords'].append('zeppelin'))
        self.assertTrue(any(p.startswith('[REB-PLAN]') and 'archive' in p for p in self.probs(REBOUND)))

    def test_the_report_shows_the_iterations(self):
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rep = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertIn('search plan: 2 iterations', rep)
        self.assertIn('differs from the previous version', rep)


class ClassedByTheProjectTest(V2):
    """The synthetic packing-history regression: a trial the project had classed came back as a combination, and nothing said so at the head."""

    def setUp(self):
        super().setUp()
        self.w = self.to_v2()
        self.proj = self.tmp / 'myproject'
        (self.proj / 'notes').mkdir(parents=True)
        (self.proj / 'notes' / 'titles.md').write_text('# Title experiments\n%s\n%s\n' % (LINE2, LINE3), encoding='utf-8')
        mutate(self.w, 'intake.json', lambda d: d.update(project_dirs=[str(self.proj)]))
        mutate(self.w, 'framing.json', lambda d: d['archives'].update(checked=True, note='project folders were given'))
        self.terms(self.w, 'intake', [{'term': 'ablation run', 'synonyms': [], 'group': 'idea'}])
        self.terms(self.w, 'tests', [{'term': 'randomised rank', 'synonyms': [], 'group': 'test', 'for': 'T1'},
                                     {'term': 'citation ratio', 'synonyms': [], 'group': 'test', 'for': 'T2'}])

    def terms(self, w, label, terms):
        f = self.tmp / ('terms-%s.json' % label)
        write_json(f, {'terms': terms})
        r = run_tool('history', 'scan', w, '--label', label, '--terms-file', f)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def entry(self):
        return next(e for e in read_json(self.w / 'history.json')['entries'] if e['file'] == 'notes/titles.md' and e['verdict'] == 'classed')

    def keep(self):
        e = self.entry()
        item = {'entry': e['id'], 'cited': 'notes/titles.md:%d' % e['line'], 'verdict_quoted': 'REJECTED', 'decision': 'kept',
                'reopen_condition': 'unless the index grows beyond 2000 records',
                'reopen_condition_source': 'notes/titles.md:3',
                'condition_met': 'The offline index now holds 5000 records, so the written condition is met for this test.'}
        mutate(self.w, 'tests.json', lambda d: [t.update(internal_history=[item]) for t in d['tests'] if t['id'] == 'T1'])

    def test_a_net_overlap_without_a_term_match_is_marked_with_the_file_and_line(self):
        w = self.warns()
        hit = [x for x in w if '[HISTORY-NET]' in x]
        self.assertTrue(hit, w)
        self.assertIn('notes/titles.md:2', hit[0])
        self.assertIn('T1', hit[0])
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[HISTORY-NET]')], [])

    def test_the_net_mark_is_at_the_head_of_the_test_on_the_card(self):
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        m = re.search(r'### T1: ([^\n]*)', card)
        self.assertTrue(m.group(1).startswith(NET), m.group(1)[:120])
        self.assertIn('notes/titles.md:2', m.group(1))

    def test_a_kept_trial_is_said_at_the_head_with_verdict_and_condition(self):
        self.keep()
        self.assertEqual([p for p in self.v2_probs() if p.startswith('[HISTORY')], [])
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        head = re.search(r'### T1: ([^\n]*)', card).group(1)
        self.assertTrue(head.startswith(BANNER), head[:120])
        for needle in ('notes/titles.md:2', 'REJECTED', 'unless the index grows beyond 2000 records', 'The offline index now holds 5000 records'):
            self.assertIn(needle, head)
        self.assertNotIn(NET, head, 'a cited trial is not also a possible overlap')

    def test_a_removed_trial_leaves_no_banner(self):
        e = self.entry()
        mutate(self.w, 'tests.json', lambda d: d.update(internal_history_removed=[
            {'cited': 'notes/titles.md:%d' % e['line'], 'what': 'The first paired retrieval test', 'why': 'Classed in the project notes; the condition is not met.'}]))
        warns = [x for x in self.warns() if '[HISTORY-NET]' in x and 'T1' in x]
        self.assertTrue(warns, 'the net still sees T2 or T1 text: marking is not silenced by a removal elsewhere')

    def test_the_classed_trials_are_all_listed_not_counted(self):
        for i in range(8):
            (self.proj / 'notes' / ('t%d.md' % i)).write_text('Variant %d of the ablation run: REJECTED. DO NOT REOPEN.\n' % i, encoding='utf-8')
        self.terms(self.w, 'intake', [{'term': 'ablation run', 'synonyms': [], 'group': 'idea'}])
        self.terms(self.w, 'tests', [{'term': 'randomised rank', 'synonyms': [], 'group': 'test', 'for': 'T1'},
                                     {'term': 'citation ratio', 'synonyms': [], 'group': 'test', 'for': 'T2'}])
        run_tool('card', self.w)
        card = (self.w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        self.assertNotRegex(card, r'\(\+\d+ more')
        for i in range(8):
            self.assertIn('notes/t%d.md' % i, card)



class NoArchivesTest(V2):
    def test_no_dirs_means_not_checked_and_no_net(self):
        w = self.to_v2()
        self.assertEqual([x for x in self.check.warnings(w) if 'HISTORY' in x], [])
        self.assertEqual(run_tool('card', w).returncode, 0)
        self.assertIn('Already tried here: not checked', (w / 'IDEA-CARD.md').read_text(encoding='utf-8'))


class ClassedIdeaBannerTest(RebV2):
    def test_banner_on_a_neighbouring_idea(self):
        self.add_plans()
        proj = self.tmp / 'myproject'
        (proj / 'notes').mkdir(parents=True)
        (proj / 'notes' / 'titles.md').write_text('# Title experiments\n%s\n%s\n' % (
            'Query mechanism variant for the title and visibility lever: REJECTED after the first ablation run.', LINE3), encoding='utf-8')
        mutate(self.w, 'intake.json', lambda d: d.update(project_dirs=[str(proj)]))
        mutate(self.w, 'framing.json', lambda d: d['archives'].update(checked=True, note='project folders were given'))
        f = self.tmp / 'terms.json'
        write_json(f, {'terms': [{'term': 'ablation run', 'synonyms': [], 'group': 'idea'}]})
        self.assertEqual(run_tool('history', 'scan', self.w, '--label', 'intake', '--terms-file', f).returncode, 0)
        ids_t = [t['id'] for t in read_json(self.w / 'tests.json')['tests']]
        write_json(f, {'terms': [{'term': 'zebra %s' % t, 'synonyms': [], 'group': 'test', 'for': t} for t in ids_t]})
        self.assertEqual(run_tool('history', 'scan', self.w, '--label', 'tests', '--terms-file', f).returncode, 0)
        ids = [i['id'] for f in ('rebound.json', 'rebound_after.json') for i in read_json(self.w / f)['ideas']]
        write_json(f, {'terms': [{'term': 'zebra %s' % i, 'synonyms': [], 'group': 'neighbour', 'for': i} for i in ids]})
        self.assertEqual(run_tool('history', 'scan', self.w, '--label', 'rebound', '--terms-file', f).returncode, 0)
        net = [x for x in self.warns(REBOUND) if '[HISTORY-NET]' in x and 'N1' in x]
        self.assertTrue(net, self.warns(REBOUND))
        r = run_tool('card', self.w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rep = (self.w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        line = next(l for l in rep.splitlines() if l.startswith('- N1') or l.startswith('- N1:'))
        self.assertIn(NET, line)
