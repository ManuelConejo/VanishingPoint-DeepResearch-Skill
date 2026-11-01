#!/usr/bin/env python3
"""Offline tests of repo-grep / repo-ls (tools/sources/repo_grep.py, tools/repo_snapshot.py): exact search in a named repository at a
commit, one shallow fetch into a bare snapshot, nothing of the repository executed. A small git repository is built by the test and
fetched through file:// (repo_grep.FILE_ORIGINS, tests only; https only by default); the GitHub REST answers of the barrier are stubbed
(CodeClient._send). Checks: citable matches (repo:<owner>/<name>/<path>:<line>@<SHA40>, tools/check_code_refs.py form), exact negative,
--path, a pattern starting with '-', no hook / filter / textconv / fsmonitor of a hostile configuration or of the repository ever runs
(witness file, with a positive control), size cap (too_large), git absent (empty PATH), https only by default, bounded cache and safe
removal, barrier before any fetch, repo-ls with a submodule. Needs git. Run: python3 -I tests/test_repo_grep.py   (unittest; pytest-compatible)."""
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import code_sources as sc        # noqa: E402
import gateway as gw             # noqa: E402
import repo_snapshot as rs       # noqa: E402
import check_code_refs as CR     # noqa: E402
import sources.repo_grep as RGS  # noqa: E402

T = '2026-10-31'
CODE_PLUGIN = P.parent / 'plugins' / 'code.md'
GIT = shutil.which('git')
CLEAN = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'LC_ALL': 'C',
         'GIT_AUTHOR_NAME': 'a', 'GIT_AUTHOR_EMAIL': 'a@example.org', 'GIT_COMMITTER_NAME': 'a', 'GIT_COMMITTER_EMAIL': 'a@example.org',
         'GIT_AUTHOR_DATE': '2024-05-01T10:00:00Z', 'GIT_COMMITTER_DATE': '2024-05-01T10:00:00Z'}


def git(cwd, *args, env=None):
    e = dict(CLEAN, HOME=str(cwd)); e.update(env or {})
    return subprocess.run([GIT, *args], cwd=str(cwd), env=e, check=True, capture_output=True).stdout.decode().strip()


def commit(repo, files, msg='c'):
    for k, v in files.items():
        f = repo / k; f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(v if isinstance(v, bytes) else v.encode())
    git(repo, 'add', '-A'); git(repo, 'commit', '-q', '-m', msg)
    return git(repo, 'rev-parse', 'HEAD')


class GitHub:
    """GitHub REST for o/lib (default branch main, created 2015): every 40-hex commit of `dates` is served with its committer date."""
    def __init__(self, dates, head=None):
        self.urls, self.dates, self.head = [], dates, head

    def __call__(self, url, headers, body=None):
        self.urls.append(url)
        api = sc.GH['api'] + 'repos/o/lib'
        u = urllib.parse.urlsplit(url)
        if url == api:
            return 200, json.dumps({'full_name': 'o/lib', 'default_branch': 'main', 'created_at': '2015-01-01T00:00:00Z'}).encode()
        if u.path.endswith('/repos/o/lib/commits') and self.head:
            return 200, json.dumps([{'sha': self.head, 'commit': {'committer': {'date': self.dates[self.head]}}}]).encode()
        for sha, d in self.dates.items():
            if url.startswith(api + '/commits/') and '?' not in url and len(url) - len(api + '/commits/') >= 7 and sha.startswith(url[len(api + '/commits/'):]):
                return 200, json.dumps({'sha': sha, 'commit': {'committer': {'date': d}, 'author': {'date': d}}}).encode()
            if url.startswith(api + '/compare/main...' + sha): return 200, json.dumps({'status': 'behind'}).encode()
            if url.startswith(api + '/commits/' + sha + '/pulls'): return 200, b'[]'
        if url.startswith(api + '/events'): return 200, b'[]'
        raise AssertionError('unexpected URL ' + url)


@unittest.skipUnless(GIT, 'git not installed')
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.env = dict(os.environ); os.environ['HOME'] = str(self.d)
        for k in ('VP_GITHUB_TOKEN', 'VP_OFFLINE', 'SWH_TOKEN'): os.environ.pop(k, None)
        self.send0, self.rg0, self.web0, self.origins0 = sc.CodeClient._send, dict(rs.RG), sc.GH['web'], RGS.FILE_ORIGINS
        self.src = self.d / 'src'; self.src.mkdir(); git(self.src, 'init', '-q', '-b', 'main')
        self.sha = commit(self.src, {'src/retry.py': 'def stop_before_delay(retry_state):\n    """Stop before the delay."""\n    return x --output=pwned\n',
                                     'README.md': 'stop_before_delay stops before\n', 'docs/x.txt': 'stop_before_delay in docs\n'})
        RGS.FILE_ORIGINS = {'o/lib': str(self.src)}

    def tearDown(self):
        sc.CodeClient._send = self.send0; rs.RG.clear(); rs.RG.update(self.rg0); sc.GH['web'] = self.web0; RGS.FILE_ORIGINS = self.origins0
        os.environ.clear(); os.environ.update(self.env); self.tmp.cleanup()

    def gateway(self, transport=None, T=T, state='st'):
        self.gh = transport or GitHub({self.sha: '2024-05-01T10:00:00Z'})
        sc.CodeClient._send = lambda client, url, headers, body=None: self.gh(url, headers, body)
        g = gw.Gateway([str(CODE_PLUGIN)], T=T, run='r', state=self.d / state)
        g.client.sleep = lambda s: None
        return g

    def cache(self, state='st'): return self.d / state / rs.RG['cache_dir']


class Grep(Base):
    def test_served_with_the_code_plugin(self):
        s = gw.Gateway([str(CODE_PLUGIN)], T=T, run='r', state=self.d / 'st').sources()
        self.assertIn('repo-grep', s['code_engines'])
        for c in ('repo-grep', 'repo-ls'): self.assertIn(c, s['commands'])
        self.assertIn('engine', gw.Gateway([], T=T, run='r', state=self.d / 'st0').call('repo-grep', 'o/lib x')['refusal'])

    def test_matches_are_citable_at_the_full_sha_then_served_from_the_cache(self):
        g = self.gateway()
        r = g.call('repo-grep', 'o/lib@' + self.sha[:12] + ' stop_before_delay')['results']
        self.assertEqual((r['sha'], r['matched_lines'], r['files_matched'], r['truncated'], r['snapshot']['cached']), (self.sha, 3, 3, False, False))
        cites = sorted(m['cite'] for m in r['matches'])
        self.assertEqual(cites, sorted([f'repo:o/lib/src/retry.py:1@{self.sha}', f'repo:o/lib/README.md:1@{self.sha}', f'repo:o/lib/docs/x.txt:1@{self.sha}']))
        m = CR.REF.search('see ' + cites[-1] + ' here')
        self.assertEqual((m.group('kind'), m.group('path'), m.group('line'), m.group('sha')), ('repo:', 'o/lib/src/retry.py', '1', self.sha))
        self.assertIn('/blob/' + self.sha + '/src/retry.py#L1', [x for x in r['matches'] if x['path'] == 'src/retry.py'][0]['permanent_url'])
        r2 = g.call('repo-grep', 'o/lib@' + self.sha + ' "stop_before_delay"')['results']      # one pair of quotes is not searched
        self.assertEqual((r2['matched_lines'], r2['snapshot']['cached'], r2['pattern']), (3, True, 'stop_before_delay'))
        self.assertEqual(len(g.call('repo-grep', 'o/lib@' + self.sha + ' stop_before_delay', n=1)['results']['matches']), 1)

    def test_without_sha_the_last_commit_before_T(self):
        g = self.gateway(GitHub({self.sha: '2024-05-01T10:00:00Z'}, head=self.sha))
        r = g.call('repo-grep', 'https://github.com/o/lib Stop before')['results']
        self.assertEqual((r['sha'], r['matched_lines'], r['id']), (self.sha, 1, 'repo:o/lib@' + self.sha))

    def test_absent_string_is_an_exact_negative(self):
        r = self.gateway().call('repo-grep', 'o/lib@' + self.sha + ' retry_if_exception')['results']
        self.assertEqual((r['matched_lines'], r['matches']), (0, []))
        self.assertIn('exact', r['note'])

    def test_path_filter_and_refused_paths(self):
        g = self.gateway()
        r = g.call('repo-grep', 'o/lib@' + self.sha + ' stop_before_delay', path='src')['results']
        self.assertEqual([m['path'] for m in r['matches']], ['src/retry.py'])
        self.assertEqual(g.call('repo-grep', 'o/lib@' + self.sha + ' stop_before_delay', path='sr*')['results']['matched_lines'], 0)   # literal pathspec
        for bad in ('../x', '/etc', 'a/./b'):
            self.assertIn('refusal', g.call('repo-grep', 'o/lib@' + self.sha + ' x', path=bad)['results'], bad)
        self.assertIn('refusal', g.call('repo-grep', 'o/lib@' + self.sha + ' a\tb')['results'])

    def test_pattern_starting_with_a_dash_is_a_literal(self):
        g = self.gateway()
        before = set(os.listdir(self.d))
        r = g.call('repo-grep', 'o/lib@' + self.sha + ' --output=pwned')['results']
        self.assertEqual([m['path'] for m in r['matches']], ['src/retry.py'])
        for pat in ('-f/etc/passwd', '-e', '--no-index', '-O', '--open-files-in-pager=touch pwned'):
            self.assertEqual(g.call('repo-grep', 'o/lib@' + self.sha + ' ' + pat)['results']['matched_lines'], 0, pat)
        self.assertEqual(set(os.listdir(self.d)) - before, set())
        self.assertFalse(list(self.d.rglob('pwned')))


class NothingExecuted(Base):
    def test_no_hook_filter_textconv_or_fsmonitor_runs(self):
        w = self.d / 'WITNESS'
        hooks = self.d / 'hooks'; hooks.mkdir()
        script = f'#!/bin/sh\necho "$0" >> {w}\n'
        for h in ('reference-transaction', 'post-checkout', 'post-merge', 'pre-auto-gc', 'post-rewrite', 'fsmonitor-watchman', 'post-index-change'):
            (hooks / h).write_text(script); (hooks / h).chmod(0o755)
            (self.src / '.git' / 'hooks' / h).write_text(script); (self.src / '.git' / 'hooks' / h).chmod(0o755)
        tool = self.d / 'evil.sh'; tool.write_text(script + 'cat\n'); tool.chmod(0o755)
        hostile = self.d / 'hostile'; hostile.mkdir()
        conf = (f'[core]\n\thooksPath = {hooks}\n\tfsmonitor = {tool}\n[filter "evil"]\n\tsmudge = {tool}\n\tclean = {tool}\n\tprocess = {tool}\n'
                f'\trequired = true\n[diff "evil"]\n\ttextconv = {tool}\n[grep]\n\tpatternType = perl\n')
        (hostile / '.gitconfig').write_text(conf)
        sha = commit(self.src, {'.gitattributes': '* filter=evil diff=evil\n', '.githooks/post-checkout': script, 'hooks/reference-transaction': script,
                                'src/retry.py': 'def stop_before_delay(retry_state):\n    return True\n', '.gitmodules': f'[submodule "s"]\n\tpath = s\n\turl = ext::{tool}\n'},
                     )
        if w.exists(): w.unlink()
        # positive control: a plain fetch under the hostile configuration does run its hook
        ctl = self.d / 'ctl.git'
        subprocess.run([GIT, 'init', '-q', '--bare', str(ctl)], env={'PATH': CLEAN['PATH'], 'HOME': str(hostile)}, check=True, capture_output=True)
        subprocess.run([GIT, '--git-dir=' + str(ctl), 'fetch', '-q', self.src.as_uri(), sha + ':refs/x'],
                       env={'PATH': CLEAN['PATH'], 'HOME': str(hostile)}, capture_output=True)
        self.assertTrue(w.exists(), 'positive control: the hostile hook runs under a plain git fetch')
        w.unlink()
        # repo-grep / repo-ls under the same hostile HOME, plus hostile git variables in the environment
        os.environ.update({'HOME': str(hostile), 'XDG_CONFIG_HOME': str(hostile), 'GIT_CONFIG_PARAMETERS': f"'core.hooksPath'='{hooks}'",
                           'GIT_CONFIG_GLOBAL': str(hostile / '.gitconfig'), 'GIT_DIR': str(self.src / '.git'), 'GIT_EXTERNAL_DIFF': str(tool)})
        g = self.gateway(GitHub({sha: '2024-05-01T10:00:00Z'}))
        r = g.call('repo-grep', 'o/lib@' + sha + ' stop_before_delay')['results']
        self.assertEqual([m['path'] for m in r['matches']], ['README.md', 'docs/x.txt', 'src/retry.py'])
        self.assertEqual(g.call('repo-grep', 'o/lib@' + sha + ' stop_(before)')['results']['matched_lines'], 0)   # fixed string, never perl
        ls = g.call('repo-ls', 'o/lib@' + sha)['results']
        self.assertIn('.gitattributes', [f['path'] for f in ls['files']])
        self.assertFalse(w.exists(), 'nothing of the repository or of the hostile configuration ran')
        snap = next(p for p in self.cache().iterdir() if rs.ENTRY.fullmatch(p.name))
        self.assertFalse((snap / 'hooks').exists() and list((snap / 'hooks').iterdir()))
        self.assertFalse((snap / 'index').exists() or (snap / 'src').exists(), 'no working tree, no index')


class Bounds(Base):
    def test_too_large_is_typed_and_leaves_nothing(self):
        sha = commit(self.src, {'data.bin': os.urandom(1 << 20)})
        rs.RG['max_fetch_bytes'] = 200000
        r = self.gateway(GitHub({sha: '2024-05-01T10:00:00Z'})).call('repo-grep', 'o/lib@' + sha + ' stop_before_delay')['results']
        self.assertEqual(r['status'], 'too_large')
        self.assertIn('repo-file o/lib/<path>@' + sha, r['fallback'])
        self.assertEqual([p.name for p in self.cache().iterdir() if p.name != '.home'], [])

    def test_git_missing_is_typed_before_any_request(self):
        os.environ['PATH'] = ''
        g = self.gateway()
        for cmd, arg in (('repo-grep', 'o/lib@' + self.sha + ' x'), ('repo-ls', 'o/lib')):
            r = g.call(cmd, arg)['results']
            self.assertEqual(r['status'], 'git_missing', cmd)
            self.assertIn('repo-tree', r['fallback'])
        self.assertEqual(self.gh.urls, [])

    def test_https_only_by_default(self):
        RGS.FILE_ORIGINS = None
        s = rs.Snapshot(self.d / 'c')
        self.assertEqual(s.origin('o/lib'), ('https://github.com/o/lib', 'https'))
        sc.GH['web'] = self.src.parent.as_uri() + '/'
        with self.assertRaises(rs.SnapshotError) as e: s.origin('o/lib')
        self.assertEqual(e.exception.code, 'fetch_failed')
        r = self.gateway().call('repo-grep', 'o/lib@' + self.sha + ' x')['results']
        self.assertEqual(r['status'], 'fetch_failed')
        bare = self.d / 'c' / 'b.git'; bare.parent.mkdir(exist_ok=True)
        git(self.d, 'init', '-q', '--bare', str(bare))
        with self.assertRaises(rs.SnapshotError) as e: s._fetch(bare, self.src.as_uri(), 'https', self.sha)   # file:// under the https rule
        self.assertEqual(e.exception.code, 'fetch_failed')
        self.assertIn('not allowed', e.exception.reason)

    def test_bounded_cache_and_safe_removal(self):
        sha2 = commit(self.src, {'src/more.py': 'stop_before_delay = 1\n'})
        rs.RG['cache_max_entries'] = 1
        g = self.gateway(GitHub({self.sha: '2024-05-01T10:00:00Z', sha2: '2024-05-02T10:00:00Z'}))
        g.call('repo-grep', 'o/lib@' + self.sha + ' x'); g.call('repo-grep', 'o/lib@' + sha2 + ' x')
        names = [p.name for p in self.cache().iterdir() if rs.ENTRY.fullmatch(p.name)]
        self.assertEqual(names, ['o_lib_' + sha2])
        s = rs.Snapshot(self.cache())
        outside = self.d / 'keep'; outside.mkdir()
        for bad in (outside, self.cache() / '..' / 'keep', self.cache() / '.home', self.cache() / 'o_lib_x'):
            with self.assertRaises(ValueError, msg=str(bad)): s._remove(bad)
        link = self.cache() / ('o_lib_' + 'f' * 40); link.symlink_to(outside)
        with self.assertRaises(ValueError): s._remove(link)
        self.assertTrue(outside.is_dir())

    def test_barrier_refuses_before_any_fetch(self):
        r = self.gateway(T='2024-05-01').call('repo-grep', 'o/lib@' + self.sha + ' stop_before_delay')['results']
        self.assertIn('after T', r['refusal'])
        self.assertFalse(self.cache().exists())

    def test_truncated_beyond_max_matches(self):
        sha = commit(self.src, {'many.txt': 'hit\n' * 50})
        rs.RG['max_matches'] = 10
        r = self.gateway(GitHub({sha: '2024-05-01T10:00:00Z'})).call('repo-grep', 'o/lib@' + sha + ' hit', n=5)['results']
        self.assertEqual((r['matched_lines'], r['truncated'], len(r['matches'])), (10, True, 5))


class Ls(Base):
    def test_repo_ls_paths_sizes_and_submodule_listed_not_followed(self):
        git(self.src, 'update-index', '--add', '--cacheinfo', '160000,' + self.sha + ',vendor/sub')
        git(self.src, 'commit', '-q', '-m', 'sub')
        sha = git(self.src, 'rev-parse', 'HEAD')
        g = self.gateway(GitHub({sha: '2024-05-01T10:00:00Z'}))
        r = g.call('repo-ls', 'o/lib@' + sha)['results']
        self.assertEqual(sorted(f['path'] for f in r['files']), ['README.md', 'docs/x.txt', 'src/retry.py'])
        self.assertEqual(r['submodules'], ['vendor/sub'])
        self.assertEqual([f['bytes'] for f in r['files'] if f['path'] == 'README.md'], [len('stop_before_delay stops before\n')])
        self.assertEqual([f['path'] for f in g.call('repo-ls', 'o/lib@' + sha, path='src')['results']['files']], ['src/retry.py'])


if __name__ == '__main__':
    unittest.main()
