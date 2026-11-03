#!/usr/bin/env python3
"""Offline tests of the `relocated` / `ambiguous` statuses of tools/check_code_refs.py: a cited file absent at the commit whose NAME exists in the
tree of the commit (path cut to the file name, wrong directory, doubled prefix). One candidate -> relocated (resolved_path, lines checked on it),
several -> ambiguous (candidates), none -> failed as before. The report is never rewritten. Minimal doubles, no network.
Run: python3 -I tests/test_check_relocated.py   (unittest; pytest-compatible)."""
import json, pathlib, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(P.parent / 'tools'))
import check_code_refs as CR   # noqa: E402

SHA = '4f2b9c0d1e3a5b7c9d0e1f2a3b4c5d6e7f8a9b0c'
FILES = {'doctor/tasks.py': 'a\nb\nc\n', 'src/exporter/builder.rs': 'x\ny\n', 'lib/util.py': '1\n2\n', 'test/util.py': '1\n', 'pkg/ok.py': 'k\n'}


class Tree:
    """GitHub engine double over FILES; `cut` makes the tree list truncated."""
    def __init__(self, cut=False, no_same_name=False):
        self.extra, self.cut = {}, cut
        if no_same_name: self.same_name = None
    def rate(self): return None
    def info(self, repo): return {'repo': repo, 'default_branch': 'main'}
    def resolve(self, repo, sha): return {'sha': SHA, 'date': '2026-01-01T00:00:00Z', 'membership': 'm', 'in_default_branch': True}
    def licence(self, repo, ref=None): return {'spdx': 'MIT', 'path': 'LICENSE'}
    def file(self, repo, sha, path):
        if path in FILES: return {'text': FILES[path], 'permanent_url': 'u/' + path}
        raise ValueError('file_not_found')
    def tree(self, repo, sha, prefix=''):
        ps = [p for p in FILES if p.startswith(prefix.rstrip('/') + '/')]
        return {'paths': ps, 'count': len(ps), 'truncated': False}
    def same_name(self, repo, sha, name):
        ps = [p for p in FILES if p.rsplit('/', 1)[-1] == name]
        return {'paths': ps, 'count': len(ps), 'truncated': self.cut}


class Relocated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)

    def tearDown(self): self.tmp.cleanup()

    def run_refs(self, *refs, gh=None):
        f = self.d / 'm.json'; f.write_text(json.dumps([{'a': ' ; '.join(f'repo:o/lib/{r}@{SHA}' for r in refs)}]), encoding='utf-8')
        rep = CR.check([f], gh=gh or Tree())
        return rep, {r['path']: r for r in rep['refs']}

    def test_the_three_observed_defects_are_relocated(self):
        rep, by = self.run_refs('tasks.py:2', 'src/builder.rs:1-2', 'doctor/doctor/tasks.py:3')
        for path, want in (('tasks.py', 'doctor/tasks.py'), ('src/builder.rs', 'src/exporter/builder.rs'), ('doctor/doctor/tasks.py', 'doctor/tasks.py')):
            r = by[path]
            self.assertEqual((r['status'], r['resolved_path'], r['checks']['file']['status']), ('relocated', want, 'relocated'), path)
            self.assertEqual(r['checks']['lines']['status'], 'in_bounds', 'lines are checked on the resolved file')
            self.assertEqual(r['path'], path, 'the cited path is kept as written: the report is not rewritten')
        self.assertEqual((rep['summary']['relocated'], rep['summary']['failed'], rep['summary']['verified']), (3, 0, 0))
        self.assertEqual(CR.exit_code(rep), 0, 'relocated is not a failure')

    def test_lines_out_of_bounds_on_the_resolved_file_stay_relocated(self):
        rep, by = self.run_refs('tasks.py:9')
        r = by['tasks.py']
        self.assertEqual((r['status'], r['checks']['lines']['status'], r['checks']['lines']['lines_in_file']), ('relocated', 'out_of_bounds', 3))

    def test_several_files_of_that_name_are_ambiguous(self):
        rep, by = self.run_refs('util.py:1')
        r = by['util.py']
        self.assertEqual((r['status'], r['candidates']), ('ambiguous', ['lib/util.py', 'test/util.py']))
        self.assertNotIn('lines', r['checks'], 'no line is checked on a guess')
        self.assertEqual((rep['summary']['ambiguous'], rep['summary']['failed']), (1, 0))

    def test_no_file_of_that_name_is_still_a_failure(self):
        rep, by = self.run_refs('nothing.py:1')
        self.assertEqual((by['nothing.py']['status'], by['nothing.py']['why']), ('failed', 'file_absent'))
        self.assertNotIn('relocated', rep['summary']); self.assertNotIn('ambiguous', rep['summary'])
        self.assertEqual(CR.exit_code(rep), 1)

    def test_truncated_tree_or_no_engine_keeps_the_failure(self):
        for gh in (Tree(cut=True), Tree(no_same_name=True)):
            r = self.run_refs('tasks.py:1', gh=gh)[1]['tasks.py']
            self.assertEqual((r['status'], r['why']), ('failed', 'file_absent'))

    def test_existing_statuses_unchanged(self):
        rep, by = self.run_refs('pkg/ok.py:1', 'pkg:1')
        self.assertEqual(by['pkg/ok.py']['status'], 'verified')
        self.assertEqual(by['pkg']['status'], 'directory')


if __name__ == '__main__':
    unittest.main()
