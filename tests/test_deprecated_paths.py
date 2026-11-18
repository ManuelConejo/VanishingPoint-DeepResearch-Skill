# SPDX-License-Identifier: Apache-2.0
"""Offline public-path transitions: arguments, stderr and exit codes."""
import pathlib, subprocess, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Transitions(unittest.TestCase):
    def test_help_and_argument_errors_match_current_scripts(self):
        for old, new in (('tools/read_possibles.py', 'tools/read_candidates.py'),
                         ('frontier/tools/tournoi.py', 'frontier/tools/tournament.py')):
            for args in (['--help'], ['--invalid-transition-option']):
                with self.subTest(old=old, args=args):
                    current = subprocess.run([sys.executable, '-I', str(ROOT / new), *args], capture_output=True, text=True)
                    legacy = subprocess.run([sys.executable, '-I', str(ROOT / old), *args], capture_output=True, text=True)
                    self.assertEqual(legacy.returncode, current.returncode)
                    self.assertEqual(legacy.stdout, current.stdout)
                    self.assertEqual(legacy.stderr, 'deprecated path, use ' + new + '\n' + current.stderr)
                    self.assertEqual(current.returncode, 0 if args == ['--help'] else 2)


if __name__ == '__main__':
    unittest.main()
