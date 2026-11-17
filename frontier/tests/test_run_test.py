# SPDX-License-Identifier: Apache-2.0
"""run_test.py: isolated execution in docker/podman, simulated engines only (regression specification R25, R30)."""
import os as _os
_os.environ['FRONTIER_EXECUTION_ENABLED'] = '1'   # orchestrator fix: execution is off by default; these tests exercise it

import json
import os
import shutil
import unittest
from pathlib import Path

from .helpers import (FRONTIER, TempCase, copy_skill, fake_calls, load_tool, make_fake_engine, mutate, read_json,
                      run_tool, set_config, write_json)

FORBIDDEN_FLAGS = {'-e', '--env', '--env-file', '--privileged', '--network=host', '--net=host'}


class RunTestBase(TempCase):
    def setUp(self):
        super().setUp()
        self.w = self.work('valid_novp')
        self.ex = self.w / 'exec' / 'T1'
        (self.ex / 'input').mkdir(parents=True)
        (self.ex / 'output').mkdir()
        (self.ex / 'input' / 'main.py').write_text('print("hello")\n', encoding='utf-8')
        write_json(self.ex / 'spec.json', {'image': 'python:3.12-slim',
                                           'command': ['python3', '/frontier/input/main.py'], 'timeout_s': 60})
        self.bin = self.tmp / 'bin'

    def env(self, extra=None):
        e = self.empty_path_env(self.bin)
        e['FRONTIER_SECRET'] = 'must-not-leak'
        e['FRONTIER_EXECUTION_ENABLED'] = '1'   # orchestrator fix: execution is off by default
        if extra:
            e.update(extra)
        return e

    def last_run_call(self):
        calls = [c for c in fake_calls(self.bin) if c['argv'][:1] == ['run']]
        self.assertTrue(calls, 'the engine was not called with run')
        return calls[-1]


class NoEngineTest(RunTestBase):
    def test_refuses_without_engine(self):
        (self.w / 'result.json').unlink()
        r = run_tool('run_test', self.w, '--test', 'T1', env=self.env())
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['status'], 'refused')
        res = read_json(self.w / 'result.json')
        self.assertEqual(res['mode'], 'plan only')
        self.assertTrue(res['reason'])

    def test_never_overwrites_an_executed_result_when_refusing(self):
        w = self.work('valid_vp')
        before = (w / 'result.json').read_text(encoding='utf-8')
        r = run_tool('run_test', w, '--test', 'T1', env=self.env())
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((w / 'result.json').read_text(encoding='utf-8'), before)


class FakeEngineTest(RunTestBase):
    def test_runs_isolated(self):
        make_fake_engine(self.bin, 'docker')
        r = run_tool('run_test', self.w, '--test', 'T1', env=self.env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        call = self.last_run_call()
        argv = call['argv']
        joined = ' '.join(argv)
        self.assertIn('--network', argv)
        self.assertEqual(argv[argv.index('--network') + 1], 'none')
        self.assertFalse(FORBIDDEN_FLAGS & set(argv), argv)
        # mounts: only inside the test directory, inputs read-only
        mounts = [argv[i + 1] for i, a in enumerate(argv) if a in ('-v', '--volume')]
        self.assertEqual(len(mounts), 2, mounts)
        ex = str(self.ex.resolve())
        for m in mounts:
            host = m.split(':')[0]
            self.assertTrue(host.startswith(ex + os.sep) or host == ex, m)
        ro = [m for m in mounts if m.endswith(':ro')]
        self.assertEqual(len(ro), 1)
        self.assertIn(os.sep + 'input:', ro[0])
        self.assertNotIn('--mount', argv)
        # no environment variable reaches the engine process beyond what the CLI needs
        self.assertNotIn('FRONTIER_SECRET', call['env'])
        self.assertIn('python:3.12-slim', joined)
        res = read_json(self.w / 'result.json')
        self.assertEqual(res['mode'], 'executed')
        self.assertEqual(res['engine'], 'docker')
        self.assertEqual(res['execution']['exit_code'], 0)
        self.assertFalse(res['execution']['timed_out'])
        self.assertIn('fake run ok', res['execution']['stdout_tail'])
        self.assertIsNone(res['decision'], 'the decision is applied by the agent from the rule, not by the tool')

    def test_podman_when_no_docker(self):
        make_fake_engine(self.bin, 'podman')
        r = run_tool('run_test', self.w, '--test', 'T1', env=self.env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read_json(self.w / 'result.json')['engine'], 'podman')

    def test_timeout(self):
        make_fake_engine(self.bin, 'docker', sleep=5)
        r = run_tool('run_test', self.w, '--test', 'T1', '--timeout', '1', env=self.env())
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        res = read_json(self.w / 'result.json')
        self.assertTrue(res['execution']['timed_out'])
        self.assertTrue(any(c['argv'][:1] == ['kill'] for c in fake_calls(self.bin)))

    def test_nonzero_exit_recorded(self):
        make_fake_engine(self.bin, 'docker', run_exit=7)
        r = run_tool('run_test', self.w, '--test', 'T1', env=self.env())
        self.assertEqual(r.returncode, 0)
        self.assertEqual(read_json(self.w / 'result.json')['execution']['exit_code'], 7)

    def test_refuses_symlink_input(self):
        make_fake_engine(self.bin, 'docker')
        outside = self.tmp / 'outside'
        outside.mkdir()
        (self.ex / 'input' / 'main.py').unlink()
        (self.ex / 'input').rmdir()
        os.symlink(str(outside), str(self.ex / 'input'))
        r = run_tool('run_test', self.w, '--test', 'T1', env=self.env())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse([c for c in fake_calls(self.bin) if c['argv'][:1] == ['run']])

    def test_refuses_bad_test_id(self):
        make_fake_engine(self.bin, 'docker')
        r = run_tool('run_test', self.w, '--test', '../../etc', env=self.env())
        self.assertEqual(r.returncode, 2)

    def test_refuses_without_before_in_log(self):
        make_fake_engine(self.bin, 'docker')
        (self.w / 'decision_log.jsonl').unlink()
        r = run_tool('run_test', self.w, '--test', 'T1', env=self.env())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('before', r.stdout + r.stderr)

    def test_refuses_existing_executed_result(self):
        w = self.work('valid_vp')
        ex = w / 'exec' / 'T1'
        (ex / 'input').mkdir(parents=True)
        (ex / 'output').mkdir()
        write_json(ex / 'spec.json', {'image': 'busybox', 'command': ['true']})
        make_fake_engine(self.bin, 'docker')
        r = run_tool('run_test', w, '--test', 'T1', env=self.env())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_refuses_missing_spec(self):
        make_fake_engine(self.bin, 'docker')
        (self.ex / 'spec.json').unlink()
        r = run_tool('run_test', self.w, '--test', 'T1', env=self.env())
        self.assertEqual(r.returncode, 2)


ENGINES = ('docker', 'podman')
ADVERSARIAL_IMAGES = ['--privileged', '--network=host', '-v', '-v=/:/h', '--volume=/:/host', 'busybox --privileged',
                      'busybox:latest --privileged', 'Busybox', '', ' busybox', 'busybox\n--privileged', '-busybox']


class Round2Base(RunTestBase):
    """Round 2 (F1): one fake engine per sub-test, in its own bin directory."""

    def engine_bin(self, engine, tag, **kw):
        b = self.tmp / ('bin-%s-%s' % (engine, tag))
        make_fake_engine(b, engine, **kw)
        return b

    def run_with(self, bindir, *extra, tools_dir=None):
        env = self.empty_path_env(bindir)
        env['FRONTIER_SECRET'] = 'must-not-leak'
        env['FRONTIER_EXECUTION_ENABLED'] = '1'   # orchestrator fix: execution is off by default
        return run_tool('run_test', self.w, '--test', 'T1', *extra, env=env, tools_dir=tools_dir)

    def run_calls(self, bindir):
        return [c for c in fake_calls(bindir) if c['argv'][:1] == ['run']]

    def set_image(self, image):
        write_json(self.ex / 'spec.json', {'image': image, 'command': ['python3', '/frontier/input/main.py'],
                                           'timeout_s': 60})


class AdversarialImageTest(Round2Base):
    """R31: the image reference is validated; an option smuggled in "image" never reaches the engine."""

    def test_adversarial_images_refused_docker_and_podman(self):
        for engine in ENGINES:
            for i, image in enumerate(ADVERSARIAL_IMAGES):
                with self.subTest(engine=engine, image=image):
                    b = self.engine_bin(engine, 'adv%d' % i)
                    self.set_image(image)
                    r = self.run_with(b)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertEqual(self.run_calls(b), [])
                    for c in fake_calls(b):
                        self.assertNotIn('--privileged', c['argv'])
                        self.assertFalse(any(a.startswith('--network=host') for a in c['argv']))
                    self.assertEqual(read_json(self.w / 'result.json')['mode'], 'plan only')

    def test_image_not_a_string_refused(self):
        b = self.engine_bin('docker', 'list')
        write_json(self.ex / 'spec.json', {'image': ['--privileged', 'busybox'], 'command': ['true']})
        r = self.run_with(b)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.run_calls(b), [])

    def test_valid_references_accepted(self):
        for i, image in enumerate(['busybox', 'busybox:1.36', 'ghcr.io/org/tool:1.2',
                                   'python@sha256:' + 'a' * 64, 'localhost:5000/x/y-z_w:tag']):
            with self.subTest(image=image):
                self.fresh()
                b = self.engine_bin('docker', 'ok%d' % i)
                self.set_image(image)
                r = self.run_with(b)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.run_calls(b)[-1]['argv'][-3], image)


class ImagePresenceTest(Round2Base):
    """R32: the image must already be present locally; nothing is pulled."""

    def test_absent_image_refused(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                b = self.engine_bin(engine, 'absent', image_present=False)
                r = self.run_with(b)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                calls = [c['argv'] for c in fake_calls(b)]
                self.assertIn(['image', 'inspect', 'python:3.12-slim'], calls)
                self.assertFalse([a for a in calls if a[:1] in (['run'], ['pull']) or a[:2] == ['image', 'pull']])
                self.assertIn('pull', r.stdout + r.stderr)

    def test_inspect_before_run_and_pull_never(self):
        b = self.engine_bin('podman', 'present')
        r = self.run_with(b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = [c['argv'] for c in fake_calls(b)]
        i_inspect = calls.index(['image', 'inspect', 'python:3.12-slim'])
        i_run = max(i for i, a in enumerate(calls) if a[:1] == ['run'])
        self.assertLess(i_inspect, i_run)
        self.assertIn('--pull=never', calls[i_run])


class LimitsTest(Round2Base):
    """R33: imposed isolation and resource options, values from config.json run_limits; never root."""

    def limits(self):
        return json.loads((FRONTIER / 'config.json').read_text(encoding='utf-8'))['run_limits']

    def test_imposed_options_docker_and_podman(self):
        lim = self.limits()
        for engine in ENGINES:
            with self.subTest(engine=engine):
                self.fresh()
                b = self.engine_bin(engine, 'lim')
                r = self.run_with(b)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                argv = self.run_calls(b)[-1]['argv']

                def val(flag):
                    self.assertIn(flag, argv)
                    return argv[argv.index(flag) + 1]
                self.assertEqual(val('--network'), 'none')
                self.assertIn('--read-only', argv)
                self.assertEqual(val('--tmpfs'), '/tmp')
                self.assertEqual(val('--cap-drop'), 'ALL')
                self.assertEqual(val('--security-opt'), 'no-new-privileges')
                self.assertEqual(val('--pids-limit'), str(lim['pids_limit']))
                self.assertEqual(val('--memory'), str(lim['memory']))
                self.assertEqual(val('--cpus'), str(lim['cpus']))
                user = val('--user')
                self.assertEqual(user, str(lim['user']))
                self.assertNotRegex(user, r'^(0|root)(:|$)')
                self.assertFalse(FORBIDDEN_FLAGS & set(argv), argv)
                self.assertNotIn('--mount', argv)
                self.assertFalse([a for a in argv if a.startswith('--env') or a.startswith('-e=')])
                self.assertNotIn('FRONTIER_SECRET', self.run_calls(b)[-1]['env'])

    def test_root_user_in_config_refused(self):
        for k, user in enumerate(['root', '0', '0:0', 'root:root', '']):
            with self.subTest(user=user):
                skill = copy_skill(self.tmp / ('skill-root-%d' % k))
                set_config(skill, lambda c: c['run_limits'].update(user=user))
                b = self.engine_bin('docker', 'root%d' % k)
                r = self.run_with(b, tools_dir=skill / 'tools')
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(self.run_calls(b), [])

    def test_host_user(self):
        """Added after JOURNAL-TESTS-ECHEC2 (declared in RAPPORT): "user": "host" = the uid:gid running Frontier."""
        skill = copy_skill(self.tmp / 'skill-host')
        set_config(skill, lambda c: c['run_limits'].update(user='host'))
        b = self.engine_bin('docker', 'host')
        r = self.run_with(b, tools_dir=skill / 'tools')
        if os.getuid() == 0:
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            return
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        argv = self.run_calls(b)[-1]['argv']
        self.assertEqual(argv[argv.index('--user') + 1], '%d:%d' % (os.getuid(), os.getgid()))

    def test_config_values_used(self):
        skill = copy_skill(self.tmp / 'skill-lim')
        set_config(skill, lambda c: c['run_limits'].update(memory='512m', cpus='1.5', pids_limit=64, user='1000:1000'))
        b = self.engine_bin('podman', 'cfg')
        r = self.run_with(b, tools_dir=skill / 'tools')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        argv = self.run_calls(b)[-1]['argv']
        for flag, v in (('--memory', '512m'), ('--cpus', '1.5'), ('--pids-limit', '64'), ('--user', '1000:1000')):
            self.assertEqual(argv[argv.index(flag) + 1], v)


class SymlinkTest(Round2Base):
    """R34: mounts resolved then checked; any symbolic link under input/ or output/ is refused."""

    def check_refused(self, make_link, tag):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                self.fresh()
                outside = self.tmp / 'outside'
                outside.mkdir(exist_ok=True)
                (outside / 'secret.txt').write_text('secret\n', encoding='utf-8')
                make_link(outside)
                b = self.engine_bin(engine, tag)
                r = self.run_with(b)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(self.run_calls(b), [])
                self.assertIn('symbolic link', r.stdout + r.stderr)

    def test_file_link_in_input(self):
        self.check_refused(lambda o: os.symlink(str(o / 'secret.txt'), str(self.ex / 'input' / 'data.txt')), 'flink')

    def test_dir_link_deep_in_input(self):
        def mk(o):
            (self.ex / 'input' / 'a' / 'b').mkdir(parents=True)
            os.symlink(str(o), str(self.ex / 'input' / 'a' / 'b' / 'escape'))
        self.check_refused(mk, 'dlink')

    def test_link_in_output(self):
        self.check_refused(lambda o: os.symlink(str(o), str(self.ex / 'output' / 'out')), 'olink')

    def test_link_pointing_inside_is_still_refused(self):
        self.check_refused(lambda o: os.symlink(str(self.ex / 'input' / 'main.py'),
                                                str(self.ex / 'input' / 'alias.py')), 'ilink')

    def test_exec_dir_link_refused(self):
        def mk(o):
            real = self.tmp / 'real-exec'
            shutil.move(str(self.w / 'exec'), str(real))
            os.symlink(str(real), str(self.w / 'exec'))
        self.check_refused(mk, 'elink')

    def test_mounts_are_resolved_paths(self):
        b = self.engine_bin('docker', 'resolved')
        r = self.run_with(b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        argv = self.run_calls(b)[-1]['argv']
        mounts = [argv[i + 1] for i, a in enumerate(argv) if a in ('-v', '--volume')]
        self.assertEqual(len(mounts), 2)
        for m in mounts:
            host = m.split(':')[0]
            self.assertEqual(host, os.path.realpath(host))
            self.assertTrue(host.startswith(os.path.realpath(str(self.ex)) + os.sep))


class OutputCapTest(Round2Base):
    """R35: the container output is read as a stream and capped (config run_limits.output_cap_bytes)."""

    def test_output_capped(self):
        skill = copy_skill(self.tmp / 'skill-cap')
        set_config(skill, lambda c: c['run_limits'].update(output_cap_bytes=10000))
        b = self.engine_bin('docker', 'cap', big_stdout=300000)
        r = self.run_with(b, tools_dir=skill / 'tools')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ex = read_json(self.w / 'result.json')['execution']
        self.assertLessEqual(len(ex['stdout_tail'].encode('utf-8')), 10000)
        self.assertTrue(ex['stdout_truncated'])
        self.assertGreaterEqual(ex['stdout_bytes'], 300000)
        self.assertIn('END-OF-OUTPUT', ex['stdout_tail'])
        self.assertFalse(ex['stderr_truncated'])

    def test_small_output_not_truncated(self):
        b = self.engine_bin('podman', 'small')
        r = self.run_with(b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ex = read_json(self.w / 'result.json')['execution']
        self.assertFalse(ex['stdout_truncated'])
        self.assertIn('fake run ok', ex['stdout_tail'])

    def test_no_unbounded_capture_in_code(self):
        text = (FRONTIER / 'tools' / 'run_test.py').read_text(encoding='utf-8')
        self.assertNotIn('capture_output=True, text=True, timeout=timeout', text)
        self.assertNotIn('.communicate(', text)


class EnvNoteTest(Round2Base):
    """R36: the image's own environment variables are not controlled, and result.json says so."""

    def test_environment_note(self):
        b = self.engine_bin('docker', 'env')
        r = self.run_with(b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        note = read_json(self.w / 'result.json')['environment_note']
        self.assertIn('image', note)
        self.assertIn('not controlled', note)


class ProofTest(Round2Base):
    """R38, R66: the "before" fingerprint gates the execution and is copied into result.json; the step is logged."""

    def log_lines(self):
        return [json.loads(x) for x in (self.w / 'decision_log.jsonl').read_text(encoding='utf-8').splitlines() if x]

    def test_fingerprint_copied(self):
        b = self.engine_bin('docker', 'fp')
        r = self.run_with(b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        res = read_json(self.w / 'result.json')
        before = [e for e in self.log_lines() if e['phase'] == 'before' and e['test'] == 'T1'][-1]
        self.assertEqual(res['before_fingerprint'], before['fingerprint'])
        self.assertEqual(res['before_utc'], before['utc'])
        self.assertRegex(res['before_fingerprint'], r'^[0-9a-f]{64}$')

    def test_before_without_fingerprint_refused(self):
        lines = self.log_lines()
        for e in lines:
            e.pop('fingerprint', None)
        (self.w / 'decision_log.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in lines), encoding='utf-8')
        b = self.engine_bin('docker', 'nofp')
        r = self.run_with(b)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.run_calls(b), [])

    def test_protocol_changed_after_before_refused(self):
        mutate(self.w, 'tests.json', lambda d: d['tests'][0]['decision_rule'].update(
            continue_if='Point estimate above 2 positions.'))
        b = self.engine_bin('docker', 'changed')
        r = self.run_with(b)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('fingerprint', r.stdout + r.stderr)
        self.assertEqual(self.run_calls(b), [])

    def test_execution_step_recorded(self):
        b = self.engine_bin('podman', 'step')
        r = self.run_with(b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        steps = [s for s in read_json(self.w / 'run.json')['steps'] if s['step'] == 'execution']
        self.assertEqual(len(steps), 1)
        self.assertIsInstance(steps[0]['duration_s'], (int, float))
        self.assertEqual(steps[0]['cost_usd'], 'unknown')

    def test_second_execution_refused_by_budget(self):
        mutate(self.w, 'run.json', lambda d: d['steps'].append(
            {'step': 'execution', 'utc': '2026-11-14T11:30:00Z', 'duration_s': 5, 'cost_usd': 'unknown'}))
        b = self.engine_bin('docker', 'budget')
        r = self.run_with(b)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('budget', r.stdout + r.stderr)
        self.assertEqual(self.run_calls(b), [])


class BuildCommandTest(unittest.TestCase):
    def test_flags(self):
        rt = load_tool('run_test')
        cmd = rt.build_command('docker', 'frontier-T1-x', Path('/w/exec/T1/input'), Path('/w/exec/T1/output'),
                               'img:1', ['python3', 'main.py'])
        self.assertEqual(cmd[:2], ['docker', 'run'])
        self.assertIn('--rm', cmd)
        self.assertEqual(cmd[cmd.index('--network') + 1], 'none')
        self.assertIn('--pull=never', cmd)
        self.assertIn('--cap-drop', cmd)
        self.assertIn(str(Path('/w/exec/T1/input')) + ':/frontier/input:ro', cmd)
        self.assertEqual(cmd[-3:], ['img:1', 'python3', 'main.py'])
        self.assertFalse(FORBIDDEN_FLAGS & set(cmd))

    def test_engine_env_is_minimal(self):
        rt = load_tool('run_test')
        env = rt.engine_env({'PATH': '/x', 'HOME': '/h', 'AWS_SECRET_ACCESS_KEY': 's', 'DOCKER_HOST': 'unix:///d'})
        self.assertEqual(set(env), {'PATH', 'HOME', 'DOCKER_HOST'})


if __name__ == '__main__':
    unittest.main()
