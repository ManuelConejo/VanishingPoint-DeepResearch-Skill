#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""tools/verifier/numbers_check.py: figures of a claim against its fragments (precision of the claim, % <-> proportion, readings of a
comma, labels and years skipped), and the replay on the shipped example (no false flag on its FOUND claims)."""
import json, pathlib, subprocess, sys, unittest

TOOLS = pathlib.Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(TOOLS / 'verifier'))
import numbers_check as N  # noqa: E402


class Test(unittest.TestCase):
    def test_precision_of_the_claim(self):
        self.assertEqual(N.problems('accuracy of 42 %', ['accuracy 41.87%']), [])
        self.assertEqual(len(N.problems('accuracy of 43 %', ['accuracy 41.87%'])), 1)
        self.assertEqual(len(N.problems('accuracy of 41.87 %', ['accuracy 42%'])), 1)      # more precise than the source: not shown

    def test_percentage_and_proportion(self):
        self.assertEqual(N.problems('F1 of 0.42', ['F1 = 42.1']), [])
        self.assertEqual(N.problems('F1 of 42 %', ['F1 = 0.418']), [])

    def test_comma_readings(self):
        self.assertEqual(N.problems('reaches 0,42 on 1,234 samples', ['0.42 on 1234 samples']), [])
        self.assertEqual(N.problems('reaches 1,5', ['reaches 1.5']), [])

    def test_skipped_figures(self):
        self.assertEqual(N.problems('GPT-4 on AIME 24 (Table 12) in 2023 with 3 seeds, Llama-3-8B', ['nothing numeric']), [])
        self.assertEqual(N.problems('3.5x faster', ['3.5× faster']), [])
        self.assertEqual(len(N.problems('3.5x faster', ['2x faster'])), 1)

    def test_report_formats(self):
        self.assertEqual(N.problems('[12] 2 269 tâches', ['consists of 2,269 real-world tasks']), [])           # citation marker, spaced thousands
        self.assertEqual(N.problems('[19] 16\u202f758 trajectoires', ['Analyzing 16,758 trajectories']), [])
        self.assertEqual(N.problems('effet de +9,8 points', ['richly-specified problems (+9.8pp)']), [])        # unit glued in the fragment
        self.assertEqual(len(N.problems('[24] 43,7 % des chaînes', ['from 12.5% to 20.8 %'])), 1)            # still flagged when absent

    def test_shipped_example_has_no_false_flag(self):
        f = TOOLS.parent / 'examples' / 'report-cs-ai' / 'verdicts.json'
        if not f.exists(): self.skipTest('no shipped example with verdicts.json (examples/report-cs-ai removed after v0.6.18)')
        d = json.loads(f.read_text())
        found = [a for a in d['claims'] if a['status'] == 'FOUND']
        self.assertTrue(found); self.assertEqual([a['id'] for a in found if N.problems(a['text'], a.get('fragments'))], [])

    def test_command_line(self):
        r = subprocess.run([sys.executable, '-I', str(TOOLS / 'verifier' / 'numbers_check.py'), 'up 43 %', 'up 41.9 %'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1); self.assertEqual(len(json.loads(r.stdout)), 1)


if __name__ == '__main__':
    unittest.main()
