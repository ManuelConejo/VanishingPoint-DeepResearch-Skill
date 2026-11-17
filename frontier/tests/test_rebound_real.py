# SPDX-License-Identifier: Apache-2.0
"""The controls shown on the format of a REAL VP run (regression specification RB46).

tests/fixtures/vp_real_claude4/ holds card.json, verdicts.json and result.json copied byte for byte from a real VP run
(46 sources, claims A1..., statuses FOUND and DISTORTED). Only state/journal.jsonl is synthetic (see SYNTHETIC-JOURNAL.txt):
the real run did not keep its gateway journal."""
import hashlib
import json
import shutil

from .helpers import mutate, read_json, run_tool, write_json
from .rb_common import RB, VP

REAL_SHA256 = {
    'card.json': '8c3849fb37ebd6c7baa57bf2191e45eafa333c725d82498901dcc2cd8960533c',
    'verdicts.json': '99be7e5cc3734f6186e3bf66608e16b66e531c6d5791475e60448ca2fc9ee0f0',
    'result.json': '0210bf116d5212ff3f9b28053a2e94a08ed0ba55cb203457f1e3b1222457e0e0',
}
A1 = {'id': 'arxiv:2409.04109', 'run': 'real', 'claim': 'A1'}      # FOUND in the real run
A5 = {'id': 'arxiv:2409.14634', 'run': 'real', 'claim': 'A5'}      # DISTORTED in the real run
A3 = {'id': 'arxiv:2603.15164', 'run': 'real', 'claim': 'A3'}      # dated 2026 in the real run


class RealBase(RB):
    def use_real_run(self, name='real', directory='vp_real_claude4'):
        """The valid VP directory, with the real run listed in intake.json and recorded in run.json."""
        def intake(d):
            d['vp']['runs'][name] = '../' + directory
        mutate(self.work(VP), 'intake.json', intake)

        def run(d):
            d['steps'].append({'step': 'rebound_vp_run', 'utc': '2026-11-14T13:00:00Z', 'duration_s': 1, 'cost_usd': 0,
                               'vp_run': name})
        mutate(self.work(VP), 'run.json', run)

    def add_material(self, ref, iid='N1'):
        self.idea(VP, iid, lambda i: i['materials'].append({'kind': 'reference', 'ref': dict(ref),
                                                            'why': 'A study of the real VP run that backs this idea.'}))


class RealFilesTest(RealBase):
    def test_the_fixture_is_the_real_run_byte_for_byte(self):
        d = self.fx / 'vp_real_claude4'
        for name, digest in REAL_SHA256.items():
            self.assertEqual(hashlib.sha256((d / name).read_bytes()).hexdigest(), digest, name)

    def test_the_synthetic_part_is_declared(self):
        d = self.fx / 'vp_real_claude4'
        self.assertIn('SYNTHETIC', (d / 'SYNTHETIC-JOURNAL.txt').read_text(encoding='utf-8'))
        self.assertTrue((d / 'state' / 'journal.jsonl').exists())

    def test_real_format_is_read_by_the_check(self):
        self.use_real_run()
        self.assertEqual(self.check.ref_status(self.work(VP), A1), 'FOUND')
        self.assertEqual(self.check.ref_status(self.work(VP), A5), 'DISTORTED')


class RealReferenceTest(RealBase):
    def test_a_found_reference_passes(self):
        self.use_real_run()
        self.add_material(A1)
        probs, warns = self.check.run_all(self.work(VP))
        self.assertEqual(probs, [])
        self.assertFalse(any(w.startswith('[REB-REF]') and 'arxiv:2409.04109' in w for w in warns), warns)

    def test_a_distorted_reference_is_a_visible_warning(self):
        self.use_real_run()
        self.add_material(A5)
        probs, warns = self.check.run_all(self.work(VP))
        self.assertEqual(probs, [])
        self.assertTrue(any(w.startswith('[REB-REF]') and 'arxiv:2409.14634' in w and 'DISTORTED' in w for w in warns), warns)

    def test_an_absent_reference_fails(self):
        self.use_real_run()
        self.add_material(A1)

        def go(d):
            for c in d['claims']:
                if c['id'] == 'A1':
                    c['status'] = 'ABSENT'
        mutate(self.fx / 'vp_real_claude4', 'verdicts.json', go)
        self.assertCode('[REF-ABSENT]')

    def test_an_identifier_that_is_not_the_claim_source_fails(self):
        self.use_real_run()
        self.add_material({'id': 'arxiv:2506.20803', 'run': 'real', 'claim': 'A1'})
        self.assertCode('[REF-MISMATCH]')

    def test_a_claim_that_the_run_does_not_have(self):
        self.use_real_run()
        self.add_material({'id': 'arxiv:2409.04109', 'run': 'real', 'claim': 'A99'})
        self.assertAnyCode(['[REF-MISSING]', '[VP-RUN]'])

    def test_the_date_barrier_reads_the_years_of_the_real_result_json(self):
        self.use_real_run()
        self.add_material(A3)
        self.assertEqual(self.probs(), [])         # T 2026-11-14: a 2026 study is allowed
        mutate(self.work(VP), 'intake.json', lambda d: d.update(T='2025-12-31'))
        probs = self.probs()
        self.assertTrue(any(p.startswith('[DATE]') and 'arxiv:2603.15164' in p for p in probs), probs)

    def test_a_card_run_is_not_a_prior_art_run(self):
        self.use_real_run()
        self.idea(VP, 'N1', lambda i: i['prior_art'].update(vp_run='real'))
        probs = self.assertCode('[REB-PRIOR-ART]')
        self.assertTrue(any('PRIOR-ART.md' in p for p in probs), probs)


class RealPriorArtChainTest(RealBase):
    """The whole chain of RB40 on the real format: a prior-art run made of the real files plus a synthetic journal
    and a synthetic PRIOR-ART.md (a real card run has none)."""

    def setUp(self):
        super().setUp()
        d = self.fx / 'vp_real_pa'
        shutil.copytree(str(self.fx / 'vp_real_claude4'), str(d))
        shutil.copyfile(str(self.fx / 'vp_rb_n1' / 'PRIOR-ART.md'), str(d / 'PRIOR-ART.md'))
        self.use_real_run('real_pa', 'vp_real_pa')
        queries = [json.loads(l)['query'] for l in (d / 'state' / 'journal.jsonl').read_text(encoding='utf-8').splitlines()]

        def go(i):
            i['prior_art'].update(vp_run='real_pa', queries=queries)
            i['prior_art']['closest_work'] = [{'ref': {'id': 'arxiv:2409.04109', 'run': 'real_pa', 'claim': 'A1'},
                                               'title': 'Can LLMs Generate Novel Research Ideas?', 'year': '2024',
                                               'what_differs': 'Judged by experts on ideas, with no paired intervention on records.'}]
        self.idea(VP, 'N1', go)
        self.queries = queries

    def test_the_chain_passes(self):
        probs, warns = self.check.run_all(self.work(VP))
        self.assertEqual(probs, [])

    def test_a_query_that_is_not_in_the_journal_is_refused(self):
        self.idea(VP, 'N1', lambda i: i['prior_art']['queries'].append('query written after the fact'))
        self.assertCode('[REB-PRIOR-ART]')

    def test_a_journal_entry_after_the_ranking_is_refused(self):
        p = self.fx / 'vp_real_pa' / 'state' / 'journal.jsonl'
        rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()]
        rows[0]['utc'] = '2026-11-14T14:30:00.000000+00:00'
        p.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
        self.assertAnyCode(['[REB-PRIOR-ART]', '[REB-ORDER]'])

    def test_the_status_is_the_answer_of_the_run(self):
        self.idea(VP, 'N1', lambda i: i['prior_art'].update(status='Not found'))
        self.assertCode('[REB-PRIOR-ART]')


class RealExportTest(RB):
    def test_arm_b_made_from_the_real_run(self):
        ex = self.fx / 'export_rebound'

        def go(d):
            d['vp_run'] = 'real'
            d['vp_runs'] = {'real': '../vp_real_claude4'}
            d['ideas'][0]['references'] = [dict(A1), dict(A5)]
            for it in d['ideas'][1:]:
                it['references'] = [dict(A1)]
        mutate(ex, 'b_01.json', go)
        key = self.tmp / 'k' / 'KEY.json'
        r = run_tool('export_rebound', '--manifest', ex / 'manifest.json', '--out', self.tmp / 'out', '--key', key)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        statuses = {ref['status'] for m in read_json(key)['cases']['case-01']['ideas'].values() if m['arm'] == 'B'
                    for ref in m['references']}
        self.assertEqual(statuses, {'FOUND', 'DISTORTED'})
        self.assertNotIn('"real"', (self.tmp / 'out' / 'blind' / 'case-01.json').read_text(encoding='utf-8'))
