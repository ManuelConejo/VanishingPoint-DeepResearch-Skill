# SPDX-License-Identifier: Apache-2.0
"""V4 guarantees: synthetic packing inputs, synthetic journals, no network or model."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .helpers import FRONTIER, load_tool, read_json, write_json, run_tool, mutate
from .v2_common import V2

# V5: the synthetic packing run supplies the component inputs.
ENTREES = FRONTIER / 'tests' / 'fixtures' / 'synthetic_packing_run'


def replay_data():
    """Synthetic inputs adapted to the synthetic three-role receipt contract.

    The supplied run has only two predictions per test and ranks T2 first.
    Select T1, add an explicit synthetic H2, and retain three papers for these
    component tests. test_v5 uses the unmodified synthetic inputs instead.
    """
    data = {'tests.json': read_json(ENTREES / 'tests.json'),
            'critique.json': read_json(ENTREES / 'critique.json'),
            'prior_art.json': read_json(ENTREES / 'prior_art.json'),
            'intake.json': {'vp': {'mode': 'vp', 'runs': {'prior_art': 'vp-main'}}}}
    data['tests.json']['ranking']['order'] = ['T1', 'T2', 'T3']
    t = data['tests.json']['tests'][0]
    t['predictions'].insert(1, dict(t['predictions'][0], hypothesis='H2',
                                  direction='Synthetic corner insert gives an intermediate intact-tile gain.', interval=[0.04, 0.2]))
    t['competing_hypotheses'] = ['H1', 'H2', 'R1']
    data['prior_art.json']['closest_work'] = data['prior_art.json']['closest_work'][:3]
    return data


def receipt(data, decision='revised'):
    t = next(t for t in data['tests.json']['tests'] if t['id'] == data['tests.json']['ranking']['order'][0])
    # H0 is the null role; replay's existing R1 remains unchanged.
    return {'version': 1, 'test': t['id'], 'critique_item': 3,
            'weakest_inference': 'The felt-sleeve and paper-cradle predictions overlap without a separate corner-scuff observation.',
            'retrieval': {'not_needed': 'The missing corner-scuff contrast is specified in the packing plan; no external fact is needed.'},
            'decision': decision, 'reason': 'Count corner scuffs separately to distinguish the overlapping protection bands.',
            'before': 'Compare intact-tile gain only', 'after': 'Compare intact-tile gain and preregistered corner-scuff count',
            'predictions': {role: copy.deepcopy(t['predictions'][i]) for i, role in enumerate(('H1', 'H2', 'H0'))}}


class V4Pure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()  # standard TMPDIR: tests must not depend on a work folder
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.data = replay_data()

    def journal(self, run='vp-main', rows=None):
        # Synthetic attribution, not a reconstruction of the unavailable replay run.
        rows = rows if rows is not None else [
            {'call': 'search-openalex', 'query': 'synthetic tile packing',
             'ids': [self.data['prior_art.json']['closest_work'][0]['ref']['id']], 'error': None}]
        p = self.work / run / 'state' / 'journal.jsonl'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        return p

    def marks(self):
        p, w = [], []
        load_tool('v4check').run(self.work, self.data, p, w)
        self.assertFalse(p, 'V4 methodological gaps must remain marks in every format')
        return '\n'.join(w)

    def ledger(self):
        return load_tool('overlap').derive(self.work, self.data)

    def test_replay_really_exposes_the_gap_not_another_critic(self):
        card = (ENTREES / 'IDEA-CARD.md').read_text(encoding='utf-8')
        report = (ENTREES / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertEqual(len(card.splitlines()), 80)
        self.assertIn('false_discrimination', report)
        self.assertEqual(self.data['critique.json']['items'][3]['category'], 'underpowered')
        self.assertIn('effect 0.15', self.data['critique.json']['items'][3]['text'])
        self.assertIn('[REVISION]', self.marks())

    def test_revision_and_no_change_are_accepted(self):
        for decision in ('revised', 'no change'):
            with self.subTest(decision=decision):
                r = receipt(self.data, decision)
                if decision == 'no change':
                    for k in ('before', 'after'):
                        r.pop(k)
                self.data['test_revision.json'] = r
                self.assertNotIn('[REVISION]', self.marks())

    def test_no_vp_requires_explained_skip_not_fabricated_search(self):
        self.data['intake.json']['vp'] = {'mode': 'none'}
        self.data['test_revision.json'] = receipt(self.data)
        self.assertNotIn('[REVISION]', self.marks())
        self.data['test_revision.json']['retrieval'] = {'run': 'gap', 'query': 'corner scuffs'}
        self.assertIn('[REVISION]', self.marks())

    def test_only_deciding_test_weakness_requires_receipt(self):
        self.data['critique.json']['items'] = [self.data['critique.json']['items'][5]]  # T2 only
        self.assertNotIn('[REVISION]', self.marks())
        self.data['critique.json']['items'][0]['test'] = 'all'
        self.assertIn('[REVISION]', self.marks())

    def test_focused_receipt_cannot_be_a_list_or_target_another_test_or_item(self):
        good = receipt(self.data)
        cases = [[], [good, good], dict(good, test='T2'), dict(good, critique_item=0),
                 dict(good, critique_item=True), dict(good, weakest_inference=' '),
                 dict(good, reason='tbd'), dict(good, decision='no change', reason=' ')]
        for bad in cases:
            with self.subTest(bad=bad):
                self.data['test_revision.json'] = bad
                self.assertIn('[REVISION]', self.marks())

    def test_predictions_need_three_explicit_distinct_roles_and_match_current_test(self):
        good = receipt(self.data)
        for mutation in ('missing', 'drift', 'same', 'unchanged', 'empty'):
            r = copy.deepcopy(good)
            if mutation == 'missing':
                r['predictions'].pop('H0')
            elif mutation == 'drift':
                r['predictions']['H1']['interval'] = [.7, .9]
            elif mutation == 'same':
                r['predictions']['H0'] = r['predictions']['H1']
            elif mutation == 'unchanged':
                r['after'] = r['before']
            else:
                r['predictions']['H2']['direction'] = ''
            self.data['test_revision.json'] = r
            self.assertIn('[REVISION]', self.marks())

    def test_exactly_one_targeted_search_not_a_hidden_loop(self):
        self.data['intake.json']['vp']['runs']['gap'] = 'vp-gap'
        r = receipt(self.data)
        r['retrieval'] = {'run': 'gap', 'query': 'corner scuff contrast'}
        self.data['test_revision.json'] = r
        search = {'call': 'search-openalex', 'query': 'corner scuff contrast', 'ids': []}
        self.journal('vp-gap', [search, {'call': 'read', 'query': 'a source'}])
        self.assertNotIn('[REVISION]', self.marks())
        for rows in ([search, search], [], [dict(search, query='unrelated')]):
            self.journal('vp-gap', rows)
            self.assertIn('[REVISION]', self.marks())
        self.journal('vp-gap', [search])
        r['retrieval']['not_needed'] = 'Cannot both skip and search for the gap.'
        self.assertIn('[REVISION]', self.marks())

    def test_revision_schema_is_small_and_validates_replay_role_mapping(self):
        schema = read_json(FRONTIER / 'schemas' / 'test_revision.json')
        validate = load_tool('schema_lite').validate
        self.assertEqual(validate(receipt(self.data), schema), [])
        self.assertTrue(validate([receipt(self.data)], schema))
        self.assertTrue(validate(dict(receipt(self.data), versions=[]), schema))

    def test_join_is_per_query_not_all_cited_papers(self):
        closest = self.data['prior_art.json']['closest_work']
        closest[0]['overlap_dimensions'] = ['problem', 'method']
        self.journal(rows=[{'call': 'search-openalex', 'query': 'first', 'ids': [closest[0]['ref']['id']]},
                           {'call': 'search-code', 'query': 'second', 'ids': ['github:owner/tool']},
                           {'call': 'read', 'query': 'not a search', 'ids': [closest[1]['ref']['id']]}])
        ledger = self.ledger()
        self.assertEqual(ledger['query_count'], 2)
        self.assertEqual(len(ledger['queries'][0]['overlaps']), 1)
        hit = ledger['queries'][0]['overlaps'][0]
        self.assertEqual(hit['difference'], closest[0]['what_differs'])
        self.assertEqual(hit['dimensions'], ['problem', 'method'])
        self.assertEqual(ledger['queries'][1]['overlaps'], [])
        self.assertEqual(len(ledger['unattributed_overlaps']), 2)
        self.assertEqual(ledger['overlap_count'], 3)

    def test_all_queries_including_repeated_failed_empty_calls(self):
        self.journal(rows=[{'call': 'search-code', 'query': 'same', 'ids': []},
                           {'call': 'search-code', 'query': 'same', 'ids': [], 'error': 'credential_missing'},
                           {'call': 'search-arxiv', 'query': 'zero', 'ids': []}])
        ledger = self.ledger()
        self.assertEqual(ledger['query_count'], 3)
        self.assertEqual(ledger['queries'][1]['error'], 'credential_missing')
        self.assertEqual([q['journal_line'] for q in ledger['queries']], [1, 2, 3])
        self.assertEqual(ledger['queries'][2]['returned_ids'], [])

    def test_citation_queries_and_additional_registered_prior_art_runs_are_kept(self):
        self.journal(rows=[{'call': 'citing', 'query': 'doi:10.1234/seed', 'ids': []},
                           {'call': 'references', 'query': 'doi:10.1234/seed', 'ids': []}])
        self.data['intake.json']['vp']['runs']['prior_art_followup'] = 'vp-followup'
        self.journal('vp-followup', [{'call': 'search-arxiv', 'query': 'followup', 'ids': []}])
        self.assertEqual(self.ledger()['query_count'], 3)

    def test_empty_ids_with_positive_count_are_unknown(self):
        self.journal(rows=[{'call': 'search-code', 'query': 'tool', 'ids': [], 'count': 3}])
        self.assertIsNone(self.ledger()['queries'][0]['returned_ids'])
        self.assertFalse(self.ledger()['complete'])

    def test_missing_and_malformed_journals_are_unknown_not_zero_coverage(self):
        for content in (None, '{broken\n'):
            if content:
                self.journal().write_text(content, encoding='utf-8')
            ledger = self.ledger()
            self.assertFalse(ledger['complete'])
            self.assertTrue(ledger['issues'])
            self.assertIn('[OVERLAP-LEDGER]', self.marks())

    def test_missing_returned_ids_are_unknown_and_never_attributed(self):
        self.journal(rows=[{'call': 'search-openalex', 'query': 'unknown', 'count': 3}])
        ledger = self.ledger()
        self.assertIsNone(ledger['queries'][0]['returned_ids'])
        self.assertEqual(ledger['queries'][0]['overlaps'], [])
        self.assertFalse(ledger['complete'])

    def test_aliases_deduplicate_paths_but_identical_independent_journals_count(self):
        self.journal()
        pa = self.data['prior_art.json']
        pa['closest_work'][1]['ref']['run'] = 'alias'
        self.data['intake.json']['vp']['runs']['alias'] = str(self.work / 'vp-main')
        self.assertEqual(self.ledger()['query_count'], 1)
        self.data['intake.json']['vp']['runs']['alias'] = 'vp-other'
        self.journal('vp-other')
        self.assertEqual(self.ledger()['query_count'], 2)

    def test_research_matter_and_neighbour_queries_share_the_ledger(self):
        self.journal()
        for name in ('research', 'matter', 'vp-neighbour'):
            self.journal(name, [{'call': 'search-code', 'query': name, 'ids': []}])
        self.data['intake.json']['vp']['runs']['neighbour'] = 'vp-neighbour'
        self.data['rebound.json'] = {'ideas': [{'id': 'N1', 'prior_art': {'vp_run': 'neighbour', 'closest_work': []}}]}
        self.assertEqual(self.ledger()['query_count'], 4)

    def test_identifier_normalization_and_software_overlaps(self):
        pa = self.data['prior_art.json']
        pa['closest_work'] = [{'ref': {'id': 'doi:10.1234/ABC', 'run': 'prior_art'},
                               'title': 'Method paper', 'what_differs': 'A different evaluation setting.',
                               'overlap_dimensions': ['setting']},
                              {'ref': {'id': 'github:Owner/Tool', 'run': 'prior_art'}, 'kind': 'software',
                               'title': 'An existing tool', 'what_differs': 'No prospective data freeze.',
                               'overlap_dimensions': ['data', 'claim']}]
        self.journal(rows=[{'call': 'search-code', 'query': 'q',
                            'ids': ['https://doi.org/10.1234/abc', 'github:owner/tool']}])
        self.assertEqual(len(self.ledger()['queries'][0]['overlaps']), 2)
        self.assertNotIn('[OVERLAP-LEDGER]', self.marks())

    def test_missing_difference_or_dimension_is_marked_never_inferred(self):
        for field in ('what_differs', 'overlap_dimensions'):
            self.data = replay_data()
            for c in self.data['prior_art.json']['closest_work']:
                c['overlap_dimensions'] = ['problem']
            self.journal(rows=[{'call': 'search-arxiv', 'query': 'q',
                                'ids': [c['ref']['id'] for c in self.data['prior_art.json']['closest_work']]}])
            self.data['prior_art.json']['closest_work'][0][field] = '' if field == 'what_differs' else ['novelty']
            self.assertIn('[OVERLAP-LEDGER]', self.marks())
            self.assertEqual(self.ledger()['overlap_count'], 3)

    def test_no_vp_reports_not_checked_without_a_novelty_boolean(self):
        self.data['intake.json']['vp'] = {'mode': 'none'}
        ledger = self.ledger()
        self.assertFalse(ledger['complete'])
        self.assertIn('not checked', json.dumps(ledger))
        self.assertNotIn('novelty', ledger)
        self.assertNotIn('novel', ledger)

    def test_cli_is_deterministic_and_preserves_source_inputs(self):
        self.journal()
        for name, value in self.data.items():
            write_json(self.work / name, value)
        original = (self.work / 'prior_art.json').read_bytes()
        result = run_tool('overlap', self.work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        saved = (self.work / 'overlap_ledger.json').read_bytes()
        self.assertEqual(read_json(self.work / 'overlap_ledger.json'), self.ledger())
        self.assertEqual(run_tool('overlap', self.work).returncode, 0)
        self.assertEqual(saved, (self.work / 'overlap_ledger.json').read_bytes())
        self.assertEqual(original, (self.work / 'prior_art.json').read_bytes())
        self.data['overlap_ledger.json'] = dict(self.ledger(), query_count=900)
        self.assertIn('[OVERLAP-LEDGER]', self.marks())


class V4Integration(V2):
    def test_synthetic_replay_with_both_new_lines_stays_within_page(self):
        w = self.to_v2()
        d = replay_data()
        write_json(w / 'tests.json', d['tests.json'])
        write_json(w / 'prior_art.json', d['prior_art.json'])
        write_json(w / 'test_revision.json', receipt(d))
        # Rendering only: the component fixture does not provide full VP runs.
        # Use the invented critic wording without claiming a new critique or search.
        cr = read_json(w / 'critique.json')
        cr.update(d['critique.json'])
        for item in cr['items']:
            item['response'] = {'action': 'open', 'note': 'Replay objection remains open for this rendering fixture.'}
        write_json(w / 'critique.json', cr)
        card_tool = load_tool('card')
        card = card_tool.render(w)
        report = card_tool.render(w, full=True)
        self.assertLessEqual(len(card.splitlines()), 80)
        self.assertEqual(sum(l.startswith('Test revision:') for l in card.splitlines()), 1)
        self.assertEqual(sum(l.startswith('Overlap ledger:') for l in card.splitlines()), 1)
        self.assertIn('Compare intact-tile gain only ->', card)
        for prediction in receipt(d)['predictions'].values():
            self.assertIn(prediction['direction'], report)
        self.assertIn(d['prior_art.json']['closest_work'][0]['what_differs'], card)

    def test_unresolved_difference_is_a_mark_in_older_formats_too(self):
        for version in (1, 2):
            w = self.work() if version == 1 else self.to_v2()
            for missing in (False, True):
                def unresolved(d):
                    c = d['closest_work'][0]
                    c.pop('what_differs', None) if missing else c.update(what_differs='')
                mutate(w, 'prior_art.json', unresolved)
                p, marks = self.check.run_all(w, with_card=False)
                self.assertFalse(p, p)
                self.assertTrue(any('[OVERLAP-LEDGER]' in s and 'difference' in s for s in marks))

    def test_new_methodological_omissions_are_advisory_in_legacy_and_v2(self):
        for version in (1, 2):
            w = self.work() if version == 1 else self.to_v2()
            p, marks = self.check.run_all(w, with_card=False)
            self.assertFalse(p, p)
            self.assertTrue(any('[REVISION]' in s for s in marks))
            self.assertTrue(any('[OVERLAP-LEDGER]' in s for s in marks))

    def test_malformed_optional_receipt_is_mark_not_schema_block(self):
        w = self.to_v2()
        (w / 'test_revision.json').write_text('{broken', encoding='utf-8')
        p, marks = self.check.run_all(w, with_card=False)
        self.assertFalse(p, p)
        self.assertTrue(any('[REVISION]' in s for s in marks))

    def test_card_report_and_fingerprint_keep_revision_and_full_ledger(self):
        w = self.to_v2()
        revision = {'version': 1, 'test': 'T1', 'critique_item': 0,
                    'weakest_inference': 'The positive control is insufficient.', 'decision': 'no change',
                    'reason': 'The existing query-term removal control already covers this inference.',
                    'retrieval': {'not_needed': 'This is a local protocol question with no external fact.'}}
        write_json(w / 'test_revision.json', revision)
        mutate(w, 'prior_art.json', lambda d: [c.update(overlap_dimensions=['problem']) for c in d['closest_work']])
        r = run_tool('overlap', w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = run_tool('card', w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        card = (w / 'IDEA-CARD.md').read_text(encoding='utf-8')
        report = (w / 'IDEA-REPORT.md').read_text(encoding='utf-8')
        self.assertLessEqual(len(card.splitlines()), 80)
        self.assertEqual(sum(l.startswith('Test revision:') for l in card.splitlines()), 1)
        self.assertEqual(sum(l.startswith('Overlap ledger:') for l in card.splitlines()), 1)
        self.assertIn('no change:', card)
        self.assertIn(revision['reason'], card)
        ledger = read_json(w / 'overlap_ledger.json')
        for row in ledger['queries']:
            self.assertIn(row['query'], report)
            for overlap in row['overlaps']:
                self.assertIn(overlap['difference'], report)
        self.assertIn('Prior-art overlap ledger', report)
        self.assertEqual(self.check.problems(w), [])
        before = self.check.inputs_fingerprint(w)
        mutate(w, 'test_revision.json', lambda d: d.update(reason='A different explicit reason.'))
        self.assertNotEqual(before, self.check.inputs_fingerprint(w))
        self.assertTrue(any('[CARD-STALE]' in s for s in self.check.problems(w)))

    def test_revision_line_shows_before_after_and_why_without_newlines(self):
        v4 = load_tool('v4check')
        d = replay_data()
        d['test_revision.json'] = receipt(d)
        line = v4.revision_line(self.tmp, d)
        self.assertTrue(line.startswith('Test revision:'))
        self.assertIn('Compare intact-tile gain only -> Compare intact-tile gain and preregistered corner-scuff count', line)
        self.assertIn(d['test_revision.json']['reason'], line)
        self.assertNotIn('\n', line)
