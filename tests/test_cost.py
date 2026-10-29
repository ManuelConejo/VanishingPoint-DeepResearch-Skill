#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/cost.py (v0.6.0 point 6): estimates built only from tools/config.json `costs` (no figure in the code: changing the
config changes the estimate), expensive options flagged for confirmation, budgets read from the user's words in four phrasings, a budget
switches every expensive option off and covers the whole run, verification included: budget.verifier_share reserved for the verifier, the
rest turned into a gateway cap by the trace model derived from costs.trace_calibration (a fixed part plus a part per call, an upper
envelope of the measured runs: R1 of the 2026-10-29 budget trial, 2.43 USD of trace at 27 calls, is under it), never under budget.min_cap,
never above call_cap, euros at par; --state writes
state/budget.json, whose cap the gateway takes when no --cap is given (never raising a lower plugin cap) and whose verifier_usd the
verifier takes as its spending limit."""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest
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
        e = C.estimate(['cs-ai'], fulltext=True); b = C.C['budget']; per, fixed = C.trace_model(); share = b['verifier_share']
        pl = C.plan(e, 20.0)
        self.assertFalse(pl['reduced']); self.assertEqual(pl['cap'], C.CAP); self.assertIn('fulltext', pl['expensive_off']); self.assertIsNone(pl['waves_max'])
        self.assertEqual(pl['verifier_usd'], round(20.0 * share, 2)); self.assertAlmostEqual(pl['verifier_usd'] + pl['search_usd'], 20.0)
        for usd in (1.5, 2.0, 3.0, 4.0):                  # 2.0 = the budget of the v0.6.0 B3 trial and of the 2026-10-29 budget trial
            pl = C.plan(e, usd)
            self.assertTrue(pl['reduced']); self.assertEqual(pl['verifier_usd'], round(usd * share, 2))
            self.assertAlmostEqual(pl['verifier_usd'] + pl['search_usd'], usd)
            self.assertEqual((pl['trace_usd_per_call'], pl['trace_usd_fixed']), (per, fixed))
            self.assertEqual(pl['cap'], max(b['min_cap'], int(max(pl['search_usd'] - fixed, 0) / per)))
            self.assertEqual(pl['below_min'], pl['search_usd'] < fixed + b['min_cap'] * per - 1e-9)
            if not pl['below_min']:                                                     # the plan fits the budget, verification included
                self.assertLessEqual(fixed + pl['cap'] * per + pl['verifier_usd'], usd + 1e-9)
            self.assertEqual(pl['waves_max'], max(1, int(b['waves_full'] * pl['cap'] / C.CAP)))
        self.assertAlmostEqual(C.plan(e, 2.0)['min_usd'], round((fixed + b['min_cap'] * per) / (1 - share), 2))
        pl = C.plan(e, 0.1); self.assertEqual(pl['cap'], b['min_cap']); self.assertTrue(pl['below_min']); self.assertEqual(pl['waves_max'], 1)
        self.assertTrue(pl['verifier_thin']); self.assertFalse(C.plan(e, 20.0)['verifier_thin'])
        pl = C.plan(C.estimate(['code']), 2.0); self.assertTrue(pl['code_note'])
        old = C.C['trace_calibration']                                                    # the cap follows the config, no figure in the code
        C.C['trace_calibration'] = {'runs': [{'calls': 10, 'usd': 1.0}, {'calls': 30, 'usd': 2.0}, {'calls': 20, 'usd': 1.7}]}
        try:
            self.assertEqual(C.trace_model(), (0.05, 0.7))                                  # slope 0.05, intercept lifted to the run at 20 calls
            self.assertEqual(C.plan(e, 4.0)['cap'], int((3.0 - 0.7) / 0.05))
        finally: C.C['trace_calibration'] = old

    def test_trace_model_is_an_upper_envelope(self):
        per, fixed = C.trace_model(); runs = C.C['trace_calibration']['runs']
        self.assertGreater(per, 0); self.assertGreaterEqual(len(runs), 2)
        for r in runs: self.assertLessEqual(r['usd'], fixed + per * r['calls'] + 1e-9, r)     # no measured run above the model
        self.assertLess(abs(min(fixed + per * r['calls'] - r['usd'] for r in runs)), 0.01)  # and the envelope touches one of them
        with self.assertRaises(ValueError): C.trace_model([{'calls': 20, 'usd': 1.0}, {'calls': 20, 'usd': 2.0}])
        self.assertEqual(C.trace_model([{'calls': 10, 'usd': 2.0}, {'calls': 30, 'usd': 1.0}])[0], 0.0)   # never a negative cost per call

    def test_state_read_by_gateway_and_verifier(self):
        import gateway as gw, verifier as V   # noqa: E401
        tmp = pathlib.Path(tempfile.mkdtemp())
        try:
            st = tmp / 'run' / 'state'
            self.assertIsNone(gw.budget_cap(st)); self.assertIsNone(V.budget_limit(None, st))
            self.assertEqual(gw.Gateway([], T='2019-01-01', state=st).cap, C.CAP)            # no budget: unchanged
            o = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'cost.py'), '--plugin', 'biology', '--text', 'As of 2019? Budget 2 USD.',
                                '--state', str(st), '--json'], capture_output=True, text=True)
            self.assertEqual(o.returncode, 0, o.stderr); pl = json.loads(o.stdout)['budget']
            doc = json.loads((st / 'budget.json').read_text())
            self.assertEqual((doc['budget_usd'], doc['cap'], doc['verifier_usd']), (2.0, pl['cap'], pl['verifier_usd']))
            self.assertLess(pl['cap'], C.CAP)
            self.assertEqual(gw.Gateway([], T='2019-01-01', state=st).cap, pl['cap'])        # the gateway takes the budget cap
            self.assertEqual(gw.Gateway([], T='2019-01-01', state=st, cap=50).cap, 50)       # an explicit --cap wins
            low = tmp / 'p.md'; low.write_text('# P\n## Sources\n```sources\nengines: openalex\ncap: 5\n```\n', encoding='utf-8')
            self.assertEqual(gw.Gateway([low], T='2019-01-01', state=st).cap, 5)             # never raises a lower plugin cap
            self.assertEqual(V.budget_limit(None, st), pl['verifier_usd']); self.assertEqual(V.budget_limit(0.7, st), 0.7)
            (st / 'budget.json').write_text('not json'); self.assertIsNone(gw.budget_cap(st)); self.assertIsNone(V.budget_limit(None, st))
            o = subprocess.run([sys.executable, '-I', str(P.parent / 'tools' / 'cost.py'), '--plugin', 'biology', '--state', str(tmp / 's2')], capture_output=True, text=True)
            self.assertFalse((tmp / 's2' / 'budget.json').exists())                          # no budget: nothing written
        finally: shutil.rmtree(tmp)

    def test_cli(self):
        t = str(P.parent / 'tools' / 'cost.py')
        o = subprocess.run([sys.executable, '-I', t, '--plugin', 'cs-ai', '--fulltext', '--lang', 'fr'], capture_output=True, text=True)
        self.assertEqual(o.returncode, 0); self.assertIn('Coût estimé', o.stdout); self.assertIn('Confirmer', o.stdout)
        o = subprocess.run([sys.executable, '-I', t, '--plugin', 'cs-ai', '--text', 'budget 1 USD', '--json'], capture_output=True, text=True)
        j = json.loads(o.stdout); self.assertTrue(j['budget']['reduced']); self.assertEqual(j['budget']['budget_usd'], 1.0)
        o = subprocess.run([sys.executable, '-I', t, '--plugin', 'biology', '--text', 'Budget 2 USD'], capture_output=True, text=True)
        self.assertIn('verification included', o.stdout); self.assertIn('reserved for the verifier', o.stdout)
        o = subprocess.run([sys.executable, '-I', t, '--text', 'max 20 € please'], capture_output=True, text=True)
        self.assertIn('par', o.stdout)


if __name__ == '__main__':
    unittest.main()
