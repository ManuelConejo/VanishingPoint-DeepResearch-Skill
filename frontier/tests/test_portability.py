# SPDX-License-Identifier: Apache-2.0
"""Portability: Python 3.9 syntax, standard library only, no network module, no Linux-only path (regression specification R4, R30)."""
import ast
import sys
import unittest

from .helpers import TOOLS

STDLIB_39 = {
    'argparse', 'ast', 'copy', 'datetime', 'hashlib', 'importlib', 'io', 'json', 'math', 'os', 'pathlib', 'platform',
    'random', 're', 'shutil', 'statistics', 'stat', 'string', 'subprocess', 'sys', 'tempfile', 'textwrap', 'time',
    'unicodedata', 'uuid', 'venv', 'collections', 'itertools', 'functools', 'typing', 'dataclasses', 'contextlib',
    'threading', 'fcntl',
}
NETWORK = {'socket', 'urllib', 'http', 'ftplib', 'smtplib', 'requests', 'ssl', 'asyncio', 'xmlrpc', 'telnetlib'}
# round 2: the tools also import each other (common, sim, setup)
# rebound round: check.py imports rebound.py (duplicate groups, quotas, tree)
# AM1 round (modification of an existing test, declared in RAPPORT-AM1.md): the new tools import each other and common
# round 3 (modification of an existing test, declared in RAPPORT-R3.md): guards.py and r3check.py are local tools too
# v2 round (modification of an existing test, declared in RAPPORT-V2.md): v2check, framing, research and named are local tools too
# V4: these two modules are local tools, subject to the same stdlib/network checks.
LOCAL = {'schema_lite', 'check', 'common', 'sim', 'setup', 'rebound', 'hybrid', 'matter', 'gwclient', 'catalogue', 'context',
         'card', 'guards', 'r3check', 'v2check', 'v3check', 'v4check', 'overlap', 'framing', 'research', 'named',
         'disclaimer', 'tournament', 'input_names'}


def tool_files():
    return sorted(TOOLS.glob('*.py'))


def imports(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split('.')[0])
    return out


class PortabilityTest(unittest.TestCase):
    def test_tools_exist(self):
        names = {p.stem for p in tool_files()}
        for n in ('setup', 'new_run', 'check', 'sim', 'run_test', 'card', 'log', 'schema_lite', 'pack_critique',
                  'common', 'step', 'export_judge'):
            self.assertIn(n, names)

    def test_python39_syntax(self):
        for p in tool_files():
            with self.subTest(tool=p.name):
                ast.parse(p.read_text(encoding='utf-8'), filename=str(p), feature_version=(3, 9))

    def test_stdlib_only(self):
        std = set(getattr(sys, 'stdlib_module_names', ())) | STDLIB_39
        for p in tool_files():
            with self.subTest(tool=p.name):
                mods = imports(ast.parse(p.read_text(encoding='utf-8')))
                self.assertEqual(sorted(m for m in mods if m not in std and m not in LOCAL), [])

    def test_no_network_modules(self):
        for p in tool_files():
            with self.subTest(tool=p.name):
                mods = imports(ast.parse(p.read_text(encoding='utf-8')))
                self.assertEqual(sorted(mods & NETWORK), [])

    def test_no_linux_only_paths_or_gnu_commands(self):
        bad = ["'/proc", '"/proc', "'/usr/bin", '"/usr/bin', "'/tmp", '"/tmp', "'/dev/shm", 'readlink -f',
               "'sed'", "'awk'", "'xargs'", "'grep'", "'bash'", 'shell=True', "'/bin/sh'"]
        # container-side paths (inside the isolated container, never on the host) are allowed explicitly
        container_side = ["'--tmpfs', '/tmp'"]
        for p in tool_files():
            text = p.read_text(encoding='utf-8')
            for c in container_side:
                text = text.replace(c, '')
            with self.subTest(tool=p.name):
                self.assertEqual([b for b in bad if b in text], [])

    def test_shebang_and_entry(self):
        for p in tool_files():
            text = p.read_text(encoding='utf-8')
            with self.subTest(tool=p.name):
                self.assertTrue(text.startswith('#!/usr/bin/env python3'), 'portable shebang')


if __name__ == '__main__':
    unittest.main()
