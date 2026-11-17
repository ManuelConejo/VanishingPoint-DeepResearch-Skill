# SPDX-License-Identifier: Apache-2.0
"""setup.py: Python check, skill-local venv, VP detection, container engine detection (simulated) (regression specification R28, R30)."""
import os as _os
_os.environ['FRONTIER_EXECUTION_ENABLED'] = '1'   # orchestrator fix: execution is off by default; these tests exercise it

import json
import shutil
import unittest
from pathlib import Path

from .helpers import FRONTIER, TempCase, fake_calls, make_fake_engine, run_tool, write_json

VP_SKILL = '---\nname: vanishingpoint\ndescription: test double of the VP skill\n---\n\n# VP\n'


class SetupBase(TempCase):
    def setUp(self):
        super().setUp()
        self.vp = self.tmp / 'vp'
        self.vp.mkdir()
        self.skill = self.vp / 'frontier'
        shutil.copytree(str(FRONTIER), str(self.skill),
                        ignore=shutil.ignore_patterns('tests', '.venv', '__pycache__', 'config.local.json'))
        self.bin = self.tmp / 'bin'

    def run_setup(self, *args, env_extra=None):
        env = self.empty_path_env(self.bin)
        env['FRONTIER_EXECUTION_ENABLED'] = '1'   # orchestrator fix: execution (and its probe) is off by default
        if env_extra:
            env.update(env_extra)
        r = run_tool('setup', *args, env=env, tools_dir=self.skill / 'tools')
        return r

    def run_json(self, *args, env_extra=None):
        r = self.run_setup('--json', *args, env_extra=env_extra)
        self.assertIn(r.returncode, (0,), r.stdout + r.stderr)
        return json.loads(r.stdout)

    def snapshot(self):
        return sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob('*') if 'bin' not in p.parts)


class SetupTest(SetupBase):
    def test_check_is_read_only(self):
        (self.vp / 'SKILL.md').write_text(VP_SKILL, encoding='utf-8')
        before = self.snapshot()
        out = self.run_json('--check')
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.skill / '.venv').exists())
        self.assertTrue(out['python']['ok'])
        self.assertEqual(out['installed_outside_skill'], [])

    def test_no_venv_when_no_package_required(self):
        out = self.run_json()
        self.assertFalse(out['venv']['needed'])
        self.assertFalse((self.skill / '.venv').exists())

    def test_venv_needed_reported_but_not_created_in_check(self):
        (self.skill / 'requirements.txt').write_text('# optional\nnumpy>=1.26\n', encoding='utf-8')
        out = self.run_json('--check')
        self.assertTrue(out['venv']['needed'])
        self.assertIn('would', out['venv']['action'])
        self.assertEqual(Path(out['venv']['path']), (self.skill / '.venv').resolve())
        self.assertFalse((self.skill / '.venv').exists())

    def test_vp_sibling(self):
        (self.vp / 'SKILL.md').write_text(VP_SKILL, encoding='utf-8')
        out = self.run_json('--check')
        self.assertTrue(out['vp']['found'])
        self.assertEqual(out['vp']['how'], 'sibling')
        self.assertEqual(Path(out['vp']['dir']), self.vp.resolve())

    def test_vp_absent(self):
        out = self.run_json('--check')
        self.assertFalse(out['vp']['found'])

    def test_vp_wrong_name(self):
        (self.vp / 'SKILL.md').write_text('---\nname: something-else\n---\n', encoding='utf-8')
        self.assertFalse(self.run_json('--check')['vp']['found'])

    def test_vp_env(self):
        other = self.tmp / 'elsewhere'
        other.mkdir()
        (other / 'SKILL.md').write_text(VP_SKILL, encoding='utf-8')
        out = self.run_json('--check', env_extra={'FRONTIER_VP_DIR': str(other)})
        self.assertTrue(out['vp']['found'])
        self.assertEqual(out['vp']['how'], 'env')

    def test_vp_config(self):
        other = self.tmp / 'cfgvp'
        other.mkdir()
        (other / 'SKILL.md').write_text(VP_SKILL, encoding='utf-8')
        cfg = json.loads((self.skill / 'config.json').read_text(encoding='utf-8'))
        cfg['vp_dir'] = str(other)
        write_json(self.skill / 'config.json', cfg)
        out = self.run_json('--check')
        self.assertTrue(out['vp']['found'])
        self.assertEqual(out['vp']['how'], 'config')

    def test_explicit_missing_vp_never_uses_valid_fallbacks(self):
        # Both the configured VP and the sibling are valid: neither may rescue
        # an invalid command-line or environment path.
        (self.vp / 'SKILL.md').write_text(VP_SKILL, encoding='utf-8')
        cfg = json.loads((self.skill / 'config.json').read_text(encoding='utf-8'))
        cfg['vp_dir'] = str(self.vp)
        write_json(self.skill / 'config.json', cfg)
        missing = str(self.tmp / 'missing')
        for args, env in ((('--vp-dir', missing), {'FRONTIER_VP_DIR': str(self.vp)}),
                          ((), {'FRONTIER_VP_DIR': missing})):
            with self.subTest(args=args, env=env):
                out = self.run_json('--check', *args, env_extra=env)
                self.assertFalse(out['vp']['found'])
                self.assertIsNone(out['vp']['dir'])
                self.assertTrue(any(missing in n for n in out['notes']))

    def test_cli_vp_takes_precedence_over_missing_environment_path(self):
        (self.vp / 'SKILL.md').write_text(VP_SKILL, encoding='utf-8')
        out = self.run_json('--check', '--vp-dir', self.vp,
                            env_extra={'FRONTIER_VP_DIR': str(self.tmp / 'missing')})
        self.assertTrue(out['vp']['found'])
        self.assertEqual(out['vp']['how'], 'cli')

    def test_empty_environment_vp_is_refused_despite_valid_fallbacks(self):
        (self.vp / 'SKILL.md').write_text(VP_SKILL, encoding='utf-8')
        cfg = json.loads((self.skill / 'config.json').read_text(encoding='utf-8'))
        cfg['vp_dir'] = str(self.vp)
        write_json(self.skill / 'config.json', cfg)
        r = self.run_setup('--check', '--json', env_extra={'FRONTIER_VP_DIR': ''})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('FRONTIER_VP_DIR', r.stderr)

    def test_cli_vp_takes_precedence_over_empty_environment_path(self):
        (self.vp / 'SKILL.md').write_text(VP_SKILL, encoding='utf-8')
        out = self.run_json('--check', '--vp-dir', self.vp, env_extra={'FRONTIER_VP_DIR': ''})
        self.assertTrue(out['vp']['found'])
        self.assertEqual(out['vp']['how'], 'cli')

    def test_no_engine(self):
        out = self.run_json('--check')
        self.assertIsNone(out['engine']['name'])
        self.assertFalse(out['execution_available'])

    def test_docker_network_none_ok(self):
        make_fake_engine(self.bin, 'docker')
        out = self.run_json('--check')
        self.assertEqual(out['engine']['name'], 'docker')
        self.assertEqual(out['engine']['network_none'], 'ok')
        self.assertTrue(out['execution_available'])
        runs = [c['argv'] for c in fake_calls(self.bin) if c['argv'][:1] == ['run']]
        self.assertTrue(runs)
        self.assertEqual(runs[-1][runs[-1].index('--network') + 1], 'none')

    def test_probe_image_absent(self):
        make_fake_engine(self.bin, 'docker', image_present=False)
        out = self.run_json('--check')
        self.assertEqual(out['engine']['network_none'], 'untested')
        self.assertFalse(out['execution_available'])
        self.assertFalse([c for c in fake_calls(self.bin) if c['argv'][:1] == ['run']])

    def test_network_none_fails(self):
        make_fake_engine(self.bin, 'docker', run_exit=125)
        out = self.run_json('--check')
        self.assertEqual(out['engine']['network_none'], 'failed')
        self.assertFalse(out['execution_available'])

    def test_daemon_down(self):
        make_fake_engine(self.bin, 'docker', version_ok=False)
        out = self.run_json('--check')
        self.assertFalse(out['execution_available'])

    def test_podman(self):
        make_fake_engine(self.bin, 'podman')
        out = self.run_json('--check')
        self.assertEqual(out['engine']['name'], 'podman')
        self.assertTrue(out['execution_available'])

    def test_human_output(self):
        r = self.run_setup('--check')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('VP', r.stdout)
        self.assertIn('Python', r.stdout)
        self.assertIn('engine', r.stdout.lower())


if __name__ == '__main__':
    unittest.main()
