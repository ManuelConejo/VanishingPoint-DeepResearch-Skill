#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of finish_run.py (network stubbed): on a copy of tests/fixtures/finish_run, the six steps run in order and each reports
ok / problems / skipped; validation passes (exit 0), run.json is derived, REPORT.html and the data exports are written and printed;
retraction check: a Crossref `updated-by` retraction (Retraction Watch source) -> retracted, a record with no notice -> none, a network
failure -> unknown (never none), notices found through `filter=updates:` (expression of concern) -> concern, the RW CSV alone -> retracted,
--offline with an empty cache -> unknown; summary.py runs only with --summary (off by default); a broken run fails validation (exit 1) but the other steps still run; law_checks runs only for law.
Contradictor offer: with the offer family's CLI found and no family configured, one line in the report's language ends SUMMARY.md and the
printed block (and is printed alone without --summary); none when a family is configured, when the host is that family, when the CLI is
missing, when contradictor.json exists, when config offer.enabled is false, or in prior-art mode."""
import contextlib, io, json, os, pathlib, shutil, sys, tempfile, unittest, urllib.error
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
        self.assertTrue((self.d / 'SUMMARY.md').is_file()); self.assertIn('**Citations confirmed**', (self.d / 'SUMMARY.md').read_text())
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


class Offer(unittest.TestCase):
    """The contradictor offer line (config contradictor.offer), environment controlled: fake CLI, empty HOME."""
    ENV = ('VP_CONTRADICTORS', 'VP_HOST', 'VP_MODEL_COMMAND_OPENAI', 'HOME')

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.d = self.tmp / 'run'; shutil.copytree(FX, self.d)
        self.fetch = F.gw.fetch; F.gw.fetch = stub; self.cfg = F._config
        self.old = {k: os.environ.get(k) for k in self.ENV}
        for k in self.ENV: os.environ.pop(k, None)
        os.environ['HOME'] = str(self.tmp / 'home'); (self.tmp / 'home').mkdir()
        exe = self.tmp / 'codex'; exe.write_text('#!/bin/sh\nexit 0\n'); exe.chmod(0o755)
        os.environ['VP_MODEL_COMMAND_OPENAI'] = json.dumps([str(exe), 'exec'])

    def tearDown(self):
        F.gw.fetch = self.fetch; F._config = self.cfg
        for k, v in self.old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        shutil.rmtree(self.tmp)

    def main_out(self, *a):
        o = io.StringIO()
        with contextlib.redirect_stdout(o): c = F.main([str(self.d), '--offline', *a])
        return c, o.getvalue()

    def test_line_in_summary(self):
        c, out = self.main_out('--summary'); self.assertEqual(c, 0, out)
        line = F.rl.msg(F.rl.of_run(self.d), 'contra_offer', minutes=F._config()['contradictor']['offer']['minutes'])
        self.assertIn('contradict', line.lower()); self.assertEqual((self.d / 'SUMMARY.md').read_text().splitlines()[-1], line)
        self.assertEqual(out.rstrip().splitlines()[-1], line); self.assertEqual(out.count(line), 1)
        c, out = self.main_out(); self.assertEqual(out.rstrip().splitlines()[-1], line)            # without --summary: printed last
        self.assertEqual(F.rl.msg('fr', 'contra_offer', minutes='2-4').count('contredis ce rapport'), 1)

    def test_no_line(self):
        cases = []
        os.environ['VP_CONTRADICTORS'] = 'openai'; cases.append(('family configured', F.contradictor_offer(self.d))); del os.environ['VP_CONTRADICTORS']
        os.environ['VP_HOST'] = 'openai'; cases.append(('host openai', F.contradictor_offer(self.d))); del os.environ['VP_HOST']
        os.environ['VP_MODEL_COMMAND_OPENAI'] = json.dumps([str(self.tmp / 'no-such-cli')]); cases.append(('CLI missing', F.contradictor_offer(self.d)))
        os.environ['VP_MODEL_COMMAND_OPENAI'] = json.dumps(['vp-no-such-cli-on-path']); cases.append(('CLI not on PATH', F.contradictor_offer(self.d)))
        os.environ['VP_MODEL_COMMAND_OPENAI'] = json.dumps([str(self.tmp / 'codex')]); self.assertTrue(F.contradictor_offer(self.d))
        (self.d / 'contradictor.json').write_text('{}'); cases.append(('already run', F.contradictor_offer(self.d))); (self.d / 'contradictor.json').unlink()
        c = self.cfg(); c['contradictor']['offer']['enabled'] = False; F._config = lambda: c
        cases.append(('off in config', F.contradictor_offer(self.d))); F._config = self.cfg
        for why, v in cases: self.assertIsNone(v, why)
        r = F.finish(self.d, offline=True, prior_art=True); self.assertIsNone(r['contradictor_offer'])
        c, out = self.main_out('--summary'); self.assertIn('contradict', out.rstrip().splitlines()[-1])
        os.environ['VP_CONTRADICTORS'] = 'openai'; c, out = self.main_out('--summary')
        self.assertNotIn('contradict this report', (self.d / 'SUMMARY.md').read_text())


if __name__ == '__main__':
    unittest.main()
