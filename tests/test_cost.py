#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/cost.py (v0.6.0 point 6): estimates built only from tools/config.json `costs` (no figure in the code: changing the
config changes the estimate), expensive options flagged for confirmation, budgets read from the user's words in four phrasings, a budget
switches every expensive option off and scales the cap and the waves below the base estimate (never under budget.min_cap), euros at par."""
import json, pathlib, subprocess, sys, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import cost as C   # noqa: E702


class T(unittest.TestCase):
    def test_estimates_from_config(self):
        cf = C.C
        e = C.estimate(['plugins/cs-ai.md'])
        self.assertEqual((e['base'], e['high'], e['confirm']), ('standard', cf['standard_usd']['high'], False))
        e = C.estimate(['cs-ai'], fulltext=True)
        self.assertEqual(e['expensive'], ['fulltext']); self.assertTrue(e['confirm'])
        self.assertAlmostEqual(e['high'] - cf['standard_usd']['high'], cf['fulltext_usd_per_text'] * C.FT_CAP, places=2)
        e = C.estimate(['code'], contradictors=['openai', 'openrouter:m'])
        self.assertEqual(e['expensive'], ['code_whole_reading', 'contradictor'])
        cli, api = [p for p in e['parts'] if p['item'] == 'contradictor']
        self.assertAlmostEqual(cli['high'], cf['contradictor_cli_call_usd'] + cf['contradictor_rereads_usd'])
        self.assertAlmostEqual(api['high'], cf['contradictor_api_call_usd'] + cf['contradictor_rereads_usd'])
        e = C.estimate(['law'], audit=True)
        self.assertAlmostEqual(e['high'], cf['law_usd']['high'] * cf['audit_factor']['high'], places=2)
        old = C.C['standard_usd']; C.C['standard_usd'] = {'low': 1.0, 'high': 1.5}
        try: self.assertEqual(C.estimate([])['high'], 1.5)
        finally: C.C['standard_usd'] = old

    def test_budget_words(self):
        for t, v in (('budget 5 $', (5.0, 'USD')), ('plafond de 2,5 dollars', (2.5, 'USD')), ('5 USD max', (5.0, 'USD')), ('max. 4 €', (4.0, 'EUR')),
                     ('Que sait-on du RAG ? budget : 3 USD', (3.0, 'USD')), ('$2 max', (2.0, 'USD'))):
            self.assertEqual(C.budget_in(t), v, t)
        self.assertIsNone(C.budget_in('What is known about the 5 $ cap of ATM fees?'))

    def test_plan(self):
        e = C.estimate(['cs-ai'], fulltext=True); b = C.C['budget']
        pl = C.plan(e, 20.0)
        self.assertFalse(pl['reduced']); self.assertEqual(pl['cap'], C.CAP); self.assertIn('fulltext', pl['expensive_off'])
        pl = C.plan(e, 1.5)
        self.assertTrue(pl['reduced']); self.assertEqual(pl['cap'], max(b['min_cap'], int(C.CAP * 1.5 / C.C['standard_usd']['high'])))
        self.assertEqual(pl['waves_max'], max(1, int(b['waves_full'] * 1.5 / C.C['standard_usd']['high'])))
        pl = C.plan(e, 0.1); self.assertEqual(pl['cap'], b['min_cap']); self.assertTrue(pl['below_min']); self.assertEqual(pl['waves_max'], 1)
        pl = C.plan(C.estimate(['code']), 2.0); self.assertTrue(pl['code_note'])

    def test_cli(self):
        t = str(P.parent / 'tools' / 'cost.py')
        o = subprocess.run([sys.executable, '-I', t, '--plugin', 'cs-ai', '--fulltext', '--lang', 'fr'], capture_output=True, text=True)
        self.assertEqual(o.returncode, 0); self.assertIn('Coût estimé', o.stdout); self.assertIn('Confirmer', o.stdout)
        o = subprocess.run([sys.executable, '-I', t, '--plugin', 'cs-ai', '--text', 'budget 1 USD', '--json'], capture_output=True, text=True)
        j = json.loads(o.stdout); self.assertTrue(j['budget']['reduced']); self.assertEqual(j['budget']['budget_usd'], 1.0)
        o = subprocess.run([sys.executable, '-I', t, '--text', 'max 20 € please'], capture_output=True, text=True)
        self.assertIn('par', o.stdout)


if __name__ == '__main__':
    unittest.main()
