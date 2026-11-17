# SPDX-License-Identifier: Apache-2.0
"""Orchestrator fix after review round 2: execution is disabled by default (written after the code: declared)."""
import os, json, subprocess, sys, unittest, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

class ExecutionOffTest(unittest.TestCase):
    def test_default_config_disables_execution(self):
        self.assertIs(json.loads((ROOT / 'config.json').read_text())['execution_enabled'], False)
    def test_run_test_refuses_by_default(self):
        env = {k: v for k, v in os.environ.items() if k != 'FRONTIER_EXECUTION_ENABLED'}
        r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'run_test.py'), '--help'], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        sys.path.insert(0, str(ROOT / 'tools'))
        import importlib, common, run_test
        old = os.environ.pop('FRONTIER_EXECUTION_ENABLED', None)
        try:
            with self.assertRaises(run_test.Refused) as c:
                run_test.prepare(pathlib.Path('/nonexistent-frontier-dir'), 'T1')
            self.assertIn('disabled', str(c.exception))
        finally:
            if old is not None: os.environ['FRONTIER_EXECUTION_ENABLED'] = old
if __name__ == '__main__': unittest.main()
