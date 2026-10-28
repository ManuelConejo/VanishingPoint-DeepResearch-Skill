#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Contract of every registered source (tools/sources/, CONTRIBUTING.md), offline (transport stubbed, temporary HOME and state):
declaration complete and valid, names / engines / commands / prefixes unique, plugin `access:` consistent with the declaration, key
hosts declared, every readable prefix routed by gateway.read, the template valid, a source whose key is missing makes 0 request to the
key's hosts (and a `skipped` engine 0 request at all, with a skipped receipt), a fake key never appears in an answer, the journal, the
receipts or the state, and is sent only to the declared hosts in the declared way. User sources: opt-in, announced, duplicates refused."""
import importlib, json, os, pathlib, re, subprocess, sys, tempfile, time, types, unittest, urllib.parse, urllib.request
P = pathlib.Path(__file__).resolve().parent
TOOLS = P.parent / 'tools'
sys.path.insert(0, str(TOOLS)); import gateway as gw, code_sources as sc, sources as reg   # noqa: E702

KEY_VARS = sorted({v for _, k in reg.key_specs() for v in k['vars']})
FAKE = {v: 'VpFake' + v.title().replace('_', '') + '9f3c2a7b' for v in KEY_VARS}   # printable, >= 8 characters, unique per variable


def plugin_access():
    """{name: access} of every plugin's ```sources block (`access:` line)."""
    out = {}
    for f in sorted((P.parent / 'plugins').glob('*.md')):
        m = re.search(r'```sources[^\n]*\n(.*?)```', f.read_text(encoding='utf-8'), re.S)
        for line in (m.group(1).splitlines() if m else []):
            line = line.split('#', 1)[0].strip()
            if line.lower().startswith('access:'):
                for e in line.split(':', 1)[1].split(','):
                    if '=' in e: k, v = e.split('=', 1); out.setdefault(f.stem, {})[k.strip().lower()] = v.strip()
    return out


class Answer:
    def __init__(self, status, body): self.status, self.body = status, body
    def read(self, n=-1): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False


class Transport:
    """Every outgoing request (fetch -> urllib.request.urlopen, PISTE opener, CodeClient._send) recorded and answered offline."""
    def __init__(self): self.calls = []

    def answer(self, url):
        host = urllib.parse.urlsplit(url).hostname
        if host == 'oauth.piste.gouv.fr': return 200, json.dumps({'access_token': 'TokPiste12345678', 'expires_in': 3600}).encode()
        return 200, b'{}'

    def record(self, url, headers, body):
        self.calls.append({'url': url, 'host': urllib.parse.urlsplit(url).hostname, 'headers': dict(headers or {}), 'body': body or b''})

    def urlopen(self, req, timeout=None):
        url = req.full_url if hasattr(req, 'full_url') else req
        self.record(url, getattr(req, 'headers', {}), getattr(req, 'data', None))
        st, b = self.answer(url)
        return Answer(st, b)

    def send(self, client, url, headers, body=None):
        self.record(url, headers, body); return self.answer(url)


class Contract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.home = pathlib.Path(self.tmp.name)
        self.env = dict(os.environ)
        for v in KEY_VARS + ['VP_USER_SOURCES']: os.environ.pop(v, None)
        os.environ['HOME'] = self.tmp.name
        self.saved = (gw.STATE, gw.fetch, gw._PISTE_OPENER, urllib.request.urlopen, sc.CodeClient._send, time.sleep, sc.TOKEN_PATH, sc.FALLBACK_DIRS)
        sc.TOKEN_PATH = None; sc.FALLBACK_DIRS = ()
        self.t = Transport(); t = self.t
        urllib.request.urlopen = t.urlopen
        gw._PISTE_OPENER = types.SimpleNamespace(open=lambda req, timeout=None: t.urlopen(req, timeout))
        sc.CodeClient._send = lambda client, url, headers, body=None: t.send(client, url, headers, body)
        time.sleep = lambda s: None

    def tearDown(self):
        gw.STATE, gw.fetch, gw._PISTE_OPENER, urllib.request.urlopen, sc.CodeClient._send, time.sleep, sc.TOKEN_PATH, sc.FALLBACK_DIRS = self.saved
        os.environ.clear(); os.environ.update(self.env)
        self.tmp.cleanup()

    # ---------------------------------------------------------------- declarations
    def test_declarations_complete(self):
        self.assertTrue(reg.SOURCES and reg.DEFAULT and reg.DEFAULT['name'] == 'doi')
        for s in reg.SOURCES:
            with self.subTest(source=s['name']):
                self.assertTrue(pathlib.Path(s['_file']).resolve().is_relative_to(TOOLS / 'sources'))
                if not s['wired']:
                    self.assertFalse(s['engines'] or s['commands'] or any(i['read'] for i in s['ids'])); self.assertTrue(s['key']); continue
                self.assertIn(s['access'], ('api', 'page', 'browser'))
                for h, v in s['hosts'].items():
                    self.assertRegex(h, r'^[a-z0-9.-]+\.[a-z]+$')
                    self.assertTrue(set(v) <= {'interval', 'stop', 'timeout'}, v)
                    if s['access'] == 'page' and 'interval' in v: self.assertGreaterEqual(v['interval'], 2.0)   # ACCESS-POLICY level 2
                for e, v in s['engines'].items():
                    self.assertRegex(e, r'^[a-z0-9][a-z0-9.-]*$')
                    self.assertTrue(set(v['options']) <= {'court', 'chamber', 'date_from', 'date_to', 'fund', 'language', 'repo'}, v['options'])
                for i in s['ids']:
                    if i['form']: re.compile(i['form'])
                    if i['law_form']: re.compile(i['law_form'])
                    self.assertTrue(i['export'] is None or callable(i['export']) or i['export'] in reg.EXPORT_TYPES)
                for op in reg.CHAIN:
                    self.assertTrue(op not in s or callable(s[op]) or (isinstance(s[op], str) and s[op]))

    def test_unique_and_registry_tables(self):
        names = [s['name'] for s in reg.SOURCES]; self.assertEqual(len(names), len(set(names)))
        prefixes = [i['prefix'] for i in reg.IDS]; self.assertEqual(len(prefixes), len(set(prefixes)))
        self.assertEqual(gw.ENGINES, reg.ENGINES); self.assertEqual(gw.CODE_ENGINES, reg.CODE_ENGINES)
        for s in reg.SOURCES:                                                  # every host setting reached fetch's tables
            for h, v in s['hosts'].items():
                if 'interval' in v: self.assertEqual(gw.INTERVAL[h], v['interval'])
                if 'stop' in v: self.assertEqual(gw.STOP[h], tuple(v['stop']))

    def test_duplicates_refused(self):
        def mod(**src): return types.SimpleNamespace(SOURCE=dict({'wired': False}, **src), __file__='stub.py', __name__='stub')
        k = {'vars': ('X_KEY',), 'send': 'bearer', 'hosts': ('h.example.org',), 'url': 'u', 'free': 'f', 'reason': 'r', 'without': 'degraded'}
        reg.build([mod(name='a', key=k), mod(name='b', key=k)])               # two unwired declarations are fine
        with self.assertRaisesRegex(reg.RegistryError, 'duplicate source name'): reg.build([mod(name='a', key=k), mod(name='a', key=k)])
        f = lambda *a: None
        live = dict(wired=True, access='api', hosts={'h.example.org': {}}, terms='t', barrier='b', read=f)
        with self.assertRaisesRegex(reg.RegistryError, 'duplicate identifier prefix'):
            reg.build([mod(name='a', ids=[{'prefix': 'pmid'}], **live), mod(name='b', ids=[{'prefix': 'pmid'}], **live)])
        with self.assertRaisesRegex(reg.RegistryError, 'duplicate engine'):
            reg.build([mod(name='a', engines={'x': f}, **live), mod(name='b', engines={'x': f}, **live)])
        with self.assertRaisesRegex(reg.RegistryError, 'access must be'): reg.build([mod(name='a', engines={'y': f}, **dict(live, access='scrape'))])
        with self.assertRaisesRegex(reg.RegistryError, 'key.hosts'): reg.build([mod(name='a', key=dict(k, hosts=()))])
        with self.assertRaisesRegex(reg.RegistryError, 'key.send'): reg.build([mod(name='a', key=dict(k, send='url'))])

    def test_template_is_a_valid_declaration(self):
        t = importlib.import_module('sources._TEMPLATE')
        r = reg.build([t]); self.assertEqual([s['name'] for s in r['sources']], ['example'])
        self.assertNotIn('example', gw.ENGINES)                                # a template is never registered

    def test_plugin_access_matches_declaration(self):
        declared = {}
        for s in reg.SOURCES:
            if not s['wired']: continue
            for e in list(s['engines']) + [v['engine'] for v in s['commands'].values()] + list(s['serves']): declared[e] = s['access']
        seen = 0
        for plugin, acc in plugin_access().items():
            for name, a in acc.items():
                if name in declared: seen += 1; self.assertEqual(a, declared[name], f'{plugin}: {name}={a}, declared {declared[name]}')
        self.assertGreater(seen, 20)

    def test_key_specs(self):
        for s, k in reg.key_specs():
            with self.subTest(source=s['name']):
                self.assertTrue(k['hosts']); self.assertTrue(all(re.fullmatch(r'[a-z0-9.-]+\.[a-z]+', h) for h in k['hosts']))
                if s['wired']: self.assertTrue(set(k['hosts']) <= set(s['hosts']), (k['hosts'], list(s['hosts'])))
                self.assertTrue(k['url'] and k['free'] and k['reason'])
                if k['send'].startswith('query:'): self.assertTrue(s['wired'] is False or k.get('rejected') is None or k['send'] == 'query:api_key')
                if s['commands']:                                               # code client: one credential, one host (code_sources.CRED_HOST)
                    self.assertEqual(sc.CRED_HOST[k['vars'][0]], k['hosts'][0])

    def test_code_hosts_in_the_closed_list(self):
        for s in reg.SOURCES:                                                  # code engines go through CodeClient: closed host list
            if s['commands']: self.assertTrue(set(s['hosts']) <= sc.HOSTS | sc.USAGE_HOSTS, (s['name'], list(s['hosts'])))

    def test_every_readable_prefix_is_routed(self):
        for s in reg.SOURCES:
            for i in s['ids']:
                with self.subTest(prefix=i['prefix']):
                    o = reg.owner(i['prefix'] + ':X1')
                    self.assertIs(o, s if i['read'] else reg.DEFAULT)
        self.assertEqual(reg.owner('12345')['name'], 'pubmed'); self.assertEqual(reg.owner('doi:10.1101/2020.03.22.002386')['name'], 'biorxiv')
        self.assertEqual(reg.owner('W2741809807')['name'], 'doi'); self.assertEqual(reg.owner(' ECLI:EU:C:2014:317 ')['name'], 'ecli')

    def test_compatibility_names(self):
        self.assertIs(gw.search_pubmed, importlib.import_module('sources.pubmed').search_pubmed)
        self.assertIs(gw.read_legi, importlib.import_module('sources.piste').read_legi)
        f0 = gw.fetch; gw.fetch = lambda u, headers=None: b'{}'
        try:
            for m in reg.MODULES:
                if 'fetch' in vars(m): self.assertIs(m.fetch, gw.fetch, m.__name__)
        finally: gw.fetch = f0
        self.assertIs(importlib.import_module('sources.arxiv').fetch, f0)

    # ---------------------------------------------------------------- keys at run time (stubbed transport)
    def _plugin(self, engines):
        f = self.home / 'p.md'; f.write_text('```sources\nengines: ' + ', '.join(engines) + '\n```\n', encoding='utf-8'); return f

    def _run_all(self, s, g):
        out = []
        for e in s['engines']: out.append(g.search(e, 'test', n=2))
        for c, v in s['commands'].items(): out.append(g.call(c, v.get('example') or 'test', 2))
        return out

    def test_missing_key_skipped_or_sent_nowhere(self):
        for s, k in reg.key_specs():
            if not s['wired']: continue
            with self.subTest(source=s['name']):
                self.t.calls.clear()
                g = gw.Gateway([str(self._plugin(list(s['engines']) + [v['engine'] for v in s['commands'].values()]))], T='2026-10-26',
                               state=str(self.home / ('st-' + s['name'])), run='c')
                outs = self._run_all(s, g)
                to_key_hosts = [c for c in self.t.calls if c['host'] in k['hosts']]
                if k['without'] == 'skipped': self.assertEqual(to_key_hosts, [], 'a request reached a key host without the key')
                for c in to_key_hosts:                                          # degraded: the key host is called, without any credential
                    self.assertNotIn('api_key=', c['url']); self.assertFalse({h.lower() for h in c['headers']} & {'authorization', 'x-api-key'})
                if k['without'] == 'skipped' and s['engines']:                  # a skipped engine: 0 request at all, a skipped receipt
                    self.assertEqual(self.t.calls, [])
                    for o in outs: self.assertEqual(o['results'].get('status'), 'skipped', o)

    def test_fake_key_never_leaks_and_goes_only_to_its_hosts(self):
        for s, k in reg.key_specs():
            if not s['wired']: continue
            with self.subTest(source=s['name']):
                for v in k['vars']: os.environ[v] = FAKE[v]
                self.t.calls.clear(); st = self.home / ('fk-' + s['name'])
                g = gw.Gateway([str(self._plugin(list(s['engines']) + [v['engine'] for v in s['commands'].values()]))], T='2026-10-26', state=str(st), run='c')
                outs = self._run_all(s, g)
                self.assertTrue(self.t.calls, 'no request made with the key')
                lits = [FAKE[v] for v in k['vars']]
                for c in self.t.calls:
                    blob = c['url'] + json.dumps(c['headers']) + c['body'].decode('latin-1')
                    if any(x in blob for x in lits):
                        self.assertIn(c['host'], k['hosts'], 'key sent to an undeclared host')
                        if k['send'].startswith('query:'):
                            q = urllib.parse.parse_qs(urllib.parse.urlsplit(c['url']).query)
                            self.assertTrue(any(x in q.get(k['send'][6:], []) for x in lits), 'key outside its declared query parameter')
                        else: self.assertFalse(any(x in c['url'] for x in lits), 'key in a URL')
                text = json.dumps(outs) + ''.join(f.read_bytes().decode('latin-1') for f in st.rglob('*') if f.is_file())
                for x in lits: self.assertNotIn(x, text, 'key literal in an answer, the journal, the receipts or the state')
                for v in k['vars']: os.environ.pop(v, None)

    # ---------------------------------------------------------------- user sources (opt-in, subprocess: the registry loads at import)
    def _user(self, body, flag):
        d = self.home / '.config' / 'vp' / 'sources'; d.mkdir(parents=True, exist_ok=True); (d / 'mine.py').write_text(body, encoding='utf-8')
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(self.home), **({'VP_USER_SOURCES': '1'} if flag else {})}
        return subprocess.run([sys.executable, '-I', str(TOOLS / 'gateway.py'), '--state', str(self.home / 'st-user'), 'sources'],
                              capture_output=True, text=True, env=env, cwd=str(self.home), timeout=120)

    USER = ("from sources._common import jget\n"
            "def search_mine(q, n, B): return [], 0\n"
            "SOURCE = {'name': 'mine', 'engines': {'mine': search_mine}, 'access': 'api', 'hosts': {'api.mine.example.org': {'interval': 1.0}},\n"
            "          'terms': 'test', 'barrier': 'test'}\n")

    def test_user_sources_opt_in_and_announced(self):
        r = self._user(self.USER, flag=False)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertNotIn('mine', json.loads(r.stdout)['engines'])
        self.assertIn('not loaded (set VP_USER_SOURCES=1', r.stderr)
        r = self._user(self.USER, flag=True)
        self.assertEqual(r.returncode, 0, r.stderr); out = json.loads(r.stdout)
        self.assertIn('mine', out['engines']); self.assertEqual(out['user_sources'], ['mine'])
        self.assertIn('user sources loaded from', r.stderr); self.assertIn('mine', r.stderr)
        r = self._user(self.USER.replace("'name': 'mine', 'engines': {'mine'", "'name': 'mine', 'engines': {'pubmed'"), flag=True)
        self.assertNotEqual(r.returncode, 0); self.assertIn("duplicate engine 'pubmed'", r.stderr)


if __name__ == '__main__':
    unittest.main()
