#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests of the run mechanics of v0.5.1 (no network, no model: gateway readings, full-text fetcher and model command are stubbed).
1. Verifier budget: the verifier's gateway readings go to their own pool (counter-<run>.verifier.txt, cap config verifier.call_cap or
   --cap), so a search cap already reached never turns the claims into SOURCE-UNAVAILABLE; the pool cap is a named config parameter;
   journal lines and run.json carry the pool; no model name is fixed for the nested verifier (config '' = the host CLI's default).
2. Full text and end steps triggered by the tools: with --T the verifier fetches the pinned full text by default (config verifier.fulltext),
   sources carrying the most claims first, at most verifier.fulltext_cap attempts, outcome per source in the output and in
   state/verifier.json; --no-fulltext and no T switch it off. finish_run.py writes state/finish_run.json; validate_card.py on the
   command line (check 13) refuses a gateway run without it or whose files changed after it, and says which command to run.
3. Paths: the tools run from any directory; --plugin takes plugins/<d>.md (from the skill directory) or a bare name; an unknown plugin,
   a missing card or a missing run directory stop with exit 2 and a one-line message, never a traceback.
Run: python3 -I tests/test_run_mechanics.py"""
import contextlib, io, json, os, pathlib, shutil, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
SKILL = P.parent
TOOLS = SKILL / 'tools'
sys.path.insert(0, str(TOOLS))
import gateway as gw, verifier as V, finish_run as F, validate_card as VC   # noqa: E401,E402

T = '2024-01-01'
CARD = {'card_id': 'mech', 'question': 'q?',
        'sources': {'S1': {'doi': '10.1/one', 'title': 'One'}, 'S2': {'arxiv': '2301.00001', 'title': 'Two'}, 'S3': {'pmid': '123', 'title': 'Three'}},
        'claims': [{'id': 'A1', 'text': 'one says 1', 'source': {'key': 'S1'}, 'location': 'abstract'},
                   {'id': 'A2', 'text': 'two says 2', 'source': {'key': 'S2'}, 'location': 'abstract'},
                   {'id': 'A3', 'text': 'two says 3', 'source': {'key': 'S2'}, 'location': 'abstract'},
                   {'id': 'A4', 'text': 'three says 4', 'source': {'key': 'S3'}, 'location': 'abstract'}]}
FAKE_MODEL = '''import json, os, sys
argv = sys.argv[1:]
json.dump({"argv": argv}, open(os.environ["VP_FAKE_RECORD"], "w"))
card = json.load(open("card.json"))
print(json.dumps({"result": json.dumps({"card_id": card["card_id"], "verdicts": [{"id": c["id"], "verdict": "ABSENT", "fragments": []} for c in card["claims"]]}),
                  "usage": {}, "total_cost_usd": 0}))
'''


def fake_read(ident, B):
    """Gateway reading without network: a dated record with an abstract."""
    return {'id': ident, 'title': 'T ' + ident, 'abstract': 'Abstract of ' + ident + ' says something.'}


def env(home):
    return {'PATH': '/usr/bin:/bin', 'HOME': str(home)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='vp-mech-'))
        self.saved_env = {k: os.environ.get(k) for k in ('VP_MODEL', 'VP_HOST', 'VP_MODEL_COMMAND_CLAUDE', 'VP_FAKE_RECORD', 'HOME')}
        self.saved_read = gw.read; gw.read = fake_read
        self.saved_run = V.subprocess.run

    def tearDown(self):
        gw.read = self.saved_read; V.subprocess.run = self.saved_run
        for k, v in self.saved_env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        shutil.rmtree(self.tmp)

    def fake_model(self):
        f = self.tmp / 'fake_model.py'; f.write_text(FAKE_MODEL)
        os.environ['VP_MODEL_COMMAND_CLAUDE'] = json.dumps([sys.executable, '-I', str(f), '-p', '--model', '{model}'])
        os.environ['VP_FAKE_RECORD'] = str(self.tmp / 'record.json'); os.environ['VP_HOST'] = 'claude'; os.environ.pop('VP_MODEL', None)

    def verify_main(self, *args):
        argv = sys.argv
        sys.argv = ['verifier.py', 'verify', '--card', str(self.tmp / 'card.json'), '--out', str(self.tmp / 'verdicts.json'),
                    '--run', 'mech', '--state', str(self.tmp / 'state'), '--sources', str(self.tmp / 'sources'), '--work', str(self.tmp / 'work'), *args]
        try:
            with contextlib.redirect_stdout(io.StringIO()): V.main()
        finally: sys.argv = argv
        return json.loads((self.tmp / 'verdicts.json').read_text())


class VerifierBudget(Base):
    def test_config_names_the_parameters(self):
        c = json.loads((TOOLS / 'config.json').read_text())['verifier']
        self.assertIsInstance(c['call_cap'], int); self.assertGreater(c['call_cap'], 0)
        self.assertIsInstance(c['fulltext'], bool); self.assertIsInstance(c['fulltext_cap'], int)
        self.assertEqual(set(c['model'].values()), {''})              # no model name fixed: the host CLI's default
        self.assertIn('call_cap', c['note']); self.assertIn('fulltext_cap', c['note'])

    def test_pool_has_its_own_counter_and_cap(self):
        st = self.tmp / 'state'
        g = gw.Gateway([], T=T, run='r', state=st, cap=2)
        self.assertIn('call', g.read('doi:10.1/a')); self.assertIn('call', g.read('doi:10.1/b'))
        self.assertIn('CAP', g.read('doi:10.1/c')['refusal'])        # the searches' cap is reached
        v = gw.Gateway([], T=T, run='r', state=st, pool='verifier')
        self.assertEqual(v.cap, json.loads((TOOLS / 'config.json').read_text())['verifier']['call_cap'])
        r = v.read('doi:10.1/c'); self.assertEqual((r['call'], r['pool']), (1, 'verifier'))
        self.assertEqual((st / 'counter-r.txt').read_text(), '2'); self.assertEqual((st / 'counter-r.verifier.txt').read_text(), '1')
        small = gw.Gateway([], T=T, run='r', state=st, pool='verifier', cap=1)
        ref = small.read('doi:10.1/d')['refusal']; self.assertIn('verifier budget', ref); self.assertIn('verifier.call_cap', ref)
        lines = [json.loads(l) for l in (st / 'journal.jsonl').read_text().splitlines()]
        self.assertEqual([l.get('pool') for l in lines], [None, None, 'verifier'])
        (self.tmp / 'run').mkdir(); shutil.copytree(st, self.tmp / 'run' / 'state')
        self.assertEqual(VC.header(self.tmp / 'run')['calls_per_pool'], {'search': 2, 'verifier': 1})
        with self.assertRaises(ValueError): gw.Gateway([], T=T, run='r', state=st, pool='no-such-pool')   # a pool without a named cap

    def test_search_cap_reached_does_not_starve_the_verifier(self):
        self.fake_model(); (self.tmp / 'card.json').write_text(json.dumps(CARD))
        (self.tmp / 'state').mkdir(); (self.tmp / 'state' / 'counter-mech.txt').write_text('60')   # searches used the whole cap
        res = self.verify_main('--T', T, '--no-fulltext')
        self.assertEqual(res['summary']['SOURCE-UNAVAILABLE'], 0)
        self.assertEqual(res['summary']['ABSENT'], 4)
        self.assertEqual(res['sources_read']['gateway']['pool'], 'verifier')
        self.assertEqual((self.tmp / 'state' / 'counter-mech.verifier.txt').read_text(), '3')    # one reading per cited source
        rec = json.loads((self.tmp / 'record.json').read_text())
        sm = os.environ.get('VP_SEARCH_MODEL') or V.CONFIG.get('search_model', '')
        self.assertEqual(rec['argv'][rec['argv'].index('--model') + 1] if '--model' in rec['argv'] else '', sm)   # '' -> the search model (section 0)
        res = self.verify_main('--T', T, '--no-fulltext', '--cap', '1', '--run', 'mech2', '--sources', str(self.tmp / 'sources2'))
        un = [c['id'] for c in res['claims'] if c['status'] == 'SOURCE-UNAVAILABLE']
        self.assertEqual(un, ['A1', 'A4'])                                                       # S2 (2 claims) read first, S1 and S3 refused
        self.assertTrue(all('verifier budget' in c['discrepancy'] for c in res['claims'] if c['id'] in un))


class FulltextAndEndSteps(Base):
    def fake_fetch(self, outcome):
        calls = []

        def run(argv, **kw):
            if not str(argv[2]).endswith('fetch_fulltext.py'): return self.saved_run(argv, **kw)
            out = pathlib.Path(argv[argv.index('--out') + 1]); ident = argv[4]; calls.append(ident)
            st = outcome.get(ident, 'OK')
            meta = {'status': st, 'T': argv[argv.index('--T') + 1], 'T_rule': 'versions dated before T only', 'version': 'v1'}
            if st == 'OK': (out / 'source.txt').write_text('Full text of ' + ident)
            else: meta['reason'] = 'no open version before T'
            (out / 'meta.json').write_text(json.dumps(meta))
            return subprocess.CompletedProcess(argv, 0, '', '')
        V.subprocess.run = run
        return calls

    def test_order_and_cap(self):
        self.assertEqual(V.claim_order(CARD), ['S2', 'S1', 'S3'])                    # most claims first, then key order
        calls = self.fake_fetch({'10.1/one': 'REFUSED'})
        g = gw.Gateway([], T=T, run='x', state=self.tmp / 'st', pool='verifier')
        s = V.load_sources(CARD, None, g, True, out_dir=self.tmp / 'src', T=T, fulltext_cap=2)
        self.assertEqual(calls, ['2301.00001', '10.1/one'])                         # S2 then S1; S3 beyond the cap (pmid: no attempt anyway)
        self.assertEqual((s['S2']['origin'], s['S2']['fulltext']['status']), ('fulltext', 'OK'))
        self.assertEqual((s['S1']['origin'], s['S1']['fulltext']['status']), ('abstract', 'REFUSED'))   # failure counted, abstract kept
        r = V.sources_read(s)
        self.assertEqual((r['fulltext_attempted'], r['fulltext_obtained']), (2, 1))
        card = dict(CARD, sources=dict(CARD['sources'], S3={'doi': '10.1/three'}))
        calls.clear(); s = V.load_sources(card, None, g, True, out_dir=self.tmp / 'src2', T=T, fulltext_cap=2)
        self.assertEqual(s['S3']['fulltext']['status'], 'NOT-TRIED'); self.assertIn('verifier.fulltext_cap', s['S3']['fulltext']['reason'])
        self.assertEqual(V.sources_read(s)['fulltext_not_tried_cap'], 1)

    def test_default_on_with_T_and_switches(self):
        self.fake_model(); (self.tmp / 'card.json').write_text(json.dumps(CARD))
        calls = self.fake_fetch({})
        res = self.verify_main('--T', T)                                             # no flag: config verifier.fulltext
        self.assertEqual(V.FULLTEXT, json.loads((TOOLS / 'config.json').read_text())['verifier']['fulltext'])
        if V.FULLTEXT:
            self.assertEqual(calls, ['2301.00001', '10.1/one']); self.assertTrue(res['sources_read']['fulltext_mode'])
            self.assertEqual(res['sources_read']['origins']['fulltext'], 2)
        receipt = json.loads((self.tmp / 'state' / 'verifier.json').read_text())
        self.assertEqual(receipt['fulltext_attempted'], len(calls)); self.assertEqual(receipt['gateway']['pool'], 'verifier')
        calls.clear(); self.verify_main('--T', T, '--no-fulltext', '--sources', str(self.tmp / 'sources-b')); self.assertEqual(calls, [])
        calls.clear(); res = self.verify_main('--sources', str(self.tmp / 'sources-c')); self.assertEqual(calls, [])   # no T: never a full text
        self.assertFalse(res['sources_read']['fulltext_mode'])

    def test_finish_run_gate(self):
        d = self.tmp / 'run'; shutil.copytree(P / 'fixtures' / 'finish_run', d)

        def cli():
            p = subprocess.run([sys.executable, '-I', str(TOOLS / 'validate_card.py'), str(d)], capture_output=True, text=True, env=env(self.tmp))
            return p.returncode, p.stdout
        c, out = cli(); self.assertEqual(c, 1); self.assertIn('13 end steps not run', out); self.assertIn('tools/finish_run.py', out)
        (d / 'state' / 'verifier.json').write_text(json.dumps({'summary': {'FOUND': 3}, 'fulltext_mode': True, 'fulltext_attempted': 2, 'fulltext_obtained': 1,
                                                                'gateway': {'pool': 'verifier', 'cap': 60}}))
        with contextlib.redirect_stdout(io.StringIO()) as o: code = F.main([str(d), '--offline'])
        self.assertEqual(code, 0, o.getvalue()); self.assertIn('full text 1/2 obtained/attempted', o.getvalue())
        rc = json.loads((d / 'state' / 'finish_run.json').read_text())
        self.assertEqual(rc['inputs'], VC.fingerprints(d)); self.assertTrue(rc['validation_passed'])
        self.assertEqual([s['step'] for s in rc['steps']][0], 'validate_card --header')
        c, out = cli(); self.assertEqual((c, out.strip()), (0, 'OK'))
        with open(d / 'REPORT.md', 'a') as f: f.write('\nOne more sentence.\n')
        c, out = cli(); self.assertEqual(c, 1); self.assertIn('13 end steps stale: REPORT.md', out)
        (d / 'state' / 'journal.jsonl').unlink()                                     # injected mode: no journal, no end-step receipt required
        self.assertEqual(VC.end_problems(d), [])


class Paths(Base):
    def run_tool(self, args, cwd):
        return subprocess.run([sys.executable, '-I', *args], capture_output=True, text=True, cwd=cwd, env=env(self.tmp), timeout=120)

    def test_gateway_from_any_directory(self):
        elsewhere = self.tmp / 'project'; elsewhere.mkdir()
        for plug in ('plugins/cs-ai.md', 'cs-ai', 'cs-ai.md'):
            p = self.run_tool([str(TOOLS / 'gateway.py'), '--plugin', plug, '--T', T, '--state', 'state', 'sources'], elsewhere)
            self.assertEqual(p.returncode, 0, p.stderr); self.assertIn('openalex', json.loads(p.stdout)['engines'])
        rel = os.path.relpath(TOOLS / 'gateway.py', elsewhere)                        # a relative form of the script path works as well
        p = self.run_tool([rel, '--plugin', 'plugins/law.md', '--T', T, '--state', 'state', 'sources'], elsewhere); self.assertEqual(p.returncode, 0, p.stderr)
        p = self.run_tool(['tools/gateway.py', '--plugin', 'plugins/law.md', '--T', T, '--state', str(self.tmp / 'st2'), 'sources'], SKILL)
        self.assertEqual(p.returncode, 0, p.stderr)
        p = self.run_tool([str(TOOLS / 'gateway.py'), '--plugin', 'plugins/nope.md', '--T', T, 'sources'], elsewhere)
        self.assertEqual(p.returncode, 2); self.assertNotIn('Traceback', p.stderr)
        self.assertIn('plugin not found', p.stderr); self.assertIn('shipped: ', p.stderr); self.assertIn('cs-ai', p.stderr)

    def test_other_tools_messages(self):
        elsewhere = self.tmp / 'project'; elsewhere.mkdir()
        p = self.run_tool([str(TOOLS / 'check_keys.py'), '--plugin', 'plugins/law.md', '--json'], elsewhere)
        self.assertEqual(p.returncode, 0, p.stderr); self.assertEqual(json.loads(p.stdout)['plugins'][0]['plugin'], 'law')
        p = self.run_tool([str(TOOLS / 'check_keys.py'), '--plugin', 'lw', '--announce'], elsewhere)
        self.assertEqual(p.returncode, 2); self.assertIn('plugin not found', p.stderr); self.assertNotIn('Traceback', p.stderr)
        p = self.run_tool([str(TOOLS / 'verifier.py'), 'verify', '--card', 'card.json', '--out', 'v.json'], elsewhere)
        self.assertEqual(p.returncode, 2); self.assertIn('card not found', p.stderr); self.assertNotIn('Traceback', p.stderr)
        (elsewhere / 'card.json').write_text(json.dumps(CARD))
        p = self.run_tool([str(TOOLS / 'verifier.py'), 'verify', '--card', 'card.json', '--out', 'v.json', '--T', T, '--plugin', 'nope'], elsewhere)
        self.assertEqual(p.returncode, 2); self.assertIn('plugin not found', p.stderr); self.assertNotIn('Traceback', p.stderr)
        p = self.run_tool([str(TOOLS / 'validate_card.py'), 'no-such-run', '--header'], elsewhere)
        self.assertEqual(p.returncode, 2); self.assertIn('not a directory', p.stdout); self.assertNotIn('Traceback', p.stderr)
        self.assertFalse((elsewhere / 'no-such-run').exists())


if __name__ == '__main__':
    unittest.main()
