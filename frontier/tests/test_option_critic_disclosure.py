# SPDX-License-Identifier: Apache-2.0
"""Offline oracles for critic routes and single-family disclosure on saved outputs."""
import hashlib
import json

from .helpers import TempCase, copy_skill, mutate, read_json, run_tool, set_config, write_json
from .v2_common import V2


SAME_FAMILY = 'Critique: same family (no independent critic available)'


class CriticDisclosureTest(TempCase):
    def test_same_agent_or_family_in_each_accepted_fallback(self):
        skill = copy_skill(self.tmp, 'skill')
        # The sequential host, a same-family subprocess and a same-family
        # sub-agent all use route=subagent: there is no separate agent-ID field.
        for mode, name in (('none', 'valid_novp'), ('vp', 'valid_vp')):
            for critic, families in (('claude', []), ('claude', ['claude']),
                                     ('anthropic', ['anthropic'])):
                with self.subTest(mode=mode, critic=critic, families=families):
                    work = self.work(name)
                    for output in ('IDEA-CARD.md', 'IDEA-REPORT.md'):
                        (work / output).unlink(missing_ok=True)
                    # Use the real same-family raw receipt on either VP mode.
                    for filename in ('critique.json', 'critique-raw.txt'):
                        (work / filename).write_bytes((self.fx / 'valid_novp' / filename).read_bytes())
                    mutate(work, 'critique.json', lambda d: d.update(critic_family=critic))
                    set_config(skill, lambda c: c['critic'].update(host_family='claude', families=families))
                    args = ('--vp-run', 'prior_art') if mode == 'vp' else ()
                    pack = run_tool('pack_critique', work, *args, tools_dir=skill / 'tools')
                    self.assertEqual(pack.returncode, 0, pack.stdout + pack.stderr)
                    self.assertEqual('vp_command' in json.loads(pack.stdout), mode == 'vp')
                    receipt = run_tool('pack_critique', work, '--receipt', 'critique-raw.txt', tools_dir=skill / 'tools')
                    self.assertEqual(receipt.returncode, 0, receipt.stdout + receipt.stderr)
                    result = run_tool('card', work, tools_dir=skill / 'tools')
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    for output in ('IDEA-CARD.md', 'IDEA-REPORT.md'):
                        self.assertIn(SAME_FAMILY, (work / output).read_text(encoding='utf-8'))
                    result = run_tool('check', work, tools_dir=skill / 'tools')
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_family_cannot_hide_behind_another_route_or_false_flag(self):
        for route, same in (('vp-contradictor', True), ('subagent', False)):
            with self.subTest(route=route, same=same):
                work = self.work('valid_vp' if route == 'vp-contradictor' else 'valid_novp')
                mutate(work, 'critique.json', lambda d: d.update(
                    route=route, critic_family='anthropic', same_family=same, no_independent_critic=True))
                result = run_tool('card', work)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('[CRITIQUE]', result.stdout)
                self.assertIn('same-family critique is done by a sub-agent' if same else 'same_family is False',
                              result.stdout)
                self.assertFalse((work / 'IDEA-CARD.md').exists())
                self.assertFalse((work / 'IDEA-REPORT.md').exists())

    def test_different_family_routes_do_not_claim_same_family(self):
        for route in ('vp-contradictor', 'subagent'):
            with self.subTest(route=route):
                work = self.work('valid_novp' if route == 'subagent' else 'valid_vp')
                mutate(work, 'critique.json', lambda d: d.update(
                    critic_family='openai', same_family=False, no_independent_critic=False))
                result = run_tool('card', work)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for output in ('IDEA-CARD.md', 'IDEA-REPORT.md'):
                    self.assertNotIn(SAME_FAMILY, (work / output).read_text(encoding='utf-8'))
                result = run_tool('check', work)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class CompactCriticDisclosureTest(V2):
    def test_same_family_survives_v2_card_compaction_and_report(self):
        work = self.to_v2()
        critique = read_json(work / 'critique.json')
        # A subagent returns trap verdicts; not_returned belongs only to the
        # VP contradictor fixture. Build a complete synthetic raw receipt.
        critique.update(route='subagent', critic_family='anthropic', same_family=True, no_independent_critic=True,
                        trap_verdicts=read_json(self.work('valid_novp') / 'critique.json')['trap_verdicts'])
        critique['second_critique']['critic_family'] = 'claude'
        raw = work / 'same-family-raw.json'
        write_json(raw, {'items': critique['items'], 'trap_verdicts': critique['trap_verdicts']})
        critique.update(raw_output=raw.name, raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
        write_json(work / 'critique.json', critique)
        result = run_tool('card', work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for output in ('IDEA-CARD.md', 'IDEA-REPORT.md'):
            self.assertIn(SAME_FAMILY, (work / output).read_text(encoding='utf-8'))
        result = run_tool('check', work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
