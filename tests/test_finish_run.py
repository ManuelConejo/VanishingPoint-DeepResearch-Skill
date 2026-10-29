#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of finish_run.py (network stubbed): on a copy of tests/fixtures/finish_run, the six steps run in order and each reports
ok / problems / skipped; validation passes (exit 0), run.json is derived, REPORT.html and the data exports are written and printed;
retraction check: a Crossref `updated-by` retraction (Retraction Watch source) -> retracted, a record with no notice -> none, a network
failure -> unknown (never none), notices found through `filter=updates:` (expression of concern) -> concern, the RW CSV alone -> retracted,
--offline with an empty cache -> unknown; summary.py runs only with --summary (off by default); a broken run fails validation (exit 1) but the other steps still run; law_checks runs only for law."""
import contextlib, io, json, pathlib, shutil, sys, tempfile, unittest, urllib.error
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import finish_run as F   # noqa: E702
FX = P / 'fixtures' / 'finish_run'
RW = {'source': 'retraction-watch', 'type': 'retraction', 'DOI': '10.1000/notice.1', 'updated': {'date-parts': [[2026, 3, 2]]}}


def stub(url, headers=None):
    if 'fx.retracted' in url and '/works/' in url: return json.dumps({'message': {'DOI': '10.1000/fx.retracted', 'updated-by': [RW]}}).encode()
    if 'fx.clean' in url and '/works/' in url: return json.dumps({'message': {'DOI': '10.1000/fx.clean'}}).encode()
    if 'updates%3A10.1000/fx.clean' in url or 'updates:10.1000/fx.clean' in url:
        return json.dumps({'message': {'items': [{'DOI': '10.1000/n2', 'update-to': [{'DOI': '10.1000/other', 'type': 'retraction'}]}]}}).encode()
    if 'fx.concern' in url and '/works/' in url: return json.dumps({'message': {'DOI': '10.1000/fx.concern'}}).encode()
    if 'fx.concern' in url: return json.dumps({'message': {'items': [{'update-to': [{'DOI': '10.1000/FX.CONCERN', 'type': 'expression_of_concern'}]}]}}).encode()
    raise urllib.error.URLError('offline test')


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.d = self.tmp / 'run'; shutil.copytree(FX, self.d)
        self.fetch = F.gw.fetch; F.gw.fetch = stub

    def tearDown(self):
        F.gw.fetch = self.fetch; shutil.rmtree(self.tmp)

    def run_main(self, *a):
        o = io.StringIO()
        with contextlib.redirect_stdout(o): c = F.main([str(self.d), *a])
        return c, o.getvalue()

    def test_full(self):
        c, out = self.run_main()
        self.assertEqual(c, 0, out)
        r = F.finish(self.d)
        self.assertEqual([s['step'] for s in r['steps']], ['validate_card --header', 'validate_result', 'retractions', 'law_checks', 'export_report', 'export_data'])
        st = {s['step']: s['status'] for s in r['steps']}
        self.assertNotIn('--- SUMMARY.md', out); self.assertFalse((self.d / 'SUMMARY.md').exists())   # v0.6.0: summary.py only with --summary
        self.assertEqual((st['validate_card --header'], st['validate_result'], st['law_checks'], st['export_report'], st['export_data']), ('ok', 'ok', 'skipped', 'ok', 'ok'))
        self.assertEqual(st['retractions'], 'problems')
        for f in ('run.json', 'REPORT.html', 'studies.csv', 'references.bib', 'references.ris', 'references.json', 'retractions.json'):
            self.assertTrue((self.d / f).is_file(), f); self.assertIn(str((self.d / f).resolve()), out)
        x = json.loads((self.d / 'retractions.json').read_text())['sources']
        self.assertEqual({k: v['state'] for k, v in x.items()}, {'S1': 'retracted', 'S2': 'none', 'S3': 'unknown'})
        self.assertTrue(x['S1']['retraction_watch']); self.assertIn('error', x['S3'])

    def test_summary_option(self):
        c, out = self.run_main('--summary')                                                            # optional step 8, off by default
        self.assertEqual(c, 0, out); self.assertIn('--- SUMMARY.md (--summary)', out)
        self.assertTrue((self.d / 'SUMMARY.md').is_file()); self.assertIn('**Verification**', (self.d / 'SUMMARY.md').read_text())
        r = F.finish(self.d, summary=True); self.assertEqual(r['steps'][-1]['step'], 'summary'); self.assertEqual(r['steps'][-1]['status'], 'ok')

    def test_states(self):
        F.gw.STATE = self.d / 'state'
        self.assertEqual(F.check_doi('10.1000/fx.concern')['state'], 'concern')
        self.assertEqual(F.check_doi('10.1000/fx.clean', offline=True)['state'], 'unknown')   # empty cache: never "none"
        rw = {'10.1000/fx.x': [{'type': 'retraction', 'doi': None, 'source': 'retraction-watch-csv', 'date': None}]}
        r = F.check_doi('10.1000/fx.x', offline=True, rw=rw); self.assertEqual((r['state'], r['retraction_watch']), ('retracted', True))
        csvp = self.tmp / 'rw.csv'; csvp.write_text('Record ID,OriginalPaperDOI,RetractionNature,RetractionDate\n1,10.1000/FX.Y,Expression of concern,1/2/2020\n')
        self.assertEqual(F._rw_rows(csvp)['10.1000/fx.y'][0]['type'], 'expression_of_concern')

    def test_broken_and_law(self):
        (self.d / 'result.json').unlink(); shutil.rmtree(self.d / 'searches')
        (self.d / 'scope.md').write_text('T = 2026-10-28. Plugin: law. Mode: standard.\n')
        c, out = self.run_main('--offline')
        self.assertEqual(c, 1); self.assertIn('FAILED', out)
        r = F.finish(self.d, offline=True); st = {s['step']: s['status'] for s in r['steps']}
        self.assertEqual((st['validate_card --header'], st['validate_result']), ('problems', 'problems'))
        self.assertNotEqual(st['law_checks'], 'skipped'); self.assertTrue((self.d / 'REPORT.html').is_file())
        self.assertFalse(F.law_used(self.d, ['plugins/biology.md'])); self.assertTrue(F.law_used(self.d, ['plugins/law.md']))


if __name__ == '__main__':
    unittest.main()
