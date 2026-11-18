# SPDX-License-Identifier: Apache-2.0
"""Rebound is an explicit handoff; the standard VP workflow stays unchanged."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReboundOptionTest(unittest.TestCase):
    def section(self):
        text = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        match = re.search(r'^## Rebound \(optional, never by default\)\n(.*?)(?=^## |\Z)',
                          text, re.M | re.S)
        self.assertIsNotNone(match, 'VP must expose the optional Rebound section')
        return match.group(0).rstrip()

    def test_explicit_only_and_short(self):
        section = self.section()
        self.assertLess(len(section.splitlines()), 12)
        for phrase in ('**When.**', 'explicit request', 'never by default', 'never inside a normal VP run',
                       'rebound', 'what could I try next', 'neighbouring ideas',
                       'how would I test this idea', 'help me advance this idea'):
            self.assertIn(phrase, section)

    def test_handoff_and_honest_measure(self):
        section = self.section()
        for phrase in ('**What it does.**', 'frontier/SKILL.md', 'as written', 'prior art',
                       'executed test results',
                       '**Cost and measure.**', 'models', 'three starting ideas', 'no executed test',
                       'not a measured claim'):
            self.assertIn(phrase, section)

    def test_inventory_readme_and_rebound_release(self):
        text = (ROOT / 'SKILL.md').read_text(encoding='utf-8')
        inventory = next(line for line in text.splitlines() if line.startswith('**Inventory'))
        self.assertIn('`frontier/`', inventory)
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertRegex(readme, r'(?im)^.*rebound.*optional.*frontier/SKILL\.md.*$')
        self.assertIn('executed test results', readme)
        changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        released = re.search(r'^## v0\.6\.28\b[^\n]*\n(.*?)(?=^## |\Z)', changelog, re.M | re.S)
        self.assertIsNotNone(released)
        self.assertIn('Rebound', released.group(1))
        self.assertIn('executed test results', released.group(1))


if __name__ == '__main__':
    unittest.main()
