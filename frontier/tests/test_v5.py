# SPDX-License-Identifier: Apache-2.0
"""V5 guarantees: synthetic packing component run, plus independent boundary cases.

No network or model calls. The synthetic source fixture is never modified.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from .helpers import FIXTURES, FRONTIER, load_tool, mutate, read_json, run_tool
from .v2_common import V2


REPLAY = FIXTURES / 'synthetic_packing_run'


def replay_data():
    return {p.name: read_json(p) for p in REPLAY.glob('*.json')}


class DraftGuarantees(unittest.TestCase):
    def setUp(self):
        self.hy = load_tool('hybrid')

    def marks(self, draft, claims, data):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / 'free_draft.md').write_text(draft, encoding='utf-8')
            data = dict(data, **{'draft_claims.json': {'claims': claims}})
            problems = []
            load_tool('r3check').check_hybrid(work, data, None, problems)
            return problems

    def test_synthetic_run_has_no_fragment_items_or_false_draft_marks(self):
        data = replay_data()
        draft = (REPLAY / 'free_draft.md').read_text(encoding='utf-8')
        claims = data['draft_claims.json']['claims']
        self.assertEqual(len(self.hy.draft_quotes(draft)), 25)
        rows = self.hy.analyse(draft, claims, data, strict=True)
        self.assertFalse([r['text'] for r in rows if r['text'] in ('000', '12')])
        # Partial matches are now explicitly uncertain, never exact-reuse errors.
        marks = self.marks(draft, claims, data)
        self.assertFalse([m for m in marks if not m.startswith('[DRAFT-REUSE?]')], marks)

    def test_numeric_and_markdown_fragments_never_become_claim_items(self):
        for fragment in ('000', '12', '12.', '12.5%', '20 000', '20\u00a0000',
                         '20\u202f000', '1,000', '1.000', '12 months', 'twenty',
                         '---', '...', '1.', '## 12', '- 000', '2. 12'):
            with self.subTest(fragment=fragment):
                self.assertEqual(self.hy.draft_quotes(fragment), [])
                self.assertEqual(self.hy.analyse(fragment, [], {}, strict=True), [])

    def test_full_numeric_claims_are_tracked_and_marks_follow_coverage(self):
        for amount in ('20 000', '20\u00a0000', '20\u202f000', '1,000', '12',
                       '12.5%', '4,5', 'sixty'):
            claim = 'The frozen archive contains %s usable records for validation.' % amount
            for prefix in ('', '- ', '1. '):
                with self.subTest(amount=amount, prefix=prefix):
                    draft = prefix + claim + '\n'
                    data = {'tests.json': {'tests': [{'decision_rule': {'continue_if': claim}}]}}
                    rows = self.hy.analyse(draft, [], data, strict=True)
                    self.assertEqual([r['text'] for r in rows], [claim])
                    self.assertTrue(rows[0]['taken_up_in'])
                    self.assertTrue(any('[DRAFT-UNMARKED]' in m for m in self.marks(draft, [], data)))
                    claims = [{'id': 'D1', 'quote': claim, 'status': 'unverified_memory'}]
                    self.assertTrue(any('[DRAFT-DECISIVE]' in m for m in self.marks(draft, claims, data)))
                    marked = copy.deepcopy(data)
                    marked['tests.json']['tests'][0]['decision_rule']['continue_if'] += ' unverified (memory)'
                    self.assertEqual(self.marks(draft, claims, marked), [])

    def test_same_number_and_generic_words_do_not_reuse_a_claim(self):
        draft = 'The archive contains 20 000 scientific articles from independent authors.'
        data = {'recommendation.json': {'reason': 'Inspect 1 000 scientific articles for the baseline.'}}
        self.assertFalse(any(r['taken_up_in'] for r in self.hy.analyse(draft, [], data, strict=True)))

    def test_qualitative_claims_survive_and_citation_alone_does_not_cover_claim(self):
        claim = 'Smith et al. (2019) found that diverse detectors outperform citation rankings.'
        draft = '- ' + claim + '\n- Compare independent controls before choosing a detector.\n'
        self.assertEqual(self.hy.draft_quotes(draft), [claim, 'Compare independent controls before choosing a detector.'])
        data = {'recommendation.json': {'reason': claim}}
        claims = [{'id': 'D1', 'quote': 'Smith et al. (2019)', 'status': 'unverified_memory'}]
        self.assertTrue(any('[DRAFT-UNMARKED]' in m for m in self.marks(draft, claims, data)))


class OverlapGuarantees(unittest.TestCase):
    def test_synthetic_run_counts_unknowns_once_and_keeps_every_query(self):
        tool = load_tool('overlap')
        data = replay_data()
        ledger = tool.derive(REPLAY, data)
        unknown = [q for q in ledger['queries'] if q['returned_ids'] is None]
        self.assertEqual(len(unknown), 19)
        self.assertEqual(sum(q['run'] == 'prior_art' for q in unknown), 11)
        self.assertTrue(all(q['error'] for q in unknown))
        issues = [i for i in ledger['issues'] if 'returned identifiers unknown' in i]
        self.assertEqual(len(issues), 1)
        self.assertIn('19 queries', issues[0])
        self.assertIn('prior_art: 11', issues[0])
        self.assertFalse(ledger['complete'])
        sources, _, _ = tool.sources(REPLAY, data)
        expected = [(s, n, r) for s in sources for n, r in tool.journal(s['path'])[0] if tool.is_search(r)]
        self.assertEqual(ledger['query_count'], len(expected))
        for q, (source, number, row) in zip(ledger['queries'], expected):
            self.assertEqual(q['journal_line'], number)
            self.assertEqual(q['query'], row.get('query', ''))
            self.assertEqual(q['error'], row.get('error'))
            if all(isinstance(i, str) and i for i in row.get('ids', [None])):
                self.assertEqual(q['returned_ids'], row['ids'])
            else:
                self.assertEqual(q['overlaps'], [])
        report = '\n'.join(tool.report_lines(ledger))
        self.assertEqual(report.count('returned IDs: unknown'), 19)
        self.assertEqual(report.count('[OVERLAP-LEDGER] ' + issues[0]), 1)
        problems, warnings = [], []
        load_tool('v4check').run(REPLAY, data, problems, warnings)
        self.assertEqual(problems, [])
        marks = [w for w in warnings if 'returned identifiers unknown' in w]
        self.assertEqual(len(marks), 1)
        self.assertTrue(marks[0].startswith('mark: [OVERLAP-LEDGER]'))

    def test_empty_missing_malformed_and_partially_known_ids(self):
        tool = load_tool('overlap')
        rows = [{'call': 'search-arxiv', 'query': 'q', 'ids': [], 'count': 0},
                {'call': 'search-arxiv', 'query': 'q', 'ids': ['arxiv:1234.56789']},
                {'call': 'search-arxiv', 'query': 'q'},
                {'call': 'search-arxiv', 'query': 'q', 'ids': [None]},
                {'call': 'search-arxiv', 'query': 'q', 'ids': [], 'count': 2},
                {'call': 'search-arxiv', 'query': 'q', 'ids': ['arxiv:1234.56789', None]}]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            path = work / 'vp' / 'state' / 'journal.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            data = {'intake.json': {'vp': {'runs': {'prior_art': 'vp'}}}, 'prior_art.json': {}}
            ledger = tool.derive(work, data)
        self.assertEqual([q['returned_ids'] for q in ledger['queries']],
                         [[], ['arxiv:1234.56789'], None, None, None, ['arxiv:1234.56789']])
        self.assertEqual(len(ledger['issues']), 1)
        self.assertIn('4 queries', ledger['issues'][0])
        self.assertIn('3 fully unknown', ledger['issues'][0])
        self.assertIn('1 partial', ledger['issues'][0])


class CardLastGuarantees(V2):
    def test_numeric_only_draft_does_not_get_a_fabricated_stub_claim(self):
        work = self.to_v2()
        (work / 'draft_claims.json').unlink(missing_ok=True)
        (work / 'free_draft.md').write_text('20 000\n12 months\n', encoding='utf-8')
        result = run_tool('hybrid', 'stub', work)
        self.assertIn('no prose claims', result.stdout + result.stderr)
        self.assertFalse((work / 'draft_claims.json').exists())
        result = run_tool('hybrid', 'scan', work, '--json')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['candidates'], [])

    def test_card_paths_then_last_command_reminder(self):
        work = self.to_v2()
        result = run_tool('card', work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:2], [str((work / n).resolve()) for n in ('IDEA-CARD.md', 'IDEA-REPORT.md')])
        self.assertIn('LAST command', lines[-1])
        self.assertIn('rerun card.py', lines[-1])
        self.assertIn('edit', lines[-1])

    def test_edit_still_reports_stale_and_regeneration_clears_it(self):
        work = self.to_v2()
        self.assertEqual(run_tool('card', work).returncode, 0)
        mutate(work, 'recommendation.json', lambda d: d.update(reason='Run the first cheap test to resolve the remaining uncertainty.'))
        problems, _ = self.check.run_all(work)
        self.assertTrue(any('[REPORT-STALE]' in p for p in problems))
        self.assertEqual(run_tool('card', work).returncode, 0)
        self.assertEqual(self.check.run_all(work)[0], [])
        report = work / 'IDEA-REPORT.md'
        report.write_text(report.read_text() + '\nHand edit\n', encoding='utf-8')
        self.assertTrue(any('[REPORT-STALE]' in p for p in self.check.run_all(work)[0]))

    def test_skill_explicitly_requires_last_command_after_every_edit(self):
        text = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('card.py is the LAST command of a run', text)
        self.assertIn('After any later edit', text)
        order = text.split('**Final order**', 1)[1].split('\n\n', 1)[0]
        self.assertNotIn('check.py` one last time', order)
