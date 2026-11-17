# SPDX-License-Identifier: Apache-2.0
"""Test-only safety net, not a sandbox; also used by children (python -I).

Blocks Python-level sockets and launches of non-registered programs: only
Frontier tools and explicitly registered Python test doubles may execute.
Every child re-installs the audit hook before running its target. The policy is
passed in argv, so an empty/custom environment cannot disable it. Denials are
journaled and checked after every unittest case, including its cleanups.
Native network calls (ctypes/libc) are outside this guard's guarantees; children
refuse ctypes imports/loading as an extra precaution, not a native-code barrier.
Known limit: in a filtered run (for example -k), a denial raised and swallowed
inside tearDownClass or tearDownModule is not checked; only the full suite ends
with the final journal check.
Real isolation requires running the suite in a container without network.
"""
import atexit
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
RUNNER = Path(__file__).resolve()
POLICY = None
VIOLATIONS = None
CHILD = False
_original_popen = subprocess.Popen


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def register_script(path):
    """Register only a Python test double just written by a test helper."""
    data = json.loads(POLICY.read_text(encoding='utf-8'))
    data['scripts'][str(Path(path).resolve())] = digest(path)
    POLICY.write_text(json.dumps(data), encoding='utf-8')


def allowed(path):
    data = json.loads(POLICY.read_text(encoding='utf-8'))
    try:
        sha = digest(path)
    except OSError:
        return False
    # Copies used for installation/portability tests have identical tool code.
    return sha == data['scripts'].get(str(path)) or (
        path.parent.name == 'tools' and sha == data['tools'].get(path.name))


def refuse(reason):
    with VIOLATIONS.open('a', encoding='utf-8') as stream:
        stream.write(reason + '\n')
    raise AssertionError('Frontier test sandbox: ' + reason)


def check_attempts():
    """Keep unexpected attempts sticky even when a test swallows a denial."""
    attempts = VIOLATIONS.read_text(encoding='utf-8') if VIOLATIONS.exists() else ''
    if attempts:
        raise AssertionError('unexpected guard attempts:\n' + attempts)


def install_test_guard():
    """Check all TestCase subclasses, including those not using our helpers."""
    import unittest
    original_run = unittest.TestCase.run
    if getattr(original_run, '_frontier_guard', False):
        return

    def guarded_run(case, result=None):
        # Registered first, executed last: setUp, tearDown and test cleanups
        # cannot swallow a denial and leave a successful result behind.
        case.addCleanup(check_attempts)
        return original_run(case, result)

    guarded_run._frontier_guard = True
    unittest.TestCase.run = guarded_run


class OfflinePopen(_original_popen):
    def __init__(self, args, *pos, **kwargs):
        if not isinstance(args, (list, tuple)) or kwargs.get('shell') or kwargs.get('executable'):
            refuse('unapproved process command')
        args = [os.fspath(a) for a in args]
        # The suite launches Python scripts with -I, or registered fake engines
        # with a Python shebang. Never execute a real container/network client.
        if args[0] == sys.executable and args[1:2] == ['-I'] and len(args) >= 3:
            target, rest = Path(args[2]), args[3:]
        else:
            target, rest = Path(args[0]), args[1:]
        if not target.is_absolute():
            target = Path(kwargs.get('cwd') or Path.cwd()) / target
        target = target.resolve()
        if not allowed(target):
            refuse('unapproved script: ' + str(target))
        wrapped = [sys.executable, '-I', str(RUNNER), str(POLICY), str(target)] + rest
        super().__init__(wrapped, *pos, **kwargs)


def audit(event, args):
    if CHILD and event == 'import' and args[0].split('.')[0] in ('ctypes', '_ctypes'):
        refuse('native FFI import: ' + args[0])
    if CHILD and event.startswith('ctypes.'):
        refuse('native FFI event: ' + event)
    if event.startswith('socket.'):
        refuse('network event: ' + event)
    if event in ('os.system', 'os.exec', 'os.posix_spawn', 'pty.spawn'):
        refuse('unapproved process event: ' + event)
    if event == 'subprocess.Popen':
        executable, argv, _, _ = args
        if executable != sys.executable or list(argv[1:4]) != ['-I', str(RUNNER), str(POLICY)]:
            refuse('process bypassed offline runner')
    if event == 'exec':
        path = Path(args[0].co_filename)
        if path.name == 'gateway.py' and not allowed(path.resolve()):
            refuse('unapproved gateway import: ' + str(path))


def install(policy=None):
    global POLICY, VIOLATIONS, CHILD
    if POLICY is not None:
        return
    if policy is None:
        state = tempfile.TemporaryDirectory(prefix='frontier-suite-')
        atexit.register(state.cleanup)
        POLICY = Path(state.name) / 'policy.json'
        tools = RUNNER.parent.parent / 'tools'
        POLICY.write_text(json.dumps({'tools': {p.name: digest(p) for p in tools.glob('*.py')},
                                      'scripts': {}}), encoding='utf-8')
        os.environ.pop('FRONTIER_VP_DIR', None)
    else:
        POLICY = Path(policy)
        CHILD = True
    VIOLATIONS = POLICY.with_name('violations.txt')
    subprocess.Popen = OfflinePopen
    sys.addaudithook(audit)


if __name__ == '__main__':
    install(sys.argv[1])
    target = Path(sys.argv[2]).resolve()
    if not allowed(target):
        refuse('unapproved script: ' + str(target))
    sys.argv = [str(target)] + sys.argv[3:]
    runpy.run_path(str(target), run_name='__main__')
