#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline tests of tools/check_code_refs.py (audit of 2026-10-31, section 6 item 4): the code references of REPORT.md, card.json and
mechanisms.json (fixtures in tests/fixtures/code_refs_run/) are found in every form (repo:, bare path with the repository of the same
bibliography entry or of the card's url field, local:, GitHub permalinks with their extra anchors, l.<a>-<b> ranges, <owner>/<name>@<SHA>),
merged per repository, file and commit, and checked mechanically: repository, commit of THAT repository, file at the commit, line bounds,
quoted fragments within the cited lines widened by k lines (config.json code_refs), licence. GitHub is a simulated engine (no network);
the host code X is a real small git repository read by `git show` (verifier/code_files.py). JSON output and exit codes of the command line.
Run: python3 -I tests/test_check_code_refs.py   (unittest; pytest-compatible)."""
import io, json, os, pathlib, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import check_code_refs as CR   # noqa: E402
import code_sources as sc      # noqa: E402

SHA = '4f2b9c0d1e3a5b7c9d0e1f2a3b4c5d6e7f8a9b0c'
RETRY = ('import time\n\n\ndef retry(f, tries=4, base=0.6):\n    """Call f, waiting base * 2**n seconds between attempts."""\n    for n in range(tries):\n'
         '        try:\n            return f()\n        except IOError:\n            time.sleep(base * 2 ** n)\n    raise RuntimeError(\'gave up\')\n')
WAIT = 'def wait_forever(step):\n    while True:\n        yield step\n'
GIT_ENV = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@t', 'GIT_AUTHOR_DATE': '2026-01-01T00:00:00Z', 'GIT_COMMITTER_DATE': '2026-01-01T00:00:00Z'}


class FakeGitHub:
    """Simulated github-repo engine (same methods as code_sources.GitHubRepo): repository o/lib at SHA, MIT."""
    def __init__(self, limited=False): self.limited, self.calls, self.extra = limited, [], {}
    def _rl(self, what):
        self.calls.append(what)
        if self.limited: raise ValueError('rate_limited')
    def rate(self): return {'limit': 60, 'remaining': 60, 'reset': 0}
    def info(self, repo):
        self._rl('info')
        if repo != 'o/lib': raise ValueError('provider_error:HTTP404')
        return {'repo': repo, 'default_branch': 'main'}
    def resolve(self, repo, sha):
        self._rl('commit')
        if repo != 'o/lib' or not SHA.startswith(sha): raise ValueError('commit_not_in_repository')
        return {'sha': SHA, 'date': '2026-01-01T00:00:00Z', 'membership': 'in the default branch history', 'in_default_branch': True}
    def licence(self, repo, ref=None): self._rl('licence'); return {'spdx': 'MIT', 'path': 'LICENSE', 'ref': ref}
    def file(self, repo, sha, path):
        self.calls.append('raw')
        files = {'src/retry.py': RETRY, 'src/wait.py': WAIT}
        if repo != 'o/lib' or sha != SHA or path not in files: raise ValueError('file_not_found')
        return {'text': files[path], 'permanent_url': sc.GH['web'] + f'o/lib/blob/{sha}/{path}'}


class CheckCodeRefs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name) / 'run'
        shutil.copytree(P / 'fixtures' / 'code_refs_run', self.d)       # outside any git work tree: no X found by parent discovery
        self.k0 = CR.K; CR.K = 3

    def tearDown(self):
        CR.K = self.k0; self.tmp.cleanup()

    def files(self): return [self.d / f for f in CR.DEFAULT_FILES]

    def test_window_from_config(self):
        cfg = json.loads((P.parent / 'tools' / 'config.json').read_text(encoding='utf-8'))['code_refs']
        self.assertEqual((self.k0, CR.MIN_CHARS), (cfg['snippet_window_lines'], cfg['snippet_min_chars']))

    def test_extract_forms(self):
        e = CR.extract(self.d / 'REPORT.md')
        forms = {(o['form'], o['repo'], o['path'], o['sha']) for o in e['refs']}
        self.assertIn(('bare', 'o/lib', 'src/retry.py', '4f2b9c0d'), forms, 'bare path: repository of the permalink of the same entry')
        self.assertIn(('permalink', 'o/lib', 'src/retry.py', SHA), forms)
        self.assertIn(('local', None, 'tools/x.py', '0123abcd'), forms)
        link = next(o for o in e['refs'] if o['form'] == 'permalink' and o['path'] == 'src/retry.py')
        self.assertEqual(link['ranges'], [(4, 6), (11, 11)], 'the extra anchor " ; #L11" belongs to the same file')
        bare = next(o for o in e['refs'] if o['form'] == 'bare' and o['path'] == 'src/retry.py')
        self.assertEqual(bare['ranges'], [(4, 4), (4, 6)], ':4 and l.4-6')
        c = CR.extract(self.d / 'card.json')
        self.assertIn(('bare', 'o/lib', 'src/retry.py', 'deadbee'), {(o['form'], o['repo'], o['path'], o['sha']) for o in c['refs']}, "card url field names the repository")
        m = CR.extract(self.d / 'mechanisms.json')
        self.assertEqual([(o['form'], o['repo'], o['ranges']) for o in m['refs']], [('repo', 'o/lib', [(4, 6)])])
        self.assertEqual([s['fragment'] for s in m['snippets']], ['time.sleep(base * 2 ** n)'])

    def test_check_statuses_and_snippets(self):
        gh = FakeGitHub(); rep = CR.check(self.files(), run_dir=self.d, gh=gh)
        by = {(r['repo'], r['path'], r['sha'][:7]): r for r in rep['refs']}
        r1 = by[('o/lib', 'src/retry.py', SHA[:7])]
        self.assertEqual((r1['status'], r1['sha'], r1['sha_full'], r1['id']), ('verified', SHA, SHA, f'repo:o/lib/src/retry.py@{SHA}'))
        self.assertEqual(r1['checks']['lines'], {'status': 'in_bounds', 'lines_in_file': 11})
        self.assertEqual(r1['checks']['licence'], {'status': 'ok', 'spdx': 'MIT', 'path': 'LICENSE'})
        self.assertEqual(len(r1['occurrences']), 4, 'REPORT bare + permalink, card S1, mechanisms: one reference')
        self.assertEqual(by[('o/lib', None, SHA[:7])]['status'], 'verified', 'o/lib@4f2b9c0d: commit only')
        w = by[('o/lib', 'src/wait.py', SHA[:7])]
        self.assertEqual((w['status'], w['failed'], w['checks']['lines']['out_of_bounds']), ('failed', ['lines'], [[40, 40]]))
        self.assertEqual((by[('o/lib', 'src/absent.py', SHA[:7])]['status'], by[('o/lib', 'src/absent.py', SHA[:7])]['failed']), ('failed', ['file']))
        other = by[('o/lib', 'src/retry.py', 'deadbee')]
        self.assertEqual((other['status'], other['checks']['commit']['status']), ('failed', 'absent'), 'a commit unknown to the named repository')
        ghost = by[('ghost/none', 'a.py', SHA[:7])]
        self.assertEqual((ghost['status'], ghost['failed']), ('failed', ['repository']))
        x = by[(None, 'tools/x.py', '0123abc')]
        self.assertEqual(x['status'], 'unchecked'); self.assertIn('local (X) reference', x['checks']['commit']['reason'])
        sn = {s['fragment']: s['status'] for s in rep['snippets']}
        self.assertEqual(sn, {'base * 2**n seconds between attempts': 'found', "raise RuntimeError('gave up')": 'found',
                              'a sentence that is not in the file': 'not_found', 'def wait_forever(step)': 'found_outside_cited_lines',
                              'def call_with_retry(fn)': 'unchecked', 'time.sleep(base * 2 ** n)': 'found_outside_cited_lines'})
        self.assertEqual(rep['summary'], {'references': 7, 'verified': 2, 'failed': 4, 'unchecked': 1, 'snippets': 6, 'snippets_found': 2,
                                          'snippets_outside_cited_lines': 2, 'snippets_not_found': 1, 'snippets_unchecked': 1,
                                          'refs_with_lines': 4, 'refs_with_prose_lines': 0, 'prose_lines_unattached': 0})
        self.assertEqual(rep['licences'], {'o/lib': {SHA: {'spdx': 'MIT', 'path': 'LICENSE'}}})
        self.assertEqual(CR.exit_code(rep), 1)
        self.assertEqual(gh.calls.count('info'), 2, 'memoised per repository (o/lib, ghost/none)')
        CR.K = 4                                                          # line 10 is within 4..6 widened by 4: found
        self.assertEqual({s['fragment']: s['status'] for s in CR.check([self.d / 'mechanisms.json'], gh=FakeGitHub())['snippets']},
                         {'time.sleep(base * 2 ** n)': 'found'})

    def test_unchecked_without_repository_rate_limit_and_strict(self):
        f = self.d / 'bare.json'; f.write_text(json.dumps([{'y_side': 'src/retry.py:4@' + SHA}]))
        rep = CR.check([f], gh=FakeGitHub())
        self.assertEqual(rep['refs'][0]['status'], 'unchecked'); self.assertIn('no repository named', rep['refs'][0]['checks']['repository']['reason'])
        self.assertEqual((CR.exit_code(rep), CR.exit_code(rep, strict=True)), (0, 1))
        rep = CR.check([f], repo='o/lib', gh=FakeGitHub())
        self.assertEqual((rep['refs'][0]['status'], rep['refs'][0]['repo_from']), ('verified', 'default'))
        gh = FakeGitHub(limited=True); rep = CR.check([f], repo='o/lib', gh=gh)
        r = rep['refs'][0]
        self.assertEqual((r['checks']['repository']['status'], r['checks']['commit']['status'], r['checks']['file']['status']), ('unchecked', 'unchecked', 'ok'),
                         'rate limited: the API checks are unchecked, the raw read of a full SHA goes on')
        self.assertEqual(r['status'], 'unchecked')
        short = self.d / 'short.json'; short.write_text(json.dumps([{'y_side': 'repo:o/lib/src/retry.py@4f2b9c0d'}]))
        r = CR.check([short], gh=FakeGitHub(limited=True))['refs'][0]
        self.assertEqual(r['checks']['file'], {'status': 'unchecked', 'reason': 'abbreviated SHA not resolved'})
        amb = self.d / 'amb.json'; amb.write_text(json.dumps([{'x': 'src/retry.py@deadbee'}]))
        r = CR.check([amb], repo='o/lib', gh=FakeGitHub())['refs'][0]
        self.assertEqual((r['status'], r['checks']['commit']['status']), ('unchecked', 'unchecked'), 'a bare path is ambiguous: not failed on the default repository')
        self.assertIn('names no repository', r['checks']['commit']['reason'])
        both = self.d / 'both.json'; both.write_text(json.dumps([{'x': 'tools/x.py:3@0123abcd, local source local:tools/x.py@0123abcd'}]))
        rs = CR.check([both], repo='o/lib', gh=FakeGitHub())['refs']
        self.assertEqual([(r['side'], r['path']) for r in rs], [('X', 'tools/x.py')], 'a bare path also cited local: is host code X')
        r = CR.check([short], gh=None)['refs'][0]
        self.assertEqual((r['status'], r['checks']['repository']['reason']), ('unchecked', 'offline (no GitHub check)'))

    def test_local_x_reference_read_by_git_show(self):
        x = pathlib.Path(self.tmp.name) / 'x'; (x / 'tools').mkdir(parents=True)
        run = lambda *a: subprocess.run(['git', '-C', str(x), *a], env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True).stdout.strip()
        run('init', '-q'); (x / 'tools' / 'x.py').write_text('a\nb\ndef call_with_retry(fn):\n    return fn()\n'); run('add', '-A'); run('commit', '-q', '-m', 'x')
        head = run('rev-parse', 'HEAD')
        rep_md = self.d / 'REPORT.md'; rep_md.write_text(rep_md.read_text().replace('0123abcd', head[:8]))
        rep = CR.check([rep_md], run_dir=self.d, x_repos=[str(x)], gh=FakeGitHub())
        r = next(r for r in rep['refs'] if r['side'] == 'X')
        self.assertEqual((r['status'], r['sha_full'], r['checks']['lines']['status']), ('verified', head, 'in_bounds'))
        self.assertEqual(next(s['status'] for s in rep['snippets'] if s['fragment'] == 'def call_with_retry(fn)'), 'found')
        sub = pathlib.Path(self.tmp.name) / 'w'; (sub / 'skill' / 'tools').mkdir(parents=True)     # X = a subtree of its git directory
        run2 = lambda *a: subprocess.run(['git', '-C', str(sub), *a], env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True).stdout.strip()
        run2('init', '-q'); (sub / 'skill' / 'tools' / 'x.py').write_text('a\nb\nc\n'); run2('add', '-A'); run2('commit', '-q', '-m', 'w')
        h2 = run2('rev-parse', 'HEAD'); f = self.d / 'x.json'; f.write_text(json.dumps([{'x_seam': f'local:tools/x.py:3@{h2}'}]))
        self.assertEqual(CR.check([f], x_repos=[str(sub)], gh=None)['refs'][0]['status'], 'failed', 'path not at the root of the git directory')
        self.assertEqual(CR.check([f], x_repos=[str(sub)], gh=None, x_prefixes=['skill/'])['refs'][0]['status'], 'verified')

    def test_command_line(self):
        out = io.StringIO()
        with redirect_stdout(out): rc = CR.main([str(self.d), '--offline'])
        rep = json.loads(out.getvalue())
        self.assertEqual((rc, rep['summary']['failed'], rep['summary']['unchecked'], rep['summary']['verified']), (0, 0, 7, 0),
                         'offline: nothing can be shown absent, everything stays unchecked (exit 0 without --strict)')
        self.assertEqual(rep['files'], [str(self.d / f) for f in CR.DEFAULT_FILES])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(CR.main([str(self.d), '--offline', '--strict']), 1)
        err = io.StringIO()
        with redirect_stderr(err): self.assertEqual(CR.main([str(self.d / 'nope')]), 2); self.assertEqual(CR.main([]), 2)
        with redirect_stderr(err): self.assertEqual(CR.main([str(self.d), '--repo', 'bad repo']), 2)



class GitLineNumbers(unittest.TestCase):
    """Security review of 2026-10-31, item 4: line numbers as git and GitHub count them (\\n only). str.splitlines also split on \\f
    (common in C and Python sources), a lone \\r, \\x1c-\\x1e, \\x85: false out_of_bounds and a shifted snippet window."""
    def test_line_bounds_and_window(self):
        text = 'L1\nL2 a\x0cb\n' + ''.join(f'L{i}\n' for i in range(3, 21))
        self.assertEqual(len(CR.cf.git_lines(text)), 20)
        self.assertEqual(CR.cf.line_check({'line': 21}, text)['status'], 'out_of_bounds')
        self.assertEqual(CR.cf.line_check({'line': 3}, 'a\x0cb\nc\n'), {'line': 3, 'end': 3, 'lines_in_file': 2, 'status': 'out_of_bounds'})
        self.assertEqual(CR.cf.git_lines('a\r\nb\r\n'), ['a', 'b'])
        w = CR._window(text, [(16, 16)]).split()
        self.assertEqual((w[0], w[-1]), ('L%d' % (16 - CR.K), 'L%d' % (16 + CR.K)))
        r = {'side': 'X', 'path': 'f.c', 'sha': SHA, 'ranges': [[20, 20]], 'kind': 'file', 'repo': None}
        class Ck:
            def local(self, path, sha, x=False): return text, {'commit': SHA, 'repo': 'x'}
        CR._check_ref(r, Ck())
        self.assertEqual((r['checks']['lines'], r['status']), ({'status': 'in_bounds', 'lines_in_file': 20}, 'verified'))
        r = dict(r, ranges=[[21, 21]]); CR._check_ref(r, Ck())
        self.assertEqual((r['checks']['lines']['status'], r['failed']), ('out_of_bounds', ['lines']))


if __name__ == '__main__':
    unittest.main()
