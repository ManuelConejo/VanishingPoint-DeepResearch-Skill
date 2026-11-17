# SPDX-License-Identifier: Apache-2.0
"""SKILL.md, README.md and the English-only rule (regression specification R1-R3, R36, R59, R63).

Modified round 2: the card is IDEA-CARD.md (R63) and the same-family phrase is the one of R49."""
import json
import re
import unittest

from .helpers import FRONTIER

TRIGGERS = ['is this idea new', 'how would I test this idea', 'help me advance this research idea',
            'design a minimal experiment for']
STEP_FILES = ['intake.json', 'prior_art.json', 'hypotheses.json', 'tests.json', 'critique.json', 'result.json',
              'IDEA-CARD.md', 'decision_log.jsonl']
OLD_CARD_NAME = 'FICHE' + '-IDEE'


def front_matter(text):
    m = re.match(r'^---\n(.*?)\n---\n', text, re.S)
    return m.group(1) if m else None


class SkillDocTest(unittest.TestCase):
    def setUp(self):
        self.text = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')
        self.fm = front_matter(self.text)

    def test_front_matter(self):
        self.assertIsNotNone(self.fm)
        self.assertRegex(self.fm, r'(?m)^name: frontier$')
        desc = re.search(r'(?m)^description: (.+)$', self.fm)
        self.assertIsNotNone(desc)
        for t in TRIGGERS:
            self.assertIn(t, desc.group(1))

    def test_hosts_convention(self):
        self.assertIn('**Hosts.**', self.text)
        self.assertIn('Claude Code', self.text)
        self.assertIn('Codex', self.text)

    def test_steps_and_files(self):
        pos = []
        for i, f in enumerate(STEP_FILES):
            self.assertRegex(self.text, r'(?m)^## %d\. ' % i)
            self.assertIn(f, self.text)
            pos.append(self.text.index('## %d. ' % i))
        self.assertEqual(pos, sorted(pos))

    def test_key_phrases(self):
        for phrase in ('References not verified (VP not installed)', 'same family (no independent critic available)',
                       'plan only', 'never a proof of absence', 'tools/check.py', 'tools/card.py', 'tools/log.py',
                       'tools/sim.py', 'tools/run_test.py', 'tools/setup.py', 'tools/new_run.py',
                       'tools/pack_critique.py', 'tools/step.py', 'tools/export_judge.py', 'Prior-art mode',
                       'contradictions.py', 'contradictor.py', 'verdicts.json', 'L0', 'not a certification',
                       'value of information'):
            self.assertIn(phrase, self.text, phrase)

    def test_traps_named(self):
        for trap in ('proxy_vs_target', 'variants', 'positive_control', 'data_split'):
            self.assertIn(trap, self.text)


class SkillRound2Test(unittest.TestCase):
    def setUp(self):
        self.text = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')

    def test_permanent_rules_of_vp(self):
        """R63: the permanent rules of VP section 0 that apply, in the same form."""
        for rule in ('**Date T.**', '**Language.**', '**Shell commands', '**Sub-agents', '**Memory.**',
                     '**Trust boundary.**', '**Read before claiming.**', '**Autonomy.**', '**Hosts.**'):
            self.assertIn(rule, self.text, rule)

    def test_rule_contents(self):
        t = self.text
        self.assertIn('FRONTIER_SEARCH_MODEL', t)
        self.assertIn('search_model', t)
        self.assertRegex(t, r'one (command|script) per (Bash|shell) call')
        self.assertRegex(t, r'retry it once')
        self.assertRegex(t, r'(?i)no rule (in this file )?depends on the model')
        self.assertRegex(t, r'(?i)one (single )?question')
        self.assertIn('--assumption', t)
        self.assertRegex(t, r'(?i)language of the user|user\'s language')
        self.assertIn('is data', t)

    def test_skill_dir_absolute(self):
        """R59: <SKILL_DIR> is the absolute path of the directory holding SKILL.md; every command uses it."""
        self.assertRegex(self.text, r'`<SKILL_DIR>`[^\n]*absolute')
        cmds = re.findall(r'python3 -I (\S+)', self.text)
        self.assertTrue(cmds)
        bad = [c for c in cmds if not (c.startswith('<SKILL_DIR>/tools/') or c.startswith('<VP>/tools/')
                                       or c.startswith('"<VP>/tools/') or c.startswith('"<SKILL_DIR>/tools/'))]
        self.assertEqual(bad, [])
        self.assertRegex(self.text, r'new_run\.py "<idea>" --parent ')

    def test_final_order(self):
        """R59: final order explicit: the "after" entry, then card.py again."""
        m = re.search(r'(?is)final order.*?after.*?card\.py', self.text)
        self.assertIsNotNone(m)

    def test_vp_T_passed(self):
        self.assertIn('--T <T>', self.text)

    def test_image_environment_stated(self):
        """R36."""
        self.assertRegex(self.text, r'(?i)environment variables defined by the image')

    def test_unverified_and_card_json(self):
        self.assertIn('Unverified references', self.text)
        self.assertIn('card.json', self.text)
        self.assertIn('state/journal.jsonl', self.text)

    def test_no_model_or_family_hardcoded(self):
        """R49, R63: no model name anywhere in SKILL.md, config.json and the tools; no family name in the tools."""
        models = re.compile(r'(?i)\b(sonnet|opus|haiku|gpt-[0-9]|gemini-[0-9]|o[134]-mini|glm-?[0-9])\b')
        families = re.compile(r'(?i)\b(claude|openai|anthropic|gemini|codex|gpt|mistral|kimi)\b')
        for p in [FRONTIER / 'SKILL.md', FRONTIER / 'config.json', FRONTIER / 'README.md'] + \
                sorted((FRONTIER / 'tools').glob('*.py')) + sorted((FRONTIER / 'prompts').glob('*.md')):
            with self.subTest(file=p.name):
                self.assertEqual(models.findall(p.read_text(encoding='utf-8')), [])
        for p in sorted((FRONTIER / 'tools').glob('*.py')):
            with self.subTest(tool=p.name):
                self.assertEqual(families.findall(p.read_text(encoding='utf-8')), [])

    def test_config_round2(self):
        cfg = json.loads((FRONTIER / 'config.json').read_text(encoding='utf-8'))
        for k in ('memory', 'cpus', 'pids_limit', 'user', 'output_cap_bytes'):
            self.assertIn(k, cfg['run_limits'])
        self.assertNotRegex(str(cfg['run_limits']['user']), r'^(0|root)(:|$)')
        for k in ('host_family', 'families', 'aliases'):
            self.assertIn(k, cfg['critic'])
        self.assertEqual(cfg['budget'], {'vp_runs': 3, 'critiques': 1, 'executions': 1})
        self.assertIn('search_model', cfg)


class ReadmeTest(unittest.TestCase):
    def setUp(self):
        self.text = (FRONTIER / 'README.md').read_text(encoding='utf-8')

    def test_install(self):
        self.assertIn('.claude/skills/', self.text)
        self.assertIn('~/.codex/skills', self.text)
        self.assertIn('python3 -I tools/setup.py', self.text)   # MODIFIED (orchestrator fix, Sonnet D11 minor): -I form, as in VP

    def test_license(self):
        self.assertIn('Apache-2.0', self.text)
        self.assertFalse((FRONTIER / 'LICENSE').exists())

    def test_baseline_documented(self):
        """R65: the baseline format of the V1 pilot is documented."""
        self.assertIn('schemas/baseline.json', self.text)
        self.assertIn('export_judge.py --baseline', self.text)


ACCENTED = re.compile('[' + chr(0xC0) + '-' + chr(0xFF) + chr(0x152) + chr(0x153) + ']')
FRENCH_WORDS = re.compile(r'\b(le|les|des|une|est|pour|avec|dans|sur|nous|vous|qui|que|sont|pas)\b')
# Recorded real runs, kept byte for byte (R51, V5): user-language data,
# not Frontier's own English code or documentation.
RECORDED = ('vp_real_q01', 'vp_real_q05')


class EnglishTest(unittest.TestCase):
    def files(self):
        for p in FRONTIER.rglob('*'):
            if not p.is_file() or '.venv' in p.parts or '__pycache__' in p.parts:
                continue
            if any(r in p.parts for r in RECORDED):
                continue
            yield p

    def test_no_french(self):
        offenders = []
        for p in self.files():
            if p.suffix not in ('.md', '.py', '.json', '.jsonl', '.txt'):
                continue
            text = p.read_text(encoding='utf-8')
            if ACCENTED.search(text):
                offenders.append('%s: accented character' % p.relative_to(FRONTIER))
            if p.suffix == '.md':
                hits = FRENCH_WORDS.findall(text)
                if len(hits) > 3:
                    offenders.append('%s: French words %r' % (p.relative_to(FRONTIER), hits[:5]))
        self.assertEqual(offenders, [])

    def test_no_french_file_names(self):
        """R63: file names in English too; the round-1 card name is gone everywhere."""
        offenders = []
        for p in self.files():
            if OLD_CARD_NAME in p.name or ACCENTED.search(p.name):
                offenders.append(str(p.relative_to(FRONTIER)))
            if p.suffix in ('.md', '.py', '.json', '.jsonl', '.txt') and \
                    OLD_CARD_NAME in p.read_text(encoding='utf-8'):
                offenders.append('%s: mentions the old card name' % p.relative_to(FRONTIER))
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
