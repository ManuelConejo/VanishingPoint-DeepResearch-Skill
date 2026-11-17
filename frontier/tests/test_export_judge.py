# SPDX-License-Identifier: Apache-2.0
"""export_judge.py: blind export for the judges of the V1 pilot, and the baseline format (regression specification R64, R65)."""
import json
import unittest

from .helpers import FRONTIER, TempCase, mutate, read_json, run_tool

GRID = ['competing_hypotheses', 'distinct_predictions', 'decisive_intervention', 'sensitivity', 'decision_rule',
        'feasibility']


def all_text(path):
    return '\n'.join(p.read_text(encoding='utf-8') for p in sorted(path.iterdir()) if p.is_file())


class ExportJudgeTest(TempCase):
    def export(self, name='valid_vp', *extra):
        out = self.tmp / ('judge-' + name)
        r = run_tool('export_judge', self.work(name), '--out', out, '--case-id', 'case-07', *extra)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return out

    def test_files_and_grid(self):
        out = self.export()
        j = read_json(out / 'judge.json')
        self.assertTrue((out / 'JUDGE.md').exists())
        self.assertEqual(j['case_id'], 'case-07')
        self.assertEqual([g['id'] for g in j['grid']], GRID)
        self.assertEqual(j['answer_format']['total'], '0-6')
        self.assertEqual(sorted(j['answer_format']['scores']), sorted(GRID))
        self.assertEqual([t['id'] for t in j['tests']], ['T1', 'T2'])
        self.assertIn('idea', j)
        self.assertTrue(all('statement' in h for h in j['hypotheses']))

    def test_blind_no_outcome(self):
        w = self.work('valid_vp')
        out = self.export()
        text = all_text(out)
        reco = read_json(w / 'recommendation.json')
        res = read_json(w / 'result.json')
        for s in (reco['reason'], res['observed'], res['decision_rule_applied'], 'Gain seen', 'Recommendation',
                  'doi:', 'arxiv:', 'pmid:', w.name, 'fixed_utc', '2026-11-14T10:00:00Z', 'critique', 'Partially',
                  'before_fingerprint', 'stdout_tail'):
            self.assertNotIn(s, text, s)
        for key in ('recommendation', 'result', 'decision_log', 'critique', 'prior_art', 'ranking'):
            self.assertNotIn(key, read_json(out / 'judge.json'))

    def test_tests_stripped_of_references(self):
        w = self.work('valid_vp')
        mutate(w, 'tests.json', lambda d: d['tests'][0]['decisive_intervention'].update(
            description='As in doi:10.1000/titles.2019, randomise the variant indexed first.'))
        out = self.export()
        self.assertNotIn('10.1000/titles.2019', all_text(out))

    def test_refuses_when_outcome_leaks(self):
        w = self.work('valid_vp')
        observed = read_json(w / 'result.json')['observed']
        mutate(w, 'tests.json', lambda d: d['tests'][0].update(unexpected_under_both=observed))
        out = self.tmp / 'judge-leak'
        r = run_tool('export_judge', w, '--out', out)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertFalse((out / 'judge.json').exists())

    def test_never_overwrites_a_foreign_directory(self):
        out = self.tmp / 'foreign'
        out.mkdir()
        (out / 'notes.txt').write_text('mine\n', encoding='utf-8')
        r = run_tool('export_judge', self.work('valid_vp'), '--out', out)
        self.assertEqual(r.returncode, 2)
        self.assertEqual((out / 'notes.txt').read_text(encoding='utf-8'), 'mine\n')

    def test_default_case_id_is_blind(self):
        out = self.tmp / 'judge-default'
        r = run_tool('export_judge', self.work('valid_vp'), '--out', out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cid = read_json(out / 'judge.json')['case_id']
        self.assertRegex(cid, r'^case-[0-9a-f]{12}$')


class BaselineTest(TempCase):
    def test_schema_exists(self):
        s = json.loads((FRONTIER / 'schemas' / 'baseline.json').read_text(encoding='utf-8'))
        self.assertIn('baseline', s['required'])
        self.assertEqual(s['properties']['baseline']['enum'], ['T1', 'T2'])

    def test_t1_and_t2_same_keys_as_frontier(self):
        frontier_out = self.tmp / 'j-frontier'
        self.assertEqual(run_tool('export_judge', self.work('valid_vp'), '--out', frontier_out,
                                  '--case-id', 'c1').returncode, 0)
        keys = set(read_json(frontier_out / 'judge.json'))
        for name in ('baseline_t1.json', 'baseline_t2.json'):
            with self.subTest(baseline=name):
                out = self.tmp / ('j-' + name)
                r = run_tool('export_judge', '--baseline', self.fx / name, '--out', out, '--case-id', 'c1')
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                j = read_json(out / 'judge.json')
                self.assertEqual(set(j), keys)
                self.assertEqual([g['id'] for g in j['grid']], GRID)
                text = all_text(out)
                b = read_json(self.fx / name)
                self.assertNotIn(b['recommendation']['reason'], text)
                self.assertNotIn('T1', [j.get('baseline')])
                self.assertNotIn(b['produced_by'], text)
                self.assertNotIn('baseline', j)

    def test_t2_needs_vp_run(self):
        mutate(self.fx, 'baseline_t2.json', lambda d: d.pop('vp_run'))
        r = run_tool('export_judge', '--baseline', self.fx / 'baseline_t2.json', '--out', self.tmp / 'j')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_baseline_tests_follow_the_tests_schema(self):
        mutate(self.fx, 'baseline_t1.json', lambda d: d['tests'][0].update(id='test-one'))
        r = run_tool('export_judge', '--baseline', self.fx / 'baseline_t1.json', '--out', self.tmp / 'j')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
