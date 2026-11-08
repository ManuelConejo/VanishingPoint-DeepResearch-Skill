#!/usr/bin/env python3
"""Offline test of the optional key broker (tools/key_broker.py, config.json key_broker, KEYS.md "Key broker"): the real broker served on
a temporary Unix socket, its upstream a stubbed HTTPS handler (no network); the client side has no key in its environment nor in its
~/.config/vp. With VP_KEY_BROKER set the run reads no key, the key reaches only the allowed host in the declared place, everything else is
refused before any upstream request, no key appears in an answer, an error, a state file nor the broker log, a rejected key still falls
back as today (key_invalid), the contradictor and setup_keys --check go through the broker, PISTE is served on the same socket, and the
routes are exactly the ones derived from the sources' key blocks and the contradictor providers."""
import base64, contextlib, io, json, os, pathlib, socket, sys, tempfile, threading, unittest, urllib.error, urllib.parse, urllib.request
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); sys.path.insert(0, str(P))
import gateway as gw, code_sources as sc, key_broker as kb, piste_broker as pb, check_keys as ck, setup_keys as sk, contradictor as ctr   # noqa: E401,E402
import sources as reg   # noqa: E402
from sources import fred as fred_src, openalex as oa_src, pubmed as pm_src   # noqa: E402
from test_engines_piste import Stub   # noqa: E402

CFG = kb.load_config()
KEYS = {'OPENALEX_KEY': 'oa-S3CR3T-0123456789abc', 'NCBI_API_KEY': 'ncbi+S3CR3T/0123456789', 'VP_GITHUB_TOKEN': 'ghp_S3CR3Ttoken0123456789',
        'SWH_TOKEN': 'swh-S3CR3T-token-0123456789', 'OPENROUTER_API_KEY': 'sk-or-S3CR3T-0123456789', 'GEMINI_API_KEY': 'gem-S3CR3T-0123456789',
        'S2_API_KEY': 's2-S3CR3T-0123456789', 'PISTE_CLIENT_ID': 'piste-S3CR3T-id-0123', 'PISTE_CLIENT_SECRET': 'piste-S3CR3T-secret-0123'}
SECRETS = [v for v in KEYS.values()] + [urllib.parse.quote(v, safe='') for v in KEYS.values()] + ["S3CR3T"]
OA = 'https://api.openalex.org/works'
EUTILS = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
PROVIDER = CFG['contradictor']['providers']['openrouter']
NOWAIT = {h: 0 for h in sc.INTERVAL}                                             # no pacing wait in the CodeClient tests


def env_names():
    return {n for _, k in reg.key_specs() for n in k['vars']} | {p['key'] for p in CFG['contradictor']['providers'].values() if p.get('key')}


class KeyBroker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = pathlib.Path(self.tmp.name)
        self.state, self.sock, self.home = d / 'state', str(d / 'kb.sock'), d / 'home'
        self.home.mkdir()
        self.saved = {k: os.environ.pop(k, None) for k in env_names() | {CFG['key_broker']['env'], CFG['piste_broker']['env'], 'HOME', 'VP_STATE',
                                                                          'VP_CONTRADICTOR_URL_OPENROUTER'}}
        os.environ['HOME'] = str(self.home)                                       # the client: no key file, no key variable
        gw.STATE = self.state; self.iv = dict(gw.INTERVAL)
        for h in ('api.openalex.org', 'eutils.ncbi.nlm.nih.gov', 'api.stlouisfed.org', 'api.piste.gouv.fr', 'oauth.piste.gouv.fr'): gw.INTERVAL[h] = 0
        self.kiv = dict(gw.KEY_INTERVAL); gw.KEY_INTERVAL.clear()
        self.held = dict(KEYS); self.routes = {}
        self.stub = Stub(self.route)                                              # upstream of the broker
        self.direct = Stub(self.route)                                            # the run's own key-less requests
        self.saved_opener = urllib.request._opener
        urllib.request.install_opener(urllib.request.build_opener(self.direct))
        self.log = kb.LOG = io.StringIO()
        self.broker = kb.Broker(CFG, opener=urllib.request.build_opener(kb._NoRedirect(), self.stub), keys=lambda n: self.held.get(n))
        self.start([os.getuid()])
        os.environ[CFG['key_broker']['env']] = self.sock; kb.forget()

    def start(self, allow, piste=False):
        self.srv = kb.serve(self.sock, CFG, allow, self.broker, piste=piste)
        threading.Thread(target=self.srv.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()

    def restart(self, allow, piste=False):
        self.srv.shutdown(); self.srv.server_close(); self.start(allow, piste); kb.forget()

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); kb.forget()
        urllib.request._opener = self.saved_opener
        gw.INTERVAL.clear(); gw.INTERVAL.update(self.iv); gw.KEY_INTERVAL.update(self.kiv)
        for k, v in self.saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.tmp.cleanup()

    # ---- helpers
    def route(self, m, u, h, b):
        p = urllib.parse.urlsplit(u)
        for prefix, fn in self.routes.items():
            if u.startswith(prefix): return fn(m, u, h, b)
        return 200, {'ok': True, 'host': p.hostname}

    def raw(self, req):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(10); s.connect(self.sock); s.sendall(req if isinstance(req, bytes) else json.dumps(req).encode() + b'\n')
            buf = b''
            while True:
                try: c = s.recv(65536)
                except ConnectionResetError: c = b''                                  # closed without an answer
                if not c: break
                buf += c
        return json.loads(buf) if buf else None

    def fetch_req(self, url, headers=None, method='GET', body=None):
        return {'op': 'fetch', 'method': method, 'url': url, 'headers': headers or {}, 'body': base64.b64encode(body).decode() if body is not None else None}

    def no_leak(self, *outs):
        texts = [self.log.getvalue()] + [json.dumps(o, ensure_ascii=False, default=str) for o in outs]
        texts += [f.read_bytes().decode('utf-8', 'replace') + f.name for f in pathlib.Path(self.tmp.name).rglob('*') if f.is_file()]
        texts += [c['url'] + json.dumps(c['headers']) + (c['body'] or '') for c in self.direct.calls]   # the run's own requests
        for t in texts:
            for s in SECRETS: self.assertNotIn(s, t)

    # ---- the client holds nothing
    def test_client_has_no_key_and_reads_none(self):
        self.assertFalse(env_names() & set(os.environ))
        self.assertEqual(list(self.home.rglob('*')), [])
        self.assertEqual(sc.key('OPENALEX_KEY'), 'VPKB.OPENALEX_KEY.VPKB')
        self.assertEqual(sc.read_token(), 'VPKB.VP_GITHUB_TOKEN.VPKB')
        self.assertIsNone(sc.key('FRED_API_KEY'))                                 # not held by the broker
        self.assertIsNone(sc.key('PISTE_CLIENT_ID'))                              # the pair has its own protocol, never a placeholder
        # even a decoy value left in the run's environment or files is never read in broker mode
        os.environ['FRED_API_KEY'] = 'decoy-S3CR3T-env'; (self.home / '.config' / 'vp').mkdir(parents=True)
        (self.home / '.config' / 'vp' / 'mistral_api_key.key').write_text('decoy-S3CR3T-file')
        try:
            self.assertIsNone(sc.key('FRED_API_KEY')); self.assertIsNone(sc.key('MISTRAL_API_KEY'))
        finally:
            os.environ.pop('FRED_API_KEY'); (self.home / '.config' / 'vp' / 'mistral_api_key.key').unlink()
        os.environ['VP_CONTACT'] = 'team@example.org'                             # not a secret: same rule as before
        try: self.assertEqual(sc.key('VP_CONTACT'), 'team@example.org')
        finally: os.environ.pop('VP_CONTACT')

    def test_without_variable_unchanged(self):
        os.environ.pop(CFG['key_broker']['env'])
        os.environ['OPENALEX_KEY'] = 'direct-value-1234'
        try:
            self.assertEqual(sc.key('OPENALEX_KEY'), 'direct-value-1234')
            self.assertFalse(kb.needs(OA + '?api_key=VPKB.OPENALEX_KEY.VPKB'))
        finally: os.environ.pop('OPENALEX_KEY')

    # ---- the key arrives at the allowed host, in its place
    def test_openalex_query_key_through_fetch(self):
        url = OA + '?search=x' + oa_src.oa_key()
        self.assertIn('api_key=VPKB.OPENALEX_KEY.VPKB', url)
        self.assertEqual(json.loads(gw.fetch(url))['host'], 'api.openalex.org')
        self.assertEqual(len(self.stub.calls), 1); self.assertEqual(self.direct.calls, [])
        sent = urllib.parse.parse_qs(urllib.parse.urlsplit(self.stub.calls[0]['url']).query)
        self.assertEqual(sent['api_key'], [KEYS['OPENALEX_KEY']]); self.assertEqual(sent['search'], ['x'])
        self.assertIn('host=api.openalex.org', self.log.getvalue()); self.assertIn('keys=OPENALEX_KEY', self.log.getvalue())
        self.no_leak()

    def test_github_bearer_through_codeclient(self):
        c = sc.CodeClient(cache_dir=self.state / 'code', interval=NOWAIT)
        self.assertEqual(c.json('https://api.github.com/search/code?q=x', sc.read_token())['host'], 'api.github.com')
        self.assertEqual(self.stub.calls[0]['headers']['authorization'], 'Bearer ' + KEYS['VP_GITHUB_TOKEN'])
        self.routes['https://api.github.com/repos/a/b'] = lambda *a: (301, b'', {'Location': 'https://api.github.com/repositories/42?t=' + KEYS['VP_GITHUB_TOKEN']})
        with self.assertRaisesRegex(ValueError, 'redirect_refused'): c.json('https://api.github.com/repos/a/b', sc.read_token())
        self.assertEqual(len(self.stub.calls), 2)                                 # never followed
        self.assertTrue(list(c.redirects.values())[0].startswith('https://api.github.com/repositories/42'))
        self.no_leak(c.redirects, c.receipts)

    def test_rate_limit_headers_forwarded(self):
        self.routes['https://api.github.com/rate'] = lambda *a: (403, {'message': 'rate'}, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1999999999'})
        c = sc.CodeClient(cache_dir=self.state / 'code', interval=NOWAIT)
        with self.assertRaisesRegex(ValueError, 'rate_limited'): c.json('https://api.github.com/rate', sc.read_token())
        self.assertEqual(c.rate_reset['api.github.com'], 1999999999)

    # ---- refusals: nothing sent upstream
    def test_refused_before_any_request(self):
        ph = lambda n: 'VPKB.%s.VPKB' % n   # noqa: E731
        bad = [self.fetch_req('https://evil.example/works?api_key=' + ph('OPENALEX_KEY')),                    # host not allowed
               self.fetch_req('https://api.openalex.org.evil.example/w?api_key=' + ph('OPENALEX_KEY')),       # not the exact host
               self.fetch_req('https://api.github.com/x?api_key=' + ph('OPENALEX_KEY')),                      # another key's host
               self.fetch_req('https://api.openalex.org/x', {'Authorization': 'Bearer ' + ph('VP_GITHUB_TOKEN')}),
               self.fetch_req('http://api.openalex.org/works?api_key=' + ph('OPENALEX_KEY')),                 # not https
               self.fetch_req('https://api.openalex.org:8443/works?api_key=' + ph('OPENALEX_KEY')),
               self.fetch_req('https://u:p@api.openalex.org/works?api_key=' + ph('OPENALEX_KEY')),
               self.fetch_req('https://api.openalex.org/works?api_key=' + ph('OPENALEX_KEY') + '#f'),
               self.fetch_req('https://api.openalex.org/' + ph('OPENALEX_KEY') + '?api_key=' + ph('OPENALEX_KEY')),   # placeholder in the path
               self.fetch_req('https://api.openalex.org/works?filter=' + ph('OPENALEX_KEY')),                 # wrong parameter
               self.fetch_req('https://api.openalex.org/works?api_key=x' + ph('OPENALEX_KEY')),               # not the whole value
               self.fetch_req('https://api.openalex.org/works', {'Authorization': 'Bearer ' + ph('OPENALEX_KEY')}),    # wrong place
               self.fetch_req('https://api.github.com/x', {'X-Api-Key': ph('VP_GITHUB_TOKEN')}),
               self.fetch_req('https://api.github.com/x', {'Authorization': 'token ' + ph('VP_GITHUB_TOKEN')}),
               self.fetch_req('https://api.openalex.org/works?q=1'),                                          # no key: never an open proxy
               self.fetch_req('https://api.openalex.org/works?api_key=' + ph('NOT_A_KEY')),                    # no route
               self.fetch_req('https://api.openalex.org/works?api_key=' + ph('VP_CONTACT')),                   # not a secret: no route
               self.fetch_req('https://api.openalex.org/works?api_key=' + ph('OPENALEX_KEY'), method='POST', body=b'{}'),   # POST on a source key
               self.fetch_req('https://api.openalex.org/works?api_key=' + ph('OPENALEX_KEY'), method='DELETE'),
               self.fetch_req('https://api.openalex.org/works?api_key=' + ph('OPENALEX_KEY'), {'Cookie': 'a=b'}),           # header not allowed
               self.fetch_req('https://api.openalex.org/works?api_key=' + ph('OPENALEX_KEY'), {'Accept': 'x\r\nX-Evil: 1'}),
               self.fetch_req('https://openrouter.ai/api/v1/other', {'Authorization': 'Bearer ' + ph('OPENROUTER_API_KEY')}, 'POST', b'{}'),
               self.fetch_req('https://openrouter.ai/api/v1/chat/completions', {'Authorization': 'Bearer ' + ph('OPENROUTER_API_KEY')}),  # GET chat
               self.fetch_req('https://openrouter.ai/api/v1/chat/completions', {'Authorization': 'Bearer ' + ph('OPENROUTER_API_KEY')}, 'POST',
                              ('{"x": "' + ph('OPENROUTER_API_KEY') + '"}').encode()),                         # placeholder in the body
               {'op': 'fetch', 'method': 'GET', 'url': 'https://api.openalex.org/works?api_key=' + ph('OPENALEX_KEY'), 'body': '!!'},
               {'op': 'nope'}, [1]]
        for q in bad: self.assertTrue(self.raw(q)['error'].startswith('refused:'), q)
        self.assertTrue(self.raw(b'not json\n')['error'].startswith('refused:'))
        self.assertTrue(self.raw(b'{"op": "keys", "x": "' + b'x' * CFG['key_broker']['max_request_bytes'] + b'"}\n')['error'].startswith('refused:'))
        self.assertEqual(self.stub.calls, [])
        self.no_leak()

    def test_not_configured_and_short_key(self):
        r = self.raw(self.fetch_req('https://api.stlouisfed.org/fred/series?api_key=VPKB.FRED_API_KEY.VPKB'))
        self.assertEqual(r, {'error': 'not_configured'})
        self.held['FRED_API_KEY'] = 'short'
        r = self.raw(self.fetch_req('https://api.stlouisfed.org/fred/series?api_key=VPKB.FRED_API_KEY.VPKB'))
        self.assertEqual(r, {'error': 'credential_invalid'}); self.assertEqual(self.stub.calls, [])
        self.assertNotIn('FRED_API_KEY', self.raw({'op': 'keys'})['keys'])

    def test_peer_of_another_uid_closed(self):
        self.restart([os.getuid() + 1])
        self.assertIsNone(self.raw({'op': 'keys'}))
        self.assertIsNone(sc.key('OPENALEX_KEY'))                                 # unreachable broker: every key absent, never a fallback to files
        self.assertEqual(self.stub.calls, [])

    # ---- no key in answers, errors, logs
    def test_answer_and_errors_masked(self):
        k = KEYS['NCBI_API_KEY']
        self.routes[EUTILS] = lambda m, u, h, b: (200, ('echo ' + k + ' / ' + urllib.parse.quote(k, safe='') + ' / ' + urllib.parse.quote_plus(k)).encode(),
                                                  {'Location': 'https://x/?k=' + k, 'X-Secret': k})
        r = self.raw(self.fetch_req(EUTILS + '?db=pubmed&term=x&api_key=VPKB.NCBI_API_KEY.VPKB'))
        self.assertEqual(r['status'], 200)
        self.assertEqual(base64.b64decode(r['body']).count(kb.MASK), 3)
        self.assertNotIn('X-Secret', r['headers']); self.assertIn('Location', r['headers'])

        def boom(m, u, h, b): raise urllib.error.URLError('cannot reach ' + u)
        self.routes[EUTILS] = boom
        r = self.raw(self.fetch_req(EUTILS + '?api_key=VPKB.NCBI_API_KEY.VPKB'))
        self.assertEqual(r, {'error': 'transport_error:URLError'})
        self.routes[EUTILS] = lambda m, u, h, b: (200, b'\x1f\x8b compressed echo', {'Content-Encoding': 'gzip'})
        self.assertEqual(self.raw(self.fetch_req(EUTILS + '?api_key=VPKB.NCBI_API_KEY.VPKB')), {'error': 'encoded_answer'})
        self.assertEqual(self.stub.calls[-1]['headers']['accept-encoding'], 'identity')
        self.assertTrue(self.raw(self.fetch_req(EUTILS + '?api_key=VPKB.NCBI_API_KEY.VPKB', {'Accept-Encoding': 'gzip'}))['error'].startswith('refused:'))
        self.assertNotIn('api_key', self.log.getvalue())                          # the log carries names and host, never a URL
        self.no_leak(r)

    # ---- key_invalid fallbacks, decided by the client as today
    def test_ncbi_rejected_key_falls_back_keyless(self):
        def eutils(m, u, h, b):
            if 'api_key=' in u: return 400, ('{"error":"API key invalid","api-key":"' + KEYS['NCBI_API_KEY'] + '"}').encode()
            return 200, {'esearchresult': {'idlist': []}}
        self.routes[EUTILS] = eutils
        out = gw.fetch(EUTILS + '?db=pubmed&term=x' + pm_src.ncbi_key())
        self.assertEqual(json.loads(out), {'esearchresult': {'idlist': []}})
        self.assertEqual(sc.invalid_keys(self.state), {'NCBI_API_KEY'})
        self.assertEqual(len(self.stub.calls), 1); self.assertEqual(len(self.direct.calls), 1)   # retried once without the key, directly
        self.assertNotIn('api_key', self.direct.calls[0]['url'])
        self.assertEqual(pm_src.ncbi_key(), '')                                   # dropped for the rest of the run
        self.no_leak(out)

    def test_openalex_rejected_key(self):
        self.routes[OA] = lambda m, u, h, b: (403, {'error': 'bad key'}) if 'api_key=' in u else (200, {'results': []})
        self.assertEqual(json.loads(gw.fetch(OA + '?search=y' + oa_src.oa_key())), {'results': []})
        self.assertEqual(sc.invalid_keys(self.state), {'OPENALEX_KEY'}); self.assertEqual(oa_src.oa_key(), '')
        self.no_leak()

    def test_fred_key_invalid_and_missing(self):
        B = gw.Barrier('2020-01-01')
        with self.assertRaises(fred_src.DataSkip) as e: fred_src.fred_json('series/search', B, search_text='gdp')
        self.assertEqual(e.exception.reason, 'credential_missing'); self.assertEqual(self.stub.calls + self.direct.calls, [])   # not held: 0 request
        self.held['FRED_API_KEY'] = 'fred-S3CR3T-0123456789'; SECRETS.append('fred-S3CR3T-0123456789'); kb.forget()
        self.routes['https://api.stlouisfed.org/'] = lambda m, u, h, b: (400, {'error_code': 400, 'error_message':
                                                                                'Bad Request. The value for variable api_key is not registered: fred-S3CR3T-0123456789'})
        with self.assertRaises(fred_src.DataSkip) as e: fred_src.fred_json('series/search', B, search_text='gdp')
        self.assertEqual(e.exception.reason, 'key_invalid'); self.assertEqual(sc.invalid_keys(self.state), {'FRED_API_KEY'})
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(self.stub.calls[0]['url']).query)['api_key'], ['fred-S3CR3T-0123456789'])
        self.no_leak(str(e.exception))

    def test_swh_rejected_token_anonymous_retry(self):
        swh = 'https://archive.softwareheritage.org/api/1/origin/search/x/'
        self.routes[swh] = lambda m, u, h, b: (401, {'detail': 'Invalid token ' + KEYS['SWH_TOKEN']}) if h.get('authorization') else (200, [{'url': 'https://x'}])
        c = sc.CodeClient(cache_dir=self.state / 'code', interval=NOWAIT); c.opener.add_handler(self.direct)
        self.assertEqual(sc.Provenance(c)._json(swh + '?limit=1'), [{'url': 'https://x'}])
        self.assertEqual(self.stub.calls[0]['headers']['authorization'], 'Bearer ' + KEYS['SWH_TOKEN'])
        self.assertEqual(sc.invalid_keys(self.state / 'code'), {'SWH_TOKEN'})
        self.assertNotIn('authorization', self.direct.calls[0]['headers'])
        self.no_leak(c.receipts)

    # ---- contradictor and setup_keys
    def test_contradictor_through_broker(self):
        url = PROVIDER['url']
        self.routes[url] = lambda m, u, h, b: (200, {'choices': [{'message': {'content': '{"verdict": "ok"}'}}], 'usage': {'cost': 0.01}})
        spec = {'provider': PROVIDER, 'via': 'openrouter', 'model': 'test/model'}; self.state.mkdir(parents=True, exist_ok=True)
        txt, m = ctr.http_call(spec, 'prompt', self.state / 'c.trace.jsonl')
        self.assertEqual(txt, '{"verdict": "ok"}'); self.assertEqual(m['usd'], 0.01)
        c = self.stub.calls[-1]
        self.assertEqual((c['method'], c['url'], c['headers']['authorization']), ('POST', url, 'Bearer ' + KEYS['OPENROUTER_API_KEY']))
        self.assertEqual(json.loads(c['body'])['model'], 'test/model')
        self.routes[url] = lambda m, u, h, b: (401, {'error': 'invalid key ' + KEYS['OPENROUTER_API_KEY']})
        txt, m = ctr.http_call(spec, 'prompt', self.state / 'd.trace.jsonl')
        self.assertIsNone(txt); self.assertEqual(m['error'], 'HTTP 401'); self.assertIn('[key withheld]', m['detail'])
        os.environ['VP_CONTRADICTOR_URL_OPENROUTER'] = 'https://evil.example/v1/chat/completions'   # an override cannot move the key
        n = len(self.stub.calls)
        txt, m = ctr.http_call(spec, 'prompt', self.state / 'e.trace.jsonl')
        self.assertIsNone(txt); self.assertIn('refused:host', m['error']); self.assertEqual(len(self.stub.calls), n)
        self.held.pop('GEMINI_API_KEY'); kb.forget()
        txt, m = ctr.http_call({'provider': CFG['contradictor']['providers']['gemini'], 'via': 'gemini', 'model': 'g'}, 'p', self.state / 'f.trace.jsonl')
        self.assertEqual(m['error'], 'credential_missing')
        self.no_leak(m)

    def test_setup_keys_check_and_install(self):
        e = sk.find('openrouter')
        self.assertEqual(sk.state(e), 'present')
        self.assertEqual(sk.check_provider(e), (True, 'OK'))
        self.assertEqual(self.stub.calls[-1]['url'], PROVIDER['check_url'])
        self.assertEqual(self.stub.calls[-1]['headers']['authorization'], 'Bearer ' + KEYS['OPENROUTER_API_KEY'])
        self.routes[PROVIDER['check_url']] = lambda *a: (401, {})
        self.assertEqual(sk.check_provider(e)[0], False)
        err = io.StringIO()
        with contextlib.redirect_stderr(err): self.assertEqual(sk.install(sk.find('fred')), 2)
        self.assertIn('broker', err.getvalue()); self.assertEqual(list(self.home.rglob('*.key')), [])
        self.no_leak()

    def test_check_keys_names_from_broker(self):
        self.assertTrue(ck.present('OPENALEX_KEY')); self.assertFalse(ck.present('FRED_API_KEY'))
        b = ck.broker_info()
        self.assertEqual((b['socket'], b['reachable']), (self.sock, True))
        self.assertEqual(set(b['held']), set(KEYS) - {'PISTE_CLIENT_ID', 'PISTE_CLIENT_SECRET'} - {'S2_API_KEY'} | {'S2_API_KEY'})
        rep = ck.report(); t = ck.text(rep)
        self.assertIn('Key broker: ' + self.sock + ' holds ', t); self.assertIn('OPENALEX_KEY', t)
        os.environ[CFG['key_broker']['env']] = self.sock + '.missing'; kb.forget()
        self.assertIn('does not answer', ck.broker_line(ck.broker_info())); self.assertFalse(ck.present('OPENALEX_KEY'))
        self.no_leak(rep, t)

    # ---- PISTE on the same socket
    def test_piste_served_by_key_broker(self):
        tok = 'piste-S3CR3T-token-abcdef'; SECRETS.append(tok)
        pc = pb.load_config(P.parent / 'tools' / 'config.json'); pc['intervals'] = {}
        self.routes[pc['oauth']] = lambda *a: (200, {'access_token': tok, 'expires_in': 3600})
        self.routes['https://api.piste.gouv.fr/'] = lambda *a: (200, {'results': [], 'total': 0})
        up = pb.Upstream(pc, opener=urllib.request.build_opener(pb._NoRedirect(), self.stub), credentials=lambda: tuple(self.held.get(k) for k in pb.KEYS))
        self.restart([os.getuid()], piste=(pb, pc, up))
        self.assertTrue(gw.piste_present()); self.assertEqual(gw.piste_broker(), self.sock)
        r = gw.search_judilibre('contrat', 5, gw.Barrier('2020-01-01'))
        self.assertEqual(r[0], [])
        api = [c for c in self.stub.calls if 'api.piste.gouv.fr' in c['url']]
        self.assertEqual(api[0]['headers']['authorization'], 'Bearer ' + tok)
        self.assertFalse((self.state / gw.PISTE_TOKEN).exists())
        self.held.pop('PISTE_CLIENT_SECRET'); kb.forget(); self.assertFalse(gw.piste_present())
        self.no_leak(r)

    # ---- routes derived from the sources and the providers
    def test_routes_are_derived(self):
        routes = kb.build_routes(CFG)
        want = {}
        for _, k in reg.key_specs():
            s = k['send']
            if s == 'bearer' or s.startswith(('query:', 'header:')):
                for v in k['vars']:
                    if v not in CFG['key_broker']['not_secret']: want[v] = (s, set(k['hosts']))
        for p in CFG['contradictor']['providers'].values():
            if p.get('key') and p['url'].startswith('https://'): want[p['key']] = ('bearer', {urllib.parse.urlsplit(p['url']).hostname})
        self.assertEqual({n: (r['send'], r['hosts']) for n, r in routes.items()}, want)
        self.assertEqual(routes['OPENROUTER_API_KEY']['post'], {('openrouter.ai', '/api/v1/chat/completions')})
        self.assertNotIn('PISTE_CLIENT_ID', routes); self.assertNotIn('VP_CONTACT', routes)
        self.assertEqual(routes['OPENALEX_KEY'], {'send': 'query:api_key', 'hosts': {'api.openalex.org'}, 'post': set(), 'get_paths': None})

    def test_broker_reads_its_own_key_files(self):
        d = pathlib.Path(self.tmp.name) / 'broker-keys'; d.mkdir()
        (d / 'openalex_key.key').write_text(KEYS['OPENALEX_KEY'] + '\n')
        self.assertEqual(kb.read_key('OPENALEX_KEY', d), KEYS['OPENALEX_KEY'])
        os.environ['CREDENTIALS_DIRECTORY'] = str(d)
        try: self.assertEqual(kb.read_key('OPENALEX_KEY'), KEYS['OPENALEX_KEY']); self.assertIsNone(kb.read_key('NCBI_API_KEY'))
        finally: os.environ.pop('CREDENTIALS_DIRECTORY')


if __name__ == '__main__':
    unittest.main()
