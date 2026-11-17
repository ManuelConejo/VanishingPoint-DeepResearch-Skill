# SPDX-License-Identifier: Apache-2.0
"""card.py section "Already tried here" (HI21-HI23), the end-to-end real case (HI26-HI28) and the documents (HI25)."""
import json
import re
from pathlib import Path

from .helpers import FRONTIER, TempCase, mutate, read_json, run_tool, write_json
from .hist_common import E_CAPS, HB, INTAKE_TERMS, FOLD_TERM, FOLD_TITLE, write_files

SECTION = '## Already tried here (internal history)'
NOT_CHECKED = 'Already tried here: not checked'


def card_lines(work):
    return (Path(work) / 'IDEA-CARD.md').read_text(encoding='utf-8').splitlines()


class NotCheckedTest(HB):
    """HI21."""

    def test_marked_in_the_head_of_the_card(self):
        for name in ('valid_vp', 'valid_novp'):
            with self.subTest(name=name):
                self.fresh()
                r = run_tool('card', self.work(name))
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                lines = card_lines(self.work(name))
                head = [l for l in lines[:8]]
                self.assertTrue(any(NOT_CHECKED in l for l in head), head)
                self.assertNotIn(SECTION, lines)
                self.assertLessEqual(len(lines), 80)

    def test_empty_list_is_the_same(self):
        mutate(self.work('valid_novp'), 'intake.json', lambda d: d.update(project_dirs=[]))
        self.assertEqual(run_tool('card', self.work('valid_novp')).returncode, 0)
        self.assertTrue(any(NOT_CHECKED in l for l in card_lines(self.work('valid_novp'))[:8]))

    def test_novp_header_follows_the_disclaimer(self):
        run_tool('card', self.work('valid_novp'))
        self.assertEqual(card_lines(self.work('valid_novp'))[1], 'References not verified (VP not installed)')


class CardSectionTest(HB):
    """HI22, HI23."""

    def accepted(self):
        work = self.full_flow()
        self.attach(work, self.good_citations(work))
        self.assertEqual(self.problems(work), [])
        r = run_tool('card', work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return work

    def test_section_lists_verdicts_and_citations(self):
        work = self.accepted()
        lines = card_lines(work)
        self.assertIn(SECTION, [l.strip() for l in lines])
        text = '\n'.join(lines)
        self.assertNotIn(NOT_CHECKED, text)
        self.assertIn('results/test_softfold.md:10', text)
        self.assertIn('LESSONS.md:5', text)
        self.assertIn('NE PAS ROUVRIR', text)
        self.assertIn('CLASS' + E_CAPS, text)
        self.assertIn('kept by T2', text)
        self.assertIn('FOLD_PACKING_SUMMARY', text)           # the reopening condition
        self.assertIn('notes/en_summary.txt', text)         # found, classed, used by no test
        self.assertLessEqual(len(lines), 80)

    def test_no_excerpt_of_the_archives_on_the_card(self):
        text = '\n'.join(card_lines(self.accepted()))
        for secret in ('-63 %', 'padding for SoftFold', 'inspection-window', 'packing option #1'):
            self.assertNotIn(secret, text)

    def test_removed_items_are_shown(self):
        work = self.full_flow()
        self.set_fold_test(work, title='Seed variance of the baseline model on identical folds')
        mutate(work, 'tests.json', lambda d: d['tests'][1]['decisive_intervention'].update(
            description='Rerun the baseline with five seeds on identical folds.'))
        e = self.entry(work, 'results/test_softfold.md', 'Verdict : -63')
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))
        mutate(work, 'tests.json', lambda d: d.update(internal_history_removed=[self.removal_note(
            e, what='A SoftFold test of the same model')]))
        self.assertEqual(run_tool('card', work).returncode, 0)
        text = '\n'.join(card_lines(work))
        self.assertIn('removed', text)
        self.assertIn('A SoftFold test of the same model', text)

    def test_nothing_found_is_said_and_is_no_proof(self):
        work = self.new_work()
        self.scan_ok(work, 'intake', [{'term': 'zzzznothingzzzz', 'synonyms': [], 'group': 'idea'}])
        self.scan_ok(work, 'tests', [{'term': 'zzzznothingzzzz', 'synonyms': [], 'group': 'test', 'for': t}
                                     for t in ('T1', 'T2')])
        self.assertEqual(run_tool('card', work).returncode, 0)
        text = '\n'.join(card_lines(work))
        self.assertIn(SECTION, text)
        self.assertIn('not a proof', text)

    def test_card_is_stale_when_history_changes(self):
        work = self.accepted()
        self.assertEqual(self.problems(work), [])
        mutate(work, 'history.json', lambda d: d.update(generated_utc='2026-11-14T13:31:00Z'))
        self.assertCode('[CARD-STALE]', work)

    def test_card_refused_while_the_check_fails(self):
        work = self.full_flow()
        r = run_tool('card', work)
        self.assertEqual(r.returncode, 1)
        self.assertIn('[HISTORY-OVERLAP]', r.stdout)
        self.assertFalse((work / 'IDEA-CARD.md').exists())


class SyntheticCaseEndToEndTest(HB):
    """HI26-HI28: the idea "replace paper folding", the test "SoftFold", the project that already classed it."""

    def test_synthetic_case(self):
        work = self.new_work()
        # 1. after the intake: the host scans with the words of the idea and its neighbours
        r = self.scan(work, 'intake', INTAKE_TERMS)
        self.assertEqual(r.returncode, 0, r.stderr)
        # 2. step 3: a test "SoftFold" and its terms (with their synonyms)
        self.set_fold_test(work)
        r = self.scan(work, 'tests', self.terms_for_tests(work))
        self.assertEqual(r.returncode, 0, r.stderr)
        classed = [e for e in self.entries(work) if e['verdict'] == 'classed']
        self.assertIn('results/test_softfold.md', {e['file'] for e in classed})
        # 3. refused without citation
        c = run_tool('check', work)
        self.assertEqual(c.returncode, 1)
        self.assertIn('[HISTORY-OVERLAP]', c.stdout)
        self.assertIn('T2', c.stdout)
        self.assertEqual(run_tool('card', work).returncode, 1)
        # 4. refused with a wrong line, then with a 10-character justification
        items = self.good_citations(work)
        items[0]['cited'] = 'results/test_softfold.md:2'
        self.attach(work, items)
        c = run_tool('check', work)
        self.assertEqual(c.returncode, 1)
        self.assertIn('[HISTORY-CITE]', c.stdout)
        items = self.good_citations(work)
        items[0]['condition_met'] = 'Conditions met.'
        self.attach(work, items)
        self.assertEqual(run_tool('check', work).returncode, 1)
        # 5. accepted with the citation and the justification; the card carries the section
        self.attach(work, self.good_citations(work))
        c = run_tool('check', work)
        self.assertEqual(c.returncode, 0, c.stdout)
        self.assertEqual(run_tool('card', work).returncode, 0)
        self.assertIn(SECTION, [l.strip() for l in card_lines(work)])
        self.assertEqual(run_tool('check', work).returncode, 0)

    def test_the_test_is_removed_instead(self):
        work = self.full_flow()
        self.assertEqual(run_tool('check', work).returncode, 1)
        self.set_fold_test(work, title='Seed variance of the baseline model on identical folds')
        mutate(work, 'tests.json', lambda d: d['tests'][1]['decisive_intervention'].update(
            description='Rerun the baseline with five seeds on identical folds.'))
        e = self.entry(work, 'results/test_softfold.md', 'Verdict : -63')
        self.scan_ok(work, 'tests', self.terms_for_tests(work, fold=False))
        mutate(work, 'tests.json', lambda d: d.update(internal_history_removed=[self.removal_note(e)]))
        self.assertEqual(run_tool('check', work).returncode, 0)
        self.assertEqual(run_tool('card', work).returncode, 0)

    def test_leak_through_a_request_refused(self):
        work = self.full_flow()
        self.attach(work, self.good_citations(work))
        self.assertEqual(run_tool('check', work).returncode, 0)
        mutate(work, 'prior_art.json', lambda d: d.update(
            searched='web search: "Verdict : -63 % padding for SoftFold. CLASS' + E_CAPS + '."'))
        c = run_tool('check', work)
        self.assertEqual(c.returncode, 1)
        self.assertIn('[HISTORY-LEAK]', c.stdout)
        mutate(work, 'prior_art.json', lambda d: d.update(
            searched='web search: paper folding versus soft fold for tile packing'))
        self.assertEqual(run_tool('check', work).returncode, 0)

    def test_no_path_given_is_not_checked_and_not_blocking(self):
        work = self.new_work(dirs=False)
        self.set_fold_test(work)
        self.assertEqual(run_tool('check', work).returncode, 0)
        self.assertEqual(run_tool('card', work).returncode, 0)
        self.assertTrue(any(NOT_CHECKED in l for l in card_lines(work)[:8]))

    def test_project_untouched(self):
        before = {str(p.relative_to(self.proj)): p.read_bytes() for p in sorted(self.proj.rglob('*'))
                  if p.is_file() and not p.is_symlink()}
        self.full_flow()
        after = {str(p.relative_to(self.proj)): p.read_bytes() for p in sorted(self.proj.rglob('*'))
                 if p.is_file() and not p.is_symlink()}
        self.assertEqual(before, after)


class DocsTest(TempCase):
    """HI25."""

    def setUp(self):
        super().setUp()
        self.skill = (FRONTIER / 'SKILL.md').read_text(encoding='utf-8')

    def test_step_before_any_proposal(self):
        heads = [m.start() for m in re.finditer(r'(?m)^## ', self.skill)]
        self.assertIn('## 0-bis. Already tried here', self.skill)
        pos = self.skill.index('## 0-bis. Already tried here')
        self.assertGreater(pos, self.skill.index('## 0. Intake'))
        self.assertLess(pos, self.skill.index('## 1. Prior art'))
        self.assertLess(pos, self.skill.index('## 3. Minimal tests'))

    def section(self):
        s = self.skill.index('## 0-bis. Already tried here')
        return self.skill[s:self.skill.index('## 1. ')]

    def test_step_content(self):
        sec = self.section()
        for phrase in ('project_dirs', 'tools/history.py', 'history.json', 'not checked', 'internal_history',
                       'internal_history_removed', 'reopening condition', 'synonyms', 'classed', 'read the files',
                       '--label intake', 'file:line', 'tools/check.py', 'tools/card.py'):
            self.assertIn(phrase, sec, phrase)
        for label in ('--label tests', '--label rebound'):
            self.assertIn(label, self.skill, label)
        self.assertRegex(self.skill, r'(?is)step 3.{0,400}history\.py|history\.py.{0,400}step 3')
        self.assertRegex(self.skill, r'(?is)step 8.{0,400}history\.py|history\.py.{0,400}step 8')

    def test_confidentiality_rule_is_permanent(self):
        s = self.skill.index('## Permanent rules')
        perm = self.skill[s:self.skill.index('## Setup')]
        self.assertRegex(perm, r'\*\*Project archives\.\*\*')
        self.assertRegex(perm, r'(?is)archives.{0,300}(stay|stays|remain|remains) local')
        self.assertRegex(perm, r'(?is)never.{0,200}(VP|network)')
        self.assertIn('[HISTORY-LEAK]', self.skill)

    def test_user_asked_once_and_absent_user(self):
        sec = self.section()
        self.assertRegex(sec, r'(?is)user is (absent|not there)')
        self.assertRegex(sec, r'(?is)local paths?')

    def test_commands_use_skill_dir(self):
        for m in re.findall(r'python3 -I (\S+)', self.skill):
            self.assertTrue(m.startswith(('<SKILL_DIR>/tools/', '<VP>/tools/', '"<VP>/tools/', '"<SKILL_DIR>/tools/')), m)

    def test_other_files(self):
        self.assertTrue((FRONTIER / 'schemas' / 'history.json').exists())
        json.loads((FRONTIER / 'schemas' / 'history.json').read_text(encoding='utf-8'))
        readme = (FRONTIER / 'README.md').read_text(encoding='utf-8')
        self.assertIn('history.py', readme)
        doc = (FRONTIER / 'tools' / 'check.py').read_text(encoding='utf-8')
        for code in ('[HISTORY-MISSING]', '[HISTORY-STALE]', '[HISTORY-QUERY]', '[HISTORY-OVERLAP]', '[HISTORY-CITE]',
                     '[HISTORY-LEAK]'):
            self.assertIn(code, doc, code)
        self.assertIn('history', (FRONTIER / 'tools' / 'card.py').read_text(encoding='utf-8').lower())
