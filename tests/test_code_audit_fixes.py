#!/usr/bin/env python3
"""Offline tests of the tool fixes of the audit of the "what would Y bring to X" mode (internal audit of 2026-10-31).
Every network answer is stubbed (CodeClient._send, file:// snapshot origins through repo_grep.FILE_ORIGINS); git is used on throwaway
repositories built here. One class per fix (the audit item in its name). Run: python3 -I tests/test_code_audit_fixes.py (unittest)."""
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest, urllib.parse
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools')); sys.path.insert(0, str(P.parent / 'tools' / 'verifier'))
import code_sources as sc        # noqa: E402
import gateway as gw             # noqa: E402
import repo_snapshot as rs       # noqa: E402
import sources.repo_grep as RGS  # noqa: E402

T = '2026-10-31'
CODE_PLUGIN = P.parent / 'plugins' / 'code.md'
GIT = shutil.which('git')
CLEAN = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'LC_ALL': 'C',
         'GIT_AUTHOR_NAME': 'a', 'GIT_AUTHOR_EMAIL': 'a@example.org', 'GIT_COMMITTER_NAME': 'a', 'GIT_COMMITTER_EMAIL': 'a@example.org',
         'GIT_AUTHOR_DATE': '2024-05-01T10:00:00Z', 'GIT_COMMITTER_DATE': '2024-05-01T10:00:00Z'}


def git(cwd, *args):
    return subprocess.run([GIT, *args], cwd=str(cwd), env=dict(CLEAN, HOME=str(cwd)), check=True, capture_output=True).stdout.decode('utf-8', 'replace').strip()


def commit(repo, files, msg='c'):
    for k, v in files.items():
        f = repo / k; f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(v if isinstance(v, bytes) else v.encode())
    git(repo, 'add', '-A'); git(repo, 'commit', '-q', '-m', msg)
    return git(repo, 'rev-parse', 'HEAD')


class GitHub:
    """GitHub REST for o/lib (default branch main, created 2015): every 40-hex commit of `dates` is served with its committer date; `extra`
    = {url prefix: (status, body)} answers tried first."""
    def __init__(self, dates, head=None, extra=None):
        self.urls, self.dates, self.head, self.extra = [], dates, head, extra or {}

    def __call__(self, url, headers, body=None):
        self.urls.append(url)
        for k, v in self.extra.items():
            if (url == k[:-1]) if k.endswith('$') else url.startswith(k):          # a key ending with $ = this exact URL
                if isinstance(v, Exception): raise v
                return v[0], (v[1] if isinstance(v[1], bytes) else json.dumps(v[1]).encode())
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


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.env = dict(os.environ); os.environ['HOME'] = str(self.d)
        for k in ('VP_GITHUB_TOKEN', 'VP_OFFLINE', 'SWH_TOKEN'): os.environ.pop(k, None)
        self.send0, self.origins0, self.wait0 = sc.CodeClient._send, RGS.FILE_ORIGINS, sc.CodeClient._wait
        sc.CodeClient._wait = lambda client, host, keyed=False: None          # no pacing in tests (the transport is stubbed)

    def tearDown(self):
        sc.CodeClient._send = self.send0; RGS.FILE_ORIGINS = self.origins0; sc.CodeClient._wait = self.wait0
        os.environ.clear(); os.environ.update(self.env); self.tmp.cleanup()

    def stub(self, transport):
        self.gh = transport
        sc.CodeClient._send = lambda client, url, headers, body=None: self.gh(url, headers, body)


# ---------------------------------------------------------------------------------------------------- 1c 1d 1e: condense_repo
@unittest.skipUnless(GIT, 'git not installed')
class CondenseNumbering_1c_1d_1e(Env):
    def setUp(self):
        super().setUp()
        import condense_repo as cr
        self.cr = cr
        self.src = self.d / 'y'; self.src.mkdir(); git(self.src, 'init', '-q', '-b', 'main')
        self.sha = commit(self.src, {'a.py': 'one\n\x0ctwo\nthree\rstill three\nfour same four\nTARGET = 1\n',
                                     'b.c': 'x\r\ny\r\nTARGET\r\n', 'lat.txt': 'caf\xe9 TARGET\n'.encode('latin-1'),
                                     '.github/w.yml': 'w' * 50 + '\n', 'docs/d.md': 'd' * 50 + '\n', 'src/core.py': 'c' * 50 + '\n',
                                     'README.md': 'r\n'})

    def digest(self, cap=100000, priority=()):
        text, summ = self.cr.condense(self.cr.LocalRepo(str(self.src)), 'HEAD', 'o/y', cap, list(priority), [])
        return text, summ

    def block_line(self, text, path, needle):
        blk = text.split(f'=== {path} @')[1].split('\n=== ')[0]
        return next(int(l.split('\t', 1)[0]) for l in blk.split('\n')[1:] if '\t' in l and needle in l.split('\t', 1)[1])

    def test_line_numbers_are_git_numbers(self):
        text, _ = self.digest()
        grep = git(self.src, 'grep', '-n', 'TARGET', 'HEAD', '--', 'a.py', 'b.c')
        want = {l.split(':')[1]: int(l.split(':')[2]) for l in grep.splitlines()}
        self.assertEqual(self.block_line(text, 'a.py', 'TARGET'), want['a.py'])
        self.assertEqual(self.block_line(text, 'b.c', 'TARGET'), want['b.c'])

    def test_full_sha_in_headers(self):
        text, _ = self.digest()
        self.assertIn(f'# Expected citation: <path>:<line>@{self.sha}', text)
        self.assertIn(f'=== a.py @{self.sha} (', text)

    def test_default_order_code_before_docs_and_ci(self):
        cap = 2 + len('one\n\x0ctwo\nthree\rstill three\nfour\u2028same four\nTARGET = 1\n') + len('x\r\ny\r\nTARGET\r\n') + len('café TARGET\n') + 51
        text, summ = self.digest(cap=cap)                   # README, a.py, b.c, lat.txt and ONE 51-character file fit
        self.assertIn('src/core.py', [l.split('=== ')[1].split(' @')[0] for l in text.splitlines() if l.startswith('=== ')])
        self.assertIn('docs/d.md', summ['not_included_cap']); self.assertIn('.github/w.yml', summ['not_included_cap'])

    def test_latin1_not_dropped(self):
        text, summ = self.digest()
        self.assertIn('café TARGET', text)
        self.assertTrue(any('latin-1' in r for r in summ['reasons']))


# ---------------------------------------------------------------------------------------------------- 1b / 5a: whole reading without a mirror
@unittest.skipUnless(GIT, 'git not installed')
class WholeReadingFromGateway_1b(Env):
    def setUp(self):
        super().setUp()
        import whole_reading as W
        self.W = W
        self.src = self.d / 'src'; self.src.mkdir(); git(self.src, 'init', '-q', '-b', 'main')
        self.sha = commit(self.src, {'src/retry.py': 'def stop():\n\x0c\n    return 1\n', 'README.md': 'lib\n'})
        RGS.FILE_ORIGINS = {'o/lib': str(self.src)}
        self.stub(GitHub({self.sha: '2024-05-01T10:00:00Z'}))
        self.run = self.d / 'run'; (self.run / 'searches').mkdir(parents=True); (self.run / 'state').mkdir()
        (self.run / 'scope.md').write_text(f'# scope\nQuestion: "what would Y bring?"\nT = {T}\n- Y : o/lib@{self.sha}\n')

    def main(self, *args):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): self.W.main([str(self.run), *args, '--material-only'])
        return json.loads(buf.getvalue().strip().splitlines()[-1])

    def check(self, s):
        y = (self.run / 'state' / 'whole-reading' / 'material-Y.txt').read_text()
        self.assertIn(f'=== src/retry.py @{self.sha} (3 lines) ===', y)
        self.assertIn('3\t    return 1', y)                                    # the form feed line does not shift the numbering
        self.assertEqual(s['Y']['pool'], 'whole_reading'); self.assertEqual(s['Y']['source'], f'o/lib@{self.sha}')
        j = [json.loads(l) for l in (self.run / 'state' / 'journal.jsonl').read_text().splitlines()]
        self.assertEqual([(x['call'], x.get('pool')) for x in j], [('repo-ls', 'whole_reading')])
        self.assertFalse((self.run / 'state' / f'counter-{self.run.name}.txt').exists())   # the searches' counter is untouched

    def test_explicit_option(self):
        self.check(self.main('--y-gateway', f'o/lib@{self.sha[:12]}'))

    def test_from_scope_without_mirror(self):
        self.check(self.main())                                                  # scope.md names Y as <owner>/<name>@<SHA>, no --y-repo

    def test_refusal_stops_with_reason(self):
        self.stub(GitHub({self.sha: '2027-01-01T00:00:00Z'}))                     # committed after T
        with self.assertRaises(SystemExit) as e: self.main('--y-gateway', f'o/lib@{self.sha}')
        self.assertIn('whole reading: not run', str(e.exception))


# ---------------------------------------------------------------------------------------------------- 5b: repo-file reads on past the cut
class RepoFileRange_5b(Env):
    def test_lines_read_on_past_the_cut(self):
        cap = gw.CFG['code_text']['served_chars']
        body = ''.join(f'line {i:06d} ' + 'x' * 30 + '\n' for i in range(1, cap // 30))   # about 1.4 times the cap
        out = {'results': {'text': body, 'bytes': len(body), 'sha256': 'h'}}
        v = gw.served_view(out, 'repo-file')['results']
        nxt = int(v['read_on'].split()[1].rstrip('-'))
        self.assertIn(f'read on with --lines {nxt}-', v['text'])
        w = gw.served_view(out, 'repo-file', f'{nxt}-')['results']
        self.assertTrue(w['text'].startswith(f'line {nxt:06d} '))
        self.assertEqual(w['text_served']['lines'][0], nxt)
        self.assertLessEqual(w['text_served']['chars'], cap)
        self.assertEqual(w["text_served"]["of_lines"], cap // 30 - 1)
        self.assertNotIn('read_on', w['text_served'])                       # the rest fits under the cap
        x = gw.served_view(out, 'repo-file', '3-4')['results']
        self.assertEqual(x['text'], 'line 000003 ' + 'x' * 30 + '\nline 000004 ' + 'x' * 30 + '\n')
        self.assertIn('refusal', gw.served_view(out, 'repo-file', '9-2')['results'])

    def test_numbering_is_git_numbering(self):
        out = {'results': {'text': 'a\n\x0cb\nc\rd\ne\n', 'bytes': 9, 'sha256': 'h'}}
        self.assertEqual(gw.served_view(out, 'code-file', '3')['results']['text'], 'c\rd\n')


# ---------------------------------------------------------------------------------------------------- 3a 3c 3d: licence read at the SHA
SHA = 'a' * 40
CARGO = '[package]\nname = "lib"\nlicense = "MIT OR Apache-2.0"\n'
APACHE = '                                 Apache License\n                           Version 2.0, January 2004\n'
MIT = 'MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\n'
SHIELD = '# PolyForm Shield License 1.0.0\n\n<https://polyformproject.org/licenses/shield/1.0.0>\n'


def licence_repo(files, spdx='NOASSERTION', path='LICENSE-APACHE'):
    """GitHub REST + raw host for o/lib at SHA: licence detection `spdx`, tree = the keys of `files`, raw = their texts."""
    tree = {'tree': [{'path': k, 'type': 'blob'} for k in files], 'truncated': False}
    extra = {sc.GH['api'] + f'repos/o/lib/license?ref={SHA}': (200, {'license': {'spdx_id': spdx}, 'path': path}),
             sc.GH['api'] + f'repos/o/lib/git/trees/{SHA}?recursive=1': (200, tree)}
    for k, v in files.items(): extra[sc.GH['raw'] + f'o/lib/{SHA}/{k}'] = (200, v.encode())
    return GitHub({SHA: '2024-05-01T10:00:00Z'}, extra=extra)


class LicenceRead_3a_3c(Env):
    def repo(self):
        return sc.GitHubRepo(sc.CodeClient(cache_dir=None))

    def test_dual_licence_kept_whole_and_directory_licence(self):
        self.stub(licence_repo({'LICENSE-APACHE': APACHE, 'LICENSE-MIT': MIT, 'Cargo.toml': CARGO, 'README.md': '# lib\nLicensed under MIT or Apache.\n',
                                'platform/LICENCE.txt': SHIELD, 'src/lib.rs': 'fn main() {}\n', 'licenses.py': 'x = 1\n',
                                'sub/LICENSE-APACHE': APACHE, 'sub/LICENSE-MIT': MIT}))
        r = self.repo().licence_read('o/lib', SHA, 'NOASSERTION')
        self.assertEqual((r['status'], r['expression']), ('read', 'MIT OR Apache-2.0'))
        self.assertTrue(r['basis'].startswith('manifest Cargo.toml'))
        self.assertEqual({f['path']: f['identified'] for f in r['files']}, {'LICENSE-APACHE': ['Apache-2.0'], 'LICENSE-MIT': ['MIT']})
        self.assertEqual(r['by_directory'], [{'directory': 'platform', 'paths': ['platform/LICENCE.txt'], 'identified': ['PolyForm-Shield-1.0.0'], 'same_as_root': False},
                                             {'directory': 'sub', 'paths': ['sub/LICENSE-APACHE', 'sub/LICENSE-MIT'], 'identified': ['Apache-2.0', 'MIT'], 'same_as_root': True}])
        self.assertEqual(r['readme'][0]['line'], 2)

    def test_readme_only_is_unread(self):
        self.stub(licence_repo({'README.md': 'released under the MIT License. See the [LICENSE](LICENSE) file\n', 'a.py': ''}, spdx=None))
        r = self.repo().licence_read('o/lib', SHA)
        self.assertEqual((r['status'], r['expression']), ('unread', None))
        self.assertIn('not a licence file', r['note']); self.assertIn('MIT License', r['readme'][0]['text'])

    def test_repo_info_serves_licence_read(self):
        self.stub(licence_repo({'LICENSE': MIT}, spdx='NOASSERTION', path='LICENSE'))
        g = gw.Gateway([str(CODE_PLUGIN)], T=T, run='r', state=self.d / 'st')
        out = g.call('repo-info', f'o/lib@{SHA}')['results']
        self.assertEqual(out['licence']['spdx'], 'NOASSERTION')
        self.assertEqual((out['licence_read']['status'], out['licence_read']['expression']), ('read', 'MIT'))

    def facts(self, card, mechs=None):
        import check_code_facts as cf, datetime
        run = self.d / 'run'; run.mkdir(exist_ok=True)
        (run / 'card.json').write_text(json.dumps(card))
        paths = [run / 'card.json']
        if mechs is not None: (run / 'mechanisms.json').write_text(json.dumps(mechs)); paths.append(run / 'mechanisms.json')
        return cf.check(paths, datetime.date.fromisoformat(T), run_dir=run, gh=self.repo(), osv=None, today=datetime.date.fromisoformat(T))

    def test_facts_confirm_through_manifest_and_parse_dual(self):
        self.stub(licence_repo({'LICENSE-APACHE': APACHE, 'LICENSE-MIT': MIT, 'Cargo.toml': CARGO, 'platform/LICENCE.txt': SHIELD,
                                'sub/LICENSE-APACHE': APACHE, 'sub/LICENSE-MIT': MIT}))          # sub/: the same dual licence as the root
        card = {'claims': [{'id': 'c1', 'text': 'o/lib is under the MIT licence.', 'source': {'key': '1'}},
                           {'id': 'c2', 'text': 'o/lib is dual licensed MIT or Apache-2.0.', 'source': {'key': '1'}},
                           {'id': 'c3', 'text': 'o/lib is under the GPL-3.0 licence.', 'source': {'key': '1'}}],
                'sources': {'1': {'code': f'repo:o/lib/sub/lib.rs@{SHA}'}}}
        mechs = [{'mechanism': 'm', 'y_side': f'platform/run.py:3@{SHA}', 'licence': 'copy allowed: MIT licence of o/lib'}]
        rep = self.facts(card)
        st = {w.split(':', 1)[1]: (f['claimed'], f['status']) for f in rep['facts'] for w in f['where']}
        self.assertEqual(st['claims.c1'], ('MIT', 'CONFIRMED'))            # GitHub: NOASSERTION; manifest: MIT OR Apache-2.0
        self.assertEqual(st['claims.c2'], ('MIT OR Apache-2.0', 'CONFIRMED'))
        self.assertEqual(st['claims.c3'], ('GPL-3.0', 'CONTRADICTED'))
        rep = self.facts(card, mechs)                                      # the mechanism lies under platform/ (PolyForm Shield)
        f = next(f for f in rep['facts'] if 'mechanisms.json:[0].licence' in f['where'])
        self.assertEqual((f['claimed'], f['status']), ('MIT', 'CONTRADICTED'))
        self.assertEqual([x['path'] for x in f['contradicted_for']], ['platform/run.py'])


class RenamedRepository_3d(Env):
    def test_api_redirect_followed_on_same_host_only(self):
        moved = sc.GH['api'] + 'repositories/42'
        tr = GitHub({}, extra={sc.GH['api'] + 'repos/old/lib': sc.RedirectRefused(moved),
                               moved: (200, {'full_name': 'new/lib', 'default_branch': 'main', 'created_at': '2015-01-01T00:00:00Z'})})
        self.stub(tr)
        g = sc.GitHubRepo(sc.CodeClient(cache_dir=None))
        x = g.info('old/lib')
        self.assertEqual(x['repo'], 'new/lib'); self.assertIn('new/lib', g.extra['repository_moved'])
        tr2 = GitHub({}, extra={sc.GH['api'] + 'repos/old/lib': sc.RedirectRefused('https://evil.example.org/repos/new/lib')})
        self.stub(tr2)
        with self.assertRaises(ValueError) as e: sc.GitHubRepo(sc.CodeClient(cache_dir=None)).info('old/lib')
        self.assertEqual(str(e.exception), 'redirect_refused'); self.assertEqual(len(tr2.urls), 1)

    def test_raw_file_read_under_the_new_name(self):
        moved = sc.GH['api'] + 'repositories/42'
        tr = GitHub({}, extra={sc.GH['raw'] + f'old/lib/{SHA}/a.py': sc.RedirectRefused(sc.GH['raw'] + f'new/lib/{SHA}/a.py'),
                               sc.GH['api'] + 'repos/old/lib': sc.RedirectRefused(moved),
                               moved: (200, {'full_name': 'new/lib', 'default_branch': 'main', 'created_at': '2015-01-01T00:00:00Z'}),
                               sc.GH['raw'] + f'new/lib/{SHA}/a.py': (200, b'x = 1\n')})
        self.stub(tr)
        f = sc.GitHubRepo(sc.CodeClient(cache_dir=None)).file('old/lib', SHA, 'a.py')
        self.assertEqual(f['text'], 'x = 1\n'); self.assertIn('/new/lib/blob/', f['permanent_url'])


# ---------------------------------------------------------------------------------------------------- 3b 1a: finish_run runs the code checks
class FinishRunCodeChecks_3b_1a(Env):
    def setUp(self):
        super().setUp()
        import finish_run as F
        self.F = F
        self.run = self.d / 'run'; self.run.mkdir()
        (self.run / 'scope.md').write_text('# scope\n\n## Expected verdict scale\nGO if seam + licence; WATCH if ...; NO-GO if ...\n')
        (self.run / 'capsule.md').write_text('# capsule\n- reviewed_by_owner: no (built by engine; the report is labelled "capsule not reviewed")\n')
        (self.run / 'card.json').write_text(json.dumps({'claims': [{'id': 'c1', 'text': 'o/lib is under the MIT licence.', 'source': {'key': '1'}}],
                                                        'sources': {'1': {'code': f'repo:o/lib/src/a.py@{SHA}'}}}))
        self.mechs = [{'mechanism': 'retry', 'y_side': f'src/a.py:1@{SHA}', 'x_seam': f'core/x.py:3@{SHA[:12]}', 'verdict': 'GO (seam exists)', 'licence': 'copy allowed, MIT'},
                      {'mechanism': 'cache', 'y_side': f'src/b.py:1@{SHA}', 'x_seam': 'absent', 'verdict': 'GO', 'licence': 'copy allowed, MIT'},
                      {'mechanism': 'log', 'y_side': f'src/c.py:1@{SHA}', 'x_seam': 'absent', 'verdict': 'NO-GO', 'licence': 'MIT'}]
        (self.run / 'mechanisms.json').write_text(json.dumps(self.mechs))

    def test_guards(self):
        facts = {'facts': [{'type': 'licence', 'claimed': 'MIT', 'status': 'CONFIRMED', 'where': ['card.json:claims.c1', 'mechanisms.json:[0].licence', 'mechanisms.json:[1].licence']}]}
        g = self.F.code_guards(self.run, facts, {'refs': []})
        self.assertEqual((g['go'], g['go_capped']), (2, 1))                  # NO-GO is not a GO
        self.assertEqual(g['mechanisms'][0]['caps'], [])
        self.assertIn('seam missing', g['mechanisms'][1]['caps'][0])
        self.assertTrue(any('capsule not reviewed' in x for x in g['labels']))
        refs = {'refs': [{'path': 'core/x.py', 'sha': SHA, 'status': 'failed'}]}
        g = self.F.code_guards(self.run, dict(facts, facts=[dict(facts['facts'][0], status='UNCHECKABLE', reason_type='network')]), refs)
        self.assertTrue(any('rule 2' in c for c in g['mechanisms'][0]['caps']) and any('not found at the SHA' in c for c in g['mechanisms'][0]['caps']))
        (self.run / 'scope.md').write_text('# scope\nno scale here\n')
        g = self.F.code_guards(self.run, facts, {'refs': []})
        self.assertTrue(any('scope missing' in c for c in g['mechanisms'][0]['caps']))

    def test_steps_in_finish_offline(self):
        self.assertTrue(self.F.code_used(self.run, ['plugins/code.md']) and self.F.code_used(self.run, ()))
        steps, files = [], []
        step = lambda name, status, detail, out=(): (steps.append((name, status, detail)), files.extend(out))
        self.F.code_checks(self.run, T, True, step, files)
        names = [x[0] for x in steps]
        self.assertEqual(names, ['code_refs', 'code_facts', 'code_guards'])
        self.assertIn('offline: unchecked', steps[0][2])
        self.assertIn('UNCHECKABLE', steps[1][2])
        self.assertEqual(steps[2][1], 'problems')                            # offline: no licence confirmed, every GO capped
        for f in ('code-refs.json', 'code-facts.json', 'code-guards.json'): self.assertTrue((self.run / f).is_file(), f)


# ---------------------------------------------------------------------------------------------------- 2a 2b 2c 2d 2e: usage
class Usage_2a_2b_2c_2d(Env):
    ROOT = 'https://packages.ecosyste.ms/api/v1/registries/pypi.org/packages/searxng'

    def transport(self):
        pkg = {'purl': 'pkg:pypi/searxng', 'repository_url': 'https://github.com/danchev/searXNG', 'first_release_published_at': '2023-01-01T00:00:00Z',
               'dependent_packages_count': 2, 'dependent_repos_count': 0}
        vers = [{'number': '7.2.4', 'published_at': '2024-06-01T00:00:00Z'}, {'number': '8.0.0rc1', 'published_at': '2024-03-01T00:00:00Z'},
                {'number': '8.0.0', 'published_at': '2024-02-01T00:00:00Z'}, {'number': '7.2.3', 'published_at': '2023-12-01T00:00:00Z'}]
        deps = [{'name': 'old-user', 'repository_url': 'https://github.com/a/old', 'first_release_published_at': '2024-01-01T00:00:00Z'},
                {'name': 'late-user', 'repository_url': 'https://github.com/a/late', 'first_release_published_at': '2027-01-01T00:00:00Z'}]
        return GitHub({}, extra={self.ROOT + '/versions?': (200, vers), self.ROOT + '/dependent_packages?': (200, deps), self.ROOT: (200, pkg),
                                 sc.RM['ecosystems_repos']: (200, {'full_name': 'o/lib', 'license': 'agpl-3.0', 'created_at': '2015-01-01T00:00:00Z'})})

    def call(self, arg, **opt):
        g = gw.Gateway([str(CODE_PLUGIN)], T=T, run='r', state=self.d / 'st')
        return g.call('usage', arg, **opt)['results']

    def test_go_deep_module_accepted(self):
        self.assertTrue(__import__('re').fullmatch(sc.USAGE_FORM, 'go:github.com/aws/aws-sdk-go-v2/service/s3'))

    def test_namesake_dependents_highest(self):
        self.stub(self.transport())
        x = self.call('pypi:searxng', repo='searxng/searxng')
        self.assertIs(x['repo_mismatch'], True); self.assertIn('namesake', x['repo_mismatch_note'])
        self.assertEqual(x['latest_release_before_T']['number'], '7.2.4')
        self.assertEqual(x['highest_release_before_T']['number'], '8.0.0')
        self.assertIn('latest_note', x)
        pre = {v['number']: v['prerelease'] for v in [x['latest_release_before_T'], x['highest_release_before_T']]}
        self.assertEqual(pre, {'7.2.4': False, '8.0.0': False}); self.assertTrue(sc.is_prerelease('8.0.0rc1') and sc.is_prerelease('14.0.1-beta2'))
        d = x['dependents']
        self.assertEqual([p['name'] for p in d['packages']], ['old-user']); self.assertEqual(d['excluded_after_T_or_undated'], 1)
        self.assertIn('not established', d['caution'])

    def test_repository_licence_canonical(self):
        self.stub(self.transport())
        x = self.call('repo:o/lib')
        self.assertEqual((x['licence'], x['licence_spdx']), ('agpl-3.0', 'AGPL-3.0'))


# ---------------------------------------------------------------------------------------------------- 4a 4b 4c 4d: paper-code
class PaperCode_4a_4b_4c_4d(Env):
    HEAD = 'b' * 40

    def transport(self, paper, models, created='2015-01-01T00:00:00Z'):
        hf = 'https://huggingface.co/api/'
        gh = GitHub({self.HEAD: '2026-09-15T10:00:00Z'}, head=self.HEAD, extra={
            hf + 'papers/': (200, paper), hf + 'models?': (200, models), hf + 'datasets?': (200, []), hf + 'spaces?': (200, []),
            sc.GH['api'] + 'repos/o/lib$': (200, {'full_name': 'o/lib', 'default_branch': 'main', 'created_at': created})})
        return gh

    def call(self, arxiv, T_='2026-10-01'):
        g = gw.Gateway([str(CODE_PLUGIN)], T=T_, run='r', state=self.d / ('st' + T_))
        return g.call('paper-code', arxiv)

    def test_github_repo_dated_on_github_not_by_the_paper(self):
        paper = {'publishedAt': '2026-09-20T00:00:00.000Z', 'githubRepo': 'https://github.com/o/lib', 'githubStars': 12}
        self.stub(self.transport(paper, []))
        r = self.call('2609.05881')['results']['repos'][0]
        self.assertEqual((r['sha'], r['date'], r['stars_as_of']), (self.HEAD, '2026-09-15T10:00:00Z', 'now (not as of T)'))
        self.assertIn('repo-head', r['dating'])

    def test_github_repo_created_after_T_refused(self):
        paper = {'publishedAt': '2026-09-20T00:00:00.000Z', 'githubRepo': 'https://github.com/o/lib'}
        self.stub(self.transport(paper, [], created='2026-10-05T00:00:00Z'))
        x = self.call('2609.05881')['results']
        self.assertEqual(x['repos'], []); self.assertIn('created on/after T', x['repos_refused'][0]['refusal'])

    def test_empty_github_repo_said(self):
        self.stub(self.transport({'publishedAt': '2026-09-20T00:00:00.000Z'}, []))
        x = self.call('2609.05881')['results']
        self.assertIn('not established', x['repos_note'])

    def test_models_dated_by_creation_and_paper_by_earliest_bound(self):
        models = [{'id': 'o/official', 'createdAt': '2026-09-21T00:00:00.000Z', 'lastModified': '2026-10-20T00:00:00.000Z', 'likes': 3, 'downloads': 9},
                  {'id': 'o/late', 'createdAt': '2026-10-03T00:00:00.000Z', 'lastModified': '2026-10-03T00:00:00.000Z'}]
        self.stub(self.transport({'publishedAt': '2026-10-25T00:00:00.000Z'}, models))   # HF date after T, arXiv id of September
        out = self.call('2609.05881')
        x = out['results']
        self.assertEqual((x['date'], x['date_arxiv_id_bound']), ('2026-09-30', '2026-09-30')); self.assertIn('later than the month', x['date_note'])
        self.assertEqual([m['id'] for m in x['models']], ['o/official'])        # modified after T, created before: kept
        self.assertIn('masked', x['models'][0]['metadata'])
        self.assertTrue(any('sort=downloads' in u and '/api/models?' in u for u in self.gh.urls))
        self.assertEqual(x['listing']['returned']['models'], 2)


if __name__ == "__main__":
    unittest.main()
