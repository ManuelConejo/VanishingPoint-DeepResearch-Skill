#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of check 14 (tools/cross_source.py, called by validate_card.py): a clause that compares, ranks, counts, excludes or reports a
search outcome across sources while citing a single source is flagged, in English and in each language of tools/report_lang.py; the same
statement without [n], or citing every source compared, passes; single-source facts, clauses of a multi-citation sentence, the bibliography
and the "`[n]` / `A<k>`" designation of the methodology appendix are not flagged; validate_card.report_problems carries the lines, numbered 14;
config.json `cross_source.enabled` = false switches the check off. The sentences below are fixtures (shapes of the lab's judged errors)."""
import pathlib, sys, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import cross_source as CS, report_lang as RL, validate_card as V   # noqa: E402,E401


def report(body, lang='en', biblio='[1] A. 2020. doi:10.1/a.\n[2] B. 2021. doi:10.1/b.\n[3] C. 2022. doi:10.1/c.\n'):
    s = RL.LANGS[lang]['sections']
    return (f'# R\n## {s[0]}\nSummary.\n## {s[1]}\nIntro.\n## {s[2]}\n### {RL.LANGS[lang]["finding"]} 1 — x\n{body}\n## {s[3]}\nS.\n'
            f'## {s[4]}\nL.\n## {s[5]}\nR.\n## {s[6]}\n{biblio}## {s[7]}\nM.\n')


class T(unittest.TestCase):
    def flags(self, body, lang='en'): return [x['sentence'] for x in CS.flagged(report(body, lang))]

    def test_flagged_english(self):
        for s in ['The largest is the multicentre study of Frampas, with 105 patients [1].',
                  'Case reports were excluded [2].',
                  'No source seen in this search reports a larger series [1].',
                  'The only trial above 60 patients reports 62.8 % [3].',
                  'Sample sizes range from 21 to 105 [1].',
                  'Welschehold published two overlapping prospective series of 40 patients [2].',
                  'The decision of 20 April 2023 itself was not retrieved; it is known only through [3].',
                  '37/40 (92.5 %) is my computation [2].',
                  'Most series are small [1].']:
            self.assertEqual(self.flags(s), [s], s)

    def test_not_flagged(self):
        for s in ['Frampas reports 105 patients and a sensitivity of 62.8 % [1].',
                  'The 105-patient study reports 62.8 % [1]. Of the series read, it is the largest (our comparison).',
                  'Most series are small; only two exceed 60 patients [1, 2].',
                  'Case reports were excluded [1-3].',
                  'Case reports were excluded [1][2].',
                  'The largest series found has 105 patients, and no larger one was seen in this search.',
                  'Sensitivity was 62.8 % [1] and 95 % [2].',
                  'Of the four studies read, none reports specificity.']:
            self.assertEqual(self.flags(s), [], s)

    def test_clause_of_multi_citation_sentence(self):
        s = 'Across studies, the lowest figure is 52.4 % [1], and Welschehold reports 95 % [2].'
        self.assertEqual(self.flags(s), [s])
        f = CS.flagged(report(s))[0]
        self.assertEqual(f['citation'], '[1]'); self.assertIn('lowest', f['markers'])

    def test_numbers(self):
        self.assertEqual(CS.numbers('[5]'), {5}); self.assertEqual(CS.numbers('[5, 10]'), {5, 10})
        self.assertEqual(CS.numbers('[12-14]'), {12, 13, 14}); self.assertEqual(CS.numbers('[12–14]'), {12, 13, 14})
        self.assertEqual(CS.numbers('[2][9]'), {2, 9}); self.assertEqual(CS.numbers('[3], [3]'), {3})

    def test_bibliography_and_designation_skipped(self):
        md = report('Frampas reports 105 patients [1].', biblio='[1] The largest study, excluded elsewhere. doi:10.1/a.\n')
        self.assertEqual(CS.flagged(md), [])
        md = report('M.').replace('## Methodology Appendix\nM.', '## Methodology Appendix\nThe ABSENT claim `[1]` / A5, the selection of five studies, was removed.')
        self.assertEqual(CS.flagged(md), [])

    def test_languages(self):
        cases = {'fr': ['La plus grande série compte 105 patients [1].', 'Les rapports de cas ont été exclus [2].',
                        "La décision n'a pas été lue [3].", 'Seules deux séries dépassent 60 patients [1].'],
                 'es': ['La mayor serie incluye 105 pacientes [1].', 'Los informes de casos fueron excluidos [2].',
                        'El único ensayo con más de 60 pacientes informa 62,8 % [3].'],
                 'de': ['Die größte Serie umfasst 105 Patienten [1].', 'Fallberichte wurden ausgeschlossen [2].',
                        'Die Entscheidung wurde nicht gelesen [3].']}
        for lang, ss in cases.items():
            for s in ss: self.assertEqual(self.flags(s, lang), [s], (lang, s))
        self.assertEqual(self.flags('Frampas rapporte 105 patients et une sensibilité de 62,8 % [1].', 'fr'), [])
        self.assertEqual(set(CS.MARKERS), set(RL.LANGS), 'one marker entry per language of report_lang.py')
        self.assertEqual({lang: [f for f, _ in v] for lang, v in CS.MARKERS.items()}, {lang: [f for f, _ in CS.MARKERS['en']] for lang in CS.MARKERS})

    def test_validate_card_lines(self):
        pb = V.report_problems(report('The largest is the study of Frampas, with 105 patients [1]. Frampas reports 62.8 % [1].'))
        p14 = [p for p in pb if p.startswith('14 ')]
        self.assertEqual(len(p14), 2, pb)
        self.assertIn('1 sentence(s)', p14[0]); self.assertIn('[1]', p14[1]); self.assertIn('largest', p14[1])
        self.assertEqual([p for p in V.report_problems(report('Frampas reports 105 patients [1].')) if p.startswith('14 ')], [])

    def test_excerpt_and_switch(self):
        long = 'The largest series ' + 'word ' * 100 + 'has 105 patients [1].'
        line = CS.problems(report(long))[1]
        self.assertLessEqual(len(line.split(': ', 1)[1]), int(CS.CFG['excerpt_chars']))
        old = dict(CS.CFG)
        try:
            CS.CFG['enabled'] = False; self.assertEqual(CS.problems(report(long)), [])
        finally:
            CS.CFG.clear(); CS.CFG.update(old)


if __name__ == '__main__':
    unittest.main()
