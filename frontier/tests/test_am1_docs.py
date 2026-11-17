# SPDX-License-Identifier: Apache-2.0
"""AM90-AM91: new schemas load, new tools exist and follow the portability rules, SKILL.md and README describe them."""
import re
import unittest

from .helpers import FRONTIER, TOOLS, load_tool, read_json

NEW_TOOLS = ('hybrid', 'context', 'matter', 'gwclient', 'catalogue')
NEW_SCHEMAS = ('draft_claims.json', 'evidence_table.json', 'material.json', 'moment.json', 'context_candidates.json')


class NewPartsTest(unittest.TestCase):
    def test_am90_tools_exist(self):
        for t in NEW_TOOLS:
            self.assertTrue((TOOLS / (t + '.py')).exists(), t)

    def test_am90_schemas_load(self):
        schema_lite = load_tool('schema_lite')
        for s in NEW_SCHEMAS:
            p = FRONTIER / 'schemas' / s
            self.assertTrue(p.exists(), s)
            # an empty object must be accepted or refused without a schema error (unsupported keyword = ValueError)
            schema_lite.validate({}, read_json(p))

    def test_am90_tools_answer_help(self):
        from .helpers import run_tool
        for t in ('hybrid', 'context', 'matter', 'catalogue'):
            r = run_tool(t, '--help')
            self.assertEqual(r.returncode, 0, (t, r.stderr))
            self.assertTrue((r.stdout + r.stderr).strip(), t)

    def test_am94_config_keys(self):
        cfg = read_json(FRONTIER / 'config.json')
        for k in ('tree_dir', 'catalogue', 'directions_index'):
            self.assertIn(k, cfg)
            self.assertIsNone(cfg[k])
        for k in ('rise', 'revive_factor', 'trough_ratio', 'min_total'):
            self.assertIn(k, cfg['moment'])
        for k in ('code_plugin', 'literature_plugin', 'min_overlap', 'max_candidates', 'timeout_s'):
            self.assertIn(k, cfg['matter'])
        for k in ('max_files', 'max_candidates'):
            self.assertIn(k, cfg['context'])


class DocsTest(unittest.TestCase):
    def setUp(self):
        self.skill = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')
        self.readme = (FRONTIER / 'README.md').read_text(encoding='utf-8')

    def test_am91_skill_describes_each_step(self):
        for phrase in ('free_draft.md', 'draft_claims.json', 'unverified (memory)', 'tools/hybrid.py',
                       'IDEA-REPORT.md', '[DRAFT-UNMARKED]', 'tools/context.py', 'context_candidates.json',
                       'key_numbers', 'FRONTIER_TREE_DIR', 'evidence_table.json', '--needed-n', 'tools/matter.py',
                       'material.json', 'moment.json', 'FRONTIER_CATALOGUE', 'FRONTIER_DIRECTIONS_INDEX',
                       'tools/catalogue.py', 'optional', 'not tied to the project'):
            self.assertIn(phrase, self.skill, phrase)

    def test_am91_headings(self):
        for h in (r'## 0-ter\. ', r'## 0-quater\. ', r'## 2-bis\. ', r'## 1-bis\. ', r'## 9\. '):
            self.assertRegex(self.skill, r'(?m)^' + h)

    def test_am91_commands_use_skill_dir(self):
        for c in re.findall(r'python3 -I (\S+)', self.skill):
            self.assertTrue(c.startswith(('<SKILL_DIR>/tools/', '<VP>/tools/', '"<VP>/tools/', '"<SKILL_DIR>/tools/')), c)
        for t in ('hybrid.py', 'context.py', 'matter.py', 'catalogue.py'):
            self.assertIn('python3 -I <SKILL_DIR>/tools/%s' % t, self.skill)

    def test_am91_readme_lists_new_tools(self):
        for t in ('hybrid.py', 'context.py', 'matter.py', 'catalogue.py', 'gwclient.py'):
            self.assertIn(t, self.readme, t)
        self.assertIn('IDEA-REPORT.md', self.readme)

    def test_optional_sources_are_never_required(self):
        self.assertRegex(self.skill, r'(?i)never required')
        self.assertRegex(self.skill, r'(?i)skipped')

    def test_unverified_mark_literal_is_shared(self):
        self.assertEqual(load_tool('hybrid').MARK, 'unverified (memory)')
