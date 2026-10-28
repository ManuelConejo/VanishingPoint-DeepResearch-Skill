#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests of the code sources of the verifier (tools/verifier/code_files.py, tools/verifier.py load_sources; plugins/code.md,
verification rule 1): a claim cited `<path>@<SHA>` is checked against the whole file read AT THE SHA by `git show`, in a real small git
repository built by the test (working copy for X, bare mirror for Y, found from capsule.json and scope.md), or through the gateway's
`code-file` (Software Heritage transport replaced by a fixture). Cases: a true claim (FOUND, fragment machine-checked, passage shown by
tools/passages.py), a false claim whose fragment exists only in the working copy / a later commit (INVALID), a SHA that does not exist
(SOURCE-UNAVAILABLE with the reason), refusals (branch, `..`, directory), an engine-written excerpt never read in place of the file,
no repository code executed (textconv, signature program, fsmonitor and hooks configured in the repository stay unused), the gateway
fallback and its date barrier. Hermetic: throwaway HOME, GIT_CONFIG_GLOBAL=/dev/null, fake engine (no model).
Run: python3 -I tests/test_verifier_code.py   (unittest; pytest-compatible)."""
import json, os, pathlib, subprocess, sys, tempfile, unittest

P = pathlib.Path(__file__).resolve().parent
TOOLS = P.parent / 'tools'
sys.path.insert(0, str(TOOLS)); sys.path.insert(0, str(TOOLS / 'verifier'))
import verifier as V          # noqa: E402
import code_files as CF       # noqa: E402
import code_sources as sc     # noqa: E402
import gateway as gw          # noqa: E402
import passages               # noqa: E402

ENV = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
       'GIT_COMMITTER_EMAIL': 't@t', 'GIT_AUTHOR_DATE': '2026-01-01T00:00:00Z', 'GIT_COMMITTER_DATE': '2026-01-01T00:00:00Z'}
V1 = 'def retry(f, tries=3):\n    """Call f at most tries times."""\n    return f()\n'
V2 = 'def retry(f, tries=5):\n    """Call f at most tries times."""\n    return f()\n'
LIB = 'def expo(base=2):\n    """Exponential wait generator."""\n    n = 0\n    while True:\n        yield base ** n\n        n += 1\n'
PLUGIN = '# Code\n## Sources\n```sources\nengines: software-heritage, provenance\ncap: 5\n```\n'


def git(repo, *args, env=None):
    return subprocess.run(['git', '-C', str(repo), *args], env={**os.environ, **ENV, **(env or {})}, check=True, capture_output=True, text=True).stdout.strip()


class FakeEngine:
    """Returns the verdicts given per claim id (no model); records the prompts."""
    def __init__(self, verdicts): self.verdicts, self.calls = verdicts, []

    def __call__(self, prompt, workdir):
        self.calls.append(prompt)
        card = json.loads((pathlib.Path(workdir) / 'card.json').read_text())
        out = [dict(self.verdicts[a['id']], id=a['id']) for a in card['claims'] if a['id'] in self.verdicts]
        return json.dumps({'card_id': card['card_id'], 'verdicts': out}), {'cost_usd': 0, 'seconds': 0}


class VerifierCode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.env0 = {k: os.environ.get(k) for k in ('HOME', *ENV)}
        os.environ['HOME'] = str(self.d / 'home'); (self.d / 'home').mkdir()
        os.environ.update(ENV)
        self.x = self.d / 'proj' / 'x'; self.x.mkdir(parents=True)          # X: working copy
        git(self.x, 'init', '-q')
        (self.x / 'pkg').mkdir(); (self.x / 'pkg' / 'api.py').write_text(V1); (self.x / 'README').write_text('x\n')
        git(self.x, 'add', '-A'); git(self.x, 'commit', '-q', '-m', 'c1'); self.sha1 = git(self.x, 'rev-parse', 'HEAD')
        (self.x / 'pkg' / 'api.py').write_text(V2)
        git(self.x, 'commit', '-q', '-am', 'c2'); self.sha2 = git(self.x, 'rev-parse', 'HEAD')
        (self.x / 'pkg' / 'api.py').write_text('# uncommitted working copy\n')  # never read: neither HEAD nor the SHA
        src = self.d / 'ysrc'; src.mkdir(); git(src, 'init', '-q')                   # Y: bare mirror supplied by the host
        (src / 'lib').mkdir(); (src / 'lib' / 'wait.py').write_text(LIB); (src / 'LICENSE').write_text('MIT License\n')
        git(src, 'add', '-A'); git(src, 'commit', '-q', '-m', 'y'); self.ysha = git(src, 'rev-parse', 'HEAD')
        self.y = self.d / 'y' / 'lib.git'; self.y.parent.mkdir()
        subprocess.run(['git', 'clone', '-q', '--bare', str(src), str(self.y)], env={**os.environ, **ENV}, check=True, capture_output=True)
        self.run = self.x / 'vp-run'; self.run.mkdir()
        (self.run / 'capsule.json').write_text(json.dumps({'identity': {'repo': str(self.x), 'sha': self.sha1},
                                                           'Y': {'repo': 'github.com/o/lib', 'sha': self.ysha, 'sha_source': 'HEAD of the default branch'}}))
        (self.run / 'scope.md').write_text(f'# scope\n- Y = o/lib@{self.ysha} (HEAD of default branch in host mirror {self.y}).\n')

    def tearDown(self):
        for k, v in self.env0.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.tmp.cleanup()

    def card(self):
        s1 = self.sha1
        return {'card_id': 'C', 'question': 'q', 'sources': {
            'S1': {'code': f'local:pkg/api.py@{s1}', 'title': 'x, pkg/api.py'},
            'S2': {'code': f'lib/wait.py@{self.ysha}', 'title': 'o, lib, lib/wait.py'},
            'S3': {'code': 'pkg/api.py@' + 'e' * 40, 'title': 'no such commit'}},
            'claims': [{'id': 'A1', 'text': 'X retries 3 times by default.', 'source': {'key': 'S1'}},
                       {'id': 'A2', 'text': 'X retries 5 times by default.', 'source': {'key': 'S1'}},
                       {'id': 'A3', 'text': 'Y has an exponential wait generator.', 'source': {'key': 'S2'}},
                       {'id': 'A4', 'text': 'X retries.', 'source': {'key': 'S3'}}]}

    def test_true_false_and_missing_sha(self):
        card = self.card(); out = self.run / 'sources'
        S = V.load_sources(card, None, None, out_dir=out, run_dir=self.run)
        self.assertEqual({k: s['origin'] for k, s in S.items()}, {'S1': 'fulltext', 'S2': 'fulltext', 'S3': 'missing'})
        self.assertEqual(S['S1']['text'], V1, 'the file at the SHA, not HEAD nor the working copy')
        self.assertEqual(S['S2']['text'], LIB)
        self.assertEqual((S['S1']['code']['repo'], S['S2']['code']['repo']), (str(self.x.resolve()), str(self.y.resolve())))
        self.assertEqual(S['S2']['code']['repo_from'], 'scope.md')
        self.assertIn('not found in the local git directories', S['S3']['note'])
        self.assertEqual((out / 'S1' / 'source.txt').read_text(), V1)
        rec = json.loads((out / 'S1' / 'code.json').read_text())
        self.assertEqual((rec['commit'], rec['path'], rec['method']), (self.sha1, 'pkg/api.py', 'git show'))
        self.assertFalse((out / 'S3').exists())
        eng = FakeEngine({'A1': {'verdict': 'FOUND', 'fragments': ['def retry(f, tries=3):'], 'location': 'pkg/api.py:1'},
                          'A2': {'verdict': 'FOUND', 'fragments': ['def retry(f, tries=5):'], 'location': 'pkg/api.py:1'},   # true only after the SHA
                          'A3': {'verdict': 'FOUND', 'fragments': ['"""Exponential wait generator."""'], 'location': 'lib/wait.py:2'}})
        res = V.verify(card, S, eng, work=self.d / 'work', windows={'mode': 'whole'})
        st = {c['id']: c['status'] for c in res['claims']}
        self.assertEqual(st, {'A1': 'FOUND', 'A2': 'INVALID', 'A3': 'FOUND', 'A4': 'SOURCE-UNAVAILABLE'})
        self.assertEqual(len(eng.calls), 2, 'one call + the single retry for the rejected fragment')
        (self.run / 'card.json').write_text(json.dumps(card)); (self.run / 'verdicts.json').write_text(json.dumps(res))
        doc = passages.build(self.run)
        got = {c['id']: c for c in doc['claims']}
        self.assertIn('def retry(f, tries=3):', json.dumps(got['A1']))
        self.assertNotIn('tries=5', json.dumps(got['A1']))
        self.assertEqual(doc['summary']['with_passage'], 2)

    def test_cli_reads_code_sources(self):
        card = self.card(); (self.run / 'card.json').write_text(json.dumps(card))
        fake = self.d / 'fake.py'
        fake.write_text('import json,sys\nprint(json.dumps({"result": json.dumps({"card_id": "C", "verdicts": []}), "total_cost_usd": 0}))\n')
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(self.d / 'home'), 'VP_HOST': 'claude',
               'VP_MODEL_COMMAND_CLAUDE': json.dumps([sys.executable, str(fake)])}
        p = subprocess.run([sys.executable, '-I', str(TOOLS / 'verifier.py'), 'verify', '--card', str(self.run / 'card.json'), '--out', str(self.run / 'verdicts.json'),
                            '--sources', str(self.run / 'sources'), '--state', str(self.run / 'state')], env=env, capture_output=True, text=True, cwd=self.d)
        self.assertEqual(p.returncode, 0, p.stderr)
        rec = json.loads((self.run / 'state' / 'verifier.json').read_text())
        self.assertEqual(rec['origins'], {'fulltext': 2, 'abstract': 0, 'missing': 1})
        self.assertEqual(rec['per_source']['S2']['code']['commit'], self.ysha)
        self.assertEqual((self.run / 'sources' / 'S2' / 'source.txt').read_text(), LIB)

    def test_explicit_repo_and_parent_discovery(self):
        card = self.card(); bare_run = self.d / 'elsewhere'; bare_run.mkdir()
        S = V.load_sources(card, None, None, out_dir=bare_run / 'sources', run_dir=bare_run)          # nothing known: no repository
        self.assertEqual(S['S1']['origin'], 'missing'); self.assertIn('no local git directory', S['S1']['note'])
        S = V.load_sources(card, None, None, out_dir=bare_run / 'sources', repos=CF.run_repos(bare_run, [str(self.y), str(self.x)]))
        self.assertEqual((S['S1']['origin'], S['S2']['origin']), ('fulltext', 'fulltext'))
        (self.run / 'capsule.json').unlink()
        self.assertEqual(CF.run_repos(self.run)[-1], {'repo': str(self.x.resolve()), 'from': 'nearest parent of the run holding .git'})

    def test_refusals(self):
        self.assertEqual(CF.code_ref('S', {'code': 'pkg/api.py@main'})['error'], 'unpinned')
        self.assertEqual(CF.code_ref('S', {'code': '../etc/passwd@' + self.sha1})['error'], 'reference')
        self.assertEqual(CF.code_ref('S', {'code': '/etc/passwd@' + self.sha1})['error'], 'reference')
        r = CF.code_ref('S', {'code': 'pkg/api.py:12-14@' + self.sha1.upper()})
        self.assertEqual((r['path'], r['line'], r['end'], r['sha'], r['side']), ('pkg/api.py', 12, 14, self.sha1, 'Y'))
        self.assertEqual(CF.code_ref('local:pkg/api.py@abc1234', {})['side'], 'X')
        self.assertIsNone(CF.code_ref('S', {'doi': '10.1/x'}))
        repos = CF.run_repos(self.run)
        t, rec = CF.read(CF.code_ref('S', {'code': 'pkg@' + self.sha1}), repos)
        self.assertIsNone(t); self.assertIn('a directory', rec['reason'])
        t, rec = CF.read(CF.code_ref('S', {'code': 'pkg/absent.py@' + self.sha1}), repos)
        self.assertIsNone(t); self.assertIn('file absent at the SHA', rec['reason'])
        t, rec = CF.read(CF.code_ref('S', {'code': 'pkg/api.py@main'}), repos)
        self.assertIsNone(t); self.assertTrue(rec['reason'].startswith('unpinned'))

    def test_engine_excerpt_never_read_in_place(self):
        card = self.card(); out = self.run / 'sources'
        (out / 'S3').mkdir(parents=True); (out / 'S3' / 'source.txt').write_text('def retry(f, tries=3): an excerpt written by the engine')
        S = V.load_sources(card, out, None, out_dir=out, run_dir=self.run)
        self.assertEqual(S['S3']['origin'], 'missing')
        (out / 'S1' / 'source.txt').write_text('tampered')                                          # overwritten by the next reading
        self.assertEqual(V.load_sources(card, out, None, out_dir=out, run_dir=self.run)['S1']['text'], V1)
        self.assertEqual((out / 'S1' / 'source.txt').read_text(), V1)

    def test_no_repository_code_executed(self):
        mark = self.d / 'executed'
        evil = self.d / 'evil.sh'; evil.write_text(f'#!/bin/sh\ntouch {mark}\ncat "$@"\n'); evil.chmod(0o755)
        for k, v in (('diff.evil.textconv', str(evil)), ('log.showSignature', 'true'), ('gpg.program', str(evil)), ('core.fsmonitor', str(evil)),
                     ('core.pager', str(evil)), ('diff.external', str(evil))):
            git(self.x, 'config', k, v)
        (self.x / '.git' / 'info').mkdir(exist_ok=True); (self.x / '.git' / 'info' / 'attributes').write_text('*.py diff=evil\n')
        hooks = self.x / '.git' / 'hooks'; hooks.mkdir(exist_ok=True)
        for h in ('post-checkout', 'pre-commit', 'reference-transaction'):
            (hooks / h).write_text(f'#!/bin/sh\ntouch {mark}\n'); (hooks / h).chmod(0o755)
        S = V.load_sources(self.card(), None, None, out_dir=self.run / 'sources', run_dir=self.run)
        self.assertEqual(S['S1']['text'], V1)
        self.assertFalse(mark.exists(), 'a program configured by the repository was run')

    def test_gateway_fallback_and_date_barrier(self):
        raw = LIB.encode(); target, rev = 'c' * 40, self.ysha
        def fake_get(client, url, token=None, cred=None, body=None):
            if '/revision/' in url: return json.dumps({'directory': 'd' * 40, 'committer_date': self.date}).encode()
            if '/directory/' in url: return json.dumps({'type': 'file', 'target': target}).encode()
            if url.endswith('/content/sha1_git:' + target + '/raw/'): return raw
            raise AssertionError('unexpected URL ' + url)
        get0, sc.CodeClient.get = sc.CodeClient.get, fake_get
        try:
            (self.d / 'code.md').write_text(PLUGIN)
            card = {'card_id': 'C', 'sources': {'S2': {'code': f'lib/wait.py@{rev}', 'url': 'https://github.com/o/lib'}},
                    'claims': [{'id': 'A1', 'text': 't', 'source': {'key': 'S2'}}]}
            self.date = '2026-01-01T00:00:00+00:00'
            g = gw.Gateway([str(self.d / 'code.md')], T='2026-10-29', run='r', state=self.d / 'state', pool='verifier', cap=5)
            S = V.load_sources(card, None, g, out_dir=self.d / 'out', repos=[])
            self.assertEqual((S['S2']['origin'], S['S2']['text'], S['S2']['code']['method']), ('fulltext', LIB, 'gateway code-file (provenance)'))
            self.assertEqual((self.d / 'out' / 'S2' / 'source.txt').read_text(), LIB)
            self.date = '2026-11-01T00:00:00+00:00'                                     # commit after T: refused by the date barrier
            g = gw.Gateway([str(self.d / 'code.md')], T='2026-10-29', run='r2', state=self.d / 'state', pool='verifier', cap=5)
            S = V.load_sources(card, None, g, out_dir=self.d / 'out2', repos=[])
            self.assertEqual(S['S2']['origin'], 'missing'); self.assertIn('after T', S['S2']['note'])
            self.assertEqual(g.call('code-file', 'https://github.com/o/lib#lib/wait.py@main'),
                             {'refusal': 'expected form <origin https://...>#<path>@<40-hex SHA>'})
        finally:
            sc.CodeClient.get = get0


if __name__ == '__main__':
    unittest.main()
