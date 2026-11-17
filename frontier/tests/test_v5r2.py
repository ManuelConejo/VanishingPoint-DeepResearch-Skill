# SPDX-License-Identifier: Apache-2.0
"""Independent V5R2 guarantees: literal inventories, uncertain reuse and API consumers.

All drafts and journal rows here are handwritten, independent of prose_spans.
No network or model calls; the historical replay is never modified.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .helpers import FRONTIER, load_tool, mutate, read_json, run_tool, write_json
from .v2_common import V2


SHORT = ['Efficacit\xe9 : 90 %', 'Recall: 0.42 at k=50', 'Accuracy: 0.9',
         'Count: 7', 'F1: 0.8', 'n = 5', 'Budget: twenty']


class ShortClaimGuarantees(unittest.TestCase):
    def setUp(self):
        self.hy = load_tool('hybrid')

    def test_handwritten_inventory_keeps_short_claims_and_textual_leads(self):
        draft = ('# Accuracy: 0.9\n## Research leads\n90 %\n12 months\n---\n'
                 '- Efficacit\xe9 : 90 %\n1. Recall: 0.42 at k=50\nAccuracy: 0.9\n'
                 'Count: 7\nF1: 0.8\nn = 5\nBudget: twenty\n'
                 'Explore\nReplicate.\nAccuracy:   0.9\n')
        expected = SHORT + ['Explore', 'Replicate.']
        self.assertEqual(self.hy.draft_quotes(draft), expected)
        spans = self.hy.prose_spans(draft)
        self.assertEqual([draft[l:r] for l, r in spans], expected + ['Accuracy:   0.9'])
        # References are not bare numbers or unit fragments and must not vanish.
        identifier = 'arxiv:1234.56789'
        self.assertEqual(self.hy.draft_quotes(identifier), [identifier])
        rows = self.hy.analyse(identifier, [], {}, strict=True)
        self.assertEqual([(r['kind'], r['text']) for r in rows], [('identifier', identifier)])

    def test_short_quantitative_claims_reach_strict_analysis_and_exact_checks(self):
        for claim in SHORT:
            for prefix in ('', '- ', '2. '):
                with self.subTest(claim=claim, prefix=prefix):
                    data = {'recommendation.json': {'reason': claim}}
                    rows = self.hy.analyse(prefix + claim, [], data, strict=True)
                    self.assertEqual([r['text'] for r in rows], [claim])
                    self.assertEqual(rows[0]['covered_by'], [])
                    self.assertEqual(len(rows[0]['taken_up_in']), 1)
                    with tempfile.TemporaryDirectory() as tmp:
                        work = Path(tmp)
                        (work / 'free_draft.md').write_text(prefix + claim, encoding='utf-8')
                        data['draft_claims.json'] = {'claims': []}
                        problems = []
                        load_tool('r3check').check_hybrid(work, data, None, problems)
                        self.assertTrue(any('[DRAFT-UNMARKED]' in p for p in problems), problems)
                        data['draft_claims.json']['claims'] = [
                            {'id': 'D1', 'quote': claim, 'status': 'unverified_memory'}]
                        problems = []
                        load_tool('r3check').check_hybrid(work, data, None, problems)
                        self.assertTrue(any('[DRAFT-DECISIVE]' in p for p in problems), problems)

    def test_bare_numbers_units_and_headings_stay_out(self):
        for fragment in ('0.42', '90 %', '20 000', '12 months', '12 ms', '12 kg', '12ms', '12kg', '12months',
                         '1e3', '1.2e-3 kg', 'vingt', 'twenty percent', '12 mois', '% / kg', '...',
                         '## Efficacit\xe9 : 90 %', '- 90 %'):
            with self.subTest(fragment=fragment):
                self.assertEqual(self.hy.draft_quotes(fragment), [])
                self.assertEqual(self.hy.analyse(fragment, [], {}, strict=True), [])

    def test_numeric_coincidence_without_content_overlap_is_not_reuse(self):
        rows = self.hy.analyse('Accuracy: 90 %', [],
                               {'recommendation.json': {'reason': 'Budget: 90 %'}}, strict=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['taken_up_in'], [])
        self.assertEqual(rows[0]['possible_reuse_in'], [])

    def test_a_quote_prefix_of_a_larger_number_is_not_exact_reuse(self):
        rows = self.hy.analyse('Count: 7', [], {'recommendation.json': {'reason': 'Count: 70'}}, strict=True)
        self.assertEqual(rows[0]['taken_up_in'], [])
        self.assertEqual(rows[0]['possible_reuse_in'], [])

    def test_a_year_value_with_a_label_is_still_a_quantitative_claim(self):
        rows = self.hy.analyse('Records: 2024', [],
                               {'recommendation.json': {'reason': 'Records: 2024'}}, strict=True)
        self.assertEqual([r['text'] for r in rows], ['Records: 2024'])
        self.assertTrue(rows[0]['taken_up_in'])


class ReuseGuarantees(unittest.TestCase):
    def test_opposites_and_low_overlap_paraphrases_are_possible_not_exact(self):
        pairs = [
            ('20 essais sur 100 r\xe9ussissent', '20 essais sur 100 \xe9chouent'),
            ('The archive contains 100 independently labelled records for validation.',
             'Our collection has 100 records.'),
            ('Accuracy: 90 %', 'Accuracy was 90 %'),
            ('F1: 0.8', 'F1 was 0.8'),
            ('n = 5', 'The sample has n equal to 5'),
            ('Smith et al. (2019) found improved retrieval.',
             'Smith et al. (2019) found worse retrieval.'),
            ('The useful archive is arxiv:1234.56789.',
             'Avoid the obsolete archive arxiv:1234.56789.')]
        hy = load_tool('hybrid')
        for source, target in pairs:
            for status in ('unverified_memory', 'verified', 'removed'):
                with self.subTest(source=source, status=status):
                    claims = [{'id': 'D1', 'quote': source, 'status': status}]
                    data = {'draft_claims.json': {'claims': claims},
                            'recommendation.json': {'reason': target + ' unverified (memory)'}}
                    rows = hy.analyse(source, claims, data, strict=True)
                    self.assertTrue(rows)
                    self.assertFalse(any(r['taken_up_in'] for r in rows), rows)
                    self.assertTrue(any(r['possible_reuse_in'] for r in rows), rows)
                    with tempfile.TemporaryDirectory() as tmp:
                        work = Path(tmp)
                        (work / 'free_draft.md').write_text(source, encoding='utf-8')
                        diagnostics = []
                        load_tool('r3check').check_hybrid(work, data, None, diagnostics)
                        self.assertTrue(any('[DRAFT-REUSE?]' in p for p in diagnostics), diagnostics)
                        self.assertFalse(any('[DRAFT-DECISIVE]' in p or '[DRAFT-UNMARKED]' in p
                                             for p in diagnostics), diagnostics)

    def test_exact_and_partial_destinations_are_kept_separate(self):
        source = '20 essais sur 100 r\xe9ussissent'
        rows = load_tool('hybrid').analyse(source, [], {
            'recommendation.json': {'reason': source + ' unverified (memory)'},
            'tests.json': {'decision_rule': {'continue_if': '20 essais sur 100 \xe9chouent'}}}, strict=True)
        self.assertEqual([x['file'] for x in rows[0]['taken_up_in']], ['recommendation.json'])
        self.assertEqual([x['file'] for x in rows[0]['possible_reuse_in']], ['tests.json'])

    def test_legacy_taken_up_api_still_returns_triples(self):
        hy = load_tool('hybrid')
        source = 'The baseline improves accuracy by 12.5% on frozen data.'
        cand = hy.candidates(source)[0]
        strings = hy.input_strings({'recommendation.json': {'reason': source}})
        self.assertEqual(hy.taken_up(cand, source, strings), [('recommendation.json', 'reason', source)])
        self.assertTrue(hy.analyse(source, [], {'recommendation.json': {'reason': source}})[0]['taken_up_in'])


class PartialIdentifierGuarantees(unittest.TestCase):
    def test_partial_ids_preserve_hits_with_one_separately_counted_mark(self):
        tool = load_tool('overlap')
        known = 'arxiv:1234.56789'
        rows = [
            {'call': 'search-arxiv', 'query': 'partial one', 'ids': [known, None], 'error': 'truncated'},
            {'call': 'search-arxiv', 'query': 'partial two', 'ids': ['', known, 4, {}]},
            {'call': 'search-arxiv', 'query': 'unknown one', 'ids': [None], 'error': 'timeout'},
            {'call': 'search-arxiv', 'query': 'unknown two', 'ids': 'bad'},
            {'call': 'search-arxiv', 'query': 'empty', 'ids': [], 'count': 0},
            {'call': 'search-arxiv', 'query': 'known', 'ids': [known]}]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            path = work / 'vp/state/journal.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text('\n' + ''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            data = {'intake.json': {'vp': {'runs': {'prior_art': 'vp'}}},
                    'prior_art.json': {'closest_work': [{'ref': {'id': known}, 'title': 'Known archive',
                                                       'overlap_dimensions': ['data'],
                                                       'what_differs': 'Different evaluation task'}]}}
            ledger = tool.derive(work, data)
            problems, warnings = [], []
            load_tool('v4check').run(work, data, problems, warnings)
        self.assertEqual(problems, [])
        queries = ledger['queries']
        self.assertEqual([q['returned_ids'] for q in queries], [[known], [known], None, None, [], [known]])
        self.assertEqual([q['ids_complete'] for q in queries], [False, False, False, False, True, True])
        self.assertEqual([q['journal_line'] for q in queries], list(range(2, 8)))
        self.assertEqual([q['query'] for q in queries], [r['query'] for r in rows])
        self.assertEqual([q['error'] for q in queries], [r.get('error') for r in rows])
        self.assertEqual([len(q['overlaps']) for q in queries], [1, 1, 0, 0, 0, 1])
        self.assertEqual(ledger['overlap_occurrences'], 3)
        self.assertEqual(ledger['unattributed_overlaps'], [])
        self.assertFalse(ledger['complete'])
        self.assertEqual(len(ledger['issues']), 1)
        issue = ledger['issues'][0]
        self.assertIn('2 fully unknown', issue)
        self.assertIn('2 partial', issue)
        self.assertIn('prior_art: 2', issue)
        self.assertEqual(len([w for w in warnings if issue in w]), 1)
        report = '\n'.join(tool.report_lines(ledger))
        self.assertIn('returned IDs: ' + known + ' (incomplete)', report)
        self.assertEqual(report.count('returned IDs: unknown'), 2)


class ConsumerGuarantees(V2):
    def test_v2_stub_and_scan_keep_short_items_with_existing_json_shape(self):
        work = self.to_v2()
        draft = '# Notes\n' + '\n'.join(SHORT + ['Explore', 'Replicate.', '12 months', '90 %']) + '\n'
        (work / 'free_draft.md').write_text(draft, encoding='utf-8')
        (work / 'draft_claims.json').unlink(missing_ok=True)
        result = run_tool('hybrid', 'stub', work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        stub = read_json(work / 'draft_claims.json')
        self.assertEqual(stub['draft_sha256'], hashlib.sha256(draft.encode()).hexdigest())
        self.assertEqual(stub['claims'], [
            {'id': 'D%d' % i, 'quote': q, 'status': 'unverified_memory'}
            for i, q in enumerate(SHORT + ['Explore', 'Replicate.'], 1)])
        result = run_tool('hybrid', 'scan', work, '--json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([r['text'] for r in json.loads(result.stdout)['candidates']], SHORT)
        priorities = run_tool('hybrid', 'priority', work)
        self.assertEqual(priorities.returncode, 0, priorities.stderr)
        self.assertEqual(len(json.loads(priorities.stdout)), 9)
        submitted = run_tool('hybrid', 'submit', work, '--run', 'prior_art',
                             '--claims', 'D1', 'D2', 'D3', 'D4', 'D5',
                             '--sources', 'S1', 'S1', 'S1', 'S1', 'S1',
                             '--why', 'These short claims decide the validation target and budget.')
        self.assertEqual(submitted.returncode, 0, submitted.stdout + submitted.stderr)
        stub = read_json(work / 'draft_claims.json')
        self.assertEqual([c['quote'] for c in stub['claims']], SHORT + ['Explore', 'Replicate.'])
        self.assertTrue(all(c.get('verification') for c in stub['claims'][:5]))

    def test_possible_reuse_is_advisory_and_visible_in_report(self):
        work = self.to_v2()
        source = ('The archive contains 100 independently labelled records for validation. ' +
                  'These working notes describe an uncertain memory to check before choosing a test. ' * 2)
        (work / 'free_draft.md').write_text(source, encoding='utf-8')
        h = hashlib.sha256(source.encode()).hexdigest()
        write_json(work / 'draft_claims.json', {'draft_sha256': h, 'claims': [
            {'id': 'D1', 'quote': source.split(' These')[0], 'status': 'unverified_memory'}]})
        mutate(work, 'run.json', lambda d: d['steps'].insert(0, {
            'step': 'free_draft', 'utc': '2026-11-14T08:50:00Z', 'duration_s': 'unknown',
            'cost_usd': 'unknown', 'sha256': h}))
        mutate(work, 'recommendation.json', lambda d: d.update(reason='Our collection has 100 records.'))
        problems, warnings = self.check.run_all(work, with_card=False)
        self.assertEqual(problems, [])
        self.assertTrue(any(w.startswith('mark: [DRAFT-REUSE?]') for w in warnings), warnings)
        priorities = load_tool('hybrid').priority(work)
        self.assertEqual(priorities[0]['impact'], 3)
        self.assertEqual(priorities[0]['taken_up_in'], [])
        self.assertEqual(priorities[0]['possible_reuse_in'], ['recommendation.json'])
        result = run_tool('card', work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = (work / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertIn('[DRAFT-REUSE?]', report)

    def test_card_stdout_positions_and_docs_agree(self):
        work = self.to_v2()
        result = run_tool('card', work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        card, report = map(Path, result.stdout.splitlines()[:2])
        self.assertEqual(card, (work / 'IDEA-CARD.md').resolve())
        self.assertEqual(report, (work / 'IDEA-REPORT.md').resolve())
        self.assertTrue(card.is_file() and report.is_file())
        self.assertIn('LAST command', result.stdout.splitlines()[-1])
        for filename in ('README.md', 'SKILL.md'):
            text = (FRONTIER / filename).read_text(encoding='utf-8')
            self.assertIn('first two lines', text)
            self.assertIn('reminder', text)
        help_result = run_tool('card', '--help')
        self.assertIn('first two lines', help_result.stdout)


class LabelledUnitNameTest(unittest.TestCase):
    """Terra v5r2: a parameter named like a unit ("m = 5") is a claim; a bare unit fragment ("5 m") is not."""

    def test_unit_named_parameters_are_kept(self):
        hy = load_tool('hybrid')
        draft = 'm = 5\ns = 3\nk <= 50\n5 m\n12 ms\n42\n'
        self.assertEqual(hy.draft_quotes(draft), ['m = 5', 's = 3', 'k <= 50'])


class InvocationPathTest(V2):
    """A card assembled with an absolute path must not look stale when checked with '.' (real run, 15/11)."""

    def test_card_name_does_not_depend_on_the_invocation_path(self):
        import os
        work = self.to_v2()
        card = load_tool('card')
        a = card.render(Path(work).resolve(), full=True)
        here = os.getcwd()
        try:
            os.chdir(str(work))
            b = card.render(Path('.'), full=True)
        finally:
            os.chdir(here)
        self.assertEqual(a, b)
        self.assertIn(Path(work).resolve().name, a)

