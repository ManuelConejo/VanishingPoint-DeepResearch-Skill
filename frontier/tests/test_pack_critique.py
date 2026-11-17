# SPDX-License-Identifier: Apache-2.0
"""pack_critique.py: material for the critique of the test PROTOCOL by another model family (regression specification R29)."""
import hashlib
import json
import unittest

from .helpers import FRONTIER, TempCase, run_tool


class PackCritiqueTest(TempCase):
    def test_subagent_pack(self):
        w = self.work('valid_novp')
        r = run_tool('pack_critique', w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        pack = w / 'critique-pack'
        protocol = (pack / 'PROTOCOL.md').read_text(encoding='utf-8')
        prompt = (pack / 'PROMPT.md').read_text(encoding='utf-8')
        self.assertIn('T1', protocol)
        self.assertIn('R1', protocol)
        self.assertIn('Decision rule', protocol)
        self.assertIn('protocol', prompt.lower())
        self.assertIn('critique.json', prompt)
        self.assertFalse((pack / 'REPORT.md').exists())
        self.assertIn('prompt', out)

    def test_vp_contradictor_pack(self):
        w = self.work('valid_vp')
        r = run_tool('pack_critique', w, '--vp-run', 'prior_art')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pack = w / 'critique-pack'
        self.assertTrue((pack / 'REPORT.md').exists())
        self.assertTrue((pack / 'card.json').exists())
        self.assertTrue((pack / 'sources' / 'S1' / 'source.txt').exists())
        out = json.loads(r.stdout)
        self.assertIn('contradictor.py', out['vp_command'])
        self.assertIn('--mode general', out['vp_command'])

    def test_vp_route_receives_protocol_prompt(self):
        """R50: the VP contradictor route receives prompts/CRITIQUE-PROTOCOL.md, through REPORT.md and --request."""
        w = self.work('valid_vp')
        r = run_tool('pack_critique', w, '--vp-run', 'prior_art')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        prompt = (FRONTIER / 'prompts' / 'CRITIQUE-PROTOCOL.md').read_text(encoding='utf-8').strip()
        report = (w / 'critique-pack' / 'REPORT.md').read_text(encoding='utf-8')
        self.assertTrue(report.startswith(prompt.splitlines()[0]))
        self.assertIn(prompt, report)
        cmd = json.loads(r.stdout)['vp_command']
        self.assertIn('--request', cmd)
        self.assertIn('CRITIQUE-PROTOCOL', cmd)
        self.assertIn('--T 2026-11-14', cmd)

    def test_prompt_asks_trap_verdicts_and_raw_output(self):
        """R46, R48: the critic returns a verdict per trap; its raw answer is kept with its SHA-256."""
        w = self.work('valid_novp')
        r = run_tool('pack_critique', w)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        prompt = (w / 'critique-pack' / 'PROMPT.md').read_text(encoding='utf-8')
        self.assertIn('trap_verdicts', prompt)
        for v in ('addressed', 'not_addressed', 'unclear'):
            self.assertIn(v, prompt)
        out = json.loads(r.stdout)
        self.assertIn('raw_output', out)
        self.assertIn('critique-raw.txt', out['raw_output'])

    def test_receipt_of_raw_output(self):
        w = self.work('valid_novp')
        r = run_tool('pack_critique', w, '--receipt', 'critique-raw.txt')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['raw_output'], 'critique-raw.txt')
        self.assertEqual(out['raw_sha256'], hashlib.sha256((w / 'critique-raw.txt').read_bytes()).hexdigest())
        bad = run_tool('pack_critique', w, '--receipt', '../valid_vp/critique-raw.json')
        self.assertEqual(bad.returncode, 2)

    def test_unknown_vp_run(self):
        r = run_tool('pack_critique', self.work('valid_vp'), '--vp-run', 'nope')
        self.assertEqual(r.returncode, 2)

    def test_missing_tests_json(self):
        w = self.work('valid_novp')
        (w / 'tests.json').unlink()
        r = run_tool('pack_critique', w)
        self.assertEqual(r.returncode, 2)


if __name__ == '__main__':
    unittest.main()
