#!/usr/bin/env python3
"""Offline test of the optional PISTE broker (tools/piste_broker.py, config.json piste_broker, KEYS.md): the real broker served on a
temporary Unix socket, its upstream a stubbed HTTPS handler (no network). With the broker variable set the gateway never reads the pair,
writes no piste-token.json, and no secret reaches its state or output; the broker forwards only the declared routes (method, host, path,
body), never answers with the token, renews it once on a 401, maps its verdicts to the same skips and errors; peers of another uid are
closed; the declared routes are exactly the endpoints piste.py calls."""
import base64, io, json, os, pathlib, socket, sys, tempfile, threading, unittest, urllib.parse, urllib.request
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); sys.path.insert(0, str(P))
import gateway as gw, code_sources as sc, piste_broker as pb   # noqa: E401,E402
from test_engines_piste import Stub, CID, CSEC, TOK, SECRETS, LAW   # noqa: E402

pb.LOG = io.StringIO()                                                                   # quiet broker log
CFG = pb.load_config(P.parent / 'tools' / 'config.json')
JL_HIT = {'results': [{'id': '5fca0d4e8a3ad4b5c66b8b41', 'decision_date': '2019-03-14', 'number': '18-10.000', 'jurisdiction': 'cc', 'chamber': 'civ1'}], 'total': 1}
LF_HIT = {'results': [], 'totalResultNumber': 0}


def route(state):
    """Upstream stub: OAuth gives TOK; the API answers by path (state['api'] may override)."""
    def r(m, u, h, b):
        if u == CFG['oauth']: return state.get('oauth', (200, {'access_token': TOK, 'expires_in': 3600}))
        if 'api' in state: return state['api'](m, u, h, b)
        return 200, JL_HIT if '/judilibre/' in u else LF_HIT
    return r


class Broker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = pathlib.Path(self.tmp.name)
        self.state = d / 'state'; self.sock = str(d / 'b.sock'); self.up = {}
        self.saved = {k: os.environ.pop(k, None) for k in gw.PISTE_KEYS + (gw.BROKER['env'],)}
        self.home = os.environ.get('HOME'); os.environ['HOME'] = str(d)                       # no ~/.config/vp key file on the client side
        gw.STATE = self.state; self.iv = dict(gw.INTERVAL); gw.INTERVAL.update({'oauth.piste.gouv.fr': 0, 'api.piste.gouv.fr': 0})
        self.direct = Stub(lambda *a: (500, {})); gw._PISTE_OPENER.add_handler(self.direct)      # the direct path must stay unused
        self.stub = Stub(route(self.up))
        cfg = dict(CFG, intervals={})
        self.upstream = pb.Upstream(cfg, opener=urllib.request.build_opener(pb._NoRedirect(), self.stub), credentials=lambda: self.up.get('pair', (CID, CSEC)))
        self.start(cfg, [os.getuid()])
        os.environ[gw.BROKER['env']] = self.sock

    def start(self, cfg, allow):
        self.srv = pb.serve(self.sock, cfg, allow, self.upstream)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()
        gw._PISTE_OPENER.handlers.remove(self.direct); gw.INTERVAL.clear(); gw.INTERVAL.update(self.iv)
        for k, v in self.saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        if self.home is None: os.environ.pop('HOME', None)
        else: os.environ['HOME'] = self.home
        self.tmp.cleanup()

    def raw(self, req):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(10); s.connect(self.sock); s.sendall(req if isinstance(req, bytes) else json.dumps(req).encode() + b'\n')
            buf = b''
            while True:
                c = s.recv(65536)
                if not c: break
                buf += c
        return json.loads(buf) if buf else None

    def no_leak(self, *outs):
        files = [f for f in self.state.rglob('*') if f.is_file()]
        self.assertNotIn(gw.PISTE_TOKEN, [f.name for f in files])
        for f in files:
            t = f.read_bytes().decode('utf-8', 'replace')
            for s in SECRETS: self.assertNotIn(s, t, f.name)
        for o in outs:
            for s in SECRETS: self.assertNotIn(s, json.dumps(o, ensure_ascii=False))

    def test_search_through_broker(self):
        g = gw.Gateway([LAW], T='2020-01-01', run='t-broker', state=self.state)
        a = g.call('search-judilibre', 'responsabilité contractuelle'); b = g.call('search-legifrance', 'contrat')
        self.assertEqual([x['id'] for x in a['results']], ['judilibre:5fca0d4e8a3ad4b5c66b8b41'])
        self.assertEqual(b['results'], [])
        self.assertEqual(self.direct.calls, [])
        api = [c for c in self.stub.calls if c['url'] != CFG['oauth']]
        self.assertEqual([c['method'] for c in api], ['GET', 'POST', 'POST'])
        for c in api: self.assertEqual(c['headers']['authorization'], 'Bearer ' + TOK)
        self.assertEqual(len([c for c in self.stub.calls if c['url'] == CFG['oauth']]), 1)          # token kept in the broker's memory
        rec = [json.loads(x) for x in (self.state / 'requests.jsonl').read_text().splitlines()]
        self.assertTrue(rec and all(r['via'] == 'broker' and r['host'] == 'api.piste.gouv.fr' for r in rec))
        self.no_leak(a, b)

    def test_answer_never_carries_token(self):
        r = self.raw({'method': 'GET', 'url': gw.JUDILIBRE + 'search?query=x', 'body': None})
        self.assertEqual(r['status'], 200); self.assertEqual(json.loads(base64.b64decode(r['body'])), JL_HIT)
        self.assertNotIn(TOK, json.dumps(r))

    def test_routes_refused(self):
        bad = [{'method': 'GET', 'url': gw.JUDILIBRE + 'export?x=1', 'body': None},                       # path not declared
               {'method': 'POST', 'url': gw.JUDILIBRE + 'search', 'body': '{}'},                           # method of another route
               {'method': 'GET', 'url': 'https://evil.example/cassation/judilibre/v1.0/search', 'body': None},
               {'method': 'GET', 'url': 'http://api.piste.gouv.fr/cassation/judilibre/v1.0/search', 'body': None},
               {'method': 'GET', 'url': 'https://api.piste.gouv.fr:8443/cassation/judilibre/v1.0/search', 'body': None},
               {'method': 'GET', 'url': 'https://u:p@api.piste.gouv.fr/cassation/judilibre/v1.0/search', 'body': None},
               {'method': 'GET', 'url': gw.JUDILIBRE + 'search', 'body': '{}'},                            # body on a GET
               {'method': 'POST', 'url': gw.LEGIFRANCE + 'search?x=1', 'body': '{}'},                     # query on a POST
               {'method': 'POST', 'url': gw.LEGIFRANCE + 'search', 'body': '[1]'},                        # body not a JSON object
               {'method': 'POST', 'url': gw.LEGIFRANCE + 'search', 'body': 'nope'},
               {'method': 'GET', 'url': CFG['oauth'], 'body': None}]
        for q in bad:
            self.assertTrue(self.raw(q)['error'].startswith('refused:'), q)
        self.assertTrue(self.raw(b'{"method": "POST", "url": "' + gw.LEGIFRANCE.encode() + b'search", "body": "' + b'x' * CFG['max_request_bytes'] + b'"}\n')['error'].startswith('refused:'))
        self.assertTrue(self.raw(b'not json\n')['error'].startswith('refused:'))
        self.assertEqual(self.stub.calls, [])                                                            # nothing sent upstream

    def test_401_one_fresh_token_then_key_invalid(self):
        self.up['api'] = lambda m, u, h, b: (401, {})
        r = gw.search_judilibre('x', 5, gw.Barrier('2020-01-01'))
        self.assertEqual((r[0]['status'], r[0]['reason']), ('skipped', 'key_invalid'))
        self.assertEqual([c['url'] == CFG['oauth'] for c in self.stub.calls], [True, False, True, False])
        self.assertEqual(sc.invalid_keys(self.state), set(gw.PISTE_KEYS))
        n = len(self.stub.calls); gw.search_judilibre('y', 5, gw.Barrier('2020-01-01')); self.assertEqual(len(self.stub.calls), n)   # 0 request after

    def test_broker_verdicts(self):
        self.up['pair'] = (None, None)
        r = gw.search_judilibre('x', 5, gw.Barrier('2020-01-01')); self.assertEqual(r[0]['reason'], 'not_configured')
        self.up['pair'] = (CID, CSEC); self.up['oauth'] = (401, {'error': 'invalid_client'})
        r = gw.search_legifrance('x', 5, gw.Barrier('2020-01-01')); self.assertEqual(r[0]['reason'], 'key_invalid')
        os.unlink(self.state / sc.INVALID_FILE); self.up['oauth'] = (200, {'access_token': TOK, 'expires_in': 3600})
        self.up['api'] = lambda m, u, h, b: (429, {})
        with self.assertRaisesRegex(gw.ProviderError, 'rate_limited'): gw.piste_json(gw.JUDILIBRE + 'search?query=z')
        self.up['api'] = lambda m, u, h, b: (403, {})
        r = gw.search_judilibre('w', 5, gw.Barrier('2020-01-01')); self.assertEqual(r[0]['reason'], 'not_subscribed')
        self.no_leak(r)

    def test_unreachable_and_other_uid(self):
        os.environ[gw.BROKER['env']] = self.sock + '.absent'
        with self.assertRaisesRegex(gw.ProviderError, 'broker'): gw.piste_json(gw.JUDILIBRE + 'search?query=a')
        self.srv.shutdown(); self.srv.server_close()
        self.start(dict(CFG, intervals={}), [os.getuid() + 1])
        os.environ[gw.BROKER['env']] = self.sock
        with self.assertRaisesRegex(gw.ProviderError, 'broker'): gw.piste_json(gw.JUDILIBRE + 'search?query=b')
        self.assertEqual(self.stub.calls, [])
        self.assertFalse((self.state / gw.PISTE_TOKEN).exists())

    def test_pair_never_read_with_broker(self):
        os.environ['PISTE_CLIENT_ID'] = 'OTHER-ID-0000'; os.environ['PISTE_CLIENT_SECRET'] = 'OTHER-SECRET-0000'
        gw.search_judilibre('x', 5, gw.Barrier('2020-01-01'))
        self.assertEqual(self.direct.calls, []); self.assertFalse((self.state / gw.PISTE_TOKEN).exists())
        self.assertNotIn('OTHER-ID-0000', json.dumps(self.stub.calls))                                  # the broker used its own pair

    def test_routes_match_piste_endpoints(self):
        want = {('GET', gw.JUDILIBRE + 'search'), ('GET', gw.JUDILIBRE + 'decision')} | \
               {('POST', gw.LEGIFRANCE + p) for p in ('search', 'consult/getArticle', 'consult/legiPart', 'consult/jorf')}
        self.assertEqual(CFG['route_set'], want); self.assertEqual(CFG['oauth'], gw.PISTE_OAUTH)
        self.assertTrue(all(urllib.parse.urlsplit(u).hostname == gw.PISTE_HOST['bearer'] for _, u in want))


if __name__ == '__main__':
    unittest.main()
