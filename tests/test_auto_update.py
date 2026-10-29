#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline test of tools/auto_update.py with local git repositories: a bare "remote" carrying the tags v0.6.6 and v0.6.7 and an
untagged commit on main after v0.6.7 (never installed), and an installed clone at v0.6.6 whose plugin.json `repository` is the remote's
path. Covers: fast-forward to the latest TAG (not main), hooks never run, refusal on local modifications and on divergence (notice line,
nothing changed), no update when the remote is not higher, the once-a-day cache, option off (notice only, notify off = nothing),
network failure and timeout (silent), VP_OFFLINE=1 (no git call, notice from the last version seen), a copy that is not its own git
repository (notice without git command), the --setup question, and check_keys.py --announce (line printed, exit code unchanged)."""
import contextlib, datetime as dt, io, json, os, pathlib, shutil, subprocess, sys, tempfile, unittest
P = pathlib.Path(__file__).resolve().parent
TOOLS = P.parent / 'tools'
sys.path.insert(0, str(TOOLS)); import auto_update as AU   # noqa: E702

CFG = AU.load_cfg()
GIT = ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'init.defaultBranch=main', '-c', 'core.hooksPath=' + os.devnull]
NOW = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)


def g(*args, cwd=None):
    p = subprocess.run(GIT + list(args), cwd=cwd, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    if p.returncode: raise AssertionError(f'git {args}: {p.stderr}')
    return p.stdout.strip()


class Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); t = pathlib.Path(self.tmp.name)
        self.home = t / 'home'; self.home.mkdir()
        self.saved_env = {k: os.environ.get(k) for k in ('VP_OFFLINE', 'HOME')}
        os.environ.pop('VP_OFFLINE', None); os.environ['HOME'] = str(self.home)
        self.remote = t / 'remote.git'; work = t / 'work'
        g('init', '-q', '--bare', str(self.remote)); g('init', '-q', str(work))
        for v, tag in (('0.6.6', 'v0.6.6'), ('0.6.7', 'v0.6.7'), ('0.6.8', None)):
            self.write_manifest(work, v); (work / 'SKILL.md').write_text(f'skill {v}\n')
            g('add', '-A', cwd=work); g('commit', '-q', '-m', v, cwd=work)
            if tag: g('tag', tag, cwd=work)
        g('tag', 'not-a-release', cwd=work)                                    # ignored by update.tag_pattern
        g('push', '-q', str(self.remote), 'main', '--tags', cwd=work)
        self.tag667 = g('rev-parse', 'v0.6.7^{commit}', cwd=work); self.main_tip = g('rev-parse', 'main', cwd=work)
        self.inst = t / 'installed'; g('clone', '-q', str(self.remote), str(self.inst)); g('reset', '-q', '--hard', 'v0.6.6', cwd=self.inst)

    def tearDown(self):
        for k, v in self.saved_env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.tmp.cleanup()

    def write_manifest(self, d, version):
        f = d / CFG['manifest']; f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({'name': 'vanishingpoint', 'version': version, 'repository': str(self.remote)}))

    def choose(self, auto, notify=None):
        f = self.home / CFG['config_dir'] / CFG['choice_file']; f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({'auto': auto, **({} if notify is None else {'notify': notify})}))

    def run_au(self, root=None, now=NOW, cfg=CFG):
        return AU.run(root=root or self.inst, home=self.home, cfg=cfg, now=now)

    def head(self): return g('rev-parse', 'HEAD', cwd=self.inst)

    def version(self): return json.loads((self.inst / CFG['manifest']).read_text())['version']

    def notice(self, root=None):
        return f"{CFG['label']} 0.6.7 available (installed 0.6.6): git -C {root or self.inst} pull"

    def test_fast_forward_to_latest_tag_without_hooks(self):
        self.choose(True)
        hook = self.inst / '.git' / 'hooks' / 'post-merge'; witness = self.inst.parent / 'hook-ran'
        hook.write_text(f'#!/bin/sh\ntouch {witness}\n'); hook.chmod(0o755)
        line = self.run_au()
        self.assertEqual(line, f"{CFG['label']} updated 0.6.6 -> 0.6.7 (takes effect at the next run)")
        self.assertEqual(self.head(), self.tag667); self.assertNotEqual(self.head(), self.main_tip)   # the tag, never main
        self.assertEqual(self.version(), '0.6.7'); self.assertFalse(witness.exists())
        self.assertEqual(g('status', '--porcelain', cwd=self.inst), '')

    def test_refused_when_tracked_files_modified(self):
        self.choose(True); before = self.head()
        (self.inst / 'SKILL.md').write_text('local edit\n')
        self.assertEqual(self.run_au(), self.notice())
        self.assertEqual(self.head(), before); self.assertEqual((self.inst / 'SKILL.md').read_text(), 'local edit\n')

    def test_untracked_file_does_not_block(self):
        self.choose(True); (self.inst / 'notes.txt').write_text('mine\n')
        self.assertIn('updated 0.6.6 -> 0.6.7', self.run_au()); self.assertTrue((self.inst / 'notes.txt').exists())

    def test_refused_when_diverged(self):
        self.choose(True)
        (self.inst / 'local.txt').write_text('x\n'); g('add', 'local.txt', cwd=self.inst); g('commit', '-q', '-m', 'local', cwd=self.inst)
        before = self.head()
        self.assertEqual(self.run_au(), self.notice()); self.assertEqual(self.head(), before); self.assertEqual(self.version(), '0.6.6')

    def test_no_update_when_remote_not_higher(self):
        self.choose(True); g('reset', '-q', '--hard', 'v0.6.7', cwd=self.inst)
        self.assertEqual(self.run_au(), ''); self.assertEqual(self.head(), self.tag667)
        g('reset', '-q', '--hard', 'v0.6.6', cwd=self.inst); self.write_manifest(self.inst, '0.7.0')     # installed above every tag
        self.assertEqual(self.run_au(now=NOW + dt.timedelta(days=2)), '')

    def test_once_a_day(self):
        self.choose(False)
        self.assertEqual(self.run_au(), self.notice())
        self.assertEqual(self.run_au(now=NOW + dt.timedelta(hours=CFG['interval_hours'] - 1)), '')     # same day: nothing, no git call
        self.assertEqual(self.run_au(now=NOW + dt.timedelta(hours=CFG['interval_hours'] + 1)), self.notice())
        state = json.loads((self.home / CFG['config_dir'] / CFG['state_file']).read_text())
        self.assertEqual((state['latest'], state['latest_tag']), ('0.6.7', 'v0.6.7'))

    def test_option_off_notice_only(self):
        before = self.head()
        self.assertEqual(self.run_au(), self.notice())                     # no answer stored: tools/config.json update.auto (false)
        self.assertFalse(CFG['auto']); self.assertEqual(self.head(), before)
        self.choose(False, notify=False)
        self.assertEqual(self.run_au(now=NOW + dt.timedelta(days=2)), ''); self.assertEqual(self.head(), before)
        self.assertEqual(AU.run(root=self.inst, home=self.home, cfg={**CFG, 'notify': False}, now=NOW + dt.timedelta(days=4)), '')

    def test_network_failure_and_timeout_silent(self):
        self.choose(True); before = self.head()
        self.write_manifest(self.inst, '0.6.6')
        man = json.loads((self.inst / CFG['manifest']).read_text()); man['repository'] = str(self.inst.parent / 'no-such-remote.git')
        (self.inst / CFG['manifest']).write_text(json.dumps(man))
        self.assertEqual(self.run_au(), '')
        saved = AU.subprocess.run

        def hang(*a, **k): raise subprocess.TimeoutExpired(a[0], k.get('timeout'))
        AU.subprocess.run = hang
        try: self.assertEqual(self.run_au(now=NOW + dt.timedelta(days=2)), '')
        finally: AU.subprocess.run = saved
        g('checkout', '-q', '--', '.', cwd=self.inst); self.assertEqual(self.head(), before)

    def test_network_failure_uses_last_version_seen(self):
        self.choose(True); self.assertIn('updated', self.run_au())
        g('reset', '-q', '--hard', 'v0.6.6', cwd=self.inst); before = self.head()
        saved = AU.subprocess.run
        AU.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(OSError('network down'))
        try: self.assertEqual(self.run_au(now=NOW + dt.timedelta(days=2)), f"{CFG['label']} 0.6.7 available (installed 0.6.6)")
        finally: AU.subprocess.run = saved
        self.assertEqual(self.head(), before)

    def test_offline(self):
        self.choose(True); before = self.head()
        os.environ['VP_OFFLINE'] = '1'; calls = []
        saved = AU.subprocess.run
        AU.subprocess.run = lambda *a, **k: calls.append(a[0]) or saved(*a, **k)
        try:
            self.assertEqual(self.run_au(), '')                              # nothing seen yet: nothing to say
            st = self.home / CFG['config_dir'] / CFG['state_file']
            st.write_text(json.dumps({'checked': (NOW - dt.timedelta(days=3)).isoformat(), 'latest': '0.6.7', 'latest_tag': 'v0.6.7'}))
            self.assertEqual(self.run_au(), self.notice())
        finally: AU.subprocess.run = saved
        self.assertFalse([c for c in calls if 'ls-remote' in c or 'fetch' in c or 'merge' in c], calls)
        self.assertEqual(self.head(), before)

    def test_not_its_own_git_repository(self):
        self.choose(True)
        copy = pathlib.Path(self.tmp.name) / 'plain'; shutil.copytree(self.inst, copy, ignore=shutil.ignore_patterns('.git'))
        self.assertEqual(self.run_au(root=copy), f"{CFG['label']} 0.6.7 available (installed 0.6.6)")
        self.assertEqual(json.loads((copy / CFG['manifest']).read_text())['version'], '0.6.6')
        nested = self.inst / 'sub'; nested.mkdir(); self.write_manifest(nested, '0.6.6')              # inside a larger repository
        self.assertEqual(self.run_au(root=nested, now=NOW + dt.timedelta(days=2)), f"{CFG['label']} 0.6.7 available (installed 0.6.6)")
        managed = AU.run(root=self.inst, home=self.home, cfg={**CFG, 'managed_path_markers': [self.inst.name]}, now=NOW + dt.timedelta(days=4))
        self.assertEqual(managed, f"{CFG['label']} 0.6.7 available (installed 0.6.6)"); self.assertEqual(self.version(), '0.6.6')

    def test_setup_question(self):
        saved = sys.stdin
        try:
            for typed, expected in (('', True), ('n', False), ('Y', True)):
                sys.stdin = io.StringIO(typed + '\n'); out = io.StringIO()
                with contextlib.redirect_stdout(out): self.assertIs(AU.setup(cfg=CFG, home=self.home), expected)
                self.assertIn('automatically? [Y/n]', out.getvalue())
                self.assertEqual(AU.choice(CFG, self.home)[0], expected)
        finally: sys.stdin = saved

    def test_check_keys_announce_prints_line_exit_unchanged(self):
        skill = TOOLS.parent
        installed = '.'.join(map(str, AU.version_tuple(json.loads((skill / CFG['manifest']).read_text())['version'])))
        st = self.home / CFG['config_dir'] / CFG['state_file']; st.parent.mkdir(parents=True, exist_ok=True)
        st.write_text(json.dumps({'checked': (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat(), 'latest': '999.0.0', 'latest_tag': 'v999.0.0'}))
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(self.home), 'VP_OFFLINE': '1'}
        cmd = [sys.executable, '-I', str(TOOLS / 'check_keys.py'), '--announce', '--plugin', 'cs-ai']
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.splitlines()[0], f"{CFG['label']} 999.0.0 available (installed {installed})" + ('' if not AU.own_repo(skill, CFG) else f': git -C {skill} pull'))
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)        # same day, nothing changed: nothing at all
        self.assertEqual((p.returncode, p.stdout), (0, ''), p.stderr)
        import check_keys as ck
        saved = AU.run; AU.run = lambda *a, **k: 1 / 0                        # a failing update never changes the host tool
        try:
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(ck.main(['--announce', '--plugin', 'cs-ai']), 0)
        finally: AU.run = saved


if __name__ == '__main__':
    unittest.main()
