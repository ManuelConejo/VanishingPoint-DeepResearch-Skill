#!/usr/bin/env python3
"""Offline tests of the repository-map selection (tools/repo_map.py, tools/condense_repo.py --selection repo-map, whole_reading --selection).

Synthetic repository only (no network, no model): a central file that is last in alphabetical order must be kept under the cap by the repo-map
and dropped by the default order; the output is deterministic; no file is truncated (each included file equals `git show` and its header counts
its git lines); the option is off by default; tags of the languages (ast for Python, regular expressions for the others); mentions of a run
directory; personalisation; the PageRank itself."""
import json, os, pathlib, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(P)); sys.path.insert(0, str(P / 'verifier'))
import condense_repo as cr, repo_map as rm  # noqa: E402
from code_files import git_lines  # noqa: E402

GIT_ENV = dict(GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t', GIT_CONFIG_GLOBAL='/dev/null', HOME='/nonexistent')


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, env={**os.environ, **GIT_ENV}).stdout.decode()


def filler(tag, n=30):
    return ''.join(f'# {tag} filler line {i} with some words to give the file a size\n' for i in range(n))


def make_repo(root):
    """aa_noise_*: unrelated files first in alphabetical order; mid_user_*: call the functions of zz_core.py; zz_core.py: central, last;
    lonely.py: defines `rare_feature_flag`, nobody references it."""
    files = {'README.md': '# Synthetic\n'}
    for i in range(6): files[f'aa_noise_{i}.py'] = f'def noise_{i}_unrelated(x):\n    return x + {i}\n' + filler(f'noise{i}')
    for i in range(6):
        files[f'mid_user_{i}.py'] = f'from zz_core import compute_totals, build_ledger\n\ndef user_{i}_entry(data):\n    return compute_totals(build_ledger(data))\n' + filler(f'user{i}')
    files['zz_core.py'] = ('def compute_totals(ledger):\n    return sum(ledger)\n\ndef build_ledger(data):\n    return list(data)\n\n' + filler('core'))
    files['lonely.py'] = 'def rare_feature_flag():\n    return True\n' + filler('lonely')
    files['src/app.js'] = 'export function startServer(port) { return port; }\n' + filler('js')
    for rel, text in files.items():
        f = root / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(text)
    git(root, 'init', '-q'); git(root, 'add', '-A'); git(root, 'commit', '-q', '-m', 'x')
    return git(root, 'rev-parse', 'HEAD').strip(), files


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        self.repo = self.d / 'y'; self.repo.mkdir(); self.sha, self.files = make_repo(self.repo)
        self.reader = cr.LocalRepo(str(self.repo))
        self.cap = sum(len(self.files[f]) for f in ('README.md', 'zz_core.py', 'mid_user_0.py', 'mid_user_1.py', 'mid_user_2.py')) + 50   # about 5 files

    def tearDown(self): self.tmp.cleanup()

    def kept(self, selection, mentions=None, cap=None, **kw):
        text, summary = cr.condense(self.reader, self.sha, 'y', cap or self.cap, selection=selection, mentions=mentions, **kw)
        return text, summary


class Selection(Base):
    def test_central_file_kept_by_repo_map_not_by_order(self):
        _, order = self.kept('order'); _, rmap = self.kept('repo-map')
        self.assertNotIn('zz_core.py', order['kept_paths'])                # alphabetical: the noise files fill the cap first
        self.assertIn('zz_core.py', rmap['kept_paths'])
        self.assertLessEqual(rmap['chars_files'], self.cap)
        self.assertEqual(rmap['repo_map']['files'], len(self.files))
        self.assertGreater(rmap['repo_map']['edges'], 0)

    def test_default_is_off(self):
        self.assertEqual(cr.DEFAULT_SELECTION, 'order')
        cfg = json.loads((P / 'config.json').read_text())['condense']
        self.assertEqual(cfg['selection'], 'order')
        t0, s0 = cr.condense(self.reader, self.sha, 'y', self.cap)
        t1, s1 = self.kept('order')
        self.assertEqual(t0, t1); self.assertEqual(s0['selection'], 'order'); self.assertIsNone(s0['repo_map'])

    def test_unknown_selection_refused(self):
        with self.assertRaises(SystemExit): self.kept('pagerank')

    def test_deterministic(self):
        a, sa = self.kept('repo-map'); b, sb = self.kept('repo-map')
        self.assertEqual(a, b); self.assertEqual(sa['kept_paths'], sb['kept_paths'])

    def test_no_file_truncated(self):
        text, s = self.kept('repo-map')
        blocks = text.split('\n=== ')[1:]
        self.assertEqual(len(blocks), len(s['kept_paths']))
        for b in blocks:
            head, _, body = b.partition('\n'); path = head.split(' @')[0]; n = int(head.rsplit('(', 1)[1].split(' ')[0])
            real = git_lines(git(self.repo, 'show', f'{self.sha}:{path}'))
            self.assertEqual(n, len(real), path)
            rows = [l for l in body.rstrip('\n').split('\n')]
            self.assertEqual(rows, [f'{i}\t{l}' for i, l in enumerate(real, 1)], path)         # every line, git numbering
        for p in self.files:                                                                   # the others are declared, never partial
            if p not in s['kept_paths']: self.assertIn(f'{p}  [not included (cap)]', text)

    def test_priority_groups_stay_first(self):
        _, s = self.kept('repo-map', priority=['lonely.py'])
        self.assertEqual(s['kept_paths'][0], 'lonely.py')

    def test_mentions_lift_a_file(self):
        _, plain = self.kept('repo-map')
        self.assertNotIn('lonely.py', plain['kept_paths'])
        _, by_ident = self.kept('repo-map', mentions={'idents': ['rare_feature_flag'], 'paths': []})
        self.assertIn('lonely.py', by_ident['kept_paths'])
        _, by_path = self.kept('repo-map', mentions={'idents': [], 'paths': ['lonely.py']})
        self.assertIn('lonely.py', by_path['kept_paths'])
        self.assertEqual(by_ident['repo_map']['mentioned_identifiers_defined'], 1)

    def test_empty_init_does_not_outrank_central_module(self):
        # a package whose __init__.py is empty and is imported by every module, next to a central module with real definitions
        root = self.d / 'z'; root.mkdir(); (root / 'pkg').mkdir(); (root / 'pkg' / '__init__.py').write_text('')
        (root / 'pkg' / 'engine.py').write_text('def run_engine():\n    return 1\n' + filler('engine'))
        for i in range(6): (root / 'pkg' / f'user_{i}.py').write_text(f'import pkg\nfrom pkg import engine\nfrom pkg.engine import run_engine\n\ndef use_{i}():\n    return run_engine()\n' + filler(f'u{i}'))
        git(root, 'init', '-q'); git(root, 'add', '-A'); git(root, 'commit', '-q', '-m', 'x'); sha = git(root, 'rev-parse', 'HEAD').strip()
        paths = [str(p.relative_to(root)) for p in sorted(root.rglob('*.py'))]
        read = lambda p: (root / p).read_bytes()
        new, _ = rm.score_files(paths, read, None, {'stem_needs_definition': True})
        old, _ = rm.score_files(paths, read, None, {'stem_needs_definition': False})
        self.assertLess(new['pkg/__init__.py'], new['pkg/engine.py'])
        self.assertGreater(old['pkg/__init__.py'], new['pkg/__init__.py'])           # the cause: the invented definition gave it mass
        self.assertEqual(max(new, key=new.get), 'pkg/engine.py')

    def test_x_side_paths_do_not_anchor_y_by_suffix(self):
        files = {'cli.py': 'def main_entry():\n    pass\n', 'agent/cli.py': 'def run_agent():\n    pass\n', 'agent/core/base.py': 'def make_base():\n    pass\n', 'x.py': 'import os\n'}
        read = lambda p: files[p].encode()
        def anchored(paths, idents=()):
            _, st = rm.score_files(sorted(files), read, {'idents': list(idents), 'paths': list(paths)}); return st['personalised_files']
        self.assertEqual(anchored(['cli.py']), 1)                    # bare name: only the file at the root of Y that is exactly that
        self.assertEqual(anchored(['src/other/cli.py']), 0)          # an X path with a directory that Y lacks: nothing
        self.assertEqual(anchored(['other/cli.py']), 0)
        self.assertEqual(anchored(['agent/cli.py']), 1)              # whole path of Y
        self.assertEqual(anchored(['x/agent/cli.py']), 0)            # longer than Y's path: not a suffix of it
        self.assertEqual(anchored(['core/base.py']), 1)              # suffix of two components
        self.assertEqual(anchored(['base.py']), 0)                   # one component, not at the root
        self.assertEqual(anchored([], ['never_defined_in_y']), 0)    # an identifier defined nowhere in Y anchors nothing
        self.assertEqual(anchored([], ['run_agent']), 1)
        self.assertEqual(anchored([], ['zzz_no_such_name']), 0)

    def test_capsule_gives_no_path_anchor(self):
        with tempfile.TemporaryDirectory() as d:
            run = pathlib.Path(d); (run / 'searches').mkdir()
            (run / 'capsule.md').write_text('target_seam: src/stamina/_core.py and `compute_totals`\n'); (run / 'scope.md').write_text('see agent/cli.py\n')
            m = rm.mentions_from_run(run)
            self.assertIn('agent/cli.py', m['paths']); self.assertNotIn('src/stamina/_core.py', m['paths']); self.assertIn('compute_totals', m['idents'])

    def test_size_exponent(self):
        sizes = {'a': 1000, 'b': 10}
        sc, _ = rm.score_files(['a', 'b'], lambda p: b'', None, {'size_exponent': 1}, sizes)
        self.assertGreater(sc['b'], sc['a'])
        sc0, _ = rm.score_files(['a', 'b'], lambda p: b'', None, {'size_exponent': 0}, sizes)
        self.assertEqual(sc0['a'], sc0['b'])

    def test_cli_and_run_mentions(self):
        run = self.d / 'run'; (run / 'searches').mkdir(parents=True)
        (run / 'scope.md').write_text(f'Y = y@{self.sha}\nQuestion: how does `rare_feature_flag` work?\n')
        out = self.d / 'out.txt'
        r = subprocess.run([sys.executable, '-I', str(P / 'condense_repo.py'), '--repo', str(self.repo), '--sha', self.sha, '--name', 'y', '--out', str(out),
                            '--cap', str(self.cap), '--selection', 'repo-map', '--run', str(run)], capture_output=True, text=True, env={**os.environ, **GIT_ENV})
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads(r.stdout); self.assertEqual(s['selection'], 'repo-map'); self.assertIn('lonely.py', s['kept_paths'])
        self.assertIn('repository map', out.read_text().split('\n')[0])
        r = subprocess.run([sys.executable, '-I', str(P / 'condense_repo.py'), '--repo', str(self.repo), '--sha', self.sha, '--name', 'y', '--out', str(out),
                            '--cap', str(self.cap)], capture_output=True, text=True, env={**os.environ, **GIT_ENV})
        self.assertEqual(json.loads(r.stdout)['selection'], 'order')

    def test_whole_reading_option(self):
        import whole_reading as W
        run = self.d / 'run2'; run.mkdir(); (run / 'scope.md').write_text(f'Question: `rare_feature_flag`\n')
        a = type('A', (), dict(selection='repo-map'))()
        sel, ment = W.y_selection(a, run, self.sha)
        self.assertEqual(sel, 'repo-map'); self.assertIn('rare_feature_flag', ment['idents'])
        a.selection = None; self.assertEqual(W.y_selection(a, run, self.sha), ('order', None))


class Tags(unittest.TestCase):
    def defs(self, path, text, stems=('__init__', 'index')):
        d, r = rm.file_tags(path, text, set(stems)); return d, r

    def test_python_ast(self):
        d, r = self.defs('pkg/core/budget.py', 'import os.path\nfrom .x import helper_fn\nLIMIT = 3\nclass Budget:\n    def spend(self): return helper_fn(LIMIT)\nasync def go(): pass\n')
        self.assertTrue({'Budget', 'spend', 'go', 'LIMIT', 'budget'} <= d)
        self.assertTrue(r['helper_fn'] >= 2 and r['path'] >= 1)

    def test_python_syntax_error_falls_back(self):
        d, r = self.defs('a.py', 'def broken(:\n    pass\nclass Still: ...\n')
        self.assertTrue({'broken', 'Still'} <= d or 'Still' in d)

    def test_package_stem(self):
        d, _ = self.defs('pkg/engine/__init__.py', 'x = 1\n'); self.assertIn('engine', d)

    def test_stem_only_for_a_file_with_definitions(self):
        for empty in ('', 'from .core import helper\n__all__ = ["helper"]\n'):
            d, _ = self.defs('pkg/engine/__init__.py', empty); self.assertEqual(d, set())
            d, _ = self.defs('pkg/core.py', empty); self.assertNotIn('core', d)
        d, _ = rm.file_tags('pkg/engine/__init__.py', '', {'__init__'}, False); self.assertEqual(d, {'engine'})   # the first measurement's behaviour
        d, _ = self.defs('pkg/core.py', 'def f(): pass\n'); self.assertIn('core', d)

    def test_javascript_typescript(self):
        d, _ = self.defs('src/a.ts', 'export function startServer() {}\nclass Router {}\ninterface Opts {}\ntype Handler = () => void\nconst build = async (x) => x\n  handle(req) {\n  }\nif (x) {\n}\n')
        self.assertTrue({'startServer', 'Router', 'Opts', 'Handler', 'build', 'handle'} <= d); self.assertNotIn('if', d)

    def test_go(self):
        d, _ = self.defs('x/server.go', 'package x\nfunc (s *Server) Serve() error {\n}\nfunc helper() {}\ntype Config struct {}\nconst Max = 3\n')
        self.assertTrue({'Serve', 'helper', 'Config', 'Max', 'server'} <= d)

    def test_rust(self):
        d, _ = self.defs('src/lib.rs', 'pub fn open_vault() {}\npub struct Vault;\ntrait Seal {}\nmod inner;\nmacro_rules! shout {}\n')
        self.assertTrue({'open_vault', 'Vault', 'Seal', 'inner', 'shout'} <= d)

    def test_java(self):
        d, _ = self.defs('a/Foo.java', 'public class Foo {\n  public static int compute(int a) {\n  }\n  private void reset() {}\n}\ninterface Bar {}\n')
        self.assertTrue({'Foo', 'compute', 'reset', 'Bar'} <= d)

    def test_c_cpp(self):
        d, _ = self.defs('src/m.c', '#define MAX_ITEMS 4\nstruct node { int v; };\ntypedef unsigned long ulong_t;\nstatic int parse_item(const char *s)\n{\n}\nint main(void) {\n}\nif (x) {\n}\n')
        self.assertTrue({'MAX_ITEMS', 'node', 'ulong_t', 'parse_item', 'main'} <= d); self.assertNotIn('if', d)

    def test_unknown_extension_has_no_tags(self):
        self.assertEqual(rm.file_tags('docs/a.md', 'def fake(): pass', set())[0], set())


class Mentions(unittest.TestCase):
    def test_text(self):
        sha = 'a' * 40
        t = ('See `Budget.spend` and parse_retry_after in src/net/client.py, plain words like budget are not identifiers; '
             f'ref src/net/retry.py:10-20@{sha} and x/other.py:3@{"b" * 40} (X side) https://example.org/some/path.html camelCaseName')
        idents, paths = rm.mentions_from_text(t, sha)
        self.assertTrue({'Budget', 'spend', 'parse_retry_after', 'camelCaseName'} <= idents); self.assertNotIn('budget', idents)
        self.assertIn('src/net/client.py', paths); self.assertIn('src/net/retry.py', paths); self.assertNotIn('x/other.py', paths)
        self.assertFalse(any('example.org' in p for p in paths))

    def test_run_dir(self):
        with tempfile.TemporaryDirectory() as d:
            run = pathlib.Path(d); (run / 'searches').mkdir()
            (run / 'scope.md').write_text('Question: how is `lease_timeout` handled?\n')
            (run / 'capsule.md').write_text('target_seam: engine_core.py\n')
            (run / 'searches' / '1.md').write_text('found in pkg/lease.py and `LeaseManager`\n'); (run / 'searches' / 'whole-reading.md').write_text('`ignored_ident`\n')
            m = rm.mentions_from_run(run)
            self.assertTrue({'lease_timeout', 'LeaseManager'} <= set(m['idents'])); self.assertNotIn('ignored_ident', m['idents'])
            self.assertIn('pkg/lease.py', m['paths']); self.assertNotIn('engine_core.py', m['paths'])   # capsule: identifiers only


class PageRank(unittest.TestCase):
    def test_sums_and_order(self):
        nodes = ['a', 'b', 'c']; edges = {'a': {'c': 1.0}, 'b': {'c': 1.0}}; pers = {n: 1 / 3 for n in nodes}
        x = rm.pagerank(nodes, edges, pers, 0.85, 100, 1e-12)
        self.assertAlmostEqual(sum(x.values()), 1.0, places=9); self.assertGreater(x['c'], x['a']); self.assertAlmostEqual(x['a'], x['b'])

    def test_personalisation_moves_mass(self):
        nodes = ['a', 'b']; x = rm.pagerank(nodes, {}, {'a': 0.9, 'b': 0.1}, 0.85, 100, 1e-12)
        self.assertGreater(x['a'], x['b'])


if __name__ == '__main__':
    unittest.main()
