#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/parse_date.py (v0.6.0 point 8): the documented rules ("en 2020" = 2021-01-01, documents of 2020 included; "avant mars
2024" = 2024-03-01; "au 1er janvier 2015" = 2015-01-01; "as of 2019" = 2020-01-01...), four languages, ISO and numeric forms, ranges, a bare
year inside a question is a topic and not a T, a lower bound is ignored, a T after today becomes today, and the command line."""
import datetime as dt, json, pathlib, subprocess, sys, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import parse_date as PD   # noqa: E702
TODAY = dt.date(2026, 10, 29)


class T(unittest.TestCase):
    def t(self, text): return PD.parse(text, TODAY)['T']

    def test_documented_rules(self):
        cases = {'en 2020': '2021-01-01', 'avant mars 2024': '2024-03-01', 'au 1er janvier 2015': '2015-01-01', 'as of 2019': '2020-01-01',
                 'in 2020': '2021-01-01', 'before 2020': '2020-01-01', 'en mars 2024': '2024-04-01', 'before March 2024': '2024-03-01',
                 "jusqu'au 31 décembre 2019": '2020-01-01', "jusqu'en 2019": '2020-01-01', 'until June 2021': '2021-07-01',
                 'fin 2020': '2021-01-01', 'end of 2020': '2021-01-01', 'début 2020': '2020-01-01', 'mid-2020': '2020-07-01', 'Mitte 2020': '2020-07-01',
                 'T = 2012-08-01': '2012-08-01', 'as of January 1, 2015': '2015-01-01', 'in Q3 2021': '2021-10-01', 'en 2020-05': '2020-06-01'}
        for k, v in cases.items(): self.assertEqual(self.t(k), v, k)

    def test_rule_text(self):
        r = PD.parse('en 2020', TODAY)
        self.assertIn('INCLUDED', r['rule']); self.assertIn('2021-01-01', r['rule']); self.assertEqual(r['matched'], '2020')
        self.assertIn('EXCLUDED', PD.parse('avant mars 2024', TODAY)['rule'])
        self.assertIn('start of that day', PD.parse('au 1er janvier 2015', TODAY)['rule'])

    def test_languages_and_forms(self):
        self.assertEqual(self.t('Was wusste man vor dem 1. März 2020?'), '2020-03-01')
        self.assertEqual(self.t('¿Qué se sabía en marzo de 2021?'), '2021-04-01')
        self.assertEqual(self.t('Que savait-on en février 2019 sur le sujet ?'), '2019-03-01')
        self.assertEqual(self.t('au 15/03/2024'), '2024-03-15')
        self.assertEqual(self.t('as of 03/15/2024'), '2024-03-15')
        self.assertEqual(self.t('2020'), '2021-01-01'); self.assertEqual(self.t('Mars 2024'), '2024-04-01'); self.assertEqual(self.t('2015-01-01'), '2015-01-01')

    def test_questions(self):
        self.assertEqual(self.t("Que savait-on en 2020 sur l'effet du jeûne intermittent ?"), '2021-01-01')
        self.assertEqual(self.t('What did we know about RAG before March 2024?'), '2024-03-01')
        self.assertEqual(self.t('Trials published between 2015 and 2020 on statins'), '2021-01-01')
        r = PD.parse('What are the effects of the 2008 crisis on bank margins?', TODAY)
        self.assertEqual(r['T'], '2026-10-29'); self.assertIn('topic', r['rule'])
        self.assertEqual(self.t('studies after 2015 on X'), '2026-10-29')
        self.assertEqual(self.t('papers that may 2020 matter'), '2026-10-29')
        r = PD.parse('avant 2020, et en 2015 ?', TODAY); self.assertEqual(r['T'], '2020-01-01'); self.assertIn('several', r['note'])

    def test_future_and_invalid(self):
        r = PD.parse('en 2030', TODAY); self.assertEqual(r['T'], '2026-10-29'); self.assertIn('after today', r['note'])
        self.assertEqual(self.t('au 31 février 2020'), '2026-10-29')          # no such day: no date read

    def test_cli(self):
        o = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'parse_date.py'), 'avant mars 2024', '--today', '2026-10-29'], capture_output=True, text=True)
        self.assertEqual(o.returncode, 0); self.assertTrue(o.stdout.startswith('T = 2024-03-01\n')); self.assertIn('scope.md: T = 2024-03-01', o.stdout)
        o = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'parse_date.py'), 'en 2020', '--json', '--today', '2026-10-29'], capture_output=True, text=True)
        self.assertEqual(json.loads(o.stdout)['T'], '2021-01-01')
        o = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'parse_date.py'), 'x', '--today', 'bad'], capture_output=True, text=True)
        self.assertEqual(o.returncode, 2)


if __name__ == '__main__':
    unittest.main()
