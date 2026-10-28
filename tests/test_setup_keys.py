#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of setup_keys.py with a temporary HOME: the key file is written 0600 in a 0700 directory, the value never appears on
stdout/stderr, the PISTE pair is written, the verdict lines for OK / refused / not subscribed come from stubbed answers of the gateway's
own request paths (urlopen for gateway.fetch, piste_http for PISTE), --remove deletes after confirmation, an unknown name exits 2 with the list."""
import contextlib, io, json, os, pathlib, stat, sys, tempfile, unittest, urllib.error
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); import setup_keys as SK, gateway as gw   # noqa: E702

SECRET = 'Zq7-fake-SECRET-value-91x'
ENVS = [v for e in SK.entries() for v in e['vars']] + ['HOME']


class Resp(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


class Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = pathlib.Path(self.tmp.name)
        self.env = {k: os.environ.pop(k) for k in ENVS if k in os.environ}; os.environ['HOME'] = self.tmp.name
        self.saved = (gw.STATE, gw.urllib.request.urlopen, gw.piste_http, SK.getpass.getpass, sys.stdin)

    def tearDown(self):
        gw.STATE, gw.urllib.request.urlopen, gw.piste_http, SK.getpass.getpass, sys.stdin = self.saved
        for k in ENVS: os.environ.pop(k, None)
        os.environ.update(self.env); self.tmp.cleanup()

    def run_main(self, argv, lines=(), tty=False):
        """main() with stdin = the given lines (tty=True: getpass stubbed and fed from the same lines)."""
        feed = io.StringIO(''.join(x + '\n' for x in lines)); feed.isatty = lambda: tty
        sys.stdin = feed; SK.getpass.getpass = lambda prompt='': feed.readline().rstrip('\n')
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): code = SK.main(argv)
        return code, out.getvalue(), err.getvalue()

    def urlopen(self, refuse):
        """Stub of urllib.request.urlopen for gateway.fetch: with api_key=, NCBI answers 400 "API key not wellformed" (its answer to
        any mistyped key, measured 2026-10-28) when refuse, else 200."""
        def f(req, timeout=None):
            url = req.full_url if hasattr(req, 'full_url') else req
            if refuse and 'api_key=' in url:
                raise urllib.error.HTTPError(url, 400, 'Bad Request', {}, io.BytesIO(b'{"error":"API key not wellformed","api-key":"' + SECRET.encode() + b'"}'))
            return Resp(b'{"esearchresult": {"count": "1", "idlist": ["1"]}, "results": [], "meta": {"count": 1}}')
        return f

    def test_write_modes_and_no_echo(self):
        gw.urllib.request.urlopen = self.urlopen(False)
        for tty in (True, False):
            code, out, err = self.run_main(['NCBI_API_KEY'], ['  ' + SECRET + '  '], tty=tty)
            f = self.home / '.config' / 'vp' / 'ncbi_api_key.key'
            self.assertEqual(code, 0, out + err); self.assertIn('PubMed (NCBI): OK', out)
            self.assertEqual(f.read_text(), SECRET + '\n')
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600); self.assertEqual(stat.S_IMODE(f.parent.stat().st_mode), 0o700)
            for part in (SECRET, SECRET[:6], SECRET[-6:]): self.assertNotIn(part, out + err)
            self.assertEqual([p.name for p in f.parent.iterdir()], ['ncbi_api_key.key'])   # no temporary file left

    def test_refused(self):
        gw.urllib.request.urlopen = self.urlopen(True)
        code, out, err = self.run_main(['ncbi'], [SECRET])
        self.assertEqual(code, 1); self.assertIn('PubMed (NCBI): key refused — check you copied it whole', out); self.assertNotIn(SECRET, out + err)

    def test_openalex_absent_check(self):
        code, out, _ = self.run_main(['openalex', '--check'])
        self.assertEqual(code, 1); self.assertIn('OpenAlex: not installed (run: python3 -I tools/setup_keys.py openalex)', out)

    def piste(self, oauth, api):
        calls = []
        def f(url, data=None, headers=None, cred=None):
            calls.append(url); assert SECRET not in url
            if 'oauth' in url: return oauth, json.dumps({'access_token': 'tok-12345678', 'expires_in': 3600}).encode()
            st = api('judilibre' if 'judilibre' in url else 'legifrance'); return st, (b'{"results": [], "total": 0}' if st == 200 else b'')
        gw.piste_http = f
        return calls

    def test_piste_pair_ok_and_not_subscribed(self):
        calls = self.piste(200, lambda api: 200 if api == 'judilibre' else 403)
        code, out, err = self.run_main(['PISTE'], ['client-id-0001', SECRET], tty=True)
        d = self.home / '.config' / 'vp'
        self.assertEqual((d / 'piste_client_id.key').read_text(), 'client-id-0001\n'); self.assertEqual((d / 'piste_client_secret.key').read_text(), SECRET + '\n')
        self.assertEqual(code, 1); self.assertIn('Judilibre: OK', out)
        self.assertIn('Légifrance: identifiers accepted but the application is not subscribed to this API (piste.gouv.fr > Applications > tick Légifrance)', out)
        self.assertNotIn(SECRET, out + err); self.assertNotIn('client-id-0001', out + err); self.assertEqual(sum('oauth' in u for u in calls), 1)
        self.piste(200, lambda api: 200)
        self.assertEqual(self.run_main(['piste', '--check'])[0:2], (0, 'Judilibre: OK\nLégifrance: OK\n'))

    def test_piste_refused(self):
        self.piste(401, lambda api: 200)
        code, out, _ = self.run_main(['piste_client_secret'], ['client-id-0001', SECRET])
        self.assertEqual(code, 1); self.assertEqual(out.count('identifiers refused'), 2)

    def test_fred_ok_and_refused(self):
        def stub(refuse):
            def f(req, timeout=None):
                url = req.full_url; self.assertTrue(url.startswith('https://api.stlouisfed.org/fred/series/search?')); self.assertIn('realtime_start=', url)
                if refuse: raise urllib.error.HTTPError(url, 400, 'Bad Request', {}, io.BytesIO(b'{"error_code":400,"error_message":"Bad Request.  The value for variable api_key is not registered."}'))
                return Resp(b'{"count": 1, "seriess": [{"id": "UNRATE", "title": "Unemployment Rate", "observation_start": "1948-01-01"}]}')
            return f
        for refuse, verdict, code in ((False, 'FRED / ALFRED: OK', 0), (True, 'FRED / ALFRED: key refused', 1)):
            gw.urllib.request.urlopen = stub(refuse)
            c, out, err = self.run_main(['fred'], [SECRET])
            self.assertEqual(c, code); self.assertIn(verdict, out); self.assertNotIn(SECRET, out + err)

    def test_remove(self):
        self.piste(200, lambda api: 200); self.run_main(['piste'], ['client-id-0001', SECRET])
        d = self.home / '.config' / 'vp'
        self.assertEqual(self.run_main(['piste', '--remove'], ['n'])[0], 0); self.assertTrue((d / 'piste_client_id.key').exists())
        code, out, _ = self.run_main(['piste', '--remove'], ['y'])
        self.assertEqual(code, 0); self.assertFalse(list(d.glob('*.key'))); self.assertIn('Deleted', out)
        self.assertIn('Nothing to remove', self.run_main(['piste', '--remove'])[1])

    def test_unknown_empty_and_menu(self):
        code, out, err = self.run_main(['nope'])
        self.assertEqual(code, 2); self.assertIn("Unknown key name 'nope'", err); self.assertIn('OPENALEX_KEY', err); self.assertIn('OPENROUTER_API_KEY', err)
        self.assertEqual(self.run_main(['swh'], [''])[0], 2); self.assertFalse((self.home / '.config' / 'vp' / 'swh_token.key').exists())
        self.assertEqual(self.run_main(['swh'], ['two words'])[0], 2)
        code, out, _ = self.run_main([], [''])
        self.assertEqual(code, 0); self.assertIn('piste', out); self.assertIn('[absent]', out)
        code, out, _ = self.run_main([], ['s2', SECRET])       # menu by name, a declared key with no engine: written, no live check
        self.assertEqual(code, 0); self.assertIn('no live check', out); self.assertIn('semanticscholar.org', out)
        self.assertEqual(self.run_main(['s2', '--check'])[0], 0)
        n = [e['name'] for e in SK.entries()].index('openalex') + 1
        self.assertIn('OPENALEX_KEY', self.run_main([], [str(n), ''])[1])


if __name__ == '__main__':
    unittest.main()
