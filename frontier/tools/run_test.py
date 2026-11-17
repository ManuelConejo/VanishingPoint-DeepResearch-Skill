#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run one Frontier test in an isolated container (SKILL.md step 5, optional). Standard library only.

Layout of the test, inside the working directory:
  <dir>/exec/<T>/spec.json   {"image": "<local image>", "command": ["python3", "/frontier/input/main.py"], "timeout_s": 600}
  <dir>/exec/<T>/input/      code and data, mounted READ-ONLY at /frontier/input
  <dir>/exec/<T>/output/     the only writable mount, at /frontier/output
Image reference: must match ^[a-z0-9][a-z0-9._/:@-]*$ (never a leading "-": an option smuggled in "image" is refused
before the engine is called), and must already be present locally: `<engine> image inspect <image>` is run first and a
missing image is refused; nothing is ever pulled (`--pull=never` as well).
Isolation, always: `--network none`, `--pull=never`, `--rm`, `--read-only` root with a tmpfs /tmp, `--cap-drop ALL`,
`--security-opt no-new-privileges`, `--pids-limit`, `--memory`, `--cpus` and `--user` (values: "run_limits" of
config.json; a root user is refused; "user": "host" = the uid:gid running Frontier, so that the container can write
output/ when the default unprivileged user cannot); exactly two bind mounts, whose paths are resolved (realpath) and checked AFTER
resolution to lie inside <dir>/exec/<T>/, and no symbolic link anywhere under input/ or output/ (refused); no
`-e`/`--env`/`--env-file`: Frontier passes no environment variable to the container. Variables defined by the IMAGE itself
(its ENV lines) are not controlled: result.json says so ("environment_note"). The engine CLI runs with a reduced
environment (PATH, HOME and the engine's own connection variables). Output: stdout and stderr are read as streams; at most
run_limits.output_cap_bytes bytes of each are kept (the end), with the total read and a "truncated" flag. Time limit:
--timeout, else spec timeout_s, else config.json run_timeout_s; the container is then killed.
Preconditions, refused with exit code 2: a valid test id, the layout above, no executed result.json already present, the
budget of executions (config.json budget.executions, counted in run.json), and a "before" entry of this test in
decision_log.jsonl (tools/log.py) whose fingerprint equals the fingerprint of the test now in tests.json: the protocol
executed is the one frozen before the result existed.
Without docker or podman on PATH: refused with exit code 3, and result.json = {"mode": "plan only", "reason": ...} is
written when there is no result.json yet (an existing result is never overwritten).
On execution: result.json = {"mode": "executed", "test", "engine", "image", "command", "before_fingerprint", "before_utc",
"environment_note", "limits", "execution": {started_utc, ended_utc, duration_s, exit_code, timed_out, stdout_tail,
stderr_tail, stdout_bytes, stderr_bytes, stdout_truncated, stderr_truncated, output_files}, "observed": null,
"decision": null}, and the step "execution" (measured duration, cost "unknown") is appended to run.json. The tool never
judges the outcome: the agent reads output/, writes "observed" and applies the decision rule fixed before ("decision",
"decision_rule_applied"), then tools/log.py after. Exit code 0 (whatever the container's exit code, which is recorded),
4 on timeout.

Usage: run_test.py DIR --test T1 [--engine docker|podman] [--timeout SECONDS]
Import: find_engine(preferred=None, path=None); build_command(engine, name, input_dir, output_dir, image, command,
        limits=None); engine_env(environ) -> dict; valid_image(s) -> bool
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

sys.dont_write_bytecode = True  # no __pycache__ written in the skill directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

ENGINES = ('docker', 'podman')
ENV_KEEP = ('PATH', 'HOME', 'SYSTEMROOT', 'TMPDIR', 'XDG_RUNTIME_DIR', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG',
            'DOCKER_CERT_PATH', 'DOCKER_TLS_VERIFY', 'CONTAINER_HOST', 'CONTAINER_CONNECTION', 'CONTAINERS_CONF')
IMAGE_RE = re.compile(r'[a-z0-9][a-z0-9._/:@-]*')
MEMORY_RE = re.compile(r'[0-9]+[bkmg]?')
CPUS_RE = re.compile(r'[0-9]+(\.[0-9]+)?')
USER_RE = re.compile(r'[a-z0-9_][a-z0-9_.-]*(:[a-z0-9_][a-z0-9_.-]*)?')
ROOT_RE = re.compile(r'(0|root)(:.*)?')
ENV_NOTE = ('Frontier passes no environment variable to the container; environment variables defined by the image '
            'itself are not controlled.')


class Refused(Exception):
    pass


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def find_engine(preferred=None, path=None):
    """(name, executable path) of the first engine found on PATH, or (None, None)."""
    for name in ([preferred] if preferred else ENGINES):
        exe = shutil.which(name, path=path)
        if exe:
            return name, exe
    return None, None


def engine_env(environ):
    return {k: environ[k] for k in ENV_KEEP if k in environ}


def valid_image(s):
    return isinstance(s, str) and IMAGE_RE.fullmatch(s) is not None


def limits_from_config(cfg=None):
    """The run limits of config.json, checked; Refused when a value is malformed or the user is root."""
    lim = (cfg or common.config())['run_limits']
    memory, cpus, user = str(lim.get('memory', '')), str(lim.get('cpus', '')), str(lim.get('user', ''))
    pids, cap = lim.get('pids_limit'), lim.get('output_cap_bytes')
    if user == 'host':
        # the uid:gid of the user running Frontier, so that the container can write output/ (still never root)
        if not hasattr(os, 'getuid'):
            raise Refused('config.json run_limits.user "host" needs a POSIX system (macOS or Linux)')
        user = '%d:%d' % (os.getuid(), os.getgid())
    if not MEMORY_RE.fullmatch(memory):
        raise Refused('config.json run_limits.memory %r is not a size such as 2g' % memory)
    if not CPUS_RE.fullmatch(cpus):
        raise Refused('config.json run_limits.cpus %r is not a number' % cpus)
    if not isinstance(pids, int) or isinstance(pids, bool) or pids < 1:
        raise Refused('config.json run_limits.pids_limit must be a positive integer')
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise Refused('config.json run_limits.output_cap_bytes must be a positive integer')
    if not user or ROOT_RE.fullmatch(user.lower()) or not USER_RE.fullmatch(user.lower()):
        raise Refused('config.json run_limits.user %r: a non-root user is required (for instance 65534:65534)' % user)
    return {'memory': memory, 'cpus': cpus, 'pids_limit': pids, 'user': user, 'output_cap_bytes': cap}


def build_command(engine, name, input_dir, output_dir, image, command, limits=None):
    lim = limits or limits_from_config()
    return [engine, 'run', '--rm', '--name', name, '--network', 'none', '--pull=never', '--read-only',
            '--tmpfs', '/tmp', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--pids-limit', str(lim['pids_limit']), '--memory', str(lim['memory']), '--cpus', str(lim['cpus']),
            '--user', str(lim['user']),
            '-v', '%s:/frontier/input:ro' % input_dir, '-v', '%s:/frontier/output:rw' % output_dir,
            '-w', '/frontier', image] + list(command)


def _inside(child, parent):
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def read_log(work):
    p = work / 'decision_log.jsonl'
    out = []
    if not p.exists():
        return out
    for line in p.read_text(encoding='utf-8').splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def last_before(work, test):
    bs = [e for e in read_log(work) if e.get('phase') == 'before' and e.get('test') == test]
    return bs[-1] if bs else None


def read_result(work):
    p = work / 'result.json'
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except ValueError:
        return {'mode': 'unreadable'}


def executions_used(work):
    try:
        steps = common.read_json(work / 'run.json').get('steps') or []
    except (OSError, ValueError, AttributeError):
        return 0
    return sum(1 for s in steps if isinstance(s, dict) and s.get('step') == 'execution')


def append_step(work, step):
    p = work / 'run.json'
    try:
        data = common.read_json(p) if p.exists() else {'steps': []}
    except ValueError:
        return False
    if not isinstance(data, dict) or not isinstance(data.get('steps'), list):
        return False
    data['steps'].append(step)
    common.write_json(p, data)
    return True


def no_links(root):
    """Refused when any entry under root (file or directory, any depth) is a symbolic link."""
    for d, dirs, files in os.walk(str(root), followlinks=False):
        for n in dirs + files:
            if os.path.islink(os.path.join(d, n)):
                raise Refused('%s is a symbolic link: refused (no symbolic link inside a mounted directory)'
                              % os.path.join(d, n))


def prepare(work, test):
    # Release note (review round 2): execution is DISABLED by default (config.json "execution_enabled": false). Hard links,
    # an unbounded output/ and the engine probe are not yet hardened or tried on a real engine; tests are delivered as plans.
    if not common.config().get('execution_enabled', False):
        raise Refused('execution is disabled in this release (config.json "execution_enabled": false): the test is '
                      'delivered as a plan ("plan only")')
    if not work.is_dir():
        raise Refused('not a directory: %s' % work)
    if not re.fullmatch(r'T[0-9]+', test or ''):
        raise Refused('--test must be a test id such as T1')
    res = read_result(work)
    if res is not None and res.get('mode') != 'plan only':
        raise Refused('result.json already records an execution (mode %r); it is never overwritten' % res.get('mode'))
    budget = common.config()['budget'].get('executions', 1)
    if executions_used(work) >= budget:
        raise Refused('budget per idea: %d execution(s) already recorded in run.json (config.json budget.executions)'
                      % budget)
    before = last_before(work, test)
    if before is None:
        raise Refused('no "before" entry for %s in decision_log.jsonl: run tools/log.py %s before --test %s first'
                      % (test, work, test))
    try:
        t = common.find_test(common.read_json(work / 'tests.json'), test)
    except (OSError, ValueError) as e:
        raise Refused('tests.json missing or not JSON (%s)' % e)
    if t is None:
        raise Refused('test %s is not in tests.json' % test)
    if not before.get('fingerprint'):
        raise Refused('the last "before" of %s has no fingerprint (written by an old tool or by hand): write a new '
                      '"before" with tools/log.py' % test)
    if before['fingerprint'] != common.fingerprint(t):
        raise Refused('the protocol of %s changed after its last "before" (fingerprint differs): the decision rule '
                      'and predictions executed must be those frozen before; write a new "before" first' % test)
    root = work.resolve()
    ex = work / 'exec' / test
    if ex.is_symlink() or (work / 'exec').is_symlink() or not ex.is_dir() or not _inside(ex.resolve(), root):
        raise Refused('test directory %s missing, outside the working directory, or a symbolic link' % ex)
    ex_r = ex.resolve()
    dirs = {}
    for sub in ('input', 'output'):
        d = ex / sub
        if d.is_symlink():
            raise Refused('%s is a symbolic link: refused (no mount outside the test directory)' % d)
        if sub == 'output' and not d.exists():
            d.mkdir()
        real = Path(os.path.realpath(str(d)))
        if not real.is_dir() or real.parent != ex_r or not _inside(real, ex_r):
            raise Refused('%s must be a real directory inside %s' % (d, ex))
        if ':' in str(real) or ',' in str(real):
            raise Refused('the path %s contains ":" or ",", which a bind mount cannot express' % real)
        no_links(real)
        dirs[sub] = real
    try:
        spec = json.loads((ex / 'spec.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise Refused('%s/spec.json missing or not JSON (%s)' % (ex, e))
    image, command = spec.get('image'), spec.get('command')
    if not valid_image(image):
        raise Refused('spec.json: "image" %r is not a valid local image reference (^[a-z0-9][a-z0-9._/:@-]*$, no '
                      'leading "-", no space, no option)' % (image,))
    if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
        raise Refused('spec.json: "command" must be a non-empty list of strings')
    return dirs['input'], dirs['output'], image, command, spec, before


class CappedReader(threading.Thread):
    """Read a pipe to its end, keeping only the last `cap` bytes and counting the total."""

    def __init__(self, pipe, cap):
        super().__init__(daemon=True)
        self.pipe, self.cap = pipe, cap
        self.buf = bytearray()
        self.total = 0

    def run(self):
        try:
            for chunk in iter(lambda: self.pipe.read(65536), b''):
                self.total += len(chunk)
                self.buf += chunk
                if len(self.buf) > self.cap:
                    del self.buf[:len(self.buf) - self.cap]
        except (OSError, ValueError):
            pass

    def text(self):
        data = bytes(self.buf)
        s = data.decode('utf-8', 'ignore')
        while len(s.encode('utf-8')) > self.cap:
            s = s[1:]
        return s


def run_capped(cmd, env, timeout, cap, on_timeout):
    """(exit code or None, timed_out, stdout reader, stderr reader); output never held beyond `cap` bytes per stream."""
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out, err = CappedReader(p.stdout, cap), CappedReader(p.stderr, cap)
    out.start()
    err.start()
    timed_out = False
    try:
        code = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        on_timeout()
        p.kill()
        code = None
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass
    out.join(timeout=30)
    err.join(timeout=30)
    for f in (p.stdout, p.stderr):
        try:
            f.close()
        except OSError:
            pass
    return code, timed_out, out, err


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir')
    ap.add_argument('--test', required=True)
    ap.add_argument('--engine', choices=list(ENGINES))
    ap.add_argument('--timeout', type=int)
    a = ap.parse_args(argv)
    work = Path(a.dir)
    name, exe = find_engine(a.engine)
    if not exe:
        reason = 'no isolated container engine (%s) found on PATH' % (a.engine or 'docker or podman')
        wrote = False
        if work.is_dir() and read_result(work) is None:
            common.write_json(work / 'result.json', {'mode': 'plan only', 'reason': reason})
            wrote = True
        print(json.dumps({'status': 'refused', 'reason': reason, 'result_json_written': wrote}))
        return 3
    env = engine_env(os.environ)
    try:
        limits = limits_from_config()
        input_dir, output_dir, image, command, spec, before = prepare(work, a.test)
        try:
            r = subprocess.run([exe, 'image', 'inspect', image], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, env=env, timeout=60)
            present = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            present = False
        if not present:
            raise Refused('image %s is not present locally (`%s image inspect` failed); Frontier never pulls: run '
                          '`%s pull %s` yourself if you trust it' % (image, name, name, image))
    except Refused as e:
        print(json.dumps({'status': 'refused', 'reason': str(e)}))
        return 2
    cfg = common.config()
    timeout = a.timeout or spec.get('timeout_s') or cfg.get('run_timeout_s') or 600
    cname = 'frontier-%s-%s' % (a.test.lower(), uuid.uuid4().hex[:8])
    cmd = build_command(exe, cname, input_dir, output_dir, image, command, limits)

    def kill():
        try:
            subprocess.run([exe, 'kill', cname], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, env=env, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass
    started, t0 = utc_now(), time.monotonic()
    code, timed_out, out, err = run_capped(cmd, env, timeout, limits['output_cap_bytes'], kill)
    duration = round(time.monotonic() - t0, 3)
    files = sorted(str(p.relative_to(output_dir.parent)) for p in output_dir.rglob('*') if p.is_file())[:50]
    cap = limits['output_cap_bytes']
    result = {
        'mode': 'executed', 'test': a.test, 'engine': name, 'image': image, 'command': [name] + cmd[1:],
        'before_fingerprint': before['fingerprint'], 'before_utc': before.get('utc'),
        'environment_note': ENV_NOTE, 'limits': limits,
        'execution': {'started_utc': started, 'ended_utc': utc_now(), 'duration_s': duration, 'exit_code': code,
                      'timed_out': timed_out, 'stdout_tail': out.text(), 'stderr_tail': err.text(),
                      'stdout_bytes': out.total, 'stderr_bytes': err.total,
                      'stdout_truncated': out.total > cap, 'stderr_truncated': err.total > cap,
                      'output_files': files},
        'observed': None, 'decision': None, 'decision_rule_applied': None,
    }
    common.write_json(work / 'result.json', result)
    logged = append_step(work, {'step': 'execution', 'utc': utc_now(), 'duration_s': duration, 'cost_usd': 'unknown',
                                'note': 'measured by tools/run_test.py (%s, %s)' % (name, a.test)})
    print(json.dumps({'status': 'timed_out' if timed_out else 'executed', 'exit_code': code,
                      'result': str((work / 'result.json').resolve()), 'run_json_step': logged,
                      'next': 'read exec/%s/output, write "observed", apply the decision rule fixed before ("decision", '
                              '"decision_rule_applied"), then tools/log.py <dir> after --test %s, then tools/card.py'
                              % (a.test, a.test)}))
    return 4 if timed_out else 0


if __name__ == '__main__':
    sys.exit(main())
