# SPDX-License-Identifier: Apache-2.0
"""SKILL.md steps 8 and 8-bis, README, the permanent rules kept (regression specification RB1, RB2, RB28, RB29)."""
import re
import unittest

from .helpers import FRONTIER
from .test_docs import front_matter


class Rebound8Test(unittest.TestCase):
    def setUp(self):
        self.text = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')

    def section(self, start, end):
        a = self.text.index(start)
        b = self.text.index(end, a + 1) if end else len(self.text)
        return self.text[a:b]

    def test_headings_and_order(self):
        s7 = self.text.index('## 7. ')
        s8 = self.text.index('## 8. ')
        s8b = self.text.index('## 8-bis. ')
        pilot = self.text.index('## Pilot tools')
        self.assertTrue(s7 < s8 < s8b < pilot)

    def test_step_8_content(self):
        sec = self.section('## 8. ', '## 8-bis. ')
        for phrase in ('rebound.json', 'IDEA-TREE.json', 'tools/rebound.py', 'schemas/rebound.json', 'facet_recombination',
                       'analogy', 'literature_bridge', 'anomaly', 'revived_old_idea', 'hypothesis_inversion',
                       'morphological_analysis', 'recurring_ingredient', 'not measured', '5 to 10', 'at most 2 per operator',
                       'before any ranking', 'Exists', 'Partially', 'Not found', 'Insufficient search', 'not checked',
                       'already done: read, do not redo', 'never a proof of absence', 'unverified',
                       'no numeric novelty score', 'not established', 'duplicate_groups', 'mechanism', 'hypothesis',
                       'minimal test', 'The researcher chooses', '0 to 2', 'rebound_vp_run', 'prior_art_checks_max',
                       'tools/step.py', 'tools/check.py', 'tools/card.py'):
            self.assertIn(phrase, sec, phrase)

    def test_step_8_bis_content(self):
        sec = self.section('## 8-bis. ', '## Pilot tools')
        for phrase in ('rebound_after.json', '2 to 4', 'at most 2 per operator', 'after', 'refuted', 'confirmed',
                       'competing_explanation', 'repairable_variant', 'scope_extension', 'transfer', 'follow_up_kind',
                       'decision_log.jsonl', 'outcome', 'same rules'):
            self.assertIn(phrase, sec, phrase)

    def test_evidence_scope_is_stated(self):
        sec = self.section('## 8. ', '## 8-bis. ')
        self.assertRegex(sec, r'(?i)recurring ingredients?')
        self.assertRegex(sec, r'(?i)no (efficacy|effectiveness) (figure|number|claim)')
        self.assertRegex(sec, r'(?i)language model.{0,80}(never|no).{0,40}(rank|sort|order)|no model score')

    def test_prospective_validation_and_pilot_tool(self):
        self.assertIn('tools/export_rebound.py', self.text)
        self.assertNotIn('20261114', self.text)          # modified round 2 (RB32): the draw is secret, no public seed
        for arm in ('A', 'B', 'C'):
            self.assertRegex(self.text, r'arm %s' % arm)

    def test_repetition_test_documented(self):
        self.assertIn('tools/rebound.py repeat', self.text)
        self.assertRegex(self.text, r'(?i)three rebounds')
        self.assertRegex(self.text, r'(?i)share of (the )?ideas found again')

    def test_date_barrier_and_memory(self):
        sec = self.section('## 8. ', '## 8-bis. ')
        self.assertRegex(sec, r'(?i)date T')
        self.assertRegex(sec, r'(?i)memory')

    def test_permanent_rules_still_there(self):
        for rule in ('**Date T.**', '**Language.**', '**Shell commands', '**Sub-agents', '**Memory.**',
                     '**Trust boundary.**', '**Read before claiming.**', '**Autonomy.**', '**Hosts.**',
                     '**VP is optional and never modified.**', '**Budget per idea:**'):
            self.assertIn(rule, self.text, rule)

    def test_rebound_commands_follow_the_form(self):
        cmds = re.findall(r'python3 -I (\S+)', self.text)
        self.assertTrue(any(c.startswith('<SKILL_DIR>/tools/rebound.py') for c in cmds))
        self.assertTrue(any(c.startswith('<SKILL_DIR>/tools/export_rebound.py') for c in cmds))
        for c in cmds:
            self.assertTrue(c.startswith(('<SKILL_DIR>/tools/', '<VP>/tools/', '"<VP>/tools/', '"<SKILL_DIR>/tools/')), c)

    def test_front_matter_trigger(self):
        fm = front_matter(self.text)
        desc = re.search(r'(?m)^description: (.+)$', fm).group(1)
        self.assertIn('neighbouring ideas', desc)
        for t in ('is this idea new', 'how would I test this idea'):
            self.assertIn(t, desc)

    def test_does_not_do_section_mentions_rebound(self):
        tail = self.text[self.text.index('## What Frontier does not do'):]
        self.assertRegex(tail, r'(?i)no ranking of neighbouring ideas by (a )?(numeric |model )?(score|note)')

    def test_one_question_rule_kept(self):
        self.assertRegex(self.text, r'(?i)one (single )?question')
        sec = self.section('## 8. ', '## 8-bis. ')
        self.assertNotRegex(sec, r'(?i)ask the user')


class Round2DocsTest(unittest.TestCase):
    """RB47."""

    def setUp(self):
        self.text = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')
        self.readme = (FRONTIER / 'README.md').read_text(encoding='utf-8')
        self.pilot = self.text[self.text.index('## Pilot tools'):self.text.index('## What Frontier does not do')]

    def test_secret_seed_and_separate_key(self):
        for phrase in ('secret', 'os.urandom', '--key', 'outside the export', '--from-key'):
            self.assertIn(phrase, self.pilot, phrase)
        self.assertRegex(self.pilot, r'(?i)never (written )?(in|into) the export')

    def test_uniform_blind_format(self):
        self.assertRegex(self.pilot, r'(?i)prior art is evaluated apart')
        self.assertIn('prior-art-form', self.pilot)
        self.assertIn('references-to-check', self.pilot)

    def test_pilot_subcommands(self):
        for phrase in ('export_rebound.py notes', 'export_rebound.py stats', 'researcher_notes', 'sha256',
                       '--reference-audit', 'prior_art_missed'):
            self.assertIn(phrase, self.pilot, phrase)
        self.assertRegex(self.pilot, r'(?i)publish the hash')

    def test_baselines_are_attested(self):
        for phrase in ('parent_idea', 'vp_runs', 'gateway journal'):
            self.assertIn(phrase, self.pilot, phrase)

    def test_prior_art_registered_and_tied_to_the_journal(self):
        sec = self.text[self.text.index('## 8. '):self.text.index('## 8-bis. ')]
        for phrase in ('one VP run per idea', 'gateway journal', 'not verified: no VP', 'prior_art_checks_card_max',
                       'selection_history'):
            self.assertIn(phrase, self.text, phrase)
        self.assertRegex(sec, r'(?i)every (written )?quer(y|ies).{0,80}journal')

    def test_scope_of_the_evidence_is_complete(self):
        sec = self.text[self.text.index('## 8. '):self.text.index('## 8-bis. ')]
        self.assertRegex(sec, r'(?i)stopped at 60 (search )?calls')
        self.assertRegex(sec, r'(?i)language processing and machine learning')
        self.assertRegex(sec, r'(?i)abstracts')

    def test_retrospective_protocol(self):
        for phrase in ('cut-off date', 'masked', 'L0', 'does not guarantee'):
            self.assertIn(phrase, self.pilot, phrase)
        self.assertRegex(self.pilot, r'(?i)retrospective')

    def test_judge_bias_and_follow_up(self):
        self.assertRegex(self.pilot, r'(?i)single judge')
        self.assertRegex(self.pilot, r'(?i)30-day follow-up')

    def test_no_order_in_disguise_is_documented(self):
        sec = self.text[self.text.index('## 8. '):self.text.index('## 8-bis. ')]
        self.assertRegex(sec, r'(?i)canonical order')
        self.assertRegex(sec, r'(?i)lexical')

    def test_recurring_ingredient_replaces_operator_measured(self):
        for t in (self.text, self.readme):
            self.assertNotIn('operator_measured', t)
        self.assertIn('recurring_ingredient', self.text)

    def test_readme_follows(self):
        for phrase in ('secret', '--key', 'stats', 'notes', 'gateway journal', 'recurring_ingredient'):
            self.assertIn(phrase, self.readme, phrase)


class ReadmeTest(unittest.TestCase):
    def test_readme(self):
        t = (FRONTIER / 'README.md').read_text(encoding='utf-8')
        for phrase in ('rebound', 'tools/rebound.py', 'tools/export_rebound.py', 'IDEA-TREE.json'):
            self.assertIn(phrase, t, phrase)

    def test_vp_dependency_still_optional(self):
        t = (FRONTIER / 'README.md').read_text(encoding='utf-8')
        self.assertRegex(t, r'(?i)optional')


if __name__ == '__main__':
    unittest.main()
