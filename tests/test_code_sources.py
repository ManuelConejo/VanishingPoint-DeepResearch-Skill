#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests of code_sources.py and of the code engines of gateway.py (10 cases).
Transport replaced by fixtures_code_sources.json (CodeClient.get or CodeClient._send); no network, VP_OFFLINE honoured.
Plugins are small temporary files written by the tests (no dependency on plugins/).
Run: python3 -I tests/test_code_sources.py   (unittest; pytest-compatible)."""
import email
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
import urllib.response

P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
F = json.loads((P / 'fixtures_code_sources.json').read_text())
FAKE_TOKEN = 'FAKE-TOKEN-NOT-A-SECRET-0123456789'
CODE_PLUGIN = ('# Code\n## Sources\n```sources\nengines: github, sourcegraph, deps.dev, hf-papers, pypi, npm, crates, software-heritage, code, versions, paper-code, provenance\n'
               'cap: 60\nkeys: VP_GITHUB_TOKEN, SWH_TOKEN\naccess: github=api, sourcegraph=api, code=api, versions=api, paper-code=api, provenance=api\n'
               'disabled: grep.app=browser, libraries.io=technical_block\n```\n')
CSAI_PLUGIN = '# CS-AI\n## Sources\n```sources\nengines: openalex, crossref, arxiv, europepmc, dblp\ncap: 60\nkeys: OPENALEX_KEY\n```\n'


def load():
    """The modules under test, or an AssertionError (the suite turns red by assertion, not by ImportError)."""
    assert importlib.util.find_spec('code_sources') is not None, 'tools/code_sources.py is missing'
    import code_sources
    import gateway
    return code_sources, gateway


sc, gw = load()


def fake_get(F, calls=None):
    """Fixture transport keyed on host and path; unknown URL = AssertionError (never a silent empty result)."""
    def get(self, url, token=None):
        u = urllib.parse.urlsplit(url)
        if calls is not None:
            calls.append((u.hostname, token))
        h, p = u.hostname, u.path
        if h == 'sourcegraph.com':
            return F['sourcegraph'].encode()
        if h == 'api.github.com':
            return json.dumps(F['github']).encode()
        if h == 'pypi.org':
            return json.dumps(F['pypi']).encode()
        if h == 'registry.npmjs.org':
            return json.dumps(F['npm'] if p.count('/') == 2 else F['npm_packument']).encode()
        if h == 'crates.io':
            return json.dumps(F['crates_deps'] if p.endswith('/dependencies') else F['crates']).encode()
        if h == 'api.deps.dev':
            return json.dumps(F['depsdev_deps'] if p.endswith(':dependencies') else F['depsdev_version']).encode()
        if h == 'huggingface.co':
            return json.dumps(F['paper'] if '/papers/' in p else F['hf_models'] if '/models' in p else []).encode()
        if h == 'archive.softwareheritage.org':
            return json.dumps(F['visit'] if 'visit/latest' in p else [dict(F['visit'], visit=1)] if p.endswith('/visits/') else F['resolve']).encode()
        raise AssertionError('unexpected URL host ' + str(h))
    return get


class Fake302(urllib.request.BaseHandler):
    """Answers 302 to every https request and counts them: the client must never issue the second one."""
    handler_order = 1

    def __init__(self):
        self.calls = []

    def https_open(self, req):
        self.calls.append(req.full_url)
        r = urllib.response.addinfourl(io.BytesIO(b''), email.message_from_string('Location: https://sourcegraph.com/elsewhere\n'), req.full_url, 302)
        r.msg = 'Found'
        return r


class CodeSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = pathlib.Path(self.tmp.name)
        self.env = {k: os.environ.pop(k) for k in ('VP_GITHUB_TOKEN', 'VP_OFFLINE', 'HOME') if k in os.environ}
        os.environ['HOME'] = str(self.d / 'home')                 # never the real ~/.config/vp in a test
        self.get0, self.token_path0, self.fetch0 = sc.CodeClient.get, sc.TOKEN_PATH, gw.fetch
        sc.TOKEN_PATH = str(self.d / 'absent.token')              # harmless: no token file is ever read
        self.plugin = self.d / 'code-test.md'
        self.plugin.write_text('# T\n## Sources\n```sources\nengines: openalex, code, versions, paper-code, provenance\ncap: 3\n```\n', encoding='utf-8')

    def tearDown(self):
        sc.CodeClient.get, sc.TOKEN_PATH, gw.fetch = self.get0, self.token_path0, self.fetch0
        for k in ('VP_GITHUB_TOKEN', 'VP_OFFLINE', 'HOME'):
            os.environ.pop(k, None)
        os.environ.update(self.env)
        self.tmp.cleanup()

    def client(self, send=None):
        c = sc.CodeClient(cache_dir=self.d / 'state')
        c.sleep = lambda s: None                               # recorded in c.waited, never slept in tests
        c._send = send or (lambda url, headers: (_ for _ in ()).throw(AssertionError('network attempted: ' + url)))
        return c

    def gateway(self, T='2026-10-26', plugins=None, run='t'):
        return gw.Gateway([self.plugin] if plugins is None else plugins, T=T, run=run, state=self.d / 'state')

    def test_client_refuses_undeclared_host_and_http_before_network(self):
        c = self.client()
        for url in ('http://api.github.com/x', 'https://evil.example/x', 'https://api.github.com:8443/x', 'https://u:p@api.github.com/x',
                    'https://127.0.0.1/', 'https://api.github.com.evil.example/x'):
            with self.assertRaises(ValueError, msg=url) as cm:
                c.get(url)
            self.assertEqual(str(cm.exception), 'host_not_declared', url)
        self.assertEqual(c.receipts, [])
        self.assertFalse((self.d / 'state' / 'requests.jsonl').exists())
        os.environ['VP_OFFLINE'] = '1'
        with self.assertRaises(RuntimeError) as cm:
            self.client().get('https://pypi.org/pypi/p/1.2/json')
        self.assertEqual(str(cm.exception), 'offline')
        self.assertEqual(sc.HOSTS, {'api.github.com', 'sourcegraph.com', 'api.deps.dev', 'pypi.org', 'registry.npmjs.org', 'crates.io',
                                    'huggingface.co', 'archive.softwareheritage.org', 'api.osv.dev'})

    def test_client_refuses_redirects(self):
        c = sc.CodeClient(cache_dir=self.d / 'state')
        c.sleep = lambda s: None
        fake = Fake302()
        c.opener.add_handler(fake)
        with self.assertRaises(ValueError) as cm:
            c.get('https://sourcegraph.com/.api/search/stream?q=x')
        self.assertEqual(str(cm.exception), 'redirect_refused')
        self.assertEqual(len(fake.calls), 1, 'no second request after a redirect')
        self.assertEqual(c.receipts[-1]['failure'], 'redirect_refused')
        self.assertNotIn('url', c.receipts[-1])

    def test_client_enforces_github_interval_from_config(self):
        cfg = json.loads((P.parent / 'tools' / 'config.json').read_text())['code_intervals']
        c = self.client(send=lambda url, headers: (200, b'{}'))
        c.clock = lambda: 0.0
        for q in ('x', 'y'):                                    # two distinct URLs: an identical one is served from the cache
            c.get('https://api.github.com/search/code?q=' + q)
        self.assertEqual(c.waited[-1][0], 'api.github.com')
        self.assertGreaterEqual(c.waited[-1][1], cfg['api.github.com'])
        self.assertGreaterEqual(cfg['api.github.com'], 6.0, 'GitHub code search: 10 requests per minute')
        for v in ('1.2', '1.3'):
            c.get(f'https://pypi.org/pypi/p/{v}/json')
        self.assertEqual(c.waited[-1][0], 'pypi.org')
        self.assertGreaterEqual(c.waited[-1][1], cfg['default'])
        self.assertTrue((self.d / 'state' / 'rate-code-api.github.com').exists(), 'last call remembered across processes')
        self.assertEqual(sc.CodeClient(interval={'default': 0.5}).interval['api.github.com'], cfg['api.github.com'])

    def test_github_without_token_is_skipped_and_token_never_logged(self):
        seen = []
        c = self.client(send=lambda url, headers: (seen.append((url, headers)) or (200, json.dumps(F['github']).encode())))
        cs = sc.CodeSearch(c)
        self.assertEqual(cs.search('alpha', 'github'), {'status': 'skipped', 'reason': 'credential_missing'})
        self.assertEqual(seen, [], 'no request without a token')
        key_file = self.d / 'home' / '.config' / 'vp' / 'vp_github_token.key'   # the only file fallback: ~/.config/vp/<name lowercase>.key
        key_file.parent.mkdir(parents=True)
        key_file.write_text(FAKE_TOKEN + '\n')
        self.assertEqual(sc.key('VP_GITHUB_TOKEN'), FAKE_TOKEN)
        out = cs.search('alpha', 'github')
        self.assertEqual([x['repo'] for x in out], ['o/r'])
        self.assertIsNone(out[0]['permanent_url'], 'a blob sha is not a revision')
        self.assertEqual(seen[-1][1]['Authorization'], 'Bearer ' + FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, seen[-1][0])
        key_file.unlink()
        self.assertIsNone(sc.read_token())
        self.assertEqual(sc.FALLBACK_DIRS, ())                                    # no other directory is ever searched
        os.environ['VP_GITHUB_TOKEN'] = FAKE_TOKEN
        self.assertEqual(sc.read_token(), FAKE_TOKEN)
        with self.assertRaises(ValueError) as cm:
            c.get('https://pypi.org/pypi/p/1.2/json', token=FAKE_TOKEN)
        self.assertEqual(str(cm.exception), 'credential_host')
        c._send = lambda url, headers: (_ for _ in ()).throw(urllib.error.HTTPError(url, 403, 'Forbidden', {'Authorization': 'x'}, io.BytesIO(b'')))
        with self.assertRaises(ValueError) as cm:
            cs.search('beta', 'github')
        self.assertEqual(str(cm.exception), 'provider_error:HTTP403')
        self.assertNotIn(FAKE_TOKEN, repr(cm.exception) + repr(cm.exception.__cause__) + repr(cm.exception.__context__))
        self.assertNotIn(FAKE_TOKEN, (self.d / 'state' / 'requests.jsonl').read_text())
        self.assertNotIn(FAKE_TOKEN, json.dumps(c.receipts))
        for r in c.receipts:
            self.assertEqual(set(r) - {'failure'}, {'utc', 'host', 'path_sha256', 'status', 'bytes', 'sha256', 'seconds'})
        os.environ['VP_GITHUB_TOKEN'] = 'BAD\nTOKEN-' + FAKE_TOKEN                # review pass 1: never in a header nor a message
        with self.assertRaises(ValueError) as cm:
            cs.search('gamma', 'github')
        self.assertEqual(str(cm.exception), 'credential_invalid')
        self.assertNotIn(FAKE_TOKEN, repr(cm.exception) + json.dumps(c.receipts) + (self.d / 'state' / 'requests.jsonl').read_text())
        del os.environ['VP_GITHUB_TOKEN']
        c._send = lambda url, headers: (_ for _ in ()).throw(ValueError('Invalid header value ' + FAKE_TOKEN))   # urllib-style message
        with self.assertRaises(ValueError) as cm:
            c.get('https://api.github.com/search/code?q=delta', token=FAKE_TOKEN)
        self.assertEqual(str(cm.exception), 'transport_error:ValueError')
        self.assertIsNone(cm.exception.__context__)                                      # review pass 2: nothing in __context__ either
        self.assertIsNone(cm.exception.__cause__)
        self.assertNotIn(FAKE_TOKEN, repr(cm.exception) + json.dumps(c.receipts) + (self.d / 'state' / 'requests.jsonl').read_text())
        c._send = lambda url, headers: (200, b'x' * (sc.MAX_BYTES + 1))                   # review pass 6: receipt even above 5 MB
        with self.assertRaises(ValueError) as cm:
            c.get('https://api.github.com/search/code?q=epsilon')
        self.assertEqual((str(cm.exception), c.receipts[-1]['failure'], c.receipts[-1]['bytes']), ('response_too_large', 'response_too_large', sc.MAX_BYTES + 1))

    def test_grep_provider_is_disabled(self):
        calls = []
        sc.CodeClient.get = fake_get(F, calls)
        cs = sc.CodeSearch(sc.CodeClient())
        with self.assertRaises(ValueError) as cm:
            cs.search('alpha', provider='grep')
        self.assertEqual(str(cm.exception), 'provider_disabled')
        self.assertEqual(calls, [])
        self.assertEqual(cs.search('alpha')[0]['repo'], 'o/r', 'default provider is Sourcegraph')
        self.assertEqual(calls, [('sourcegraph.com', None)])
        urls = []
        sc.CodeClient.get = lambda self, url, token=None: urls.append(url) or F['sourcegraph'].encode()
        cs.search('foo repo:evil/x "q"', language='Python', repo='o/r')          # review pass 3: a filter word inside the pattern stays part of the pattern
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(urls[-1]).query)['q'][0]
        self.assertEqual(q, 'patterntype:literal content:"foo repo:evil/x \\"q\\"" count:10 timeout:10s lang:Python repo:^github\\.com/o/r$')
        self.assertNotIn('grep.app', sc.HOSTS)

    def test_sourcegraph_results_carry_permanent_url_and_absent_dating(self):
        sc.CodeClient.get = fake_get(F)
        r = self.gateway().search('code', 'alpha', repo='o/r')
        self.assertEqual(r['call'], 1)
        self.assertEqual(r['github'], {'status': 'skipped', 'reason': 'credential_missing'})
        self.assertEqual(r['warning'], 'live index: results cannot be dated')
        self.assertEqual(r['excluded_post_T_or_forbidden'], 0)
        x = r['results'][0]
        self.assertEqual((x['repo'], x['path'], x['line'], x['revision'], x['dating']), ('o/r', 'a.py', 12, 'a' * 40, 'absent'))
        self.assertEqual(x['permanent_url'], 'https://github.com/o/r/blob/' + 'a' * 40 + '/a.py#L12')
        self.assertEqual(hashlib.sha256(F['network_a'].encode()).hexdigest(), F['recordings']['network_a']['sha256'])
        os.environ['VP_GITHUB_TOKEN'] = FAKE_TOKEN
        get0 = sc.CodeClient.get
        sc.CodeClient.get = lambda self, url, token=None: (_ for _ in ()).throw(ValueError('rate_limited')) if 'github' in url else get0(self, url, token)
        r = self.gateway(run='t2').search('code', 'alpha')              # a typed GitHub error keeps the Sourcegraph results
        self.assertEqual((r['github'], len(r['results'])), ({'status': 'error', 'reason': 'rate_limited'}, 1))
        self.assertNotIn(FAKE_TOKEN, json.dumps(r) + (self.d / 'state' / 'journal.jsonl').read_text())
        rows = sc.parse_sourcegraph(F['network_a'])                        # real capture
        self.assertTrue(rows)
        self.assertTrue(all(r['line'] > 0 and len(r['revision']) == 40 and r['permanent_url'] for r in rows))
        with self.assertRaises(ValueError):
            sc.CodeSearch(sc.CodeClient()).search('alpha', regex=True, repo='o/r\nrepo:evil')
        with self.assertRaises(ValueError) as cm:
            sc.check_query('(a+)+', regex=True)
        self.assertEqual(str(cm.exception), 'regex_unbounded')

    def test_versions_merges_registry_and_depsdev_dates(self):
        sc.CodeClient.get = fake_get(F)
        r = self.gateway().call('versions', 'pypi:p@1.2')['results']
        self.assertEqual((r['package'], r['version'], r['dependencies']), ('p', '1.2', ['q>=1']))
        self.assertEqual((r['date'], r['date_registry'], r['date_deps_dev']), ('2020-02-02T00:00:00Z', '2020-01-01T00:00:00Z', '2020-02-02T00:00:00Z'))
        self.assertEqual([n['versionKey']['name'] for n in r['graph']], ['p', 'q'])
        self.assertEqual(r['advisories'], [{'id': 'GHSA-xxxx'}])
        self.assertNotIn('dating', r)
        without = dict(F, depsdev_version={k: v for k, v in F['depsdev_version'].items() if k != 'publishedAt'})
        sc.CodeClient.get = fake_get(without)
        self.assertEqual(self.gateway(run='t2').call('versions', 'pypi:p@1.2')['results']['date'], '2020-01-01T00:00:00Z')
        self.assertIn('version_mismatch', self.gateway(run='t3').call('versions', 'pypi:p@2.0')['results']['error'])
        self.assertEqual(self.gateway().call('versions', 'pypi:p'), {'refusal': 'expected form <pypi|npm|cargo>:<package>@<version>'})
        for arg in ('pypi:..@1', 'pypi:p@..', 'pypi:a/../b@1', 'npm:@s/..@1', 'pypi:p@1/2'):                # review pass 4: no traversal
            self.assertIn('expected form', self.gateway().call('versions', arg)['refusal'], arg)
        for pkg, ver in (('..', '1'), ('p', '..'), ('a/../b', '1'), ('p', '1/2')):
            with self.assertRaises(ValueError) as cm:
                sc.Versions(sc.CodeClient()).metadata('pypi', pkg, ver)
            self.assertEqual(str(cm.exception), 'reference', (pkg, ver))
        self.assertEqual(re.fullmatch(gw.VERSION_FORM, 'npm:@scope/name@1.0.0').groups(), ('npm', '@scope/name', '1.0.0'))
        self.assertEqual(sc.check_ref('@scope/name', '1.0.0'), ('%40scope%2Fname', '1.0.0'))
        self.assertFalse((self.d / 'state' / 'journal.jsonl').exists() and 'expected form' in (self.d / 'state' / 'journal.jsonl').read_text())
        v = sc.Versions(sc.CodeClient())
        self.assertEqual(v.metadata('npm', 'p', '1.2')['date'], '2020-01-03T00:00:00.000Z')
        self.assertEqual((v.metadata('cargo', 'p', '1.2')['date'], v.metadata('cargo', 'p', '1.2')['dependencies'][0]['crate_id']), ('2020-01-01', 'q'))
        sc.CodeClient.get = fake_get(dict(F, pypi={'info': F['network_b']['info'], 'urls': F['network_b']['urls']}))
        x = v.metadata('pypi', 'matplotlib', '3.5.0')                     # real PyPI capture (reduced)
        self.assertEqual((x['version'], x['date'], x['dependencies']), ('3.5.0', '2021-11-16T07:14:45.184664Z', None))

    def test_gateway_serves_code_engines_only_when_a_plugin_declares_them(self):
        sc.CodeClient.get = fake_get(F)
        gw.fetch = lambda url: (_ for _ in ()).throw(AssertionError('network'))
        csai = self.d / 'cs-ai-test.md'
        csai.write_text(CSAI_PLUGIN, encoding='utf-8')
        for plugins in ([], [csai]):
            g = self.gateway(plugins=plugins)
            s = g.sources()
            self.assertEqual(s['code_engines'], [])
            self.assertFalse(set(s['commands']) & set(gw.CODE_ENGINES))
            for cmd, arg in (('search-code', 'alpha'), ('versions', 'pypi:p@1.2'), ('paper-code', '2507.19457'), ('provenance', 'https://github.com/o/r')):
                r = g.call(cmd, arg)
                self.assertEqual(list(r), ['refusal'], (plugins, cmd))
                self.assertTrue(r['refusal'].startswith(f"engine '{gw.CODE_ENGINES[cmd]}' not declared by the plugins"), r)
            self.assertFalse((self.d / 'state' / 'journal.jsonl').exists(), 'a refusal is neither counted nor journaled')
        partial = self.d / 'partial.md'
        partial.write_text('## Sources\n```sources\nengines: code, versions\n```\n', encoding='utf-8')
        g = self.gateway(plugins=[partial])
        self.assertEqual(g.sources()['code_engines'], ['code', 'versions'])
        self.assertEqual(g.call('search-code', 'alpha')['call'], 1)
        self.assertIn('refusal', g.call('paper-code', '2507.19457'))
        code_plugin = self.d / 'code-full.md'
        code_plugin.write_text(CODE_PLUGIN, encoding='utf-8')
        full = gw.Gateway([code_plugin], T='2026-10-26', run='r', state=self.d / 'state').sources()
        self.assertEqual(full['code_engines'], ['code', 'paper-code', 'provenance', 'versions'])
        self.assertEqual(full['engines'], [])
        self.assertNotIn('github', full['not_wired']); self.assertEqual(full['served_by'].get('github'), 'code')   # served by the code engine
        self.assertNotIn('GITHUB', full['keys_present'], 'no token in the environment nor in the temporary home')
        self.assertIn('VP_GITHUB_TOKEN', gw.read_plugin(code_plugin)['keys'])

    def test_gateway_counts_and_journals_code_calls_in_the_same_counter(self):
        sc.CodeClient.get = fake_get(F)
        gw.fetch = lambda url: json.dumps({'results': [], 'meta': {'count': 0}}).encode()
        g = self.gateway()
        self.assertEqual(g.call('search-code', 'alpha')['call'], 1)
        self.assertEqual(g.search('openalex', 'x')['call'], 2)
        r = g.call('versions', 'pypi:p@1.2')
        self.assertEqual((r['call'], r['cap'], r['bound'], r['index_total'], r['excluded_post_T_or_forbidden']), (3, 3, 'documents before 2026-10-26', None, 0))
        self.assertIn('CAP', g.call('paper-code', '2507.19457')['refusal'])
        self.assertEqual((self.d / 'state' / 'counter-t.txt').read_text(), '3')
        lines = [json.loads(x) for x in (self.d / 'state' / 'journal.jsonl').read_text().splitlines()]
        self.assertEqual([x['call'] for x in lines], ['search-code', 'search-openalex', 'versions'])
        self.assertEqual([x['engine'] for x in lines], ['code', 'openalex', 'versions'])
        self.assertEqual([x['query'] for x in lines], ['alpha', 'x', 'pypi:p@1.2'])
        self.assertTrue((self.d / 'state' / 'requests.jsonl').exists() is False or FAKE_TOKEN not in (self.d / 'state' / 'requests.jsonl').read_text())

    def test_dated_barrier_removes_results_on_or_after_T_and_keeps_undated_with_warning(self):
        sc.CodeClient.get = fake_get(F)
        r = self.gateway(T='2020-02-02').call('versions', 'pypi:p@1.2')     # deps.dev publishedAt == T
        self.assertEqual((r['results'], r['excluded_post_T_or_forbidden']), ({'refusal': 'after T'}, 1))
        self.assertNotIn('warning', r)
        r = self.gateway(T='2020-02-03', run='t2').call('versions', 'pypi:p@1.2')
        self.assertEqual((r['results']['date'], r['excluded_post_T_or_forbidden']), ('2020-02-02T00:00:00Z', 0))
        self.assertNotIn('warning', r)
        late = dict(F, pypi=json.loads(json.dumps(F['pypi']).replace('2020-01-01', '2020-02-03')))   # review pass 2: registry >= T, deps.dev < T
        sc.CodeClient.get = fake_get(late)
        r = self.gateway(T='2020-02-03', run='t2b').call('versions', 'pypi:p@1.2')
        self.assertEqual((r['results'], r['excluded_post_T_or_forbidden']), ({'refusal': 'after T'}, 1))
        sc.CodeClient.get = fake_get(F)
        r = self.gateway(T='2025-08-01', run='t3').call('paper-code', '2507.19457v2')
        self.assertEqual([m['id'] for m in r['results']['models']], ['o/m-old'])
        self.assertEqual((r['excluded_post_T_or_forbidden'], r['results']['repos'][0]['date'], r['results']['arxiv']), (1, '2025-07-25', '2507.19457'))
        r = self.gateway(T='2025-07-25', run='t4').call('paper-code', '2507.19457')
        self.assertEqual(r['results'], {'refusal': 'after T'})
        r = self.gateway(T='2026-01-01', run='t5').call('provenance', 'https://github.com/o/r')   # the only visit is on T: none before T
        self.assertTrue(r['results']['refusal'].startswith('unavailable before T'), r); self.assertNotIn('warning', r)
        r = self.gateway(T='2026-01-02', run='t6').call('provenance', 'https://github.com/o/r')
        self.assertEqual((r['results']['swhid'], r['results']['date_visited']), ('swh:1:snp:' + 'b' * 40, '2026-01-01'))
        for arg in ('ftp://x/y', 'http://github.com/o/r', 'github.com/o/r', 'swh:2:x', 'swh:1:bad', 'swh:1:rev:' + 'c' * 39,
                    'https://user:pass@/x', 'https://u:p@github.com/o/r', 'https://github.com'):      # review pass 7: https://host/... or a full swhid
            self.assertEqual(self.gateway(run='t6b').call('provenance', arg), {'refusal': 'expected form <origin https://... | swh:1:...>'}, arg)
        for origin in ('ftp://x/y', 'https://user:pass@/x', 'https://u:p@github.com/o/r'):
            with self.assertRaises(ValueError) as cm:
                sc.Provenance(sc.CodeClient()).visit(origin)
            self.assertEqual(str(cm.exception), 'origin', origin)
        self.assertFalse((self.d / 'state' / 'counter-t6b.txt').exists(), 'a refused form is not counted')
        r = self.gateway(T='2026-01-02', run='t7').call('provenance', 'swh:1:rev:' + 'c' * 40)
        self.assertEqual((r['results']['dating'], r['warning']), ('absent', 'live index: results cannot be dated'))
        r = self.gateway(T='2000-01-01', run='t8').search('code', 'alpha')
        self.assertEqual((r['results'][0]['dating'], r['excluded_post_T_or_forbidden'], r['warning']), ('absent', 0, 'live index: results cannot be dated'))


if __name__ == '__main__':
    unittest.main()
