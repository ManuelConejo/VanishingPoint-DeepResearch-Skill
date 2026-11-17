# SPDX-License-Identifier: Apache-2.0
"""card.py: IDEA-CARD.md assembled by a tool from the JSON files, after check.py (regression specification R20, R26, R49, R60, R61).

Modified round 2: the card is IDEA-CARD.md (R63); the same-family line is "Critique: same family (no independent critic
available)" (R49)."""
import copy
import json
import unittest

from .helpers import HEADER, TempCase, load_tool, mutate, run_tool

MAX_LINES = 80
CARD = 'IDEA-CARD.md'
SAME_FAMILY = 'Critique: same family (no independent critic available)'


class CardTest(TempCase):
    def make(self, name):
        r = run_tool('card', self.work(name))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p = self.work(name) / CARD
        self.assertTrue(p.exists())
        return p.read_text(encoding='utf-8')

    def test_refuses_when_check_fails(self):
        mutate(self.work(), 'hypotheses.json', lambda d: d.update(rivals=[]))
        r = run_tool('card', self.work())
        self.assertEqual(r.returncode, 1)
        self.assertIn('[RIVAL]', r.stdout + r.stderr)
        self.assertFalse((self.work() / CARD).exists())

    def test_vp_card(self):
        text = self.make('valid_vp')
        self.assertNotIn(HEADER, text)
        self.assertIn('Recommendation: DIG', text)
        self.assertIn('T2) is now worth its day', text)
        self.assertIn('not a certification of novelty or value', text)
        self.assertIn('doi:10.1000/titles.2019 [FOUND]', text)
        self.assertIn('[DISTORTED]', text)
        self.assertIn('Prior art: Partially', text)
        self.assertIn('R1', text)
        self.assertIn('T1', text)
        self.assertIn('continue', text)
        self.assertNotIn(SAME_FAMILY, text)
        self.assertLessEqual(len(text.splitlines()), MAX_LINES)
        self.assertEqual(load_tool('check').problems(self.work('valid_vp')), [])

    def test_novp_card(self):
        text = self.make('valid_novp')
        self.assertEqual(text.splitlines()[1], HEADER)
        self.assertIn('Recommendation: TEST FIRST', text)
        self.assertIn('Plan only', text)
        self.assertIn('assumption', text.lower())
        self.assertIn('[unverified]', text)
        self.assertLessEqual(len(text.splitlines()), MAX_LINES)
        self.assertEqual(load_tool('check').problems(self.work('valid_novp')), [])

    def test_same_family_line(self):
        text = self.make('valid_novp')
        self.assertIn(SAME_FAMILY, text)

    def test_not_found_caveat(self):
        def f(d):
            d['answer'] = 'Not found'
            d['closest_work'] = []
        mutate(self.work('valid_novp'), 'prior_art.json', f)
        text = self.make('valid_novp')
        self.assertIn('Prior art: Not found', text)
        self.assertIn('never a proof of absence', text)

    def test_three_tests_fit_one_page(self):
        def f(d):
            t3 = copy.deepcopy(d['tests'][1])
            t3['id'] = 'T3'
            d['tests'].append(t3)
            d['ranking']['order'].append('T3')
        mutate(self.work('valid_vp'), 'tests.json', f)
        mutate(self.work('valid_vp'), 'critique.json',
               lambda d: d['trap_verdicts'].update(T3=copy.deepcopy(d['trap_verdicts']['T2'])))
        text = self.make('valid_vp')
        self.assertLessEqual(len(text.splitlines()), MAX_LINES)

    # modified round 2 (R40): the non-distinguishing simulation is now produced by sim.py itself (a hand edit is refused)
    def test_simulation_warning_shown(self):
        w = self.work('valid_novp')
        r = run_tool('sim', '--design', 'paired', '--n', '20', '--sd', '5', '--scenario', 'H1=3', '--scenario', 'R1=0',
                     '--expect', 'H1=continue', '--expect', 'R1=stop', '--continue-if-lower-above', '0',
                     '--stop-if-upper-below', '1', '--write-into', w / 'tests.json', '--test', 'T1')
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.make('valid_novp')
        self.assertIn('does NOT distinguish', text)

    def test_hand_edited_simulation_refused(self):
        mutate(self.work('valid_vp'), 'tests.json',
               lambda d: d['tests'][0]['sensitivity']['simulation'].update(distinguishes=False, min_p_expected=0.4))
        r = run_tool('card', self.work('valid_vp'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('[SIM-RERUN]', r.stdout)

    def test_decision_log_shown(self):
        text = self.make('valid_vp')
        self.assertIn('Before', text)
        self.assertIn('After', text)


class CardRound2Test(TempCase):
    def test_stale_card_refused(self):
        """R60: an "after" appended without regenerating the card makes the card stale."""
        w = self.work('valid_novp')
        self.assertEqual(run_tool('card', w).returncode, 0)
        self.assertIn('<!-- frontier inputs sha256:', (w / CARD).read_text(encoding='utf-8'))
        check = load_tool('check')
        self.assertEqual(check.problems(w), [])
        r = run_tool('log', w, 'after', '--test', 'T1', '--assumption', '--text', 'Assumed: ran T1 next.')
        self.assertEqual(r.returncode, 0, r.stderr)
        probs = check.problems(w)
        self.assertTrue(any(p.startswith('[CARD-STALE]') for p in probs), probs)
        self.assertEqual(run_tool('card', w).returncode, 0)
        self.assertEqual(check.problems(w), [])

    def test_stale_after_json_change(self):
        w = self.work('valid_vp')
        self.assertEqual(run_tool('card', w).returncode, 0)
        mutate(w, 'recommendation.json', lambda d: d.update(
            reason='The citation step (T2) is worth its day because the retrieval test held.'))
        probs = load_tool('check').problems(w)
        self.assertTrue(any(p.startswith('[CARD-STALE]') for p in probs), probs)

    def test_invalid_card_never_written(self):
        """R61: the content is checked in memory; an invalid card is never written, not even as a temporary file."""
        w = self.work('valid_vp')
        card = load_tool('card')
        before = sorted(p.name for p in w.iterdir())
        card.render = lambda work: '# Idea card\n' + 'line\n' * 200
        self.assertEqual(card.main([str(w)]), 1)
        self.assertEqual(sorted(p.name for p in w.iterdir()), before)

    def test_invalid_card_does_not_replace_a_good_one(self):
        w = self.work('valid_vp')
        self.assertEqual(run_tool('card', w).returncode, 0)
        good = (w / CARD).read_text(encoding='utf-8')
        card = load_tool('card')
        card.render = lambda work: '# Idea card\n' + 'line\n' * 200
        self.assertEqual(card.main([str(w)]), 1)
        self.assertEqual((w / CARD).read_text(encoding='utf-8'), good)

    def test_trap_verdicts_on_card(self):
        text_path = self.work('valid_novp') / CARD
        self.assertEqual(run_tool('card', self.work('valid_novp')).returncode, 0)
        text = text_path.read_text(encoding='utf-8')
        self.assertIn('Critic trap verdicts', text)


if __name__ == '__main__':
    unittest.main()
