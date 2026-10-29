#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of the report languages (tools/report_lang.py, v0.6.0 point 1): language detection of questions; the fixture report of
tests/fixtures/finish_run translated to French (titles, `### Constat n —`, coverage block) passes validate_card.py checks 6-12 exactly as the
English one; mixed languages, a missing section or an English finding word in a French report are refused (check 6); the readers of the
titles (export_report: bibliography, page breaks, finding anchors, <html lang>; export_data: bibliography entries; passages; followups;
living_diff: findings and French verdict words; evidence_bank: skipped sections) give the same results on the French copy as on the original."""
import json, pathlib, re, shutil, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import report_lang as RL, validate_card as V, export_report as X, export_data as D, living_diff as L, followups as FU, evidence_bank as EB   # noqa: E402,E401
FX = P / 'fixtures' / 'finish_run'


def french(md):
    """The English report with the French titles, finding word, coverage words and verdict words (prose unchanged: the checks read the form)."""
    for en, fr in zip(RL.EN, RL.LANGS['fr']['sections']):
        md = re.sub(r'^## ' + re.escape(en) + r'\s*$', '## ' + fr, md, flags=re.M)
    md = re.sub(r'^### Finding (\d+) —', r'### Constat \1 —', md, flags=re.M)
    md = md.replace('Source coverage. Active:', 'Couverture des sources. Actives :').replace('Skipped or degraded:', 'Ignorées ou dégradées :')
    return md.replace('Verdict: established', 'Verdict : établi').replace('Verdict: probable', 'Verdict : probable').replace('Verdict: open', 'Verdict : ouvert')


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.en = (FX / 'REPORT.md').read_text(encoding='utf-8'); self.fr = french(self.en)

    def tearDown(self): shutil.rmtree(self.tmp)

    def test_detect(self):
        cases = {"Que sait-on de l'effet du jeûne intermittent sur l'HbA1c ?": 'fr', 'What is known about speculative decoding?': 'en',
                 '¿Qué se sabe sobre el ayuno intermitente y la diabetes?': 'es', 'Was ist über die Wirkung von Vitamin D auf Stürze bekannt?': 'de',
                 'Comment les juridictions administratives traitent-elles le déréférencement ?': 'fr', '': 'en', 'RAG': 'en'}
        for q, c in cases.items(): self.assertEqual(RL.detect(q), c, q)

    def test_table_complete(self):
        keys = set(RL.LANGS['en']) ; mkeys = set(RL.LANGS['en']['msg'])
        for c, Lg in RL.LANGS.items():
            self.assertEqual(set(Lg), keys, c); self.assertEqual(set(Lg['msg']), mkeys, c); self.assertEqual(len(Lg['sections']), 8, c)
            self.assertEqual(len(set(Lg['sections'])), 8, c)
            for i, t in enumerate(Lg['sections']): self.assertEqual(RL.canonical(t), RL.EN[i]); self.assertEqual(RL.canonical(t.upper()), RL.EN[i])
        self.assertIsNone(RL.canonical('Synthesis'))

    def test_validate_french_same_as_english(self):
        self.assertEqual(V.report_problems(self.en), [])
        self.assertEqual(V.report_problems(self.fr), [])
        self.assertEqual(RL.report_language(self.fr), 'fr'); self.assertEqual(RL.report_language(self.en), 'en')
        self.assertEqual([t for t, _ in V.sections(self.fr)], RL.EN)

    def test_refusals(self):
        mixed = self.fr.replace('## Bibliographie', '## Bibliography')
        pb = V.report_problems(mixed); self.assertTrue(any(p.startswith('6 ') and 'Bibliographie' in p for p in pb), pb)
        miss = self.fr.replace('## Recommandations', '## Conseils')
        self.assertTrue(any(p.startswith('6 ') and "missing: ['Recommandations']" in p for p in V.report_problems(miss)))
        word = self.fr.replace('### Constat 2 —', '### Finding 2 —', 1)
        self.assertTrue(any('"### Constat n — <title>"' in p for p in V.report_problems(word)))
        nocov = self.fr.replace('Couverture des sources', 'Couverture')
        self.assertTrue(any(p.startswith('10 ') for p in V.report_problems(nocov)))

    def test_whole_run_french(self):
        d = self.tmp / 'run'; shutil.copytree(FX, d); (d / 'REPORT.md').write_text(self.fr, encoding='utf-8')
        e = self.tmp / 'run_en'; shutil.copytree(FX, e)
        self.assertEqual([p for p in V.problems(d) if not p.startswith('9 ')], [p for p in V.problems(e) if not p.startswith('9 ')])
        self.assertEqual(D.bib_entries(self.fr), D.bib_entries(self.en)); self.assertTrue(D.bib_entries(self.fr))
        h = X.render(self.fr, [], passages=None)
        self.assertIn('<html lang="fr">', h); self.assertIn('id="finding-3"', h); self.assertIn('class="pb">Bibliographie', h)
        self.assertEqual(len(re.findall(r'href="#ref-\d+"', h)), len(re.findall(r'href="#ref-\d+"', X.render(self.en, [], passages=None))))
        self.assertIn('<html lang="en">', X.render(self.en, []))
        self.assertEqual(FU._section(self.fr, 'Methodology Appendix'), FU._section(self.en, 'Methodology Appendix').replace(
            'Source coverage. Active:', 'Couverture des sources. Actives :').replace('Skipped or degraded:', 'Ignorées ou dégradées :'))
        units_fr = EB.report_units(self.fr); units_en = EB.report_units(self.en)
        self.assertEqual(len(units_fr), len(units_en)); self.assertTrue(all(u['section'] not in ('Bibliographie', 'Annexe méthodologique') for u in units_fr))

    def test_living_diff_french(self):
        d = self.tmp / 'fr'; shutil.copytree(FX, d); (d / 'REPORT.md').write_text(self.fr, encoding='utf-8')
        e = self.tmp / 'en'; shutil.copytree(FX, e)
        rf, re_ = L.read_run(d), L.read_run(e)
        self.assertEqual([f['n'] for f in rf['findings']], [f['n'] for f in re_['findings']]); self.assertEqual(len(rf['findings']), 5)
        self.assertEqual([f['words'] for f in rf['findings']], [f['words'] for f in re_['findings']])
        self.assertEqual(set(rf['sources']), set(re_['sources'])); self.assertEqual(rf['one_line'], re_['one_line'])
        self.assertEqual(RL.verdict_word('Verdict : ouvert ; probable ensuite'), 'open')
        self.assertEqual(L.verdict_words('établi pour les fractures, ouvert pour les chutes'), ['established', 'open'])

    def test_cli(self):
        import subprocess
        o = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'report_lang.py'), "Quel est l'état de l'art ?"], capture_output=True, text=True)
        j = json.loads(o.stdout); self.assertEqual((j['language'], j['titles'][0], j['finding']), ('fr', 'Résumé', 'Constat'))


if __name__ == '__main__':
    unittest.main()
