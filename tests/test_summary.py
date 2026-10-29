#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/summary.py (v0.6.0 point 2): on a copy of tests/fixtures/finish_run, SUMMARY.md gives the answer (first sentences of
the Executive Summary, no [n]), the confidence level from the FOUND share of the RAW verifier output (state/verifier.json; the "23 FOUND of 41" case of run A is never "high"; thresholds of config `summary`, lowered under min_sources), the number of claims removed after verification (18 in that case),
"N claims verified, of which X FOUND", the cost (host figure, else the receipts as partial, else unknown), the duration (run-start.json to
finish_run.json) and the absolute paths of REPORT.html / REPORT.pdf; summary.json names the file to attach (PDF first); the French run
gives the French message; exit 2 without REPORT.md."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); sys.path.insert(0, str(P))
import summary as S   # noqa: E402
from test_report_lang import french   # noqa: E402
FX = P / 'fixtures' / 'finish_run'


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()); self.d = self.tmp / 'run'; shutil.copytree(FX, self.d)
        (self.d / 'state' / 'run-start.json').write_text(json.dumps({'created_utc': '2026-10-28T09:50:00+00:00'}))
        (self.d / 'state' / 'finish_run.json').write_text(json.dumps({'finished_utc': '2026-10-28T10:12:30+00:00'}))
        (self.d / 'REPORT.html').write_text('<html></html>')

    def tearDown(self): shutil.rmtree(self.tmp)

    def test_english(self):
        x = S.build(self.d); v = json.loads((self.d / 'verdicts.json').read_text())['claims']
        found = sum(c['status'] == 'FOUND' for c in v)
        self.assertEqual(x['counts_basis'], 'verdicts'); self.assertEqual(x['level'], 'unknown')   # no raw verifier output: removals unknown
        (self.d / 'state' / 'verifier.json').write_text(json.dumps({'summary': {s: sum(c['status'] == s for c in v) for s in S.ORDER}}))
        x = S.build(self.d); self.assertEqual(x['counts_basis'], 'verifier')
        self.assertEqual((x['claims'], x['found']), (len(v), found)); self.assertNotRegex(x['answer'], r'\[\d+\]'); self.assertTrue(x['answer'])
        share = found / len(v); lv = S.LEVELS
        exp = 'high' if share >= lv['high'] else 'medium' if share >= lv['medium'] else 'low'
        if x['bibliography_entries'] < S.MIN_SOURCES: exp = {'high': 'medium', 'medium': 'low'}.get(exp, exp)
        self.assertEqual(x['level'], exp)
        self.assertEqual(x['duration_s'], 22 * 60 + 30); self.assertEqual(x['cost_kind'], 'unknown')
        self.assertEqual(x['attach'], str((self.d / 'REPORT.html').resolve())); self.assertIsNone(x['report_pdf'])
        t = S.render(x)
        self.assertIn(f'**Verification**: {len(v)} claims verified, of which {found} FOUND', t); self.assertIn('**Duration**: 22 min', t)
        self.assertIn('**Cost**: not known to the run files', t); self.assertIn(str((self.d / 'REPORT.html').resolve()), t)
        self.assertLessEqual(len(t.splitlines()), 7)

    def test_raw_verifier_23_of_41(self):
        """Run A of the v0.6.0 trials: the verifier judged 41 claims, 23 FOUND, 18 ABSENT; section 7 then removed the 18 ABSENT from
        verdicts.json. The confidence must come from the raw output (23/41 = 56 %), never "high" from the 23 FOUND left in verdicts.json."""
        md = (self.d / 'REPORT.md').read_text()                                   # enough sources: the level is not lowered for their number
        (self.d / 'REPORT.md').write_text(md.replace('\n## Methodology Appendix', ''.join(f'\n[{k}] Extra source {k}.\n' for k in range(20, 40)) + '\n## Methodology Appendix', 1))
        kept = [{'id': f'A{i}', 'status': 'FOUND'} for i in range(1, 24)]
        (self.d / 'verdicts.json').write_text(json.dumps({'claims': kept}))
        raw = {'FOUND': 23, 'DISTORTED': 0, 'ABSENT': 18, 'SOURCE-UNAVAILABLE': 0, 'INVALID': 0, 'UNVERIFIED': 0, 'unsupported_rate': 0.439}
        (self.d / 'state' / 'verifier.json').write_text(json.dumps({'summary': raw, 'cost_usd': 1.15}))
        for lang in (None, 'fr'):
            x = S.build(self.d, lang=lang)
            self.assertEqual((x['claims'], x['found'], x['counts_basis']), (41, 23, 'verifier'))
            self.assertGreaterEqual(x['bibliography_entries'], S.MIN_SOURCES)
            self.assertNotEqual(x['level'], 'high'); self.assertEqual(x['level'], 'low'); self.assertEqual(x['found_share'], round(23 / 41, 3))
            t = S.render(x)
            self.assertNotRegex(t, r'\b(high|élevée)\b'); self.assertNotIn('23 of 23', t); self.assertNotIn('23 sur 23', t); self.assertIn('ABSENT 18', t)
        self.assertIn('**Verification**: 41 claims verified, of which 23 FOUND (ABSENT 18); 18 removed from the report after verification', S.render(S.build(self.d)))
        self.assertEqual(S.build(self.d)['removed'], 18)
        self.assertIn('18 retirées du rapport après vérification', S.render(S.build(self.d, lang='fr')))
        # nothing removed yet (verdicts.json still holds the 41 claims): the count is 0 and not shown
        full = kept + [{'id': f'B{i}', 'status': 'ABSENT'} for i in range(18)]
        (self.d / 'verdicts.json').write_text(json.dumps({'claims': full}))
        x = S.build(self.d); self.assertEqual((x['removed'], x['claims']), (0, 41)); self.assertNotIn('removed from the report', S.render(x))
        (self.d / 'verdicts.json').write_text(json.dumps({'claims': kept}))
        # no state/verifier.json, removed claims still listed in verdicts.json: same raw counts
        (self.d / 'state' / 'verifier.json').unlink()
        (self.d / 'verdicts.json').write_text(json.dumps({'claims': kept, 'filter': {'removed': [{'id': f'B{i}', 'status': 'ABSENT'} for i in range(18)]}}))
        x = S.build(self.d); self.assertEqual((x['claims'], x['found'], x['counts_basis'], x['level']), (41, 23, 'verdicts+removed', 'low'))
        self.assertEqual(x['removed'], 18); self.assertIn('18 removed from the report after verification', S.render(x))
        # verdicts.json alone, removals unknown: never a level computed on the kept claims
        (self.d / 'verdicts.json').write_text(json.dumps({'claims': kept}))
        x = S.build(self.d); self.assertEqual((x['counts_basis'], x['level'], x['removed']), ('verdicts', 'unknown', None))
        self.assertNotRegex(S.render(x), r'\bhigh\b'); self.assertNotIn('23 of 23 checked', S.render(x))

    def test_costs_pdf_french(self):
        (self.d / 'state' / 'verifier.json').write_text(json.dumps({'cost_usd': 0.42}))
        (self.d / 'REPORT.pdf').write_bytes(b'%PDF-1.4')
        x = S.build(self.d); self.assertEqual((x['cost_usd'], x['cost_kind']), (0.42, 'partial')); self.assertTrue(x['attach'].endswith('REPORT.pdf'))
        self.assertIn('0.42 USD known from the receipts', S.render(x))
        x = S.build(self.d, cost_usd=3.1); self.assertIn('**Cost**: 3.10 USD', S.render(x))
        (self.d / 'REPORT.md').write_text(french((self.d / 'REPORT.md').read_text()))
        t = S.render(S.build(self.d))
        self.assertIn('**Réponse** : ', t); self.assertIn('affirmations vérifiées dont', t); self.assertIn('**Durée** : 22 min', t); self.assertIn('(PDF : ', t)
        self.assertIn('constats : ', t)

    def test_cli(self):
        t = str(P.parent / 'tools' / 'summary.py')
        o = subprocess.run([sys.executable, '-I', t, str(self.d), '--cost-usd', '2.5'], capture_output=True, text=True)
        self.assertEqual(o.returncode, 0, o.stderr); self.assertTrue((self.d / 'SUMMARY.md').is_file()); self.assertEqual(o.stdout, (self.d / 'SUMMARY.md').read_text())
        self.assertEqual(json.loads((self.d / 'summary.json').read_text())['cost_usd'], 2.5)
        (self.d / 'REPORT.md').unlink()
        self.assertEqual(subprocess.run([sys.executable, '-I', t, str(self.d)], capture_output=True).returncode, 2)


if __name__ == '__main__':
    unittest.main()
