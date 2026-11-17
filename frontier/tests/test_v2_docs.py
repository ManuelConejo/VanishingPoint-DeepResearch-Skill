# SPDX-License-Identifier: Apache-2.0
"""V2-29 .. V2-31 of regression specification: documentation, configuration, portability of the v2 additions."""
import ast
import json
import re
from pathlib import Path

from .helpers import FRONTIER, TempCase, load_tool

SKILL = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')
README = (FRONTIER / 'README.md').read_text(encoding='utf-8')


class DocsV2Test(TempCase):
    def test_skill_describes_the_v2_path_and_its_tools(self):
        for needle in ('## Frontier v2: the path', 'tools/framing.py', 'tools/research.py', 'tools/named.py', 'research_plan.json',
                       'framing.json', 'named_elements.json', 'belief_shift', 'voi', 'context_use', '## Next step',
                       'Marked, not blocking', 'frontier_version": 4', 'REOPENS A TRIAL CLASSED BY YOUR PROJECT',
                       'search_plan', 'claimed fixed, not proven', 'Insufficient search', 'operator not measured'):
            self.assertIn(needle, SKILL, needle)

    def test_every_v2_code_is_documented_and_implemented(self):
        doc = (FRONTIER / 'tools' / 'v2check.py').read_text(encoding='utf-8').split('"""')[1]
        codes = set(re.findall(r'\[[A-Z]+(?:-[A-Z]+)*\]', doc))
        self.assertGreaterEqual(len(codes), 20)
        src = ''.join((FRONTIER / 'tools' / n).read_text(encoding='utf-8') for n in ('v2check.py', 'check.py', 'research.py', 'framing.py', 'named.py'))
        for c in codes:
            self.assertIn(c, src, c)
            self.assertIn(c, SKILL, c)

    def test_readme_mentions_v2(self):
        for needle in ('Frontier v2', 'framing.py', 'research.py'):
            self.assertIn(needle, README, needle)

    def test_the_skill_keeps_the_hosts_and_the_single_command_rule(self):
        self.assertIn('**Hosts.**', SKILL)
        self.assertRegex(SKILL, r'one command per Bash call')

    def test_config_holds_the_v2_limits(self):
        cfg = json.loads((FRONTIER / 'config.json').read_text(encoding='utf-8'))
        self.assertNotIn('card_max_lines_v2', cfg, 'v2 uses the shared card_max_lines limit')
        r = cfg['research']
        self.assertEqual((r['iterations_min'], r['iterations_max'], r['fields_min'], r['keywords_min']), (2, 3, 2, 2))
        self.assertIn('command', r)
        self.assertEqual(cfg['card_max_lines'], 80, 'the page of the older directories is unchanged')

    def test_run_json_schema_knows_the_new_steps(self):
        schema = json.loads((FRONTIER / 'schemas' / 'run.json').read_text(encoding='utf-8'))
        enum = schema['properties']['steps']['items']['properties']['step']['enum']
        for s in ('framing', 'research_plan', 'named'):
            self.assertIn(s, enum)
        step = load_tool('step')
        for s in ('framing', 'research_plan', 'named'):
            self.assertIn(s, step.STEPS)


class PortabilityV2Test(TempCase):
    def test_new_tools_use_the_standard_library_and_local_modules_only(self):
        local = {p.stem for p in (FRONTIER / 'tools').glob('*.py')}
        for name in ('v2check', 'framing', 'research', 'named'):
            tree = ast.parse((FRONTIER / 'tools' / (name + '.py')).read_text(encoding='utf-8'))
            mods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods.update(a.name.split('.')[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module.split('.')[0])
            import sys
            for m in mods:
                self.assertTrue(m in sys.stdlib_module_names or m in local, '%s imports %s' % (name, m))
            self.assertFalse(mods & {'socket', 'urllib', 'http', 'requests', 'ssl', 'ftplib', 'smtplib'}, name)

    def test_no_model_or_family_name_in_the_new_tools(self):
        fam = re.compile(r'(?i)\b(claude|openai|anthropic|gemini|codex|gpt|mistral|kimi|sonnet|opus|haiku)\b')
        for name in ('v2check', 'framing', 'research', 'named'):
            self.assertEqual(fam.findall((FRONTIER / 'tools' / (name + '.py')).read_text(encoding='utf-8')), [], name)

    def test_the_new_tools_print_a_usage(self):
        from .helpers import run_tool
        for name in ('framing', 'research', 'named'):
            r = run_tool(name, '--help')
            self.assertEqual(r.returncode, 0, name)
            self.assertIn('Usage', r.stdout)
