# SPDX-License-Identifier: Apache-2.0
"""check.py and the history step (regression specification HI14-HI20, HI24): overlap with a CLASSED trial, citations, confidentiality."""
import copy
import json
from pathlib import Path

from .helpers import mutate, read_json, run_tool, write_json
from .hist_common import E_CAPS, HB, INTAKE_TERMS, FOLD_TERM, FOLD_TITLE, write_files


def term(name, *syn, **kw):
    d = {'term': name, 'synonyms': list(syn), 'group': 'idea'}
    d.update(kw)
    return d


class MissingAndStaleTest(HB):
    """HI14, HI15."""

    def test_no_dirs_no_check(self):
        self.assertEqual(self.problems(self.work('valid_novp')), [])
        mutate(self.work('valid_novp'), 'tests.json', lambda d: d['tests'][0].update(internal_history=[{'junk': 1}]))
        self.assertNoCode('[HISTORY', self.work('valid_novp'))

    def test_dirs_without_history_refused(self):
        work = self.new_work()
        self.assertCode('[HISTORY-MISSING]', work)

    def test_stale_project_dirs(self):
        work = self.full_flow()
        mutate(work, 'intake.json', lambda d: d.update(project_dirs=[str(self.tmp / 'elsewhere')]))
        self.assertCode('[HISTORY-STALE]', work)

    def test_missing_queries(self):
        for label in ('intake', 'tests'):
            with self.subTest(label=label):
                self.fresh()
                work = self.full_flow()
                mutate(work, 'history.json', lambda d: d.update(queries=[q for q in d['queries'] if q['label'] != label]))
                self.assertCode('[HISTORY-QUERY]', work, label)

    def test_every_test_needs_a_for_term(self):
        work = self.full_flow()

        def go(d):
            for q in d['queries']:
                if q['label'] == 'tests':
                    q['terms'] = [t for t in q['terms'] if t.get('for') != 'T1']
        mutate(work, 'history.json', go)
        self.assertCode('[HISTORY-QUERY]', work, 'T1')

    def test_rebound_label_required_when_a_rebound_file_exists(self):
        work = self.new_work('valid_novp_rebound')
        self.scan_ok(work, 'intake', INTAKE_TERMS)
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))
        self.assertCode('[HISTORY-QUERY]', work, 'rebound')
        self.scan_ok(work, 'rebound', self.rebound_terms(work))
        self.assertNoCode('[HISTORY', work)

    def test_every_idea_needs_a_for_term(self):
        work = self.new_work('valid_novp_rebound')
        self.scan_ok(work, 'intake', INTAKE_TERMS)
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))
        self.scan_ok(work, 'rebound', self.rebound_terms(work)[:-1])
        self.assertCode('[HISTORY-QUERY]', work, 'N5')


class OverlapTest(HB):
    """HI16."""

    def test_fold_test_refused_without_citation(self):
        work = self.full_flow()
        probs = self.assertCode('[HISTORY-OVERLAP]', work, 'T2')
        text = ' '.join(p for p in probs if p.startswith('[HISTORY-OVERLAP]'))
        self.assertIn('results/test_softfold.md', text)
        self.assertIn('LESSONS.md', text)
        self.assertNotIn('T1', text)

    def test_tried_only_is_not_blocking(self):
        work = self.new_work()
        self.scan_ok(work, 'intake', [term('paper folding', 'CRADLE')])
        mutate(work, 'tests.json', lambda d: d['tests'][0].update(title='Seed variance of the paper folding baseline'))
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))
        self.assertTrue(any(e['verdict'] == 'tried' for e in self.entries(work)))
        self.assertNoCode('[HISTORY-OVERLAP]', work)

    def test_synonym_in_the_text_overlaps(self):
        work = self.new_work()
        self.scan_ok(work, 'intake', INTAKE_TERMS + [term('softfold', 'soft fold', 'FOLD')])
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))     # no `for` term on softfold
        self.assertNoCode('[HISTORY-OVERLAP]', work)
        self.set_fold_test(work, title='A pairwise soft-fold loss on the same folds')
        mutate(work, 'tests.json', lambda d: d['tests'][1]['decisive_intervention'].update(
            description='Compare the two losses on identical folds.'))
        self.assertCode('[HISTORY-OVERLAP]', work, 'T2')

    def test_for_term_declares_the_overlap(self):
        work = self.new_work()
        self.scan_ok(work, 'intake', INTAKE_TERMS)
        self.set_fold_test(work, title='A pairwise ordering loss on the same folds')
        mutate(work, 'tests.json', lambda d: d['tests'][1]['decisive_intervention'].update(
            description='Compare the two losses on identical folds.'))
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=True))      # `for` T2 on softfold
        self.assertCode('[HISTORY-OVERLAP]', work, 'T2')

    def test_generic_term_does_not_overlap_but_is_warned(self):
        write_files(self.proj, {'notes/pick.md': 'Tile packing rule: REJECTED.\n'})
        for generic, want in ((True, False), (False, True)):
            with self.subTest(generic=generic):
                work = self.new_work(name='hw%d' % generic)
                self.scan_ok(work, 'intake', [term('tile packing', generic=generic)])
                mutate(work, 'tests.json', lambda d: d['tests'][0].update(title='A tile packing backtest of title length'))
                self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))
                got = any(p.startswith('[HISTORY-OVERLAP]') for p in self.problems(work))
                self.assertEqual(got, want)
                warned = any('generic' in w for w in self.check.warnings(work))
                self.assertEqual(warned, generic)


class CitationTest(HB):
    """HI17."""

    def test_accepted_with_citation_and_justification(self):
        work = self.full_flow()
        self.attach(work, self.good_citations(work))
        self.assertEqual(self.problems(work), [])

    def test_defects_refused(self):
        entry_line = 'results/test_softfold.md:10'
        cases = {
            'unknown entry': {'entry': 'E9999'},
            'wrong line': {'cited': 'results/test_softfold.md:11'},
            'wrong file': {'cited': 'LESSONS.md:5'},
            'no citation': {'cited': None},
            'invented verdict': {'verdict_quoted': 'APPROVED FOR PRODUCTION'},
            'no verdict': {'verdict_quoted': None},
            'invented condition': {'reopen_condition': 'reopen whenever the team feels like it', 'reopen_condition_source': None},
            'source of the condition missing': {'reopen_condition_source': 'research/fold/NOPE.md:5'},
            'source line without the text': {'reopen_condition_source': 'research/fold/FOLD_PACKING_SUMMARY.md:3'},
            'source outside the project': {'reopen_condition_source': '../../etc/hosts:1'},
            'short justification': {'condition_met': 'it is fine'},
            'placeholder justification': {'condition_met': 'n/a'},
            'no justification': {'condition_met': None},
            'not kept': {'decision': 'removed'},
        }
        for name, over in cases.items():
            with self.subTest(name):
                self.fresh()
                work = self.full_flow()
                items = self.good_citations(work)
                for k, v in over.items():
                    if v is None:
                        items[0].pop(k, None)
                    else:
                        items[0][k] = v
                self.attach(work, items)
                probs = self.problems(work)
                self.assertTrue(any(p.startswith(('[HISTORY-CITE]', '[SCHEMA]')) for p in probs), (name, probs))
                self.assertTrue(probs, name)

    def test_empty_internal_history_is_not_a_citation(self):
        work = self.full_flow()
        self.attach(work, [])
        self.assertCode('[HISTORY-OVERLAP]', work, 'T2')

    def test_every_overlapping_file_must_be_cited(self):
        work = self.full_flow()
        self.attach(work, self.good_citations(work)[:1])
        self.assertCode('[HISTORY-OVERLAP]', work, 'LESSONS.md')

    def test_an_unrelated_entry_does_not_cover(self):
        work = self.full_flow()
        self.attach(work, [self.cite(work, 'notes/en_summary.txt', 'Corner trimming', verdict_quoted='REJECTED',
                                     reopen_condition='Reopen if the universe grows beyond 2000 tiles',
                                     reopen_condition_source=None)])
        self.assertCode('[HISTORY-OVERLAP]', work, 'results/test_softfold.md')

    def test_condition_of_the_entry_itself_needs_no_source(self):
        work = self.full_flow()
        own = self.entry(work, 'results/test_softfold.md', 'Verdict : -63')['reopen_condition']
        first = self.cite(work, 'results/test_softfold.md', 'Verdict : -63', reopen_condition=own,
                          reopen_condition_source=None)        # None drops the key
        self.attach(work, [first, self.good_citations(work)[1]])
        self.assertEqual(self.problems(work), [])

    def test_entry_without_any_condition_needs_a_source(self):
        work = self.full_flow()
        second = self.good_citations(work)[1]
        second.pop('reopen_condition_source')
        self.attach(work, [self.good_citations(work)[0], second])
        self.assertCode('[HISTORY-CITE]', work)

    def test_citations_are_not_sent_to_the_critic(self):
        work = self.full_flow()
        self.attach(work, self.good_citations(work))
        r = run_tool('pack_critique', work)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        pack = ''.join(p.read_text(encoding='utf-8') for p in (work / 'critique-pack').glob('*.md'))
        self.assertNotIn('FOLD_PACKING_SUMMARY', pack)
        self.assertNotIn('condition_met', pack)
        self.assertNotIn('internal_history', pack)
        self.assertNoCode('[HISTORY-LEAK]', work)


class ReboundTest(HB):
    """HI18."""

    def flow(self, base='valid_novp_rebound'):
        work = self.new_work(base)
        self.scan_ok(work, 'intake', INTAKE_TERMS)
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))
        mutate(work, 'rebound.json', lambda d: [i['test'].update(
            one_line='Replay the design with a SoftFold objective instead of the plainfold objective.')
            for i in d['ideas'] if i['id'] == 'N2'])
        self.scan_ok(work, 'rebound', self.rebound_terms(work, {'N2': FOLD_TERM}))
        return work

    def attach_idea(self, work, iid, items, fname='rebound.json'):
        def go(d):
            for i in d['ideas']:
                if i['id'] == iid:
                    i['internal_history'] = items
        mutate(work, fname, go)

    def test_idea_refused_then_accepted(self):
        work = self.flow()
        self.assertCode('[HISTORY-OVERLAP]', work, 'N2')
        self.attach_idea(work, 'N2', self.good_citations(work))
        self.assertNoCode('[HISTORY', work)
        self.assertEqual(self.problems(work), [])

    def test_idea_with_a_bad_citation_refused(self):
        work = self.flow()
        items = self.good_citations(work)
        items[0]['cited'] = 'results/test_softfold.md:3'
        self.attach_idea(work, 'N2', items)
        self.assertCode('[HISTORY-CITE]', work)

    def test_rebound_after_file_is_checked_too(self):
        work = self.new_work('valid_vp_rebound')
        self.scan_ok(work, 'intake', INTAKE_TERMS)
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))
        mutate(work, 'rebound_after.json', lambda d: d['ideas'][0]['test'].update(
            one_line='Replay the follow-up with a SoftFold objective on the same folds.'))
        bid = read_json(work / 'rebound_after.json')['ideas'][0]['id']
        self.scan_ok(work, 'rebound', self.rebound_terms(work, {bid: FOLD_TERM}))
        self.assertCode('[HISTORY-OVERLAP]', work, bid)
        self.attach_idea(work, bid, self.good_citations(work), 'rebound_after.json')
        self.assertNoCode('[HISTORY', work)


class RemovedTest(HB):
    """HI19."""

    def removed_flow(self):
        work = self.full_flow()
        self.set_fold_test(work, title='Seed variance of the baseline model on identical folds')
        mutate(work, 'tests.json', lambda d: d['tests'][1]['decisive_intervention'].update(
            description='Rerun the baseline with five seeds on identical folds.'))
        e = self.entry(work, 'results/test_softfold.md', 'Verdict : -63')
        # the host reruns history.py on the terms of the tests as they are now (the SoftFold test is gone)
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))
        return work, e

    def note(self, e, **over):
        return self.removal_note(e, **over)

    def test_removed_test_with_note_accepted(self):
        work, e = self.removed_flow()
        mutate(work, 'tests.json', lambda d: d.update(internal_history_removed=[self.note(e)]))
        self.assertEqual(self.problems(work), [])
        self.assertTrue(e['id'] not in [x['id'] for x in self.entries(work)])    # the note survives the new scan

    def test_removed_without_note_still_accepted(self):
        work, e = self.removed_flow()
        self.assertEqual(self.problems(work), [])

    def test_bad_notes_refused(self):
        work, e = self.removed_flow()
        for over in ({'cited': 'results/nope.md:1'}, {'cited': 'results/test_softfold.md:999'},
                     {'cited': '../../etc/hosts:1'}, {'why': 'no'}, {'what': ''}):
            with self.subTest(over=over):
                mutate(work, 'tests.json', lambda d: d.update(internal_history_removed=[self.note(e, **over)]))
                self.assertCode('[HISTORY-CITE]', work)

    def test_a_note_does_not_dispense_a_kept_test_from_citing(self):
        work = self.full_flow()
        e = self.entry(work, 'results/test_softfold.md', 'Verdict : -63')
        mutate(work, 'tests.json', lambda d: d.update(internal_history_removed=[self.note(e)]))
        self.assertCode('[HISTORY-OVERLAP]', work, 'T2')


class LeakTest(HB):
    """HI20: nothing found in the archives goes into a request."""

    def setUp(self):
        super().setUp()
        write_files(self.proj, {'notes/idea.md': 'We could replace our paper folding model for tile packing '
                                                 'with a learner. REJECTED.\n'})
        self.work_dir = self.new_work('valid_vp', 'hv')
        self.scan_ok(self.work_dir, 'intake', INTAKE_TERMS + [term('softfold', 'fold')])
        self.scan_ok(self.work_dir, 'tests', self.terms_for_tests(self.work_dir, fold=False))
        self.journal = self.fx / 'vp_prior_art' / 'state' / 'journal.jsonl'

    def add_query(self, query):
        entry = {'utc': '2026-11-14T13:31:00.000000+00:00', 'run': 'vp-2026-11-14-vp-prior-art', 'T': '2026-11-14',
                 'call': 'search-openalex', 'engine': 'openalex', 'query': query, 'n': 20, 'count': 0, 'excluded': 0,
                 'error': None, 'ids': []}
        with open(str(self.journal), 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def test_baseline_has_no_leak(self):
        self.assertEqual(self.problems(self.work_dir), [])

    def test_excerpt_in_a_gateway_query(self):
        self.add_query('Verdict : -63 % padding for SoftFold. CLASS' + E_CAPS + '. inspection-window')
        self.assertCode('[HISTORY-LEAK]', self.work_dir, 'results/test_softfold.md')

    def test_reopen_condition_in_a_query(self):
        self.add_query('R\u00e9ouverture conditionnelle des berceaux de papier dans research/fold/FOLD_PACKING_SUMMARY.md')
        self.assertCode('[HISTORY-LEAK]', self.work_dir)

    def test_archive_path_in_a_query(self):
        for make in (lambda: 'results/test_softfold.md ranking', lambda: str(self.proj) + ' ranking'):
            with self.subTest(make=make()):
                self.fresh()
                self.add_query(make())          # after fresh(): the project folder is a new temporary one
                self.assertCode('[HISTORY-LEAK]', self.work_dir)

    def test_idea_words_are_not_a_leak(self):
        self.add_query('paper folding tile packing soft fold softfold objective')
        self.add_query('replace our paper folding model for tile packing')   # also in the archives, and in the idea
        self.assertNoCode('[HISTORY-LEAK]', self.work_dir)

    def test_other_places(self):
        leaked = 'Verdict : -63 % padding for SoftFold. CLASS' + E_CAPS + '.'
        places = {
            'scope.md of the VP run': lambda: (self.fx / 'vp_prior_art' / 'scope.md').write_text(leaked, encoding='utf-8'),
            'prior_art.json searched': lambda: mutate(self.work_dir, 'prior_art.json', lambda d: d.update(
                searched='OpenAlex, query: ' + leaked)),
            'critique pack PROTOCOL.md': lambda: write_files(self.work_dir, {'critique-pack/PROTOCOL.md': '# P\n' + leaked}),
            'critique pack PROMPT.md': lambda: write_files(self.work_dir, {'critique-pack/PROMPT.md': leaked}),
        }
        for name, put in places.items():
            with self.subTest(name):
                self.fresh()
                put()
                self.assertCode('[HISTORY-LEAK]', self.work_dir)

    def rb_work(self):
        work = self.new_work('valid_novp_rebound', 'hr')
        self.scan_ok(work, 'intake', INTAKE_TERMS + [term('softfold', 'fold')])
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))
        self.scan_ok(work, 'rebound', self.rebound_terms(work))
        return work

    def test_rebound_query_and_scope(self):
        self.assertNoCode('[HISTORY-LEAK]', self.rb_work())
        leaked = 'Verdict : -63 % padding for SoftFold. CLASS' + E_CAPS + '.'
        for field in ('queries', 'scope'):
            with self.subTest(field=field):
                self.fresh()
                work = self.rb_work()

                def go(d):
                    pa = d['ideas'][0]['prior_art']
                    pa[field] = [leaked] if field == 'queries' else leaked
                mutate(work, 'rebound.json', go)
                self.assertCode('[HISTORY-LEAK]', work)

    def test_no_check_without_project_dirs(self):
        self.add_query('Verdict : -63 % padding for SoftFold. CLASS' + E_CAPS + '.')
        mutate(self.work_dir, 'intake.json', lambda d: d.pop('project_dirs'))
        self.assertNoCode('[HISTORY', self.work_dir)


class StepTest(HB):
    """HI24."""

    def test_history_step_recorded(self):
        work = self.full_flow(fold=False)
        r = run_tool('step', work, '--step', 'history')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        steps = read_json(work / 'run.json')['steps']
        self.assertIn('history', [s['step'] for s in steps])
        self.assertEqual(self.problems(work), [])
