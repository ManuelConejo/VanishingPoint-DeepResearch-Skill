#!/usr/bin/env python3
"""Offline tests of the fixes of the independent security review by Codex of 2026-10-31 (items 1-11):
  1. repo-head retries: a backdated head refused by its push event is followed by the head BEFORE that push (payload `before`), never by an
     older commit of the same push; a backdate check that cannot run gives the verdict `unverified` (warned), never `none_detected`;
  2. check_code_facts dates its commits through GitHubRepo.head_gated / barrier (backdate checks), not gate() alone;
  3. find-implementations: lines and snippets of a pinned repository come from the file read at the dated commit, never from the search
     provider; hits of another revision of the same file are not merged;
  4. an undated find-implementations result carries no citation form (cite, id, permanent_url);
  5. Sourcegraph answers bounded before any hit is built (path length, matches per file, hits in all);
  6. repo-grep / repo-ls output bounded in bytes (one record, all records), git under a memory bound;
  7. forks-ahead refuses a comparison whose commits GitHub listed only in part;
  8. gh: the title at T is served only when the events establish it (a full page without a rename after T: current title, marked);
  9. HTTP reads under a total deadline and a byte cap (CodeClient, sources._common.fetch, error bodies);
 10. HTTP caches under an aggregate byte cap (no write beyond it, nothing evicted), receipts rotated beyond a size;
 11. a same-content copy of a repository refused at dating comes back as a candidate.
Transport replaced (CodeClient._send, urlopen); no network. Run: python3 -I tests/test_codex_review_fixes.py   (unittest; pytest-compatible)."""
import datetime, io, json, os, pathlib, sys, tempfile, time, unittest, urllib.error, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import code_sources as sc                  # noqa: E402
import check_code_facts as F               # noqa: E402
import repo_snapshot as rs                 # noqa: E402
from sources import _common as cm          # noqa: E402
from sources import forks_ahead as fa      # noqa: E402
from sources import github_issues as gi    # noqa: E402

TD = datetime.date.today() - datetime.timedelta(days=10)          # T inside the 90 days of public events GitHub keeps
T = TD.isoformat()
day = lambda n: (TD + datetime.timedelta(days=n)).isoformat() + 'T00:00:00Z'
A, B_, C, D, X, Y = ('a' * 40, 'b' * 40, 'c' * 40, 'd' * 40, 'e' * 40, 'f' * 40)


class Bar:
    """The date barrier of the gateway (sources._common.Barrier) at T."""
    def __new__(cls, t=T): return cm.Barrier(t)


class World:
    """GitHub API, raw host and Sourcegraph. repos: name -> {commits {sha: (committer, author, parents)}, head [shas], pulls {sha: [..]},
    events [..], files {(sha, path): text}, fail (substring of URL -> HTTP code)}."""
    def __init__(self, repos, sg=None):
        self.repos, self.sg, self.urls = repos, sg, []

    def __call__(self, url, headers, body=None):
        self.urls.append(url)
        u = urllib.parse.urlsplit(url)
        if u.hostname == 'sourcegraph.com': return 200, self.sg
        if url.startswith(sc.GH['raw']):
            rest = url[len(sc.GH['raw']):].split('/')
            f = self.repos.get('/'.join(rest[:2]), {}).get('files', {}).get((rest[2], urllib.parse.unquote('/'.join(rest[3:]))))
            if f is not None: return 200, f.encode()
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO(b''))
        rest = url[len(sc.GH['api'] + 'repos/'):].split('?')[0].split('/')
        name, tail = '/'.join(rest[:2]), rest[2:]
        r = self.repos.get(name)
        if r is None: raise urllib.error.HTTPError(url, 404, 'Not Found', {}, io.BytesIO(b''))
        for k, code in r.get('fail', {}).items():
            if k in url: raise urllib.error.HTTPError(url, code, 'x', {}, io.BytesIO(b''))
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
        if tail[0] == 'license': return 200, json.dumps({'license': {'spdx_id': 'MIT'}, 'path': 'LICENSE'}).encode()
        raise AssertionError('unexpected URL ' + url)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.env = dict(os.environ); os.environ['HOME'] = str(self.d)
        for k in ('VP_GITHUB_TOKEN', 'VP_OFFLINE', 'SWH_TOKEN'): os.environ.pop(k, None)
        self.tables = (sc.IMPL, sc.__dict__.setdefault('HL', {}), rs.RG, gi.GI)     # config tables the tests change
        self.saved = [dict(x) for x in self.tables]
        self.send0 = sc.CodeClient._send
        def offline(client, url, headers, body=None): raise AssertionError('network attempted in a test')
        sc.CodeClient._send = offline                                   # no test reaches the network by accident

    def tearDown(self):
        sc.CodeClient._send = self.send0
        for x, s in zip(self.tables, self.saved): x.clear(); x.update(s)
        os.environ.clear(); os.environ.update(self.env); self.tmp.cleanup()

    def client(self, world, cache=True):
        """A code client whose transport is `world`, also for the clients the engines derive from it (class attribute: no network)."""
        sc.CodeClient._send = lambda client, url, headers, body=None: world(url, headers, body)
        c = sc.CodeClient(hosts=sc.HOSTS | sc.GH_HOSTS | sc.USAGE_HOSTS, cache_dir=self.d / 'state' if cache else None)
        c.sleep = lambda s: None
        return c


class Item1HeadRetries(Base):
    def test_push_refusal_falls_back_on_the_head_before_the_push(self):
        repos = {'o/r': {'commits': {D: (day(-1), day(-1), [C]), C: (day(-2), day(-2), [X]), X: (day(-60), day(-60), [])}, 'head': [D, C, X],
                         'events': [{'type': 'PushEvent', 'created_at': day(1), 'payload': {'ref': 'refs/heads/main', 'head': D, 'before': X}}]}}
        gh = sc.GitHubRepo(self.client(World(repos)))
        h, why = gh.head_gated('o/r', Bar())
        self.assertIsNone(why)
        self.assertNotEqual(h['sha'], C, 'C came with the same push as D (after T): never served as the head at T')
        self.assertEqual(h['sha'], X, 'the default-branch head before that push')

    def test_push_refusal_without_before_refuses(self):
        repos = {'o/r': {'commits': {D: (day(-1), day(-1), [C]), C: (day(-2), day(-2), [])}, 'head': [D, C],
                         'events': [{'type': 'PushEvent', 'created_at': day(1), 'payload': {'ref': 'refs/heads/main', 'head': D}}]}}
        h, why = sc.GitHubRepo(self.client(World(repos))).head_gated('o/r', Bar())
        self.assertIsNone(h); self.assertIn('same push', why)

    def test_a_check_that_cannot_run_is_not_a_negative(self):
        repos = {'o/r': {'commits': {X: (day(-60), day(-60), [])}, 'head': [X], 'fail': {'/pulls': 500}}}
        extra = {}
        h, why = sc.GitHubRepo(self.client(World(repos)), extra).head_gated('o/r', Bar(), extra)
        self.assertIsNone(why)
        self.assertEqual(h['backdate_check']['verdict'], 'unverified')
        self.assertIn('not established', extra.get('warning', ''))


class Item2FactChecker(Base):
    def test_last_commit_through_the_backdate_barrier(self):
        repos = {'o/p': {'commits': {A: (day(-3), day(-3), [])}, 'head': [A], 'pulls': {A: [{'merged_at': day(2), 'base': {'ref': 'main'}}]}}}
        gh = sc.GitHubRepo(self.client(World(repos)))
        p = self.d / 'card.json'
        p.write_text(json.dumps({'card_id': 't', 'sources': {'S': {'code': 'repo:o/p@' + A}},
                                 'claims': [{'id': 'A1', 'text': f'The last commit of o/p is dated {day(-3)[:10]}.', 'source': {'key': 'S'}},
                                            {'id': 'A2', 'text': 'o/p is licensed MIT.', 'source': {'key': 'S'}}]}))
        rep = F.check([p], TD, gh=gh, today=datetime.date.today())
        st = {f['type']: (f['status'], f.get('reason_type')) for f in rep['facts']}
        self.assertEqual(st['last_commit'], ('UNCHECKABLE', 'after_T'), 'merged into the default branch after T: not the last commit before T')
        self.assertEqual(st['licence'], ('UNCHECKABLE', 'after_T'), 'the pinned commit entered the default branch after T')


def sse(items):
    return ('event: matches\ndata: ' + json.dumps(items) + '\n\nevent: done\ndata: {}\n\n').encode()


def content(repo, path, commit, stars, lines):
    return {'type': 'content', 'repository': 'github.com/' + repo, 'path': path, 'commit': commit, 'repoStars': stars,
            'lineMatches': [{'lineNumber': n - 1, 'line': l} for n, l in lines]}


class Item3to5Implementations(Base):
    def find(self, world, n=5, **kw):
        return sc.Implementations(self.client(world)).find('retry-after', Bar(), n=n, **kw)

    def test_pinned_lines_come_from_the_file_at_the_commit(self):
        sg = sse([content('o/r', 'net.py', A, 10, [(5, 'h = "Retry-After"  # INVENTED after T')])])
        repos = {'o/r': {'commits': {A: (day(-30), day(-30), [])}, 'files': {(A, 'net.py'): 'import x\n\n\nv = r.headers["retry-after"]\n'}}}
        out = self.find(World(repos, sg))
        self.assertEqual(out[0]['dating'], 'indexed commit dated before T')
        self.assertEqual((out[0]['lines'], out[0]['snippets']), ([4], ['v = r.headers["retry-after"]']), 'read at the commit, not the provider text')
        self.assertNotIn('INVENTED', json.dumps(out))

    def test_snippets_absent_at_the_commit_are_not_certified(self):
        sg = sse([content('o/r', 'invented/path.py', A, 10, [(5, 'retry-after INVENTED')])])
        repos = {'o/r': {'commits': {A: (day(-30), day(-30), [])}}}
        out = self.find(World(repos, sg))
        self.assertIn('refusal', out[0]); self.assertNotIn('cite', out[0])

    def test_hits_of_another_revision_are_not_merged(self):
        G = sc.Implementations(self.client(World({})))._groups(
            [sc.hit('o/r', 'a.py', 3, A, 'one') | {'found_by': 'x'}, sc.hit('o/r', 'a.py', 9, B_, 'two') | {'found_by': 'x'}], [])
        f = G['o/r']['files']['a.py']
        self.assertEqual((f['commit'], f['lines']), (A, [3]))

    def test_undated_results_carry_no_citation(self):
        sc.IMPL['pinned_repos'] = 0
        sg = sse([content('o/r', 'net.py', A, 10, [(5, 'retry-after')])])
        out = self.find(World({}, sg))
        self.assertTrue(out[0]['dating'].startswith('absent'))
        for k in ('cite', 'permanent_url'): self.assertNotIn(k, out[0])
        self.assertIsNone(out[0]['id']); self.assertEqual(out[0]['index_commit'], A)

    def test_sourcegraph_answer_bounded_before_hits_are_built(self):
        sc.IMPL.update(path_max_chars=50, matches_per_file_max=3, hits_max=5)
        many = [(i, 'retry-after') for i in range(1, 1001)]
        sg = sse([content('o/r', 'p' * 60 + '.py', A, 1, many), content('o/s', 'a.py', A, 1, many), content('o/t', 'b.py', A, 1, many)])
        im = sc.Implementations(self.client(World({}, sg)))
        hits = im._sourcegraph('sourcegraph_global', ['retry-after'], None, None)
        self.assertEqual([h['repo'] for h in hits], ['o/s'] * 3 + ['o/t'] * 2, 'long path skipped, 3 matches per file, 5 hits in all')
        self.assertEqual(im.status['sourcegraph_global']['status'], 'truncated')
        self.assertEqual(len(sc.parse_sourcegraph(sg.decode(), limit=4)), 4)


class Item6Snapshot(Base):
    def snap(self):
        return rs.Snapshot(self.d / 'cache')

    def test_one_record_bounded(self):
        rs.RG.update(record_max_bytes=1000, output_max_bytes=10_000_000)
        argv = [sys.executable, '-I', '-c', 'import sys; sys.stdout.write("x" * 3000000 + "\\nshort\\n")']
        recs, truncated, rc, _ = self.snap()._stream(argv, 'none', 30, 100, b'\n')
        self.assertEqual([len(r) for r in recs], [1000, 5], 'the long record is cut, the next one read')
        self.assertEqual(rc, 0)

    def test_all_records_bounded(self):
        rs.RG.update(record_max_bytes=1000, output_max_bytes=50_000)
        argv = [sys.executable, '-I', '-c', 'import sys\nfor i in range(100000): sys.stdout.write("y" * 900 + "\\n")']
        recs, truncated, rc, _ = self.snap()._stream(argv, 'none', 30, 10**6, b'\n')
        self.assertTrue(truncated); self.assertLessEqual(sum(len(r) for r in recs), 50_000)

    def test_git_under_a_memory_bound(self):
        if not hasattr(rs, 'resource') or rs.resource is None: self.skipTest('no resource module (not POSIX)')
        rs.RG.update(git_max_memory_bytes=300_000_000)
        argv = [sys.executable, '-I', '-c', 'b = bytearray(600000000)']
        _, _, rc, _ = self.snap()._stream(argv, 'none', 30, 10, b'\n')
        self.assertNotEqual(rc, 0, 'allocation beyond repo_grep.git_max_memory_bytes fails')


class Item7Forks(Base):
    def test_partial_comparison_refused(self):
        class G:
            def check(self, r): return r
            def backdate(self, *a, **k): return {'verdict': 'none_detected', 'signals': []}
            def _api(self, path):
                return {'status': 'ahead', 'ahead_by': 400, 'behind_by': 0, 'files': [{'filename': 'a.py'}],
                        'commits': [{'sha': A, 'parents': [{'sha': B_}], 'commit': {'committer': {'date': day(-5)}, 'author': {'date': day(-5)}}}]}
        served, why = fa.compare(G(), 'o/r', 'f/r', B_, A, Bar())
        self.assertIsNone(served); self.assertIn('1 of 400', why)


class Item8IssueTitle(Base):
    def test_title_not_established_from_a_full_page_without_rename(self):
        gi.GI['events_page'] = 3
        events = [{'event': 'labeled', 'created_at': day(i)} for i in (1, 2, 3)]
        st, title, complete, title_known = gi._events_at_T(events, Bar(), 'Current title')
        self.assertTrue(complete); self.assertFalse(title_known)
        events[1] = {'event': 'renamed', 'created_at': day(2), 'rename': {'from': 'Old', 'to': 'Current title'}}
        self.assertEqual(gi._events_at_T(events, Bar(), 'Current title')[1:], ('Old', True, True))

    def test_read_marks_the_current_title(self):
        gi.GI['events_page'] = 2
        def world(url, headers, body=None):
            if url.endswith('/issues/7'): return 200, json.dumps({'title': 'Now', 'created_at': day(-100), 'state': 'open', 'number': 7,
                                                                  'html_url': 'https://github.com/o/r/issues/7'}).encode()
            if '/events' in url: return 200, json.dumps([{'event': 'labeled', 'created_at': day(1)}, {'event': 'labeled', 'created_at': day(2)}]).encode()
            return 200, b'[]'
        out = gi.read_gh_ident('gh:o/r#7', Bar(), self.client(world))
        self.assertIn('state_at_T', out); self.assertTrue(out['title_as_of'].startswith('now'))


class Item9And10Http(Base):
    class Drip:
        def __init__(self, n, pause): self.n, self.pause, self.status = n, pause, 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read1(self, k=-1):
            if self.n <= 0: return b''
            time.sleep(self.pause); self.n -= 1; return b'x'
        read = read1

    def test_code_client_total_deadline(self):
        sc.HL['total_timeout_s'] = 0.5
        sc.CodeClient._send = self.send0                                # the real transport, over the fake opener below
        c = sc.CodeClient(); c.sleep = lambda s: None
        c.opener = type('O', (), {'open': lambda s, req, timeout=None: Item9And10Http.Drip(40, 0.1)})()
        t0 = time.monotonic()
        with self.assertRaises(ValueError) as e: c.get('https://api.github.com/x')
        self.assertEqual(str(e.exception), 'transport_error:TimeoutError'); self.assertLess(time.monotonic() - t0, 2.5)

    def test_common_fetch_byte_cap_and_error_body(self):
        sc.HL['fetch_max_bytes'] = 1000
        class Big:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read1(self, k=-1): return b'z' * min(k if k > 0 else 65536, 65536)
            def read(self, k=-1):
                if k is None or k < 0: raise AssertionError('unbounded read')
                return self.read1(k)
        saved, cm.STATE = cm.STATE, self.d / 'st'
        u0 = cm.urllib.request.urlopen
        cm.urllib.request.urlopen = lambda req, timeout=None: Big()
        try:
            with self.assertRaises(cm.ProviderError): cm.fetch('https://example.org/big')
            self.assertFalse((self.d / 'st' / 'cache').exists() and any((self.d / 'st' / 'cache').iterdir()))
        finally: cm.urllib.request.urlopen = u0; cm.STATE = saved

    def test_cache_cap_and_receipts_rotation(self):
        sc.HL.update(cache_max_bytes=150, receipts_max_bytes=400)
        c = self.client(lambda url, headers, body=None: (200, b'v' * 100))
        c.get('https://api.github.com/a'); c.get('https://api.github.com/b')
        files = list((self.d / 'state' / 'cache').iterdir())
        self.assertEqual(len(files), 1, 'the second answer is served but not cached beyond http_limits.cache_max_bytes')
        self.assertEqual(c.receipts[-1].get('cache'), 'full')
        for i in range(10): c.get(f'https://api.github.com/r{i}')
        self.assertLessEqual((self.d / 'state' / 'requests.jsonl').stat().st_size, 400 + 400)
        self.assertTrue((self.d / 'state' / 'requests.jsonl.1').exists())


class Item11Copies(Base):
    def test_copy_of_a_refused_repository_comes_back(self):
        lines = [(4, 'v = r.headers["retry-after"]')]
        sg = sse([content('bad/fake', 'net.py', B_, 9999, lines), content('good/lib', 'net.py', A, 10, lines)])
        repos = {'bad/fake': {'commits': {B_: (day(1), day(1), [])}},
                 'good/lib': {'commits': {A: (day(-30), day(-30), [])}, 'files': {(A, 'net.py'): 'import x\n\n\nv = r.headers["retry-after"]\n'}}}
        out = sc.Implementations(self.client(World(repos, sg))).find('retry-after', Bar(), n=5)
        r = {x['repo']: x for x in out}
        self.assertIn('refusal', r['bad/fake'])
        self.assertIn('good/lib', r, 'no longer hidden as a copy of a repository refused at dating')
        self.assertEqual(r['good/lib']['dating'], 'indexed commit dated before T')


if __name__ == '__main__':
    unittest.main()
