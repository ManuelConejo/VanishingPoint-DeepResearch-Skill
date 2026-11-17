# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for the Frontier tests: tool loading, synthetic working directories, fake container engines.

No network, no model call, no real container: engines are fake executables written into a temporary directory.
"""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .sandbox import register_script

HERE = Path(__file__).resolve().parent
FRONTIER = HERE.parent
TOOLS = FRONTIER / 'tools'
FIXTURES = HERE / 'fixtures'
HEADER = 'References not verified (VP not installed)'


def load_tool(name):
    """Import frontier/tools/<name>.py as a module (the tools import each other from their own directory)."""
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location('frontier_tool_' + name, str(TOOLS / (name + '.py')))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_tool(name, *args, env=None, cwd=None, timeout=120, tools_dir=None):
    tdir = Path(tools_dir) if tools_dir else TOOLS
    cmd = [sys.executable, '-I', str(tdir / (name + '.py'))] + [str(a) for a in args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd, timeout=timeout)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def mutate(work, filename, fn):
    """Load <work>/<filename>, apply fn(data) in place (its return value is ignored), write it back."""
    p = Path(work) / filename
    data = read_json(p)
    fn(data)
    write_json(p, data)


def make_fake_engine(bindir, name='docker', run_exit=0, sleep=0.0, image_present=True, version_ok=True, big_stdout=0):
    """Write a fake docker/podman executable that records its argv and environment keys in <bindir>/calls.jsonl.

    big_stdout: number of extra bytes ("x") the fake `run` writes to stdout after "fake run ok" (output cap tests)."""
    bindir = Path(bindir)
    bindir.mkdir(parents=True, exist_ok=True)
    script = (
        '#!' + sys.executable + '\n'
        'import json, os, sys, time\n'
        'from pathlib import Path\n'
        'here = Path(__file__).resolve().parent\n'
        'with open(str(here / "calls.jsonl"), "a") as f:\n'
        '    f.write(json.dumps({"argv": sys.argv[1:], "env": sorted(os.environ)}) + "\\n")\n'
        'args = sys.argv[1:]\n'
        'if args[:2] == ["image", "inspect"]:\n'
        '    sys.exit(0 if %r else 1)\n'
        'if args[:1] in (["version"], ["info"]):\n'
        '    sys.exit(0 if %r else 1)\n'
        'if args[:1] == ["run"]:\n'
        '    time.sleep(%r)\n'
        '    print("fake run ok")\n'
        '    big = %d\n'
        '    while big > 0:\n'
        '        k = min(big, 65536)\n'
        '        sys.stdout.write("x" * k)\n'
        '        big -= k\n'
        '    sys.stdout.write("\\nEND-OF-OUTPUT\\n")\n'
        '    sys.stdout.flush()\n'
        '    sys.exit(%r)\n'
        'sys.exit(0)\n'
    ) % (image_present, version_ok, float(sleep), int(big_stdout), int(run_exit))
    p = bindir / name
    p.write_text(script, encoding='utf-8')
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    register_script(p)
    return p


def copy_skill(dest_parent, name='frontier'):
    """Copy the skill (without its tests) into <dest_parent>/<name>; returns the copy (its tools/ and config.json)."""
    dest = Path(dest_parent) / name
    shutil.copytree(str(FRONTIER), str(dest),
                    ignore=shutil.ignore_patterns('tests', '.venv', '__pycache__', 'config.local.json'))
    return dest


def set_config(skill_dir, fn):
    """Apply fn(config) in place to <skill_dir>/config.json."""
    mutate(skill_dir, 'config.json', fn)


def fake_calls(bindir):
    p = Path(bindir) / 'calls.jsonl'
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]


class TempCase(unittest.TestCase):
    """A test case with a fresh temporary directory and a copy of all fixtures."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='frontier-test-'))
        self.fx = self.tmp / 'fx'
        shutil.copytree(str(FIXTURES), str(self.fx))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def fresh(self):
        """Start again from pristine fixtures (used inside subTest loops)."""
        self.tearDown()
        self.setUp()

    def work(self, name='valid_vp'):
        return self.fx / name

    def empty_path_env(self, bindir=None):
        """Environment for a subprocess whose PATH holds only <bindir> (or an empty directory)."""
        d = Path(bindir) if bindir else self.tmp / 'emptybin'
        d.mkdir(parents=True, exist_ok=True)
        env = {'PATH': str(d), 'HOME': str(self.tmp)}
        if os.environ.get('SYSTEMROOT'):
            env['SYSTEMROOT'] = os.environ['SYSTEMROOT']
        return env
