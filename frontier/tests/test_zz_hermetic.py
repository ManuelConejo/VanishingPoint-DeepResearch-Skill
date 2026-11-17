# SPDX-License-Identifier: Apache-2.0
"""Safety oracles for Python sockets and unregistered program launches."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

from .helpers import FRONTIER, TempCase, load_tool
from . import sandbox


class HermeticTest(TempCase):
    @contextmanager
    def expected_denial(self, reason):
        log = sandbox.VIOLATIONS
        before = log.read_text(encoding='utf-8') if log.exists() else ''
        try:
            yield
        finally:
            after = log.read_text(encoding='utf-8') if log.exists() else ''
            self.assertEqual(after, before + reason + '\n')
            # Remove only the exact intentional probe, keeping earlier violations.
            log.write_text(before, encoding='utf-8')

    def probe(self, source, env=None):
        script = self.tmp / 'probe.py'
        script.write_text(source, encoding='utf-8')
        sandbox.register_script(script)
        # Empty environment and -I must still retain the guard in descendants.
        return subprocess.run([sys.executable, '-I', str(script)], env={} if env is None else env,
                              capture_output=True, text=True)

    def test_guard_state_uses_tempfile_directory(self):
        self.assertEqual(sandbox.POLICY.parent.parent, Path(tempfile.gettempdir()))
        if os.environ.get('TMPDIR'):
            self.assertEqual(sandbox.POLICY.parent.parent, Path(os.environ['TMPDIR']).resolve())

    def test_child_honours_its_own_tmpdir(self):
        tmpdir = self.tmp / 'child-temp'
        home = self.tmp / 'child-home'
        tmpdir.mkdir()
        home.mkdir()
        r = self.probe('import tempfile\nprint(tempfile.gettempdir())\n',
                       env={'HOME': str(home), 'TMPDIR': str(tmpdir)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), str(tmpdir))

    def test_am60_swallowed_attempt_fails_filtered_run(self):
        class SwallowedAttempt(unittest.TestCase):
            def test_am60_swallowed(self):
                try:
                    socket.getaddrinfo('localhost', 80)
                except AssertionError:
                    pass

            def test_not_selected(self):
                raise RuntimeError('the AM60 filter must exclude this test')

        # testNamePatterns is the unittest CLI's -k test_am60 selection mechanism.
        SwallowedAttempt.__qualname__ = 'SwallowedAttempt'
        loader = unittest.TestLoader()
        loader.testNamePatterns = ['*test_am60*']
        result = unittest.TestResult()
        with self.expected_denial('network event: socket.getaddrinfo'):
            loader.loadTestsFromTestCase(SwallowedAttempt).run(result)
            self.assertEqual(result.testsRun, 1)
            self.assertFalse(result.wasSuccessful())
            self.assertEqual(len(result.failures), 1)
            self.assertIn('unexpected guard attempts', result.failures[0][1])

    def test_attempt_swallowed_in_cleanup_is_also_reported(self):
        class CleanupAttempt(unittest.TestCase):
            def runTest(self):
                def cleanup():
                    try:
                        socket.getaddrinfo('localhost', 80)
                    except AssertionError:
                        pass
                self.addCleanup(cleanup)

        result = unittest.TestResult()
        with self.expected_denial('network event: socket.getaddrinfo'):
            CleanupAttempt().run(result)
            self.assertEqual(result.testsRun, 1)
            self.assertFalse(result.wasSuccessful())
            self.assertEqual(len(result.failures), 1)
            self.assertIn('unexpected guard attempts', result.failures[0][1])

    def test_ctypes_import_blocked_in_child(self):
        for module in ('ctypes', '_ctypes'):
            with self.subTest(module=module), self.expected_denial('native FFI import: ' + module):
                r = self.probe('import ' + module + '\n')
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('native FFI import', r.stderr)

    def test_gateway_blocked_before_process_creation(self):
        real = (FRONTIER.parent / 'tools' / 'gateway.py').resolve()
        gw = load_tool('gwclient')
        command = gw.build_command(real.parent.parent, '2026-11-14', 'test', self.tmp / 'state',
                                   'code', 'repo-info', 'owner/name', 1)
        with self.expected_denial('unapproved script: ' + str(real)):
            with self.assertRaisesRegex(AssertionError, 'unapproved script'):
                subprocess.run(command, env={})
        self.assertFalse((self.tmp / 'state').exists())

    def test_gateway_blocked_in_isolated_child_with_empty_environment(self):
        real = (FRONTIER.parent / 'tools' / 'gateway.py').resolve()
        with self.expected_denial('unapproved script: ' + str(real)):
            r = self.probe('import subprocess, sys\nsubprocess.run([sys.executable, "-I", %r])\n' % str(real))
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('unapproved script', r.stderr)

    def test_gateway_import_blocked_before_executing_code(self):
        gateway = self.tmp / 'gateway.py'
        marker = self.tmp / 'started'
        gateway.write_text('from pathlib import Path\nPath(%r).touch()\n' % str(marker), encoding='utf-8')
        with self.expected_denial('unapproved gateway import: ' + str(gateway)):
            r = self.probe('import runpy\nrunpy.run_path(%r, run_name="__main__")\n' % str(gateway))
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse(marker.exists())

    def test_network_blocked_in_parent(self):
        with self.expected_denial('network event: socket.getaddrinfo'):
            with self.assertRaisesRegex(AssertionError, 'network event'):
                socket.getaddrinfo('localhost', 80)

    def test_network_blocked_in_isolated_child(self):
        with self.expected_denial('network event: socket.__new__'):
            r = self.probe('import socket\nsocket.socket()\n')
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('network event', r.stderr)

    def test_native_network_client_blocked(self):
        with self.expected_denial('unapproved script: ' + str((self.tmp / 'curl').resolve())):
            with self.assertRaisesRegex(AssertionError, 'unapproved script'):
                subprocess.run([str(self.tmp / 'curl'), 'https://example.invalid'])

    def test_zz_no_unexpected_attempt_in_the_suite(self):
        log = sandbox.VIOLATIONS
        self.assertEqual(log.read_text(encoding='utf-8') if log.exists() else '', '')
