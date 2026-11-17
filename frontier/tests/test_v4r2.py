# SPDX-License-Identifier: Apache-2.0
"""V4R2 reviewer guarantees, offline; size cases do not use the replay."""
import copy
import unittest
from unittest.mock import patch

from .helpers import FRONTIER, load_tool, mutate, read_json, run_tool
from .test_v4 import replay_data, receipt
from .v2_common import V2


class ReceiptGuarantees(unittest.TestCase):
    def test_both_decisions_require_current_distinct_predictions(self):
        tool = load_tool('v4check')
        for decision in ('revised', 'no change'):
            data = replay_data()
            good = receipt(data, decision)
            if decision == 'no change':
                good.pop('before')
                good.pop('after')
            for defect in (None, 'absent', 'role', 'drift', 'duplicate'):
                with self.subTest(decision=decision, defect=defect):
                    r = copy.deepcopy(good)
                    if defect == 'absent':
                        r.pop('predictions')
                    elif defect == 'role':
                        r['predictions'].pop('H0')
                    elif defect == 'drift':
                        r['predictions']['H2']['interval'] = [999, 1000]
                    elif defect == 'duplicate':
                        r['predictions']['H0'] = r['predictions']['H1']
                    data['test_revision.json'] = r
                    p, w = [], []
                    tool.run(FRONTIER.parent, data, p, w)
                    self.assertEqual(p, [])
                    self.assertEqual(any('[REVISION]' in x for x in w), defect is not None)

    def test_h0_accepts_existing_identifiers_without_prefix_conventions(self):
        tool = load_tool('v4check')
        for hid in ('NULL_BASELINE', 'alternative-7', 'V1'):
            data = replay_data()
            test = data['tests.json']['tests'][0]
            old = test['predictions'][2]['hypothesis']
            test['predictions'][2]['hypothesis'] = hid
            test['competing_hypotheses'] = [hid if x == old else x for x in test['competing_hypotheses']]
            data['test_revision.json'] = receipt(data)
            self.assertEqual(tool.revision_problems(FRONTIER.parent, data), [], hid)
            data['test_revision.json']['predictions']['H0']['hypothesis'] = 'undeclared'
            self.assertTrue(tool.revision_problems(FRONTIER.parent, data))


class CardAndCritiqueGuarantees(V2):
    def test_legacy_marks_are_one_line_and_do_not_require_artifacts(self):
        for upgrade in (None, self.to_r3, self.to_v2):
            self.fresh()
            work = upgrade() if upgrade else self.work()
            before = {p.name for p in work.iterdir()}
            text = load_tool('card').render(work)
            lines = [line for line in text.splitlines() if line.startswith('Marks: ')]
            self.assertEqual(len(lines), 1)
            self.assertIn('[REVISION]', lines[0])
            self.assertIn('[OVERLAP-LEDGER]', lines[0])
            self.assertEqual(before, {p.name for p in work.iterdir()})

    def test_open_methodological_critique_is_visible_in_every_format(self):
        for upgrade in (None, self.to_r3, self.to_v2):
            self.fresh()
            work = upgrade() if upgrade else self.work()
            def open_items(d):
                for item in d['items']:
                    item['response'] = {'action': 'open', 'note': 'Methodological objection remains open.'}
                d.pop('second_critique', None)
            mutate(work, 'critique.json', open_items)
            p, w = self.check.run_all(work, with_card=False)
            self.assertEqual(p, [])
            self.assertTrue(any('mark: [CRITIQUE]' in x for x in w))
            text = load_tool('card').render(work)
            self.assertIn('[CRITIQUE]', text)
            self.assertIn('open', text)
            # Actual factual and arithmetic errors still block with this open item.
            mutate(work, 'hypotheses.json', lambda d: d['hypotheses'][0]['against'].append(
                {'id': 'doi:10.1000/ghost.2021', 'run': 'prior_art', 'claim': 'A4',
                 'says': 'This reference is absent from the registered run.'}))
            mutate(work, 'tests.json', lambda d: d['tests'][0]['feasibility'].update(
                data='Confirmation on 300 months (2006-2025).'))
            p, _ = self.check.run_all(work, with_card=False)
            self.assertTrue(any('[REF-ABSENT]' in x for x in p), p)
            self.assertTrue(any('[ARITH-PERIOD]' in x for x in p), p)

    def test_open_factual_or_arithmetic_critique_still_blocks(self):
        # Terra v4r2: an error the critic reports as factual or arithmetic must still stop the run while open.
        for category in ('factual_error', 'arithmetic_error'):
            for upgrade in (None, self.to_r3, self.to_v2):
                with self.subTest(category=category, upgrade=getattr(upgrade, '__name__', 'legacy')):
                    self.fresh()
                    work = upgrade() if upgrade else self.work()
                    def first_open(d, action='open'):
                        d['items'][0].update(category=category,
                                             response={'action': action, 'note': 'Checked against the source.'})
                        for item in d['items'][1:]:
                            item['response'] = {'action': 'open', 'note': 'Methodological objection remains open.'}
                        d.pop('second_critique', None)
                    mutate(work, 'critique.json', first_open)
                    p, _ = self.check.run_all(work, with_card=False)
                    self.assertTrue(any('[CRITIQUE-FACT]' in x for x in p), p)
                    for action in ('rejected', 'fixed'):
                        mutate(work, 'critique.json', lambda d: first_open(d, action))
                        p, _ = self.check.run_all(work, with_card=False)
                        self.assertFalse(any('[CRITIQUE-FACT]' in x for x in p), (action, p))

    def oversized(self):
        work = self.to_v2()
        scenarios = [{'name': 'Scenario %d' % i, 'if': 'Synthetic condition %d' % i,
                      'then': 'Retain action %d in full' % i, 'why': 'Independent possible outcome %d.' % i}
                     for i in range(100)]
        mutate(work, 'tests.json', lambda d: d['ranking'].update(scenarios=scenarios))
        return work, scenarios

    def test_general_size_overflow_is_explicit_and_preserves_candidate_and_report(self):
        work, scenarios = self.oversized()
        card = load_tool('card')
        with self.assertRaises(ValueError) as caught:
            card.render(work)
        error = caught.exception
        self.assertEqual(type(error).__name__, 'CardSizeError')
        self.assertIn('[CARD-SIZE]', str(error))
        self.assertIn('80', str(error))
        self.assertIn('Ranking', str(error))
        report = card.render(work, full=True)
        for scenario in scenarios:
            self.assertIn(scenario['then'], error.text)
            self.assertIn(scenario['then'], report)
        reco = read_json(work / 'recommendation.json')
        self.assertIn(reco['reason'], error.text)
        self.assertIn(reco['next_step']['first_action'], error.text)
        self.assertGreater(len(error.text.splitlines()), 80)
        self.assertFalse(card._FULL)

    def test_size_cli_error_preserves_existing_outputs_without_traceback(self):
        work, _ = self.oversized()
        self.assertEqual(self.check.run_all(work, with_card=False)[0], [])
        for name in ('IDEA-CARD.md', 'IDEA-REPORT.md'):
            (work / name).write_text('Previously valid output\n', encoding='utf-8')
        r = run_tool('card', work)
        self.assertEqual(r.returncode, 1)
        self.assertIn('[CARD-SIZE]', r.stdout + r.stderr)
        self.assertIn('Ranking', r.stdout + r.stderr)
        self.assertNotIn('Traceback', r.stdout + r.stderr)
        for name in ('IDEA-CARD.md', 'IDEA-REPORT.md'):
            self.assertEqual((work / name).read_text(), 'Previously valid output\n')

    def test_configured_cap_is_enforced_by_render(self):
        work = self.to_v2()
        card = load_tool('card')
        original = card.common.config()
        with patch.object(card.common, 'config', return_value=dict(original, card_max_lines=12)):
            with self.assertRaises(ValueError) as caught:
                card.render(work)
        self.assertIn('12', str(caught.exception))


class InstructionGuarantees(unittest.TestCase):
    def test_host_may_leave_methodological_objections_open(self):
        text = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')
        self.assertNotIn('A blocking item is never left open.', text)
        self.assertIn('Only factual or arithmetic errors stop the run.', text)

