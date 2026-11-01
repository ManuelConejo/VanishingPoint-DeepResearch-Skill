#!/usr/bin/env python3
"""Offline tests of find-implementations (tools/sources/implementations.py, code_sources.Implementations; internal code bench 2026-10-31, case C2:
2 expected repositories of 5 found) and of the backdate signals of the GitHub barrier (code_sources.GitHubRepo.backdate; security review of
2026-10-31, item 2):
  1. served with plugins/code.md (enabled_by sourcegraph / github), refused for a plugin that declares neither;
  2. the most used packages of the ecosystem (ecosyste.ms) are searched by ONE Sourcegraph query restricted to their repositories, then one
     global query; non-implementation paths excluded in the query; ' OR ' alternatives; typed filters; refusals without request;
  3. grouping by repository, vendored copies (pip/_vendor/urllib3 -> urllib3) and same-content copies removed from the distinct list and
     listed apart; ranking: universe first, then stars; each repository cited repo:<owner>/<name>/<path>:<a>-<b>@<SHA40>;
  4. the first implementations.pinned_repos repositories dated through the repo-file barrier; an indexed commit after T replaced by the last
     commit of the default branch before T, lines looked up again in the file at that commit; the others undated;
  5. GitHub code search skipped without token (said), merged with a token; a Sourcegraph challenge is typed, never retried;
  6. backdate: a pull request merged on/after T, a push event on/after T, a parent dated on/after T -> refused; committer date earlier than the
     author date -> served with a warning; a check that fails never blocks.
Transport replaced (CodeClient._send); no network. Run: python3 -I tests/test_implementations.py   (unittest; pytest-compatible)."""
import datetime, io, json, os, pathlib, sys, tempfile, unittest, urllib.error, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import code_sources as sc        # noqa: E402
import gateway as gw             # noqa: E402

T = '2026-10-31'
OLD, OLD2, NEWC, VEND, MIRR, SMALL, PAR = ('1' * 40, '2' * 40, '3' * 40, '4' * 40, '5' * 40, '6' * 40, '7' * 40)
CODE_PLUGIN = P.parent / 'plugins' / 'code.md'
RETRY = ['        retry_after = response.headers.get("Retry-After")', '        if re.match(r"^\\s*[0-9]+\\s*$", retry_after):']
HTTP_AT_OLD2 = 'import time\n\n\ndef wait(resp):\n    ra = resp.headers.get("Retry-After")\n    return float(ra or 0)\n'


def sse(items):
    return ('event: matches\ndata: ' + json.dumps(items) + '\n\nevent: progress\ndata: {"done": true}\n\nevent: done\ndata: {}\n\n').encode()


def content(repo, path, commit, stars, lines):
    return {'type': 'content', 'repository': 'github.com/' + repo, 'path': path, 'commit': commit, 'repoStars': stars,
            'lineMatches': [{'lineNumber': n - 1, 'line': l} for n, l in lines]}


class World:
    """ecosyste.ms, Sourcegraph, GitHub API and raw host. repos: name -> {created, commits {sha: (committer, author, parents)}, head, files,
    pulls {sha: [...]}, events [...]}; records URLs and Sourcegraph queries."""
    def __init__(self, sg='ok', github_items=None):
        self.urls, self.queries, self.sg, self.github_items = [], [], sg, github_items or []
        self.repos = {
            'urllib3/urllib3': {'commits': {OLD: ('2026-10-20T10:00:00Z', '2026-10-20T10:00:00Z', [])},   # lines 10 and 12 hold the literal
                                'files': {(OLD, 'src/urllib3/util/retry.py'): '\n' * 9 + RETRY[0] + '\n\n' + RETRY[1] + '\n'}},
            'big/app': {'commits': {NEWC: (T + 'T05:00:00Z', T + 'T05:00:00Z', []), OLD2: ('2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z', [])},
                        'head': [NEWC, OLD2], 'files': {(OLD2, 'app/http.py'): HTTP_AT_OLD2}},
            'small/lib': {'commits': {SMALL: ('2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z', [])}},
            'gh/only': {'commits': {OLD: ('2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', [])}, 'head': [OLD],
                        'files': {(OLD, 'net/retry.py'): 'x = 1\nh = r.headers["Retry-After"]\n'}}}

    def __call__(self, url, headers, body=None):
        self.urls.append(url)
        u = urllib.parse.urlsplit(url); q = dict(urllib.parse.parse_qsl(u.query))
        if u.hostname == 'packages.ecosyste.ms':
            if q.get('page') != '1': return 200, b'[]'
            return 200, json.dumps([{'name': 'requests', 'repository_url': 'https://github.com/psf/requests'},
                                    {'name': 'urllib3', 'repository_url': 'https://github.com/urllib3/urllib3'},
                                    {'name': 'nogit', 'repository_url': 'https://gitlab.com/x/y'},
                                    {'name': 'pip', 'repository_url': 'https://github.com/pypa/pip.git'}]).encode()
        if u.hostname == 'sourcegraph.com':
            self.queries.append(q['q'])
            if self.sg == 'challenge':
                raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {'cf-mitigated': 'challenge'}, io.BytesIO(b''))
            if 'repo:^github\\.com/(' in q['q']:
                return 200, sse([content('urllib3/urllib3', 'src/urllib3/util/retry.py', OLD, 4000, [(10, RETRY[0]), (12, RETRY[1])]),
                                 content('pypa/pip', 'src/pip/_vendor/urllib3/util/retry.py', VEND, 9000, [(10, RETRY[0]), (12, RETRY[1])]),
                                 content('psf/requests', 'venv/lib/site-packages/pip/_vendor/urllib3/util/retry.py', VEND, 50, [(10, RETRY[0])])])
            return 200, sse([content('big/app', 'app/http.py', NEWC, 50000, [(7, '    ra = resp.headers.get("Retry-After")')]),
                             content('copy/mirror', 'src/urllib3/util/retry.py', MIRR, 20, [(11, RETRY[0]), (13, '  ' + RETRY[1])]),
                             content('small/lib', 'lib/retry.py', SMALL, 10, [(3, 'RETRY_AFTER = "retry-after"')])])
        if url.startswith(sc.GH['api'] + 'search/code'):
            return 200, json.dumps({'items': self.github_items}).encode()
        if url.startswith(sc.GH['api'] + 'repos/'):
            rest = url[len(sc.GH['api'] + 'repos/'):].split('?')[0].split('/')
            name, tail = '/'.join(rest[:2]), rest[2:]
            r = self.repos.get(name)
            if r is None: raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO(b''))
            if not tail: return 200, json.dumps({'full_name': name, 'default_branch': 'main', 'created_at': '2015-01-01T00:00:00Z'}).encode()
            if tail[0] == 'commits' and len(tail) == 1:
                return 200, json.dumps([{'sha': s, 'commit': {'committer': {'date': r['commits'][s][0]}}} for s in r.get('head', [])]).encode()
            if tail[0] == 'commits' and len(tail) == 2 and tail[1] in r['commits']:
                c, a, ps = r['commits'][tail[1]]
                return 200, json.dumps({'sha': tail[1], 'parents': [{'sha': p} for p in ps], 'commit': {'committer': {'date': c}, 'author': {'date': a}}}).encode()
            if tail[0] == 'commits' and len(tail) == 3 and tail[2] == 'pulls': return 200, json.dumps(r.get('pulls', {}).get(tail[1], [])).encode()
            if tail[0] == 'commits': raise urllib.error.HTTPError(url, 422, 'Unprocessable', {}, io.BytesIO(b''))
            if tail[0] == 'compare': return 200, json.dumps({'status': 'behind'}).encode()
            if tail[0] == 'events': return 200, json.dumps(r.get('events', [])).encode()
        if url.startswith(sc.GH['raw']):
            rest = url[len(sc.GH['raw']):].split('/')
            f = self.repos.get('/'.join(rest[:2]), {}).get('files', {}).get((rest[2], '/'.join(rest[3:])))
            if f is not None: return 200, f.encode()
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO(b''))
        raise AssertionError('unexpected URL ' + url)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.env = dict(os.environ); os.environ['HOME'] = str(self.d)
        for k in ('VP_GITHUB_TOKEN', 'VP_OFFLINE', 'SWH_TOKEN'): os.environ.pop(k, None)
        self.send0, self.impl0 = sc.CodeClient._send, dict(sc.IMPL)

    def tearDown(self):
        sc.CodeClient._send = self.send0
        sc.IMPL.clear(); sc.IMPL.update(self.impl0)
        os.environ.clear(); os.environ.update(self.env); self.tmp.cleanup()

    def gateway(self, world, plugin=CODE_PLUGIN, T=T, state='st'):
        sc.CodeClient._send = lambda client, url, headers, body=None: world(url, headers, body)
        g = gw.Gateway([str(plugin)], T=T, run='r', state=self.d / state)
        g.client.sleep = lambda s: None
        return g


class Served(Base):
    def test_served_with_the_code_plugin_only(self):
        self.assertIn('find-implementations', gw.Gateway([str(CODE_PLUGIN)], T=T, run='r', state=self.d / 'a').sources()['commands'])
        other = self.d / 'other.md'
        other.write_text('# Other\n\n## Sources\n\n```sources\nengines: openalex\n```\n')
        g = gw.Gateway([str(other)], T=T, run='r', state=self.d / 'b')
        self.assertNotIn('find-implementations', g.sources()['commands'])
        self.assertIn('not declared', g.call('find-implementations', 'Retry-After')['refusal'])

    def test_gateway_help_documents_the_command(self):
        for w in ('find-implementations', '--ecosystem', 'repo:<owner>/<name>/<path>:<a>-<b>@<SHA40>', 'backdate'):
            self.assertIn(w, gw.__doc__)


class Pipeline(Base):
    def run_c2(self, world=None, **opt):
        w = world or World(); g = self.gateway(w)
        return w, g.call('find-implementations', 'retry-after', 20, language='python', **opt)

    def test_universe_then_global_queries(self):
        w, out = self.run_c2()
        self.assertEqual(len(w.queries), 2)
        uq, glob = w.queries
        self.assertIn('repo:^github\\.com/(psf/requests|urllib3/urllib3|pypa/pip)$', uq)
        self.assertNotIn('repo:', glob)
        for q in (uq, glob):
            self.assertIn('content:"retry-after"', q); self.assertIn(' lang:python', q)
            self.assertIn(' -file:' + sc.IMPL['excluded_paths'], q)
        self.assertEqual(out['implementations']['ecosystem'], 'pypi', 'python -> pypi (implementations.language_ecosystems)')
        u = out['implementations']['providers']['universe']
        self.assertEqual((u['repositories'], u['packages_without_github_repository'], u['as_of']), (3, 1, 'now'))

    def test_grouping_copies_ranking_and_citation(self):
        w, out = self.run_c2()
        r = out['results']
        self.assertEqual([x['repo'] for x in r], ['urllib3/urllib3', 'big/app', 'small/lib'], 'universe first, then stars')
        im = out['implementations']
        cp = {c['repo']: c for c in im['copies_removed']}
        self.assertEqual((cp['pypa/pip']['kind'], cp['pypa/pip']['of'], cp['pypa/pip']['upstream_name']), ('vendored', 'urllib3/urllib3', ['urllib3']))
        self.assertEqual((cp['copy/mirror']['kind'], cp['copy/mirror']['of']), ('same_content', 'urllib3/urllib3'))
        self.assertEqual((cp['psf/requests']['upstream_name'], cp['psf/requests']['of']), (['urllib3'], 'urllib3/urllib3'), 'innermost vendored copy')
        self.assertEqual(sorted(r[0]['copies']), ['copy/mirror', 'psf/requests', 'pypa/pip'])
        self.assertEqual((im['repositories_matching'], im['distinct']), (6, 3))
        self.assertEqual(r[0]['cite'], f'repo:urllib3/urllib3/src/urllib3/util/retry.py:10-10@{OLD}',
                         'lines re-read at the commit: line 12 (retry_after) does not hold the literal the index claimed (Codex review, item 3)')
        self.assertEqual(r[0]['id'], f'repo:urllib3/urllib3/src/urllib3/util/retry.py@{OLD}')
        self.assertEqual((r[0]['popularity']['ecosystem_rank'], r[0]['popularity']['package'], r[0]['popularity']['stars']), (2, 'urllib3', 4000))
        self.assertIn('read the cited file', im['caution'])

    def test_pinning_through_the_barrier(self):
        w, out = self.run_c2()
        r = {x['repo']: x for x in out['results']}
        u = r['urllib3/urllib3']
        self.assertEqual((u['date'], u['dating'], u['backdate_check']['verdict']), ('2026-10-20T10:00:00Z', 'indexed commit dated before T', 'none_detected'))
        b = r['big/app']                                   # indexed commit dated on T: replaced by the last commit before T, lines found again
        self.assertEqual(b['cite'], f'repo:big/app/app/http.py:5-5@{OLD2}')
        self.assertEqual((b['lines'], b['date']), ([5], '2026-09-01T00:00:00Z'))
        self.assertIn('last commit of the default branch before T', b['dating'])
        self.assertFalse([x for x in w.urls if x.startswith(sc.GH['raw'] + 'big/app/' + NEWC)], 'nothing read at the commit after T')

    def test_pinned_bound_then_undated(self):
        sc.IMPL['pinned_repos'] = 1
        w, out = self.run_c2()
        r = out['results']
        self.assertIn('date', r[0]); self.assertNotIn('date', r[1])
        self.assertTrue(r[1]['dating'].startswith('absent'))
        self.assertNotIn('cite', r[1], 'undated: no citation form (Codex review 2026-10-31, item 4)')
        self.assertEqual((r[1]['id'], r[1]['index_commit']), (None, NEWC), 'the live index commit, marked undated')
        self.assertFalse([x for x in w.urls if '/repos/big/app' in x], 'no GitHub request beyond the bound')

    def test_alternatives_and_typed_filters(self):
        w = World(); g = self.gateway(w)
        out = g.call('find-implementations', 'Retry-After OR retry_after lang:python eco:pypi file:retry.py')
        q = w.queries[0]
        self.assertIn('(content:"Retry-After" OR content:"retry_after")', q); self.assertIn(' file:retry\\.py', q)
        self.assertEqual(out['implementations']['alternatives'], ['Retry-After', 'retry_after'])
        n0 = len(w.urls)
        self.assertIn('given twice', g.call('find-implementations', 'x lang:python', language='go')['results']['refusal'])
        self.assertIn('empty pattern', g.call('find-implementations', 'lang:python')['results']['refusal'])
        self.assertIn('too_many_alternatives', g.call('find-implementations', ' OR '.join('abcdefgh'[:int(sc.IMPL['max_alternatives']) + 1]))['results']['refusal'])
        self.assertIn('unknown ecosystem', g.call('find-implementations', 'x eco:nowhere')['results']['refusal'])
        self.assertEqual(len(w.urls), n0, 'refusals make no request')

    def test_without_ecosystem_no_universe(self):
        w = World(); g = self.gateway(w)
        out = g.call('find-implementations', 'retry-after', language='cobol')
        self.assertEqual(len(w.queries), 1); self.assertNotIn('universe', out['implementations']['providers'])
        self.assertFalse([x for x in w.urls if 'ecosyste.ms' in x])
        r = {x['repo']: x for x in out['results']}
        self.assertIn('repository not resolved on GitHub (provider_error:HTTP404)', r['copy/mirror']['refusal'], 'an unknown repository is refused, not a crash')

    def test_github_code_search_skipped_without_token_merged_with_one(self):
        w, out = self.run_c2()
        self.assertEqual(out['implementations']['providers']['github']['reason'], 'credential_missing')
        os.environ['VP_GITHUB_TOKEN'] = 'VpFakeGithubToken9f3c2a7b'
        items = [{'repository': {'full_name': 'gh/only'}, 'path': 'net/retry.py', 'html_url': 'https://github.com/gh/only/blob/x/net/retry.py'},
                 {'repository': {'full_name': 'gh/only'}, 'path': 'tests/test_retry.py', 'html_url': 'u'}]
        w2 = World(github_items=items); g = self.gateway(w2, state='st2')
        out = g.call('find-implementations', 'retry-after', 20, language='python')
        r = {x['repo']: x for x in out['results']}
        self.assertEqual(r['gh/only']['found_by'], ['github'])
        self.assertEqual(r['gh/only']['cite'], f'repo:gh/only/net/retry.py:2-2@{OLD}', 'no commit from GitHub search: last commit before T, line found')
        self.assertEqual(r['gh/only']['files_matching'], 1, 'excluded test path dropped')

    def test_sourcegraph_challenge_is_typed_not_retried(self):
        w, out = self.run_c2(World(sg='challenge'))
        self.assertEqual(len(w.queries), 1, 'the stop holds for the global query too')
        p = out['implementations']['providers']
        self.assertEqual((p['sourcegraph_universe']['status'], p['sourcegraph_global']['status']), ('blocked', 'blocked'))
        self.assertEqual(out['results'], [])


class Backdate(Base):
    def head(self, w, T=T):
        return self.gateway(w, T=T).call('repo-head', 'gh/only')['results']

    def test_pull_request_merged_after_T_is_refused(self):
        w = World(); w.repos['gh/only']['pulls'] = {OLD: [{'merged_at': T + 'T09:00:00Z', 'base': {'ref': 'main'}}]}
        r = self.head(w)
        self.assertIn('entered the default branch on/after T', r['refusal']); self.assertIn('pull request', r['refusal'])

    def test_repo_head_skips_a_candidate_merged_on_T(self):
        w = World(); w.repos['gh/only']['head'] = [OLD, PAR]
        w.repos['gh/only']['commits'][PAR] = ('2025-12-01T00:00:00Z', '2025-12-01T00:00:00Z', [])
        w.repos['gh/only']['pulls'] = {OLD: [{'merged_at': T + 'T00:05:32Z', 'base': {'ref': 'main'}}]}
        r = self.head(w)
        self.assertEqual(r['sha'], PAR, 'the next commit listed before T')

    def test_pull_request_merged_before_T_passes(self):
        w = World(); w.repos['gh/only']['pulls'] = {OLD: [{'merged_at': '2026-01-02T00:00:00Z', 'base': {'ref': 'main'}},
                                                          {'merged_at': T + 'T09:00:00Z', 'base': {'ref': 'release'}}]}
        r = self.head(w)
        self.assertEqual((r['sha'], r['backdate_check']['verdict']), (OLD, 'none_detected'))
        self.assertIn('residual', r['backdate_check'])

    def test_push_event_after_T_is_refused(self):
        w = World(); w.repos['gh/only']['events'] = [{'type': 'PushEvent', 'created_at': T + 'T08:00:00Z', 'payload': {'ref': 'refs/heads/main', 'head': OLD}}]
        self.assertIn('push of the commit', self.head(w)['refusal'])

    def test_events_not_requested_when_T_is_older_than_the_window(self):
        w = World(); old_T = (datetime.date.today() - datetime.timedelta(days=int(sc.GH['events_window_days']) + 5)).isoformat()
        w.repos['gh/only']['commits'][OLD] = ('2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z', [])
        r = self.head(w, T=old_T)
        self.assertIn('not observable', r['backdate_check']['checks']['events'])
        self.assertFalse([u for u in w.urls if u.endswith('/events?per_page=100')])

    def test_parent_dated_after_T_is_refused_and_later_parent_is_suspect(self):
        w = World(); w.repos['gh/only']['commits'][OLD] = ('2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', [PAR])
        w.repos['gh/only']['commits'][PAR] = (T + 'T01:00:00Z', T + 'T01:00:00Z', [])
        self.assertIn('first parent', self.head(w)['refusal'])
        w = World(); w.repos['gh/only']['commits'][OLD] = ('2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', [PAR])
        w.repos['gh/only']['commits'][PAR] = ('2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', [])
        out = self.gateway(w, state='s2').call('repo-head', 'gh/only')
        self.assertEqual(out['results']['backdate_check']['verdict'], 'suspect'); self.assertIn('possibly backdated', out['warning'])

    def test_committer_before_author_is_suspect_and_served(self):
        w = World(); w.repos['gh/only']['commits'][OLD] = ('2026-01-01T00:00:00Z', '2026-06-01T00:00:00Z', [])
        out = self.gateway(w).call('repo-file', 'gh/only/net/retry.py@' + OLD)
        self.assertEqual(out['results']['backdate_check']['signals'][0]['check'], 'dates')
        self.assertIn('possibly backdated', out['warning']); self.assertIn('Retry-After', out['results']['text'])

    def test_a_failing_check_never_blocks(self):
        w = World()
        def broken(url, headers, body=None):
            if '/pulls' in url or '/events' in url: raise urllib.error.HTTPError(url, 500, 'Server Error', {}, io.BytesIO(b''))
            return w(url, headers, body)
        r = self.head(broken)
        self.assertEqual((r['sha'], r['backdate_check']['verdict']), (OLD, 'unverified'), 'served, but a check not run is never a negative')
        self.assertIn('not run (provider_error:HTTP500)', r['backdate_check']['checks']['pulls'])


if __name__ == '__main__':
    unittest.main()
