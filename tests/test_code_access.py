#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests of the code ACCESS defects found by the code bench of 2026-10-31 (skill-vp/chantier-code/banc-code-31-10/RESULTATS.md,
defects a1-a5), each red on the code before the fix:
  1. github-repo served with plugins/code.md (source `github`): repo-head resolves a named repository to the last commit of its default
     branch before T (same gate as every commit: default branch history, repository created before T); repo-info gives SPDX licence,
     archived and the last commit before T with the licence at it; repo-tree lists the paths at a commit; the gateway help documents them.
  2. search-code: repo:, lang:, file:/path: typed inside the pattern are filters of the provider, not words of the literal pattern.
  3. Sourcegraph keyless: a 429 is retried after bounded waits then stopped for the run (no burst), a Cloudflare challenge is never retried;
     both typed in the answer; GitHub code search without a token is said unusable.
  4. OSV: the barrier is `published`; an advisory published before T and modified after T is served whole, marked.
  5. check_code_refs: lines written in prose ("lines 206-207 and 271-302", "L12 in <ref>") are checked when unambiguous.
Transport replaced (CodeClient._send); no network. Run: python3 -I tests/test_code_access.py   (unittest; pytest-compatible)."""
import io, json, os, pathlib, sys, tempfile, unittest, urllib.error, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import code_sources as sc        # noqa: E402
import gateway as gw             # noqa: E402
import check_code_refs as CR     # noqa: E402

T = '2026-10-31'
NEW = 'a' * 40                                   # newest commit listed: committer date on T (after the barrier)
OLD = '1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e'  # last commit before T
STOP = 'def stop_before_delay(retry_state):\n    return True\n'
CODE_PLUGIN = P.parent / 'plugins' / 'code.md'


class GitHub:
    """GitHub API and raw host for o/lib (default branch main); records the URLs."""
    def __init__(self, compare='behind', created='2015-01-01T00:00:00Z'):
        self.urls, self.compare, self.created = [], compare, created

    def __call__(self, url, headers, body=None):
        self.urls.append(url)
        api, raw = sc.GH['api'] + 'repos/o/lib', sc.GH['raw'] + 'o/lib/'
        u = urllib.parse.urlsplit(url); q = dict(urllib.parse.parse_qsl(u.query))
        if url == api:
            return 200, json.dumps({'full_name': 'o/lib', 'default_branch': 'main', 'license': {'spdx_id': 'MIT'}, 'created_at': self.created,
                                    'pushed_at': '2026-10-30T23:00:00Z', 'archived': True, 'fork': False}).encode()
        if url == api + '/license': return 200, json.dumps({'path': 'LICENSE', 'license': {'spdx_id': 'MIT'}}).encode()
        if url == api + '/license?ref=' + OLD: return 200, json.dumps({'path': 'LICENSE', 'license': {'spdx_id': 'Apache-2.0'}}).encode()
        if u.path.endswith('/repos/o/lib/commits') and q == {'sha': 'main', 'until': T + 'T00:00:00Z', 'per_page': str(sc.GH['head_candidates'])}:
            return 200, json.dumps([{'sha': NEW, 'commit': {'committer': {'date': T + 'T02:00:00Z'}, 'author': {'date': '2026-10-30T20:00:00Z'}}},
                                    {'sha': OLD, 'commit': {'committer': {'date': '2024-05-01T10:00:00Z'}}}]).encode()
        if url == api + '/commits/' + OLD:
            return 200, json.dumps({'sha': OLD, 'commit': {'committer': {'date': '2024-05-01T10:00:00Z'}, 'author': {'date': '2024-05-01T10:00:00Z'}}}).encode()
        if url.startswith(api + '/compare/main...' + OLD): return 200, json.dumps({'status': self.compare}).encode()
        if url == api + '/git/trees/' + OLD + '?recursive=1':
            return 200, json.dumps({'truncated': False, 'tree': [{'path': 'tenacity', 'type': 'tree'}, {'path': 'tenacity/stop.py', 'type': 'blob'},
                                                                  {'path': 'tenacity/__init__.py', 'type': 'blob'}, {'path': 'README.rst', 'type': 'blob'},
                                                                  {'path': '../evil', 'type': 'blob'}]}).encode()
        if url == raw + OLD + '/tenacity/stop.py': return 200, STOP.encode()
        if u.hostname == urllib.parse.urlsplit(sc.RM['deps_dev_projects']).hostname:
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO(b''))
        raise AssertionError('unexpected URL ' + url)


SSE_HIT = ('event: matches\ndata: ' + json.dumps([{'type': 'content', 'repository': 'github.com/urllib3/urllib3', 'path': 'src/urllib3/util/retry.py',
           'commit': OLD, 'lineMatches': [{'lineNumber': 9, 'line': 'def parse_retry_after(self, retry_after):'}]}]) + '\n\nevent: done\ndata: {}\n\n')


class Sourcegraph:
    """sourcegraph.com: answers in turn from `plan` (200 = a hit, 429 = rate limit, 'challenge' = Cloudflare challenge); records the queries."""
    def __init__(self, plan, retry_after=None):
        self.plan, self.queries, self.retry_after = list(plan), [], retry_after

    def __call__(self, url, headers, body=None):
        u = urllib.parse.urlsplit(url)
        if u.hostname != 'sourcegraph.com': raise AssertionError('unexpected URL ' + url)
        self.queries.append(dict(urllib.parse.parse_qsl(u.query))['q'])
        x = self.plan.pop(0) if self.plan else 429
        if x == 200: return 200, SSE_HIT.encode()
        hd = {'cf-mitigated': 'challenge'} if x == 'challenge' else ({'Retry-After': str(self.retry_after)} if self.retry_after else {})
        raise urllib.error.HTTPError(url, 429, 'Too Many Requests', hd, io.BytesIO(b'<!DOCTYPE html><title>Just a moment...</title>'))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.env = dict(os.environ); os.environ['HOME'] = str(self.d)
        for k in ('VP_GITHUB_TOKEN', 'VP_OFFLINE', 'SWH_TOKEN'): os.environ.pop(k, None)
        self.send0, self.sleep0 = sc.CodeClient._send, None
        self.slept = []

    def tearDown(self):
        sc.CodeClient._send = self.send0
        os.environ.clear(); os.environ.update(self.env); self.tmp.cleanup()

    def gateway(self, transport, T=T, run='r', state='st'):
        sc.CodeClient._send = lambda client, url, headers, body=None: transport(url, headers, body)
        g = gw.Gateway([str(CODE_PLUGIN)], T=T, run=run, state=self.d / state)
        g.client.sleep = self.slept.append
        return g


class GithubRepoServed(Base):
    def test_code_plugin_serves_the_github_repo_commands(self):
        s = gw.Gateway([str(CODE_PLUGIN)], T=T, run='r', state=self.d / 'st').sources()
        self.assertIn('github-repo', s['code_engines'])
        for c in ('repo-head', 'repo-info', 'repo-tree', 'repo-file'): self.assertIn(c, s['commands'])

    def test_repo_head_resolves_the_last_commit_of_the_default_branch_before_T(self):
        t = GitHub(); g = self.gateway(t)
        for arg in ('o/lib', 'repo:o/lib', sc.GH['web'] + 'o/lib'):
            r = g.call('repo-head', arg)['results']
            self.assertEqual((r['sha'], r['date'], r['in_default_branch'], r['id']), (OLD, '2024-05-01T10:00:00Z', True, 'repo:o/lib@' + OLD), arg)
            self.assertIn('repo-file o/lib/<path>@' + OLD, r['next'])
        self.assertFalse([u for u in t.urls if '/commits/' + NEW in u], 'the commit dated on T is never resolved')

    def test_repo_head_keeps_the_hardened_gate(self):
        r = self.gateway(GitHub(compare='diverged'), run='a', state='a').call('repo-head', 'o/lib')['results']
        self.assertIn('not in the default branch history', r['refusal'])
        r = self.gateway(GitHub(compare='ahead'), run='b', state='b').call('repo-head', 'o/lib')['results']
        self.assertIn('refusal', r)
        r = self.gateway(GitHub(created=T + 'T00:00:00Z'), run='c', state='c').call('repo-head', 'o/lib')['results']
        self.assertIn('repository created on/after T', r['refusal'])

    def test_repo_info_licence_archived_and_last_commit_before_T(self):
        out = self.gateway(GitHub()).call('repo-info', 'o/lib'); r = out['results']
        self.assertEqual((r['licence_spdx'], r['archived'], r['as_of']), ('MIT', True, 'now'))
        self.assertEqual((r['at_T']['last_commit']['sha'], r['at_T']['last_commit']['date'], r['at_T']['licence']['spdx']), (OLD, '2024-05-01T10:00:00Z', 'Apache-2.0'))
        self.assertIn('archived', out['warning'])

    def test_repo_tree_then_repo_file_at_the_commit(self):
        g = self.gateway(GitHub())
        r = g.call('repo-tree', 'o/lib@' + OLD)['results']
        self.assertEqual((r['paths'], r['count'], r['truncated'], r['sha']), (['tenacity/stop.py', 'tenacity/__init__.py', 'README.rst'], 3, False, OLD))
        self.assertEqual(g.call('repo-tree', 'o/lib/tenacity@' + OLD)['results']['paths'], ['tenacity/stop.py', 'tenacity/__init__.py'])
        self.assertEqual(g.call('repo-file', 'o/lib/tenacity/stop.py@' + OLD)['results']['text'], STOP)
        g2 = self.gateway(GitHub(), T='2024-05-01', run='r2', state='st2')
        self.assertIn('after T', g2.call('repo-tree', 'o/lib@' + OLD)['results']['refusal'])

    def test_gateway_help_documents_the_named_repository_route(self):
        for w in ('repo-head <owner>/<name>', 'repo-tree <owner>/<name>', 'repo-file <owner>/<name>/<path>@<SHA>', 'at_T', 'archived'):
            self.assertIn(w, gw.__doc__)


class SearchCodeFilters(Base):
    def test_split_filters(self):
        self.assertEqual(sc.split_filters('parse_retry_after repo:urllib3/urllib3'), ('parse_retry_after', {'repo': 'urllib3/urllib3'}))
        self.assertEqual(sc.split_filters('Retry-After lang:python repo:^github\\.com/will-ockmore/httpx-retries$ path:src/x.py'),
                         ('Retry-After', {'language': 'python', 'repo': 'will-ockmore/httpx-retries', 'path': 'src/x.py'}))
        self.assertEqual(sc.split_filters('stop_before_delay language:Python r:https://github.com/jd/tenacity'),
                         ('stop_before_delay', {'language': 'Python', 'repo': 'jd/tenacity'}))
        self.assertEqual(sc.split_filters('x=repo:y'), ('x=repo:y', {}), 'only whitespace-delimited tokens')
        for bad, code in (('a repo:o/r repo:o/s', 'filter_conflict'), ('a repo:o/r;rm', 'filter_invalid'), ('a lang:py$(x)', 'filter_invalid')):
            with self.assertRaises(ValueError, msg=bad) as cm: sc.split_filters(bad)
            self.assertEqual(str(cm.exception), code)

    def test_typed_filters_reach_sourcegraph_as_filters(self):
        s = Sourcegraph([200]); g = self.gateway(s)
        out = g.call('search-code', 'parse_retry_after repo:urllib3/urllib3 lang:python file:retry.py')
        q = s.queries[0]
        self.assertIn('content:"parse_retry_after"', q); self.assertNotIn('content:"parse_retry_after repo', q)
        self.assertIn('repo:^github\\.com/urllib3/urllib3$', q); self.assertIn(' lang:python', q); self.assertIn(' file:retry\\.py', q)
        self.assertEqual(out['filters_from_pattern'], {'repo': 'urllib3/urllib3', 'language': 'python', 'path': 'retry.py'})
        self.assertEqual(out['results'][0]['repo'], 'urllib3/urllib3')

    def test_conflicting_or_filter_only_queries_are_refused_without_request(self):
        s = Sourcegraph([200]); g = self.gateway(s)
        self.assertIn('given twice', g.call('search-code', 'x repo:o/a', repo='o/b')['results']['refusal'])
        self.assertIn('empty pattern', g.call('search-code', 'repo:urllib3/urllib3')['results']['refusal'])
        self.assertEqual(s.queries, [])


class SourcegraphLimits(Base):
    def test_429_bounded_backoff_then_answer(self):
        s = Sourcegraph([429, 200]); g = self.gateway(s)
        out = g.call('search-code', 'parse_retry_after')
        self.assertEqual(len(out['results']), 1); self.assertNotIn('sourcegraph', out)
        self.assertEqual(self.slept[0], float(sc.SG_LIMITS['retry_waits_s'][0]))     # then the ordinary host pacing (code_intervals)
        self.assertIn(('sourcegraph.com', float(sc.SG_LIMITS['retry_waits_s'][0])), g.client.waited)

    def test_retry_after_used_when_short(self):
        s = Sourcegraph([429, 200], retry_after=2); g = self.gateway(s)
        g.call('search-code', 'parse_retry_after')
        self.assertTrue(0 < self.slept[0] <= 2.0, self.slept)

    def test_persistent_429_stops_sourcegraph_for_the_run(self):
        s = Sourcegraph([429] * 10); g = self.gateway(s)
        out = g.call('search-code', 'parse_retry_after')
        n = len(sc.SG_LIMITS['retry_waits_s']) + 1
        self.assertEqual(len(s.queries), n, 'one try plus one per bounded wait')
        self.assertEqual((out['results'], out['sourcegraph']['status']), ([], 'rate_limited')); self.assertTrue(out['sourcegraph']['until_utc'])
        self.assertTrue((self.d / 'st' / sc.SG_STOP_FILE).exists())
        g2 = self.gateway(s, run='r', state='st')                        # a later process of the same run: no request at all
        out2 = g2.call('search-code', 'other words')
        self.assertEqual((len(s.queries), out2['sourcegraph']['status']), (n, 'rate_limited'))
        self.assertIn('repo-head', out2['sourcegraph']['advice'])

    def test_cloudflare_challenge_is_not_retried(self):
        s = Sourcegraph(['challenge', 200]); g = self.gateway(s)
        out = g.call('search-code', 'stop_before_delay')
        self.assertEqual((len(s.queries), self.slept, out['sourcegraph']['status']), (1, [], 'blocked'))
        self.assertIn('never circumvented', out['sourcegraph']['reason'])
        g.call('search-code', 'stop_before_delay tenacity'); self.assertEqual(len(s.queries), 1)

    def test_github_code_search_said_unusable_without_token(self):
        out = self.gateway(Sourcegraph([200])).call('search-code', 'x')
        self.assertIn('401', out['github']['note']); self.assertIn('Requires authentication', out['github']['note'])


class OsvPublishedBarrier(unittest.TestCase):
    def test_published_before_T_modified_after_is_served_marked(self):
        B = gw.Barrier('2024-12-01')
        v = {'id': 'GHSA-h5c8-rqwp-cp95', 'aliases': ['CVE-2024-22195'], 'published': '2024-01-11T15:20:48Z', 'modified': '2026-01-01T00:00:00Z',
             'summary': 'Jinja vulnerable to HTML attribute injection', 'details': 'xmlattr filter', 'severity': [{'type': 'CVSS_V3', 'score': 'S'}],
             'affected': [{'package': {'name': 'jinja2', 'ecosystem': 'PyPI'}, 'ranges': [{'events': [{'introduced': '0'}, {'fixed': '3.1.3'}]}]}]}
        x = gw.osv_item(v, B, with_details=True)
        self.assertEqual((x['summary'], x['affected'][0]['events'][1], x['abstract'], x['modified_after_T']),
                         ('Jinja vulnerable to HTML attribute injection', {'fixed': '3.1.3'}, 'xmlattr filter', True))
        self.assertNotIn('2026', json.dumps(x['date_modified']))
        self.assertIsNone(gw.osv_item(dict(v, published='2024-12-01T00:00:00Z'), gw.Barrier('2024-12-01')), 'published on T: refused')


class ProseLines(unittest.TestCase):
    class GH:
        extra = {}
        def rate(self): return None
        def info(self, repo): return {'default_branch': 'main'}
        def resolve(self, repo, sha): return {'sha': OLD, 'date': '2024-05-01T10:00:00Z', 'membership': 'in the default branch history', 'in_default_branch': True}
        def licence(self, repo, ref=None): return {'spdx': 'MIT', 'path': 'LICENSE'}
        def file(self, repo, sha, path): return {'text': ''.join(f'line {i}\n' for i in range(1, 101)), 'permanent_url': 'u'}

    def test_prose_lines_of_a_bibliography_entry_are_checked(self):
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / 'REPORT.md'
            f.write_text('# R\n\n## Bibliography\n'
                         f'9. searxng, code: repo:o/lib/searx/network.py@{OLD}, basis read: whole file read at the SHA; lines 20-27 and 71-99\n'
                         f'10. see lines 3-5 of repo:o/lib/a.py@{OLD} and L12 in repo:o/lib/b.py@{OLD}\n'
                         f'11. code: repo:o/lib/c.py@{OLD}, lines 150-160\n'
                         f'12. repo:o/lib/d.py@{OLD} and repo:o/lib/e.py@{OLD} were both read, lines 1-2 somewhere\n', encoding='utf-8')
            rep = CR.check([f], gh=self.GH())
        by = {r['path']: r for r in rep['refs']}
        self.assertEqual((by['searx/network.py']['ranges'], by['searx/network.py']['checks']['lines']['status']), ([(20, 27), (71, 99)], 'in_bounds'))
        self.assertEqual((by['a.py']['ranges'], by['b.py']['ranges']), ([(3, 5)], [(12, 12)]))
        self.assertEqual((by['c.py']['status'], by['c.py']['checks']['lines']['status']), ('failed', 'out_of_bounds'), 'a prose line beyond the file fails')
        self.assertEqual((by['d.py']['ranges'], by['e.py']['ranges']), ([], []), 'ambiguous: not guessed')
        self.assertEqual((rep['summary']['refs_with_prose_lines'], rep['summary']['prose_lines_unattached']), (4, 1))


class MultiRangeReference(unittest.TestCase):
    def test_path_with_several_ranges_is_one_reference(self):   # rejeu C5: tenacity/__init__.py:418-501,596-665@SHA read as a file "596-665"
        o = CR._segment_refs(f'[2] jd/tenacity, repo:o/lib/tenacity/__init__.py:418-501,596-665@{OLD} (iter)', 'w')
        self.assertEqual([(x['path'], x['ranges']) for x in o], [('tenacity/__init__.py', [(418, 501), (596, 665)])])


if __name__ == '__main__':
    unittest.main()
