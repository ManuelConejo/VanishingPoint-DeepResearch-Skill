#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests of tools/contradictor.py without network, real model or cost: a fake OpenAI-compatible endpoint (local HTTP server, reached
through VP_CONTRADICTOR_URL_<PROVIDER> and through a provider added by VP_CONTRADICTOR_PROVIDERS), a fake Codex executable for the
`openai` family (VP_MODEL_COMMAND_OPENAI) and a fake claude executable for the `claude` family, the match call and the rereads
(VP_MODEL_COMMAND_CLAUDE). A synthetic run directory holds REPORT.md, scope.md and the whole-reading material.
Checked: option absent (no family), material missing, key missing (credential_missing, never the key value), a provider without
key, an unknown provider or family, the mechanical statuses (quotation not found, reference missing, X side absent), the match
call (not exclusive), the rereads (false detected, false added, miss verified, miss false), a non-JSON answer, the cut of Y at the
cap (declared), the receipts, --prompts-only, the resolution of the families (argument, environment, ~/.config/vp/contradictors),
no model name anywhere unless the user gives one."""
import http.server, json, os, pathlib, subprocess, sys, tempfile, threading, unittest
P = pathlib.Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(P)); import contradictor as C  # noqa: E402

SHA_X = '0123456789abcdef0123456789abcdef01234567'; SHA_Y = 'fedcba9876543210fedcba9876543210fedcba98'
FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, sys
p = sys.stdin.read()
assert "--tools" in sys.argv and sys.argv[sys.argv.index("--tools") + 1] == "", sys.argv
cap = float(sys.argv[sys.argv.index("--max-budget-usd") + 1])
assert cap <= 0.4 or ('"false_claims"' in p and "# REPORT" in p), sys.argv   # rereads capped per call, the contradictor call at the run ceiling
assert "--model" not in sys.argv or sys.argv[sys.argv.index("--model") + 1] != "", sys.argv   # an empty model is stripped, never passed
if '"false_claims"' in p and "# REPORT" in p:
    txt = json.dumps({"false_claims": [], "missed": [{"claim": "claude miss: genuinely missing retry", "refs_Y": ["lib/evidence.py:1@SHA_Y12"], "refs_X": ["core/proof.py:2@SHA_X12"], "why": "w"}]}).replace("SHA_Y12", "%s").replace("SHA_X12", "%s") % (SHA_Y12, SHA_X12)
elif "## List B" in p:
    ids = []
    for chunk in p.split("## List B")[1].split("### ")[1:]:
        bid, body = chunk.split("\n", 1)
        if "already stated" in body: ids.append(bid.strip())
    txt = json.dumps({"pairs": [{"A": "A1", "B": b} for b in ids], "justification": "fake"})
elif "# Quotation from the report" in p:
    txt = "CONTRADICTED" if "really wrong" in p else "NOT CONTRADICTED"
else:
    txt = "FOUND" if "genuinely missing" in p else "ABSENT"
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}}))
print(json.dumps({"type": "result", "subtype": "success", "result": txt, "total_cost_usd": 0.02, "num_turns": 1,
                  "usage": {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 0, "output_tokens": 3}}))
'''.replace('SHA_X12', repr(SHA_X[:12])).replace('SHA_Y12', repr(SHA_Y[:12]))
FAKE_CODEX = r'''#!/usr/bin/env python3
import json, sys
p = sys.stdin.read()
assert sys.argv[-1] == "-" and "exec" in sys.argv, sys.argv
assert "-m" not in sys.argv or sys.argv[sys.argv.index("-m") + 1] != "", sys.argv
assert "# REPORT" in p and "# Y" in p and "# X" in p
txt = json.dumps({"false_claims": [{"quote": "X writes the verdicts without the notes", "evidence": ["core/state.py:2@%s"], "why": "codex: really wrong, see line 2"}],
                  "missed": [{"claim": "codex miss: genuinely missing audit trail", "refs_Y": ["lib/evidence.py:1@%s"], "refs_X": ["core/proof.py:1@%s"], "why": "assemble"}]}) % (SHA_X12, SHA_Y12, SHA_X12)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": txt}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 500, "output_tokens": 50}}))
'''.replace('SHA_X12', repr(SHA_X[:12])).replace('SHA_Y12', repr(SHA_Y[:12]))

ANSWER_A = {"false_claims": [
    {"quote": "X writes the verdicts without the notes", "evidence": [f"core/state.py:2@{SHA_X[:12]}"], "why": "really wrong: the notes are written"},
    {"quote": "this sentence is nowhere in the report", "evidence": [f"core/state.py:1@{SHA_X[:12]}"], "why": "x"},
    {"quote": "the proof module returns one", "evidence": [f"core/missing.py:1@{SHA_X[:12]}"], "why": "y"},
    {"quote": "a fourth one beyond the cap", "evidence": [f"core/state.py:1@{SHA_X[:12]}"], "why": "z"}],
    "missed": [
    {"claim": "vendor-a miss: genuinely missing evidence chain", "refs_Y": [f"lib/evidence.py:2@{SHA_Y[:12]}"], "refs_X": [f"core/proof.py:2@{SHA_X[:12]}"], "why": "a"},
    {"claim": "the state class (already stated by the report)", "refs_Y": [f"lib/evidence.py:1@{SHA_Y[:12]}"], "refs_X": [f"core/state.py:1@{SHA_X[:12]}"], "why": "b"},
    {"claim": "no X side at all", "refs_Y": [f"lib/evidence.py:1@{SHA_Y[:12]}"], "refs_X": [], "why": "c"},
    {"claim": "an absent one", "refs_Y": [f"lib/evidence.py:1@{SHA_Y[:12]}"], "refs_X": [f"core/proof.py:1@{SHA_X[:12]}"], "why": "d"}]}
KEYS_OK = {'Bearer FAKE-OPENROUTER-KEY-0123', 'Bearer FAKE-ACME-KEY-4567'}


class FakeEndpoint(http.server.BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0); body = json.loads(self.rfile.read(n))
        auth = self.headers.get('Authorization')
        FakeEndpoint.calls.append(dict(path=self.path, auth=auth, model=body['model'], temperature=body.get('temperature'), max_tokens=body.get('max_tokens'),
                                       reasoning=body.get('reasoning'), prompt=body['messages'][0]['content']))
        if auth is not None and auth not in KEYS_OK: self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":"no"}'); return
        content = json.dumps(ANSWER_A) if 'vendor-a' in body['model'] else 'Sorry, I cannot answer in JSON.'
        usage = {'cost': 0.25, 'prompt_tokens': 10, 'completion_tokens': 5} if self.path.startswith('/openrouter') else {'prompt_tokens': 10, 'completion_tokens': 5}
        out = json.dumps({'choices': [{'message': {'content': content}}], 'usage': usage}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a): pass


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(('127.0.0.1', 0), FakeEndpoint); cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        for name, body in (('fake-claude', FAKE_CLAUDE), ('fake-codex', FAKE_CODEX)):
            f = self.d / name; f.write_text(body); f.chmod(0o755)
        keys = ('VP_MODEL_COMMAND_CLAUDE', 'VP_MODEL_COMMAND_OPENAI', 'VP_HOST', 'VP_MODEL', 'VP_CONTRADICTORS', 'VP_CONTRADICTOR_URL_OPENROUTER', 'VP_CONTRADICTOR_PROVIDERS',
                'OPENROUTER_API_KEY', 'GEMINI_API_KEY', 'ACME_KEY', 'HOME')
        self.env0 = {k: os.environ.get(k) for k in keys}
        for k in keys: os.environ.pop(k, None)
        os.environ['VP_MODEL_COMMAND_CLAUDE'] = json.dumps([str(self.d / 'fake-claude'), '-p', '--model', '{model}', '--output-format', 'json'])
        os.environ['VP_MODEL_COMMAND_OPENAI'] = json.dumps([str(self.d / 'fake-codex'), 'exec', '-m', '{model}', '--json', '-'])
        base = f'http://127.0.0.1:{self.port}'
        os.environ['VP_CONTRADICTOR_URL_OPENROUTER'] = base + '/openrouter/v1/chat/completions'
        os.environ['VP_CONTRADICTOR_PROVIDERS'] = json.dumps({'acme': {'url': base + '/acme/v1/chat/completions', 'key': 'ACME_KEY'}, 'local': {'url': base + '/local/v1/chat/completions', 'key': None}})
        os.environ['HOME'] = str(self.d / 'home'); (self.d / 'home').mkdir()
        FakeEndpoint.calls.clear()
        run = self.d / 'run'; wr = run / 'state' / 'whole-reading'; wr.mkdir(parents=True); self.run = run
        (run / 'scope.md').write_text(f'# scope.md\n\nQuestion (verbatim): "Does Y bring something to X?"\nT = 2026-10-20\n\n- X : /x/host@{SHA_X} ; target = the state layer\n- Y : owner/repo@{SHA_Y}\nTarget: the state layer\n')
        (run / 'REPORT.md').write_text('# Report\n\n## Executive Summary\n\nThe comparison shows that X writes the verdicts without the notes [1].\n\n## Main Analysis\n\n'
                                       '### Finding 1 — The state class is present (GO)\n\nX has a State class [1]. The proof module returns one [2].\n\n'
                                       '### Finding 2 — Runner (WATCH)\n\nThe runner loops [3].\n\n## Bibliography\n\n[1] core/state.py@' + SHA_X + '\n')
        (wr / 'material-X.txt').write_text(f'# X = host@{SHA_X[:12]} - 2 whole files. Expected citation: <path>:<line>@{SHA_X[:12]}\n\n'
                                           f'=== core/state.py @{SHA_X[:12]} (3 lines) ===\n1\tclass State:\n2\t    notes = write_notes()\n3\t    pass\n\n'
                                           f'=== core/proof.py @{SHA_X[:12]} (2 lines) ===\n1\tdef proof():\n2\t    return 1\n\n')
        big = ''.join(f'=== lib/file{i}.py @{SHA_Y[:12]} (2 lines) ===\n1\tx = {i}\n2\ty = {i}\n\n' for i in range(60))
        (wr / 'material-Y.txt').write_text(f'# Y tree\nlib/evidence.py\n\n=== lib/evidence.py @{SHA_Y[:12]} (2 lines) ===\n1\tclass Evidence:\n2\t    chain = []\n\n' + big)

    def tearDown(self):
        for k, v in self.env0.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.tmp.cleanup()

    def tool(self, *args, rc=0):
        r = subprocess.run([sys.executable, '-I', str(P / 'contradictor.py'), str(self.run), *args], capture_output=True, text=True, env=os.environ, timeout=120)
        self.assertEqual(r.returncode, rc, r.stderr + r.stdout)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def receipt(self): return json.loads((self.run / 'contradictor.json').read_text())


class Contradictor(Base):
    def test_absent_without_family(self):
        s = self.tool(); self.assertEqual(s['status'], 'absent'); self.assertEqual(self.receipt()['status'], 'absent')
        self.assertFalse((self.run / 'state' / 'contradictor' / 'PROMPT.md').exists()); self.assertEqual(FakeEndpoint.calls, [])

    def test_material_missing(self):
        (self.run / 'state' / 'whole-reading' / 'material-Y.txt').unlink()
        s = self.tool('--families', 'openrouter:vendor-a/model'); self.assertEqual(s['status'], 'skipped'); self.assertIn('whole_reading.py', s['note']); self.assertEqual(FakeEndpoint.calls, [])

    def test_key_missing_never_shown(self):
        s = self.tool('--families', 'openrouter:vendor-a/model', 'gemini:some-model')
        self.assertEqual(s['status'], 'done'); self.assertEqual(s['families'], {'openrouter:vendor-a/model': 'credential_missing', 'gemini:some-model': 'credential_missing'})
        self.assertEqual(FakeEndpoint.calls, []); self.assertEqual(s['false_detected'], 0)
        r = self.receipt(); self.assertIn('OPENROUTER_API_KEY', r['families']['openrouter:vendor-a/model']['note']); self.assertIn('GEMINI_API_KEY', r['families']['gemini:some-model']['note'])
        self.assertEqual(r['cost_usd']['total'], 0)

    def test_prompts_only_and_y_cut(self):
        s = self.tool('--families', 'openai', '--prompts-only', '--y-cap', '600')
        self.assertEqual(s['status'], 'prompts'); self.assertTrue(s['y_truncated']); self.assertGreater(s['y_files_not_included'], 0); self.assertEqual(FakeEndpoint.calls, [])
        p = (self.run / 'state' / 'contradictor' / 'PROMPT.md').read_text()
        self.assertIn('[Contradictor: Y cut at 600 characters', p); self.assertIn('NOT INCLUDED', p); self.assertIn('=== lib/evidence.py @', p)
        self.assertIn('Date of the request (T): 2026-10-20', p); self.assertIn('"Does Y bring something to X?"', p); self.assertIn('Target X: the state layer', p)
        self.assertIn(f'<path>:<line>@{SHA_Y[:12]} for Y; <path>:<line>@{SHA_X[:12]} for X', p); self.assertIn('# REPORT\n\n# Report', p)
        for k in ('{REPORT}', '{Y}', '{X}', '{T}', '{REQUEST}', '{Y_FORM}', '{X_SHA}'): self.assertNotIn(k, p)
        self.assertEqual(self.receipt()['status'], 'prompts')

    def test_full_run_three_families(self):
        os.environ['OPENROUTER_API_KEY'] = 'FAKE-OPENROUTER-KEY-0123'; os.environ['ACME_KEY'] = 'FAKE-ACME-KEY-4567'
        s = self.tool('--families', 'openrouter:vendor-a/model', 'acme:vendor-b/model', 'openai', '--model', 'test-reread')
        self.assertEqual(s['status'], 'done', s)
        self.assertEqual(s['families'], {'openrouter:vendor-a/model': 'ok (4 false, 4 missed)', 'acme:vendor-b/model': 'answer is not the expected JSON', 'openai': 'ok (1 false, 1 missed)'})
        self.assertEqual([(c['path'].split('/')[1], c['model']) for c in FakeEndpoint.calls], [('openrouter', 'vendor-a/model'), ('acme', 'vendor-b/model')])
        self.assertTrue(all(c['temperature'] == 0 and c['max_tokens'] == 8000 for c in FakeEndpoint.calls)); self.assertIn('# REPORT', FakeEndpoint.calls[0]['prompt'])
        self.assertEqual(FakeEndpoint.calls[0]['reasoning'], {'effort': 'low'}); self.assertIsNone(FakeEndpoint.calls[1]['reasoning'])   # provider "extra" only for openrouter
        r = self.receipt(); st = {(e['family'].split(':')[0], e['kind'], e['i']): e['status'] for e in r['elements']}
        self.assertEqual(st[('openrouter', 'false', 1)], 'false detected'); self.assertEqual(st[('openrouter', 'false', 2)], 'false added: quotation not found in the report')
        self.assertEqual(st[('openrouter', 'false', 3)], 'false added: reference missing from the material'); self.assertNotIn(('openrouter', 'false', 4), st)   # cap 3 per list
        self.assertEqual(st[('openrouter', 'miss', 1)], 'miss verified'); self.assertEqual(st[('openrouter', 'miss', 2)], 'not exclusive: already stated in the report')
        self.assertEqual(st[('openrouter', 'miss', 3)], 'miss false: X side absent'); self.assertNotIn(('openrouter', 'miss', 4), st)
        self.assertEqual(st[('openai', 'false', 1)], 'false detected'); self.assertEqual(st[('openai', 'miss', 1)], 'miss verified')
        self.assertEqual(s['false_detected'], 2); self.assertEqual(s['misses_verified'], 2)
        self.assertEqual([f['family'] for f in r['false_detected']], ['openrouter:vendor-a/model', 'openai']); self.assertGreaterEqual(r['false_detected'][0]['position'], 0)
        self.assertEqual(r['cost_usd']['contradictors'], 0.25); self.assertEqual(r['cost_usd']['rereads'], round(0.02 * 5, 4))   # 1 match + 2 false + 2 miss rereads
        self.assertEqual(r['reread'], {'host': 'claude', 'model': 'test-reread'})
        self.assertEqual((r['families']['openai']['via'], r['families']['openai']['kind'], r['families']['openai']['model'], r['families']['openai']['usd']), ('openai', 'cli', '(host default)', 0.0))
        self.assertTrue(r['families']['openrouter:vendor-a/model']['cost_known']); self.assertFalse(r['families']['acme:vendor-b/model']['cost_known'])
        d = self.run / 'state' / 'contradictor'
        self.assertTrue((d / 'openrouter_vendor-a_model.json').exists() and (d / 'acme_vendor-b_model.json').exists() and (d / 'openai.json').exists() and (d / 'match.trace.jsonl').exists())
        self.assertEqual(len(list(d.glob('reread-*.trace.jsonl'))), 4)
        blob = ''.join(f.read_text(errors='replace') for f in list(d.iterdir()) + [self.run / 'contradictor.json'] if f.is_file())
        self.assertNotIn('FAKE-OPENROUTER-KEY', blob); self.assertNotIn('FAKE-ACME-KEY', blob)
        self.assertEqual((self.run / 'REPORT.md').read_text()[:8], '# Report')   # the tool never edits the report
        self.assertIn('apply:', r['note'])

    def test_provider_without_key_and_claude_family(self):
        s = self.tool('--families', 'local:vendor-a/model', 'claude:some-model')
        self.assertEqual(s['status'], 'done', s); self.assertEqual(s['families'], {'local:vendor-a/model': 'ok (4 false, 4 missed)', 'claude:some-model': 'ok (0 false, 1 missed)'})
        self.assertEqual([c['auth'] for c in FakeEndpoint.calls], [None])   # no key: no Authorization header
        r = self.receipt(); self.assertEqual((r['families']['claude:some-model']['via'], r['families']['claude:some-model']['model']), ('claude', 'some-model'))
        self.assertEqual(r['reread']['model'], '(host default)'); self.assertEqual(r['cost_usd']['contradictors'], 0.02)
        self.assertTrue((self.run / 'state' / 'contradictor' / 'claude_some-model.json').exists()); self.assertEqual(s['misses_verified'], 2)

    def test_budget_stops_rereads(self):
        os.environ['OPENROUTER_API_KEY'] = 'FAKE-OPENROUTER-KEY-0123'
        s = self.tool('--families', 'openrouter:vendor-a/model', '--max-usd', '0.43')    # match call 0.02, then exactly one reread fits (0.02 + 0.4)
        r = self.receipt(); statuses = [e['status'] for e in r['elements']]
        self.assertEqual(statuses.count('not reread: contradictor budget reached'), 1); self.assertEqual(statuses.count('false detected'), 1)
        self.assertEqual(len(list((self.run / 'state' / 'contradictor').glob('reread-*.trace.jsonl'))), 1); self.assertEqual(s['status'], 'done')
        self.tool('--families', 'openrouter:vendor-a/model', '--max-usd', '0.1')         # not even the match call
        self.assertFalse(any(e['status'].startswith('miss verified') or e['status'] == 'not exclusive: already stated in the report' for e in self.receipt()['elements']))

    def test_hostile_inputs(self):
        os.environ['OPENROUTER_API_KEY'] = 'FAKE-OPENROUTER-KEY-0123'
        rep = self.run / 'REPORT.md'; rep.write_text(rep.read_text() + '\nA template literal {X} and {REPORT} and {Y} in the report.\n')
        self.tool('--families', 'openai', '--prompts-only')
        p = (self.run / 'state' / 'contradictor' / 'PROMPT.md').read_text()
        self.assertEqual(p.count('class State:'), 1); self.assertIn('literal {X} and {REPORT} and {Y}', p)   # one-pass substitution
        self.assertEqual(C.as_list({'quote': 'q'}), [{'quote': 'q'}]); self.assertEqual(C.as_list(3), []); self.assertEqual(C.as_list(None), [])
        self.assertEqual(C.first_verdict('UNCONTRADICTED', ('NOT CONTRADICTED', 'CONTRADICTED')), 'UNDECIDED')
        self.assertEqual(C.first_verdict('**CONTRADICTED**\nbecause', ('NOT CONTRADICTED', 'CONTRADICTED')), 'CONTRADICTED')
        self.assertEqual(C.first_verdict('UNFOUNDED', ('NOT FOUND', 'FOUND', 'ABSENT')), 'UNDECIDED')
        os.environ['VP_CONTRADICTOR_PROVIDERS'] = json.dumps({'plain': {'url': 'http://example.invalid/v1/chat/completions', 'key': 'OPENROUTER_API_KEY'}})
        s = self.tool('--families', 'plain:m'); self.assertEqual(s['families']['plain:m'], 'insecure_url')   # a key never goes over plain http
        (self.d / 'home' / '.config' / 'vp').mkdir(parents=True); (self.d / 'home' / '.config' / 'vp' / 'contradictors').write_text('  # nothing\n\n')
        self.assertEqual(C.families(), [])                                                      # blank file = absent, config decides

    def test_unknown_family_or_provider(self):
        os.environ['OPENROUTER_API_KEY'] = 'FAKE-OPENROUTER-KEY-0123'
        s = self.tool('--families', 'nope:m', 'openrouter', 'openrouter:vendor-a/model')
        self.assertIn('unknown family', s['families']['nope:m']); self.assertIn('openrouter', s['families']['nope:m']); self.assertIn('unknown family', s['families']['openrouter'])
        self.assertEqual(s['families']['openrouter:vendor-a/model'], 'ok (4 false, 4 missed)')


class Resolution(Base):
    def test_families_and_providers(self):
        self.assertEqual(C.families(), [])
        (self.d / 'home' / '.config' / 'vp').mkdir(parents=True); (self.d / 'home' / '.config' / 'vp' / 'contradictors').write_text('openrouter:a/b, openai\n# comment\nopenrouter:a/b\n')
        self.assertEqual(C.families(), ['openrouter:a/b', 'openai'])
        os.environ['VP_CONTRADICTORS'] = 'Claude:Model-X,openai'; self.assertEqual(C.families(), ['claude:model-x', 'openai'])
        self.assertEqual(C.families(['openai']), ['openai'])
        self.assertEqual(C.family_spec('openai'), {'via': 'openai', 'model': '', 'kind': 'cli'}); self.assertEqual(C.family_spec('claude:m')['model'], 'm')
        self.assertIsNone(C.family_spec('x:m')); self.assertIsNone(C.family_spec('openrouter')); self.assertEqual(C.family_spec('Gemini:a/b')['provider']['key'], 'GEMINI_API_KEY')
        self.assertEqual(C.family_spec('acme:z')['kind'], 'http'); self.assertIsNone(C.family_spec('local:z')['provider']['key'])
        for name in ('openrouter', 'gemini', 'openai-api', 'mistral', 'ollama', 'acme', 'local'): self.assertIn(name, C.providers())
        self.assertEqual(C.strip_model(['claude', '-p', '--model', '', '--output-format', 'json']), ['claude', '-p', '--output-format', 'json'])
        self.assertEqual(C.strip_model(['codex', 'exec', '-m', 'x', '-']), ['codex', 'exec', '-m', 'x', '-'])
        cfg = json.loads((P / 'config.json').read_text())['contradictor']
        self.assertEqual(cfg['families'], []); self.assertNotIn('models', cfg)
        self.assertFalse(any(k == 'model' for v in cfg['providers'].values() for k in v))   # no model name in the config

    def test_quote_and_refs(self):
        rep = 'Alpha beta.  The  “runner” loops twice [3]. Gamma.'
        self.assertEqual(C.find_quote('the "runner" loops twice', rep)[::2], (True, 'substring'))
        self.assertEqual(C.find_quote('the runner loops thrice [3]', rep)[0], True)       # difflib window
        self.assertFalse(C.find_quote('completely different words here', rep)[0])
        xb = C.parse_material(f'=== a/b/c.py @{SHA_X[:12]} (2 lines) ===\n1\tx\n2\ty\n\n'); yb = C.parse_material('=== arxiv:2501.01234v1 (3 lines) ===\n1\ta\n2\tb\n3\tc\n')
        refs = C.parse_refs([f'b/c.py:2@{SHA_X[:8]}', f'a/b/c.py:3@{SHA_X[:12]}', 'arxiv:2501.01234v1 (line 3)', 'arxiv:2501.01234v1, lines 2-4', f'zz.py:1@{SHA_X[:12]}'], xb, yb)
        self.assertEqual([(r['side'], r['exists']) for r in refs], [('X', True), ('X', False), ('Y', True), ('Y', False), ('unknown', False)])
        ex = C.extracts(refs, xb, yb); self.assertIn('=== a/b/c.py @' + SHA_X[:12] + ' (lines 1-2 of 2)', ex); self.assertIn('=== arxiv:2501.01234v1  (lines 1-3 of 3)', ex)
        y, excl = C.truncate_y('head\n' + ''.join(f'=== f{i}.py @{SHA_Y[:12]} (1 lines) ===\n1\tz\n\n' for i in range(10)), 120)
        self.assertTrue(excl); self.assertIn('NOT INCLUDED', y); self.assertLess(len(y) - y.index('\n\n') - 2, 125)


if __name__ == '__main__':
    unittest.main()
