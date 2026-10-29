#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/summary.py (v0.6.0 point 2): on a copy of tests/fixtures/finish_run, SUMMARY.md gives the answer (first sentences of
the Executive Summary, no [n]), "Citations confirmed: X of N checked" on the RAW verifier output (state/verifier.json; the "23 FOUND
of 41" case of run A never reads 23 of 23) with the number of claims removed after verification (18 in that case), no "confidence" level in
any language (external audit of 2026-10-29), the coverage line (research angles of scope.md reached by a kept source, distinct studies of
tools/study_family.py, the notice under min_sources), at most six lines, the cost (host figure, else the receipts as partial, else unknown), the duration (run-start.json to
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
        self.assertEqual(x['counts_basis'], 'verdicts'); self.assertIsNone(x['found_share'])   # no raw verifier output: removals unknown
        self.assertIn('claims kept in verdicts.json (raw verifier output missing', S.render(x))
        (self.d / 'state' / 'verifier.json').write_text(json.dumps({'summary': {s: sum(c['status'] == s for c in v) for s in S.ORDER}}))
        x = S.build(self.d); self.assertEqual(x['counts_basis'], 'verifier')
        self.assertEqual((x['claims'], x['found']), (len(v), found)); self.assertNotRegex(x['answer'], r'\[\d+\]'); self.assertTrue(x['answer'])
        self.assertEqual(x['found_share'], round(found / len(v), 3)); self.assertNotIn('level', x)
        self.assertEqual((x['bibliography_entries'], x['studies'], x['study_families']), (15, 14, [['S4', 'S5']]))   # VITAL falls / fractures
        self.assertEqual(x['duration_s'], 22 * 60 + 30); self.assertEqual(x['cost_kind'], 'unknown')
        self.assertEqual(x['attach'], str((self.d / 'REPORT.html').resolve())); self.assertIsNone(x['report_pdf'])
        t = S.render(x)
        self.assertIn(f'**Citations confirmed**: {found} of {len(v)} checked ({100 * found // len(v)} %)', t); self.assertIn('**Duration**: 22 min', t)
        self.assertIn('14 distinct studies (15 bibliography entries, versions of one study counted once)', t)
        self.assertNotRegex(t, r'(?i)confiden|\bhigh\b|\bmedium\b|\blow\b')
        self.assertIn('**Cost**: not known to the run files', t); self.assertIn(str((self.d / 'REPORT.html').resolve()), t)
        self.assertLessEqual(len(t.splitlines()), 6)

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
            self.assertEqual(x['found_share'], round(23 / 41, 3))
            t = S.render(x)
            self.assertNotRegex(t, r'(?i)\b(high|élevée|confidence|confiance)\b'); self.assertNotIn('23 of 23', t); self.assertNotIn('23 sur 23', t); self.assertIn('ABSENT 18', t)
            self.assertLessEqual(len(t.splitlines()), 6)
        self.assertIn('**Citations confirmed**: 23 of 41 checked (56 %); ABSENT 18; 18 removed from the report after verification', S.render(S.build(self.d)))
        self.assertNotIn('fewer than', S.render(S.build(self.d)))                  # 35 entries: no notice
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
        x = S.build(self.d); self.assertEqual((x['claims'], x['found'], x['counts_basis']), (41, 23, 'verdicts+removed'))
        self.assertEqual(x['removed'], 18); self.assertIn('18 removed from the report after verification', S.render(x))
        # verdicts.json alone, removals unknown: never a level computed on the kept claims
        (self.d / 'verdicts.json').write_text(json.dumps({'claims': kept}))
        x = S.build(self.d); self.assertEqual((x['counts_basis'], x['found_share'], x['removed']), ('verdicts', None, None))
        self.assertNotRegex(S.render(x), r'\bhigh\b'); self.assertNotIn('23 of 23 checked', S.render(x))
        self.assertIn('23 of the 23 claims kept in verdicts.json (raw verifier output missing', S.render(x))

    def test_costs_pdf_french(self):
        (self.d / 'state' / 'verifier.json').write_text(json.dumps({'cost_usd': 0.42}))
        (self.d / 'REPORT.pdf').write_bytes(b'%PDF-1.4')
        x = S.build(self.d); self.assertEqual((x['cost_usd'], x['cost_kind']), (0.42, 'partial')); self.assertTrue(x['attach'].endswith('REPORT.pdf'))
        self.assertIn('0.42 USD known from the receipts', S.render(x))
        x = S.build(self.d, cost_usd=3.1); self.assertIn('**Cost**: 3.10 USD', S.render(x))
        (self.d / 'REPORT.md').write_text(french((self.d / 'REPORT.md').read_text()))
        t = S.render(S.build(self.d))
        self.assertIn('**Réponse** : ', t); self.assertIn('**Citations confirmées** : 7 sur les 8 affirmations gardées', t); self.assertIn('14 études distinctes', t); self.assertIn('**Durée** : 22 min', t); self.assertIn('(PDF : ', t)
        self.assertIn('constats : ', t)

    def test_four_languages_no_confidence(self):
        """Every language of tools/report_lang.py: the citations and coverage labels exist, no level word, at most six lines (a follow-up
        number goes on the answer line)."""
        import report_lang as RL
        (self.d / 'state' / 'verifier.json').write_text(json.dumps({'summary': {'FOUND': 7, 'ABSENT': 1}}))
        (self.d / 'followup.json').write_text(json.dumps({'n': 2}))
        for lang in RL.LANGS:
            m = RL.LANGS[lang]['msg']; self.assertNotIn('confidence', m); self.assertNotIn('level', m)
            for k in ('citations', 'citations_found', 'citations_kept', 'citations_none', 'coverage', 'angles_reached', 'studies', 'sources', 'source_one', 'few_sources'):
                self.assertIn(k, m, (lang, k))
            t = S.render(S.build(self.d, lang=lang)); self.assertLessEqual(len(t.splitlines()), 6, t)
            self.assertTrue(t.startswith('**' + RL.msg(lang, 'followup', n=2) + ' — ' + RL.msg(lang, 'answer') + '**'), t)
            self.assertIn('**' + m['citations'] + '**', t); self.assertIn('**' + m['coverage'] + '**', t)
            self.assertNotRegex(t, r'(?i)confian|confiden|vertrauen|élevée|\bhoch\b')

    def test_coverage_angles_and_studies(self):
        """Angles of scope.md reached by a kept source (identifier of card.json in a searches/ file naming the angle); not shown when the
        searches name no angle; fewer than min_sources distinct studies -> notice, counted on studies, not entries."""
        (self.d / 'scope.md').write_text('# Scope\n## Angles\n1. Trials.\n2. Reviews.\n3. Registries.\n4. Harms.\n## Plan\n1. x\n')
        sd = self.d / 'searches'
        for f in sd.glob('*.md'): f.unlink()
        (sd / '1.md').write_text('# searches/1.md (angles 1 and 2)\nIds: pmid:32492153\n')
        (sd / '2.md').write_text('# searches/2.md (angle 3)\nIds: pmid:99999999\n')
        (sd / '3.md').write_text('# searches/3.md (angle 4)\nnothing\n')
        x = S.build(self.d); self.assertEqual((x['angles_reached'], x['angles']), (2, 4))
        self.assertIn('2 of 4 research angles reached by a kept source', S.render(x))
        self.assertEqual(S._angle_numbers('angles 4-6 and 8'), {4, 5, 6, 8}); self.assertEqual(S._angle_numbers('angles 4,5,6'), {4, 5, 6})
        self.assertEqual(S._angle_numbers('Angles: 1 (meta-analyses, 2-8 C), 5 (negative results). T = 2022-01-01'), {1, 5})
        for f in sd.glob('*.md'): f.write_text('no angle named\npmid:32492153\n')
        x = S.build(self.d); self.assertIsNone(x['angles']); self.assertNotIn('research angles', S.render(x))
        md = (self.d / 'REPORT.md').read_text()
        (self.d / 'REPORT.md').write_text(md.replace('\n## Methodology Appendix', ''.join(f'\n[{k}] VITAL investigators. Vitamin D supplementation and falls in VITAL, extra {k}. 2020. pmid:3249215{k % 10}.\n' for k in range(20, 24)) + '\n## Methodology Appendix', 1))
        x = S.build(self.d); self.assertEqual(x['bibliography_entries'], 19); self.assertLess(x['studies'], 19)

    def test_cli(self):
        t = str(P.parent / 'tools' / 'summary.py')
        o = subprocess.run([sys.executable, '-I', t, str(self.d), '--cost-usd', '2.5'], capture_output=True, text=True)
        self.assertEqual(o.returncode, 0, o.stderr); self.assertTrue((self.d / 'SUMMARY.md').is_file()); self.assertEqual(o.stdout, (self.d / 'SUMMARY.md').read_text())
        self.assertEqual(json.loads((self.d / 'summary.json').read_text())['cost_usd'], 2.5)
        (self.d / 'REPORT.md').unlink()
        self.assertEqual(subprocess.run([sys.executable, '-I', t, str(self.d)], capture_output=True).returncode, 2)


if __name__ == '__main__':
    unittest.main()
