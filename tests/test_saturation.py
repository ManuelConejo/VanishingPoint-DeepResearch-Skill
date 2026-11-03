#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""tools/saturation.py: waves closed from searches/*.md and the gateway journal, the stopping rule of SKILL.md section 4 (two consecutive
empty waves of at least the minimum calls, or the ceiling), other pools left out, Chapman indicator, command line."""
import json, pathlib, subprocess, sys, tempfile, unittest

TOOLS = pathlib.Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(TOOLS))
import saturation as S  # noqa: E402


class Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = pathlib.Path(self.tmp.name)
        (self.d / 'searches').mkdir(); (self.d / 'state').mkdir()

    def tearDown(self): self.tmp.cleanup()

    def wave(self, name, ids, calls, pool_calls=0, **kw):
        lines = [f'- arxiv:{i} | title | 2025 | basis title | PROBABLE. on topic' for i in ids] + ['- arxiv:2401.99999 | t | 2025 | EXCLUDED. off topic']
        (self.d / 'searches' / name).write_text('# ' + name + '\n\n## Candidates\n' + '\n'.join(lines) + '\n')
        with open(self.d / 'state' / 'journal.jsonl', 'a') as f:
            for _ in range(calls): f.write(json.dumps({'call': 'search-arxiv'}) + '\n')
            for _ in range(pool_calls): f.write(json.dumps({'call': 'read', 'pool': 'verifier'}) + '\n')
        return S.run(self.d, close=True, **kw)

    def test_two_empty_waves_stop(self):
        r = self.wave('1.md', ['2401.00001', '2401.00002'], 6, pool_calls=3, min_calls=4)
        self.assertEqual((r['decision'], r['waves'][0]['calls'], r['eligible_total']), ('continue', 6, 2))   # EXCLUDED and verifier pool left out
        self.assertEqual(self.wave('2.md', ['2401.00002'], 4)['decision'], 'continue')                       # one empty wave
        r = self.wave('3.md', ['2401.00001'], 5)
        self.assertEqual(r['decision'], 'stop'); self.assertIn('wave 3: 5 calls, 0 new', r['scope_line'])

    def test_short_empty_wave_proves_nothing(self):
        self.wave('1.md', ['2401.00001'], 6, min_calls=4); self.wave('2.md', ['2401.00001'], 4)
        r = self.wave('3.md', ['2401.00001'], 2)
        self.assertEqual(r['decision'], 'continue'); self.assertIn('fewer than 4 calls', r['reason'])

    def test_new_document_resets(self):
        self.wave('1.md', ['2401.00001'], 6, min_calls=4); self.wave('2.md', ['2401.00001'], 4)
        self.assertEqual(self.wave('3.md', ['2401.00003'], 4)['decision'], 'continue')

    def test_ceiling(self):
        self.assertEqual(self.wave('1.md', ['2401.00001'], 10, min_calls=4, cap=10)['decision'], 'ceiling')

    def test_chapman_indicator(self):
        self.wave('1.md', ['2401.00001', '2401.00002', '2401.00003'], 6, min_calls=4)
        c = self.wave('2.md', ['2401.00002', '2401.00003', '2401.00004'], 4)['chapman']
        self.assertEqual((c['n1'], c['n2'], c['m'], c['N']), (3, 3, 2, 4.3)); self.assertTrue(c['indicator_only'])

    def test_command_line(self):
        cmd = [sys.executable, '-I', str(TOOLS / 'saturation.py'), '--dir', str(self.d), '--close-wave']
        r = subprocess.run(cmd, capture_output=True, text=True); self.assertEqual(r.returncode, 2); self.assertIn('--min-calls', r.stderr)
        r = subprocess.run(cmd + ['--min-calls', '4'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(json.loads(r.stdout)['waves'][0]['wave'], 1)
        r = subprocess.run(cmd[:-1], capture_output=True, text=True)                                           # no closure: nothing written
        self.assertEqual(len(json.loads(r.stdout)['waves']), 1)


if __name__ == '__main__':
    unittest.main()
