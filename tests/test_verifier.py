#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of verifier.py (fake engine, fake executables). Checks: role file and citation check used in place (tools/verifier/),
statuses FOUND / DISTORTED / ABSENT / INVALID / SOURCE-UNAVAILABLE / UNVERIFIED, single retry, split per source, sources through
the gateway (abstract), downstream filter rule, model_call for both host profiles (claude: argv after -p, tool restrictions,
JSON output; openai: prompt on stdin, JSONL event stream), config dir guard. Fixture texts are data (French figures kept as data)."""
import json, os, pathlib, stat, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
TOOLS = P.parent / 'tools'
sys.path.insert(0, str(TOOLS)); import verifier as V   # noqa: E702

CARD = {'card_id': 'C1', 'question': 'q?', 'sources': {'S1': {'doi': '10.1/a', 'title': 'Source A'}, 'S2': {'arxiv': '2401.00001', 'title': 'Source B'}, 'S3': {'doi': '10.1/c'}},
        'claims': [
            {'id': 'A1', 'text': 'M reaches 71.2 % on X.', 'source': {'key': 'S1'}, 'location': 'Tab. 2'},
            {'id': 'A2', 'text': 'M reaches 75 % on X.', 'source': {'key': 'S1'}, 'location': 'Tab. 2'},
            {'id': 'A3', 'text': 'M is evaluated on Y.', 'source': {'key': 'S1'}, 'location': ''},
            {'id': 'A4', 'text': 'B uses 5 examples.', 'source': {'arxiv': '2401.00001'}, 'location': ''},
            {'id': 'A5', 'text': 'C concludes Z.', 'source': {'key': 'S3'}, 'location': ''}]}
SRC = {'S1': {'text': 'Results. On the X set, method M reaches 71.2 % accuracy against 64.0 % for B.', 'origin': 'fulltext', 'note': '', 'desc': CARD['sources']['S1']},
       'S2': {'text': 'Source B\n\nWe use 5 in-context examples for the B baseline.', 'origin': 'abstract', 'note': '(record + abstract)', 'desc': CARD['sources']['S2']},
       'S3': {'text': '', 'origin': 'missing', 'note': 'after T', 'desc': {}}}

FAKE_CLAUDE = '''import json, os, sys
json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(), "anthropic": os.environ.get("ANTHROPIC_API_KEY"), "oauth": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")}, open(os.environ["VP_FAKE_RECORD"], "w"))
print(json.dumps({"result": "{\\"card_id\\": \\"C1\\", \\"verdicts\\": []}", "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 1, "output_tokens": 7}, "total_cost_usd": 0.12, "num_turns": 3}))
'''
FAKE_CODEX = '''import json, os, sys
prompt = sys.stdin.read()
json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": prompt, "anthropic": os.environ.get("ANTHROPIC_API_KEY")}, open(os.environ["VP_FAKE_RECORD"], "w"))
for ev in [{"type": "thread.started", "thread_id": "t1"}, {"type": "turn.started"},
           {"type": "item.completed", "item": {"id": "i1", "type": "reasoning", "text": "thinking"}},
           {"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "draft"}},
           {"type": "item.completed", "item": {"id": "i3", "type": "agent_message", "text": "{\\"card_id\\": \\"C1\\", \\"verdicts\\": [{\\"id\\": \\"A1\\"}]}"}},
           {"type": "turn.completed", "usage": {"input_tokens": 20, "cached_input_tokens": 4, "output_tokens": 9}}]:
    print(json.dumps(ev))
'''


def answer(verdicts): return json.dumps({'card_id': 'C1', 'verdicts': verdicts})


class Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.get(k) for k in ('VP_HOST', 'VP_MODEL_COMMAND_CLAUDE', 'VP_MODEL_COMMAND_OPENAI', 'CLAUDE_CONFIG_DIR', 'ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'VP_FAKE_RECORD')}
        for k in self.saved: os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.tmp.cleanup()

    def fake(self, name, body):
        """Writes a fake executable (python script) in the temp dir; returns the command list with {model} placeholder."""
        p = pathlib.Path(self.tmp.name) / name; p.write_text(body); p.chmod(p.stat().st_mode | stat.S_IEXEC)
        return [sys.executable, '-I', str(p)]

    def test_role_file_and_citation_check_in_place(self):
        self.assertTrue(V.ROLE_FILE.is_file()); self.assertEqual(V.ROLE_FILE.parent, TOOLS / 'verifier')
        self.assertEqual(pathlib.Path(sys.modules['citation_check'].__file__).parent, TOOLS / 'verifier')
        self.assertTrue((TOOLS / 'verifier' / 'fetch_fulltext.py').is_file())
        role = V.ROLE_FILE.read_text(encoding='utf-8')
        for s in ('FOUND', 'DISTORTED', 'ABSENT', 'SOURCE-UNAVAILABLE', 'card_id', 'discrepancy', 'fragments'): self.assertIn(s, role)
        self.assertEqual(V.STATUSES, ['FOUND', 'DISTORTED', 'ABSENT', 'SOURCE-UNAVAILABLE', 'INVALID', 'UNVERIFIED'])

    def test_statuses_and_retry(self):
        calls = []
        def engine(prompt, workdir):
            calls.append(prompt)
            d = pathlib.Path(workdir)
            self.assertEqual((d / 'ROLE.md').read_text(), V.ROLE_FILE.read_text())
            self.assertEqual(sorted(p.name for p in (d / 'sources').iterdir()), ['S1', 'S2'])   # S3 missing: not passed on
            self.assertIn('(record + abstract)', prompt)
            card = json.loads((d / 'card.json').read_text())
            self.assertEqual([a['id'] for a in card['claims']], ['A1', 'A2', 'A3', 'A4'])
            if len(calls) == 1:
                return answer([
                    {'id': 'A1', 'source': 'S1', 'verdict': 'FOUND', 'fragments': ['method M reaches 71.2 % accuracy'], 'confidence': 'high'},
                    {'id': 'A2', 'source': 'S1', 'verdict': 'DISTORTED', 'discrepancy': 'figure: card says 75 %, source says 71.2 %', 'fragments': ['method M reaches 71.2 %']},
                    {'id': 'A3', 'source': 'S1', 'verdict': 'ABSENT', 'fragments': [], 'search': 'Y'},
                    {'id': 'A4', 'source': 'S2', 'verdict': 'FOUND', 'fragments': ['an invented fragment that does not exist']}]), {'cost_usd': 0.1, 'seconds': 1}
            self.assertIn('RETRY', prompt); self.assertIn('A4', prompt); self.assertNotIn('- A1', prompt)
            return answer([{'id': 'A4', 'source': 'S2', 'verdict': 'FOUND', 'fragments': ['yet another fragment absent from the source']}]), {'cost_usd': 0.05, 'seconds': 1}
        r = V.verify(CARD, SRC, engine, work=self.tmp.name)
        st = {a['id']: a['status'] for a in r['claims']}
        self.assertEqual(st, {'A1': 'FOUND', 'A2': 'DISTORTED', 'A3': 'ABSENT', 'A4': 'INVALID', 'A5': 'SOURCE-UNAVAILABLE'})
        self.assertEqual(len(calls), 2); self.assertEqual(r['retries'], 1); self.assertEqual(r['mode'], 'card'); self.assertEqual(r['card_id'], 'C1')
        self.assertAlmostEqual(r['cost_usd'], 0.15); self.assertEqual(r['summary']['unsupported_rate'], 0.75); self.assertEqual(r['summary']['FOUND'], 1)
        self.assertEqual(r['claims'][4]['discrepancy'], 'after T'); self.assertEqual(r['claims'][3]['source_origin'], 'abstract')
        self.assertIn('problems', r['claims'][3]); self.assertEqual(r['role_file'], 'tools/verifier/ROLE.md')
        f = V.filter_claims(r)
        self.assertEqual([a['id'] for a in f['kept']], ['A1', 'A5']); self.assertEqual([a['id'] for a in f['removed']], ['A2', 'A3', 'A4'])
        self.assertEqual([a['id'] for a in f['to_flag']], ['A5'])

    def test_source_mode_and_failure(self):
        seen = []
        def engine(prompt, workdir):
            card = json.loads((pathlib.Path(workdir) / 'card.json').read_text()); seen.append([a['id'] for a in card['claims']])
            if 'A4' in seen[-1]: return None, {'error': 'timeout', 'cost_usd': 0, 'seconds': 1}
            return answer([{'id': i, 'source': 'S1', 'verdict': 'FOUND', 'fragments': ['method M reaches 71.2 %']} for i in seen[-1]]), {'cost_usd': 0.1, 'seconds': 1}
        r = V.verify(CARD, SRC, engine, work=self.tmp.name, mode='auto', max_chars=10)   # too big for one call: per source
        self.assertEqual(r['mode'], 'source'); self.assertEqual(seen, [['A1', 'A2', 'A3'], ['A4']])
        st = {a['id']: a['status'] for a in r['claims']}
        self.assertEqual(st, {'A1': 'FOUND', 'A2': 'FOUND', 'A3': 'FOUND', 'A4': 'UNVERIFIED', 'A5': 'SOURCE-UNAVAILABLE'})
        self.assertEqual(r['retries'], 0)                                                   # no retry after a failed call
        self.assertEqual(r['claims'][3]['discrepancy'], 'timeout')

    def test_sources_through_gateway(self):
        class Fake:
            def read(self, ident):
                return {'results': {'title': 'T', 'abstract': 'dated abstract'}} if ident == 'doi:10.1/a' else {'refusal': 'after T or forbidden'}
        d = pathlib.Path(self.tmp.name); (d / 'S2').mkdir(); (d / 'S2' / 'source.txt').write_text('local full text')
        s = V.load_sources(CARD, sources_dir=d, gateway=Fake())
        self.assertEqual({k: v['origin'] for k, v in s.items()}, {'S1': 'abstract', 'S2': 'fulltext', 'S3': 'missing'})
        self.assertEqual(s['S1']['text'], 'T\n\ndated abstract'); self.assertEqual(s['S3']['note'], 'after T or forbidden')

    def test_model_call_claude_profile(self):
        rec = pathlib.Path(self.tmp.name) / 'record.json'; os.environ['VP_FAKE_RECORD'] = str(rec)
        os.environ['VP_MODEL_COMMAND_CLAUDE'] = json.dumps(self.fake('fake-claude.py', FAKE_CLAUDE) + ['-p', '--model', '{model}', '--output-format', 'json', '--no-session-persistence'])
        os.environ['ANTHROPIC_API_KEY'] = 'secret-key'; os.environ['CLAUDE_CODE_OAUTH_TOKEN'] = 'secret-token'
        work = pathlib.Path(self.tmp.name) / 'work'; work.mkdir()
        text, m = V.model_call('PROMPT TEXT', str(work), 'model-x', host='claude')
        self.assertEqual(json.loads(text), {'card_id': 'C1', 'verdicts': []})
        self.assertEqual((m['cost_usd'], m['tokens_in'], m['tokens_out'], m['turns'], m['host']), (0.12, 16, 7, 3, 'claude')); self.assertIn('seconds', m)
        r = json.loads(rec.read_text())
        argv = r['argv']
        self.assertEqual(argv[argv.index('-p') + 1], 'PROMPT TEXT'); self.assertEqual(argv[argv.index('--model') + 1], 'model-x')
        self.assertEqual(argv[argv.index('--allowedTools') + 1], 'Read Grep Glob'); self.assertIn('Bash', argv[argv.index('--disallowedTools') + 1])
        self.assertEqual(pathlib.Path(r['cwd']).resolve(), work.resolve()); self.assertIsNone(r['anthropic']); self.assertIsNone(r['oauth'])
        os.environ['VP_HOST'] = 'claude'                                              # host from env when not given
        self.assertEqual(V.model_call('p2', str(work), 'm')[1]['host'], 'claude')

    def test_model_call_openai_profile(self):
        rec = pathlib.Path(self.tmp.name) / 'record.json'; os.environ['VP_FAKE_RECORD'] = str(rec)
        os.environ['VP_MODEL_COMMAND_OPENAI'] = json.dumps(self.fake('fake-codex.py', FAKE_CODEX) + ['exec', '-m', '{model}', '-s', 'read-only', '--json', '-'])
        os.environ['ANTHROPIC_API_KEY'] = 'secret-key'
        work = pathlib.Path(self.tmp.name) / 'work'; work.mkdir()
        text, m = V.model_call('PROMPT ON STDIN', str(work), 'gpt-x', host='openai')
        self.assertEqual(json.loads(text), {'card_id': 'C1', 'verdicts': [{'id': 'A1'}]})     # last agent_message, not the draft
        self.assertEqual((m['cost_usd'], m['tokens_in'], m['tokens_out'], m['turns'], m['host']), (0, 24, 9, 1, 'openai'))
        r = json.loads(rec.read_text())
        self.assertEqual(r['stdin'], 'PROMPT ON STDIN'); self.assertNotIn('--allowedTools', r['argv']); self.assertNotIn('PROMPT ON STDIN', r['argv'])
        self.assertEqual(r['argv'][r['argv'].index('-m') + 1], 'gpt-x'); self.assertEqual(r['argv'][-1], '-')
        self.assertEqual(pathlib.Path(r['cwd']).resolve(), work.resolve()); self.assertIsNone(r['anthropic'])
        os.environ['VP_HOST'] = 'openai'
        self.assertEqual(V.model_call('p2', str(work), 'm')[1]['host'], 'openai')

    def test_model_call_failure_is_reported_not_raised(self):
        os.environ['VP_MODEL_COMMAND_CLAUDE'] = json.dumps(self.fake('fake-bad.py', 'print("not json")\n') + ['-p'])
        text, m = V.model_call('p', self.tmp.name, 'm', host='claude')
        self.assertIsNone(text); self.assertIn('error', m); self.assertEqual(m['cost_usd'], 0)
        os.environ['VP_MODEL_COMMAND_OPENAI'] = json.dumps([sys.executable, '-I', str(pathlib.Path(self.tmp.name) / 'missing-executable.py')])
        text, m = V.model_call('p', self.tmp.name, 'm', host='openai')
        self.assertIsNone(text); self.assertIn('error', m)

    def test_unsafe_card_id_and_identifier_keys_stay_inside_workdir(self):
        victim = pathlib.Path(self.tmp.name) / 'victim'; victim.mkdir(); (victim / 'keep.txt').write_text('x')
        self.assertEqual(V.fs_key('/abs/../../x'), '_abs_.._.._x'); self.assertEqual(V.fs_key('..'), 'source'); self.assertEqual(V.fs_key('doi:10.1/ab'), 'doi_10.1_ab')
        card = {'card_id': str(victim), 'claims': [{'id': 'A1', 'text': 't', 'source': {'doi': '10.1038/abc'}}]}
        src = {'doi:10.1038/abc': {'text': 'some text', 'origin': 'fulltext', 'note': '', 'desc': {}}}
        work = pathlib.Path(self.tmp.name) / 'work'; work.mkdir()
        texts, _ = V.prepare(work / V.fs_key(card['card_id']), card, src)
        self.assertTrue((victim / 'keep.txt').exists())                                   # nothing outside the work directory is touched
        f = json.loads((work / V.fs_key(card['card_id']) / 'card.json').read_text())
        self.assertEqual(f['claims'][0]['source']['key'], 'doi_10.1038_abc'); self.assertIn('doi_10.1038_abc', f['sources'])
        self.assertTrue((work / V.fs_key(card['card_id']) / 'sources' / 'doi_10.1038_abc' / 'source.txt').exists())
        sd = pathlib.Path(self.tmp.name) / 'srcdir'; sd.mkdir(); (sd / 'S1.txt').write_text('flat layout')
        (sd / 'S2').mkdir(); (sd / 'S2' / 'source.txt').write_text('nested layout')
        out = V.load_sources({'claims': [{'id': 'a', 'source': {'key': 'S1'}}, {'id': 'b', 'source': {'key': 'S2'}}]}, sources_dir=sd)
        self.assertEqual((out['S1']['text'], out['S2']['text']), ('flat layout', 'nested layout'))

    def test_model_free_by_host(self):
        saved = os.environ.pop('VP_MODEL', None)
        try:
            self.assertEqual(V.default_model('claude'), (V.CFG.get('model') or {}).get('claude', '') if isinstance(V.CFG.get('model'), dict) else V.CFG.get('model', ''))
            self.assertEqual(V.default_model('openai'), (V.CFG.get('model') or {}).get('openai', '') if isinstance(V.CFG.get('model'), dict) else '')
            self.assertEqual(V.strip_model(['codex', 'exec', '-m', '', '-']), ['codex', 'exec', '-']); self.assertEqual(V.strip_model(['c', '--model', 'x']), ['c', '--model', 'x'])
            os.environ['VP_MODEL'] = 'chosen'; self.assertEqual(V.default_model('openai'), 'chosen')
        finally:
            if saved is None: os.environ.pop('VP_MODEL', None)
            else: os.environ['VP_MODEL'] = saved

    def test_model_command_sources(self):
        self.assertEqual(V.host_name(None), os.environ.get('VP_HOST') or V.CONFIG.get('host') or 'claude')
        cmd = V.model_command('claude'); self.assertEqual(cmd[0], 'claude'); self.assertIn('{model}', cmd)
        cmd = V.model_command('openai'); self.assertEqual(cmd[:2], ['codex', 'exec']); self.assertEqual(cmd[-1], '-')
        os.environ['VP_MODEL_COMMAND_OPENAI'] = '{"not": "a list"}'
        with self.assertRaises(RuntimeError): V.model_command('openai')
        with self.assertRaises(RuntimeError): V.model_command('unknown-host')


if __name__ == '__main__':
    unittest.main()
