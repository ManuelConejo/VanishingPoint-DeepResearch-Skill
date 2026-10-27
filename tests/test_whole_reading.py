#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests of tools/whole_reading.py with a fake model executable (no network, no real model, no cost).

1. Synthetic case (always run): a throwaway git repository X, a run directory with scope.md, capsule.md (seam), searches/1.md
   (citation), state/calls.jsonl (x-read), a Y material file; both host profiles (claude: stream-json trace; openai: codex
   JSONL events) through VP_MODEL_COMMAND_<HOST>; --material-only; the X cap; a second call after the receipt.
2. Reference materials (run only when the environment names them, otherwise skipped): VP_TEST_WR_CASES = JSON list of
   {"run": <run dir with scope.md, capsule.md, searches/ or fouilles/, state/calls.jsonl or etat/appels.jsonl>,
    "y_material": <file>, "x": {"repo", "sha", "name", "prefix"}, "x2": {...} optional, "expected_x": <material-X.json of a
   reference run> optional}. Checks that the X material is rebuilt identically (same included paths) and that the fake
   reader's output is written under the caps.
"""
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(P)); import whole_reading as W  # noqa: E402

FAKE_CLAUDE = '''#!/usr/bin/env python3
import json, sys
p = sys.stdin.read()
assert "--tools" in sys.argv and sys.argv[sys.argv.index("--tools") + 1] == "", sys.argv
assert "stream-json" in sys.argv and "--verbose" in sys.argv, sys.argv
n = p.split("# X in full")[-1].count("=== ")
txt = "## Composite capabilities\\n\\nFake reader: %d whole files seen, prompt %d chars, model %s.\\n\\n## Concrete defects of X revealed by the comparison\\n\\nnot read\\n" % (n, len(p), sys.argv[sys.argv.index("--model") + 1])
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": txt}]}}))
print(json.dumps({"type": "result", "subtype": "success", "result": txt, "total_cost_usd": 0.01, "num_turns": 1,
                  "usage": {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 0, "output_tokens": 20}}))
'''
FAKE_OPENAI = '''#!/usr/bin/env python3
import json, sys
p = sys.stdin.read()
assert sys.argv[-1] == "-" and "exec" in sys.argv, sys.argv
txt = "## Composite capabilities\\n\\nFake codex reader: prompt %d chars, model %s.\\n" % (len(p), sys.argv[sys.argv.index("-m") + 1])
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": txt}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1000, "output_tokens": 30}}))
'''
GIT_ENV = dict(GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t', GIT_CONFIG_GLOBAL='/dev/null', HOME='/nonexistent')


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, env={**os.environ, **GIT_ENV}).stdout.decode()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        for name, body in (('fake-claude', FAKE_CLAUDE), ('fake-codex', FAKE_OPENAI)):
            f = self.d / name; f.write_text(body); f.chmod(0o755)
        self.env0 = {k: os.environ.get(k) for k in ('VP_MODEL_COMMAND_CLAUDE', 'VP_MODEL_COMMAND_OPENAI', 'VP_HOST', 'VP_MODEL')}
        os.environ['VP_MODEL_COMMAND_CLAUDE'] = json.dumps([str(self.d / 'fake-claude'), '-p', '--model', '{model}', '--output-format', 'json'])
        os.environ['VP_MODEL_COMMAND_OPENAI'] = json.dumps([str(self.d / 'fake-codex'), 'exec', '-m', '{model}', '--json', '-'])
        os.environ.pop('VP_HOST', None); os.environ.pop('VP_MODEL', None)

    def tearDown(self):
        for k, v in self.env0.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.tmp.cleanup()

    def run_tool(self, run, *args):
        r = subprocess.run([sys.executable, '-I', str(P / 'whole_reading.py'), str(run), *args], capture_output=True, text=True, env=os.environ, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout.strip().splitlines()[-1])


class Synthetic(Base):
    def setUp(self):
        super().setUp()
        x = self.d / 'x'; x.mkdir(); git(x, 'init', '-q')
        (x / 'core').mkdir(); (x / 'core' / 'state.py').write_text('class State:\n    pass\n' * 3)
        (x / 'core' / 'proof.py').write_text('def proof():\n    return 1\n')
        (x / 'adapters').mkdir(); (x / 'adapters' / 'runner.py').write_text('def run():\n    return 0\n' * 40)
        (x / 'README.md').write_text('# X\n'); (x / 'bin.dat').write_bytes(b'\x00\x01')
        git(x, 'add', '-A'); git(x, 'commit', '-q', '-m', 'one'); self.sha = git(x, 'rev-parse', 'HEAD').strip(); self.x = x
        run = self.d / 'run'; (run / 'searches').mkdir(parents=True); (run / 'state').mkdir()
        (run / 'scope.md').write_text(f'# scope.md\n\nQuestion (verbatim): "Does Y bring something to X?"\nT = 2026-10-20\n\n## 1. X@SHA and Y@SHA\n- X : {x}@{self.sha} ; target = the state layer\n- Y : owner/repo@0123456789abcdef0123456789abcdef01234567\n')
        (run / 'capsule.md').write_text(f'# Capsule\n\n- target_seam:\n  - core/state.py:1@{self.sha[:8]} (State) - the seam\n- intention: none\n- refusals:\n  - none\n')
        (run / 'searches' / '1.md').write_text(f'# search 1\n\nX side: adapters/runner.py:3@{self.sha[:12]} runs; adapters/runner.py:7@{self.sha[:12]} again; missing/none.py:1@{self.sha[:12]}.\n')
        (run / 'searches' / 'whole-reading.md').write_text('stale, must be ignored and overwritten\n')
        (run / 'state' / 'calls.jsonl').write_text(json.dumps(dict(family='reading', cmd='x-read', args=['proof.py'], opts={}, rc=0)) + '\n'
                                                   + json.dumps(dict(cmd='x-read', args=['README.md'], opts={'repo': 'other'}, rc=0)) + '\n')
        (self.d / 'Y.txt').write_text('# Y tree\n=== a.py @0123456789ab (2 lines) ===\n1\tx = 1\n2\ty = 2\n' * 50)
        self.run = run

    def test_material_only(self):
        s = self.run_tool(self.run, '--y-material', str(self.d / 'Y.txt'), '--material-only')
        self.assertEqual(s['status'], 'material')
        paths = [f[1] for f in s['files_X']]
        self.assertEqual(paths, ['core/state.py', 'adapters/runner.py', 'core/proof.py'])  # seam first, then by mentions (2), then 1
        self.assertEqual([f[4] for f in s['files_X']][0], ['seam']); self.assertIn('citation', [f[4] for f in s['files_X']][1])
        self.assertEqual(s['excluded'], [])
        d = self.run / 'state' / 'whole-reading'
        p = (d / 'PROMPT.md').read_text()
        self.assertIn('# Y in full', p); self.assertIn('# X in full', p); self.assertIn('=== core/state.py @' + self.sha[:12], p)
        self.assertIn('Date of the request (T): 2026-10-20', p); self.assertIn('"Does Y bring something to X?"', p)
        self.assertNotIn('{Y}', p); self.assertTrue((d / 'material-X.json').exists()); self.assertTrue((d / 'material-Y.txt').exists())
        self.assertFalse((d / 'receipt.json').exists())
        self.assertEqual((self.run / 'searches' / 'whole-reading.md').read_text(), 'stale, must be ignored and overwritten\n')

    def test_claude_profile_sync(self):
        s = self.run_tool(self.run, '--y-material', str(self.d / 'Y.txt'), '--model', 'test-model', '--sync')
        self.assertEqual(s['status'], 'done', s); self.assertEqual(s['usd'], 0.01)
        out = (self.run / 'searches' / 'whole-reading.md').read_text()
        self.assertTrue(out.startswith('# searches/whole-reading.md - whole reading before verdicts'))
        self.assertIn('X = 3 whole files', out); self.assertIn('Fake reader: 3 whole files seen', out); self.assertIn('model test-model', out)
        r = json.loads((self.run / 'state' / 'whole-reading' / 'receipt.json').read_text())
        self.assertEqual((r['host'], r['model'], r['rc'], r['tool_calls']), ('claude', 'test-model', 0, 0))
        self.assertEqual([f['path'] for f in r['material_X']['included']], ['core/state.py', 'adapters/runner.py', 'core/proof.py'])
        self.assertEqual(r['material_Y']['chars'], len((self.d / 'Y.txt').read_text())); self.assertEqual(r['prompt_chars'], len((self.run / 'state' / 'whole-reading' / 'PROMPT.md').read_text()))
        again = self.run_tool(self.run, '--y-material', str(self.d / 'Y.txt'))  # second call: the receipt is returned, nothing relaunched
        self.assertEqual(again['status'], 'done'); self.assertEqual(again['files_X'], ['core/state.py', 'adapters/runner.py', 'core/proof.py'])
        self.assertFalse(any(self.x.glob('**/.git/HEAD.lock')))  # X untouched (read-only git)
        self.assertEqual(git(self.x, 'status', '--porcelain'), '')

    def test_openai_profile_env_host(self):
        os.environ['VP_HOST'] = 'openai'
        s = self.run_tool(self.run, '--y-material', str(self.d / 'Y.txt'), '--model', 'gpt-test', '--sync')
        self.assertEqual(s['status'], 'done', s); self.assertEqual(s['usd'], 0.0)
        out = (self.run / 'searches' / 'whole-reading.md').read_text()
        self.assertIn('via openai', out); self.assertIn('Fake codex reader', out); self.assertIn('model gpt-test', out)
        r = json.loads((self.run / 'state' / 'whole-reading' / 'receipt.json').read_text())
        self.assertEqual((r['host'], r['tokens_in'], r['tokens_out'], r['subtype']), ('openai', 1000, 30, 'success'))

    def test_x_cap_never_truncates(self):
        s = self.run_tool(self.run, '--y-material', str(self.d / 'Y.txt'), '--material-only', '--x-cap', '200')
        inc = [f[1] for f in s['files_X']]; exc = [e['path'] for e in s['excluded']]
        self.assertIn('core/state.py', inc); self.assertIn('adapters/runner.py', exc)
        self.assertTrue(all('not included (cap 200)' in e['reason'] for e in s['excluded'] if e['path'] == 'adapters/runner.py'))
        x = (self.run / 'state' / 'whole-reading' / 'material-X.txt').read_text()
        self.assertIn('# Not included: adapters/runner.py [not included (cap 200)]', x)
        for f in inc:  # an included file is whole
            self.assertEqual(x.count(f'=== {f} @'), 1)

    def test_arguments_override_scope(self):
        s = self.run_tool(self.run, '--y-material', str(self.d / 'Y.txt'), '--material-only', '--x-repo', str(self.x), '--x-sha', self.sha, '--x-name', 'host',
                          '--T', '2026-01-01', '--request', 'R', '--target', 'the target')
        self.assertEqual(s['files_X'][0][0], 'host')
        p = (self.run / 'state' / 'whole-reading' / 'PROMPT.md').read_text()
        self.assertIn('(T): 2026-01-01', p); self.assertIn('"R"', p); self.assertIn('Target X: the target', p); self.assertIn('# X = host@', p)

    def test_failed_reader(self):
        os.environ['VP_MODEL_COMMAND_CLAUDE'] = json.dumps(['/bin/false'])
        s = self.run_tool(self.run, '--y-material', str(self.d / 'Y.txt'), '--sync')
        self.assertEqual(s['status'], 'failed', s)
        self.assertEqual((self.run / 'searches' / 'whole-reading.md').read_text(), 'stale, must be ignored and overwritten\n')


class LabMaterials(Base):
    """Rebuilds the material of reference runs when VP_TEST_WR_CASES names them (a host that has them); skipped otherwise."""
    def test_cases(self):
        spec = os.environ.get('VP_TEST_WR_CASES')
        if not spec: self.skipTest('VP_TEST_WR_CASES not set')
        for c in json.loads(spec):
            with self.subTest(run=c['run']):
                src = pathlib.Path(c['run']); run = self.d / ('run-' + src.parent.name + '-' + src.name); run.mkdir()
                for f in ('scope.md', 'capsule.md'):
                    if (src / f).exists(): shutil.copy(src / f, run / f)
                sdir = src / 'searches' if (src / 'searches').exists() else src / 'fouilles'
                (run / 'searches').mkdir()
                for f in sdir.glob('*.md'):
                    if f.name not in ('whole-reading.md', 'lecture-entiere.md'): shutil.copy(f, run / 'searches' / f.name)
                (run / 'state').mkdir()
                calls = src / 'state' / 'calls.jsonl' if (src / 'state' / 'calls.jsonl').exists() else src / 'etat' / 'appels.jsonl'
                if calls.exists(): shutil.copy(calls, run / 'state' / 'calls.jsonl')
                args = ['--y-material', c['y_material'], '--x-repo', c['x']['repo'], '--x-sha', c['x']['sha'], '--x-name', c['x']['name'], '--x-prefix', c['x'].get('prefix', '')]
                if c.get('x2'): args += ['--x2-repo', c['x2']['repo'], '--x2-sha', c['x2']['sha'], '--x2-name', c['x2']['name'], '--x2-prefix', c['x2'].get('prefix', '')]
                if c.get('T'): args += ['--T', c['T']]
                if c.get('request'): args += ['--request', c['request']]
                if c.get('target'): args += ['--target', c['target']]
                s = self.run_tool(run, *args, '--model', 'fake-model', '--sync')
                self.assertEqual(s['status'], 'done', s)
                r = json.loads((run / 'state' / 'whole-reading' / 'receipt.json').read_text())
                self.assertLessEqual(r['material_X']['chars'], W.X_CAP); self.assertGreater(len(r['material_X']['included']), 0)
                self.assertIn('Fake reader', (run / 'searches' / 'whole-reading.md').read_text())
                if c.get('expected_x'):
                    exp = json.loads(pathlib.Path(c['expected_x']).read_text())
                    want = [(f.get('X'), f.get('chemin') or f.get('path')) for f in exp['inclus' if 'inclus' in exp else 'included']]
                    got = [(f['X'], f['path']) for f in r['material_X']['included']]
                    self.assertEqual(sorted(got), sorted(want))


if __name__ == '__main__':
    unittest.main()
