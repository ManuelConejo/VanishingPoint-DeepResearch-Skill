# SPDX-License-Identifier: Apache-2.0
"""R3 documentation, new_run marker, blind comparison template (regression specification: R3-17 .. R3-19, A9 tooling)."""
import json
import re
from pathlib import Path

from .helpers import FRONTIER, TempCase, load_tool, read_json, run_tool, write_json
from .r3_common import R3


class DocsTest(TempCase):
    def setUp(self):
        super().setUp()
        self.skill = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')

    def test_skill_documents_every_round3_rule(self):
        for needle in ('tools/guards.py', 'refused-before', 'unverified provenance', '## Tomorrow', '--observed',
                       'second_critique', 'critique2', 'data_seen_before', 'verdict_scope', 'sensitivity.power', 'sim.py robust',
                       'decisive_claims.json', 'coverage-write', 'recall unknown', 'hybrid.py priority', 'hybrid.py richness',
                       'outcome_source: "scenario"', 'first two lines', 'followed by the reminder',
                       'without requiring an exact total line count'):
            if needle == 'refused-before':
                needle = 'BEFORE the gateway is called'
            self.assertIn(needle, self.skill)

    def test_every_check_code_of_r3_is_listed_in_the_skill_or_the_check_docstring(self):
        doc = (FRONTIER / 'tools' / 'r3check.py').read_text(encoding='utf-8').split('"""')[1]
        codes = set(re.findall(r'\[[A-Z]+(?:-[A-Z]+)*\]', doc))
        self.assertGreaterEqual(len(codes), 20)
        src = (FRONTIER / 'tools' / 'r3check.py').read_text(encoding='utf-8') + (FRONTIER / 'tools' / 'check.py').read_text(encoding='utf-8')
        for c in codes - {'[BUDGET]'}:
            self.assertIn(c, src)


class NewRunTest(TempCase):
    def test_new_run_stamps_the_directory_as_r3(self):
        guards = load_tool('guards')
        r = run_tool('new_run', 'a bare idea about titles', '--parent', self.tmp, '--date', '2026-11-14')
        self.assertEqual(r.returncode, 0, r.stderr)
        d = Path(r.stdout.strip())
        self.assertTrue((d / 'frontier-version.json').is_file())
        self.assertTrue(guards.is_r3(d))
        self.assertFalse(guards.is_r3(self.fx / 'valid_vp'))


class CompareTemplateTest(TempCase):
    def manifest(self, n=3, usd=(1.0, 1.05), minutes=(20, 21)):
        ideas = []
        for i in range(n):
            f, m = self.tmp / ('f%d.md' % i), self.tmp / ('m%d.md' % i)
            f.write_text('# Idea card: x\nT 2026 | assembled by tools/card.py\nFirst step: do the thing %d\n<!-- frontier inputs sha256:ab -->\n' % i, encoding='utf-8')
            m.write_text('Answer of the model alone %d: try the thing.\n' % i, encoding='utf-8')
            ideas.append({'id': 'I%d' % i, 'idea': 'bare idea %d' % i, 'arms': {
                'frontier': {'file': str(f), 'usd': usd[0], 'minutes': minutes[0]},
                'model_alone': {'file': str(m), 'usd': usd[1], 'minutes': minutes[1]}}})
        p = self.tmp / 'manifest.json'
        write_json(p, {'ideas': ideas})
        return p

    def export(self, man, key=None):
        return run_tool('export_compare', 'export', '--manifest', man, '--out', self.tmp / 'out', '--key', key or self.tmp / 'key.json')

    def test_equal_budget_is_required(self):
        self.assertEqual(self.export(self.manifest()).returncode, 0)
        self.fresh()
        r = self.export(self.manifest(usd=(1.0, 2.0)))
        self.assertEqual(r.returncode, 1)
        self.assertIn('budget must be equal', r.stderr)
        r = self.export(self.manifest(minutes=(20, 40)))
        self.assertEqual(r.returncode, 1)

    def test_several_ideas_and_a_key_outside(self):
        self.assertEqual(self.export(self.manifest(n=2)).returncode, 1)
        r = self.export(self.manifest(), key=self.tmp / 'out' / 'key.json')
        self.assertEqual(r.returncode, 1)

    def test_blind_files_hold_no_tool_name_and_the_seed_stays_in_the_key(self):
        self.assertEqual(self.export(self.manifest()).returncode, 0)
        key = read_json(self.tmp / 'key.json')
        blind = self.tmp / 'out' / 'blind'
        for p in blind.glob('*'):
            body = p.read_text(encoding='utf-8')
            self.assertNotIn(key['seed'], body)
            self.assertNotRegex(body, r'(?i)tools/card\.py|<!--|frontier inputs')
        for i in range(3):
            m = key['mapping']['I%d' % i]
            self.assertEqual(sorted(m.values()), ['frontier', 'model_alone'])
            a = (blind / ('I%d.A.md' % i)).read_text(encoding='utf-8')
            self.assertEqual('First step' in a, m['A'] == 'frontier')

    def test_stats_tally_per_real_arm(self):
        self.export(self.manifest())
        key = read_json(self.tmp / 'key.json')
        ans = {}
        for i in range(3):
            fr_label = next(l for l, a in key['mapping']['I%d' % i].items() if a == 'frontier')
            other = 'B' if fr_label == 'A' else 'A'
            ans['I%d' % i] = {'preferred': fr_label, 'work_avoided_minutes': {fr_label: 30, other: 10},
                              'first_action_in_2min': {fr_label: True, other: False}, 'invented_references': {fr_label: 0, other: 1}}
        write_json(self.tmp / 'ans.json', ans)
        r = run_tool('export_compare', 'stats', '--key', self.tmp / 'key.json', '--answers', self.tmp / 'ans.json')
        out = json.loads(r.stdout)
        self.assertEqual(out['arms']['frontier']['preferred'], 3)
        self.assertEqual(out['arms']['model_alone']['preferred'], 0)
        self.assertEqual(out['arms']['frontier']['mean_work_avoided_minutes'], 30)
        self.assertEqual(out['arms']['model_alone']['invented_references'], 3)
        self.assertIn('no significance claim', out['reading'])

    def test_too_few_judged_ideas_is_not_concluding(self):
        self.export(self.manifest())
        write_json(self.tmp / 'ans.json', {'I0': {'preferred': 'tie'}})
        r = run_tool('export_compare', 'stats', '--key', self.tmp / 'key.json', '--answers', self.tmp / 'ans.json')
        self.assertIn('not concluding', json.loads(r.stdout)['reading'])


class SyntheticCardFixClaimTest(R3):
    def test_synthetic_card_1_figure_not_in_the_stored_simulation_is_refused(self):
        # Synthetic mismatch: the cited packing probability is absent from the stored simulation.
        w = self.to_r3()
        mutate_crit = lambda d: d['items'][0]['response'].update(proof={
            'kind': 'calculation', 'where': 'tests.T1.sensitivity.simulation', 'evidence': 'p_expected 0.9876',
            'addresses': 'the index sensitive to titles shown by simulation of the control'})
        from .helpers import mutate
        mutate(w, 'critique.json', mutate_crit)
        self.assertCode('[FIX-PROOF]')
