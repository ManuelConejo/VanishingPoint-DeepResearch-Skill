#!/usr/bin/env python3
"""Offline tests of the fixes to tools/check_code_refs.py and tools/check_code_facts.py found by the pass over 44 real code-plugin reports
(2026-11-01): a bibliography year read as a cited line, lines of ANOTHER file attached to the only reference of an entry, a failure without a
typed `why`, a directory cited as a file, an unreadable file counted as failed, a "GitHub reports NOASSERTION" note read as the asserted
licence, an `owner/name` plainly named in the subject of a fact but unknown to the sources (no_target). Minimal fixtures, no network.
Run: python3 -I tests/test_check_verif_fixes.py   (unittest; pytest-compatible)."""
import datetime, json, os, pathlib, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import check_code_refs as CR   # noqa: E402
import check_code_facts as F   # noqa: E402

SHA = '4f2b9c0d1e3a5b7c9d0e1f2a3b4c5d6e7f8a9b0c'
GIT_ENV = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@t', 'GIT_AUTHOR_DATE': '2026-01-01T00:00:00Z', 'GIT_COMMITTER_DATE': '2026-01-01T00:00:00Z'}
WHY_FAILED = {'repository_absent', 'commit_not_in_repository', 'file_absent', 'lines_out_of_bounds'}


class Fake:
    """GitHub engine double for o/lib: files src/a.py (3 lines) and a directory pkg/ ; `tree_error` makes the tree read fail."""
    def __init__(self, tree_error=None, tree=True):
        self.extra, self.tree_error = {}, tree_error
        if not tree: self.tree = None
    def rate(self): return None
    def info(self, repo): return {'repo': repo, 'default_branch': 'main'}
    def resolve(self, repo, sha): return {'sha': SHA, 'date': '2026-01-01T00:00:00Z', 'membership': 'm', 'in_default_branch': True}
    def licence(self, repo, ref=None): return {'spdx': 'MIT', 'path': 'LICENSE'}
    def file(self, repo, sha, path):
        if path == 'src/a.py': return {'text': 'a\nb\nc\n', 'permanent_url': 'u'}
        raise ValueError('file_not_found')
    def tree(self, repo, sha, prefix=''):
        if self.tree_error: raise ValueError(self.tree_error)
        return {'paths': ['pkg/x.py'] if prefix.rstrip('/') == 'pkg' else [], 'count': 1 if prefix.rstrip('/') == 'pkg' else 0, 'truncated': False}


class Refs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)

    def tearDown(self): self.tmp.cleanup()

    def md(self, text):
        p = self.d / 'REPORT.md'; p.write_text(text, encoding='utf-8'); return p

    def test_bibliography_year_is_not_a_line(self):
        e = CR.extract(self.md(f'[1] o/lib, src/a.py lines 1-2, 2025, local:src/a.py@{SHA}, basis abstract\n'
                               f'[2] o/lib, src/b.py lines 7 and 9, 2026, local:src/b.py@{SHA}\n[3] o/lib, src/c.py lines 12, 2150, local:src/c.py@{SHA}\n'
                               f'[4] kin. src/d.py, lines 8 and 16-76, 2026. local:src/d.py@{SHA}. Basis read.\n'))
        self.assertEqual([o['ranges'] for o in e['refs']], [[(1, 2)], [(7, 7), (9, 9)], [(12, 12), (2150, 2150)], [(8, 8), (16, 76)]],
                         'a year after a comma is not a line (1900-2099 only, not a range); "and" lists and other numbers are kept')

    def test_lines_of_another_file_are_not_attached(self):
        e = CR.extract(self.md(f'[10] o/lib, docs/files.mdx lines 78-98 and docs/api/message.mdx lines 177 and 288, at {SHA}, repo:o/lib/docs/files.mdx@{SHA}\n'))
        self.assertEqual(e['refs'][0]['ranges'], [(78, 98)])
        self.assertEqual(e['refs'][0].get('prose_unattached'), 1, 'lines named after another file are counted, not guessed')
        e = CR.extract(self.md(f'[11] o/lib, README.md lines 3-5, repo:o/lib/README.md@{SHA}\n'))
        self.assertEqual(e['refs'][0]['ranges'], [(3, 5)], 'the same file named before the lines: attached')

    def test_repository_stated_by_the_entry(self):
        e = CR.extract(self.md(f'[2] zpao/lib, package.json, 2025, code: package.json@{SHA} (repo zpao/lib), basis abstract\n'
                               f'[5] tldraw/app, src/q.ts line 2, 2025, code: src/q.ts@{SHA}, basis abstract\n'
                               f'[6] a bare entry, 2025, code: src/z.ts@{SHA}\n'
                               f'[7] p/q, x.ts, 2025, code: x.ts@{SHA} (repo r/one) and y.ts@{SHA} (repo r/two)\n'))
        self.assertEqual([(o['path'], o['repo']) for o in e['refs']],
                         [('package.json', 'zpao/lib'), ('src/q.ts', 'tldraw/app'), ('src/z.ts', None), ('x.ts', None), ('y.ts', None)],
                         'an explicit "(repo owner/name)" or the entry\'s opening "owner/name," names the repository; ambiguous or absent: none')
        c = self.d / 'card.json'
        c.write_text(json.dumps({'sources': {'S1': {'code': f'package.json@{SHA}', 'title': 'zpao/lib, package.json'}, 'S2': {'code': f'a.txt@{SHA}', 'title': 'npm page'}}}))
        self.assertEqual([(o['path'], o['repo']) for o in CR.extract(c)['refs']], [('package.json', 'zpao/lib'), ('a.txt', None)])

    def test_repo_info_is_a_repository_record_not_a_file(self):
        f = self.d / 'm.json'
        f.write_text(json.dumps([{'a': f'repo-info/o/lib@{SHA}', 'b': f'repo:o/lib/repo-info@{SHA}', 'c': f'repo-info/ghost/none@{SHA}'}]))
        class G(Fake):
            def info(self, repo):
                if repo != 'o/lib': raise ValueError('provider_error:HTTP404')
                return super().info(repo)
        rep = CR.check([f], gh=G())
        by = {r['id']: r for r in rep['refs']}
        self.assertEqual({r['kind'] for r in rep['refs']}, {'commit'})
        self.assertEqual(sorted((r['repo'], r['status']) for r in rep['refs']), [('ghost/none', 'failed'), ('o/lib', 'verified')],
                         'the pseudo path repo-info[/owner/name] checks the repository and the commit; same record = one reference')

    def test_every_failure_has_a_typed_why(self):
        f = self.d / 'm.json'
        f.write_text(json.dumps([{'a': f'repo:o/lib/src/a.py:9@{SHA}', 'b': f'repo:o/lib/src/zz.py@{SHA}', 'c': f'repo:ghost/none/a.py@{SHA}'}]))
        class Ghost(Fake):
            def info(self, repo):
                if repo != 'o/lib': raise ValueError('provider_error:HTTP404')
                return super().info(repo)
        rep = CR.check([f], gh=Ghost(tree=False))
        failed = [r for r in rep['refs'] if r['status'] == 'failed']
        self.assertEqual(len(failed), 3)
        self.assertEqual(sorted(r['why'] for r in failed), ['file_absent', 'lines_out_of_bounds', 'repository_absent'])
        self.assertTrue(all(r['why'] in WHY_FAILED and r.get('why_detail') for r in failed))

    def test_unchecked_has_a_typed_why(self):
        f = self.d / 'm.json'; f.write_text(json.dumps([{'a': f'repo:o/lib/src/a.py:1@{SHA}'}]))
        class Limited(Fake):
            def info(self, repo): raise ValueError('rate_limited')
            def resolve(self, repo, sha): raise ValueError('rate_limited')
            def licence(self, repo, ref=None): raise ValueError('rate_limited')
        r = CR.check([f], gh=Limited())['refs'][0]
        self.assertEqual((r['status'], r['why']), ('unchecked', 'rate_limited'))
        r = CR.check([f], gh=None)['refs'][0]
        self.assertEqual((r['status'], r['why']), ('unchecked', 'offline'))
        g = self.d / 'n.json'; g.write_text(json.dumps([{'a': f'src/a.py:1@{SHA}'}]))
        r = CR.check([g], gh=Fake())['refs'][0]
        self.assertEqual((r['status'], r['why']), ('unchecked', 'no_repository_named'))
        self.assertEqual(CR.check([f], gh=Fake())['refs'][0].get('why'), None, 'verified: no why')

    def test_directory_cited_as_a_file(self):
        f = self.d / 'm.json'; f.write_text(json.dumps([{'a': f'repo:o/lib/pkg@{SHA}'}]))
        rep = CR.check([f], gh=Fake())
        r = next(r for r in rep['refs'] if r['path'] == 'pkg')
        self.assertEqual((r['status'], r['checks']['file']['status']), ('directory', 'directory'))
        self.assertEqual((rep['summary']['directory'], rep['summary']['failed']), (1, 0))
        self.assertEqual(CR.exit_code(rep), 0, 'a directory is not a failure')
        g = self.d / 'z.json'; g.write_text(json.dumps([{'a': f'repo:o/lib/nothing@{SHA}'}]))
        r = CR.check([g], gh=Fake())['refs'][0]
        self.assertEqual((r['status'], r['why']), ('failed', 'file_absent'), 'the tree answers: nothing under that path')
        r = CR.check([g], gh=Fake(tree_error='rate_limited'))['refs'][0]
        self.assertEqual((r['status'], r['why']), ('unchecked', 'rate_limited'), 'file or directory undecided: never failed')

    def test_local_directory_and_unreadable_file(self):
        x = self.d / 'x'; (x / 'pkg').mkdir(parents=True)
        run = lambda *a: subprocess.run(['git', '-C', str(x), *a], env={**os.environ, **GIT_ENV}, check=True, capture_output=True, text=True).stdout.strip()
        run('init', '-q'); (x / 'pkg' / 'm.py').write_text('a\n'); (x / 'bin.dat').write_bytes(b'\0\1\2'); run('add', '-A'); run('commit', '-q', '-m', 'x')
        head = run('rev-parse', 'HEAD')
        f = self.d / 'm.json'; f.write_text(json.dumps([{'a': f'local:pkg@{head}', 'b': f'local:bin.dat@{head}', 'c': f'local:nothing.py@{head}',
                                                          'd': f'local:pkg/m.py:9@{head}'}]))
        rep = CR.check([f], x_repos=[str(x)], gh=None)
        by = {r['path']: r for r in rep['refs']}
        self.assertEqual((by['pkg']['status'], by['pkg']['checks']['file']['status']), ('directory', 'directory'))
        self.assertEqual((by['bin.dat']['status'], by['bin.dat']['why']), ('unchecked', 'file_unreadable'), 'a binary file is not read: unchecked, not failed')
        self.assertEqual((by['nothing.py']['status'], by['nothing.py']['why']), ('failed', 'file_absent'))
        self.assertEqual((by['pkg/m.py']['status'], by['pkg/m.py']['why']), ('failed', 'lines_out_of_bounds'))


class Facts(unittest.TestCase):
    def facts(self, text, kind='claim', known=(), src=None):
        f, _ = F._facts_of(text, 'w', F.Targets(set(known), None, None), src or {'side': 'Y', 'repo': 'o/y', 'sha': None}, kind=kind)
        return f

    def test_report_note_is_not_the_asserted_licence(self):
        t = 'BSD-3 (LICENSE.txt read at the SHA; GitHub reports NOASSERTION); compatible with the host'
        f = self.facts(t, kind='licence_field')
        self.assertEqual([x['claimed'] for x in f], ['BSD-3-Clause'], '"BSD-3" is BSD-3-Clause; "GitHub reports NOASSERTION" is a reading, not a claim')
        self.assertEqual([x['claimed'] for x in self.facts('Licence: NOASSERTION', kind='licence_field')], ['NOASSERTION'], 'a plain NOASSERTION claim stays')
        self.assertEqual([x['claimed'] for x in self.facts('MIT (GitHub reports Apache-2.0 for the docs)', kind='licence_field')], ['MIT'])
        self.assertEqual([x['claimed'] for x in self.facts('GitHub reports MIT', kind='licence_field')], ['MIT'], 'alone, it is still the licence stated')

    def test_named_repository_in_subject_position(self):
        for text, want in (('twbs/icons repository is MIT-licensed and not archived.', 'twbs/icons'), ('The twbs/icons repository is licensed MIT.', 'twbs/icons'),
                           ('The licence file of unovue/reka-ui at the pinned commit is the MIT licence.', 'unovue/reka-ui'),
                           ('Upstream dtolnay/serde-yaml is archived.', 'dtolnay/serde-yaml'), ('hashicorp/go-checkpoint has an MPL-2.0 licence.', 'hashicorp/go-checkpoint')):
            f = self.facts(text)
            self.assertTrue(f and all(x['repo'] == want and x['target_from'] in ('clause', 'text') for x in f), text)
        self.assertEqual({x['repo'] for x in self.facts('chompjs is MIT-licensed and turns objects into data (Python/C).', src={'side': 'Y', 'repo': None})}, {None},
                         'a slash in the middle of a sentence is not a repository')

    def test_no_false_attribution_in_licence_fields(self):
        """Contradictions that rate limiting had hidden (44 reports, 2026-11-01): every one was an extraction error."""
        tg = F.Targets({'o/inspector', 'o/host'}, None, 'o/host')
        src = {'side': 'Y', 'repo': None, 'sha': None}
        f, u = F._facts_of('copy allowed: MIT for @a and b; ISC for o/inspector (compatible with X)', 'w', tg, src, kind='licence_field')
        self.assertEqual([(x['claimed'], x['repo']) for x in f], [('ISC', 'o/inspector')], 'the MIT clause names no repository: not o/inspector')
        f, u = F._facts_of('async-openai MIT, genai MIT OR Apache-2.0, rig-core MIT; others compatible with host (MIT)', 'w', tg, src, kind='licence_field')
        self.assertEqual(f, [], 'several packages with their own licences: no expression, and the host (X) is not the subject')
        self.assertTrue(u and u[0]['why'] == 'several licences in one clause')
        f, u = F._facts_of('manifest "MIT OR Apache-2.0" (both files read), MIT option compatible with host MIT clause', 'w', tg, src, kind='licence_field')
        self.assertEqual([x['repo'] for x in f], [], 'X named by its name part in a licence field is the comparison, not the subject')
        f, _ = F._facts_of('MIT OR Apache-2.0 dual licence', 'w', tg, {'side': 'Y', 'repo': 'o/inspector', 'sha': None}, kind='licence_field')
        self.assertEqual([x['claimed'] for x in f], ['MIT OR Apache-2.0'], 'a real expression is kept')
        f, _ = F._facts_of('BSD-2-Clause, confirmed from the LICENSE file; licences of x/notify and y not read', 'w', F.Targets(set(), None, None), src, kind='licence_field')
        self.assertEqual([x['repo'] for x in f], [], 'an unknown owner/name in a licence field is never deduced as its subject')

    def test_other_extraction_errors_found_once_the_api_answered(self):
        tg = F.Targets({'o/known'}, None, None)
        src = {'side': 'Y', 'repo': 'o/known', 'sha': None}
        f, _ = F._facts_of('Radial needs o/known built from source; its last commit is 2025-11-11.', 'w', tg, {'side': 'Y', 'repo': None, 'sha': None})
        self.assertEqual([x for x in f if x['type'] == 'last_commit'], [], '"its last commit": the subject is not the repository named in the previous clause')
        f, _ = F._facts_of('`ng` (repository a/ng): MIT, a last commit on 2025-09-14', 'w', tg, {'side': 'Y', 'repo': None, 'sha': None}, kind='prose')
        self.assertEqual(f, [], 'a clause that names another repository is not about the known one')
        f, _ = F._facts_of('o/known is MIT-licensed, a last commit on 2025-09-14', 'w', tg, src)
        self.assertEqual({x['type'] for x in f}, {'licence', 'last_commit'}, 'the plain case stays')
        f, u = F._facts_of('Twemoji MIT and CC-BY-4.0 with attribution; Noto OFL-1.1', 'w', tg, src, kind='licence_field')
        self.assertEqual([x['claimed'] for x in f], ['OFL-1.1'], 'MIT and CC-BY-4.0 is not "MIT": CC-BY / OFL identifiers are in the vocabulary')
        self.assertEqual(u[0]['why'], 'several licences in one clause')
        self.assertEqual(len(F.SENTENCE.split('One thing. `x` is another.')), 2, 'a sentence may start with a code span')

    def test_cited_manifest_decides_the_licence(self):
        """B12: the crate cited declares "MIT AND Apache-2.0" in ITS Cargo.toml, the root manifest says MIT: confirmed, not contradicted."""
        files = {'sub/Cargo.toml': '[package]\nlicense = "MIT AND Apache-2.0"\n', 'sub/bad/Cargo.toml': '[package]\nlicense = "GPL-3.0-only"\n'}
        class GH:
            extra = {}
            def info(self, repo): return {'repo': repo, 'created_at': '2014-01-01T00:00:00Z', 'default_branch': 'm', 'archived': False}
            def resolve(self, repo, sha): return {'sha': SHA, 'date': '2023-01-20T00:00:00Z', 'in_default_branch': True}
            def barrier(self, repo, r, B, extra=None): return None
            def licence(self, repo, ref=None): return {'spdx': 'NOASSERTION', 'path': 'LICENSE'}
            def licence_read(self, repo, sha, detected=None): return {'status': 'read', 'expression': 'MIT', 'basis': 'manifest Cargo.toml', 'by_directory': []}
            def file(self, repo, sha, path):
                if path not in files: raise ValueError('file_not_found')
                return {'text': files[path]}
        for path, claimed, want in (('sub/Cargo.toml', 'MIT AND Apache-2.0', 'CONFIRMED'), ('sub/Cargo.toml', 'MIT', 'CONTRADICTED'),
                                    ('sub/bad/Cargo.toml', 'MIT', 'CONTRADICTED'), ('other/x.rs', 'MIT', 'CONFIRMED')):
            ob = F.Observer(GH(), None, datetime.date(2026, 1, 1))
            f = {'type': 'licence', 'claimed': claimed, 'repo': 'o/r', 'sha': SHA, 'paths': [path], 'where': ['w']}
            self.assertEqual(F._check_repo_fact(f, ob, datetime.date(2026, 1, 1), True)['status'], want, (path, claimed))

    def test_unknown_target_is_still_no_target(self):
        f = self.facts('qrcode.react is a component, licensed ISC.', src={'side': 'Y', 'repo': None, 'sha': None})
        self.assertEqual([x['repo'] for x in f], [None], 'a package name is not a repository: not deduced')


if __name__ == '__main__':
    unittest.main()
